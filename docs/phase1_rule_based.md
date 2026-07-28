# Phase 1 trajectory rule engine

Phase 1 detects ten trajectory-only event labels: `stationary`, the three
mutually exclusive moving speed bands, `high_lateral_acceleration`,
`high_magnitude_jerk`, and left/right plus low/high-speed starting-turn labels.
It does not implement OD, LD, lane-change, crosswalk, proximity, or lead/trail
rules.

## Input and feature semantics

The engine consumes the ordered `frames` array from either canonical schema.
It preserves `frame_index` and uses `time_since_start_s` in seconds. Canonical
ego position and velocity are LCS metres and m/s. `speed_mps` is the magnitude
of the canonicalizer's timestamp-derived horizontal velocity.
`acceleration_mps2` is the timestamp-derived scalar speed derivative.
`heading_lcs_rad` is standard quaternion yaw in radians, and
`yaw_rate_radps` is its timestamp-derived rate. These canonical values are not
changed.

The detection feature layer causally derives world acceleration from adjacent
velocity samples, rotates it into the current ego body frame, and calculates:

```text
a_long =  cos(heading) * ax + sin(heading) * ay
a_lat  = -sin(heading) * ax + cos(heading) * ay
|a|    = hypot(a_long, a_lat)
j_long = (a_long[t] - a_long[t-1]) / actual_dt
j_lat  = (a_lat[t] - a_lat[t-1]) / actual_dt
jerk   = hypot(j_long, j_lat)
```

The configured jerk feature is the magnitude of the 2D acceleration-vector
derivative. It therefore preserves jerk caused by acceleration-direction
changes even when acceleration magnitude remains constant. The earlier
change-in-acceleration-magnitude calculation remains available only as the
legacy `acceleration_magnitude` mode. Heading is unwrapped
with the shortest signed angular difference before rate or accumulated-change
calculations. No smoothing is enabled. Zero/negative time deltas and gaps over
`max_sample_gap_s` invalidate affected derivatives and are reported as quality
issues; invalid samples break rather than bridge events. Empty and single-frame
inputs are valid. Missing frame identity, timestamp, or ego objects fail
clearly.

## Rules and boundaries

All numeric policy is centralized in `configs/direct_scenarios.yaml`.

- Stationary is `[0, 0.5)` m/s (`taxonomy_defined`). Speed-band segmentation
  is lossless by default: no speed band has a minimum-duration filter.
- Low is `[0.5, 5.0)`, medium `[5.0, 15.0)`, and high `[15.0, infinity)`
  (`taxonomy_defined`). There is no stationary/low gap. Negative or invalid
  speed is unclassified. Per-frame bands are exclusive; the existing window
  median remains available for legacy summaries.
- Speed event bounds are inclusive samples: `start_frame`/`start_timestamp_s`
  and `end_frame`/`end_timestamp_s` identify the first and last classified
  samples. Adjacent states therefore end at one sample and begin at the next;
  invalid or missing speed samples terminate an interval and are never bridged.
- High lateral acceleration enters at absolute 2.5 m/s² and releases below
  2.0 m/s² for at least 0.3 s (`engineering_default`). Evidence retains the
  signed peak.
- High jerk enters at 5.0 m/s³ and releases below 4.0 m/s³ for at least 0.1 s;
  isolated samples are rejected (`engineering_default`).
- A turn enters at absolute yaw rate 0.08 rad/s, releases below 0.04 rad/s,
  lasts at least 0.5 s, and accumulates at least 0.30 rad. When complete ODLD
  lane context shows that the ego remains on one logical route lane throughout
  the candidate, the accumulated-heading requirement is raised to 60 degrees
  (1.0472 rad) to reject ordinary curved-lane following. Inactive gaps,
  pre-context, and post-context are configurable. These magnitude/duration
  values are `provisional`.
- Standard LCS quaternion yaw is counter-clockwise about +Z, so positive
  heading change is configured as left, matching the prior pipeline sign.
- Turn-speed qualification uses the exact speed at the yaw-rate trigger frame:
  low below 5.0 m/s and high at or above 5.0 m/s. The cutoff is `provisional`.

A physical turn produces one direction event and one speed-qualified event.
Both carry the same `physical_turn_event_id`; they are complementary labels,
not duplicate physical detections. Event boundaries include configured context,
while `trigger_start_frame` and `trigger_end_frame` preserve the active rule
range. Duration is the end timestamp minus the start timestamp.

## Pipeline and output

Per-frame input generation runs the engine once over the full recording and
writes `recording_rule_events.json` beside the frame folders. Each canonical
frame independently produces one model-facing `frame.json` and one same-frame
`bev.png`. Rule labels remain outside model inputs to prevent label leakage.

Run the standalone detector after canonicalization:

```bash
python -m ms_odd_tagging.tagger.rule_based.registry \
  outputs/01_canonical/RECORDING_canonical_frames.json \
  --output outputs/04_tagging/RECORDING_rule_events.json
```

An event contains scenario, original frame/timestamp bounds, duration,
detector version, deterministic confidence, and measured evidence with
threshold provenance.

## Extension contract

Implement the `ScenarioDetector` protocol, declare `required_features` and
`output_scenarios`, then register the detector in `detector_registry()`.
Dependencies can use names such as `trajectory.speed_mps`, `od.objects`,
`ld.lanes`, `od.objects + trajectory`, `ld.lanes + trajectory`, or
`od.objects + ld.lanes + trajectory`. Future modalities can emit the same
`ScenarioEvent`; no central scenario-specific branching is required. Phase 1
deliberately registers trajectory-only detectors.

Synthetic tests establish implementation and boundary behavior only. The
provisional thresholds and sign convention still require human validation on
representative recordings; a smoke result is never ground truth.
