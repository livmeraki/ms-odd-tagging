# Lane Debug v2

Isolated duplicate of the LD-based lane/following-lane/lane-change path. Production modules are not modified.

The experiment uses continuous lane tracks built from observed/recovered LD lane segments and accepted inferred gaps:

`observed/recovered segment -> inferred gap -> observed/recovered segment -> ...`

Each track preserves piece provenance as `observed_ld`, `recovered_full_edge`, or `inferred_gap`.

## Track-topology-first adjacency

Adjacent lanes are no longer chosen primarily by re-running a nearest-lane search at every frame. A static adjacency graph is built between continuous tracks using sustained overlap, same-direction heading compatibility, stable lateral separation, side consistency, and shared physical boundary edge IDs when available. Each relation stores an ego-track station interval where it is valid.

Per frame, the detector activates the precomputed left/right relation at the ego station. The previous frame-local method is retained only as `frame_local_adjacency_debug` for comparison.

Optional hysteresis is enabled by default and can be disabled independently:

```json
"track_topology_hysteresis_enabled": true,
"track_topology_switch_score_margin": 0.75,
"track_topology_switch_confirmation_frames": 3
```

A physical member lane ID may change while the stable `continuous_track_id` stays the same. That is a fragment transition, not an adjacency switch.

## Boundary-aware inferred ego corridor

Strict ego assignment first requires the ego center to be inside an actual reconstructed track polygon. The 1 m outside tolerance is continuity-only: it may preserve the previous track, but cannot acquire a new nearby track.

If no real ego track is valid, the detector directly inspects physical LD `lane_lines` / `road_boundaries` plus reconstructed lane boundaries. If a compatible left/right boundary pair encloses ego with plausible width and heading, it creates an explicit inferred corridor:

```text
left physical boundary | inferred ego corridor | right physical boundary
```

The output is marked `source = inferred_from_physical_boundaries` and stored in `inferred_ego_corridor`; it is never represented as observed LD. When the selected boundaries belong to reconstructed continuous tracks, those tracks become the inferred left/right adjacent tracks.

## Run

```bash
python -m ms_odd_tagging.experiments.lane_debug_v2.pipeline \
  <RECORDING_ID> \
  --canonical-dir <CANONICAL_ODLD_DIR> \
  --run-id topology_boundary_01
```

Outputs are always fresh under `outputs/debug_lane_v2/<run_id>/`.

Serve the explorer:

```bash
python -m http.server 8002 --directory outputs/debug_lane_v2/<run_id>/explorers
```

Then open `http://localhost:8002/<RECORDING_ID>_lane_debug_v2_plotly.html`.

Important frame evidence now includes:

- `continuous_ego_track`
- `inferred_ego_corridor`
- `continuous_adjacency` (primary track-topology result)
- `frame_local_adjacency_debug` (old frame-local comparison)
- `segment_ego_lane`, `segment_left_lane`, `segment_right_lane`
- `track_adjacency_graph` at recording level

Optional enforced lead-direction filtering still requires an explicit threshold chosen after inspecting the diagnostic distribution.
