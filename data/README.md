# Data Directory

Keep private and large datasets outside Git.

- `data/01_raw/` contains local OD/LD/trajectory recordings and is ignored.
- `data/02_gt/` contains local reviewed ground-truth label files and is ignored.
- `tests/fixtures/` contains only tiny synthetic or anonymized regression fixtures.
- Real-recording integration tests read external data and skip when it is unavailable.

A runnable recording requires `annotations_OD.json`, `annotations_LD.json`, and
`traj_lcs.txt`. Do not commit partial or complete production recordings.
