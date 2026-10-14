from __future__ import annotations

import glob
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from software_service import detect


def main() -> int:
    paths = [Path(p) for p in glob.glob(str(ROOT / "results/experiments/*-cross-build/report-with-retests.json"))]
    source = max(paths, key=lambda p: p.stat().st_mtime)
    data = json.loads(source.read_text(encoding="utf-8"))
    target_id = "crossbuild_clang17_o3_compare_early"
    result = detect(target_id, "512", data["sample_report"], 20000, int(data["cpu"]), 5, 2)
    diffs = [r["analysis"]["paired_mean_difference_ns"] for r in result["runs"]]
    confirmation = {
        "target_id": target_id,
        "pairs_per_round": 20000,
        "repeats": 5,
        "formal_environment": result["formal_environment"],
        "same_input_control_passed": result["same_input_control_passed"],
        "conclusion": result["conclusion"],
        "round_differences_ns": diffs,
        "round_significant": [r["analysis"]["statistically_distinguishable"] for r in result["runs"]],
        "mean_difference_ns": statistics.fmean(diffs),
        "stdev_difference_ns": statistics.stdev(diffs),
        "report_json": result["report_json"],
    }
    for row in data["rows"]:
        if row["target_id"] == target_id:
            row["confirmation"] = confirmation
            row["final_formal_environment"] = confirmation["formal_environment"]
            row["final_conclusion"] = confirmation["conclusion"]
    data["confirmation"] = confirmation
    data["confirmed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    data["final_formal_accepted_rows"] = sum(1 for r in data["rows"] if r.get("final_formal_environment", r["formal_environment"]))
    data["final_baseline_repeated_difference_count"] = sum(
        1 for r in data["rows"] if r["variant"] == "baseline" and r.get("final_conclusion", r["conclusion"]) == "重复观察到同方向差异"
    )
    data["final_comparison_detected_count"] = sum(
        1 for r in data["rows"] if r["variant"] == "compare_early" and r.get("final_conclusion", r["conclusion"]) == "重复观察到同方向差异"
    )
    data["success"] = (
        data["functional_success"]
        and data["final_formal_accepted_rows"] == len(data["rows"])
        and data["final_baseline_repeated_difference_count"] == 0
        and data["final_comparison_detected_count"] == 6
    )
    output = source.parent / "report-final.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(confirmation, ensure_ascii=False, indent=2), flush=True)
    print(json.dumps({"success": data["success"], "report": str(output)}, ensure_ascii=False, indent=2), flush=True)
    return 0 if data["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
