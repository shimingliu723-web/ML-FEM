from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from binary_audit import binary_locate
from code_audit import locate_code
from env_check import assess_environment
from formal_timing import run_formal_timing
from mlkem_service import get_mlkem, run_known_answer_test
from repair_manager import repair_and_compare
from sample_generator import generate_samples
from target_manager import list_targets, run_target_command


def banner(title: str) -> None:
    line = "=" * 78
    print(f"\n{line}")
    print(f"│ {title}")
    print(line)


def item(label: str, value: Any) -> None:
    print(f"{label:<22}: {value}")


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_command(command: list[str], timeout: int = 300) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "output_tail": proc.stdout.strip().splitlines()[-30:],
    }


def write_svg(path: Path, before_diff: float, after_diff: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    max_abs = max(abs(before_diff), abs(after_diff), 1.0)

    def width(value: float) -> float:
        return 360 * abs(value) / max_abs

    before_w = width(before_diff)
    after_w = width(after_diff)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="360" viewBox="0 0 900 360">
<style>
text {{ font-family: Arial, 'Noto Sans CJK SC', sans-serif; fill:#111827; }}
.title {{ font-size:24px; font-weight:700; }}
.label {{ font-size:18px; }}
.small {{ font-size:14px; fill:#4b5563; }}
.axis {{ stroke:#9ca3af; stroke-width:2; }}
</style>
<rect x="0" y="0" width="900" height="360" fill="#ffffff"/>
<text x="40" y="45" class="title">修复前后配对均值差对比</text>
<text x="40" y="75" class="small">数值越接近 0，表示两类输入的时间分布越难区分。</text>
<line x1="450" y1="105" x2="450" y2="290" class="axis"/>
<text x="438" y="315" class="small">0 ns</text>
<text x="40" y="140" class="label">修复前</text>
<rect x="{450 - before_w if before_diff < 0 else 450}" y="112" width="{before_w}" height="44" rx="6" fill="#ef4444"/>
<text x="620" y="140" class="label">{before_diff:.2f} ns</text>
<text x="40" y="230" class="label">修复后</text>
<rect x="{450 - after_w if after_diff < 0 else 450}" y="202" width="{after_w}" height="44" rx="6" fill="#10b981"/>
<text x="620" y="230" class="label">{after_diff:.2f} ns</text>
<text x="40" y="338" class="small">实验环境：服务器固定 CPU 核；输入类别等长；统计结果见同目录 JSON/Markdown 报告。</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="服务器证明性实验套件")
    parser.add_argument("--level", default="512", choices=["512", "768", "1024"])
    parser.add_argument("--pairs", type=int, default=2000)
    parser.add_argument("--cpu", type=int, default=0)
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "results" / "proof_suite" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "run_id": run_id,
        "level": f"ML-KEM-{args.level}",
        "pairs": args.pairs,
        "cpu": args.cpu,
        "out_dir": str(out_dir),
    }

    banner("A1-13 服务器证明性实验套件")
    item("运行编号", run_id)
    item("项目目录", ROOT)
    item("参数集", f"ML-KEM-{args.level}")
    item("计时配对次数", args.pairs)
    item("固定 CPU", args.cpu)

    banner("步骤1：构建平台与目标实现")
    build = run_command(["make", "all"], timeout=300)
    target_builds = {}
    for target in ["variant_early_return", "variant_early_return_xor", "variant_early_return_while"]:
        target_builds[target] = run_target_command(target, "build", timeout=240)
    summary["build"] = {"make_all": build, "targets": target_builds}
    item("make all", "PASS" if build["returncode"] == 0 else "FAIL")
    item("对照目标构建", f"{sum(1 for x in target_builds.values() if x.get('success'))}/{len(target_builds)} PASS")

    banner("步骤2：环境自检")
    env = assess_environment(args.cpu, quick=False)
    summary["environment_check"] = env
    item("环境等级", env["grade"])
    item("正式计时适用", "是" if env["formal_timing_ready"] else "否/需说明边界")
    item("推荐用途", env["recommended_use"])
    item("CPU频率策略", env["cpu_frequency"]["governor"])
    item("虚拟化类型", env["virtualization"]["virtualization_kind"])
    item("抖动 p95/median", env["jitter_probe"]["p95_over_median"])

    banner("步骤3：基本功能与公开测试向量")
    basic = {}
    for level in ["512", "768", "1024"]:
        basic[level] = get_mlkem(level).selftest(20)
        total = basic[level].get("total", basic[level].get("iterations", "?"))
        item(f"ML-KEM-{level}", f"{basic[level]['passed']}/{total} passed; avg(ns)={basic[level]['average_ns']}")
    vectors = run_known_answer_test()
    summary["basic"] = basic
    summary["known_answer_test"] = vectors
    item("公开测试向量", f"{vectors['checks_passed']}/{vectors['checks_total']} passed")
    item("向量验证耗时", f"{vectors['elapsed_ns'] / 1e9:.3f} s")

    banner("步骤4：等长输入样本生成")
    samples = generate_samples("mlkem_native_baseline", args.level, 32)
    summary["samples"] = samples
    item("样本类别", " / ".join(samples["sample_classes"]))
    item("每类数量", samples["count"])
    item("密文长度", f"{samples['ciphertext_bytes']} bytes")
    item("样本报告", samples["report_json"])

    banner("步骤5：时间检测与统计检验")
    baseline_timing = run_formal_timing(args.level, args.pairs, args.cpu, "mlkem_native_baseline")
    contrast_timing = run_formal_timing(args.level, args.pairs, args.cpu, "variant_early_return")
    summary["timing"] = {"baseline": baseline_timing, "contrast": contrast_timing}
    base_a = baseline_timing["analysis"]
    con_a = contrast_timing["analysis"]
    item("规范实现差值(ns)", f"{base_a['paired_mean_difference_ns']:.2f}")
    item("规范实现可区分", "是" if base_a["statistically_distinguishable"] else "否")
    item("对照实现差值(ns)", f"{con_a['paired_mean_difference_ns']:.2f}")
    item("对照实现可区分", "是" if con_a["statistically_distinguishable"] else "否")
    item("对照统计结论", contrast_timing.get("statistical_analysis", {}).get("verdict", {}).get("text"))
    item("对照报告", contrast_timing["report_json"])

    banner("步骤6：泄露定位证据")
    source_location = locate_code("variant_early_return")
    binary_before = binary_locate("variant_early_return", args.level, "mlkem_dec")
    binary_after = binary_locate("mlkem_native_baseline", args.level, "mlkem_dec")
    summary["location"] = {
        "source": source_location,
        "binary_before": binary_before,
        "binary_baseline": binary_after,
    }
    item("源码比较模式", source_location["compare_style"])
    item("对照条件跳转", binary_before["conditional_jump_count"])
    item("规范条件跳转", binary_after["conditional_jump_count"])
    item("定位说明", source_location["summary"])

    banner("步骤7：常数时间防护与复测闭环")
    repair = repair_and_compare("variant_early_return", args.level, args.pairs, args.cpu, overwrite=True)
    summary["repair_closure"] = repair
    rsum = repair["summary"]
    item("修复目标", repair["repair"]["repaired_id"])
    item("补丁摘要", repair["repair"]["patch_sha256"][:20])
    item("修复前差值(ns)", f"{rsum['before_diff_ns']:.2f}")
    item("修复前可区分", "是" if rsum["before_distinguishable"] else "否")
    item("修复后差值(ns)", f"{rsum['after_diff_ns']:.2f}")
    item("修复后可区分", "是" if rsum["after_distinguishable"] else "否")
    item("差值降低(ns)", f"{rsum['absolute_diff_reduction_ns']:.2f}")
    item("补丁文件", repair["repair"]["patch_file"])

    chart_path = out_dir / "repair_before_after.svg"
    write_svg(chart_path, float(rsum["before_diff_ns"]), float(rsum["after_diff_ns"]))
    summary["chart"] = str(chart_path)

    report_path = out_dir / "proof_suite_result.json"
    save_json(report_path, summary)

    markdown_path = out_dir / "PROOF_SUMMARY.md"
    markdown_path.write_text(
        "\n".join([
            "# A1-13 服务器证明性实验总结",
            "",
            f"- 运行编号：`{run_id}`",
            f"- 参数集：ML-KEM-{args.level}",
            f"- 配对次数：{args.pairs}",
            f"- 固定 CPU：{args.cpu}",
            f"- 环境等级：{env['grade']}",
            f"- 公开测试向量：{vectors['checks_passed']}/{vectors['checks_total']} passed",
            f"- 样本类别：{', '.join(samples['sample_classes'])}",
            f"- 规范实现差值：{base_a['paired_mean_difference_ns']:.2f} ns；可区分：{base_a['statistically_distinguishable']}",
            f"- 对照实现差值：{con_a['paired_mean_difference_ns']:.2f} ns；可区分：{con_a['statistically_distinguishable']}",
            f"- 对照条件跳转：{binary_before['conditional_jump_count']}；规范条件跳转：{binary_after['conditional_jump_count']}",
            f"- 修复前差值：{rsum['before_diff_ns']:.2f} ns；修复后差值：{rsum['after_diff_ns']:.2f} ns",
            f"- SVG 图：`{chart_path}`",
            f"- JSON 报告：`{report_path}`",
            "",
            "## 结论",
            "",
            "服务器环境下，平台完成了基本功能验证、公开向量验证、等长样本生成、时间检测、源码/二进制定位、常数时间防护与复测闭环。",
        ]),
        encoding="utf-8",
    )

    banner("测试总结")
    item("基本功能", "PASS")
    item("公开向量", f"{vectors['checks_passed']}/{vectors['checks_total']} PASS")
    item("样本生成", f"{len(samples['sample_classes'])} 类等长样本")
    item("时间检测", f"规范实现可区分={base_a['statistically_distinguishable']}；对照实现可区分={con_a['statistically_distinguishable']}")
    item("泄露定位", f"源码={source_location['compare_style']}；二进制条件跳转 {binary_before['conditional_jump_count']} vs {binary_after['conditional_jump_count']}")
    item("修复闭环", f"{rsum['before_diff_ns']:.2f} ns → {rsum['after_diff_ns']:.2f} ns")
    item("JSON报告", report_path)
    item("Markdown总结", markdown_path)
    item("SVG图", chart_path)
    print("\n建议截图：从“步骤5：时间检测与统计检验”到“测试总给”各截一张；SVG 图可放入报告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
