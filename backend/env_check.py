from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from env_report import get_environment_report

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], timeout: int = 8) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except Exception as exc:
        return None, f"unavailable: {exc}"


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _detect_virtualization() -> dict[str, Any]:
    proc_version = _read("/proc/version").lower()
    product = _read("/sys/class/dmi/id/product_name")
    vendor = _read("/sys/class/dmi/id/sys_vendor")
    _, virt = _run(["bash", "-lc", "systemd-detect-virt 2>/dev/null || true"])
    _, lscpu = _run(["bash", "-lc", "lscpu | grep -E 'Hypervisor|Virtualization|Model name' || true"])
    text = "\n".join([proc_version, product.lower(), vendor.lower(), virt.lower(), lscpu.lower()])
    is_wsl = "microsoft" in proc_version or "wsl" in proc_version
    is_vm = any(token in text for token in ["vmware", "virtualbox", "kvm", "qemu", "hyper-v", "microsoft"])
    return {
        "is_wsl": is_wsl,
        "is_virtualized": is_vm,
        "virtualization_kind": virt or ("wsl2" if is_wsl else "unknown"),
        "product_name": product or "unavailable",
        "system_vendor": vendor or "unavailable",
        "lscpu_virtualization_lines": lscpu.splitlines(),
    }


def _cpu_frequency_state() -> dict[str, Any]:
    governor = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    cur = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    minf = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq")
    maxf = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq")
    return {
        "governor_available": bool(governor),
        "governor": governor or "unavailable",
        "current_freq_khz": cur or "unavailable",
        "min_freq_khz": minf or "unavailable",
        "max_freq_khz": maxf or "unavailable",
    }


def _affinity_state(cpu: int) -> dict[str, Any]:
    available = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
    taskset_path = shutil.which("taskset")
    can_pin = bool(taskset_path and available and cpu in available)
    return {
        "available_cpus": available,
        "requested_cpu": cpu,
        "taskset": taskset_path or "unavailable",
        "can_pin_requested_cpu": can_pin,
    }


def _jitter_probe(rounds: int = 80) -> dict[str, Any]:
    """Small local stability probe.

    It does not replace the formal ML-KEM timing experiment.  It only checks
    whether the current runtime has large scheduling/frequency drift before
    users trust nanosecond-level timing conclusions.
    """
    samples: list[int] = []
    seed = 0x12345678
    for _ in range(rounds):
        start = time.perf_counter_ns()
        x = seed
        for i in range(16000):
            x = ((x * 1103515245 + 12345 + i) & 0x7FFFFFFF)
        seed ^= x
        samples.append(time.perf_counter_ns() - start)
    ordered = sorted(samples)
    mean = statistics.fmean(samples)
    median = statistics.median(samples)
    stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    p95 = ordered[int((len(ordered) - 1) * 0.95)]
    p99 = ordered[int((len(ordered) - 1) * 0.99)]
    return {
        "rounds": rounds,
        "mean_ns": round(mean, 2),
        "median_ns": round(median, 2),
        "stdev_ns": round(stdev, 2),
        "p95_ns": p95,
        "p99_ns": p99,
        "max_ns": max(samples),
        "p95_over_median": round(p95 / median, 4) if median else None,
        "max_over_median": round(max(samples) / median, 4) if median else None,
    }


def assess_environment(cpu: int = 0, quick: bool = True) -> dict[str, Any]:
    env = get_environment_report()
    virt = _detect_virtualization()
    freq = _cpu_frequency_state()
    affinity = _affinity_state(cpu)
    jitter = _jitter_probe(40 if quick else 120)

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, severity: str, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "severity": severity, "detail": detail})

    add("Linux/WSL 基础运行", platform.system().lower() == "linux", "error", platform.platform())
    add("gcc 可用", shutil.which("gcc") is not None, "error", shutil.which("gcc") or "未找到 gcc")
    add("make 可用", shutil.which("make") is not None, "error", shutil.which("make") or "未找到 make")
    add("taskset 固定 CPU", affinity["can_pin_requested_cpu"], "warning", f"CPU {cpu}; taskset={affinity['taskset']}")
    add("CPU 频率策略可读", freq["governor_available"], "warning", f"governor={freq['governor']}")
    add("非虚拟化/低虚拟化干扰", not virt["is_virtualized"], "warning", f"kind={virt['virtualization_kind']}")
    p95_ratio = jitter.get("p95_over_median") or 99
    max_ratio = jitter.get("max_over_median") or 99
    add("本地计时抖动较低", p95_ratio < 1.25 and max_ratio < 2.5, "warning", f"p95/median={p95_ratio}, max/median={max_ratio}")

    formal_binary = ROOT / "experiments" / "formal_timing"
    add("正式计时程序已构建", formal_binary.is_file(), "warning", str(formal_binary))

    errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]

    if errors:
        grade = "red"
        formal_timing_ready = False
        recommended_use = "基础依赖不完整，需先安装构建/运行环境"
        conclusion = "当前环境尚不满足平台基础运行条件。"
    elif warnings:
        grade = "yellow"
        formal_timing_ready = False
        recommended_use = "适合功能演示、样本生成、定位和修复流程验证；不建议作为正式计时结论来源"
        conclusion = "平台功能可以运行，但当前环境存在虚拟化、频率不可控或抖动偏高等因素，不适合作为正式高精度计时依据。"
    else:
        grade = "green"
        formal_timing_ready = True
        recommended_use = "适合作为正式计时检测和修复前后对比实验环境"
        conclusion = "当前环境具备较好的 CPU 固定、频率可观测和低抖动条件，可用于正式高精度计时实验。"

    return {
        "grade": grade,
        "formal_timing_ready": formal_timing_ready,
        "recommended_use": recommended_use,
        "conclusion": conclusion,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "environment": env,
        "virtualization": virt,
        "cpu_frequency": freq,
        "affinity": affinity,
        "jitter_probe": jitter,
        "interpretation": {
            "product_scope": "基础功能、样本生成、源码/二进制定位、修复与报告展示可在普通 Linux/WSL2/虚拟机运行。",
            "timing_scope": "正式计时结论应在 CPU 调度稳定、可固定核心、后台干扰较低的 Linux 服务器或真实 Linux 主机生成。",
        },
    }


def main() -> int:
    result = assess_environment()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
