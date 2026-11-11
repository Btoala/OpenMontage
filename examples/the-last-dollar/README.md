# The Last Dollar — production preparation

This is a **49-slot import template and offline validation kit**, not the recovered
49-shot storyboard and not a finished film. It targets the existing `animation`
pipeline at commit `fecb9a1e3cc23ef84de30b272059457a427f16f8`.

The original 49-shot text, complete narration and individual approved frames were
not recovered. Older 20-panel and 40-panel boards were found; the latter contains
duplicate numbering and invalid timecodes. They cannot safely be relabeled as
shots 1–49. Source images and private recovery notes are kept outside this public
code branch. There is no assumed mapping from those panels to the 49 slots.

The user authorized preparation and validation, **not paid generation, purchasing,
or overwriting existing assets**. No command in this kit generates media, contacts
a provider, uploads files, or completes an approval checkpoint.

## Files

| File | Purpose |
|---|---|
| `shots.template.json` | Exactly 49 empty slots; unknowns remain null. |
| `production.json` | Target, known creative constraints, provider/runtime recommendations and gates. |
| `character-lock.json` | Reference/identity checklist; canonical Shot 01 reference remains missing. |
| `config.preflight.yaml` | Valid native config with a zero-dollar cap; must be explicitly loaded. |
| `cost-model.json` | Dated published prices, assumptions and retake scenarios. |
| `approval-request.template.json` | Exact-action approval form; intentionally unsigned. |
| `production.py` | Offline initializer, input validator, native artifact compiler and cost arithmetic. |

Run from the repository root with Python 3.10+ and the repository Python
dependencies. No additional paid service or Claude subscription is needed to
prepare/import. Codex is the orchestrating assistant.

```bash
python examples/the-last-dollar/production.py preflight
python examples/the-last-dollar/production.py cost
python examples/the-last-dollar/production.py init --dest projects/the-last-dollar-import
```

The first command intentionally exits **2** for the empty template. `init` creates
the normal project directory layout and Backlot identity marker, with no scenes
or completed checkpoints. It refuses an existing destination, including symlinks.
Use a fresh versioned name to preserve earlier work.

After recovering the original material, fill a working copy of
`shots.template.json`, then:

```bash
python examples/the-last-dollar/production.py preflight --shots /absolute/path/shots.json --asset-root /absolute/path/source-assets
python examples/the-last-dollar/production.py compile --shots /absolute/path/shots.json --asset-root /absolute/path/source-assets --dest projects/the-last-dollar-plan-v001
python -m backlot open the-last-dollar-plan-v001
```

Compilation creates native, schema-validated `artifacts/script.json`,
`artifacts/scene_plan.json` and `artifacts/asset_manifest.json`. Backlot can read
the resulting storyboard. They are explicitly **unapproved drafts**, not evidence
that prior pipeline gates have passed. Production must review/approve the normal
proposal, script and scene-plan gates before the assets stage. The compiler does
not bypass the prerequisite checks in `lib/checkpoint.py`.

## Import contract

- IDs are `SH001` through `SH049`, exactly once and in order. These identify empty
  target slots until their original source mapping is recovered.
- Set a source reference for each shot. Never populate a slot from an earlier
  storyboard merely because the printed number matches.
- Set `start_frame` and `duration_frames` at the declared FPS. Starts must be
  contiguous, with no gaps or overlaps, and total runtime must be 180–300 seconds.
  The 30 FPS in the template is an editorial proposal, not recovered timing.
- Supply location, action, expression, framing, camera, continuity in/out and
  story beat. Use `N/A: reason` for genuinely inapplicable fields.
- `character_ids` reference `characters[].id`; `identity_lock` records fixed
  design features. Attach the same approved reference set to relevant shots.
- `narration.status` is `recovered` with exact source text and source reference,
  or `silent` with `text: ""`. Missing narration is neither silence nor license
  to write replacement lines. Offsets/durations are frames relative to the shot.
- Supply `audio_cues` only when actual cue positions are known. Each cue needs a
  unique filename-safe `id`, `kind` (`sfx`, `ambience`, `music`), `description`,
  `offset_frames`, `duration_frames` and `gain_db`; fades default to zero. Optional
  `audio_path` imports an existing file. Split cross-shot ambience into linked
  cues and preserve the tail in the final mix.
