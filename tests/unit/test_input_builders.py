from __future__ import annotations

from ms_odd_tagging.input_generator import canonical_builder, frame_input_builder


def test_canonical_builder_dispatches_odld(monkeypatch) -> None:
    captured = {}

    def fake_forward(module_main, argv):
        captured["module_main"] = module_main
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(canonical_builder, "_forward_main", fake_forward)
    result = canonical_builder.main(
        ["--mode", "odld", "--ld-radius-m", "80", "recording-a"]
    )
    assert result == 0
    assert captured["module_main"] is canonical_builder.canonical_odld.main
    assert captured["argv"][-1] == "recording-a"
    assert captured["argv"][captured["argv"].index("--ld-radius-m") + 1] == "80.0"


def test_canonical_builder_dispatches_od(monkeypatch) -> None:
    captured = {}

    def fake_forward(module_main, argv):
        captured["module_main"] = module_main
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(canonical_builder, "_forward_main", fake_forward)
    result = canonical_builder.main(["--mode", "od", "recording-b"])
    assert result == 0
    assert captured["module_main"] is canonical_builder.canonical.main
    assert captured["argv"][-1] == "recording-b"


def test_frame_input_builder_dispatches_standard(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_forward(module_main, argv):
        captured["module_main"] = module_main
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(frame_input_builder, "_forward_main", fake_forward)
    result = frame_input_builder.main(
        [
            "--bev-style",
            "standard",
            "--input-dir",
            str(tmp_path / "in"),
            "--output-dir",
            str(tmp_path / "out"),
            "--recording",
            "recording-a",
        ]
    )
    assert result == 0
    assert captured["module_main"] is frame_input_builder.frame_input.main
    assert "--ld-line-patterns" in captured["argv"]


def test_frame_input_builder_dispatches_explorer_aligned(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_forward(module_main, argv):
        captured["module_main"] = module_main
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(frame_input_builder, "_forward_main", fake_forward)
    result = frame_input_builder.main(
        [
            "--bev-style",
            "revised",
            "--input-dir",
            str(tmp_path / "in"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert result == 0
    assert captured["module_main"] is frame_input_builder.frame_input_revised.main
    assert "--ld-line-patterns" not in captured["argv"]
