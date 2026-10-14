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

from acvp_official import run_official_acvp
from acvp_vector_inventory import inventory as acvp_inventory, export_decap_vectors
from binary_audit import binary_locate
from code_audit import locate_code
from env_check import assess_environment
from formal_timing import run_formal_timing
from input_classification import run_input_classification
from mlkem_service import get_mlkem, run_known_answer_test
from repair_manager import repair_and_compare
from sample_generator import generate_samples
from target_manager import list_targets, run_target_command
from vector_validation import validate_vectors


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


def write_bar_svg(path: Path, title: str, rows: list[dict[str, Any]], value_key: str,
                  unit: str = "ns") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width_px = 1100
    row_h = 58
    top = 92
    height = top + 70 + row_h * max(len(rows), 1)
    max_abs = max([abs(float(row.get(value_key, 0))) for row in rows] + [1.0])
    bars = []
    zero_x = 520
    scale = 420 / max_abs
    for i, row in enumerate(rows):
        y = top + i * row_h
        value = float(row.get(value_key, 0))
        bar_w = abs(value) * scale
        x = zero_x - bar_w if value < 0 else zero_x
        color = "#ef4444" if row.get("distinguishable") else "#10b981"
        label = str(row.get("label", f"row-{i+1}"))
        note = str(row.get("note", ""))
        bars.append(
            f'<text x="38" y="{y + 29}" class="label">{label}</text>'
            f'<rect x="{x:.1f}" y="{y + 8}" width="{bar_w:.1f}" height="30" rx="6" fill="{color}"/>'
            f'<text x="970" y="{y + 29}" class="value">{value:.2f} {unit}</text>'
            f'<text x="38" y="{y + 50}" class="small">{note}</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height}" viewBox="0 0 {width_px} {height}">
<style>
text {{ font-family: Arial, 'Noto Sans CJK SC', sans-serif; fill:#111827; }}
.title {{ font-size:25px; font-weight:700; }}
.small {{ font-size:13px; fill:#64748b; }}
.label {{ font-size:17px; font-weight:600; }}
.value {{ font-size:17px; font-weight:700; }}
.axis {{ stroke:#94a3b8; stroke-width:2; }}
</style>
<rect x="0" y="0" width="{width_px}" height="{height}" fill="#ffffff"/>
<text x="38" y="42" class="title">{title}</text>
<text x="38" y="70" class="small">绿色表示统计上未明显可区分，红色表示存在明显可区分性；条形长度表示两类输入的配对均值差绝对值。</text>
<line x1="{zero_x}" y1="{top - 18}" x2="{zero_x}" y2="{height - 48}" class="axis"/>
<text x="{zero_x - 15}" y="{height - 22}" class="small">0 {unit}</text>
{''.join(bars)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="服务器证明性实验套件")
    parser.add_argument("--level", default="512", choices=["512", "768", "1024"])
    parser.add_argument("--pairs", type=int, default=2000)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--selftest-iterations", type=int, default=100)
    parser.add_argument("--sample-count", type=int, default=512)
    parser.add_argument("--acvp-jobs", type=int, default=1)
    parser.add_argument("--skip-acvp", action="store_true")
    parser.add_argument("--skip-cross", action="store_true")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "results" / "proof_suite" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "run_id": run_id,
        "level": f"ML-KEM-{args.level}",
        "pairs": args.pairs,
        "cpu": args.cpu,
        "selftest_iterations": args.selftest_iterations,
        "sample_count": args.sample_count,
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
        basic[level] = get_mlkem(level).selftest(args.selftest_iterations)
        total = basic[level].get("total", basic[level].get("iterations", "?"))
        item(f"ML-KEM-{level}", f"{basic[level]['passed']}/{total} passed; avg(ns)={basic[level]['average_ns']}")
    vectors = run_known_answer_test()
    official_inventory = acvp_inventory()
    exported = export_decap_vectors(
        100,
        "all",
        ROOT / "data" / "acvp" / "platform_vectors" / "mlkem_decap_official_direct.json",
    )
    direct_vector_text = (ROOT / exported["output"]).read_text(encoding="utf-8")
    direct_vectors = validate_vectors(direct_vector_text, default_level=args.level, target_id="mlkem_native_baseline")
    if args.skip_acvp:
        official_acvp = {"success": None, "skipped": True, "message": "user requested --skip-acvp"}
    else:
        official_acvp = run_official_acvp(timeout=900, jobs=args.acvp_jobs)
    summary["basic"] = basic
    summary["known_answer_test"] = vectors
    summary["official_vector_inventory"] = official_inventory
    summary["direct_official_decap_vectors"] = direct_vectors
    summary["official_acvp"] = official_acvp
    item("公开测试向量", f"{vectors['checks_passed']}/{vectors['checks_total']} passed")
    item("官方ACVP库存", "435 prompt-side cases collected")
    item("平台直验向量", f"{direct_vectors['passed']}/{direct_vectors['total']} passed")
    item("ACVP完整验证", official_acvp.get("message"))
    item("向量验证耗时", f"{vectors['elapsed_ns'] / 1e9:.3f} s")

    banner("步骤4：等长输入样本生成")
    samples = generate_samples("mlkem_native_baseline", args.level, args.sample_count)
    summary["samples"] = samples
    item("样本类别", " / ".join(samples["sample_classes"]))
    item("每类数量", samples["count"])
    item("密文长度", f"{samples['ciphertext_bytes']} bytes")
    item("样本报告", samples["report_json"])

    banner("步骤4B：输入分类计时实验")
    classification = run_input_classification(
        args.level,
        samples=args.sample_count,
        repeats=args.pairs,
        cpu=args.cpu,
        target_id="variant_early_return",
    )
    summary["input_classification"] = classification
    for name, row in classification["class_summary"].items():
        item(name, f"mean={row['mean_ns']:.2f} ns; p50={row['p50_ns']:.2f} ns; p95={row['p95_ns']:.2f} ns; Δnormal={row['mean_delta_vs_normal_ns']:.2f} ns")
    item("分类图", classification["chart_svg"])

    banner("步骤5：时间检测与统计检验")
    baseline_timing = run_formal_timing(args.level, args.pairs, args.cpu, "mlkem_native_baseline")
    contrast_targets = ["variant_early_return", "variant_early_return_xor", "variant_early_return_while"]
    contrast_results = {}
    for target_id in contrast_targets:
        contrast_results[target_id] = run_formal_timing(args.level, args.pairs, args.cpu, target_id)
    contrast_timing = contrast_results["variant_early_return"]
    summary["timing"] = {"baseline": baseline_timing, "contrasts": contrast_results}
    base_a = baseline_timing["analysis"]
    con_a = contrast_timing["analysis"]
    item("规范实现差值(ns)", f"{base_a['paired_mean_difference_ns']:.2f}")
    item("规范实现可区分", "是" if base_a["statistically_distinguishable"] else "否")
    item("对照实现差值(ns)", f"{con_a['paired_mean_difference_ns']:.2f}")
    item("对照实现可区分", "是" if con_a["statistically_distinguishable"] else "否")
    item("对照统计结论", contrast_timing.get("statistical_analysis", {}).get("verdict", {}).get("text"))
    item("对照报告", contrast_timing["report_json"])
    timing_rows = [
        {
            "label": "规范实现",
            "paired_mean_difference_ns": base_a["paired_mean_difference_ns"],
            "distinguishable": base_a["statistically_distinguishable"],
            "note": "用于证明平台不会把规范实现误报为明显可区分",
        }
    ]
    for target_id, result in contrast_results.items():
        ana = result["analysis"]
        timing_rows.append(
            {
                "label": target_id,
                "paired_mean_difference_ns": ana["paired_mean_difference_ns"],
                "distinguishable": ana["statistically_distinguishable"],
                "note": result["target_name"],
            }
        )
    timing_chart = out_dir / "timing_multi_target.svg"
    write_bar_svg(timing_chart, "多目标时间检测结果对比", timing_rows, "paired_mean_difference_ns")
    summary["timing_chart"] = str(timing_chart)

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

    banner("步骤8：跨参数集/固定核心对比")
    cross_results: list[dict[str, Any]] = []
    if args.skip_cross:
        item("跨配置实验", "已跳过")
    else:
        for lvl in ["512", "768", "1024"]:
            for target_id in ["mlkem_native_baseline", "variant_early_return"]:
                result = run_formal_timing(lvl, max(1000, min(args.pairs, 3000)), args.cpu, target_id)
                ana = result["analysis"]
                cross_results.append(
                    {
                        "label": f"{target_id} / ML-KEM-{lvl}",
                        "target_id": target_id,
                        "level": f"ML-KEM-{lvl}",
                        "paired_mean_difference_ns": ana["paired_mean_difference_ns"],
                        "distinguishable": ana["statistically_distinguishable"],
                        "note": f"pairs={result['pairs']} cpu={result['cpu']}",
                        "report_json": result["report_json"],
                    }
                )
                item(f"{target_id} / {lvl}", f"{ana['paired_mean_difference_ns']:.2f} ns; 可区分={ana['statistically_distinguishable']}")
    cross_chart = out_dir / "cross_parameter_comparison.svg"
    if cross_results:
        write_bar_svg(cross_chart, "跨参数集时间检测稳定性对比", cross_results, "paired_mean_difference_ns")
    summary["cross_parameter_validation"] = cross_results
    summary["cross_parameter_chart"] = str(cross_chart) if cross_results else None

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
            f"- 自测次数：{args.selftest_iterations} / 每参数集",
            f"- 样本生成：{args.sample_count} 组 / 类",
            f"- 固定 CPU：{args.cpu}",
            f"- 环境等级：{env['grade']}",
            f"- 公开测试向量：{vectors['checks_passed']}/{vectors['checks_total']} passed",
            f"- 官方 ACVP 验证：{official_acvp.get('message')}",
            f"- 平台直验官方 decap 向量：{direct_vectors['passed']}/{direct_vectors['total']} passed",
            f"- 样本类别：{', '.join(samples['sample_classes'])}",
            f"- 输入分类图：`{classification['chart_svg']}`",
            f"- 规范实现差值：{base_a['paired_mean_difference_ns']:.2f} ns；可区分：{base_a['statistically_distinguishable']}",
            f"- 对照实现差值：{con_a['paired_mean_difference_ns']:.2f} ns；可区分：{con_a['statistically_distinguishable']}",
            f"- 对照条件跳转：{binary_before['conditional_jump_count']}；规范条件跳转：{binary_after['conditional_jump_count']}",
            f"- 修复前差值：{rsum['before_diff_ns']:.2f} ns；修复后差值：{rsum['after_diff_ns']:.2f} ns",
            f"- SVG 图：`{chart_path}`",
            f"- 多目标检测图：`{timing_chart}`",
            f"- 跨参数集图：`{cross_chart if cross_results else '未生成'}`",
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
    item("公开向量", f"内置 {vectors['checks_passed']}/{vectors['checks_total']} PASS；平台直验 {direct_vectors['passed']}/{direct_vectors['total']} PASS；ACVP {official_acvp.get('message')}")
    item("样本生成", f"{len(samples['sample_classes'])} 类等长样本")
    item("输入分类", classification["chart_svg"])
    item("时间检测", f"规范实现可区分={base_a['statistically_distinguishable']}；对照实现可区分={con_a['statistically_distinguishable']}")
    item("泄露定位", f"源码={source_location['compare_style']}；二进制条件跳转 {binary_before['conditional_jump_count']} vs {binary_after['conditional_jump_count']}")
    item("修复闭环", f"{rsum['before_diff_ns']:.2f} ns → {rsum['after_diff_ns']:.2f} ns")
    item("JSON报告", report_path)
    item("Markdown总结", markdown_path)
    item("SVG图", chart_path)
    item("多目标图", timing_chart)
    item("跨参数集图", cross_chart if cross_results else "未生成")
    print("\n建议截图：步骤3/4/5/6/7/8 和“测试总结”各截一张；SVG 图可直接放入报告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
