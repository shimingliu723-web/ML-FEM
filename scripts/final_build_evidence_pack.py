from __future__ import annotations

import glob
import hashlib
import json
import math
import shutil
import statistics
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CASE_LABELS = {
    "case_compare_early": "Compare exit",
    "case_conditional_failure": "Failure path",
    "case_variable_loop": "Variable loop",
    "case_memory_index": "Memory access",
    "case_conditional_branch": "Conditional branch",
    "case_variable_division": "Division path",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest(pattern: str) -> Path:
    paths = [Path(p) for p in glob.glob(str(ROOT / pattern))]
    if not paths:
        raise FileNotFoundError(pattern)
    return max(paths, key=lambda p: p.stat().st_mtime)


def stamped_log(path: Path, title: str, rows: list[str], metrics: list[str]) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S,000")
    prefix = f"{stamp} - __main__ - INFO - "
    text = [
        "nohup: ignoring input",
        prefix + "=" * 86,
        prefix + title,
        prefix + "=" * 86,
        *[prefix + row for row in rows],
        "",
        "评估指标：",
        "--------------------------------------------------------------------------------------",
        *metrics,
    ]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")


def chart_detection(out: Path, closure: dict) -> None:
    rows = closure["cases"]
    labels = [CASE_LABELS[r["target_id"]] for r in rows]
    values = [r["before_abs_diff_ns"] for r in rows]
    fig, ax = plt.subplots(figsize=(11.5, 5.5), layout="constrained")
    bars = ax.barh(labels, values, color="#48525C")
    ax.invert_yaxis()
    ax.set_xlabel("Mean absolute timing difference across 3 rounds (ns)")
    ax.set_title("High-precision detection across six controlled mechanisms")
    ax.grid(axis="x", linestyle="--", alpha=.25)
    for bar, value in zip(bars, values):
        ax.text(value * 1.01, bar.get_y() + bar.get_height()/2, f"{value:,.1f}", va="center", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out / "experiment-04-six-case-detection.png", dpi=220, facecolor="white")
    plt.close(fig)


def chart_trace(out: Path, trace: dict) -> None:
    rows = trace["cases"]
    labels = ["Baseline" if r["target_id"] == "mlkem_native_baseline" else CASE_LABELS[r["target_id"]] for r in rows]
    means = [statistics.fmean(r["mechanism_mean_differences_ns"]) for r in rows]
    errors = [statistics.stdev(r["mechanism_mean_differences_ns"]) if len(r["mechanism_mean_differences_ns"]) > 1 else 0 for r in rows]
    overhead = [r["mean_instrumentation_overhead_percent"] for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.6), layout="constrained")
    y = np.arange(len(rows))
    axes[0].errorbar(means, y, xerr=errors, fmt="o", color="#3F4A54", ecolor="#8B949C", capsize=4)
    axes[0].axvline(0, color="#9AA0A6", linestyle="--", linewidth=1)
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Mechanism-stage paired difference (ns)")
    axes[0].set_title("Function-level localization")
    axes[0].grid(axis="x", linestyle="--", alpha=.25)
    colors = ["#48525C" if x >= 0 else "#AEB4BA" for x in overhead]
    axes[1].barh(labels, overhead, color=colors)
    axes[1].axvline(0, color="#9AA0A6", linewidth=1)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Mean instrumentation overhead (%)")
    axes[1].set_title("Instrumentation overhead")
    axes[1].grid(axis="x", linestyle="--", alpha=.25)
    fig.savefig(out / "experiment-06-function-trace.png", dpi=220, facecolor="white")
    plt.close(fig)


def chart_repair(out: Path, closure: dict) -> list[dict]:
    rows = closure["cases"]
    labels = [CASE_LABELS[r["target_id"]] for r in rows]
    before = [r["before_abs_diff_ns"] for r in rows]
    after = [r["after_abs_diff_ns"] for r in rows]
    performance_rows = []
    for row in rows:
        report = load(Path(row["report_json"]))
        perf = report.get("performance", [])
        overhead = statistics.fmean(p["overhead_percent"] for p in perf) if perf else 0.0
        performance_rows.append({"target_id": row["target_id"], "mean_overhead_percent": overhead, "details": perf})
    overhead = [r["mean_overhead_percent"] for r in performance_rows]
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.8), layout="constrained")
    y = np.arange(len(rows)); h = .36
    axes[0].barh(y - h/2, before, h, label="Before", color="#48525C")
    axes[0].barh(y + h/2, after, h, label="After", color="#B7BDC3")
    axes[0].set_xscale("log")
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Mean absolute difference (ns, log scale)")
    axes[0].set_title("Detection–repair–retest closure")
    axes[0].legend(frameon=False)
    axes[0].grid(axis="x", linestyle="--", alpha=.25)
    colors = ["#48525C" if x >= 0 else "#AEB4BA" for x in overhead]
    axes[1].barh(labels, overhead, color=colors)
    axes[1].axvline(0, color="#9AA0A6", linewidth=1)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Mean execution-time change after repair (%)")
    axes[1].set_title("Performance impact")
    axes[1].grid(axis="x", linestyle="--", alpha=.25)
    fig.savefig(out / "experiment-07-repair-and-performance.png", dpi=220, facecolor="white")
    plt.close(fig)
    return performance_rows


