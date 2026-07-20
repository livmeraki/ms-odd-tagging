# Data Directory

Keep private and large datasets outside Git.

- `data/01_raw/` contains local OD/LD/trajectory recordings and is ignored for new files.
- `data/02_gt/` contains reviewed ground-truth label files.
- `tests/fixtures/` contains only tiny synthetic or anonymized test fixtures.

The small recording already tracked in `01_raw` is an inherited partial LD/trajectory sample; it is not a complete runnable OD or OD+LD recording.
