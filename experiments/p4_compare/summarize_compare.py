#!/usr/bin/env python3
"""汇总 P4 三组对照复测：检测能力 + 性能开销。

用 backend/stats.py 的分析口径逐轮计算，再按目标聚合。只依赖标准库。

用法：
    python3 experiments/p4_compare/summarize_compare.py [项目根目录]

对应竞赛题目要求 7（防护效果验证）与要求 8（性能要求）：
- 表 1 给检测能力：每轮配对检验是否判出差异，以及差异的大小与置信区间；
- 表 2 给解封装耗时分布（均值、中位数、P90/P95/P99、标准差）；
- 表 3 给相对基线实现的性能开销。
"""

import glob
import os
import re
import statistics
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SCRIPT_DIR.parents[1]

sys.path.insert(0, str(BASE / "backend"))
sys.path.insert(0, str(SCRIPT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

import stats  # noqa: E402

OUT = BASE / "results" / "p4_compare"
LEVEL = "512"

LABELS = {
    "mlkem_native_baseline": "平台基线实现",
    "variant_early_return": "对照实现(早退比较)",
    "variant_fixed": "修复实现(固定流程)",
}
ORDER = ["mlkem_native_baseline", "variant_early_return", "variant_fixed"]


def main():
    files = sorted(glob.glob(str(OUT / "*.csv")))
    if not files:
        print("没有找到 %s/*.csv" % OUT)
        return 1

    per_target = {}
    for path in files:
        match = re.match(r"(.+)-r(\d+)\.csv$", Path(path).name)
        if not match:
            print("跳过无法解析的文件名：%s" % Path(path).name)
            continue
        target, round_number = match.group(1), int(match.group(2))
        try:
            result = stats.analyze_file(path)
        except Exception as error:
            print("%s 分析失败：%s" % (Path(path).name, error))
            continue
        per_target.setdefault(target, []).append(
            {
                "round": round_number,
                "paired": result["paired"],
                "a": result["class_a"],
                "verdict": result["verdict"],
                "t": result["paired"]["difference_t_test"],
                "w": result["paired"]["difference_wilcoxon"],
            }
        )

    print("=" * 108)
    print("表 1  检测能力：每个目标每一轮的配对分析（差值 = 变化输入 − 正常输入）")
    print("=" * 108)
    print(
        "%-24s %3s %7s %13s %24s %11s %11s %s"
        % ("目标", "轮", "配对数", "块平衡均值差ns", "95%区间ns", "配对t p", "Wilcoxon p", "判定")
    )
    print("-" * 108)
    for target in ORDER:
        rows = sorted(per_target.get(target, []), key=lambda item: item["round"])
        if not rows:
            continue
        for row in rows:
            paired, t_test = row["paired"], row["t"]
            low, high = paired["paired_difference_ci_ns"]
            print(
                "%-24s %3d %7d %13.2f %11.2f ~ %10.2f %11.3g %11.3g %s"
                % (
                    LABELS.get(target, target),
                    row["round"],
                    row["a"]["count"],
                    paired["paired_mean_difference_ns"],
                    low,
                    high,
                    t_test["p_value"] if t_test else float("nan"),
                    row["w"]["p_value"],
                    "存在差异" if row["verdict"]["statistically_significant"] else "未检出",
                )
            )
        diffs = [r["paired"]["paired_mean_difference_ns"] for r in rows]
        detected = sum(1 for r in rows if r["verdict"]["statistically_significant"])
        print(
            "%-24s 平均 %13.2f ns   检出 %d/%d 轮"
            % ("  ↳ 汇总", statistics.fmean(diffs), detected, len(rows))
        )
        print()

    print("=" * 108)
    print("表 2  性能：正常输入（未篡改密文）的解封装耗时分布，参数集 ML-KEM-%s" % LEVEL)
    print("=" * 108)
    print(
        "%-24s %12s %12s %12s %12s %12s %12s"
        % ("目标", "均值ns", "中位数ns", "P90ns", "P95ns", "P99ns", "标准差ns")
    )
    print("-" * 108)
    means = {}
    for target in ORDER:
        rows = per_target.get(target, [])
        if not rows:
            continue
        summaries = [r["a"] for r in rows]
        means[target] = statistics.fmean(s["mean_ns"] for s in summaries)
        print(
            "%-24s %12.1f %12.1f %12.1f %12.1f %12.1f %12.1f"
            % (
                LABELS.get(target, target),
                means[target],
                statistics.fmean(s["p50_ns"] for s in summaries),
                statistics.fmean(s["p90_ns"] for s in summaries),
                statistics.fmean(s["p95_ns"] for s in summaries),
                statistics.fmean(s["p99_ns"] for s in summaries),
                statistics.fmean(s["stddev_ns"] for s in summaries),
            )
        )
    print()

    baseline = means.get("mlkem_native_baseline")
    if baseline:
        print("=" * 108)
        print("表 3  相对基线实现的性能开销")
        print("=" * 108)
        print("%-24s %14s %14s" % ("目标", "均值差ns", "相对开销"))
        print("-" * 108)
        for target in ORDER:
            if target not in means:
                continue
            delta = means[target] - baseline
            print("%-24s %14.1f %13.2f%%" % (LABELS.get(target, target), delta, 100.0 * delta / baseline))
        print()

    env_path = OUT / "env.txt"
    if env_path.is_file():
        print("=" * 108)
        print("实验环境")
        print("=" * 108)
        print(env_path.read_text(encoding="utf-8").strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
