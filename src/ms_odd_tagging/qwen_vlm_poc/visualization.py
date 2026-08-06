"""Standalone HTML review page for Qwen VLM POC outputs."""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def _rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _candidate_id_suffix(candidate_id: str, recording_id: str) -> str:
    prefix = f"{recording_id}_"
    return candidate_id[len(prefix) :] if candidate_id.startswith(prefix) else candidate_id


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_match(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern))
    return matches[-1] if matches else None


def _read_raw_content(path: Path | None) -> tuple[str | None, dict[str, Any] | None]:
    if path is None:
        return None, None
    data = _load_json(path)
    try:
        content = data["response"]["choices"][0]["message"]["content"]
    except Exception:
        content = data.get("error")
    return content, data.get("response", {}).get("usage")


def _make_contact_sheet(candidate: dict[str, Any], candidate_id: str, run_root: Path) -> Path | None:
    image_paths = [Path(path) for path in candidate.get("bev_paths", []) if Path(path).is_file()]
    if not image_paths:
        return None
    out_dir = run_root / "review_contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{candidate_id}_contact.jpg"
    if out_path.is_file():
        return out_path

    thumb_w = 360
    label_h = 22
    gap = 8
    cols = min(3, len(image_paths))
    rows = math.ceil(len(image_paths) / cols)
    thumbs: list[tuple[Image.Image, str]] = []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        scale = thumb_w / image.width
        thumb_h = max(1, int(image.height * scale))
        image = image.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        thumbs.append((image, path.stem.rsplit("_frame_", 1)[-1]))
    cell_h = max(image.height for image, _ in thumbs) + label_h
    sheet = Image.new("RGB", (cols * thumb_w + (cols + 1) * gap, rows * cell_h + (rows + 1) * gap), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (image, label) in enumerate(thumbs):
        row, col = divmod(index, cols)
        x = gap + col * (thumb_w + gap)
        y = gap + row * (cell_h + gap)
        sheet.paste(image, (x, y + label_h))
        draw.text((x, y), f"frame {label}", fill=(20, 28, 36))
    sheet.save(out_path, quality=88)
    return out_path


def _load_rows(run_root: Path, candidate_root: Path, scenario: str) -> list[dict[str, Any]]:
    manifest_path = run_root / f"manifest_{scenario}.json"
    if not manifest_path.is_file():
        return []
    manifest = _load_json(manifest_path)
    rows = []
    for validation, raw in zip(manifest.get("validation", []), manifest.get("raw_results", [])):
        candidate_id = validation["candidate_id"]
        decision = validation.get("decision") or {}
        recording_id = decision.get("recording_id")
        if not recording_id or recording_id == "None":
            recording_id = candidate_id.split(f"_{scenario}_")[0]
        candidate_path = candidate_root / scenario / recording_id / f"{candidate_id}.json"
        candidate = _load_json(candidate_path).get("candidate", {}) if candidate_path.is_file() else {}
        raw_path = _latest_match(run_root / "raw_responses" / scenario, f"{candidate_id}_*.json")
        request_path = _latest_match(run_root / "request_payloads" / scenario, f"{candidate_id}_*.json")
        contact_path = _make_contact_sheet(candidate, candidate_id, run_root)
        raw_content, usage = _read_raw_content(raw_path)
        rows.append(
            {
                "scenario": scenario,
                "candidate_id": candidate_id,
                "candidate_label": _candidate_id_suffix(candidate_id, recording_id),
                "recording_id": recording_id,
                "frame_range": f"{candidate.get('start_frame', decision.get('window_start_frame'))}-{candidate.get('end_frame', decision.get('window_end_frame'))}",
                "recall_reasons": candidate.get("recall_reasons") or [],
                "decision": decision.get("decision"),
                "confidence": decision.get("confidence"),
                "event_range": (
                    f"{decision.get('event_start_frame')}-{decision.get('event_end_frame')}"
                    if decision.get("event_start_frame") is not None
                    else ""
                ),
                "primary_object_ids": decision.get("primary_object_ids") or [],
                "evidence_ids": decision.get("evidence_ids") or [],
                "reason": decision.get("reason") or raw.get("error") or "",
                "ambiguities": decision.get("ambiguities") or [],
                "insufficient_evidence": decision.get("insufficient_evidence"),
                "accepted": bool(validation.get("accepted")),
                "review_required": bool(validation.get("review_required")),
                "validation_reasons": validation.get("reasons") or [],
                "latency_s": raw.get("elapsed_s"),
                "usage": usage or {},
                "candidate_path": str(candidate_path) if candidate_path.is_file() else None,
                "raw_path": str(raw_path) if raw_path else None,
                "request_path": str(request_path) if request_path else None,
                "contact_path": str(contact_path) if contact_path.is_file() else None,
                "raw_content": raw_content,
            }
        )
    return rows


def build_payload(run_root: Path, candidate_root: Path) -> dict[str, Any]:
    rows = []
    for scenario in ("on_intersection", "waiting_for_pedestrian_to_cross"):
        rows.extend(_load_rows(run_root, candidate_root, scenario))
    events = []
    for path in sorted((run_root / "events").glob("*/*_events.json")):
        events.append({"path": str(path), "events": json.loads(path.read_text(encoding="utf-8"))})
    return {
        "schema_version": "qwen-vlm-poc-review-html-v1",
        "run_root": str(run_root),
        "candidate_root": str(candidate_root),
        "rows": rows,
        "events": events,
    }


def _render_status(row: dict[str, Any]) -> str:
    if row["accepted"]:
        return "accepted"
    if row["review_required"]:
        return "review"
    return "valid reject"


def render_html(payload: dict[str, Any], output_path: Path) -> str:
    output_dir = output_path.parent
    rows_html = []
    for index, row in enumerate(payload["rows"]):
        status = _render_status(row)
        status_class = status.replace(" ", "-")
        contact = (
            f'<a href="{html.escape(_rel(Path(row["contact_path"]), output_dir))}">'
            f'<img src="{html.escape(_rel(Path(row["contact_path"]), output_dir))}" alt="BEV contact sheet"></a>'
            if row.get("contact_path")
            else '<div class="missing">No BEV contact sheet</div>'
        )
        links = []
        for label, key in (("candidate", "candidate_path"), ("request", "request_path"), ("raw", "raw_path")):
            if row.get(key):
                links.append(f'<a href="{html.escape(_rel(Path(row[key]), output_dir))}">{label}</a>')
        evidence = "".join(f"<li>{html.escape(eid)}</li>" for eid in row["evidence_ids"])
        objects = ", ".join(row["primary_object_ids"]) or "-"
        usage = row.get("usage") or {}
        rows_html.append(
            f"""
<article class="candidate {status_class}" data-scenario="{html.escape(row['scenario'])}" data-status="{html.escape(status_class)}">
  <div class="media">{contact}</div>
  <div class="body">
    <div class="topline"><span class="scenario">{html.escape(row['scenario'])}</span><span class="status">{html.escape(status)}</span></div>
    <h2>{html.escape(row['frame_range'])}</h2>
    <p class="muted">{html.escape(row['recording_id'])}</p>
    <dl>
      <dt>candidate</dt><dd>{html.escape(row['candidate_label'])}</dd>
      <dt>recall</dt><dd>{html.escape(', '.join(row['recall_reasons']) or '-')}</dd>
      <dt>decision</dt><dd>{html.escape(str(row['decision']))}</dd>
      <dt>confidence</dt><dd>{html.escape(str(row['confidence']))}</dd>
      <dt>event</dt><dd>{html.escape(row['event_range'] or '-')}</dd>
      <dt>objects</dt><dd>{html.escape(objects)}</dd>
      <dt>latency</dt><dd>{html.escape(str(row['latency_s']))} s</dd>
      <dt>tokens</dt><dd>{html.escape(str(usage.get('total_tokens', '-')))}</dd>
    </dl>
    <p>{html.escape(row['reason'])}</p>
    <p class="muted">validation: {html.escape(', '.join(row['validation_reasons']) or 'none')}</p>
    <details><summary>Evidence IDs</summary><ul>{evidence}</ul></details>
    <details><summary>Raw response</summary><pre>{html.escape(row.get('raw_content') or '')}</pre></details>
    <div class="links">{' '.join(links)}</div>
  </div>
</article>"""
        )
    accepted_count = sum(1 for row in payload["rows"] if row["accepted"])
    review_count = sum(1 for row in payload["rows"] if row["review_required"])
    reject_count = len(payload["rows"]) - accepted_count - review_count
    event_rows = []
    for group in payload["events"]:
        for event in group["events"]:
            event_rows.append(
                f"<li><b>{html.escape(event.get('scenario', ''))}</b> "
                f"frames {event.get('start_frame')}-{event.get('end_frame')} "
                f"confidence {event.get('confidence')} "
                f"<span>{html.escape(group['path'])}</span></li>"
            )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Qwen VLM POC Review</title>
  <style>
    :root{{--bg:#f6f8fb;--fg:#17202a;--panel:#fff;--muted:#657287;--border:#d8dee8;--accepted:#087f5b;--review:#9a6700;--reject:#566171;--link:#2458c6}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
    header{{padding:18px 24px;background:var(--panel);border-bottom:1px solid var(--border)}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:18px;margin:4px 0}}main{{max-width:1500px;margin:auto;padding:18px;display:grid;gap:14px}}
    .summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}}.stat,.candidate,.events{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px}}.stat b{{display:block;font-size:22px}}.muted{{color:var(--muted)}}.filters{{display:flex;gap:10px;flex-wrap:wrap}}button{{border:1px solid var(--border);background:var(--panel);color:var(--fg);border-radius:6px;padding:7px 10px;cursor:pointer}}button.active{{outline:2px solid var(--link)}}.candidate{{display:grid;grid-template-columns:minmax(420px,1.2fr) minmax(340px,.8fr);gap:14px}}img{{width:100%;height:auto;border:1px solid var(--border);border-radius:6px}}.topline{{display:flex;justify-content:space-between;gap:10px}}.scenario{{font-weight:700}}.status{{border-radius:999px;padding:2px 8px;color:#fff;background:var(--reject)}}.accepted .status{{background:var(--accepted)}}.review .status{{background:var(--review)}}dl{{display:grid;grid-template-columns:100px minmax(0,1fr);gap:4px 10px}}dt{{color:var(--muted)}}dd{{margin:0;min-width:0;overflow-wrap:anywhere}}a{{color:var(--link);font-weight:600;margin-right:10px}}pre{{white-space:pre-wrap;background:#f1f4f8;border:1px solid var(--border);border-radius:6px;padding:10px;max-height:280px;overflow:auto}}li{{overflow-wrap:anywhere}}.missing{{border:1px dashed var(--border);border-radius:6px;min-height:220px;display:grid;place-items:center;color:var(--muted)}}@media(max-width:900px){{.candidate{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
  <header>
    <h1>Qwen VLM POC Review</h1>
    <p class="muted">{html.escape(payload['run_root'])}</p>
  </header>
  <main>
    <section class="summary">
      <div class="stat"><span>Candidates</span><b>{len(payload['rows'])}</b></div>
      <div class="stat"><span>Accepted</span><b>{accepted_count}</b></div>
      <div class="stat"><span>Review</span><b>{review_count}</b></div>
      <div class="stat"><span>Valid Reject</span><b>{reject_count}</b></div>
    </section>
    <nav class="filters">
      <button class="active" data-filter="all">All</button>
      <button data-filter="on_intersection">on_intersection</button>
      <button data-filter="waiting_for_pedestrian_to_cross">waiting_for_pedestrian</button>
      <button data-status="accepted">Accepted</button>
      <button data-status="review">Review</button>
      <button data-status="valid-reject">Valid Reject</button>
    </nav>
    <section class="events"><h2>Accepted Events</h2><ul>{''.join(event_rows) or '<li>None</li>'}</ul></section>
    {''.join(rows_html)}
  </main>
  <script>
    const buttons=[...document.querySelectorAll('button')],cards=[...document.querySelectorAll('.candidate')];
    buttons.forEach(button=>button.addEventListener('click',()=>{{buttons.forEach(item=>item.classList.remove('active'));button.classList.add('active');const scenario=button.dataset.filter,status=button.dataset.status;cards.forEach(card=>{{const show=(!scenario||scenario==='all'||card.dataset.scenario===scenario)&&(!status||card.dataset.status===status);card.style.display=show?'grid':'none';}})}}));
  </script>
</body>
</html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a standalone Qwen VLM POC review HTML page.")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.run_root / "qwen_review.html"
    payload = build_payload(args.run_root, args.candidate_root)
    render_html(payload, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
