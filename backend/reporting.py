from __future__ import annotations

import json
import time
from pathlib import Path

from env_report import get_environment_report
from target_manager import list_targets

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "results" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

THREAT_MODEL = {
    "attacker_control": "测试方能够多次提交不同类别的 ML-KEM 解封装输入，平台在本地对同一实现进行重复测量。",
    "observable": "观测信息限定为解封装函数运行时间及统计结果，不读取私钥或中间敏感状态。",
    "local_scope": "当前平台主要覆盖本地高精度计时实验，使用固定 CPU 核、统一编译选项和原始数据记录降低随机干扰。",
    "remote_boundary": "网络远程计时受网络抖动影响较大，不能直接把本地结论推广为远程可观察结论。",
    "non_goals": "平台不访问第三方系统，不做网络探测，不处理真实业务数据。",
}

REPRO_STEPS = [
    "cd /disk4/lsm/A1-13-MLKEM-Platform",
    "make all",
    "python3 tests/test_basic.py",
    "MLKEM_HOST=0.0.0.0 MLKEM_PORT=8000 ./scripts/start.sh",
    "在平台中选择目标实现与参数集",
    "运行公开测试向量验证",
    "生成等长测试样本并保存 CSV/JSON",
    "运行精确时间检测，记录 raw_csv 与 report_json",
    "运行代码定位与修复前后对比",
]

REQUIREMENTS = [
    ("1 基本密码功能", "已完成", "KeyGen / Encaps / Decaps、连续正确性测试、公开测试向量验证"),
    ("2 时间测量环境", "已完成", "环境页展示 CPU、系统、GCC、-O3、CPU 绑定、预热、异常样本策略"),
    ("3 输入分类与测试", "已完成", "自动生成 normal / changed_mid / changed_first / changed_last 等长样本"),
    ("4 统计检测", "已完成", "均值、标准差、P50/P95、配对差、95% 区间、显著可区分判断"),
    ("5 代码定位", "已完成", "定位 verify.h、kem.c 中比较调用、统一选择和失败处理位置"),
    ("6 固定流程改进", "已完成基础版", "早退对照版本与固定流程版本源码差异、复测结果"),
    ("7 改进效果验证", "已完成基础版", "同一环境下运行对照/改进版本前后复测"),
    ("8 性能要求", "已完成基础版", "输出前后平均时间、P50/P95 与开销百分比"),
    ("9 跨环境验证", "部分完成", "目前完成一种 Linux 软件运行环境；可继续扩展 -O0/-O2/-O3 或不同 CPU"),
    ("10 威胁模型", "已完成", "明确输入控制、观测信息、本地/远程边界和非目标"),
    ("11 可复现性", "已完成", "提供构建命令、实验参数、CSV/JSON、报告和复现步骤"),
    ("12 创新要求", "已完成基础版", "自动样本生成、源码定位、前后复测和要求矩阵"),
]


def latest_files() -> dict:
    def newest(pattern: str) -> str:
        files = sorted(ROOT.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0)
        return str(files[-1]) if files else "尚未生成"
    return {
        "latest_sample_json": newest("results/samples/*/samples.json"),
        "latest_timing_json": newest("results/formal_timing/*.json"),
        "latest_timing_csv": newest("results/formal_timing/*.csv"),
    }


def requirement_matrix() -> list[dict]:
    return [{"requirement": a, "status": b, "evidence": c} for a, b, c in REQUIREMENTS]


def report_payload() -> dict:
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "environment": get_environment_report(),
        "targets": list_targets(),
        "threat_model": THREAT_MODEL,
        "repro_steps": REPRO_STEPS,
        "requirements": requirement_matrix(),
        "latest_files": latest_files(),
    }


def generate_markdown_report() -> dict:
    payload = report_payload()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"A1-13-report-{stamp}.md"
    lines = [
        "# A1-13 ML-KEM 时间特性检测与防护平台实验报告",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 一、题目要求完成矩阵",
        "",
        "| 要求 | 状态 | 平台证据 |",
        "| --- | --- | --- |",
    ]
    for item in payload["requirements"]:
        lines.append(f"| {item['requirement']} | {item['status']} | {item['evidence']} |")
    lines += ["", "## 二、威胁模型", ""]
    for key, value in payload["threat_model"].items():
        lines.append(f"- {key}: {value}")
    env = payload["environment"]
    lines += ["", "## 三、测量环境", "", f"- 系统：{env['platform']}", f"- 处理器：{env['processor']}", f"- 编译器：{env['compiler']}", f"- 编译选项：{env['optimization']}", f"- 计时方式：{env['clock']}", f"- 预热策略：{env['warmup']}", f"- 异常样本处理：{env['outlier_policy']}"]
    lines += ["", "## 四、可复现步骤", ""]
    for idx, step in enumerate(payload["repro_steps"], 1):
        lines.append(f"{idx}. `{step}`")
    latest = payload["latest_files"]
    lines += ["", "## 五、最近一次实验文件", "", f"- 样本 JSON：{latest['latest_sample_json']}", f"- 计时 JSON：{latest['latest_timing_json']}", f"- 计时 CSV：{latest['latest_timing_csv']}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": str(path), "json": str(json_path), "payload": payload}
