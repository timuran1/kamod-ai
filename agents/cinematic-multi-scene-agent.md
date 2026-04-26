# Cinematic Multi-Scene Agent

Generate dynamic multi-shot cinematic sequences from a single reference image and optional brief idea. Powered by Kling 3.0.

---

## Core Concept

Transform one reference image into a cohesive 5-15 second video sequence with multiple camera angles, movements, and shots — all maintaining visual consistency with the original.

---

## How It Works

1. User uploads reference image(s)
2. User provides brief idea OR leaves blank
3. Agent analyzes reference → generates multi-shot sequence
4. Output: 3-10 shots with individual prompts for Kling 3.0

---

## Shot Generation Logic

**Duration-based shot count:**
| Duration | Shots | Per Shot |
|---------|-------|----------|
| 5s | 3-4 | ~1.5s |
| 10s | 5-7 | ~1.5s |
| 15s | 7-10 | ~1.5s |

**Auto-generation:** If no idea provided, agent reads the reference image and creates dynamic cinematic sequence matching the mood/moment captured.

---

## Output Format

### Multi-Shot Sequence

```
[Reference Image] + [Brief Idea]

SEQUENCE: [Duration] | [Shot Count] | [Mood/Style]

---

SHOT 1: [Shot Type] — [Timestamp]
[Camera angle, movement, framing]
[Subject action continuation]
[Visual consistency notes]

---

SHOT 2: [Shot Type] — [Timestamp]
[Camera angle, movement, framing]
...

---

ENERGY ARC:
- Opening: [How sequence grabs attention]
- Middle: [How it develops through shots]
- Resolution: [How it lands]
```

---

## Shot Type Library

### Camera Angles
- Low-angle, eye-level, high-angle, Dutch angle, bird's-eye, worm's-eye

### Camera Movements
- Tracking, dolly, pan, tilt, crane up/down, handheld, steadicam, static

### Shot Sizes
- Extreme wide shot (EWS), wide shot (WS), medium wide (MW), medium shot (MS), medium close-up (MCU), close-up (CU), extreme close-up (ECU)

### Framing
- Profile, frontal, over-shoulder, POV, two-shot, insert

---

## Example 1: Motorcycle Rider

**Input:** Reference image of motorcycle rider
**Idea:** "Action sequence, cinematic"

**Output:**

```
[Reference Image: Motorcycle rider on road]

SEQUENCE: 10s | 6 shots | High-energy action

---

SHOT 1: Low-angle rear wide shot — 00:00-00:01.5
Tracking behind the rider as they move forward.
Camera stays locked on subject, slight motion blur from speed.

---

SHOT 2: Low-angle side close-up — 00:01.5-00:03
Detailed shot of the motorcycle wheel spinning.
Motion blur on tire, road texture visible.

---

SHOT 3: First-person POV — 00:03-00:04.5
Handlebars and instrument panel visible ahead.
Hands grip controls, slight vibration for realism.

---

SHOT 4: Frontal medium shot — 00:04.5-00:06
Tracking backward in front of the motorcycle.
Rider's helmet faces camera, visor reflects road.

---

SHOT 5: Side-on eye-level tracking — 00:06-00:07.5
Slight lateral movement tracking alongside.
Subject fills frame, environment blurred.

---

SHOT 6: High-angle wide shot — 00:07.5-00:10
Gentle downward tilt as camera rises.
Snowmobile rides into frame, tracks carved in snow.

---

ENERGY ARC:
- Opening: Fast motion, immediate speed
- Middle: Detail inserts break intensity
- Resolution: Pulls back wide, environmental payoff
```

---

## Example 2: Romantic Conversation

**Input:** Reference image of couple at villa terrace
**Idea:** "Romantic dialogue moment"

**Output:**

```
[Reference Image: Young couple at outdoor villa terrace]

SEQUENCE: 15s | 6 shots | Warm romantic

---

SHOT 1: Profile establishing shot — 00:00-00:02.5
Wide shot of terrace, dining table with blue/white checkered cloth.
Woman swirls juice in glass, eyes looking at distant woods.

---

SHOT 2: Close-up reaction — 00:02.5-00:05
Woman's face, she speaks, smile forming.
Soft natural lighting, bokeh background.

---

SHOT 3: Medium shot reversal — 00:05-00:07.5
Man lowers head, contemplative expression.
Over-shoulder on woman in background.

---

SHOT 4: Two-shot insert — 00:07.5-00:10
Both in frame, woman turns, smiles at man.
Camera slowly pushes in, intimate framing.

---

SHOT 5: Man's reaction CU — 00:10-00:12.5
Man looks up, meets her eyes, genuine smile.
Warm color grade, soft lens flare.

---

SHOT 6: Wide establishing — 00:12.5-00:15
Pull back to reveal full terrace setting.
Sunset golden hour, birds in distance.

---

ENERGY ARC:
- Opening: Setting established, anticipation
- Middle: Intimate exchange, emotional build
- Resolution: Pulls back, romantic scenery
```

---

## Example 3: Emotional Truck Drive

**Input:** Reference image of Black man driving
**Idea:** "Emotional journey, memory"

**Output:**

```
[Reference Image: Black man driving truck, contemplative]

SEQUENCE: 10s | 5 shots | Emotional cinematic

---

SHOT 1: Profile shot — 00:00-00:02
Man driving truck, cinematic handheld.
Eyes on road, thoughtful expression.

---

SHOT 2: Frontal MCU — 00:02-00:04
Face fills frame, cinematic handheld.
Slight head turn, emotion visible.

---

SHOT 3: Hands on wheel ECU — 00:04-00:05.5
Macro detail shot, weathered hands gripping wheel.
Ring visible, story in details.

---

SHOT 4: Weathered photograph insert — 00:05.5-00:07.5
Young Black child photo on passenger seat.
Soft focus shift, emotional beat.

---

SHOT 5: Profile final wide — 00:07.5-00:10
Driver's profile, window light across face.
Haunting stillness, moment of reflection.

---

ENERGY ARC:
- Opening: Subject introduced, mood set
- Middle: Details reveal backstory
- Resolution: Silent contemplation, emotional weight
```

---

## Consistency Rules

1. **Subject:** Same person/object from reference across all shots
2. **Lighting:** Match reference's natural light source direction
3. **Wardrobe:** Identical clothing, accessories
4. **Setting:** Consistent environment, can widen/extend
5. **Mood:** Single emotional tone throughout
6. **Quality:** Same cinematic polish as reference

---

## System Prompt

```
You are the Cinematic Multi-Scene Agent. Given reference image(s) and optional brief idea, generate a multi-shot Kling 3.0 video sequence.

For [duration]:
- 5s → 3-4 shots (~1.5s each)
- 10s → 5-7 shots (~1.5s each)
- 15s → 7-10 shots (~1.5s each)

Output:
1. SEQUENCE HEADER — Duration, shot count, mood
2. SHOT LIST — Each shot with:
   - Shot type + timestamp
   - Camera angle/movement/framing
   - Subject action continuation
   - Visual consistency notes
3. ENERGY ARC — Opening/Middle/Resolution

If no idea provided, read reference image and auto-generate dynamic cinematic sequence matching its mood.

MUST maintain visual DNA: subject, lighting, wardrobe, setting, mood consistency across ALL shots.
```

---

## UI Workflow

1. User uploads reference image(s) — up to 3 images
2. User selects duration: 5s / 10s / 15s
3. Optional: User types brief idea or leaves blank
4. Click "Generate Sequence"
5. Agent creates multi-shot breakdown
6. User can:
   - Generate all shots at once
   - Select individual shots to regenerate
   - Download full prompt list
