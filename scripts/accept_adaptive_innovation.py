"""Reproducible comparison of fixed and adaptive detection policies."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from software_service import BUILTINS, adaptive_detect, detect, make_samples


def main() -> int:
    cpu = min(__import__("os").sched_getaffinity(0))
    level = "768"
    rows = []
    output = ROOT / "results" / "innovation" / time.strftime("%Y%m%d-%H%M%S-adaptive-comparison")
    output.mkdir(parents=True, exist_ok=False)
    for target_id in BUILTINS:
        samples = make_samples(target_id, level, 512)
        fixed_attempts = [detect(target_id, level, samples["report_json"], 10_000, cpu, 3, 2, False)]
        while not fixed_attempts[-1]["formal_environment"] and len(fixed_attempts) < 3:
            fixed_attempts.append(detect(target_id, level, samples["report_json"], 10_000, cpu, 3, 2, False))
        fixed = next((item for item in fixed_attempts if item["formal_environment"]), fixed_attempts[-1])
        adaptive_attempts = [adaptive_detect(target_id, level, samples["report_json"], cpu, 2)]
        while not adaptive_attempts[-1]["decision"]["formal"] and len(adaptive_attempts) < 3:
            adaptive_attempts.append(adaptive_detect(target_id, level, samples["report_json"], cpu, 2))
        adaptive = next((item for item in adaptive_attempts if item["decision"]["formal"]), adaptive_attempts[-1])
        fixed_detected = fixed["conclusion"] == "重复观察到同方向差异"
        adaptive_detected = adaptive["decision"]["stable_difference"]
        expected = target_id != "mlkem_native_baseline"
        rows.append({
            "target_id": target_id,
            "expected_difference": expected,
            "fixed_conclusion": fixed["conclusion"],
            "adaptive_conclusion": adaptive["conclusion"],
            "fixed_detected": fixed_detected,
            "adaptive_detected": adaptive_detected,
            "conclusion_agreement": fixed_detected == adaptive_detected,
            "adaptive_correct": adaptive_detected == expected,
            "adaptive_pairs": adaptive["resources"]["adaptive_pairs"],
            "fixed_pairs": adaptive["resources"]["fixed_reference_pairs"],
            "saving_percent": adaptive["resources"]["pair_saving_percent"],
            "formal": fixed["formal_environment"] and adaptive["decision"]["formal"],
            "fixed_attempt_reports": [item["report_json"] for item in fixed_attempts],
            "adaptive_attempt_reports": [item["report_json"] for item in adaptive_attempts],
            "environment_retest_policy": "固定或自适应批次未通过既定环境门槛时，最多执行两次独立重测；所有尝试均保留，选择首个正式批次用于对照。",
            "fixed_report": fixed["report_json"],
            "adaptive_report": adaptive["report_json"],
        })

    report = {
        "experiment": "环境感知的自适应序贯检测与固定10000对×3轮方法对照",
        "level": "ML-KEM-768",
        "targets": len(rows),
        "fixed_adaptive_agreement": sum(r["conclusion_agreement"] for r in rows) / len(rows),
        "adaptive_accuracy_on_controlled_catalog": sum(r["adaptive_correct"] for r in rows) / len(rows),
        "mean_pair_saving_percent": statistics.fmean(r["saving_percent"] for r in rows),
        "all_formal": all(r["formal"] for r in rows),
        "success": all(r["conclusion_agreement"] and r["adaptive_correct"] and r["formal"] for r in rows),
        "rows": rows,
    }
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "实验十三：环境感知的自适应序贯检测创新模块",
        "=" * 84,
        f"固定与自适应结论一致率：{report['fixed_adaptive_agreement']:.1%}",
        f"受控目录判断正确率：{report['adaptive_accuracy_on_controlled_catalog']:.1%}",
        f"平均配对样本节省率：{report['mean_pair_saving_percent']:.2f}%",
        f"正式证据：{report['all_formal']}",
        "-" * 84,
    ]
    for row in rows:
        lines.append(
            f"{row['target_id']}: fixed={row['fixed_conclusion']}; "
            f"adaptive={row['adaptive_conclusion']}; pairs={row['adaptive_pairs']}/{row['fixed_pairs']}; "
            f"saving={row['saving_percent']:.2f}%; agreement={row['conclusion_agreement']}; "
            f"fixed_attempts={len(row['fixed_attempt_reports'])}; adaptive_attempts={len(row['adaptive_attempt_reports'])}"
        )
    (output / "experiment-13-adaptive-innovation.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [r["target_id"].replace("mlkem_native_", "").replace("case_", "") for r in rows]
    savings = [r["saving_percent"] for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), layout="constrained")
    axes[0].barh(names, savings, color="#4b5563")
    axes[0].axvline(0, color="#999999", linewidth=1)
    axes[0].set_xlabel("Paired-sample reduction versus fixed policy (%)")
    axes[0].set_title("Adaptive sample allocation")
    for i, value in enumerate(savings):
        axes[0].text(value, i, f" {value:.1f}%", va="center")
    matrix = [[int(r["conclusion_agreement"]), int(r["adaptive_correct"]), int(r["formal"])] for r in rows]
    axes[1].imshow(matrix, cmap="Greys", vmin=0, vmax=1, aspect="auto")
    axes[1].set_xticks(range(3), ["Fixed agreement", "Expected result", "Formal evidence"])
    axes[1].set_yticks(range(len(names)), names)
    for i, values in enumerate(matrix):
        for j, value in enumerate(values):
            axes[1].text(j, i, "PASS" if value else "REVIEW", ha="center", va="center", color="white" if value else "black", fontweight="bold")
    axes[1].set_title("Reproducible acceptance matrix")
    fig.suptitle("Environment-aware sequential detection innovation")
    fig.savefig(output / "experiment-13-adaptive-innovation.png", dpi=180)
    plt.close(fig)
    print(json.dumps({"success": report["success"], "output": str(output), "report": str(report_path)}, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
