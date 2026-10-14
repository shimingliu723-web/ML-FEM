"""Cross-compiler and optimization validation used by the desktop software."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import subprocess
from pathlib import Path


OPTIMIZATIONS = ("-O2", "-O3", "-Os")
VARIANTS = {
    "baseline": "mlkem_native_baseline",
    "compare_early": "case_compare_early",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compiler_candidates() -> dict[str, Path]:
    candidates: dict[str, Path] = {}
    gcc = shutil.which("gcc")
    if gcc:
        candidates["gcc"] = Path(gcc)
    known_clang = Path("/disk4/lsm/miniconda3/pkgs/clang-17-17.0.6-default_hb5137d0_8/bin/clang-17")
    clang = shutil.which("clang-17") or shutil.which("clang")
    if clang:
        candidates["clang"] = Path(clang)
    elif known_clang.is_file():
        candidates["clang"] = known_clang
    return candidates


def _compiler_env(name: str, compiler: Path) -> dict[str, str]:
    env = os.environ.copy()
    if name == "clang" and "/disk4/lsm/miniconda3/pkgs/" in str(compiler):
        paths = [
            "/disk4/lsm/miniconda3/pkgs/libclang-cpp17-17.0.6-default_hb5137d0_8/lib",
            "/disk4/lsm/miniconda3/pkgs/libllvm17-17.0.6-ha7bfdaf_3/lib",
            "/disk4/lsm/miniconda3/lib",
        ]
        env["LD_LIBRARY_PATH"] = ":".join(paths + [env.get("LD_LIBRARY_PATH", "")]).rstrip(":")
    return env


def available_configurations() -> list[dict]:
    rows = []
    for name, compiler in _compiler_candidates().items():
        env = _compiler_env(name, compiler)
        version = subprocess.check_output([str(compiler), "--version"], env=env, text=True).splitlines()[0]
        for optimization in OPTIMIZATIONS:
            rows.append({"id": f"{name}-{optimization[1:].lower()}", "compiler": name,
                         "compiler_path": str(compiler), "compiler_version": version,
                         "optimization": optimization})
    return rows


def _build_target(root: Path, config: dict, variant: str) -> dict:
    if variant == "baseline":
        source = root / "core/mlkem-native/mlkem"
        random_source = root / "core/randombytes.c"
    else:
        source = root / "targets/case_compare_early/src/mlkem"
        random_source = root / "targets/case_compare_early/src/randombytes.c"
    compiler = Path(config["compiler_path"])
    target_id = f"crossbuild_{config['compiler']}_{config['optimization'][1:].lower()}_{variant}"
    directory = root / "targets" / target_id
    lib_dir = directory / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    library = lib_dir / "libmlkem512.so"
    command = [str(compiler), config["optimization"], "-fPIC", "-std=c99", "-Wall", "-Wextra", "-Wpedantic",
               "-I" + str(source), "-DMLK_CONFIG_NAMESPACE_PREFIX=mlkem", "-DMLK_CONFIG_PARAMETER_SET=512",
               "-shared", str(source / "mlkem_native.c"), str(random_source), "-o", str(library)]
    proc = subprocess.run(command, cwd=root, env=_compiler_env(config["compiler"], compiler), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    if proc.returncode:
        raise ValueError(f"{config['id']} / {variant} 编译失败：{proc.stdout[-1200:]}")
    target = {
        "id": target_id, "name": f"跨构建 {config['id']} {variant}", "role": "experiment",
        "description": "由软件高级验证模块生成的跨编译实验目标", "levels": ["512"],
        "library_template": f"targets/{target_id}/lib/libmlkem{{level}}.so", "build": [], "selftest": [],
        "case_type": "cross_build", "mechanism": "fixed_flow_baseline" if variant == "baseline" else "comparison_early_exit",
        "sample_strategy": "复用同一批 ML-KEM-512 等长输入", "repair_strategy": "本验证不执行修复",
        "limitations": "结论仅适用于当前CPU、编译器版本、优化级别、输入与测量环境。",
    }
    (directory / "target.json").write_text(json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8")
    profile = {"compiler": config["compiler_version"], "compiler_path": str(compiler),
               "optimization_flags": config["optimization"], "command": command,
               "library_sha256": {"512": _digest(library)}, "library_bytes": library.stat().st_size}
    (directory / "build_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"target_id": target_id, "compiler": config["compiler"],
            "compiler_version": config["compiler_version"], "optimization": config["optimization"],
            "configuration": config["id"], "variant": variant, "library": str(library),
            "library_sha256": _digest(library), "library_bytes": library.stat().st_size,
            "build_command": command}


def run_cross_build(root: Path, output: Path, sample_report: str, pairs: int, cpu: int,
                    repeats: int, config_ids: list[str] | None = None) -> dict:
    from binary_audit import binary_locate
    from software_service import detect

    available = available_configurations()
    by_id = {item["id"]: item for item in available}
    requested = config_ids or [f"{name}-{opt[1:].lower()}" for name in ("gcc", "clang") for opt in OPTIMIZATIONS]
    unknown = [item for item in requested if item not in by_id]
    selected = [by_id[item] for item in requested if item in by_id]
    if not selected:
        raise ValueError("没有可用的 GCC/Clang 编译器，无法执行跨编译验证")
    report = {"kind": "cross_build", "success": False, "pairs": pairs, "repeats": repeats, "cpu": cpu,
              "sample_report": sample_report, "requested_configurations": requested,
              "available_configurations": list(by_id), "missing_configurations": unknown, "rows": []}
    for config in selected:
        for variant in VARIANTS:
            built = _build_target(root, config, variant)
            detected = detect(built["target_id"], "512", sample_report, pairs, cpu, repeats, 2)
            runs = detected["runs"]
            diffs = [r["analysis"]["paired_mean_difference_ns"] for r in runs]
            valid = [r["analysis"]["valid"]["mean_ns"] for r in runs]
            changed = [r["analysis"]["changed"]["mean_ns"] for r in runs]
            report["rows"].append({**built, "basic_success": detected["correctness"]["success"],
                "formal_environment": detected["formal_environment"],
                "same_input_control_passed": detected["same_input_control_passed"],
                "conclusion": detected["conclusion"], "round_differences_ns": diffs,
                "mean_difference_ns": statistics.fmean(diffs),
                "stdev_difference_ns": statistics.stdev(diffs) if len(diffs) > 1 else 0.0,
                "valid_mean_ns": statistics.fmean(valid), "changed_mean_ns": statistics.fmean(changed),
                "all_rounds_significant": all(r["statistics"]["verdict"]["statistically_significant"] for r in runs),
                "binary_counts": binary_locate(built["target_id"], "512")["counts"],
                "detection_report": detected["report_json"]})
    baselines = [r for r in report["rows"] if r["variant"] == "baseline"]
    comparisons = [r for r in report["rows"] if r["variant"] == "compare_early"]
    report["functional_success"] = all(r["basic_success"] for r in report["rows"])
    report["comparison_direction_consistent"] = all(
        (all(x < 0 for x in r["round_differences_ns"]) or all(x > 0 for x in r["round_differences_ns"]))
        for r in comparisons)
    report["baseline_repeated_difference_count"] = sum(r["conclusion"] == "重复观察到同方向差异" for r in baselines)
    report["formal_accepted_rows"] = sum(bool(r["formal_environment"]) for r in report["rows"])
    report["formal_total_rows"] = len(report["rows"])
    report["complete_matrix"] = not unknown and len({r["compiler"] for r in report["rows"]}) >= 2
    report["success"] = bool(report["functional_success"] and report["comparison_direction_consistent"]
                             and report["baseline_repeated_difference_count"] == 0)
    report["conclusion"] = ("跨编译器与优化级别矩阵验证完成" if report["success"] and report["complete_matrix"]
                            else "可用构建配置验证完成，但完整矩阵或验收条件未全部满足")
    report["scope"] = "本实验只改变编译器和优化级别；结论不能推广到其他CPU架构或网络路径。"

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    labels = [item["id"] for item in selected]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for variant, marker, title in [("baseline", "o", "Baseline"), ("compare_early", "s", "Comparison case")]:
        rows = [r for r in report["rows"] if r["variant"] == variant]
        axes[0].errorbar(range(len(rows)), [r["mean_difference_ns"] for r in rows],
                         yerr=[r["stdev_difference_ns"] for r in rows], marker=marker, capsize=4, label=title)
    axes[0].axhline(0, color="#777777", linestyle="--", linewidth=1)
    axes[0].set_xticks(range(len(labels)), labels, rotation=20)
    axes[0].set_ylabel("Changed - normal (ns)")
    axes[0].set_title("Timing difference across build configurations")
    axes[0].legend()
    baseline = [r for r in report["rows"] if r["variant"] == "baseline"]
    axes[1].bar([x - .18 for x in range(len(baseline))], [r["valid_mean_ns"] / 1000 for r in baseline], .36,
                label="Mean decapsulation (us)")
    ax2 = axes[1].twinx()
    ax2.bar([x + .18 for x in range(len(baseline))], [r["library_bytes"] / 1024 for r in baseline], .36,
            color="#999999", label="Library size (KiB)")
    axes[1].set_xticks(range(len(labels)), labels, rotation=20)
    axes[1].set_ylabel("Time (us)")
    ax2.set_ylabel("Library size (KiB)")
    axes[1].set_title("Baseline performance and binary size")
    h1, l1 = axes[1].get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    axes[1].legend(h1 + h2, l1 + l2, loc="upper left")
    chart = output / "cross-build-comparison.png"
    fig.savefig(chart, dpi=180, facecolor="white")
    plt.close(fig)
    report["chart_png"] = str(chart)
    lines = ["=" * 86, "跨编译器与优化级别验证", "=" * 86,
             f"规模: {pairs} 对 × {repeats} 轮; CPU={cpu}; 配置={','.join(item['id'] for item in selected)}"]
    for row in report["rows"]:
        lines.append(f"{row['configuration']} / {row['variant']}: mean_diff={row['mean_difference_ns']:.2f} ns; "
                     f"formal={row['formal_environment']}; conclusion={row['conclusion']}")
    lines += ["-" * 86, f"结论: {report['conclusion']}", f"范围: {report['scope']}"]
    log = output / "cross-build-summary.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report["summary_log"] = str(log)
    return report
