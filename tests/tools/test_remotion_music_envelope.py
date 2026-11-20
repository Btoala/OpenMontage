"""Execute production audio curves and a staged-input FFmpeg proof, offline.

The FFmpeg proof exercises the Python adapter/staging and actual JSX envelopes.
It is NOT a full Remotion video render; that separate opt-in suite needs a
working browser. It must never be reported as end-to-end Remotion evidence.
"""

import array
import json
import math
import os
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from tools.video.video_compose import VideoCompose


ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(__file__).with_name("remotion_music_envelope.cjs")
NODE_READY = shutil.which("node") and (ROOT / "remotion-composer/node_modules/typescript").is_dir()
pytestmark = pytest.mark.skipif(not NODE_READY, reason="existing Node/Remotion packages required; no auto-install")


def envelope(family, music):
    process = subprocess.run(
        ["node", str(HELPER)], input=json.dumps({"family": family, "music": music, "fps": 30, "frames": 120}),
        text=True, capture_output=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


@pytest.mark.parametrize("family", ["documentary-montage", "explainer-data"])
@pytest.mark.parametrize("volume,fade_in,fade_out", [(0.5, 1, 1), (0.25, 0, 0), (0, 0, 0), (1, 0, 1), (1, 1, 0), (0.4, 4, 4)])
def test_actual_renderer_volume_and_fade_expressions(family, volume, fade_in, fade_out):
    values = envelope(family, {"src": "bed.wav", "volume": volume,
                              "fadeInSeconds": fade_in, "fadeOutSeconds": fade_out})["volumes"]
    assert all(math.isfinite(v) and 0 <= v <= volume for v in values)
    assert values[0] == (0 if fade_in else volume)
    assert values[15] == pytest.approx(volume * min(1, 0.5 / fade_in if fade_in else 1,
                                                 3.5 / fade_out if fade_out else 1))
    assert values[60] == pytest.approx(volume * min(1, 2 / fade_in if fade_in else 1,
                                                 2 / fade_out if fade_out else 1))
    assert values[105] == pytest.approx(volume * min(1, 3.5 / fade_in if fade_in else 1,
                                                  0.5 / fade_out if fade_out else 1))


@pytest.mark.parametrize("family,default", [("documentary-montage", 0.15), ("explainer-data", 0.1)])
def test_actual_renderer_defaults_stay_unchanged(family, default):
    values = envelope(family, {"src": "bed.wav", "fadeInSeconds": 0, "fadeOutSeconds": 0})["volumes"]
    assert values == [default] * 120


def tone(path, frequencies):
    samples = array.array("h", (
        round(32767 * sum(0.1 * math.sin(2 * math.pi * f * i / 48000) for f in frequencies))
        for i in range(4 * 48000)
    ))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(samples.tobytes())


def frequency_amplitude(samples, frequency, start, end):
    values = samples[round(start * 48000):round(end * 48000)]
    step = 2 * math.pi * frequency / 48000
    real = sum(v * math.cos(step * i) for i, v in enumerate(values))
    imaginary = sum(v * math.sin(step * i) for i, v in enumerate(values))
    return 2 * math.hypot(real, imaginary) / len(values)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="local FFmpeg required")
