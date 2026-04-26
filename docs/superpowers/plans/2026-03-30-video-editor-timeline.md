# Video Editor Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-clip `/video-editor` page with a full visual multi-clip timeline editor: sequential clips on a hybrid canvas+DOM timeline, per-clip audio/text/transitions, and a one-click export pipeline that uploads the final MP4 to Supabase Storage.

**Architecture:** Hybrid canvas (ruler, waveform, playhead) + DOM clip divs (thumbnails, trim handles, drag-to-reorder) in a single `video_editor.html`. Backend is pure Flask + FFmpeg subprocess — no new Python packages except `supabase` for storage upload. Export runs in a background thread polled by the client.

**Tech Stack:** Python/Flask, FFmpeg 8.1 (already installed), Web Audio API, Canvas 2D API, Supabase Storage REST API.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `templates/video_editor.html` | **Replace entirely** | Full timeline UI — canvas, clip DOM, ops panel, export modal |
| `app.py` | **Modify** | Add 4 new routes: `add-audio-advanced`, `add-text-layer`, `export`, `export/status/<id>` |
| `static/fonts/` | **Create dir** | Font TTF files downloaded on first use |
| `static/video_editor/` | **Existing** | All uploaded + processed temp files |
| `.env` | **User adds vars** | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET` |

---

## Task 1: Font Management Backend

**Files:**
- Modify: `app.py` (add after existing `_VE_DIR` block, ~line 2535)

- [ ] **Step 1: Add font constants and `ensure_font()` to `app.py`**

Add this block immediately after the `_VE_DIR` / `_VE_ALLOWED` definitions:

```python
import urllib.request

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "static", "fonts")

_FONT_URLS = {
    "noto-sans":      "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
    "noto-sans-bold": "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSans/hinted/ttf/NotoSans-Bold.ttf",
    "noto-serif":     "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSerif/hinted/ttf/NotoSerif-Regular.ttf",
    "roboto":         "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf",
    "oswald":         "https://github.com/googlefonts/OswaldFont/raw/main/fonts/ttf/Oswald-Regular.ttf",
}

def ensure_font(name):
    """Download font TTF if not cached. Returns absolute path."""
    os.makedirs(_FONTS_DIR, exist_ok=True)
    path = os.path.join(_FONTS_DIR, f"{name}.ttf")
    if not os.path.exists(path):
        url = _FONT_URLS.get(name)
        if not url:
            raise ValueError(f"Unknown font: {name}")
        urllib.request.urlretrieve(url, path)
    return path
```

- [ ] **Step 2: Create the fonts directory**

```bash
mkdir -p /Users/timurbek/Seedance-2.0-API/static/fonts
```

- [ ] **Step 3: Verify by running a quick test in Python shell**

```bash
cd /Users/timurbek/Seedance-2.0-API
python3 -c "
import sys; sys.path.insert(0, '.')
from app import ensure_font
p = ensure_font('noto-sans')
print('Font saved to:', p)
import os; print('File size:', os.path.getsize(p), 'bytes')
"
```
Expected: prints a path ending in `noto-sans.ttf` and a file size > 100000 bytes.

- [ ] **Step 4: Commit**

```bash
git add app.py static/fonts/
git commit -m "feat(video-editor): add font download system for drawtext"
```

---

## Task 2: Advanced Audio Route

**Files:**
- Modify: `app.py` (add before the `if __name__ == "__main__":` line)

- [ ] **Step 1: Add `/api/video/add-audio-advanced` route**

```python
@app.route("/api/video/add-audio-advanced", methods=["POST"])
def video_add_audio_advanced():
    d = request.json or {}
    try:
        vid_path = _ve_path(d.get("video_id", "").strip(), d.get("video_ext", "mp4").strip())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.exists(vid_path):
        return jsonify({"error": "Video file not found"}), 404

    vol        = max(0.0, min(2.0, float(d.get("volume", 1.0))))
    fade_in    = max(0.0, min(10.0, float(d.get("fade_in", 0))))
    fade_out   = max(0.0, min(10.0, float(d.get("fade_out", 0))))
    mute       = bool(d.get("mute", False))
    mode       = d.get("mode", "replace")   # "replace" | "mix"

    aud_id  = d.get("audio_id", "").strip()
    aud_ext = d.get("audio_ext", "mp3").strip()
    aud_vol = max(0.0, min(2.0, float(d.get("audio_volume", 1.0))))

    out_id = uuid.uuid4().hex
    out    = os.path.join(_VE_DIR, f"{out_id}.mp4")

    # Build audio filter for original track
    if mute:
        orig_filter = "volume=0"
    else:
        parts = [f"volume={vol}"]
        if fade_in  > 0: parts.append(f"afade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            # Get duration of video to compute fade-out start
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", vid_path],
                capture_output=True, text=True)
            try:
                dur = float(probe.stdout.strip())
                parts.append(f"afade=t=out:st={max(0, dur - fade_out)}:d={fade_out}")
            except Exception:
                pass
        orig_filter = ",".join(parts)

    if not aud_id:
        # No replacement track — just apply filters to original audio
        cmd = ["ffmpeg", "-y", "-i", vid_path,
               "-c:v", "copy", "-af", orig_filter, out]
        ok, err = _ve_run(cmd)
    else:
        try:
            aud_path = _ve_path(aud_id, aud_ext)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not os.path.exists(aud_path):
            return jsonify({"error": "Audio file not found"}), 404

        if mode == "mix":
            mix_filter = (
                f"[0:a]{orig_filter}[a0];"
                f"[1:a]volume={aud_vol}[a1];"
                f"[a0][a1]amix=inputs=2:duration=shortest[aout]"
            )
            cmd = ["ffmpeg", "-y", "-i", vid_path, "-i", aud_path,
                   "-filter_complex", mix_filter,
                   "-c:v", "copy", "-map", "0:v:0", "-map", "[aout]",
                   "-shortest", out]
        else:
            # replace
            cmd = ["ffmpeg", "-y", "-i", vid_path, "-i", aud_path,
                   "-c:v", "copy",
                   "-map", "0:v:0", "-map", "1:a:0",
                   "-af", f"volume={aud_vol}", "-shortest", out]
        ok, err = _ve_run(cmd)

    if not ok:
        return jsonify({"error": "Processing failed: " + err[-400:]}), 500
    return jsonify({"url": f"/static/video_editor/{out_id}.mp4",
                    "file_id": out_id, "ext": "mp4"})
```

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/timurbek/Seedance-2.0-API && python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

- [ ] **Step 3: Quick manual test** — start server, upload a video, call the route:

```bash
curl -s -X POST http://localhost:5000/api/video/add-audio-advanced \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $(grep APP_SECRET_KEY .env | cut -d= -f2)" \
  -d '{"video_id":"REPLACE_WITH_REAL_FILE_ID","video_ext":"mp4","volume":0.5,"fade_in":1.0}'
```
Expected: `{"url": "/static/video_editor/....mp4", ...}`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(video-editor): add advanced audio route with volume/fade/mute"
```

---

## Task 3: Text Layer Route

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add `/api/video/add-text-layer` route**

