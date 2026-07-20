We need to implement the directly derivable motional scenarios in the existing
`ms-odd-tagging` repository using OD ALT, LD ALT, and ego trajectory data.
>>do we make it in the same repo?

Do not begin by editing code.

First inspect the existing repository, current data schemas, sample outputs, and
pipeline. Then report your findings and propose a concrete implementation plan.
After presenting the plan, proceed with implementation unless a critical
ambiguity would make the implementation unsafe.

==================================================
1. PROJECT CONTEXT
==================================================

The current pipeline uses:

- Ego trajectory / SLAM data
- OD ALT objects with timestamped bbox3d information
- LD ALT lane lines, road boundaries, and free-space information
- Canonical synchronized JSON
- BEV visualizations
- JSON-only and JSON+BEV model evaluation modes
- Rule-based candidate generation
- LLM/VLM verification and final JSON generation

Important existing repository location:

- Repository: `ms-odd-tagging`
- Canonical OD+LD builder:
  `src/ms_odd_tagging/canonical/build_canonical_odld_json.py`

LD data currently exists for only a limited number of recordings, so prioritize
those recordings for development and validation.

The current goal is to implement scenarios classified as directly derivable in:

`Motional Scenarios(Derivability (OD+LD+traj-based)).csv`

Read that file and use its `Derivability`, `Scenario`, `Scenario Definition`,
and reasoning columns as the authoritative initial scope.

Do not implement LLM/VLM-only or hybrid scenarios as deterministic rules unless
they are required as shared infrastructure.

==================================================
2. INSPECTION REQUIRED BEFORE EDITING
==================================================

Inspect at least:

1. Repository structure and current Git status.
2. Canonical OD+LD+trajectory schema.
3. Raw OD, LD, and trajectory readers.
4. Timestamp and frame synchronization logic.
5. Current coordinate conventions.
6. Current window builder.
7. Existing preliminary candidate or scenario-tagging logic.
8. Existing BEV renderer.
9. Existing JSON-only and JSON+BEV prompt builders.
10. Existing output schemas and validators.
11. Existing tests and sample recordings.
12. The derivability CSV and all scenarios marked `Direct`.

Confirm through the actual data:

- trajectory sampling rate,
- canonical frame sampling rate,
- timestamp units,
- ego coordinate convention,
- OD bbox3d coordinate convention,
- object ID persistence,
- whether OD object positions are already ego-relative,
- whether OD object velocity is provided or must be derived,
- LD lane ID stability across frames,
- LD lane point ordering,
- whether LD IDs such as L1/R1 are spatial labels or persistent track IDs,
- lane and boundary confidence fields,
- availability of crosswalk and stopline objects,
- how missing LD frames are represented.

Do not assume that lane labels are temporally persistent without verifying them.

Before implementation, output:

A. A concise repository/data inspection summary.
B. A table of all `Direct` scenarios containing:
   - scenario name,
   - required source data,
   - shared features,
   - proposed rule,
   - unresolved assumptions,
   - expected output type.
C. A staged implementation plan.
D. Files that will be added or modified.

==================================================
3. DYNAMIC EVENT TAGGING
==================================================

Change motional scenario tagging from static window-level classification to
dynamic event detection.

The detector should not only say that a scenario exists somewhere in a window.
It must identify when the event begins and ends.

Internally, detectors may generate frame-level Boolean signals or scores, but
the final rule-based output must consist of event intervals.

Recommended event structure:

{
  "scenario": "changing_lane_to_left",
  "start_frame": 120,
  "end_frame": 157,
  "start_timestamp_s": 12.0,
  "end_timestamp_s": 15.7,
  "duration_s": 3.7,
  "confidence": 1.0,
  "evidence": {
    "...": "scenario-specific evidence"
  }
}

Use the repository’s existing naming and schema conventions where possible.
Do not silently introduce an incompatible second event schema.

Implement reusable temporal processing:

- trigger-on condition,
- active-state continuation,
- trigger-off condition,
- minimum active duration,
- entry hysteresis,
- exit hysteresis,
- merge short gaps,
- suppress isolated one-sample spikes,
- configurable pre-event and post-event padding,
- handling of missing observations,
- handling of recording boundaries,
- no event leaking across recordings.

Make event segmentation generic rather than implementing custom interval merging
inside every detector.

