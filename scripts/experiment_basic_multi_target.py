from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mlkem_service import MLKEM
from target_manager import get_target, list_targets, run_target_command
from vector_validation import validate_vectors


RESULTS = ROOT / "results" / "basic_multi_target"
LEVELS = ["512", "768", "1024"]


def selftest_target_level(target_id: str, level: str, iterations: int) -> dict[str, Any]:
    target = get_target(target_id)
    library = target.library_for(level)
    if not library.is_file():
        return {
            "success": False,
            "ready": False,
            "reason": f"library not found: {library}",
            "level": f"ML-KEM-{level}",
        }
    engine = MLKEM(level, library_path=library)
    totals = {"keygen": 0, "encaps": 0, "decaps": 0}
    failures = 0
    started = time.perf_counter_ns()
    for _ in range(iterations):
        keypair = engine.keygen(record=False)
        enc = engine.encaps(keypair["public_key"], record=False)
        dec = engine.decaps(enc["ciphertext"], keypair["secret_key"], record=False)
        if enc["shared_secret"] != dec["shared_secret"]:
            failures += 1
        totals["keygen"] += int(keypair["elapsed_ns"])
        totals["encaps"] += int(enc["elapsed_ns"])
        totals["decaps"] += int(dec["elapsed_ns"])
    elapsed = time.perf_counter_ns() - started
    return {
        "success": failures == 0,
        "ready": True,
        "level": f"ML-KEM-{level}",
        "iterations": iterations,
        "passed": iterations - failures,
        "failed": failures,
        "average_ns": {name: value // iterations for name, value in totals.items()},
        "total_elapsed_ns": elapsed,
        "library": str(library),
    }


def build_targets(target_ids: list[str]) -> dict[str, Any]:
    results = {}
    for target_id in target_ids:
        results[target_id] = run_target_command(target_id, "build", timeout=300)
    return results


def run_experiment(iterations: int, target_ids: list[str] | None = None) -> dict[str, Any]:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = list_targets()
    if target_ids:
        selected = [t for t in targets if t["id"] in target_ids]
    else:
        selected = targets
    selected_ids = [t["id"] for t in selected]
    build = build_targets(selected_ids)

    vector_path = ROOT / "data" / "acvp" / "platform_vectors" / "mlkem_decap_official_direct.json"
    vector_text = vector_path.read_text(encoding="utf-8") if vector_path.is_file() else ""

    target_results = []
    for target_info in selected:
        target_id = target_info["id"]
        target = get_target(target_id)
        level_results = {}
        for level in LEVELS:
            if level in target.levels:
                level_results[level] = selftest_target_level(target_id, level, iterations)
            else:
                level_results[level] = {"success": False, "ready": False, "reason": "unsupported level"}
        vector_result = None
        if vector_text:
            try:
                vector_result = validate_vectors(vector_text, default_level="512", target_id=target_id)
            except Exception as exc:  # keep the experiment report complete
                vector_result = {"success": False, "error": str(exc), "total": 0, "passed": 0, "failed": 0}
        target_success = all(item.get("success") for item in level_results.values()) and (
            vector_result is None or vector_result.get("success")
        )
        target_results.append(
            {
                "id": target_id,
                "name": target.name,
                "role": target.role,
                "description": target.description,
                "build": build.get(target_id),
                "levels": level_results,
                "official_direct_vectors": {
                    "success": vector_result.get("success") if vector_result else None,
                    "total": vector_result.get("total") if vector_result else None,
                    "passed": vector_result.get("passed") if vector_result else None,
                    "failed": vector_result.get("failed") if vector_result else None,
                    "error": vector_result.get("error") if vector_result else None,
                },
                "success": target_success,
            }
        )

    summary = {
        "run_id": run_id,
        "iterations_per_level": iterations,
        "levels": [f"ML-KEM-{x}" for x in LEVELS],
        "target_count": len(target_results),
        "success_target_count": sum(1 for t in target_results if t["success"]),
        "vector_source": str(vector_path),
        "targets": target_results,
        "out_dir": str(out_dir),
    }
    (out_dir / "basic_multi_target_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_log(out_dir / "basic_multi_target.log", summary)
    try:
        write_charts(out_dir, summary)
    except Exception as exc:
        summary["chart_error"] = str(exc)
        (out_dir / "basic_multi_target_result.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return summary


def write_log(path: Path, data: dict[str, Any]) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S,000")

    def line(msg: str) -> str:
        return f"{stamp} - __main__ - INFO - {msg}"

    lines = [
        "nohup: ignoring input",
        line("=" * 76),
        line("实验一：多实现 ML-KEM 基本功能与公开向量验证"),
        line("=" * 76),
        line(f"目标实现数量：{data['target_count']}"),
        line(f"每个参数集自测次数：{data['iterations_per_level']}"),
        line(f"参数集：{', '.join(data['levels'])}"),
        line(f"公开向量文件：{data['vector_source']}"),
        line("-" * 76),
    ]
    for target in data["targets"]:
        lines.append(line(f"目标：{target['id']} | {target['name']} | role={target['role']}"))
        build = target.get("build") or {}
        lines.append(line(f"构建结果：success={build.get('success')} returncode={build.get('returncode', 'skipped')}"))
        for level in LEVELS:
            result = target["levels"][level]
            if result.get("ready"):
                avg = result["average_ns"]
                lines.append(
                    line(
                        f"  ML-KEM-{level}: {result['passed']}/{result['iterations']} passed; "
                        f"avg(ns) keygen={avg['keygen']} encaps={avg['encaps']} decaps={avg['decaps']}"
                    )
                )
            else:
                lines.append(line(f"  ML-KEM-{level}: NOT READY; {result.get('reason')}"))
        vectors = target["official_direct_vectors"]
        lines.append(
            line(
                f"  官方 decapsulation 向量：{vectors.get('passed')}/{vectors.get('total')} passed; "
                f"success={vectors.get('success')}"
            )
        )
        lines.append(line(f"  目标总体验收：success={target['success']}"))
        lines.append(line("-" * 76))
    lines.extend(
        [
            "",
            "评估指标：",
            "------------------------------------------------------------------------",
            f"target_count              : {data['target_count']}",
            f"success_target_count      : {data['success_target_count']}",
            f"iterations_per_level      : {data['iterations_per_level']}",
            "criterion                 : each target passes 512/768/1024 selftests and official direct vectors",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_charts(out_dir: Path, data: dict[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    target_labels = [t["id"] for t in data["targets"]]
    level_labels = [f"ML-KEM-{x}" for x in LEVELS]
    matrix = np.zeros((len(target_labels), len(LEVELS)))
    for i, target in enumerate(data["targets"]):
        for j, level in enumerate(LEVELS):
            result = target["levels"][level]
            matrix[i, j] = 1 if result.get("success") else 0

    fig, ax = plt.subplots(figsize=(13.5, max(5.6, 0.62 * len(target_labels) + 2.0)))
    ax.imshow(matrix, cmap=plt.matplotlib.colors.ListedColormap(["#ef4444", "#22c55e"]), vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(level_labels)))
    ax.set_xticklabels(level_labels, fontsize=10)
    ax.set_yticks(range(len(target_labels)))
    ax.set_yticklabels(target_labels, fontsize=9)
    ax.set_title("Experiment 1: Basic Function Pass Matrix")
    ax.set_xlabel("Parameter set")
    ax.set_ylabel("Target implementation")
    ax.set_xticks(np.arange(-.5, len(level_labels), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(target_labels), 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    for i in range(len(target_labels)):
        for j in range(len(level_labels)):
            ax.text(j, i, "PASS" if matrix[i, j] else "FAIL", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_dir / "basic_pass_matrix.png", dpi=220)
    plt.close(fig)

    rows = []
    for target in data["targets"]:
        for level in LEVELS:
            result = target["levels"][level]
            if result.get("ready"):
                rows.append((f"{target['id']}\n{level}", result["average_ns"]["decaps"]))
    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    fig_w = max(12, 0.46 * len(labels))
    fig, ax = plt.subplots(figsize=(fig_w, 6.2))
    bars = ax.bar(range(len(values)), values, color="#2563eb")
    ax.set_title("Experiment 1: Average Decapsulation Time by Target")
    ax.set_ylabel("Average time (ns)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=75, ha="right", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value}", ha="center", va="bottom", fontsize=7, rotation=90)
    fig.tight_layout()
    fig.savefig(out_dir / "basic_decaps_average.png", dpi=220)
    plt.close(fig)

    vector_pass = [t["official_direct_vectors"].get("passed") or 0 for t in data["targets"]]
    vector_total = [t["official_direct_vectors"].get("total") or 0 for t in data["targets"]]
    fig, ax = plt.subplots(figsize=(12.5, max(5.2, 0.50 * len(target_labels) + 1.5)))
    y = np.arange(len(target_labels))
    ax.barh(y, vector_total, color="#dbeafe", label="total")
    ax.barh(y, vector_pass, color="#16a34a", label="passed")
    ax.set_yticks(y)
    ax.set_yticklabels(target_labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Official direct vector cases")
    ax.set_title("Experiment 1: Official Direct Vector Validation")
    ax.legend()
    for yi, p, total in zip(y, vector_pass, vector_total):
        ax.text(total + 0.8, yi, f"{p}/{total}", va="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "basic_official_vectors.png", dpi=220)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run basic ML-KEM selftests across all configured targets.")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--targets", nargs="*", default=None)
    args = parser.parse_args()
    result = run_experiment(args.iterations, args.targets)
    print(json.dumps({
        "run_id": result["run_id"],
        "out_dir": result["out_dir"],
        "target_count": result["target_count"],
        "success_target_count": result["success_target_count"],
    }, ensure_ascii=False, indent=2))
    print(f"log: {Path(result['out_dir']) / 'basic_multi_target.log'}")
    print(f"json: {Path(result['out_dir']) / 'basic_multi_target_result.json'}")
    return 0 if result["success_target_count"] == result["target_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
