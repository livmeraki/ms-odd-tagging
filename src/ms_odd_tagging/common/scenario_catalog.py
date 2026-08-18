"""Load the single source-of-truth scenario catalog."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[3] / "configs" / "scenario_catalog.csv"
VALID_METHODS = {"rule", "vlm"}
VALID_STATUSES = {"active", "experimental", "unsupported"}


@dataclass(frozen=True)
class ScenarioCatalogEntry:
    name: str
    category: str
    methods: tuple[str, ...]
    status: str


@lru_cache(maxsize=1)
def load_scenario_catalog(path: Path | str | None = None) -> tuple[ScenarioCatalogEntry, ...]:
    catalog_path = Path(path) if path is not None else CATALOG_PATH
    rows: list[ScenarioCatalogEntry] = []
    seen: set[str] = set()
    with catalog_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        expected_fields = ["name", "category", "methods", "status"]
        if reader.fieldnames != expected_fields:
            raise ValueError(
                f"{catalog_path}: expected columns {expected_fields}, got {reader.fieldnames}"
            )

        for row in reader:
            name = (row.get("name") or "").strip()
            category = (row.get("category") or "").strip()
            if not name:
                raise ValueError(f"{catalog_path}: scenario name cannot be empty")
            if name in seen:
                raise ValueError(f"{catalog_path}: duplicate scenario {name}")
            if not category:
                raise ValueError(f"{catalog_path}: {name} requires a category")
            seen.add(name)

            method = (row.get("methods") or "").strip()
            if "+" in method:
                raise ValueError(
                    f"{catalog_path}: {name} must use one current method; combined methods are not supported"
                )
            if method and method not in VALID_METHODS:
                raise ValueError(f"{catalog_path}: {name} has unknown method: {method}")
            methods = (method,) if method else ()

            status = (row.get("status") or "").strip()
            if status not in VALID_STATUSES:
                raise ValueError(f"{catalog_path}: {name} has invalid status {status!r}")
            if status == "unsupported" and methods:
                raise ValueError(
                    f"{catalog_path}: unsupported scenario {name} cannot declare a method"
                )
            if status != "unsupported" and not methods:
                raise ValueError(
                    f"{catalog_path}: supported scenario {name} must declare a method"
                )

            rows.append(
                ScenarioCatalogEntry(
                    name=name,
                    category=category,
                    methods=methods,
                    status=status,
                )
            )
    return tuple(rows)


def scenario_names_for_method(method: str) -> tuple[str, ...]:
    if method not in VALID_METHODS:
        raise ValueError(f"unknown scenario method: {method}")
    return tuple(
        entry.name for entry in load_scenario_catalog() if method in entry.methods
    )