==================================================
4. ONE TAGGING SAMPLE PER SECOND
==================================================

The rule-based tagging decision timeline should operate at 1 Hz:

- Generate one tagging observation per second of recording.
- Select samples by timestamp, not by assuming a fixed raw frame interval.
- Preserve the mapping from each 1 Hz observation to its original frame index
  and timestamp.
- Define deterministic behavior when no frame occurs at an exact whole second,
  such as nearest valid frame within a configurable tolerance.
- Avoid duplicate source frames.
- Report missing seconds explicitly when no frame is within tolerance.

Important distinction:

- Output decisions and event state transitions are evaluated on the 1 Hz
  tagging timeline.
- Higher-frequency raw/canonical frames may still be used internally when
  necessary to calculate stable speed, acceleration, jerk, heading, lane
  association, or object motion.
- Do not reduce derivative quality by calculating jerk from only sparse 1 Hz
  points when better synchronized source data exists.
- Event boundaries will therefore be reported at approximately one-second
  resolution unless refined from valid high-frequency evidence.

Create a reusable timestamp-based 1 Hz sampler and test irregular timestamps,
dropped frames, and non-zero recording start times.

==================================================
5. SHARED FEATURE EXTRACTION
==================================================

Create a shared feature layer. Scenario detectors must not independently
recalculate the same quantities.

Suggested organization, adapted to the repository:

features/
  ego_motion.py
  object_motion.py
  object_tracks.py
  lane_geometry.py
  lane_assignment.py
  spatial_relations.py
  crosswalk_geometry.py

detectors/
  base.py
  dynamics.py
  turns.py
  lane_change.py
  proximity.py
  crosswalk.py
  registry.py
  event_segmentation.py

Use the current repository structure if it already has equivalent modules.

--------------------------------------------------
5.1 Ego-motion features
--------------------------------------------------

Provide reusable, timestamp-aware calculations for:

- ego speed,
- longitudinal acceleration,
- lateral acceleration,
- acceleration magnitude,
- jerk magnitude,
- ego heading,
- unwrapped heading,
- heading-rate / yaw-rate,
- cumulative heading change,
- trajectory curvature,
- lateral displacement relative to the local path,
- stopped duration.

Use actual timestamp differences.
Do not assume constant frame spacing.
Handle angle wraparound correctly.
Do not smooth by default in a way that removes real peaks.

If smoothing is needed:

- make it optional and configurable,
- preserve the original signal,
- document the method,
- expose both raw and processed values,
- avoid aggressive smoothing that cuts meaningful hills and valleys.

--------------------------------------------------
5.2 Other-vehicle speed and heading
--------------------------------------------------

Calculate surrounding-object motion from persistent OD tracks when reliable
velocity is not directly provided.

For each usable object track derive, where possible:

- object speed,
- object heading,
- velocity vector,
- longitudinal velocity relative to ego,
- lateral velocity relative to ego,
- relative speed,
- distance to ego,
- bearing relative to ego,
- motion direction confidence,
- number of observations used,
- track continuity and timestamp gaps.

Important:

- Do not estimate world motion by directly differentiating ego-relative
  coordinates without compensating for ego translation and rotation.
- Transform observations into a consistent local or world coordinate system
  before deriving object velocity.
- Use object orientation only after confirming quaternion and heading
  conventions.
- Distinguish object body orientation from actual direction of travel.
- Mark speed or heading as unavailable when the track is too short,
  discontinuous, or unreliable.
- Do not fabricate a value from one observation.
- Add configurable minimum track duration and displacement thresholds.

These features should support scenarios such as:

- near_high_speed_vehicle,
- crossed_by_vehicle,
- crossed_by_bike,
- following or lead-vehicle scenarios,
- vehicle motion reasoning in later phases.

==================================================
6. LANE GEOMETRY AND LANE-ID TRACKING
==================================================

Lane understanding is required to distinguish:

- following a curving lane,
- turning,
- changing lanes,
- simply following the same physical lane.

Do not classify a turn or lane change using global heading change alone.

Implement reusable lane geometry and lane-assignment features.

--------------------------------------------------
6.1 Lane representation
--------------------------------------------------

Represent each LD lane line using its geometric polyline rather than fitting
only one global straight line.

Where appropriate:

- validate and filter low-confidence points,
- order points consistently from near ego to far ego,
- resample polylines by arc length,
- preserve curved geometry,
- calculate local tangent and normal,
- calculate signed distance from ego to a lane line,
- calculate closest point,
- calculate local lane heading,
- calculate lane width from paired boundaries,
- avoid forcing curved lanes into a single straight-line model.

--------------------------------------------------
6.2 Temporal lane tracking
--------------------------------------------------

Track physical lane-line identities over time.

Do not assume labels such as L1, R1, L2, and R2 remain stable across frames.

Associate lane lines between timestamps using a combination of:

- geometric overlap,
- resampled point distance,
- local heading similarity,
- left/right ordering,
- confidence,
- predicted position after ego motion compensation.

Create stable internal lane-track IDs when possible.

Expose association quality and avoid switching track IDs when detections reorder.

--------------------------------------------------
6.3 Current ego lane
--------------------------------------------------

Infer and track the ego vehicle’s current lane corridor.

The current lane should be represented by:

- stable current-lane ID,
- left boundary track ID,
- right boundary track ID,
- lane centerline,
- local lane heading,
- lane width,
- ego lateral offset from center,
- lane-assignment confidence,
- reason when assignment is unavailable.

Use temporal continuity and hysteresis to prevent lane identity flicker.

A lane change should be based primarily on a transition from one physical lane
corridor to an adjacent physical lane corridor, not merely lateral ego movement
or heading change.

A curved road should retain the same current-lane ID while ego follows the lane.

--------------------------------------------------
6.4 Turn versus lane change
--------------------------------------------------

Create explicit features that allow detectors to distinguish:

- same-lane curvature following,
- lane change to the left,
- lane change to the right,
- road or intersection turn,
- uncertain lane geometry.

Potential evidence includes:

- stable physical lane ID before and after,
- ego crossing a tracked lane boundary,
- centerline transition,
- signed lateral offset progression,
- heading change relative to current lane tangent,
- absolute ego heading change,
- lane continuation availability,
- duration of the transition.

Do not use one hardcoded heuristic without exposing its evidence.

==================================================
7. BEV VISUALIZATION
==================================================

Update the BEV visualization to make lane-related decisions inspectable.

The BEV must clearly show:

- ego vehicle,
- ego trajectory,
- OD objects and IDs,
- LD lane lines,
- stable internal lane-track IDs when available,
- current ego lane highlighted,
- left and right current-lane boundaries,
- current-lane centerline,
- current lane ID,
- lane-assignment confidence,
- current 1 Hz tagging timestamp,
- active rule-based events.

Use the existing BEV coordinate convention:

- ego centered at selected frame,
- ego forward points upward,
- ego left is image left.

The current-lane highlight must fill only the lane corridor between the correct
left and right boundaries. It must not confuse a lane centerline with a lane
boundary or overlap adjacent lanes.

Keep the default visualization readable. Put detailed debug overlays behind
CLI flags or configuration options.

Add an optional debug BEV mode showing:

- lane association across adjacent samples,
- previous/current stable track IDs,
- ego lateral offset,
- boundary-crossing evidence,
- detector evidence.

==================================================
8. CONFIGURABLE LD AND OD RADIUS THRESHOLDS
==================================================

Create centralized configuration for spatial thresholds.

At minimum support:

- general OD object search radius,
- vehicle radius,
- pedestrian radius,
- bike radius,
- motorcycle radius,
- traffic cone radius,
- barrier radius,
- LD lane search radius,
- LD crosswalk search radius,
- LD stopline search radius,
- lane-assignment maximum distance,
- minimum LD confidence,
- minimum OD track duration.

Do not scatter magic numbers across detector modules.

Use explicit units in names, for example:

- `vehicle_radius_m`
- `lane_search_radius_m`
- `min_track_duration_s`

Where scenario definitions require different distances, use scenario-specific
configuration while retaining shared defaults.

Evidence should include the threshold used and the measured value.

==================================================
9. DIRECT-SCENARIO IMPLEMENTATION ORDER
==================================================

Implement in stages, but keep one shared architecture.

Stage A: trajectory-based dynamics and turns

Examples include, depending on the CSV’s Direct rows:

- stationary
- low_magnitude_speed
- medium_magnitude_speed
- high_magnitude_speed
- high_lateral_acceleration
- high_magnitude_jerk
- starting_left_turn
- starting_right_turn
- starting_low_speed_turn
- starting_high_speed_turn

Stage B: trajectory + lane/crosswalk rules

Examples include, only when marked Direct:

- changing_lane
- changing_lane_to_left
- changing_lane_to_right
- traversing_crosswalk
- on_stopline_crosswalk
- accelerating_at_crosswalk
- stopping_at_crosswalk
- stationary_at_crosswalk

Stage C: OD spatial and object-motion rules

Examples include, only when marked Direct:

- near_high_speed_vehicle
- near_long_vehicle
- near_multiple_bikes
- near_multiple_motorcycle
- near_multiple_pedestrians
- near_multiple_vehicles
- near_pedestrian_on_crosswalk
- near_pedestrian_on_crosswalk_with_ego

The actual implementation list must come from the CSV, not only from the
examples above.

Commit or structure changes so that each stage can be reviewed independently.
Do not implement all detectors as one large file.

==================================================
10. RULE DESIGN REQUIREMENTS
==================================================

Each detector must provide:

- scenario name,
- required source data,
- candidate condition,
- event start condition,
- event continuation condition,
- event end condition,
- minimum duration,
- configurable thresholds,
- confidence or rule quality,
- evidence fields,
- explicit unavailable/insufficient-data handling.

A detector must not return false merely because required data is missing.
Internally distinguish:

- true,
- false,
- unavailable / insufficient evidence.

Map this appropriately to the repository’s external schema without silently
treating unavailable evidence as a confident rejection.

Mutually exclusive groups should be enforced where applicable:

- stationary / low / medium / high speed,
- left / right lane-change direction,
- left / right starting turn,
- low-speed / high-speed turn where definitions are exclusive.

More specific tags may coexist with their parent tag when taxonomy semantics
require it. For example:

- `changing_lane`
- `changing_lane_to_left`

Document the parent-child policy and apply it consistently.

==================================================
11. SPEED AND DERIVATIVE THRESHOLDS
==================================================

Reuse authoritative thresholds already present in the repository or taxonomy.

Known existing speed-band definitions should not be contradicted:

- stationary: use the project’s confirmed stationary threshold
- low: 0.5 <= representative speed < 5 m/s
- medium: 5 <= representative speed < 15 m/s
- high: representative speed >= 15 m/s

Before coding, verify how the current project defines representative speed for
dynamic events:

- instantaneous 1 Hz sample,
- local median,
- rolling median,
- event median,
- another existing definition.

Choose one definition explicitly and test exact threshold boundaries.

Do not generate explanations that contradict the numeric condition.

==================================================
12. MODEL INPUT COMPACTION
==================================================

The JSON+BEV mode currently sends structured JSON together with BEV images.

Compact the model-facing JSON input to reduce token count while preserving all
information needed for scenario decisions.

Requirements:

- Keep canonical source data unchanged.
- Implement compaction only in the model-input or prompt-preparation layer.
- Do not mutate source JSON.
- Remove redundant repeated fields.
- Avoid repeating static metadata in every frame.
- Round numeric values only at the model-facing serialization boundary.
- Preserve frame/timestamp references.
- Preserve evidence needed by the taxonomy.
- Preserve object IDs and stable lane IDs.
- Prefer compact arrays or shared dictionaries when they remain unambiguous.
- Include a format/schema version.
- Provide a readable debug expansion or documentation for the compact format.
- Compare approximate serialized character/token counts before and after.
- Add a test that compaction does not remove required fields.

Do not compact JSON-only mode and JSON+BEV mode into semantically different
evidence. The modes should differ only in whether BEV images are attached and
in clearly documented image-specific references.

==================================================
13. ONE OUTPUT SCHEMA FOR JSON AND JSON+BEV
==================================================

JSON-only and JSON+BEV modes must use exactly the same final model output schema
so their results can be compared fairly.

Requirements:

- one schema file or one schema definition,
- one validator,
- one taxonomy list,
- same required top-level fields,
- same per-label structure,
- same evidence structure,
- same rejected-label behavior,
- same schema version,
- same deterministic validation rules.

The prompt content may differ because BEV images are attached in one mode, but
the expected response schema must not differ.

Refactor duplicate output schemas if they currently exist.