```python
@app.route("/api/video/add-text-layer", methods=["POST"])
def video_add_text_layer():
    d = request.json or {}
    try:
        inp = _ve_path(d.get("file_id", "").strip(), d.get("ext", "mp4").strip())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.exists(inp):
        return jsonify({"error": "File not found"}), 404

    layers = d.get("layers", [])   # list of text layer dicts
    if not layers:
        return jsonify({"error": "No text layers provided"}), 400

    output_width = int(d.get("output_width", 1920))
    scale = output_width / 1920.0

    SAFE_COLORS = {"white", "black", "yellow", "red", "cyan"}
    SAFE_FONTS  = {"noto-sans", "noto-sans-bold", "noto-serif", "roboto", "oswald"}
    POSITIONS = {
        "bottom-center": "x=(w-text_w)/2:y=h-text_h-{pad}",
        "top-center":    "x=(w-text_w)/2:y={pad}",
        "top-left":      "x={pad}:y={pad}",
        "center":        "x=(w-text_w)/2:y=(h-text_h)/2",
    }

    filters = []
    for layer in layers:
        text     = str(layer.get("text", "")).strip()
        if not text:
            continue
        font_key = layer.get("font", "noto-sans") if layer.get("font") in SAFE_FONTS else "noto-sans"
        size     = max(8, min(300, int(float(layer.get("size", 26)) * scale)))
        color    = layer.get("color", "white") if layer.get("color") in SAFE_COLORS else "white"
        pos_key  = layer.get("position", "bottom-center")
        pos_tmpl = POSITIONS.get(pos_key, POSITIONS["bottom-center"])
        pad      = max(20, int(40 * scale))
        pos      = pos_tmpl.replace("{pad}", str(pad))
        t_start  = float(layer.get("from_sec", 0))
        t_end    = layer.get("to_sec")   # None = full duration

        # Escape text for ffmpeg drawtext
        safe = (text.replace("\\", "\\\\")
                    .replace("'",  "\u2019")
                    .replace(":",  "\\:")
                    .replace("[",  "\\[")
                    .replace("]",  "\\]"))

        try:
            font_path = ensure_font(font_key)
        except Exception as e:
            return jsonify({"error": f"Font error: {e}"}), 500

        enable = ""
        if t_end is not None:
            enable = f":enable='between(t,{t_start},{t_end})'"
        elif t_start > 0:
            enable = f":enable='gte(t,{t_start})'"

        filters.append(
            f"drawtext=fontfile='{font_path}':text='{safe}':"
            f"fontsize={size}:fontcolor={color}:"
            f"box=1:boxcolor=black@0.5:boxborderw={max(4,int(8*scale))}:"
            f"{pos}{enable}"
        )

    if not filters:
        return jsonify({"error": "No valid text layers"}), 400

    vf = ",".join(filters)
    out_id = uuid.uuid4().hex
    out    = os.path.join(_VE_DIR, f"{out_id}.mp4")
    cmd    = ["ffmpeg", "-y", "-i", inp, "-vf", vf, "-c:a", "copy", out]
    ok, err = _ve_run(cmd, timeout=180)
    if not ok:
        return jsonify({"error": "Processing failed: " + err[-400:]}), 500
    return jsonify({"url": f"/static/video_editor/{out_id}.mp4",
                    "file_id": out_id, "ext": "mp4"})
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

- [ ] **Step 3: Test with a real video and Cyrillic text**

```bash
curl -s -X POST http://localhost:5000/api/video/add-text-layer \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $(grep APP_SECRET_KEY .env | cut -d= -f2)" \
  -d '{
    "file_id": "REPLACE_WITH_REAL_FILE_ID", "ext": "mp4",
    "output_width": 1920,
    "layers": [{"text": "Привет мир", "font": "noto-sans", "size": 48, "color": "white", "position": "bottom-center"}]
  }'
```
Expected: returns URL. Open the URL in browser — Cyrillic text should appear.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(video-editor): add text layer route with font download + Unicode"
```

---

## Task 4: Supabase Storage Integration

**Files:**
- Modify: `app.py` (add helper function)
- User action: Create `video-exports` bucket in Supabase dashboard, set it to **public**

- [ ] **Step 1: Add Supabase env vars to `.env`**

```bash
# Add to .env:
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
SUPABASE_BUCKET=video-exports
```

- [ ] **Step 2: Create the `video-exports` bucket in Supabase dashboard**

Go to Supabase → Storage → New bucket → name: `video-exports` → check "Public bucket" → Create.

- [ ] **Step 3: Add `upload_to_supabase()` helper to `app.py`**

Add after the `ensure_font()` function:

```python
def upload_to_supabase(local_path, remote_name):
    """Upload a local file to Supabase Storage. Returns public URL or None."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key  = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    bucket       = os.getenv("SUPABASE_BUCKET", "video-exports")

    if not supabase_url or not service_key:
        return None   # Supabase not configured — skip upload silently

    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{remote_name}"
    with open(local_path, "rb") as f:
        resp = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "video/mp4",
                "x-upsert": "true",
            },
            data=f,
            timeout=300,
        )
    if not resp.ok:
        return None
    return f"{supabase_url}/storage/v1/object/public/{bucket}/{remote_name}"
```

- [ ] **Step 4: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

- [ ] **Step 5: Test upload (only if Supabase is configured)**

