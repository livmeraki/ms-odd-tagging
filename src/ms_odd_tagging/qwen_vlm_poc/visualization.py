"""Standalone HTML review page for Qwen VLM POC outputs."""

from __future__ import annotations

import argparse
import html
import json
import math
from collections import Counter, defaultdict
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


def _discover_manifests(run_root: Path) -> list[Path]:
    return sorted(
        path
        for path in run_root.rglob("manifest_*.json")
        if path.is_file() and "candidate_only" not in path.name
    )


def _scenario_from_manifest(path: Path) -> str:
    name = path.name
    return name.removeprefix("manifest_").removesuffix(".json")


def _read_raw_content(path: Path | None) -> tuple[str | None, dict[str, Any] | None]:
    if path is None:
        return None, None
    data = _load_json(path)
    try:
        content = data["response"]["choices"][0]["message"]["content"]
    except Exception:
        content = data.get("error")
    return content, data.get("response", {}).get("usage")


def _make_contact_sheet(candidate: dict[str, Any], candidate_id: str, manifest_dir: Path) -> Path | None:
    image_paths = [Path(path) for path in candidate.get("bev_paths", []) if Path(path).is_file()]
    if not image_paths:
        return None
    out_dir = manifest_dir / "review_contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{candidate_id}_contact.jpg"

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


def _candidate_path_candidates(
    manifest_dir: Path,
    candidate_root: Path,
    scenario: str,
    recording_id: str,
    candidate_id: str,
) -> list[Path]:
    return [
        manifest_dir / "candidates" / scenario / recording_id / f"{candidate_id}.json",
        candidate_root / scenario / recording_id / f"{candidate_id}.json",
        candidate_root / "candidates" / scenario / recording_id / f"{candidate_id}.json",
    ]


def _find_candidate_path(
    manifest_dir: Path,
    candidate_root: Path,
    scenario: str,
    recording_id: str,
    candidate_id: str,
) -> Path | None:
    for path in _candidate_path_candidates(manifest_dir, candidate_root, scenario, recording_id, candidate_id):
        if path.is_file():
            return path
    matches = sorted(candidate_root.rglob(f"{candidate_id}.json")) if candidate_root.is_dir() else []
    return matches[-1] if matches else None


def _status(validation: dict[str, Any], decision: dict[str, Any]) -> str:
    if validation.get("accepted"):
        return "accepted"
    if validation.get("review_required"):
        return "review"
    if decision.get("decision") is False:
        return "rejected"
    return "failed"


def _load_rows_from_manifest(manifest_path: Path, candidate_root: Path) -> list[dict[str, Any]]:
    manifest_dir = manifest_path.parent
    scenario = _scenario_from_manifest(manifest_path)
    manifest = _load_json(manifest_path)
    rows = []
    raw_results = manifest.get("raw_results", [])
    validations = manifest.get("validation", [])
    for index, validation in enumerate(validations):
        raw = raw_results[index] if index < len(raw_results) else {}
        candidate_id = validation["candidate_id"]
        decision = validation.get("decision") or {}
        recording_id = decision.get("recording_id")
        if not recording_id or recording_id == "None":
            recording_id = candidate_id.split(f"_{scenario}_")[0]
        candidate_path = _find_candidate_path(manifest_dir, candidate_root, scenario, recording_id, candidate_id)
        candidate = _load_json(candidate_path).get("candidate", {}) if candidate_path else {}
        raw_path = _latest_match(manifest_dir / "raw_responses" / scenario, f"{candidate_id}_*.json")
        request_path = _latest_match(manifest_dir / "request_payloads" / scenario, f"{candidate_id}_*.json")
        contact_path = _make_contact_sheet(candidate, candidate_id, manifest_dir)
        raw_content, usage = _read_raw_content(raw_path)
        status = _status(validation, decision)
        rows.append(
            {
                "scenario": scenario,
                "status": status,
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
                "validation_reasons": validation.get("reasons") or [],
                "latency_s": raw.get("elapsed_s"),
                "usage": usage or {},
                "candidate_path": str(candidate_path) if candidate_path else None,
                "raw_path": str(raw_path) if raw_path else None,
                "request_path": str(request_path) if request_path else None,
                "contact_path": str(contact_path) if contact_path else None,
                "raw_content": raw_content,
                "manifest_path": str(manifest_path),
            }
        )
    return rows


def _load_events(run_root: Path) -> list[dict[str, Any]]:
    groups = []
    for path in sorted((run_root).rglob("*_events.json")):
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(events, list):
            groups.append({"path": str(path), "events": events})
    return groups


