"""Inject following-lane debugging into the established OD+LD explorer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRACKER_CSS = """
  .laneTrackerSection { margin-top: 14px; padding-top: 10px; border-top: 1px solid #edf1f5; }
  .laneTrackerSection h3 { margin: 0 0 6px; font-size: 15px; }
  .laneTrackerReadout { margin-top: 8px; padding: 8px; border-radius: 6px; background: #ecfdf5; color: #14532d; font-size: 12px; line-height: 1.5; }
  .laneTrackerLegend { display: flex; flex-wrap: wrap; gap: 5px 10px; margin-top: 8px; color: #475569; font-size: 11px; }
  .laneTrackerLegend span::before { content: ""; display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 2px; background: var(--lane-color); }
"""


TRACKER_CONTROLS = """
    <div class="laneTrackerSection">
      <h3>Generated Lane Tracker</h3>
      <label><input id="showLaneTracker" type="checkbox" checked /> Show active ego lane area</label>
      <label><input id="showLaneTrackerAdjacent" type="checkbox" checked /> Show left / right lane areas</label>
      <label><input id="showLaneTrackerRoutes" type="checkbox" /> Show logical route continuity</label>
      <label><input id="showLaneTrackerBridges" type="checkbox" checked /> Show probable gap extensions</label>
      <label><input id="showLaneTrackerCenterlines" type="checkbox" /> Show tracked centerlines</label>
      <label><input id="showLaneTrackerLead" type="checkbox" checked /> Highlight selected lead</label>
      <label><input id="showLdGapExtensions" type="checkbox" checked /> Show experimental LD line gap extensions</label>
      <div class="laneTrackerLegend">
        <span style="--lane-color:#06b6d4">left</span>
        <span style="--lane-color:#22c55e">ego</span>
        <span style="--lane-color:#15803d">ego logical route</span>
        <span style="--lane-color:#f59e0b">right</span>
        <span style="--lane-color:#ef4444">lead</span>
      </div>
      <div id="laneTrackerReadout" class="laneTrackerReadout"></div>
      <div id="ldGapExtensionReadout" class="laneTrackerReadout"></div>
      <div class="note">Generated lane roles, gap extensions, and lead selection use the same frame as the original explorer. Lane identifiers remain internal and are not drawn.</div>
      <div class="note">Experimental LD gap extensions are visualization-only. They connect aligned dashed-to-dashed and solid-to-dashed line endpoints; they do not affect lane assignment or scenario tags.</div>
    </div>
"""


TRACKER_SCRIPT = r"""
const TRACKER_COLORS = {
  left: '#06b6d4',
  ego: '#22c55e',
  right: '#f59e0b',
  lead: '#ef4444',
  gap: '#0f766e',
  unknown: '#a855f7',
  inactive: '#94a3b8'
};

const LD_GAP_MAX_DISTANCE_M = 12.0;
const LD_GAP_MAX_HEADING_DIFFERENCE_DEG = 30.0;
const LD_GAP_DASHED_PATTERNS = new Set(['dashed', 'broken', 'virtual', 'zigzag']);

function normalizedVector(x, y) {
  const length = Math.hypot(x, y);
  return length > 1e-6 ? [x / length, y / length] : null;
}

function clampUnit(value) {
  return Math.max(-1, Math.min(1, value));
}

function ldLineEndpoints(feature) {
  if (!Array.isArray(feature.x) || !Array.isArray(feature.y) ||
      feature.x.length < 2 || feature.x.length !== feature.y.length) return [];
  const last = feature.x.length - 1;
  const startOutward = normalizedVector(
    feature.x[0] - feature.x[1],
    feature.y[0] - feature.y[1]
  );
  const endOutward = normalizedVector(
    feature.x[last] - feature.x[last - 1],
    feature.y[last] - feature.y[last - 1]
  );
  const endpoints = [];
  if (startOutward) endpoints.push({
    key: `${feature.id}:start`, feature,
    point: [feature.x[0], feature.y[0]], outward: startOutward
  });
  if (endOutward) endpoints.push({
    key: `${feature.id}:end`, feature,
    point: [feature.x[last], feature.y[last]], outward: endOutward
  });
  return endpoints;
}

function buildLdGapExtensions() {
  const started = performance.now();
  const endpoints = ld.laneLines.flatMap(ldLineEndpoints);
  const candidates = [];
  const approachMinimum = Math.cos(35 * Math.PI / 180);
  for (let aIndex = 0; aIndex < endpoints.length; aIndex++) {
    const a = endpoints[aIndex];
    for (let bIndex = aIndex + 1; bIndex < endpoints.length; bIndex++) {
      const b = endpoints[bIndex];
      if (a.feature.id === b.feature.id) continue;
      const aDashed = LD_GAP_DASHED_PATTERNS.has(a.feature.pattern);
      const bDashed = LD_GAP_DASHED_PATTERNS.has(b.feature.pattern);
      if (!aDashed && !bDashed) continue;
      if (a.feature.color && b.feature.color && a.feature.color !== b.feature.color) continue;
      const dx = b.point[0] - a.point[0];
      const dy = b.point[1] - a.point[1];
      const distance = Math.hypot(dx, dy);
      if (distance < 0.3 || distance > LD_GAP_MAX_DISTANCE_M) continue;
      const direction = [dx / distance, dy / distance];
      const aApproach = a.outward[0] * direction[0] + a.outward[1] * direction[1];
      const bApproach = -(b.outward[0] * direction[0] + b.outward[1] * direction[1]);
      if (aApproach < approachMinimum || bApproach < approachMinimum) continue;
      const oppositeDot = -(a.outward[0] * b.outward[0] + a.outward[1] * b.outward[1]);
      const headingDifferenceDeg = Math.acos(clampUnit(oppositeDot)) * 180 / Math.PI;
      if (headingDifferenceDeg > LD_GAP_MAX_HEADING_DIFFERENCE_DEG) continue;
      candidates.push({
        a, b, distance, headingDifferenceDeg,
        kind: aDashed && bDashed ? 'dashed-to-dashed' : 'solid-to-dashed',
        score: distance + headingDifferenceDeg * 0.08
      });
    }
  }
  candidates.sort((a, b) => a.score - b.score);
  const usedEndpoints = new Set();
  const connections = [];
  for (const candidate of candidates) {
    if (usedEndpoints.has(candidate.a.key) || usedEndpoints.has(candidate.b.key)) continue;
    usedEndpoints.add(candidate.a.key);
    usedEndpoints.add(candidate.b.key);
    connections.push(candidate);
  }
  return {
    connections,
    endpointCount: endpoints.length,
    candidateCount: candidates.length,
    buildMilliseconds: performance.now() - started
  };
}

const LD_GAP_EXTENSION_RESULT = buildLdGapExtensions();

function ldGapExtensionTraces() {
  if (!document.getElementById('showLdGapExtensions').checked ||
      !LD_GAP_EXTENSION_RESULT.connections.length) return [];
  const x = [], y = [], customdata = [];
  for (const connection of LD_GAP_EXTENSION_RESULT.connections) {
    x.push(connection.a.point[0], connection.b.point[0], null);
    y.push(connection.a.point[1], connection.b.point[1], null);
    const detail = [
      connection.kind,
      connection.distance,
      connection.headingDifferenceDeg,
      `${connection.a.feature.pattern || 'unknown'} → ${connection.b.feature.pattern || 'unknown'}`
    ];
    customdata.push(detail, detail, detail);
  }
  return [{
    type: 'scattergl', mode: 'lines', name: 'experimental LD gap extension',
    x, y, customdata,
    line: {color: TRACKER_COLORS.gap, width: 3, dash: 'dash'},
    hovertemplate: '%{customdata[0]}<br>gap=%{customdata[1]:.2f} m<br>heading difference=%{customdata[2]:.1f}°<br>%{customdata[3]}<extra></extra>'
  }];
}

function updateLdGapExtensionReadout() {
  const result = LD_GAP_EXTENSION_RESULT;
  const dashed = result.connections.filter(item => item.kind === 'dashed-to-dashed').length;
  const mixed = result.connections.length - dashed;
  document.getElementById('ldGapExtensionReadout').innerHTML =
    `<b>Experimental LD gap overlay</b><br>` +
    `${result.connections.length} accepted connections ` +
    `(${dashed} dashed-to-dashed, ${mixed} solid-to-dashed)<br>` +
    `${result.endpointCount} endpoints · ${result.candidateCount} aligned candidates · ` +
    `${result.buildMilliseconds.toFixed(1)} ms initial build`;
}

function trackerFrame() {
  return LANE_TRACKER.frames[currentIndex] || null;
}

function trackerRoleDefinitions(frame) {
  if (!frame) return [];
  const roles = [['ego', frame.ego_lane]];
  if (document.getElementById('showLaneTrackerAdjacent').checked) {
    roles.unshift(['left', frame.left_lane]);
    roles.push(['right', frame.right_lane]);
  }
  return roles.filter(([, assignment]) => assignment && assignment.lane_id);
}

function trackerPhysicalPolygonTrace(role, assignment) {
  const x = [], y = [];
  for (const lane of LANE_TRACKER.lanes) {
    if (lane.lane_id !== assignment.lane_id ||
        !Array.isArray(lane.polygon_lcs_m) || lane.polygon_lcs_m.length < 3) continue;
    for (const point of lane.polygon_lcs_m) {
      x.push(point[0]); y.push(point[1]);
    }
    x.push(lane.polygon_lcs_m[0][0], null);
    y.push(lane.polygon_lcs_m[0][1], null);
  }
  if (!x.length) return null;
  return {
    type: 'scatter', mode: 'lines', name: `${role} tracked lane`,
    x, y,
    fill: 'toself',
    fillcolor: TRACKER_COLORS[role] + '24',
    line: {color: TRACKER_COLORS[role], width: role === 'ego' ? 5 : 3},
    hovertemplate: `${role} active physical lane<br>physical=${assignment.lane_id || 'none'}<br>logical=${assignment.logical_lane_id || 'none'}<br>confidence=${assignment.confidence || 'unknown'}<br>method=${assignment.method || 'unknown'}<extra></extra>`
  };
}

function trackerPhysicalCenterlineTrace(role, assignment) {
  const x = [], y = [];
  for (const lane of LANE_TRACKER.lanes) {
    if (lane.lane_id !== assignment.lane_id ||
        !Array.isArray(lane.centerline_lcs_m) || lane.centerline_lcs_m.length < 2) continue;
    for (const point of lane.centerline_lcs_m) {
      x.push(point[0]); y.push(point[1]);
    }
    x.push(null); y.push(null);
  }
  if (!x.length) return null;
  return {
    type: 'scattergl', mode: 'lines', name: `${role} tracked centerline`,
    x, y,
    line: {color: TRACKER_COLORS[role], width: 2, dash: 'dot'},
    hoverinfo: 'skip'
  };
}

function trackerCurvatureContinuationTraces(role, assignment) {
  if (!assignment || !assignment.lane_id) return [];
  const traces = [];
  for (const lane of LANE_TRACKER.lanes) {
    if (lane.lane_id !== assignment.lane_id ||
        !Array.isArray(lane.curvature_continuations)) continue;
    for (const continuation of lane.curvature_continuations) {
      if (!continuation || !continuation.destination_lane_id) continue;
      const gap = continuation.inferred_gap_polygon_lcs_m || [];
      if (gap.length >= 3) {
        const x = [], y = [];
        for (const point of gap) {
          x.push(point[0]); y.push(point[1]);
        }
        x.push(gap[0][0], null);
        y.push(gap[0][1], null);
        traces.push({
          type: 'scatter', mode: 'lines',
          name: `${role} inferred continuation gap`,
          x, y,
          fill: 'toself',
          fillcolor: TRACKER_COLORS[role] + '12',
          line: {color: '#84cc16', width: 3, dash: 'dash'},
          hovertemplate:
            `${role} inferred continuation gap<br>` +
            `source=${continuation.source_lane_id || assignment.lane_id}<br>` +
            `destination=${continuation.destination_lane_id || 'none'}<br>` +
            `bridged=${continuation.bridged_distance_m || 'n/a'} m<br>` +
            `${continuation.method || 'curvature continuation'}<extra></extra>`
        });
      }
      const observed = continuation.observed_destination_polygon_lcs_m || [];
      if (observed.length >= 3) {
        const x = [], y = [];
        for (const point of observed) {
          x.push(point[0]); y.push(point[1]);
        }
        x.push(observed[0][0], null);
        y.push(observed[0][1], null);
        traces.push({
          type: 'scatter', mode: 'lines',
          name: `${role} observed downstream continuation`,
          x, y,
          fill: 'toself',
          fillcolor: TRACKER_COLORS[role] + '16',
          line: {color: '#65a30d', width: 3, dash: 'dot'},
          hovertemplate:
            `${role} observed downstream continuation<br>` +
            `source=${continuation.source_lane_id || assignment.lane_id}<br>` +
            `destination=${continuation.destination_lane_id || 'none'}<br>` +
            `confidence=${continuation.confidence || 'reduced'}<extra></extra>`
        });
      }
      const projected = continuation.projected_centerline_lcs_m || [];
      if (projected.length >= 2) {
        traces.push({
          type: 'scattergl', mode: 'lines',
          name: `${role} projected continuation path`,
          x: projected.map(point => point[0]),
          y: projected.map(point => point[1]),
          line: {color: '#bef264', width: 2, dash: 'dashdot'},
          hoverinfo: 'skip'
        });
      }
    }
  }
  return traces;
}

function trackerEgoRouteTrace(assignment) {
  if (!assignment || !assignment.logical_lane_id) return null;
  const x = [], y = [];
  for (const lane of LANE_TRACKER.lanes) {
    if (lane.logical_lane_id !== assignment.logical_lane_id ||
        lane.lane_id === assignment.lane_id ||
        !Array.isArray(lane.polygon_lcs_m) || lane.polygon_lcs_m.length < 3) continue;
    for (const point of lane.polygon_lcs_m) {
      x.push(point[0]); y.push(point[1]);
    }
    x.push(lane.polygon_lcs_m[0][0], null);
    y.push(lane.polygon_lcs_m[0][1], null);
  }
  if (!x.length) return null;
  return {
    type: 'scatter', mode: 'lines', name: 'ego logical route context',
    x, y,
    fill: 'toself',
    fillcolor: TRACKER_COLORS.ego + '08',
    line: {color: '#15803d', width: 1.5, dash: 'dot'},
    hovertemplate: `ego logical route context<br>logical=${assignment.logical_lane_id || 'none'}<br>active physical lane=${assignment.lane_id || 'none'}<extra></extra>`
  };
}

function trackerBridgeTrace(assignment) {
  if (!assignment || !assignment.logical_lane_id) return null;
  const x = [], y = [];
  for (const bridge of LANE_TRACKER.bridges) {
    if (bridge.logical_lane_id !== assignment.logical_lane_id ||
        !Array.isArray(bridge.polygon_lcs_m) || bridge.polygon_lcs_m.length < 3) continue;
    for (const point of bridge.polygon_lcs_m) {
      x.push(point[0]); y.push(point[1]);
    }
    x.push(bridge.polygon_lcs_m[0][0], null);
    y.push(bridge.polygon_lcs_m[0][1], null);
  }
  if (!x.length) return null;
  return {
    type: 'scatter', mode: 'lines', name: 'ego logical route extension',
    x, y,
    fill: 'toself',
    fillcolor: TRACKER_COLORS.ego + '10',
    line: {color: '#15803d', width: 2, dash: 'dash'},
    hovertemplate: `ego logical route probable gap extension<br>logical=${assignment.logical_lane_id || 'none'}<extra></extra>`
  };
}

function laneTrackerTraces() {
  const frame = trackerFrame();
  if (!frame) return [];
  const traces = [];
  if (document.getElementById('showLaneTracker').checked) {
    for (const [role, assignment] of trackerRoleDefinitions(frame)) {
      const polygon = trackerPhysicalPolygonTrace(role, assignment);
      if (polygon) traces.push(polygon);
      for (const continuation of trackerCurvatureContinuationTraces(role, assignment)) {
        traces.push(continuation);
      }
      if (document.getElementById('showLaneTrackerCenterlines').checked) {
        const centerline = trackerPhysicalCenterlineTrace(role, assignment);
        if (centerline) traces.push(centerline);
      }
    }
  }
  if (document.getElementById('showLaneTrackerRoutes').checked) {
    const route = trackerEgoRouteTrace(frame.ego_lane);
    if (route) traces.push(route);
    if (document.getElementById('showLaneTrackerBridges').checked) {
      const bridge = trackerBridgeTrace(frame.ego_lane);
      if (bridge) traces.push(bridge);
    }
  }
  if (document.getElementById('showLaneTrackerLead').checked &&
      frame.lead && Array.isArray(frame.lead.position_lcs_m)) {
    traces.push({
      type: 'scatter', mode: 'markers', name: 'lane-tracker selected lead',
      x: [frame.lead.position_lcs_m[0]], y: [frame.lead.position_lcs_m[1]],
      marker: {
        size: 17, color: 'rgba(0,0,0,0)',
        line: {color: TRACKER_COLORS.lead, width: 4},
        symbol: 'circle'
      },
      hovertemplate: `selected lead #${frame.lead.object_id}<br>${frame.lead.class}<br>${frame.lead.longitudinal_m.toFixed(1)} m ahead<br>${frame.lead.ego_lane_area_source || 'unknown lane area'}<extra></extra>`
    });
  }
  return traces;
}

function laneRoleSummary(role, assignment) {
  if (!assignment || !assignment.logical_lane_id) {
    if (assignment && assignment.method === 'direction_mismatch_rejected') {
      const difference = Number.isFinite(assignment.heading_difference_deg)
        ? `, heading difference ${assignment.heading_difference_deg.toFixed(1)}°`
        : '';
      return `${role}: rejected ${assignment.direction_relation.replaceAll('_', ' ')} candidate${difference}`;
    }
    return `${role}: unavailable`;
  }
  const direction = role !== 'ego' && assignment.same_direction_as_ego === true
    ? `, same direction${Number.isFinite(assignment.heading_difference_deg) ? ` (${assignment.heading_difference_deg.toFixed(1)}°)` : ''}`
    : '';
  return `${role}: ${assignment.confidence || 'unknown'} / ${assignment.method || 'unknown'}${direction}`;
}

function laneContinuationSummary(assignment) {
  if (!assignment || !assignment.lane_id) return 'continuation: none';
  const lane = LANE_TRACKER.lanes.find(item => item.lane_id === assignment.lane_id);
  const continuations = lane && Array.isArray(lane.curvature_continuations)
    ? lane.curvature_continuations.filter(item => item.destination_lane_id)
    : [];
  if (!continuations.length) return 'continuation: none';
  const first = continuations[0];
  return `continuation: ${first.source_lane_id || assignment.lane_id} → ${first.destination_lane_id} · ` +
    `${first.bridged_distance_m || 'n/a'} m inferred gap · ${first.confidence || 'reduced confidence'}`;
}

function updateLaneTrackerReadout() {
  const frame = trackerFrame();
  const target = document.getElementById('laneTrackerReadout');
  if (!frame) {
    target.textContent = 'No generated lane-tracker result for this frame.';
    return;
  }
  const lead = frame.lead
    ? `lead #${frame.lead.object_id} at ${frame.lead.longitudinal_m.toFixed(1)} m (${frame.lead.tracking_status || 'observed'})`
    : 'no stable lead';
  target.innerHTML =
    `<b>${frame.state.replaceAll('_', ' ')}</b><br>` +
    `${laneRoleSummary('left', frame.left_lane)}<br>` +
    `${laneRoleSummary('ego', frame.ego_lane)}<br>` +
    `${laneRoleSummary('right', frame.right_lane)}<br>` +
    `active ego physical: ${frame.ego_lane?.lane_id || 'none'} · ego logical route: ${frame.ego_lane?.logical_lane_id || 'none'}<br>` +
    `${laneContinuationSummary(frame.ego_lane)}<br>` +
    `${lead}<br>${frame.reason.replaceAll('_', ' ')}`;
}
"""


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(
            f"Unable to inject {label}: expected one marker, found {count}"
        )
    return text.replace(old, new, 1)


def _insert_tracker_controls(page: str) -> str:
    class_filter_marker = '    <label for="classFilter">Object classes</label>'
    if class_filter_marker in page:
        return _replace_once(
            page,
            class_filter_marker,
            TRACKER_CONTROLS + "\n" + class_filter_marker,
            "lane-tracker controls",
        )
    return _replace_once(
        page,
        "    <div id=\"animControls\">",
        TRACKER_CONTROLS + "\n    <div id=\"animControls\">",
        "lane-tracker controls",
    )


def _compact_payload(result: dict[str, Any]) -> dict[str, Any]:
    frames = []
    for frame in result["frames"]:
        frames.append(
            {
                "frame_index": frame["frame_index"],
                "time_since_start_s": frame["time_since_start_s"],
                "state": frame["state"],
                "reason": frame["reason"],
                "ego_lane": frame["ego_lane"],
                "left_lane": frame["left_lane"],
                "right_lane": frame["right_lane"],
                "lead": frame["lead"],
            }
        )
    return {
        "recording_id": result["recording_id"],
        "lanes": result["lane_geometry"],
        "bridges": result.get("probable_lane_bridges", []),
        "frames": frames,
        "intervals": result["intervals"],
    }


def render_original_explorer_with_lane_tracker(
    base_explorer_path: Path,
    result: dict[str, Any],
    output_path: Path,
) -> None:
    """Copy the original explorer and add synchronized lane-tracker debugging."""
    page = base_explorer_path.read_text(encoding="utf-8")
    page = page.replace(
        '<input id="followEgo" type="checkbox" />',
        '<input id="followEgo" type="checkbox" checked />',
    )
    page = page.replace(
        '<input id="showNearbyLd" type="checkbox" checked />',
        '<input id="showNearbyLd" type="checkbox" />',
    )
    page = page.replace(
        "'LD line: intersection=true', '#d946ef', 'solid', 4.2, 0.82",
        "'LD line: intersection=true', '#d946ef', 'solid', 2.0, 0.82",
    )
    original_output_dir_uri = base_explorer_path.parent.resolve().as_uri()
    original_index_uri = (
        base_explorer_path.parent.parent / "dataset_odld_explorer_index.html"
    ).resolve().as_uri()
    payload_json = json.dumps(
        _compact_payload(result),
        ensure_ascii=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    page = page.replace(
        'href="../dataset_odld_explorer_index.html"',
        f'href="{original_index_uri}"',
    )
    page = page.replace(
        "const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;",
        "const DEBUG_BASE = "
        f"`{original_output_dir_uri}/debug/"
        "${encodeURIComponent(DATA.summary.recording)}`;",
    )
    page = _replace_once(
        page,
        "</style>",
        TRACKER_CSS + "\n</style>",
        "lane-tracker styles",
    )
    page = _insert_tracker_controls(page)
    page = _replace_once(
        page,
        "const DATA = ",
        f"const LANE_TRACKER = {payload_json};\nconst DATA = ",
        "lane-tracker payload",
    )
    page = _replace_once(
        page,
        "function render() {",
        TRACKER_SCRIPT + "\nfunction render() {",
        "lane-tracker functions",
    )
    page = _replace_once(
        page,
        "  traces.unshift(...ldTraces());",
        "  traces.unshift(...ldTraces());\n"
        "  traces.unshift(...ldGapExtensionTraces());\n"
        "  traces.unshift(...laneTrackerTraces());\n"
        "  updateLaneTrackerReadout();\n"
        "  updateLdGapExtensionReadout();",
        "lane-tracker map traces",
    )
    page = _replace_once(
        page,
        "filter.addEventListener('change', render);",
        "for (const id of ['showLaneTracker','showLaneTrackerAdjacent','showLaneTrackerBridges',"
        "'showLaneTrackerRoutes','showLaneTrackerCenterlines','showLaneTrackerLead',"
        "'showLdGapExtensions']) "
        "document.getElementById(id).addEventListener('change', render);\n"
        "filter.addEventListener('change', render);",
        "lane-tracker control listeners",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
