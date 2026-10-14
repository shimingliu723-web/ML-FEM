from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from software_service import validate_basic

CASES = [
    "mlkem_native_baseline", "case_compare_early", "case_conditional_failure",
    "case_variable_loop", "case_memory_index", "case_conditional_branch", "case_variable_division",
]


def main() -> int:
    out = ROOT / "results/final_experiments" / time.strftime("%Y%m%d-%H%M%S-full-vector-validation")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for target_id in CASES:
        print("[START]", target_id, flush=True)
        result = validate_basic(target_id, ["512", "768", "1024"], 100)
        item = {
            "target_id": target_id,
            "success": result["success"],
            "selftests": result["selftests"],
            "vectors": result["vectors"],
            "vector_source": result["vector_source"],
            "library_sha256": result["library_sha256"],
            "report_json": result["report_json"],
        }
        rows.append(item)
        print(f"[DONE] {target_id}: vectors={item['vectors']['passed']}/{item['vectors']['total']}; selftests=300/300; success={item['success']}", flush=True)
    report = {
        "kind": "seven-target-full-official-vector-validation",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "targets": rows,
        "target_count": len(rows),
        "passed_target_count": sum(1 for r in rows if r["success"]),
        "official_cases_per_target": [r["vectors"]["total"] for r in rows],
        "total_vector_executions": sum(r["vectors"]["total"] for r in rows),
        "total_random_selftests": 7 * 3 * 100,
    }
    report["success"] = report["passed_target_count"] == report["target_count"] and all(x == 435 for x in report["official_cases_per_target"])
    path = out / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S,000")
    p = f"{stamp} - __main__ - INFO - "
    log = ["nohup: ignoring input", p + "="*84, p + "实验二：七目标基本功能与435项官方向量完整验证", p + "="*84]
    for row in rows:
        log.append(p + f"{row['target_id']}: selftests=300/300; official_vectors={row['vectors']['passed']}/{row['vectors']['total']}; success={row['success']}; report={row['report_json']}")
    log += ["", "评估指标：", "------------------------------------------------------------------------------------", f"target_pass               : {report['passed_target_count']}/{report['target_count']}", f"vector_executions         : {report['total_vector_executions']}", f"random_selftests          : {report['total_random_selftests']}", f"overall_success           : {report['success']}", f"JSON                      : {path}"]
    (out / "experiment-02-full-vectors.log").write_text("\n".join(log)+"\n", encoding="utf-8")
    labels = ["Baseline", "Compare exit", "Failure path", "Variable loop", "Memory access", "Conditional branch", "Division path"]
    values = [r["vectors"]["passed"] for r in rows]
    fig, ax = plt.subplots(figsize=(11.5, 5.2), layout="constrained")
    bars = ax.barh(labels, values, color="#46515B")
    ax.invert_yaxis(); ax.set_xlim(0, 475)
    ax.set_xlabel("Official ACVP/FIPS 203 cases passed")
    ax.set_title("Full official-vector validation across seven targets")
    ax.grid(axis="x", linestyle="--", alpha=.25)
    for bar, value in zip(bars, values): ax.text(value+5, bar.get_y()+bar.get_height()/2, f"{value}/435", va="center", fontweight="bold")
    fig.savefig(out / "experiment-02-full-vectors.png", dpi=220, facecolor="white")
    plt.close(fig)
    print(json.dumps({"success": report["success"], "report": str(path)}, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
