# KAMOD AI — Brand & Design System

> Reference document for presentations, pitch decks, marketing, and UI consistency.

---

## 1. Brand Identity

### Name & Tagline
- **Product name:** KAMOD AI
- **Tagline:** *"From Idea to Video — Instantly."*
- **Sub-tagline:** *"The autonomous video studio powered by BytePlus Seed."*
- **Category:** Autonomous AI Content Studio

### Brand Personality
| Trait | Expression |
|---|---|
| **Intelligent** | Clean, precise, no clutter |
| **Creative** | Gradient energy, cinematic feel |
| **Professional** | Dark UI, high contrast, serious typography |
| **Fast** | Motion language, sharp edges, forward momentum |

---

## 2. Color Palette

### Primary Colors
| Name | Hex | Usage |
|---|---|---|
| **Deep Space** | `#0a0a0f` | Page background |
| **Surface Dark** | `#13131a` | Cards, panels |
| **Surface Mid** | `#0e0e18` | Input fields |
| **Border** | `#1e1e2e` | Dividers, card borders |

### Accent Colors
| Name | Hex | Usage |
|---|---|---|
| **Violet** | `#a78bfa` | Primary brand color, headers, highlights |
| **Sky Blue** | `#60a5fa` | Secondary accent, links |
| **Mint Green** | `#34d399` | Success, active states, CTAs |
| **Deep Purple** | `#7c3aed` | Buttons, hover states |
| **Indigo** | `#4f46e5` | Gradient anchor |

### Semantic Colors
| Name | Hex | Usage |
|---|---|---|
| **Warning** | `#f59e0b` | Caution states |
| **Error** | `#f87171` | Errors, required fields |
| **Text Primary** | `#e0e0e0` | Body text |
| **Text Muted** | `#888888` | Descriptions, hints |
| **Text Dim** | `#555555` | Labels, placeholders |

### Signature Gradients
```
Brand Gradient (Logo / Hero):
  linear-gradient(135deg, #a78bfa → #60a5fa)

Rainbow Accent (Progress bars / dividers):
  linear-gradient(90deg, #a78bfa → #60a5fa → #34d399)

Action Gradient (Buttons):
  linear-gradient(135deg, #7c3aed → #4f46e5)

Video Gradient (Video module):
  linear-gradient(135deg, #6d5fd6 → #3b7dd8)

Success Gradient (Completed states):
  linear-gradient(135deg, #34d399 → #4ade80)
```

---

## 3. Typography

### Font Stack
```
Primary:   -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif
Code/IDs:  "SF Mono", "Fira Code", "Courier New", monospace
```

### Type Scale
| Role | Size | Weight | Color |
|---|---|---|---|
| Hero H1 | 2.4rem | 700 | Gradient text |
| Section H2 | 1.6rem | 700 | `#e0e0e0` |
| Card Title | 0.8rem | 700 | `#555` uppercase |
| Body | 0.9rem | 400 | `#e0e0e0` |
| Caption | 0.75rem | 400 | `#888` |
| Label | 0.78rem | 500 | `#999` |

### Logo Treatment
```
KAMOD AI
━━━━━━━━
Font:   Bold, tight letter-spacing (-0.02em)
Color:  linear-gradient(135deg, #a78bfa, #60a5fa)
Style:  -webkit-background-clip: text (gradient text)
Accent: Small "AI" in lighter weight or Sky Blue
```

---

## 4. Logo Concepts

### Option A — Text Mark
```
╔══════════════════╗
║  K A M O D  AI  ║   ← Gradient violet→blue
║  ─────────────  ║   ← Thin mint green underline
║  Autonomous     ║   ← Muted caption
║  Video Studio   ║
╚══════════════════╝
```

### Option B — Icon + Text
```
  ▶ KAMOD AI
  ─
Icon: Play button (▶) filled with brand gradient
      OR: Abstract "K" formed by two video-frame lines
```

### Option C — Monogram Badge
```
  ┌───┐
  │ K │   ← Dark background #13131a
  │AI │   ← Gradient fill on letters
  └───┘
```

---

## 5. UI Component Language

### Cards
```
Background:  #13131a
Border:      1px solid #222233
Radius:      14px
Padding:     24px
Shadow:      none (flat dark design)
```

