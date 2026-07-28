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
MODEL_INPUT_ROOT = env_path("MS_ODD_MODEL_INPUT_ROOT", OUTPUT_ROOT / "03_model_inputs")

DATA_RAW = DATA_ROOT / "01_raw"
DATA_GT = DATA_ROOT / "02_gt"
CANONICAL = OUTPUT_ROOT / "01_canonical"
WINDOWS = OUTPUT_ROOT / "02_windows"
MODEL_INPUTS = MODEL_INPUT_ROOT
FRAME_INPUTS = OUTPUT_ROOT / "02_frame_inputs"
FRAME_INPUTS_REVISED = OUTPUT_ROOT / "02_frame_inputs_revised"
TAGGING = OUTPUT_ROOT / "04_tagging"
VALIDATION = OUTPUT_ROOT / "05_validation"
GT_COMPARISON = OUTPUT_ROOT / "06_gt_comparison"
SCENARIO_EXPLORERS = OUTPUT_ROOT / "07_scenario_explorers"
FRAME_GT_AUTHORING = OUTPUT_ROOT / "frame_gt_authoring"
FOLLOWING_LANE = OUTPUT_ROOT / "scenarios" / "following_lane"
