# Qwen VLM BEV Style GT Run

This is the prepared next run for the filled GT on:

`Rec_Drv_GER_MACHET18_20260422_101126`

It uses the compact candidate payload plus two 512 px BEV images per request. This avoids the previous vLLM context-length failures caused by sending the full nested candidate evidence JSON.

## Run

```bash
cd /home/stradvision/Desktop/s_park/ms-odd-tagging

scripts/qwen_vlm_poc/run_next_bev_style_gt_experiment.sh
```

The script expects vLLM at:

`http://127.0.0.1:8001`

Override it if needed:

```bash
ENDPOINT_BASE=http://127.0.0.1:8080 \
scripts/qwen_vlm_poc/run_next_bev_style_gt_experiment.sh
```

## Inputs

GT:

`/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd/ms-odd-tagging-data/outputs/bev_style_gt_experiment_Rec_Drv_GER_MACHET18_20260422_101126/gt.csv`

Candidates:

`/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd/ms-odd-tagging-data/outputs/bev_style_candidate_test_Rec_Drv_GER_MACHET18_20260422_101126/candidates/waiting_for_pedestrian_to_cross/Rec_Drv_GER_MACHET18_20260422_101126/`

Config:

`configs/qwen_vlm_poc_reduced_2img_512.json`

## Outputs

By default the wrapper writes a timestamped run folder:

`/media/stradvision/25eb199d-ae8a-49d6-b7e9-675eb144ddcd/ms-odd-tagging-data/outputs/bev_style_gt_experiment_Rec_Drv_GER_MACHET18_20260422_101126/run_next_compact_2img_512px_YYYYMMDD_HHMMSS/`

Files:

- `gallery.html`
- `report.html`
- `scene_results.csv`
- `summary.csv`

Use a fixed output folder name if needed:

```bash
RUN_NAME=run_next_compact_2img_512px \
scripts/qwen_vlm_poc/run_next_bev_style_gt_experiment.sh
```

Reuse cache instead of forcing fresh calls:

```bash
FORCE_CACHE_REFRESH=0 \
scripts/qwen_vlm_poc/run_next_bev_style_gt_experiment.sh
```
