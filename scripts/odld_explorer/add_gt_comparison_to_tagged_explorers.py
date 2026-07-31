#!/usr/bin/env python3
"""Duplicate tagged ODLD explorers and add synchronized GT comparison plots."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from ms_odd_tagging.common.config import DATA_GT, GT_COMPARISON, OUTPUT_ROOT
from ms_odd_tagging.gt_comparison.authoring import build_review_payload

DEFAULT_SOURCE_DIR = OUTPUT_ROOT / "scenarios" / "following_lane_tagged" / "04_visualization"
DEFAULT_OUTPUT_DIR = OUTPUT_ROOT / "07_odld_scenario_explorers_gt_comparison"
DEFAULT_DETAILS = GT_COMPARISON / "rule_based_gt_details.csv"
DEFAULT_SUMMARY = GT_COMPARISON / "rule_based_gt_summary.json"
DEFAULT_GT_DIR = DATA_GT


GT_STYLE = """
  .gtComparisonHeader { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
  .gtComparisonHeader h2 { margin:0 auto 0 0; font-size:17px; }
  .gtMetrics { display:flex; gap:7px; flex-wrap:wrap; }
  .gtMetric { padding:4px 8px; border-radius:999px; background:#eef2ff; color:#312e81; font-size:12px; font-weight:700; }
  .gtWarning { background:#fff7ed; color:#9a3412; }
  #gtComparisonTimeline { min-height:650px; }
  #gtComparisonReadout { margin-top:8px; padding:8px; border-radius:6px; background:#f8fafc; color:#334155; font-size:12px; line-height:1.45; }
"""

GT_AUTHORING_STYLE = """
  .gtRemovedLaneTrackerTimeline { display:none; }
  #gtAuthoringPanel { display:block; }
  #gtAuthoringPanel > summary { cursor:pointer; font-size:17px; font-weight:700; padding:2px 0 8px; }
  .gtAuthoringWorkspace { display:grid; grid-template-columns:minmax(0,1.55fr) minmax(340px,.9fr); gap:12px; align-items:start; }
  .gtAuthoringWorkspace > .panel { min-width:0; }
  .gtAuthoringWorkspace #gtAuthoringPanel[open] { max-height:608px; overflow:auto; }
  .gtAuthoringBody { display:grid; gap:10px; }
  .gtAuthoringHeader { display:grid; gap:7px; }
  .gtAuthoringCommandRow { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }
  .gtAuthoringFileRow { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; }
  .gtAuthoringHeader label { display:grid; gap:4px; font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; }
  .gtAuthoringHeader select, .gtAuthoringHeader input { width:auto; height:30px; min-width:150px; border:1px solid #cbd5e1; border-radius:5px; padding:0 7px; background:white; color:#172033; }
  .gtAuthoringHeader button, .gtAuthoringActions button { width:auto; min-height:32px; height:auto; border:1px solid #94a3b8; border-radius:5px; background:white; color:#334155; padding:6px 9px; cursor:pointer; }
  .gtAuthoringCommandRow button, .gtAuthoringFileRow button { width:100%; margin:0; }
  .gtAuthoringHeader button.primary, .gtAuthoringActions button.primary { background:#2458c6; border-color:#2458c6; color:white; }
  .gtAuthoringHeader button:disabled, .gtAuthoringActions button:disabled, .gtTri button:disabled { opacity:.45; cursor:not-allowed; }
  #gtAuthoringImport { display:none; }
  #gtAuthoringStatus { color:#475569; font-size:12px; line-height:1.45; }
  #gtAuthoringExclusion { color:#b42318; font-weight:700; font-size:12px; }
  .gtScenarioPicker { position:relative; width:100%; }
  .gtScenarioPicker > summary { cursor:pointer; min-height:32px; width:100%; box-sizing:border-box; border:1px solid #94a3b8; border-radius:5px; padding:7px 9px; background:white; color:#334155; list-style:none; }
  .gtScenarioPickerMenu { position:absolute; z-index:12; left:0; right:0; min-width:330px; max-height:320px; overflow:auto; padding:9px; border:1px solid #94a3b8; border-radius:6px; background:white; box-shadow:0 8px 24px rgba(15,23,42,.16); }
  .gtScenarioPickerActions { display:flex; gap:6px; margin-bottom:8px; }
  .gtScenarioChoices { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:5px 10px; }
  .gtScenarioChoice { display:flex !important; align-items:center; gap:6px !important; font-size:12px !important; color:#334155 !important; text-transform:none !important; font-weight:500 !important; }
  .gtScenarioChoice input { width:14px; height:14px; min-width:0; }
  .gtAuthoringLabels { max-height:430px; overflow:auto; border-top:1px solid #e2e8f0; padding-top:4px; }
  .gtAuthoringGroup { border-bottom:1px solid #e2e8f0; padding:7px 0; }
  .gtAuthoringGroup > summary { cursor:pointer; font-weight:700; color:#334155; }
  .gtAuthoringGroupLabels { display:grid; grid-template-columns:minmax(180px,1fr) auto; gap:6px 10px; align-items:center; padding-top:7px; }
  .gtAuthoringLabel.predicted { color:#16803c; font-weight:700; }
  .gtTri { display:flex; }
  .gtTri button { min-width:32px; height:28px; border:1px solid #cbd5e1; border-left:0; background:white; color:#334155; cursor:pointer; }
  .gtTri button:first-child { border-left:1px solid #cbd5e1; border-radius:5px 0 0 5px; }
  .gtTri button:last-child { border-radius:0 5px 5px 0; }
  .gtTri button.active[data-value="true"] { background:#16803c; color:white; }
  .gtTri button.active[data-value="false"] { background:#b42318; color:white; }
  .gtTri button.active[data-value="null"] { background:#6b7280; color:white; }
  .gtAuthoringFields { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:8px; }
  .gtAuthoringFields label { display:grid; gap:4px; font-size:11px; color:#64748b; text-transform:uppercase; font-weight:700; }
  .gtAuthoringFields input, .gtAuthoringFields select, .gtAuthoringFields textarea { width:100%; border:1px solid #cbd5e1; border-radius:5px; padding:6px 7px; background:white; color:#172033; font:13px system-ui,sans-serif; }
  .gtAuthoringFields textarea { min-height:54px; resize:vertical; }
  .gtAuthoringActions { display:flex; gap:7px; flex-wrap:wrap; }
  @media (max-width:1250px) {
    .gtAuthoringWorkspace { grid-template-columns:1fr; }
    .gtAuthoringWorkspace #gtAuthoringPanel[open] { max-height:none; overflow:visible; }
  }
"""


def authoring_panel() -> str:
    return """
    <details class="panel" id="gtAuthoringPanel" open>
      <summary>Frame GT authoring</summary>
      <div class="gtAuthoringBody">
      <div class="gtAuthoringHeader">
        <details class="gtScenarioPicker" id="gtScenarioPicker">
          <summary id="gtScenarioPickerSummary">Scenario filter</summary>
          <div class="gtScenarioPickerMenu">
            <div class="gtScenarioPickerActions">
              <button id="gtScenarioSelectAll" type="button">Select all</button>
              <button id="gtScenarioSelectNone" type="button">Select none</button>
            </div>
            <div id="gtScenarioChoices" class="gtScenarioChoices"></div>
          </div>
        </details>
        <div class="gtAuthoringCommandRow">
          <button id="gtAuthoringAddCurrent" class="primary" type="button">Add current frame</button>
          <button id="gtAuthoringPrev" type="button">Previous</button>
          <button id="gtAuthoringNext" type="button">Next</button>
        </div>
        <div class="gtAuthoringFileRow">
          <button id="gtAuthoringImportButton" type="button">Import JSON</button>
          <button id="gtAuthoringSaveToGt" type="button">Save to GT folder</button>
          <button id="gtAuthoringDownload" class="primary" type="button">Download JSON</button>
        </div>
        <input id="gtAuthoringImport" type="file" accept="application/json">
      </div>
      <div id="gtAuthoringStatus"></div>
      <div id="gtAuthoringExclusion"></div>
      <div id="gtAuthoringLabels" class="gtAuthoringLabels"></div>
      <div class="gtAuthoringActions">
        <button id="gtAuthoringUnknownFalse" type="button">Set unknown to false</button>
        <button id="gtAuthoringCopyPrevious" type="button">Copy previous review frame</button>
      </div>
      <div class="gtAuthoringFields">
        <label>Review status<select id="gtAuthoringNeedsReview"><option value="true">Needs review</option><option value="false">Reviewed</option></select></label>
        <label>Confidence<select id="gtAuthoringConfidence"><option value="">Not set</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
        <label>Reviewer<input id="gtAuthoringReviewer"></label>
        <label>Notes<textarea id="gtAuthoringNotes"></textarea></label>
      </div>
      </div>
    </details>"""


def authoring_script(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return (
        "const GT_AUTHORING = "
        + serialized
        + r""";
const gtAuthoringStorageKey = `ms-odd-frame-gt:${GT_AUTHORING.recording_id}`;
const gtAuthoringPreferenceKey = 'ms-odd-gt-authoring-preferences-v2';
let gtAuthoring = GT_AUTHORING.gt;
const gtAuthoringFrames = GT_AUTHORING.review_frames || [];
const gtAuthoringByFrameIndex = new Map(gtAuthoringFrames.map(frame => [Number(frame.frame_index), frame]));
const gtAuthoringFrameIndexes = gtAuthoringFrames.map(frame => Number(frame.frame_index)).sort((a, b) => a - b);
let gtAuthoringPreferences = {
  panelOpen: true,
  pickerOpen: false,
  selectedScenarios: [...GT_AUTHORING.taxonomy],
  groupOpen: Object.fromEntries(GT_AUTHORING.scenario_groups.map(group => [group.id, true])),
};
function gtAuthoringLoadPreferences() {
  try {
    const local = JSON.parse(localStorage.getItem(gtAuthoringPreferenceKey) || 'null');
    const carried = window.name.startsWith(`${gtAuthoringPreferenceKey}:`)
      ? JSON.parse(window.name.slice(gtAuthoringPreferenceKey.length + 1))
      : null;
    const saved = carried || local;
    if (saved && typeof saved === 'object') {
      gtAuthoringPreferences = {
        ...gtAuthoringPreferences,
        ...saved,
        groupOpen: {...gtAuthoringPreferences.groupOpen, ...(saved.groupOpen || {})},
        selectedScenarios: Array.isArray(saved.selectedScenarios)
          ? saved.selectedScenarios.filter(label => GT_AUTHORING.taxonomy.includes(label))
          : gtAuthoringPreferences.selectedScenarios,
      };
    }
  } catch (error) { console.warn(error); }
}
function gtAuthoringSavePreferences() {
  const serialized = JSON.stringify(gtAuthoringPreferences);
  localStorage.setItem(gtAuthoringPreferenceKey, serialized);
  window.name = `${gtAuthoringPreferenceKey}:${serialized}`;
}
function gtAuthoringActiveLabelsAt(frameIndex) {
  return (tags.events || [])
    .filter(event => Number(event.startFrame) <= frameIndex && frameIndex <= Number(event.endFrame))
    .map(event => event.scenario);
}
function gtAuthoringRegisterFrame(item) {
  const index = Number(item.frame_index);
  if (gtAuthoringByFrameIndex.has(index)) return;
  gtAuthoringFrames.push(item);
  gtAuthoringByFrameIndex.set(index, item);
  gtAuthoringFrameIndexes.push(index);
  gtAuthoringFrameIndexes.sort((a, b) => a - b);
}
function gtAuthoringRestore() {
  try {
    const saved = localStorage.getItem(gtAuthoringStorageKey);
    if (saved) {
      const loaded = JSON.parse(saved);
      if (loaded.schema_version === gtAuthoring.schema_version) gtAuthoring = loaded;
    }
  } catch (error) { console.warn(error); }
}
function gtAuthoringNormalize() {
  gtAuthoring.label_fields = [...GT_AUTHORING.taxonomy];
  gtAuthoring.formula_filled_label_fields = [...(GT_AUTHORING.gt.formula_filled_label_fields || [])];
  gtAuthoring.frames = gtAuthoring.frames || {};
  for (const item of gtAuthoringFrames) {
    const baseline = GT_AUTHORING.gt.frames[item.frame_id] || {};
    const saved = gtAuthoring.frames[item.frame_id] || {};
    gtAuthoring.frames[item.frame_id] = {...baseline, ...saved, labels: {...(baseline.labels || {}), ...(saved.labels || {})}};
  }
  for (const [frameId, saved] of Object.entries(gtAuthoring.frames)) {
    const frameIndex = Number(saved.frame_index);
    if (!Number.isFinite(frameIndex) || gtAuthoringByFrameIndex.has(frameIndex)) continue;
    gtAuthoringRegisterFrame({
      frame_id: frameId,
      frame_index: frameIndex,
      timestamp_unix_s: saved.timestamp_unix_s ?? null,
      time_since_start_s: saved.time_since_start_s ?? traj.rel_t[frameIndex] ?? null,
      reference: saved.reference || {},
      derivation: {active_labels: gtAuthoringActiveLabelsAt(frameIndex), active_events: []},
    });
  }
}
function gtAuthoringSave() {
  localStorage.setItem(gtAuthoringStorageKey, JSON.stringify(gtAuthoring));
  gtAuthoringRender();
}
function gtAuthoringSelectedScenarios() {
  return new Set(gtAuthoringPreferences.selectedScenarios);
}
function currentGtAuthoringFrame() {
  return gtAuthoringByFrameIndex.get(Number(currentIndex)) || null;
}
function currentGtAuthoringGtFrame() {
  const item = currentGtAuthoringFrame();
  return item ? gtAuthoring.frames[item.frame_id] : null;
}
function gtAuthoringScenarioLabels(definition) {
  const selected = gtAuthoringSelectedScenarios();
  return definition.scenarios.filter(label => selected.has(label));
}
function gtAuthoringSetFrameByOffset(offset) {
  if (!gtAuthoringFrameIndexes.length) return;
  const current = Number(currentIndex);
  let target = gtAuthoringFrameIndexes[0];
  if (offset < 0) {
    for (const frameIndex of gtAuthoringFrameIndexes) {
      if (frameIndex < current) target = frameIndex;
      else break;
    }
  } else {
    target = gtAuthoringFrameIndexes[gtAuthoringFrameIndexes.length - 1];
    for (const frameIndex of gtAuthoringFrameIndexes) {
      if (frameIndex > current) { target = frameIndex; break; }
    }
  }
  setFrame(target);
}
function gtAuthoringHandleKeydown(event) {
  const tag = event.target?.tagName;
  if (['INPUT','TEXTAREA','SELECT','BUTTON'].includes(tag)) return;
  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    gtAuthoringSetFrameByOffset(-1);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    gtAuthoringSetFrameByOffset(1);
  }
}
function gtAuthoringSpeedLabels(speed) {
  const labels = {
    stationary: null,
    low_magnitude_speed: null,
    medium_magnitude_speed: null,
    high_magnitude_speed: null,
  };
  if (!Number.isFinite(speed) || speed < 0) return labels;
  const active = speed >= 15 ? 'high_magnitude_speed'
    : speed >= 5 ? 'medium_magnitude_speed'
    : speed >= 0.5 ? 'low_magnitude_speed'
    : 'stationary';
  for (const label of Object.keys(labels)) labels[label] = label === active;
  return labels;
}
function gtAuthoringAddCurrentFrame() {
  const frameIndex = Number(currentIndex);
  if (gtAuthoringByFrameIndex.has(frameIndex)) return;
  const frameId = `${GT_AUTHORING.recording_id}:frame-${String(frameIndex).padStart(6, '0')}`;
  const speed = Number(traj.speed?.[frameIndex]);
  const labels = Object.fromEntries(GT_AUTHORING.taxonomy.map(label => [label, null]));
  Object.assign(labels, gtAuthoringSpeedLabels(speed));
  const time = Number(traj.rel_t?.[frameIndex]);
  const item = {
    frame_id: frameId,
    frame_index: frameIndex,
    timestamp_unix_s: null,
    time_since_start_s: Number.isFinite(time) ? time : null,
    reference: {
      speed_mps: Number.isFinite(speed) ? speed : null,
      speed_formula_label: Object.entries(labels).find(([label, value]) =>
        value === true && ['stationary','low_magnitude_speed','medium_magnitude_speed','high_magnitude_speed'].includes(label)
      )?.[0] || null,
    },
    derivation: {
      active_labels: gtAuthoringActiveLabelsAt(frameIndex),
      active_events: [],
    },
  };
  gtAuthoringRegisterFrame(item);
  gtAuthoring.frames[frameId] = {
    frame_id: frameId,
    frame_index: frameIndex,
    timestamp_unix_s: null,
    time_since_start_s: item.time_since_start_s,
    reference: item.reference,
    labels,
    confidence: null,
    needs_review: true,
    notes: '',
    reviewer: '',
    reviewed_at: '',
    excluded_from_evaluation: frameIndex < GT_AUTHORING.minimum_scored_frame_index,
  };
  gtAuthoringSave();
}
function gtAuthoringSetLabel(label, value) {
  const frame = currentGtAuthoringGtFrame();
  if (!frame || frame.excluded_from_evaluation) return;
  frame.labels[label] = value;
  gtAuthoringSave();
}
function gtAuthoringRenderLabels(item, frame) {
  const root = document.getElementById('gtAuthoringLabels');
  root.innerHTML = '';
  if (!item || !frame) return;
  const predicted = new Set(item.derivation.active_labels || []);
  for (const definition of GT_AUTHORING.scenario_groups) {
    const visibleLabels = gtAuthoringScenarioLabels(definition);
    if (!visibleLabels.length) continue;
    const details = document.createElement('details');
    details.className = 'gtAuthoringGroup';
    details.open = gtAuthoringPreferences.groupOpen[definition.id] !== false;
    details.addEventListener('toggle', () => {
      gtAuthoringPreferences.groupOpen[definition.id] = details.open;
      gtAuthoringSavePreferences();
    });
    const summary = document.createElement('summary');
    summary.textContent = `${definition.label} (${visibleLabels.length})`;
    details.appendChild(summary);
    const labelsRoot = document.createElement('div');
    labelsRoot.className = 'gtAuthoringGroupLabels';
    for (const label of visibleLabels) {
      const name = document.createElement('span');
      name.className = 'gtAuthoringLabel';
      name.classList.toggle('predicted', predicted.has(label));
      name.textContent = label.replaceAll('_', ' ') + (predicted.has(label) ? ' · predicted' : '');
      labelsRoot.appendChild(name);
      const group = document.createElement('div');
      group.className = 'gtTri';
      for (const [text, value] of [['Y', true], ['N', false], ['?', null]]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = text;
        button.dataset.value = String(value);
        button.disabled = Boolean(frame.excluded_from_evaluation);
        button.classList.toggle('active', frame.labels[label] === value);
        button.onclick = () => gtAuthoringSetLabel(label, value);
        group.appendChild(button);
      }
      labelsRoot.appendChild(group);
    }
    details.appendChild(labelsRoot);
    root.appendChild(details);
  }
}
function gtAuthoringRender() {
  const item = currentGtAuthoringFrame();
  const frame = currentGtAuthoringGtFrame();
  const sampledCount = gtAuthoringFrames.length;
  document.getElementById('gtAuthoringPrev').disabled = !sampledCount;
  document.getElementById('gtAuthoringNext').disabled = !sampledCount;
  document.getElementById('gtAuthoringAddCurrent').disabled = Boolean(item);
  if (!item || !frame) {
    document.getElementById('gtAuthoringStatus').textContent = `Frame ${currentIndex} is not in GT yet. Use “Review/tag current frame” to label this exact time.`;
    document.getElementById('gtAuthoringExclusion').textContent = '';
    document.getElementById('gtAuthoringLabels').innerHTML = '';
    for (const id of ['gtAuthoringNeedsReview','gtAuthoringConfidence','gtAuthoringReviewer','gtAuthoringNotes','gtAuthoringUnknownFalse','gtAuthoringCopyPrevious']) document.getElementById(id).disabled = true;
    return;
  }
  const known = Object.values(frame.labels || {}).filter(value => typeof value === 'boolean').length;
  document.getElementById('gtAuthoringStatus').textContent = `Review frame ${item.frame_index} · ${known}/${GT_AUTHORING.taxonomy.length} labels set`;
  document.getElementById('gtAuthoringExclusion').textContent = frame.excluded_from_evaluation ? `Excluded from scoring: source frames below ${GT_AUTHORING.minimum_scored_frame_index} are unreliable.` : '';
  for (const id of ['gtAuthoringNeedsReview','gtAuthoringConfidence','gtAuthoringReviewer','gtAuthoringNotes','gtAuthoringUnknownFalse','gtAuthoringCopyPrevious']) document.getElementById(id).disabled = Boolean(frame.excluded_from_evaluation);
  document.getElementById('gtAuthoringNeedsReview').value = String(Boolean(frame.needs_review));
  document.getElementById('gtAuthoringConfidence').value = frame.confidence ?? '';
  document.getElementById('gtAuthoringReviewer').value = frame.reviewer ?? '';
  document.getElementById('gtAuthoringNotes').value = frame.notes ?? '';
  gtAuthoringRenderLabels(item, frame);
}
function gtAuthoringDownload() {
  const blob = new Blob([JSON.stringify(gtAuthoring, null, 2) + '\n'], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = GT_AUTHORING.download_filename;
  a.click();
  URL.revokeObjectURL(url);
}
async function gtAuthoringSaveToGtFolder() {
  gtAuthoringSave();
  const button = document.getElementById('gtAuthoringSaveToGt');
  const original = button.textContent;
  button.disabled = true;
  button.textContent = 'Saving...';
  try {
    const response = await fetch('/__gt_authoring_save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(gtAuthoring),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.status !== 'ok') {
      throw new Error(result.error || `HTTP ${response.status}`);
    }
    document.getElementById('gtAuthoringStatus').textContent =
      `Saved to GT folder: ${result.file}`;
  } catch (error) {
    document.getElementById('gtAuthoringStatus').textContent =
      `GT folder save unavailable: ${error.message}. Use Download JSON or serve with the GT authoring save server.`;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}
function gtAuthoringInitialize() {
  gtAuthoringLoadPreferences();
  const panel = document.getElementById('gtAuthoringPanel');
  const picker = document.getElementById('gtScenarioPicker');
  panel.open = gtAuthoringPreferences.panelOpen !== false;
  picker.open = gtAuthoringPreferences.pickerOpen === true;
  panel.addEventListener('toggle', () => {
    gtAuthoringPreferences.panelOpen = panel.open;
    gtAuthoringSavePreferences();
  });
  picker.addEventListener('toggle', () => {
    gtAuthoringPreferences.pickerOpen = picker.open;
    gtAuthoringSavePreferences();
  });
  const choices = document.getElementById('gtScenarioChoices');
  for (const label of GT_AUTHORING.taxonomy) {
    const choice = document.createElement('label');
    choice.className = 'gtScenarioChoice';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = label;
    input.checked = gtAuthoringPreferences.selectedScenarios.includes(label);
    input.addEventListener('change', () => {
      gtAuthoringPreferences.selectedScenarios = [...choices.querySelectorAll('input:checked')].map(item => item.value);
      gtAuthoringSavePreferences();
      gtAuthoringUpdateScenarioSummary();
      gtAuthoringRender();
    });
    const text = document.createElement('span');
    text.textContent = label.replaceAll('_', ' ');
    choice.append(input, text);
    choices.appendChild(choice);
  }
  const setScenarioSelection = checked => {
    for (const input of choices.querySelectorAll('input')) input.checked = checked;
    gtAuthoringPreferences.selectedScenarios = checked ? [...GT_AUTHORING.taxonomy] : [];
    gtAuthoringSavePreferences();
    gtAuthoringUpdateScenarioSummary();
    gtAuthoringRender();
  };
  document.getElementById('gtScenarioSelectAll').onclick = () => setScenarioSelection(true);
  document.getElementById('gtScenarioSelectNone').onclick = () => setScenarioSelection(false);
  gtAuthoringRestore();
  gtAuthoringNormalize();
  gtAuthoringUpdateScenarioSummary();
  for (const id of ['gtAuthoringNeedsReview','gtAuthoringConfidence','gtAuthoringReviewer','gtAuthoringNotes']) {
    document.getElementById(id).addEventListener('change', event => {
      const frame = currentGtAuthoringGtFrame();
      if (!frame) return;
      const key = {gtAuthoringNeedsReview:'needs_review',gtAuthoringConfidence:'confidence',gtAuthoringReviewer:'reviewer',gtAuthoringNotes:'notes'}[id];
      frame[key] = id === 'gtAuthoringNeedsReview' ? event.target.value === 'true' : event.target.value || '';
      if (id === 'gtAuthoringNeedsReview' && !frame.needs_review) frame.reviewed_at = new Date().toISOString();
      gtAuthoringSave();
    });
  }
  document.getElementById('gtAuthoringPrev').onclick = () => gtAuthoringSetFrameByOffset(-1);
  document.getElementById('gtAuthoringNext').onclick = () => gtAuthoringSetFrameByOffset(1);
  document.getElementById('gtAuthoringAddCurrent').onclick = gtAuthoringAddCurrentFrame;
  document.getElementById('gtAuthoringSaveToGt').onclick = gtAuthoringSaveToGtFolder;
  document.getElementById('gtAuthoringDownload').onclick = gtAuthoringDownload;
  document.getElementById('gtAuthoringImportButton').onclick = () => document.getElementById('gtAuthoringImport').click();
  document.getElementById('gtAuthoringImport').onchange = async event => {
    const loaded = JSON.parse(await event.target.files[0].text());
    if (loaded.recording_id !== GT_AUTHORING.recording_id || loaded.schema_version !== gtAuthoring.schema_version) {
      alert('Recording or frame GT schema does not match');
      return;
    }
    gtAuthoring = loaded;
    gtAuthoringNormalize();
    gtAuthoringSave();
  };
  document.getElementById('gtAuthoringUnknownFalse').onclick = () => {
    const frame = currentGtAuthoringGtFrame();
    if (!frame) return;
    const labels = [...gtAuthoringSelectedScenarios()];
    for (const label of labels) if (frame.labels[label] === null) frame.labels[label] = false;
    gtAuthoringSave();
  };
  document.getElementById('gtAuthoringCopyPrevious').onclick = () => {
    const item = currentGtAuthoringFrame();
    const frame = currentGtAuthoringGtFrame();
    if (!item || !frame) return;
    const position = gtAuthoringFrameIndexes.indexOf(Number(item.frame_index));
    if (position <= 0) return;
    const previous = gtAuthoring.frames[gtAuthoringByFrameIndex.get(gtAuthoringFrameIndexes[position - 1]).frame_id];
    const selected = [...gtAuthoringSelectedScenarios()];
    for (const label of selected) frame.labels[label] = previous.labels?.[label] ?? null;
    gtAuthoringSave();
  };
  document.addEventListener('keydown', gtAuthoringHandleKeydown);
  gtAuthoringRender();
}
function gtAuthoringUpdateScenarioSummary() {
  const selected = gtAuthoringPreferences.selectedScenarios.length;
  document.getElementById('gtScenarioPickerSummary').textContent =
    selected === GT_AUTHORING.taxonomy.length
      ? `Scenario filter · all ${selected}`
      : `Scenario filter · ${selected}/${GT_AUTHORING.taxonomy.length}`;
}
"""
    )


def comparison_panel(recording_summary: dict, quality: dict) -> str:
    status = quality.get("status", "unknown")
    exact = recording_summary.get("exact_match_accuracy")
    exact_text = "n/a" if exact is None else f"{100 * exact:.1f}%"
    warning_class = " gtWarning" if status != "valid" else ""
    return f"""
    <div class="panel" id="gtComparisonPanel">
      <div class="gtComparisonHeader">
        <h2>GT comparison</h2>
        <label>Scenario
          <select id="gtScenarioFilter"><option value="all" selected>all scored scenarios</option></select>
        </label>
        <label><input id="gtMismatchOnly" type="checkbox" /> Mismatches only</label>
        <div class="gtMetrics">
          <span class="gtMetric">exact frame match {exact_text}</span>
          <span class="gtMetric{warning_class}">GT {html.escape(status)}</span>
          <span class="gtMetric">frames 0-4 excluded</span>
        </div>
      </div>
      <div id="gtComparisonTimeline"></div>
      <div id="gtComparisonReadout">Click a GT or prediction marker to inspect that source frame.</div>
    </div>"""


def inject_authoring(
    page: str,
    recording: str,
    authoring_payload: dict,
    source_dir: Path,
) -> str:
    """Duplicate a current tagged explorer and add synchronized GT editing."""
    markers = {
        "</style>": GT_AUTHORING_STYLE + "\n</style>",
        '    <div class="panel"><div id="laneTrackerTimeline"></div></div>':
            '    <div class="panel gtRemovedLaneTrackerTimeline" aria-hidden="true">'
            '<div id="laneTrackerTimeline"></div></div>',
        '    <div class="panel"><div id="map"></div></div>':
            '    <div class="gtAuthoringWorkspace">\n'
            '      <div class="panel"><div id="map"></div></div>\n'
            + authoring_panel()
            + '\n    </div>',
        "const DATA =":
            authoring_script(authoring_payload) + "\nconst DATA =",
        "  updateTagTimelineCursor();\n}":
            "  updateTagTimelineCursor();\n"
            "  if (typeof gtAuthoringRender === 'function') gtAuthoringRender();\n}",
        "renderTagTimeline();\n":
            "renderTagTimeline();\ngtAuthoringInitialize();\n",
    }
    for old, new in markers.items():
        if page.count(old) != 1:
            raise ValueError(
                f"{recording}: expected one authoring marker {old!r}, "
                f"found {page.count(old)}"
            )
        page = page.replace(old, new, 1)
    source_debug = (source_dir / "debug").resolve().as_uri()
    page = page.replace(
        "const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;",
        f"const DEBUG_BASE = `{source_debug}/${{encodeURIComponent(DATA.summary.recording)}}`;",
        1,
    )
    return page.replace("<title>", "<title>GT authoring - ", 1)


GT_SCRIPT = r"""
function gtComparisonRows() {
  const selected = gtScenarioFilter.value;
  const mismatchOnly = document.getElementById('gtMismatchOnly').checked;
  return GT_COMPARE.rows.filter(row =>
    (selected === 'all' || row.label === selected) &&
    (!mismatchOnly || row.expected !== row.actual)
  );
}

function gtMarkerTrace(rows, source) {
  const isGt = source === 'gt';
  return {
    type: 'scattergl',
    mode: 'markers',
    name: isGt ? 'Ground truth' : 'Tagged prediction',
    x: rows.map(row => row.time),
    y: rows.map(row => `${isGt ? 'GT' : 'Tag'} · ${row.label.replaceAll('_', ' ')}`),
    marker: {
      size: 8,
      symbol: rows.map(row => {
        const value = isGt ? row.expected : row.actual;
        if (row.expected !== row.actual) return 'x';
        return value ? (isGt ? 'square' : 'circle') : (isGt ? 'square-open' : 'circle-open');
      }),
      color: rows.map(row => row.expected !== row.actual ? '#dc2626' : (isGt ? '#059669' : '#2563eb')),
      line: {width: 1}
    },
    customdata: rows.map(row => [row.frameIndex, row.label, row.expected, row.actual, row.outcome]),
    hovertemplate: `${isGt ? 'GT' : 'tag'}<br>%{customdata[1]}<br>frame %{customdata[0]} · t=%{x:.2f}s<br>GT=%{customdata[2]} · tag=%{customdata[3]}<br>%{customdata[4]}<extra></extra>`
  };
}

function renderGtComparison() {
  const rows = gtComparisonRows();
  const labels = [...new Set(rows.map(row => row.label))];
  const traces = rows.length ? [gtMarkerTrace(rows, 'gt'), gtMarkerTrace(rows, 'tag')] : [];
  const height = Math.max(300, 125 + labels.length * 68);
  const element = document.getElementById('gtComparisonTimeline');
  element.style.height = `${height}px`;
  Plotly.newPlot(element, traces, {
    margin: {...SHARED_TIMELINE_MARGIN, l: 225},
    xaxis: sharedTimelineXAxis(),
    yaxis: {title: '', automargin: false, categoryorder: 'array',
      categoryarray: labels.flatMap(label => [`Tag · ${label.replaceAll('_', ' ')}`, `GT · ${label.replaceAll('_', ' ')}`])},
    hovermode: 'closest',
    legend: {orientation: 'h', x: 0.5, xanchor: 'center', y: -0.16},
    shapes: [{type:'line', x0:traj.rel_t[currentIndex], x1:traj.rel_t[currentIndex],
      y0:0, y1:1, yref:'paper', line:{color:'#111827', width:2, dash:'dot'}}],
    annotations: rows.length ? [] : [{text:'No comparison rows match this filter', showarrow:false, x:0.5, y:0.5, xref:'paper', yref:'paper'}]
  }, {responsive:true});
  attachSharedTimeAxis('gtComparisonTimeline');
  if (!element._gtClickAttached) {
    element._gtClickAttached = true;
    element.on('plotly_click', eventData => {
      const point = eventData.points && eventData.points[0];
      if (!point || !point.customdata) return;
      setFrame(point.customdata[0]);
      const [frame, label, expected, actual, outcome] = point.customdata;
      document.getElementById('gtComparisonReadout').textContent =
        `frame ${frame} · ${label.replaceAll('_',' ')} · GT=${expected} · tag=${actual} · ${outcome}`;
    });
  }
}

function updateGtComparisonCursor() {
  const element = document.getElementById('gtComparisonTimeline');
  if (!element || !element.data) return;
  Plotly.relayout(element, {shapes:[{type:'line', x0:traj.rel_t[currentIndex], x1:traj.rel_t[currentIndex],
    y0:0, y1:1, yref:'paper', line:{color:'#111827', width:2, dash:'dot'}}]});
}
"""


def load_rows(path: Path, gt_dir: Path) -> dict[str, list[dict]]:
    time_by_frame = {}
    for gt_path in gt_dir.glob("*_frame_gt.json"):
        payload = json.loads(gt_path.read_text(encoding="utf-8"))
        recording = payload["recording_id"]
        for frame in payload.get("frames", {}).values():
            time_by_frame[(recording, int(frame["frame_index"]))] = float(
                frame["time_since_start_s"]
            )
    grouped: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            recording = row["recording_id"]
            frame_index = int(row["frame_index"])
            grouped[row["recording_id"]].append(
                {
                    "frameIndex": frame_index,
                    "time": round(time_by_frame[(recording, frame_index)], 4),
                    "label": row["label"],
                    "expected": row["expected"].lower() == "true",
                    "actual": row["actual"].lower() == "true",
                    "outcome": row["outcome"],
                }
            )
    return grouped


def inject(
    page: str,
    recording: str,
    rows: list[dict],
    recording_summary: dict,
    quality: dict,
    source_dir: Path,
    authoring_payload: dict | None = None,
) -> str:
    authoring_style = GT_AUTHORING_STYLE if authoring_payload is not None else ""
    authoring_html = authoring_panel() if authoring_payload is not None else ""
    authoring_data_script = (
        authoring_script(authoring_payload) + "\n" if authoring_payload is not None else ""
    )
    authoring_cursor = (
        "  if (typeof gtAuthoringRender === 'function') gtAuthoringRender();\n"
        if authoring_payload is not None
        else ""
    )
    authoring_init = (
        "gtAuthoringInitialize();\n" if authoring_payload is not None else ""
    )
    markers = {
        "</style>": GT_STYLE + authoring_style + "\n</style>",
        '    <div class="panel"><div id="tagTimeline"></div></div>':
            '    <div class="panel"><div id="tagTimeline"></div></div>\n'
            + comparison_panel(recording_summary, quality),
        "const DATA =": "const GT_COMPARE = "
            + json.dumps(
                {
                    "recordingId": recording,
                    "scoredLabels": recording_summary.get("label_metrics")
                    and [row["label"] for row in recording_summary["label_metrics"]]
                    or sorted({row["label"] for row in rows}),
                    "rows": rows,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
            + ";\n"
            + GT_SCRIPT
            + "\n"
            + authoring_data_script
            + "\nconst DATA =",
        "  updateTagTimelineCursor();\n}":
            "  updateTagTimelineCursor();\n  updateGtComparisonCursor();\n}",
        "renderTagTimeline();\n":
            "renderTagTimeline();\n"
            "const gtScenarioFilter = document.getElementById('gtScenarioFilter');\n"
            "for (const label of GT_COMPARE.scoredLabels) {\n"
            "  const option = document.createElement('option');\n"
            "  option.value = label;\n"
            "  option.textContent = label.replaceAll('_', ' ');\n"
            "  gtScenarioFilter.appendChild(option);\n"
            "}\n"
            "if (!SHARED_TIME_PLOT_IDS.includes('gtComparisonTimeline')) SHARED_TIME_PLOT_IDS.push('gtComparisonTimeline');\n"
            "if (document.getElementById('laneTrackerTimeline')) {\n"
            "  if (!SHARED_TIME_PLOT_IDS.includes('laneTrackerTimeline')) SHARED_TIME_PLOT_IDS.push('laneTrackerTimeline');\n"
            "  attachSharedTimeAxis('laneTrackerTimeline');\n"
            "}\n"
            "renderGtComparison();\n"
            "document.getElementById('gtScenarioFilter').addEventListener('change', renderGtComparison);\n"
            "document.getElementById('gtMismatchOnly').addEventListener('change', renderGtComparison);\n"
            + authoring_init,
    }
    if authoring_payload is not None:
        markers['    <div class="panel"><div id="laneTrackerTimeline"></div></div>'] = (
            '    <div class="panel gtRemovedLaneTrackerTimeline" aria-hidden="true">'
            '<div id="laneTrackerTimeline"></div></div>'
        )
        markers['    <div class="panel"><div id="map"></div></div>'] = (
            '    <div class="gtAuthoringWorkspace">\n'
            '      <div class="panel"><div id="map"></div></div>\n'
            + authoring_html
            + '\n    </div>'
        )
    if authoring_cursor:
        markers["  updateTagTimelineCursor();\n  updateGtComparisonCursor();\n}"] = (
            "  updateTagTimelineCursor();\n  updateGtComparisonCursor();\n"
            + authoring_cursor
            + "}"
        )
    for old, new in markers.items():
        if page.count(old) != 1:
            raise ValueError(f"{recording}: expected one marker {old!r}, found {page.count(old)}")
        page = page.replace(old, new, 1)
    source_debug = (source_dir / "debug").resolve().as_uri()
    page = page.replace(
        "const DEBUG_BASE = `debug/${encodeURIComponent(DATA.summary.recording)}`;",
        f"const DEBUG_BASE = `{source_debug}/${{encodeURIComponent(DATA.summary.recording)}}`;",
        1,
    )
    return page.replace("<title>", "<title>GT comparison - ", 1)


def index_html(records: list[dict]) -> str:
    links = "\n".join(
        f'<li><a href="{quote(row["file"])}">{html.escape(row["recording"])}</a>'
        f'<span>{row["frames"]} compared frames · {100 * row["exact"]:.1f}% exact frame match</span></li>'
        for row in records
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tagged scenario GT comparison explorers</title>
<style>body{{font:15px system-ui,sans-serif;max-width:1000px;margin:auto;padding:24px;background:#f8fafc;color:#172033}}
h1{{font-size:23px}}ul{{list-style:none;padding:0}}li{{display:flex;justify-content:space-between;gap:20px;padding:13px 4px;border-bottom:1px solid #d8deea}}
a{{font-weight:650;color:#2458c6}}span{{color:#657087}}</style></head>
<body><h1>Tagged scenario GT comparison explorers</h1><ul>{links}</ul></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--gt-dir", type=Path, default=DEFAULT_GT_DIR)
    parser.add_argument(
        "--frame-input-root",
        type=Path,
        default=None,
        help=(
            "Optional revised frame-input root. When provided, duplicate explorers "
            "also receive synchronized frame-level GT authoring controls."
        ),
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Regenerate matching recording pages without replacing the existing index and manifest.",
    )
    parser.add_argument(
        "--merge-index",
        action="store_true",
        help="Update matching entries in an existing index and manifest while preserving other recordings.",
    )
    args = parser.parse_args()

    grouped = load_rows(args.details, args.gt_dir)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    summaries = {row["recording_id"]: row for row in summary["recordings"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for recording, rows in sorted(grouped.items()):
        source = args.source_dir / f"{recording}_following_lane_explorer.html"
        if not source.is_file():
            raise FileNotFoundError(source)
        recording_summary = summaries[recording]
        authoring_payload = None
        if args.frame_input_root is not None:
            gt_path = args.gt_dir / f"{recording}_frame_gt.json"
            authoring_payload = build_review_payload(
                args.frame_input_root,
                recording,
                gt_path if gt_path.is_file() else None,
            )
        output_name = f"{recording}_animated_odld_explorer_w_gt_comparison.html"
        output = args.output_dir / output_name
        output.write_text(
            inject(
                source.read_text(encoding="utf-8"),
                recording,
                rows,
                recording_summary,
                summary["gt_quality"],
                args.source_dir,
                authoring_payload,
            ),
            encoding="utf-8",
        )
        records.append(
            {
                "recording": recording,
                "file": output_name,
                "frames": recording_summary["reviewed_frames_scored"],
                "exact": recording_summary["exact_match_accuracy"],
            }
        )
        print(f"Wrote {output}")
    if args.skip_index and args.merge_index:
        parser.error("--skip-index and --merge-index are mutually exclusive")
    if args.merge_index:
        manifest_path = args.output_dir / "manifest.json"
        existing = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {"recordings": []}
        )
        merged = {
            row["recording"]: row for row in existing.get("recordings", [])
        }
        merged.update({row["recording"]: row for row in records})
        merged_records = [merged[key] for key in sorted(merged)]
        manifest = {
            **existing,
            "schema_version": "tagged-scenario-gt-comparison-explorers-v1",
            "source_dir": str(args.source_dir),
            "frame_input_root": str(args.frame_input_root) if args.frame_input_root else None,
            "minimum_frame_index": summary["minimum_scored_frame_index"],
            "recordings": merged_records,
        }
        (args.output_dir / "index.html").write_text(
            index_html(merged_records), encoding="utf-8"
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Updated {args.output_dir / 'index.html'}")
    elif not args.skip_index:
        (args.output_dir / "index.html").write_text(index_html(records), encoding="utf-8")
        (args.output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "tagged-scenario-gt-comparison-explorers-v1",
                    "source_dir": str(args.source_dir),
                    "frame_input_root": str(args.frame_input_root) if args.frame_input_root else None,
                    "minimum_frame_index": summary["minimum_scored_frame_index"],
                    "recordings": records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
