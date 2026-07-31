# Lanelet2 LCS ego/adjacent-lane POC

This is an isolated, opt-in experiment. It does not replace, call, or mutate
the current following-lane detector. With the feature flag omitted, the command
does no input reads and writes no outputs.

## What it consumes

The CLI reads existing `*_canonical_odld_frames.json` recordings. It reuses:

- ordered LD lane-line polylines;
- road boundaries whose source attribute is `drivable`;
- ego `position_lcs_m` and `heading_lcs_rad`.

All output polygons and points remain in LCS metres. The ego-relative frame is
used only to select a local window, orient boundary samples, calculate overlap,
and determine left/right ordering. Existing LD lane objects and topology links
are deliberately not trusted as an HD map.

## Algorithm

For each selected frame, the POC:

1. filters malformed, short, discontinuous, or distant boundary polylines;
2. orients boundaries with the ego heading;
3. evaluates every local boundary pair using longitudinal overlap, heading
   agreement, sampled width, width stability, continuity, and side crossing;
4. creates a temporary lane polygon and centerline for each accepted pair;
5. constructs Lanelet2 points, shared line strings, lanelets, a map, generic
   traffic rules, and a routing graph;
6. matches ego candidates using polygon containment/tolerance, heading
   difference, and centerline distance;
7. queries routing `left`, `right`, `adjacentLeft`, and `adjacentRight`;
8. records a shared-boundary geometric fallback separately from Lanelet2
   results.

The Lanelet2 routing documentation distinguishes `left/right` (reachable by a
lane change under the selected traffic rules) from adjacent-left/right
(neighboring but not lane-change reachable). Inferred line attributes cannot
provide authoritative legality. See the
[official routing documentation](https://docs.ros.org/en/rolling/p/lanelet2_routing/index.html).

## Installation and license

Lanelet2 includes C++ and Python APIs and is distributed under the BSD
3-Clause license; this POC does not copy Lanelet2 source. See the
[official Lanelet2 repository](https://github.com/fzi-forschungszentrum-informatik/lanelet2).

On a supported Linux environment, try:

```bash
python -m pip install -e ".[dev,lanelet2-poc]"
python -c "import lanelet2; print(lanelet2)"
```

ROS installations can use the distribution package (for example,
`ros-${ROS_DISTRO}-lanelet2`) and must expose the matching Python bindings to
the interpreter running this project. Source, ROS, Docker, and Conan options
are described in the official repository. Wheel and platform availability can
vary; validate `import lanelet2` in the exact runtime used by the CLI.

The optional dependency is Linux-gated. On Windows the project and disabled
POC remain installable, but a separate Lanelet2 build/binding setup is required
for routing.

## Commands

Disabled/no-op check:

```powershell
python .\run_lanelet2_poc.py
```

One real recording and one frame, requiring Lanelet2:

```powershell
python .\run_lanelet2_poc.py Rec_Drv_GER_MACHET18_20260319_144819 `
  --enable-lanelet2-poc --frame 0 --visualize
```

A range uses an exclusive stop:

```powershell
python .\run_lanelet2_poc.py <recording-id> `
  --enable-lanelet2-poc --frame 100:150 --visualize
```

For geometry/matching diagnostics on a host without Lanelet2:

```powershell
python .\run_lanelet2_poc.py <recording-id> `
  --enable-lanelet2-poc --allow-geometric-only --frame 0
```

That last mode is not a Lanelet2 routing validation. Its output explicitly
reports `routing.backend = "geometric_fallback"` and leaves all four Lanelet2
query results null.

Outputs are written below `outputs/lanelet2_poc/`:

- `results/*_lanelet2_poc.json`: versioned structured results;
- `logs/*.jsonl`: one structured diagnostic event per frame;
- `visualization/*.html`: optional heading-up LCS overlay, with a strong green
  ego fill and light blue/orange adjacent fills.

Thresholds are in `configs/lanelet2_poc.json`.

## Output and failure behavior

Every valid frame reports ego, left-adjacent, and right-adjacent `exists`,
lane ID, left/right boundary IDs, polygon, and confidence. It also includes
candidate scores, pair metrics, boundary/pair/match rejection reasons, routing
backend and query values, and debug-overlay IDs.

Invalid ego poses, missing boundaries, missing outer boundaries, fragmented
lines, intersections, multiple candidates, and ego near a boundary produce
structured unknown/ambiguous results rather than exceptions. A required but
missing Lanelet2 installation is a CLI configuration error before processing.

## Assumptions and limitations

- Boundary point order is not assumed; it is normalized against ego heading.
- A complete lanelet still needs two plausible detected boundaries. The POC
  does not invent a missing outer boundary.
- Shared-boundary inference is geometric and local. Fragment IDs that describe
  the same physical marking are not merged yet.
- Generic Germany/vehicle traffic rules are only a routing experiment.
  Detection data lacks regulatory elements and reliable lane-change
  permissions, so legal neighbors are not ground truth.
- Intersections are intentionally conservative. A valid turning connector may
  be rejected if its local direction differs too much from ego heading.
- Candidate construction is per frame and quadratic in the number of local
  boundaries; the local window bounds the POC cost.
- Lanelet2 primitives normally assume a valid map. Here they are temporary
  containers around noisy detections, so routing success does not prove map
  validity.

## Comparing with the current detector

Run both workflows for the same recording/frame range:

```powershell
python .\run_following_lane_pipeline.py <recording-id> --stop-after assignments
python .\run_lanelet2_poc.py <recording-id> `
  --enable-lanelet2-poc --frame 100:150 --visualize
```

Compare the current detector's `ego_lane`, `left_lane`, and `right_lane` IDs
and polygons under `outputs/scenarios/following_lane/02_frame_assignments/`
with the POC result. IDs are from different namespaces, so compare boundary
IDs, polygon containment, neighbor existence, confidence, and transition
stability rather than raw lane-ID equality. Review disagreement frames in both
HTML visualizations and inspect the POC rejection reasons before changing the
production detector.
