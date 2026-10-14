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
    reports = [Path(p) for p in glob.glob(str(ROOT / "results/final_experiments/*-cross-parameter/report.json"))]
    source = max(reports, key=lambda p: p.stat().st_mtime)
    data = json.loads(source.read_text(encoding="utf-8"))
    pairs = int(data["pairs_per_round"])
    repeats = int(data["repeats"])
    cpu = int(data["cpu"])
    retests = []
    for row in data["rows"]:
        baseline_needs = row["target_id"] == "mlkem_native_baseline" and row["conclusion"] != "本次各轮未检出显著差异"
        environment_needs = not row["formal_environment"]
        if not (baseline_needs or environment_needs):
            row["final_formal_environment"] = row["formal_environment"]
            row["final_conclusion"] = row["conclusion"]
            continue
        print(f"[RETEST] {row['target_id']} ML-KEM-{row['level']}", flush=True)
        result = detect(
            row["target_id"], row["level"], data["sample_reports"][row["level"]],
            pairs, cpu, repeats, 2,
        )
        diffs = [r["analysis"]["paired_mean_difference_ns"] for r in result["runs"]]
        item = {
            "target_id": row["target_id"], "level": row["level"],
            "formal_environment": result["formal_environment"],
            "same_input_control_passed": result["same_input_control_passed"],
            "conclusion": result["conclusion"],
            "round_differences_ns": diffs,
            "mean_difference_ns": statistics.fmean(diffs),
            "report_json": result["report_json"],
        }
        retests.append(item)
        row["retest"] = item
        row["final_formal_environment"] = item["formal_environment"]
        row["final_conclusion"] = item["conclusion"]
        print(json.dumps(item, ensure_ascii=False), flush=True)

    for row in data["rows"]:
        row.setdefault("final_formal_environment", row["formal_environment"])
        row.setdefault("final_conclusion", row["conclusion"])
    data["retests"] = retests
    data["retested_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    data["final_formal_count"] = sum(1 for r in data["rows"] if r["final_formal_environment"])
    data["final_baseline_no_repeated_difference"] = sum(
        1 for r in data["rows"]
        if r["target_id"] == "mlkem_native_baseline" and r["final_conclusion"] != "重复观察到同方向差异"
    )
    data["final_controlled_detected"] = sum(
        1 for r in data["rows"]
        if r["target_id"] != "mlkem_native_baseline" and r["final_conclusion"] == "重复观察到同方向差异"
    )
    data["success"] = (
        data["functional_pass_count"] == len(data["rows"])
        and data["final_formal_count"] == len(data["rows"])
        and data["final_baseline_no_repeated_difference"] == 3
        and data["final_controlled_detected"] == 18
    )
    output = source.parent / "report-with-retests.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": data["success"], "report": str(output), "retest_count": len(retests)}, ensure_ascii=False, indent=2))
    return 0 if data["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
