"""Static HTML explorer for Qwen VLM candidate generation quality."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any


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
        return Path(os.path.relpath(path, html_path.parent)).as_posix()
    except ValueError:
        return path.as_uri() if path.is_absolute() else path_string


def _pct(value: int, start: int, end: int) -> float:
    span = max(1, end - start)
    return max(0.0, min(100.0, 100.0 * (value - start) / span))


def _timeline(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") or {}
    start = int(candidate.get("start_frame") or 0)
    end = int(candidate.get("end_frame") or start)
    raw_start = int(metadata.get("raw_trigger_start_frame", start))
    raw_end = int(metadata.get("raw_trigger_end_frame", end))
    raw_left = _pct(raw_start, start, end)
    raw_width = max(0.8, _pct(raw_end, start, end) - raw_left)
    marks = []
    for frame in candidate.get("selected_frame_indices", []):
        if isinstance(frame, int):
            marks.append(
                f'<span class="frame-mark" style="left:{_pct(frame, start, end):.3f}%" '
                f'title="BEV frame {frame}"></span>'
            )
    return (
        '<div class="timeline">'
        f'<div class="raw-trigger" style="left:{raw_left:.3f}%;width:{raw_width:.3f}%" '
        f'title="raw trigger {raw_start}–{raw_end}"></div>'
        + "".join(marks)
        + '</div>'
        f'<div class="timeline-labels"><span>{start}</span><span>raw {raw_start}–{raw_end}</span><span>{end}</span></div>'
    )


def _candidate_card(candidate: dict[str, Any], html_path: Path, ordinal: int) -> str:
    metadata = candidate.get("metadata") or {}
    candidate_id = str(candidate.get("candidate_id") or f"candidate-{ordinal}")
    pedestrians = [str(value) for value in candidate.get("primary_object_ids", [])]
    source_ids = [str(value) for value in metadata.get("source_candidate_ids", [])]
    source_count = int(metadata.get("source_candidate_count") or max(1, len(source_ids)))
    duration = float(candidate.get("end_timestamp_s", 0.0)) - float(candidate.get("start_timestamp_s", 0.0))
    images = []
    for index, (frame, bev_path) in enumerate(
        zip(candidate.get("selected_frame_indices", []), candidate.get("bev_paths", [])), start=1
    ):
        src = html.escape(_relative_uri(str(bev_path), html_path), quote=True)
        images.append(
            '<figure>'
            f'<a href="{src}"><img loading="lazy" src="{src}" alt="candidate BEV frame {frame}"></a>'
            f'<figcaption>#{index} · frame <strong>{html.escape(str(frame))}</strong></figcaption>'
            '</figure>'
        )
    if not images:
        images.append('<div class="missing">No rendered BEVs.</div>')

    source_html = "".join(f"<li>{html.escape(value)}</li>" for value in source_ids) or "<li>-</li>"
    search = " ".join([candidate_id, str(candidate.get("recording_id", "")), *pedestrians, *source_ids]).lower()
    merged = metadata.get("scene_merged") is True
    badge = "MERGED SCENE" if merged else "CANDIDATE"
    return f"""
<section class="candidate" data-search="{html.escape(search)}" data-source-count="{source_count}">
  <header>
    <div><span class="ordinal">#{ordinal}</span> <strong>{html.escape(candidate_id)}</strong></div>
    <span class="badge">{badge}</span>
  </header>
  <div class="summary-grid">
    <div><span class="label">Recording</span><strong>{html.escape(str(candidate.get('recording_id', '-')))}</strong></div>
    <div><span class="label">Context</span><strong>{candidate.get('start_frame')} → {candidate.get('end_frame')}</strong></div>
    <div><span class="label">Duration</span><strong>{duration:.2f} s</strong></div>
    <div><span class="label">Pedestrians</span><strong>{html.escape(', '.join(pedestrians) or '-')}</strong></div>
    <div><span class="label">Merged sources</span><strong>{source_count}</strong></div>
    <div><span class="label">BEVs</span><strong>{len(candidate.get('bev_paths', []))}</strong></div>
  </div>
  <h3>Candidate timeline</h3>
  {_timeline(candidate)}
  <div class="legend"><span><i class="legend-raw"></i>raw trigger</span><span><i class="legend-frame"></i>selected BEV</span></div>
  <h3>Ordered BEV sequence</h3>
  <div class="bevs">{''.join(images)}</div>
  <details>
    <summary>Source candidates ({source_count})</summary>
    <ul>{source_html}</ul>
  </details>
  <details>
    <summary>Candidate metadata</summary>
    <pre>{html.escape(json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False))}</pre>
  </details>
