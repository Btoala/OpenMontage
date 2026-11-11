"""Offline tests. Invented fixture text is never production storyboard material."""
import copy
import importlib.util
import json
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("last_dollar_import", ROOT / "examples/the-last-dollar/production.py")
kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kit)


@pytest.fixture
def ready():
    data = kit.read_json(kit.HERE / "shots.template.json")
    data["source_confirmed"] = True
    data["characters"] = [{"id": "fixture", "identity_lock": "TEST FIXTURE ONLY"}]
    for i, shot in enumerate(data["shots"]):
        for field in ("source_ref", "location", "action", "expression", "framing", "camera",
                      "continuity_in", "continuity_out", "story_beat"):
            shot[field] = "TEST FIXTURE ONLY, NOT A RECOVERED SCENE"
        shot.update(start_frame=i * 150, duration_frames=150, character_ids=["fixture"],
                    motion_mode="ai_video", transition_out="cut")
        shot["narration"].update(status="silent", text="")
    return data


def test_unfilled_template_cannot_become_a_native_storyboard(tmp_path):
    data = kit.read_json(kit.HERE / "shots.template.json")
    report = kit.preflight(data)
    assert report["status"] == "blocked_missing_input"
    assert report["source_shots"] == 49
    with pytest.raises(ValueError):
        kit.new_project(tmp_path / "blocked", data, tmp_path, True)
    assert not (tmp_path / "blocked").exists()


def test_init_has_no_fabricated_native_artifacts_or_checkpoints(tmp_path):
    data = kit.read_json(kit.HERE / "shots.template.json")
    p = kit.new_project(tmp_path / "draft", data, tmp_path, False)
    assert not list(p.glob("checkpoint_*.json"))
    assert not list((p / "artifacts").glob("*.json"))
    assert kit.read_json(p / "planning/production.json")["approval_policy"]["paid_generation_enabled"] is False


def test_imports_native_schemas_and_backlot_reads_all_shots(ready, tmp_path):
    from backlot.state import load_board_state
    p = kit.new_project(tmp_path / "test-only", ready, tmp_path, True)
    for name in ("script", "scene_plan", "asset_manifest"):
        kit.validate_native(name, kit.read_json(p / "artifacts" / (name + ".json")))
    assert len(kit.read_json(p / "artifacts/scene_plan.json")["scenes"]) == 49
    state = load_board_state(p)
    assert len(state["storyboard"]["scenes"]) == 49
    assert not list(p.glob("checkpoint_*.json"))


@pytest.mark.parametrize("change", [
    lambda d: d["shots"].pop(),
    lambda d: d["shots"][1].update(id="SH001"),
    lambda d: d["shots"][1].update(start_frame=149),
    lambda d: d["shots"][1].update(start_frame=151),
    lambda d: d["shots"][0].update(start_frame=False),
    lambda d: d["shots"][0].update(duration_frames=-1),
    lambda d: d["shots"][0].update(character_ids=["unknown"]),
    lambda d: d["shots"][0].update(motion_mode="still_pan"),
    lambda d: d["shots"][0]["narration"].update(status="unrecovered"),
    lambda d: d["shots"][0]["narration"].update(text="guess"),
    lambda d: d.update(source_confirmed=False),
    lambda d: d.update(aspect_ratio="16:9"),
])
def test_incomplete_or_changed_contract_is_rejected(ready, change):
    change(ready)
    assert kit.ready_errors(ready)


def test_narration_and_foley_offsets_survive_mapping(ready):
    shot = ready["shots"][2]
    shot["narration"].update(status="recovered", text="TEST LINE", source_ref="test-only",
                              offset_frames=15, duration_frames=60)
    shot["audio_cues"] = [{"id": "test-coin", "kind": "sfx", "description": "TEST ONLY",
                            "offset_frames": 90, "duration_frames": 30, "gain_db": -8,
                            "fade_in_frames": 0, "fade_out_frames": 10}]
    out = kit.compile_artifacts(ready)
    assert [c["start_frame"] for c in out["audio_timeline"]["cues"]] == [315, 390]
    assert out["script"]["sections"][2]["text"] == "TEST LINE"
    assert out["scene_plan"]["metadata"]["shot_details"][2]["continuity_in"] == shot["continuity_in"]
    assert out["scene_plan"]["metadata"]["burn_captions"] is False


def test_narration_cannot_spill_out_of_shot(ready):
    ready["shots"][0]["narration"].update(status="recovered", text="test", source_ref="test",
                                         offset_frames=100, duration_frames=60)
    assert any("narration timing" in e for e in kit.ready_errors(ready))


def test_existing_project_is_preserved(ready, tmp_path):
    p = tmp_path / "existing"
    p.mkdir()
    original = p / "asset.txt"
    original.write_text("do not overwrite")
    before = kit.digest(original)
    with pytest.raises(FileExistsError):
        kit.new_project(p, ready, tmp_path, True)
    assert kit.digest(original) == before


def test_existing_symlink_is_rejected(ready, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(FileExistsError):
        kit.new_project(link, ready, tmp_path, True)


def test_input_asset_is_copied_unchanged_and_hashed(ready, tmp_path):
    # Arbitrary fixture bytes test copying only, not image quality/probing.
    source = tmp_path / "reference.png"
    source.write_bytes(b"TEST FIXTURE BYTES")
    ready["shots"][0]["reference_paths"] = [source.name]
    before = kit.digest(source)
    p = kit.new_project(tmp_path / "copy", ready, tmp_path, True)
    entry = kit.read_json(p / "planning/asset_index.json")[0]
    assert kit.digest(p / entry["path"]) == before == kit.digest(source)
    assert "cost_usd" not in kit.read_json(p / "artifacts/asset_manifest.json")["assets"][0]


@pytest.mark.parametrize("raw", ["../escape.mp4", "/etc/passwd", "https://example.com/file.png", "missing.png"])
def test_escaping_or_missing_assets_are_rejected(ready, tmp_path, raw):
    ready["shots"][0]["reference_paths"] = [raw]
    assert kit.ready_errors(ready, tmp_path)


def test_offline_commands_never_connect(ready, tmp_path, monkeypatch):
    def no_connect(*args, **kwargs):
        raise AssertionError("Offline import attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", no_connect)
    kit.preflight(ready)
    kit.cost_scenarios()
    kit.new_project(tmp_path / "offline", ready, tmp_path, True)


def test_zero_budget_native_configuration_blocks_a_paid_reservation():
    from lib.config_model import OpenMontageConfig
    from tools.cost_tracker import CostTracker, ApprovalRequiredError
    cfg = OpenMontageConfig.load(kit.HERE / "config.preflight.yaml")
    tracker = CostTracker(budget_total_usd=cfg.budget.total_usd,
                          reserve_pct=cfg.budget.reserve_pct,
                          single_action_approval_usd=cfg.budget.single_action_approval_usd,
                          require_approval_for_new_paid_tool=True, mode=cfg.budget.mode)
    entry = tracker.estimate("test-provider", "test", 0.01)
    with pytest.raises(ApprovalRequiredError):
        tracker.reserve(entry)
    assert tracker.budget_spent_usd == tracker.budget_reserved_usd == 0
