from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from software_service import detect, make_samples, validate_basic


CASES = [
    ("mlkem_native_baseline", "规范基线"),
    ("case_compare_early", "比较提前结束"),
    ("case_conditional_failure", "条件失败路径"),
    ("case_variable_loop", "数据相关循环"),
    ("case_memory_index", "数据相关访存"),
    ("case_conditional_branch", "条件分支"),
    ("case_variable_division", "运行期除法路径"),
]
LEVELS = ("512", "768", "1024")


def write_log(path: Path, report: dict) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S,000")
    prefix = f"{stamp} - __main__ - INFO - "
    lines = [
        "nohup: ignoring input",
        prefix + "=" * 82,
        prefix + "实验八：七目标 × 三参数集稳定性验证",
        prefix + "=" * 82,
        prefix + f"固定 CPU：{report['cpu']}",
        prefix + f"每轮配对次数：{report['pairs_per_round']}",
        prefix + f"独立重复轮数：{report['repeats']}",
        prefix + f"目标数量：{len(CASES)}；参数集数量：{len(LEVELS)}",
        prefix + "-" * 82,
    ]
    for row in report["rows"]:
        rounds = ", ".join(f"{x:.2f}" for x in row["round_differences_ns"])
        lines.append(
            prefix
            + f"{row['target_id']} / ML-KEM-{row['level']}: "
            + f"mean_diff={row['mean_difference_ns']:.2f} ns; "
            + f"rounds=[{rounds}]; conclusion={row['conclusion']}; "
            + f"formal={row['formal_environment']}; A/A={row['same_input_control_passed']}"
        )
    lines += [
        "",
        "评估指标：",
        "----------------------------------------------------------------------------------",
        f"functional_pass          : {report['functional_pass_count']}/{len(report['rows'])}",
        f"formal_admitted          : {report['formal_count']}/{len(report['rows'])}",
        f"baseline_not_detected     : {report['baseline_expected_count']}/{len(LEVELS)}",
        f"controlled_detected       : {report['controlled_expected_count']}/{6 * len(LEVELS)}",
        f"overall_success           : {report['success']}",
        f"JSON                      : {report['report_json']}",
        f"chart                     : {report['chart_png']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def draw_chart(path: Path, rows: list[dict]) -> None:
    names = [
        "Baseline", "Compare exit", "Failure path", "Variable loop",
        "Memory access", "Conditional branch", "Division path",
    ]
    colors = {"512": "#3B4A5A", "768": "#7B8794", "1024": "#B9C0C7"}
    fig, axes = plt.subplots(2, 1, figsize=(13.2, 9.4), layout="constrained")

    ax = axes[0]
    width = 0.24
    xs = list(range(len(CASES)))
    for offset, level in zip((-width, 0, width), LEVELS):
        vals = []
        for target_id, _ in CASES:
            row = next(r for r in rows if r["target_id"] == target_id and r["level"] == level)
            vals.append(abs(row["mean_difference_ns"]))
        ax.bar([x + offset for x in xs], vals, width, label=f"ML-KEM-{level}", color=colors[level])
    ax.set_yscale("log")
    ax.set_ylabel("Absolute mean difference across 3 rounds (ns, log scale)")
    ax.set_title("Timing differences across seven targets and three parameter sets")
    ax.set_xticks(xs, names, rotation=16, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.legend(frameon=False, ncol=3)

    ax = axes[1]
    matrix = []
    for target_id, _ in CASES:
        row_values = []
        for level in LEVELS:
            row = next(r for r in rows if r["target_id"] == target_id and r["level"] == level)
            expected = (
                row["conclusion"] == "本次各轮未检出显著差异"
                if target_id == "mlkem_native_baseline"
                else row["conclusion"] == "重复观察到同方向差异"
            )
            row_values.append(1 if expected and row["formal_environment"] else 0)
        matrix.append(row_values)
    im = ax.imshow(matrix, cmap=matplotlib.colors.ListedColormap(["#D9DDE1", "#3F4A54"]), vmin=0, vmax=1, aspect="auto")
    ax.set_yticks(range(len(names)), names)
    ax.set_xticks(range(3), [f"ML-KEM-{x}" for x in LEVELS])
    ax.set_title("Expected verdict and formal-timing admission")
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            ax.text(j, i, "PASS" if value else "REVIEW", ha="center", va="center", color="white" if value else "#222222", fontweight="bold")
    fig.savefig(path, dpi=220, facecolor="white")
    plt.close(fig)


def main() -> int:
    pairs = int(os.environ.get("CROSS_PARAMETER_PAIRS", "10000"))
    repeats = int(os.environ.get("CROSS_PARAMETER_REPEATS", "3"))
    cpu = min(os.sched_getaffinity(0))
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "results" / "final_experiments" / f"{run_id}-cross-parameter"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "kind": "seven-target-cross-parameter-validation",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cpu": cpu,
        "pairs_per_round": pairs,
        "repeats": repeats,
        "rows": [],
    }

    samples = {level: make_samples("mlkem_native_baseline", level, 512) for level in LEVELS}
    report["sample_reports"] = {level: data["report_json"] for level, data in samples.items()}
    for target_id, name in CASES:
        basic = validate_basic(target_id, list(LEVELS), 100)
        for level in LEVELS:
            print(f"[START] {target_id} ML-KEM-{level}", flush=True)
            result = detect(target_id, level, samples[level]["report_json"], pairs, cpu, repeats, 2)
            diffs = [r["analysis"]["paired_mean_difference_ns"] for r in result["runs"]]
            row = {
                "target_id": target_id,
                "name": name,
                "level": level,
                "basic_success": basic["success"],
                "formal_environment": result["formal_environment"],
                "same_input_control_passed": result["same_input_control_passed"],
                "conclusion": result["conclusion"],
                "round_differences_ns": diffs,
                "mean_difference_ns": statistics.mean(diffs),
                "stdev_difference_ns": statistics.stdev(diffs) if len(diffs) > 1 else 0.0,
                "report_json": result["report_json"],
            }
            report["rows"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    report["functional_pass_count"] = sum(1 for r in report["rows"] if r["basic_success"])
    report["formal_count"] = sum(1 for r in report["rows"] if r["formal_environment"])
    report["baseline_expected_count"] = sum(
        1 for r in report["rows"]
        if r["target_id"] == "mlkem_native_baseline" and r["conclusion"] == "本次各轮未检出显著差异"
    )
    report["controlled_expected_count"] = sum(
        1 for r in report["rows"]
        if r["target_id"] != "mlkem_native_baseline" and r["conclusion"] == "重复观察到同方向差异"
    )
    report["success"] = (
        report["functional_pass_count"] == len(report["rows"])
        and report["formal_count"] == len(report["rows"])
        and report["baseline_expected_count"] == len(LEVELS)
        and report["controlled_expected_count"] == 6 * len(LEVELS)
    )
    report_path = out_dir / "report.json"
    chart_path = out_dir / "cross-parameter-stability.png"
    report["report_json"] = str(report_path)
    report["chart_png"] = str(chart_path)
    draw_chart(chart_path, report["rows"])
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_log(out_dir / "experiment-08-cross-parameter.log", report)
    print(json.dumps({"success": report["success"], "report": str(report_path), "chart": str(chart_path)}, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
