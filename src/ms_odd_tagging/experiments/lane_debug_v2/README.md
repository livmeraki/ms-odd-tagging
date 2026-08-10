# Lane Debug v2

Isolated LD lane experiment. Production lane/tagging modules are not modified.

## Current architecture

1. Reconstruct every trustworthy canonical LD lane segment.
2. Connect accepted canonical continuations into persistent continuous tracks.
3. Raw LD **cannot create standalone lanes**. It may only bridge two canonical track endpoints when both terminal lane fragments reference the same physical left/right raw LD boundaries and endpoint heading/width checks pass.
4. Accepted bridges are merged into the canonical tracks they connect, so a bridge does not introduce a temporary logical lane ID.
5. Build a static left-to-right lane ordering by sampling each constructed track and selecting the immediate compatible track on each side at every cross-section.
6. Per frame, assign ego by strict polygon containment and classify all static tracks as `ego`, `left_adjacent`, `right_adjacent`, or `irrelevant` from the precomputed cross-section ordering.

Hysteresis is intentionally disabled while validating this topology. Normal lane adjacency should be stable without temporal smoothing.

Strict ego assignment still uses the 1 m tolerance only to preserve the previous track; the tolerance cannot acquire a new adjacent track.

When no constructed track contains ego, boundary-aware inferred ego corridors remain available as explicitly inferred fallback evidence and consecutive inferred corridors are connected into ego-specific inferred routes.

## Explorer

The duplicated Plotly explorer exposes independent layers:

- `canonical tracks`
- `anchored LD bridges`
- `ego/adjacent roles`
- `lane-order neighbors`
- `raw LD lines`
- inferred ego corridor / connected inferred route

This separates construction failures from role-classification failures.

## Run

```bash
python -m ms_odd_tagging.experiments.lane_debug_v2.pipeline \
  <RECORDING_ID> \
  --canonical-dir <CANONICAL_ODLD_DIR> \
  --run-id static_order_01
```

Outputs are always fresh under `outputs/debug_lane_v2/<run_id>/`.
