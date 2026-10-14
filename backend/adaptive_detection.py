"""Environment-aware sequential evidence policy for timing measurements.

The policy is deliberately separated from measurement code.  It consumes the
same reports produced by ``software_service.measure`` and only decides whether
to stop, continue, or downgrade the evidence.  This keeps the established
fixed-size detector available as an explicit comparison baseline.
"""

from __future__ import annotations

import math
from pathlib import Path


FIXED_REFERENCE_PAIRS = 30_000  # 10,000 pairs x 3 independent rounds


def schedule_for_environment(environment: dict) -> list[int]:
    """Select a predeclared sample schedule from the native jitter probe."""
    ratio = float(environment["native_probe"]["p95_over_median"])
    if ratio <= 1.20:
        return [1_000, 3_000, 10_000]
    if ratio <= 1.50:
        return [3_000, 5_000, 10_000]
    return [5_000, 10_000, 10_000]


def evidence_row(report: dict) -> dict:
    analysis = report["analysis"]
    verdict = report["statistics"]["verdict"]
    difference = float(analysis["paired_mean_difference_ns"])
    interval = [float(v) for v in analysis["paired_difference_ci95_ns"]]
    relative = float(analysis["relative_mean_difference_percent"])
    significant = bool(verdict["statistically_significant"])
    tests_agree = bool(verdict["tests_agree"])
    practical = abs(relative) >= 1.0 or abs(difference) >= 50.0
    return {
        "pairs": int(report["pairs"]),
        "seed": int(report["seed"]),
        "mean_difference_ns": difference,
        "normal_mean_ns": float(analysis["valid"]["mean_ns"]),
        "changed_mean_ns": float(analysis["changed"]["mean_ns"]),
        "ci95_ns": interval,
        "relative_difference_percent": relative,
        "statistically_significant": significant,
        "tests_agree": tests_agree,
        "practically_relevant": practical,
        "direction": 1 if difference > 0 else (-1 if difference < 0 else 0),
        "cpu_migrations": int(report["cpu_migrations"]),
        "report_json": report["report_json"],
        "raw_csv": report["raw_csv"],
    }


def _same_direction(rows: list[dict]) -> bool:
    directions = [r["direction"] for r in rows]
    return bool(directions) and 0 not in directions and len(set(directions)) == 1


def decide(stages: list[dict], formal_environment: bool, final: bool = False) -> dict:
    """Return a transparent stop/continue decision from accumulated stages."""
    runs = [s["run"] for s in stages]
    controls = [s["control"] for s in stages]
    recent_runs = runs[-2:]
    recent_controls = controls[-2:]
    systematic_control = (
        len(recent_controls) == 2
        and all(r["statistically_significant"] and r["tests_agree"] for r in recent_controls)
        and _same_direction(recent_controls)
    )
    stable_difference = (
        len(recent_runs) == 2
        and all(r["statistically_significant"] and r["tests_agree"] and r["practically_relevant"] for r in recent_runs)
        and _same_direction(recent_runs)
        and not systematic_control
    )
    recent_three = runs[-3:]
    stable_null = (
        len(recent_three) == 3
        and all((not r["statistically_significant"]) and r["tests_agree"] for r in recent_three)
        and not systematic_control
    )
    migrations = any(r["cpu_migrations"] for r in runs + controls)
    formal = formal_environment and not migrations and not systematic_control

    if systematic_control:
        conclusion = "同输入对照连续出现同方向偏移，证据不足"
        action = "stop" if final else "continue"
        reason = "A/A对照提示系统测量偏移"
    elif stable_difference:
        conclusion = "序贯证据重复观察到同方向差异"
        action = "stop"
        reason = "连续两个独立阶段统计显著、检验一致、方向一致且达到实际意义阈值"
    elif stable_null:
        conclusion = "序贯证据未观察到稳定差异"
        action = "stop"
        reason = "最近三个独立阶段均未显著且统计检验一致"
    elif final:
        conclusion = "序贯证据不足，需要人工复核或追加实验"
        action = "stop"
        reason = "达到预设最大样本预算后仍未形成一致证据"
    else:
        conclusion = "证据累积中"
        action = "continue"
        reason = "当前阶段不足以形成重复、同方向的正式结论"

    return {
        "action": action,
        "conclusion": conclusion,
        "reason": reason,
        "formal": formal,
        "stable_difference": stable_difference,
        "stable_null": stable_null,
        "systematic_control": systematic_control,
        "stage_count": len(stages),
    }


def resource_summary(stages: list[dict]) -> dict:
    used = sum(int(s["pairs"]) for s in stages)
    saving = 100.0 * (1.0 - used / FIXED_REFERENCE_PAIRS)
    return {
        "adaptive_pairs": used,
        "fixed_reference_pairs": FIXED_REFERENCE_PAIRS,
        "pair_saving_percent": saving,
        "adaptive_control_pairs": used,
        "fixed_reference_control_pairs": FIXED_REFERENCE_PAIRS,
        "comparison_basis": "固定方法10000对×3轮；两种方法均包含同规模A/A对照，故按分类配对数比较",
    }


def plot_report(result: dict, output: Path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stages = result["stages"]
    labels = [f"S{i + 1}\n{stage['pairs']:,} pairs" for i, stage in enumerate(stages)]
    means = [stage["run"]["mean_difference_ns"] for stage in stages]
    lows = [stage["run"]["ci95_ns"][0] for stage in stages]
    highs = [stage["run"]["ci95_ns"][1] for stage in stages]
    cumulative = []
    total = 0
    for stage in stages:
        total += stage["pairs"]
        cumulative.append(total)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    yerr = [[m - lo for m, lo in zip(means, lows)], [hi - m for m, hi in zip(means, highs)]]
    axes[0].errorbar(range(len(stages)), means, yerr=yerr, fmt="o-", capsize=7, color="#4b5563")
    axes[0].axhline(0, color="#999999", linestyle="--", linewidth=1)
    axes[0].set_xticks(range(len(stages)), labels)
    axes[0].set_ylabel("Paired mean difference (ns)")
    axes[0].set_title("Sequential evidence and 95% confidence intervals")

    axes[1].step(range(len(stages)), cumulative, where="mid", color="#4b5563", linewidth=2, label="Adaptive")
    axes[1].axhline(FIXED_REFERENCE_PAIRS, color="#9ca3af", linestyle="--", label="Fixed 10,000 × 3")
    axes[1].fill_between(range(len(stages)), cumulative, alpha=0.15, color="#4b5563")
    axes[1].set_xticks(range(len(stages)), labels)
    axes[1].set_ylabel("Cumulative paired samples")
    axes[1].set_title("Automatically allocated sample budget")
    axes[1].legend()
    verdict = "stable difference" if result["decision"]["stable_difference"] else ("no stable difference" if result["decision"]["stable_null"] else "inconclusive")
    fig.suptitle(result["target_id"] + " / ML-KEM-" + result["level"] + "\nSequential verdict: " + verdict)
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return str(output)
