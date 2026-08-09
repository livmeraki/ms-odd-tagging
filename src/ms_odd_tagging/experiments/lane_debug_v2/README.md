# Lane Debug v2

Isolated duplicate of the LD-based lane/following-lane/lane-change path. Production modules are not modified.

Run one recording:

```bash
python -m ms_odd_tagging.experiments.lane_debug_v2.pipeline \
  <RECORDING_ID> \
  --canonical-dir <CANONICAL_ODLD_DIR>
```

Optional enforced lead-direction filtering requires an explicit threshold chosen after inspecting the diagnostic distribution. Edit `configs/lane_debug_v2.json`:

```json
"lead_direction_filter_mode": "enforce",
"maximum_lead_direction_difference_deg": <chosen threshold>
```

Outputs are always fresh and live under `outputs/debug_lane_v2/<run_id>/`. Existing run directories are refused rather than reused.

Serve the explorer:

```bash
python -m http.server 8002 --directory outputs/debug_lane_v2/<run_id>/explorers
```

Then open `http://localhost:8002/<RECORDING_ID>_lane_debug_v2_plotly.html`.
