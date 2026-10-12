from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import re
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = Path(__file__).resolve().parent / "lib"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = RESULTS_DIR / "operations.jsonl"
_LOG_LOCK = threading.Lock()


@dataclass(frozen=True)
class Parameters:
    public_key: int
    secret_key: int
    ciphertext: int
    shared_secret: int = 32


PARAMETERS = {
    "512": Parameters(800, 1632, 768),
    "768": Parameters(1184, 2400, 1088),
    "1024": Parameters(1568, 3168, 1568),
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _from_b64(value: str, expected: int, label: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError(f"{label}不是有效的Base64数据") from exc
    if len(decoded) != expected:
        raise ValueError(f"{label}长度应为{expected}字节，实际为{len(decoded)}字节")
    return decoded


def _record(operation: str, level: str, elapsed_ns: int, success: bool) -> None:
    item = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "operation": operation,
        "level": f"ML-KEM-{level}",
        "elapsed_ns": elapsed_ns,
        "success": success,
    }
    with _LOG_LOCK:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


class MLKEM:
    def __init__(self, level: str, library_path: Path | None = None):
        if level not in PARAMETERS:
            raise ValueError("参数集必须是512、768或1024")
        self.level = level
        self.params = PARAMETERS[level]
        lib_path = library_path or (LIB_DIR / f"libmlkem{level}.so")
        if not lib_path.exists():
            raise RuntimeError(f"缺少核心库：{lib_path}")
        self.lib = ctypes.CDLL(str(lib_path))
        byte_ptr = ctypes.POINTER(ctypes.c_uint8)
        self.lib.mlkem_keypair.argtypes = [byte_ptr, byte_ptr]
        self.lib.mlkem_keypair.restype = ctypes.c_int
        self.lib.mlkem_enc.argtypes = [byte_ptr, byte_ptr, byte_ptr]
        self.lib.mlkem_enc.restype = ctypes.c_int
        self.lib.mlkem_dec.argtypes = [byte_ptr, byte_ptr, byte_ptr]
        self.lib.mlkem_dec.restype = ctypes.c_int

    @staticmethod
    def _array(size: int, data: bytes | None = None):
        array_type = ctypes.c_uint8 * size
        return array_type(*data) if data is not None else array_type()

    def keygen(self, record: bool = True) -> dict:
        pk = self._array(self.params.public_key)
        sk = self._array(self.params.secret_key)
        start = time.perf_counter_ns()
        rc = self.lib.mlkem_keypair(pk, sk)
        elapsed = time.perf_counter_ns() - start
        if record:
            _record("keygen", self.level, elapsed, rc == 0)
        if rc != 0:
            raise RuntimeError(f"密钥生成失败，返回码{rc}")
        return {
            "level": f"ML-KEM-{self.level}",
            "public_key": _b64(bytes(pk)),
            "secret_key": _b64(bytes(sk)),
            "public_key_bytes": self.params.public_key,
            "secret_key_bytes": self.params.secret_key,
            "elapsed_ns": elapsed,
        }

    def encaps(self, public_key: str, record: bool = True) -> dict:
        pk_bytes = _from_b64(public_key, self.params.public_key, "公钥")
        pk = self._array(self.params.public_key, pk_bytes)
        ct = self._array(self.params.ciphertext)
        ss = self._array(self.params.shared_secret)
        start = time.perf_counter_ns()
        rc = self.lib.mlkem_enc(ct, ss, pk)
        elapsed = time.perf_counter_ns() - start
        if record:
            _record("encaps", self.level, elapsed, rc == 0)
        if rc != 0:
            raise RuntimeError(f"密钥封装失败，返回码{rc}")
        return {
            "level": f"ML-KEM-{self.level}",
            "ciphertext": _b64(bytes(ct)),
            "shared_secret": _b64(bytes(ss)),
            "ciphertext_bytes": self.params.ciphertext,
            "shared_secret_bytes": self.params.shared_secret,
            "elapsed_ns": elapsed,
        }

    def decaps(self, ciphertext: str, secret_key: str, record: bool = True) -> dict:
        ct_bytes = _from_b64(ciphertext, self.params.ciphertext, "密文")
        sk_bytes = _from_b64(secret_key, self.params.secret_key, "私钥")
        ct = self._array(self.params.ciphertext, ct_bytes)
        sk = self._array(self.params.secret_key, sk_bytes)
        ss = self._array(self.params.shared_secret)
        start = time.perf_counter_ns()
        rc = self.lib.mlkem_dec(ss, ct, sk)
        elapsed = time.perf_counter_ns() - start
        if record:
            _record("decaps", self.level, elapsed, rc == 0)
        if rc != 0:
            raise RuntimeError(f"密钥解封装失败，返回码{rc}")
        return {
            "level": f"ML-KEM-{self.level}",
            "shared_secret": _b64(bytes(ss)),
            "shared_secret_bytes": self.params.shared_secret,
            "elapsed_ns": elapsed,
        }

    def demo(self) -> dict:
        keypair = self.keygen()
        encapsulated = self.encaps(keypair["public_key"])
        decapsulated = self.decaps(encapsulated["ciphertext"], keypair["secret_key"])
        matched = encapsulated["shared_secret"] == decapsulated["shared_secret"]
        return {
            "level": f"ML-KEM-{self.level}",
            "matched": matched,
            "public_key": keypair["public_key"],
            "secret_key": keypair["secret_key"],
            "ciphertext": encapsulated["ciphertext"],
            "encapsulated_secret": encapsulated["shared_secret"],
            "decapsulated_secret": decapsulated["shared_secret"],
            "timings_ns": {
                "keygen": keypair["elapsed_ns"],
                "encaps": encapsulated["elapsed_ns"],
                "decaps": decapsulated["elapsed_ns"],
            },
            "sizes": {
                "public_key": self.params.public_key,
                "secret_key": self.params.secret_key,
                "ciphertext": self.params.ciphertext,
                "shared_secret": self.params.shared_secret,
            },
        }

    def selftest(self, iterations: int) -> dict:
        if iterations < 1 or iterations > 1000:
            raise ValueError("测试次数必须在1到1000之间")
        failures = 0
        totals = {"keygen": 0, "encaps": 0, "decaps": 0}
        started = time.perf_counter_ns()
        for _ in range(iterations):
            result = self.demo()
            if not result["matched"]:
                failures += 1
            for name, value in result["timings_ns"].items():
                totals[name] += value
        elapsed = time.perf_counter_ns() - started
        return {
            "level": f"ML-KEM-{self.level}",
            "iterations": iterations,
            "passed": iterations - failures,
            "failed": failures,
            "success": failures == 0,
            "average_ns": {name: value // iterations for name, value in totals.items()},
            "total_elapsed_ns": elapsed,
        }


BASIC_VECTOR_DIR = ROOT / "core" / "mlkem-native" / "examples" / "basic"
TIMING_SOURCE_DIR = ROOT / "experiments" / "clangover-poc"
TIMING_BINARY = TIMING_SOURCE_DIR / "clangover-pqcrystal-kyber-bounded"
TIMING_LOG = TIMING_SOURCE_DIR / "attack_log.jsonl"


def _run_command(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def _parse_vector_header() -> dict:
    header = BASIC_VECTOR_DIR / "expected_test_vectors.h"
    text = header.read_text(encoding="utf-8", errors="ignore")
    names = ["d", "z", "m", "pk", "sk", "ct", "ss"]
    vectors = {}
    for name in names:
        match = re.search(rf"test_vector_{name}\[(\d+)\]", text)
        if match:
            vectors[name] = int(match.group(1))
    return {
        "source": str(header),
        "available_items": vectors,
        "source_note": "mlkem-native 自带 expected_test_vectors.h，包含确定性 keygen、encaps、decaps 对照数据。",
    }


def run_known_answer_test() -> dict:
    started = time.perf_counter_ns()
    build = _run_command(["make", "build"], BASIC_VECTOR_DIR, timeout=120)
    run = _run_command(["make", "run"], BASIC_VECTOR_DIR, timeout=120)
    elapsed = time.perf_counter_ns() - started
    output = run.stdout.strip().splitlines()
    passed_lines = [line for line in output if "DONE" in line]
    levels = ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"]
    return {
        "success": build.returncode == 0 and run.returncode == 0,
        "build_status": build.returncode,
        "run_status": run.returncode,
        "levels": levels,
        "checks_total": 15,
        "checks_passed": len(passed_lines),
        "elapsed_ns": elapsed,
        "vectors": _parse_vector_header(),
        "output_tail": output[-18:],
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def run_timing_detection(cpu: int = 0, timeout_seconds: int = 600) -> dict:
    if not TIMING_BINARY.exists():
        raise RuntimeError(f"缺少计时实验程序：{TIMING_BINARY}")
    if timeout_seconds < 30 or timeout_seconds > 1800:
        raise ValueError("运行上限必须在30到1800秒之间")

    if TIMING_LOG.exists():
        TIMING_LOG.unlink()
    command = ["taskset", "-c", str(cpu), "env", "TERM=dumb", "timeout", str(timeout_seconds), str(TIMING_BINARY)]
    started = time.perf_counter_ns()
    proc = _run_command(command, TIMING_SOURCE_DIR, timeout=timeout_seconds + 30)
    elapsed = time.perf_counter_ns() - started

    counts: dict[str, int] = {}
    done = []
    measurements = []
    complete = None
    if TIMING_LOG.exists():
        with TIMING_LOG.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = str(item.get("event"))
                counts[event] = counts.get(event, 0) + 1
                if event == "coeff_done":
                    done.append(item)
                elif event == "measurement":
                    measurements.append(item)
                elif event == "complete":
                    complete = item

    correct = sum(1 for item in done if item.get("correct") == 1)
    iterations = [float(item.get("iterations", 0)) for item in done]
    confidences = [float(item.get("confidence", 0)) for item in done]
    last_means = measurements[-1].get("means", []) if measurements else []
    separation = 0.0
    if len(last_means) >= 9:
        separation = abs(float(last_means[8]) - float(last_means[7]))

    return {
        "success": proc.returncode == 0 and complete is not None,
        "exit_status": proc.returncode,
        "cpu": cpu,
        "timeout_seconds": timeout_seconds,
        "elapsed_ns": elapsed,
        "log_file": str(TIMING_LOG),
        "counts": counts,
        "coefficients_done": len(done),
        "correct": correct,
        "accuracy": (correct / len(done) * 100.0) if done else 0.0,
        "complete": complete,
        "iteration_summary": {
            "mean": statistics.fmean(iterations) if iterations else 0.0,
            "p50": _percentile(iterations, 0.50),
            "p90": _percentile(iterations, 0.90),
        },
        "confidence_summary": {
            "mean": statistics.fmean(confidences) if confidences else 0.0,
            "min": min(confidences) if confidences else 0.0,
            "max": max(confidences) if confidences else 0.0,
        },
        "last_means": last_means,
        "reference_gap": separation,
        "distinguishable": separation >= 8.0,
        "detection_note": "参考类别均值差距达到阈值" if separation >= 8.0 else "参考类别均值差距不明显",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "affinity_cpu": cpu,
        },
        "output_tail": proc.stdout.strip().splitlines()[-20:],
    }


_INSTANCES: dict[str, MLKEM] = {}


def get_mlkem(level: str) -> MLKEM:
    if level not in _INSTANCES:
        _INSTANCES[level] = MLKEM(level)
    return _INSTANCES[level]
