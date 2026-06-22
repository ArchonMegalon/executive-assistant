#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = "/data/session"
DEFAULT_SESSION_REF = "default-wa-web"
DEFAULT_CONTAINER_NAME = "ea-whatsapp-web-session"


def _load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = _parse_env_value(raw_value)


def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                loaded = json.loads(value)
                if isinstance(loaded, str):
                    return loaded
            except Exception:
                return value[1:-1]
        return value[1:-1]
    return value


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_iso(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_json_payload(*, raw_json: str = "", source_file: str = "") -> object:
    raw = str(raw_json or "").strip()
    path_text = str(source_file or "").strip()
    if not raw and path_text:
        try:
            raw = Path(path_text).read_text(encoding="utf-8")
        except OSError:
            raw = ""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _iter_required_routes(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict) and isinstance(payload.get("routes"), list):
        payload = payload.get("routes")
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [dict(payload)]
    return []


def _normalized_route_key(value: object) -> str:
    raw = str(value or "").strip()
    if raw in {"default", "*"}:
        return "*"
    return raw


def _route_expectation_mismatch(route: dict[str, object], expected: dict[str, object]) -> dict[str, object]:
    mismatches: dict[str, object] = {}
    for key, expected_value in expected.items():
        if key in {"route_key", "key"}:
            continue
        actual_value = route.get(key)
        if actual_value != expected_value:
            mismatches[key] = {
                "actual": actual_value,
                "expected": expected_value,
            }
    return mismatches


def _container_route_state_payload(
    *,
    container_name: str,
    state_file: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any] | None:
    script = f"test -f {json.dumps(str(state_file))} && cat {json.dumps(str(state_file))}"
    try:
        completed = run(
            ["docker", "exec", container_name, "sh", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def default_state_file(*, data_dir: str, session_ref: str) -> Path:
    return Path(str(data_dir or DEFAULT_DATA_DIR).strip() or DEFAULT_DATA_DIR) / f"{session_ref}.heyy-ai-routes.json"


def check_route_persistence(
    *,
    state_file: Path,
    session_ref: str,
    min_route_count: int,
    min_private_route_count: int,
    require_default_route: bool,
    stale_seconds: int,
    required_routes: list[dict[str, object]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        state_file_present = state_file.is_file()
    except OSError:
        state_file_present = False
    if not state_file_present:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "route_state_file_missing",
            "state_file": str(state_file),
        }
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "route_state_file_unreadable",
            "state_file": str(state_file),
        }
    if not isinstance(payload, dict):
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "route_state_not_object",
        }
    persisted_session_ref = str(payload.get("session_ref") or "").strip()
    if session_ref and persisted_session_ref != session_ref:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "session_ref_mismatch",
            "session_ref": session_ref,
            "state_session_ref": persisted_session_ref,
        }
    routes = payload.get("routes") if isinstance(payload.get("routes"), dict) else {}
    route_count = len(routes)
    private_route_count = len([key for key in routes if str(key) != "*"])
    default_route_present = "*" in routes
    if route_count < min_route_count:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "min_route_count": min_route_count,
            "ok": False,
            "ready": False,
            "reason": "route_count_too_low",
            "route_count": route_count,
        }
    if require_default_route and not default_route_present:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "default_route_missing",
            "route_count": route_count,
        }
    if private_route_count < min_private_route_count:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "min_private_route_count": min_private_route_count,
            "ok": False,
            "private_route_count": private_route_count,
            "ready": False,
            "reason": "private_route_count_too_low",
            "route_count": route_count,
        }
    for required in required_routes or []:
        route_key = _normalized_route_key(required.get("route_key") or required.get("key"))
        if not route_key:
            continue
        route = routes.get(route_key)
        if not isinstance(route, dict):
            return {
                "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
                "ok": False,
                "ready": False,
                "reason": "required_route_missing",
                "required_route_key": "default" if route_key == "*" else route_key,
                "route_count": route_count,
            }
        mismatches = _route_expectation_mismatch(route, required)
        if mismatches:
            return {
                "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
                "mismatches": mismatches,
                "ok": False,
                "ready": False,
                "reason": "required_route_mismatch",
                "required_route_key": "default" if route_key == "*" else route_key,
                "route_count": route_count,
            }
    persisted_at = _parse_iso(payload.get("persisted_at"))
    if persisted_at is None:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "persisted_at_missing_or_invalid",
            "route_count": route_count,
        }
    age_seconds = max(0, int((checked_at - persisted_at).total_seconds()))
    if stale_seconds > 0 and age_seconds > stale_seconds:
        return {
            "age_seconds": age_seconds,
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "ok": False,
            "ready": False,
            "reason": "route_state_stale",
            "route_count": route_count,
            "stale_seconds": stale_seconds,
        }
    return {
        "age_seconds": age_seconds,
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "default_route_present": default_route_present,
        "ok": True,
        "persisted_at": persisted_at.isoformat().replace("+00:00", "Z"),
        "private_route_count": private_route_count,
        "ready": True,
        "reason": "ready",
        "required_route_count": len(required_routes or []),
        "route_count": route_count,
        "session_ref": persisted_session_ref,
        "stale_seconds": stale_seconds,
    }