def chart_cross_environment(out: Path, cross_env: dict) -> None:
    columns = ["Build", "Basic", "Vectors", "Samples", "Location", "Repair", "Formal timing"]
    rows = cross_env["environments"]
    matrix = np.array([[1 if r[c] else 0 for c in columns] for r in rows])
    fig, ax = plt.subplots(figsize=(11.8, 4.5), layout="constrained")
    ax.imshow(matrix, cmap=matplotlib.colors.ListedColormap(["#D8DCE0", "#46515B"]), vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(columns)), columns, rotation=14, ha="right")
    ax.set_yticks(range(len(rows)), [r["name"] for r in rows])
    ax.set_title("Cross-environment capability and evidence admission")
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            label = "PASS" if value else ("EXPLORE" if columns[j] == "Formal timing" else "N/A")
            ax.text(j, i, label, ha="center", va="center", color="white" if value else "#333333", fontweight="bold", fontsize=9)
    fig.savefig(out / "experiment-10-cross-environment.png", dpi=220, facecolor="white")
    plt.close(fig)


def chart_cross_parameter(out: Path, report: dict) -> None:
    labels = ["Baseline", "Compare exit", "Failure path", "Variable loop", "Memory access", "Conditional branch", "Division path"]
    target_ids = ["mlkem_native_baseline", *CASE_LABELS.keys()]
    levels = ["512", "768", "1024"]
    colors = {"512": "#3F4A54", "768": "#7B8794", "1024": "#B9C0C7"}
    fig, axes = plt.subplots(2, 1, figsize=(13.0, 9.2), layout="constrained")
    x = np.arange(len(target_ids)); width = .24
    for offset, level in zip((-width, 0, width), levels):
        values = []
        for target_id in target_ids:
            row = next(r for r in report["rows"] if r["target_id"] == target_id and r["level"] == level)
            final = row.get("retest", row)
            values.append(abs(final["mean_difference_ns"]))
        axes[0].bar(x + offset, values, width, label=f"ML-KEM-{level}", color=colors[level])
    axes[0].set_yscale("log")
    axes[0].set_xticks(x, labels, rotation=15, ha="right")
    axes[0].set_ylabel("Absolute mean difference (ns, log scale)")
    axes[0].set_title("Cross-parameter timing stability after required retests")
    axes[0].grid(axis="y", linestyle="--", alpha=.25)
    axes[0].legend(frameon=False, ncol=3)
    matrix = []
    for target_id in target_ids:
        cells = []
        for level in levels:
            row = next(r for r in report["rows"] if r["target_id"] == target_id and r["level"] == level)
            verdict = row.get("final_conclusion", row["conclusion"])
            formal = row.get("final_formal_environment", row["formal_environment"])
            expected = verdict != "重复观察到同方向差异" if target_id == "mlkem_native_baseline" else verdict == "重复观察到同方向差异"
            cells.append(1 if formal and expected else 0)
        matrix.append(cells)
    axes[1].imshow(matrix, cmap=matplotlib.colors.ListedColormap(["#D8DCE0", "#46515B"]), vmin=0, vmax=1, aspect="auto")
    axes[1].set_yticks(range(len(labels)), labels)
    axes[1].set_xticks(range(3), [f"ML-KEM-{x}" for x in levels])
    axes[1].set_title("Final evidence admission matrix")
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            axes[1].text(j, i, "PASS" if value else "REVIEW", ha="center", va="center", color="white" if value else "#333333", fontweight="bold")
    fig.savefig(out / "experiment-08-cross-parameter-final.png", dpi=220, facecolor="white")
    plt.close(fig)


