"""Final explorer wrapper: highlight inferred pieces as part of selected tracks."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .explorer_visualization import render_plotly_explorer as _render_base


_OLD_DRAW_TRACK = """function drawTrack(out,t,role,strong,constructionOnly=false){const color=constructionOnly?colors.irrelevant:roleColor(role);for(const id of t.member_lane_ids||[]){const lane=laneMap.get(String(id));if(!lane)continue;const hover=`${constructionOnly?'constructed':role} ${t.track_id} lane ${id} · ${laneRangeHover(id)}`;out.push(polygonTrace(lane.polygon_lcs_m,hover,color,strong?2:0.7,strong?'22':'07'));}drawFillPieces(out,t,color,strong);if(strong)drawAnchored(out,t,color,true);}"""

_NEW_DRAW_TRACK = """function drawTrack(out,t,role,strong,constructionOnly=false){const color=constructionOnly?colors.irrelevant:roleColor(role);for(const id of t.member_lane_ids||[]){const lane=laneMap.get(String(id));if(!lane)continue;const hover=`${constructionOnly?'constructed':role} ${t.track_id} lane ${id} · ${laneRangeHover(id)}`;out.push(polygonTrace(lane.polygon_lcs_m,hover,color,strong?2:0.7,strong?'22':'07'));}drawFillPieces(out,t,color,strong);if(strong){for(const p of t.pieces||[]){if(p.kind!=='static_inferred_corridor'&&p.kind!=='static_inferred_connector'&&p.kind!=='ego_supported_inferred_route')continue;const name=`${role} integrated ${p.kind} · ${t.track_id}`;if((p.polygon_lcs_m||[]).length)out.push(polygonTrace(p.polygon_lcs_m,name,color,2,'22','solid'));if((p.centerline_lcs_m||[]).length)out.push(lineTrace(p.centerline_lcs_m,`${name} centerline`,color,2,'solid'));}drawAnchored(out,t,color,true);}}"""


def render_plotly_explorer(
    recording: dict[str, Any],
    following: dict[str, Any],
    lane_changes: dict[str, Any],
    path: Path,
    run_id: str,
) -> None:
    """Render the base explorer, then make inferred pieces part of track highlight."""
    _render_base(recording, following, lane_changes, path, run_id)
    html = path.read_text(encoding="utf-8")
    if _OLD_DRAW_TRACK not in html:
        raise RuntimeError("lane-debug explorer drawTrack signature changed; integrated highlight patch not applied")
    html = html.replace(_OLD_DRAW_TRACK, _NEW_DRAW_TRACK, 1)
    path.write_text(html, encoding="utf-8")