def resolve_route_persistence(
    *,
    state_file: Path,
    session_ref: str,
    min_route_count: int,
    min_private_route_count: int,
    require_default_route: bool,
    stale_seconds: int,
    required_routes: list[dict[str, object]] | None = None,
    container_name: str = DEFAULT_CONTAINER_NAME,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = check_route_persistence(
        state_file=state_file,
        session_ref=session_ref,
        min_route_count=min_route_count,
        min_private_route_count=min_private_route_count,
        require_default_route=require_default_route,
        stale_seconds=stale_seconds,
        required_routes=required_routes,
        now=now,
    )
    if report.get("ready"):
        return report
    if str(report.get("reason") or "").strip() != "route_state_file_missing":
        return report
    container = str(container_name or "").strip()
    if not container or not str(state_file).startswith("/"):
        return report
    payload = _container_route_state_payload(container_name=container, state_file=state_file, run=run)
    if not isinstance(payload, dict):
        return report
    tmp_dir = Path(tempfile.gettempdir()) / "ea-whatsapp-web-route-persistence"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{session_ref or 'session'}.json"
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        resolved = check_route_persistence(
            state_file=tmp_path,
            session_ref=session_ref,
            min_route_count=min_route_count,
            min_private_route_count=min_private_route_count,
            require_default_route=require_default_route,
            stale_seconds=stale_seconds,
            required_routes=required_routes,
            now=now,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    resolved["state_file_checked_in_container"] = True
    resolved["state_file_container"] = container
    resolved["state_file"] = str(state_file)
    return resolved


def parse_args() -> argparse.Namespace:
    _load_env_file()
    session_ref = _env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", DEFAULT_SESSION_REF)
    data_dir = _env("WA_WEB_SESSION_DATA_DIR", DEFAULT_DATA_DIR)
    default_file = _env("WA_WEB_HEYY_AI_ROUTE_MAP_STATE_FILE") or str(default_state_file(data_dir=data_dir, session_ref=session_ref))
    parser = argparse.ArgumentParser(description="Check persisted WhatsApp Web Heyy AI route map state.")
    parser.add_argument("--state-file", default=default_file)
    parser.add_argument("--session-ref", default=session_ref)
    parser.add_argument("--min-route-count", type=int, default=_int_value(_env("EA_WHATSAPP_WEB_ROUTE_PERSIST_MIN_ROUTE_COUNT", "2"), 2))
    parser.add_argument(
        "--min-private-route-count",
        type=int,
        default=_int_value(_env("EA_WHATSAPP_WEB_ROUTE_PERSIST_MIN_PRIVATE_ROUTE_COUNT", "1"), 1),
    )
    parser.add_argument("--allow-missing-default-route", action="store_true")
    parser.add_argument("--required-route-json", default=_env("EA_WHATSAPP_WEB_ROUTE_PERSIST_REQUIRED_ROUTES_JSON"))
    parser.add_argument("--required-route-file", default=_env("EA_WHATSAPP_WEB_ROUTE_PERSIST_REQUIRED_ROUTES_FILE"))
    parser.add_argument("--stale-seconds", type=int, default=_int_value(_env("EA_WHATSAPP_WEB_ROUTE_PERSIST_STALE_SECONDS", "86400"), 86400))
    parser.add_argument("--container-name", default=_env("EA_WHATSAPP_WEB_SESSION_CONTAINER_NAME", DEFAULT_CONTAINER_NAME))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = resolve_route_persistence(
        state_file=Path(str(args.state_file)),
        session_ref=str(args.session_ref or "").strip(),
        min_route_count=max(0, int(args.min_route_count)),
        min_private_route_count=max(0, int(args.min_private_route_count)),
        require_default_route=not bool(args.allow_missing_default_route),
        required_routes=_iter_required_routes(_load_json_payload(raw_json=str(args.required_route_json or ""), source_file=str(args.required_route_file or ""))),
        stale_seconds=max(0, int(args.stale_seconds)),
        container_name=str(args.container_name or "").strip(),
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if bool(report.get("ready")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