@pytest.mark.parametrize("family", ["documentary-montage", "explainer-data"])
def test_ffmpeg_proof_uses_staged_source_and_production_envelope(tmp_path, monkeypatch, family):
    monkeypatch.setenv("OPENMONTAGE_ASSET_CACHE", "0")
    monkeypatch.setattr(VideoCompose, "_remotion_available", lambda self: True)
    music_path = tmp_path / "music.wav"
    tone(music_path, [880])
    output = tmp_path / "adapter-only.mp4"
    proof = tmp_path / f"ffmpeg-staged-{family}.mp4"
    captured = {}

    def capture(self, command, **kwargs):
        # Substitute only the CLI for inspection; never pretend this is a render.
        props_path = Path(next(x.split("=", 1)[1] for x in command if x.startswith("--props=")))
        public_dir = Path(next(x.split("=", 1)[1] for x in command if x.startswith("--public-dir=")))
        props = json.loads(props_path.read_text())
        music = props["music"] if family == "documentary-montage" else props["audio"]["music"]
        captured["music"] = music
        shutil.copy2(public_dir / music["src"], tmp_path / "staged.wav")
        output.write_bytes(b"stub: not video")

    monkeypatch.setattr(VideoCompose, "run_command", capture)
    config = {"asset_id": "bed", "volume": 0.5, "fade_in_seconds": 1, "fade_out_seconds": 1}
    result = VideoCompose()._remotion_render({
        "output_path": str(output),
        "edit_decisions": {"renderer_family": family, "audio": {"music": config},
                           "cuts": [{"id": "t", "type": "text_card", "text": "Audio test",
                                     "source": "", "in_seconds": 0, "out_seconds": 4}]},
        "asset_manifest": {"assets": [{"id": "bed", "path": str(music_path)}]},
    })
    assert result.success, result.error
    assert result.data["staged_media_count"] == 1
    curve = envelope(family, captured["music"])["volumes"]
    with wave.open(str(tmp_path / "staged.wav"), "rb") as source:
        music_samples = array.array("h")
        music_samples.frombytes(source.readframes(source.getnframes()))
    # Sample the actual JSX envelope at each video frame. The extra frequencies
    # are synthetic stand-ins for an existing narration/SFX mix, not speech.
    mixed = array.array("h", (
        round(value * curve[min(i // 1600, 119)]
              + 32767 * 0.06 * math.sin(2 * math.pi * 220 * i / 48000)
              + 32767 * 0.06 * math.sin(2 * math.pi * 440 * i / 48000))
        for i, value in enumerate(music_samples)
    ))
    with wave.open(str(tmp_path / "mix.wav"), "wb") as dest:
        dest.setnchannels(1)
        dest.setsampwidth(2)
        dest.setframerate(48000)
        dest.writeframes(mixed.tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=duration=4:size=640x360:rate=30", "-i", str(tmp_path / "mix.wav"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(proof)],
                   check=True, capture_output=True, timeout=30)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
                                               "-show_format", "-of", "json", str(proof)]))
    assert any(s["codec_name"] == "aac" for s in probe["streams"])
    assert abs(float(probe["format"]["duration"]) - 4) < 0.1
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(proof), "-vn",
                                   "-ac", "1", "-ar", "48000", "-f", "f32le", "-"])
    decoded = array.array("f")
    decoded.frombytes(raw)
    levels = {"early": frequency_amplitude(decoded, 880, 0.05, 0.25),
              "middle": frequency_amplitude(decoded, 880, 1.5, 2.5),
              "late": frequency_amplitude(decoded, 880, 3.75, 3.95)}
    assert levels["middle"] == pytest.approx(0.05, rel=0.1)
    assert 0.03 < levels["early"] / levels["middle"] < 0.3
    assert 0.03 < levels["late"] / levels["middle"] < 0.3
    other = {str(f): frequency_amplitude(decoded, f, 1.5, 2.5) for f in (220, 440)}
    assert all(v == pytest.approx(0.06, rel=0.1) for v in other.values())
    volume_run = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(proof), "-af",
                                 "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=30)
    assert volume_run.returncode == 0
    evidence = os.environ.get("OPENMONTAGE_MUSIC_EVIDENCE_DIR")
    if evidence:
        destination = Path(evidence)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proof, destination / proof.name)
        metrics = {"test_type": "FFmpeg proof from staged source + production JSX envelope; NOT a Remotion render",
                   "family": family, "music_frequency_hz": 880, "music_amplitudes": levels,
                   "other_tone_amplitudes": other, "duration_seconds": probe["format"]["duration"],
                   "volume_detect": [line for line in volume_run.stderr.splitlines() if "_volume:" in line]}
        (destination / f"{proof.stem}.json").write_text(json.dumps(metrics, indent=2))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", str(proof),
                        "-frames:v", "1", str(destination / f"{proof.stem}.png")],
                       check=True, capture_output=True, timeout=30)
