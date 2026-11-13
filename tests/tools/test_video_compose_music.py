"""Offline contracts for documented Remotion music (issue #937).

CLI execution is stubbed here; real decoded-audio tests live in
test_video_compose_music_render.py. No provider discovery or API calls.
"""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools.video.video_compose import VideoCompose


@pytest.fixture
def capture_render(monkeypatch):
    captured = {}
    monkeypatch.setenv("OPENMONTAGE_ASSET_CACHE", "0")
    monkeypatch.setattr(VideoCompose, "_remotion_available", lambda self: True)
    monkeypatch.setattr("tools.video.video_compose.shutil.which", lambda name: name)
    monkeypatch.setattr(VideoCompose, "_run_final_review", lambda *a, **kw: {"status": "pass"})

    def run(self, command, **kwargs):
        captured["command"] = command
        props_path = Path(next(a.split("=", 1)[1] for a in command if a.startswith("--props=")))
        captured["props"] = json.loads(props_path.read_text())
        public_arg = next((a for a in command if a.startswith("--public-dir=")), None)
        if public_arg:
            public_dir = Path(public_arg.split("=", 1)[1])
            captured["public_dir"] = public_dir
            captured["files"] = {p.name: p.read_bytes() for p in public_dir.rglob("*") if p.is_file()}
        Path(command[5]).write_bytes(b"mock render, not audiovisual evidence")

    monkeypatch.setattr(VideoCompose, "run_command", run)
    return captured


def render_inputs(tmp_path, music, *, legacy=False, family="documentary-montage"):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    ed = {
        "renderer_family": family,
        "render_runtime": "remotion",
        "cuts": [{"id": "clip", "source": "clip", "in_seconds": 0, "out_seconds": 4}],
    }
    if legacy:
        ed["music"] = music
    else:
        ed["audio"] = {"music": music}
    return {
        "operation": "render",
        "output_path": str(tmp_path / "output.mp4"),
        "edit_decisions": ed,
        "asset_manifest": {"assets": [{"id": "clip", "path": str(clip)}]},
    }


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("family", ["documentary-montage", "explainer-data"])
def test_music_asset_reaches_both_compositions_and_stages_once(tmp_path, capture_render, legacy, family):
    bed = tmp_path / "bed with space.wav"
    bed.write_bytes(b"music")
    config = {"asset_id": "bed", "volume": 0.35, "fade_in_seconds": 1, "fade_out_seconds": 2}
    inputs = render_inputs(tmp_path, config, legacy=legacy, family=family)
    inputs["asset_manifest"]["assets"].append({"id": "bed", "path": str(bed)})
    original = copy.deepcopy(inputs)
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    props = capture_render["props"]
    assert props["music"] == props["audio"]["music"]
    assert props["music"]["volume"] == 0.35
    assert props["music"]["fadeInSeconds"] == 1
    assert props["music"]["fadeOutSeconds"] == 2
    assert capture_render["files"][props["music"]["src"]] == b"music"
    assert result.data["staged_media_count"] == 2
    assert inputs == original
    assert bed.read_bytes() == b"music"
    assert not capture_render["public_dir"].exists()


@pytest.mark.parametrize("source_key", ["src", "source", "path"])
@pytest.mark.parametrize("as_uri", [False, True])
def test_direct_operation_resolves_source_aliases_and_file_uris(tmp_path, capture_render, source_key, as_uri):
    music = tmp_path / "music with spaces.wav"
    music.write_bytes(b"audio")
    inputs = render_inputs(tmp_path, {source_key: music.as_uri() if as_uri else str(music)})
    inputs["operation"] = "remotion_render"
    inputs["edit_decisions"]["cuts"][0]["source"] = inputs["asset_manifest"]["assets"][0]["path"]
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert capture_render["files"][capture_render["props"]["music"]["src"]] == b"audio"


