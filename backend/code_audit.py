from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from formal_timing import run_formal_timing
from target_manager import get_target
from repair_manager import generate_repair, _classify_memcmp, _memcmp_block

ROOT = Path(__file__).resolve().parents[1]

CHECKS = [
    {
        "id": "compare_function",
        "title": "比较函数实现",
        "requirement": "定位可变时间比较函数或固定时间比较函数",
        "relative_path": "src/mlkem/src/verify.h",
        "patterns": ["mlk_ct_memcmp", "return 0xFF", "r |= a[i] ^ b[i]"],
    },
    {
        "id": "decaps_compare_call",
        "title": "解封装流程中的比较调用",
        "requirement": "说明比较函数与 ML-KEM 解封装流程的对应关系",
        "relative_path": "src/mlkem/src/kem.c",
        "patterns": ["fail = mlk_ct_memcmp", "mlk_indcpa_enc", "mlk_ct_cmov_zero"],
    },
    {
        "id": "conditional_select",
        "title": "统一选择与失败处理",
        "requirement": "定位统一错误处理和掩码选择逻辑",
        "relative_path": "src/mlkem/src/verify.h",
        "patterns": ["mlk_ct_cmov_zero", "mlk_ct_sel_uint8"],
    },
]

CASE_CHECKS = {
    "mlkem_native_baseline": {
        "mechanism": "规范固定流程基线",
        "relative_path": "src/verify.h",
        "patterns": ["r |= a[i] ^ b[i]", "mlk_ct_cmov_zero"],
        "explanation": "比较过程完整扫描输入，并在解封装末端使用掩码选择；该证据仅说明此处采用固定流程写法。",
    },
    "case_compare_early": {
        "mechanism": "比较函数提前结束",
        "relative_path": "src/verify.h",
        "patterns": ["if (a[i] != b[i])", "return 0xFF"],
        "explanation": "比较函数在首个不同位置结束，执行工作量与首个不同位置相关。",
    },
    "case_conditional_failure": {
        "mechanism": "失败处理条件路径",
        "relative_path": "src/kem.c",
        "patterns": ["if (fail == 0)", "mlk_hash_j", "mlk_memcpy(ss, kr"],
        "explanation": "解封装验证结果进入两条不同的后续处理路径，定位到失败处理阶段。",
    },
    "case_variable_loop": {
        "mechanism": "数据相关循环次数",
        "relative_path": "src/verify.h",
        "patterns": ["size_t rounds = r ? 64u : 4096u", "i < rounds"],
        "explanation": "循环上限由比较汇总结果决定，执行迭代次数随输入类别变化。",
    },
    "case_memory_index": {
        "mechanism": "数据相关内存索引",
        "relative_path": "src/verify.h",
        "patterns": ["case_stride", "case_table[(i * case_stride)", "case_table_ready", "i < 4096u"],
        "explanation": "比较结果决定固定次数循环中的访问步长：一类重复命中同一缓存线，另一类跨缓存线访问。",
    },
    "case_conditional_branch": {
        "mechanism": "数据相关条件分支",
        "relative_path": "src/kem.c",
        "patterns": ["if (fail != 0)", "case_marker", "case_i < 1024u"],
        "explanation": "验证结果直接控制是否进入固定工作量路径，定位到解封装验证后的控制流。",
    },
    "case_variable_division": {
        "mechanism": "可变除数运算",
        "relative_path": "src/verify.h",
        "patterns": ["case_divisor", "/ case_divisor", "i < 1024u", "if (r != 0)"],
        "explanation": "比较结果控制一个包含固定上限运行期除法的有界路径，需结合编译后二进制中的 div/idiv 指令判断；该案例同时包含路径选择。",
    },
}


def _target_source_root(target_id: str) -> Path:
    if target_id == "mlkem_native_baseline":
        return ROOT / "core" / "mlkem-native" / "mlkem"
    return ROOT / "targets" / target_id / "src" / "mlkem"


def _extract_snippet(path: Path, patterns: list[str], context: int = 6) -> dict:
    if not path.is_file():
        return {"path": str(path), "found": False, "matches": [], "snippet": ""}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    indexes = []
    for idx, line in enumerate(lines):
        if any(p in line for p in patterns):
            indexes.append(idx)
    if not indexes:
        return {"path": str(path), "found": False, "matches": [], "snippet": ""}
    start = max(min(indexes) - context, 0)
    end = min(max(indexes) + context + 1, len(lines))
    snippet = "\n".join(f"{i + 1:04d}: {lines[i]}" for i in range(start, end))
    return {
        "path": str(path),
        "found": True,
        "matches": [i + 1 for i in indexes],
        "snippet": snippet,
    }


