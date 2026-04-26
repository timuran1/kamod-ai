# Video Analyzer Agent

Analyze any video (10s-5min) and generate structured content for multiple use cases in the KAMOD pipeline.

---

## Input Requirements

**Required:**
- Upload: Video file (MP4/MOV/WebM)
- Duration: 10 seconds to 5 minutes
- Language: Select output language (Russian / Uzbek / English)

**Optional:**
- Transcript (auto-generated if not provided)
- Specific use case focus

---

## Supported Use Cases

| Use Case | Output Sections |
|---------|----------------|
| **Cinematic Prompts** | Shot-by-shot breakdown with camera/lighting/movement |
| **SEO & Social Pack** | Hooks, titles, keywords, B-roll ideas |
| **ShortForm Creators** | TikTok/Reels summaries, repurposing ideas |
| **Education Pack** | Flashcards, concepts, lesson outline |
| **Podcast Pack** | Episode summary, highlights, topic index |
| **Marketing Pack** | Ad hooks, emails, tweets, pain points |
| **Meeting Notes** | Decisions, action items, risks |
| **Full Transcription** | Spoken audio transcript in the original spoken language |

---

## Language Selection

User must select output language before analysis:

- 🇺🇸 **English**
- 🇷🇺 **Russian**
- 🇺🇿 **Uzbek**

All outputs will be generated in selected language only.

Exception: **Full Transcription** preserves the original spoken language automatically. If the speaker talks in Uzbek, return Uzbek. If Russian, return Russian. If multiple languages are spoken, preserve each language as spoken.

---

## Use Case Outputs

### CINCEMATIC PROMPTS

Generate shot-by-shot breakdown for AI video recreation:

```
SEQUENCE: [Duration] | [Shot Count]

---

SHOT 1 ([timestamp]) — [Shot Name]
• Camera: [angle, movement, lens]
• Lighting: [key light, fill, mood]
• Subject: [action, expression, position]
• Atmosphere: [mood, color grade, texture]
• Movement: [camera motion, subject motion]
• Prompt: "[Full generation prompt for AI video tool]"

---

... repeat for each shot

---

CAMERA ANGLES USED: [list]
LIGHTING STYLE: [description]
OVERALL MOOD: [tone description]
```

**Prompt Format for AI Video Tools:**
- Include: camera angle, movement, lighting setup
- Describe: subject action, expression, wardrobe
- Specify: atmosphere, color grade, visual style
- Add: motion keywords, duration, transitions

---

### SEO & SOCIAL PACK

```
## Video Summaries (3-5 bullets)
- [Short, scroll-stopping bullet 1]
- [Short, scroll-stopping bullet 2]
- [Short, scroll-stopping bullet 3]

## Hook Ideas (3-7)
1. [1-sentence hook]
2. [1-sentence hook]
3. [1-sentence hook]

## Title Options (5-10)
1. [Title option]
2. [Title option]
3. [Title option]

## SEO Keywords/Tags (10-20)
[Keyword], [Keyword], [Keyword]...

## B-Roll/Overlay Ideas (5)
- [B-roll idea]
- [B-roll idea]
```

---

### SHORTFORM CREATORS

```
## Captions for TikTok/Reels/Shorts (3-5)
- [Bullet summary optimized for short-form]
- [Bullet summary optimized for short-form]

## Hook & Title Ideas (3-7)
1. [Hook/Title combo]
2. [Hook/Title combo]

## Content Repurposing Ideas (5)
- "Turn this into a 30-sec clip about [topic]"
- "Create a reaction video on [moment]"
- "Make a before/after format from [content]"
- "Extract the [key insight] as standalone tip"
- "Use [scene] as transition in another video"
```

---

### EDUCATION PACK

```
## Flashcards (10-30 pairs)
Q: [Question] / A: [Answer] ([timestamp])
Q: [Question] / A: [Answer] ([timestamp])

## Key Concepts with Timestamps
- [Concept 1] — [timestamp]
- [Concept 2] — [timestamp]
- [Concept 3] — [timestamp]

## Lesson Outline
- Section 1: [Topic]
- Section 2: [Topic]
- Section 3: [Topic]

## Homework/Practice Questions (3-5)
1. [Question]
2. [Question]
3. [Question]

## Student Summary — Beginner (max 200 words)
[Simplified summary of content]

## Student Summary — Intermediate (max 200 words)
[Technical summary of content]
```

---

### PODCAST/INTERVIEW PACK

```
## Episode Summary (150-250 words)
[Detailed but concise episode overview]

## Highlight Moments (5-10)
1. [Timestamp] — [Moment Title]
   [1-2 sentence description]
   Short-clip title: [Title]
   Caption: [Caption]

2. [Timestamp] — [Moment Title]
   ...

## Topic Index
- [Topic 1]: [timestamp range]
- [Topic 2]: [timestamp range]
- [Topic 3]: [timestamp range]
```

---

### MARKETING & BUSINESS

