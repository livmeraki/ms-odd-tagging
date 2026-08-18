"""Compatibility facade for rule-based ground-truth evaluation."""

from ms_odd_tagging.gt_comparison.rule_based_evaluation import *  # noqa: F401,F403
from ms_odd_tagging.gt_comparison.rule_based_evaluation import main


if __name__ == "__main__":
    raise SystemExit(main())
