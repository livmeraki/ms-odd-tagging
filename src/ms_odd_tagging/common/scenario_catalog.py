"""Load the single source-of-truth scenario catalog."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[3] / "configs" / "scenario_catalog.csv"
VALID_METHODS = {"rule", "vlm"}
VALID_STATUSES = {"implemented", "poc_calibration", "vlm_poc", "unsupported"}


@dataclass(frozen=True)
class ScenarioCatalogEntry:
    name: str
    category: str
    methods: tuple[str, ...]
    status: str
    taxonomy_status: str
    vlm_candidate_group: str | None = None
    notes: str | None = None


@lru_cache(maxsize=1)
def load_scenario_catalog(path: Path | str | None = None) -> tuple[ScenarioCatalogEntry, ...]:
    catalog_path = Path(path) if path is not None else CATALOG_PATH
    rows: list[ScenarioCatalogEntry] = []
    seen: set[str] = set()
    with catalog_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("name") or "").strip()
            if not name:
                raise ValueError(f"{catalog_path}: scenario name cannot be empty")
            if name in seen:
                raise ValueError(f"{catalog_path}: duplicate scenario {name}")
            seen.add(name)

            methods = tuple(
                method.strip()
                for method in (row.get("methods") or "").split("+")
                if method.strip()
            )
            unknown_methods = sorted(set(methods) - VALID_METHODS)
            if unknown_methods:
                raise ValueError(
                    f"{catalog_path}: {name} has unknown methods: {', '.join(unknown_methods)}"
                )

            status = (row.get("status") or "").strip()
            if status not in VALID_STATUSES:
                raise ValueError(f"{catalog_path}: {name} has invalid status {status!r}")
            if status == "unsupported" and methods:
                raise ValueError(
                    f"{catalog_path}: unsupported scenario {name} cannot declare methods"
                )
            if "vlm" in methods and not (row.get("vlm_candidate_group") or "").strip():
                raise ValueError(
                    f"{catalog_path}: VLM scenario {name} requires vlm_candidate_group"
                )

            rows.append(
                ScenarioCatalogEntry(
                    name=name,
                    category=(row.get("category") or "").strip(),
                    methods=methods,
                    status=status,
                    taxonomy_status=(row.get("taxonomy_status") or "").strip(),
                    vlm_candidate_group=(row.get("vlm_candidate_group") or "").strip() or None,
                    notes=(row.get("notes") or "").strip() or None,
                )
            )
    return tuple(rows)


def scenario_names_for_method(method: str) -> tuple[str, ...]:
    if method not in VALID_METHODS:
        raise ValueError(f"unknown scenario method: {method}")
    return tuple(
        entry.name for entry in load_scenario_catalog() if method in entry.methods
    )


def vlm_candidate_groups() -> tuple[str, ...]:
    groups: list[str] = []
    for entry in load_scenario_catalog():
        if "vlm" not in entry.methods or entry.vlm_candidate_group is None:
            continue
        if entry.vlm_candidate_group not in groups:
            groups.append(entry.vlm_candidate_group)
    return tuple(groups)


def vlm_labels_for_group(group: str) -> tuple[str, ...]:
    return tuple(
        entry.name
        for entry in load_scenario_catalog()
        if "vlm" in entry.methods and entry.vlm_candidate_group == group
    )
