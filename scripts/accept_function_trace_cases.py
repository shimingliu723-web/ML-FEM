from __future__ import annotations

import glob
import json
import os
import statistics
import time
from pathlib import Path

from function_trace import run_trace
from software_service import ROOT

CASES = [
    "mlkem_native_baseline",
    "case_compare_early",
    "case_conditional_failure",
    "case_variable_loop",
    "case_memory_index",
    "case_conditional_branch",
    "case_variable_division",
]


def main() -> None:
    pairs = int(os.environ.get("TRACE_ACCEPT_PAIRS", "10000"))
    repeats = int(os.environ.get("TRACE_ACCEPT_REPEATS", "3"))
    cpu = min(os.sched_getaffinity(0))
    acceptance = sorted(glob.glob(str(ROOT / "results/acceptance/*seven-cases.json")))[-1]
    samples = json.loads(Path(acceptance).read_text())["sample_report"]
    result = {"kind": "seven-case-function-trace-acceptance", "pairs": pairs,
              "repeats": repeats, "cpu": cpu, "sample_report": samples, "cases": []}
    for target_id in CASES:
        print("[START]", target_id, flush=True)
        report = run_trace(target_id, "512", samples, pairs, cpu, repeats, 2)
        mechanism = report["stage_names"][-1]
        mechanism_rounds = [r["stages"][-1] for r in report["rounds"] if not r["control"]]
        overhead = [x["overhead_percent"] for r in report["rounds"] if not r["control"] for x in r["overhead"]]
        item = {
            "target_id": target_id,
            "success": report["success"],
            "mechanism_instrumented": report["mechanism_instrumented"],
            "mechanism_stage": mechanism,
            "mechanism_mean_differences_ns": [r["statistics"]["paired"]["paired_mean_difference_ns"] for r in mechanism_rounds],
            "mechanism_significant": [r["statistics"]["verdict"]["statistically_significant"] for r in mechanism_rounds],
            "candidates": [x["stage"] for x in report["auxiliary_analysis"] if x["candidate"]],
            "mean_instrumentation_overhead_percent": statistics.fmean(overhead),
            "report_json": report["report_json"],
            "chart_png": report["chart_png"],
        }
        result["cases"].append(item)
        print("[DONE]", target_id, "stage=", mechanism, "diffs=", item["mechanism_mean_differences_ns"],
              "candidates=", item["candidates"], flush=True)
    result["success"] = all(x["success"] and x["mechanism_instrumented"] for x in result["cases"])
    result["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out = ROOT / "results/acceptance" / time.strftime("%Y%m%d-%H%M%S-function-trace-seven-cases.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("[REPORT]", out, flush=True)
    print("[SUCCESS]", result["success"], flush=True)


if __name__ == "__main__":
    main()
