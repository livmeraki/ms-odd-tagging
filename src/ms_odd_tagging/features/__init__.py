"""Reusable feature extraction for deterministic scenario rules."""

from .ego_motion import EgoMotionFeatures, extract_ego_motion_features

__all__ = ["EgoMotionFeatures", "extract_ego_motion_features"]