def locate_code(target_id: str) -> dict:
    target = get_target(target_id)
    source_root = _target_source_root(target_id)
    findings = []
    for item in CHECKS:
        path = source_root / item["relative_path"] if not item["relative_path"].startswith("src/mlkem/") else source_root / item["relative_path"].replace("src/mlkem/", "")
        result = _extract_snippet(path, item["patterns"])
        result.update({
            "id": item["id"],
            "title": item["title"],
            "requirement": item["requirement"],
            "patterns": item["patterns"],
        })
        findings.append(result)
    compare_note = "unknown"
    verify_path = source_root / "src" / "verify.h"
    if verify_path.is_file():
        text = verify_path.read_text(encoding="utf-8", errors="ignore")
        try:
            style = _classify_memcmp(_memcmp_block(text)[2])
            compare_note = {"early_return_compare": "early_return", "constant_time_accumulate": "fixed_time"}.get(style, "unknown")
        except ValueError:
            pass
    case = CASE_CHECKS.get(target_id)
    mechanism_evidence = None
    if case:
        evidence = _extract_snippet(source_root / case["relative_path"], case["patterns"], context=8)
        mechanism_evidence = {
            **evidence,
            "mechanism": case["mechanism"],
            "patterns": case["patterns"],
            "explanation": case["explanation"],
        }
    if mechanism_evidence and mechanism_evidence["found"]:
        summary = f"已定位“{mechanism_evidence['mechanism']}”的源码证据。{mechanism_evidence['explanation']}"
    elif case:
        summary = f"未定位到“{case['mechanism']}”的预期完整模式，不能自动下结论，需要人工复核。"
    else:
        summary = {"early_return": "发现首个不同字节提前返回的比较模式，对应解封装重加密验证环节。", "fixed_time": "发现完整扫描与掩码汇总模式；这不是对整个实现的常数时间证明。", "unknown": "源码缺失或模式不受支持，需要人工分析，不能判为固定时间。"}[compare_note]
    return {
        "target_id": target_id,
        "target_name": target.name,
        "role": target.role,
        "source_root": str(source_root),
        "compare_style": compare_note,
        "mechanism": case["mechanism"] if case else "用户接入实现",
        "mechanism_evidence": mechanism_evidence,
        "summary": summary,
        "findings": findings,
    }


def diff_targets(before_id: str = "variant_early_return", after_id: str = "variant_repaired") -> dict:
    before = _target_source_root(before_id) / "src" / "verify.h"
    after = _target_source_root(after_id) / "src" / "verify.h"
    if not before.is_file() or not after.is_file():
        raise FileNotFoundError("对比目标源码不存在，请先构建或检查 targets 目录")
    before_lines = before.read_text(encoding="utf-8", errors="ignore").splitlines()
    after_lines = after.read_text(encoding="utf-8", errors="ignore").splitlines()
    diff = list(difflib.unified_diff(before_lines, after_lines, fromfile=str(before), tofile=str(after), lineterm=""))
    filtered = []
    keep_next = 0
    for line in diff:
        if "mlk_ct_memcmp" in line or "if (a[i] != b[i])" in line or "r |= a[i] ^ b[i]" in line or "return 0xFF" in line:
            keep_next = 12
        if keep_next > 0 or line.startswith(("---", "+++", "@@")):
            filtered.append(line)
            keep_next = max(keep_next - 1, 0)
    return {
        "before_id": before_id,
        "after_id": after_id,
        "before_file": str(before),
        "after_file": str(after),
        "diff_lines": filtered[:240],
        "explanation": "对照版本使用遇到首个差异立即返回的比较逻辑；改进版本恢复为完整扫描并汇总差异的固定流程写法。",
    }


def compare_fix(level: str = "512", pairs: int = 1000, cpu: int = 0) -> dict:
    if pairs < 100 or pairs > 20000:
        raise ValueError("前后对比配对次数应在100到20000之间")
    generate_repair("variant_early_return", "variant_repaired", overwrite=True, build=True, validate_pairs=100, cpu=cpu)
    before = run_formal_timing(level, pairs, cpu, "variant_early_return")
    after = run_formal_timing(level, pairs, cpu, "variant_repaired")
    b = before["analysis"]
    a = after["analysis"]
    return {
        "level": f"ML-KEM-{level}",
        "pairs": pairs,
        "cpu": cpu,
        "before": before,
        "after": after,
        "summary": {
            "before_diff_ns": b["paired_mean_difference_ns"],
            "before_distinguishable": b["statistically_distinguishable"],
            "after_diff_ns": a["paired_mean_difference_ns"],
            "after_distinguishable": a["statistically_distinguishable"],
            "absolute_diff_reduction_ns": abs(b["paired_mean_difference_ns"]) - abs(a["paired_mean_difference_ns"]),
        },
    }



def performance_compare(level: str = "512", pairs: int = 1000, cpu: int = 0) -> dict:
    """Run the contrast/fixed pair and report timing cost in judge-friendly fields."""
    compared = compare_fix(level, pairs, cpu)
    before = compared["before"]["analysis"]
    after = compared["after"]["analysis"]
    before_mean = before["valid"]["mean_ns"]
    after_mean = after["valid"]["mean_ns"]
    overhead = after_mean - before_mean
    overhead_pct = 100.0 * overhead / before_mean if before_mean else 0.0
    compared["performance"] = {
        "before_mean_ns": before_mean,
        "before_p50_ns": before["valid"]["p50_ns"],
        "before_p95_ns": before["valid"]["p95_ns"],
        "after_mean_ns": after_mean,
        "after_p50_ns": after["valid"]["p50_ns"],
        "after_p95_ns": after["valid"]["p95_ns"],
        "overhead_ns": overhead,
        "overhead_percent": overhead_pct,
        "interpretation": "改进版本保持相同功能语义，以固定流程实现降低可区分差异；性能开销以正常输入路径的均值和分位数对比表示。",
    }
    return compared
