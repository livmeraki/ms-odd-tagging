"""Default stage paths for local data and generated artifacts."""

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def load_local_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"'")
        if name and name not in os.environ:
            os.environ[name] = value


def env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


load_local_env()

DATA_ROOT = env_path("MS_ODD_DATA_ROOT", Path("data"))
OUTPUT_ROOT = env_path("MS_ODD_OUTPUT_ROOT", Path("outputs"))

DATA_RAW = DATA_ROOT / "01_raw"
DATA_GT = DATA_ROOT / "02_gt"

# Active pipeline stages.
CANONICAL = OUTPUT_ROOT / "01_canonical"
FRAME_INPUTS = OUTPUT_ROOT / "02_frame_inputs"
TAGGING = OUTPUT_ROOT / "03_tagging"
VALIDATION = OUTPUT_ROOT / "04_validation"
GT_COMPARISON = OUTPUT_ROOT / "05_gt_comparison"
SCENARIO_EXPLORERS = OUTPUT_ROOT / "06_scenario_explorers"
ODLD_SCENARIO_EXPLORERS = SCENARIO_EXPLORERS / "odld"
ODLD_GT_AUTHORING_EXPLORERS = SCENARIO_EXPLORERS / "gt_authoring"
ODLD_GT_COMPARISON_EXPLORERS = SCENARIO_EXPLORERS / "gt_comparison"
SCENARIO_REVIEW_EXPLORERS = SCENARIO_EXPLORERS / "reviews"

# Transitional compatibility aliases. Explorer-aligned frame generation owns
# the canonical 02_frame_inputs directory.
FRAME_INPUTS_REVISED = FRAME_INPUTS

# Legacy window/model-input pipeline locations. These are no longer numbered
# active stages; keep them isolated so they cannot be confused with 03_tagging.
WINDOWS = OUTPUT_ROOT / "legacy" / "windows"
MODEL_INPUT_ROOT = env_path(
    "MS_ODD_MODEL_INPUT_ROOT", OUTPUT_ROOT / "legacy" / "model_inputs"
)
MODEL_INPUTS = MODEL_INPUT_ROOT

FRAME_GT_AUTHORING = OUTPUT_ROOT / "frame_gt_authoring"
FOLLOWING_LANE = OUTPUT_ROOT / "scenarios" / "following_lane"
