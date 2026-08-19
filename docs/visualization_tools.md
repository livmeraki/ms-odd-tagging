# Visualization tool ownership

Use `ms-odd explore` for the supported, package-owned generic scenario explorer.
It consumes canonical JSON (or a raw trajectory through its documented compatibility
path), runs deterministic event detection, and writes a standalone review page.

The large scripts under `scripts/odld_explorer/` are specialized developer tools,
not competing public entrypoints:

| Tool | Input/tag source | Status |
|---|---|---|
| `generate_dataset_explorers.py` | Raw OD and trajectory | Base renderer used by the ODLD tools |
| `generate_odld_dataset_explorers_w_scenario_tag.py` | Canonical ODLD plus event/window and rule results | Specialized full ODLD debugger |
| `generate_odld_dataset_explorers_w_frame_scenario_tag.py` | Canonical ODLD plus externally generated per-frame tags | Specialized frame-tag compatibility tool |

The event-tag and frame-tag modes are intentionally retained because their tag
inputs are not equivalent. Their byte-identical index HTML, embedded `DATA`
parsing, manifest handling, output naming, and recording-path helpers now live in
`scripts/odld_explorer/odld_explorer_common.py`.

Lane, topology, VLM, GT-authoring, and review overlays remain separate. They add
domain-specific payloads or controls and should not be folded into the generic
explorer merely because they produce HTML.
