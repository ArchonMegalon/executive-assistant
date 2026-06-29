#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_FILE = ROOT / "docker-compose.whatsapp-web-session.yml"
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_SESSION_REF = "default-wa-web"
DEFAULT_ACTION_STATE_FILE = "/data/whatsapp-actions/processed.json"
DEFAULT_QR_FRESH_SECONDS = 120
DEFAULT_ENV_VALUES = {
    "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED": "1",
    "EA_WHATSAPP_WEB_ACTION_STATE_FILE": DEFAULT_ACTION_STATE_FILE,
}
CALLBACK_SECRET_KEYS = (
    "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET",
    "EA_WHATSAPP_CALLBACK_SECRET",
    "EA_TELEGRAM_CALLBACK_SECRET",
)
SENSITIVE_ENV_KEYS = (*CALLBACK_SECRET_KEYS, "EA_WHATSAPP_WEB_SESSION_API_TOKEN")
SECRET_FILE_KEY = "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE"
HOST_SECRET_FILE_CANDIDATES = (
    ROOT / "config" / "whatsapp_audiobook_callback_secret",
    ROOT / "config" / "whatsapp_audiobook_callback_secret.local",
)
API_CONTAINER_SECRET_FILES = (
    "/config/whatsapp_audiobook_callback_secret",
    "/config/whatsapp_audiobook_callback_secret.local",
)
PROCESSOR_CONTAINER_SECRET_FILES = (
    "/app/config/whatsapp_audiobook_callback_secret",
    "/app/config/whatsapp_audiobook_callback_secret.local",
)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _parse_env_value(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env_file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _parse_env_value(value)
    return values


def _merged_env(args: argparse.Namespace) -> dict[str, str]:
    values = {**DEFAULT_ENV_VALUES, **_env_file_values(Path(str(args.env_file or DEFAULT_ENV_FILE)))}
    values.update({key: value for key, value in os.environ.items() if key.startswith("EA_WHATSAPP") or key.startswith("EA_TELEGRAM")})
    return values


def _bool_env(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_iso_timestamp(value: object) -> datetime | None:
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


def _request_json(
    *,
    method: str,
    url: str,
    token: str = "",
    auth_header_name: str = "Authorization",
    auth_header_prefix: str = "Bearer ",
    timeout: float = 15.0,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers[auth_header_name or "Authorization"] = f"{auth_header_prefix}{token}"
    request = urllib.request.Request(url, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout), 0.1)) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            payload.setdefault("ok", False)
            payload.setdefault("reason", f"http_{exc.code}")
            return payload
        return {"ok": False, "reason": f"http_{exc.code}"}
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}


def _session_api_headers(args: argparse.Namespace, values: dict[str, str]) -> dict[str, object]:
    return {
        "token": str(args.session_api_token or values.get("EA_WHATSAPP_WEB_SESSION_API_TOKEN") or "").strip(),
        "auth_header_name": str(
            args.auth_header_name or values.get("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME") or "Authorization"
        ),
        "auth_header_prefix": str(
            args.auth_header_prefix
            if args.auth_header_prefix is not None
            else values.get("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX") or "Bearer "
        ),
        "timeout": float(args.timeout_seconds),
    }


def _configured_session_ref(args: argparse.Namespace, values: dict[str, str]) -> str:
    return str(args.session_ref or values.get("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF") or DEFAULT_SESSION_REF).strip()


def _sidecar_health(
    args: argparse.Namespace,
    values: dict[str, str],
    request_json: Callable[..., dict[str, Any]],
) -> dict[str, object]:
    base_url = str(
        args.session_api_base_url or values.get("EA_WHATSAPP_WEB_SESSION_API_BASE_URL") or DEFAULT_SESSION_API_BASE_URL
    ).strip().rstrip("/")
    payload = request_json(
        method="GET",
        url=f"{base_url}/healthz",
        **_session_api_headers(args, values),
    )
    return {
        "sidecar_health_probed": True,
        "sidecar_health_ok": bool(payload.get("ok", True)),
        "sidecar_health_status": str(payload.get("status") or "").strip(),
        "sidecar_health_session_ref": str(payload.get("session_ref") or "").strip(),
    }


