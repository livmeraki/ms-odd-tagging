from __future__ import annotations

from ms_odd_tagging.canonical import builder as canonical_builder
from ms_odd_tagging.frame_inputs import builder as frame_input_builder


def test_canonical_builder_dispatches(monkeypatch) -> None:
    captured = {}

    def fake_forward(module_main, argv):
        captured["module_main"] = module_main
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(canonical_builder, "_forward_main", fake_forward)
    result = canonical_builder.main(["--ld-radius-m", "80", "recording-a"])
    assert result == 0
    assert captured["module_main"] is canonical_builder.canonical_odld.main
    assert captured["argv"][-1] == "recording-a"
    assert captured["argv"][captured["argv"].index("--ld-radius-m") + 1] == "80.0"


def test_frame_builder_dispatches_generator(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_forward(module_main, argv):
        captured["module_main"] = module_main
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(frame_input_builder, "_forward_main", fake_forward)
    result = frame_input_builder.main(
        [
            "--input-dir",
            str(tmp_path / "in"),
            "--output-dir",
            str(tmp_path / "out"),
            "--recording",
            "recording-a",
        ]
    )
    assert result == 0
    assert captured["module_main"] is frame_input_builder.frame_generator.main
    assert captured["argv"][captured["argv"].index("--width") + 1] == "900"
    assert captured["argv"][captured["argv"].index("--height") + 1] == "1200"


def test_frame_builder_defaults() -> None:
    args = frame_input_builder.parse_args([])
    assert args.output_dir.name == "02_frame_inputs"
    assert args.width == 900
    assert args.height == 1200


def test_frame_builder_preserves_explicit_size() -> None:
    args = frame_input_builder.parse_args(["--width", "750", "--height", "1000"])
    assert args.width == 750
    assert args.height == 1000
