from __future__ import annotations

import csv
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from target_manager import get_target


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "experiments" / "input_classification"
RESULTS = ROOT / "results" / "input_classification"


def _percentile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summary(values: list[int]) -> dict[str, Any]:
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    half = 1.96 * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "mean_ns": mean,
        "stddev_ns": std,
        "p05_ns": _percentile(values, 0.05),
        "p50_ns": _percentile(values, 0.50),
        "p95_ns": _percentile(values, 0.95),
        "ci95_mean_ns": [mean - half, mean + half],
        "minimum_ns": min(values),
        "maximum_ns": max(values),
    }


def _write_svg(path: Path, class_summary: dict[str, dict[str, Any]], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    classes = ["normal", "changed_first", "changed_mid", "changed_last"]
    means = [float(class_summary[name]["mean_ns"]) for name in classes]
    p95s = [float(class_summary[name]["p95_ns"]) for name in classes]
    max_value = max(p95s + [1.0])
    chart_w = 840
    left = 150
    top = 92
    bar_h = 34
    row_h = 74
    height = top + len(classes) * row_h + 78
    rows = []
    for idx, name in enumerate(classes):
        y = top + idx * row_h
        mean_w = means[idx] / max_value * chart_w
        p95_w = p95s[idx] / max_value * chart_w
        color = "#2563eb" if name == "normal" else "#f97316"
        rows.append(
            f'<text x="32" y="{y + 25}" class="label">{name}</text>'
            f'<rect x="{left}" y="{y + 4}" width="{p95_w:.1f}" height="{bar_h}" rx="6" fill="#dbeafe"/>'
            f'<rect x="{left}" y="{y + 10}" width="{mean_w:.1f}" height="{bar_h - 12}" rx="5" fill="{color}"/>'
            f'<text x="{left + chart_w + 20}" y="{y + 25}" class="value">mean {means[idx]:.1f} ns / p95 {p95s[idx]:.1f} ns</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1220" height="{height}" viewBox="0 0 1220 {height}">
<style>
text {{ font-family: Arial, 'Noto Sans CJK SC', sans-serif; fill:#111827; }}
.title {{ font-size:25px; font-weight:700; }}
.small {{ font-size:13px; fill:#64748b; }}
.label {{ font-size:17px; font-weight:700; }}
.value {{ font-size:16px; }}
</style>
<rect width="1220" height="{height}" fill="#ffffff"/>
<text x="32" y="42" class="title">{title}</text>
<text x="32" y="70" class="small">深色条为均值，浅色背景条为 p95；四类输入长度相同，差别仅为固定位置 1 bit 改动。</text>
{''.join(rows)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def run_input_classification(
    level: str,
    samples: int = 512,
    repeats: int = 10000,
    cpu: int = 0,
    target_id: str = "variant_early_return",
) -> dict[str, Any]:
    if level not in {"512", "768", "1024"}:
        raise ValueError("参数集必须为512、768或1024")
    if not 1 <= samples <= 4096:
        raise ValueError("samples 必须在 1 到 4096 之间")
    if not 100 <= repeats <= 1000000:
        raise ValueError("repeats 必须在 100 到 1000000 之间")
    allowed = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else set(range(os.cpu_count() or 1))
    if cpu not in allowed:
        raise ValueError(f"CPU {cpu} 不在本进程可用核心范围内")
    if not BINARY.is_file():
        raise RuntimeError("请先执行 make all 或 make input-classification")
    target = get_target(target_id)
    library = target.library_for(level)
    if not library.is_file():
        raise RuntimeError(f"目标库不存在：{library}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06d}"
    csv_path = RESULTS / f"{run_id}.csv"
    command = [str(BINARY), str(library), level, str(samples), str(repeats), str(csv_path)]
    if shutil.which("taskset"):
        command = ["taskset", "-c", str(cpu)] + command
    started = time.perf_counter()
    proc = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "输入分类计时程序执行失败")

    values: dict[str, list[int]] = {}
    with csv_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            values.setdefault(row["class_name"], []).append(int(row["elapsed_ns"]))
    class_summary = {name: _summary(vals) for name, vals in sorted(values.items())}
    normal_mean = class_summary.get("normal", {}).get("mean_ns", 0.0)
    for name, summary in class_summary.items():
        summary["mean_delta_vs_normal_ns"] = summary["mean_ns"] - normal_mean

    chart = csv_path.with_suffix(".svg")
    _write_svg(chart, class_summary, f"输入分类计时统计 / {target_id} / ML-KEM-{level}")
    result = {
        "target_id": target_id,
        "target_name": target.name,
        "level": f"ML-KEM-{level}",
        "samples_per_class": samples,
        "repeats": repeats,
        "measurements_per_class": {name: len(vals) for name, vals in values.items()},
        "cpu": cpu if shutil.which("taskset") else None,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "input_definition": {
            "normal": "正常生成的固定长度输入",
            "changed_first": "同一输入第 0 字节翻转 1 bit，长度不变",
            "changed_mid": "同一输入中间字节翻转 1 bit，长度不变",
            "changed_last": "同一输入末尾字节翻转 1 bit，长度不变",
        },
        "measurement": "C 中 CLOCK_MONOTONIC_RAW，仅包围目标 decapsulation 调用；预热 2000 轮；四类输入交错执行。",
        "outlier_policy": "保存全部原始计时，不做事后剔除。",
        "platform": platform.platform(),
        "processor": platform.processor(),
        "raw_csv": str(csv_path),
        "chart_svg": str(chart),
        "class_summary": class_summary,
    }
    report = csv_path.with_suffix(".json")
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_json"] = str(report)
    return result

