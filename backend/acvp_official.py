from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACVP_SOURCE = ROOT / "data" / "acvp"
MLKEM_NATIVE = ROOT / "core" / "mlkem-native"
LOCAL_VERSION = "local-fips203"
ACVP_DEST = MLKEM_NATIVE / "test" / "acvp" / ".acvp-data" / LOCAL_VERSION / "files"
RESULTS = ROOT / "results" / "acvp"


def _copy_dataset(name: str) -> None:
    src = ACVP_SOURCE / name
    dst = ACVP_DEST / name
    dst.mkdir(parents=True, exist_ok=True)
    for filename in ["prompt.json", "expectedResults.json"]:
        source_file = src / filename
        if source_file.is_file():
            shutil.copy2(source_file, dst / filename)


def prepare_local_acvp_data() -> dict[str, Any]:
    if not ACVP_SOURCE.is_dir():
        raise FileNotFoundError(f"缺少 ACVP 向量目录：{ACVP_SOURCE}")
    ACVP_DEST.mkdir(parents=True, exist_ok=True)
    datasets = [
        "ML-KEM-keyGen-FIPS203",
        "ML-KEM-encapDecap-FIPS203",
        "ML-KEM-encapDecap-FIPS203-tr1",
    ]
    for name in datasets:
        _copy_dataset(name)
    return {
        "version": LOCAL_VERSION,
        "destination": str(ACVP_DEST),
        "datasets": datasets,
    }


def _run(command: list[str], timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(MLKEM_NATIVE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "output": proc.stdout,
        "output_tail": proc.stdout.strip().splitlines()[-80:],
    }


def run_official_acvp(timeout: int = 900, jobs: int = 1) -> dict[str, Any]:
    prepared = prepare_local_acvp_data()
    build = _run(["make", "acvp"], timeout=timeout)
    if build["returncode"] != 0:
        result = {
            "success": False,
            "prepared": prepared,
            "build": build,
            "run": None,
            "cases": 0,
            "message": "ACVP binaries failed to build",
        }
    else:
        run = _run(
            ["python3", "./test/acvp/acvp_client.py", "--version", LOCAL_VERSION, "--jobs", str(jobs)],
            timeout=timeout,
        )
        output = run["output"]
        match = re.search(r"ALL GOOD! \((\d+) cases in ([0-9.]+)s\)", output)
        dropped = re.findall(r"Dropped (\d+) ACVP test case", output)
        result = {
            "success": run["returncode"] == 0 and match is not None,
            "prepared": prepared,
            "build": build,
            "run": run,
            "cases": int(match.group(1)) if match else 0,
            "elapsed_reported_seconds": float(match.group(2)) if match else None,
            "dropped_cases": sum(int(x) for x in dropped),
            "message": match.group(0) if match else "ACVP run did not report ALL GOOD",
        }

    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"acvp_official_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_json"] = str(path)
    # Do not keep the full output in memory for callers that embed this in the
    # final proof report; the JSON file above still preserves it.
    if result.get("build"):
        result["build"].pop("output", None)
    if result.get("run"):
        result["run"].pop("output", None)
    return result

