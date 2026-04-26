# Video Editor Timeline — Design Spec
**Date:** 2026-03-29
**Status:** Approved by user
**Feature:** Visual multi-clip timeline editor for KAMOD AI Flask app

---

## 1. Overview

Replace the current single-clip video editor (`/video-editor`) with a full visual timeline editor. Users upload multiple video clips, arrange them sequentially on a timeline, trim each clip by dragging handles, set transitions between clips, add audio, overlay text, and export a single merged MP4 — all within the existing Flask app.

---

## 2. Layout (approved: Option B)

```
┌─────────────────────────────────────────────────────────┐
│ NAV                                                     │
├──────────────────────────┬──────────────────────────────┤
│  VIDEO PREVIEW           │  OPERATIONS PANEL            │
│  (16:9, switches clip    │  [Audio][Resize][Text]       │
│   with playhead)         │  [Extract][Transitions]      │
│                          │  [controls for active tab]   │
│  [+ Add Clips]           │                              │
│  (drop zone below video) │  [Export Final Video ▼]      │
├──────────────────────────┴──────────────────────────────┤
│ TRANSPORT: [⏮][⏸][⏭]  00:00:04.2 / 00:00:22.5  3 clips  Zoom ──●── │
├─────────────────────────────────────────────────────────┤
│ TIMELINE                                                │
│  ruler  │  0s    2s    4s    6s    8s    10s ...        │
│  VIDEO  │  [clip_01██████][clip_02█████][clip_03████]  │
│  AUDIO  │  [~~~waveform (combined)~~~~~~~~~~~~~~~~~~]  │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Timeline Architecture (approved: Approach 3 — Hybrid)

- **Canvas layer** (z-index 0): draws time ruler, audio waveform, red playhead line. Re-renders via `requestAnimationFrame`.
- **DOM clip layer** (z-index 1, absolutely positioned over canvas): one `<div>` per clip with yellow trim handles on left/right edges. Clips are positioned by computing `timelineStart` as the cumulative sum of all prior clips' trimmed durations.
- **Interaction state machine**: `idle | seeking | trimming-left | trimming-right | dragging-clip`

### 3.1 Clip Data Model

```js
{
  id: string,           // uuid
  file_id: string,      // server upload ID
  ext: string,          // 'mp4', 'mov', etc.
  name: string,
  blobUrl: string,      // local object URL for preview
  originalDuration: number,
  inPoint: number,      // trim start within original (default: 0)
  outPoint: number,     // trim end within original (default: originalDuration)
  thumbnails: Image[],  // extracted at load time via canvas
  waveform: Float32Array, // from Web Audio API
  textLayers: TextLayer[],
  audioOverride: AudioOverride | null,
  transitionIn: Transition | null, // transition before this clip
}
```

### 3.2 Playback Model

Video preview shows one `<video>` element. When playhead is at timeline position `T`:
1. Find which clip contains `T` by summing trimmed durations
2. Set `video.src = clip.blobUrl` (only if clip changed)
3. Set `video.currentTime = T - clip.timelineStart + clip.inPoint`

---

## 4. Operations Panel

Six tabs — operations apply to the **selected clip** unless stated otherwise.

### 4.1 Audio (approved: Level B)

- **Original audio**
  - Volume slider (0–150%, default 100%)
  - Fade In slider (0–5s)
  - Fade Out slider (0–5s)
  - Mute toggle
- **Add audio track** (upload MP3/WAV/AAC)
  - Replace or Mix mode
  - Added track volume slider (0–150%)
- Apply Audio button → calls `/api/video/add-audio` with volume/fade params via FFmpeg filter

FFmpeg filter for volume + fade (applied to the already-trimmed clip stream, so duration starts at 0):
```
volume={vol},afade=t=in:d={fadeIn},afade=t=out:st={trimmedDuration-fadeOut}:d={fadeOut}
```
where `trimmedDuration = outPoint - inPoint`. The fade-out start time is relative to the trimmed clip's start (0), not the original file's outPoint.

### 4.2 Resize (export-time, applies to full composition)

Format picker at export: **16:9** (1920×1080) · **9:16** (1080×1920) · **1:1** (1080×1080) · **4:5** (1080×1350)

FFmpeg uses `scale + pad` to maintain aspect ratio without stretching:
```
scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2:black
```

### 4.3 Text Overlay

**Controls per text layer:**
- Template picker (6 presets, see §4.3.1)
- Text input (textarea, supports Unicode — Russian/Uzbek/English)
- Font: Noto Sans · Noto Serif · Roboto · Oswald
- Size: number input (baseline at 1920×1080)
- Position: Bottom Center · Top Center · Top Left · Center
- Color: White · Yellow · Red · Cyan · Black
- Show from / Show to (seconds, empty = full clip duration)

**Text size scaling:** `effective_px = user_size × (output_width / 1920)`
At export, font_size in the FFmpeg drawtext filter is multiplied by this factor so text fills the same visual proportion regardless of output resolution.

**Multiple layers:** Users can add multiple text layers per clip. Each layer is stored in `clip.textLayers[]` and chained as FFmpeg `-vf` filter steps: `drawtext=...,drawtext=...,drawtext=...`

**Font files:** Server downloads Noto Sans and Noto Serif on first run to `static/fonts/`. Roboto and Oswald similarly. FFmpeg `drawtext` references the font file path directly — no OS font dependency.

#### 4.3.1 Text Templates (6 presets)

| # | Name | Font | Size (baseline) | Position | Style |
|---|------|------|-----------------|----------|-------|
| 1 | Subtitle | Noto Sans | 26px | Bottom Center | Semi-transparent black bg box |
| 2 | Bold Title | Noto Sans Black | 52px | Center | White + purple glow shadow |
| 3 | Lower Third | Noto Sans Bold | 30px (name) + 16px (role) | Bottom Left | Purple accent bar above — applied as **two TextLayers** |
| 4 | Kinetic Caption | Noto Sans Black | 30px | Bottom Center | Yellow (#facc15) highlight block |
| 5 | Minimal Top Bar | Noto Sans | 18px | Top Center | Dark frosted strip |
| 6 | Quote Card | Noto Serif | 22px italic | Center | Full-frame dim overlay |

Templates pre-fill all controls; values remain editable after selection. The **Lower Third** template creates two TextLayers on apply (name layer + role layer) so each has its own size, position offset, and font weight. Both layers are chained as separate `drawtext` filters at export.

### 4.4 Transitions (between clips)

5 options displayed as a strip in the Transitions tab. Assigned per clip-join via a `✦` icon between clips on the timeline. Stored as `clip.transitionIn`.

| Transition | FFmpeg Method | Duration |
|-----------|---------------|----------|
| Fade Black | `fade` to/from black on adjacent clips | 0.5s |
| Cross Dissolve | `xfade=transition=dissolve` | 0.5s |
| Wipe Right | `xfade=transition=wiperight` | 0.5s |
| Zoom In | `xfade=transition=zoomin` | 0.5s |
| Fade White | `fade` to/from white on adjacent clips | 0.5s |

All durations configurable (0.2–2.0s).

**Important:** `xfade` operates on two adjacent input streams simultaneously and **must be applied during the merge step**, not after. The export pipeline builds a single FFmpeg command that interleaves trimmed clip inputs with `xfade` filter chains rather than running a separate post-merge pass.

### 4.5 Extract Audio

Extract audio from selected clip as MP3 or WAV. Calls existing `/api/video/extract-audio`.

---

## 5. Export Flow

On "Export Final Video" click:

1. Show format picker modal (16:9 / 9:16 / 1:1 / 4:5) + aspect ratio preview
2. Server-side pipeline per clip:
   a. **Trim**: `/api/video/trim` with `inPoint` / `outPoint`
   b. **Audio**: `/api/video/add-audio` with volume + fade params
   c. **Text**: `/api/video/add-text` for each text layer (chained)
3. **Merge all clips**: `/api/video/merge` with ordered file_ids
4. **Transitions**: apply `xfade` filters between merged segments
5. **Resize**: apply scale+pad to final output
6. Return download URL

Export is long-running — show a progress indicator with SSE or polling.

---

## 6. New Backend Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/api/video/add-audio-advanced` | POST | Volume + fade in/out + mix/replace |
| `/api/video/add-text-layer` | POST | Text with font file + Unicode + scaling |
| `/api/video/export` | POST | Full pipeline: trim→audio→text→merge+transitions→resize |
| `/api/video/export/status/<job_id>` | GET | Poll export job progress |

