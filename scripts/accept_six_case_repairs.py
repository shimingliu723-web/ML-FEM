import json
import os
import time
from pathlib import Path

from software_service import ROOT, make_samples, repair

default_cases = [
    "case_compare_early",
    "case_conditional_failure",
    "case_variable_loop",
    "case_memory_index",
    "case_conditional_branch",
    "case_variable_division",
]
cases = [x for x in os.environ.get("REPAIR_CASES", ",".join(default_cases)).split(",") if x]
cpu = min(os.sched_getaffinity(0))
sample = make_samples("mlkem_native_baseline", "512", 512)
summary = {
    "kind": "six-case-repair-closure",
    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "pairs_per_round": int(os.environ.get("REPAIR_PAIRS", "10000")),
    "repeats": 3,
    "cpu": cpu,
    "sample_report": sample["report_json"],
    "cases": [],
}
for target_id in cases:
    print(f"[START] {target_id}", flush=True)
    result = repair(target_id, "512", sample["report_json"], summary["pairs_per_round"], cpu, 3, 2)
    item = {
        "target_id": target_id,
        "success": result.get("success"),
        "repaired_id": result.get("repaired_id"),
        "repair_types": result.get("patch", {}).get("repair_types", []),
        "effect_confirmed": result.get("effect_confirmed"),
        "before_conclusion": result.get("before", {}).get("conclusion"),
        "after_conclusion": result.get("after", {}).get("conclusion"),
        "before_formal": result.get("before", {}).get("formal_environment"),
        "after_formal": result.get("after", {}).get("formal_environment"),
        "before_abs_diff_ns": result.get("mean_abs_diff_before_ns"),
        "after_abs_diff_ns": result.get("mean_abs_diff_after_ns"),
        "report_json": result.get("report_json"),
    }
    summary["cases"].append(item)
    print(json.dumps(item, ensure_ascii=False), flush=True)

summary["success"] = all(x["success"] and x["effect_confirmed"] for x in summary["cases"])
output = ROOT / "results" / "acceptance" / (time.strftime("%Y%m%d-%H%M%S") + "-six-case-repair-closure.json")
output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[REPORT] {output}", flush=True)
print(f"[SUCCESS] {summary['success']}", flush=True)