### Buttons — Primary
```
Background:  linear-gradient(135deg, #a78bfa, #6d5fd6)
Text:        #ffffff, font-weight 600
Radius:      9px
Padding:     12px 24px
Hover:       opacity 0.85, slight scale(0.98)
```

### Buttons — Success / Generate
```
Background:  linear-gradient(135deg, #34d399, #059669)
```

### Buttons — Danger
```
Background:  linear-gradient(135deg, #f87171, #dc2626)
```

### Status Badges
```
Processing:  bg #1a1a2e  text #888     border #333
Completed:   bg #0d1a14  text #34d399  border #1a3d25
Failed:      bg #1a0a0a  text #f87171  border #3d1a1a
```

### Input Fields
```
Background:  #0e0e18
Border:      1px solid #2a2a3a
Radius:      8px
Focus:       border-color → #34d399
Text:        #e0e0e0
```

---

## 6. Motion & Animation

```css
/* Standard transition */
transition: all 0.2s ease;

/* Button press */
transform: scale(0.98);

/* Spinner (loading) */
@keyframes spin { to { transform: rotate(360deg); } }
animation: spin 0.8s linear infinite;

/* Fade-in cards */
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } }
animation: fadeIn 0.3s ease;
```

**Principles:**
- Keep motion subtle and fast (0.15–0.3s)
- No decorative animations — only functional feedback
- Loading states always visible (never silent waits)

---

## 7. Iconography

- **Style:** Unicode emoji + minimal SVG line icons
- **Size:** 14–16px inline, 20–24px standalone
- **No icon libraries needed** — keep it zero-dependency

| Feature | Icon |
|---|---|
| Video Generation | 🎬 |
| Image / Storyboard | 🖼️ |
| Voice / TTS | 🎙️ |
| Voice Clone | 🔁 |
| AI Director | 🤖 |
| Music / Audio | 🎵 |
| Analytics | 📊 |
| Download | ⬇ |
| Success | ✓ |
| Error | ✗ |
| Processing | ⏳ |

---

## 8. Pitch Deck Design Guidelines

### Slide Background
```
Option 1 (Dark): #0a0a0f with subtle radial glow — rgba(167,139,250,0.06) center
Option 2 (Gradient): linear-gradient(135deg, #0a0a0f 0%, #0f0818 100%)
```

### Slide Title Style
```
Font:    Bold, 40–48pt
Color:   White for words, Violet (#a78bfa) for key term
Example: "One Prompt.  Complete Video."
          white         violet
```

### Data/Stats Callout
```
Large number:  80pt, Bold, Gradient text (#a78bfa → #34d399)
Label below:   14pt, #888, uppercase
```

### Architecture Diagrams
```
Boxes:      #13131a fill, #222233 border, 12px radius
Arrows:     #a78bfa color, 2px weight
Labels:     #e0e0e0 text, 11pt
Highlight:  Mint green (#34d399) for BytePlus model boxes
```

---

## 9. Brand Voice

| Context | Tone | Example |
|---|---|---|
| Headline | Bold, declarative | *"One prompt. Complete video."* |
| Feature description | Direct, benefit-first | *"Seedance 2.0 animates your keyframes — no timeline editing."* |
| Error messages | Clear, non-blaming | *"Generation failed. Try a shorter prompt."* |
| Loading states | Active, confident | *"Generating your storyboard…"* |
| Success states | Quiet, satisfying | *"✓ Done"* |

### Words to use
`autonomous · instant · cinematic · professional · generate · pipeline · agent`

### Words to avoid
`AI-powered` (overused) · `revolutionary` · `cutting-edge` · `leverage`

---

## 10. Competitive Positioning

```
        HIGH QUALITY
              │
    Runway ●  │  ● KAMOD AI ◄ (BytePlus-native, autonomous)
              │
COMPLEX ──────┼────── SIMPLE
              │
   Manual ●   │  ● Basic wrappers
              │
        LOW QUALITY
```

**Key differentiator:** KAMOD AI is the only tool that chains
Seed 2.0 + Seedream + Seedance + TTS into a single autonomous pipeline
with no external video tools.
