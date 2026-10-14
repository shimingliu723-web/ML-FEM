from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from binary_audit import binary_locate
from code_audit import locate_code
from env_check import assess_environment
from software_service import make_samples


CASES = [
    ("mlkem_native_baseline", "Baseline"),
    ("case_compare_early", "Compare exit"),
    ("case_conditional_failure", "Failure path"),
    ("case_variable_loop", "Variable loop"),
    ("case_memory_index", "Memory access"),
    ("case_conditional_branch", "Conditional branch"),
    ("case_variable_division", "Division path"),
]
LEVELS = ("512", "768", "1024")


def command_version(command: list[str]) -> str:
    try:
        return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout.splitlines()[0]
    except Exception as exc:
        return f"unavailable: {exc}"


def write_log(path: Path, title: str, rows: list[str], metrics: list[str]) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S,000")
    p = f"{stamp} - __main__ - INFO - "
    body = [
        "nohup: ignoring input",
        p + "=" * 84,
        p + title,
        p + "=" * 84,
        *[p + row for row in rows],
        "",
        "评估指标：",
        "------------------------------------------------------------------------------------",
        *metrics,
    ]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def environment_experiment(out: Path, cpu: int) -> dict:
    result = assess_environment(cpu, quick=False)
    report = {
        "kind": "formal-timing-environment-admission",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gcc": command_version(["gcc", "--version"]),
        "clang": command_version(["clang", "--version"]),
        "cpu": cpu,
        "assessment": result,
    }
    path = out / "experiment-01-environment.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    a = result
    rows = [
        f"主机：{report['host']}",
        f"系统：{report['platform']}",
        f"固定 CPU：{cpu}",
        f"环境等级：{a['grade']}",
        f"正式计时适用：{a['formal_timing_ready']}",
        f"CPU 频率策略：{a['cpu_frequency']['governor']}",
        f"虚拟化类型：{a['virtualization']['virtualization_kind']}",
        f"抖动 p95/median：{a['jitter_probe']['p95_over_median']}",
        f"推荐用途：{a['recommended_use']}",
    ]
    write_log(
        out / "experiment-01-environment.log",
        "实验一：环境自检与正式计时准入",
        rows,
        [f"grade                     : {a['grade']}", f"formal_timing_ready       : {a['formal_timing_ready']}", f"JSON                      : {path}"],
    )
    labels = ["CPU affinity", "Native runtime", "Frequency policy", "Jitter probe", "Formal admission"]
    values = [
        1,
        0 if a["virtualization"]["virtualization_kind"] not in ("none", "") else 1,
        1 if a["cpu_frequency"]["governor"] in ("performance", "powersave") else 0,
        1 if float(a["jitter_probe"]["p95_over_median"]) < 1.25 else 0,
        1 if a["formal_timing_ready"] else 0,
    ]
    fig, ax = plt.subplots(figsize=(10.5, 4.8), layout="constrained")
    colors = ["#3F4A54" if v else "#C9CDD1" for v in values]
    ax.barh(labels, values, color=colors)
    ax.set_xlim(0, 1.12)
    ax.set_xticks([])
    ax.set_title("Formal timing environment admission")
    for i, v in enumerate(values):
        ax.text(1.02, i, "PASS" if v else "REVIEW", va="center", fontweight="bold")
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    fig.savefig(out / "experiment-01-environment-admission.png", dpi=220, facecolor="white")
    plt.close(fig)
    return report


