# Developer Handover Guide

This document is for the engineer who will take over and further improve the Motional Scenario ODD Tagging project. It explains what the project does, where the important files are, how to run the main tools, and where future development should focus.

## 1. What this project does

The project automatically tags autonomous-driving Motional Scenarios from three main sources:

```text
annotations_OD.json
annotations_LD.json
traj_lcs.txt
```

- **OD annotation** provides detected objects and their properties.
- **LD annotation** provides road geometry such as lanes, boundaries, crosswalks, and stoplines.
- **Ego trajectory** provides the ego vehicle pose and motion over time.

The important difference from normal frame-level ODD tagging is that many Motional Scenarios require temporal interpretation. Labels such as `changing_lane`, `starting_left_turn`, or `waiting_for_pedestrian_to_cross` cannot always be decided from one frame. The system therefore combines geometry, object relations, ego motion, temporal filtering, and selective VLM reasoning.

The current high-level flow is:

```text
Raw Recording
    │
    ▼
Canonicalization
    │
    ▼
outputs/01_canonical
    │
    ├─────────────── Rule / Geometry / Temporal analysis
    │
    └─────────────── Frame / BEV generation
                         │
                         ▼
                  outputs/02_frame_inputs
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        Rule scenario tags      VLM candidates
                                      │
                                      ▼
                               VLM inference
                                      │
                                      ▼
                               validation / merge
              └──────────┬───────────┘
                         ▼
               Motional Scenario tags
                         │
                         ▼
                    GT Workspace
```

The project intentionally uses deterministic rule/geometry logic where the evidence is explicit, and VLM only where semantic interpretation is useful.

---

## 2. Start here

For a new developer, read the repository in this order:

1. `README.md`
2. `docs/handover/KOR/00_OVERVIEW.md`
3. `docs/handover/KOR/01_SETUP_AND_RUN.md`
4. `docs/handover/KOR/02_PIPELINE.md`
5. `docs/handover/KOR/04_SCENARIO_STATUS.md`
6. `docs/handover/KOR/07_KNOWN_ISSUES.md`
7. `docs/handover/KOR/08_NEXT_STEPS.md`

The Korean handover files remain the detailed project reference. This English guide is the developer-oriented summary of those documents.

---

## 3. Repository structure

The main repository structure is:

```text
configs/
    direct_scenarios.yaml
    following_lane.json
    ld_topology.json
    scenario_catalog.csv

data/
    README.md

docs/handover/KOR/
    00_OVERVIEW.md
    01_SETUP_AND_RUN.md
    01A_SETUP_AND_RUN_LINUX.md
    01B_SETUP_AND_RUN_WINDOWS.md
    02_PIPELINE.md
    03_DATA_FORMAT.md
    04_SCENARIO_STATUS.md
    05_ALGORITHMS.md
    06_EVALUATION.md
    07_KNOWN_ISSUES.md
    08_NEXT_STEPS.md
    09_REFERENCES.md

scripts/odld_explorer/
    generate.py
    explorer.py
    odld_explorer_common.py

src/ms_odd_tagging/
    canonical/
    features/
    frame_inputs/
    gt/
    ld_topology/
    scenarios/
    tagger/
    validator/
    vlm/
    pipeline.py

tests/
```

The most important rule for maintenance is: **do not create another parallel implementation unless absolutely necessary**. The repository cleanup intentionally moved toward one current implementation per feature.

---

## 4. Main configuration files

### `configs/scenario_catalog.csv`

This is the source of truth for scenario support.

It tells you:

- scenario name
- category
- current method: `rule`, `vlm`, or blank
- status: `active`, `experimental`, or `unsupported`

When adding or changing a scenario, check this file first.

Do not duplicate the support list in Markdown or another Python constant unless the code requires it.

### `configs/direct_scenarios.yaml`

This contains runtime configuration for deterministic rule detectors.

Use it for:

- thresholds
- minimum duration
- hysteresis
- merge/inactive gaps
- enabled rule scenarios
- scenario-specific detector parameters

This file answers **how a rule detector behaves**. `scenario_catalog.csv` answers **what scenarios exist and which method owns them**.

