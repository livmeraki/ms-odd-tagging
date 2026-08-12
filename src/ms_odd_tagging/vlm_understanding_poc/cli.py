"""CLI for the VLM-understanding diagnostic PoC."""

from __future__ import annotations

import argparse
from pathlib import Path

from .runner import load_manifest, run_probe, write_outputs


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
    if args.limit is not None:
        probes = probes[: args.limit]

    print(f"Loaded {len(probes)} probe(s)")
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
