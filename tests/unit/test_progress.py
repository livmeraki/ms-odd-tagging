from __future__ import annotations

from ms_odd_tagging.common.progress import ProgressReporter


def test_progress_reporter_prints_counts_and_percentage(capsys) -> None:
    progress = ProgressReporter("sample", 4, "frame", min_interval_s=999.0, steps=2)

    progress.start()
    progress.advance("first")
    progress.advance("second")
    progress.finish()

    output = capsys.readouterr().out
    assert "[sample] [....................] 0/4 frames (  0.0%) - starting" in output
    assert "[sample] [==========..........] 2/4 frames ( 50.0%) - second" in output
    assert "[sample] [====================] 4/4 frames (100.0%) - done" in output


def test_progress_reporter_handles_empty_work(capsys) -> None:
    ProgressReporter("empty", 0, "recording").start()

    assert "[empty] no recordings to process" in capsys.readouterr().out