</section>
"""


def build_candidate_explorer(manifest_path: Path, output_path: Path | None = None) -> Path:
    manifest_path = manifest_path.resolve()
    manifest = _read_json(manifest_path)
    output_path = (output_path or manifest_path.with_name(manifest_path.stem + "_candidates.html")).resolve()

    candidates: list[dict[str, Any]] = []
    missing: list[str] = []
    for value in manifest.get("candidate_bundles", []):
        path = Path(str(value))
        if not path.is_absolute():
            path = (manifest_path.parent / path).resolve()
        if path.is_file():
            candidates.append(_candidate_from_bundle(path))
        else:
            missing.append(str(path))

    candidates.sort(
        key=lambda item: (
            str(item.get("recording_id", "")),
            int(item.get("start_frame") or 0),
            int(item.get("end_frame") or 0),
        )
    )
    merged_count = sum(1 for item in candidates if (item.get("metadata") or {}).get("scene_merged") is True)
    total_sources = sum(int((item.get("metadata") or {}).get("source_candidate_count") or 1) for item in candidates)
    recording_count = len({str(item.get("recording_id")) for item in candidates})
    cards = "".join(_candidate_card(item, output_path, index) for index, item in enumerate(candidates, start=1))
    warning = ""
    if missing:
        warning = '<div class="warning">Missing candidate bundles:<pre>' + html.escape("\n".join(missing)) + "</pre></div>"

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Candidate Explorer</title>
<style>
:root{{--bg:#111;--panel:#181818;--panel2:#0d0d0d;--text:#eee;--muted:#999;--border:#343434;--accent:#4f8cff;--raw:#db8b24}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1600px;margin:auto;padding:22px}} h1{{margin:0 0 4px}} h3{{margin:18px 0 8px}} .muted{{color:var(--muted)}}
.metrics{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}} .metric{{border:1px solid var(--border);background:var(--panel);padding:9px 13px;border-radius:9px}} .metric strong{{font-size:18px;margin-left:5px}}
.toolbar{{position:sticky;top:0;z-index:4;background:#111e;backdrop-filter:blur(8px);padding:10px 0}} input,select{{background:#222;color:var(--text);border:1px solid #555;border-radius:8px;padding:8px 10px;margin-right:8px}}
.candidate{{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:15px;margin:18px 0}} .candidate header{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
.badge{{font-size:11px;font-weight:700;border-radius:999px;padding:4px 8px;background:#243754}} .ordinal{{color:var(--muted);margin-right:6px}}
.summary-grid{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:14px 0}} .summary-grid>div{{background:var(--panel2);border:1px solid #2a2a2a;border-radius:8px;padding:8px;min-width:0}} .label{{display:block;color:var(--muted);font-size:12px;margin-bottom:3px}} .summary-grid strong{{overflow-wrap:anywhere}}
.timeline{{height:34px;position:relative;border:1px solid var(--border);border-radius:8px;background:#0b0b0b;overflow:hidden}} .raw-trigger{{position:absolute;top:8px;height:16px;background:var(--raw);opacity:.55;border-radius:5px}} .frame-mark{{position:absolute;top:3px;width:3px;height:28px;background:var(--accent);transform:translateX(-1px)}}
.timeline-labels{{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-top:4px}} .legend{{display:flex;gap:16px;color:var(--muted);font-size:12px;margin-top:5px}} .legend i{{display:inline-block;width:14px;height:8px;margin-right:5px}} .legend-raw{{background:var(--raw)}} .legend-frame{{background:var(--accent)}}
.bevs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}} figure{{margin:0;background:var(--panel2);border:1px solid var(--border);border-radius:9px;overflow:hidden}} figure img{{width:100%;display:block}} figcaption{{padding:7px 9px}} a{{color:inherit}}
details{{margin-top:10px}} summary{{cursor:pointer;font-weight:600}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel2);padding:10px;border-radius:8px;max-height:360px;overflow:auto}} .warning{{background:#493719;border-radius:8px;padding:10px}} .missing{{padding:30px;color:var(--muted)}} .hidden{{display:none!important}}
@media(max-width:1000px){{.summary-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}}} @media(max-width:620px){{.summary-grid{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body><main>
<h1>Candidate Explorer</h1>
<div class="muted">{html.escape(str(manifest_path))}</div>
<div class="muted">Scenario: {html.escape(str((candidates[0].get('scenario') if candidates else '-')))} · strategy: {html.escape(str(manifest.get('candidate_strategy', '-')))}</div>
<div class="metrics">
  <div class="metric">Scenes <strong>{len(candidates)}</strong></div>
  <div class="metric">Merged scenes <strong>{merged_count}</strong></div>
  <div class="metric">Source candidates <strong>{total_sources}</strong></div>
  <div class="metric">Recordings <strong>{recording_count}</strong></div>
</div>
<div class="toolbar">
  <input id="search" placeholder="Search recording / pedestrian / candidate">
  <select id="mergeFilter"><option value="all">All scenes</option><option value="multi">Merged from 2+</option><option value="single">Single-source scenes</option></select>
</div>
{warning}
{cards or '<div class="warning">No candidate bundles found.</div>'}
</main>
<script>
const search=document.querySelector('#search');
const mergeFilter=document.querySelector('#mergeFilter');
const cards=[...document.querySelectorAll('.candidate')];
function apply(){{
  const term=(search.value||'').trim().toLowerCase();
  const mode=mergeFilter.value;
  cards.forEach(card=>{{
    const count=Number(card.dataset.sourceCount||1);
    const searchOk=!term||(card.dataset.search||'').includes(term);
    const mergeOk=mode==='all'||(mode==='multi'&&count>=2)||(mode==='single'&&count===1);
    card.classList.toggle('hidden',!(searchOk&&mergeOk));
  }});
}}
search.addEventListener('input',apply); mergeFilter.addEventListener('change',apply);
</script>
</body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a candidate-only HTML explorer from a Qwen manifest.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = build_candidate_explorer(args.manifest, args.output)
    print(f"Candidate explorer: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
