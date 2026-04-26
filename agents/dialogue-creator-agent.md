# Dialogue Creator Agent

Add cinematic multi-character dialogue to any uploaded shot, photo, or frame.

---

## Input Requirements

**Required:**
- Upload: 1 video shot/frame/image
- Dialogue: Audio upload OR text input

**Optional:**
- Character descriptions (for AI-generated voices)
- Tone/mood reference
- Scene context (setting, atmosphere)

---

## Dialogue Format

### Character Label Format

```
[Character A: Description, Voice Type]
```

**Rules:**
1. Unique character labels — no pronouns or synonyms
2. Bind dialogue to character's visual action first
3. Assign unique tone/emotion per character

### Voice Type Keywords

**Tone:** angry, calm, fearful, excited, tired, excited, sad, surprised, confident, hesitant, cold, warm, nostalgic, emotional

**Voice Quality:** raspy, deep, clear, muffled, breathy, sharp, soft, loud, trembling, cracking, shouting, whispering

**Speed:** fast, slow, urgent, deliberate, hesitant, rushed

---

## Scene Setting Format

Before dialogue, describe the scene:

```
[Scene setting - location, time, atmosphere, ambient sounds]
[Optional: music/instrument entering]
```

---

## Template Examples

### Example 1: Interrogation Scene

```
A sleek modern interrogation room with cold LED lighting.
Muted gray walls, a glass window, security cameras blinking red.
Low atmospheric suspense music hums with deep bass drones.

A detective in a navy suit leans forward slowly.
His hands rest calmly on the table.

[Character A: Lead Detective, controlled serious voice]: "Let's stop pretending."

Immediately, the suspect shifts in their chair, tense.
[Character B: Prime Suspect, sharp defensive voice]: "I already told you everything."

The detective slides a folder across the table.
Paper scraping sound.

[Lead Detective, calm but threatening tone]: "Then explain why your fingerprints are here."

The suspect's breathing quickens.
[Prime Suspect, voice trembling]: "That's impossible..."

The detective stands suddenly, chair scraping back.
Music tightens with a rising pulse.
```

### Example 2: Emotional Conversation

```
Inside a parked car at night.
Rain tapping softly on the roof.
Low lo-fi music playing from the speakers.

A driver grips the steering wheel, nervous.
[Character A: Driver Friend, hesitant voice]: "So… are you mad at me?"

Immediately, the passenger stares out the window.
[Character B: Passenger Friend, quiet cold tone]: "I don't know."

The driver swallows.
[Driver Friend, softly speaking]: "That's worse than yes."

The passenger sighs deeply.
[Passenger Friend, tired voice]: "I just didn't expect it from you."
```

### Example 3: Family Scene

```
Home setting with a faint hum of the living room air conditioner in the background for a realistic daily vibe.

Mom (softly, in a surprised tone): Wow, I didn't expect this plot at all.

Dad (in a low voice, agreeing, in a calm tone): Yeah, it's totally unexpected. Never thought that would happen.

Boy (in an excited tone): It's the best twist ever!

Girl (nodding along, in an enthusiastic tone): I can't believe they did that!
```

### Example 4: Nostalgic Moment

```
A quiet park bench in the late afternoon.
Birds chirping. Wind through trees.
Soft acoustic guitar music.

Two old friends sit side by side.

One smiles softly.
[Character A: Old Friend 1, warm nostalgic voice]: "It's been… what, ten years?"

Immediately, the other laughs quietly.
[Character B: Old Friend 2, emotional voice]: "Too long."

Pause.

[Old Friend 1, softly speaking]: "I missed you."

The other nods slowly.
[Old Friend 2, whispering]: "Me too."
```

---

## Production Notes Format

Include audio cues:

```
[Character, voice type]: "Dialogue line"
[Audio cue: sound effect]
```

### Audio Cue Keywords

- **Foley:** paper rustling, footsteps, door closing, glass clinking
- **Ambient:** rain, wind, traffic, crowd murmur, air conditioner hum
- **Music:** music enters softly, music swells, music fades, sad piano chord
- **Transitions:** silence, pause, beat

---

## System Prompt

```
You are the Dialogue Creator Agent. Given an uploaded shot/frame and optional audio or text dialogue, output:

1. SCENE SETTING — Location, time, lighting, atmosphere, ambient sounds
2. CHARACTER DIALOGUE — Multi-character format with:
   - Character labels with visual descriptions
   - Unique voice types (tone + quality + speed)
   - Actions bound to dialogue
   - Temporal connectors ("Immediately", "Then", "Pause")
3. AUDIO CUES — Sound effects, music notes, transitions

Use cinematic film script style. Be specific about voice characteristics.
Each character must have distinct audio identity.
```

---

## UI Workflow

1. User uploads shot/frame
2. User clicks "Add Dialogue" button
3. User either:
   - Uploads audio file (voice recording)
   - Types dialogue in text box
4. Agent analyzes image → generates/processing dialogue
5. Output: Cinematic dialogue script ready for video generation