- `reference_paths`, `video_paths`, narration `audio_path`/`words_path` and cue
  `audio_path` must resolve inside `--asset-root`. URLs, absolute paths, missing
  files and escaping symlinks are rejected. Supplied bytes are copied into the
  new project, content-hashed and indexed. Existing files are never changed.
- Source images are references, not completed animated shots. `provided_video`
  requires a real supplied video path. Only `ai_video` and `provided_video` are
  accepted; a silent downgrade to pan/zoom stills is rejected.
- `source_confirmed: true` records the operator's explicit source reconciliation.
  It is not paid approval, visual acceptance or proof of ownership/licensing.

The exact original shot records remain in `inputs/shots.json` and
`scene_plan.metadata.shot_details`. This preserves continuity and audio fields
which the native per-scene schema does not accept directly. Absolute frame
positions for narration and foley are also exported in
`planning/audio_timeline.json`. The editor must apply that sidecar at the native
edit/compose stages; upstream does not automatically consume it.

Imported media are hash-checked, **not quality-reviewed or ffprobed by this
utility**. Before generation/compose, inspect media, measure narration duration,
align final words, verify cue windows and derive edit decisions. An audio path
does not prove it fits its assigned duration.

## Recommended production route

Use `animation` with `ai_video` shots. This supports image/video selectors,
selective narration and a canonical scene/asset/edit pipeline. `cinematic` is
primarily footage-led; `animated-explainer` assumes denser explanatory narration.
`character-animation` is an alternate SVG/GSAP rig workflow requiring newly
authored rigs and a look approval; it does not reproduce the existing frames
automatically.

| Gate | Required work |
|---|---|
| Recover | Reconcile the 49 original shots, exact narration, Shot 01 reference and asset inventory. |
| Proposal | Preserve story, 9:16 look, sparse C. Jonathan voice, score and environmental sound. Select provider/model/runtime and itemized budget. |
| Script / scene plan | Import exact text and timing; review the triple-loop beats without inventing replacements. |
| References | Approve character views, outfit, props, locations and style. Hash and reuse them. |
| Motion sample | Choose three real recovered shots that test identity, hand/coin contact and expression. Show exact inputs/cost before any paid request. |
| Assets | After sample acceptance, generate/reuse at most five shots per proposed batch; review each batch and each take. No automatic paid retries. |
| Edit | Fit actual clip lengths to approved timings; place measured narration, music transitions, rain, footsteps and coin transients. |
| Compose / review | Render only after native gates; check all 49 shots, continuity, every audio cue, clipping and final duration. Publishing requires separate approval. |

Seed reuse helps reproducibility but does not lock identity. Prefer approved
first-frame conditioning and stable reference images. A long multi-shot prompt
can save calls but sacrifices per-shot control; do not assume it preserves 49
shots exactly. Likewise, ten seconds is not cheaper than five on a per-second
endpoint. Generate only the motion and handles the recovered shot actually needs.

## Runtimes and current evidence

| Runtime | Fit | Validation in this environment |
|---|---|---|
| Remotion | Preferred native timeline and optional final word-caption sidecars/burns. No designed overlays requested. | Dependencies installed, but the system browser failed with a socket permission error. Installed does not mean render-ready. |
| FFmpeg | Browser-free cuts, fades, sound mixing and final encoding. | Installed; relevant audio timing tests passed. Candidate when the final film needs straightforward clip composition. |
| HyperFrames | Alternate for explicit SVG/GSAP character acting. | Registry reports available; a full render was not verified. Browser-dependent. |

Do not lock a runtime from the registry flag alone. A switch is a proposal
decision; this kit makes a recommendation without granting that decision.

## Existing accounts versus native API access

The Python registry found **0/31 image, 0/35 video, 0/19 TTS, 0/8 music-generation,
0/1 sound-effects and 0/1 local-music-library providers available**. It found
1/2 music-search tools (`pixabay_music`), which unconditionally reports available;
actual search/download and license suitability were not verified. These are
environment-specific observations, not statements that the user has no accounts.

Connected Higgsfield and ElevenLabs apps are separate authenticated surfaces.
Their completed assets can be imported through this kit after user-approved
generation. Their tokens are not exposed as native OpenMontage environment keys.
The selected C. Jonathan voice is discoverable in ElevenLabs, but speech quota
and native API access have not been established.

