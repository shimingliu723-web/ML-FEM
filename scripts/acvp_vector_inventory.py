from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACVP_ROOT = ROOT / "data" / "acvp"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_by_param(obj: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in obj.get("testGroups", []):
        key = str(group.get("parameterSet") or group.get("tgId") or "unknown")
        counts[key] = counts.get(key, 0) + len(group.get("tests", []))
    return counts


def _group_map(obj: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(group["tgId"]): group for group in obj.get("testGroups", [])}


def _hex_to_b64(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def inventory() -> dict[str, Any]:
    datasets = []
    for folder in sorted(p for p in ACVP_ROOT.iterdir() if p.is_dir()):
        dataset = {"name": folder.name, "files": []}
        for name in ["prompt.json", "expectedResults.json", "validation.json", "internalProjection.json"]:
            path = folder / name
            if not path.exists():
                continue
            obj = _load(path)
            groups = obj.get("testGroups", [])
            total = sum(len(group.get("tests", [])) for group in groups)
            dataset["files"].append(
                {
                    "file": str(path.relative_to(ROOT)),
                    "groups": len(groups),
                    "tests": total,
                    "by_parameter_set": _count_by_param(obj),
                    "bytes": path.stat().st_size,
                }
            )
        datasets.append(dataset)
    return {"source": "NIST ACVP Server gen-val/json-files", "datasets": datasets}


def export_decap_vectors(limit: int, level: str, output: Path, include_tr1: bool = True) -> dict[str, Any]:
    """Export ACVP decapsulation vectors into the platform JSON format.

    The platform validator accepts Base64 fields named level, ct, sk and ss.
    ACVP stores the same materials as hex fields c, dk and k split between
    prompt.json and expectedResults.json, so this function joins them by
    tgId/tcId and writes a compact JSON array.
    """

    rows = []
    dataset_names = ["ML-KEM-encapDecap-FIPS203"]
    if include_tr1:
        dataset_names.append("ML-KEM-encapDecap-FIPS203-tr1")

    for dataset_name in dataset_names:
        prompt = _load(ACVP_ROOT / dataset_name / "prompt.json")
        expected = _load(ACVP_ROOT / dataset_name / "expectedResults.json")
        expected_groups = _group_map(expected)

        for group in prompt.get("testGroups", []):
            if group.get("function") != "decapsulation":
                continue
            if level != "all" and str(group.get("parameterSet")) != level:
                continue
            if not group.get("tests") or "dk" not in group["tests"][0]:
                continue
            tg_id = int(group["tgId"])
            exp_by_tc = {int(test["tcId"]): test for test in expected_groups[tg_id].get("tests", [])}
            for test in group.get("tests", []):
                tc_id = int(test["tcId"])
                exp = exp_by_tc[tc_id]
                rows.append(
                    {
                        "source": f"NIST ACVP {dataset_name}",
                        "tgId": tg_id,
                        "tcId": tc_id,
                        "level": str(group.get("parameterSet")),
                        "ct": _hex_to_b64(test["c"]),
                        "sk": _hex_to_b64(test["dk"]),
                        "ss": _hex_to_b64(exp["k"]),
                    }
                )
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
        if len(rows) >= limit:
            break

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output.relative_to(ROOT)), "level": level, "exported": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory and convert NIST ACVP ML-KEM vectors.")
    parser.add_argument("--export-decap", action="store_true", help="Export decapsulation vectors for platform validation.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--level", default="ML-KEM-512", choices=["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024", "all"])
    parser.add_argument("--out", default="data/acvp/platform_vectors/mlkem512_decap_100.json")
    args = parser.parse_args()

    result: dict[str, Any] = {"inventory": inventory()}
    if args.export_decap:
        result["export"] = export_decap_vectors(args.limit, args.level, ROOT / args.out)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
