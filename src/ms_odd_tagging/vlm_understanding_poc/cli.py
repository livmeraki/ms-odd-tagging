"""CLI for the VLM-understanding diagnostic PoC."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from .runner import Probe, load_manifest, run_probe, write_outputs


_COLOR_WORDS = (
    "orange",
    "green",
    "blue",
    "red",
    "purple",
    "yellow",
    "white",
    "black",
    "cyan",
)

_ORIENTATION_MARKERS = (
    "image up",
    "image down",
    "image left",
    "image right",
    "forward direction",
    "ahead relative",
    "behind relative",
    "left relative",
    "right relative",
)


def _no_color_legend(legend: Any) -> Any:
    """Remove mappings whose identity depends primarily on color.

    Shape-based ego semantics are retained without the color adjective. A generic
    mapping such as ``orange object -> pedestrian`` is removed rather than becoming
    the misleading ``object -> pedestrian``.
    """
    if not isinstance(legend, dict):
        return legend
    reduced: dict[str, Any] = {}
    for raw_key, value in legend.items():
        key = str(raw_key)
        lower = key.lower()
        has_color = any(word in lower for word in _COLOR_WORDS)
        if not has_color:
            reduced[key] = value
            continue

        # Preserve a genuinely shape-defined symbol while removing the color cue.
        if "rectangle" in lower or "triangle" in lower or "nose" in lower:
            stripped = key
            for word in _COLOR_WORDS:
                stripped = stripped.replace(word, "").replace(word.capitalize(), "")
            stripped = " ".join(stripped.split())
            if stripped:
                reduced[stripped] = value
    return reduced or None


def _no_orientation_legend(legend: Any) -> Any:
    """Remove explicit ego-relative orientation/direction mappings."""
    if not isinstance(legend, dict):
        return legend
    reduced: dict[str, Any] = {}
    for raw_key, value in legend.items():
        key = str(raw_key)
        combined = f"{key} {value}".lower()
        if any(marker in combined for marker in _ORIENTATION_MARKERS):
            continue
        reduced[key] = value
    return reduced or None


def expand_legend_ablations(probes: list[Probe]) -> list[Probe]:
    """Expand each legend-bearing probe into four controlled variants.

    The image, question, expected answer, and all other evidence remain identical.
    Only the legend changes. ``modality`` is suffixed so summary.csv reports each
    ablation separately.
    """
    expanded: list[Probe] = []
    for probe in probes:
        if probe.legend is None:
            continue
        variants = (
            ("full_legend", probe.legend),
            ("no_color_legend", _no_color_legend(probe.legend)),
            ("no_orientation_legend", _no_orientation_legend(probe.legend)),
            ("no_legend", None),
        )
        for variant_name, legend in variants:
            expanded.append(
                replace(
                    probe,
                    probe_id=f"{probe.probe_id}__{variant_name}",
                    modality=f"{probe.modality}/{variant_name}",
                    legend=legend,
                    notes=(
                        f"Legend ablation variant: {variant_name}. "
                        + (probe.notes or "")
                    ).strip(),
                )
            )
    return expanded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit VLM understanding of BEV/evidence inputs.")
    parser.add_argument("--manifest", type=Path, required=True, help="Probe manifest JSON.")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/vlm_understanding_poc"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:8001/v1/chat/completions")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--category",
        action="append",
        default=None,
        help="Run only selected category. Repeat to select multiple categories.",
    )
    parser.add_argument(
        "--modality",
        action="append",
        default=None,
        help="Run only selected modality. Repeat to select multiple modalities.",
    )
    parser.add_argument(
        "--legend-ablation",
        action="store_true",
        help=(
            "Expand every legend-bearing selected probe into full-legend, no-color, "
            "no-orientation, and no-legend variants."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    probes = load_manifest(args.manifest)
    if args.category:
        wanted = set(args.category)
        probes = [probe for probe in probes if probe.category in wanted]
    if args.modality:
        wanted = set(args.modality)
        probes = [probe for probe in probes if probe.modality in wanted]

    if args.legend_ablation:
        probes = expand_legend_ablations(probes)

    if args.limit is not None:
        probes = probes[: args.limit]

    print(f"Loaded {len(probes)} probe(s)")
    if args.legend_ablation:
        print("Legend ablation: full / no-color / no-orientation / none")

    results = []
    for index, probe in enumerate(probes, start=1):
        print(f"[{index}/{len(probes)}] {probe.probe_id}: {probe.category}/{probe.modality}")
        result = run_probe(
            probe,
            endpoint=args.endpoint,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout_s=args.timeout_s,
        )
        results.append(result)
        if result.get("ok"):
            output = result.get("model_output") or {}
            print(
                f"  answer={output.get('answer')!r} correct={result.get('correct')} "
                f"confidence={output.get('confidence')} elapsed={result.get('elapsed_s')}s"
            )
        else:
            print(f"  ERROR: {result.get('error')}")

    write_outputs(results, args.output_dir)
    scored = [result for result in results if result.get("correct") is not None]
    correct = sum(bool(result["correct"]) for result in scored)
    accuracy = correct / len(scored) if scored else 0.0
    print(f"Done. scored={len(scored)} correct={correct} accuracy={accuracy:.3f}")
    print(f"Results: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
