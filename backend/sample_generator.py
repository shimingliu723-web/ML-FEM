from __future__ import annotations

import base64
import ctypes
import csv
import json
import time
import os
from pathlib import Path

from mlkem_service import PARAMETERS, MLKEM
from target_manager import get_target

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "samples"
RESULTS.mkdir(parents=True, exist_ok=True)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def generate_samples(target_id: str, level: str, count: int = 32) -> dict:
    if level not in PARAMETERS:
        raise ValueError("参数集必须为512、768或1024")
    if not 1 <= count <= 4096:
        raise ValueError("样本数量必须在1到4096之间")
    target = get_target(target_id)
    library = target.library_for(level)
    if not library.is_file():
        raise RuntimeError(f"目标库不存在：{library}")
    engine = MLKEM(level, library_path=library)
    params = PARAMETERS[level]
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns())
    out_dir = RESULTS / f"{run_id}-{target_id}-{level}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    csv_path = out_dir / "samples.csv"
    rows = []
    for index in range(count):
        kp = engine.keygen(record=False)
        enc = engine.encaps(kp["public_key"], record=False)
        normal_ct = base64.b64decode(enc["ciphertext"])
        mid_changed = bytearray(normal_ct)
        mid_changed[len(mid_changed) // 2] ^= 1
        first_changed = bytearray(normal_ct)
        first_changed[0] ^= 1
        last_changed = bytearray(normal_ct)
        last_changed[-1] ^= 1
        rows.append({
            "index": index,
            "public_key_b64": kp["public_key"],
            "secret_key_b64": kp["secret_key"],
            "normal_b64": enc["ciphertext"],
            "changed_mid_b64": _b64(bytes(mid_changed)),
            "changed_first_b64": _b64(bytes(first_changed)),
            "changed_last_b64": _b64(bytes(last_changed)),
            "shared_secret_b64": enc["shared_secret"],
        })
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        os.chmod(csv_path, 0o600)
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "target_id": target_id,
        "target_name": target.name,
        "level": f"ML-KEM-{level}",
        "count": count,
        "ciphertext_bytes": params.ciphertext,
        "sample_classes": ["normal", "changed_mid", "changed_first", "changed_last"],
        "rule": "每组样本由同一次封装结果生成，三类 changed 样本均保持长度不变，仅翻转固定位置1位。",
        "randomness": "实现使用操作系统随机源；不声称可用种子重新生成同一密钥。精确复测使用此受限权限样本文件。",
        "data_policy": "样本文件包含专用实验材料，权限0600；不包含在普通日志或报告导出中。",
        "csv": str(csv_path),
    }
    report_path = out_dir / "samples.json"
    report_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata["report_json"] = str(report_path)
    return metadata
