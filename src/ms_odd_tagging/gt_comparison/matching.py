"""Ground-truth matching helpers for active frames and legacy windows."""

from ms_odd_tagging.tagger.model_based.local_vllm import (
    gt_labels_for_frame,
    gt_labels_for_window,
    output_window_ids,
)


__all__ = ["gt_labels_for_frame", "gt_labels_for_window", "output_window_ids"]
