"""Static HTML reviewer for Qwen VLM candidate manifests.

The renderer is scenario-agnostic. Scenario-specific evidence formatting lives in
small adapters registered in ``SCENARIO_ADAPTERS``. Only
``waiting_for_pedestrian_to_cross`` is registered initially.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ScenarioAdapter:
    title: str
    summary: Callable[[dict[str, Any]], list[tuple[str, str]]]
    evidence: Callable[[dict[str, Any]], str]


def _evidence_by_kind(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("kind")): item
        for item in candidate.get("evidence", [])
        if isinstance(item, dict) and item.get("kind")
    }


def _waiting_summary(candidate: dict[str, Any]) -> list[tuple[str, str]]:
    metadata = candidate.get("metadata") or {}
    evidence = _evidence_by_kind(candidate)
    conflict = ((evidence.get("pedestrian_corridor_conflict") or {}).get("data") or {})
    motion = conflict.get("motion") or {}
    pedestrian_id = str(metadata.get("pedestrian_id") or (candidate.get("primary_object_ids") or ["-"])[0])
    ped_motion = motion.get(pedestrian_id) or {}
    return [
        ("Pedestrian", pedestrian_id),
        ("Candidate", f"{candidate.get('start_frame')} → {candidate.get('end_frame')}"),
        ("Raw trigger", f"{metadata.get('raw_trigger_start_frame')} → {metadata.get('raw_trigger_end_frame')}"),
        ("Ped motion", str(ped_motion.get("pedestrian_motion_state", "-"))),
        ("Ped speed", _fmt_number(ped_motion.get("pedestrian_speed_mps"), "m/s")),
        ("Displacement", _fmt_number(ped_motion.get("pedestrian_displacement_m"), "m")),
        ("Lateral velocity", _fmt_number(ped_motion.get("lateral_velocity_mps"), "m/s")),
    ]


def _waiting_evidence(candidate: dict[str, Any]) -> str:
    evidence = _evidence_by_kind(candidate)
    conflict = ((evidence.get("pedestrian_corridor_conflict") or {}).get("data") or {})
    corridor = ((evidence.get("ego_future_corridor") or {}).get("data") or {})
    landmarks = ((evidence.get("event_landmarks") or {}).get("data") or {})
    payload = {
        "landmarks": landmarks,
        "future_corridor": corridor,
        "pedestrian_conflict": conflict,
    }
    return _json_pre(payload)


def _generic_summary(candidate: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("Scenario", str(candidate.get("scenario", "-"))),
        ("Candidate", f"{candidate.get('start_frame')} → {candidate.get('end_frame')}"),
        ("Primary objects", ", ".join(str(v) for v in candidate.get("primary_object_ids", [])) or "-"),
    ]


def _generic_evidence(candidate: dict[str, Any]) -> str:
    return _json_pre(candidate.get("evidence", []))


SCENARIO_ADAPTERS: dict[str, ScenarioAdapter] = {
    "waiting_for_pedestrian_to_cross": ScenarioAdapter(
        title="Waiting for pedestrian to cross",
        summary=_waiting_summary,
        evidence=_waiting_evidence,
    ),
}

GENERIC_ADAPTER = ScenarioAdapter(
    title="Qwen VLM candidate",
    summary=_generic_summary,
    evidence=_generic_evidence,
)


def _fmt_number(value: Any, suffix: str = "") -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "-"
    return f"{float(value):.3f} {suffix}".strip()


def _json_pre(value: Any) -> str:
    return "<pre>" + html.escape(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)) + "</pre>"


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _candidate_from_bundle(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    candidate = data.get("candidate", data)
    if not isinstance(candidate, dict):
        raise ValueError(f"invalid candidate bundle: {path}")
    return candidate


def _relative_uri(path_string: str, html_path: Path) -> str:
    path = Path(path_string)
    try:
        relative = os.path.relpath(path, html_path.parent)
    except ValueError:
        return path.as_uri() if path.is_absolute() else path_string
    return Path(relative).as_posix()


def _status(validation: dict[str, Any] | None) -> tuple[str, str]:
    if validation is None:
        return "NO VLM RESULT", "neutral"
    decision = validation.get("decision") or {}
    if validation.get("accepted") is True:
        return "ACCEPTED", "accepted"
    if decision.get("decision") is True:
        return "POSITIVE / NOT ACCEPTED", "review"
    if validation.get("review_required") is True:
        return "REVIEW", "review"
    return "REJECTED", "rejected"


def _validation_panel(validation: dict[str, Any] | None) -> str:
    if validation is None:
        return '<div class="muted">Candidate-only run: no VLM decision available.</div>'
    decision = validation.get("decision") or {}
    rows = [
        ("VLM decision", str(decision.get("decision", "-"))),
        ("Accepted", str(validation.get("accepted", False))),
        ("Confidence", _fmt_number(decision.get("confidence"))),
        ("Event range", f"{decision.get('event_start_frame')} → {decision.get('event_end_frame')}"),
        ("Insufficient evidence", str(decision.get("insufficient_evidence", "-"))),
        ("Review required", str(validation.get("review_required", False))),
    ]
    table = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    reason = html.escape(str(decision.get("reason") or "-"))
    ambiguities = decision.get("ambiguities") or []
    validation_reasons = validation.get("reasons") or []
    return (
        f'<table class="kv">{table}</table>'
        f'<div class="reason"><strong>Reason</strong><br>{reason}</div>'
        f'<div class="reason"><strong>Ambiguities</strong><br>{html.escape(json.dumps(ambiguities, ensure_ascii=False))}</div>'
        f'<div class="reason"><strong>Validation reasons</strong><br>{html.escape(json.dumps(validation_reasons, ensure_ascii=False))}</div>'
    )


def _candidate_card(
    candidate: dict[str, Any],
    validation: dict[str, Any] | None,
    html_path: Path,
    ordinal: int,
) -> str:
    scenario = str(candidate.get("scenario") or "unknown")
    adapter = SCENARIO_ADAPTERS.get(scenario, GENERIC_ADAPTER)
    status_text, status_class = _status(validation)
    summary_rows = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in adapter.summary(candidate)
    )
    landmarks = (candidate.get("metadata") or {}).get("landmark_roles") or {}
    role_by_frame = {int(frame): str(role) for role, frame in landmarks.items() if isinstance(frame, int)}
    images = []
    for frame_index, bev_path in zip(candidate.get("selected_frame_indices", []), candidate.get("bev_paths", [])):
        role = role_by_frame.get(int(frame_index), "selected") if isinstance(frame_index, int) else "selected"
        src = html.escape(_relative_uri(str(bev_path), html_path), quote=True)
        images.append(
            '<figure>'
            f'<img loading="lazy" src="{src}" alt="BEV frame {frame_index}">'
            f'<figcaption><strong>{html.escape(role)}</strong><br>frame {html.escape(str(frame_index))}</figcaption>'
            '</figure>'
        )
    if not images:
        images.append('<div class="muted">No rendered BEVs for this candidate.</div>')
    candidate_id = html.escape(str(candidate.get("candidate_id") or f"candidate-{ordinal}"))
    return f"""
    <section class="candidate {status_class}" data-status="{status_class}" data-id="{candidate_id}">
      <header>
        <div><span class="ordinal">#{ordinal}</span> <strong>{candidate_id}</strong></div>
        <span class="badge {status_class}">{status_text}</span>
      </header>
      <div class="grid two">
        <div>
          <h3>Candidate</h3>
          <table class="kv">{summary_rows}</table>
        </div>
        <div>
          <h3>VLM / validation</h3>
          {_validation_panel(validation)}
        </div>
      </div>
      <h3>Selected BEV landmarks</h3>
      <div class="bevs">{''.join(images)}</div>
      <details>
        <summary>Structured scenario evidence</summary>
        {adapter.evidence(candidate)}
      </details>
      <details>
        <summary>Full candidate JSON</summary>
        {_json_pre(candidate)}
      </details>
    </section>
    """


def build_review_html(manifest_path: Path, output_path: Path | None = None) -> Path:
    manifest_path = manifest_path.resolve()
    manifest = _read_json(manifest_path)
    output_path = (output_path or manifest_path.with_name(manifest_path.stem + "_review.html")).resolve()

    validation_by_id = {
        str(row.get("candidate_id")): row
        for row in manifest.get("validation", [])
        if isinstance(row, dict) and row.get("candidate_id")
    }
    candidates: list[dict[str, Any]] = []
    missing_bundles: list[str] = []
    for value in manifest.get("candidate_bundles", []):
        path = Path(str(value))
        if not path.is_absolute():
            path = (manifest_path.parent / path).resolve()
        if not path.exists():
            missing_bundles.append(str(path))
            continue
        candidates.append(_candidate_from_bundle(path))

    accepted_count = sum(1 for row in validation_by_id.values() if row.get("accepted") is True)
    review_count = sum(1 for row in validation_by_id.values() if row.get("review_required") is True)
    positive_count = sum(
        1
        for row in validation_by_id.values()
        if isinstance(row.get("decision"), dict) and row["decision"].get("decision") is True
    )
    scenario_names = sorted({str(candidate.get("scenario") or "unknown") for candidate in candidates})
    cards = "".join(
        _candidate_card(candidate, validation_by_id.get(str(candidate.get("candidate_id"))), output_path, index)
        for index, candidate in enumerate(candidates, start=1)
    )
    missing_html = ""
    if missing_bundles:
        missing_html = '<div class="warning"><strong>Missing candidate bundles:</strong><pre>' + html.escape("\n".join(missing_bundles)) + "</pre></div>"

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Qwen VLM Review</title>
<style>
:root {{ font-family: Inter, system-ui, sans-serif; color-scheme: light dark; }}
body {{ margin: 0; background: #111; color: #eee; }}
main {{ max-width: 1500px; margin: auto; padding: 24px; }}
.toolbar {{ position: sticky; top: 0; z-index: 5; background: #111e; backdrop-filter: blur(8px); padding: 12px 0; display:flex; gap:8px; flex-wrap:wrap; }}
button {{ padding: 7px 11px; border-radius: 8px; border: 1px solid #555; background:#222; color:#eee; cursor:pointer; }}
.summary {{ display:flex; gap:12px; flex-wrap:wrap; margin:12px 0 20px; }}
.metric {{ background:#1b1b1b; border:1px solid #333; border-radius:10px; padding:10px 14px; }}
.candidate {{ border:1px solid #333; border-left:5px solid #666; border-radius:12px; padding:16px; margin:18px 0; background:#181818; }}
.candidate.accepted {{ border-left-color:#2e9d56; }} .candidate.review {{ border-left-color:#d49a2a; }} .candidate.rejected {{ border-left-color:#b74d4d; }}
.candidate header {{ display:flex; justify-content:space-between; gap:12px; align-items:center; }}
.badge {{ padding:5px 9px; border-radius:999px; font-size:12px; font-weight:700; }}
.badge.accepted {{ background:#163d25; }} .badge.review {{ background:#4a3514; }} .badge.rejected {{ background:#461c1c; }} .badge.neutral {{ background:#333; }}
.grid.two {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }}
.kv {{ border-collapse:collapse; width:100%; }} .kv th,.kv td {{ text-align:left; padding:5px 8px; border-bottom:1px solid #2d2d2d; vertical-align:top; }} .kv th {{ width:170px; color:#aaa; }}
.bevs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }}
figure {{ margin:0; background:#0d0d0d; border:1px solid #333; border-radius:10px; overflow:hidden; }} figure img {{ width:100%; display:block; }} figcaption {{ padding:8px 10px; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#0d0d0d; padding:12px; border-radius:8px; max-height:480px; overflow:auto; }}
details {{ margin-top:12px; }} summary {{ cursor:pointer; font-weight:600; }} .reason {{ margin-top:8px; }} .muted {{ color:#999; }} .warning {{ padding:12px; background:#4a3514; border-radius:8px; }}
.hidden {{ display:none !important; }}
@media(max-width:800px) {{ .grid.two {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body><main>
<h1>Qwen VLM Review</h1>
<div class="muted">Manifest: {html.escape(str(manifest_path))}</div>
<div class="muted">Scenario(s): {html.escape(', '.join(scenario_names) or '-')} · Candidate strategy: {html.escape(str(manifest.get('candidate_strategy', '-')))}</div>
<div class="summary">
  <div class="metric">Candidates <strong>{len(candidates)}</strong></div>
  <div class="metric">VLM positive <strong>{positive_count}</strong></div>
  <div class="metric">Accepted <strong>{accepted_count}</strong></div>
  <div class="metric">Review <strong>{review_count}</strong></div>
</div>
<div class="toolbar">
  <button onclick="filterCards('all')">All</button>
  <button onclick="filterCards('accepted')">Accepted</button>
  <button onclick="filterCards('review')">Review / positive-not-accepted</button>
  <button onclick="filterCards('rejected')">Rejected</button>
  <button onclick="filterCards('neutral')">No VLM result</button>
</div>
{missing_html}
{cards or '<div class="warning">No candidate bundles found in this manifest.</div>'}
</main>
<script>
function filterCards(status) {{
  document.querySelectorAll('.candidate').forEach(card => {{
    card.classList.toggle('hidden', status !== 'all' && card.dataset.status !== status);
  }});
}}
</script>
</body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a static HTML reviewer from a Qwen VLM manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = build_review_html(args.manifest, args.output)
    print(f"Review HTML: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
