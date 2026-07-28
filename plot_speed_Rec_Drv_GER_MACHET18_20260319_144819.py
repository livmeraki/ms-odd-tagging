#!/usr/bin/env python3
"""Plot ego speed for Rec_Drv_GER_MACHET18_20260319_152119."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt

from ms_odd_tagging.common.config import DATA_RAW


def read_trajectory(path: Path) -> list[tuple[float, float, float, float]]:
    rows: list[tuple[float, float, float, float]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 8:
                raise ValueError(f"{path}:{line_number}: expected 8 columns")
            timestamp, tx, ty, tz, *_ = map(float, parts)
            rows.append((timestamp, tx, ty, tz))
    return rows


def derivative(values: list[float], times: list[float]) -> list[float | None]:
    n = len(values)
    if n < 2:
        return [None] * n

    result: list[float | None] = [None] * n
    for i in range(n):
        if i == 0:
            dt = times[1] - times[0]
            result[i] = (values[1] - values[0]) / dt if dt > 0 else None
            continue
        if i == n - 1:
            dt = times[-1] - times[-2]
            result[i] = (values[-1] - values[-2]) / dt if dt > 0 else None
            continue

        dt_left = times[i] - times[i - 1]
        dt_right = times[i + 1] - times[i]
        if dt_left > 0 and dt_right > 0:
            if 0.8 * dt_left <= dt_right <= 1.2 * dt_left:
                left_deriv = (values[i] - values[i - 1]) / dt_left
                right_deriv = (values[i + 1] - values[i]) / dt_right
                result[i] = (left_deriv + right_deriv) / 2.0
            else:
                result[i] = (values[i + 1] - values[i - 1]) / (dt_left + dt_right)
        elif dt_right > 0:
            result[i] = (values[i + 1] - values[i]) / dt_right
        elif dt_left > 0:
            result[i] = (values[i] - values[i - 1]) / dt_left
        else:
            result[i] = None
    return result


def compute_speed(rows: list[tuple[float, float, float, float]]) -> tuple[list[float], list[float], list[float]]:
    if not rows:
        return [], [], []

    timestamps = [row[0] for row in rows]
    xs = [row[1] for row in rows]
    ys = [row[2] for row in rows]

    time_since_start = [t - timestamps[0] for t in timestamps]

    adjacent_speed: list[float] = [float('nan')] * len(rows)
    for i in range(1, len(rows)):
        dt = timestamps[i] - timestamps[i - 1]
        if dt > 0:
            dx = xs[i] - xs[i - 1]
            dy = ys[i] - ys[i - 1]
            adjacent_speed[i] = math.hypot(dx, dy) / dt

    vx = derivative(xs, timestamps)
    vy = derivative(ys, timestamps)
    derivative_speed = [
        math.hypot(vx_i, vy_i) if vx_i is not None and vy_i is not None else float('nan')
        for vx_i, vy_i in zip(vx, vy)
    ]

    return time_since_start, adjacent_speed, derivative_speed


def plot_speed(
    time_since_start: list[float],
    adjacent_speed: list[float],
    derivative_speed: list[float],
    output_path: Path,
) -> None:
    plt.figure(figsize=(10, 4))
    plt.plot(
        time_since_start,
        adjacent_speed,
        marker='o',
        markersize=2,
        linewidth=1,
        label='adjacent difference',
    )
    plt.plot(
        time_since_start,
        derivative_speed,
        marker='.',
        markersize=2,
        linewidth=1,
        label='central derivative',
    )
    plt.title("Ego speed comparison for Rec_Drv_GER_MACHET18_20260319_152119")
    plt.xlabel("Time since start (s)")
    plt.ylabel("Speed (m/s)")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.show()


def main() -> None:
    trajectory_path = DATA_RAW / "Rec_Drv_GER_MACHET18_20260319_152119" / "traj_lcs.txt"
    if not trajectory_path.exists():
        raise FileNotFoundError(
            f"Trajectory file not found: {trajectory_path}\n"
            "Please update MS_ODD_DATA_ROOT or add the recording under its 01_raw folder."
        )

    rows = read_trajectory(trajectory_path)
    time_since_start, adjacent_speed, derivative_speed = compute_speed(rows)

    print("time_since_start_s,adjacent_speed_mps,derivative_speed_mps")
    for t, sa, sd in zip(time_since_start, adjacent_speed, derivative_speed):
        print(f"{t:.6f},{sa:.6f},{sd:.6f}")

    plot_speed(
        time_since_start,
        adjacent_speed,
        derivative_speed,
        Path("speed_plot_Rec_Drv_GER_MACHET18_152119_comparison.png"),
    )


if __name__ == "__main__":
    main()
