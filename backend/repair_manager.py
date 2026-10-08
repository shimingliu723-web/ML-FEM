from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import stat
import time
from pathlib import Path

from formal_timing import run_formal_timing
from target_manager import TARGETS_DIR, get_target, run_target_command

ROOT = Path(__file__).resolve().parents[1]
BASELINE_VERIFY = ROOT / "core" / "mlkem-native" / "mlkem" / "src" / "verify.h"


def _safe_id(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", value):
        raise ValueError("目标ID只能包含字母、数字、下划线和短横线，长度3到64")
    return value


def _source_root(target_id: str) -> Path:
    if target_id == "mlkem_native_baseline":
        return ROOT / "core" / "mlkem-native" / "mlkem"
    return TARGETS_DIR / target_id / "src" / "mlkem"


def _target_dir(target_id: str) -> Path:
    path = (TARGETS_DIR / target_id).resolve()
    if TARGETS_DIR.resolve() not in path.parents and path != TARGETS_DIR.resolve():
        raise ValueError("修复目标必须位于 targets 目录内")
    return path


def _memcmp_block(text: str) -> tuple[int, int, str]:
    start = text.index("static MLK_INLINE uint8_t mlk_ct_memcmp")
    marker = "\n/**\n * Copy len bytes from x to r if b is zero;"
    end = text.index(marker, start)
    return start, end, text[start:end]


def _baseline_memcmp_block() -> str:
    text = BASELINE_VERIFY.read_text(encoding="utf-8", errors="ignore")
    return _memcmp_block(text)[2]


def _classify_memcmp(block: str) -> str:
    if "return 0xFF" in block and "r |= a[i] ^ b[i]" not in block:
        return "early_return_compare"
    if "r |= a[i] ^ b[i]" in block:
        return "constant_time_accumulate"
    return "unknown_compare_style"


def _repaired_id(before_id: str) -> str:
    if before_id.startswith("variant_early_return"):
        return before_id.replace("variant_early_return", "variant_repaired", 1)
    return f"repaired_{before_id}"


def generate_repair(before_id: str = "variant_early_return", repaired_id: str | None = None,
                    overwrite: bool = False, build: bool = True, validate_pairs: int = 100,
                    cpu: int = 0) -> dict:
    """Create a repaired target for the early-return compare pattern.

    The function records only source locations, patch digest, build output and timing
    statistics. It never logs keys, intermediate values, full samples, or validation
    internals.
    """
    before_id = _safe_id(before_id)
    before_target = get_target(before_id)
    repaired_id = _safe_id(repaired_id or _repaired_id(before_id))
    if repaired_id == before_id:
        raise ValueError("修复目标ID不能与原目标相同")
    before_dir = _target_dir(before_id)
    dest = _target_dir(repaired_id)
    if not before_dir.is_dir():
        raise FileNotFoundError(f"原目标目录不存在：{before_dir}")
    if dest.exists():
        if not overwrite:
            raise FileExistsError(f"修复目标已存在：{repaired_id}；如需覆盖请设置 overwrite=true")
        shutil.rmtree(dest)
    shutil.copytree(before_dir, dest, ignore=shutil.ignore_patterns("lib", "repair_report.json"))

    verify = dest / "src" / "mlkem" / "src" / "verify.h"
    original_text = verify.read_text(encoding="utf-8", errors="ignore")
    start, end, original_block = _memcmp_block(original_text)
    style = _classify_memcmp(original_block)
    if style != "early_return_compare":
        raise ValueError(f"当前自动修复器只处理早退比较模式，识别结果为：{style}")
    fixed_block = _baseline_memcmp_block()
    fixed_text = original_text[:start] + fixed_block + original_text[end:]
    verify.write_text(fixed_text, encoding="utf-8")

    cfg_path = dest / "target.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.update({
        "id": repaired_id,
        "name": f"修复实现：{before_target.name}",
        "role": "repaired",
        "description": "由平台自动生成的修复目标：将早退比较替换为完整扫描与掩码汇总的固定流程写法。",
        "library_template": f"targets/{repaired_id}/lib/libmlkem{{level}}.so",
        "build": ["bash", f"targets/{repaired_id}/build.sh"],
        "selftest": [],
        "repair_from": before_id,
    })
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    build_script = dest / "build.sh"
    script = build_script.read_text(encoding="utf-8")
    script = script.replace(before_id, repaired_id)
    script = re.sub(r"TARGET_DIR=\"\$PROJECT_DIR/targets/[^\"]+\"", f"TARGET_DIR=\"$PROJECT_DIR/targets/{repaired_id}\"", script)
    build_script.write_text(script, encoding="utf-8")
    build_script.chmod(build_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    diff_lines = list(difflib.unified_diff(
        original_text.splitlines(), fixed_text.splitlines(),
        fromfile=f"{before_id}/verify.h", tofile=f"{repaired_id}/verify.h", lineterm=""
    ))
    patch_text = "\n".join(diff_lines) + "\n"
    patch_hash = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
    patch_file = dest / "repair.patch"
    patch_file.write_text(patch_text, encoding="utf-8")

    build_result = run_target_command(repaired_id, "build") if build else {"success": True, "skipped": True}
    validation = None
    if build_result.get("success") and validate_pairs:
        validation = run_formal_timing("512", int(validate_pairs), int(cpu), repaired_id)

    report = {
        "success": bool(build_result.get("success")),
        "before_id": before_id,
        "repaired_id": repaired_id,
        "repair_type": "early_return_compare_to_constant_time_accumulate",
        "changed_file": str(verify),
        "source_pattern": "early-return compare",
        "replacement": "full scan plus accumulated difference mask",
        "patch_sha256": patch_hash,
        "patch_file": str(patch_file),
        "diff_preview": [line for line in diff_lines if "mlk_ct_memcmp" in line or "return 0xFF" in line or "r |= a[i] ^ b[i]" in line or line.startswith(("---", "+++", "@@"))][:120],
        "build": build_result,
        "validation": {
            "ran": validation is not None,
            "target": validation.get("target_id") if validation else None,
            "report_json": validation.get("report_json") if validation else None,
            "statistically_distinguishable": validation.get("analysis", {}).get("statistically_distinguishable") if validation else None,
            "paired_mean_difference_ns": validation.get("analysis", {}).get("paired_mean_difference_ns") if validation else None,
        },
        "logging_policy": "仅记录目标ID、文件路径、补丁摘要、统计结果和报告路径；不记录私钥、中间状态、完整样本或验证内部值。",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (dest / "repair_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def repair_and_compare(before_id: str = "variant_early_return", level: str = "512", pairs: int = 1000,
                       cpu: int = 0, overwrite: bool = True) -> dict:
    repaired_id = _repaired_id(_safe_id(before_id))
    repair = generate_repair(before_id, repaired_id, overwrite=overwrite, build=True, validate_pairs=100, cpu=cpu)
    before = run_formal_timing(level, pairs, cpu, before_id)
    after = run_formal_timing(level, pairs, cpu, repaired_id)
    b, a = before["analysis"], after["analysis"]
    return {
        "level": f"ML-KEM-{level}",
        "pairs": pairs,
        "cpu": cpu,
        "repair": repair,
        "before": before,
        "after": after,
        "summary": {
            "before_diff_ns": b["paired_mean_difference_ns"],
            "before_distinguishable": b["statistically_distinguishable"],
            "after_diff_ns": a["paired_mean_difference_ns"],
            "after_distinguishable": a["statistically_distinguishable"],
            "absolute_diff_reduction_ns": abs(b["paired_mean_difference_ns"]) - abs(a["paired_mean_difference_ns"]),
            "before_formal_verdict": before.get("statistical_analysis", {}).get("verdict", {}).get("text"),
            "after_formal_verdict": after.get("statistical_analysis", {}).get("verdict", {}).get("text"),
        },
    }