### `configs/following_lane.json`

Configuration for following-lane and lane relationship logic.

Use this when debugging:

- ego lane assignment
- left/right adjacent lanes
- lane continuity
- lead/trail relation
- following-lane scenarios

### `configs/ld_topology.json`

Configuration for LD topology reconstruction and intersection-related geometry.

This affects lane/intersection interpretation and can propagate into lane change, turn, following-lane, and VLM candidate logic.

---

## 5. Core implementation files

### A. Canonicalization

```text
src/ms_odd_tagging/canonical/
```

Primary responsibility:

- combine OD, LD, and ego trajectory
- preserve source frame alignment
- construct ego motion fields
- normalize recording-level LD geometry
- build `ld_feature_store`
- expose nearby LD references per frame

The canonical schema is:

```text
odld-trajectory-canonical-frame-v1
```

The rest of the project should consume canonical data instead of independently reparsing raw OD/LD files.

Developer rule: if a new detector needs reusable information that can be derived once for all scenarios, consider adding it to canonical data or the feature layer rather than recomputing it inside the detector.

### B. Feature extraction

```text
src/ms_odd_tagging/features/
```

Important modules include:

```text
ego_motion.py
object_relations.py
road_feature_relations.py
pedestrian_crosswalk_relations.py
object_path_crossing_relations.py
traffic_relations.py
traffic_light_context.py
```

These modules create reusable evidence for the scenario detectors.

A new detector should reuse these relations whenever possible.

### C. Rule-based tagging

```text
src/ms_odd_tagging/tagger/rule_based/
```

Typical detector structure:

```text
Canonical frames
    ↓
Feature / relation extraction
    ↓
Frame-level state
    ↓
Temporal filtering / hysteresis
    ↓
Event segmentation
    ↓
ScenarioEvent(start, end, evidence)
```

Important detector areas include:

- dynamics / speed / jerk
- turns
- lane changes
- crosswalk behavior
- object interactions
- pedestrian-crosswalk interactions
- object path crossing
- traffic interactions

Do not treat Motional Scenarios as only a threshold on one frame. Most accuracy problems are temporal-boundary, lane-continuity, or evidence-quality problems.

### D. Following lane

```text
src/ms_odd_tagging/scenarios/following_lane/
```

This subsystem handles lane assignment and following-lane relationships.

It is one of the most important components to understand before changing lane-change or traffic-interaction logic because LD segments do not always correspond one-to-one with a physical continuous lane.

Important distinction:

- **physical lane assignment**: which lane geometry contains/represents ego at the current location
- **logical continuity**: which separated LD segments belong to the same driving path over time

Do not merge these concepts in visualization or scenario logic.

### E. LD topology

```text
src/ms_odd_tagging/ld_topology/
```

Used for intersection/topology understanding and supporting lane context.

Changes here can have downstream effects on:

- lane change suppression in intersections
- turns
- following lane
- intersection-related VLM candidates

Treat this as shared infrastructure, not an isolated visualization feature.

### F. Frame input / BEV

```text
src/ms_odd_tagging/frame_inputs/
```

Default output is generated at 1 FPS and stored as:

```text
outputs/02_frame_inputs/<RECORDING_ID>/
    frame_XXXXXX/
        frame.json
        bev.png
    recording_frame_tags_1fps/
```

The frame input is shared by:

- GT review
- debugging
- VLM evidence generation

A sampled BEV does not contain every source frame. Rule detection may still use the full canonical frame sequence, so always compare frame index and timestamp when debugging apparent inconsistencies.

### G. VLM

```text
src/ms_odd_tagging/vlm/
```

The VLM path is hybrid, not full-frame classification:

```text
Rule / geometry candidate generation
    ↓
Candidate / episode merge
    ↓
Evidence / BEV selection
    ↓
VLM inference
    ↓
Validation
    ↓
Event merge
```

Current VLM groups are managed by the VLM config and the scenario catalog.

The VLM should be used as a verifier for semantically ambiguous cases. Do not send every frame to the model unless there is a clear benchmark showing that the extra cost is justified.

