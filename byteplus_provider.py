import base64
import io
import json
import os
import time
import uuid
import wave
from typing import Any, Dict, Iterable, List, Optional

import requests


def _pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


ARK_DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
ARK_CHAT_MODEL = "seed-2-0-lite-260228"
ARK_IMAGE_MODEL = "seedream-5-0-lite-260128"
ARK_VIDEO_MODEL = "dreamina-seedance-2-0-260128"
ARK_VIDEO_FAST_MODEL = "dreamina-seedance-2-0-fast-260128"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _json_error(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(data, dict):
        detail = data.get("error") or data.get("message") or data.get("detail") or data
        if isinstance(detail, dict):
            return detail.get("message") or detail.get("error") or json.dumps(detail)
        return str(detail)
    return json.dumps(data)


def _data_uri(raw: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"


def data_uri_from_bytes(raw: bytes, mime_type: str) -> str:
    return _data_uri(raw, mime_type)


def data_uri_from_existing(uri: str, default_mime: str = "image/jpeg") -> str:
    if uri.startswith("data:"):
        return uri
    return f"data:{default_mime};base64,{uri.split(',', 1)[-1]}"


def normalize_status(status: Optional[str]) -> str:
    value = (status or "").lower()
    if value in {"succeeded", "success", "completed", "done"}:
        return "completed"
    if value in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    return "processing"


def extract_output_url(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("url", "video_url", "image_url", "audio_url", "output", "video", "image", "audio"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            nested = extract_output_url(value)
            if nested:
                return nested
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                nested = extract_output_url(first)
                if nested:
                    return nested
    outputs = payload.get("outputs")
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return extract_output_url(first)
    # BytePlus image API returns {"data": [{"url": "..."}]}
    data_field = payload.get("data")
    if isinstance(data_field, list) and data_field:
        first = data_field[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            nested = extract_output_url(first)
            if nested:
                return nested
    # BytePlus video API returns {"content": {"video_url": "..."}} (flat dict)
    content = payload.get("content")
    if isinstance(content, dict):
        nested = extract_output_url(content)
        if nested:
            return nested
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                nested = extract_output_url(item)
                if nested:
                    return nested
    return None


class BytePlusModelArk:
    def __init__(self) -> None:
        self.base_url = _env("ARK_BASE_URL", ARK_DEFAULT_BASE_URL).rstrip("/")
        self.api_key = _env("ARK_API_KEY")
        self.chat_model = _env("ARK_CHAT_MODEL", ARK_CHAT_MODEL)
        self.image_model = _env("ARK_IMAGE_MODEL", ARK_IMAGE_MODEL)
        self.video_model = _env("ARK_VIDEO_MODEL", ARK_VIDEO_MODEL)
        self.video_fast_model = _env("ARK_VIDEO_FAST_MODEL", ARK_VIDEO_FAST_MODEL)

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("ARK_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=kwargs.pop("timeout", 120),
            **kwargs,
        )
        if not response.ok:
            raise requests.HTTPError(f"{response.status_code}: {_json_error(response)}", response=response)
        return response.json()

    def chat(
        self,
        text: str,
        *,
        system: Optional[str] = None,
        image_urls: Optional[Iterable[str]] = None,
        video_urls: Optional[Iterable[str]] = None,
        reasoning_effort: str = "medium",
        response_json: bool = False,
    ) -> str:
        content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
        for url in image_urls or []:
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        for url in video_urls or []:
            if url:
                content.append({"type": "video_url", "video_url": {"url": url, "fps": 1}})
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        payload: Dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "reasoning_effort": reasoning_effort if reasoning_effort in {"minimal", "low", "medium", "high"} else "medium",
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}
        data = self._request("POST", "/chat/completions", json=payload)
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content_value = message.get("content")
            if isinstance(content_value, str):
                return content_value.strip()
            if isinstance(content_value, list):
                text_parts = [p.get("text", "") for p in content_value if isinstance(p, dict)]
                return "\n".join(t for t in text_parts if t).strip()
        return str(data)

    def chat_json(self, text: str, *, system: Optional[str] = None, image_urls: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        raw = self.chat(text, system=system, image_urls=image_urls, response_json=True)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw[: raw.rfind("```")] if "```" in raw else raw
        return json.loads(raw.strip())

    def create_video_task(
        self,
        prompt: str,
        *,
        image_urls: Optional[Iterable[str]] = None,
        video_urls: Optional[Iterable[str]] = None,
        audio_urls: Optional[Iterable[str]] = None,
        ratio: str = "16:9",
        duration: int = 5,
        generate_audio: bool = True,
        fast: bool = False,
        watermark: bool = False,
        resolution: Optional[str] = None,
    ) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for url in (image_urls or []):
            # Always use reference_image — mixing first_frame with reference_image
            # causes a 400 "cannot mix first/last frame with reference media" error.
            content.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
        for url in video_urls or []:
            content.append({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"})
        for url in audio_urls or []:
            content.append({"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"})
        payload: Dict[str, Any] = {
            "model": self.video_fast_model if fast else self.video_model,
            "content": content,
            "generate_audio": bool(generate_audio),
            "ratio": ratio,
            "duration": duration,
            "watermark": bool(watermark),
        }
        if resolution:
            payload["resolution"] = resolution
        data = self._request("POST", "/contents/generations/tasks", json=payload)
        task_id = data.get("id") or data.get("task_id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise ValueError(f"No task id in ModelArk response: {data}")
        return {"request_id": task_id, "raw": data, "model": payload["model"]}

    def get_task(self, task_id: str) -> Dict[str, Any]:
        data = self._request("GET", f"/contents/generations/tasks/{task_id}", timeout=60)
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        status = normalize_status(inner.get("status"))
        return {
            "status": status,
            "url": extract_output_url(inner),
            "error": inner.get("error") or inner.get("message"),
            "raw": inner,
        }

    def wait_for_task(self, task_id: str, *, timeout: int = 1800, interval: int = 10) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout:
            result = self.get_task(task_id)
            if result["status"] == "completed":
                return result
            if result["status"] == "failed":
                raise RuntimeError(result.get("error") or "BytePlus task failed")
            time.sleep(interval)
        raise TimeoutError("Timed out waiting for BytePlus task completion")

    def create_image_task(
        self,
        prompt: str,
        *,
        image_urls: Optional[Iterable[str]] = None,
        ratio: str = "1:1",
        size: str = "1K",
        response_format: str = "url",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.image_model,
            "prompt": prompt,
            "response_format": response_format,
            "size": size,
            "ratio": ratio,
            "watermark": False,
        }
        refs = [u for u in (image_urls or []) if u]
        if refs:
            payload["image"] = refs[0] if len(refs) == 1 else refs
        data = self._request("POST", "/images/generations", json=payload)
        url = extract_output_url(data)
        task_id = data.get("id") or data.get("task_id") or f"img-{uuid.uuid4().hex}"
        return {"request_id": task_id, "url": url, "raw": data, "model": self.image_model}


class BytePlusVoice:
    """BytePlus Seed-TTS 2.0 via bidirectional WebSocket.

    Protocol reverse-engineered from the volcengine_audio PyPI SDK (v0.1.x).

    WebSocket URL  : wss://voice.ap-southeast-1.bytepluses.com/api/v3/tts/bidirection
    Auth header    : Authorization: Bearer;{access_token}
    Appid          : embedded in StartSession payload under 'app.appid'

    Binary frame layout (every client→server and server→client message):
        Byte 0 : 0x11  (protocol_version=1 in upper 4 bits, header_size=1 in lower 4 bits)
        Byte 1 : (message_type << 4) | 0x04   (0x04 = CARRY_EVENT_ID flag)
                 client sends 0x14 (FULL_CLIENT_REQUEST + CARRY_EVENT_ID)
        Byte 2 : (serialization << 4) | compression
                 0x10 = JSON + no compression   0x00 = RAW  + no compression (audio)
        Byte 3 : 0x00  (reserved)

        Bytes  4– 7 : event number    (uint32, big-endian)
        Bytes  8–11 : session_id_len  (uint32, big-endian)  ← 0 if no session
        Bytes 12–(12+sid_len-1) : session_id UTF-8 bytes
        Bytes (12+sid_len)–(12+sid_len+3) : payload_len (uint32, big-endian)
        Bytes (12+sid_len+4)+ : payload (JSON or raw PCM)

    Event numbers (client→server):
        1   StartConnection   2   FinishConnection
        100 StartSession      102 FinishSession
        200 TaskRequest

    Event numbers (server→client):
        50  ConnectionStarted   150 SessionStarted
        152 SessionFinished     153 SessionFailed
        350 TTSSentenceStart    351 TTSSentenceEnd
        352 TTSResponse (audio) 359 TTSEnded
        15  ERROR_INFORMATION
    """

    # ── Protocol constants (from volcengine_audio SDK) ──────────────────────
    _HDR           = bytes([0x11, 0x14, 0x10, 0x00])   # JSON, no compression
    _HDR_RAW       = bytes([0x11, 0x14, 0x00, 0x00])   # RAW,  no compression

    _EV_START_CONN    = 1
    _EV_FINISH_CONN   = 2
    _EV_START_SESSION = 100
    _EV_FINISH_SESSION= 102
    _EV_TASK_REQUEST  = 200

    _EV_CONN_STARTED  = 50
    _EV_SESS_STARTED  = 150
    _EV_SESS_FINISHED = 152
    _EV_SESS_FAILED   = 153
    _EV_TTS_RESPONSE  = 352   # audio chunk
    _EV_TTS_ENDED     = 359   # all audio done
    _EV_ERROR         = 15

    _MSG_AUDIO_ONLY_RESP = 0xB   # server audio-only response
    _MSG_FULL_RESP       = 0x9   # server full response (JSON)
    _MSG_ERROR           = 0xF   # server error

    _TTS2_WS_URL = "wss://voice.ap-southeast-1.bytepluses.com/api/v3/tts/bidirection"

    def __init__(self) -> None:
        self.app_id  = _env("BYTEPLUS_VOICE_APP_ID")
        self.token   = _env("BYTEPLUS_VOICE_ACCESS_TOKEN")
        self.cluster = _env("BYTEPLUS_VOICE_CLUSTER", "volcano_tts")
        self.tts_url = _env("BYTEPLUS_TTS_HTTP_URL", "https://openspeech.byteoversea.com/api/v1/tts")
        self.default_voice = _env("BYTEPLUS_TTS_DEFAULT_VOICE", "BV001_streaming")

    def _require(self) -> None:
        if not self.app_id or not self.token:
            raise RuntimeError("BYTEPLUS_VOICE_APP_ID and BYTEPLUS_VOICE_ACCESS_TOKEN are required")

    # ── Binary frame helpers (exact volcengine_audio protocol) ──────────────

    @staticmethod
    def _build_frame(
        event: int,
        session_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> bytes:
        """Build a TTS 2.0 binary frame with event + optional session_id + JSON payload."""
        import struct as _st
        frame = bytearray(BytePlusVoice._HDR)
        frame.extend(_st.pack(">I", event))
        if session_id:
            sid_b = session_id.encode()
            frame.extend(_st.pack(">I", len(sid_b)))
            frame.extend(sid_b)
        meta = json.dumps(payload or {}).encode()
        frame.extend(_st.pack(">I", len(meta)))
        frame.extend(meta)
        return bytes(frame)

    @staticmethod
    def _parse_response(data: bytes) -> Dict[str, Any]:
        """Parse a server binary frame.

        Returns dict: {msg_type, event, ser_method, session_id, payload_bytes}
        """
        import struct as _st
        if len(data) < 8:
            return {"msg_type": -1, "event": -1, "ser_method": 0,
                    "session_id": "", "payload_bytes": b""}
        msg_type   = (data[1] >> 4) & 0xF
        ser_method = (data[2] >> 4) & 0xF
        event_num  = _st.unpack(">I", data[4:8])[0]

        # ERROR frames (msg_type=0xF) have NO session_id section:
        # layout is HDR(4) + error_code(4) + payload(rest)
        # Treating bytes 8-11 as sid_len would corrupt the parse → empty message.
        if msg_type == 0xF:
            return {
                "msg_type":      msg_type,
                "event":         event_num,
                "ser_method":    ser_method,
                "session_id":    "",
                "payload_bytes": data[8:],   # payload starts right after error_code
            }

        # All other frames: optional session_id then payload
        sid_len    = _st.unpack(">I", data[8:12])[0] if len(data) >= 12 else 0
        sid_end    = 12 + sid_len
        session_id = data[12:sid_end].decode(errors="replace") if sid_len else ""
        payload_bytes = data[sid_end + 4:] if len(data) > sid_end + 4 else b""
        return {
            "msg_type":      msg_type,
            "event":         event_num,
            "ser_method":    ser_method,
            "session_id":    session_id,
            "payload_bytes": payload_bytes,
        }

    # ── TTS 2.0 main ────────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: str = "English",
        audio_format: str = "mp3",
    ) -> bytes:
        """Synthesize via Seed-TTS 2.0 WebSocket; falls back to HTTP TTS if websockets absent."""
        self._require()
        try:
            import websockets.sync.client  # noqa: F401
            return self._synthesize_tts2(text, voice=voice)
        except ImportError:
            return self._synthesize_http_legacy(
                text, voice=voice, language=language, audio_format=audio_format
            )

    def _synthesize_tts2(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        resource_id: str = "seed-tts-1.0",
    ) -> bytes:
        """Seed-TTS 2.0 WebSocket implementation. Returns WAV bytes (24 kHz / 16-bit / mono)."""
        import websockets.sync.client as _wsc

        voice_type = voice or self.default_voice
        session_id = uuid.uuid4().hex
        connect_id = uuid.uuid4().hex

        # Auth: per BytePlus TTS 2.0 WebSocket docs
        # X-Api-App-Key  = APP ID (legacy auth, still supported)
        # X-Api-Access-Key = Access Token
        # X-Api-Resource-Id = model resource identifier (REQUIRED)
        # X-Api-Connect-Id  = unique connection trace ID
        headers = {
            "X-Api-App-Key":     self.app_id,
            "X-Api-Access-Key":  self.token,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Connect-Id":  connect_id,
        }

        audio_chunks: List[bytes] = []
        done = False

        with _wsc.connect(
            self._TTS2_WS_URL,
            additional_headers=headers,
            open_timeout=30,
            close_timeout=10,
        ) as ws:
            # ── 1. StartConnection ──────────────────────────────────────────
            ws.send(self._build_frame(self._EV_START_CONN))

            # ── 2. StartSession (voice config; no app block per docs) ───────
            ws.send(self._build_frame(
                self._EV_START_SESSION,
                session_id=session_id,
                payload={
                    "event":     self._EV_START_SESSION,
                    "namespace": "BidirectionalTTS",
                    "req_params": {
                        "speaker": voice_type,
                        "audio_params": {
                            "format":      "pcm",
                            "sample_rate": 24000,
                        },
                    },
                },
            ))

            # ── 3. TaskRequest ──────────────────────────────────────────────
            ws.send(self._build_frame(
                self._EV_TASK_REQUEST,
                session_id=session_id,
                payload={
                    "event":     self._EV_TASK_REQUEST,
                    "namespace": "BidirectionalTTS",
                    "req_params": {
                        "text":    text,
                        "speaker": voice_type,
                        "audio_params": {
                            "format":      "pcm",
                            "sample_rate": 24000,
                        },
                    },
                },
            ))

            # ── 4. FinishSession ────────────────────────────────────────────
            ws.send(self._build_frame(
                self._EV_FINISH_SESSION,
                session_id=session_id,
                payload={"event": self._EV_FINISH_SESSION, "namespace": "BidirectionalTTS"},
            ))

            # ── 5. Collect server responses ─────────────────────────────────
            for raw in ws:
                if not isinstance(raw, bytes):
                    continue  # ignore text frames
                frame = self._parse_response(raw)
                ev    = frame["event"]
                mt    = frame["msg_type"]
                ser   = frame["ser_method"]

                if ev == self._EV_ERROR or mt == self._MSG_ERROR:
                    try:
                        err = json.loads(frame["payload_bytes"])
                    except Exception:
                        err = {"raw": frame["payload_bytes"].decode(errors="replace")}
                    code = err.get("status_code", ev)
                    msg  = err.get("message") or err.get("raw") or str(err)
                    raise RuntimeError(f"TTS 2.0 error [{code}]: {msg or '(no message from server)'}")

                if ev == self._EV_SESS_FAILED:
                    try:
                        err = json.loads(frame["payload_bytes"])
                    except Exception:
                        err = {"raw": frame["payload_bytes"].decode(errors="replace")}
                    code = err.get("status_code", 153)
                    msg  = err.get("message") or err.get("raw") or str(err)
                    raise RuntimeError(f"TTS 2.0 session failed [{code}]: {msg or '(no message from server)'}")

                # Audio chunk: event=352, ser_method=0 (RAW), msg_type=0xB
                if ev == self._EV_TTS_RESPONSE and ser == 0:
                    audio_chunks.append(frame["payload_bytes"])

                # Session fully finished — exit loop
                if ev in (self._EV_SESS_FINISHED, self._EV_TTS_ENDED):
                    done = True
                    break

        if not audio_chunks:
            raise ValueError(
                "Seed-TTS 2.0 returned no audio. "
                "Check APP_ID, access token, voice ID, and that the seed-tts-2.0 model is enabled."
            )

        pcm_data = b"".join(audio_chunks)
        return _pcm_to_wav_bytes(pcm_data, sample_rate=24000)

    def _synthesize_http_legacy(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        language: str = "English",
        audio_format: str = "mp3",
    ) -> bytes:
        """Legacy BytePlus TTS 1.x HTTP fallback (used when websockets is not installed)."""
        payload = {
            "app": {"appid": self.app_id, "token": self.token, "cluster": self.cluster},
            "user": {"uid": "kamod-local"},
            "audio": {
                "voice_type": voice or self.default_voice,
                "encoding": audio_format if audio_format in {"mp3", "ogg_opus", "pcm"} else "mp3",
                "rate": 24000,
            },
            "request": {
                "reqid": uuid.uuid4().hex,
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "language": language,
            },
        }
        response = requests.post(
            self.tts_url,
            headers={"Authorization": f"Bearer;{self.token}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        if not response.ok:
            raise requests.HTTPError(f"{response.status_code}: {_json_error(response)}", response=response)
        data = response.json()
        audio = data.get("data") or data.get("audio") or data.get("result")
        if not audio:
            raise ValueError(f"No audio data in BytePlus Voice response: {data}")
        if isinstance(audio, dict):
            audio = audio.get("audio") or audio.get("data")
        if isinstance(audio, str):
            return base64.b64decode(audio)
        raise ValueError(f"Unexpected audio payload: {data}")

    # ── BytePlus MegaTTS Voice Replication API ──────────────────────────────

    _CLONE_BASE = "https://voice.ap-southeast-1.bytepluses.com"

    def _clone_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer;{self.token}",
            "Resource-Id":   "volc.megatts.voiceclone",
            "Content-Type":  "application/json",
        }

    def upload_voice(
        self,
        audio_url: str,
        speaker_id: str,
        *,
        model_type: int = 0,
        need_noise_reduction: bool = False,
        need_volume_normalization: bool = False,
    ) -> Dict[str, Any]:
        """Submit reference audio for voice cloning (BytePlus MegaTTS).

        model_type: 0=Mega (default), 1=ICL 1.0, 2=DiT Standard, 3=DiT Restoration
        Returns raw API response dict.
        """
        self._require()
        payload: Dict[str, Any] = {
            "appid":      self.app_id,
            "speaker_id": speaker_id,
            "audios": [{"audio_url": audio_url}],
            "source":     2,
            "model_type": model_type,
        }
        if need_noise_reduction:
            payload["need_noise_reduction"] = True
        if need_volume_normalization:
            payload["need_volume_normalization"] = True
        resp = requests.post(
            f"{self._CLONE_BASE}/api/v1/mega_tts/audio/upload",
            headers=self._clone_headers(),
            json=payload,
            timeout=120,
        )
        if not resp.ok:
            raise requests.HTTPError(f"{resp.status_code}: {_json_error(resp)}", response=resp)
        return resp.json()

    def get_clone_status(self, speaker_id: str) -> Dict[str, Any]:
        """Poll voice clone status (BytePlus MegaTTS).

        Returned status codes: 0=NotFound, 1=Training, 2=Success, 3=Failed, 4=Active
        """
        self._require()
        resp = requests.post(
            f"{self._CLONE_BASE}/api/v1/mega_tts/status",
            headers=self._clone_headers(),
            json={"appid": self.app_id, "speaker_id": speaker_id},
            timeout=30,
        )
        if not resp.ok:
            raise requests.HTTPError(f"{resp.status_code}: {_json_error(resp)}", response=resp)
        return resp.json()

    def synthesize_with_clone(self, text: str, speaker_id: str) -> bytes:
        """Synthesize text using a cloned voice (uses volc.megatts.default resource)."""
        self._require()
        try:
            import websockets.sync.client as _wsc  # noqa: F401
            return self._synthesize_tts2(text, voice=speaker_id, resource_id="volc.megatts.default")
        except ImportError:
            return self._synthesize_http_legacy(text, voice=speaker_id)