```bash
echo "test" > /tmp/test.mp4
python3 -c "
import sys; sys.path.insert(0,'.')
import app as a
url = a.upload_to_supabase('/tmp/test.mp4', 'test-upload.mp4')
print('Supabase URL:', url)
"
```
Expected: prints a public Supabase URL, or `None` if env vars not set (that's fine).

- [ ] **Step 6: Commit**

```bash
git add app.py .env.example
git commit -m "feat(video-editor): add Supabase Storage upload helper"
```

---

## Task 5: Export Pipeline Route

**Files:**
- Modify: `app.py`

This is the most complex backend task. The export route:
1. Receives the full clip list with per-clip settings
2. Runs trim + audio + text per clip in sequence
3. Merges all clips with xfade transitions in **one FFmpeg command**
4. Applies resize to final output
5. Uploads to Supabase
6. Stores result in `export_jobs` dict for polling

- [ ] **Step 1: Add `export_jobs` dict and helper near top of app.py (after `jobs = {}`)**

```python
export_jobs = {}   # job_id -> {status, progress, url, supabase_url, error}
```

- [ ] **Step 2: Add the export background worker function**

```python
def _run_export(job_id, clips, output_format, output_width, output_height):
    """Background thread: trim+audio+text each clip, merge with transitions, resize, upload."""
    try:
        export_jobs[job_id]["status"] = "processing"
        processed = []

        total_steps = len(clips) * 3 + 3  # trim+audio+text per clip + merge + resize + upload
        step = 0

        def progress(msg):
            nonlocal step
            step += 1
            export_jobs[job_id]["progress"] = {"step": step, "total": total_steps, "msg": msg}

        for i, clip in enumerate(clips):
            fid = clip["file_id"]
            ext = clip.get("ext", "mp4")
            in_pt  = float(clip.get("in_point", 0))
            out_pt = float(clip.get("out_point", 0)) or None

            # ── Trim ──────────────────────────────────────────────────────────
            progress(f"Trimming clip {i+1}/{len(clips)}")
            try:
                inp = _ve_path(fid, ext)
            except ValueError as e:
                raise Exception(f"Clip {i+1}: {e}")
            trim_id = uuid.uuid4().hex
            trim_out = os.path.join(_VE_DIR, f"{trim_id}.mp4")
            cmd = ["ffmpeg", "-y", "-i", inp, "-ss", str(in_pt)]
            if out_pt:
                cmd += ["-to", str(out_pt)]
            cmd += ["-c:v", "copy", "-c:a", "copy", trim_out]
            ok, err = _ve_run(cmd)
            if not ok:
                cmd2 = ["ffmpeg", "-y", "-i", inp, "-ss", str(in_pt)]
                if out_pt:
                    cmd2 += ["-to", str(out_pt)]
                cmd2 += [trim_out]
                ok, err = _ve_run(cmd2)
            if not ok:
                raise Exception(f"Trim failed for clip {i+1}: {err[-300:]}")
            current_id, current_ext = trim_id, "mp4"

            # ── Audio ─────────────────────────────────────────────────────────
            progress(f"Audio clip {i+1}/{len(clips)}")
            audio = clip.get("audio", {})
            if audio:
                vol      = max(0.0, min(2.0, float(audio.get("volume", 1.0))))
                fade_in  = max(0.0, float(audio.get("fade_in", 0)))
                fade_out = max(0.0, float(audio.get("fade_out", 0)))
                mute     = bool(audio.get("mute", False))

                parts = ["volume=0"] if mute else [f"volume={vol}"]
                if not mute:
                    if fade_in  > 0: parts.append(f"afade=t=in:st=0:d={fade_in}")
                    if fade_out > 0:
                        probe = subprocess.run(
                            ["ffprobe","-v","error","-show_entries","format=duration",
                             "-of","default=noprint_wrappers=1:nokey=1",
                             os.path.join(_VE_DIR, f"{current_id}.{current_ext}")],
                            capture_output=True, text=True)
                        try:
                            dur = float(probe.stdout.strip())
                            parts.append(f"afade=t=out:st={max(0,dur-fade_out)}:d={fade_out}")
                        except Exception:
                            pass

                aud_id  = audio.get("audio_id", "").strip()
                aud_ext_v = audio.get("audio_ext", "mp3").strip()
                aud_vol = max(0.0, min(2.0, float(audio.get("audio_volume", 1.0))))
                mode    = audio.get("mode", "replace")

                a_out_id = uuid.uuid4().hex
                a_out    = os.path.join(_VE_DIR, f"{a_out_id}.mp4")
                src_path = os.path.join(_VE_DIR, f"{current_id}.{current_ext}")

                if aud_id:
                    try:
                        aud_path = _ve_path(aud_id, aud_ext_v)
                    except ValueError:
                        aud_path = None

                    if aud_path and os.path.exists(aud_path) and mode == "mix":
                        mix_f = (f"[0:a]{','.join(parts)}[a0];"
                                 f"[1:a]volume={aud_vol}[a1];"
                                 f"[a0][a1]amix=inputs=2:duration=shortest[aout]")
                        cmd = ["ffmpeg","-y","-i",src_path,"-i",aud_path,
                               "-filter_complex",mix_f,"-c:v","copy",
                               "-map","0:v:0","-map","[aout]","-shortest",a_out]
                    elif aud_path and os.path.exists(aud_path):
                        cmd = ["ffmpeg","-y","-i",src_path,"-i",aud_path,
                               "-c:v","copy","-map","0:v:0","-map","1:a:0",
                               "-af",f"volume={aud_vol}","-shortest",a_out]
                    else:
                        cmd = ["ffmpeg","-y","-i",src_path,"-c:v","copy",
                               "-af",",".join(parts),a_out]
                else:
                    cmd = ["ffmpeg","-y","-i",src_path,"-c:v","copy",
                           "-af",",".join(parts),a_out]

                ok, err = _ve_run(cmd)
                if not ok:
                    raise Exception(f"Audio failed for clip {i+1}: {err[-300:]}")
                current_id, current_ext = a_out_id, "mp4"

            # ── Text layers ───────────────────────────────────────────────────
            progress(f"Text clip {i+1}/{len(clips)}")
            text_layers = clip.get("text_layers", [])
            if text_layers:
                SAFE_COLORS = {"white","black","yellow","red","cyan"}
                SAFE_FONTS  = {"noto-sans","noto-sans-bold","noto-serif","roboto","oswald"}
                POSITIONS   = {
                    "bottom-center": "x=(w-text_w)/2:y=h-text_h-{p}",
                    "top-center":    "x=(w-text_w)/2:y={p}",
                    "top-left":      "x={p}:y={p}",
                    "center":        "x=(w-text_w)/2:y=(h-text_h)/2",
                }
                scale = output_width / 1920.0
                pad   = max(20, int(40 * scale))
                filt_parts = []
                for layer in text_layers:
                    txt = str(layer.get("text","")).strip()
                    if not txt: continue
                    fk   = layer.get("font","noto-sans") if layer.get("font") in SAFE_FONTS else "noto-sans"
                    sz   = max(8, min(300, int(float(layer.get("size",26)) * scale)))
                    col  = layer.get("color","white") if layer.get("color") in SAFE_COLORS else "white"
                    pos  = POSITIONS.get(layer.get("position","bottom-center"), POSITIONS["bottom-center"]).replace("{p}", str(pad))
                    safe = (txt.replace("\\","\\\\").replace("'","\u2019")
                              .replace(":",  "\\:").replace("[","\\[").replace("]","\\]"))
                    try:
                        fp = ensure_font(fk)
                    except Exception:
                        continue
                    t0 = float(layer.get("from_sec",0))
                    t1 = layer.get("to_sec")
                    en = (f":enable='between(t,{t0},{t1})'" if t1 is not None
                          else (f":enable='gte(t,{t0})'" if t0 > 0 else ""))
                    filt_parts.append(
                        f"drawtext=fontfile='{fp}':text='{safe}':"
                        f"fontsize={sz}:fontcolor={col}:"
                        f"box=1:boxcolor=black@0.5:boxborderw={max(4,int(8*scale))}:"
                        f"{pos}{en}")

                if filt_parts:
                    t_out_id = uuid.uuid4().hex
                    t_out    = os.path.join(_VE_DIR, f"{t_out_id}.mp4")
                    src_path = os.path.join(_VE_DIR, f"{current_id}.{current_ext}")
                    cmd = ["ffmpeg","-y","-i",src_path,"-vf",",".join(filt_parts),"-c:a","copy",t_out]
                    ok, err = _ve_run(cmd, timeout=300)
                    if not ok:
                        raise Exception(f"Text failed for clip {i+1}: {err[-300:]}")
                    current_id, current_ext = t_out_id, "mp4"

            processed.append({"id": current_id, "ext": current_ext,
                               "transition": clip.get("transition")})

        # ── Merge with transitions ────────────────────────────────────────────
        progress("Merging clips")
        merge_id = uuid.uuid4().hex
        merge_out = os.path.join(_VE_DIR, f"{merge_id}.mp4")

        if len(processed) == 1:
            # Single clip — just copy
            import shutil
            shutil.copy(os.path.join(_VE_DIR, f"{processed[0]['id']}.{processed[0]['ext']}"), merge_out)
        else:
            paths = [os.path.join(_VE_DIR, f"{p['id']}.{p['ext']}") for p in processed]
            transitions = [p.get("transition") for p in processed]

            # Check if any clip needs xfade
            has_xfade = any(t and t.get("type") not in (None, "none", "fade-black", "fade-white")
                            for t in transitions)

            if has_xfade:
                # Build complex xfade filter graph
                # Get durations via ffprobe
                durations = []
                for path in paths:
                    pr = subprocess.run(
                        ["ffprobe","-v","error","-show_entries","format=duration",
                         "-of","default=noprint_wrappers=1:nokey=1", path],
                        capture_output=True, text=True)
                    try:
                        durations.append(float(pr.stdout.strip()))
                    except Exception:
                        durations.append(5.0)

                inputs = []
                for p in paths:
                    inputs += ["-i", p]

                vlinks = [f"[{i}:v]" for i in range(len(paths))]
                alinks = [f"[{i}:a]" for i in range(len(paths))]
                v_chain, a_chain = vlinks[0], alinks[0]
                offset = 0.0
                filter_parts = []

                for i in range(1, len(paths)):
                    td   = float(transitions[i].get("duration", 0.5)) if transitions[i] else 0.5
                    ttype = (transitions[i].get("type","dissolve") if transitions[i] else "dissolve")
                    offset += durations[i-1] - td

                    v_out = f"[xv{i}]"
                    a_out = f"[xa{i}]"
                    filter_parts.append(
                        f"{v_chain}{vlinks[i]}xfade=transition={ttype}:duration={td}:offset={offset}{v_out}")
                    filter_parts.append(
                        f"{a_chain}{alinks[i]}acrossfade=d={td}{a_out}")
                    v_chain, a_chain = v_out, a_out

                fc = ";".join(filter_parts)
                cmd = inputs + ["-filter_complex", fc,
                                "-map", v_chain, "-map", a_chain, merge_out]
            else:
                # Simple concat (no xfade or fade-black/white)
                # For fade-black/white apply fade filters before concat
                list_path = os.path.join(_VE_DIR, f"{uuid.uuid4().hex}.txt")
                with open(list_path, "w") as lf:
                    for p in paths:
                        lf.write(f"file '{p}'\n")
                cmd = ["ffmpeg","-y","-f","concat","-safe","0","-i",list_path,"-c","copy",merge_out]
                ok, err = _ve_run(cmd)
                os.unlink(list_path)
                if not ok:
                    raise Exception(f"Merge failed: {err[-300:]}")

            if has_xfade:
                ok, err = _ve_run(cmd, timeout=600)
                if not ok:
                    raise Exception(f"Merge+transitions failed: {err[-300:]}")

        # ── Resize ────────────────────────────────────────────────────────────
        progress("Resizing")
        final_id  = uuid.uuid4().hex
        final_out = os.path.join(_VE_DIR, f"{final_id}.mp4")
        vf = (f"scale={output_width}:{output_height}:"
              f"force_original_aspect_ratio=decrease,"
              f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:black")
        cmd = ["ffmpeg","-y","-i",merge_out,"-vf",vf,"-c:a","copy",final_out]
        ok, err = _ve_run(cmd, timeout=600)
        if not ok:
            raise Exception(f"Resize failed: {err[-300:]}")

        # ── Upload to Supabase ─────────────────────────────────────────────────
        progress("Uploading")
        remote_name = f"exports/{job_id}.mp4"
        supabase_url_result = upload_to_supabase(final_out, remote_name)

        export_jobs[job_id].update({
            "status":       "completed",
            "url":          f"/static/video_editor/{final_id}.mp4",
            "supabase_url": supabase_url_result,
            "progress":     {"step": total_steps, "total": total_steps, "msg": "Done"},
        })

    except Exception as e:
        export_jobs[job_id].update({"status": "failed", "error": str(e)})
```

- [ ] **Step 3: Add the two export routes**

```python
@app.route("/api/video/export", methods=["POST"])
def video_export():
    d = request.json or {}
    clips = d.get("clips", [])
    if not clips:
        return jsonify({"error": "No clips provided"}), 400

    FORMATS = {
        "16:9": (1920, 1080), "9:16": (1080, 1920),
        "1:1":  (1080, 1080), "4:5":  (1080, 1350),
    }
    fmt = d.get("format", "16:9")
    if fmt not in FORMATS:
        return jsonify({"error": f"Unknown format: {fmt}"}), 400
    w, h = FORMATS[fmt]

    job_id = uuid.uuid4().hex
    export_jobs[job_id] = {"status": "queued", "progress": {}, "url": None,
                           "supabase_url": None, "error": None}
    os.makedirs(_VE_DIR, exist_ok=True)

    t = threading.Thread(target=_run_export, args=(job_id, clips, fmt, w, h), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/video/export/status/<job_id>", methods=["GET"])
def video_export_status(job_id):
    job = export_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)
```

- [ ] **Step 4: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

- [ ] **Step 5: Smoke test — start server, submit a 2-clip export**

```bash
# Assuming you have two uploaded file_ids from previous tests:
curl -s -X POST http://localhost:5000/api/video/export \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $(grep APP_SECRET_KEY .env | cut -d= -f2)" \
  -d '{
    "format": "16:9",
    "clips": [
      {"file_id": "CLIP1_ID", "ext": "mp4", "in_point": 0, "out_point": 5},
      {"file_id": "CLIP2_ID", "ext": "mp4", "in_point": 0, "out_point": 5,
       "transition": {"type": "dissolve", "duration": 0.5}}
    ]
  }'
# Returns {"job_id": "..."}
# Poll status:
# curl http://localhost:5000/api/video/export/status/JOB_ID \
#   -H "X-API-Key: ..."
```
Expected: status progresses `queued → processing → completed` with a download URL.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat(video-editor): full export pipeline with trim+audio+text+merge+transitions+resize+supabase"
```

---

## Task 6: Frontend — Timeline Canvas (Ruler + Waveform + Playhead)

**Files:**
- Create: `templates/video_editor.html` (replace existing file entirely)

Start with the skeleton + canvas rendering. No clip interaction yet — just ruler, waveform from a loaded video, and playhead.

- [ ] **Step 1: Create the page skeleton with canvas**

Create `templates/video_editor.html` with this structure. The canvas section handles ruler, waveform, and playhead. Clips are a separate DOM layer added in Task 7.

Key CSS layout:
```css
.editor-shell {
  display: grid;
  grid-template-rows: auto auto 1fr;  /* top-area, transport, timeline */
  height: calc(100vh - 120px);        /* full height below nav */
}
.top-area {
  display: grid;
  grid-template-columns: 1fr 320px;
}
.timeline-wrap {
  position: relative;        /* canvas + clips layer stacked */
  overflow-x: auto;
  background: #080810;
}
canvas#tlCanvas {
  position: absolute; top: 0; left: 0;
  pointer-events: none;      /* clicks pass through to clips */
}
#clipLayer {
  position: absolute; top: 0; left: 0;
  width: 100%; height: 100%;
}
```

Canvas constants (JS):
```js
const LABEL_W  = 56;   // px — track label column
const RULER_H  = 26;   // px
const VIDEO_H  = 72;   // px — clip track height
const AUDIO_H  = 44;   // px
const TL_H     = RULER_H + VIDEO_H + AUDIO_H;
```

`renderCanvas()` function — called by `requestAnimationFrame`:
```js
function renderCanvas() {
  const canvas = document.getElementById('tlCanvas');
  const ctx    = canvas.getContext('2d');
  const W = canvas.offsetWidth;
  canvas.width  = W;
  canvas.height = TL_H;

  const vid = document.getElementById('vidPlayer');
  const dur = (vid && vid.duration && !isNaN(vid.duration)) ? vid.duration : 0;
  if (!dur) {
    ctx.fillStyle = '#080810'; ctx.fillRect(0, 0, W, TL_H);
    ctx.fillStyle = '#333'; ctx.font = '12px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('Upload clips to see the timeline', W/2, TL_H/2);
    requestAnimationFrame(renderCanvas);
    return;
  }

  // pixels-per-second — expose to global for clip layer to use
  window.TL_PPS    = (W - LABEL_W) / (getTotalDuration() / state.zoom);
  window.TL_SCROLL = state.scrollSeconds;

  const tx = t => LABEL_W + (t - state.scrollSeconds) * window.TL_PPS;

  // Clear
  ctx.fillStyle = '#080810'; ctx.fillRect(0, 0, W, TL_H);

  // ── Ruler ──────────────────────────────────────────────────────
  ctx.fillStyle = '#0d0d16'; ctx.fillRect(0, 0, W, RULER_H);
  const pps = window.TL_PPS;
  let tickInt = pps > 120 ? 0.5 : pps > 50 ? 1 : pps > 15 ? 2 : pps > 6 ? 5 : 10;
  const startT = Math.floor(state.scrollSeconds / tickInt) * tickInt;
  ctx.font = '9px monospace'; ctx.textAlign = 'center';
  for (let t = startT; t <= getTotalDuration() + tickInt; t += tickInt) {
    const x = tx(t);
    if (x < LABEL_W - 1 || x > W + 1) continue;
    const major = Math.round(t / tickInt) % 5 === 0;
    ctx.strokeStyle = major ? '#3a3a5e' : '#1e1e2e';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, RULER_H - (major ? 12 : 5)); ctx.lineTo(x, RULER_H); ctx.stroke();
    if (major) {
      ctx.fillStyle = '#555';
      const label = t >= 60 ? `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}` : `${t.toFixed(0)}s`;
      ctx.fillText(label, x, RULER_H - 14);
    }
  }

  // ── Video track background + label ───────────────────────────────
  ctx.fillStyle = '#0e0e18'; ctx.fillRect(0, RULER_H, W, VIDEO_H);
  ctx.fillStyle = '#111120'; ctx.fillRect(0, RULER_H, LABEL_W, VIDEO_H);
  ctx.fillStyle = '#6d5fd6'; ctx.font = 'bold 9px sans-serif'; ctx.textAlign = 'center';
  ctx.fillText('VIDEO', LABEL_W/2, RULER_H + VIDEO_H/2 + 3);

  // ── Audio track + waveform ────────────────────────────────────────
  const AY = RULER_H + VIDEO_H;
  ctx.fillStyle = '#07070f'; ctx.fillRect(0, AY, W, AUDIO_H);
  ctx.fillStyle = '#0e0e18'; ctx.fillRect(0, AY, LABEL_W, AUDIO_H);
  ctx.fillStyle = '#2a7a4a'; ctx.font = 'bold 9px sans-serif';
  ctx.fillText('AUDIO', LABEL_W/2, AY + AUDIO_H/2 + 3);

  if (state.combinedWaveform.length > 0) {
    const totalDur = getTotalDuration();
    const mid = AY + AUDIO_H / 2;
    const maxAmp = (AUDIO_H / 2) - 4;
    state.combinedWaveform.forEach((v, i) => {
      const t = (i / state.combinedWaveform.length) * totalDur;
      const x = tx(t);
      if (x < LABEL_W || x > W) return;
      const h = v * maxAmp;
      ctx.fillStyle = '#4ade80';
      ctx.fillRect(x, mid - h, Math.max(1, window.TL_PPS * totalDur / state.combinedWaveform.length - 1), h * 2);
    });
  }

  // ── Track separator ──────────────────────────────────────────────
  ctx.strokeStyle = '#1e1e2e'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(LABEL_W, 0); ctx.lineTo(LABEL_W, TL_H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, RULER_H); ctx.lineTo(W, RULER_H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, AY); ctx.lineTo(W, AY); ctx.stroke();

  // ── Playhead ─────────────────────────────────────────────────────
  const phX = tx(state.playheadTime);
  if (phX >= LABEL_W && phX <= W) {
    ctx.strokeStyle = '#f87171'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(phX, 0); ctx.lineTo(phX, TL_H); ctx.stroke();
    ctx.fillStyle = '#f87171';
    ctx.beginPath(); ctx.moveTo(phX-6,0); ctx.lineTo(phX+6,0); ctx.lineTo(phX,12); ctx.closePath(); ctx.fill();
  }

  requestAnimationFrame(renderCanvas);
}
```

- [ ] **Step 2: Add state object and `getTotalDuration()` helper**

```js
const state = {
  clips: [],            // [{id, file_id, ext, name, blobUrl, originalDuration,
                        //   inPoint, outPoint, thumbnails, waveform,
                        //   textLayers, audio, transition}]
  playheadTime: 0,
  zoom: 1.0,            // 1 = whole composition fits in view
  scrollSeconds: 0,
  combinedWaveform: [], // merged Float32Array of all clips
  dragging: null,       // null | {type:'seek'|'trim-left'|'trim-right'|'clip', clipIdx, startX, startTime}
  selectedClip: null,   // index into state.clips
  isPlaying: false,
};

