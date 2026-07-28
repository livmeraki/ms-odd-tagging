# Prompt Usage Notes

## Recommended first experiment

Recording:

```text
Rec_Drv_GER_MACHET18_20260227_153128
```

Runs:

1. Rule-based per-frame baseline from `recording_rule_events.json`.
2. Per-frame JSON-only Qwen3 2B Vision using `json_only_user_prompt.md`.
3. Per-frame JSON + current-frame BEV using `json_bev_user_prompt.md`.

## Bias control

Keep `recording_rule_events.json` separate from each `frame.json`. The frame
generator already does this so formula labels cannot leak into model input.

## Suggested compact model input

Keep:

- `schema_version`
- `recording_id`
- `frame_id`
- `frame_index`
- `time_since_start_s`
- `bev`
- `taxonomy`
- `ego`
- `scenario_signals`
- `object_counts`
- `objects`
- `interaction_candidates`
- `ld`
- `data_notes`

Remove:

- rule-based event outputs
- samples from neighboring frames
- any fields not used by the schema

## Output handling

Reject and retry if:

- output is not valid JSON
- a required label is missing
- label values are strings instead of booleans
- confidence is outside `[0, 1]`
- `recording_id`, `frame_id`, or `model_mode` is missing

Retry prompt suffix:

```text
Your previous response did not match the required JSON schema. Return only valid JSON. Do not include markdown or explanation outside the JSON object.
```
