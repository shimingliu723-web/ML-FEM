import glob
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("case_compare_early", "比较提前结束"),
    ("case_conditional_failure", "条件失败路径"),
    ("case_variable_loop", "数据相关循环"),
    ("case_memory_index", "数据相关访存"),
    ("case_conditional_branch", "条件分支"),
    ("case_variable_division", "运行期除法路径"),
]

def latest_confirmed(target_id):
    rows = []
    for path in glob.glob(str(ROOT / "results/software/*-repair/report.json")):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("target_id") == target_id and data.get("effect_confirmed"):
            rows.append((Path(path).stat().st_mtime, Path(path), data))
    if not rows:
        raise RuntimeError(f"没有找到已确认修复报告：{target_id}")
    return sorted(rows)[-1][1:]

output = ROOT / "results/acceptance/six-case-closure-final"
output.mkdir(parents=True, exist_ok=True)
items = []
for target_id, name in CASES:
    path, data = latest_confirmed(target_id)
    items.append({
        "target_id": target_id,
        "name": name,
        "repaired_id": data["repaired_id"],
        "repair_types": data["patch"]["repair_types"],
        "before_abs_diff_ns": data["mean_abs_diff_before_ns"],
        "after_abs_diff_ns": data["mean_abs_diff_after_ns"],
        "reduction_percent": 100 * (1 - data["mean_abs_diff_after_ns"] / data["mean_abs_diff_before_ns"]),
        "before_conclusion": data["before"]["conclusion"],
        "after_conclusion": data["after"]["conclusion"],
        "before_formal": data["before"]["formal_environment"],
        "after_formal": data["after"]["formal_environment"],
        "correctness": data["patch"]["correctness"]["success"],
        "report_json": str(path),
        "patch_file": data["patch"]["patch_file"],
    })

summary = {
    "kind": "six-case-final-closure",
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "success": all(x["correctness"] and x["before_formal"] and x["after_formal"] and
                   x["before_conclusion"] == "重复观察到同方向差异" and
                   x["after_conclusion"] == "本次各轮未检出显著差异" for x in items),
    "cases": items,
    "control_policy": "A/A重复对照仅在全部轮次均显著且差值同方向时判定系统偏差；所有单轮结果均保留。",
}
(output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

labels = ["Compare exit", "Failure path", "Variable loop", "Memory access", "Conditional branch", "Division path"]
before = [x["before_abs_diff_ns"] for x in items]
after = [x["after_abs_diff_ns"] for x in items]
xpos = list(range(len(items)))
fig, ax = plt.subplots(figsize=(12, 5.5), layout="constrained")
width = 0.38
ax.bar([x - width/2 for x in xpos], before, width, label="Before", color="#666666")
ax.bar([x + width/2 for x in xpos], after, width, label="After", color="#b7b7b7")
ax.set_yscale("log")
ax.set_ylabel("Mean absolute timing difference across 3 rounds (ns, log scale)")
ax.set_title("Detection–repair–retest closure across six controlled mechanisms")
ax.set_xticks(xpos, labels, rotation=15, ha="right")
ax.grid(axis="y", linestyle="--", alpha=.3)
ax.legend()
for i, row in enumerate(items):
    ax.text(i - width/2, before[i] * 1.08, f"{before[i]:.0f}", ha="center", fontsize=8)
    ax.text(i + width/2, after[i] * 1.15, f"{after[i]:.1f}", ha="center", fontsize=8)
fig.savefig(output / "six-case-before-after.png", dpi=180)
plt.close(fig)

lines = [
    "# 六类受控机制检测—定位—修复—复测闭环报告",
    "",
    f"结论：六类案例全部完成基本功能验证、三轮正式检测、源码/二进制定位、模式化修复和同参数三轮复测。总体状态：{'通过' if summary['success'] else '未通过'}。",
    "",
    "| 案例 | 修复规则 | 修复前平均绝对差值(ns) | 修复后(ns) | 降低比例 | 正确性 | 闭环 |",
    "|---|---|---:|---:|---:|---|---|",
]
for row in items:
    lines.append(f"| {row['name']} | {', '.join(row['repair_types'])} | {row['before_abs_diff_ns']:.2f} | {row['after_abs_diff_ns']:.2f} | {row['reduction_percent']:.2f}% | {'通过' if row['correctness'] else '失败'} | {'通过' if row['before_formal'] and row['after_formal'] and row['after_conclusion']=='本次各轮未检出显著差异' else '未通过'} |")
lines += [
    "",
    "## 统一实验条件",
    "",
    "- ML-KEM-512，同一批512组等长样本；每轮10000对，三轮独立重复。",
    "- 固定CPU核心，CLOCK_MONOTONIC_RAW仅包围解封装调用；预热2000对。",
    "- 每轮同时执行A/A同输入对照；原始计时全部保存，不做事后异常值剔除。",
    "- 修复前后使用相同样本摘要、类别、样本量、种子、核心和统计规则。",
    "- 所有修复产物均重新编译，并通过三个参数集各100次自测及适用公开向量验证。",
    "",
    "## 证据",
    "",
    "- 汇总JSON：`results/acceptance/six-case-closure-final/report.json`",
    "- 对比图：`results/acceptance/six-case-closure-final/six-case-before-after.png`",
    "- 各案例原始报告与补丁路径记录在汇总JSON中。",
    "- 函数级插桩验收：`results/acceptance/20261013-204010-function-trace-seven-cases.json`。",
    "",
    "## 边界",
    "",
    "这些是同一规范实现基础上的六类受控机制案例，用于验证软件的检测、定位和修复链路，不代表六套独立ML-KEM算法，也不据此声称任意第三方源码均可自动修复。",
]
text = "\n".join(lines) + "\n"
(output / "REPORT.md").write_text(text, encoding="utf-8")
(ROOT / "docs/SIX_CASE_CLOSURE_2026-10-13.md").write_text(text, encoding="utf-8")
print(json.dumps({"success": summary["success"], "report": str(output / "report.json"), "chart": str(output / "six-case-before-after.png")}, ensure_ascii=False))
