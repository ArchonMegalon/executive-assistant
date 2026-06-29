#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ENV = "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE"
TARGET_ENV = "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_RUNTIME_FILE"
DEFAULT_SOURCE = Path("config/whatsapp_audiobook_callback_secret")
DEFAULT_TARGET = Path(".runtime/secrets/whatsapp_audiobook_callback_secret")
RUNTIME_UID = 10001
RUNTIME_GID = 10001


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _resolve(root: Path, raw: str | Path) -> Path:
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _mode(path: Path) -> str:
    return oct(path.stat().st_mode & 0o777)


def _chmod_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _write_projection(target: Path, payload: str, *, uid: int, gid: int) -> dict[str, Any]:
    _chmod_private_dir(target.parent)
    tmp = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    chown_applied = False
    try:
        os.chown(tmp, uid, gid)
        chown_applied = True
    except PermissionError:
        chown_applied = False
    except OSError:
        chown_applied = False
    tmp.chmod(0o400 if chown_applied else 0o444)
    os.replace(tmp, target)
    return {
        "chown_applied": chown_applied,
        "target_gid": target.stat().st_gid,
        "target_mode": _mode(target),
        "target_uid": target.stat().st_uid,
    }


def materialize_projection(
    *,
    root: Path = ROOT,
    env_file: Path | None = None,
    source: Path | None = None,
    target: Path | None = None,
    uid: int = RUNTIME_UID,
    gid: int = RUNTIME_GID,
) -> dict[str, Any]:
    root = root.resolve()
    values = _parse_env_file(env_file or (root / ".env"))
    source_raw = str(source or os.getenv(SOURCE_ENV) or values.get(SOURCE_ENV) or DEFAULT_SOURCE).strip()
    target_raw = str(target or os.getenv(TARGET_ENV) or values.get(TARGET_ENV) or DEFAULT_TARGET).strip()
    source_path = _resolve(root, source_raw)
    target_path = _resolve(root, target_raw)
    if source_path == target_path:
        raise ValueError("source_and_target_must_differ")

    status = "ready"
    reason = ""
    payload = ""
    if source_path.exists():
        payload = source_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not payload:
        status = "skipped"
        reason = "source_secret_missing_or_empty"

    write_result = _write_projection(target_path, f"{payload}\n" if payload else "", uid=uid, gid=gid)
    return {
        "status": status,
        "reason": reason,
        "source_env": SOURCE_ENV,
        "source_path": str(source_path),
        "target_env": TARGET_ENV,
        "target_path": str(target_path),
        "target_parent_mode": _mode(target_path.parent),
        "secret_present": bool(payload),
        **write_result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize a container-readable WhatsApp callback secret projection.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--uid", type=int, default=RUNTIME_UID)
    parser.add_argument("--gid", type=int, default=RUNTIME_GID)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize_projection(
        env_file=args.env_file,
        source=args.source,
        target=args.target,
        uid=args.uid,
        gid=args.gid,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