def _scenario_stats(rows: list[dict[str, Any]], manifest_counts: Counter[str]) -> list[dict[str, Any]]:
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_scenario[row["scenario"]].append(row)
    stats = []
    for scenario in sorted(set(by_scenario) | set(manifest_counts)):
        scenario_rows = by_scenario.get(scenario, [])
        statuses = Counter(row["status"] for row in scenario_rows)
        decisions = Counter(str(row["decision"]) for row in scenario_rows)
        stats.append(
            {
                "scenario": scenario,
                "candidates": len(scenario_rows),
                "accepted": statuses["accepted"],
                "review": statuses["review"],
                "rejected": statuses["rejected"],
                "failed": statuses["failed"],
                "positive_decisions": decisions["True"],
                "negative_decisions": decisions["False"],
                "recordings": len({row["recording_id"] for row in scenario_rows}) or manifest_counts[scenario],
            }
        )
    return stats


def build_payload(run_root: Path, candidate_root: Path) -> dict[str, Any]:
    rows = []
    manifests = _discover_manifests(run_root)
    manifest_counts = Counter(_scenario_from_manifest(path) for path in manifests)
    for manifest_path in manifests:
        rows.extend(_load_rows_from_manifest(manifest_path, candidate_root))
    rows.sort(key=lambda row: (row["scenario"], row["recording_id"], row["frame_range"], row["candidate_id"]))
    return {
        "schema_version": "qwen-vlm-poc-review-html-v2",
        "run_root": str(run_root),
        "candidate_root": str(candidate_root),
        "rows": rows,
        "scenario_stats": _scenario_stats(rows, manifest_counts),
        "events": _load_events(run_root),
    }


def _badge(text: str, css_class: str = "") -> str:
    return f'<span class="badge {html.escape(css_class)}">{html.escape(text)}</span>'


def _status_label(status: str) -> str:
    return {
        "accepted": "accepted",
        "review": "review",
        "rejected": "rejected",
        "failed": "failed",
    }.get(status, status)


def _stats_table(stats: list[dict[str, Any]]) -> str:
    rows = []
    for item in stats:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['scenario'])}</td>"
            f"<td>{item['recordings']}</td>"
            f"<td>{item['candidates']}</td>"
            f"<td>{item['positive_decisions']}</td>"
            f"<td>{item['negative_decisions']}</td>"
            f"<td>{item['accepted']}</td>"
            f"<td>{item['review']}</td>"
            f"<td>{item['rejected']}</td>"
            f"<td>{item['failed']}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="9">No candidate rows</td></tr>'


def _filters(stats: list[dict[str, Any]]) -> str:
    scenario_buttons = "".join(
        f'<button data-filter="{html.escape(item["scenario"])}">{html.escape(item["scenario"])} ({item["candidates"]})</button>'
        for item in stats
    )
    return (
        '<button class="active" data-filter="all">All</button>'
        f"{scenario_buttons}"
        '<button data-status="accepted">Accepted</button>'
        '<button data-status="review">Review</button>'
        '<button data-status="rejected">Rejected</button>'
        '<button data-status="failed">Failed</button>'
    )


def _event_rows(groups: list[dict[str, Any]]) -> str:
    rows = []
    for group in groups:
        for event in group["events"]:
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(event.get('scenario', '')))}</td>"
                f"<td>{html.escape(str(event.get('recording_id', '')))}</td>"
                f"<td>{event.get('start_frame')}-{event.get('end_frame')}</td>"
                f"<td>{html.escape(str(event.get('confidence')))}</td>"
                f"<td>{html.escape(str(event.get('primary_object_ids') or '-'))}</td>"
                f"<td>{html.escape(group['path'])}</td>"
                "</tr>"
            )
    return "".join(rows) or '<tr><td colspan="6">None</td></tr>'


