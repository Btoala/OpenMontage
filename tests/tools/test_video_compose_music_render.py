"""Opt-in, entirely local Remotion + FFmpeg integration tests.

Run with OPENMONTAGE_TEST_REMOTION=1 and REMOTION_TEST_BROWSER set to an
already installed Chromium executable. Uses the existing node_modules only;
npm offline mode prevents dependency downloads. Synthetic WAVs are free.
"""

import array
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.media_profiles import ALL_PROFILES, AspectRatio, MediaProfile
from tools.video.video_compose import VideoCompose


pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_TEST_REMOTION") != "1",
    reason="opt-in local render: set OPENMONTAGE_TEST_REMOTION=1",
)


def run(command):
    return subprocess.run(command, check=True, capture_output=True, timeout=60)


def decode(path):
    raw = run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
               "-ar", "48000", "-f", "f32le", "-"]).stdout
    samples = array.array("f")
    samples.frombytes(raw)
    return samples


def amplitude(samples, frequency, start, end):
    window = samples[round(start * 48000):round(end * 48000)]
    step = 2 * math.pi * frequency / 48000
    real = sum(value * math.cos(step * i) for i, value in enumerate(window))
    imag = sum(value * math.sin(step * i) for i, value in enumerate(window))
    return 2 * math.hypot(real, imag) / len(window)


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    root = tmp_path_factory.mktemp("music-render")
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=duration=4:size=640x360:rate=30", "-an", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(root / "clip.mp4")])
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=880:duration=4:sample_rate=48000", str(root / "music.wav")])
    # Separate frequencies stand in for narration and already-mixed SFX.
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=220:duration=4:sample_rate=48000", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=4:sample_rate=48000", "-filter_complex",
         "amix=inputs=2:normalize=0", str(root / "narration-sfx.wav")])
    return root


@pytest.fixture
def local_renderer(monkeypatch):
    browser = os.environ.get("REMOTION_TEST_BROWSER")
    assert browser and Path(browser).is_file(), "Set REMOTION_TEST_BROWSER to installed Chromium"
    assert VideoCompose()._remotion_available(), "Existing Remotion node_modules are required"
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    monkeypatch.setenv("NPM_CONFIG_OFFLINE", "true")
    monkeypatch.setenv("OPENMONTAGE_ASSET_CACHE", "0")
    monkeypatch.setitem(ALL_PROFILES, "music-test", MediaProfile(
        name="music-test", width=640, height=360,
        aspect_ratio=AspectRatio.LANDSCAPE_16_9, fps=30,
        codec="libx264", audio_codec="aac", crf=23,
    ))
    return browser


@pytest.mark.parametrize("family", ["documentary-montage", "explainer-data"])
@pytest.mark.parametrize("volume,fade,other_audio", [(0.5, 1, True), (0.25, 0, False), (0, 0, False)])
def test_decoded_music_gain_fades_mute_and_existing_audio(
    tmp_path, sources, local_renderer, family, volume, fade, other_audio,
):
    name = f"{family}-volume-{volume}-fade-{fade}"
    output = tmp_path / f"{name}.mp4"
    music = {"asset_id": "bed", "volume": volume,
             "fade_in_seconds": fade, "fade_out_seconds": fade}
    ed = {
        "version": "1.0", "render_runtime": "remotion", "renderer_family": family,
        "total_duration_seconds": 4,
        "cuts": [{"id": "c1", "source": "clip", "in_seconds": 0, "out_seconds": 4,
                  "transition_in": "cut", "transition_out": "cut"}],
        "audio": {"music": music},
    }
    if family == "explainer-data":
        # Exercise the documented legacy location on the actual Explainer path.
        ed["music"] = ed["audio"].pop("music")
    if other_audio:
        voice = {"src": str(sources / "narration-sfx.wav"), "volume": 0.6,
                 "fadeInSeconds": 0, "fadeOutSeconds": 0}
        if family == "documentary-montage":
            ed["soundtrack"] = voice
            ed["captions"] = {"words": [{"word": "AUDIO CHECK", "startMs": 0, "endMs": 4000}], "fontSize": 24}
        else:
            ed["audio"]["narration"] = voice
            ed["captions"] = [{"word": "AUDIO CHECK", "startMs": 0, "endMs": 4000}]
            ed["captionStyle"] = {"fontSize": 24}
    manifest = {"assets": [{"id": "clip", "path": str(sources / "clip.mp4")},
                           {"id": "bed", "path": str(sources / "music.wav")}]}
    result = VideoCompose().execute({
        "operation": "render", "edit_decisions": ed, "asset_manifest": manifest,
        "output_path": str(output), "profile": "music-test",
        "remotion_browser_executable": local_renderer, "remotion_concurrency": 1,
        "remotion_timeout_ms": 60000,
    })
    assert result.success, result.error
    assert result.data["staged_media_count"] == (3 if other_audio else 2)
    probe = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", str(output)]).stdout)
    assert any(s["codec_name"] == "aac" for s in probe["streams"])
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert video["width"] == 640 and video["height"] == 360
    assert abs(float(probe["format"]["duration"]) - 4) < 0.1
    samples = decode(output)
    reference = amplitude(decode(sources / "music.wav"), 880, 1.5, 2.5)
    levels = {"early": amplitude(samples, 880, 0.05, 0.25),
              "middle": amplitude(samples, 880, 1.5, 2.5),
              "late": amplitude(samples, 880, 3.75, 3.95)}
    metrics = {"name": name, "music_amplitude": levels, "reference_amplitude": reference,
               "expected_volume": volume, "duration": probe["format"]["duration"],
               "codec": "aac", "final_review": result.data["final_review"],
               "other_audio_amplitude": {str(f): amplitude(samples, f, 1.5, 2.5) for f in (220, 440)}}
    evidence = os.environ.get("OPENMONTAGE_MUSIC_EVIDENCE_DIR")
    if evidence:
        destination = Path(evidence)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, destination / output.name)
        (destination / f"{name}.json").write_text(json.dumps(metrics, indent=2))
        if other_audio:
            run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", str(output),
                 "-frames:v", "1", str(destination / f"{name}.png")])
    if volume:
        assert levels["middle"] / reference == pytest.approx(volume, rel=0.2)
        if fade:
            assert 0.03 < levels["early"] / levels["middle"] < 0.4
            assert 0.03 < levels["late"] / levels["middle"] < 0.4
        else:
            assert levels["early"] / levels["middle"] == pytest.approx(1, rel=0.2)
            assert levels["late"] / levels["middle"] == pytest.approx(1, rel=0.2)
    else:
        assert max(abs(s) for s in samples) < 0.0001
    if other_audio:
        for frequency in (220, 440):
            assert amplitude(samples, frequency, 1.5, 2.5) > 0.03
    first = run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(output),
                 "-frames:v", "1", "-f", "md5", "-"]).stdout
    last = run(["ffmpeg", "-v", "error", "-ss", "3.5", "-i", str(output),
                "-frames:v", "1", "-f", "md5", "-"]).stdout
    assert first != last, "moving source video became frozen"
