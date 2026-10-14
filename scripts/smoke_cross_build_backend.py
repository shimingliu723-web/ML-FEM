"""Small real-build smoke test for the desktop cross-build backend."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from software_service import cross_build_validate

cpu = min(os.sched_getaffinity(0))
result = cross_build_validate("", 500, cpu, 1, ["gcc-o2"])
assert result["success"], result
assert len(result["rows"]) == 2
assert all(row["basic_success"] for row in result["rows"])
assert Path(result["chart_png"]).is_file()
assert Path(result["summary_log"]).is_file()
print(json.dumps({"success": True, "report_json": result["report_json"],
                  "rows": len(result["rows"]), "configuration": "gcc-o2"}, ensure_ascii=False))
