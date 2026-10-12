from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], timeout: int = 10) -> str:
    try:
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return proc.stdout.strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def get_environment_report() -> dict:
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
    compiler = _run(["gcc", "--version"]).splitlines()[0]
    governor = _run(["bash", "-lc", "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo unavailable"])
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "compiler": compiler,
        "optimization": "-O3 -fPIC -std=c99 -Wall -Wextra -Wpedantic",
        "clock": "CLOCK_MONOTONIC_RAW，仅包围 mlkem_dec 调用",
        "warmup": "正式计时程序预热 2000 组",
        "cpu_affinity": affinity,
        "cpu_governor_cpu0": governor,
        "outlier_policy": "保存全部原始计时，统计阶段不做事后剔除；报告中给出原始 CSV 与 JSON 路径",
        "project_root": str(ROOT),
        "formal_timing_binary": str(ROOT / "experiments" / "formal_timing"),
        "results_dir": str(ROOT / "results"),
        "lscpu_head": _run(["bash", "-lc", "lscpu | sed -n '1,18p'" ]).splitlines(),
    }