### H. GT Workspace

```text
src/ms_odd_tagging/gt/
```

The GT Workspace is the main human review tool for sampled frames and prediction-prefilled labels.

It is used to:

- inspect BEV + frame data
- inspect predicted tags
- correct labels
- save reviewed GT

GT must remain independent from prediction output. Prediction can prefill an unreviewed frame, but reviewed GT is the human reference.

### I. ODLD Explorer

```text
scripts/odld_explorer/
```

Use:

```text
python scripts/odld_explorer/generate.py
```

The explorer is intended for debugging the full recording context, especially:

- OD objects
- LD geometry
- ego trajectory
- scenario intervals
- lane relationships
- topology
- road/object relation evidence

Use the GT Workspace for frame-level review and the ODLD Explorer for full-recording diagnosis.

---

## 6. Installation

### Linux

```bash
git clone https://github.com/livmeraki/ms-odd-tagging.git
cd ms-odd-tagging
git switch refactor/repo-cleanup-20260813

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Windows PowerShell

```powershell
git clone https://github.com/livmeraki/ms-odd-tagging.git
Set-Location ms-odd-tagging
git switch refactor/repo-cleanup-20260813

python -m venv .venv-win
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-win\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

---

## 7. Data setup

Set the two root directories.

Linux:

```bash
export MS_ODD_DATA_ROOT=/absolute/path/to/data
export MS_ODD_OUTPUT_ROOT=/absolute/path/to/outputs
```

Windows PowerShell:

```powershell
$env:MS_ODD_DATA_ROOT = "D:\path\to\data"
$env:MS_ODD_OUTPUT_ROOT = "D:\path\to\outputs"
```

Expected raw layout:

```text
$MS_ODD_DATA_ROOT/01_raw/<RECORDING_ID>/
    annotations_OD.json
    annotations_LD.json
    traj_lcs.txt
```

---

## 8. Main commands

The current public CLI surface is intentionally small:

```text
ms-odd-tagging     full pipeline
ms-odd-canonical   canonicalization only
ms-odd-frames      frame / BEV generation
ms-odd-rules       deterministic scenario detection
ms-odd-lane        following-lane analysis
ms-odd-topology    LD topology analysis
ms-odd-vlm         VLM candidate / inference workflow
ms-odd-gt          GT Workspace
ms-odd-validate    frame-input validation
```

Start by checking:

```bash
ms-odd-tagging --help
```

### Smoke test

```bash
ms-odd-tagging <RECORDING_ID> \
  --frame-limit 1 \
  --existing-output regenerate
```

### Normal run

```bash
ms-odd-tagging <RECORDING_ID>
```

Default frame sampling is 1 FPS.

Useful options:

```bash
ms-odd-tagging <RECORDING_ID> --frames-per-second 2
ms-odd-tagging <RECORDING_ID> --all-frames
ms-odd-tagging <RECORDING_ID> --existing-output resume
ms-odd-tagging <RECORDING_ID> --existing-output regenerate
ms-odd-tagging <RECORDING_ID> --stop-after canonical
```

---

## 9. How to use the ODLD Explorer

Linux:

```bash
python scripts/odld_explorer/generate.py \
  --source-root "$MS_ODD_DATA_ROOT/01_raw" \
  --canonical-dir "$MS_ODD_OUTPUT_ROOT/01_canonical" \
  --output-dir "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers" \
  --index-path "$MS_ODD_OUTPUT_ROOT/07_odld_scenario_explorers/index.html" \
  --regenerate-existing
```

Windows PowerShell:

```powershell
python scripts/odld_explorer/generate.py `
  --source-root (Join-Path $env:MS_ODD_DATA_ROOT "01_raw") `
  --canonical-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "01_canonical") `
  --output-dir (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers") `
  --index-path (Join-Path $env:MS_ODD_OUTPUT_ROOT "07_odld_scenario_explorers\index.html") `
  --regenerate-existing
```

Open:

```text
<MS_ODD_OUTPUT_ROOT>/07_odld_scenario_explorers/index.html
```

Use the explorer when a detector result looks wrong and you need to determine whether the cause is:

- raw OD data
- LD geometry
- ego trajectory
- lane assignment
- topology
- relation extraction
- temporal event logic

---

## 10. How to use the GT Workspace

```bash
ms-odd-gt \
  --frame-root "$MS_ODD_OUTPUT_ROOT/02_frame_inputs" \
  --gt-root "$MS_ODD_OUTPUT_ROOT/06_gt_comparison/gt" \
  --source-hz 10 \
  --sample-hz 1 \
  --host 127.0.0.1 \
  --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Recommended use:

1. run predictions first
2. open the GT Workspace
3. review prediction-prefilled labels
4. correct incorrect labels
5. mark reviewed frames/recordings
6. use the reviewed GT for evaluation

When comparing GT and prediction, remember that sampled frame selection can differ by source frame index. The current workspace uses exact frame matching first and timestamp-based fallback when needed.

---

## 11. How to use the VLM path

Check the available options:

```bash
ms-odd-vlm --help
```

The local VLM endpoint is expected to be OpenAI-compatible. The project has been designed around a local vLLM/Qwen workflow.

A typical development loop is:

```text
1. generate candidate episodes
2. inspect candidate evidence
3. verify BEV images
4. run VLM inference
5. inspect accepted/rejected decisions
6. compare against GT
7. adjust candidate logic or prompts
```

Do not optimize prompts before checking candidate recall. If the correct event never reaches the VLM, prompt quality cannot fix the false negative.

On native Windows, the VLM client can run, but the local vLLM server should run on Linux/WSL2 or another Linux GPU host.

---

## 12. How to debug a wrong scenario result

Use this order instead of immediately changing thresholds:

```text
1. Was the source data present?
2. Is canonical alignment correct?
3. Is the reusable feature/relation correct?
4. Is lane/topology reconstruction correct?
5. Did the detector create the correct frame-level state?
6. Did temporal segmentation remove or shorten it?
7. For VLM scenarios, was a candidate generated?
8. Was the correct evidence sent to the VLM?
9. Did validation reject the model output?
10. Is the GT itself correct?
```

This distinction is important because a downstream false negative may actually originate from lane reconstruction or candidate generation rather than the final detector threshold.

---

## 13. Known areas that need improvement

The current documentation identifies the following as the most important technical risks.

### Lane continuity and reconstruction

LD segments can split a physical lane into multiple IDs. This affects:

- changing lane
- following lane
- lead/trail relation
- intersection exit stability

Future work should preserve the distinction between physical lane assignment and logical continuity.

### False lane changes at intersections

Large lane-ID changes while entering or traversing an intersection can resemble lane changes. Existing suppression logic should not be weakened without regression testing.

### Short or missing LD segments

Short boundaries and temporary LD gaps can make lane/topology reconstruction unstable. Persistence can help, but excessive persistence can keep incorrect geometry alive too long.

### Sparse traffic-light observations

Traffic-light objects can appear only in a small number of OD frames. With 1 FPS sampled BEV, a valid traffic-light observation may not appear in the sampled frame.

A future implementation should consider temporal existence persistence and stopline/intersection association, but must not invent traffic-light state when the source annotation does not contain it.

### Object velocity and association noise

The following scenarios are especially sensitive:

- `near_high_speed_vehicle`
- `crossed_by_*`
- slow-lead logic

Always inspect object association and frame gaps before calibrating speed thresholds.

### Jerk / derivative noise

Acceleration and jerk amplify small trajectory errors. Use temporal filtering, sample-gap validation, and hysteresis rather than raw derivatives alone.

### VLM runtime

VLM is much more expensive than deterministic tagging. Keep candidate gating, candidate merging, image limits, and caching.

---

## 14. Recommended development priorities

The current handover recommends the following order.

### P0 — Establish a reproducible baseline

Before algorithm work, fix:

- evaluation recording list
- GT version
- commit SHA
- scenario subset
- configuration version
- evaluation unit
- output artifact format

Without this, threshold or algorithm changes cannot be compared reliably.

Also verify the project from a fresh clone:

```text
clone
→ install
→ smoke pipeline
→ full pipeline
→ ODLD Explorer
→ GT Workspace
→ pytest
```

### P1 — Accuracy work

Prioritize false-negative analysis rather than globally loosening thresholds.

For each FN, determine whether it is:

- missing source evidence
- candidate-generation miss
- relation/geometry failure
- threshold issue
- temporal boundary issue
- lane/topology downstream failure

Traffic-light persistence and traffic-interaction calibration are high-value areas.

### P2 — Architecture simplification

Continue reducing duplicated logic.

Important candidates:

- unify following-lane calculations with the main rule pipeline where duplicate work exists
- make frame input and frame-tag exporters share one sampling helper
- simplify GT alignment after sampling is unified
- optimize GT Workspace loading with cached recording summaries/manifests

### P3 — VLM benchmark

Keep a fixed VLM benchmark containing:

- model version
- prompt version
- scenario group
- candidate count
- image count
- GPU
- cache status
- runtime
- accuracy/F1

---

## 15. Adding a new rule-based scenario

Recommended process:

```text
1. confirm taxonomy/policy definition
2. add or update scenario_catalog.csv
3. define required evidence
4. check whether the feature already exists
5. add reusable feature/relation logic if necessary
6. implement frame-level detector state
7. implement temporal event segmentation
8. add configuration to direct_scenarios.yaml
9. add unit tests
10. inspect the result in the ODLD Explorer
11. create/review GT
12. evaluate on a fixed recording set
13. calibrate thresholds
14. update documentation
```

Do not place geometry computation directly in several detectors if it can be shared through the feature layer.

---

## 16. Adding a new VLM scenario

Recommended process:

```text
1. add/update the scenario in scenario_catalog.csv
2. define a high-recall deterministic candidate rule
3. define candidate episode merging
4. define what evidence is actually required
5. select a small number of representative BEV frames
6. write the scenario prompt/output contract
7. validate the structured response
8. merge accepted decisions into events
9. build positive and hard-negative GT cases
10. benchmark candidate recall separately from VLM accuracy
```

Measure two things separately:

- **candidate recall**: did the correct event reach the VLM?
- **VLM decision quality**: given a correct candidate, did the model make the right decision?

This separation makes VLM debugging much faster.

---

## 17. Testing discipline

Run:

```bash
python -m pytest
```

Before merging an algorithm change, also run a small fixed regression set that includes at least:

- straight road
- left lane change
- right lane change
- straight intersection traversal
- left/right intersection turn
- short/missing LD segment
- split/merge lane

A unit-test pass alone is not enough for lane/topology changes because many failures are data-dependent geometry regressions.

---

## 18. Maintenance rules for the next developer

1. Keep one implementation per feature.
2. Keep `scenario_catalog.csv` as the scenario-support source of truth.
3. Keep detector thresholds in configuration, not documentation.
4. Reuse canonical/features rather than reparsing raw data inside detectors.
5. Preserve full-frame rule evaluation and sampled-frame review as separate concepts.
6. Do not infer unsupported source information, especially traffic-light state.
7. Treat lane/topology changes as high-impact shared-infrastructure changes.
8. Measure candidate recall separately from VLM accuracy.
9. Record commit/config/GT versions for every reported metric.
10. Update the handover docs whenever a public command, path, schema, or workflow changes.

---

## 19. Suggested first week for the next developer

### Day 1

- install from a fresh clone
- run one-recording smoke test
- inspect `outputs/01_canonical`
- inspect `outputs/02_frame_inputs`

### Day 2

- generate the ODLD Explorer
- inspect one correct and one incorrect lane/following-lane case
- read `05_ALGORITHMS.md` and `07_KNOWN_ISSUES.md`

### Day 3

- run the GT Workspace
- review a small recording set
- understand `scenario_catalog.csv` and `direct_scenarios.yaml`

### Day 4

- select one known false positive and one false negative
- trace each from source data → canonical → features → detector → event

### Day 5

- establish a reproducible evaluation subset
- run `pytest`
- choose the first improvement task based on measured failure cases, not intuition

This gives the next engineer enough context to improve the system without first reverse-engineering the entire repository.
