"""Ground-truth comparison metrics."""

from ms_odd_tagging.tagger.model_based.local_vllm import validate_against_gt

compare_labels = validate_against_gt

__all__ = ["compare_labels", "validate_against_gt"]

