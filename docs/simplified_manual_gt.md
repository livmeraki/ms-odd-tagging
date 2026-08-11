# Simplified manual GT quickstart

This tool creates fast, prediction-prefilled, frame-level manual ground truth for the simplified taxonomy and computes F1 from only manually reviewed frames.

## 1. Generate the review page

```bash
python -m ms_odd_tagging.simplified_taxonomy.manual_gt review \
  path/to/recording_simplified.json \
  --source-hz 10 \
  --sample-hz 1 \
  --output outputs/06_gt_comparison/simplified_manual_gt.html
```

Open the HTML in a browser. Existing predictions are prefilled. Correct them, then use **Save + Next** or press **Space**. Progress is stored in browser localStorage.

The page intentionally leaves a BEV/image hook panel so it can be embedded into the existing ODLD explorer next. The first version prioritizes getting reviewed GT and F1 quickly.

## 2. Export reviewed GT

Press **Export GT JSON**. Only frames explicitly marked reviewed are included. Each row keeps both `prediction` and `gt` so prediction-assisted annotation never silently becomes GT.

`unknown` scalar GT values are excluded from scoring for that field.

## 3. Calculate F1

```bash
python -m ms_odd_tagging.simplified_taxonomy.manual_gt score \
  path/to/recording_manual_gt.json \
  --output outputs/06_gt_comparison/simplified_f1.json
```

The report contains per-field precision/recall/F1, per-interaction-tag precision/recall/F1, overall macro F1, and micro F1.

## Current interaction tags

- `waiting_for_pedestrian_to_cross`
- `crossed_by_vehicle`
- `near_multiple_vehicles`
- `accelerating_at_crosswalk`
- `stationary_at_crosswalk`
- `stopping_at_crosswalk`
- `near_long_vehicle`
- `near_multiple_pedestrians`
- `near_pedestrian_on_crosswalk`
