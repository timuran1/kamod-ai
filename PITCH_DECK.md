# KAMOD AI — Pitch Deck
### Betahacks AI Lab: Seed Agents Challenge

---

## SLIDE 1 — The Hook
**Title:** `One Prompt.  Complete Video.`

**Visual:** Full-screen dark background. Show a single text input box with the prompt:
> *"A cinematic product ad for a luxury electric car at sunset."*
Arrow pointing down to: a finished storyboard grid + video thumbnail + audio waveform.

**Spoken (15 sec):**
> *"Today, creating a professional video takes a team, a budget, and days of work.
> KAMOD AI does it in one prompt — script, visuals, video, and voice — fully automated."*

---

## SLIDE 2 — The Demo Result
**Title:** `From this → to this, in under 5 minutes`

**Visual:** Side-by-side split screen
- LEFT: plain text prompt
- RIGHT: 4-panel storyboard + video player + audio controls

**Key stats (large numbers):**
```
  1          4           1
prompt    scenes      voiceover
typed    generated    synthesized
```

**Spoken (10 sec):**
> *"One input. Seed 2.0 writes the script. Seedream 5.0 builds the storyboard.
> Seedance 2.0 generates the video. Seed-TTS adds the voice. Zero manual steps."*

---

## SLIDE 3 — How It Works (Architecture)
**Title:** `The Seed Agent Pipeline`

**Visual:** Clean horizontal flow diagram

```
[Text Prompt]
     │
     ▼
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│  SEED 2.0   │────▶│ SEEDREAM 5.0 │────▶│ SEEDANCE 2.0  │────▶│  SEED-TTS  │
│  AI Director│     │  Storyboard  │     │  Video Gen    │     │  Voiceover │
│  Scriptwriter│    │  Keyframes   │     │  I2V / T2V    │     │  + Clone   │
└─────────────┘     └──────────────┘     └───────────────┘     └────────────┘
                                                                       │
                                                                       ▼
                                                              [Final Video + Audio]
```

**Bottom note:** `100% BytePlus Seed models · No Sora · No Runway · No external video tools`

**Spoken (20 sec):**
> *"Every layer uses a BytePlus Seed model.
> Seed 2.0 acts as the AI Director — it reads intent and engineers the prompts.
> Seedream generates photorealistic keyframes.
> Seedance animates them into video.
> Seed-TTS narrates — or clones any real voice in under 3 minutes.
> The whole stack runs on a lightweight Python backend. No GPU servers required."*

---

## SLIDE 4 — The Market
**Title:** `Every Brand Needs Video. Almost None Can Afford It.`

**Visual:** Three vertical columns

```
┌────────────────┐   ┌────────────────┐   ┌────────────────┐
│  E-COMMERCE    │   │  REAL ESTATE   │   │  EDUCATION     │
│                │   │                │   │                │
│ 26M+ sellers   │   │ 2M+ agents     │   │ 200M+ creators │
│ need product   │   │ need property  │   │ need course    │
│ ads daily      │   │ walkthroughs   │   │ videos fast    │
│                │   │                │   │                │
│ Cost today:    │   │ Cost today:    │   │ Cost today:    │
│ $500–$5,000    │   │ $300–$2,000    │   │ $200–$1,000    │
│ per video      │   │ per listing    │   │ per lesson     │
│                │   │                │   │                │
│ With KAMOD AI: │   │ With KAMOD AI: │   │ With KAMOD AI: │
│   < $1         │   │   < $1         │   │   < $1         │
└────────────────┘   └────────────────┘   └────────────────┘
```

**Spoken (15 sec):**
> *"The market for automated video creation is enormous.
> Every e-commerce seller, every real estate agent, every online educator
> needs professional video — but can't afford agencies or production teams.
> KAMOD AI reduces the cost per video from thousands of dollars to under a dollar."*

---

## SLIDE 5 — Vision & Ask
**Title:** `This Is Version 1. Here's Where It Goes.`

**Visual:** Timeline or 3-step roadmap

```
NOW                    6 MONTHS               12 MONTHS
────────────────────────────────────────────────────────
Studio tool         API + SDK               Platform
for solo creators   for developers          for enterprises

1 user,             100s of apps            Millions of
1 video at a time   built on KAMOD          automated videos/day

BytePlus models     Plug-in model           White-label
as the engine       marketplace             infrastructure
```

**Bottom — Bold closing line:**
> *"We're not building a video editor. We're building the content engine that runs itself."*

**Spoken (20 sec):**
> *"Today KAMOD AI is a studio tool. In 6 months, it's an API platform — letting any developer
> drop autonomous video generation into their product with one API call.
> In 12 months, it's infrastructure for enterprise content at scale.
> BytePlus Seed models are the engine. We're building the distribution layer on top.
> We're looking for partners who want to own that layer with us."*

---

## Presentation Notes

### Timing (2-minute version for Betahacks)
| Slide | Time |
|---|---|
| Slide 1 — Hook | 0:00–0:15 |
| Slide 2 — Demo result | 0:15–0:30 |
| **LIVE DEMO** (switch to screen) | 0:30–1:00 |
| Slide 3 — Architecture | 1:00–1:30 |
| Slide 4 — Market | 1:30–1:45 |
| Slide 5 — Vision | 1:45–2:00 |

### Design spec for slides (use in Google Slides / Figma / PowerPoint)
- **Background:** `#0a0a0f`
- **Title font:** Bold, 44pt, white with violet keyword (`#a78bfa`)
- **Body font:** Regular, 18pt, `#e0e0e0`
- **Accent boxes:** `#13131a` background, `#222233` border, 12px radius
- **BytePlus model labels:** Mint green `#34d399` background badge
- **Arrows/connectors:** Violet `#a78bfa`, 2px
- **Stats:** 72pt bold, gradient text (`#a78bfa` → `#34d399`)