function getTotalDuration() {
  return state.clips.reduce((s, c) => s + (c.outPoint - c.inPoint), 0) || 0;
}

function getClipTimelineStart(idx) {
  let t = 0;
  for (let i = 0; i < idx; i++) t += state.clips[i].outPoint - state.clips[i].inPoint;
  return t;
}
```

- [ ] **Step 3: Wire canvas to timeline container with `ResizeObserver`**

```js
const tlWrap = document.getElementById('tlWrap');
const canvas = document.getElementById('tlCanvas');
new ResizeObserver(() => {
  canvas.width  = tlWrap.offsetWidth;
  canvas.height = TL_H;
}).observe(tlWrap);
requestAnimationFrame(renderCanvas);
```

- [ ] **Step 4: Start the server and open `/video-editor`**

```bash
python3 app.py
# Open http://localhost:5000/video-editor
```
Expected: Dark page with canvas timeline showing "Upload clips to see the timeline".

- [ ] **Step 5: Commit**

```bash
git add templates/video_editor.html
git commit -m "feat(video-editor): canvas timeline skeleton with ruler, waveform, playhead"
```

---

## Task 7: Frontend — Clip DOM Layer + Drag Interactions

**Files:**
- Modify: `templates/video_editor.html`

- [ ] **Step 1: Add `renderClips()` function**

Renders one `<div>` per clip, positioned absolutely over the canvas VIDEO track row using `window.TL_PPS`:

```js
function renderClips() {
  const layer = document.getElementById('clipLayer');
  layer.innerHTML = '';
  state.clips.forEach((clip, i) => {
    const tlStart = getClipTimelineStart(i);
    const dur     = clip.outPoint - clip.inPoint;
    const x       = LABEL_W + (tlStart - state.scrollSeconds) * (window.TL_PPS || 0);
    const w       = dur * (window.TL_PPS || 0);
    if (x + w < LABEL_W || x > (layer.offsetWidth || 900)) return;

    const div = document.createElement('div');
    div.className = 'clip-div' + (state.selectedClip === i ? ' selected' : '');
    div.style.cssText = `left:${x}px;top:${RULER_H + 4}px;width:${Math.max(20,w)}px;height:${VIDEO_H - 8}px`;
    div.dataset.idx = i;

    // Thumbnail strip
    const thumbStrip = document.createElement('div');
    thumbStrip.className = 'thumb-strip';
    clip.thumbnails.forEach(img => {
      const th = document.createElement('div');
      th.className = 'thumb';
      th.style.backgroundImage = `url(${img.src})`;
      thumbStrip.appendChild(th);
    });
    div.appendChild(thumbStrip);

    // Label
    const label = document.createElement('span');
    label.className = 'clip-label';
    label.textContent = clip.name;
    div.appendChild(label);

    // Trim handles
    const lh = document.createElement('div'); lh.className = 'trim-handle left';  lh.dataset.side = 'left';
    const rh = document.createElement('div'); rh.className = 'trim-handle right'; rh.dataset.side = 'right';
    div.appendChild(lh); div.appendChild(rh);

    // Transition icon (between this and previous clip)
    if (i > 0) {
      const icon = document.createElement('div');
      icon.className = 'transition-icon';
      icon.title = clip.transition ? clip.transition.type : 'No transition';
      icon.textContent = clip.transition ? '✦' : '+';
      icon.dataset.idx = i;
      icon.onclick = (e) => { e.stopPropagation(); openTransitionPicker(i); };
      layer.appendChild(icon);
      // Position left of this clip
      icon.style.cssText = `left:${x - 14}px;top:${RULER_H + VIDEO_H/2 - 10}px`;
    }

    layer.appendChild(div);
  });
}
```

- [ ] **Step 2: Add CSS for clip divs**

```css
.clip-div {
  position: absolute; border-radius: 5px; overflow: hidden;
  background: linear-gradient(135deg, #2d2560, #1d3d70);
  border: 1px solid #4a3fa0; cursor: grab; user-select: none;
  box-sizing: border-box;
}
.clip-div.selected { border-color: #a78bfa; box-shadow: 0 0 0 1px #a78bfa; }
.thumb-strip { position: absolute; inset: 0; display: flex; gap: 1px; overflow: hidden; opacity: 0.45; }
.thumb { flex-shrink: 0; width: 64px; height: 100%; background-size: cover; background-position: center; }
.clip-label { position: relative; z-index: 1; font-size: 9px; color: #ddd; padding: 0 8px; pointer-events: none; text-shadow: 0 1px 4px #000; }
.trim-handle { position: absolute; top: 0; bottom: 0; width: 8px; background: #facc15; z-index: 2; cursor: ew-resize; border-radius: 3px 0 0 3px; }
.trim-handle.left  { left: 0; border-radius: 3px 0 0 3px; }
.trim-handle.right { right: 0; border-radius: 0 3px 3px 0; }
.transition-icon { position: absolute; width: 20px; height: 20px; border-radius: 50%; background: #1a1a2e; border: 1px dashed #3a3a5e; display: flex; align-items: center; justify-content: center; font-size: 9px; color: #a78bfa; cursor: pointer; z-index: 5; }
```

- [ ] **Step 3: Add mouse event handlers on `#clipLayer`**

```js
const clipLayer = document.getElementById('clipLayer');

clipLayer.addEventListener('mousedown', e => {
  const clipDiv = e.target.closest('.clip-div');
  const handle  = e.target.closest('.trim-handle');
  const idx     = clipDiv ? parseInt(clipDiv.dataset.idx) : -1;

  if (handle && clipDiv) {
    // Start trim drag
    state.dragging = { type: handle.dataset.side === 'left' ? 'trim-left' : 'trim-right',
                       clipIdx: idx, startX: e.clientX };
    e.preventDefault();
  } else if (clipDiv) {
    state.selectedClip = idx;
    state.dragging = { type: 'clip', clipIdx: idx, startX: e.clientX,
                       origOrder: [...state.clips.map((_,i)=>i)] };
    renderOpsPanel();
    e.preventDefault();
  } else {
    // Click on background/ruler → seek
    const rect = clipLayer.getBoundingClientRect();
    const x    = e.clientX - rect.left;
    const t    = state.scrollSeconds + (x - LABEL_W) / (window.TL_PPS || 1);
    seekTo(Math.max(0, Math.min(getTotalDuration(), t)));
    state.dragging = { type: 'seek', startX: e.clientX };
  }
});

window.addEventListener('mousemove', e => {
  if (!state.dragging) return;
  const dx  = e.clientX - state.dragging.startX;
  const dt  = dx / (window.TL_PPS || 1);

  if (state.dragging.type === 'trim-left') {
    const clip = state.clips[state.dragging.clipIdx];
    clip.inPoint = Math.max(0, Math.min(clip.outPoint - 0.1, clip.inPoint + dt));
    state.dragging.startX = e.clientX;
    buildCombinedWaveform();
    renderClips();
  } else if (state.dragging.type === 'trim-right') {
    const clip = state.clips[state.dragging.clipIdx];
    clip.outPoint = Math.max(clip.inPoint + 0.1, Math.min(clip.originalDuration, clip.outPoint + dt));
    state.dragging.startX = e.clientX;
    buildCombinedWaveform();
    renderClips();
  } else if (state.dragging.type === 'seek') {
    const newT = state.playheadTime + dt;
    seekTo(Math.max(0, Math.min(getTotalDuration(), newT)));
    state.dragging.startX = e.clientX;
  } else if (state.dragging.type === 'clip') {
    // Reorder by drag threshold
    if (Math.abs(dx) > 30) {
      const dir = dx > 0 ? 1 : -1;
      const i = state.dragging.clipIdx;
      const j = i + dir;
      if (j >= 0 && j < state.clips.length) {
        [state.clips[i], state.clips[j]] = [state.clips[j], state.clips[i]];
        state.dragging.clipIdx = j;
        state.dragging.startX  = e.clientX;
        buildCombinedWaveform();
        renderClips();
      }
    }
  }
});

window.addEventListener('mouseup', () => { state.dragging = null; });
```

- [ ] **Step 4: Add thumbnail extraction function**

```js
async function extractThumbnails(video, count = 10) {
  const offscreen = document.createElement('canvas');
  offscreen.width = 80; offscreen.height = 45;
  const ctx = offscreen.getContext('2d');
  const saved = video.currentTime;
  const thumbs = [];
  for (let i = 0; i < count; i++) {
    const t = (i / Math.max(1, count - 1)) * video.duration;
    await new Promise(res => {
      const onSeeked = () => { video.removeEventListener('seeked', onSeeked); res(); };
      video.addEventListener('seeked', onSeeked);
      video.currentTime = t;
      setTimeout(res, 1500); // fallback
    });
    ctx.drawImage(video, 0, 0, 80, 45);
    const img = new Image();
    img.src = offscreen.toDataURL('image/jpeg', 0.5);
    thumbs.push(img);
  }
  video.currentTime = saved;
  return thumbs;
}
```

- [ ] **Step 5: Add waveform analysis**

```js
async function analyzeWaveform(blobUrl, bins = 150) {
  try {
    const ctx  = new AudioContext();
    const resp = await fetch(blobUrl);
    const buf  = await resp.arrayBuffer();
    const audio = await ctx.decodeAudioData(buf);
    const data  = audio.getChannelData(0);
    const block = Math.floor(data.length / bins);
    const wave  = [];
    for (let i = 0; i < bins; i++) {
      let sum = 0;
      for (let j = 0; j < block; j++) sum += Math.abs(data[i * block + j]);
      wave.push(sum / block);
    }
    const max = Math.max(...wave, 0.001);
    return wave.map(v => v / max);
  } catch { return []; }
}

function buildCombinedWaveform() {
  const all = [];
  for (const clip of state.clips) {
    if (clip.waveform && clip.waveform.length) {
      const start = Math.floor((clip.inPoint / clip.originalDuration) * clip.waveform.length);
      const end   = Math.floor((clip.outPoint / clip.originalDuration) * clip.waveform.length);
      all.push(...clip.waveform.slice(start, end));
    }
  }
  state.combinedWaveform = all;
}
```

- [ ] **Step 6: Test in browser — upload two videos, verify clips appear on timeline with handles**

Open `http://localhost:5000/video-editor`, upload 2 clips. Expected:
- Both clip divs appear on the VIDEO row
- Drag a yellow handle → clip shrinks/grows
- Drag clip center → clips swap positions
- Click background → playhead moves

- [ ] **Step 7: Commit**

```bash
git add templates/video_editor.html
git commit -m "feat(video-editor): clip DOM layer with thumbnails, trim handles, drag-to-reorder"
```

---

## Task 8: Frontend — Video Preview + Transport Controls

**Files:**
- Modify: `templates/video_editor.html`

- [ ] **Step 1: Add `seekTo()` and multi-clip playback logic**

```js
function seekTo(timelineT) {
  state.playheadTime = timelineT;
  let elapsed = 0;
  for (const clip of state.clips) {
    const dur = clip.outPoint - clip.inPoint;
    if (timelineT <= elapsed + dur) {
      const offsetInClip = timelineT - elapsed + clip.inPoint;
      const vid = document.getElementById('vidPlayer');
      if (vid.src !== clip.blobUrl) {
        vid.src = clip.blobUrl;
        vid.load();
      }
      vid.currentTime = offsetInClip;
      document.getElementById('clipIndicator').textContent = clip.name;
      return;
    }
    elapsed += dur;
  }
}

function playPause() {
  if (state.isPlaying) {
    state.isPlaying = false;
    document.getElementById('vidPlayer').pause();
    document.getElementById('btnPlay').textContent = '▶';
  } else {
    state.isPlaying = true;
    document.getElementById('btnPlay').textContent = '⏸';
    animatePlayback();
  }
}

let _lastRafTs = null;
function animatePlayback(ts) {
  if (!state.isPlaying) return;
  if (_lastRafTs != null) {
    const delta = (ts - _lastRafTs) / 1000;
    const newT  = state.playheadTime + delta;
    if (newT >= getTotalDuration()) {
      state.isPlaying = false;
      document.getElementById('btnPlay').textContent = '▶';
      state.playheadTime = 0;
      seekTo(0);
    } else {
      state.playheadTime = newT;
      seekTo(newT);
    }
  }
  _lastRafTs = ts;
  requestAnimationFrame(animatePlayback);
}
requestAnimationFrame(ts => { _lastRafTs = ts; });

// Update timecode display each frame
setInterval(() => {
  const total = getTotalDuration();
  const t = state.playheadTime;
  const fmt = s => `${String(Math.floor(s/60)).padStart(2,'0')}:${String(Math.floor(s%60)).padStart(2,'0')}.${String(Math.floor((s%1)*10)).padStart(1,'0')}`;
  document.getElementById('timecodeDisplay').textContent = `${fmt(t)} / ${fmt(total)}`;
  document.getElementById('clipCount').textContent = `${state.clips.length} clip${state.clips.length !== 1 ? 's' : ''}`;
}, 100);
```

- [ ] **Step 2: Add transport HTML**

```html
<div class="transport-bar">
  <div class="tbtn" onclick="seekTo(0)">⏮</div>
  <div class="tbtn play" id="btnPlay" onclick="playPause()">▶</div>
  <div class="tbtn" onclick="seekTo(getTotalDuration())">⏭</div>
  <span id="timecodeDisplay" class="timecode-display">00:00.0 / 00:00.0</span>
  <span id="clipCount" class="clip-count">0 clips</span>
  <div class="zoom-wrap">
    <span class="zoom-lbl">Zoom</span>
    <input type="range" min="0.5" max="8" step="0.5" value="1"
           oninput="state.zoom=parseFloat(this.value); renderClips()">
  </div>
</div>
```

- [ ] **Step 3: Wire keyboard shortcuts**

```js
document.addEventListener('keydown', e => {
  if (['INPUT','TEXTAREA'].includes(e.target.tagName)) return;
  if (e.code === 'Space') { e.preventDefault(); playPause(); }
  if (e.code === 'ArrowLeft')  seekTo(Math.max(0, state.playheadTime - 1));
  if (e.code === 'ArrowRight') seekTo(Math.min(getTotalDuration(), state.playheadTime + 1));
});
```

- [ ] **Step 4: Test playback — upload clips, press Space to play**

Expected: red playhead moves across the timeline, video preview shows each clip as playhead enters it.

- [ ] **Step 5: Commit**

```bash
git add templates/video_editor.html
git commit -m "feat(video-editor): multi-clip playback, transport controls, keyboard shortcuts"
```

---

## Task 9: Frontend — Operations Panel (Audio, Text, Transitions, Resize)

**Files:**
- Modify: `templates/video_editor.html`

- [ ] **Step 1: Add ops panel HTML with 5 tabs**

Tabs: `Audio | Text | Transitions | Resize | Extract`

Each tab panel uses the selected clip (`state.clips[state.selectedClip]`).

**Audio tab** (level B — volume slider, fade in/out, mute, add track upload, replace/mix, track volume):
```html
<div class="ops-panel" id="panel-audio">
  <p class="ops-hint">Applies to selected clip</p>

  <div class="ops-section">
    <label>Original Volume</label>
    <div class="slider-row">
      <input type="range" min="0" max="150" value="100" id="audioVol"
             oninput="document.getElementById('audioVolVal').textContent=this.value+'%'">
      <span id="audioVolVal">100%</span>
    </div>
    <div class="slider-row">
      <label>Fade In</label>
      <input type="range" min="0" max="50" value="0" step="1" id="fadeIn"
             oninput="document.getElementById('fadeInVal').textContent=(this.value/10).toFixed(1)+'s'">
      <span id="fadeInVal">0.0s</span>
    </div>
    <div class="slider-row">
      <label>Fade Out</label>
      <input type="range" min="0" max="50" value="0" step="1" id="fadeOut"
             oninput="document.getElementById('fadeOutVal').textContent=(this.value/10).toFixed(1)+'s'">
      <span id="fadeOutVal">0.0s</span>
    </div>
    <label class="toggle-row">
      <input type="checkbox" id="audioMute"> Mute original audio
    </label>
  </div>

  <div class="ops-section">
    <label>Add Audio Track</label>
    <div class="mini-upload" id="audioTrackZone" onclick="document.getElementById('audioTrackInput').click()">
      <input type="file" id="audioTrackInput" accept="audio/*" style="display:none">
      <span id="audioTrackName">Drop MP3 / WAV / AAC</span>
    </div>
    <div class="radio-row" id="audioModeGroup">
      <div class="rbtn active" id="rbtn-replace" onclick="setAudioMode('replace')">Replace</div>
      <div class="rbtn"        id="rbtn-mix"     onclick="setAudioMode('mix')">Mix</div>
    </div>
    <div class="slider-row">
      <label>Track Volume</label>
      <input type="range" min="0" max="150" value="100" id="trackVol"
             oninput="document.getElementById('trackVolVal').textContent=this.value+'%'">
      <span id="trackVolVal">100%</span>
    </div>
  </div>

  <button class="btn-op" id="btnApplyAudio" onclick="applyAudio()">Apply Audio</button>
  <div class="op-error" id="errAudio"></div>
</div>
```

- [ ] **Step 2: Add Text tab with 6 template buttons**

```html
<div class="ops-panel hidden" id="panel-text">
  <div class="template-chips">
    <div class="tpl-chip" onclick="applyTextTemplate('subtitle')">Subtitle</div>
    <div class="tpl-chip" onclick="applyTextTemplate('title')">Bold Title</div>
    <div class="tpl-chip" onclick="applyTextTemplate('lower-third')">Lower Third</div>
    <div class="tpl-chip" onclick="applyTextTemplate('kinetic')">Kinetic</div>
    <div class="tpl-chip" onclick="applyTextTemplate('topbar')">Top Bar</div>
    <div class="tpl-chip" onclick="applyTextTemplate('quote')">Quote</div>
  </div>
  <textarea id="textInput" placeholder="Type text here... (Russian, Uzbek, English all supported)"></textarea>
  <div class="form-2col">
    <div>
      <label>Font</label>
      <select id="textFont">
        <option value="noto-sans">Noto Sans (Cyrillic)</option>
        <option value="noto-serif">Noto Serif</option>
        <option value="roboto">Roboto</option>
        <option value="oswald">Oswald</option>
      </select>
    </div>
    <div>
      <label>Size</label>
      <input type="number" id="textSize" value="26" min="8" max="200">
    </div>
  </div>
  <div class="form-2col">
    <div>
      <label>Position</label>
      <select id="textPos">
        <option value="bottom-center">Bottom Center</option>
        <option value="top-center">Top Center</option>
        <option value="top-left">Top Left</option>
        <option value="center">Center</option>
      </select>
    </div>
    <div>
      <label>Color</label>
      <div class="color-swatches" id="textColorSwatches">
        <div class="swatch active" style="background:#fff"    data-c="white"  onclick="setTextColor(this)"></div>
        <div class="swatch"        style="background:#facc15" data-c="yellow" onclick="setTextColor(this)"></div>
        <div class="swatch"        style="background:#f87171" data-c="red"    onclick="setTextColor(this)"></div>
        <div class="swatch"        style="background:#34d399" data-c="cyan"   onclick="setTextColor(this)"></div>
        <div class="swatch"        style="background:#000;border:1px solid #333" data-c="black" onclick="setTextColor(this)"></div>
      </div>
    </div>
  </div>
  <div class="form-2col">
    <div><label>Show from (s)</label><input type="number" id="textFrom" value="0" min="0" step="0.5"></div>
    <div><label>Show to (s)</label><input type="number" id="textTo" placeholder="end" min="0" step="0.5"></div>
  </div>
  <button class="btn-op" onclick="addTextLayer()">Add Text Layer</button>
  <div id="textLayersList"></div>
  <div class="op-error" id="errText"></div>
</div>
```

Template presets JS:
```js
const TEXT_TEMPLATES = {
  'subtitle':     { text:'Subtitle text', font:'noto-sans',      size:26, position:'bottom-center', color:'white'  },
  'title':        { text:'EPISODE ONE',   font:'noto-sans-bold', size:52, position:'center',        color:'white'  },
  'lower-third':  { text:'Name Here',     font:'noto-sans-bold', size:30, position:'bottom-center', color:'white',
                    extra: { text:'Role / Title', font:'noto-sans', size:16, position:'bottom-center', color:'white' } },
  'kinetic':      { text:'CAPTION HERE',  font:'noto-sans-bold', size:30, position:'bottom-center', color:'black'  },
  'topbar':       { text:'KAMOD AI',      font:'noto-sans',      size:18, position:'top-center',    color:'white'  },
  'quote':        { text:'Your quote here', font:'noto-serif',   size:22, position:'center',        color:'white'  },
};

function applyTextTemplate(key) {
  const tpl = TEXT_TEMPLATES[key];
  if (!tpl) return;
  document.getElementById('textInput').value    = tpl.text;
  document.getElementById('textFont').value     = tpl.font;
  document.getElementById('textSize').value     = tpl.size;
  document.getElementById('textPos').value      = tpl.position;
  document.querySelectorAll('#textColorSwatches .swatch').forEach(s => {
    s.classList.toggle('active', s.dataset.c === tpl.color);
  });
}
```

- [ ] **Step 3: Add Transitions tab**

```html
<div class="ops-panel hidden" id="panel-transitions">
  <p class="ops-hint">Select transition before the selected clip (clip 2+)</p>
  <div class="transition-grid" id="transitionGrid">
    <!-- rendered by renderTransitionPicker() -->
  </div>
  <div class="form-row">
    <label>Duration</label>
    <div class="slider-row">
      <input type="range" min="2" max="20" value="5" id="transitionDur"
             oninput="document.getElementById('transDurVal').textContent=(this.value/10).toFixed(1)+'s'">
      <span id="transDurVal">0.5s</span>
    </div>
  </div>
  <button class="btn-op" onclick="applyTransition()">Set Transition</button>
</div>
```

Transition types and their xfade names:
```js
const TRANSITIONS = [
  { key:'none',      label:'None',          xfade:null           },
  { key:'dissolve',  label:'Cross Dissolve', xfade:'dissolve'    },
  { key:'wiperight', label:'Wipe Right',     xfade:'wiperight'   },
  { key:'zoomin',    label:'Zoom In',        xfade:'zoomin'      },
  { key:'fade',      label:'Fade Black',     xfade:'fade'        },
  { key:'fadewhite', label:'Fade White',     xfade:'fadewhite'   },
];
```

- [ ] **Step 4: Add `applyAudio()`, `addTextLayer()`, `applyTransition()` JS functions**

All three follow the same pattern: read values from the panel, store in `state.clips[state.selectedClip]`, update the clip's stored settings, re-render the ops panel to show the change.

- [ ] **Step 5: Test all three tabs in browser**

- Set volume to 50% on a clip → verify stored in `state.clips[0].audio.volume`
- Apply "Subtitle" template → verify text input fills in
- Set "Cross Dissolve" on clip 2 → verify `state.clips[1].transition.type === 'dissolve'`

- [ ] **Step 6: Commit**

```bash
git add templates/video_editor.html
git commit -m "feat(video-editor): ops panel — audio/text/transitions tabs with template presets"
```

---

## Task 10: Frontend — Export Modal + Full Wiring

**Files:**
- Modify: `templates/video_editor.html`

- [ ] **Step 1: Add Export modal HTML**

```html
<div id="exportModal" class="modal hidden">
  <div class="modal-box">
    <h3>Export Final Video</h3>
    <p class="modal-subtitle">Choose output format — text sizes scale automatically</p>
    <div class="format-chips" id="formatChips">
      <div class="fmt-chip active" data-fmt="16:9"  onclick="setFmt(this,'16:9')">
        <strong>16:9</strong><span>YouTube · 1920×1080</span>
      </div>
      <div class="fmt-chip" data-fmt="9:16"  onclick="setFmt(this,'9:16')">
        <strong>9:16</strong><span>TikTok · Reels · 1080×1920</span>
      </div>
      <div class="fmt-chip" data-fmt="1:1"   onclick="setFmt(this,'1:1')">
        <strong>1:1</strong><span>Instagram · 1080×1080</span>
      </div>
      <div class="fmt-chip" data-fmt="4:5"   onclick="setFmt(this,'4:5')">
        <strong>4:5</strong><span>Feed Portrait · 1080×1350</span>
      </div>
    </div>
    <div id="exportProgress" style="display:none">
      <div class="progress-bar-wrap"><div class="progress-bar" id="progressBar"></div></div>
      <p class="progress-msg" id="progressMsg">Starting...</p>
    </div>
    <div id="exportResult" style="display:none">
      <a id="dlLink"       class="btn-download" href="#" download>⬇ Download MP4</a>
      <a id="supabaseLink" class="btn-supabase"  href="#" target="_blank" style="display:none">☁ Open in Supabase</a>
    </div>
    <div id="exportError" class="op-error"></div>
    <div class="modal-footer">
      <button onclick="closeExportModal()" class="btn-cancel">Cancel</button>
      <button onclick="startExport()"      class="btn-op" id="btnStartExport">Export</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add `startExport()` function**

```js
let selectedFmt = '16:9';
function setFmt(el, fmt) {
  selectedFmt = fmt;
  document.querySelectorAll('.fmt-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
}

async function startExport() {
  if (state.clips.length === 0) return;
  document.getElementById('btnStartExport').disabled = true;
  document.getElementById('exportProgress').style.display = 'block';
  document.getElementById('exportResult').style.display   = 'none';
  document.getElementById('exportError').textContent      = '';

  const payload = {
    format: selectedFmt,
    clips: state.clips.map(clip => ({
      file_id:     clip.file_id,
      ext:         clip.ext,
      in_point:    clip.inPoint,
      out_point:   clip.outPoint,
      audio:       clip.audio || {},
      text_layers: clip.textLayers || [],
      transition:  clip.transition || null,
    }))
  };

  try {
    const r = await fetch('/api/video/export', {
      method:'POST', headers: HEADERS,
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    pollExport(d.job_id);
  } catch(e) {
    document.getElementById('exportError').textContent = e.message;
    document.getElementById('btnStartExport').disabled = false;
  }
}

function pollExport(jobId) {
  const interval = setInterval(async () => {
    try {
      const r = await fetch(`/api/video/export/status/${jobId}`, { headers: HEADERS });
      const d = await r.json();

      if (d.progress && d.progress.total) {
        const pct = Math.round((d.progress.step / d.progress.total) * 100);
        document.getElementById('progressBar').style.width = pct + '%';
        document.getElementById('progressMsg').textContent  = d.progress.msg || '';
      }

      if (d.status === 'completed') {
        clearInterval(interval);
        document.getElementById('exportProgress').style.display = 'none';
        document.getElementById('exportResult').style.display   = 'block';
        const dlLink = document.getElementById('dlLink');
        dlLink.href     = d.url;
        dlLink.download = `kamod_export_${selectedFmt.replace(':','x')}.mp4`;
        if (d.supabase_url) {
          const sl = document.getElementById('supabaseLink');
          sl.href  = d.supabase_url;
          sl.style.display = 'block';
        }
        document.getElementById('btnStartExport').disabled = false;
      } else if (d.status === 'failed') {
        clearInterval(interval);
        document.getElementById('exportError').textContent = d.error || 'Export failed';
        document.getElementById('btnStartExport').disabled = false;
      }
    } catch(e) { /* retry next poll */ }
  }, 2000);
}
```

- [ ] **Step 3: Wire the "Add Clips" upload zone**

```js
async function handleClipUpload(file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/api/video/upload', { method:'POST', body: fd, headers:{'X-API-Key': API_KEY} });
  const d = await r.json();
  if (d.error) { alert('Upload failed: ' + d.error); return; }

  // Load video to get duration + thumbnails + waveform
  const blobUrl = URL.createObjectURL(file);
  const vid     = document.createElement('video');
  vid.src       = blobUrl;
  await new Promise(res => { vid.onloadedmetadata = res; });

  const thumbnails = await extractThumbnails(vid);
  const waveform   = await analyzeWaveform(blobUrl);

  state.clips.push({
    id: d.file_id, file_id: d.file_id, ext: d.ext, name: file.name,
    blobUrl, originalDuration: vid.duration,
    inPoint: 0, outPoint: vid.duration,
    thumbnails, waveform,
    textLayers: [], audio: {}, transition: null,
  });

  buildCombinedWaveform();
  renderClips();

  // Switch preview to first clip if it's the first upload
  if (state.clips.length === 1) seekTo(0);
}
```

- [ ] **Step 4: Final integration check — run full user flow**

1. `python3 app.py` → open `http://localhost:5000/video-editor`
2. Upload 2-3 video clips → verify thumbnails appear on timeline
3. Drag yellow handle to trim a clip → verify clip shrinks
4. Press Space → playback moves across clips
5. Open Audio tab → set volume 50%, fade in 1s → click Apply Audio
6. Open Text tab → click "Subtitle" template → type "Тест / Test" → click Add Text Layer
7. Open Transitions tab → set "Cross Dissolve" on clip 2 → click Set Transition
8. Click Export → choose 9:16 → Export → wait for progress → click Download
9. Open downloaded MP4 — verify: trimmed clips, faded audio, Cyrillic subtitle, dissolve transition, 9:16 aspect ratio

- [ ] **Step 5: Update nav in video_editor.html to mark Editor as active** (already done in previous work, verify)

```bash
grep 'class="active"' templates/video_editor.html
# Should show: <a href="/video-editor" class="active">Editor</a>
```

- [ ] **Step 6: Final commit**

```bash
git add templates/video_editor.html app.py static/fonts/ static/video_editor/
git commit -m "feat(video-editor): complete visual timeline editor with export pipeline and Supabase upload"
```

---

## Supabase Setup Checklist (User Action Required)

Before testing the export + upload:
- [ ] Go to Supabase dashboard → Storage → New bucket → name: `video-exports` → **Public bucket** ✓
- [ ] Copy your Project URL: `https://YOUR_PROJECT.supabase.co`
- [ ] Copy your Service Role Key (Settings → API → service_role)
- [ ] Add to `.env`:
  ```
  SUPABASE_URL=https://YOUR_PROJECT.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...
  SUPABASE_BUCKET=video-exports
  ```
- [ ] Restart `python3 app.py`

If Supabase is not configured, export still works — it just skips the upload and returns a local download URL only.

---

## Known FFmpeg Requirements

| Feature | FFmpeg filter | Notes |
|---------|--------------|-------|
| Volume + fade | `volume`, `afade` | Supported since FFmpeg 2.x |
| Text overlay | `drawtext` | Requires `--enable-libfreetype` — verify with `ffmpeg -filters \| grep drawtext` |
| xfade transitions | `xfade` | Requires FFmpeg 4.3+ — your version is 8.1 ✓ |
| Resize + pad | `scale`, `pad` | Always supported |

Verify drawtext is available:
```bash
ffmpeg -filters 2>/dev/null | grep drawtext
# Should print: ... drawtext ...
```
