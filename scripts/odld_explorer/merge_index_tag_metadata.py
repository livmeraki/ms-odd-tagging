from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_odld_dataset_explorers_w_frame_scenario_tag as explorer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--tag-manifest", type=Path, required=True)
    args = parser.parse_args()

    target_manifest_path = args.target_dir / "manifest.json"
    target_manifest = json.loads(target_manifest_path.read_text(encoding="utf-8"))
    tag_manifest = json.loads(args.tag_manifest.read_text(encoding="utf-8"))
    tags_by_recording = {
        row["recording"]: row for row in tag_manifest.get("recordings", [])
    }

    patched = 0
    rows = []
    for row in target_manifest.get("recordings", []):
        source = tags_by_recording.get(row["recording"])
        if source and (row.get("tagEvents") == 0 or row.get("tagScenarios") == 0):
            for key in ("tagScenarios", "tagEvents", "tagScenarioList"):
                row[key] = source[key]
            patched += 1
        rows.append(row)

    target_manifest["recordings"] = [
        {key: row[key] for key in explorer.INDEX_ROW_KEYS} for row in rows
    ]
    target_manifest_path.write_text(
        json.dumps(target_manifest, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    (args.target_dir / "index.html").write_text(
        explorer.index_html(rows), encoding="utf-8"
    )
    print(f"patched tag metadata rows: {patched}")
    print(f"rows: {len(rows)}")
    print(f"zero tagEvents rows: {sum(1 for row in rows if row.get('tagEvents') == 0)}")


if __name__ == "__main__":
    main()
