from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from mlkem_service import MLKEM, PARAMETERS
from target_manager import get_target


def _decode_b64(value: str, label: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError(f"{label} 不是有效 Base64") from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _items_from_text(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        raise ValueError("请输入 JSON 数组、单个 JSON 对象或 JSON Lines")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        raise ValueError("JSON 顶层必须是对象或数组")
    except json.JSONDecodeError:
        items = []
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_no} 行不是合法 JSON") from exc
            if not isinstance(item, dict):
                raise ValueError(f"第 {line_no} 行必须是 JSON 对象")
            items.append(item)
        if not items:
            raise ValueError("未解析到任何向量")
        return items


def validate_vectors(text: str, default_level: str = "768", target_id: str = "mlkem_native_baseline") -> dict:
    items = _items_from_text(text)
    if len(items) > 200:
        raise ValueError("单次最多验证 200 条向量")
    target = get_target(target_id)
    results = []
    passed = 0
    failed = 0
    for index, item in enumerate(items):
        level = str(item.get("level", default_level)).replace("ML-KEM-", "")
        if level not in PARAMETERS:
            raise ValueError(f"第 {index + 1} 条参数集不支持：{level}")
        library = target.library_for(level)
        if not library.is_file():
            raise RuntimeError(f"目标库不存在：{library}")
        params = PARAMETERS[level]
        ct_text = str(item.get("ciphertext") or item.get("ct") or "")
        sk_text = str(item.get("secret_key") or item.get("sk") or "")
        ss_text = item.get("shared_secret") or item.get("ss")
        if not ct_text or not sk_text:
            raise ValueError(f"第 {index + 1} 条必须包含 ciphertext/ct 和 secret_key/sk")
        ct = _decode_b64(ct_text, f"第 {index + 1} 条 ciphertext")
        sk = _decode_b64(sk_text, f"第 {index + 1} 条 secret_key")
        length_ok = len(ct) == params.ciphertext and len(sk) == params.secret_key
        expected = _decode_b64(str(ss_text), f"第 {index + 1} 条 shared_secret") if ss_text else None
        engine = MLKEM(level, library_path=library)
        row = {
            "index": index + 1,
            "level": f"ML-KEM-{level}",
            "ciphertext_bytes": len(ct),
            "secret_key_bytes": len(sk),
            "expected_ciphertext_bytes": params.ciphertext,
            "expected_secret_key_bytes": params.secret_key,
            "length_ok": length_ok,
            "ciphertext_sha256_16": _digest(ct),
            "secret_key_sha256_16": _digest(sk),
        }
        if not length_ok:
            row.update({"passed": False, "reason": "输入长度不符合参数集要求"})
            failed += 1
            results.append(row)
            continue
        dec = engine.decaps(ct_text, sk_text, record=False)
        actual = _decode_b64(dec["shared_secret"], "actual shared_secret")
        row["actual_shared_secret_sha256_16"] = _digest(actual)
        if expected is None:
            row.update({"passed": True, "reason": "未提供期望共享结果，仅完成解封装和长度检查"})
            passed += 1
        else:
            ok = actual == expected
            row.update({
                "passed": ok,
                "reason": "共享结果一致" if ok else "共享结果不一致",
                "expected_shared_secret_sha256_16": _digest(expected),
            })
            passed += 1 if ok else 0
            failed += 0 if ok else 1
        results.append(row)
    return {
        "target_id": target_id,
        "target_name": target.name,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "success": failed == 0,
        "accepted_format": "JSON object、JSON array 或 JSON Lines；字段支持 level, ciphertext/ct, secret_key/sk, shared_secret/ss",
        "results": results,
    }
