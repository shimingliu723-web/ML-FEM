from __future__ import annotations

import glob
import hashlib
import json
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    packs = [Path(p) for p in glob.glob(str(ROOT / "results/final_experiments/*-final-evidence-pack"))]
    pack = max(packs, key=lambda p: p.stat().st_mtime)
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = []
    for entry in manifest["files"]:
        path = pack / entry["file"]
        actual = digest(path) if path.is_file() else None
        checks.append({
            "file": entry["file"], "exists": path.is_file(),
            "expected_sha256": entry["sha256"], "actual_sha256": actual,
            "hash_match": actual == entry["sha256"],
        })
    json_checks = []
    for path in sorted(pack.glob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            json_checks.append({"file": path.name, "parse": True, "kind": data.get("kind") if isinstance(data, dict) else None})
        except Exception as exc:
            json_checks.append({"file": path.name, "parse": False, "error": str(exc)})
    image_checks = []
    for path in sorted(pack.glob("*.png")):
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                size = image.size
            image_checks.append({"file": path.name, "valid": True, "width": size[0], "height": size[1], "large_enough": size[0] >= 900 and size[1] >= 500})
        except Exception as exc:
            image_checks.append({"file": path.name, "valid": False, "error": str(exc), "large_enough": False})
    log_checks = []
    for path in sorted(pack.glob("*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        log_checks.append({"file": path.name, "bytes": path.stat().st_size, "nonempty": bool(text.strip()), "has_summary": "评估指标" in text or "overall_success" in text})
    report = {
        "kind": "final-evidence-reproducibility-check",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pack": str(pack),
        "manifest_entries_checked": len(checks),
        "manifest_hashes_passed": sum(1 for x in checks if x["hash_match"]),
        "json_files_checked": len(json_checks),
        "json_files_passed": sum(1 for x in json_checks if x["parse"]),
        "png_files_checked": len(image_checks),
        "png_files_passed": sum(1 for x in image_checks if x["valid"] and x["large_enough"]),
        "log_files_checked": len(log_checks),
        "log_files_passed": sum(1 for x in log_checks if x["nonempty"]),
        "file_checks": checks,
        "json_checks": json_checks,
        "image_checks": image_checks,
        "log_checks": log_checks,
    }
    report["success"] = (
        report["manifest_hashes_passed"] == report["manifest_entries_checked"]
        and report["json_files_passed"] == report["json_files_checked"]
        and report["png_files_passed"] == report["png_files_checked"]
        and report["log_files_passed"] == report["log_files_checked"]
    )
    report_path = pack / "experiment-12-reproducibility.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "nohup: ignoring input", "="*84, "实验十二：最终证据包完整性与可复现性检查", "="*84,
        f"manifest_hashes           : {report['manifest_hashes_passed']}/{report['manifest_entries_checked']}",
        f"JSON_parse                : {report['json_files_passed']}/{report['json_files_checked']}",
        f"PNG_validation            : {report['png_files_passed']}/{report['png_files_checked']}",
        f"log_nonempty              : {report['log_files_passed']}/{report['log_files_checked']}",
        f"overall_success           : {report['success']}",
        f"JSON                      : {report_path}",
    ]
    log_path = pack / "experiment-12-reproducibility.log"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for path in (report_path, log_path):
        manifest["files"].append({"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)})
    manifest["verified_at"] = report["created_at"]
    manifest["verification_success"] = report["success"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": report["success"], "pack": str(pack), "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
