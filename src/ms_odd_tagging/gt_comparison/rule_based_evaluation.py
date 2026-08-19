"""Compatibility alias for the relocated rule-based evaluation implementation."""

import sys

from ms_odd_tagging.evaluation import rule_based as _implementation


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
