from __future__ import annotations

from pathlib import Path

from ms_odd_tagging.frame_inputs import revised_bev


def _minimal_frame() -> dict:
    return {
        "frame_index": 0,
        "ego": {
            "position_lcs_m": [0.0, 0.0, 0.0],
            "heading_lcs_rad": 0.0,
            "speed_mps": 0.0,
        },
        "objects": [],
        "ld": {"available": False, "nearby_feature_ids": {}},
    }


def test_static_bev_context_is_reused_for_same_recording(monkeypatch) -> None:
    recording = {"recording_id": "rec", "ld_feature_store": {}}
    calls = {"count": 0}
    original = revised_bev._uncached_bev_static_context

    def counted(value):
        calls["count"] += 1
        return original(value)

    monkeypatch.setattr(revised_bev, "_uncached_bev_static_context", counted)
    first = revised_bev.build_bev_static_context(recording)
    second = revised_bev.build_bev_static_context(recording)

    assert first is second
    assert calls["count"] == 1


def test_renderer_exposes_phase_timings(tmp_path: Path) -> None:
    recording = {"recording_id": "timed", "ld_feature_store": {}}
    output = tmp_path / "bev.png"

    revised_bev.render_revised_bev_png(
        recording,
        _minimal_frame(),
        output,
        (45.0, 45.0, 25.0, 95.0),
        (90, 120),
    )

    timings = revised_bev.pop_render_timings(output)
    assert timings["bev_render_time_s"] >= 0.0
    assert timings["bev_static_context_time_s"] >= 0.0
    assert timings["bev_draw_time_s"] >= 0.0
    assert timings["png_encode_write_time_s"] >= 0.0
    assert revised_bev.pop_render_timings(output) == {}
