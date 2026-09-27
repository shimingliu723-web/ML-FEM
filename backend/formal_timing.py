"""Paired, same-length ML-KEM decapsulation timing experiment."""

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

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "experiments" / "formal_timing"
LIB_DIR = ROOT / "backend" / "lib"
RESULTS = ROOT / "results" / "formal_timing"


def percentile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(values: list[int]) -> dict:
    return {
        "count": len(values),
        "mean_ns": statistics.fmean(values),
        "stddev_ns": statistics.stdev(values),
        "p05_ns": percentile(values, 0.05),
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "minimum_ns": min(values),
        "maximum_ns": max(values),
    }


def analyze_csv(path: Path) -> dict:
    valid, changed, differences, orders = [], [], [], []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            a = int(row["valid_ns"])
            b = int(row["changed_ns"])
            valid.append(a)
            changed.append(b)
            differences.append(b - a)
            orders.append(int(row["order"]))
    if len(valid) < 100:
        raise ValueError("有效配对数据不足100组")
    mean_difference = statistics.fmean(differences)
    standard_error = statistics.stdev(differences) / math.sqrt(len(differences))
    half_width = 1.96 * standard_error
    lower, upper = mean_difference - half_width, mean_difference + half_width
    return {
        "valid": summarize(valid),
        "changed": summarize(changed),
        "paired_mean_difference_ns": mean_difference,
        "paired_difference_ci95_ns": [lower, upper],
        "paired_t_statistic": mean_difference / standard_error if standard_error else None,
        "statistically_distinguishable": lower > 0 or upper < 0,
        "relative_mean_difference_percent": 100 * mean_difference / statistics.fmean(valid),
        "first_valid_count": orders.count(0),
        "first_changed_count": orders.count(1),
        "method": "配对均值差及其95%正态近似置信区间；不删除异常值；结果仅描述本次环境和这两类样本",
    }


def run_formal_timing(level: str, pairs: int = 10000, cpu: int = 0) -> dict:
    if level not in {"512", "768", "1024"}:
        raise ValueError("参数集必须为512、768或1024")
    if not 100 <= pairs <= 100000:
        raise ValueError("配对次数应在100到100000之间")
    allowed = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else set(range(os.cpu_count() or 1))
    if cpu not in allowed:
        raise ValueError(f"CPU {cpu} 不在本进程可用核心范围内")
    library = LIB_DIR / f"libmlkem{level}.so"
    if not BINARY.is_file() or not library.is_file():
        raise RuntimeError("请先在Linux执行 make all formal-timing")
    RESULTS.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06d}"
    csv_path = RESULTS / f"{run_id}.csv"
    command = [str(BINARY), str(library), level, str(pairs), str(csv_path)]
    if shutil.which("taskset"):
        command = ["taskset", "-c", str(cpu)] + command
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "计时程序执行失败")
    analysis = analyze_csv(csv_path)
    metadata = {
        "level": f"ML-KEM-{level}",
        "pairs": pairs,
        "cpu": cpu if shutil.which("taskset") else None,
        "elapsed_seconds": time.perf_counter() - started,
        "sample_definition": {
            "valid": "由同一实现正常封装得到的32组固定长度输入",
            "changed": "每组正常输入的中间字节翻转1位，长度不变",
            "order": "每组配对随机安排先后顺序",
        },
        "measurement": "C中CLOCK_MONOTONIC_RAW，仅包围mlkem_dec调用；预热2000组",
        "outlier_policy": "保存全部原始计时，不做事后剔除",
        "platform": platform.platform(),
        "processor": platform.processor(),
        "library": str(library),
        "raw_csv": str(csv_path),
        "analysis": analysis,
    }
    report_path = csv_path.with_suffix(".json")
    report_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata["report_json"] = str(report_path)
    return metadata