Add a test that builds both modes and asserts equality of the final response
schema.

==================================================
14. PROPOSED COMMON INTERFACES
==================================================

Adapt these ideas to the existing codebase rather than copying them blindly.

Detector interface:

class ScenarioDetector(Protocol):
    scenario_name: str

    def detect(
        self,
        observations: Sequence[TaggingObservation],
        context: DetectionContext,
        config: DetectorConfig,
    ) -> list[ScenarioEvent]:
        ...

Shared tagging observation:

- tagging_index
- source_frame_index
- timestamp_s
- ego-motion features
- current-lane assignment
- nearby-object features
- map/crosswalk/stopline relations
- data-availability flags

Detector registry:

- register detectors by scenario name,
- select scenarios through CLI/config,
- deterministic detector order,
- no import-time side effects.

==================================================
15. OUTPUT FILES
==================================================

Produce:

1. Dynamic event JSON for each recording.
2. Optional 1 Hz frame-level diagnostic JSON.
3. A scenario summary containing:
   - event count,
   - total active duration,
   - first/last occurrence,
   - unavailable-data count.
4. BEV debug images for selected samples.
5. A machine-readable threshold/config snapshot.
6. A detector coverage report showing:
   - implemented Direct scenarios,
   - skipped Direct scenarios,
   - reason for each skip.

Do not silently label an unimplemented scenario as false.

==================================================
16. TESTING
==================================================

Add unit tests for:

- timestamp-based 1 Hz sampling,
- irregular timestamps,
- dropped frames,
- angle unwrapping,
- speed-band boundaries,
- acceleration and jerk with variable dt,
- object velocity with ego-motion compensation,
- short or broken object tracks,
- curved-lane following without false lane change,
- actual left lane change,
- actual right lane change,
- lane-ID reorder without physical lane switch,
- lane assignment hysteresis,
- current-lane corridor selection,
- event onset/offset,
- minimum duration,
- gap merging,
- events at recording boundaries,
- unavailable LD data,
- unavailable OD data,
- OD/LD radius thresholds,
- identical output schema for JSON and JSON+BEV,
- compact model input retaining required evidence.

Where sample GT does not exist, add synthetic deterministic fixtures.

Also run the implementation on at least one recording with LD and one recording
without LD. Report the difference in detector availability.

==================================================
17. CLI AND BACKWARD COMPATIBILITY
==================================================

Integrate with the current CLI rather than creating a disconnected script.

Useful options may include:

- `--tagging-rate-hz 1`
- `--scenarios ...`
- `--config ...`
- `--recording ...`
- `--debug-bev`
- `--write-frame-diagnostics`
- `--compact-model-input`
- `--no-compact-model-input`

Preserve existing behavior where practical.
If an incompatible change is necessary, explain it and add a migration note.

==================================================
18. IMPLEMENTATION CONSTRAINTS
==================================================

- Do not use an LLM/VLM to solve deterministic geometry or arithmetic.
- Do not hardcode recording-specific IDs or frame ranges.
- Do not edit source annotation data.
- Do not overwrite existing outputs by default.
- Do not duplicate canonical data structures unnecessarily.
- Do not hide errors through broad exception handling.
- Use typed data structures where the project style permits.
- Use clear units in field names.
- Keep calculations deterministic.
- Preserve original raw and derived signals.
- Add logging for unavailable evidence and rejected lane/object associations.
- Avoid a large rewrite unrelated to this task.

==================================================
19. COMPLETION REPORT
==================================================

After implementation, report:

1. Inspection findings.
2. Direct scenarios found in the CSV.
3. Direct scenarios implemented.
4. Direct scenarios not implemented and why.
5. Files added and modified.
6. Rule and threshold summary.
7. Dynamic-event output example.
8. 1 Hz sampling behavior.
9. Lane-tracking and current-lane method.
10. Other-vehicle speed and heading method.
11. BEV current-lane highlighting changes.
12. Model-input compaction results.
13. Confirmation that both model modes share one output schema.
14. Tests run and results.
15. Commands to reproduce the outputs.
16. Known limitations and recommended next step.

Do not claim a scenario works merely because the code runs. Distinguish between:

- implemented,
- unit-tested,
- sample-tested,
- manually verified,
- blocked by unavailable or unreliable data.