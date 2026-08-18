# Presentation quantitative evidence

Evidence lock date: 2026-08-13 (Asia/Seoul)  
Repository/branch: `livmeraki/ms-odd-tagging`, `tool/manual-gt-simplified`  
Verified commit: `38c8e910510d56b04d304a969f9a007de0fda015`  
Issue: [#1 — Lock quantitative evidence for internship presentation](https://github.com/livmeraki/ms-odd-tagging/issues/1)

## A. Concise presentation table

| Metric | Value | Sample/scope | Confidence | Can I present it? | Exact slide wording |
|---|---:|---|---|---|---|
| Current main-output Micro Precision / Recall / F1 (original lane-change detector; no PoC) | **0.8125 / 0.8125 / 0.8125** | 30 scored GT-finished recordings; 1,800 manually reviewed sampled frames; 5,386 known GT field decisions pooled across 4 active fields; traffic-light intersection excluded | HIGH | **Yes, with scope** | “On 30 GT-reviewed recordings (1,800 sampled frames), the original main-branch output achieved **81.2% Micro F1** (P=81.2%, R=81.2%) across four active fields.” |
| Current Macro F1 | **0.8107** | Unweighted mean over 4 active fields; traffic-light-intersection context is explicitly excluded | MEDIUM | Yes, but not as headline | “Macro F1 was **81.1% across four reviewed fields**, excluding traffic-light-intersection context.” |
| Motion-state field | **P/R/F1 = 1.0000 / 1.0000 / 1.0000** | 1,800 known reviewed frame labels; state values are stationary/moving/starting/stopping | HIGH | **Yes, with scope** | “Ego motion state reached **100% F1 on 1,800 reviewed sampled frames**.” |
| Lane-keeping frame F1 | **P=0.9530, R=0.7950, F1=0.8668** | 1,351 GT-positive sampled frames; 1,074 TP, 53 FP, 277 FN across 30 recordings | HIGH | **Yes, with scope** | “Lane keeping achieved **86.7% frame F1** (95.3% precision, 79.5% recall) on 1,351 GT-positive sampled frames.” |
| Original lane-change frame F1 | **Left 0.2424; Right 0.2353** | Left: 4 TP/0 FP/25 FN over 29 GT-positive frames; right: 2 TP/0 FP/13 FN over 15 GT-positive frames; 2 unknown-direction GT frames remain missed | HIGH counts; MEDIUM generalization | **Yes, as preliminary** | “The original lane-change detector had **100% observed precision with zero false-positive reviewed frames/events**; left/right event F1 was 46.2%/50.0%.” |
| GT scale | **30 recordings; 1,800 reviewed sampled frames; 29.85 min driving** | Each recording is about 59.7 s and has 60 reviewed samples; 17,940 underlying source frames | HIGH | **Yes** | “Ground-truth validation covers **30 recordings / 1,800 reviewed samples / 29.9 minutes of driving**.” |
| Processing scale | **220 recordings; 131,560 source frames; 218.90 min (3.65 h)** | Canonical manifest and current Phase-2 event outputs; all recordings are about 59.7 s | HIGH | **Yes** | “The pipeline processed **220 recordings—131,560 frames and 3.65 hours of driving**.” |
| Tag scale | **58 declared; 33 emitted** | 58 tags in the canonical scenario taxonomy; 33 distinct scenarios actually emitted in the 220-recording Phase-2 event output | HIGH | **Yes, keep distinction** | “The system defines **58 scenario tags**, with **33 observed in the 220-recording run**.” |
| Waiting-pedestrian VLM candidates | **193 rule-generated candidate events** | `waiting_for_pedestrian_to_cross` events in 220 Phase-2 event files; no persisted VLM response set was found | MEDIUM | Yes only as candidates | “Rule-based filtering produced **193 waiting-pedestrian candidate episodes** across 220 recordings for selective VLM review.” |
| VLM overflow payload cap | **speed rows 30→≤12; track points 24→≤10; images 6→≤4** | Deterministic overflow fallback verified by unit fixture; reductions are at least 60.0%, 58.3%, and 33.3% for that fixture | HIGH for code behavior; LOW for real-world savings | Yes as engineering behavior, not runtime/quality | “The overflow fallback caps VLM context by reducing the test payload from **30→12 speed samples, 24→10 track points, and 6→4 images**.” |
| Historical Micro Accuracy / Micro F1 / Macro F1 candidates | **0.9371 / 0.8604 / 0.7696 — NOT VERIFIED** | No matching keyed metric in committed history, docs, reports, or local metric artifacts | HIGH confidence in non-verification | **No** | Do not put these numbers on a slide. |
| Claimed topology precision change | **83.3% → 89.4% — NOT VERIFIED** | No artifact with confusion counts, sample IDs, scorer, or matching commit was found | HIGH confidence in non-verification | **No** | Do not present until the original before/after artifact is recovered. |
| Human-effort reduction | **NOT MEASURED** | No manual-vs-assisted stopwatch benchmark exists in the inspected repo/artifacts | HIGH | **No** | “Human-time savings have not yet been benchmarked.” |

## B. Top 3 numbers for today's presentation

1. **81.2% Micro F1** — say the full scope: original main-branch output with no PoC, 30 GT-reviewed recordings, 1,800 sampled frames, four active fields; traffic-light context excluded.
2. **220 recordings / 131,560 frames / 3.65 hours processed** — this is processing scale, not GT scale.
3. **30 GT recordings / 1,800 reviewed samples / 29.9 minutes** — this makes the reliability sample size explicit.

If a tag-level quality number is more useful than a second scale number, replace #3 with **86.7% lane-keeping frame F1 (95.3% precision, 79.5% recall; 1,351 GT-positive frames)**.

## C. Numbers not to use

- **0.9371 Micro Accuracy, 0.8604 Micro F1, 0.7696 Macro F1:** no matching metric-bearing artifact or commit was found. Exact-value searches were restricted to keyed metric fields/text so raw numeric coordinates could not create false provenance. These values are **NOT VERIFIED**.
- **83.3% → 89.4% topology precision:** no before/after confusion matrix, evaluated IDs, scorer output, or source commit links these values to topology. **NOT VERIFIED**.
- **0.9725 accuracy / 0.9386 Micro F1 / 0.8836 Macro F1 as current:** these are real in `outputs/06_gt_comparison/rule_based_gt_summary.json`, but the artifact is dated 2026-07-24, marked **provisional**, uses only 5 recordings and 8 older labels, reports 173 frames still `needs_review`, and uses different scoring semantics. It may be described only as an old provisional five-recording experiment, not current system performance.
- **Any waiting-pedestrian F1:** `interaction_tags.*` is excluded from current F1, and no reviewed VLM-result artifact was found. The 193 count is candidate generation, not GT accuracy and not confirmed VLM calls.
- **Any human-time percentage:** pipeline runtime, VLM latency, and human interaction time are different quantities. No controlled manual-vs-assisted human-time benchmark exists here.
- **“All 220 recordings have GT”:** false. There are 30 finished GT documents, and all 30 are scored.
- **A cherry-picked lane score made by changing GT or selecting main/PoC per example:** invalid. GT remains unchanged, and this report uses the original main detector consistently.`n- **A generic “58 implemented and validated tags”:** too broad. The defensible wording is 58 declared taxonomy tags, 33 emitted in this run, 13 simplified scenario classes in the source evaluation, and only four active report fields.

## 1. Current GT/F1 evidence

The main-output aggregate uses the original main-branch lane-change tags and no PoC overlay. Its SHA-256 is:

```text
498B2AFA6B951BFC117510B07FF05BB52F2A38A355AA92AF8DD3AC043F6B6CD3
```

Current scope:

- Prediction scope: unmodified current/main pipeline predictions, including the original `phase2-basic-lane-change-v1` lane-change tags. **No PoC predictions are included.**
- Presentation-only scoring exclusion: `road_context.traffic_light_intersection` is removed without changing any GT labels or predictions. The four-field Micro counts are derived from the canonical aggregate by subtracting that field: 0 TP / 234 FP / 234 FN.
- 31 GT documents were found: all 30 finished recordings were scored, and 1 unfinished recording (`Rec_Drv_GER_MACHET18_20260415_092926`) was skipped; scored recordings had 0 missing prediction recordings and 0 missing prediction frames.
- 60 manually reviewed sampled frames per recording = **1,800 reviewed sampled frames**.
- The recordings cover **1,791.0020 seconds (29.8500 minutes)** and 17,940 underlying 10 Hz source frames.
- Four active report fields: `ego_motion.state`, `ego_maneuver.type`, `ego_maneuver.direction`, and `traffic_relation.lead`. `road_context.traffic_light_intersection` is explicitly excluded from this presentation score.
- Unknown or null GT field values are skipped. Predictions are never used as GT by the scorer. Only finished manual-GT documents enter the default aggregate.
- Explicit F1 exclusions: `ego_motion.speed_band`, `traffic_relation.trail`, `road_context.intersection`, `road_context.traffic_light_relevant`, `road_context.on_stopline_crosswalk`, `road_context.traffic_light_intersection`, and `interaction_tags.*`.
- Unlike the old dynamic evaluator, the current simplified evaluator does **not** exclude source frame indexes below 5. Its 60 approximately 1 Hz samples include the start of each recording.
- Micro statistics pool **5,386 known GT field decisions** (`TP + FN`). A wrong categorical value contributes one FP and one FN, which is why pooled precision and recall are identical here.
- Macro F1 is the unweighted mean of the four included field F1 values. The fields have unequal known-GT counts, so Micro F1 remains the preferred headline.

Field metrics:

| Active field | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| `ego_motion.state` | 1,800 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| `ego_maneuver.type` | 1,249 | 335 | 335 | 0.7885 | 0.7885 | 0.7885 |
| `ego_maneuver.direction` | 169 | 40 | 40 | 0.8086 | 0.8086 | 0.8086 |
| `traffic_relation.lead` | 1,158 | 635 | 635 | 0.6458 | 0.6458 | 0.6458 |
| **Micro (4 fields)** | **4,376** | **1,010** | **1,010** | **0.8125** | **0.8125** | **0.8125** |

Representative frame-scenario metrics:

| Simplified scenario | GT-positive frames | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| stationary | 246 | 246 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| start | 231 | 231 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| stop | 1 | 1 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| lane keeping | 1,351 | 1,074 | 53 | 277 | 0.9530 | 0.7950 | 0.8668 |
| lane changing left | 29 | 4 | 0 | 25 | 1.0000 | 0.1379 | 0.2424 |
| lane changing right | 15 | 2 | 0 | 13 | 1.0000 | 0.1333 | 0.2353 |

The 30 scored recording IDs are:

```text
Rec_Drv_GER_MACHET18_20260319_144819
Rec_Drv_GER_MACHET18_20260319_145319
Rec_Drv_GER_MACHET18_20260319_151819
Rec_Drv_GER_MACHET18_20260319_152119
Rec_Drv_GER_MACHET18_20260325_091707
Rec_Drv_GER_MACHET18_20260414_103936
Rec_Drv_GER_MACHET18_20260414_105136
Rec_Drv_GER_MACHET18_20260414_105636
Rec_Drv_GER_MACHET18_20260414_110436
Rec_Drv_GER_MACHET18_20260414_110936
Rec_Drv_GER_MACHET18_20260414_112736
Rec_Drv_GER_MACHET18_20260414_113736
Rec_Drv_GER_MACHET18_20260414_114836
Rec_Drv_GER_MACHET18_20260414_114936
Rec_Drv_GER_MACHET18_20260414_120736
Rec_Drv_GER_MACHET18_20260414_121236
Rec_Drv_GER_MACHET18_20260414_122136
Rec_Drv_GER_MACHET18_20260414_122536
Rec_Drv_GER_MACHET18_20260414_123336
Rec_Drv_GER_MACHET18_20260414_165909
Rec_Drv_GER_MACHET18_20260414_172609
Rec_Drv_GER_MACHET18_20260414_173409
Rec_Drv_GER_MACHET18_20260414_174109
Rec_Drv_GER_MACHET18_20260415_090901
Rec_Drv_GER_MACHET18_20260415_101226
Rec_Drv_GER_MACHET18_20260415_104326
Rec_Drv_GER_MACHET18_20260415_112526
Rec_Drv_GER_MACHET18_20260415_145922
Rec_Drv_GER_MACHET18_20260422_100926
Rec_Drv_GER_MACHET18_20260422_101226
```

## 1.1 Original main-branch lane-change evidence

The presentation score uses only the original main-branch lane-change tags. No boundary-crossing PoC predictions are included.

| Original detector metric, 30 GT recordings | Value |
|---|---:|
| Left frame TP / FP / FN | 4 / **0** / 25 |
| Left frame Precision / Recall / F1 | **1.0000 / 0.1379 / 0.2424** |
| Right frame TP / FP / FN | 2 / **0** / 13 |
| Right frame Precision / Recall / F1 | **1.0000 / 0.1333 / 0.2353** |
| Left event TP / FP / FN | 3 / **0** / 7 |
| Left event Precision / Recall / F1 | **1.0000 / 0.3000 / 0.4615** |
| Right event TP / FP / FN | 2 / **0** / 4 |
| Right event Precision / Recall / F1 | **1.0000 / 0.3333 / 0.5000** |

The original detector is precision-first: it produced **zero false-positive reviewed frames and zero false-positive events** for both directions. Its limitation is recall. The cohort contains 29 left-positive frames / 10 left events, 15 right-positive frames / 6 right events, and 2 unknown-direction frames/events.

Implementation provenance: main commit `122452d854b8c41d81c25bd2763ffe8ecd5ce3a7`, detector version `phase2-basic-lane-change-v1`. The exact main-output evaluation is `outputs/06_gt_comparison/aggregate_f1_current_30gt.json`, SHA-256 `498B2AFA6B951BFC117510B07FF05BB52F2A38A355AA92AF8DD3AC043F6B6CD3`.

Safe slide wording: “Across 30 GT-reviewed recordings, the original lane-change detector produced zero false-positive reviewed frames or events—100% observed precision—with event recall of 30.0% left and 33.3% right.”
## 2. Historical-metric verification

| Candidate number | Exact source found? | What it measured | Safe to present? |
|---|---|---|---|
| Micro Accuracy ≈0.9371 | No | Nothing traceable; no keyed metric match | **No — NOT VERIFIED** |
| Micro F1 ≈0.8604 | No | Nothing traceable; no keyed metric match | **No — NOT VERIFIED** |
| Macro F1 ≈0.7696 | No | Nothing traceable; no keyed metric match. The older 24-recording baseline has maneuver-type F1 0.7696, but that does not make it a Macro F1 result. | **No — NOT VERIFIED** |
| Precision 83.3%→89.4% after topology | No | No traceable before/after evaluation | **No — NOT VERIFIED** |
| Old provisional Micro Accuracy 0.9725 / Micro F1 0.9386 / Macro F1 0.8836 | Yes: `outputs/06_gt_comparison/rule_based_gt_summary.json` | 5 recordings, 295 scored frames, 8 old binary labels (2,360 label comparisons); first five source frames excluded; artifact itself says provisional, with 173 pending frames | Only with the complete historical caveat; not recommended today |

The old real artifact contains P=0.9325, R=0.9449, F1=0.9386, but it predates the finished simplified-GT workflow and has no encoded Git commit. The evaluator's commit lineage begins at `7c0e0b20df67a2973c3b7fae5daba1d18df8a65d` and was later refactored; that is not enough to claim an exact producing commit.

## 3. Scale

- **220 canonical/processed recordings**, 131,560 source frames, **13,133.9879 s = 218.8998 min = 3.6483 h** in `outputs/01_canonical/manifest.json`.
- **220 Phase-2 rule-event output files** and **12,660 emitted events**.
- **58 declared taxonomy tags**; **33 distinct tags emitted** in those event files.
- **30 scored GT-finished recordings**, 1,800 reviewed samples, 29.85 minutes of scored driving; all finished GT recordings have predictions.
- **13 simplified scenario classes** appear in the current frame-scenario evaluation.
- **193 `waiting_for_pedestrian_to_cross` rule-generated candidate events** across the 220 recordings. The config version is `phase2-traffic-light-vlm-episode-candidates-v1`, but no persisted VLM response corpus was found, so do not call these 193 completed VLM inferences or evaluated VLM episodes.

## 4. Runtime and human time

No defensible production runtime result was found:

- The repository has a wall-clock profiler (`qwen-vlm-poc-timing-v1`, introduced in commit `0dfcea68639f4e4849382f5b5d27af49b22f4800`), but no generated timing JSON is present in the inspected outputs.
- Some VLM client result objects can contain request `elapsed_s`, but there is no persisted response set here from which to aggregate VLM latency.
- No manual-vs-assisted stopwatch study or human interaction log exists.
- Therefore, **pipeline wall-clock runtime, VLM runtime, and human review time reduction are all unreported**. File timestamps are not a substitute.

### Under-10-minute human-effort benchmark

Use two comparable 30-frame, approximately 30-second excerpts from two of the already GT-finished recordings (for example `...144819` and `...145319`) in the GT workspace.

1. Randomly assign excerpt A to **manual-from-blank** and excerpt B to **assisted review**. Use the same four active report fields for both.
2. Manual task: set all five fields without viewing predictions. Start the stopwatch on the first editable frame; stop immediately after saving frame 30.
3. Assisted task: show/copy the existing prediction, correct every wrong field, and save. Start and stop at the same UI moments. Count actual corrections as well as seconds.
4. Exclude server startup/page-load time, breaks, and automatic pipeline runtime. Record only active human interaction time.
5. Normalize before comparing: `seconds_per_frame = elapsed_seconds / 30`.
6. Report `human-effort reduction = 1 - (assisted seconds/frame ÷ manual seconds/frame)`; multiply by 100 for percent. Also report both raw times, frame counts, and correction count.

This is a quick preliminary benchmark, not a controlled study. Avoid reusing the same excerpt in both modes because memory would favor the second pass.

## 5. Traceable before → after evidence

1. **Deterministic VLM overflow compaction:** commit `451bd1dfe8552dcffaac1244e2cfe624f33a5fd7` added overflow fallback; test commit `4abc66a895a4d897f085f477ced55ae86179edc6` verifies 30→≤12 speed rows, 24→≤10 pedestrian-track points, and the client caps images at 6→≤4. For that fixture these are at least **60.0%, 58.3%, and 33.3% reductions**. This verifies context reduction, not latency, accuracy, or real-request byte reduction.
## D. Exact source paths and verification commands

Primary sources:

- `outputs/06_gt_comparison/aggregate_f1_current_30gt.json` (canonical 30-GT main-only result)
- `outputs/06_gt_comparison/aggregate_f1.json` (older 24-recording baseline)
- `outputs/06_gt_comparison/f1_review_current_30gt/frame_scenario_f1.csv`
- `outputs/06_gt_comparison/f1_review_current_30gt/scenario_f1.csv`
- `outputs/06_gt_comparison/gt/*_manual_gt.json`
- `outputs/06_gt_comparison/predictions/*_simplified_prediction.json`
- `src/ms_odd_tagging/simplified_taxonomy/aggregate_score.py`
- `outputs/01_canonical/manifest.json`
- `outputs/04_tagging/rule_based_events_phase2/*_rule_based_scenario_events.json`
- `outputs/06_gt_comparison/rule_based_gt_summary.json` (old provisional evidence only)
- `src/ms_odd_tagging/qwen_vlm_poc/profiling.py`
- `src/ms_odd_tagging/qwen_vlm_poc/client.py`
- `tests/unit/test_qwen_vlm_bev_input.py`

Commands used (PowerShell, from repository root):

```powershell
git fetch --all --prune
git rev-parse HEAD
git log --all --date=iso --pretty=format:'%H%x09%ad%x09%d%x09%s'

$env:PYTHONPATH='src'
& 'C:\Users\StradVision\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m ms_odd_tagging.simplified_taxonomy.aggregate_score --prediction-root outputs\06_gt_comparison\predictions --output outputs\06_gt_comparison\aggregate_f1_current_30gt.json --review-dir outputs\06_gt_comparison\f1_review_current_30gt
Get-FileHash outputs\06_gt_comparison\aggregate_f1_current_30gt.json -Algorithm SHA256

$a = Get-Content -Raw outputs\06_gt_comparison\aggregate_f1_current_30gt.json | ConvertFrom-Json
$a.micro
$a.scalar_fields
$a.frame_scenario_f1
$a.scenario_f1
$a.recordings

$m = Get-Content -Raw outputs\01_canonical\manifest.json | ConvertFrom-Json
$m.recordings.Count
($m.recordings | Measure-Object frame_count -Sum).Sum
($m.recordings | Measure-Object duration_s -Sum).Sum
$m.scenario_taxonomy.Count

$files = Get-ChildItem outputs\04_tagging\rule_based_events_phase2 -File
# Each JSON was parsed; events were counted by `scenario` and `source`.

Get-ChildItem outputs\06_gt_comparison -Filter rule_based_gt_summary.json -File -Recurse
git log --all -p -G'Micro accuracy: 0\.9371|Micro F1: 0\.8604|Macro F1: 0\.7696|83\.3%|89\.4%' -- . ':(exclude)data/**'
rg -n --no-ignore --hidden -g '*.json' -g '*.md' -g '*.csv' -g '*.txt' -g '*.log' '"accuracy"\s*:\s*0\.9371|"f1"\s*:\s*0\.8604|"macro_f1"\s*:\s*0\.7696|Micro accuracy:\s*0\.9371|Micro F1:\s*0\.8604|Macro F1:\s*0\.7696|83\.3%\s*[-→>]+\s*89\.4%' outputs docs artifacts .agents

git show 451bd1dfe8552dcffaac1244e2cfe624f33a5fd7
git show 4abc66a895a4d897f085f477ced55ae86179edc6
```

The hashed source aggregate is the deterministic 30-GT main-output evaluation using the original lane-change detector and no PoC overlay. The 81.2% presentation score is a transparent four-field derivation that excludes the traffic-light field without modifying GT or predictions.
