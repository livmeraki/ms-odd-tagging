# Canonical package and command ownership

This document answers “for X, use Y.” Compatibility paths remain only to avoid
breaking existing notebooks, tests, and source-tree scripts.

| Responsibility | Canonical Python boundary | Canonical command | Status |
|---|---|---|---|
| Full deterministic input pipeline | `ms_odd_tagging.pipeline` | `ms-odd pipeline` / `ms-odd-tagging` | Production |
| Raw OD+LD+trajectory normalization | `ms_odd_tagging.canonical` | `ms-odd canonical` / `ms-odd-canonical` | Production |
| Canonical JSON to sampled frame inputs/BEVs | `ms_odd_tagging.frame_inputs` | `ms-odd frame-inputs` / `ms-odd-frame-inputs` | Production |
| Shared deterministic measurements | `ms_odd_tagging.features` | none | Production support |
| Scenario-specific production logic | `ms_odd_tagging.scenarios` and `ms_odd_tagging.tagger.rule_based` | `ms-odd rules` | Production |
| Geometry implementation ownership | `ms_odd_tagging.geometry` registry | none | Boundary registry |
| Model transport contract/backend ownership | `ms_odd_tagging.vlm` | `ms-odd tag` | Candidate boundary |
| Evaluation and GT comparison | `ms_odd_tagging.evaluation` | `ms-odd evaluate-rules` | Tool |
| Generic visualization | `ms_odd_tagging.visualization` | `ms-odd explore` | Tool |
| Lane/VLM research implementations | named PoC/candidate packages | `ms-odd *-poc` / candidate commands | Non-production |

## Dependency direction

1. `canonical` reads raw annotation and trajectory files and writes normalized
   recording JSON.
2. `frame_inputs` reads canonical JSON. It must not parse raw OD/LD files.
3. `features` derives measurements without deciding final scenario policy.
4. scenario/tagger packages apply policy and emit events or tags.
5. visualization and evaluation consume outputs; production code must not depend
   on either package.
6. experiments may consume canonical packages, but canonical packages must never
   import experiments.

## Compatibility import paths

The explorer-aligned builder is the only production frame-input route.
`frame_input.py`, `frame_input_revised.py`,
`_frame_input_standard_impl.py`, and
`_frame_input_explorer_aligned_impl.py` are compatibility/migration internals.
They are deliberately not installed command targets. The standard renderer path
remains solely as a regression oracle until output-equivalence fixtures allow

## Geometry and scenario ownership

Similar geometry is not automatically shared geometry. The registry in
`ms_odd_tagging.geometry` identifies the owner and lifecycle status of each
implementation. In particular, following-lane is production; LD topology is a
candidate; BEV-lane and Lanelet2 are experiments.

The registry in `ms_odd_tagging.scenarios` distinguishes reusable features,
production rule policy, candidate model inference, and Qwen experiment logic.
This prevents a PoC from becoming canonical merely through a newer filename.

## VLM ownership

`ms_odd_tagging.vlm` owns only transport-neutral request/response contracts and
backend lifecycle metadata. Prompt construction, candidate generation, and
scenario evidence remain with their scenario or experiment. The Qwen package is
therefore explicit experiment code, while the generic local-vLLM path remains a
candidate compatibility backend.

## Compatibility policy

Existing `ms-odd-*` commands and root `run_*.py` scripts remain supported in
this PR. `ms-odd` is the single discoverable command surface for new use.
Compatibility paths may be removed only after caller search, fixture comparison,
and a deprecation window.


## Physical implementation ownership

Canonical normalization now lives in `ms_odd_tagging.canonical`; active per-frame JSON, generation policy, and BEV rendering live in `ms_odd_tagging.frame_inputs`. The similarly named modules under `ms_odd_tagging.input_generator` are compatibility aliases only. They resolve to the same module objects so existing imports and monkeypatch points continue to work, but all new code and tests must import the owning packages directly.
