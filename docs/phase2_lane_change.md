# Phase 2 boundary-crossing lane-change PoC

The detector consumes ego motion, the existing following-lane tracker's
physical/logical identities, and nearby LD lane-boundary geometry. It does not
perform lane assignment itself.

An ego-center crossing of a nearby non-intersection LD lane line is the
mandatory and ultimate trigger. Candidate crossings are evaluated independently
of lane-ID changes; identities and adjacency are evidence, not prerequisites.
A logical lane-ID transition alone cannot emit an event. Boundaries marked as
intersection geometry and normalized road boundaries are not eligible triggers.

A transition is emitted only when the ego center remains on the crossed-to side
after the configured confirmation interval and exceeds the minimum signed
distance from the crossed segment. Left versus right comes from signed ego
motion across the oriented boundary. Returning across the line before
confirmation rejects that directional candidate.

Each confirmed physical transition emits the generic lane-change event and
exactly one directional event. Both labels share a physical event ID. Event
bounds include configured pre-crossing context through the frame that confirms
crossing persistence. Detection runs once on the recording; windows only
reference the same recording-level event.

Thresholds are defined under lane_change_detection in
configs/direct_scenarios.yaml.
