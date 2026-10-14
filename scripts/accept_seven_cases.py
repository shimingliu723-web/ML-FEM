from __future__ import annotations

import json
import os
import time
from pathlib import Path

from binary_audit import binary_locate
from code_audit import locate_code
from repair_delivery import repair_plan
from software_service import ROOT, detect, make_samples, validate_basic

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
    cpu = min(os.sched_getaffinity(0))
    pairs = int(os.environ.get("CASE_ACCEPT_PAIRS", "3000"))
    repeats = int(os.environ.get("CASE_ACCEPT_REPEATS", "3"))
    sample = make_samples("mlkem_native_baseline", "512", 512)
    report = {
        "kind": "seven-case-acceptance",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cpu": cpu,
        "pairs_per_round": pairs,
        "repeats": repeats,
        "sample_report": sample["report_json"],
        "cases": [],
    }
    for target_id in CASES:
        print(f"[START] {target_id}", flush=True)
        basic = validate_basic(target_id, ["512", "768", "1024"], 100)
        source = locate_code(target_id)
        binary = binary_locate(target_id, "512")
        plans = [p["kind"] for p in repair_plan(target_id)]
        timing = detect(target_id, "512", sample["report_json"], pairs, cpu, repeats, 2)
        item = {
            "target_id": target_id,
            "basic_success": basic["success"],
            "source_evidence": bool(source.get("mechanism_evidence") and source["mechanism_evidence"]["found"]),
            "mechanism": source.get("mechanism"),
            "binary_counts": binary["counts"],
            "repair_rules": plans,
            "timing_report": timing["report_json"],
            "timing_conclusion": timing["conclusion"],
            "formal_environment": timing["formal_environment"],
        }
        repaired = ROOT / "targets" / (target_id + "_repaired")
        if repaired.is_dir():
            repaired_timing = detect(target_id + "_repaired", "512", sample["report_json"], pairs, cpu, repeats, 2)
            item.update({
                "repaired_basic_success": validate_basic(target_id + "_repaired", ["512", "768", "1024"], 100)["success"],
                "repaired_timing_report": repaired_timing["report_json"],
                "repaired_timing_conclusion": repaired_timing["conclusion"],
                "repaired_formal_environment": repaired_timing["formal_environment"],
            })
        report["cases"].append(item)
        print(f"[DONE] {target_id}: basic={item['basic_success']} timing={item['timing_conclusion']}", flush=True)
    report["success"] = all(c["basic_success"] and c["source_evidence"] for c in report["cases"])
    out = ROOT / "results" / "acceptance" / time.strftime("%Y%m%d-%H%M%S-seven-cases.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[REPORT] {out}", flush=True)
    print(f"[SUCCESS] {report['success']}", flush=True)


if __name__ == "__main__":
    main()