def _candidate_card(row: dict[str, Any], output_dir: Path) -> str:
    contact = (
        f'<a href="{html.escape(_rel(Path(row["contact_path"]), output_dir))}">'
        f'<img src="{html.escape(_rel(Path(row["contact_path"]), output_dir))}" alt="BEV contact sheet"></a>'
        if row.get("contact_path")
        else '<div class="missing">No BEV contact sheet</div>'
    )
    links = []
    for label, key in (("candidate", "candidate_path"), ("request", "request_path"), ("raw", "raw_path"), ("manifest", "manifest_path")):
        if row.get(key):
            links.append(f'<a href="{html.escape(_rel(Path(row[key]), output_dir))}">{label}</a>')
    evidence = "".join(f"<li>{html.escape(eid)}</li>" for eid in row["evidence_ids"])
    objects = ", ".join(str(item) for item in row["primary_object_ids"]) or "-"
    usage = row.get("usage") or {}
    recall = ", ".join(row["recall_reasons"]) or "-"
    validation = ", ".join(row["validation_reasons"]) or "none"
    status = row["status"]
    decision_text = "positive" if row["decision"] is True else "negative" if row["decision"] is False else "none"
    return f"""
<article id="{html.escape(row['candidate_id'])}" class="candidate {html.escape(status)}" data-scenario="{html.escape(row['scenario'])}" data-status="{html.escape(status)}" data-search="{html.escape((row['recording_id'] + ' ' + row['candidate_id'] + ' ' + row['reason']).lower())}">
  <div class="media">{contact}</div>
  <div class="body">
    <div class="topline">
      <div>{_badge(row['scenario'], 'scenario')} {_badge(_status_label(status), status)} {_badge(decision_text, 'decision')}</div>
      <a class="anchor" href="#{html.escape(row['candidate_id'])}">#</a>
    </div>
    <h2>{html.escape(row['recording_id'])}</h2>
    <div class="frame">frames {html.escape(row['frame_range'])}</div>
    <dl>
      <dt>candidate</dt><dd>{html.escape(row['candidate_label'])}</dd>
      <dt>recall</dt><dd>{html.escape(recall)}</dd>
      <dt>confidence</dt><dd>{html.escape(str(row['confidence']))}</dd>
      <dt>event</dt><dd>{html.escape(row['event_range'] or '-')}</dd>
      <dt>objects</dt><dd>{html.escape(objects)}</dd>
      <dt>latency</dt><dd>{html.escape(str(row['latency_s']))} s</dd>
      <dt>tokens</dt><dd>{html.escape(str(usage.get('total_tokens', '-')))}</dd>
    </dl>
    <p class="reason">{html.escape(row['reason'])}</p>
    <p class="muted">validation: {html.escape(validation)}</p>
    <details><summary>Evidence IDs</summary><ul>{evidence}</ul></details>
    <details><summary>Raw response</summary><pre>{html.escape(row.get('raw_content') or '')}</pre></details>
    <div class="links">{' '.join(links)}</div>
  </div>
</article>"""


