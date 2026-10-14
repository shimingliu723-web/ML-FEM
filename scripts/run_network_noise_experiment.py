#!/usr/bin/env python3
"""Run the reproducible network latency/jitter experiment from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from software_service import network_noise_detect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--level", choices=("512", "768", "1024"), default="768")
    parser.add_argument("--samples", required=True)
    parser.add_argument("--pairs", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--category", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--profiles", default="none,low,medium,high")
    arguments = parser.parse_args()
    result = network_noise_detect(
        arguments.target,
        arguments.level,
        arguments.samples,
        arguments.pairs,
        arguments.cpu,
        arguments.repeats,
        arguments.category,
        [item.strip() for item in arguments.profiles.split(",") if item.strip()],
    )
    print(json.dumps({
        "success": result["success"],
        "conclusion": result.get("conclusion"),
        "report_json": result.get("report_json"),
        "summary_log": result.get("summary_log"),
        "chart_png": result.get("chart_png"),
    }, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
