#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
FLEET_ROOT = Path(str(os.environ.get("FLEET_ROOT") or "/docker/fleet"))
REPO_SOURCE = ROOT / "scripts" / "codexea"
FLEET_SHIM = FLEET_ROOT / "scripts" / "codex-shims" / "codexea"


def _default_assignment_value(script_text: str, variable_name: str) -> str:
    patterns = (
        re.compile(rf'{re.escape(variable_name)}="\$\{{{re.escape(variable_name)}:-([^}}]+)\}}"'),
        re.compile(rf'local\s+\w+="\$\{{{re.escape(variable_name)}:-([^}}]+)\}}"'),
        re.compile(rf'{re.escape(variable_name)}="([^"]+)"'),
    )
    for pattern in patterns:
        match = pattern.search(script_text)
        if match is not None:
            return match.group(1)
    raise AssertionError(f"Missing default assignment for {variable_name}")


def verify() -> dict[str, object]:
    issues: list[str] = []
    details: dict[str, object] = {
        "repo_source": REPO_SOURCE.relative_to(ROOT).as_posix(),
        "fleet_shim": str(FLEET_SHIM),
    }

    if not REPO_SOURCE.is_file():
        issues.append("repo_codexea_source_missing")
    if not FLEET_SHIM.is_file():
        issues.append("fleet_codexea_shim_missing")
    if issues:
        return {
            "contract_name": "ea.codexea_fleet_shim_parity.v1",
            "status": "fail",
            "issues": issues,
            "details": details,
        }

    repo_source = REPO_SOURCE.read_text(encoding="utf-8")
    fleet_shim = FLEET_SHIM.read_text(encoding="utf-8")

    shared_defaults = {
        "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS": {
            "repo": _default_assignment_value(repo_source, "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS"),
            "fleet": _default_assignment_value(fleet_shim, "CODEXEA_STARTUP_STATUS_CACHE_TTL_SECONDS"),
        },
        "CODEXEA_STATUS_CONNECT_TIMEOUT_SECONDS": {
            "repo": _default_assignment_value(repo_source, "CODEXEA_STATUS_CONNECT_TIMEOUT_SECONDS"),
            "fleet": _default_assignment_value(fleet_shim, "CODEXEA_STATUS_CONNECT_TIMEOUT_SECONDS"),
        },
        "CODEXEA_STATUS_MAX_TIME_SECONDS": {
            "repo": _default_assignment_value(repo_source, "CODEXEA_STATUS_MAX_TIME_SECONDS"),
            "fleet": _default_assignment_value(fleet_shim, "CODEXEA_STATUS_MAX_TIME_SECONDS"),
        },
    }
    details["shared_defaults"] = shared_defaults
    for variable_name, values in shared_defaults.items():
        if values["repo"] != values["fleet"]:
            issues.append(f"{variable_name.lower()}_drift")

    startup_niceness = {
        "repo": _default_assignment_value(repo_source, "CODEXEA_NICE"),
        "fleet": _default_assignment_value(fleet_shim, "CODEXEA_PROCESS_NICE"),
    }
    details["startup_niceness_default"] = startup_niceness
    if startup_niceness["repo"] != startup_niceness["fleet"]:
        issues.append("startup_niceness_default_drift")

    startup_probe_path = {
        "repo_uses_refresh": "show_status --startup --refresh || true" in repo_source,
        "fleet_uses_refresh": "show_status --startup --refresh || true" in fleet_shim,
        "repo_uses_cached_default": "show_status --startup || true" in repo_source,
        "fleet_uses_cached_default": "show_status --startup || true" in fleet_shim,
    }
    details["startup_probe_path"] = startup_probe_path
    if startup_probe_path["repo_uses_refresh"] != startup_probe_path["fleet_uses_refresh"]:
        issues.append("startup_probe_refresh_path_drift")
    if startup_probe_path["repo_uses_cached_default"] != startup_probe_path["fleet_uses_cached_default"]:
        issues.append("startup_probe_cached_path_drift")

    return {
        "contract_name": "ea.codexea_fleet_shim_parity.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "details": details,
    }


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--help", "-h"}:
        print(
            "\n".join(
                [
                    "Usage:",
                    "  python3 scripts/verify_codexea_fleet_shim_parity.py",
                    "",
                    "Verifies that the live Fleet CodexEA shim keeps critical",
                    "launcher defaults aligned with the repo CodexEA source.",
                    "",
                    "Checks:",
                    "  - startup status cache ttl default",
                    "  - status connect/max-time defaults",
                    "  - startup niceness default",
                    "  - startup probe cache-vs-refresh path",
                ]
            )
        )
        return 0
    if len(sys.argv) > 1:
        print(f"Unknown arguments: {' '.join(sys.argv[1:])}", file=sys.stderr)
        return 2
    result = verify()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
