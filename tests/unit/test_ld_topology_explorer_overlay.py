from __future__ import annotations

from scripts.odld_explorer.add_ld_topology_overlay_to_explorer import inject_overlay


def test_ld_topology_overlay_injects_expected_controls_and_render_hook():
    page = """
<html>
<head><style>
</style></head>
<body>
    <label for="classFilter">Object classes</label>
<script>
const DATA = {"summary":{}};
function render() {
  const traces = [];
  Plotly.react('map', traces, {});
}
filter.addEventListener('change', render);
</script>
</body>
</html>
"""
    result = {
        "frames": [],
        "components": [],
        "lanes": [],
    }
    output = inject_overlay(page, result, {"lines": []})
    assert "LD Topology Overlay" in output
    assert "const LD_TOPOLOGY =" in output
    assert "addLdTopologyTraces(traces);" in output
    assert "showLdTopologyRawIntersection" in output
    assert 'id="showLdTopologyAllComponents" type="checkbox" checked' in output
