# Motional Scenario Prompt Pack

Reusable prompts for evaluating synchronized OD + LD + ego-trajectory frames with LLM/VLM APIs.

The prompts are designed for the current model input package:

```text
outputs/02_frame_inputs/<recording>/frame_<index>/
  frame.json
  bev.png
```

For Together Qwen3 2B Vision:

- Use `system_prompt.md` as the system message.
- Use `json_only_user_prompt.md` for the JSON-only run.
- Use `json_bev_user_prompt.md` for the JSON + BEV run.
- Require output matching `output_schema.json`.

Efficiency notes:

- Do not include `preliminary_candidates` in the model input for the first
  unbiased test. Keep it only for later comparison against the formula-only
  baseline.
- Send exactly one frame and its same-frame BEV per request.
- Keep output concise and schema-valid.
- Ask for evidence summaries, not hidden chain-of-thought.
- Use PNG/JPEG BEV images for true vision input.
