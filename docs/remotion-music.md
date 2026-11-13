# Documented music configuration in Remotion

The templated `render` and direct `remotion_render` operations resolve music
asset IDs using `asset_manifest`, stage local audio, and send a playable `src`
to both CinematicRenderer and Explainer. Example:

```json
{
  "audio": {
    "music": {
      "asset_id": "music-bed",
      "volume": 0.25,
      "fade_in_seconds": 1,
      "fade_out_seconds": 2
    }
  }
}
```

The manifest entry for `music-bed` must contain a non-empty `path`. Explicit
asset IDs are authoritative: an unknown ID is an error, even if a `src` is also
provided. Missing local files fail before launching the render CLI. Filesystem
paths, file URIs, and paths relative to the active Remotion public directory
are supported; HTTP(S)/data sources pass through to Remotion without a Python
network fetch. This adapter does not validate remote availability.

Legacy top-level `music` and direct `src`/`source`/`path` inputs remain supported.
When both locations exist, `audio.music` wins. An explicit empty object or null
canonical block disables legacy music. Snake-case fade keys override camelCase
aliases. Volume must be finite and within 0–1; timing values must be finite and
nonnegative. Zero volume means mute; zero fade means no fade. Omitted defaults
remain composition-specific (music volume 0.15 for CinematicRenderer and 0.1 for
Explainer; fades 2/3 seconds for both).

Existing narration, captions, scenes and SFX payloads are preserved. This change
does not add a segmented narration/SFX adapter or dynamic ducking. Existing
supported narration tracks and pre-mixed SFX remain the way to supply those
layers. The existing explicit `audio_path` still means an approved complete mix
that replaces the rendered audio, including music. Include music in that mix
when using `audio_path`.

FFmpeg, HyperFrames, and hand-authored atelier routing are unchanged. In
particular, music is not promoted to FFmpeg's replacement `audio_path` because
that would discard existing audio and bypass volume/fades. The tool version is
bumped so cached silent renders from the old version cannot be reused.

## Offline verification

Run the adapter contracts with:

```bash
python -m pytest -q tests/tools/test_video_compose_music.py
```

With the existing Node/Remotion dependencies and FFmpeg, run the production
audio-expression tests and staged-input FFmpeg proof:

```bash
python -m pytest -q tests/tools/test_remotion_music_envelope.py
```

These execute the actual JSX audio expressions with supplied hook values, then
measure a synthetic AAC export made using the staged WAV and those envelopes.
They are not a full Remotion render. To verify the full browser path on a host
that permits Chromium, opt into the six additional tests:

```bash
OPENMONTAGE_TEST_REMOTION=1 REMOTION_TEST_BROWSER=/path/to/chromium \
  python -m pytest -q tests/tools/test_video_compose_music_render.py
```

No dependencies are automatically installed. The full-render tests set npm
offline mode, use only synthetic local inputs, and inspect decoded output with
FFmpeg. `OPENMONTAGE_MUSIC_EVIDENCE_DIR` optionally saves proof files and metrics.
