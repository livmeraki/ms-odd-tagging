"""Repository-relative default stage paths."""

from pathlib import Path

DATA_RAW = Path("data/01_raw")
DATA_GT = Path("data/02_gt")
CANONICAL = Path("outputs/01_canonical")
WINDOWS = Path("outputs/02_windows")
MODEL_INPUTS = Path("outputs/03_model_inputs")
TAGGING = Path("outputs/04_tagging")
VALIDATION = Path("outputs/05_validation")
GT_COMPARISON = Path("outputs/06_gt_comparison")

