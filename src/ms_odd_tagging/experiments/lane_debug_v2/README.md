# Lane Debug v2

Isolated duplicate of the LD-based lane/following-lane/lane-change path. Production modules are not modified.

The current experiment adds **continuous lane tracks** on top of valid raw/recovered LD lane segments. Existing curvature-aware continuation evidence is promoted into recursively merged tracks:

`observed/recovered segment -> inferred gap -> observed/recovered segment -> ...`

Each track preserves piece provenance as `observed_ld`, `recovered_full_edge`, or `inferred_gap`. Ego logical-lane assignment and adjacent-lane context use the continuous track first; the original segment-level assignments are retained in each frame as `segment_ego_lane`, `segment_left_lane`, and `segment_right_lane` for comparison.

Run one recording:

```bash
python -m ms_odd_tagging.experiments.lane_debug_v2.pipeline \
  <RECORDING_ID> \
  --canonical-dir <CANONICAL_ODLD_DIR> \
  --run-id continuous_track_01
```

Outputs are always fresh and live under `outputs/debug_lane_v2/<run_id>/`. Existing run directories are refused rather than reused.

Serve the explorer:

```bash
python -m http.server 8002 --directory outputs/debug_lane_v2/<run_id>/explorers
```

Then open `http://localhost:8002/<RECORDING_ID>_lane_debug_v2_plotly.html`.

Useful explorer controls:

- `continuous tracks`: merged lane-track geometry used for primary ego/adjacency context
- `track pieces/gaps`: shows observed/recovered pieces and inferred gaps separately
- `raw reconstructed segments`: the original segment-level lane polygons
- `segment adjacency comparison`: shows the segment geometry so old vs new adjacency can be inspected
- `full referenced edges`, `canonical ranges`, `detector boundaries`: boundary-range diagnostics

The debug panel shows both `continuous_adjacency` (including all candidate tracks and rejection reasons) and the previous segment-level adjacency so missed/false adjacent lanes can be compared frame by frame.

Optional enforced lead-direction filtering still requires an explicit threshold chosen after inspecting the diagnostic distribution:

```json
"lead_direction_filter_mode": "enforce",
"maximum_lead_direction_difference_deg": <chosen threshold>
```
