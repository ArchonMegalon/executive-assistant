#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable
from urllib.parse import urlparse
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]


def _default_base_url() -> str:
    host_port = str(os.environ.get("EA_HOST_PORT") or "").strip()
    if not host_port:
        env_path = ROOT / ".env"
        if env_path.is_file():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if str(key).strip() == "EA_HOST_PORT":
                    host_port = str(value).strip()
                    break
    host_port = host_port or "8090"
    return f"http://localhost:{host_port}"


def _request_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = str(os.environ.get("EA_API_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-EA-API-Token"] = token
    return headers


def _fetch_json(url: str) -> dict[str, Any]:
    req = request.Request(url, headers=_request_headers())
    try:
        with request.urlopen(req, timeout=10) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(f"fetch_failed:{url}:{exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"fetch_invalid_json:{url}:{exc}") from exc
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _looks_like_local_base_url(base_url: str) -> bool:
    host = str(urlparse(base_url).hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _fetch_container_health_live() -> dict[str, Any]:
    container_name = str(os.environ.get("EA_API_CONTAINER_NAME") or "ea-api").strip() or "ea-api"
    command = [
        "docker",
        "exec",
        container_name,
        "/bin/sh",
        "-lc",
        "curl -fsS http://127.0.0.1:8090/health/live",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        payload = json.loads(completed.stdout)
    except Exception as exc:
        raise RuntimeError(f"container_probe_failed:{container_name}:{exc}") from exc
    return dict(payload or {}) if isinstance(payload, dict) else {}


def verify_memorial_runtime_overlay(
    *,
    base_url: str | None = None,
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_json,
    require_mounted: bool = True,
) -> dict[str, Any]:
    resolved_base_url = (base_url or _default_base_url()).rstrip("/")
    health_url = f"{resolved_base_url}/health/live"
    issues: list[str] = []
    errors: dict[str, str] = {}
    try:
        payload = fetch_json(health_url)
    except Exception as exc:
        return {
            "contract_name": "ea.memorial_runtime_overlay.v1",
            "status": "fail",
            "issues": ["health_live_fetch_failed"],
            "errors": {"health_live": str(exc)},
            "base_url": resolved_base_url,
            "health_url": health_url,
            "require_mounted": require_mounted,
            "memorial_runtime": {},
            "next_action": "start_runtime_with_memorial_overlay",
        }

    source = "http"
    memorial_runtime = dict(payload.get("memorial_runtime") or {})
    if not memorial_runtime and _looks_like_local_base_url(resolved_base_url):
        try:
            container_payload = _fetch_container_health_live()
            container_runtime = dict(container_payload.get("memorial_runtime") or {})
            if container_runtime:
                payload = container_payload
                memorial_runtime = container_runtime
                source = "container_loopback_fallback"
        except Exception as exc:
            errors["container_loopback_probe"] = str(exc)

    if not memorial_runtime:
        issues.append("memorial_runtime_missing_from_health_live")
    state = str(memorial_runtime.get("state") or "").strip()
    configured_enabled = bool(memorial_runtime.get("configured_enabled"))
    route_mounted = bool(memorial_runtime.get("route_mounted"))
    next_action = str(memorial_runtime.get("next_action") or "").strip()
    healthcheck_slug = str(memorial_runtime.get("healthcheck_slug") or "").strip()

    if require_mounted:
        if not configured_enabled:
            issues.append("memorial_runtime_not_enabled")
        if not route_mounted:
            issues.append("memorial_route_not_mounted")
        if state != "mounted":
            issues.append(f"memorial_runtime_state_not_mounted:{state or 'missing'}")
        if not healthcheck_slug:
            issues.append("memorial_healthcheck_slug_missing")

    return {
        "contract_name": "ea.memorial_runtime_overlay.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "errors": errors,
        "base_url": resolved_base_url,
        "health_url": health_url,
        "source": source,
        "require_mounted": require_mounted,
        "memorial_runtime": {
            "state": state,
            "configured_enabled": configured_enabled,
            "route_mounted": route_mounted,
            "healthcheck_slug": healthcheck_slug,
            "route_path": str(memorial_runtime.get("route_path") or ""),
        },
        "public_surface_flags": dict(payload.get("public_surface_flags") or {}),
        "next_action": next_action,
    }


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_memorial_runtime_overlay.py [--base-url URL] [--pretty] [--no-require-mounted]\n\n"
            "Fail closed unless /health/live reports the memorial runtime overlay as mounted."
        )
        return 0
    parser = argparse.ArgumentParser(
        description="Verify that /health/live reports the memorial runtime overlay as mounted."
    )
    parser.add_argument("--base-url", default="")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--no-require-mounted", action="store_true")
    args = parser.parse_args()

    result = verify_memorial_runtime_overlay(
        base_url=str(args.base_url or "").strip() or None,
        require_mounted=not bool(args.no_require_mounted),
    )
    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
