from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["axes.unicode_minus"] = False
    return plt


def chart_timing(data: dict[str, Any], out_dir: Path) -> Path:
    plt = setup_matplotlib()
    labels = ["baseline"]
    diffs = [data["timing"]["baseline"]["analysis"]["paired_mean_difference_ns"]]
    distinguishable = [data["timing"]["baseline"]["analysis"]["statistically_distinguishable"]]
    for target_id, result in data["timing"]["contrasts"].items():
        labels.append(target_id)
        diffs.append(result["analysis"]["paired_mean_difference_ns"])
        distinguishable.append(result["analysis"]["statistically_distinguishable"])
    colors = ["#dc2626" if x else "#16a34a" for x in distinguishable]
    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    bars = ax.bar(labels, diffs, color=colors)
    ax.axhline(0, color="#111827", linewidth=1)
    ax.set_title("Timing Detection: Paired Mean Difference")
    ax.set_ylabel("Changed - Normal (ns)")
    ax.set_xlabel("Target implementation")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.tick_params(axis="x", rotation=25)
    for bar, value, flag in zip(bars, diffs, distinguishable):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:.1f} ns\n{'dist.' if flag else 'not dist.'}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
        )
    fig.tight_layout()
    path = out_dir / "chart_timing_detection.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    return path


def chart_input_classification(data: dict[str, Any], out_dir: Path) -> Path:
    plt = setup_matplotlib()
    cls = data["input_classification"]["class_summary"]
    order = ["normal", "changed_first", "changed_mid", "changed_last"]
    means = [cls[x]["mean_ns"] for x in order]
    p50 = [cls[x]["p50_ns"] for x in order]
    p95 = [cls[x]["p95_ns"] for x in order]
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    x = range(len(order))
    ax.plot(x, means, marker="o", linewidth=2.6, label="mean")
    ax.plot(x, p50, marker="s", linewidth=2.2, label="p50")
    ax.plot(x, p95, marker="^", linewidth=2.2, label="p95")
    ax.set_xticks(list(x))
    ax.set_xticklabels(order)
    ax.set_title("Input Classification Timing Statistics")
    ax.set_ylabel("Time (ns)")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    for i, value in enumerate(means):
        ax.text(i, value, f"{value:.1f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    path = out_dir / "chart_input_classification.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    return path


def chart_repair(data: dict[str, Any], out_dir: Path) -> Path:
    plt = setup_matplotlib()
    summary = data["repair_closure"]["summary"]
    labels = ["before repair", "after repair"]
    values = [summary["before_diff_ns"], summary["after_diff_ns"]]
    flags = [summary["before_distinguishable"], summary["after_distinguishable"]]
    colors = ["#dc2626" if x else "#16a34a" for x in flags]
    fig, ax = plt.subplots(figsize=(8.8, 5.8))
    bars = ax.bar(labels, values, color=colors, width=0.48)
    ax.axhline(0, color="#111827", linewidth=1)
    ax.set_title("Repair Closure: Before vs After")
    ax.set_ylabel("Changed - Normal (ns)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    for bar, value, flag in zip(bars, values, flags):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:.2f} ns\n{'distinguishable' if flag else 'not distinguishable'}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=10,
        )
    fig.tight_layout()
    path = out_dir / "chart_repair_closure.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    return path


def chart_cross_parameter(data: dict[str, Any], out_dir: Path) -> Path:
    plt = setup_matplotlib()
    rows = data["cross_parameter_validation"]
    baseline = [r for r in rows if r["target_id"] == "mlkem_native_baseline"]
    contrast = [r for r in rows if r["target_id"] != "mlkem_native_baseline"]
    levels = [r["level"] for r in baseline]
    base_values = [r["paired_mean_difference_ns"] for r in baseline]
    con_values = [r["paired_mean_difference_ns"] for r in contrast]
    x = range(len(levels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10, 6.2))
    ax.bar([i - width / 2 for i in x], base_values, width=width, label="baseline", color="#16a34a")
    ax.bar([i + width / 2 for i in x], con_values, width=width, label="contrast", color="#dc2626")
    ax.axhline(0, color="#111827", linewidth=1)
    ax.set_xticks(list(x))
    ax.set_xticklabels(levels)
    ax.set_title("Cross-Parameter Timing Stability")
    ax.set_ylabel("Changed - Normal (ns)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend()
    for i, value in enumerate(base_values):
        ax.text(i - width / 2, value, f"{value:.1f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=9)
    for i, value in enumerate(con_values):
        ax.text(i + width / 2, value, f"{value:.1f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=9)
    fig.tight_layout()
    path = out_dir / "chart_cross_parameter.png"
    fig.savefig(path, dpi=240)
    plt.close(fig)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PNG charts from proof_suite_result.json.")
    parser.add_argument("proof_json", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    data = load_json(args.proof_json)
    out_dir = args.out_dir or args.proof_json.parent / "charts_png"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        chart_timing(data, out_dir),
        chart_input_classification(data, out_dir),
        chart_repair(data, out_dir),
        chart_cross_parameter(data, out_dir),
    ]
    print("generated charts:")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