def render_html(payload: dict[str, Any], output_path: Path) -> str:
    output_dir = output_path.parent
    rows = payload["rows"]
    accepted_count = sum(1 for row in rows if row["status"] == "accepted")
    review_count = sum(1 for row in rows if row["status"] == "review")
    rejected_count = sum(1 for row in rows if row["status"] == "rejected")
    failed_count = sum(1 for row in rows if row["status"] == "failed")
    candidate_cards = "".join(_candidate_card(row, output_dir) for row in rows)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Qwen VLM Review</title>
  <style>
    :root{{--bg:#f6f7f9;--fg:#17202a;--panel:#fff;--muted:#647083;--border:#d6dce5;--line:#e8edf3;--accepted:#087f5b;--review:#9a6700;--rejected:#566171;--failed:#b42318;--link:#2458c6}}
    *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}a{{color:var(--link);font-weight:600;text-decoration:none}}a:hover{{text-decoration:underline}}
    header{{position:sticky;top:0;z-index:5;background:rgba(255,255,255,.96);border-bottom:1px solid var(--border);padding:14px 20px}}h1{{font-size:21px;margin:0 0 4px}}h2{{font-size:17px;margin:4px 0}}.muted{{color:var(--muted)}}.layout{{display:grid;grid-template-columns:310px minmax(0,1fr);gap:16px;max-width:1760px;margin:0 auto;padding:16px}}aside{{position:sticky;top:82px;align-self:start;display:grid;gap:12px}}.panel,.candidate{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px}}.summary{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.stat{{border:1px solid var(--line);border-radius:7px;padding:8px;background:#fbfcfe}}.stat b{{display:block;font-size:22px}}.filters{{display:grid;gap:8px}}button,input{{border:1px solid var(--border);background:var(--panel);color:var(--fg);border-radius:6px;padding:8px 10px}}button{{text-align:left;cursor:pointer}}button.active{{outline:2px solid var(--link)}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid var(--line);padding:7px;text-align:left;vertical-align:top}}th{{font-size:12px;color:var(--muted);font-weight:700}}main{{display:grid;gap:14px}}.candidate{{display:grid;grid-template-columns:minmax(520px,1.25fr) minmax(380px,.75fr);gap:14px}}img{{width:100%;height:auto;border:1px solid var(--border);border-radius:6px;background:white}}.topline{{display:flex;justify-content:space-between;gap:10px;align-items:start}}.badge{{display:inline-flex;align-items:center;border-radius:999px;padding:2px 8px;margin:0 4px 4px 0;background:#eef2f7;color:#253041;font-weight:700;font-size:12px}}.badge.accepted{{background:var(--accepted);color:white}}.badge.review{{background:var(--review);color:white}}.badge.rejected{{background:var(--rejected);color:white}}.badge.failed{{background:var(--failed);color:white}}.badge.scenario{{background:#e7efff;color:#143d86}}.badge.decision{{background:#edf7ee;color:#23512b}}.frame{{font-weight:700;color:#394457;margin-bottom:8px}}dl{{display:grid;grid-template-columns:96px minmax(0,1fr);gap:4px 10px}}dt{{color:var(--muted)}}dd{{margin:0;min-width:0;overflow-wrap:anywhere}}.reason{{font-size:15px}}pre{{white-space:pre-wrap;background:#f1f4f8;border:1px solid var(--border);border-radius:6px;padding:10px;max-height:280px;overflow:auto}}li,td,dd,p{{overflow-wrap:anywhere}}.links a{{margin-right:10px}}.missing{{border:1px dashed var(--border);border-radius:6px;min-height:260px;display:grid;place-items:center;color:var(--muted)}}.hidden{{display:none!important}}@media(max-width:1100px){{.layout{{grid-template-columns:1fr}}aside{{position:static}}.candidate{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
  <header>
    <h1>Qwen VLM Review</h1>
    <div class="muted">{html.escape(payload['run_root'])}</div>
  </header>
  <div class="layout">
    <aside>
      <section class="panel">
        <h2>Summary</h2>
        <div class="summary">
          <div class="stat"><span>Candidates</span><b>{len(rows)}</b></div>
          <div class="stat"><span>Accepted</span><b>{accepted_count}</b></div>
          <div class="stat"><span>Review</span><b>{review_count}</b></div>
          <div class="stat"><span>Rejected</span><b>{rejected_count}</b></div>
          <div class="stat"><span>Failed</span><b>{failed_count}</b></div>
          <div class="stat"><span>Scenarios</span><b>{len(payload['scenario_stats'])}</b></div>
        </div>
      </section>
      <section class="panel filters">
        <h2>Navigate</h2>
        <input id="search" placeholder="Search recording, candidate, reason">
        {_filters(payload['scenario_stats'])}
      </section>
    </aside>
    <main>
      <section class="panel">
        <h2>Candidate Outcomes By Tag</h2>
        <table>
          <thead><tr><th>tag</th><th>recordings</th><th>candidates</th><th>positive</th><th>negative</th><th>accepted</th><th>review</th><th>rejected</th><th>failed</th></tr></thead>
          <tbody>{_stats_table(payload['scenario_stats'])}</tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Accepted Events</h2>
        <table>
          <thead><tr><th>tag</th><th>recording</th><th>frames</th><th>confidence</th><th>objects</th><th>path</th></tr></thead>
          <tbody>{_event_rows(payload['events'])}</tbody>
        </table>
      </section>
      {candidate_cards or '<section class="panel">No candidates found.</section>'}
    </main>
  </div>
  <script>
    const buttons=[...document.querySelectorAll('button')];
    const cards=[...document.querySelectorAll('.candidate')];
    const search=document.querySelector('#search');
    let scenario='all', status=null;
    function applyFilters(){{
      const term=(search.value||'').trim().toLowerCase();
      cards.forEach(card=>{{
        const scenarioOk=scenario==='all'||card.dataset.scenario===scenario;
        const statusOk=!status||card.dataset.status===status;
        const searchOk=!term||(card.dataset.search||'').includes(term);
        card.classList.toggle('hidden',!(scenarioOk&&statusOk&&searchOk));
      }});
    }}
    buttons.forEach(button=>button.addEventListener('click',()=>{{
      buttons.forEach(item=>item.classList.remove('active'));
      button.classList.add('active');
      scenario=button.dataset.filter||'all';
      status=button.dataset.status||null;
      applyFilters();
    }}));
    search.addEventListener('input',applyFilters);
  </script>
</body>
</html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a standalone Qwen VLM POC review HTML page.")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.run_root / "qwen_review.html"
    candidate_root = args.candidate_root or args.run_root
    payload = build_payload(args.run_root, candidate_root)
    render_html(payload, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
