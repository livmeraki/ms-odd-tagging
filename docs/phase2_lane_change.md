# Phase 2 basic lane-change detection

The detector consumes the existing following-lane tracker's per-frame logical
ego lane and left/right adjacent logical lanes. It does not perform lane
assignment itself.

A transition is emitted only when the source lane has been stable, the target
is a source-adjacent lane, and the target remains stable for the configured
duration. The target must appear in the source lane's left/right adjacency
within the configured missing-gap tolerance immediately before the transition.
That near-boundary source-side adjacency determines left versus right.
Short missing assignments and temporary unrelated lane IDs are tolerated only
up to their configured limits. Returning to the source before confirmation
rejects the candidate.

Each confirmed physical transition emits `changing_lane` and exactly one of
`changing_lane_to_left` or `changing_lane_to_right`. Both labels share a
`physical_lane_change_event_id`. Event bounds are inclusive observed frames:
the final confirmed source frame through the frame that confirms target
stability. Detection runs once on the recording; windows only reference the
same recording-level event.

Thresholds are defined under `lane_change_detection` in
`configs/direct_scenarios.yaml`.
