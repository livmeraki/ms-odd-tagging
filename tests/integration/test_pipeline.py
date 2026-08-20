from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


RECORDING = "Rec_Synthetic_Current_Pipeline"


def write_synthetic_recording(root: Path) -> None:
    rec_dir = root / RECORDING
    rec_dir.mkdir(parents=True)

    od_annotations = {
        "scene": {"id": "synthetic-scene", "name": RECORDING, "frameCount": 20},
        "objects": [],
    }
    ld_annotations = {
        "scene": {"id": "synthetic-scene", "name": RECORDING, "frameCount": 20},
        "lanes": {
            "points": [],
            "lines": [],
            "lanes": [],
            "roadBoundaries": [],
            "topologies": [],
        },
        "roadmarks": [],
    }

    (rec_dir / "annotations_OD.json").write_text(json.dumps(od_annotations), encoding="utf-8")
    (rec_dir / "annotations_LD.json").write_text(json.dumps(ld_annotations), encoding="utf-8")

    trajectory = [
        f"{idx * 0.1:.1f} {idx * 0.5:.3f} 0.0 0.0 0.0 0.0 0.0 1.0"
        for idx in range(20)
    ]
    (rec_dir / "traj_lcs.txt").write_text("\n".join(trajectory) + "\n", encoding="utf-8")


def _env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    return env


def test_current_cli_modules_show_help() -> None:
    repo = Path(__file__).resolve().parents[2]
    modules = (
        "ms_odd_tagging.pipeline",
        "ms_odd_tagging.canonical.builder",
        "ms_odd_tagging.frame_inputs.builder",
        "ms_odd_tagging.tagger.rule_based.registry",
        "ms_odd_tagging.scenarios.following_lane.pipeline",
        "ms_odd_tagging.ld_topology.cli",
        "ms_odd_tagging.qwen_vlm_poc.cli",
        "ms_odd_tagging.simplified_taxonomy.gt_workspace",
        "ms_odd_tagging.validator.frame_schema",
    )

    for module in modules:
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            cwd=repo,
            env=_env(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, f"{module}: {result.stderr}"
        assert "usage:" in result.stdout.lower()


def test_pipeline_canonical_smoke(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    source_root = tmp_path / "data" / "01_raw"
    output_root = tmp_path / "outputs"
    write_synthetic_recording(source_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ms_odd_tagging.pipeline",
            RECORDING,
            "--source-root",
            str(source_root),
            "--output-root",
            str(output_root),
            "--stop-after",
            "canonical",
        ],
        cwd=repo,
        env=_env(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    canonical_files = list((output_root / "01_canonical").glob("*.json"))
    assert canonical_files
    assert list((output_root / "runtime_logs").glob("pipeline_*.json"))