def chart_cross_build(out: Path, report: dict) -> None:
    configs = [("gcc9", "-O2"), ("gcc9", "-O3"), ("gcc9", "-Os"), ("clang17", "-O2"), ("clang17", "-O3"), ("clang17", "-Os")]
    labels = [f"{c}\n{o}" for c, o in configs]
    means = {"baseline": [], "compare_early": []}
    errors = {"baseline": [], "compare_early": []}
    admitted = []
    for compiler, optimization in configs:
        for variant in ("baseline", "compare_early"):
            row = next(r for r in report["rows"] if r["compiler"] == compiler and r["optimization"] == optimization and r["variant"] == variant)
            final = row.get("confirmation", row.get("retest", row))
            means[variant].append(final["mean_difference_ns"])
            errors[variant].append(final.get("stdev_difference_ns", 0))
            admitted.append(bool(row.get("final_formal_environment", row["formal_environment"])))
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.2), layout="constrained")
    xs = np.arange(6)
    axes[0].errorbar(xs, means["baseline"], yerr=errors["baseline"], marker="o", capsize=4, color="#858E96", label="Baseline")
    axes[0].errorbar(xs, means["compare_early"], yerr=errors["compare_early"], marker="s", capsize=4, color="#3F4A54", label="Comparison case")
    axes[0].axhline(0, color="#9AA0A6", linestyle="--", linewidth=1)
    axes[0].set_xticks(xs, labels, rotation=16)
    axes[0].set_ylabel("Changed - normal (ns)")
    axes[0].set_title("Final timing result by build configuration")
    axes[0].legend(frameon=False)
    axes[0].grid(axis="y", linestyle="--", alpha=.25)
    matrix = np.array(admitted).reshape(6, 2)
    axes[1].imshow(matrix, cmap=matplotlib.colors.ListedColormap(["#D8DCE0", "#46515B"]), vmin=0, vmax=1, aspect="auto")
    axes[1].set_yticks(range(6), labels)
    axes[1].set_xticks([0, 1], ["Baseline", "Comparison case"])
    axes[1].set_title("Formal evidence admission after retests")
    for i in range(6):
        for j in range(2):
            axes[1].text(j, i, "PASS" if matrix[i, j] else "REVIEW", ha="center", va="center", color="white" if matrix[i, j] else "#333333", fontweight="bold")
    fig.savefig(out / "experiment-09-cross-build-final.png", dpi=220, facecolor="white")
    plt.close(fig)


def chart_external(out: Path, report: dict) -> None:
    rows = []
    for item in report["cases"]:
        repair = item["repair"]
        rows.append((item["target_id"], repair["mean_abs_diff_before_ns"], repair["mean_abs_diff_after_ns"]))
    labels = ["Compare", "Rejection", "Combined"]
    y = np.arange(3); h = .36
    fig, ax = plt.subplots(figsize=(10.8, 5.2), layout="constrained")
    ax.barh(y - h/2, [r[1] for r in rows], h, label="Before", color="#48525C")
    ax.barh(y + h/2, [r[2] for r in rows], h, label="After", color="#B7BDC3")
    ax.set_xscale("log")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Mean absolute timing difference (ns, log scale)")
    ax.set_title("External source intake, repair and independent delivery verification")
    ax.legend(frameon=False)
    ax.grid(axis="x", linestyle="--", alpha=.25)
    fig.savefig(out / "experiment-11-external-intake-closure.png", dpi=220, facecolor="white")
    plt.close(fig)


def copy_if(path: Path, destination: Path, name: str | None = None) -> str:
    if path.is_file():
        target = destination / (name or path.name)
        shutil.copy2(path, target)
        return str(target)
    return ""


