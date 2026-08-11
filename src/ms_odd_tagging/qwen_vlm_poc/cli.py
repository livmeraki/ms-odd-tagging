"""CLI for the Qwen VLM scenario-tagging POC."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from .candidates import generate_candidates
from .client import VlmClient, extract_message_text
from .config import SCENARIOS, load_config
from .evidence import load_candidate_bundle, render_candidate_bevs, write_candidate_bundle
from .event_driven import generate_event_driven_candidates
from .loader import canonical_path, load_recording
from .merging import merge_decisions
from .profiling import RunProfiler
from .review_html import build_review_html
from .scene_merge import merge_waiting_scene_candidates
from .validation import parse_and_validate_response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small Qwen VLM POC for selected scenarios.")
    parser.add_argument("--recording", action="append", help="Recording ID to process. Repeat for multiple recordings.")
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument(
        "--candidate-strategy",
        choices=("current", "event-driven"),
        default="current",
        help=(
            "Candidate generation strategy. 'current' preserves the existing POC. "
            "'event-driven' is an additive experiment; it currently changes only "
            "waiting_for_pedestrian_to_cross and falls back to current for other scenarios."
        ),
    )
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--timeout-s", type=float, default=None)
    parser.add_argument("--retries", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--window-seconds", type=float, default=None)
    parser.add_argument("--frames-per-second", type=float, default=None)
    parser.add_argument("--max-bev-images", type=int, default=None)
    parser.add_argument("--candidate-only", action="store_true", help="Generate deterministic bundles and skip VLM calls.")
    parser.add_argument("--candidate-bundle", action="append", type=Path, help="Run one saved candidate bundle. Repeatable.")
    parser.add_argument("--force-cache-refresh", action="store_true")
    parser.add_argument("--limit-candidates", type=int, default=None)
    parser.add_argument("--export-review-bundles", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def _config_from_args(args: argparse.Namespace):
    overrides = {
        "model": args.model,
        "endpoint": args.endpoint,
        "timeout_s": args.timeout_s,
        "retries": args.retries,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "window_seconds": args.window_seconds,
        "frames_per_second": args.frames_per_second,
        "max_bev_images": args.max_bev_images,
        "input_dir": args.input_dir,
        "output_root": args.output_root,
        "cache_enabled": False if args.no_cache else None,
    }
    return load_config(args.config, overrides=overrides)


def _run_directory(base_output_root: Path, now: datetime | None = None) -> Path:
    """Return a unique timestamped directory for one CLI invocation."""
    generated_at = now or datetime.now()
    run_id = generated_at.strftime("%Y%m%d_%H%M%S_%f")
    return base_output_root / run_id


def _copy_review_bundle(bundle_path: Path, output_root: Path, reason: str) -> Path:
    safe_reason = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_"
        for char in reason
    ).strip("_")[:120] or "review_required"
    target = output_root / "review" / safe_reason / bundle_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_path, target)
    return target


def _recording_for_bundle(bundle_path: Path, input_dir: Path) -> dict:
    candidate = load_candidate_bundle(bundle_path)
    return load_recording(canonical_path(input_dir, candidate.recording_id))


def _generate_candidates(recording: dict, scenario: str, config, strategy: str):
    if strategy == "event-driven":
        candidates = generate_event_driven_candidates(recording, scenario, config)
        if scenario == "waiting_for_pedestrian_to_cross":
            return merge_waiting_scene_candidates(recording, candidates, config)
        return candidates
    return generate_candidates(recording, scenario, config)


def _finalize_outputs(
    manifest: dict,
    manifest_path: Path,
    profiler: RunProfiler,
) -> tuple[Path, Path]:
    timing_path = manifest_path.with_name(manifest_path.stem + "_timing.json")
    manifest["timing_profile"] = str(timing_path)
    with profiler.measure("manifest_write", path=str(manifest_path)):
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    with profiler.measure("review_html_generation", path=str(manifest_path)):
        review_path = build_review_html(manifest_path)
    profiler.write(timing_path)
    return review_path, timing_path


def _print_timing(profiler: RunProfiler, timing_path: Path) -> None:
    print(f"Timing profile: {timing_path}")
    for line in profiler.console_lines():
        print(line)


def _focused_scene_results(validation_rows: list[dict]) -> list[dict]:
    focused_groups: dict[str, list[dict]] = {}
    for row in validation_rows:
        parent_scene_id = row.get("parent_scene_candidate_id")
        if not parent_scene_id:
            continue
        focused_groups.setdefault(str(parent_scene_id), []).append(row)
    results = []
    for parent_scene_id, rows in sorted(focused_groups.items()):
        accepted_rows = [row for row in rows if row.get("accepted") is True]
        accepted_pedestrians = []
        for row in accepted_rows:
            decision = row.get("decision") or {}
            for object_id in decision.get("primary_object_ids") or []:
                if object_id not in accepted_pedestrians:
                    accepted_pedestrians.append(object_id)
        results.append(
            {
                "parent_scene_candidate_id": parent_scene_id,
                "decision": bool(accepted_rows),
                "accepted_focused_candidate_ids": [row["candidate_id"] for row in accepted_rows],
                "accepted_primary_object_ids": accepted_pedestrians,
                "focused_candidate_count": len(rows),
                "review_required": not accepted_rows and any(row.get("review_required") for row in rows),
                "all_focused_negative": not accepted_rows,
            }
        )
    return results


def main() -> int:
    profiler = RunProfiler()
    args = parse_args()
    with profiler.measure("config_load"):
        config = _config_from_args(args)
    if not args.candidate_bundle and not args.recording:
        raise SystemExit("--recording is required unless --candidate-bundle is supplied")

    strategy_root = (
        config.output_root / "event_driven"
        if args.candidate_strategy == "event-driven"
        else config.output_root
    )
    output_root = _run_directory(strategy_root)
    output_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "qwen-vlm-poc-run-manifest-v1",
        "candidate_strategy": args.candidate_strategy,
        "effective_output_root": str(output_root),
        "run_id": output_root.name,
        "generated_at_local": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "config": config.to_dict(),
        "candidate_bundles": [],
        "raw_results": [],
        "validation": [],
        "focused_scene_results": [],
        "events": [],
        "review_bundles": [],
    }

    candidate_rows = []
    if args.candidate_bundle:
        for bundle_path in args.candidate_bundle:
            with profiler.measure("candidate_bundle_load", bundle_path=str(bundle_path)):
                candidate = load_candidate_bundle(bundle_path)
                recording = _recording_for_bundle(bundle_path, config.input_dir)
            if candidate.scenario != args.scenario:
                raise SystemExit(f"{bundle_path} scenario {candidate.scenario!r} does not match --scenario {args.scenario!r}")
            candidate_rows.append((recording, candidate, bundle_path))
            manifest["candidate_bundles"].append(str(bundle_path))
    else:
        for recording_id in args.recording or []:
            path = canonical_path(config.input_dir, recording_id)
            with profiler.measure("recording_load", recording_id=recording_id):
                recording = load_recording(path)
            with profiler.measure(
                "candidate_generation",
                recording_id=recording_id,
                scenario=args.scenario,
                strategy=args.candidate_strategy,
            ):
                candidates = _generate_candidates(
                    recording,
                    args.scenario,
                    config,
                    args.candidate_strategy,
                )
            if args.limit_candidates is not None:
                candidates = candidates[: args.limit_candidates]
            for candidate in candidates:
                with profiler.measure(
                    "bev_render",
                    recording_id=recording_id,
                    candidate_id=candidate.candidate_id,
                ):
                    candidate = render_candidate_bevs(recording, candidate, output_root, config)
                with profiler.measure(
                    "candidate_bundle_write",
                    recording_id=recording_id,
                    candidate_id=candidate.candidate_id,
                ):
                    bundle_path = write_candidate_bundle(candidate, output_root)
                candidate_rows.append((recording, candidate, bundle_path))
                manifest["candidate_bundles"].append(str(bundle_path))

    if args.candidate_only:
        manifest_path = output_root / f"manifest_candidate_only_{args.scenario}.json"
        review_path, timing_path = _finalize_outputs(manifest, manifest_path, profiler)
        print(f"Wrote {len(candidate_rows)} candidate bundle(s)")
        print(f"Candidate strategy: {args.candidate_strategy}")
        print(f"Run directory: {output_root}")
        print(f"Manifest: {manifest_path}")
        print(f"Review HTML: {review_path}")
        _print_timing(profiler, timing_path)
        return 0

    client = VlmClient(
        config,
        cache_dir=strategy_root / "cache",
        raw_dir=output_root / "raw_responses" / args.scenario,
        request_dir=output_root / "request_payloads" / args.scenario,
    )
    accepted_by_recording: dict[str, list] = {}
    recording_by_id = {}
    for recording, candidate, bundle_path in candidate_rows:
        recording_by_id[candidate.recording_id] = recording
        try:
            with profiler.measure(
                "vlm_inference",
                recording_id=candidate.recording_id,
                candidate_id=candidate.candidate_id,
            ):
                raw = client.infer(candidate, force_refresh=args.force_cache_refresh)
            with profiler.measure(
                "response_extract",
                recording_id=candidate.recording_id,
                candidate_id=candidate.candidate_id,
            ):
                raw_text = extract_message_text(raw)
            with profiler.measure(
                "validation",
                recording_id=candidate.recording_id,
                candidate_id=candidate.candidate_id,
            ):
                validation = parse_and_validate_response(raw_text, candidate, config)
        except Exception as exc:
            raw = {"ok": False, "candidate_id": candidate.candidate_id, "error": str(exc)}
            with profiler.measure(
                "validation_error_fallback",
                recording_id=candidate.recording_id,
                candidate_id=candidate.candidate_id,
            ):
                validation = parse_and_validate_response("{}", candidate, config)
                validation = type(validation)(
                    accepted=False,
                    review_required=True,
                    reasons=["inference_failure_or_timeout:" + str(exc)],
                    decision=validation.decision,
                    raw_text=validation.raw_text,
                )
        manifest["raw_results"].append(raw)
        validation_row = {
            "candidate_id": candidate.candidate_id,
            "parent_scene_candidate_id": candidate.metadata.get("parent_scene_candidate_id"),
            "focused_primary_pedestrian_id": candidate.metadata.get("focused_primary_pedestrian_id"),
            "accepted": validation.accepted,
            "review_required": validation.review_required,
            "reasons": validation.reasons,
            "decision": validation.decision.to_dict() if validation.decision else None,
            "decisions": [decision.to_dict() for decision in validation.decisions],
        }
        manifest["validation"].append(validation_row)
        if validation.accepted and validation.decisions:
            for decision in validation.decisions:
                accepted_by_recording.setdefault(candidate.recording_id, []).append((candidate, decision))
        elif args.export_review_bundles and validation.review_required:
            with profiler.measure(
                "review_bundle_copy",
                recording_id=candidate.recording_id,
                candidate_id=candidate.candidate_id,
            ):
                review_path = _copy_review_bundle(
                    bundle_path,
                    output_root,
                    validation.reasons[0] if validation.reasons else "review_required",
                )
            manifest["review_bundles"].append(str(review_path))

    manifest["focused_scene_results"] = _focused_scene_results(manifest["validation"])

    for recording_id, accepted in accepted_by_recording.items():
        with profiler.measure("event_merge", recording_id=recording_id):
            events = merge_decisions(recording_by_id[recording_id], accepted, config)
        event_path = output_root / "events" / args.scenario / f"{recording_id}_events.json"
        with profiler.measure("event_write", recording_id=recording_id, path=str(event_path)):
            event_path.parent.mkdir(parents=True, exist_ok=True)
            event_path.write_text(
                json.dumps([event.to_dict() for event in events], indent=2, sort_keys=True),
                encoding="utf-8",
            )
        manifest["events"].append(str(event_path))

    manifest_path = output_root / f"manifest_{args.scenario}.json"
    review_path, timing_path = _finalize_outputs(manifest, manifest_path, profiler)
    print(f"Processed {len(candidate_rows)} candidate(s)")
    print(f"Candidate strategy: {args.candidate_strategy}")
    print(f"Accepted recordings: {len(accepted_by_recording)}")
    print(f"Run directory: {output_root}")
    print(f"Manifest: {manifest_path}")
    print(f"Review HTML: {review_path}")
    _print_timing(profiler, timing_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
