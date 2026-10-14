"""One-target real measurement smoke test for the adaptive detector."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from software_service import adaptive_detect, make_samples


cpu = min(os.sched_getaffinity(0))
samples = make_samples("case_compare_early", "768", 128)
result = adaptive_detect("case_compare_early", "768", samples["report_json"], cpu, 2)
print(json.dumps({
    "success": result["success"],
    "conclusion": result["conclusion"],
    "formal": result["decision"]["formal"],
    "stages": len(result["stages"]),
    "adaptive_pairs": result["resources"]["adaptive_pairs"],
    "saving_percent": result["resources"]["pair_saving_percent"],
    "report": result["report_json"],
    "chart": result["chart_png"],
}, ensure_ascii=False, indent=2))
