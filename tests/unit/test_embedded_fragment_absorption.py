from ms_odd_tagging.experiments.lane_debug_v2.embedded_fragment_absorption import (
    absorb_embedded_observed_fragments,
)


def _lane(lane_id, start, end, right_edge_id="85", width=3.5):
    half = width / 2.0
    return {
        "lane_id": str(lane_id),
        "centerline_lcs_m": [list(start), list(end)],
        "polygon_lcs_m": [
            [start[0], start[1] + half],
            [end[0], end[1] + half],
            [end[0], end[1] - half],
            [start[0], start[1] - half],
        ],
        "left_boundary_lcs_m": [[start[0], start[1] + half], [end[0], end[1] + half]],
        "right_boundary_lcs_m": [[start[0], start[1] - half], [end[0], end[1] - half]],
        "left_edge_id": "left-common",
        "right_edge_id": right_edge_id,
    }


def test_absorbs_observed_fragment_embedded_in_host_inferred_gap():
    a = [23.9080, 4.1434]
    b = [28.6538, 4.4829]
    before = _lane("2310", [20.0, 3.86], a)
    fragment = _lane("1575", a, b)
    after = _lane("2320", b, [34.0, 4.86])
    lanes = [before, fragment, after]

    host = {
        "track_id": "physical_track_0007",
        "logical_lane_id": "physical_track_0007",
        "member_lane_ids": ["2310", "2320"],
        "median_width_m": 3.5,
        "pieces": [
            {"kind": "observed_ld", "lane_id": "2310", "centerline_lcs_m": before["centerline_lcs_m"], "polygon_lcs_m": before["polygon_lcs_m"]},
            {
                "kind": "inferred_gap",
                "source_lane_id": "2310",
                "destination_lane_id": "2320",
                "centerline_lcs_m": [a, b],
                "polygon_lcs_m": [],
            },
            {"kind": "observed_ld", "lane_id": "2320", "centerline_lcs_m": after["centerline_lcs_m"], "polygon_lcs_m": after["polygon_lcs_m"]},
        ],
    }
    donor = {
        "track_id": "physical_track_0003",
        "logical_lane_id": "physical_track_0003",
        "member_lane_ids": ["1575"],
        "median_width_m": 3.5,
        "pieces": [
            {"kind": "observed_ld", "lane_id": "1575", "centerline_lcs_m": fragment["centerline_lcs_m"], "polygon_lcs_m": fragment["polygon_lcs_m"]},
        ],
    }

    tracks, debug = absorb_embedded_observed_fragments([donor, host], lanes)

    assert [t["track_id"] for t in tracks] == ["physical_track_0007"]
    merged = tracks[0]
    assert set(merged["member_lane_ids"]) == {"2310", "1575", "2320"}
    assert [p["kind"] for p in merged["pieces"]] == ["observed_ld", "observed_ld", "observed_ld"]
    assert merged["pieces"][1]["lane_id"] == "1575"
    assert merged["pieces"][1]["absorbed_into_host_track"] is True
    assert merged["inferred_gap_count"] == 0
    accepted = [row for row in debug if row.get("accepted")]
    assert len(accepted) == 1
    assert accepted[0]["donor_track_id"] == "physical_track_0003"
    assert accepted[0]["host_track_id"] == "physical_track_0007"
    assert accepted[0]["shared_boundary_ids"] == ["85"]


def test_does_not_absorb_without_continuous_boundary_evidence():
    a = [0.0, 0.0]
    b = [5.0, 0.0]
    before = _lane("A", [-5.0, 0.0], a, right_edge_id="host")
    fragment = _lane("B", a, b, right_edge_id="other")
    after = _lane("C", b, [10.0, 0.0], right_edge_id="host")
    host = {
        "track_id": "host",
        "member_lane_ids": ["A", "C"],
        "median_width_m": 3.5,
        "pieces": [
            {"kind": "observed_ld", "lane_id": "A", "centerline_lcs_m": before["centerline_lcs_m"]},
            {"kind": "inferred_gap", "source_lane_id": "A", "destination_lane_id": "C", "centerline_lcs_m": [a, b]},
            {"kind": "observed_ld", "lane_id": "C", "centerline_lcs_m": after["centerline_lcs_m"]},
        ],
    }
    donor = {
        "track_id": "donor",
        "member_lane_ids": ["B"],
        "median_width_m": 3.5,
        "pieces": [{"kind": "observed_ld", "lane_id": "B", "centerline_lcs_m": fragment["centerline_lcs_m"]}],
    }

    tracks, debug = absorb_embedded_observed_fragments([host, donor], [before, fragment, after])
    assert {t["track_id"] for t in tracks} == {"host", "donor"}
    assert not any(row.get("accepted") for row in debug)
    assert any("boundary_discontinuity" in row.get("rejection_reasons", []) for row in debug)
