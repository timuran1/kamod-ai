import os
import json
import uuid
import sqlite3
import threading
import time
import requests
import secrets
import mimetypes
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, g, Response, stream_with_context, session, redirect
from seedance_api import SeedanceAPI
from byteplus_provider import (
    BytePlusModelArk,
    BytePlusVoice,
    data_uri_from_bytes,
    data_uri_from_existing,
    extract_output_url,
)
from dotenv import load_dotenv

load_dotenv()

byteplus_modelark = BytePlusModelArk()
byteplus_voice = BytePlusVoice()

app = Flask(__name__)

# --- Session secret --------------------------------------------------------
# APP_SECRET_KEY must be set in .env for all environments.
# In development (FLASK_ENV=development) a weak fallback is allowed so the
# app still starts during local setup.  In any other environment the app
# refuses to start rather than silently using a guessable secret.
_secret = os.getenv("APP_SECRET_KEY", "")
if not _secret:
    if os.getenv("FLASK_ENV") == "development":
        import warnings
        warnings.warn(
            "APP_SECRET_KEY is not set. Using an insecure fallback "
            "because FLASK_ENV=development. Set a real key before deploying.",
            stacklevel=1,
        )
        _secret = "dev-insecure-fallback-do-not-use-in-production"
    else:
        raise RuntimeError(
            "APP_SECRET_KEY environment variable is not set. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\" "
            "and add it to your .env file."
        )
app.secret_key = _secret
del _secret  # don't leave the value sitting in module scope

# --- Authentication --------------------------------------------------------
# Default-deny: every path requires a valid session EXCEPT
# static assets and the login/logout routes themselves.

@app.before_request
def check_auth():
    path = request.path
    if path.startswith("/static/"):
        return
    if path in ("/login", "/logout"):
        return
    if not session.get("authenticated"):
        if request.is_json or path.startswith("/api/"):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(f"/login?next={path}")

@app.route("/login", methods=["GET", "POST"])
def login():
    """Single-password login. Stores auth state in a server-side session cookie."""
    error = None
    if request.method == "POST":
        key = request.form.get("key", "").strip()
        if key == os.getenv("APP_SECRET_KEY", ""):
            session["authenticated"] = True
            return redirect(request.args.get("next") or "/")
        error = "Wrong key — try again."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

DB_PATH = os.path.join(os.path.dirname(__file__), "usage.db")
api = SeedanceAPI()

LEGACY_MEDIA_BASE = "https://api.muapi.ai/api/v1"
LEGACY_CLOUD_VIDEO_BASE = "https://api.atlascloud.ai/api/v1"

# ---------------------------------------------------------------------------
# legacy cloud Cloud — Seedance 2.0 model IDs
# ---------------------------------------------------------------------------
# Quality (standard) variants
SEEDANCE_ATLAS_T2V       = "bytedance/seedance-2.0/text-to-video"
SEEDANCE_ATLAS_I2V       = "bytedance/seedance-2.0/image-to-video"
SEEDANCE_ATLAS_R2V       = "bytedance/seedance-2.0/reference-to-video"
# Fast variants
SEEDANCE_ATLAS_T2V_FAST  = "bytedance/seedance-2.0-fast/text-to-video"
SEEDANCE_ATLAS_I2V_FAST  = "bytedance/seedance-2.0-fast/image-to-video"
SEEDANCE_ATLAS_R2V_FAST  = "bytedance/seedance-2.0-fast/reference-to-video"

# Translates legacy legacy provider Kling model names → legacy cloud Cloud model IDs
KLING_MODEL_MAP = {
    "kling-v3.0-pro-text-to-video":   "kwaivgi/kling-v3.0-pro/text-to-video",
    "kling-v3.0-std-text-to-video":   "kwaivgi/kling-v3.0-std/text-to-video",
    "kling-v3.0-pro-image-to-video":  "kwaivgi/kling-v3.0-pro/image-to-video",
    "kling-v3.0-std-image-to-video":  "kwaivgi/kling-v3.0-std/image-to-video",
    "kling-v3.0-pro-motion-control":  "kwaivgi/kling-v2.6-pro/motion-control",
    "kling-v3.0-std-motion-control":  "kwaivgi/kling-v2.6-std/motion-control",
}

# UI-facing pricing config for the safe redesign shell.
# Keep this in backend config instead of baking numbers into templates so it can
# be replaced cleanly later by token / billing logic.
AI_VIDEOS_V2_CONFIG = {
    "kling": {
        "provider": "KAMOD AI Pipeline",
        "pricing_label": "KAMOD estimate",
        "source_url": "https://www.atlascloud.ai/collections/kling-v3",
        "rates": {
            "kling-v3.0-pro-text-to-video": 0.095,
            "kling-v3.0-std-text-to-video": 0.071,
            "kling-v3.0-pro-image-to-video": 0.095,
            "kling-v3.0-std-image-to-video": 0.071,
            "kling-v3.0-pro-motion-control": 0.112,
            "kling-v3.0-std-motion-control": 0.070,
        },
        "labels": {
            "kling-v3.0-pro-text-to-video": "Pro T2V",
            "kling-v3.0-std-text-to-video": "Standard T2V",
            "kling-v3.0-pro-image-to-video": "Pro I2V",
            "kling-v3.0-std-image-to-video": "Standard I2V",
            "kling-v3.0-pro-motion-control": "Pro Motion",
            "kling-v3.0-std-motion-control": "Standard Motion",
        },
        "card_copy": {
            "kling-v3.0-pro-text-to-video": "From $0.095 / sec",
            "kling-v3.0-std-text-to-video": "From $0.071 / sec",
            "kling-v3.0-pro-image-to-video": "From $0.095 / sec",
            "kling-v3.0-std-image-to-video": "From $0.071 / sec",
            "kling-v3.0-pro-motion-control": "From $0.112 / sec",
            "kling-v3.0-std-motion-control": "From $0.070 / sec",
        },
    }
}

# ---------------------------------------------------------------------------
# Safe input parsing helpers
# ---------------------------------------------------------------------------
# Using bare int() / float() on user-supplied strings raises ValueError → 500.
# These helpers return the default when the field is absent, and abort with a
# clear 400 response when the value is present but not a valid number.

from flask import abort as _abort

def _int(value, default, name="value"):
    """Parse an integer from a request field.  Returns default if missing; 400 if unparseable."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _abort(400, description=f"'{name}' must be a whole number, got: {value!r}")

def _float(value, default, name="value"):
    """Parse a float from a request field.  Returns default if missing; 400 if unparseable."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        _abort(400, description=f"'{name}' must be a number, got: {value!r}")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT UNIQUE, prompt TEXT, mode TEXT, model TEXT,
                aspect_ratio TEXT, duration INTEGER, quality TEXT,
                status TEXT DEFAULT 'processing', video_url TEXT,
                cost REAL, error TEXT, created_at TEXT
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY, name TEXT, graph TEXT,
                created_at TEXT, updated_at TEXT
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY, workflow_id TEXT,
                status TEXT DEFAULT 'running',
                node_results TEXT DEFAULT '{}',
                error TEXT, created_at TEXT, completed_at TEXT
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS gen_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page TEXT,
                model TEXT,
                prompt TEXT,
                aspect_ratio TEXT,
                duration INTEGER,
                quality TEXT,
                output_url TEXT,
                status TEXT DEFAULT 'processing',
                specs TEXT,
                created_at TEXT,
                request_id TEXT
            )""")
        # Migration: add request_id column to existing databases
        try:
            db.execute("ALTER TABLE gen_history ADD COLUMN request_id TEXT")
        except Exception:
            pass  # column already exists
        try:
            db.execute("ALTER TABLE gen_history ADD COLUMN output_text TEXT")
        except Exception:
            pass  # column already exists
        for table, column, col_type in (
            ("generations", "completed_at", "TEXT"),
            ("generations", "execution_time_ms", "REAL"),
            ("gen_history", "cost", "REAL"),
            ("gen_history", "completed_at", "TEXT"),
            ("gen_history", "execution_time_ms", "REAL"),
        ):
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except Exception:
                pass  # column already exists
        db.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                filmmaker_note TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                expires_days INTEGER DEFAULT 7,
                status TEXT DEFAULT 'active'
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_token TEXT NOT NULL,
                video_url TEXT NOT NULL,
                label TEXT,
                sort_order INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_token TEXT NOT NULL,
                selected_label TEXT,
                client_name TEXT,
                comment TEXT,
                submitted_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Add client_ip to delivery_feedback if it was created before this migration.
        # SQLite raises OperationalError if the column already exists; that is fine.
        try:
            db.execute("ALTER TABLE delivery_feedback ADD COLUMN client_ip TEXT")
        except sqlite3.OperationalError:
            pass
        db.commit()

init_db()
jobs = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def db_insert_gen(request_id, prompt, mode, model, aspect_ratio, duration, quality):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""INSERT OR IGNORE INTO generations
            (request_id,prompt,mode,model,aspect_ratio,duration,quality,status,created_at)
            VALUES(?,?,?,?,?,?,?,'processing',?)""",
            (request_id, prompt, mode, model, aspect_ratio, duration, quality,
             datetime.utcnow().isoformat()))
        db.commit()

def _extract_execution_time_ms(result):
    """Best-effort timing extraction from legacy provider-style completed payloads."""
    if not isinstance(result, dict):
        return None
    raw = result.get("executionTime")
    if raw is None:
        timings = result.get("timings") or {}
        if isinstance(timings, dict):
            raw = timings.get("inference")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _extract_cost(result):
    if not isinstance(result, dict):
        return None
    for key in ("cost", "credits_used", "price", "amount"):
        value = result.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
    return None


def db_update_gen(request_id, status, video_url=None, cost=None, error=None, execution_time_ms=None):
    completed_at = datetime.utcnow().isoformat() if status == "completed" else None
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            UPDATE generations
            SET status=?,
                video_url=COALESCE(?, video_url),
                cost=COALESCE(?, cost),
                error=?,
                completed_at=COALESCE(?, completed_at),
                execution_time_ms=COALESCE(?, execution_time_ms)
            WHERE request_id=?""",
            (status, video_url, cost, error, completed_at, execution_time_ms, request_id))
        db.commit()

def log_history(page, model, prompt, aspect_ratio=None, duration=None, quality=None, specs=None, request_id=None):
    with sqlite3.connect(DB_PATH) as db:
        cur = db.execute("""
            INSERT INTO gen_history (page, model, prompt, aspect_ratio, duration, quality, specs, status, created_at, request_id, output_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', ?, ?, NULL)""",
            (page, model, prompt, aspect_ratio, duration, quality, specs,
             datetime.utcnow().isoformat(), request_id))
        db.commit()
        return cur.lastrowid

