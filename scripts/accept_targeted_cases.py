import json
import os
from software_service import detect, make_samples, validate_basic

cpu = min(os.sched_getaffinity(0))
sample = make_samples("mlkem_native_baseline", "512", 512)
out = []
for target_id in (x for x in os.environ.get("TARGET_CASES", "case_memory_index,case_variable_division").split(",") if x):
    basic = validate_basic(target_id, ["512", "768", "1024"], 100)
    result = detect(target_id, "512", sample["report_json"], int(os.environ.get("TARGET_PAIRS", "10000")), cpu, 3, 2)
    item = {
        "target_id": target_id,
        "basic_success": basic["success"],
        "conclusion": result["conclusion"],
        "formal_environment": result["formal_environment"],
        "same_input_control_passed": result["same_input_control_passed"],
        "differences_ns": [r["analysis"]["paired_mean_difference_ns"] for r in result["runs"]],
        "significant": [r["analysis"]["statistically_distinguishable"] for r in result["runs"]],
        "control_differences_ns": [r["analysis"]["paired_mean_difference_ns"] for r in result["controls"]],
        "control_significant": [r["analysis"]["statistically_distinguishable"] for r in result["controls"]],
        "report_json": result["report_json"],
    }
    out.append(item)
    print(json.dumps(item, ensure_ascii=False), flush=True)

print(json.dumps({"success": all(x["basic_success"] and x["conclusion"] == "重复观察到同方向差异" for x in out), "cases": out}, ensure_ascii=False, indent=2))