All `/api/video/*` routes require `X-API-Key` header (enforced by the existing `check_auth()` before_request hook). The frontend sends the key from `{{ app_secret_key }}` — same pattern as all other pages.

Existing routes (`/api/video/trim`, `/api/video/merge`, `/api/video/resize`, `/api/video/extract-audio`) remain unchanged.

---

## 7. Font Management

```python
FONTS = {
    "noto-sans":        "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSans/hinted/ttf/NotoSans-Regular.ttf",
    "noto-sans-bold":   "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSans/hinted/ttf/NotoSans-Bold.ttf",
    "noto-serif":       "https://github.com/notofonts/latin-greek-cyrillic/raw/main/fonts/NotoSerif/hinted/ttf/NotoSerif-Regular.ttf",
    "roboto":           "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf",
    "oswald":           "https://github.com/googlefonts/OswaldFont/raw/main/fonts/ttf/Oswald-Regular.ttf",
}

def ensure_font(name):
    os.makedirs("static/fonts", exist_ok=True)
    path = f"static/fonts/{name}.ttf"
    if not os.path.exists(path):
        import urllib.request
        urllib.request.urlretrieve(FONTS[name], path)
    return path
```

Note: URLs are verified at implementation time. If a GitHub raw URL changes, update `FONTS` dict. All fonts cover Latin + Cyrillic (Noto) or Latin (Roboto, Oswald). Noto Sans/Serif cover Russian and Uzbek Cyrillic script natively.

---

## 8. File Structure Changes

```
templates/
  video_editor.html        ← REPLACE entirely (new timeline editor)
static/
  video_editor/            ← existing (uploads + processed files)
  fonts/                   ← NEW (downloaded font files)
app.py                     ← add new /api/video/* routes
```

---

## 9. Key Constraints

- All video processing is server-side (FFmpeg subprocess)
- No new Python dependencies beyond what's installed
- Font files downloaded once on first use, cached locally
- `static/video_editor/` files are not auto-deleted (manual cleanup)
- Export job runs in a background thread; client polls `/api/video/export/status/<job_id>` (polling chosen over SSE for simplicity — consistent with the existing `jobs` dict pattern in app.py)
- Canvas and DOM clip positions are computed from the same `pps` (pixels-per-second) value — recalculated on zoom change and window resize via `ResizeObserver`