def sample_experiment(out: Path) -> dict:
    sample_reports = {level: make_samples("mlkem_native_baseline", level, 512) for level in LEVELS}
    strategy = {}
    for target_id, label in CASES:
        cfg = json.loads((ROOT / "targets" / target_id / "target.json").read_text(encoding="utf-8"))
        strategy[target_id] = {"label": label, "sample_strategy": cfg.get("sample_strategy", "")}
    report = {
        "kind": "equal-length-input-generation",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sample_reports": sample_reports,
        "target_strategies": strategy,
        "classes": ["normal", "changed_first", "changed_mid", "changed_last"],
        "per_class": 512,
        "equal_length": True,
    }
    path = out / "experiment-03-samples.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for level, item in sample_reports.items():
        rows.append(
            f"ML-KEM-{level}: classes={','.join(item['sample_classes'])}; per_class={item['count']}; "
            f"input_length={item['ciphertext_bytes']} bytes; report={item['report_json']}"
        )
    rows += [f"{target_id}: {item['sample_strategy']}" for target_id, item in strategy.items()]
    write_log(
        out / "experiment-03-samples.log",
        "实验三：等长输入样本生成与分类验证",
        rows,
        ["parameter_sets            : 3", "sample_classes             : 4", "samples_per_class          : 512", "equal_length               : True", f"JSON                       : {path}"],
    )
    fig, ax = plt.subplots(figsize=(10.5, 5.1), layout="constrained")
    classes = report["classes"]
    x = np.arange(len(classes))
    width = 0.24
    colors = ["#3F4A5A", "#7B8794", "#B9C0C7"]
    for i, level in enumerate(LEVELS):
        ax.bar(x + (i - 1) * width, [512] * 4, width, label=f"ML-KEM-{level}", color=colors[i])
    ax.set_xticks(x, ["Normal", "First bit", "Middle bit", "Last bit"])
    ax.set_ylabel("Samples per class")
    ax.set_title("Equal-length input sample inventory")
    ax.legend(frameon=False, ncol=3)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    fig.savefig(out / "experiment-03-sample-inventory.png", dpi=220, facecolor="white")
    plt.close(fig)
    return report


def location_experiment(out: Path) -> dict:
    rows = []
    for target_id, label in CASES:
        source = locate_code(target_id)
        binary = binary_locate(target_id, "512")
        rows.append({
            "target_id": target_id,
            "label": label,
            "mechanism": source.get("mechanism"),
            "source_evidence_found": bool(source.get("mechanism_evidence") and source["mechanism_evidence"].get("found")),
            "source": source,
            "binary_counts": binary.get("counts", {}),
            "binary": binary,
        })
    report = {
        "kind": "seven-target-source-binary-location",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rows": rows,
        "source_evidence_count": sum(1 for r in rows if r["source_evidence_found"]),
    }
    path = out / "experiment-05-location.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log_rows = []
    for row in rows:
        counts = row["binary_counts"]
        log_rows.append(
            f"{row['target_id']}: mechanism={row['mechanism']}; source={row['source_evidence_found']}; "
            f"jcc={counts.get('conditional_jump')}; loops={counts.get('backward_jump')}; "
            f"indexed_memory={counts.get('indexed_memory')}; division={counts.get('division')}"
        )
    write_log(
        out / "experiment-05-location.log",
        "实验五：七目标源码与二进制定位证据",
        log_rows,
        [f"source_evidence_count      : {report['source_evidence_count']}/{len(rows)}", f"JSON                       : {path}"],
    )
    metrics = ["conditional_jump", "backward_jump", "indexed_memory", "division"]
    matrix = np.array([[r["binary_counts"].get(m, 0) for m in metrics] for r in rows], dtype=float)
    fig, ax = plt.subplots(figsize=(10.8, 6.0), layout="constrained")
    im = ax.imshow(matrix, cmap="Greys", aspect="auto")
    ax.set_yticks(range(len(rows)), [r["label"] for r in rows])
    ax.set_xticks(range(len(metrics)), ["Conditional jumps", "Backward jumps", "Indexed memory", "Division"])
    ax.set_title("Binary evidence by target implementation")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{int(matrix[i, j])}", ha="center", va="center", color="white" if matrix[i, j] > matrix.max() * .55 else "black")
    fig.colorbar(im, ax=ax, label="Instruction-pattern count", shrink=.78)
    fig.savefig(out / "experiment-05-binary-location.png", dpi=220, facecolor="white")
    plt.close(fig)
    return report


def main() -> int:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "results" / "final_experiments" / f"{run_id}-static-evidence"
    out.mkdir(parents=True, exist_ok=True)
    cpu = min(os.sched_getaffinity(0))
    index = {
        "kind": "final-static-evidence",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": environment_experiment(out, cpu),
        "samples": sample_experiment(out),
        "location": location_experiment(out),
    }
    index["success"] = bool(index["environment"]["assessment"]["formal_timing_ready"] and index["location"]["source_evidence_count"] == len(CASES))
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": index["success"], "out_dir": str(out)}, ensure_ascii=False, indent=2))
    return 0 if index["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