def update_history(row_id, status, output_url=None, output_text=None, cost=None, execution_time_ms=None):
    completed_at = datetime.utcnow().isoformat() if status == "completed" else None
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            UPDATE gen_history
            SET status=?,
                output_url=COALESCE(?, output_url),
                output_text=COALESCE(?, output_text),
                cost=COALESCE(?, cost),
                completed_at=COALESCE(?, completed_at),
                execution_time_ms=COALESCE(?, execution_time_ms)
            WHERE id=?""",
            (status, output_url, output_text, cost, completed_at, execution_time_ms, row_id))
        db.commit()

def muapi_headers():
    return {"x-api-key": os.getenv("MUAPI" + "_API_KEY"), "Content-Type": "application/json"}

def atlas_headers():
    return {"Authorization": f"Bearer {os.getenv('ATLAS' + 'CLOUD_API_KEY')}", "Content-Type": "application/json"}

def atlas_generate(model, payload):
    """POST to legacy cloud Cloud video generation endpoint, return (prediction_id, raw_data) or raise."""
    payload = dict(payload)
    payload["model"] = model
    print(f"[atlas_generate] model={model!r}")
    print(f"[atlas_generate] payload={json.dumps(payload, indent=2)}")
    resp = requests.post(f"{LEGACY_CLOUD_VIDEO_BASE}/model/generateVideo", json=payload,
                         headers=atlas_headers(), timeout=60)
    print(f"[atlas_generate] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()
    data = resp.json()
    pred_id = (data.get("data") or {}).get("id") or data.get("id")
    return pred_id, data

def atlas_poll(prediction_id, timeout=780, interval=10):
    """Poll legacy cloud Cloud until completed/failed or timeout.

    legacy cloud wraps every result in {"code":200,"data":{...}}.
    Status and outputs live inside data["data"], NOT at the top level.
    Returns the inner data dict on success so callers can read outputs directly.
    """
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{LEGACY_CLOUD_VIDEO_BASE}/model/result/{prediction_id}",
                         headers=atlas_headers(), timeout=30)
        raw_text = r.text
        print(f"[atlas_poll] id={prediction_id} http={r.status_code} body={raw_text[:600]}")
        r.raise_for_status()
        raw = r.json()
        # Unwrap {"code":200,"data":{...}} envelope
        inner  = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = inner.get("status") or "processing"
        if status in ("completed", "succeeded"):
            return inner          # callers use inner["outputs"] etc.
        elif status == "failed":
            raise Exception(f"legacy cloud task failed: {inner.get('error') or raw.get('message')}")
        time.sleep(interval)
    raise TimeoutError("Timed out waiting for legacy cloud generation to complete")

def extract_url(data, *keys):
    for k in keys:
        v = data.get(k)
        if v:
            return v[0] if isinstance(v, list) else v
    return None


def _local_static_url(filename):
    return f"/static/uploads/{filename}"


def _save_upload_to_static(file_storage, prefix="upload"):
    upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    ext = os.path.splitext(file_storage.filename or "")[1] or mimetypes.guess_extension(file_storage.mimetype or "") or ".bin"
    filename = f"{prefix}_{uuid.uuid4().hex}{ext}"
    file_storage.save(os.path.join(upload_dir, filename))
    return _local_static_url(filename)


def _provider_media_url(url):
    """Return a URL/data URI that ModelArk can consume."""
    if not url:
        return url
    if url.startswith("data:") or url.startswith("http://") or url.startswith("https://") or url.startswith("asset://"):
        return url
    if url.startswith("/static/"):
        path = os.path.join(os.path.dirname(__file__), url.lstrip("/"))
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            return data_uri_from_bytes(fh.read(), mime)
    return url


def _provider_media_urls(urls):
    return [_provider_media_url(u) for u in urls if u]


def _extract_api_error_text(response):
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("error") or body.get("detail") or body.get("message")
            if isinstance(detail, dict):
                return detail.get("error") or detail.get("message") or str(detail)
            if detail:
                return str(detail)
            return json.dumps(body)
        if isinstance(body, list):
            return json.dumps(body)
    except Exception:
        pass
    return response.text.strip() or f"HTTP {response.status_code}"

def muapi_poll(request_id, timeout=600, interval=5):
    start = time.time()
    while time.time() - start < timeout:
        data = muapi_result(request_id)
        status = data.get("status")
        if status == "completed":
            return data
        elif status == "failed":
            raise Exception(f"API task failed: {data.get('error')}")
        time.sleep(interval)
    raise TimeoutError("Timed out waiting for completion")


def muapi_result(request_id):
    r = requests.get(f"{LEGACY_MEDIA_BASE}/predictions/{request_id}/result",
                     headers=muapi_headers(), timeout=30)
    if not r.ok:
        detail = _extract_api_error_text(r)
        raise Exception(f"API task failed: {detail}")
    return r.json()

# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    try:
        url = _save_upload_to_static(file, "asset")
        return jsonify({"url": url})
    except requests.HTTPError as e:
        return jsonify({"error": f"Upload failed: {e.response.text}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ugc/upload-datauri", methods=["POST"])
def ugc_upload_datauri():
    """Accept a base64 data URI, save it locally, return a static URL."""
    d = request.json or {}
    img_bytes, mime = _decode_data_uri(d.get("data_uri", ""))
    if not img_bytes:
        return jsonify({"error": "Invalid or missing data_uri"}), 400
    ext = mime.split("/")[-1] if "/" in mime else "jpg"
    label = d.get("label", "ref")
    try:
        upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"ugc_{label}_{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(upload_dir, filename), "wb") as fh:
            fh.write(img_bytes)
        url = _local_static_url(filename)
        print(f"[ugc_upload_datauri] label={label!r} mime={mime} url={url}")
        return jsonify({"url": url})
    except requests.HTTPError as e:
        return jsonify({"error": f"Upload failed: {e.response.text}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Video generator
# ---------------------------------------------------------------------------

@app.route("/")
@app.route("/film-studio")
def index():
    return render_template("film_studio_v2.html")


@app.route("/seedance-legacy")
def seedance_legacy_page():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("index.html", embed=embed, legacy=True)

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/analytics")
def analytics():
    return render_template("analytics.html")

@app.route("/api/analytics/connect", methods=["POST"])
def analytics_connect():
    """Store OAuth tokens for social platforms (placeholder — real OAuth TBD)."""
    d = request.json or {}
    platform = d.get("platform", "")
    token    = d.get("access_token", "")
    if platform not in ("instagram", "youtube", "meta"):
        return jsonify({"error": "Unknown platform"}), 400
    if not token:
        return jsonify({"error": "access_token required"}), 400
    # TODO: store securely per-user; for now store in session/env
    return jsonify({"ok": True, "platform": platform})

@app.route("/api/analytics/disconnect", methods=["POST"])
def analytics_disconnect():
    d = request.json or {}
    platform = d.get("platform", "")
    return jsonify({"ok": True, "platform": platform})

@app.route("/workflows")
def workflows_page():
    return render_template("workflow.html")

@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    prompt       = data.get("prompt", "").strip()
    mode         = data.get("mode", "text")
    aspect_ratio = data.get("aspect_ratio", "16:9")
    duration     = _int(data.get("duration"), 5, "duration")
    quality      = data.get("quality", "basic")
    # Accept either images_list (array) or legacy image_url (single string)
    images_list  = data.get("images_list") or []
    image_url    = data.get("image_url", "").strip()
    if not images_list and image_url:
        images_list = [image_url]
    images_list = [u for u in images_list if u and u.strip()]

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    print(f"[/generate] mode={mode!r} aspect_ratio={aspect_ratio!r} duration={duration} images_list_count={len(images_list)}")
    if images_list:
        for idx, url in enumerate(images_list, 1):
            print(f"[/generate]   image_{idx} = {url[:80]}...")

    if mode == "image" and not images_list:
        return jsonify({"error": "At least one image URL is required"}), 400

    try:
        rid = _byteplus_video_job(
            prompt,
            image_urls=images_list[:9] if mode == "image" else None,
            aspect_ratio=aspect_ratio,
            duration=duration,
            generate_audio=True,
            fast=str(quality).lower() in {"fast", "global-fast", "vip-fast"},
            model_label="BytePlus Seedance 2.0 I2V" if mode == "image" else "BytePlus Seedance 2.0 T2V",
            mode="image" if mode == "image" else "text",
            history_page="film-studio",
            history_quality=quality,
        )
        db_insert_gen(rid, prompt, mode, "byteplus-seedance-2.0", aspect_ratio, duration, quality)
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        if mode == "image":
            # ── Image mode: legacy provider (proven, handles multi-image & @image refs) ──
            if not images_list:
                return jsonify({"error": "At least one image URL is required"}), 400
            print(f"[/generate] → legacy provider Seedance I2V | aspect_ratio={aspect_ratio!r} | images={len(images_list)} | quality={quality!r}")
            # Normalise new tier keys to what the seedance_api expects.
            _i2v_quality_map = {
                "global-standard": "basic",
                "global-fast":     "basic",   # no separate fast I2V; fall back to basic
                "vip-standard":    "high",
                "vip-fast":        "high",    # closest I2V equivalent
            }
            i2v_quality = _i2v_quality_map.get(quality, quality)
            # HD 1080p VIP route: use sd-2-vip-image-to-video-1080p directly.
            if quality in ("hd", "1080p", "vip-hd") or i2v_quality == "vip-hd":
                payload = {
                    "prompt":       prompt,
                    "images_list":  images_list,
                    "aspect_ratio": aspect_ratio,
                    "duration":     duration,
                }
                r = requests.post(f"{LEGACY_MEDIA_BASE}/sd-2-vip-image-to-video-1080p",
                                  json=payload, headers=muapi_headers(), timeout=60)
                if not r.ok:
                    try:
                        body = r.json()
                        detail = (body.get("detail") if isinstance(body.get("detail"), str)
                                  else (body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else None)) \
                                 or body.get("error") or str(body)
                    except Exception:
                        detail = r.text
                    return jsonify({"error": detail}), r.status_code
                submission = r.json()
                model_name = "sd-2-vip-image-to-video-1080p"
            else:
                payload = {
                    "prompt": prompt,
                    "images_list": images_list[:9],
                    "aspect_ratio": aspect_ratio,
                    "duration": duration,
                    "quality": i2v_quality,
                }
                request_id = _seedance2_i2v_job_with_fallback(
                    payload,
                    mode,
                    "seedance-v2.0-i2v",
                    history_prompt=prompt,
                    history_aspect_ratio=aspect_ratio,
                    history_duration=duration,
                    history_quality=quality,
                    history_page="film-studio",
                )
                return jsonify({"request_id": request_id})

            request_id = submission.get("request_id") or submission.get("id")
            if not request_id:
                return jsonify({"error": f"Unexpected API response: {submission}"}), 500
            jobs[request_id] = {"status": "processing", "url": None, "error": None, "provider": "muapi"}
            db_insert_gen(request_id, prompt, mode, model_name, aspect_ratio, duration, quality)

            def poll_muapi(rid):
                try:
                    result    = api.wait_for_completion(rid)
                    video_url = extract_url(result, "outputs", "url", "video_url", "output", "video")
                    cost      = _extract_cost(result)
                    timing_ms = _extract_execution_time_ms(result)
                    jobs[rid].update({"status": "completed", "url": video_url,
                                      "cost": cost, "execution_time_ms": timing_ms})
                    db_update_gen(rid, "completed", video_url=video_url, cost=cost,
                                  execution_time_ms=timing_ms)
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        TimeoutError) as e:
                    err = f"[network] {e}"
                    jobs[rid].update({"status": "failed", "error": err, "recoverable": True})
                    db_update_gen(rid, "failed", error=err)
                except Exception as e:
                    jobs[rid].update({"status": "failed", "error": str(e), "recoverable": False})
                    db_update_gen(rid, "failed", error=str(e))

            threading.Thread(target=poll_muapi, args=(request_id,), daemon=True).start()

        else:
            # ── Text mode: pure legacy provider routing (all tiers) ────────────────
            # global-standard / basic  → sd-2-text-to-video
            # global-fast              → sd-2-text-to-video-fast
            # vip-standard             → sd-2-vip-text-to-video
            # vip-fast                 → sd-2-vip-text-to-video-fast
            # vip-hd / hd / 1080p      → sd-2-vip-text-to-video-1080p
            q = (quality or "").lower()
            t2v_slug = {
                "global-standard": "sd-2-text-to-video",
                "global-fast":     "sd-2-text-to-video-fast",
                "basic":           "sd-2-text-to-video",         # legacy alias
                "high":            "sd-2-text-to-video",         # legacy alias
                "vip-standard":    "sd-2-vip-text-to-video",
                "vip-fast":        "sd-2-vip-text-to-video-fast",
                "vip-hd":          "sd-2-vip-text-to-video-1080p",
                "hd":              "sd-2-vip-text-to-video-1080p",
                "1080p":           "sd-2-vip-text-to-video-1080p",
            }.get(q, "sd-2-text-to-video")  # safe default

            print(f"[/generate] → legacy provider T2V {t2v_slug!r} | ratio={aspect_ratio!r}")
            provider = "muapi"
            payload = {"prompt": prompt, "aspect_ratio": aspect_ratio, "duration": duration}
            r = requests.post(f"{LEGACY_MEDIA_BASE}/{t2v_slug}",
                              json=payload, headers=muapi_headers(), timeout=60)
            if not r.ok:
                try:
                    body = r.json()
                    detail = (body.get("detail") if isinstance(body.get("detail"), str)
                              else (body.get("detail", {}).get("error") if isinstance(body.get("detail"), dict) else None)) \
                             or body.get("error") or str(body)
                except Exception:
                    detail = r.text
                return jsonify({"error": detail}), r.status_code
            submission = r.json()
            rid = submission.get("request_id") or (submission.get("output") or {}).get("id")
            if not rid:
                return jsonify({"error": f"Unexpected API response: {submission}"}), 500

            request_id = rid
            model_name = t2v_slug
            jobs[request_id] = {"status": "processing", "url": None, "error": None, "provider": "muapi"}
            db_insert_gen(request_id, prompt, mode, model_name, aspect_ratio, duration, quality)

            def poll_t2v(rid):
                try:
                    result    = api.wait_for_completion(rid)
                    video_url = extract_url(result, "outputs", "url", "video_url", "output", "video")
                    cost      = _extract_cost(result)
                    timing_ms = _extract_execution_time_ms(result)
                    jobs[rid].update({"status": "completed", "url": video_url,
                                      "cost": cost, "execution_time_ms": timing_ms})
                    db_update_gen(rid, "completed", video_url=video_url, cost=cost,
                                  execution_time_ms=timing_ms)
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        TimeoutError) as e:
                    err = f"[network] {e}"
                    jobs[rid].update({"status": "failed", "error": err, "recoverable": True})
                    db_update_gen(rid, "failed", error=err)
                except Exception as e:
                    jobs[rid].update({"status": "failed", "error": str(e), "recoverable": False})
                    db_update_gen(rid, "failed", error=str(e))

            threading.Thread(target=poll_t2v, args=(request_id,), daemon=True).start()

        return jsonify({"request_id": request_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status/<request_id>")
def status(request_id):
    # Primary: in-memory job tracker (covers all active/recent jobs)
    job = jobs.get(request_id)
    if job:
        return jsonify(job)
    try:
        result = byteplus_modelark.get_task(request_id)
        if result.get("status") != "processing" or result.get("url"):
            return jsonify(result)
    except Exception:
        pass
    # Fallback for post-restart recovery: try legacy cloud first (new primary), then legacy provider (legacy)
    try:
        r = requests.get(f"{LEGACY_CLOUD_VIDEO_BASE}/model/result/{request_id}",
                         headers=atlas_headers(), timeout=30)
        if r.ok:
            raw   = r.json()
            inner = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            s     = inner.get("status") or "processing"
            if s in ("succeeded", "success"):
                s = "completed"
            url   = _atlas_extract_url(inner) if s == "completed" else None
            # Only return if legacy cloud has meaningful info (not a 404-style empty response)
            if s != "processing" or url:
                return jsonify({"status": s, "url": url, "error": inner.get("error"),
                                "provider": "atlas"})
    except Exception:
        pass
    try:
        return jsonify(api.get_result(request_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/recheck/<request_id>")
def recheck_job(request_id):
    """Re-spawn the polling thread for a job that failed due to network errors."""
    job = jobs.get(request_id)
    if job and job.get("status") == "processing":
        return jsonify({"status": "processing", "message": "Already polling"})

    # Determine which provider originally handled this job.
    # Kling jobs store "atlas"; Seedance T2V/I2V/Omni jobs store "muapi".
    provider = (job or {}).get("provider", "muapi")
    jobs[request_id] = {"status": "processing", "url": None, "error": None, "provider": provider}
    db_update_gen(request_id, "processing", error=None)

    def poll(rid, prov):
        try:
            if prov == "byteplus-modelark":
                result = byteplus_modelark.wait_for_task(rid)
                url = result.get("url")
                jobs[rid].update({"status": "completed", "url": url})
                db_update_gen(rid, "completed", video_url=url)
            elif prov == "atlas":
                inner     = atlas_poll(rid)
                video_url = _atlas_extract_url(inner)
                jobs[rid].update({"status": "completed", "url": video_url})
                db_update_gen(rid, "completed", video_url=video_url)
            else:
                result    = api.wait_for_completion(rid)
                video_url = extract_url(result, "outputs", "url", "video_url", "output", "video")
                cost      = _extract_cost(result)
                timing_ms = _extract_execution_time_ms(result)
                jobs[rid].update({"status": "completed", "url": video_url,
                                  "cost": cost, "execution_time_ms": timing_ms})
                db_update_gen(rid, "completed", video_url=video_url, cost=cost,
                              execution_time_ms=timing_ms)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                TimeoutError) as e:
            err = f"[network] {e}"
            jobs[rid].update({"status": "failed", "error": err, "recoverable": True})
            db_update_gen(rid, "failed", error=err)
        except Exception as e:
            jobs[rid].update({"status": "failed", "error": str(e), "recoverable": False})
            db_update_gen(rid, "failed", error=str(e))

    threading.Thread(target=poll, args=(request_id, provider), daemon=True).start()
    return jsonify({"status": "processing", "message": "Recheck started"})

@app.route("/download/<request_id>")
def download(request_id):
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT video_url, id FROM generations WHERE request_id=?", (request_id,)
        ).fetchone()
    if not row or not row[0]:
        return jsonify({"error": "Video not found"}), 404
    video_url, gen_id = row[0], row[1]
    filename = f"Kamod{gen_id}.mp4"
    r = requests.get(video_url, stream=True, timeout=60)
    r.raise_for_status()
    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            yield chunk
    return Response(
        stream_with_context(generate()),
        content_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# /download-url was removed — it was an open SSRF proxy.
# ai_director.html now links directly to the image URL for saving.


def _safe_download_filename(name, fallback="kamod-download"):
    raw = os.path.basename(str(name or "").strip()) or fallback
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in raw)
    return safe[:120] or fallback


@app.route("/api/download-media")
def download_media():
    """Restricted media download helper for trusted CDN/static assets only."""
    url = (request.args.get("url") or "").strip()
    filename = _safe_download_filename(request.args.get("filename"), "kamod-media")
    if not url:
        return jsonify({"error": "url is required"}), 400

    if url.startswith("/static/"):
        rel_path = url[len("/static/"):].lstrip("/")
        static_root = os.path.realpath(app.static_folder)
        local_path = os.path.realpath(os.path.join(static_root, rel_path))
        if not local_path.startswith(static_root + os.sep) or not os.path.isfile(local_path):
            return jsonify({"error": "File not found"}), 404
        mime = mimetypes.guess_type(local_path)[0] or "application/octet-stream"

        def local_stream():
            with open(local_path, "rb") as fh:
                while True:
                    chunk = fh.read(8192)
                    if not chunk:
                        break
                    yield chunk

        return Response(stream_with_context(local_stream()), content_type=mime,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"cdn.muapi.ai"}:
        return jsonify({"error": "Unsupported download host"}), 400

    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    mime = r.headers.get("Content-Type") or mimetypes.guess_type(parsed.path)[0] or "application/octet-stream"

    def remote_stream():
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    return Response(stream_with_context(remote_stream()), content_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------

@app.route("/api/balance")
def api_balance():
    try:
        r = requests.get(f"{LEGACY_MEDIA_BASE}/account/balance", headers=muapi_headers(), timeout=10)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stats")
def api_stats():
    db = get_db()
    total_requests = db.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
    total_cost     = db.execute("SELECT COALESCE(SUM(cost),0) FROM generations").fetchone()[0]
    completed      = db.execute("SELECT COUNT(*) FROM generations WHERE status='completed'").fetchone()[0]
    failed         = db.execute("SELECT COUNT(*) FROM generations WHERE status='failed'").fetchone()[0]
    processing     = db.execute("SELECT COUNT(*) FROM generations WHERE status='processing'").fetchone()[0]
    avg_cost       = (total_cost / completed) if completed else 0
    by_model = db.execute("""SELECT model,COUNT(*) as requests,COALESCE(SUM(cost),0) as total_cost
        FROM generations GROUP BY model ORDER BY requests DESC""").fetchall()
    history = db.execute("""SELECT request_id,prompt,mode,model,quality,duration,aspect_ratio,
        status,video_url,cost,error,created_at,completed_at,execution_time_ms FROM generations
        ORDER BY created_at DESC LIMIT 50""").fetchall()
    return jsonify({
        "total_requests": total_requests, "total_cost": round(total_cost, 4),
        "avg_cost": round(avg_cost, 4), "completed": completed,
        "failed": failed, "processing": processing,
        "by_model": [dict(r) for r in by_model],
        "history":  [dict(r) for r in history],
    })

# ---------------------------------------------------------------------------
# Generation History API
# ---------------------------------------------------------------------------

@app.route("/api/history/<page>")
def api_history(page):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT id, model, prompt, output_url, output_text, status, aspect_ratio, duration, quality,
                   specs, created_at, request_id, cost, completed_at, execution_time_ms
            FROM gen_history WHERE page=? ORDER BY created_at DESC LIMIT 30""", (page,)).fetchall()
    return jsonify({"history": [dict(r) for r in rows]})

# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------

