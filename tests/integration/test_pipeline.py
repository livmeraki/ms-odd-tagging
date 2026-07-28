from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ms_odd_tagging.input_generator.canonical import build_recording as build_canonical
from ms_odd_tagging.input_generator.frame_input import build_recording as build_frames
from ms_odd_tagging.tagger.model_based.local_vllm import (
    load_gt_labels,
    output_window_ids,
    retry_prompt,
    validate_against_gt,
    validate_output,
)
from ms_odd_tagging.gt_comparison.labels import build_gt_payload
from ms_odd_tagging.validator.frame_schema import validate_frame_file
from ms_odd_tagging.input_generator.windows import (
    build_candidates,
)


RECORDING = "Rec_Drv_GER_MACHET18_20260227_153128"


def write_synthetic_recording(root: Path) -> None:
    rec_dir = root / RECORDING
    rec_dir.mkdir(parents=True)
    annotations = {"scene": {"frameCount": 60}, "objects": []}
    (rec_dir / "annotations.json").write_text(json.dumps(annotations), encoding="utf-8")
    rows = []
    for idx in range(60):
        timestamp = idx * 0.1
        rows.append(f"{timestamp:.1f} {idx * 1.0:.3f} 0.0 0.0 0.0 0.0 0.0 1.0")
    (rec_dir / "traj_lcs.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_imports_work() -> None:
    import ms_odd_tagging

    assert ms_odd_tagging.__version__


def test_cli_help_works() -> None:
    repo = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    for module in (
        "ms_odd_tagging.input_generator.canonical",
        "ms_odd_tagging.input_generator.frame_input",
        "ms_odd_tagging.tagger.model_based.local_vllm",
        "ms_odd_tagging.validator.frame_schema",
    ):
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout

    result = subprocess.run(
        [sys.executable, str(repo / "run_pipeline.py"), "--help"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_run_pipeline_script_works_without_pythonpath(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "source"
    output_root = tmp_path / "outputs"
    write_synthetic_recording(source_root)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "run_pipeline.py"),
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--stop-after",
            "frame-inputs",
            "--frame-limit",
            "2",
            RECORDING,
        ],
        cwd=repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    recording_root = output_root / "02_frame_inputs" / RECORDING
    assert (recording_root / "frame_000000" / "frame.json").is_file()
    assert (recording_root / "frame_000000" / "bev.png").is_file()
    assert (recording_root / "frame_000010" / "frame.json").is_file()
    assert not (recording_root / "frame_000001").exists()
    assert not (output_root / "02_windows").exists()


def test_sample_pipeline_and_schema_validation(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    canonical_dir = tmp_path / "canonical"
    frame_inputs_dir = tmp_path / "frame_inputs"
    write_synthetic_recording(source_root)

    canonical_path, canonical = build_canonical(source_root, canonical_dir, RECORDING)
    assert canonical_path.is_file()
    assert canonical["recording"]["frame_count"] == 60

    manifest, count = build_frames(
        canonical_path,
        frame_inputs_dir,
        extent=(45.0, 45.0, 25.0, 95.0),
        size=(320, 288),
        ld_filters={"roadmark_classes": {"line"}, "line_patterns": {"solid"}},
        max_objects=24,
        frame_limit=2,
    )
    assert count == 2
    assert manifest["generated_frame_count"] == 2
    frame_path = frame_inputs_dir / RECORDING / "frame_000000" / "frame.json"
    payload = json.loads(frame_path.read_text(encoding="utf-8"))
    assert payload["frame_id"] == f"{RECORDING}:frame-000000"
    assert payload["bev"]["frame_index"] == payload["frame_index"]
    assert validate_frame_file(frame_path) == []
    assert not (tmp_path / "windows").exists()


def test_ld_context_gates_following_lane_candidates() -> None:
    def frame(index: int, has_ld_context: bool) -> dict:
        summary = {
            "nearby_lane_line_count": 2 if has_ld_context else 0,
            "nearby_lane_count": 1 if has_ld_context else 0,
            "nearest_lane_line_distance_m": 1.2 if has_ld_context else None,
            "nearest_lane_distance_m": 2.4 if has_ld_context else None,
            "lane_line_pattern_counts": {"solid": 1} if has_ld_context else {},
        }
        return {
            "frame_index": index,
            "time_since_start_s": index * 0.1,
            "ego": {"speed_mps": 8.0},
            "scenario_signals": {"lead_candidate": None},
            "objects": [],
            "ld": {
                "available": True,
                "summary": summary,
                "quality_flags": {"nearby_lane_ids_with_invalid_boundary_ranges": []},
            },
        }

    frames_without_ld_context = [frame(index, False) for index in range(50)]
    candidates = build_candidates(frames_without_ld_context, [], [], 0.1)
    assert candidates["ld_context"]["available"] is True
    assert candidates["ld_context"]["candidate"] is None
    assert candidates["candidate_flags"]["following_lane_without_lead"] is False

    frames_with_ld_context = [frame(index, True) for index in range(50)]
    candidates = build_candidates(frames_with_ld_context, [], [], 0.1)
    assert candidates["ld_context"]["candidate"]["qualifying_fraction"] == 1.0
    assert candidates["candidate_flags"]["following_lane_without_lead"] is True
    evidence = candidates["evidence"]["following_lane_without_lead"]
    assert evidence["ld_lane_context"]["minimum_nearest_lane_line_distance_m"] == 1.2


def test_output_schema_loads() -> None:
    repo = Path(__file__).resolve().parents[2]
    schema = json.loads((repo / "schemas" / "output_schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["labels"]["required"]
    assert "stationary" in schema["properties"]["labels"]["required"]
    assert "frame_id" in schema["required"]
    assert "window_id" not in schema["properties"]
    assert schema["properties"]["schema_version"]["const"] == "motional-scenario-frame-output-v1"
    decision_schema = schema["$defs"]["label_decision"]["properties"]
    assert decision_schema["evidence_frames"]["maxItems"] == 3
    assert decision_schema["object_ids"]["maxItems"] == 2


def test_model_output_rejects_long_evidence_arrays() -> None:
    repo = Path(__file__).resolve().parents[2]
    schema = json.loads((repo / "schemas" / "output_schema.json").read_text(encoding="utf-8"))
    label_names = schema["properties"]["labels"]["required"]
    labels = {
        label: {
            "value": False,
            "confidence": 0.1,
            "evidence_summary": "none",
            "evidence_frames": [0, 5, 25, 49],
            "object_ids": ["1", "2", "3"],
        }
        for label in label_names
    }
    output = {
        "schema_version": "motional-scenario-frame-output-v1",
        "recording_id": RECORDING,
        "frame_id": f"{RECORDING}:frame-000025",
        "model_mode": "json_bev",
        "labels": labels,
        "overall_quality": {"confidence": 0.5, "data_issues": []},
        "review_priority": "low",
    }
    refined = {"frame_id": f"{RECORDING}:frame-000025", "ego": {"speed_mps": 0.0}}

    errors = validate_output(output, RECORDING, f"{RECORDING}_000-049", "json_bev", refined)

    assert "labels.stationary.evidence_frames must contain at most 3 items" in errors
    assert "labels.stationary.object_ids must contain at most 2 items" in errors


def test_speed_band_labels_reject_frame_and_object_evidence() -> None:
    repo = Path(__file__).resolve().parents[2]
    schema = json.loads((repo / "schemas" / "output_schema.json").read_text(encoding="utf-8"))
    label_names = schema["properties"]["labels"]["required"]
    labels = {
        label: {
            "value": False,
            "confidence": 0.1,
            "evidence_summary": "none",
            "evidence_frames": [],
            "object_ids": [],
        }
        for label in label_names
    }
    labels["high_magnitude_speed"]["evidence_frames"] = [0]
    labels["high_magnitude_speed"]["object_ids"] = ["1"]
    output = {
        "schema_version": "motional-scenario-frame-output-v1",
        "recording_id": RECORDING,
        "frame_id": f"{RECORDING}:frame-000025",
        "model_mode": "json_bev",
        "labels": labels,
        "overall_quality": {"confidence": 0.5, "data_issues": []},
        "review_priority": "low",
    }
    refined = {"frame_id": f"{RECORDING}:frame-000025", "ego": {"speed_mps": 0.0}}

    errors = validate_output(output, RECORDING, f"{RECORDING}_000-049", "json_bev", refined)

    assert "labels.high_magnitude_speed.evidence_frames must be empty for speed-band labels" in errors
    assert "labels.high_magnitude_speed.object_ids must be empty for speed-band labels" in errors


def test_false_labels_reject_default_frame_and_object_evidence() -> None:
    repo = Path(__file__).resolve().parents[2]
    schema = json.loads((repo / "schemas" / "output_schema.json").read_text(encoding="utf-8"))
    label_names = schema["properties"]["labels"]["required"]
    labels = {
        label: {
            "value": False,
            "confidence": 0.1,
            "evidence_summary": "unsupported",
            "evidence_frames": [],
            "object_ids": [],
        }
        for label in label_names
    }
    labels["following_lane_with_lead"]["evidence_frames"] = [5, 25, 49]
    labels["following_lane_with_lead"]["object_ids"] = ["1", "4"]
    output = {
        "schema_version": "motional-scenario-frame-output-v1",
        "recording_id": RECORDING,
        "frame_id": f"{RECORDING}:frame-000025",
        "model_mode": "json_bev",
        "labels": labels,
        "overall_quality": {"confidence": 0.5, "data_issues": []},
        "review_priority": "low",
    }
    refined = {"frame_id": f"{RECORDING}:frame-000025", "ego": {"speed_mps": 0.0}}

    errors = validate_output(output, RECORDING, f"{RECORDING}_000-049", "json_bev", refined)

    assert "labels.following_lane_with_lead.evidence_frames must be empty for false labels" in errors
    assert "labels.following_lane_with_lead.object_ids must be empty for false labels" in errors


def test_ego_only_labels_reject_object_ids() -> None:
    repo = Path(__file__).resolve().parents[2]
    schema = json.loads((repo / "schemas" / "output_schema.json").read_text(encoding="utf-8"))
    label_names = schema["properties"]["labels"]["required"]
    labels = {
        label: {
            "value": False,
            "confidence": 0.1,
            "evidence_summary": "none",
            "evidence_frames": [],
            "object_ids": [],
        }
        for label in label_names
    }
    labels["starting_left_turn"] = {
        "value": True,
        "confidence": 0.8,
        "evidence_summary": "yaw rate onset",
        "evidence_frames": [25],
        "object_ids": ["1"],
    }
    output = {
        "schema_version": "motional-scenario-frame-output-v1",
        "recording_id": RECORDING,
        "frame_id": f"{RECORDING}:frame-000025",
        "model_mode": "json_bev",
        "labels": labels,
        "overall_quality": {"confidence": 0.5, "data_issues": []},
        "review_priority": "low",
    }
    refined = {"frame_id": f"{RECORDING}:frame-000025", "ego": {"speed_mps": 0.0}}

    errors = validate_output(output, RECORDING, f"{RECORDING}_000-049", "json_bev", refined)

    assert "labels.starting_left_turn.object_ids must be empty for ego-only labels" in errors


def test_retry_prompt_mentions_shortening_arrays() -> None:
    prompt = retry_prompt(["labels.stationary.object_ids must contain at most 2 items"])
    assert "Shorten arrays" in prompt
    assert "evidence_frames array must have at most 3 items" in prompt
    assert "object_ids array must have at most 2 items" in prompt
    assert "For false labels, set evidence_frames=[] and object_ids=[]" in prompt
    assert "For ego-only labels" in prompt
    assert "Do not use default object IDs" in prompt
    assert "For speed-band labels, set evidence_frames=[] and object_ids=[]" in prompt


def test_gt_window_id_matching() -> None:
    gt_path = Path(__file__).resolve().parents[1] / "fixtures" / "gt" / f"{RECORDING}_gt.json"
    labels = load_gt_labels(gt_path, RECORDING, f"{RECORDING}_000-049")
    assert labels is not None
    assert output_window_ids(RECORDING, f"{RECORDING}_000-049") == {
        f"{RECORDING}_000-049",
        f"{RECORDING}:000-049",
    }


def test_gt_mismatch_does_not_create_validation_error() -> None:
    gt_labels = {"stationary": True}
    output = {"labels": {"stationary": {"value": False}}}
    result = validate_against_gt(output, gt_labels)
    assert result["status"] == "failed"
    assert result["mismatches"] == [{"label": "stationary", "expected": True, "actual": False}]


def test_gt_template_formula_fills_speed_labels(tmp_path: Path) -> None:
    model_input_root = tmp_path / "model_inputs"
    window_dir = model_input_root / RECORDING / f"{RECORDING}_000-049"
    window_dir.mkdir(parents=True)
    refined = {
        "recording_id": RECORDING,
        "source_window_id": f"{RECORDING}:000-049",
        "time_window": {
            "start_frame": 0,
            "end_frame": 49,
            "start_time_s": 0.0,
            "end_time_s": 4.9,
        },
        "ego_summary": {"median_speed_mps": 12.0},
    }
    (window_dir / "refined.json").write_text(json.dumps(refined), encoding="utf-8")

    payload = build_gt_payload(model_input_root, RECORDING)
    labels = payload["windows"][f"{RECORDING}:000-049"]["labels"]

    assert labels["high_magnitude_speed"] is False
    assert labels["medium_magnitude_speed"] is True
    assert labels["low_magnitude_speed"] is False
    assert labels["following_lane_with_lead"] is None


def test_no_tracked_secret_or_server_absolute_path_patterns() -> None:
    repo = Path(__file__).resolve().parents[2]
    banned = (
        "sk" + "-",
        "BEGIN " + "PRIVATE KEY",
        "/home/" + "stradvision",
        "/media/" + "stradvision",
        "C:" + "\\Users",
    )
    tracked_files = subprocess.run(
        ["git", "ls-files"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.splitlines()
    for relative_path in tracked_files:
        path = repo / relative_path
        if not path.exists():
            continue
        if path.suffix.lower() in {".png", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in banned:
            assert pattern not in text, f"{pattern} found in {relative_path}"
