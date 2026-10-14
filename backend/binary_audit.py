from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from target_manager import get_target

ROOT = Path(__file__).resolve().parents[1]
CONDITIONAL_JUMPS = {
    "ja", "jae", "jb", "jbe", "jc", "je", "jg", "jge", "jl", "jle", "jna", "jnae",
    "jnb", "jnbe", "jnc", "jne", "jng", "jnge", "jnl", "jnle", "jno", "jnp", "jns",
    "jnz", "jo", "jp", "jpe", "jpo", "js", "jz",
}
COND_MOVES = {"cmova", "cmovae", "cmovb", "cmovbe", "cmove", "cmovg", "cmovge", "cmovl", "cmovle", "cmovne", "cmovno", "cmovnp", "cmovns", "cmovo", "cmovp", "cmovs", "cmovz", "cmovnz"}
SETCC = {"seta", "setae", "setb", "setbe", "sete", "setg", "setge", "setl", "setle", "setne", "setno", "setnp", "setns", "seto", "setp", "sets", "setz", "setnz"}


def _objdump() -> str:
    tool = shutil.which("objdump")
    if not tool:
        raise RuntimeError("服务器未找到 objdump，无法执行二进制定位")
    return tool


def _instruction(line: str) -> tuple[int, str, str] | None:
    # Example: "    a9d2:\t75 3f                \tjne    aa13 <mlkem_dec+0x93>"
    match = re.match(r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{2}\s+)+\s*([a-zA-Z][a-zA-Z0-9_.]*)\b(.*)$", line)
    if not match:
        return None
    return int(match.group(1), 16), match.group(2).lower(), match.group(3).strip()


def _window(lines: list[str], index: int, radius: int = 4) -> list[str]:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return lines[start:end]


def binary_locate(target_id: str, level: str = "512", function: str = "mlkem_dec") -> dict:
    if level not in {"512", "768", "1024"}:
        raise ValueError("参数集必须为512、768或1024")
    target = get_target(target_id)
    library = target.library_for(level)
    if not library.is_file():
        raise FileNotFoundError(f"目标库不存在：{library}")
    requested_function = function
    if target_id == "case_variable_division" and function == "mlkem_dec":
        function = "mlkem_poly_tomsg"
    command = [_objdump(), "-d", "--demangle", f"--disassemble={function}", str(library)]
    proc = subprocess.run(command, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or "objdump 反汇编失败")
    lines = proc.stdout.splitlines()
    findings = []
    counts = {"conditional_jump": 0, "conditional_move": 0, "setcc": 0,
              "backward_jump": 0, "division": 0, "indexed_memory": 0}
    for i, line in enumerate(lines):
        parsed = _instruction(line)
        if not parsed:
            continue
        address, mnemonic, operands = parsed
        kind = None
        if mnemonic in CONDITIONAL_JUMPS:
            kind = "conditional_jump"
        elif mnemonic in COND_MOVES:
            kind = "conditional_move"
        elif mnemonic in SETCC:
            kind = "setcc"
        elif mnemonic in {"div", "divl", "divq", "idiv", "idivl", "idivq"}:
            kind = "division"
        elif "(" in operands and "," in operands and re.search(r"\([^)]*,[^)]*\)", operands):
            kind = "indexed_memory"
        if not kind:
            continue
        counts[kind] += 1
        if kind == "conditional_jump":
            target_match = re.match(r"^([0-9a-fA-F]+)\b", operands)
            if target_match and int(target_match.group(1), 16) < address:
                counts["backward_jump"] += 1
        findings.append({
            "kind": kind,
            "mnemonic": mnemonic,
            "operands": operands,
            "line": line.strip(),
            "context": _window(lines, i),
            "note": ({
                "conditional_jump": "条件跳转会改变控制流；条件来源需与源码证据对应。",
                "conditional_move": "条件移动通常用于避免控制流分支，仍需结合数据来源判断。",
                "setcc": "setcc 将比较结果写入寄存器，需结合后续数据流判断。",
                "division": "发现运行期整数除法候选指令；是否由目标表达式产生需与源码和符号位置对应。",
                "indexed_memory": "发现带索引的内存操作候选；是否由输入相关索引产生需与源码对应。",
            })[kind],
        })
    likely_runtime_branches = [f for f in findings if f["kind"] == "conditional_jump"]
    return {
        "target_id": target_id,
        "target_name": target.name,
        "level": f"ML-KEM-{level}",
        "library": str(library),
        "function": function,
        "requested_function": requested_function,
        "command": command,
        "total_disassembly_lines": len(lines),
        "counts": counts,
        "finding_count": len(findings),
        "conditional_jump_count": len(likely_runtime_branches),
        "summary": (
            f"函数 {function} 中发现 {len(likely_runtime_branches)} 条条件跳转、"
            f"{counts['backward_jump']} 条向后跳转、{counts['conditional_move']} 条条件移动、"
            f"{counts['division']} 条整数除法、{counts['indexed_memory']} 条索引访存候选。"
            "二进制定位只能给出候选控制流证据，是否与敏感数据相关需要结合源码定位和计时结果。"
        ),
        "findings": findings[:80],
        "logging_policy": "仅记录库路径、函数名、指令助记符和反汇编片段；不记录私钥、中间状态、完整输入输出或验证内部值。",
    }
