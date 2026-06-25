from __future__ import annotations

import errno
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError

_DEFAULT_GEMINI_AUTH_ACCOUNT = "EA_GEMINI_VORTEX_DEFAULT_AUTH"
_GEMINI_DIRECT_KEY_ENV_NAMES = ("EA_GEMINI_VORTEX_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
_GEMINI_FALLBACK_KEY_PREFIX = "GOOGLE_API_KEY_FALLBACK_"
_UTC = timezone.utc


def _env_value(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return raw


def _preview_text(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    return cleaned[:limit]


def _normalize_cli_model_name(raw_model: str) -> str:
    model = str(raw_model or "").strip()
    if not model:
        return ""
    prefix = "gemini_vortex:"
    if model.startswith(prefix):
        candidate = model[len(prefix) :].strip()
        if candidate:
            return candidate
    return model


def _clean_cli_failure_detail(raw_detail: str) -> str:
    text = str(raw_detail or "").strip()
    if not text:
        return "gemini_vortex_failed"
    filtered: list[str] = []
    skip_trace_hint = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("(node:") and "DeprecationWarning:" in stripped and "punycode" in stripped:
            skip_trace_hint = True
            continue
        if skip_trace_hint and stripped.startswith("(Use `node --trace-deprecation"):
            skip_trace_hint = False
            continue
        skip_trace_hint = False
        if stripped == "YOLO mode is enabled. All tool calls will be automatically approved.":
            continue
        if stripped == "Loaded cached credentials.":
            continue
        filtered.append(stripped)
    cleaned = "\n".join(filtered).strip()
    return cleaned or text


def _gemini_cli_parallel_limit() -> int:
    raw = _env_value("EA_GEMINI_VORTEX_MAX_PARALLEL") or "1"
    try:
        return max(1, min(16, int(raw)))
    except Exception:
        return 1


def _gemini_cli_lock_timeout_seconds(timeout_seconds: int) -> float:
    raw = _env_value("EA_GEMINI_VORTEX_LOCK_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(1.0, min(float(raw), float(max(15, timeout_seconds))))
        except Exception:
            pass
    return max(5.0, min(30.0, float(max(15, timeout_seconds))))


def _gemini_cli_spawn_retries() -> int:
    raw = _env_value("EA_GEMINI_VORTEX_SPAWN_RETRIES") or "2"
    try:
        return max(0, min(6, int(raw)))
    except Exception:
        return 2


def _gemini_cli_retry_delay_seconds(attempt: int) -> float:
    base = 0.35
    return min(2.0, base * max(1, attempt))


def _gemini_spawn_pressure_cooldown_seconds() -> int:
    raw = _env_value("EA_GEMINI_VORTEX_SPAWN_PRESSURE_COOLDOWN_SECONDS") or "45"
    try:
        return max(5, min(600, int(raw)))
    except Exception:
        return 45


def _is_retryable_spawn_oserror(exc: OSError) -> bool:
    if exc.errno in {errno.EAGAIN, errno.ENOMEM, errno.EBUSY}:
        return True
    lowered = str(exc).strip().lower()
    return "eagain" in lowered or "resource temporarily unavailable" in lowered


def _is_retryable_cli_failure_detail(detail: str) -> bool:
    lowered = str(detail or "").strip().lower()
    if not lowered:
        return False
    return any(
        token in lowered
        for token in (
            "spawn /usr/bin/node eagain",
            "resource temporarily unavailable",
            "workerthreadstaskrunner::delayedscheduler::start",
            "node_platform.cc:68",
            "assert",
        )
    )


@contextmanager
def _acquire_gemini_cli_slot(*, timeout_seconds: int) -> Any:
    root = _provider_ledger_dir() or Path("/tmp/ea_provider_ledger")
    root.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _gemini_cli_lock_timeout_seconds(timeout_seconds)
    handle = None
    acquired = None
    try:
        while time.monotonic() < deadline:
            for index in range(_gemini_cli_parallel_limit()):
                lock_path = root / f"gemini_vortex_cli_slot_{index}.lock"
                candidate = lock_path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    handle = candidate
                    acquired = {"slot_index": index, "path": str(lock_path)}
                    break
                except BlockingIOError:
                    candidate.close()
            if acquired is not None:
                break
            time.sleep(0.2)
        if acquired is None:
            raise ToolExecutionError("gemini_vortex_cli_busy")
        yield acquired
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass


def _provider_ledger_dir() -> Path | None:
    raw = _env_value("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "/tmp/ea_provider_ledger"
    if not raw:
        return None
    try:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(_UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value).astimezone(_UTC)
    except Exception:
        return None


def _gemini_fallback_key_env_names() -> tuple[str, ...]:
    entries: list[tuple[int, str]] = []
    for name, value in os.environ.items():
        if not name.startswith(_GEMINI_FALLBACK_KEY_PREFIX):
            continue
        if not str(value or "").strip():
            continue
        suffix = name.removeprefix(_GEMINI_FALLBACK_KEY_PREFIX)
        priority = int(suffix) if suffix.isdigit() else 10_000
        entries.append((priority, name))
    entries.sort(key=lambda item: (item[0], item[1]))
    return tuple(name for _, name in entries)


def _gemini_direct_key_env_name() -> str:
    for name in _GEMINI_DIRECT_KEY_ENV_NAMES:
        if _env_value(name):
            return name
    return ""


def _env_truthy(name: str) -> bool:
    return _env_value(name).lower() in {"1", "true", "yes", "on"}


def _gemini_vertex_adc_ready() -> bool:
    if not _env_truthy("GOOGLE_GENAI_USE_VERTEXAI"):
        return False
    if not (_env_value("GOOGLE_CLOUD_PROJECT") and _env_value("GOOGLE_CLOUD_LOCATION")):
        return False
    credentials_path = _env_value("GOOGLE_APPLICATION_CREDENTIALS")
    return bool(credentials_path and _readable_file(Path(credentials_path)))


def _gemini_selection_mode() -> str:
    raw = _env_value("EA_GEMINI_VORTEX_SELECTION_MODE").lower()
    if raw in {"fallback", "round_robin"}:
        return raw
    return "round_robin" if _gemini_fallback_key_env_names() else "fallback"


def _gemini_default_auth_ready() -> bool:
    auth_state, auth_detail = gemini_vortex_auth_state()
    return auth_state == "ready" and auth_detail in {"cli_config", "vertex_adc"}


def _gemini_default_auth_slot_enabled() -> bool:
    raw = _env_value("EA_GEMINI_VORTEX_DEFAULT_AUTH_ENABLED")
    if raw.lower() in {"0", "false", "no", "off"}:
        return False
    return True


def _gemini_config_source_dir() -> Path | None:
    raw = _env_value("EA_GEMINI_VORTEX_CONFIG_DIR")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def _gemini_home_root() -> Path:
    raw = _env_value("EA_GEMINI_VORTEX_HOME_ROOT") or "/tmp/ea-gemini-vortex"
    return Path(raw)


def _readable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.R_OK)
    except OSError:
        return False


def gemini_vortex_auth_state() -> tuple[str, str]:
    direct_key_env = _gemini_direct_key_env_name()
    if direct_key_env:
        return ("ready", f"api_key:{direct_key_env}")
    if _gemini_fallback_key_env_names():
        return ("ready", "api_key")
    if _gemini_vertex_adc_ready():
        return ("ready", "vertex_adc")
    source_dir = _gemini_config_source_dir()
    if source_dir is None:
        return ("missing", "auth_config_dir_missing")
    unreadable = [
        name
        for name in ("settings.json", "oauth_creds.json", "google_accounts.json")
        if (source_dir / name).exists() and not os.access(source_dir / name, os.R_OK)
    ]
    if unreadable:
        return ("degraded", f"auth_config_unreadable:{','.join(unreadable)}")
    if not _readable_file(source_dir / "settings.json"):
        return ("missing", "auth_settings_missing")
    if not (_readable_file(source_dir / "oauth_creds.json") or _readable_file(source_dir / "google_accounts.json")):
        return ("missing", "auth_credentials_missing")
    return ("ready", "cli_config")


def _copy_gemini_cli_config(*, source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "settings.json",
        "oauth_creds.json",
        "google_accounts.json",
        "trustedFolders.json",
        "installation_id",
        "state.json",
        "projects.json",
    ):
        source = source_dir / name
        if not source.is_file():
            continue
        target = target_dir / name
        try:
            shutil.copy2(source, target)
        except OSError:
            continue
        try:
            target.chmod(0o600)
        except Exception:
            pass


def _prepare_gemini_cli_home(slot: str) -> str | None:
    safe_slot = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(slot or "default")) or "default"
    home = _gemini_home_root() / safe_slot
    gemini_dir = home / ".gemini"
    source_dir = _gemini_config_source_dir()
    if source_dir is not None:
        _copy_gemini_cli_config(source_dir=source_dir, target_dir=gemini_dir)
    else:
        gemini_dir.mkdir(parents=True, exist_ok=True)
    (gemini_dir / "tmp").mkdir(parents=True, exist_ok=True)
    return str(home)


def _prepare_gemini_cli_env_auth_home(slot: str) -> str:
    safe_slot = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(slot or "default")) or "default"
    home = _gemini_home_root() / f"env_{safe_slot}"
    gemini_dir = home / ".gemini"
    (gemini_dir / "tmp").mkdir(parents=True, exist_ok=True)
    return str(home)


def _next_round_robin_index(slot_count: int) -> int:
    if slot_count <= 1:
        return 0
    root = _provider_ledger_dir()
    if root is None:
        return 0
    target = root / "gemini_vortex_slot_index"
    try:
        with target.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            raw = handle.read().strip()
            current = int(raw) if raw else -1
            next_index = (current + 1) % slot_count
            handle.seek(0)
            handle.truncate()
            handle.write(str(next_index))
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return next_index
    except Exception:
        return 0


def _slot_env_suffix(slot: str) -> str:
    return str(slot or "default").strip().upper().replace("-", "_")


def _slot_owner(slot: str) -> str:
    return _env_value(f"EA_GEMINI_VORTEX_SLOT_{_slot_env_suffix(slot)}_OWNER")


def _slot_quota_posture(slot: str) -> str:
    return _env_value(f"EA_GEMINI_VORTEX_SLOT_{_slot_env_suffix(slot)}_QUOTA_POSTURE")


def _slot_lease_seconds() -> int:
    raw = _env_value("EA_GEMINI_VORTEX_SLOT_LEASE_SECONDS") or "900"
    try:
        return max(30, int(raw))
    except Exception:
        return 900


def _slot_ledger_path() -> Path | None:
    root = _provider_ledger_dir()
    if root is None:
        return None
    return root / "gemini_vortex_slots.json"


def _load_slot_ledger() -> dict[str, dict[str, Any]]:
    target = _slot_ledger_path()
    if target is None:
        return {}
    try:
        if not target.exists():
            return {}
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    payload: dict[str, dict[str, Any]] = {}
    for slot, item in loaded.items():
        if isinstance(item, dict):
            payload[str(slot)] = dict(item)
    return payload


def _save_slot_ledger(payload: dict[str, dict[str, Any]]) -> None:
    target = _slot_ledger_path()
    if target is None:
        return
    try:
        target.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    except Exception:
        return


def _spawn_pressure_ledger_path() -> Path | None:
    root = _provider_ledger_dir()
    if root is None:
        return None
    return root / "gemini_vortex_spawn_pressure.json"


def _load_spawn_pressure_state() -> dict[str, Any]:
    target = _spawn_pressure_ledger_path()
    if target is None or not target.exists():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _save_spawn_pressure_state(payload: dict[str, Any]) -> None:
    target = _spawn_pressure_ledger_path()
    if target is None:
        return
    try:
        target.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    except Exception:
        return


def _clear_spawn_pressure_state() -> None:
    target = _spawn_pressure_ledger_path()
    if target is None:
        return
    try:
        target.unlink(missing_ok=True)
    except Exception:
        return


def _spawn_pressure_active() -> tuple[bool, str]:
    payload = _load_spawn_pressure_state()
    if not payload:
        return (False, "")
    expires_at = _parse_iso(str(payload.get("cooldown_expires_at") or ""))
    now = datetime.now(_UTC)
    if expires_at is None or expires_at <= now:
        _clear_spawn_pressure_state()
        return (False, "")
    detail = str(payload.get("detail") or "").strip()
    remaining_seconds = max(1, int((expires_at - now).total_seconds()))
    reason = f"spawn_pressure_cooldown:{remaining_seconds}s"
    if detail:
        reason = f"{reason}:{detail[:160]}"
    return (True, reason)


def _record_spawn_pressure(detail: str) -> None:
    now = datetime.now(_UTC)
    cooldown_seconds = _gemini_spawn_pressure_cooldown_seconds()
    payload = {
        "state": "cooldown",
        "recorded_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "cooldown_expires_at": (now + timedelta(seconds=cooldown_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "detail": str(detail or "").strip()[:240],
    }
    _save_spawn_pressure_state(payload)


def _lease_is_active(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    current = now or datetime.now(_UTC)
    lease_expires_at = _parse_iso(str(entry.get("lease_expires_at") or ""))
    return bool(lease_expires_at and lease_expires_at > current)


@dataclass(frozen=True)
class GeminiAuthSlot:
    slot: str
    account_name: str
    fallback_key_env_name: str | None = None


def gemini_vortex_slot_status() -> list[dict[str, Any]]:
    adapter = GeminiVortexToolAdapter()
    ledger = _load_slot_ledger()
    now = datetime.now(_UTC)
    spawn_pressure_active, spawn_pressure_detail = _spawn_pressure_active()
    payload: list[dict[str, Any]] = []
    for slot in adapter._auth_slots():
        entry = dict(ledger.get(slot.slot) or {})
        active_lease = _lease_is_active(entry, now=now)
        payload.append(
            {
                "slot": slot.slot,
                "account_name": slot.account_name,
                "configured": True,
                "slot_owner": _slot_owner(slot.slot),
                "quota_posture": _slot_quota_posture(slot.slot) or "unknown",
                "active_lease": active_lease,
                "lease_holder": str(entry.get("lease_holder") or "") if active_lease else "",
                "lease_expires_at": str(entry.get("lease_expires_at") or "") if active_lease else "",
                "last_used_principal_id": str(entry.get("lease_holder") or ""),
                "last_used_at": str(entry.get("last_used_at") or ""),
                "last_result": str(entry.get("last_result") or ""),
                "last_result_detail": str(entry.get("last_result_detail") or ""),
                "spawn_pressure_active": spawn_pressure_active,
                "spawn_pressure_detail": spawn_pressure_detail if spawn_pressure_active else "",
            }
        )
    return payload


class GeminiVortexToolAdapter:
    def _command_base(self) -> list[str]:
        raw = _env_value("EA_GEMINI_VORTEX_COMMAND") or "gemini"
        return shlex.split(raw)

    def _default_model(self) -> str:
        return _env_value("EA_GEMINI_VORTEX_MODEL") or "gemini-3.5-flash"

    def _timeout_seconds(self, payload: dict[str, Any] | None = None) -> int:
        raw = _env_value("EA_GEMINI_VORTEX_TIMEOUT_SECONDS") or "300"
        try:
            configured_timeout = max(15, int(raw))
        except Exception:
            configured_timeout = 300
        requested_timeout = 0
        if isinstance(payload, dict):
            try:
                requested_timeout = max(0, int(payload.get("timeout_seconds") or 0))
            except Exception:
                requested_timeout = 0
        if requested_timeout > 0:
            return max(15, min(configured_timeout, requested_timeout))
        return configured_timeout

    def _auth_slots(self) -> tuple[GeminiAuthSlot, ...]:
        direct_key_env = _gemini_direct_key_env_name()
        slots: list[GeminiAuthSlot] = []
        if direct_key_env:
            slots.append(
                GeminiAuthSlot(
                    slot="default",
                    account_name=direct_key_env,
                    fallback_key_env_name=direct_key_env,
                )
            )
        elif _gemini_default_auth_slot_enabled():
            slots.append(
                GeminiAuthSlot(
                    slot="default",
                    account_name=_DEFAULT_GEMINI_AUTH_ACCOUNT,
                    fallback_key_env_name=None,
                )
            )
        for index, env_name in enumerate(_gemini_fallback_key_env_names(), start=1):
            slots.append(
                GeminiAuthSlot(
                    slot=f"fallback_{index}",
                    account_name=env_name,
                    fallback_key_env_name=env_name,
                )
            )
        return tuple(slots)

    def _ordered_auth_slots(self) -> tuple[GeminiAuthSlot, ...]:
        slots = self._auth_slots()
        if len(slots) <= 1 or _gemini_selection_mode() != "round_robin":
            return slots
        start = _next_round_robin_index(len(slots))
        return slots[start:] + slots[:start]

    def _select_auth_slots(self, *, principal_id: str) -> tuple[GeminiAuthSlot, ...]:
        ordered = list(self._ordered_auth_slots())
        if not ordered:
            return ()
        clean_principal = str(principal_id or "").strip()
        if not clean_principal:
            return tuple(ordered)
        ledger = _load_slot_ledger()
        now = datetime.now(_UTC)
        same_principal = next(
            (
                slot
                for slot in ordered
                if str((ledger.get(slot.slot) or {}).get("lease_holder") or "") == clean_principal
                and _lease_is_active(dict(ledger.get(slot.slot) or {}), now=now)
            ),
            None,
        )
        if same_principal is not None:
            return tuple([same_principal, *[slot for slot in ordered if slot.slot != same_principal.slot]])
        available = next(
            (
                slot
                for slot in ordered
                if not _lease_is_active(dict(ledger.get(slot.slot) or {}), now=now)
            ),
            None,
        )
        if available is not None:
            return tuple([available, *[slot for slot in ordered if slot.slot != available.slot]])
        return tuple(ordered)

    def _record_slot_usage(
        self,
        slot: GeminiAuthSlot,
        *,
        principal_id: str,
        success: bool,
        detail: str = "",
    ) -> dict[str, str]:
        now = datetime.now(_UTC)
        lease_holder = str(principal_id or "").strip()
        lease_expires_at = (
            (now + timedelta(seconds=_slot_lease_seconds())).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if lease_holder
            else ""
        )
        ledger = _load_slot_ledger()
        ledger[slot.slot] = {
            "account_name": slot.account_name,
            "slot_owner": _slot_owner(slot.slot),
            "quota_posture": _slot_quota_posture(slot.slot) or "unknown",
            "lease_holder": lease_holder,
            "lease_expires_at": lease_expires_at,
            "last_used_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "last_result": "ready" if success else "failed",
            "last_result_detail": str(detail or "").strip()[:400],
        }
        _save_slot_ledger(ledger)
        return {
            "lease_holder": lease_holder,
            "lease_expires_at": lease_expires_at,
            "slot_owner": _slot_owner(slot.slot),
            "quota_posture": _slot_quota_posture(slot.slot) or "unknown",
        }

    def _command_env(self, slot: GeminiAuthSlot) -> dict[str, str]:
        env = dict(os.environ)
        if slot.fallback_key_env_name or _gemini_vertex_adc_ready():
            prepared_home = _prepare_gemini_cli_env_auth_home(slot.slot)
        else:
            prepared_home = _prepare_gemini_cli_home(slot.slot)
        if prepared_home:
            env["HOME"] = prepared_home
            env["XDG_CONFIG_HOME"] = str(Path(prepared_home) / ".config")
            env["XDG_CACHE_HOME"] = str(Path(prepared_home) / ".cache")
            env["XDG_DATA_HOME"] = str(Path(prepared_home) / ".local" / "share")
            Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
            Path(env["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
            Path(env["XDG_DATA_HOME"]).mkdir(parents=True, exist_ok=True)
        if slot.fallback_key_env_name:
            api_key = _env_value(slot.fallback_key_env_name)
            if api_key:
                if slot.fallback_key_env_name == "EA_GEMINI_VORTEX_API_KEY":
                    env["GEMINI_API_KEY"] = api_key
                    env.pop("GOOGLE_API_KEY", None)
                elif slot.fallback_key_env_name == "GEMINI_API_KEY":
                    env["GEMINI_API_KEY"] = api_key
                    env.pop("GOOGLE_API_KEY", None)
                else:
                    env["GOOGLE_API_KEY"] = api_key
                    env.pop("GEMINI_API_KEY", None)
                    if slot.fallback_key_env_name.startswith(_GEMINI_FALLBACK_KEY_PREFIX):
                        env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        env.setdefault("UV_THREADPOOL_SIZE", _env_value("EA_GEMINI_VORTEX_UV_THREADPOOL_SIZE") or "1")
        return env

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        source_text = str(payload.get("normalized_text") or payload.get("source_text") or "").strip()
        if not source_text:
            raise ToolExecutionError("source_text_required")
        prompt_parts: list[str] = []
        generation_instruction = str(payload.get("generation_instruction") or payload.get("instructions") or "").strip()
        if generation_instruction:
            prompt_parts.append(generation_instruction)
        goal = str(payload.get("goal") or "").strip()
        if goal:
            prompt_parts.append(f"Goal: {goal}")
        response_schema = payload.get("response_schema_json")
        if isinstance(response_schema, dict) and response_schema:
            prompt_parts.append(
                "Return JSON only. Match this schema contract as closely as possible:\n"
                + json.dumps(response_schema, ensure_ascii=True)
            )
        else:
            prompt_parts.append("Return JSON only. No markdown fences, no commentary.")
        context_pack = payload.get("context_pack")
        if isinstance(context_pack, dict) and context_pack:
            prompt_parts.append("Context pack:\n" + json.dumps(context_pack, ensure_ascii=True))
        prompt_parts.append(source_text)
        return "\n\n".join(part for part in prompt_parts if part).strip()

    def _extract_response_text(self, stdout: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        raw = str(stdout or "").strip()
        if not raw:
            raise ToolExecutionError("gemini_vortex_empty_output")
        try:
            envelope = json.loads(raw)
        except Exception:
            return raw, {}, {}
        if not isinstance(envelope, dict):
            return raw, {}, {}
        response = str(envelope.get("response") or "").strip()
        stats = envelope.get("stats") if isinstance(envelope.get("stats"), dict) else {}
        if response:
            return response, envelope, stats
        return raw, envelope, stats

    def _parse_structured(self, text: str) -> tuple[str, dict[str, Any], str]:
        cleaned = _strip_fences(text)
        try:
            loaded = json.loads(cleaned)
        except Exception:
            return cleaned, {}, "text/plain"
        if isinstance(loaded, dict):
            return json.dumps(loaded, indent=2, ensure_ascii=True), loaded, "application/json"
        return json.dumps(loaded, indent=2, ensure_ascii=True), {"result": loaded}, "application/json"

    def _token_counts(self, stats: dict[str, Any]) -> tuple[int, int]:
        total_in = 0
        total_out = 0
        models = stats.get("models")
        if not isinstance(models, dict):
            return (0, 0)
        for row in models.values():
            if not isinstance(row, dict):
                continue
            tokens = row.get("tokens")
            if not isinstance(tokens, dict):
                continue
            total_in += int(tokens.get("input") or 0)
            total_out += int(tokens.get("candidates") or tokens.get("output") or 0)
        return (total_in, total_out)

    def execute(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        prompt = self._build_prompt(payload)
        model = _normalize_cli_model_name(str(payload.get("model") or self._default_model()).strip()) or self._default_model()
        principal_id = str((request.context_json or {}).get("principal_id") or payload.get("principal_id") or "").strip()
        spawn_pressure_active, spawn_pressure_detail = _spawn_pressure_active()
        if spawn_pressure_active:
            raise ToolExecutionError(f"gemini_vortex_{spawn_pressure_detail}")
        command = self._command_base() + [
            "-p",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            "yolo",
            "--skip-trust",
        ]
        if model:
            command.extend(["-m", model])
        ordered_slots = self._select_auth_slots(principal_id=principal_id)
        if not ordered_slots:
            auth_state, auth_detail = gemini_vortex_auth_state()
            raise ToolExecutionError(f"gemini_vortex_auth_missing:{auth_state}:{auth_detail}")
        completed: subprocess.CompletedProcess[str] | None = None
        selected_slot = ordered_slots[0]
        selected_lease = {
            "lease_holder": "",
            "lease_expires_at": "",
            "slot_owner": _slot_owner(selected_slot.slot),
            "quota_posture": _slot_quota_posture(selected_slot.slot) or "unknown",
        }
        failures: list[str] = []
        for slot in ordered_slots:
            try:
                command_env = self._command_env(slot)
                timeout_seconds = self._timeout_seconds(payload)
                attempt_count = max(1, _gemini_cli_spawn_retries() + 1)
                last_retry_detail = ""
                for attempt_index in range(1, attempt_count + 1):
                    try:
                        with _acquire_gemini_cli_slot(timeout_seconds=timeout_seconds):
                            completed = subprocess.run(
                                command,
                                check=True,
                                text=True,
                                capture_output=True,
                                timeout=timeout_seconds,
                                env=command_env,
                            )
                        break
                    except subprocess.CalledProcessError as exc:
                        detail = _clean_cli_failure_detail(exc.stderr or "")
                        if detail == "gemini_vortex_failed":
                            detail = _clean_cli_failure_detail(exc.stdout or "")
                        if attempt_index < attempt_count and _is_retryable_cli_failure_detail(detail):
                            last_retry_detail = detail
                            time.sleep(_gemini_cli_retry_delay_seconds(attempt_index))
                            continue
                        if _is_retryable_cli_failure_detail(detail):
                            _record_spawn_pressure(detail)
                        raise
                    except OSError as exc:
                        if attempt_index < attempt_count and _is_retryable_spawn_oserror(exc):
                            last_retry_detail = str(exc).strip() or exc.__class__.__name__
                            time.sleep(_gemini_cli_retry_delay_seconds(attempt_index))
                            continue
                        if _is_retryable_spawn_oserror(exc):
                            _record_spawn_pressure(str(exc).strip() or exc.__class__.__name__)
                        raise
                if completed is None:
                    retry_detail = last_retry_detail or "gemini_vortex_failed"
                    if _is_retryable_cli_failure_detail(retry_detail):
                        _record_spawn_pressure(retry_detail)
                    raise ToolExecutionError(f"gemini_vortex_failed:{retry_detail[:240]}")
                selected_slot = slot
                selected_lease = self._record_slot_usage(slot, principal_id=principal_id, success=True)
                _clear_spawn_pressure_state()
                break
            except FileNotFoundError as exc:
                raise ToolExecutionError("gemini_vortex_cli_missing") from exc
            except subprocess.TimeoutExpired as exc:
                raise ToolExecutionError("gemini_vortex_timeout") from exc
            except subprocess.CalledProcessError as exc:
                detail = _clean_cli_failure_detail(exc.stderr or "")
                if detail == "gemini_vortex_failed":
                    detail = _clean_cli_failure_detail(exc.stdout or "")
                self._record_slot_usage(slot, principal_id=principal_id, success=False, detail=detail)
                failures.append(f"{slot.account_name}:{detail[:160]}")
            except OSError as exc:
                detail = str(exc).strip() or exc.__class__.__name__
                self._record_slot_usage(slot, principal_id=principal_id, success=False, detail=detail)
                failures.append(f"{slot.account_name}:{detail[:160]}")
            except ToolExecutionError as exc:
                detail = str(exc).strip() or "gemini_vortex_failed"
                self._record_slot_usage(slot, principal_id=principal_id, success=False, detail=detail)
                failures.append(f"{slot.account_name}:{detail[:160]}")
        if completed is None:
            summary = " | ".join(failures) if failures else "gemini_vortex_failed"
            auth_state, auth_detail = gemini_vortex_auth_state()
            if auth_state == "missing" and selected_slot.account_name == _DEFAULT_GEMINI_AUTH_ACCOUNT:
                raise ToolExecutionError(f"gemini_vortex_auth_missing:{auth_state}:{auth_detail}")
            raise ToolExecutionError(f"gemini_vortex_failed:{summary[:400]}")
        response_text, envelope, stats = self._extract_response_text(completed.stdout or "")
        normalized_text, structured_output_json, mime_type = self._parse_structured(response_text)
        tokens_in, tokens_out = self._token_counts(stats)
        action_kind = str(request.action_kind or "content.generate") or "content.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"gemini-vortex:{uuid.uuid4()}",
            output_json={
                "normalized_text": normalized_text,
                "structured_output_json": structured_output_json,
                "preview_text": _preview_text(normalized_text),
                "mime_type": mime_type,
                "model": model,
                "provider_key_slot": selected_slot.slot,
                "provider_account_name": selected_slot.account_name,
                "lease_holder": selected_lease["lease_holder"],
                "lease_expires_at": selected_lease["lease_expires_at"],
                "slot_owner": selected_lease["slot_owner"],
                "quota_posture": selected_lease["quota_posture"],
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "model": model,
                "prompt_length": len(prompt),
                "mime_type": mime_type,
                "structured": bool(structured_output_json),
                "tool_version": definition.version,
                "provider_key_slot": selected_slot.slot,
                "provider_account_name": selected_slot.account_name,
                "lease_holder": selected_lease["lease_holder"],
                "lease_expires_at": selected_lease["lease_expires_at"],
                "slot_owner": selected_lease["slot_owner"],
                "quota_posture": selected_lease["quota_posture"],
                "selection_mode": _gemini_selection_mode(),
                "response_envelope_keys": sorted(envelope.keys()) if isinstance(envelope, dict) else [],
            },
            model_name=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        )
