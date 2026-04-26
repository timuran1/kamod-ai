# KAMOD AI — Autonomous Video Production Studio

> **Betahacks AI Lab: Seed Agents Challenge — Track 2: AI-Powered Content Automation**

KAMOD AI is an autonomous video production agent that turns a single text prompt into a fully scripted, storyboarded, narrated, and generated video — using only BytePlus Seed models. 

---

## What It Does

Type one sentence. KAMOD AI:

1. **Plans the video** — Seed 2.0 writes a scene-by-scene script with cinematography notes, based on user uploaded video/photo/references.
2. **Builds the storyboard** — Seedream 5.0 generates photorealistic keyframes (1K / 2K / 4K)
3. **Generates the video** — Seedance 2.0 animates each keyframe into cinematic motion video
4. **Adds the voiceover** — Seed-TTS narrates in 8 professional voices, or clones any real voice via BytePlus MegaTTS

---

## BytePlus Models Used

| Model | Role |
|---|---|
| **Seed 2.0** | AI Director — script generation, prompt engineering, content analysis |
| **Seedream 5.0** | Storyboard & keyframe image generation |
| **Seedance 2.0** | Image-to-video and text-to-video generation |
| **Seed-TTS 1.x** | Professional voiceover (8 voices) |
| **BytePlus MegaTTS** | Real-time voice cloning from a reference audio sample |

---

## Architecture

```
User Prompt
    │
    ▼
Seed 2.0 — Scene planning & cinematic prompt engineering
    │
    ├──► Seedream 5.0 — Keyframe / storyboard generation
    │         │
    │         ▼
    │    Seedance 2.0 — Image-to-Video generation
    │
    └──► Seed-TTS — Voiceover synthesis
              │
              └──► MegaTTS — Voice cloning (optional)
                        │
                        ▼
               Final: Video + Audio assembled
```

**Backend:** Python / Flask · BytePlus ModelArk API · Async job polling  
**Frontend:** Vanilla JS / HTML / CSS — no framework overhead

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/kamod-ai.git
cd kamod-ai
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your BytePlus credentials:

| Variable | Where to get it |
|---|---|
| `ARK_API_KEY` | [BytePlus ModelArk Console](https://console.byteplus.com/ark) |
| `BYTEPLUS_VOICE_APP_ID` | [BytePlus Speech Console](https://console.byteplus.com/speech/service) |
| `BYTEPLUS_VOICE_ACCESS_TOKEN` | Same as above |

### 4. Run

```bash
python app.py
```

Open **http://localhost:5001**

---

## Features

- 🎬 **AI Film Studio** — Full storyboard + video pipeline from one prompt
- 🖼️ **Storyboard Generator** — Multi-scene keyframes with 1K/2K/4K resolution
- 🎥 **UGC Studio** — Product ad automation (image-to-video)
- 🎙️ **Voice Over Studio** — 8 BytePlus Seed-TTS voices
- 🔁 **Voice Clone** — Clone any voice in ~2 minutes via BytePlus MegaTTS
- 🤖 **AI Director** — Seed 2.0 multimodal content analysis
- 📊 **History & Analytics** — Full job log with usage tracking

---

## Competition Track

**Track 2: AI-Powered Content Automation**  
Building an "always-on" content engine: Input → Generation → Distribution pipeline for marketing and e-commerce at scale.
