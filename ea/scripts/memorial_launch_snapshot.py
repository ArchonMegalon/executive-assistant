#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
EA_DIR = SCRIPT_DIR.parent
REPO_ROOT = EA_DIR.parent


def _extract_json_status(stdout: str) -> tuple[str, dict[str, Any]]:
    try:
        payload = json.loads(str(stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return "", {}
    if not isinstance(payload, dict):
        return "", {}
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"pass", "warn", "fail"}:
        return "", {}
    detail: dict[str, Any] = {}
    if isinstance(payload.get("findings"), list):
        detail["finding_count"] = len(payload["findings"])
        fail_codes = [
            item.get("code")
            for item in payload["findings"]
            if isinstance(item, dict) and item.get("status") == "fail"
        ]
        warn_codes = [
            item.get("code")
            for item in payload["findings"]
            if isinstance(item, dict) and item.get("status") == "warn"
        ]
        if fail_codes:
            detail["fail_codes"] = fail_codes
        if warn_codes:
            detail["warn_codes"] = warn_codes
    if isinstance(payload.get("checks"), list):
        detail["check_count"] = len(payload["checks"])
        fail_codes = [
            item.get("code")
            for item in payload["checks"]
            if isinstance(item, dict) and item.get("status") == "fail"
        ]
        warn_codes = [
            item.get("code")
            for item in payload["checks"]
            if isinstance(item, dict) and item.get("status") == "warn"
        ]
        if fail_codes:
            detail["fail_codes"] = fail_codes
        if warn_codes:
            detail["warn_codes"] = warn_codes
    return status, detail


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    retries: int = 0,
) -> dict[str, Any]:
    attempts = max(1, retries + 1)
    last_result: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            result = {
                "command": command,
                "cwd": str(cwd) if cwd else None,
                "returncode": proc.returncode,
                "duration_ms": int((time.time() - started) * 1000),
                "stdout": proc.stdout[-5000:],
                "stderr": proc.stderr[-5000:],
                "attempt": attempt,
            }
            semantic_status, semantic_detail = _extract_json_status(proc.stdout)
            if semantic_status:
                result["semantic_status"] = semantic_status
                result["semantic_detail"] = semantic_detail
        except Exception as exc:
            result = {
                "command": command,
                "cwd": str(cwd) if cwd else None,
                "returncode": -1,
                "duration_ms": int((time.time() - started) * 1000),
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "attempt": attempt,
            }
        last_result = result
        stderr = str(result.get("stderr") or "")
        if int(result.get("returncode") or 0) == 0:
            return result
        if "TimeoutError" not in stderr and "timed out" not in stderr.lower():
            return result
        if attempt < attempts:
            time.sleep(1.0)
    return last_result or {
        "command": command,
        "cwd": str(cwd) if cwd else None,
        "returncode": -1,
        "duration_ms": 0,
        "stdout": "",
        "stderr": "unknown_error",
        "attempt": attempts,
    }


def snapshot_status(commands: list[dict[str, Any]]) -> str:
    if any(int(item.get("returncode") or 0) != 0 for item in commands):
        return "fail"
    semantic_statuses = {str(item.get("semantic_status") or "").lower() for item in commands}
    if "fail" in semantic_statuses:
        return "fail"
    if "warn" in semantic_statuses:
        return "warn"
    return "pass"


def env_status() -> dict[str, Any]:
    keys = [
        "EA_RUNTIME_MODE",
        "EA_ENABLE_PUBLIC_MEMORIALS",
        "EA_PUBLIC_MEMORIAL_RATE_BACKEND",
        "EA_PUBLIC_MEMORIAL_REDIS_URL",
        "EA_PUBLIC_MEMORIAL_DIR",
        "EA_PRIVATE_MEMORIAL_PROFILE_DIR",
        "FLIPLINK_API_BASE_URL",
        "FLIPLINK_CREATE_PATH",
        "FLIPLINK_CUSTOM_DOMAIN",
    ]
    redacted: dict[str, Any] = {}
    for key in keys:
        value = os.getenv(key)
        if value is None:
            redacted[key] = None
        elif "URL" in key and value:
            redacted[key] = value.split("@")[-1] if "@" in value else value
        else:
            redacted[key] = value
    redacted["FLIPLINK_API_KEY_configured"] = bool(os.getenv("FLIPLINK_API_KEY"))
    return redacted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a launch evidence snapshot for the memorial flagship demo.")
    parser.add_argument("slug")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--questions", default="")
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--output", default="")
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    ea_dir = repo_root / "ea"
    output = Path(args.output) if args.output else Path.cwd() / f"memorial_launch_snapshot_{args.slug}_{int(time.time())}.json"

    commands: list[tuple[list[str], Path, int, int]] = [
        (["git", "rev-parse", "HEAD"], repo_root, 60, 0),
        (["git", "status", "--short"], repo_root, 60, 0),
        ([sys.executable, "scripts/memorial_flagship_preflight.py", args.slug, "--json"], ea_dir, 180, 0),
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_memorial_archive_registry_public.py",
                "tests/test_memorial_flagship_preflight.py",
                "tests/test_memorial_demo_rehearsal_contracts.py",
            ],
            repo_root,
            180,
            0,
        ),
    ]
    if args.base_url and not args.skip_live:
        commands.append(
            (
                [sys.executable, "scripts/memorial_flagship_preflight.py", args.slug, "--base-url", args.base_url, "--json"],
                ea_dir,
                180,
                1,
            )
        )
        commands.append(
            (
                [
                    sys.executable,
                    "scripts/verify_memorial_video_call_avatar_ready.py",
                    "--slug",
                    args.slug,
                    "--base-url",
                    args.base_url,
                    "--json",
                ],
                ea_dir,
                120,
                0,
            )
        )
        rehearsal_command = [
            sys.executable,
            "scripts/memorial_demo_rehearsal.py",
            args.slug,
            "--base-url",
            args.base_url,
            "--skip-tts",
            "--json",
        ]
        if args.questions:
            rehearsal_command.extend(["--questions", args.questions])
        commands.append((rehearsal_command, ea_dir, 240, 0))

    command_results = [run_command(command, cwd=cwd, timeout=timeout, retries=retries) for command, cwd, timeout, retries in commands]
    snapshot = {
        "slug": args.slug,
        "base_url": args.base_url,
        "status": snapshot_status(command_results),
        "created_at_epoch": int(time.time()),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "environment": env_status(),
        "commands": command_results,
    }
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0 if snapshot["status"] in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
