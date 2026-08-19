# Pedestrian VLM Understanding Experiment

This controlled audit targets the false-positive failure observed when a spatial
question was asked even though no pedestrian existed. It separates five tasks:

1. pedestrian presence
2. spatial relation, including `not_applicable`
3. ego-path interaction
4. direct `waiting_for_pedestrian_to_cross` decision
5. evidence-gated decision requiring presence, path interaction, and stopped ego

The fixture set is balanced: four positives and four hard negatives. The images
are synthetic diagnostic inputs, not performance evidence for natural recordings.

## Generate fixtures and validate immediately

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pseudo_bev

python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli \
  --dry-run
```

## Fast first VLM run

Start the vision server in one terminal:

```bash
scripts/vllm/run_vision_server.sh Qwen/Qwen3-VL-8B-Instruct
```

Then run presence and the two waiting-decision variants with the full legend:

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli \
  --task pedestrian_presence \
  --task waiting_direct \
  --task waiting_evidence_gated \
  --condition full_legend
```

This creates 24 calls: 8 scenes x 3 tasks x 1 condition. Results are written to
`outputs/vlm_understanding_pedestrian_experiment/`.

## Legend ablation for the spatial layer

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli \
  --task spatial_relation
```

This creates 32 calls: 8 scenes x 1 task x 4 legend conditions. The expected
answer for absent-pedestrian scenes is `not_applicable`, so the model is no
longer forced to hallucinate left/right/ahead/behind.

## Full experiment

```bash
python -m ms_odd_tagging.vlm_understanding_poc.pedestrian_experiment_cli
```

The full matrix is 160 calls. Use task and condition filters for iteration before
running the whole matrix.

Key outputs:

- `pedestrian_scene_results.csv`: every model decision
- `pedestrian_condition_summary.csv`: accuracy and false-positive rate by task and legend condition