@app.route("/api/workflows", methods=["GET"])
def list_workflows():
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id,name,created_at,updated_at FROM workflows ORDER BY updated_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/workflows", methods=["POST"])
def save_workflow():
    data    = request.json
    wf_id   = data.get("id") or str(uuid.uuid4())
    name    = data.get("name", "Untitled Workflow")
    graph   = json.dumps(data.get("graph", {}))
    now     = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""INSERT INTO workflows(id,name,graph,created_at,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,graph=excluded.graph,updated_at=excluded.updated_at""",
            (wf_id, name, graph, now, now))
        db.commit()
    return jsonify({"id": wf_id, "name": name})

@app.route("/api/workflows/<wf_id>", methods=["GET"])
def get_workflow(wf_id):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    result = dict(row)
    result["graph"] = json.loads(result["graph"] or "{}")
    return jsonify(result)

@app.route("/api/workflows/<wf_id>", methods=["DELETE"])
def delete_workflow(wf_id):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("DELETE FROM workflows WHERE id=?", (wf_id,))
        db.commit()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Workflow execution
# ---------------------------------------------------------------------------

@app.route("/api/workflows/<wf_id>/run", methods=["POST"])
def run_workflow(wf_id):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if not row:
        return jsonify({"error": "Workflow not found"}), 404

    graph  = json.loads(row["graph"] or "{}")
    run_id = str(uuid.uuid4())
    now    = datetime.utcnow().isoformat()

    with sqlite3.connect(DB_PATH) as db:
        db.execute("""INSERT INTO workflow_runs(id,workflow_id,status,node_results,created_at)
            VALUES(?,?,'running','{}',?)""", (run_id, wf_id, now))
        db.commit()

    def run():
        try:
            _execute_workflow(graph, run_id)
        except Exception as e:
            with sqlite3.connect(DB_PATH) as db:
                db.execute("UPDATE workflow_runs SET status='failed',error=?,completed_at=? WHERE id=?",
                           (str(e), datetime.utcnow().isoformat(), run_id))
                db.commit()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"run_id": run_id})

@app.route("/api/runs/<run_id>", methods=["GET"])
def get_run(run_id):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    result = dict(row)
    result["node_results"] = json.loads(result["node_results"] or "{}")
    return jsonify(result)

def _topo_sort(nodes, edges):
    adj    = {n["id"]: [] for n in nodes}
    in_deg = {n["id"]: 0  for n in nodes}
    for e in edges:
        src, tgt = e["sourceNode"], e["targetNode"]
        if src in adj and tgt in in_deg:
            adj[src].append(tgt)
            in_deg[tgt] += 1
    queue  = [n for n in in_deg if in_deg[n] == 0]
    order  = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for nb in adj.get(n, []):
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                queue.append(nb)
    return order

def _execute_workflow(graph, run_id):
    nodes        = {n["id"]: n for n in graph.get("nodes", [])}
    edges        = graph.get("edges", [])
    order        = _topo_sort(list(nodes.values()), edges)
    outputs      = {}   # nodeId -> { portId: value }
    node_results = {}

    def save_results():
        with sqlite3.connect(DB_PATH) as db:
            db.execute("UPDATE workflow_runs SET node_results=? WHERE id=?",
                       (json.dumps(node_results), run_id))
            db.commit()

    for node_id in order:
        node      = nodes[node_id]
        node_type = node["type"]
        params    = node.get("params", {})

        # Resolve inputs from connected upstream outputs
        resolved = {}
        for e in edges:
            if e["targetNode"] == node_id:
                val = (outputs.get(e["sourceNode"]) or {}).get(e["sourcePort"])
                if val is not None:
                    resolved[e["targetPort"]] = val

        node_results[node_id] = {"status": "running"}
        save_results()

        try:
            result = _exec_node(node_type, params, resolved)
            outputs[node_id]      = result
            node_results[node_id] = {"status": "done", "outputs": result}
        except Exception as e:
            node_results[node_id] = {"status": "error", "error": str(e)}
            save_results()
            raise Exception(f"Node '{node_id}' ({node_type}) failed: {e}")

        save_results()

    with sqlite3.connect(DB_PATH) as db:
        db.execute("UPDATE workflow_runs SET status='completed',completed_at=? WHERE id=?",
                   (datetime.utcnow().isoformat(), run_id))
        db.commit()

def _exec_node(node_type, params, inputs):
    h = muapi_headers()

    def post_and_poll(endpoint, payload):
        r = requests.post(f"{LEGACY_MEDIA_BASE}/{endpoint}", json=payload, headers=h, timeout=60)
        r.raise_for_status()
        data = r.json()
        rid  = data.get("request_id")
        if rid:
            result = muapi_poll(rid)
            return result
        return data

    # ── Text ──────────────────────────────────────────────
    if node_type == "text-prompt":
        return {"text": params.get("value", "")}

    # ── Utility ───────────────────────────────────────────
    if node_type == "util-passthrough":
        return {"output": next(iter(inputs.values()), "")}

    if node_type == "util-concatenator":
        sep = params.get("separator", " ")
        return {"text": sep.join([str(inputs.get("a", "")), str(inputs.get("b", ""))])}

    if node_type == "output-viewer":
        return {"data": next(iter(inputs.values()), "")}

    # ── Image ─────────────────────────────────────────────
    if node_type == "image-generate":
        model  = params.get("model", "wan2.1-text-to-image")
        result = post_and_poll(model, {
            "prompt":       inputs.get("text", ""),
            "aspect_ratio": params.get("aspect_ratio", "16:9"),
        })
        url = extract_url(result, "url", "image", "image_url", "output")
        return {"image": url}

    if node_type == "image-upscale":
        result = post_and_poll("ai-image-upscaler", {"image_url": inputs.get("image", "")})
        url = extract_url(result, "url", "image", "image_url", "output")
        return {"image": url}

    if node_type == "background-remove":
        result = post_and_poll("ai-background-remover", {"image_url": inputs.get("image", "")})
        url = extract_url(result, "url", "image", "image_url", "output")
        return {"image": url}

    # ── Video ─────────────────────────────────────────────
    if node_type == "video-t2v":
        sub    = api.text_to_video(
            prompt=inputs.get("text", ""),
            aspect_ratio=params.get("aspect_ratio", "16:9"),
            duration=_int(params.get("duration"), 5, "duration"),
            quality=params.get("quality", "basic"))
        result = api.wait_for_completion(sub["request_id"])
        url    = extract_url(result, "url", "video_url", "output", "video")
        return {"video": url}

    if node_type == "video-i2v":
        sub    = api.image_to_video(
            prompt=inputs.get("text", ""),
            images_list=[inputs.get("image", "")],
            aspect_ratio=params.get("aspect_ratio", "16:9"),
            duration=_int(params.get("duration"), 5, "duration"),
            quality=params.get("quality", "basic"))
        result = api.wait_for_completion(sub["request_id"])
        url    = extract_url(result, "url", "video_url", "output", "video")
        return {"video": url}

    if node_type == "video-extend":
        sub    = api.extend_video(
            request_id=inputs.get("video", ""),
            prompt=inputs.get("text", ""),
            duration=_int(params.get("duration"), 5, "duration"),
            quality=params.get("quality", "basic"))
        result = api.wait_for_completion(sub["request_id"])
        url    = extract_url(result, "url", "video_url", "output", "video")
        return {"video": url}

    # ── Audio ─────────────────────────────────────────────
    if node_type == "audio-music":
        result = post_and_poll("suno-create-music", {
            "prompt":   inputs.get("text", ""),
            "duration": _int(params.get("duration"), 30, "duration"),
        })
        url = extract_url(result, "url", "audio", "audio_url", "output")
        return {"audio": url}

    return {}

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# AI Video Effects
# ---------------------------------------------------------------------------

@app.route("/effects")
def effects_page():
    return render_template("effects.html")


@app.route("/api/effects", methods=["POST"])
def apply_effect():
    data        = request.json
    prompt      = data.get("prompt", "").strip()
    image_url   = data.get("image_url", "").strip()
    name        = data.get("name", "").strip()
    aspect_ratio= data.get("aspect_ratio", "16:9")
    resolution  = data.get("resolution", "480p")
    quality     = data.get("quality", "medium")
    duration    = _int(data.get("duration"), 5, "duration")

    if not image_url:
        return jsonify({"error": "Image URL is required"}), 400
    if not name:
        return jsonify({"error": "Effect name is required"}), 400

    try:
        resp = requests.post(
            f"{LEGACY_MEDIA_BASE}/generate_wan_ai_effects",
            json={"prompt": prompt, "image_url": image_url, "name": name,
                  "aspect_ratio": aspect_ratio, "resolution": resolution,
                  "quality": quality, "duration": duration},
            headers=muapi_headers(),
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()
        request_id = result.get("data", {}).get("request_id")
        if not request_id:
            return jsonify({"error": f"No request_id in response: {result}"}), 500
        return jsonify({"request_id": request_id})
    except requests.HTTPError as e:
        return jsonify({"error": f"API error: {e.response.text}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/effects/status/<request_id>")
def effects_status(request_id):
    try:
        resp = requests.get(
            f"{LEGACY_MEDIA_BASE}/predictions/{request_id}/result",
            headers=muapi_headers(), timeout=30
        )
        resp.raise_for_status()
        result = resp.json()
        status    = result.get("data", {}).get("status") or result.get("status")
        video_url = (result.get("video", {}) or {}).get("url") or extract_url(result, "url", "video_url")
        return jsonify({"status": status, "url": video_url, "raw": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Music & Speech
# ---------------------------------------------------------------------------

@app.route("/audio")
def audio_page():
    return render_template("audio_v2.html")


@app.route("/audio-legacy")
def audio_legacy_page():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("audio.html", embed=embed, legacy=True)


def _audio_post(endpoint, payload):
    """POST to a muapi endpoint, return (request_id, raw_data) or raise."""
    resp = requests.post(f"{LEGACY_MEDIA_BASE}/{endpoint}", json=payload,
                         headers=muapi_headers(), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # request_id may be at top level or nested under "data"
    rid = data.get("request_id") or (data.get("data") or {}).get("request_id")
    return rid, data

# Maps request_id -> gen_history row id for audio jobs
audio_jobs = {}

@app.route("/audio-download/<request_id>")
def audio_download(request_id):
    """Proxy-stream audio/video without exposing legacy provider URL."""
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT output_url, model, id FROM gen_history WHERE specs=? AND output_url IS NOT NULL",
            (request_id,)).fetchone()
    if not row or not row[0]:
        return jsonify({"error": "Not found or still processing"}), 404
    media_url = row[0]
    model     = row[1] or "audio"
    row_id    = row[2]
    # Determine filename and content type
    ext = "mp3"
    ctype = "audio/mpeg"
    if any(k in model for k in ("lipsync", "mmaudio-video", "voice-clone")):
        ext   = "mp4"
        ctype = "video/mp4"
    filename = f"Kamod-Audio-{row_id}.{ext}"
    r = requests.get(media_url, stream=True, timeout=60)
    r.raise_for_status()
    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            yield chunk
    return Response(
        stream_with_context(generate()),
        content_type=ctype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.route("/api/audio/status/<request_id>")
def audio_status(request_id):
    try:
        resp = requests.get(f"{LEGACY_MEDIA_BASE}/predictions/{request_id}/result",
                            headers=muapi_headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        # normalise status & url across response shapes
        status = (result.get("data") or {}).get("status") or result.get("status")
        # Try common URL locations, including MMAudio's outputs array
        outputs = result.get("outputs") or []
        outputs_url = outputs[0] if isinstance(outputs, list) and outputs else None
        url = (extract_url(result, "url", "audio_url", "audio", "video_url") or
               outputs_url or
               (result.get("video") or {}).get("url") or
               (result.get("audio") or {}).get("url") or
               (result.get("data") or {}).get("url") or
               (result.get("data") or {}).get("audio_url"))
        # Persist to history on completion
        if status == "completed" and url:
            hist_id = audio_jobs.get(request_id)
            if hist_id:
                update_history(hist_id, "completed", output_url=url)
        elif status == "failed":
            hist_id = audio_jobs.get(request_id)
            if hist_id:
                update_history(hist_id, "failed")
        return jsonify({"status": status, "url": url, "raw": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Suno Music ────────────────────────────────────────────────

@app.route("/api/audio/suno-create", methods=["POST"])
def suno_create():
    d = request.json
    prompt = d.get("prompt", "")
    dur    = _int(d.get("duration"), 30, "duration")
    try:
        payload = {"prompt": prompt, "style": d.get("style", ""), "duration": dur}
        rid, _ = _audio_post("suno-create-music", payload)
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hid = log_history("audio", "suno-create-music", prompt, duration=dur, specs=rid)
        audio_jobs[rid] = hid
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/audio/suno-remix", methods=["POST"])
def suno_remix():
    d = request.json
    prompt = d.get("prompt", "")
    try:
        rid, _ = _audio_post("suno-remix-music", {
            "audio_url": d.get("audio_url", ""), "prompt": prompt,
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hid = log_history("audio", "suno-remix-music", prompt, specs=rid)
        audio_jobs[rid] = hid
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/audio/suno-extend", methods=["POST"])
def suno_extend():
    d = request.json
    prompt = d.get("prompt", "")
    dur    = _int(d.get("duration"), 30, "duration")
    try:
        rid, _ = _audio_post("suno-extend-music", {
            "audio_url": d.get("audio_url", ""), "prompt": prompt, "duration": dur,
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hid = log_history("audio", "suno-extend-music", prompt, duration=dur, specs=rid)
        audio_jobs[rid] = hid
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Lip-Sync ──────────────────────────────────────────────────

LIPSYNC_MODELS = {
    "sync-lipsync":    "sync-lipsync",
    "latentsync":      "latentsync-video",
    "creatify-lipsync":"creatify-lipsync",
    "veed-lipsync":    "veed-lipsync",
}

@app.route("/api/audio/lipsync", methods=["POST"])
def lipsync():
    d     = request.json
    model = d.get("model", "sync-lipsync")
    endpoint = LIPSYNC_MODELS.get(model, "sync-lipsync")
    try:
        rid, _ = _audio_post(endpoint, {
            "video_url": d.get("video_url", ""),
            "audio_url": d.get("audio_url", ""),
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hid = log_history("audio", endpoint, d.get("video_url", ""), specs=rid)
        audio_jobs[rid] = hid
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── MMAudio ───────────────────────────────────────────────────

@app.route("/api/audio/mmaudio-text", methods=["POST"])
def mmaudio_text():
    d = request.json
    try:
        rid, _ = _audio_post("mmaudio-v2/text-to-audio", {
            "prompt":   d.get("prompt", ""),
            "duration": _int(d.get("duration"), 10, "duration"),
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hid = log_history("audio", "mmaudio-v2/text-to-audio", d.get("prompt", ""),
                          duration=_int(d.get("duration"), 10, "duration"), specs=rid)
        audio_jobs[rid] = hid
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/audio/mmaudio-video", methods=["POST"])
def mmaudio_video():
    d = request.json
    try:
        rid, _ = _audio_post("mmaudio-v2/video-to-video", {
            "video_url": d.get("video_url", ""),
            "prompt":    d.get("prompt", ""),
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hid = log_history("audio", "mmaudio-v2/video-to-video",
                          d.get("prompt", "") or d.get("video_url", ""), specs=rid)
        audio_jobs[rid] = hid
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Voice Clone (BytePlus MegaTTS) ───────────────────────────

# status code → human-readable label
_CLONE_STATUS = {0: "not_found", 1: "training", 2: "success", 3: "failed", 4: "active"}


@app.route("/api/audio/voice-clone", methods=["POST"])
def voice_clone():
    d = request.json or {}
    audio_url  = d.get("audio_url", "").strip()
    speaker_id = d.get("speaker_id", "").strip()
    model_type = int(d.get("model_type", 0))
    need_noise = bool(d.get("need_noise_reduction", False))
    need_norm  = bool(d.get("need_volume_normalization", False))

    if not audio_url:
        return jsonify({"error": "Reference audio URL is required"}), 400
    if not speaker_id:
        return jsonify({"error": "Speaker ID is required"}), 400
    if len(speaker_id) < 4:
        return jsonify({"error": "Speaker ID must be at least 4 characters"}), 400

    try:
        result = byteplus_voice.upload_voice(
            _provider_media_url(audio_url),
            speaker_id,
            model_type=model_type,
            need_noise_reduction=need_noise,
            need_volume_normalization=need_norm,
        )
        base_resp = result.get("BaseResp") or {}
        code = base_resp.get("StatusCode", 0)
        msg  = base_resp.get("StatusMessage", "")
        if code != 0:
            return jsonify({"error": f"Upload failed [{code}]: {msg}"}), 500
        return jsonify({"speaker_id": speaker_id, "ok": True})
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/audio/voice-clone/status/<speaker_id>")
def voice_clone_status(speaker_id):
    try:
        result = byteplus_voice.get_clone_status(speaker_id)
        code   = result.get("status", 0)
        label  = _CLONE_STATUS.get(code, "unknown")
        return jsonify({
            "speaker_id":  result.get("speaker_id", speaker_id),
            "status":      label,
            "status_code": code,
            "demo_audio":  result.get("demo_audio"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/audio/voice-clone/synthesize", methods=["POST"])
def voice_clone_synthesize():
    d = request.json or {}
    speaker_id = d.get("speaker_id", "").strip()
    text       = d.get("text", "").strip()

    if not speaker_id:
        return jsonify({"error": "speaker_id is required"}), 400
    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        audio_bytes = byteplus_voice.synthesize_with_clone(text, speaker_id)
        os.makedirs(_VO_DIR, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.wav"
        with open(os.path.join(_VO_DIR, filename), "wb") as fh:
            fh.write(audio_bytes)
        url = f"/static/voiceover/{filename}"
        hid = log_history("audio", "byteplus-voice-clone", text, specs=speaker_id)
        update_history(hid, "completed", output_url=url)
        return jsonify({"url": url})
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# AI Avatars & Motion Control
# ---------------------------------------------------------------------------

@app.route("/avatars")
def avatars_page():
    return render_template("avatars_v2.html")


@app.route("/avatars-legacy")
def avatars_legacy_page():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("avatars.html", embed=embed, legacy=True)


def _avatar_poll_url(result):
    """Extract video URL from avatar/motion-control response."""
    outputs = result.get("outputs") or []
    if outputs:
        return outputs[0]
    return extract_url(result, "url", "video_url", "video",
                       "output") or (result.get("video") or {}).get("url")


@app.route("/api/avatars/status/<request_id>")
def avatar_status(request_id):
    try:
        resp = requests.get(f"{LEGACY_MEDIA_BASE}/predictions/{request_id}/result",
                            headers=muapi_headers(), timeout=30)
        resp.raise_for_status()
        result = resp.json()
        status = ((result.get("data") or {}).get("status") or result.get("status"))
        url    = _avatar_poll_url(result)
        return jsonify({"status": status, "url": url, "raw": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Talking Avatar models (image + audio → video) ────────────

AVATAR_MODELS = {
    "kling-v2-avatar-pro":      "kling-v2-avatar-pro",
    "kling-v2-avatar-standard": "kling-v2-avatar-standard",
    "wan2.2-speech-to-video":   "wan2.2-speech-to-video",
}

@app.route("/api/avatars/generate", methods=["POST"])
def avatar_generate():
    d         = request.json
    model     = d.get("model", "kling-v2-avatar-pro")
    image_url = d.get("image_url", "").strip()
    audio_url = d.get("audio_url", "").strip()

    if not image_url:
        return jsonify({"error": "Reference image URL is required"}), 400
    if not audio_url:
        return jsonify({"error": "Audio dialogue URL is required"}), 400
    if model not in AVATAR_MODELS:
        return jsonify({"error": f"Unknown model: {model}"}), 400

    try:
        rid, _ = _audio_post(AVATAR_MODELS[model], {
            "image_url": image_url,
            "audio_url": audio_url,
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Motion Control ───────────────────────────────────────────

MOTION_MODELS = {
    "kling-v2.6-pro-motion-control": "kling-v2.6-pro-motion-control",
    "kling-v2.6-std-motion-control": "kling-v2.6-std-motion-control",
}

@app.route("/api/avatars/motion-control", methods=["POST"])
def motion_control():
    d         = request.json
    model     = d.get("model", "kling-v2.6-pro-motion-control")
    prompt    = d.get("prompt", "")
    image_url = d.get("image_url", "").strip()
    video_url = d.get("video_url", "").strip()

    if not image_url:
        return jsonify({"error": "Input image URL is required"}), 400
    if not video_url:
        return jsonify({"error": "Input video URL is required"}), 400

    endpoint = MOTION_MODELS.get(model, "kling-v2.6-pro-motion-control")
    try:
        rid, _ = _audio_post(endpoint, {
            "prompt":    prompt,
            "image_url": image_url,
            "video_url": video_url,
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Video Edit
# ---------------------------------------------------------------------------

@app.route("/api/video-edit", methods=["POST"])
def video_edit():
    d = request.json or {}
    prompt       = d.get("prompt", "").strip()
    video_url    = d.get("video_url", "").strip()
    images_list  = d.get("images_list", [])
    aspect_ratio = d.get("aspect_ratio", "16:9")
    quality      = d.get("quality", "basic")
    remove_wm    = d.get("remove_watermark", False)
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if not video_url:
        return jsonify({"error": "Video URL is required"}), 400
    payload = {
        "prompt": prompt,
        "video_urls": [video_url],
        "images_list": images_list,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "remove_watermark": remove_wm,
    }
    try:
        r = requests.post(f"{LEGACY_MEDIA_BASE}/seedance-v2.0-video-edit",
                          json=payload, headers=muapi_headers(), timeout=60)
        if not r.ok:
            try: detail = r.json()
            except: detail = r.text
            return jsonify({"error": str(detail)}), r.status_code
        data = r.json()
        rid = data.get("request_id")
        if not rid:
            return jsonify({"error": f"Unexpected response: {data}"}), 500
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        db_insert_gen(rid, prompt, "video-edit", "seedance-v2.0-video-edit", aspect_ratio, None, quality)

        def poll(request_id):
            try:
                result = muapi_poll(request_id)
                video_out = extract_url(result, "outputs", "url", "video_url", "output", "video")
                cost = _extract_cost(result)
                timing_ms = _extract_execution_time_ms(result)
                jobs[request_id].update({"status": "completed", "url": video_out,
                                         "cost": cost, "execution_time_ms": timing_ms})
                db_update_gen(request_id, "completed", video_url=video_out, cost=cost,
                              execution_time_ms=timing_ms)
            except Exception as e:
                jobs[request_id].update({"status": "failed", "error": str(e)})
                db_update_gen(request_id, "failed", error=str(e))

        threading.Thread(target=poll, args=(rid,), daemon=True).start()
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Seedance 2.0 Omni Reference
# ---------------------------------------------------------------------------

def _omni_poll(poll_url, timeout=600, interval=5):
    """Poll a URL (supports both standard predictions path and custom URLs)."""
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(poll_url, headers=muapi_headers(), timeout=30)
        if not r.ok:
            raise requests.HTTPError(
                f"{r.status_code} {r.reason} — {r.text[:300]}",
                response=r)
        data = r.json()
        # Handle nested status: top-level or inside data/output
        status = (data.get("data") or {}).get("status") or \
                 (data.get("output") or {}).get("status") or \
                 data.get("status")
        if status == "completed":
            # Merge output into top-level for extract_url compatibility
            if isinstance(data.get("output"), dict):
                merged = {**data, **data["output"]}
                merged["outputs"] = data["output"].get("outputs") or []
                return merged
            return data
        elif status == "failed":
            err = (data.get("output") or {}).get("error") or data.get("error") or "Task failed"
            raise Exception(f"Omni task failed: {err}")
        time.sleep(interval)
    raise TimeoutError("Timed out waiting for Omni completion")


@app.route("/api/omni-reference", methods=["POST"])
def omni_reference():
    d = request.json or {}
    prompt      = d.get("prompt", "").strip()
    images_list = d.get("images_list", [])
    video_files = d.get("video_files", [])
    audio_files = d.get("audio_files", [])
    aspect_ratio = d.get("aspect_ratio", "16:9")
    duration    = _int(d.get("duration"), 5, "duration")
    quality     = (d.get("quality") or "standard").lower()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if duration < 4 or duration > 15:
        return jsonify({"error": "Duration must be between 4 and 15 seconds"}), 400
    # Route to the correct VIP Omni endpoint based on quality tier.
    _omni_map = {
        "vip-hd":       "sd-2-vip-omni-reference-1080p",
        "hd":           "sd-2-vip-omni-reference-1080p",
        "1080p":        "sd-2-vip-omni-reference-1080p",
        "vip-fast":     "sd-2-vip-omni-reference-fast",
        "fast":         "sd-2-vip-omni-reference-fast",
        "vip-standard": "sd-2-vip-omni-reference",
        "standard":     "sd-2-vip-omni-reference",
    }
    omni_slug = _omni_map.get((quality or "").lower(), "sd-2-vip-omni-reference")
    payload = {"prompt": prompt, "aspect_ratio": aspect_ratio, "duration": duration}
    if images_list:
        payload["images_list"] = images_list[:9]
    if video_files:
        payload["video_files"] = video_files[:3]
    if audio_files:
        payload["audio_files"] = audio_files[:3]
    try:
        r = requests.post(f"{LEGACY_MEDIA_BASE}/{omni_slug}",
                          json=payload, headers=muapi_headers(), timeout=60)
        if not r.ok:
            try:
                body = r.json()
                if isinstance(body.get("detail"), dict):
                    detail = body["detail"].get("error") or str(body["detail"])
                elif body.get("error"):
                    detail = body["error"]
                else:
                    detail = str(body)
            except Exception:
                detail = r.text
            return jsonify({"error": detail}), r.status_code
        data = r.json()
        app.logger.info("Omni submission response: %s", json.dumps(data)[:500])
        # request_id may be top-level or nested inside output.id
        rid = data.get("request_id") or (data.get("output") or {}).get("id")
        if not rid:
            return jsonify({"error": f"Unexpected response: {data}"}), 500
        # Prefer the explicit polling URL returned by the API, fall back to standard path
        poll_url = (data.get("output") or {}).get("urls", {}).get("get") or \
                   f"{LEGACY_MEDIA_BASE}/predictions/{rid}/result"
        app.logger.info("Omni polling URL: %s", poll_url)
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        db_insert_gen(rid, prompt, "omni", omni_slug, aspect_ratio, duration, quality)

        def poll(request_id, p_url):
            try:
                result = _omni_poll(p_url)
                video_out = extract_url(result, "outputs", "url", "video_url", "output", "video")
                cost = _extract_cost(result)
                timing_ms = _extract_execution_time_ms(result)
                jobs[request_id].update({"status": "completed", "url": video_out,
                                         "cost": cost, "execution_time_ms": timing_ms})
                db_update_gen(request_id, "completed", video_url=video_out, cost=cost,
                              execution_time_ms=timing_ms)
            except Exception as e:
                jobs[request_id].update({"status": "failed", "error": str(e)})
                db_update_gen(request_id, "failed", error=str(e))

        threading.Thread(target=poll, args=(rid, poll_url), daemon=True).start()
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Seedance 2 Omni Character Training
# ---------------------------------------------------------------------------

@app.route("/api/omni-character/train", methods=["POST"])
def omni_character_train():
    """Train a reusable character from a reference portrait photo."""
    d              = request.json or {}
    image_url      = d.get("image_url", "").strip()
    character_name = d.get("character_name", "").strip()
    description    = d.get("description", "").strip()

    if not image_url:
        return jsonify({"error": "image_url is required"}), 400
    if not character_name:
        return jsonify({"error": "character_name is required"}), 400

    payload = {"image_url": image_url, "character_name": character_name}
    if description:
        payload["description"] = description

    try:
        r = requests.post(f"{LEGACY_MEDIA_BASE}/seedance-2-omni-reference-train",
                          json=payload, headers=muapi_headers(), timeout=60)
        if not r.ok:
            try:
                body   = r.json()
                detail = body.get("error") or body.get("detail") or str(body)
            except Exception:
                detail = r.text
            return jsonify({"error": detail}), r.status_code

        data = r.json()
        app.logger.info("Omni character train response: %s", json.dumps(data)[:400])
        rid = data.get("request_id") or (data.get("output") or {}).get("id")
        if not rid:
            return jsonify({"error": f"Unexpected response: {data}"}), 500

        poll_url = (data.get("output") or {}).get("urls", {}).get("get") or \
                   f"{LEGACY_MEDIA_BASE}/predictions/{rid}/result"
        jobs[rid] = {"status": "processing", "url": None, "error": None,
                     "character_name": character_name, "type": "character_train"}

        def poll_train(request_id, p_url, name):
            try:
                result = _omni_poll(p_url)
                # Training result — no video URL, just the completed request_id itself is the token
                jobs[request_id].update({
                    "status": "completed",
                    "character_name": name,
                    "omni_ref": f"@omni-character:{request_id}",
                })
            except Exception as e:
                jobs[request_id].update({"status": "failed", "error": str(e)})

        threading.Thread(target=poll_train, args=(rid, poll_url, character_name), daemon=True).start()
        return jsonify({"request_id": rid, "character_name": character_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/omni-character/status/<request_id>")
def omni_character_status(request_id):
    """Poll character training job status."""
    job = jobs.get(request_id)
    if job:
        return jsonify(job)
    # Fallback: query legacy provider directly
    try:
        r = requests.get(f"{LEGACY_MEDIA_BASE}/predictions/{request_id}/result",
                         headers=muapi_headers(), timeout=30)
        r.raise_for_status()
        data   = r.json()
        status = (data.get("output") or {}).get("status") or data.get("status") or "processing"
        return jsonify({"status": status, "omni_ref": f"@omni-character:{request_id}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


# ---------------------------------------------------------------------------
# Seedance 2 — First & Last Frame
# ---------------------------------------------------------------------------

_FLF_ENDPOINTS = {
    # UI values sent by the frontend
    "global-standard": "sd-2-first-last-frame",
    "global-fast":     "sd-2-first-last-frame-fast",
    "vip-standard":    "sd-2-vip-first-last-frame",
    "vip-fast":        "sd-2-vip-first-last-frame-fast",
    # legacy aliases (kept for back-compat)
    "standard":        "sd-2-first-last-frame",
    "fast":            "sd-2-first-last-frame-fast",
    "vip":             "sd-2-vip-first-last-frame",
}

@app.route("/api/first-last-frame", methods=["POST"])
def first_last_frame():
    d            = request.json or {}
    prompt       = (d.get("prompt") or "").strip()
    images_list  = d.get("images_list") or []
    aspect_ratio = d.get("aspect_ratio", "16:9")
    duration     = _int(d.get("duration"), 5, "duration")
    quality      = (d.get("quality") or "standard").lower()

    images_list = [u for u in images_list if u and u.strip()]
    if not images_list:
        return jsonify({"error": "At least one image (first frame) is required"}), 400
    if len(images_list) > 2:
        images_list = images_list[:2]
    if duration < 4 or duration > 15:
        return jsonify({"error": "Duration must be between 4 and 15 seconds"}), 400

    slug = _FLF_ENDPOINTS.get(quality, _FLF_ENDPOINTS["standard"])

    payload = {
        "prompt":      prompt,
        "images_list": images_list,
        "duration":    duration,
    }
    # VIP-fast infers aspect from images; others accept the field.
    if quality != "vip-fast":
        payload["aspect_ratio"] = aspect_ratio

    try:
        r = requests.post(f"{LEGACY_MEDIA_BASE}/{slug}",
                          json=payload, headers=muapi_headers(), timeout=60)
        if not r.ok:
            try:
                body = r.json()
                if isinstance(body.get("detail"), dict):
                    detail = body["detail"].get("error") or str(body["detail"])
                elif body.get("error"):
                    detail = body["error"]
                else:
                    detail = str(body)
            except Exception:
                detail = r.text
            return jsonify({"error": detail}), r.status_code
        data = r.json()
        app.logger.info("FLF submission response: %s", json.dumps(data)[:500])
        rid = data.get("request_id") or (data.get("output") or {}).get("id")
        if not rid:
            return jsonify({"error": f"Unexpected response: {data}"}), 500
        poll_url = (data.get("output") or {}).get("urls", {}).get("get") or \
                   f"{LEGACY_MEDIA_BASE}/predictions/{rid}/result"
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        db_insert_gen(rid, prompt, "first-last-frame", slug, aspect_ratio, duration, quality)

        def poll(request_id, p_url):
            try:
                result    = _omni_poll(p_url)
                video_out = extract_url(result, "outputs", "url", "video_url", "output", "video")
                cost      = _extract_cost(result)
                timing_ms = _extract_execution_time_ms(result)
                jobs[request_id].update({"status": "completed", "url": video_out,
                                         "cost": cost, "execution_time_ms": timing_ms})
                db_update_gen(request_id, "completed", video_url=video_out, cost=cost,
                              execution_time_ms=timing_ms)
            except Exception as e:
                jobs[request_id].update({"status": "failed", "error": str(e)})
                db_update_gen(request_id, "failed", error=str(e))

        threading.Thread(target=poll, args=(rid, poll_url), daemon=True).start()
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Video Combiner
# ---------------------------------------------------------------------------

@app.route("/api/combine-videos", methods=["POST"])
def combine_videos():
    d = request.json or {}
    videos_list  = d.get("videos_list", [])
    aspect_ratio = d.get("aspect_ratio", "auto")
    if len(videos_list) < 2:
        return jsonify({"error": "At least 2 video clips are required"}), 400
    payload = {"videos_list": videos_list[:60], "aspect_ratio": aspect_ratio}
    try:
        r = requests.post(f"{LEGACY_MEDIA_BASE}/video-combiner",
                          json=payload, headers=muapi_headers(), timeout=60)
        if not r.ok:
            try:
                body = r.json()
                detail = body.get("error") or body.get("detail") or str(body)
            except Exception:
                detail = r.text
            return jsonify({"error": detail}), r.status_code
        data = r.json()
        rid = data.get("request_id") or (data.get("output") or {}).get("id")
        if not rid:
            return jsonify({"error": f"Unexpected response: {data}"}), 500
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        db_insert_gen(rid, f"[combiner] {len(videos_list)} clips", "combiner",
                      "video-combiner", aspect_ratio, None, None)

        def poll(request_id):
            try:
                result = muapi_poll(request_id)
                video_url = extract_url(result, "outputs", "url", "video_url", "output", "video")
                cost = _extract_cost(result)
                timing_ms = _extract_execution_time_ms(result)
                jobs[request_id].update({"status": "completed", "url": video_url,
                                         "cost": cost, "execution_time_ms": timing_ms})
                db_update_gen(request_id, "completed", video_url=video_url, cost=cost,
                              execution_time_ms=timing_ms)
            except Exception as e:
                jobs[request_id].update({"status": "failed", "error": str(e)})
                db_update_gen(request_id, "failed", error=str(e))

        threading.Thread(target=poll, args=(rid,), daemon=True).start()
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Image Generation
# ---------------------------------------------------------------------------

@app.route("/images")
def images_page():
    return render_template("ai_images_v2.html")


@app.route("/images-v2")
def images_page_v2():
    return render_template("ai_images_v2.html")


@app.route("/images-legacy")
def images_page_legacy():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("images.html", embed=embed, legacy=True)


@app.route("/storyboard")
def storyboard_page():
    return render_template("storyboard_v2.html")


@app.route("/storyboard-v2")
def storyboard_page_v2():
    return render_template("storyboard_v2.html")


@app.route("/storyboard-legacy")
def storyboard_page_legacy():
    return render_template("storyboard.html")


# ---------------------------------------------------------------------------
# Storyboard Generation
# ---------------------------------------------------------------------------

def _load_storyboard_prompt():
    """Load storyboard_prompt.md from project root (live-reload)."""
    path = os.path.join(os.path.dirname(__file__), "storyboard_prompt.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Generate a professional 3x3 storyboard grid as a single 16:9 HD image with 9 cinematic frames."


_STORYBOARD_THINK_SUFFIX = """

---

Based on the storyboard requirements above and any reference images provided, output EXACTLY this JSON (no markdown fences, no extra text):
{
  "image_prompt": "<Highly detailed prompt for BytePlus Seedream image model to render a single 16:9 HD storyboard image. Must describe: 3x3 grid layout with thin white borders between 9 frames, each frame's cinematic composition (wide/medium/close-up), lighting, character appearance, setting, and the specific moment captured. No text overlays, no labels, no frame numbers. Hyper-realistic photographic quality.>",
  "shot_list": [
    "Frame 1: <2-4 second motion prompt starting from the reference image>",
    "Frame 2: <2-4 second motion prompt>",
    "Frame 3: <2-4 second motion prompt>",
    "Frame 4: <2-4 second motion prompt>",
    "Frame 5: <2-4 second motion prompt>",
    "Frame 6: <2-4 second motion prompt>",
    "Frame 7: <2-4 second motion prompt>",
    "Frame 8: <2-4 second motion prompt>",
    "Frame 9: <2-4 second motion prompt>"
  ]
}"""


def _decode_image_parts(images_b64):
    image_urls = []
    for uri in images_b64[:8]:
        if uri:
            image_urls.append(data_uri_from_existing(uri))
    return image_urls



@app.route("/api/storyboard/generate", methods=["POST"])
def storyboard_generate():
    import base64 as _b64
    import uuid as _uuid

    d = request.json or {}
    story = d.get("story", "").strip()
    images = d.get("images", [])
    if not story:
        return jsonify({"error": "Story is required"}), 400

    sb_prompt = _load_storyboard_prompt().replace("[YOUR STORY]", story)
    think_text = sb_prompt + _STORYBOARD_THINK_SUFFIX
    image_refs = _decode_image_parts(images)

    try:
        plan = byteplus_modelark.chat_json(think_text, image_urls=image_refs)
        image_prompt = plan.get("image_prompt", "").strip()
        shot_list = plan.get("shot_list", [])
    except Exception as e:
        return jsonify({"error": f"Planning step failed: {str(e)}"}), 500

    if not image_prompt:
        return jsonify({"error": "Planning model returned empty image prompt"}), 500

    sb_resolution = str(d.get("resolution", "2K")).upper()
    if sb_resolution not in ("1K", "2K", "4K"):
        sb_resolution = "2K"

    try:
        generated = byteplus_modelark.create_image_task(image_prompt, image_urls=image_refs, ratio="16:9", size=sb_resolution)
    except Exception as e:
        return jsonify({"error": f"Image generation failed: {str(e)}"}), 500

    image_url = generated.get("url")
    image_b64 = ""
    image_mime = "image/png"
    if image_url and image_url.startswith("data:") and "," in image_url:
        header, image_b64 = image_url.split(",", 1)
        image_mime = header.split(";", 1)[0].replace("data:", "") or image_mime
    elif image_url:
        try:
            img_resp = requests.get(image_url, timeout=120)
            img_resp.raise_for_status()
            image_mime = img_resp.headers.get("Content-Type", "image/png").split(";", 1)[0]
            image_b64 = _b64.b64encode(img_resp.content).decode("ascii")
        except Exception:
            pass

    if not image_b64:
        return jsonify({"error": "Image model returned no downloadable image. Try again."}), 500

    ext = "png" if "png" in image_mime else "jpg"
    fname = f"{_uuid.uuid4().hex}.{ext}"
    sb_dir = os.path.join(os.path.dirname(__file__), "static", "storyboards")
    os.makedirs(sb_dir, exist_ok=True)
    with open(os.path.join(sb_dir, fname), "wb") as fh:
        fh.write(_b64.b64decode(image_b64))
    static_url = f"/static/storyboards/{fname}"

    hid = log_history("storyboard", "byteplus-seedream-5.0-lite", story[:300], aspect_ratio="16:9")
    update_history(hid, "completed", output_url=static_url)
    return jsonify({"image_b64": image_b64, "image_mime": image_mime, "image_url": static_url, "shot_list": shot_list})


# ---------------------------------------------------------------------------
# Frame Extractor
# ---------------------------------------------------------------------------

_FRAME_POSITIONS = {
    1: "top-left corner (row 1, column 1)",
    2: "top-center (row 1, column 2)",
    3: "top-right corner (row 1, column 3)",
    4: "middle-left (row 2, column 1)",
    5: "dead center (row 2, column 2)",
    6: "middle-right (row 2, column 3)",
    7: "bottom-left corner (row 3, column 1)",
    8: "bottom-center (row 3, column 2)",
    9: "bottom-right corner (row 3, column 3)",
}

_FRAME_RESOLUTIONS = {
    "1K": "1024 × 576 pixels",
    "2K": "2048 × 1152 pixels",
    "4K": "4096 × 2304 pixels",
}

def _load_frame_extractor_prompt():
    path = os.path.join(os.path.dirname(__file__), "frame-extractor-agent.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are a Frame Extractor Agent. Analyze the 3x3 storyboard grid and regenerate the requested frame at high resolution."


@app.route("/api/storyboard/extract-frames", methods=["POST"])
def storyboard_extract_frames():
    import base64 as _b64
    import uuid as _uuid

    d = request.json or {}
    image_uri = d.get("storyboard_image", "")
    frames = [int(f) for f in d.get("frames", []) if 1 <= int(f) <= 9]
    resolution = d.get("resolution", "2K").upper()
    if not image_uri:
        return jsonify({"error": "Storyboard image is required"}), 400
    if not frames:
        return jsonify({"error": "Select at least one frame (1-9)"}), 400
    if resolution not in _FRAME_RESOLUTIONS:
        resolution = "2K"

    image_ref = data_uri_from_existing(image_uri)
    sb_dir = os.path.join(os.path.dirname(__file__), "static", "storyboards")
    os.makedirs(sb_dir, exist_ok=True)
    results = []
    agent_doc = _load_frame_extractor_prompt()

    for frame_num in frames:
        prompt_text = (
            f"{agent_doc}\n\nTASK: Extract and regenerate Frame {frame_num} from the attached 3x3 storyboard grid. "
            f"Frame position: {_FRAME_POSITIONS[frame_num]}. Target resolution: {resolution} ({_FRAME_RESOLUTIONS[resolution]}). "
            "Output only the regenerated frame with no borders, labels, grid, or text."
        )
        try:
            generated = byteplus_modelark.create_image_task(prompt_text, image_urls=[image_ref], ratio="16:9", size=resolution)
            url = generated.get("url")
            if not url:
                results.append({"frame": frame_num, "error": "Model returned no image URL"})
                continue
            if url.startswith("data:") and "," in url:
                header, img_b64 = url.split(",", 1)
                img_mime = header.split(";", 1)[0].replace("data:", "") or "image/png"
                img_bytes = _b64.b64decode(img_b64)
            else:
                img_resp = requests.get(url, timeout=120)
                img_resp.raise_for_status()
                img_mime = img_resp.headers.get("Content-Type", "image/png").split(";", 1)[0]
                img_bytes = img_resp.content
                img_b64 = _b64.b64encode(img_bytes).decode("ascii")
            ext = "png" if "png" in img_mime else "jpg"
            fname = f"frame_{frame_num}_{_uuid.uuid4().hex[:8]}.{ext}"
            with open(os.path.join(sb_dir, fname), "wb") as fh:
                fh.write(img_bytes)
            results.append({"frame": frame_num, "image_b64": img_b64, "image_mime": img_mime, "image_url": f"/static/storyboards/{fname}", "resolution": resolution})
        except Exception as e:
            results.append({"frame": frame_num, "error": str(e)})
    return jsonify({"results": results})


def _img_poll_url(result):
    outputs = result.get("outputs") or []
    if outputs:
        return outputs[0]
    return extract_url(result, "url", "image", "image_url", "output")


def _muapi_result_payload(request_id):
    """Fetch a legacy provider prediction result payload, even when legacy provider responds with HTTP 400 for failed jobs."""
    resp = requests.get(f"{LEGACY_MEDIA_BASE}/predictions/{request_id}/result",
                        headers=muapi_headers(), timeout=30)
    try:
        payload = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise
    if resp.ok or resp.status_code == 400:
        return payload
    resp.raise_for_status()
    return payload


def _muapi_result_status(payload):
    data = payload.get("data") or {}
    return data.get("status") or payload.get("status") or ("failed" if (data.get("error") or payload.get("error")) else None)


def _muapi_result_error(payload):
    data = payload.get("data") or {}
    return data.get("error") or payload.get("error") or payload.get("message") or ""


@app.route("/api/images/status/<request_id>")
def images_status(request_id):
    if request_id in jobs:
        return jsonify(jobs[request_id])
    try:
        result = _muapi_result_payload(request_id)
        status = _muapi_result_status(result)
        url = _img_poll_url(result)
        error = _muapi_result_error(result)
        return jsonify({"status": status, "url": url, "error": error})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/images/generate", methods=["POST"])
def images_generate():
    d       = request.json
    model   = "seedream-5-0-lite-260128"
    prompt  = d.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    try:
        refs = _provider_media_urls([u for u in (d.get("images_list") or []) if u and str(u).strip()])
        result = byteplus_modelark.create_image_task(
            prompt,
            image_urls=refs,
            ratio=d.get("aspect_ratio", "1:1"),
            size=str(d.get("resolution", "1k")).upper(),
        )
        rid = result["request_id"]
        hist_id = log_history("images", model, prompt, aspect_ratio=d.get("aspect_ratio", "1:1"),
                              quality=d.get("quality"), request_id=rid,
                              specs=json.dumps({"provider": "byteplus-modelark", "task_id": rid, "model": result.get("model")}))
        update_history(hist_id, "completed", output_url=result.get("url"))
        jobs[rid] = {"status": "completed", "url": result.get("url"), "error": None, "provider": "byteplus-modelark"}
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/images/edit", methods=["POST"])
def images_edit():
    d         = request.json
    model     = "seedream-5-0-lite-260128-edit"
    prompt    = d.get("prompt", "").strip()
    image_url = d.get("image_url", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if not image_url:
        return jsonify({"error": "Image URL is required"}), 400

    try:
        extras = [u for u in (d.get("extra_images") or []) if u and str(u).strip()]
        refs = _provider_media_urls(([image_url] + extras)[:14])
        result = byteplus_modelark.create_image_task(
            prompt,
            image_urls=refs,
            ratio=d.get("aspect_ratio", "1:1"),
            size=str(d.get("resolution", "1k")).upper(),
        )
        rid = result["request_id"]
        hist_id = log_history("images", model, prompt, aspect_ratio=d.get("aspect_ratio", "1:1"),
                              quality=d.get("quality"), specs="edit", request_id=rid)
        update_history(hist_id, "completed", output_url=result.get("url"))
        jobs[rid] = {"status": "completed", "url": result.get("url"), "error": None, "provider": "byteplus-modelark"}
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Kling v3.0 Video Generation
# ---------------------------------------------------------------------------

@app.route("/kling")
def kling_page():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("kling.html", embed=embed)


# ---------------------------------------------------------------------------
# AI Videos page — Seedance 2.0, Veo 3.1, Grok, AI Clipping
# ---------------------------------------------------------------------------

@app.route("/ai-videos")
def ai_videos_page():
    return render_template("ai_videos_v2.html", v2_config=AI_VIDEOS_V2_CONFIG)


@app.route("/ai-videos-v2")
def ai_videos_page_v2():
    return render_template("ai_videos_v2.html", v2_config=AI_VIDEOS_V2_CONFIG)


@app.route("/ai-videos-legacy")
def ai_videos_page_legacy():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("ai_videos.html", embed=embed, legacy=True)


def _ai_vid_post(endpoint, payload):
    """POST to a legacy provider endpoint, return (request_id, raw_data) or raise."""
    r = requests.post(f"{LEGACY_MEDIA_BASE}/{endpoint}", json=payload,
                      headers=muapi_headers(), timeout=60)
    if not r.ok:
        try:
            body = r.json()
            if isinstance(body.get("detail"), dict):
                detail = body["detail"].get("error") or str(body["detail"])
            else:
                detail = body.get("error") or body.get("detail") or str(body)
        except Exception:
            detail = r.text
        raise requests.HTTPError(f"{r.status_code}: {detail}", response=r)
    data = r.json()
    rid = (data.get("request_id") or
           data.get("id") or
           (data.get("output") or {}).get("id") or
           (data.get("data") or {}).get("request_id") or
           (data.get("data") or {}).get("id"))
    return rid, data


def _ai_vid_job(endpoint, payload, mode, model, history_prompt=None,
                history_specs=None, history_aspect_ratio=None,
                history_duration=None, history_quality=None,
                history_page="ai-videos"):
    """Submit a job, start background poll thread, return request_id."""
    rid, _ = _ai_vid_post(endpoint, payload)
    if not rid:
        raise ValueError(f"No request_id in response from {endpoint}")
    jobs[rid] = {"status": "processing", "url": None, "error": None}
    hid = log_history(
        history_page,
        model,
        history_prompt if history_prompt is not None else payload.get("prompt", ""),
        aspect_ratio=history_aspect_ratio if history_aspect_ratio is not None else payload.get("aspect_ratio"),
        duration=history_duration if history_duration is not None else payload.get("duration"),
        quality=history_quality if history_quality is not None else (payload.get("quality") or payload.get("scale")),
        specs=history_specs if history_specs is not None else rid,
        request_id=rid,
    )

    def _poll(request_id, hist_id):
        try:
            result = muapi_poll(request_id)
            url = extract_url(result, "outputs", "url", "video_url", "output", "video")
            # AI Clipping may return a list
            if not url:
                outputs = result.get("outputs")
                if isinstance(outputs, list) and outputs:
                    url = outputs[0]
            cost = _extract_cost(result)
            timing_ms = _extract_execution_time_ms(result)
            jobs[request_id].update({"status": "completed", "url": url,
                                     "cost": cost,
                                     "execution_time_ms": timing_ms,
                                     "clips": result.get("outputs") if isinstance(result.get("outputs"), list) else None})
            update_history(hist_id, "completed", output_url=url, cost=cost,
                           execution_time_ms=timing_ms)
        except Exception as e:
            jobs[request_id].update({"status": "failed", "error": str(e)})
            update_history(hist_id, "failed")

    threading.Thread(target=_poll, args=(rid, hid), daemon=True).start()
    return rid


def _byteplus_video_job(prompt, *, image_urls=None, video_urls=None, audio_urls=None,
                        aspect_ratio="16:9", duration=5, generate_audio=True,
                        fast=False, model_label="BytePlus Seedance 2.0",
                        mode="t2v", history_page="ai-videos", history_quality=None,
                        history_specs=None, resolution=None):
    clean_images = _provider_media_urls(image_urls or [])
    clean_videos = _provider_media_urls(video_urls or [])
    clean_audios = _provider_media_urls(audio_urls or [])
    submission = byteplus_modelark.create_video_task(
        prompt,
        image_urls=clean_images,
        video_urls=clean_videos,
        audio_urls=clean_audios,
        ratio=aspect_ratio,
        duration=duration,
        generate_audio=generate_audio,
        fast=fast,
        resolution=resolution,
    )
    rid = submission["request_id"]
    model = submission.get("model") or model_label
    specs = history_specs or json.dumps({
        "provider": "byteplus-modelark",
        "task_id": rid,
        "model": model,
    })
    jobs[rid] = {"status": "processing", "url": None, "error": None, "provider": "byteplus-modelark"}
    hid = log_history(
        history_page,
        model_label,
        prompt,
        aspect_ratio=aspect_ratio,
        duration=duration,
        quality=history_quality or ("fast" if fast else "standard"),
        specs=specs,
        request_id=rid,
    )

    def _poll(task_id, hist_id):
        try:
            result = byteplus_modelark.wait_for_task(task_id)
            url = result.get("url")
            jobs[task_id].update({"status": "completed", "url": url})
            update_history(hist_id, "completed", output_url=url)
        except Exception as exc:
            jobs[task_id].update({"status": "failed", "error": str(exc)})
            update_history(hist_id, "failed")

    threading.Thread(target=_poll, args=(rid, hid), daemon=True).start()
    return rid


def _is_not_found_error(exc):
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 404:
        return True
    return "not found" in str(exc).lower()


def _seedance2_i2v_job_with_fallback(payload, mode, model, **history_kwargs):
    """Submit Seedance 2.0 I2V, tolerating legacy provider slug changes on 404 only."""
    endpoints = (
        "sd-2-i2v",
        "sd-2-image-to-video",
        "seedance-v2.0-i2v",
        "sd-2-i2v-480p",
    )
    not_found = []
    for endpoint in endpoints:
        try:
            return _ai_vid_job(endpoint, payload, mode, model, **history_kwargs)
        except requests.HTTPError as exc:
            if not _is_not_found_error(exc):
                raise
            not_found.append(endpoint)
            app.logger.warning("Seedance 2.0 I2V endpoint not found: %s", endpoint)
    raise requests.HTTPError(f"Seedance 2.0 I2V endpoint not found. Tried: {', '.join(not_found)}")


@app.route("/api/ai-videos/status/<request_id>")
def ai_videos_status(request_id):
    job = jobs.get(request_id)
    if job:
        return jsonify(job)
    # Fall back to history table
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT status, output_url, cost, execution_time_ms FROM gen_history WHERE specs=? OR request_id=? ORDER BY id DESC LIMIT 1",
            (request_id, request_id)).fetchone()
    if row:
        return jsonify({"status": row["status"], "url": row["output_url"],
                        "cost": row["cost"], "execution_time_ms": row["execution_time_ms"]})
    return jsonify({"error": "Not found"}), 404


# ── Seedance 2.0 ──────────────────────────────────────────────────────────

@app.route("/api/ai-videos/seedance/t2v", methods=["POST"])
def aiv_seedance_t2v():
    d = request.json or {}
    prompt = d.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    try:
        rid = _byteplus_video_job(
            prompt,
            aspect_ratio=d.get("aspect_ratio", "16:9"),
            duration=_int(d.get("duration"), 5, "duration"),
            generate_audio=bool(d.get("generate_audio", True)),
            fast=True,
            model_label="BytePlus Seedance 2.0 T2V",
            mode="t2v",
        )
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-videos/seedance/i2v", methods=["POST"])
def aiv_seedance_i2v():
    d = request.json or {}
    prompt    = d.get("prompt", "").strip()
    image_url = d.get("image_url", "").strip()
    model     = d.get("model", "seedance-v1.5-pro-i2v")
    if not image_url:
        return jsonify({"error": "image_url is required"}), 400
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    try:
        images = [image_url]
        if d.get("last_image"):
            images.append(d["last_image"])
        rid = _byteplus_video_job(
            prompt,
            image_urls=images,
            aspect_ratio=d.get("aspect_ratio", "16:9"),
            duration=_int(d.get("duration"), 5, "duration"),
            generate_audio=bool(d.get("generate_audio", True)),
            fast="fast" in model,
            model_label="BytePlus Seedance 2.0 I2V",
            mode="i2v",
        )
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-videos/multiscene/render", methods=["POST"])
def aiv_multiscene_render():
    d = request.json or {}
    prompt = (d.get("prompt") or "").strip()
    images_list = [u for u in (d.get("images_list") or []) if u and str(u).strip()]
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if not images_list:
        return jsonify({"error": "At least one reference image is required"}), 400

    duration = _int(d.get("duration"), 10, "duration")
    if duration < 4 or duration > 15:
        return jsonify({"error": "duration must be between 4 and 15 seconds"}), 400

    try:
        rid = _byteplus_video_job(
            prompt,
            image_urls=images_list[:9],
            aspect_ratio=d.get("aspect_ratio", "16:9"),
            duration=duration,
            generate_audio=bool(d.get("generate_audio", True)),
            fast=str(d.get("quality", "")).lower() in {"fast", "global-fast", "vip-fast"},
            model_label="KAMOD Multi Scene Render",
            mode="multiscene",
            history_quality=d.get("quality", "basic"),
        )
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Veo 3.1 ───────────────────────────────────────────────────────────────

# Quality → legacy provider model slug mapping for Veo 3.1
_VEO_T2V_MODELS = {
    "lite":     "veo3.1-lite-text-to-video",
    "standard": "veo3.1-text-to-video",
    "fast":     "veo3.1-fast-text-to-video",
}
_VEO_I2V_MODELS = {
    "lite":     "veo3.1-lite-image-to-video",
    "standard": "veo3.1-image-to-video",
    # no public 'veo3.1-fast-image-to-video' variant documented; fall back to fast alias below
    "fast":     "veo3.1-fast-image-to-video",
}

@app.route("/api/ai-videos/veo/t2v", methods=["POST"])
def aiv_veo_t2v():
    d = request.json or {}
    prompt = d.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    quality = (d.get("quality") or "fast").lower()
    model_slug = _VEO_T2V_MODELS.get(quality, "veo3.1-fast-text-to-video")
    payload = {
        "prompt":       prompt,
        "aspect_ratio": d.get("aspect_ratio", "16:9"),
        "duration":     _int(d.get("duration"), 5, "duration"),
        "resolution":   d.get("resolution", "720p"),
    }
    try:
        rid = _ai_vid_job(model_slug, payload, "t2v", model_slug)
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-videos/veo/i2v", methods=["POST"])
def aiv_veo_i2v():
    d = request.json or {}
    image_url = d.get("image_url", "").strip()
    if not image_url:
        return jsonify({"error": "image_url is required"}), 400
    quality = (d.get("quality") or "fast").lower()
    model_slug = _VEO_I2V_MODELS.get(quality, "veo3.1-fast-image-to-video")
    payload = {
        "prompt":       d.get("prompt", "").strip(),
        "image_url":    image_url,
        "aspect_ratio": d.get("aspect_ratio", "16:9"),
        "duration":     _int(d.get("duration"), 5, "duration"),
        "resolution":   d.get("resolution", "720p"),
    }
    if d.get("last_image"):
        payload["last_image"] = d["last_image"]
    try:
        rid = _ai_vid_job(model_slug, payload, "i2v", model_slug)
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-videos/veo/reference", methods=["POST"])
def aiv_veo_reference():
    d = request.json or {}
    prompt      = d.get("prompt", "").strip()
    images_list = d.get("images_list", [])
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if not images_list:
        return jsonify({"error": "At least one reference image is required"}), 400
    payload = {
        "prompt":          prompt,
        "images_list":     images_list[:3],
        "resolution":      d.get("resolution", "720p"),
        "duration":        _int(d.get("duration"), 5, "duration"),
        "generate_audio":  bool(d.get("generate_audio", True)),
    }
    try:
        rid = _ai_vid_job("veo3.1-reference-to-video", payload, "reference", "veo3.1-reference")
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Grok ─────────────────────────────────────────────────────────────────

@app.route("/api/ai-videos/grok/t2v", methods=["POST"])
def aiv_grok_t2v():
    d = request.json or {}
    prompt = d.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    payload = {
        "prompt":       prompt,
        "aspect_ratio": d.get("aspect_ratio", "16:9"),
        "mode":         d.get("mode", "normal"),
        "resolution":   d.get("resolution", "720p"),
        "duration":     _int(d.get("duration"), 5, "duration"),
    }
    try:
        rid = _ai_vid_job("grok-imagine-text-to-video", payload, "t2v", "grok-imagine-t2v")
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-videos/grok/i2v", methods=["POST"])
def aiv_grok_i2v():
    d = request.json or {}
    images_list = d.get("images_list", [])
    if not images_list:
        return jsonify({"error": "At least one image is required"}), 400
    payload = {
        "prompt":       d.get("prompt", "").strip(),
        "images_list":  images_list[:3],
        "mode":         d.get("mode", "normal"),
        "resolution":   d.get("resolution", "720p"),
        "duration":     _int(d.get("duration"), 5, "duration"),
    }
    try:
        rid = _ai_vid_job("grok-imagine-image-to-video", payload, "i2v", "grok-imagine-i2v")
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── AI Content Analysis (BytePlus) ──────────────────────────────────────────

_ANALYZER_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "agents", "video-analyzer-agent.md")

def _load_analyzer_prompt():
    try:
        with open(_ANALYZER_PROMPT_PATH, encoding="utf-8") as _f:
            return _f.read()
    except FileNotFoundError:
        return "You are the Video Analyzer Agent. Analyze the uploaded video and respond in the requested language only."

_ANALYSIS_LANG_MAP = {"en": "English", "ru": "Russian", "uz": "Uzbek"}
_ANALYSIS_UCASE_LABELS = {
    "cinematic": "CINEMATIC PROMPTS",
    "seo":       "SEO & SOCIAL PACK",
    "shortform": "SHORTFORM CREATORS",
    "education": "EDUCATION PACK",
    "podcast":   "PODCAST / INTERVIEW PACK",
    "marketing": "MARKETING & BUSINESS",
    "meeting":   "INTERNAL MEETINGS",
    "transcribe": "FULL TRANSCRIPTION",
}


@app.route("/api/ai-videos/analyze", methods=["POST"])
def aiv_analyze():
    """AI Content Analysis using BytePlus Seed 2.0 Lite."""

    d         = request.json or {}
    video_url = (d.get("video_url") or "").strip()
    lang_key  = (d.get("language") or "en").lower()
    ucase_key = (d.get("use_case") or "cinematic").lower()

    if not video_url:
        return jsonify({"error": "video_url is required"}), 400

    language   = _ANALYSIS_LANG_MAP.get(lang_key, "English")
    ucase_name = _ANALYSIS_UCASE_LABELS.get(ucase_key, "CINEMATIC PROMPTS")

    # Build prompt from agent spec + requested language + requested use case
    agent_spec = _load_analyzer_prompt()
    if ucase_key == "transcribe":
        task_prompt = (
            f"{agent_spec}\n\n"
            f"---\n\n"
            f"TASK: Transcribe the spoken audio from the provided video.\n"
            f"USE CASE: {ucase_name}.\n"
            "Detect the spoken language automatically and write the transcript in the same language that is spoken. "
            "Do not translate the transcript into the selected UI language. If multiple languages are spoken, preserve each language as spoken.\n"
            "Return ONLY the transcript, with simple timestamps when possible. "
            "If there is no spoken dialogue, write: No spoken dialogue detected."
        )
        language = "Original spoken language"
    else:
        task_prompt = (
            f"{agent_spec}\n\n"
            f"---\n\n"
            f"TASK: Analyze the provided video.\n"
            f"OUTPUT LANGUAGE: {language} (all output MUST be in {language} only).\n"
            f"USE CASE: {ucase_name} — produce ONLY the sections defined for this use case in the spec above.\n"
            f"Never invent facts. If something is not present in the video, write the equivalent of "
            f"'Not specified in the video' in {language}. Be concise and copy-paste ready."
        )

    try:
        output = byteplus_modelark.chat(
            task_prompt,
            video_urls=[_provider_media_url(video_url)],
            reasoning_effort="medium",
        ).strip()
    except Exception as e:
        return jsonify({"error": f"Analysis failed: {e}"}), 500

    hid = log_history("ai-videos", "AI Content Analysis",
                      f"[analysis/{ucase_key}/{lang_key}] {video_url}",
                      specs=f"analysis-{ucase_key}-{lang_key}")
    try:
        update_history(hid, "completed", output_text=output)
    except Exception:
        pass
    return jsonify({"output": output, "language": language, "use_case": ucase_name})


# ── YouTube Downloader ────────────────────────────────────────────────────

@app.route("/api/ai-videos/youtube-download", methods=["POST"])
def aiv_youtube_download():
    d = request.json or {}
    yt_url = (d.get("url") or "").strip()
    if not yt_url:
        return jsonify({"error": "url is required"}), 400
    fmt = (d.get("format") or "720p").strip()  # e.g. "720p", "1080p", "mp3", "m4a", "aac"
    payload = {"url": yt_url, "format": fmt}
    try:
        rid = _ai_vid_job("youtube-download", payload, "youtube", "youtube-download")
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Auto Crop ─────────────────────────────────────────────────────────────

@app.route("/api/ai-videos/autocrop", methods=["POST"])
def aiv_autocrop():
    d = request.json or {}
    video_url = (d.get("video_url") or "").strip()
    if not video_url:
        return jsonify({"error": "video_url is required"}), 400
    payload = {
        "video_url":    video_url,
        "aspect_ratio": d.get("aspect_ratio", "9:16"),
        "start_time":   _float(d.get("start_time"), 0.0, "start_time"),
        # Cap the fallback to a short safe window if the client cannot determine
        # duration, instead of accidentally sending an open-ended clip.
        "end_time":     _float(d.get("end_time"), 8.0, "end_time"),
    }
    try:
        clip_duration = max(1, round(payload["end_time"] - payload["start_time"]))
        rid = _ai_vid_job(
            "autocrop",
            payload,
            "autocrop",
            "KAMOD Auto Crop",
            history_prompt=f"[autocrop] {video_url}",
            history_aspect_ratio=payload["aspect_ratio"],
            history_duration=clip_duration,
        )
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-videos/upscale", methods=["POST"])
def aiv_upscale():
    d = request.json or {}
    video_url = d.get("video_url", "").strip()
    if not video_url:
        return jsonify({"error": "video_url is required"}), 400
    scale = str(d.get("scale", "2"))
    payload = {
        "video_url": video_url,
        "scale":     scale,
    }
    try:
        rid = _ai_vid_job(
            "topaz-video-upscale",
            payload,
            "upscale",
            "KAMOD Upscale",
            history_prompt=f"[upscale] {video_url}",
            history_quality=f"{scale}x",
        )
        return jsonify({"request_id": rid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _atlas_extract_url(inner):
    """Pull the first video URL out of an legacy cloud result dict (handles all known shapes)."""
    outputs = inner.get("outputs") or []
    if isinstance(outputs, list) and outputs:
        return outputs[0]
    # Fallback: try common single-value keys
    for k in ("url", "video_url", "video", "output", "result"):
        v = inner.get(k)
        if v:
            if isinstance(v, list) and v:
                return v[0]
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                # e.g. {"url": "https://..."}
                for sub in ("url", "video_url", "video"):
                    sv = v.get(sub)
                    if isinstance(sv, str) and sv:
                        return sv
    return None


def _translate_refs_for_atlas(prompt):
    """Convert legacy provider-style @imageN/@videoN/@audioN refs to legacy cloud natural-language style.

    legacy provider:  '@image1 holds @image2 and speaks'
    legacy cloud:  'image 1 holds image 2 and speaks'
    """
    import re
    prompt = re.sub(r'@image(\d+)',  r'image \1',  prompt)
    prompt = re.sub(r'@video(\d+)',  r'video \1',  prompt)
    prompt = re.sub(r'@audio(\d+)',  r'audio \1',  prompt)
    return prompt


@app.route("/api/kling/status/<request_id>")
def kling_status(request_id):
    job = jobs.get(request_id)
    if job:
        return jsonify(job)

    try:
        r = requests.get(f"{LEGACY_CLOUD_VIDEO_BASE}/model/result/{request_id}",
                         headers=atlas_headers(), timeout=30)
        r.raise_for_status()
        raw = r.json()
        inner = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = inner.get("status") or "processing"
        if status in ("succeeded", "success"):
            status = "completed"
        url = _atlas_extract_url(inner) if status == "completed" else None
        error = inner.get("error") or None

        if status in ("completed", "failed"):
            try:
                with sqlite3.connect(DB_PATH) as _db:
                    _db.execute(
                        "UPDATE gen_history SET status=?, output_url=? WHERE request_id=? AND status NOT IN ('completed')",
                        (status, url, request_id)
                    )
                    _db.commit()
            except Exception:
                pass

        return jsonify({"status": status, "url": url, "error": error})
    except Exception as e:
        return jsonify({"error": str(e), "status": "processing"}), 500


@app.route("/api/kling/t2v", methods=["POST"])
def kling_t2v():
    d = request.json
    model  = d.get("model", "kwaivgi/kling-v3.0-pro/text-to-video")
    prompt = d.get("prompt", "").strip()
    dur    = _int(d.get("duration"), 5, "duration")
    aspect = d.get("aspect_ratio", "16:9")
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    model = KLING_MODEL_MAP.get(model, model)
    try:
        rid, _ = atlas_generate(model, {
            "prompt":       prompt,
            "aspect_ratio": aspect,
            "duration":     dur,
            "sound":        d.get("generate_audio", True),
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hist_id = log_history("kling", model, prompt, aspect_ratio=aspect, duration=dur, request_id=rid)
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        def _poll_kling(request_id, hid):
            try:
                inner = atlas_poll(request_id)
                url = _atlas_extract_url(inner)
                jobs[request_id].update({"status": "completed", "url": url})
                update_history(hid, "completed", output_url=url)
            except Exception as ex:
                jobs[request_id].update({"status": "failed", "error": str(ex)})
                update_history(hid, "failed")
        threading.Thread(target=_poll_kling, args=(rid, hist_id), daemon=True).start()
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/kling/i2v", methods=["POST"])
def kling_i2v():
    d         = request.json
    model     = d.get("model", "kwaivgi/kling-v3.0-pro/image-to-video")
    prompt    = d.get("prompt", "").strip()
    image_url = d.get("image_url", "").strip()
    dur       = _int(d.get("duration"), 5, "duration")
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if not image_url:
        return jsonify({"error": "Image URL is required"}), 400
    model = KLING_MODEL_MAP.get(model, model)
    payload = {"prompt": prompt, "image": image_url,
               "duration": dur,
               "sound": d.get("generate_audio", True)}
    if d.get("last_image"):
        payload["end_image"] = d["last_image"].strip()
    try:
        rid, _ = atlas_generate(model, payload)
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hist_id = log_history("kling", model, prompt, duration=dur, request_id=rid)
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        def _poll_kling_i2v(request_id, hid):
            try:
                inner = atlas_poll(request_id)
                url = _atlas_extract_url(inner)
                jobs[request_id].update({"status": "completed", "url": url})
                update_history(hid, "completed", output_url=url)
            except Exception as ex:
                jobs[request_id].update({"status": "failed", "error": str(ex)})
                update_history(hid, "failed")
        threading.Thread(target=_poll_kling_i2v, args=(rid, hist_id), daemon=True).start()
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/kling/motion", methods=["POST"])
def kling_motion():
    d         = request.json
    model     = d.get("model", "kwaivgi/kling-v2.6-pro/motion-control")
    image_url = d.get("image_url", "").strip()
    video_url = d.get("video_url", "").strip()
    prompt    = d.get("prompt", "")
    if not image_url:
        return jsonify({"error": "Image URL is required"}), 400
    if not video_url:
        return jsonify({"error": "Video URL is required"}), 400
    model = KLING_MODEL_MAP.get(model, model)
    try:
        rid, _ = atlas_generate(model, {
            "prompt":               prompt,
            "image":                image_url,
            "video":                video_url,
            "character_orientation": d.get("character_orientation", "image"),
            "keep_original_sound":  d.get("keep_original_sound", True),
        })
        if not rid:
            return jsonify({"error": "No request_id returned"}), 500
        hist_id = log_history("kling", model, prompt, specs="motion-control", request_id=rid)
        jobs[rid] = {"status": "processing", "url": None, "error": None}
        def _poll_kling_mc(request_id, hid):
            try:
                inner = atlas_poll(request_id)
                url = _atlas_extract_url(inner)
                jobs[request_id].update({"status": "completed", "url": url})
                update_history(hid, "completed", output_url=url)
            except Exception as ex:
                jobs[request_id].update({"status": "failed", "error": str(ex)})
                update_history(hid, "failed")
        threading.Thread(target=_poll_kling_mc, args=(rid, hist_id), daemon=True).start()
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# AI Prompt Enhancer
# ---------------------------------------------------------------------------

@app.route("/api/enhance-prompt", methods=["POST"])
def enhance_prompt():
    raw = (request.json or {}).get("prompt", "").strip()
    if not raw:
        return jsonify({"error": "prompt is required"}), 400
    try:
        system = (
            "You are an expert prompt engineer for Seedance 2.0, a state-of-the-art "
            "text-to-video AI by ByteDance. Your job is to take a rough user prompt and "
            "rewrite it into a vivid, cinematic prompt that maximises video quality. "
            "Include: camera movement (e.g. slow dolly, aerial tracking), lighting mood, "
            "subject detail, motion physics, and atmosphere. Keep it under 200 words. "
            "Return ONLY the enhanced prompt — no explanations, no preamble."
        )
        enhanced = byteplus_modelark.chat(f"Enhance this prompt:\n{raw}", system=system, reasoning_effort="low")
        return jsonify({"enhanced": enhanced.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/kling/scenes", methods=["POST"])
def kling_scenes():
    import json as _json

    d = request.json or {}
    duration = _int(d.get("duration"), 10, "duration")
    aspect_ratio = (d.get("aspect_ratio") or "16:9").strip()
    idea = (d.get("idea") or "").strip()
    dialogue = (d.get("dialogue") or "").strip()
    refs = [str(u).strip() for u in (d.get("reference_urls") or []) if str(u).strip()]

    if duration < 4 or duration > 15:
        return jsonify({"error": "Duration must be between 4 and 15 seconds"}), 400
    if not refs:
        return jsonify({"error": "At least one reference image is required"}), 400

    system_prompt = _load_kling_scenes_prompt()
    user_ctx = [
        "Create a KAMOD AI Scenes workflow for video generation.",
        f"DURATION: {duration} seconds",
        f"ASPECT RATIO: {aspect_ratio}",
        "If the user idea is blank, infer the scene arc from the uploaded image(s).",
        "Use reference images as visual DNA and maintain identity, wardrobe, lighting, setting, and mood consistency.",
        "Return JSON only with this schema: {sequence_title, summary, mood, duration, shot_count, shots:[{id,title,timestamp,camera,action,consistency,dialogue_beat,kling_prompt}], energy_arc:{opening,middle,resolution}}.",
        "Write kling_prompt in English and make each prompt detailed, cinematic, and generation-ready.",
    ]
    user_ctx.append(f"USER IDEA: {idea}" if idea else "USER IDEA: (blank) - infer from reference image(s).")
    if dialogue:
        user_ctx.append(f"DIALOGUE / SPOKEN MOMENT: {dialogue}")

    try:
        result = byteplus_modelark.chat_json(
            "\n".join(user_ctx),
            system=system_prompt,
            image_urls=_provider_media_urls(refs[:3]),
        )
        hist_prompt = idea or result.get("sequence_title") or "Multi Scene workflow"
        hid = log_history("ai-videos", "KAMOD Multi Scene Plan", hist_prompt, aspect_ratio=aspect_ratio, duration=duration, quality="plan", specs=f"multiscene-plan-{uuid.uuid4()}")
        update_history(hid, "completed", output_text=_json.dumps(result, ensure_ascii=False, indent=2))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Scenes generation failed: {e}"}), 500


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

# Prompt agent system prompt files — edit .md files to update without restarting
_AGENT_PROMPT_FILES = {
    "cinematic": "seedance-2-vfx-agent.md",
    "sound":     "seedance_2_sound_effects_agent_system_prompt.md",
    "music":     "seedance_2_music_sound_agent_system_prompt.md",
}

def _load_agent_prompt(mode="cinematic"):
    filename = _AGENT_PROMPT_FILES.get(mode, _AGENT_PROMPT_FILES["cinematic"])
    path = os.path.join(os.path.dirname(__file__), filename)
    try:
        with open(path, encoding="utf-8") as _f:
            return _f.read()
    except FileNotFoundError:
        return "You are a Seedance 2.0 Cinematic Prompt Agent. Convert user ideas into structured Seedance 2.0 video prompts under 2000 characters."


def _load_kling_scenes_prompt():
    base_dir = os.path.join(os.path.dirname(__file__), "agents")
    chunks = []
    for filename in ("cinematic-multi-scene-agent.md", "dialogue-creator-agent.md"):
        path = os.path.join(base_dir, filename)
        try:
            with open(path, encoding="utf-8") as _f:
                chunks.append(_f.read())
        except FileNotFoundError:
            continue
    if chunks:
        return "\n\n---\n\n".join(chunks)
    return (
        "You are a cinematic multi-scene workflow agent. Given reference image(s), "
        "an optional idea, and optional dialogue context, produce a structured multi-shot "
        "sequence with Kling-ready prompts and continuity across all shots."
    )


@app.route("/api/build-prompt", methods=["POST"])
def build_prompt():
    import base64 as _b64
    d      = request.json or {}
    idea   = d.get("idea", "").strip()
    dur    = d.get("duration", "")
    style  = d.get("style", "").strip()
    mode   = d.get("mode", "cinematic")  # cinematic | sound | music
    images = d.get("images", [])         # list of base64 data-URIs, max 3
    if not idea:
        return jsonify({"error": "idea is required"}), 400

    user_msg = idea
    if dur:
        user_msg += f"\n\nTarget duration: {dur} seconds."
    if style:
        user_msg += f"\nStyle: {style}."
    if images:
        user_msg += f"\n\n{len(images)} reference image(s) attached. Analyse them and incorporate the visual details into your prompt output."

    try:
        system_prompt = _load_agent_prompt(mode)
        image_urls = []
        for img_b64 in images[:3]:
            mime = "image/jpeg"
            if img_b64.startswith("data:image/png"):
                mime = "image/png"
            elif img_b64.startswith("data:image/webp"):
                mime = "image/webp"
            image_urls.append(data_uri_from_bytes(_b64.b64decode(img_b64.split(",", 1)[-1]), mime))
        prompt = byteplus_modelark.chat(user_msg, system=system_prompt, image_urls=image_urls, reasoning_effort="medium").strip()
        if len(prompt) > 8000:
            prompt = prompt[:8000]
        return jsonify({"prompt": prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Community Prompts
# ---------------------------------------------------------------------------

COMMUNITY_PROMPTS = [
    {"prompt": "A determined penguin straps itself into a homemade rocket sled on an icy mountain. The rocket ignites with a massive burst and launches the penguin across the frozen landscape at insane speed, blasting through snowdrifts and leaving a fiery trail behind.", "category": "action", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1551085254-e96b210db58a?w=600&h=340&fit=crop"},
    {"prompt": "Slow cinematic dolly shot through a neon-lit cyberpunk alley at midnight, rain falling softly, reflections shimmering on wet pavement, a lone figure in a holographic coat walks into the mist.", "category": "cinematic", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=600&h=340&fit=crop"},
    {"prompt": "Aerial tracking shot over a vast ancient forest at golden hour, mist rising from the canopy, a river of light weaving between the trees, birds scattering in slow motion.", "category": "nature", "aspect_ratio": "16:9", "duration": 15, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&h=340&fit=crop"},
    {"prompt": "A colossal alien starship descends through storm clouds above a futuristic city, gravity waves ripple the skyscrapers below, lightning arcs around the hull, crowds watch in awe.", "category": "sci-fi", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1462331940025-496dfbfc7564?w=600&h=340&fit=crop"},
    {"prompt": "A lone samurai stands at the edge of a cliff during a cherry blossom storm, petals swirling in slow motion, dramatic low-angle shot with a blazing sunset backdrop, katana gleaming.", "category": "cinematic", "aspect_ratio": "9:16", "duration": 5, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1528360983277-13d401cdc186?w=600&h=340&fit=crop"},
    {"prompt": "Macro lens drift across a crystal cave, bioluminescent crystals pulsing with soft blue and violet light, water droplets falling in slow motion, ethereal ambient mist.", "category": "nature", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1520121401995-928cd50d4e27?w=600&h=340&fit=crop"},
    {"prompt": "A fire dancer performs on a black sand beach at night, spinning twin flames in perfect arcs, ocean waves crashing softly in the background, wide-angle overhead shot.", "category": "action", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1504639725590-34d0984388bd?w=600&h=340&fit=crop"},
    {"prompt": "A dragon made entirely of aurora borealis light soars over snow-capped mountains, its wings leaving trails of colour across the night sky, camera follows from below.", "category": "fantasy", "aspect_ratio": "16:9", "duration": 15, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1531366936337-7c912a4589a7?w=600&h=340&fit=crop"},
    {"prompt": "Time-lapse of a massive thunderstorm building over the ocean at dusk, lightning illuminating enormous cumulonimbus clouds, waves growing from calm to towering, dramatic wide shot.", "category": "nature", "aspect_ratio": "16:9", "duration": 10, "quality": "basic",
     "thumbnail_url": "https://images.unsplash.com/photo-1605727216801-e27ce1d0cc28?w=600&h=340&fit=crop"},
    {"prompt": "A robot chef in a sleek futuristic kitchen crafts an elaborate molecular gastronomy dish, precision movements, sparks of liquid nitrogen, close-up cuts between ingredients and technique.", "category": "sci-fi", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=600&h=340&fit=crop"},
    {"prompt": "Cinematic close-up of a vintage vinyl record spinning, camera slowly pulling back to reveal a dimly lit jazz club, silhouettes of musicians, smoke curling in the spotlight.", "category": "cinematic", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?w=600&h=340&fit=crop"},
    {"prompt": "A phoenix rises from an erupting volcano, feathers of living flame spreading wide, camera cranes upward as ash rains down and the sky turns blood orange.", "category": "fantasy", "aspect_ratio": "9:16", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=600&h=340&fit=crop"},
    {"prompt": "Extreme sports athlete base-jumps from a mountain peak at sunrise, tracking shot follows the free fall through clouds, parachute deploys revealing a breathtaking valley below.", "category": "action", "aspect_ratio": "16:9", "duration": 15, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1503220317375-aaad61436b1b?w=600&h=340&fit=crop"},
    {"prompt": "Deep ocean bioluminescent creatures drift past the camera in complete darkness, a whale glides silently overhead, rays of dim light penetrating from the surface far above.", "category": "nature", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1518020382113-a7e8fc38eac9?w=600&h=340&fit=crop"},
    {"prompt": "An ancient wizard's library comes to life — books fly open, star maps spin, potions bubble, candles float, camera weaves through the chaos in a single fluid shot.", "category": "fantasy", "aspect_ratio": "16:9", "duration": 10, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1481627834876-b7833e8f5570?w=600&h=340&fit=crop"},
    {"prompt": "Portrait mode: a model in haute couture walks a runway flooded with water, slow-motion splash with each step, studio lights refracted into rainbows, editorial fashion film.", "category": "cinematic", "aspect_ratio": "9:16", "duration": 5, "quality": "high",
     "thumbnail_url": "https://images.unsplash.com/photo-1509631179647-0177331693ae?w=600&h=340&fit=crop"},
]


@app.route("/api/community-prompts")
def community_prompts():
    return jsonify({"prompts": COMMUNITY_PROMPTS})


# ---------------------------------------------------------------------------
# AI Director
# ---------------------------------------------------------------------------

AI_DIRECTOR_SYSTEM = """You are Kamod AI Director, an advanced creative film director AI. Transform the user's idea into structured creative direction with 4 key cinematic shots.

Generate exactly 4 shots with these scene types:
1. B-ROLL: atmospheric/establishing. Camera: WIDE TRACKING, CRANE SHOT, or DRONE VISTA
2. HERO: emotional centerpiece. Camera: LOW-ANGLE, EYE-LEVEL CLOSE-UP, or CENTERED
3. AD: commercial-ready. Camera: CLEAN MEDIUM SHOT, RULE OF THIRDS, or PRODUCT MACRO
4. MOOD: artistic/stylized. Camera: DUTCH ANGLE, EXTREME CLOSE-UP, or SOFT BOKEH

Rules:
- script, sceneTitle, reasoning must be in the user's selected language (EN/RU/UZ)
- visualDescription must always be in ENGLISH only
- Each visualDescription must include the specific camera technique
- Return valid JSON only with this structure:
{
  "script": string,
  "suggestions": [
    { "sceneTitle": string, "sceneType": "B-ROLL"|"HERO"|"AD"|"MOOD", "visualDescription": string, "reasoning": string }
  ]
}"""

@app.route("/ai-director")
def ai_director():
    return render_template("ai_director_v2.html")

@app.route("/ai-director-v2")
def ai_director_v2():
    return render_template("ai_director_v2.html")

@app.route("/ai-director-legacy")
def ai_director_legacy():
    return render_template("ai_director.html")

@app.route("/api/ai-director/analyze", methods=["POST"])
def ai_director_analyze():
    d = request.json or {}
    story    = d.get("story", "").strip()
    language = d.get("language", "EN")
    img_b64  = d.get("image_base64", "")
    if not story:
        return jsonify({"error": "story is required"}), 400
    try:
        image_urls = []
        if img_b64:
            import base64 as _b64
            image_urls.append(data_uri_from_bytes(_b64.b64decode(img_b64.split(",", 1)[-1]), "image/jpeg"))
        result = byteplus_modelark.chat_json(
            f"Language: {language}\n\nUser idea:\n{story}",
            system=AI_DIRECTOR_SYSTEM,
            image_urls=image_urls,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai-director/generate-image", methods=["POST"])
def ai_director_generate_image():
    d         = request.json or {}
    visual    = d.get("visual_description", "").strip()
    aspect    = d.get("aspect_ratio", "16:9")
    image_url = d.get("image_url", "").strip()   # hosted reference image URL
    if not visual:
        return jsonify({"error": "visual_description is required"}), 400

    prompt = f"Cinematic still frame, {aspect} aspect ratio: {visual}"

    try:
        result = byteplus_modelark.create_image_task(
            prompt,
            image_urls=[_provider_media_url(image_url)] if image_url else None,
            ratio=aspect,
            size="2K",
        )
        rid = result["request_id"]
        hid = log_history("ai-director", "byteplus-seedream-5.0-lite", prompt, aspect_ratio=aspect, request_id=rid)
        update_history(hid, "completed", output_url=result.get("url"))
        jobs[rid] = {"status": "completed", "url": result.get("url"), "error": None, "provider": "byteplus-modelark"}
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        return jsonify({"error": e.response.text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-director/image-status/<request_id>")
def ai_director_image_status(request_id):
    if request_id in jobs:
        return jsonify(jobs[request_id])
    try:
        result = _muapi_result_payload(request_id)
        status = _muapi_result_status(result)
        url = _img_poll_url(result)
        error = _muapi_result_error(result)
        if status == "completed" and url:
            with sqlite3.connect(DB_PATH) as _db:
                _db.execute(
                    "UPDATE gen_history SET status='completed', output_url=? WHERE request_id=? AND page='ai-director'",
                    (url, request_id))
                _db.commit()
        elif status == "failed":
            with sqlite3.connect(DB_PATH) as _db:
                _db.execute(
                    "UPDATE gen_history SET status='failed' WHERE request_id=? AND page='ai-director'",
                    (request_id,))
                _db.commit()
        return jsonify({"status": status, "url": url, "error": error})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai-director/download-image/<request_id>")
def ai_director_download_image(request_id):
    row = None
    with sqlite3.connect(DB_PATH) as _db:
        row = _db.execute(
            "SELECT output_url FROM gen_history WHERE page='ai-director' AND request_id=? ORDER BY id DESC LIMIT 1",
            (request_id,)
        ).fetchone()
    if not row or not row[0]:
        return jsonify({"error": "Image not found"}), 404

    image_url = row[0]
    r = requests.get(image_url, stream=True, timeout=60)
    r.raise_for_status()

    content_type = r.headers.get("Content-Type", "image/jpeg")
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"

    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    return Response(
        stream_with_context(generate()),
        content_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="kamod-director-{request_id}.{ext}"'}
    )


# ---------------------------------------------------------------------------
# Voice Over Studio  (BytePlus TTS)
# ---------------------------------------------------------------------------

_VO_DIR = os.path.join(os.path.dirname(__file__), "static", "voiceover")

def _pcm_to_wav(pcm_data, sample_rate=24000, channels=1, sample_width=2):
    """Wrap raw PCM bytes in a WAV container using stdlib only."""
    import wave, io as _io
    buf = _io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


@app.route("/api/voiceover/generate", methods=["POST"])
def voiceover_generate():
    d = request.json or {}
    voice         = d.get("voice", "zh_male_jieshuonansheng_mars_bigtts")
    text          = d.get("text", "").strip()
    style_instr   = d.get("style_instruction", "").strip()
    language      = d.get("language", "English")
    tone          = d.get("tone", "")
    pace          = d.get("pace", "")

    if not text:
        return jsonify({"error": "Script text is required"}), 400
    # Build TTS prompt with style directives embedded in the text
    directives = []
    if style_instr:
        directives.append(style_instr)
    if tone:
        directives.append(f"Tone: {tone}")
    if pace:
        directives.append(f"Pace: {pace}")
    if language and language != "English":
        directives.append(f"Deliver in {language} with natural native intonation")
    full_prompt = ("; ".join(directives) + ".\n\n" + text) if directives else text

    try:
        output_fmt = d.get("output_format", "mp3").lower()  # "mp3" or "wav"
        encoding = "mp3" if output_fmt == "mp3" else "pcm"
        audio_bytes = byteplus_voice.synthesize(full_prompt, voice=voice, language=language, audio_format=encoding)

        os.makedirs(_VO_DIR, exist_ok=True)

        if output_fmt == "mp3":
            file_bytes = audio_bytes
            ext = "mp3"
        else:
            file_bytes = _pcm_to_wav(audio_bytes, sample_rate=24000)
            ext = "wav"

        filename = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(_VO_DIR, filename), "wb") as fh:
            fh.write(file_bytes)

        audio_url = f"/static/voiceover/{filename}"
        hid = log_history("audio", f"byteplus-tts-{voice}", text[:120])
        update_history(hid, "completed", output_url=audio_url)

        return jsonify({"url": audio_url, "filename": filename, "voice": voice, "format": ext})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voiceover/enhance", methods=["POST"])
def voiceover_enhance():
    d       = request.json or {}
    script  = d.get("script", "").strip()
    style   = d.get("style", "").strip()
    tmpl    = d.get("template", "").strip()

    if not script:
        return jsonify({"error": "Script is required"}), 400
    system = (
        "You are an expert voice over scriptwriter. "
        "Rewrite the script for optimal spoken delivery — add natural rhythm, pacing cues "
        "(commas, ellipses, dashes), emotional inflection, and vivid language. "
        "Keep the same core message. Return ONLY the enhanced script, no explanations."
    )
    context = []
    if tmpl:   context.append(f"Template style: {tmpl}")
    if style:  context.append(f"Style instructions: {style}")
    context.append(f"Original script:\n{script}")

    try:
        enhanced = byteplus_modelark.chat("\n".join(context), system=system, reasoning_effort="low")
        return jsonify({"enhanced": enhanced.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Legacy music Music Generation
# ---------------------------------------------------------------------------

_LYRIA_DIR = os.path.join(os.path.dirname(__file__), "static", "lyria")

@app.route("/api/audio/lyria", methods=["POST"])
def audio_lyria():
    return jsonify({"error": "Lyria music generation is not part of the BytePlus provider migration. Use the existing music tools or add a BytePlus music provider when available."}), 501


# ---------------------------------------------------------------------------
# UGC Studio
# ---------------------------------------------------------------------------

_UGC_AGENTS = {
    "product_review": "ugc-product-review-agent.md",
    "lifestyle_ad":   "ugc-lifestyle-ad-agent.md",
    "unboxing_asmr":  "ugc-unboxing-asmr-agent.md",
}

def _load_ugc_agent(mode):
    """Load UGC agent prompt file at request time (live-reload)."""
    fname = _UGC_AGENTS.get(mode)
    if not fname:
        return None
    path = os.path.join(os.path.dirname(__file__), fname)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None

def _decode_data_uri(uri):
    """Decode a single data-URI to (bytes, mime_type), or (None, None)."""
    import base64 as _b64
    if not uri or "," not in uri:
        return None, None
    header, data = uri.split(",", 1)
    mime = "image/jpeg"
    if "image/png"  in header: mime = "image/png"
    elif "image/webp" in header: mime = "image/webp"
    try:
        return _b64.b64decode(data), mime
    except Exception:
        return None, None


@app.route("/ugc-studio")
def ugc_studio_page():
    return render_template("ugc_studio_v2.html")


@app.route("/ugc-studio-legacy")
def ugc_studio_legacy_page():
    embed = request.args.get("embed") in ("1", "true", "yes")
    return render_template("ugc_studio.html", embed=embed, legacy=True)


@app.route("/api/ugc/render-video", methods=["POST"])
def ugc_render_video():
    """Render a generated UGC variation through the proven Seedance 2.0 I2V path."""
    d = request.json or {}
    prompt = (d.get("prompt") or "").strip()
    images_list = [u for u in (d.get("images_list") or []) if u and str(u).strip()]
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if not images_list:
        return jsonify({"error": "At least one reference image is required"}), 400

    duration = _int(d.get("duration"), 5, "duration")
    if duration < 4 or duration > 15:
        return jsonify({"error": "duration must be between 4 and 15 seconds"}), 400

    aspect_ratio = d.get("aspect_ratio", "9:16")
    quality = d.get("quality", "basic")
    # Resolution picker: 480p / 720p / 1080p → passed to Seedance API as "resolution"
    _res_map = {"480p": "480p", "720p": "720p", "1080p": "1080p"}
    resolution = _res_map.get(str(d.get("resolution", "")).lower())
    try:
        print(f"[/api/ugc/render-video] byteplus seedance | images={len(images_list)} "
              f"aspect_ratio={aspect_ratio!r} duration={duration} quality={quality!r} resolution={resolution!r}")
        rid = _byteplus_video_job(
            prompt,
            image_urls=images_list[:9],
            aspect_ratio=aspect_ratio,
            duration=duration,
            generate_audio=True,
            fast=str(quality).lower() in {"fast", "global-fast", "vip-fast"},
            model_label="KAMOD UGC Render",
            mode="ugc",
            history_page="ugc_studio",
            history_quality=quality,
            resolution=resolution,
        )
        db_insert_gen(rid, prompt, "ugc", "byteplus-seedance-2.0", aspect_ratio, duration, quality)
        return jsonify({"request_id": rid})
    except requests.HTTPError as e:
        response = getattr(e, "response", None)
        return jsonify({
            "error": str(e),
            "stage": "seedance_i2v_submit",
            "model": "byteplus-seedance-2.0",
            "images_count": len(images_list),
        }), (getattr(response, "status_code", None) or 500)
    except Exception as e:
        return jsonify({
            "error": str(e),
            "stage": "seedance_i2v_submit",
            "model": "byteplus-seedance-2.0",
            "images_count": len(images_list),
        }), 500


@app.route("/api/ugc/generate", methods=["POST"])
def ugc_generate():
    import json as _json

    d    = request.json or {}
    mode = d.get("mode", "product_review")

    agent_content = _load_ugc_agent(mode)
    if not agent_content:
        return jsonify({"error": f"Agent file not found for mode: {mode}"}), 500

    # Build structured user context from all inputs
    ctx = []
    ctx.append(f"MODE: {mode}")
    if d.get("product_name"):        ctx.append(f"PRODUCT NAME: {d['product_name']}")
    if d.get("product_description"): ctx.append(f"PRODUCT DESCRIPTION: {d['product_description']}")
    if d.get("user_idea"):           ctx.append(f"USER IDEA (may be Uzbek/Russian/English): {d['user_idea']}")
    if d.get("target_audience"):     ctx.append(f"TARGET AUDIENCE: {d['target_audience']}")
    if d.get("mood"):                ctx.append(f"MOOD / VIBE: {d['mood']}")
    if d.get("duration"):            ctx.append(f"DURATION: {d['duration']} seconds")
    if d.get("aspect_ratio"):        ctx.append(f"ASPECT RATIO: {d['aspect_ratio']}")
    if d.get("speaking_style"):      ctx.append(f"SPEAKING STYLE: {d['speaking_style']}")
    if d.get("product_category"):    ctx.append(f"PRODUCT CATEGORY: {d['product_category']}")
    if d.get("spoken_hook"):         ctx.append(f"SPOKEN HOOK: {d['spoken_hook']}")
    # Mode-specific fields
    if mode == "product_review":
        feats = [f for f in d.get("features", []) if f]
        if feats: ctx.append(f"KEY FEATURES: {' | '.join(feats)}")
        if d.get("review_angle"): ctx.append(f"REVIEW ANGLE: {d['review_angle']}")
    elif mode == "lifestyle_ad":
        if d.get("lifestyle_angle"):  ctx.append(f"LIFESTYLE ANGLE: {d['lifestyle_angle']}")
        if d.get("emotional_angle"):  ctx.append(f"EMOTIONAL ANGLE: {d['emotional_angle']}")
    elif mode == "unboxing_asmr":
        if d.get("reveal_style"):     ctx.append(f"REVEAL STYLE: {d['reveal_style']}")
        if d.get("product_details"):  ctx.append(f"TACTILE / PRODUCT DETAILS: {d['product_details']}")

    # Prompt style
    prompt_style = d.get("prompt_style", "standard")
    if prompt_style == "structured":
        dur = d.get("duration") or 15
        ctx.append(
            f"PROMPT STYLE: structured-timestamp — "
            f"For each variation, write 'seedance_prompt_en' as a timestamped sequence covering the full {dur}s duration. "
            f"Format each segment on its own line: [00:00-00:03] <visual description>. "
            f"Break the video into 3–5 segments with clear visual beats and camera actions. "
            f"Do not include narration or spoken lines inside the timestamp lines — those stay in 'spoken_line' only. "
            f"Example (5s): [00:00-00:02] Close-up of @image1 on a marble surface... [00:02-00:05] Creator picks it up..."
        )

    # Decode images early so reference instructions can be injected into context
    img_bytes, mime = _decode_data_uri(d.get("image") or d.get("product_image"))
    inf_bytes, inf_mime = _decode_data_uri(d.get("influencer_image"))

    # Compute Seedance image slot numbers dynamically so @imageN is always correct
    _slot = 1
    _product_slot = None
    _influencer_slot = None
    if img_bytes:
        _product_slot = _slot
        _slot += 1
    if inf_bytes:
        _influencer_slot = _slot
        _slot += 1
    _has_refs = _product_slot or _influencer_slot

    # Dynamic reference instructions with exact @imageN slot numbers
    if _product_slot:
        ctx.append(
            f"PRODUCT REFERENCE: MANDATORY — the product image is attached as @image{_product_slot}. "
            f"In EVERY Seedance prompt you generate, you MUST write '@image{_product_slot}' explicitly "
            f"(e.g. 'The creator holds @image{_product_slot} and presents it to camera'). "
            f"Place @image{_product_slot} in the first sentence of the prompt. "
            "Also enforce consistency: maintain the same product design, shape, color, packaging, and branding throughout. "
            "Do not substitute or redesign the product. Do not describe a generic product."
        )
    if _influencer_slot:
        ctx.append(
            f"CHARACTER REFERENCE: MANDATORY — the influencer/character image is attached as @image{_influencer_slot}. "
            f"In EVERY Seedance prompt you generate, you MUST write '@image{_influencer_slot}' explicitly "
            f"(e.g. 'Using @image{_influencer_slot} as the character reference, the creator holds ...'). "
            f"Place @image{_influencer_slot} in the first sentence of the prompt. "
            "Also enforce consistency: maintain the same face, identity, hairstyle, skin tone, and appearance throughout. "
            "Do not use generic phrases like 'a woman' or 'a creator' — use the exact uploaded person."
        )
    if _product_slot and _influencer_slot:
        ctx.append(
            f"DUAL REFERENCE RULE: Both @image{_product_slot} (product) and @image{_influencer_slot} (character) "
            "MUST appear in EVERY prompt. Place both in the opening sentence. "
            f"Example structure: 'Using @image{_influencer_slot} as the character reference, "
            f"the creator holds @image{_product_slot} and speaks directly to camera...'"
        )

    print(f"[ugc_generate] mode={mode} product_slot={_product_slot} influencer_slot={_influencer_slot} has_refs={_has_refs}")

    full_prompt = agent_content + "\n\n---\n\nUSER INPUTS:\n" + "\n".join(ctx)
    print(f"[ugc_generate] prompt_len={len(full_prompt)} image_parts={(_slot - 1)}")

    image_urls = []

    # Product image (slot 1 if provided)
    if img_bytes:
        image_urls.append(data_uri_from_bytes(img_bytes, mime))

    # Influencer / character image (slot 2 if both provided, slot 1 if only influencer)
    if inf_bytes:
        image_urls.append(data_uri_from_bytes(inf_bytes, inf_mime))

    # Optional mood image (lifestyle only)
    if mode == "lifestyle_ad":
        mb, mm = _decode_data_uri(d.get("mood_image"))
        if mb:
            image_urls.append(data_uri_from_bytes(mb, mm))

    try:
        raw = byteplus_modelark.chat(full_prompt, image_urls=image_urls, response_json=True, reasoning_effort="medium").strip()
        # Strip markdown code fence if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if "```" in raw:
                raw = raw[:raw.rfind("```")].rstrip()
        result = _json.loads(raw)
    except _json.JSONDecodeError as e:
        return jsonify({"error": f"Model returned invalid JSON: {e}", "raw": raw[:500]}), 500
    except Exception as e:
        return jsonify({"error": f"Generation failed: {e}"}), 500

    # Safety net: the agent is instructed to include @image slots, but make the
    # response render-ready even if the model omits them.
    if _product_slot or _influencer_slot:
        if _product_slot and _influencer_slot:
            ref_sentence = (
                f"Using @image{_influencer_slot} as the influencer/character reference and "
                f"@image{_product_slot} as the product reference, maintain the same uploaded "
                "person and product throughout."
            )
            required_refs = (f"@image{_product_slot}", f"@image{_influencer_slot}")
        elif _product_slot:
            ref_sentence = (
                f"Using @image{_product_slot} as the product reference, maintain the same "
                "uploaded product design, shape, color, and packaging throughout."
            )
            required_refs = (f"@image{_product_slot}",)
        else:
            ref_sentence = (
                f"Using @image{_influencer_slot} as the influencer/character reference, "
                "maintain the same uploaded face, identity, hairstyle, and appearance throughout."
            )
            required_refs = (f"@image{_influencer_slot}",)

        for variation in result.get("variations", []) or []:
            prompt_text = variation.get("seedance_prompt_en") or ""
            if any(ref not in prompt_text for ref in required_refs):
                variation["seedance_prompt_en"] = f"{ref_sentence} {prompt_text}".strip()

        result["reference_slots"] = {
            "product": _product_slot,
            "influencer": _influencer_slot,
        }

    concept = result.get("concept_summary", "")[:300]
    hid = log_history("ugc_studio", f"byteplus-seed-2.0-lite/{mode}", concept)
    update_history(hid, "completed")

    return jsonify(result)


if __name__ == "__main__":
    _debug = os.getenv("FLASK_ENV") == "development"
    app.run(debug=_debug, port=int(os.getenv("PORT", 5001)), threaded=True)
