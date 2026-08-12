# VLM Understanding PoC

This PoC is diagnostic. It does **not** start by asking the VLM for a motional-scenario tag. It separates failures into four stages:

1. `bev_symbol_literacy` — can the model read the custom BEV visual language?
2. `spatial_understanding` / `temporal_understanding` — can it reason about positions and motion from BEV?
3. `structured_comprehension` — can it correctly read neutral structured evidence without images?
4. `fusion_consistency` — can it combine BEV and structured evidence without inventing or contradicting facts?

The existing BEV renderer currently uses, among other cues, a green ego footprint/nose, orange pedestrians, class-specific object colors, cyan proximity outline, blue lane lines, red crosswalks, purple stoplines, amber/brown road boundaries, and a yellow highlight for active objects. The PoC should explicitly test these conventions rather than assuming the VLM understands them.

## 1. Create a probe manifest

Copy the example:

```bash
cp examples/vlm_understanding_poc_manifest.example.json examples/vlm_understanding_poc_manifest.json
```

Edit each `images` path to point to real BEV PNGs. Paths are resolved relative to the manifest file. For structured evidence, either inline JSON directly or use:

```json
"structured_evidence": {"json_file": "../some/evidence.json"}
```

The same form works for `legend`.

For every probe, set a small, objectively checkable `expected_answer`. Keep questions factual. Examples:

- identify ego and forward direction
- identify pedestrian/object color
- count visible objects
- front/behind/left/right
- same lane vs adjacent lane
- stopline ahead vs behind
- pedestrian moving toward/away/stationary across consecutive BEVs
- restate ego speed or object position from structured evidence
- check whether BEV and structured evidence agree

Do not begin with scenario tags such as `waiting_for_pedestrian_to_cross`; add those only after the perception tests pass.

## 2. Run a smoke test

With the local OpenAI-compatible vLLM server already running on port 8001:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.cli \
  --manifest examples/vlm_understanding_poc_manifest.json \
  --limit 3
```

Default endpoint and model are:

```text
http://127.0.0.1:8001/v1/chat/completions
Qwen/Qwen3-VL-8B-Instruct
```

Override if needed:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.cli \
  --manifest examples/vlm_understanding_poc_manifest.json \
  --endpoint http://127.0.0.1:8001/v1/chat/completions \
  --model Qwen/Qwen3-VL-8B-Instruct
```

## 3. Run one diagnostic layer at a time

BEV literacy only:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.cli \
  --manifest examples/vlm_understanding_poc_manifest.json \
  --category bev_symbol_literacy
```

Spatial and temporal reasoning:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.cli \
  --manifest examples/vlm_understanding_poc_manifest.json \
  --category spatial_understanding \
  --category temporal_understanding
```

Structured evidence only:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.cli \
  --manifest examples/vlm_understanding_poc_manifest.json \
  --modality structured_only
```

Fusion only:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.cli \
  --manifest examples/vlm_understanding_poc_manifest.json \
  --modality fusion
```

## 4. Outputs

Default output directory:

```text
outputs/vlm_understanding_poc/
```

It contains:

- `probe_results.jsonl` — full model observations, visual cues, structured fields, confidence, ambiguity, elapsed time, and correctness
- `review.csv` — compact row-per-probe review sheet
- `summary.csv` — accuracy grouped by `category × modality`

The key diagnostic comparison is not just total accuracy. Compare the same facts across modalities:

```text
BEV only -> structured only -> fusion
```

A failure pattern can then be interpreted as:

- BEV wrong, structured correct: visual-language/perception problem
- BEV correct, structured wrong: serialization/prompt comprehension problem
- both correct, fusion wrong: modality conflict/fusion problem
- all factual probes correct, scenario tag wrong: scenario definition/reasoning boundary problem

## Recommended first dataset

Start with about 20 deliberately selected scenes rather than a large batch. Include easy positives, easy negatives, and confusing cases. Aim for 15–20 factual probes per scene only if useful; duplicated or trivial questions add little value.

For the BEV specifically, include controlled ablations:

1. normal BEV + legend
2. normal BEV without legend
3. recolored BEV with matching changed legend
4. recolored BEV with original legend (intentional contradiction)
5. BEV with one symbol removed

This tests whether the VLM is actually reading the supplied visual convention versus relying on memorized color priors or geometry alone.