def _sidecar_status_payload(
    *,
    base_url: str,
    session_ref: str,
    args: argparse.Namespace,
    values: dict[str, str],
    request_json: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return request_json(
        method="GET",
        url=f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/status",
        **_session_api_headers(args, values),
    )


def _sidecar_qr_payload(
    *,
    base_url: str,
    session_ref: str,
    args: argparse.Namespace,
    values: dict[str, str],
    request_json: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return request_json(
        method="GET",
        url=f"{base_url}/sessions/{urllib.parse.quote(session_ref)}/qr",
        **_session_api_headers(args, values),
    )


def _compose_contract(compose_file: Path) -> dict[str, object]:
    text = compose_file.read_text(encoding="utf-8", errors="ignore") if compose_file.exists() else ""
    return {
        "compose_file_present": compose_file.exists(),
        "processor_service_declared": "ea-whatsapp-web-action-processor:" in text,
        "processor_script_mounted": "process_whatsapp_web_session_actions.py" in text,
        "processor_state_volume_declared": "ea_whatsapp_web_actions" in text,
    }


def _processor_volume_targets(compose_file: Path) -> tuple[str, ...]:
    if not compose_file.exists():
        return ()
    try:
        lines = compose_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ()

    targets: list[str] = []
    in_processor = False
    processor_indent = 0
    in_volumes = False
    volumes_indent = 0
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        if stripped == "ea-whatsapp-web-action-processor:":
            in_processor = True
            processor_indent = indent
            in_volumes = False
            continue
        if in_processor and indent <= processor_indent and stripped.endswith(":"):
            in_processor = False
            in_volumes = False
        if not in_processor:
            continue
        if stripped == "volumes:":
            in_volumes = True
            volumes_indent = indent
            continue
        if in_volumes and indent <= volumes_indent and not stripped.startswith("- "):
            in_volumes = False
        if not in_volumes or not stripped.startswith("- "):
            continue
        spec = stripped[2:].strip().strip("'\"")
        if not spec or spec.startswith("{"):
            continue
        parts = spec.rsplit(":", 2)
        target = ""
        if len(parts) == 2:
            target = parts[1]
        elif len(parts) == 3:
            mode_values = {mode.strip() for mode in parts[2].split(",")}
            target = parts[1] if mode_values <= {"ro", "rw", "z", "Z", "cached", "delegated", "consistent"} else parts[2]
        target = target.strip()
        if target.startswith("/") and target not in targets:
            targets.append(target.rstrip("/") or "/")
    return tuple(targets)


def _path_is_within(path: Path, parent: str) -> bool:
    raw_path = path.as_posix().rstrip("/") or "/"
    raw_parent = str(parent or "").rstrip("/") or "/"
    return raw_path == raw_parent or raw_path.startswith(f"{raw_parent}/")


def _container_env_presence(
    *,
    container_name: str,
    keys: tuple[str, ...],
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, bool]:
    try:
        completed = run(
            ["docker", "exec", container_name, "env"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return {key: False for key in keys}
    if completed.returncode != 0:
        return {key: False for key in keys}
    present: dict[str, bool] = {key: False for key in keys}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in present:
            present[key] = bool(value.strip())
    return present


def _file_has_value(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _host_secret_file_present(values: dict[str, str]) -> bool:
    configured = str(values.get(SECRET_FILE_KEY) or "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend(HOST_SECRET_FILE_CANDIDATES)
    return any(_file_has_value(path) for path in candidates)


def _state_file_report(
    args: argparse.Namespace,
    values: dict[str, str],
    *,
    processor_volume_targets: tuple[str, ...] = (),
) -> dict[str, object]:
    state_file = Path(str(args.state_file or values.get("EA_WHATSAPP_WEB_ACTION_STATE_FILE") or DEFAULT_ACTION_STATE_FILE))
    stale_seconds = max(1, _int_value(args.state_stale_seconds, 600))
    is_processor_volume_path = state_file.is_absolute() and any(
        _path_is_within(state_file, target) for target in processor_volume_targets
    )
    report: dict[str, object] = {
        "state_file": str(state_file),
        "state_file_checked_on_host": True,
        "state_file_json_readable": True,
        "state_file_object": False,
        "state_file_parent_writable": False,
        "state_file_present": state_file.is_file(),
        "state_file_probe_source": "host",
        "state_file_processor_volume_path": is_processor_volume_path,
        "state_fresh": False,
        "state_stale_seconds": stale_seconds,
        "state_updated_at_valid": False,
    }

    if is_processor_volume_path and not state_file.parent.exists():
        report["state_file_host_probe_skipped"] = True
        report["state_file_host_probe_skip_reason"] = "processor_volume_parent_absent"
    else:
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            probe = state_file.parent / f".{state_file.name}.readiness.{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            report["state_file_parent_writable"] = True
        except OSError:
            report["state_file_parent_writable"] = False

    if not state_file.is_file():
        return report

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report["state_file_json_readable"] = False
        return report
    if not isinstance(state, dict):
        return report

    report["state_file_object"] = True
    state_session_ref = str(state.get("session_ref") or "").strip()
    updated_at = _parse_iso_timestamp(state.get("updated_at"))
    report["state_session_ref"] = state_session_ref
    report["state_updated_at"] = str(state.get("updated_at") or "").strip()
    report["state_updated_at_valid"] = updated_at is not None
    if updated_at is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - updated_at).total_seconds()))
        report["state_age_seconds"] = age_seconds
        report["state_fresh"] = age_seconds <= stale_seconds
    else:
        report["state_fresh"] = False
    return report


def _container_state_file_report(
    *,
    container_name: str,
    state_file: str,
    stale_seconds: int,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    script = r"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

state_file = Path(sys.argv[1])
stale_seconds = max(1, int(sys.argv[2]))

def parse_iso(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

report = {
    "state_file": str(state_file),
    "state_file_checked_in_container": True,
    "state_file_container": sys.argv[3] if len(sys.argv) > 3 else "",
    "state_file_json_readable": True,
    "state_file_object": False,
    "state_file_parent_writable": False,
    "state_file_present": state_file.is_file(),
    "state_fresh": False,
    "state_stale_seconds": stale_seconds,
    "state_updated_at_valid": False,
}
try:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    probe = state_file.parent / f".{state_file.name}.readiness.{os.getpid()}"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    report["state_file_parent_writable"] = True
except OSError:
    pass

if state_file.is_file():
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        report["state_file_json_readable"] = False
    else:
        if isinstance(state, dict):
            report["state_file_object"] = True
            report["state_session_ref"] = str(state.get("session_ref") or "").strip()
            report["state_updated_at"] = str(state.get("updated_at") or "").strip()
            updated_at = parse_iso(state.get("updated_at"))
            report["state_updated_at_valid"] = updated_at is not None
            if updated_at is not None:
                age_seconds = max(0, int((datetime.now(timezone.utc) - updated_at).total_seconds()))
                report["state_age_seconds"] = age_seconds
                report["state_fresh"] = age_seconds <= stale_seconds
            else:
                report["state_fresh"] = False
print(json.dumps(report, sort_keys=True))
"""
    try:
        completed = run(
            ["docker", "exec", container_name, "python", "-c", script, str(state_file), str(max(1, stale_seconds)), container_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return {"state_file_checked_in_container": False}
    if completed.returncode != 0:
        return {"state_file_checked_in_container": False}
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"state_file_checked_in_container": False}
    return parsed if isinstance(parsed, dict) else {"state_file_checked_in_container": False}


def _state_needs_container_probe(state: dict[str, object]) -> bool:
    if not bool(state.get("state_file_processor_volume_path")):
        return False
    if not bool(state.get("state_file_parent_writable")):
        return True
    if not bool(state.get("state_file_present")):
        return True
    if not bool(state.get("state_file_json_readable")):
        return True
    if not bool(state.get("state_file_object")):
        return True
    if bool(state.get("state_file_object")) and not bool(state.get("state_fresh", True)):
        return True
    return False


def _merge_container_state(
    *,
    host_state: dict[str, object],
    container_state: dict[str, object],
) -> dict[str, object]:
    host_observations = {
        "state_file_host_json_readable": host_state.get("state_file_json_readable"),
        "state_file_host_object": host_state.get("state_file_object"),
        "state_file_host_parent_writable": host_state.get("state_file_parent_writable"),
        "state_file_host_present": host_state.get("state_file_present"),
        "state_file_host_fresh": host_state.get("state_fresh"),
    }
    return {
        **host_state,
        **host_observations,
        **container_state,
        "state_file_container_probe_attempted": True,
        "state_file_container_probe_succeeded": True,
        "state_file_probe_source": "processor_container",
    }


def _container_volume_state_unverified(state: dict[str, object]) -> bool:
    return (
        bool(state.get("state_file_processor_volume_path"))
        and bool(state.get("state_file_host_probe_skipped"))
        and not bool(state.get("state_file_container_probe_succeeded"))
    )


def _container_secret_file_present(
    *,
    container_name: str,
    paths: tuple[str, ...],
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    script = " || ".join(f"[ -s {path!r} ]" for path in paths)
    try:
        completed = run(
            ["docker", "exec", container_name, "sh", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _sidecar_status(
    args: argparse.Namespace,
    values: dict[str, str],
    state: dict[str, object],
    request_json: Callable[..., dict[str, Any]],
) -> dict[str, object]:
    if not bool(args.probe_sidecar):
        return {"sidecar_probed": False}
    base_url = str(
        args.session_api_base_url or values.get("EA_WHATSAPP_WEB_SESSION_API_BASE_URL") or DEFAULT_SESSION_API_BASE_URL
    ).strip().rstrip("/")
    qr_fresh_seconds = max(10, _int_value(values.get("EA_WHATSAPP_WEB_QR_FRESH_SECONDS"), DEFAULT_QR_FRESH_SECONDS))
    configured_ref = _configured_session_ref(args, values)
    state_ref = str(state.get("state_session_ref") or "").strip()
    health = _sidecar_health(args, values, request_json)
    health_ref = str(health.get("sidecar_health_session_ref") or "").strip()
    candidate_refs: list[tuple[str, str]] = []
    for source, candidate in (
        ("state_file", state_ref),
        ("sidecar_healthz", health_ref),
        ("configured", configured_ref),
    ):
        if not candidate or any(existing == candidate for existing, _ in candidate_refs):
            continue
        candidate_refs.append((candidate, source))

    effective_ref = configured_ref
    effective_source = "configured"
    payload: dict[str, Any] = {}
    for candidate, source in candidate_refs or [(configured_ref, "configured")]:
        current = _sidecar_status_payload(
            base_url=base_url,
            session_ref=candidate,
            args=args,
            values=values,
            request_json=request_json,
        )
        effective_ref = candidate
        effective_source = source
        payload = current
        if str(current.get("reason") or "").strip() != "session_not_found":
            break
    qr_payload: dict[str, Any] = {}
    if bool(payload.get("qr_required")) or str(payload.get("status") or "").strip() == "qr_required":
        qr_payload = _sidecar_qr_payload(
            base_url=base_url,
            session_ref=effective_ref,
            args=args,
            values=values,
            request_json=request_json,
        )
    sidecar_last_qr_at = str(payload.get("last_qr_at") or "").strip()
    if not sidecar_last_qr_at:
        sidecar_last_qr_at = str(qr_payload.get("last_qr_at") or "").strip()
    sidecar_last_qr = _parse_iso_timestamp(sidecar_last_qr_at)
    sidecar_qr_age_seconds = None
    if sidecar_last_qr is not None:
        sidecar_qr_age_seconds = max(0, int((datetime.now(timezone.utc) - sidecar_last_qr).total_seconds()))
    sidecar_qr_fresh = sidecar_qr_age_seconds is not None and sidecar_qr_age_seconds <= qr_fresh_seconds
    return {
        "sidecar_probed": True,
        "sidecar_ok": bool(payload.get("ok", True)) and str(payload.get("status") or "") != "initialize_failed",
        "sidecar_ready": bool(payload.get("ready")),
        "sidecar_status": str(payload.get("status") or "").strip(),
        "sidecar_store_message_text": bool(payload.get("store_message_text")),
        "sidecar_qr_metadata_probed": bool(qr_payload),
        "sidecar_qr_present": bool(qr_payload.get("qr_present") if qr_payload else payload.get("qr_present")),
        "sidecar_qr_required": bool(qr_payload.get("qr_required") if qr_payload else payload.get("qr_required")),
        "sidecar_last_qr_at": sidecar_last_qr_at,
        "sidecar_qr_age_seconds": sidecar_qr_age_seconds,
        "sidecar_qr_fresh": sidecar_qr_fresh,
        "sidecar_qr_fresh_seconds": qr_fresh_seconds,
        "configured_session_ref": configured_ref,
        "effective_session_ref": effective_ref,
        "effective_session_ref_source": effective_source,
        **health,
    }


def build_report(
    args: argparse.Namespace,
    *,
    request_json: Callable[..., dict[str, Any]] = _request_json,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    values = _merged_env(args)
    compose_file = Path(str(args.compose_file or DEFAULT_COMPOSE_FILE))
    compose = _compose_contract(compose_file)
    processor_volume_targets = _processor_volume_targets(compose_file)
    secret_present = any(bool(str(values.get(key) or "").strip()) for key in CALLBACK_SECRET_KEYS) or _host_secret_file_present(values)
    processor_enabled = _bool_env(values.get("EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED"))
    state = _state_file_report(args, values, processor_volume_targets=processor_volume_targets)

    container_report: dict[str, object] = {"containers_checked": False}
    if bool(args.probe_sidecar) and not bool(args.check_containers) and _state_needs_container_probe(state):
        container_state = _container_state_file_report(
            container_name=str(args.processor_container),
            state_file=str(args.state_file or values.get("EA_WHATSAPP_WEB_ACTION_STATE_FILE") or DEFAULT_ACTION_STATE_FILE),
            stale_seconds=max(1, _int_value(args.state_stale_seconds, 600)),
            run=run,
        )
        if bool(container_state.get("state_file_checked_in_container")):
            state = _merge_container_state(host_state=state, container_state=container_state)
        else:
            state["state_file_container_probe_attempted"] = True
            state["state_file_container_probe_succeeded"] = False
    if bool(args.check_containers):
        if not bool(state.get("state_file_present")) or not bool(state.get("state_file_parent_writable")):
            container_state = _container_state_file_report(
                container_name=str(args.processor_container),
                state_file=str(args.state_file or values.get("EA_WHATSAPP_WEB_ACTION_STATE_FILE") or DEFAULT_ACTION_STATE_FILE),
                stale_seconds=max(1, _int_value(args.state_stale_seconds, 600)),
                run=run,
            )
            if bool(container_state.get("state_file_checked_in_container")):
                state = _merge_container_state(host_state=state, container_state=container_state)
            else:
                state["state_file_container_probe_attempted"] = True
                state["state_file_container_probe_succeeded"] = False
        api_env = _container_env_presence(container_name=str(args.api_container), keys=CALLBACK_SECRET_KEYS, run=run)
        processor_env = _container_env_presence(
            container_name=str(args.processor_container),
            keys=("EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED", *CALLBACK_SECRET_KEYS),
            run=run,
        )
        api_secret_file_present = _container_secret_file_present(
            container_name=str(args.api_container),
            paths=API_CONTAINER_SECRET_FILES,
            run=run,
        )
        processor_secret_file_present = _container_secret_file_present(
            container_name=str(args.processor_container),
            paths=PROCESSOR_CONTAINER_SECRET_FILES,
            run=run,
        )
        container_report = {
            "containers_checked": True,
            "api_callback_secret_present": any(api_env.values()) or api_secret_file_present,
            "processor_callback_secret_present": any(processor_env.get(key, False) for key in CALLBACK_SECRET_KEYS) or processor_secret_file_present,
            "processor_container_enabled": bool(processor_env.get("EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED")),
        }
    sidecar = _sidecar_status(args, values, state, request_json)

    reasons: list[str] = []
    if not processor_enabled:
        ready = True
        return {
            "ready": ready,
            "reason": "disabled",
            "reasons": reasons,
            "callback_secret_present": secret_present,
            "action_processor_enabled": processor_enabled,
            **compose,
            **sidecar,
            **state,
            **container_report,
        }

    if not secret_present:
        reasons.append("callback_secret_missing")
    for key in ("compose_file_present", "processor_service_declared", "processor_script_mounted", "processor_state_volume_declared"):
        if not bool(compose.get(key)):
            reasons.append(key)
    state_unknown = _container_volume_state_unverified(state)
    if state_unknown:
        reasons.append("state_file_container_probe_unavailable")
    else:
        if not bool(state.get("state_file_parent_writable")):
            reasons.append("state_file_parent_not_writable")
        if not bool(state.get("state_file_present")):
            reasons.append("state_file_missing")
    if bool(state.get("state_file_present")) and not state_unknown:
        if not bool(state.get("state_file_json_readable")):
            reasons.append("state_file_unreadable")
        elif not bool(state.get("state_file_object")):
            reasons.append("state_file_not_object")
        elif not bool(state.get("state_updated_at_valid")):
            reasons.append("state_updated_at_invalid")
        elif not bool(state.get("state_fresh")):
            reasons.append("state_file_stale")
        state_session_ref = str(state.get("state_session_ref") or "").strip()
        expected_session_ref = str(sidecar.get("effective_session_ref") or _configured_session_ref(args, values)).strip()
        if state_session_ref and expected_session_ref and state_session_ref != expected_session_ref:
            reasons.append("state_session_ref_mismatch")
    if bool(sidecar.get("sidecar_probed")):
        if not bool(sidecar.get("sidecar_ready")):
            reasons.append("sidecar_not_ready")
        if not bool(sidecar.get("sidecar_store_message_text")):
            reasons.append("sidecar_message_text_storage_disabled")
    if bool(container_report.get("containers_checked")):
        if not bool(container_report.get("api_callback_secret_present")):
            reasons.append("api_container_callback_secret_missing")
        if not bool(container_report.get("processor_callback_secret_present")):
            reasons.append("processor_container_callback_secret_missing")
        if not bool(container_report.get("processor_container_enabled")):
            reasons.append("processor_container_disabled_or_not_running")

    ready = not reasons
    return {
        "ready": ready,
        "reason": "ready" if ready else reasons[0],
        "reasons": reasons,
        "callback_secret_present": secret_present,
        "action_processor_enabled": processor_enabled,
        **compose,
        **sidecar,
        **state,
        **container_report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check live readiness for WhatsApp Web selected-button action processing.")
    parser.add_argument("--env-file", default=_env("EA_WHATSAPP_WEB_ACTION_ENV_FILE", str(DEFAULT_ENV_FILE)))
    parser.add_argument("--compose-file", default=_env("EA_WHATSAPP_WEB_ACTION_COMPOSE_FILE", str(DEFAULT_COMPOSE_FILE)))
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", DEFAULT_SESSION_REF))
    parser.add_argument("--session-api-token", default=_env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"))
    parser.add_argument("--auth-header-prefix", default=os.environ.get("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "))
    parser.add_argument("--timeout-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "15") or "15"))
    parser.add_argument("--state-file", default=_env("EA_WHATSAPP_WEB_ACTION_STATE_FILE", DEFAULT_ACTION_STATE_FILE))
    parser.add_argument("--state-stale-seconds", type=int, default=_int_value(_env("EA_WHATSAPP_WEB_ACTION_STATE_STALE_SECONDS", "600"), 600))
    parser.add_argument("--probe-sidecar", action="store_true")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Return success for a live processor that is only waiting on operator QR/session pairing.",
    )
    parser.add_argument("--check-containers", action="store_true")
    parser.add_argument("--api-container", default=_env("EA_API_CONTAINER", "ea-api"))
    parser.add_argument("--processor-container", default=_env("EA_WHATSAPP_WEB_ACTION_PROCESSOR_CONTAINER", "ea-whatsapp-web-action-processor"))
    return parser.parse_args()


def healthcheck_ok(report: dict[str, object]) -> bool:
    if bool(report.get("ready")):
        return True
    reasons = {str(reason) for reason in list(report.get("reasons") or [])}
    if not reasons or reasons - {"sidecar_not_ready"}:
        return False
    if not bool(report.get("sidecar_ok")) or not bool(report.get("sidecar_health_ok")):
        return False
    if not bool(report.get("state_fresh")):
        return False
    return bool(report.get("sidecar_qr_required")) and bool(report.get("sidecar_qr_present"))


def main() -> int:
    args = parse_args()
    report = build_report(args)
    print(json.dumps(report, sort_keys=True))
    if bool(args.healthcheck):
        return 0 if healthcheck_ok(report) else 2
    return 0 if bool(report.get("ready")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
