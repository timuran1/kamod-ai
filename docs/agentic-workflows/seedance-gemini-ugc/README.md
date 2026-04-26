# Seedance + Seed 2.0 Lite Agentic UGC Workflow Report

Date: 2026-04-25

This note documents the UGC Studio repair and the reusable pattern for future KAMOD filmmaker tools where Seed 2.0 Lite creates an editable creative plan and Seedance renders the final video.

## What Broke

The UGC workflow looked correct visually, but the render step failed because the uploaded image state was not reliably saved in JavaScript.

The upload helper expected every upload card to contain an element named `.uz-icon`:

```js
zone.querySelector('.uz-icon').style.display = 'none';
```

The current UGC upload cards did not have `.uz-icon`. When the user selected an image, the preview could appear, but the JavaScript crashed before `productImgUri` or `influencerImgUri` was saved. That created a misleading state:

- The user saw an uploaded product or character preview.
- Seed 2.0 Lite sometimes generated prompts without `@image1` or `@image2`.
- The render button believed there were no reference images.
- The UI showed: `Preparing render failed: Please upload at least one product or character reference image before rendering video.`

There was also a provider endpoint mismatch risk. Successful MuAPI dashboard examples used the model endpoint `sd-2-i2v`, while older code paths referenced `seedance-v2.0-i2v`. The UGC render handoff now starts with the successful `sd-2-i2v` path and keeps fallback protection for alias changes.

## What Fixed It

The working fix has four layers:

1. Make upload state reliable.
2. Lock image slot ordering before Seed 2.0 Lite prompt generation.
3. Make the generated prompt visibly include image references.
4. Submit the render through Seedance 2.0 I2V with the exact `images_list` ordering.

The final slot convention is:

- Product image is `@image1`.
- Influencer or character image is `@image2` when both product and influencer are uploaded.
- If only one image is uploaded, it becomes `@image1`.

The prompt shown to the user should include the same reference tokens that Seedance receives. This is important because the visible editable prompt is the creative source of truth.

## Working Architecture

The workflow has two separate model responsibilities:

Seed 2.0 Lite:

- Reads the user idea, product details, language, use case, and uploaded reference images.
- Generates three editable UGC prompt variations.
- Outputs structured JSON for the UI.
- Does not render video.

Seedance 2.0 I2V:

- Receives the selected edited prompt.
- Receives `images_list` in the same order as the visible `@imageN` tokens.
- Renders the final video.

The core rule is simple:

```text
Seed 2.0 Lite plans. The user edits. Seedance renders.
```

## Correct Data Flow

1. User uploads product and optional influencer/reference images.
2. Frontend stores data URIs in stable state.
3. Frontend sends the same images to `/api/ugc/generate` for Seed 2.0 Lite planning.
4. Backend attaches those images to Seed 2.0 Lite in order.
5. Backend injects strict context:
   - Product slot: `@image1`
   - Influencer slot: `@image2`
6. Seed 2.0 Lite returns three variations.
7. Backend safety net prepends missing reference tokens if Seed 2.0 Lite forgets them.
8. Frontend displays editable prompts with visible `@image1/@image2`.
9. User chooses one variation and clicks `Generate Video`.
10. Frontend uploads data URI references to MuAPI-hosted URLs.
11. Frontend submits selected prompt plus `images_list` to `/api/ugc/render-video`.
12. Backend submits to Seedance 2.0 I2V.
13. Backend polls status and returns the generated video.

## Seedance Payload That Works

Successful MuAPI examples use this shape:

```json
{
  "prompt": "Using @image2 as the character reference and @image1 as the product reference, the creator holds @image1 and speaks directly to camera...",
  "images_list": [
    "https://cdn.muapi.ai/outputs/product.png",
    "https://cdn.muapi.ai/outputs/character.jpeg"
  ],
  "aspect_ratio": "9:16",
  "quality": "basic",
  "duration": 10,
  "remove_watermark": false
}
```

Critical details:

- `@image1` maps to `images_list[0]`.
- `@image2` maps to `images_list[1]`.
- Do not change the order after Seed 2.0 Lite has generated the prompt.
- Do not silently fall back to text-to-video when references are expected.
- Include `remove_watermark: false` for parity with known successful runs.

## Agent Prompt Contract

Each UGC agent should be explicit about image references.

Minimum required agent rules:

```text
Product reference image is always @image1 when uploaded.
Influencer / character reference image is always @image2 when uploaded together with a product image.
Every seedance_prompt_en must include these tokens in the first sentence.
If both references are provided, open with:
"Using @image2 as the influencer/character reference and @image1 as the product reference, ..."
```

This rule should exist in the agent file and also be injected dynamically from the backend, because model output can drift.

## Defensive Safeguards

Future tools should keep these safeguards:

- Frontend should store uploaded image state and recover from visible preview state if needed.
- Upload handlers must not assume decorative DOM nodes exist.
- Generated prompt cards should show `@image1/@image2` to the user.
- Backend should repair missing reference tokens before returning Seed 2.0 Lite output.
- Render endpoint should validate that references exist before submitting I2V.
- Render endpoint should return stage-specific errors: upload, submit, polling, or provider failure.
- Status polling should use the matching provider status endpoint.
- Avoid provider-name leakage in product UI, but keep model IDs in logs and docs.

## Why This Pattern Is Strong For Filmmakers

This architecture is useful for filmmaker workflows because it separates creative planning from rendering.

Good future workflow examples:

- Product review spot: product reference plus creator reference.
- Character continuity scene: actor reference plus wardrobe reference.
- Multi-scene ad: one key image plus support references.
- Director prompt builder: Seed 2.0 Lite turns a story beat into shot prompts, Seedance renders selected shots.
- Storyboard to video: Seed 2.0 Lite creates shot list and motion language, Seedance renders chosen frames or scenes.
- Brand film builder: product image, founder/actor image, setting image, then selectable scene variations.

The best user experience is not another model aggregator. The best experience is a workflow:

```text
Upload references -> generate structured creative options -> edit the prompt -> render through KAMOD pipeline -> save history.
```

## Build Checklist For Future Agentic Video Tools

Use this checklist before building the next tool:

- Define the workflow outcome, not just the model name.
- Decide exact reference slots before prompt generation.
- Show the slot rules in the editable prompt.
- Send the same images to Seed 2.0 Lite and Seedance in the same order.
- Store a snapshot of references when the plan is generated.
- Never let a render button depend on only current mutable UI state.
- Keep prompt generation, render submission, polling, and history as separate stages.
- Preserve user-editable prompts.
- Save completed outputs and failed states cleanly.
- Test one no-reference path, one product-only path, and one product-plus-character path.

## Practical Debugging Lesson

When a tool says it has an uploaded image but the render path says no image exists, check the state transition, not the model first.

The important question is:

```text
Did the same reference that the user sees in the UI actually reach the final render payload?
```

For this bug, the answer was no. Once the upload state and image-slot contract were fixed, the UGC render worked again.
