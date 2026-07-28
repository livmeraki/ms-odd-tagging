"""Frame-level following-lane tagging based on LD lane assignments."""

from .detector import DEFAULT_CONFIG, run_following_lane

__all__ = ["DEFAULT_CONFIG", "run_following_lane"]
