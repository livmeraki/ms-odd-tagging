"""Plotly explorer for canonical tracks, anchored LD bridges, and static lane ordering."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_plotly_explorer(
    recording: dict[str, Any],
    following: dict[str, Any],
    lane_changes: dict[str, Any],
    path: Path,
    run_id: str,
) -> None:
    try:
        from plotly.offline import get_plotlyjs
        plotly_js = get_plotlyjs()
    except Exception as exc:
        raise RuntimeError("plotly is required") from exc

    source = {f.get("frame_index"): f for f in recording.get("frames", [])}
    store = recording.get("ld_feature_store") or {}
    points = {
        str(p.get("point_id")): p.get("position_lcs_m", [])[:2]
        for p in store.get("points", [])
        if len(p.get("position_lcs_m") or []) >= 2
    }

    raw = []
    for collection, key, kind in (
        ("lane_lines", "line_id", "lane_line"),
        ("road_boundaries", "road_boundary_id", "road_boundary"),
    ):
        for feature in store.get(collection, []):
            ids = list(feature.get("point_ids") or []) or [
                e.get("point_id") for e in feature.get("elements") or []
            ]
            pts = [points[str(pid)] for pid in ids if str(pid) in points]
            if len(pts) >= 2:
                raw.append({"id": str(feature.get(key)), "kind": kind, "pts": pts})

    frames = []
    for frame in following.get("frames", []):
        src = source.get(frame.get("frame_index"), {})
        ego = src.get("ego") or {}
        frames.append(
            {
                **frame,
                "ego_position": ego.get("position_lcs_m"),
                "ego_heading": ego.get("heading_lcs_rad"),
            }
        )

    payload = {
        "run_id": run_id,
        "recording_id": following.get("recording_id"),
        "lanes": following.get("lane_geometry", []),
        "tracks": following.get("continuous_lane_tracks", []),
        "network": following.get("constructed_lane_network", {}),
        "lane_order": following.get("static_lane_order_topology", {}),
        "canonical_track_count": following.get(
            "canonical_continuous_lane_track_count_before_bridge_merge", 0
        ),
        "bridge_count": following.get("anchored_ld_bridge_count", 0),
        "bridge_debug": following.get("anchored_ld_bridge_debug", []),
        "bridge_merge_debug": following.get("anchored_ld_bridge_merge_debug", []),
        "routes": following.get("inferred_ego_routes", []),
        "raw": raw,
        "frames": frames,
    }
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )

    html = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Lane Debug</title>
<script>__PLOTLY_JS__</script>
<style>
body{font:13px system-ui;margin:0;background:#f6f7fb}
header{padding:8px;background:#fff;position:sticky;top:0;z-index:3}
#controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
#plot{height:73vh}
#panel{height:22vh;overflow:auto;white-space:pre-wrap;background:#fff;padding:8px;font-family:monospace}
input[type=range]{width:300px}
</style>
</head>
<body>
<header>
  <b id="title"></b>
  <div id="controls">
    <button id="prev">◀</button>
    <button id="play">▶ Play</button>
    <button id="next">▶</button>
    <button id="center">Center ego</button>
    <input id="frame" type="range" min="0" step="1">
    <span id="label"></span>
    <label><input id="follow" type="checkbox" checked>follow ego</label>
    <label><input id="canonical" type="checkbox" checked>canonical tracks</label>
    <label><input id="bridges" type="checkbox" checked>anchored LD bridges</label>
    <label><input id="selected" type="checkbox" checked>ego/adjacent + inferred route</label>
    <label><input id="order" type="checkbox" checked>lane-order neighbors</label>
    <label><input id="raw" type="checkbox">raw LD lines</label>
    <label><input id="ids" type="checkbox">track IDs</label>
    <label><input id="traj" type="checkbox" checked>ego trajectory</label>
  </div>
</header>
<div id="plot"></div>
<div id="panel"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const slider = document.getElementById('frame');
const plot = document.getElementById('plot');
const playButton = document.getElementById('play');
const laneMap = new Map(D.lanes.map(x => [String(x.lane_id), x]));
const colors = {
  ego: '#22c55e',
  left_adjacent: '#06b6d4',
  right_adjacent: '#f59e0b',
  irrelevant: '#94a3b8',
  bridge: '#7c3aed'
};
let timer = null;
let view = null;
let span = null;
let relayoutBound = false;

slider.max = Math.max(0, D.frames.length - 1);
document.getElementById('title').textContent =
  `${D.recording_id} — static lane order — ${D.run_id}`;

function lineTrace(points, name, color, width=1, dash='solid') {
  return {
    x: (points || []).map(q => q[0]),
    y: (points || []).map(q => q[1]),
    mode: 'lines',
    name,
    line: {color, width, dash},
    showlegend: false,
    hoverinfo: 'name'
  };
}

function polygonTrace(points, name, color, width=1, alpha='08', dash='solid') {
  return {
    ...lineTrace(points, name, color, width, dash),
    fill: 'toself',
    fillcolor: color + alpha
  };
}

function bridgePieces(track) {
  return (track.pieces || []).filter(piece => piece.kind === 'anchored_ld_bridge');
}

function drawBridgePieces(out, track, color=colors.bridge, strong=false) {
  for (const piece of bridgePieces(track)) {
    if ((piece.polygon_lcs_m || []).length) {
      out.push(polygonTrace(
        piece.polygon_lcs_m,
        `anchored bridge · ${track.track_id}`,
        color,
        strong ? 2 : 1,
        strong ? '20' : '0c',
        'dash'
      ));
    }
    if ((piece.centerline_lcs_m || []).length) {
      out.push(lineTrace(
        piece.centerline_lcs_m,
        `anchored bridge centerline · ${track.track_id}`,
        color,
        strong ? 1.8 : 1,
        'dash'
      ));
    }
  }
}

function drawTrack(out, track, role, strong, constructionOnly=false) {
  const color = constructionOnly
    ? colors.irrelevant
    : (colors[role] || colors.irrelevant);

  for (const laneId of track.member_lane_ids || []) {
    const lane = laneMap.get(String(laneId));
    if (!lane) continue;
    out.push(polygonTrace(
      lane.polygon_lcs_m,
      `${constructionOnly ? 'constructed' : role} ${track.track_id} lane ${laneId}`,
      color,
      strong ? 2 : 0.7,
      strong ? '22' : '07'
    ));
    out.push(lineTrace(
      lane.left_boundary_lcs_m,
      `${laneId} left`,
      color,
      strong ? 1.6 : 0.6
    ));
    out.push(lineTrace(
      lane.right_boundary_lcs_m,
      `${laneId} right`,
      color,
      strong ? 1.6 : 0.6
    ));
  }

  if (strong) drawBridgePieces(out, track, color, true);

  if (
    document.getElementById('ids').checked &&
    (track.centerline_lcs_m || []).length
  ) {
    const q = track.centerline_lcs_m[
      Math.floor(track.centerline_lcs_m.length / 2)
    ];
    out.push({
      x: [q[0]],
      y: [q[1]],
      mode: 'text',
      text: [track.track_id],
      showlegend: false
    });
  }
}

function roleMap(frame) {
  return new Map(
    (((frame.lane_roles || {}).roles) || []).map(
      x => [String(x.track_id), x.role]
    )
  );
}

function drawInferredEgoRoute(out, frame) {
  const corridor = frame.inferred_ego_corridor || {};
  const routeId =
    corridor.inferred_ego_route && corridor.inferred_ego_route.route_id;
  if (!routeId) return;

  const route = (D.routes || []).find(x => x.route_id === routeId);
  if (!route) return;

  for (const piece of route.pieces || []) {
    if (piece.frame_index > frame.frame_index) continue;
    if (!(piece.polygon_lcs_m || []).length) continue;

    out.push(polygonTrace(
      piece.polygon_lcs_m,
      `ego inferred route ${routeId} @${piece.frame_index}`,
      colors.ego,
      1.5,
      '18',
      'solid'
    ));
  }
}

function closestPoint(line, origin) {
  let best = null;
  let bestDistance = Infinity;
  for (const q of line || []) {
    const distance = Math.hypot(q[0] - origin[0], q[1] - origin[1]);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = q;
    }
  }
  return best;
}

function drawLaneOrder(out, frame) {
  if (!document.getElementById('order').checked) return;
  const cs = frame.lane_roles && frame.lane_roles.cross_section;
  if (!cs || !cs.point) return;

  out.push({
    x: [cs.point[0]],
    y: [cs.point[1]],
    mode: 'markers',
    marker: {size: 8, color: '#111827'},
    showlegend: false,
    hovertext: 'static lane-order cross-section',
    hoverinfo: 'text'
  });

  for (const side of ['left', 'right']) {
    const candidate = cs[side];
    if (!candidate || !candidate.track_id) continue;

    const track = D.tracks.find(
      x => String(x.track_id) === String(candidate.track_id)
    );
    if (!track || !(track.centerline_lcs_m || []).length) continue;

    const q = closestPoint(track.centerline_lcs_m, cs.point);
    if (!q) continue;

    out.push(lineTrace(
      [cs.point, q],
      `${side} immediate neighbor`,
      side === 'left' ? colors.left_adjacent : colors.right_adjacent,
      2,
      'dot'
    ));
  }
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  playButton.textContent = '▶ Play';
}

function play() {
  if (timer) {
    stop();
    return;
  }

  playButton.textContent = '❚❚ Pause';
  timer = setInterval(() => {
    if (+slider.value >= D.frames.length - 1) {
      stop();
      return;
    }
    slider.value = +slider.value + 1;
    draw();
  }, 100);
}

function draw() {
  const frame = D.frames[+slider.value] || {};
  const ego = frame.ego_position || [0, 0];
  const out = [];
  const roles = roleMap(frame);

  if (document.getElementById('raw').checked) {
    for (const raw of D.raw) {
      out.push(lineTrace(
        raw.pts,
        `${raw.kind} ${raw.id}`,
        '#cbd5e1',
        0.7
      ));
    }
  }

  if (document.getElementById('canonical').checked) {
    for (const track of D.tracks) {
      drawTrack(out, track, 'irrelevant', false, true);
    }
  }

  if (document.getElementById('bridges').checked) {
    for (const track of D.tracks) {
      drawBridgePieces(out, track, colors.bridge, false);
    }
  }

  if (document.getElementById('selected').checked) {
    for (const track of D.tracks) {
      const role = roles.get(String(track.track_id));
      if (role && role !== 'irrelevant') {
        drawTrack(out, track, role, true, false);
      }
    }
    drawInferredEgoRoute(out, frame);
  }

  drawLaneOrder(out, frame);

  if (document.getElementById('traj').checked) {
    out.push(lineTrace(
      D.frames.filter(x => x.ego_position).map(x => x.ego_position),
      'ego trajectory',
      '#111827',
      1.2
    ));
  }

  out.push({
    x: [ego[0]],
    y: [ego[1]],
    mode: 'markers+text',
    text: ['EGO'],
    textposition: 'top center',
    marker: {size: 13, color: colors.ego, symbol: 'triangle-up'},
    showlegend: false
  });

  const follow = document.getElementById('follow').checked;
  const xSpan = span ? span.x : 110;
  const ySpan = span ? span.y : 110;
  const xRange = follow
    ? [ego[0] - xSpan / 2, ego[0] + xSpan / 2]
    : (view ? view.x : [ego[0] - 55, ego[0] + 55]);
  const yRange = follow
    ? [ego[1] - ySpan / 2, ego[1] + ySpan / 2]
    : (view ? view.y : [ego[1] - 55, ego[1] + 55]);

  Plotly.react(
    plot,
    out,
    {
      margin: {l:35, r:10, t:10, b:35},
      xaxis: {scaleanchor:'y', scaleratio:1, range:xRange},
      yaxis: {range:yRange},
      uirevision: 'static-lane-order'
    },
    {responsive:true, displaylogo:false}
  ).then(() => {
    if (!relayoutBound) {
      plot.on('plotly_relayout', event => {
        const x0 = event['xaxis.range[0]'];
        const x1 = event['xaxis.range[1]'];
        const y0 = event['yaxis.range[0]'];
        const y1 = event['yaxis.range[1]'];

        if ([x0, x1, y0, y1].every(Number.isFinite)) {
          view = {x:[x0, x1], y:[y0, y1]};
          span = {x:Math.abs(x1 - x0), y:Math.abs(y1 - y0)};
        }
      });
      relayoutBound = true;
    }
  }).catch(error => {
    console.error('Plotly render failed', error);
    document.getElementById('panel').textContent =
      `Plotly render failed: ${error && error.stack ? error.stack : error}`;
  });

  document.getElementById('label').textContent =
    `frame ${frame.frame_index} · ${Number(frame.time_since_start_s || 0).toFixed(2)}s`;

  document.getElementById('panel').textContent = JSON.stringify({
    ego_lane: frame.ego_lane,
    lane_roles: frame.lane_roles,
    inferred_ego_corridor: frame.inferred_ego_corridor,
    constructed_lane_count: D.network && D.network.lane_count,
    canonical_track_count_before_bridge_merge: D.canonical_track_count,
    anchored_bridge_count: D.bridge_count,
    anchored_bridge_debug: D.bridge_debug,
    anchored_bridge_merge_debug: D.bridge_merge_debug,
    frame_local_adjacency_debug: frame.frame_local_adjacency_debug
  }, null, 2);
}

for (const id of [
  'follow',
  'canonical',
  'bridges',
  'selected',
  'order',
  'raw',
  'ids',
  'traj'
]) {
  document.getElementById(id).onchange = draw;
}

slider.oninput = () => {
  stop();
  draw();
};

document.getElementById('prev').onclick = () => {
  stop();
  slider.value = Math.max(0, +slider.value - 1);
  draw();
};

document.getElementById('next').onclick = () => {
  stop();
  slider.value = Math.min(D.frames.length - 1, +slider.value + 1);
  draw();
};

document.getElementById('center').onclick = () => {
  view = null;
  span = null;
  draw();
};

playButton.onclick = play;
draw();
</script>
</body>
</html>'''

    html = html.replace("__PLOTLY_JS__", plotly_js).replace("__DATA__", data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
