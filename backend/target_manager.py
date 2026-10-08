from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS_DIR = ROOT / "targets"


@dataclass(frozen=True)
class Target:
    id: str
    name: str
    role: str
    description: str
    levels: list[str]
    library_template: str
    build: list[str]
    selftest: list[str]

    def library_for(self, level: str) -> Path:
        if level not in self.levels:
            raise ValueError(f"目标 {self.id} 不支持 ML-KEM-{level}")
        return (ROOT / self.library_template.format(level=level)).resolve()


def _load_target(path: Path) -> Target:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Target(
        id=str(data["id"]),
        name=str(data["name"]),
        role=str(data.get("role", "baseline")),
        description=str(data.get("description", "")),
        levels=[str(x) for x in data.get("levels", ["512", "768", "1024"])],
        library_template=str(data["library_template"]),
        build=[str(x) for x in data.get("build", [])],
        selftest=[str(x) for x in data.get("selftest", [])],
    )


def list_targets() -> list[dict]:
    items = []
    for config in sorted(TARGETS_DIR.glob("*/target.json")):
        target = _load_target(config)
        libs = {level: target.library_for(level).is_file() for level in target.levels}
        items.append({
            "id": target.id,
            "name": target.name,
            "role": target.role,
            "description": target.description,
            "levels": target.levels,
            "libraries": libs,
            "config": str(config),
        })
    return items


def get_target(target_id: str) -> Target:
    config = TARGETS_DIR / target_id / "target.json"
    if not config.is_file():
        raise ValueError(f"未知目标实现：{target_id}")
    return _load_target(config)


def run_target_command(target_id: str, command_name: str, timeout: int = 180) -> dict:
    target = get_target(target_id)
    command = target.build if command_name == "build" else target.selftest
    if not command:
        return {"success": True, "skipped": True, "message": f"{target_id} 未配置 {command_name} 命令"}
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "success": proc.returncode == 0,
        "target": target_id,
        "command_name": command_name,
        "command": command,
        "returncode": proc.returncode,
        "output_tail": proc.stdout.strip().splitlines()[-30:],
    }



def _safe_id(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", value):
        raise ValueError("目标ID只能包含字母、数字、下划线和短横线，长度3到64")
    return value


def register_target(data: dict) -> dict:
    target_id = _safe_id(str(data.get("id", "")))
    name = str(data.get("name") or target_id)
    role = str(data.get("role") or "custom")
    description = str(data.get("description") or "用户注册的本地 ML-KEM 实现")
    levels = [str(x) for x in data.get("levels", ["512", "768", "1024"])]
    for level in levels:
        if level not in {"512", "768", "1024"}:
            raise ValueError(f"不支持的参数集：{level}")
    library_template = str(data.get("library_template") or "")
    if not library_template:
        raise ValueError("必须提供 library_template，例如 /path/libmlkem{level}.so")
    build_command = str(data.get("build_command") or "").strip()
    selftest_command = str(data.get("selftest_command") or "").strip()
    config = {
        "id": target_id,
        "name": name,
        "role": role,
        "description": description,
        "levels": levels,
        "library_template": library_template,
        "build": shlex.split(build_command) if build_command else [],
        "selftest": shlex.split(selftest_command) if selftest_command else [],
    }
    directory = TARGETS_DIR / target_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "target.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    target = _load_target(path)
    libs = {level: target.library_for(level).is_file() for level in target.levels}
    return {"success": True, "target": target_id, "config": str(path), "libraries": libs}
