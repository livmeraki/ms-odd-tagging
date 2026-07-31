# Following-lane frame workflow

This isolated workflow is the first rebuilt rule-based scenario. It does not
modify the legacy tag registry. The processing order is explicit:

1. Reconstruct valid lane polygons and centerlines from LD boundary ranges.
2. Merge one-to-one directed LD continuations using source-end to
   destination-start distance and heading agreement. Parallel and opposing
   lanes remain separate.
3. Resolve intersection branches from the ego path actually observed in the
   recording. The selected route retains one `route_lane_id` before, through,
   and after an intersection; untraveled branches retain separate IDs.
4. Assign ego, left/right adjacent lanes, and detected objects at every original frame.
5. Select the nearest dynamic vehicle ahead in the ego route lane and emit exactly one per-frame state.
6. Merge only consecutive equal scenario states into inclusive observed-frame intervals.
7. Copy the established animated OD+LD explorer and add the generated lane
   tracker, gap extensions, lead selection, readout, and synchronized state
   timeline to its existing map and playback controls.

The combined explorer preserves the original object, LD, trajectory, timeline,
note, filtering, zoom, and playback behavior. The generated overlay highlights
every visible segment belonging to the current logical lane. Its controls can
show or hide left/ego/right lane areas, probable gap extensions, tracked
centerlines, and the selected lead. Lane identifiers remain internal and are
not drawn.

The tracker also reads the LD boundary `intersection` and `pattern` attributes:
intersection-attributed boundaries are purple and dashed, while ordinary
solid/dashed/virtual boundaries keep their recorded line pattern.

Virtual lane lines are treated as weaker lane-assignment evidence. A lane
bounded only by virtual lines receives a larger score penalty and cannot receive
`high` confidence. Mixed real/virtual evidence receives a smaller penalty.
Virtual-involving lanes whose centerline changes direction by more than 25
degrees are rejected. By contrast, a dashed lane line paired with a fragmented
`drivable` LD road boundary receives a reliability bonus. Physical segments
belonging to the previously selected logical route are preferred across short
boundary gaps, while the result remains a per-frame geometric assignment.

The explorer also includes a visualization-only experimental LD gap overlay.
It greedily joins aligned, color-compatible dashed-to-dashed and
solid-to-dashed line endpoints when the gap is 0.3-12 m and the heading
difference is at most 30 degrees. Each endpoint is used by at most one
connection. The overlay is computed once when the page loads, can be toggled
independently, and does not change lane geometry, lane assignment, lead
selection, or scenario tags.

Lane assignment also uses the LD boundary `drivable` attribute. A lane with an
explicitly non-drivable boundary is excluded; a lane with explicit drivable
evidence is preferred over one whose drivable status is unavailable. Missing
metadata stays `unknown` and is never converted to `true` implicitly.

An LD road boundary whose `boundary_attribute` is `drivable` is normalized as
a solid lane line. It participates in the same polygon, nearest-boundary,
assignment, route-bridge, and rendering logic as a regular LD lane line. The
original `road_boundary` source and attribute remain in the evidence fields.

When exact LD polygons contain a gap, the workflow builds a lower-confidence
`probable` corridor from the route lane's recorded direction and width. A gap
bounded by the same route on both sides may extend up to 65 m; an unbounded end
may extend only 20 m. The lateral allowance is the estimated half-width plus
0.75 m. Probable object assignment is limited to dynamic lead-capable classes
that are 0–80 m ahead. These settings are configurable and probable evidence is
kept distinct from exact polygon evidence in JSON and the explorer.

At a topology split, outgoing branches are classified by signed lateral
direction relative to the source lane: positive is left and negative is right.
The driven continuation remains ego while sibling branches receive left/right
roles. Probable gaps are rendered as lane-aligned boundary-to-boundary bridge
polygons on every frame, rather than a generic rectangular overlay.

Lead identity uses temporal hysteresis. The current lead is retained unless a
new candidate is at least 8 m closer for five consecutive frames. A missing
detection is held for up to five frames and visibly marked as predicted instead
of immediately jumping to another object.

A lead is eligible only when its center lies inside an exact polygon belonging
to the ego route or inside one of that route's explicit boundary-to-boundary
gap bridges. The broader endpoint/centerline extrapolation used to preserve ego
lane state cannot independently create a lead candidate.

`unknown` is emitted for invalid speed or an unassignable ego lane.
`not_applicable` is emitted below 0.5 m/s. Both states break scenario intervals;
there is no median, fixed window, smoothing, or state bridging.

## Commands

Run one recording through one stage at a time:

```powershell
python .\run_following_lane_pipeline.py Rec_Drv_GER_MACHET18_20260319_144819 --stop-after lane-geometry
python .\run_following_lane_pipeline.py Rec_Drv_GER_MACHET18_20260319_144819 --stop-after assignments
python .\run_following_lane_pipeline.py Rec_Drv_GER_MACHET18_20260319_144819 --stop-after tags
python .\run_following_lane_pipeline.py Rec_Drv_GER_MACHET18_20260319_144819
```

Run every canonical ODLD recording by omitting the recording ID:

```powershell
python .\run_following_lane_pipeline.py
```

By default, visualization writes a self-contained lane debugger. It shows the
current ego, left, and right lane polygons; physical and logical lane IDs;
assignment method/confidence; scored ego-lane candidates; source LD geometry;
and the complete per-frame detector output. Use the frame number field, arrow
keys, slider, or playback controls to navigate. The selected source frame is
also stored in the URL fragment, so a frame can be bookmarked or shared.

To inject the same lane overlay into an existing OD+LD explorer, pass:

```powershell
python .\run_following_lane_pipeline.py <recording-id> `
  --base-explorer-dir C:\path\to\dataset_scene_explorers_odld
```

Outputs are separated under `outputs/scenarios/following_lane/` as
`01_lane_geometry`, `02_frame_assignments`, `03_tags`, and `04_visualization`.
Thresholds are editable in `configs/following_lane.json`.