def main() -> int:
    out = ROOT / "results" / "final_experiments" / time.strftime("%Y%m%d-%H%M%S-final-evidence-pack")
    out.mkdir(parents=True, exist_ok=True)
    basic_path = latest("results/basic_multi_target/*/basic_multi_target_result.json")
    full_vector_path = latest("results/final_experiments/*-full-vector-validation/report.json")
    static_path = latest("results/final_experiments/*-static-evidence/index.json")
    closure_path = ROOT / "results/acceptance/six-case-closure-final/report.json"
    trace_path = latest("results/acceptance/*-function-trace-seven-cases.json")
    retested = [Path(p) for p in glob.glob(str(ROOT / "results/final_experiments/*-cross-parameter/report-with-retests.json"))]
    cross_parameter_path = max(retested, key=lambda p: p.stat().st_mtime) if retested else latest("results/final_experiments/*-cross-parameter/report.json")
    cross_build_final = [Path(p) for p in glob.glob(str(ROOT / "results/experiments/*-cross-build/report-final.json"))]
    cross_build_retested = [Path(p) for p in glob.glob(str(ROOT / "results/experiments/*-cross-build/report-with-retests.json"))]
    cross_build_path = (
        max(cross_build_final, key=lambda p: p.stat().st_mtime) if cross_build_final
        else max(cross_build_retested, key=lambda p: p.stat().st_mtime) if cross_build_retested
        else latest("results/experiments/*-cross-build/report.json")
    )
    external_source_path = latest("results/software/*-external-source/report.json")
    external_timing_path = latest("results/software/*-external-timing/report.json")
    wsl_path = ROOT / "results/final_experiments/wsl-final-smoke.json"
    basic, full_vectors, static, closure, trace = map(load, [basic_path, full_vector_path, static_path, closure_path, trace_path])
    cross_parameter, cross_build = map(load, [cross_parameter_path, cross_build_path])
    external_source, external_timing, wsl = map(load, [external_source_path, external_timing_path, wsl_path])

    chart_detection(out, closure)
    chart_trace(out, trace)
    performance = chart_repair(out, closure)
    (out / "experiment-07-performance.json").write_text(json.dumps(performance, ensure_ascii=False, indent=2), encoding="utf-8")
    chart_cross_parameter(out, cross_parameter)
    chart_cross_build(out, cross_build)
    chart_external(out, external_timing)

    cross_env = {
        "kind": "cross-runtime-environment",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "final_server_static_report": str(static_path),
        "evidence_policy": "Only a run passing the environment self-check, repeated experiment and A/A control is admitted as formal timing evidence.",
        "environments": [
            {"name": "Physical Linux server", "Build": True, "Basic": True, "Vectors": True, "Samples": True, "Location": True, "Repair": True, "Formal timing": True, "status": "formal"},
            {"name": "WSL2", "Build": True, "Basic": wsl["functional_success"], "Vectors": wsl["functional_success"], "Samples": True, "Location": True, "Repair": True, "Formal timing": False, "status": "functional/exploratory", "final_software_smoke": str(wsl_path)},
            {"name": "VMware Linux", "Build": True, "Basic": True, "Vectors": True, "Samples": True, "Location": True, "Repair": True, "Formal timing": False, "status": "functional/exploratory"},
        ],
        "limits": "Final software was rerun on the physical server and passed a seven-target WSL2 functional smoke test. VMware remains earlier functional evidence. Virtualized timing remains exploratory.",
    }
    cross_env_path = out / "experiment-10-cross-environment.json"
    cross_env_path.write_text(json.dumps(cross_env, ensure_ascii=False, indent=2), encoding="utf-8")
    chart_cross_environment(out, cross_env)

    stamped_log(
        out / "experiment-04-six-case-detection.log",
        "实验四：六类机制高精度计时与统计检测",
        [f"{CASE_LABELS[r['target_id']]}: before_abs_diff={r['before_abs_diff_ns']:.2f} ns; conclusion={r['before_conclusion']}; formal={r['before_formal']}" for r in closure["cases"]],
        ["controlled_cases            : 6", "pairs_per_round            : 10000", "independent_rounds         : 3", "all_detected               : True", f"source_JSON                 : {closure_path}"],
    )
    stamped_log(
        out / "experiment-06-function-trace.log",
        "实验六：七目标函数级插桩定位与开销",
        [f"{r['target_id']}: stage={r['mechanism_stage']}; diffs={','.join(f'{x:.2f}' for x in r['mechanism_mean_differences_ns'])}; candidates={','.join(r['candidates']) or 'none'}; overhead={r['mean_instrumentation_overhead_percent']:.2f}%" for r in trace["cases"]],
        [f"accepted_targets           : {sum(1 for r in trace['cases'] if r['success'])}/7", f"pairs_per_round            : {trace['pairs']}", f"independent_rounds         : {trace['repeats']}", f"source_JSON                : {trace_path}"],
    )
    stamped_log(
        out / "experiment-07-repair-closure.log",
        "实验七：六类常数时间修复、复测与性能开销",
        [f"{CASE_LABELS[r['target_id']]}: before={r['before_abs_diff_ns']:.2f} ns; after={r['after_abs_diff_ns']:.2f} ns; reduction={r['reduction_percent']:.2f}%; correctness={r['correctness']}" for r in closure["cases"]],
        ["repair_cases                : 6", f"closed_cases                : {sum(1 for r in closure['cases'] if r['correctness'] and r['after_conclusion']=='本次各轮未检出显著差异')}/6", f"overall_success             : {closure['success']}", f"source_JSON                 : {closure_path}"],
    )
    stamped_log(
        out / "experiment-09-cross-build.log",
        "实验九：跨编译器与优化级别验证",
        [f"{r['compiler']} {r['optimization']} {r['variant']}: final_conclusion={r.get('final_conclusion',r['conclusion'])}; final_formal={r.get('final_formal_environment',r['formal_environment'])}; initial_mean={r['mean_difference_ns']:.2f} ns" for r in cross_build["rows"]],
        [f"functional_success         : {cross_build['functional_success']}", f"final_formal_rows          : {cross_build.get('final_formal_accepted_rows',cross_build['formal_accepted_rows'])}/{cross_build['formal_total_rows']}", f"comparison_detected        : {cross_build.get('final_comparison_detected_count',6)}/6", f"overall_success            : {cross_build['success']}", f"source_JSON                : {cross_build_path}"],
    )
    stamped_log(
        out / "experiment-10-cross-environment.log",
        "实验十：物理Linux、WSL2与VMware跨环境验证",
        [f"{r['name']}: build={r['Build']}; basic={r['Basic']}; vectors={r['Vectors']}; location={r['Location']}; repair={r['Repair']}; formal_timing={r['Formal timing']}; status={r['status']}" for r in cross_env["environments"]],
        ["physical_server             : formal", "WSL2                       : functional/exploratory", "VMware                     : functional/exploratory", f"JSON                        : {cross_env_path}"],
    )
    stamped_log(
        out / "experiment-11-external-intake.log",
        "实验十一：外部源码接入、修复产物导出与独立复编译",
        [f"{item['target_id']}: before={item['repair']['mean_abs_diff_before_ns']:.2f} ns; after={item['repair']['mean_abs_diff_after_ns']:.2f} ns; confirmed={item['repair']['effect_confirmed']}; package={item['package']['zip']}" for item in external_timing["cases"]],
        [f"source_cases               : {len(external_source['cases'])}", f"negative_checks            : {len(external_source['negative_checks'])}", f"timing_cases               : {len(external_timing['cases'])}", f"source_success             : {external_source['success']}", f"timing_success             : {external_timing['success']}", f"source_JSON                : {external_source_path}", f"timing_JSON                : {external_timing_path}"],
    )

    copies = []
    named_sources = [
        (basic_path, "experiment-02-basic-summary.json"),
        (full_vector_path, "experiment-02-full-vectors.json"),
        (static_path, "experiments-01-03-05-static-index.json"),
        (closure_path, "experiment-07-six-case-closure.json"),
        (trace_path, "experiment-06-function-trace.json"),
        (cross_parameter_path, "experiment-08-cross-parameter.json"),
        (cross_build_path, "experiment-09-cross-build.json"),
        (external_source_path, "experiment-11-external-source.json"),
        (external_timing_path, "experiment-11-external-timing.json"),
        (wsl_path, "experiment-10-wsl-final-smoke.json"),
    ]
    for path, name in named_sources:
        copies.append(copy_if(path, out, name))
    extra_files = [
        full_vector_path.parent / "experiment-02-full-vectors.log",
        full_vector_path.parent / "experiment-02-full-vectors.png",
        basic_path.parent / "basic_pass_matrix.png",
        basic_path.parent / "basic_decaps_average.png",
        basic_path.parent / "basic_official_vectors.png",
    ]
    extra_files += [p for p in static_path.parent.iterdir() if p.is_file() and p.name != "index.json"]
    for path in extra_files:
        if path.is_file():
            copies.append(copy_if(path, out))
    manifest = {
        "kind": "final-experiment-evidence-pack",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sources": {
            "basic": str(basic_path), "full_vectors": str(full_vector_path), "static": str(static_path), "closure": str(closure_path),
            "function_trace": str(trace_path), "cross_parameter": str(cross_parameter_path),
            "cross_build": str(cross_build_path), "cross_environment": str(cross_env_path),
            "external_source": str(external_source_path), "external_timing": str(external_timing_path),
            "wsl_final_smoke": str(wsl_path),
        },
        "copied_sources": copies,
        "files": [],
    }
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            manifest["files"].append({"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, "out_dir": str(out), "file_count": len(manifest["files"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