```
## Ad Hooks (3)
1. [Hook for ad]
2. [Hook for ad]
3. [Hook for ad]

## Email Subject Lines + Angles (3 each)
Subject: [Subject line]
Angle: [Brief angle description]

## Tweet/X Post Ideas (5)
- [Tweet idea 1]
- [Tweet idea 2]
- [Tweet idea 3]
- [Tweet idea 4]
- [Tweet idea 5]

## Customer Pain Points
- [Pain point mentioned]
- [Pain point mentioned]

## Objections
- [Objection mentioned]
- [Objection mentioned]

## Benefits/Outcomes
- [Benefit/outcome]
- [Benefit/outcome]
```

---

### INTERNAL MEETINGS

```
## Decisions Made
- [Decision 1]
- [Decision 2]
- [Decision 3]

## Action Items
**Name:**
- [Action item]
**Name:**
- [Action item]

## Risks/Open Questions
- [Risk/question]
- [Risk/question]

## Meeting Summary (5-7 bullets)
- [Summary point]
- [Summary point]
- [Summary point]
```

---

### FULL TRANSCRIPTION

Return only the spoken transcript from the video:

```
[00:00] [Transcribed spoken text in the original spoken language]
[00:05] [Continue transcript...]
```

Rules:
- Detect the spoken language automatically.
- Preserve the original spoken language and do not translate.
- Include simple timestamps when possible.
- Do not summarize, analyze, rewrite, or add extra sections.
- If there is no spoken dialogue, write: No spoken dialogue detected.

---

## Analysis Process

1. **Video Upload** → User drops video file
2. **Language Selection** → Choose English/Russian/Uzbek
3. **Auto-Transcript** → System generates transcript
4. **Use Case Selection** → Choose one or multiple outputs
5. **Analysis Run** → Seed 2.0 Lite processes video + transcript
6. **Output Generation** → Structured content in selected language

---

## Rules for Analysis

- **Never invent facts** — Only use content from video
- **If unknown, say:** "Not specified in the video"
- **Use compact bullets** — No long paragraphs except summaries
- **No extra sections** — Only defined headings above
- **Base answers on video** — Always reference transcript
- **Concise output** — Ready to copy-paste
- **Transcription mode** — Preserve the original spoken language and return only the transcript.

---

## System Prompt

```
You are the Video Analyzer Agent. Analyze uploaded video and transcript to generate structured content.

INPUT:
- Video file (10s-5min)
- Transcript (auto-generated or provided)
- Output language: [EN/RU/UZ]
- Use case: [selected use case]

PROCESS:
1. Analyze video content and transcript
2. Identify key moments, topics, visual elements
3. For Cinematic: break down shots with camera/lighting details
4. Generate output in selected language only

OUTPUT RULES:
- Never invent facts not in video
- Compact bullets, no long paragraphs
- Only use headings defined for selected use case
- Concise, copy-paste ready format

For CINEMATIC PROMPTS specifically:
- Each shot needs: camera angle, movement, lighting
- Include atmosphere, color grade, visual style
- Generate AI video-ready prompts (Veo/Sora compatible)
- Note transitions between shots
```

---

## UI Workflow

```
┌─────────────────────────────────────────────────────────┐
│  UPLOAD ZONE                                           │
│  [Drop video here] or [Browse]                          │
│  Supported: MP4, MOV, WebM (10s-5min)                  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  LANGUAGE SELECT                                       │
│  [🇺🇸 English] [🇷🇺 Russian] [🇺🇿 Uzbek]                │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  USE CASE SELECTOR                                      │
│                                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  │ CINEMA  │ │ SEO+    │ │ SHORTS │ │ EDU     │        │
│  │ 🎬      │ │ SOCIAL  │ │ 📱     │ │ 📚      │        │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                     │
│  │ PODCAST │ │ MARKET  │ │ MEETING │                     │
│  │ 🎙️      │ │ 📈      │ │ 📋     │                     │
│  └─────────┘ └─────────┘ └─────────┘                     │
│                                                         │
│  [Select multiple or single use case]                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ANALYZE VIDEO                                          │
│  [▶️ Analyze]                                           │
│                                                         │
│  Progress: ████████░░ 80%                              │
│  Step: Processing transcript...                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  OUTPUT TABS                                           │
│  [Cinematic] [SEO] [Shorts] [Education] [Podcast] ...  │
│                                                         │
│  [Generated content in selected language]              │
│  [Copy] [Download] [Share]                             │
└─────────────────────────────────────────────────────────┘
```

---

## Additional Features

| Feature | Description |
|---------|-------------|
| **Multi-select use cases** | Generate multiple packs at once |
| **Timestamp extraction** | Auto-detect key moments |
| **Transcript editor** | Manual corrections before analysis |
| **Export formats** | .txt, .md, .json, copy to clipboard |
| **Thumbnail preview** | Video frames for shot identification |

---

## Technical Notes

- **Max video duration:** 5 minutes
- **Supported formats:** MP4, MOV, WebM
- **Transcript:** Auto-generated via speech-to-text
- **Processing:** Based on video content + transcript
- **Output:** Generated in selected language only
