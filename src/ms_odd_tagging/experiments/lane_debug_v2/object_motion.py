"""Object motion evidence for lane-debug v2."""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Any


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def wrap_angle(v: float) -> float:
    return math.atan2(math.sin(v), math.cos(v))


def build_object_motion_evidence(recording: dict[str, Any], *, history_frames: int = 3, minimum_displacement_m: float = 0.5) -> dict[tuple[int, str], dict[str, Any]]:
    tracks: dict[str, list[tuple[int, float, tuple[float,float]]]] = defaultdict(list)
    for frame in recording.get("frames", []):
        fi = frame.get("frame_index")
        ts = frame.get("time_since_start_s")
        if not isinstance(fi, int) or not _finite(ts):
            continue
        for obj in frame.get("objects", []):
            p = obj.get("position_lcs_m") or []
            oid = str(obj.get("object_id"))
            if len(p) >= 2 and _finite(p[0]) and _finite(p[1]):
                tracks[oid].append((fi, float(ts), (float(p[0]), float(p[1]))))
    out: dict[tuple[int, str], dict[str, Any]] = {}
    for oid, samples in tracks.items():
        for i, (fi, ts, p) in enumerate(samples):
            lo = max(0, i-history_frames)
            hi = min(len(samples)-1, i+history_frames)
            a = samples[lo]
            b = samples[hi]
            dx, dy = b[2][0]-a[2][0], b[2][1]-a[2][1]
            disp = math.hypot(dx, dy)
            dt = b[1]-a[1]
            if dt > 0 and disp >= minimum_displacement_m:
                heading = math.atan2(dy, dx)
                speed = disp/dt
                status = "moving"
            else:
                heading = None
                speed = 0.0 if dt > 0 else None
                status = "stationary_or_ambiguous"
            out[(fi, oid)] = {
                "object_motion_heading_rad": heading,
                "object_motion_heading_deg": None if heading is None else round(math.degrees(heading), 2),
                "object_motion_speed_mps": None if speed is None else round(speed, 3),
                "object_motion_displacement_m": round(disp, 3),
                "object_motion_window_dt_s": round(dt, 3),
                "object_motion_source": "temporal_position_history",
                "object_motion_status": status,
            }
    return out
