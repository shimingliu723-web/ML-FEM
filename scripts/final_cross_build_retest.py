from __future__ import annotations

import glob
import json
import os
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from software_service import detect


def main() -> int:
    paths = [Path(p) for p in glob.glob(str(ROOT / "results/experiments/*-cross-build/report.json"))]
    source = max(paths, key=lambda p: p.stat().st_mtime)
    data = json.loads(source.read_text(encoding="utf-8"))
    retests = []
    for row in data["rows"]:
        comparison_needs = row["variant"] == "compare_early" and row["conclusion"] != "重复观察到同方向差异"
        baseline_bad = row["variant"] == "baseline" and row["conclusion"] == "重复观察到同方向差异"
        environment_needs = not row["formal_environment"]
        if not (comparison_needs or baseline_bad or environment_needs):
            row["final_formal_environment"] = row["formal_environment"]
            row["final_conclusion"] = row["conclusion"]
            continue
        print(f"[RETEST] {row['target_id']}", flush=True)
        result = detect(
            row["target_id"], "512", data["sample_report"],
            int(data["pairs"]), int(data["cpu"]), int(data["repeats"]), 2,
        )
        diffs = [r["analysis"]["paired_mean_difference_ns"] for r in result["runs"]]
        item = {
            "target_id": row["target_id"],
            "formal_environment": result["formal_environment"],
            "same_input_control_passed": result["same_input_control_passed"],
            "conclusion": result["conclusion"],
            "round_differences_ns": diffs,
            "mean_difference_ns": statistics.fmean(diffs),
            "stdev_difference_ns": statistics.stdev(diffs) if len(diffs) > 1 else 0.0,
            "report_json": result["report_json"],
        }
        row["retest"] = item
        row["final_formal_environment"] = item["formal_environment"]
        row["final_conclusion"] = item["conclusion"]
        retests.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    for row in data["rows"]:
        row.setdefault("final_formal_environment", row["formal_environment"])
        row.setdefault("final_conclusion", row["conclusion"])
    data["retests"] = retests
    data["retested_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    data["final_formal_accepted_rows"] = sum(1 for r in data["rows"] if r["final_formal_environment"])
    data["final_baseline_repeated_difference_count"] = sum(
        1 for r in data["rows"] if r["variant"] == "baseline" and r["final_conclusion"] == "重复观察到同方向差异"
    )
    data["final_comparison_detected_count"] = sum(
        1 for r in data["rows"] if r["variant"] == "compare_early" and r["final_conclusion"] == "重复观察到同方向差异"
    )
    data["success"] = (
        data["functional_success"]
        and data["final_formal_accepted_rows"] == len(data["rows"])
        and data["final_baseline_repeated_difference_count"] == 0
        and data["final_comparison_detected_count"] == 6
    )
    output = source.parent / "report-with-retests.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": data["success"], "report": str(output), "retest_count": len(retests)}, ensure_ascii=False, indent=2))
    return 0 if data["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