def test_direct_operation_resolves_manifest_id(tmp_path, capture_render):
    music = tmp_path / "music.wav"
    music.write_bytes(b"audio")
    inputs = render_inputs(tmp_path, {"asset_id": "bed"})
    inputs["operation"] = "remotion_render"
    inputs["asset_manifest"]["assets"].append({"id": "bed", "path": str(music)})
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert capture_render["files"][capture_render["props"]["music"]["src"]] == b"audio"


@pytest.mark.parametrize("music", [{"asset_id": "absent"}, {"src": "absent.wav"}, {"path": "absent.wav"}])
def test_missing_music_fails_before_cli(tmp_path, capture_render, music):
    result = VideoCompose().execute(render_inputs(tmp_path, music))
    assert not result.success
    assert "Music" in result.error and ("not found" in result.error)
    assert "command" not in capture_render
    assert not (tmp_path / "output.mp4").exists()
    assert not list(tmp_path.glob(".remotion-public-*"))


@pytest.mark.parametrize("path", [None, "", 12])
def test_manifest_without_valid_path_is_an_error(path):
    resolved, error = VideoCompose._resolve_music({"audio": {"music": {"asset_id": "bed"}}}, {"bed": {"path": path}})
    assert resolved is None
    assert "no valid path" in error


def test_unknown_asset_id_cannot_fall_back_to_filename_or_src(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bed").write_bytes(b"unregistered")
    resolved, error = VideoCompose._resolve_music({"music": {"asset_id": "bed", "src": "bed"}}, {})
    assert resolved is None
    assert "not found in asset_manifest" in error


@pytest.mark.parametrize("kind", ["missing", "directory", "missing_file_uri"])
def test_manifest_path_must_be_a_file(tmp_path, capture_render, kind):
    path = tmp_path / "bed.wav"
    if kind == "directory":
        path.mkdir()
    source = path.as_uri() if kind == "missing_file_uri" else str(path)
    inputs = render_inputs(tmp_path, {"asset_id": "bed"})
    inputs["asset_manifest"]["assets"].append({"id": "bed", "path": source})
    result = VideoCompose().execute(inputs)
    assert not result.success and "Music file not found" in result.error
    assert "command" not in capture_render


@pytest.mark.parametrize("value", [0, 0.25, 1])
def test_valid_volume_including_explicit_mute(value):
    result, error = VideoCompose._resolve_music({"music": {"src": "bed.wav", "volume": value}}, {})
    assert error is None and result["volume"] == value


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), "quiet", None, True])
def test_invalid_volume_is_rejected(value):
    result, error = VideoCompose._resolve_music({"music": {"src": "bed.wav", "volume": value}}, {})
    assert result is None and "volume" in error


@pytest.mark.parametrize("field", ["fade_in_seconds", "fade_out_seconds", "fadeInSeconds", "fadeOutSeconds"])
@pytest.mark.parametrize("value", [-1, float("nan"), "one", None])
def test_invalid_fades_are_rejected(field, value):
    result, error = VideoCompose._resolve_music({"music": {"src": "bed.wav", field: value}}, {})
    assert result is None and field in error


def test_zero_fades_snake_precedence_and_existing_options():
    config = {"src": "bed.wav", "fade_in_seconds": 0, "fadeInSeconds": 99,
              "fade_out_seconds": 0, "fadeOutSeconds": 99, "volume": 0,
              "offsetSeconds": 2, "loop": True, "ducking": False, "custom": "keep"}
    result, error = VideoCompose._resolve_music({"music": config}, {})
    assert error is None
    assert result["fadeInSeconds"] == result["fadeOutSeconds"] == result["volume"] == 0
    assert result["loop"] is True and result["offsetSeconds"] == 2
    assert result["ducking"] is False and result["custom"] == "keep"
    assert config["fadeInSeconds"] == 99


def test_omitted_settings_keep_renderer_defaults():
    result, error = VideoCompose._resolve_music({"music": {"src": "bed.wav"}}, {})
    assert error is None
    assert "volume" not in result and "fadeInSeconds" not in result and "fadeOutSeconds" not in result


