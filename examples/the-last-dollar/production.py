#!/usr/bin/env python3
"""Offline import/preflight utility. Never submits, uploads, purchases or renders.

This is artifact preparation for OpenMontage's existing animation pipeline,
not a second orchestrator. Production remains governed by AGENT_GUIDE.md.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHOT_IDS = [f"SH{i:03d}" for i in range(1, 50)]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def local_file(base, raw):
    """Resolve existing regular files within the explicitly supplied input root."""
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError("Asset path must be a nonempty relative path")
    base = Path(base).resolve()
    path = (base / raw).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError(f"Missing or escaping local asset: {raw}")
    return path


def is_frames(value, minimum=0):
    return type(value) is int and value >= minimum


def ready_errors(data, asset_root=None):
    """Fail closed on incomplete story, discontinuous timing, or lost cue data."""
    errors = []
    if not isinstance(data, dict):
        return ["Input must be a JSON object"]
    if data.get("version") != "1.0":
        errors.append("version must be 1.0")
    if data.get("source_confirmed") is not True:
        errors.append("source_confirmed must explicitly confirm the recovered 49-shot source")
    if data.get("aspect_ratio") != "9:16":
        errors.append("aspect_ratio must preserve the approved 9:16 framing")
    fps = data.get("fps")
    if fps not in (24, 25, 30):
        errors.append("fps must be an explicit 24, 25 or 30")
        fps = 30
    shots = data.get("shots")
    if not isinstance(shots, list):
        return errors + ["shots must be an array"]
    if [s.get("id") if isinstance(s, dict) else None for s in shots] != SHOT_IDS:
        errors.append("Exactly 49 shots, in order SH001..SH049, are required")
    characters = data.get("characters", [])
    if not isinstance(characters, list):
        return errors + ["characters must be an array"]
    character_ids = [c.get("id") for c in characters if isinstance(c, dict)]
    if len(character_ids) != len(set(character_ids)):
        errors.append("Duplicate character IDs")
    for c in characters:
        if not isinstance(c, dict) or not c.get("id") or not c.get("identity_lock"):
            errors.append("Every character needs id and identity_lock")
    cursor = 0
    cue_ids = set()
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"Shot at index {index} must be an object")
            continue
        sid = shot.get("id", f"index-{index}")
        for key in ("source_ref", "location", "action", "expression", "camera",
                    "framing", "continuity_in", "continuity_out", "story_beat"):
            if not isinstance(shot.get(key), str) or not shot[key].strip():
                errors.append(f"{sid}: missing {key}; use explicit 'N/A: reason' when appropriate")
        if not is_frames(shot.get("start_frame")) or shot.get("start_frame") != cursor:
            errors.append(f"{sid}: start_frame must be {cursor}; gaps/overlaps are not inferred")
        duration = shot.get("duration_frames")
        if not is_frames(duration, 1):
            errors.append(f"{sid}: duration_frames must be a positive integer")
            duration = 0
        ids = shot.get("character_ids")
        if not isinstance(ids, list) or any(c not in character_ids for c in ids):
            errors.append(f"{sid}: character_ids must reference the character bible (or [] for an insert)")
        if shot.get("transition_out") not in ("cut", "fade"):
            errors.append(f"{sid}: transition_out must be cut or fade")
        if shot.get("motion_mode") not in ("ai_video", "provided_video"):
            errors.append(f"{sid}: motion_mode must be ai_video or provided_video; still-only substitution is not approved")
        narration = shot.get("narration", {})
        if not isinstance(narration, dict):
            narration = {}
        status = narration.get("status")
        if status == "silent":
            if narration.get("text") != "":
                errors.append(f"{sid}: explicit silence requires empty text")
            if narration.get("audio_path") or narration.get("words_path"):
                errors.append(f"{sid}: silent shot cannot silently carry narration assets")
        elif status == "recovered":
            if not isinstance(narration.get("text"), str) or not narration["text"].strip():
                errors.append(f"{sid}: recovered narration needs exact source text")
            if not narration.get("source_ref"):
                errors.append(f"{sid}: narration needs its source_ref")
            offset, length = narration.get("offset_frames"), narration.get("duration_frames")
            if not is_frames(offset) or not is_frames(length, 1) or offset + length > duration:
                errors.append(f"{sid}: narration timing must fit inside its shot")
        else:
            errors.append(f"{sid}: narration must be recovered or explicitly silent, never guessed")
        for field in ("reference_paths", "video_paths"):
            paths = shot.get(field, [])
            if not isinstance(paths, list):
                errors.append(f"{sid}: {field} must be an array")
                continue
            for raw in paths:
                if asset_root is not None:
                    try:
                        local_file(asset_root, raw)
                    except ValueError as exc:
                        errors.append(f"{sid}: {exc}")
        if shot.get("motion_mode") == "provided_video" and not shot.get("video_paths"):
            errors.append(f"{sid}: provided_video needs at least one actual video file")
        cues = shot.get("audio_cues", [])
        if not isinstance(cues, list):
            errors.append(f"{sid}: audio_cues must be an array")
            cues = []
        for cue in cues:
            if not isinstance(cue, dict):
                errors.append(f"{sid}: each audio cue must be an object")
                continue
            cid = cue.get("id")
            if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", cid) or cid in cue_ids:
                errors.append(f"{sid}: cue id must be unique and filename-safe")
            cue_ids.add(cid)
            start, length = cue.get("offset_frames"), cue.get("duration_frames")
            if not is_frames(start) or not is_frames(length, 1) or start + length > duration:
                errors.append(f"{sid}: cue {cid} must fit shot; split a cross-shot ambience into linked cues")
            if cue.get("kind") not in ("sfx", "music", "ambience") or not cue.get("description"):
                errors.append(f"{sid}: cue {cid} needs kind and description")
            if not isinstance(cue.get("gain_db"), (int, float)) or isinstance(cue.get("gain_db"), bool) or not math.isfinite(cue["gain_db"]):
                errors.append(f"{sid}: cue {cid} needs finite gain_db")
            for field in ("fade_in_frames", "fade_out_frames"):
                fade = cue.get(field, 0)
                if not is_frames(fade) or (is_frames(length) and fade > length):
                    errors.append(f"{sid}: cue {cid} invalid {field}")
        for item in [narration, *cues]:
            for field in ("audio_path", "words_path"):
                if item.get(field) and asset_root is not None:
                    try:
                        local_file(asset_root, item[field])
                    except ValueError as exc:
                        errors.append(f"{sid}: {exc}")
        cursor += duration
    if not 180 <= cursor / fps <= 300:
        errors.append(f"Runtime {cursor / fps:.3f}s must be within the requested 180–300s")
    return errors


def validate_native(name, data):
    from jsonschema import Draft202012Validator
    schema = read_json(ROOT / "schemas" / "artifacts" / f"{name}.schema.json")
    Draft202012Validator(schema).validate(data)


def compile_artifacts(data):
    errors = ready_errors(data)
    if errors:
        raise ValueError("\n".join(errors))
    fps = data["fps"]
    sections, scenes, audio_cues = [], [], []
    for shot in data["shots"]:
        sid, start = shot["id"], shot["start_frame"] / fps
        end = (shot["start_frame"] + shot["duration_frames"]) / fps
        narration = shot["narration"]
        sections.append({"id": sid, "label": shot["story_beat"],
                         "text": narration["text"], "start_seconds": start, "end_seconds": end,
                         "source_ref": narration.get("source_ref") or shot["source_ref"],
                         "speaker_directions": "C. Jonathan; soft, sad, restrained. Narrate only recovered text."})
        scenes.append({"id": sid, "type": "generated" if shot["motion_mode"] == "ai_video" else "broll",
                       "description": shot["action"], "start_seconds": start, "end_seconds": end,
                       "script_section_id": sid, "framing": shot["framing"], "movement": shot["camera"],
                       "transition_out": shot["transition_out"], "overlay_notes": "No designed text overlays or burned captions.",
                       "shot_intent": shot["story_beat"],
                       "required_assets": [{"type": "video", "description": f"{sid}: {shot['action']}",
                                            "source": "generate" if shot["motion_mode"] == "ai_video" else "provided"}]})
        if narration["status"] == "recovered":
            audio_cues.append({"id": f"{sid}-narration", "scene_id": sid, "kind": "narration",
                              "text": narration["text"], "start_frame": shot["start_frame"] + narration["offset_frames"],
                              "duration_frames": narration["duration_frames"], "gain_db": 0,
                              "audio_path": narration.get("audio_path"), "words_path": narration.get("words_path"),
                              "timing_status": "provided_not_probed" if narration.get("audio_path") else "planned"})
        for cue in shot["audio_cues"]:
            timed = copy.deepcopy(cue)
            timed.update(scene_id=sid, start_frame=shot["start_frame"] + cue["offset_frames"])
            audio_cues.append(timed)
    meta = {"status": "imported_draft_not_approved", "source": "inputs/shots.json",
            "aspect_ratio": "9:16", "fps": fps, "pipeline": "animation",
            "audio_cues": "planning/audio_timeline.json", "paid_generation_authorized": False}
    script = {"version": "1.0", "title": "The Last Dollar", "total_duration_seconds": end,
              "sections": sections, "metadata": meta,
              "voice_performance": {"performance_intent": "Sparse, soft, sad narration; C. Jonathan.",
                                    "pacing_profile": "contemplative", "pause_policy": "Preserve silent action and breathing room."}}
    plan = {"version": "1.0", "scenes": scenes,
            "metadata": {**meta, "animation_mode": "ai_video", "characters": data["characters"],
                         "shot_details": data["shots"], "overlays": [], "burn_captions": False}}
    assets = {"version": "1.0", "assets": [], "metadata": {"status": "empty_no_generated_assets"}}
    for name, obj in (("script", script), ("scene_plan", plan), ("asset_manifest", assets)):
        validate_native(name, obj)
    return {"script": script, "scene_plan": plan, "asset_manifest": assets,
            "audio_timeline": {"version": "1.0", "fps": fps, "cues": audio_cues,
                               "mix_status": "not_rendered", "master_gain_db": None,
                               "speech_ducking_required": True}}


def copy_assets(data, asset_root, target, artifacts):
    """Copy referenced bytes into a NEW draft; retain original inputs and hashes."""
    index = []
    mapping = {}
    for shot in data["shots"]:
        sid = shot["id"]
        refs = [(p, "image") for p in shot["reference_paths"]]
        refs += [(p, "video") for p in shot["video_paths"]]
        n = shot["narration"]
        if n.get("audio_path"):
            refs.append((n["audio_path"], "narration"))
        if n.get("words_path"):
            refs.append((n["words_path"], "alignment"))
        for cue in shot["audio_cues"]:
            if cue.get("audio_path"):
                refs.append((cue["audio_path"], "music" if cue["kind"] == "music" else "sfx"))
        for number, (raw, kind) in enumerate(refs, 1):
            source = local_file(asset_root, raw)
            sha = digest(source)
            relative = f"assets/imported/{sha}{source.suffix.lower()}"
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                with dest.open("xb") as stream, source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, stream)
            if digest(dest) != sha:
                raise ValueError("Copied asset digest mismatch")
            mapping[raw] = relative
            index.append({"scene_id": sid, "kind": kind, "source_relative_path": raw,
                          "path": relative, "sha256": sha, "size_bytes": source.stat().st_size})
            if kind != "alignment":
                artifacts["asset_manifest"]["assets"].append({"id": f"{sid}-import-{number:03d}",
                    "type": kind, "path": relative, "scene_id": sid, "source_tool": "provided_local_import",
                    "generation_summary": "Existing local asset copied without alteration; original cost and license not inferred."})
    for cue in artifacts["audio_timeline"]["cues"]:
        for key in ("audio_path", "words_path"):
            if cue.get(key):
                cue[key] = mapping[cue[key]]
    artifacts["asset_manifest"]["metadata"] = {"status": "imported_only_not_generated", "hash_index": "planning/asset_index.json"}
    validate_native("asset_manifest", artifacts["asset_manifest"])
    return index


def new_project(dest, source_data, asset_root, compile_ready):
    dest = Path(dest).absolute()
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing destination: {dest}")
    artifacts = None
    if compile_ready:
        errors = ready_errors(source_data, asset_root)
        if errors:
            raise ValueError("\n".join(errors))
        artifacts = compile_artifacts(source_data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Stage completely, then reserve the final directory exclusively; no replace/merge.
    with tempfile.TemporaryDirectory(prefix=".last-dollar-import-", dir=dest.parent) as temp:
        stage = Path(temp)
        for part in ("inputs", "planning", "artifacts", "assets/images", "assets/video", "assets/audio", "assets/music", "renders"):
            (stage / part).mkdir(parents=True, exist_ok=True)
        write_new(stage / "project.json", {"version": "1.0", "project_id": dest.name,
            "title": "The Last Dollar — import preparation", "pipeline_type": "animation",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "setup_status": "draft_plan_imported" if compile_ready else "awaiting_original_49_shots"})
        write_new(stage / "inputs/shots.json", source_data)
        for name in ("production.json", "character-lock.json", "approval-request.template.json", "cost-model.json"):
            shutil.copyfile(HERE / name, stage / "planning" / name)
        shutil.copyfile(HERE / "config.preflight.yaml", stage / "planning/config.preflight.yaml")
        if artifacts:
            index = copy_assets(source_data, asset_root, stage, artifacts)
            write_new(stage / "planning/asset_index.json", index)
            for name in ("script", "scene_plan", "asset_manifest"):
                write_new(stage / "artifacts" / f"{name}.json", artifacts[name])
            write_new(stage / "planning/audio_timeline.json", artifacts["audio_timeline"])
        dest.mkdir(exist_ok=False)
        try:
            for child in stage.iterdir():
                shutil.move(str(child), str(dest / child.name))
        except Exception:
            # Leave this new, partial destination intact for review; never delete user files.
            raise
    return dest


def preflight(data, asset_root=None):
    errors = ready_errors(data, asset_root)
    return {"version": "1.0", "status": "blocked_missing_input" if errors else "draft_import_ready",
            "source_shots": len(data.get("shots", [])), "errors": errors,
            "binary_presence": {n: bool(shutil.which(n)) for n in ("python3", "node", "ffmpeg", "ffprobe")},
            "paid_generation_authorized": False, "generation_calls": 0,
            "note": "Import readiness is not render readiness, approval, or proof of provider access."}


def cost_scenarios():
    model = read_json(HERE / "cost-model.json")
    result = []
    for provider in model["routes"]:
        for requested_seconds in (245, 343, 490):
            billed = requested_seconds + provider["rounding_reserve_seconds_per_shot"] * 49
            row = {"route": provider["id"], "requested_seconds_per_pass": requested_seconds,
                   "reserved_billable_seconds_per_pass": billed}
            for attempts in (1, 1.5, 2):
                row[f"motion_usd_{attempts}x"] = round(billed * provider["usd_per_second"] * attempts, 4)
            result.append(row)
    return {"status": "planning_estimates_not_quotes", "rates_checked": model["rates_checked"],
            "scenarios": result, "extra_allowances": model["extra_allowances"],
            "approval_granted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("preflight", help="Read-only check; incomplete template returns exit 2")
    check.add_argument("--shots", type=Path, default=HERE / "shots.template.json")
    check.add_argument("--asset-root", type=Path)
    for name in ("init", "compile"):
        cmd = sub.add_parser(name, help="Create a new draft workspace; refuses any existing path")
        cmd.add_argument("--dest", type=Path, required=True)
        cmd.add_argument("--shots", type=Path, default=HERE / "shots.template.json")
        cmd.add_argument("--asset-root", type=Path)
    sub.add_parser("cost", help="Offline cost arithmetic; no quotes or generation requests")
    args = parser.parse_args()
    try:
        if args.command == "cost":
            out = cost_scenarios()
        elif args.command == "preflight":
            out = preflight(read_json(args.shots), args.asset_root or args.shots.parent)
        else:
            target = new_project(args.dest, read_json(args.shots), args.asset_root or args.shots.parent,
                                 args.command == "compile")
            out = {"created": str(target), "checkpoints_completed": 0, "generation_calls": 0}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 2 if out.get("status") == "blocked_missing_input" else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "generation_calls": 0}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