| Native option | Required setup | Assessment |
|---|---|---|
| `pika_video` | `PIKA_API_KEY` | Strong request validation, reference inputs, no-submit quote path, settled billing. No key verified. 1080p is upscaled from 768p. Quality on this character still needs a sample. |
| `higgsfield_video` | `HIGGSFIELD_KEY`, or key + secret | Wrapper is experimental. It advertises character consistency but exposes only `image_url`, not a Soul-ID control. App credits do not establish API balance or wrapper compatibility. |
| `kling_video` | `FAL_KEY` or `FAL_AI_API_KEY` | Existing first-frame adapter, but its baked-in Standard cost estimate is stale. It does not expose `generate_audio`. Block paid use until exact request pricing is reconciled. |
| `elevenlabs_tts` | `ELEVENLABS_API_KEY` | Can return word timestamps with `with_timestamps`; exact sparse script still missing. Reuse C. Jonathan only after sample approval. |
| MiniCut music/SFX | MiniCut CLI and signed-in account | Installed tools in repository, not installed CLI here. Quote/approval required. These direct tools are not on the stock animation assets-stage allowlist; a reviewed manifest extension would be needed to invoke them in that stage. Imported tracks remain supported. |
| Flow / Runway / OpenArt assets | Existing export files, or separately configured native provider | Do not assume web subscriptions are API credentials. No need to buy another editor to prepare this project. |

No native provider credentials were found in this checkout's environment. Do not
paste secrets into JSON, Git or chat. Use the execution environment's secure
credential configuration if a native route is selected.

## Sound and cost

Keep narration, score, ambience and foley as separate tracks. Approve a licensed
existing score or a specific quoted generation. No approved music file or foley
library was recovered. Do not quietly drop music. Pika's native clip audio can
include unwanted speech/music; quarantine it and review it rather than mixing
49 unrelated clip scores. Captions stay off by default; any later subtitle
sidecar must use measured final narration timing, not equal-duration word splits.

Current provider price snapshots:

- Pika H3 Flex I2V at 1080p: $0.035/output second; 768p: $0.02. Reference-to-video
  at 1080p: $0.075/output second, plus input video seconds if supplied.
- Kling v3 Standard via fal: $0.084/second without audio, $0.126 with audio.
  The fork estimates $0.02/second for Standard; do not use that for authorization.

For 49 shots, 245–490 requested seconds per pass, 1.5–2 total successful takes per
shot, plus allowances for reference stills, voice/music/SFX and 20% contingency:
plan approximately **$30–$90 for Pika I2V**, **$50–$140 for Pika multi-reference**,
or **$65–$195 for conservatively priced Kling with audio**. These are planning
budgets, not quotes. Pika reserves one extra output second per shot in the local
estimator. Stills and audio allowances are explicitly unquoted. Existing assets
may lower cash use; weak consistency may increase retakes. Operator labor, taxes,
subscriptions and hosted rendering are excluded. The README's $1.33 example is
not a production estimate for this film.

The kit deliberately contains no paid executor. `config.preflight.yaml` also
sets the native tracker to cap mode with $0, but it is **not automatically loaded
by upstream** and is **not a universal interceptor around arbitrary tool calls**.
Future production must load it explicitly and retain approval controls; merely
changing a JSON flag cannot authorize spending.

Sources checked November 10, 2026:

- https://dev.pika.art/models/pika/pika-h3-flex/image-to-video/pricing
- https://dev.pika.art/models/pika/pika-h3-flex/reference-to-video/pricing
- https://fal.ai/models/fal-ai/kling-video/v3/standard/image-to-video
- https://higgsfield.ai/creator-hub/help-center/integrations/what-is-the-higgsfield-api

## Verification

```bash
python -m pytest -q tests/examples/test_last_dollar_import.py
```

Tests cover absent source material, duplicate/missing IDs, gaps/overlaps, unknown
characters, narration overflow, audio-cue mapping, source hashes, filesystem
escapes, no-overwrite behavior, offline execution, native schemas, Backlot's
49-scene join and the zero-budget reservation block. Fixture scenes are marked
TEST ONLY and never delivered as recovered story material.

The next production action remains blocked by missing original material and
unapproved provider/runtime choices. This setup is ready to receive that material;
it is not ready to run a paid 49-shot batch.