@pytest.mark.parametrize("canonical", [{"src": "canonical.wav"}, {}, None])
def test_canonical_block_overrides_legacy_even_when_empty(canonical):
    result, error = VideoCompose._resolve_music({"audio": {"music": canonical}, "music": {"src": "legacy.wav"}}, {})
    assert error is None
    assert result == (canonical or None)


@pytest.mark.parametrize("music", ["bad", [], 0, False, {"volume": 0.2}, {"asset_id": ""}])
def test_malformed_configuration_does_not_silently_disappear(music):
    result, error = VideoCompose._resolve_music({"music": music}, {})
    assert result is None and error


def test_existing_public_relative_music_remains_playable(tmp_path, capture_render):
    public = tmp_path / "public"
    (public / "audio").mkdir(parents=True)
    (public / "audio" / "bed.wav").write_bytes(b"pre-staged")
    inputs = render_inputs(tmp_path, {"src": "audio/bed.wav"})
    inputs["public_dir"] = str(public)
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    assert capture_render["props"]["music"]["src"] == "audio/bed.wav"
    assert (public / "audio" / "bed.wav").read_bytes() == b"pre-staged"


@pytest.mark.parametrize("source", ["https://example.invalid/bed.mp3", "data:audio/wav;base64,AAAA"])
def test_remote_sources_are_forwarded_without_python_fetch(tmp_path, capture_render, source):
    result = VideoCompose().execute(render_inputs(tmp_path, {"src": source}))
    assert result.success, result.error
    assert capture_render["props"]["music"]["src"] == source


def test_preserves_narration_sound_effects_captions_and_video(tmp_path, capture_render):
    files = {}
    for name in ("music", "narration", "sfx"):
        files[name] = tmp_path / f"{name}.wav"
        files[name].write_bytes(name.encode())
    inputs = render_inputs(tmp_path, {"src": str(files["music"])})
    ed = inputs["edit_decisions"]
    ed["audio"]["narration"] = {"src": str(files["narration"]), "volume": 0.8}
    ed["audio"]["sfx"] = [{"src": str(files["sfx"]), "start_seconds": 1}]
    ed["soundtrack"] = {"src": str(files["narration"]), "volume": 0.8}
    ed["captions"] = {"words": [{"word": "Keep", "startMs": 0, "endMs": 500}]}
    ed["subtitles"] = {"caption_props": {"fontSize": 40}}
    original = copy.deepcopy(inputs)
    result = VideoCompose().execute(inputs)
    assert result.success, result.error
    props = capture_render["props"]
    for field in (props["audio"]["narration"], props["soundtrack"]):
        assert capture_render["files"][field["src"]] == b"narration"
        assert field["volume"] == 0.8
    assert capture_render["files"][props["audio"]["sfx"][0]["src"]] == b"sfx"
    assert props["captions"] == ed["captions"]
    assert props["captionProps"] == {"fontSize": 40}
    assert props["scenes"][0]["durationSeconds"] == 4
    assert result.data["staged_media_count"] == 4
    assert inputs == original


def test_render_failure_cleans_music_and_keeps_original(tmp_path, capture_render, monkeypatch):
    music = tmp_path / "music.wav"
    music.write_bytes(b"keep")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "remotion", stderr="synthetic failure")

    monkeypatch.setattr(VideoCompose, "run_command", fail)
    result = VideoCompose().execute(render_inputs(tmp_path, {"src": str(music)}))
    assert not result.success and "synthetic failure" in result.error
    assert music.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".remotion-public-*"))
    assert not (tmp_path / ".remotion_props.json").exists()


def test_cache_does_not_reuse_old_silent_render():
    current, previous = VideoCompose(), VideoCompose()
    previous.version = "0.1.0"
    inputs = {"operation": "render", "edit_decisions": {"audio": {"music": {"asset_id": "bed"}}}}
    assert current.cache_key(inputs) != previous.cache_key(inputs)
