#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EA_API_CONTAINER = os.environ.get("CODEXEA_EA_API_CONTAINER", "ea-api").strip() or "ea-api"


def _git_root_from(path: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    root = completed.stdout.strip()
    return Path(root).expanduser() if root else None


def _candidate_roots() -> list[Path]:
    candidates: list[Path] = []
    for name in ("CODEXEA_SOURCE_ROOT", "CODEXEA_REPO_ROOT", "CODEXEA_FLEET_ROOT"):
        raw = str(os.environ.get(name) or "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    cwd_git_root = _git_root_from(Path.cwd())
    if cwd_git_root is not None:
        candidates.append(cwd_git_root)
    candidates.extend([ROOT, ROOT.parent])

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _default_app_root() -> Path:
    for root in _candidate_roots():
        nested_app = root / "ea"
        if (nested_app / "app" / "container.py").is_file():
            return nested_app
        if (root / "app" / "container.py").is_file():
            return root
    return ROOT / "ea"


APP_ROOT = Path(os.environ.get("CODEXEA_EA_APP_ROOT") or _default_app_root()).expanduser()


def _ledger_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = str(os.environ.get("CODEXEA_ONEMIN_LEDGER_PATHS") or "").strip()
    if explicit:
        for raw in re.split(r"[:\n]", explicit):
            raw = raw.strip()
            if raw:
                candidates.append(Path(raw).expanduser())
    for root in _candidate_roots():
        candidates.extend(
            [
                root / "config" / "onemin_api_keys.local.json",
                root / "config" / "onemin_api_keys.json",
            ]
        )

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(float(str(os.environ.get(name) or default)))
    except Exception:
        value = int(default)
    value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, "") or "").strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "on", "enabled", "enable", "active"}


def _first_non_empty(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _redact_runtime_text(text: object) -> str:
    rendered = str(text or "")
    if not rendered:
        return ""
    for key, value in os.environ.items():
        normalized = key.upper()
        if not value or len(value) < 8:
            continue
        if any(marker in normalized for marker in ("TOKEN", "API_KEY", "PASSWORD", "SECRET")):
            rendered = rendered.replace(value, "[REDACTED]")
    rendered = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", rendered)
    rendered = re.sub(
        r"CODEXEA_ROUTE_REQUEST_JSON=[^\s,\]]+",
        "CODEXEA_ROUTE_REQUEST_JSON=[REDACTED]",
        rendered,
    )
    return rendered


def _backend_error_summary(error: object, *, limit: int = 240) -> str:
    text = " ".join(_redact_runtime_text(str(error or "")).split())
    if not text:
        return "unknown_error"
    if "Traceback (most recent call last)" in text:
        prefix = text.split(":Traceback", 1)[0].strip(": ")
        match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", text)
        reason = match.group(1) if match else "runtime_traceback"
        return f"{prefix}:{reason}" if prefix else reason
    if len(text) <= max(1, limit):
        return text
    return f"{text[: max(1, limit) - 3].rstrip()}..."


DEFAULT_PROBE_LIMIT = _env_int("CODEXEA_ONEMIN_PROBE_LIMIT", 8, minimum=0)
DEFAULT_TIMEOUT_SECONDS = _env_int("CODEXEA_ONEMIN_TIMEOUT_SECONDS", 300, minimum=1, maximum=1800)
DEFAULT_COOLDOWN_SECONDS = _env_int("CODEXEA_ONEMIN_PROBE_COOLDOWN_DEFAULT_SECONDS", 300, minimum=1, maximum=86400)
MAX_COOLDOWN_SECONDS = _env_int("CODEXEA_ONEMIN_PROBE_COOLDOWN_MAX_SECONDS", 1800, minimum=1, maximum=86400)
MAX_COOLDOWN_RECORDS = _env_int("CODEXEA_ONEMIN_PROBE_COOLDOWN_MAX_RECORDS", 200, minimum=1, maximum=10000)
DEFAULT_ONEMIN_ROUTE_BACKEND_ORDER = os.environ.get(
    "CODEXEA_ONEMIN_ROUTE_BACKEND_ORDER",
    "docker,local_python,http_runtime_telemetry",
)

CONTAINER_SCRIPT = r"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from app.api.routes import providers as providers_route
from app.api.routes.responses import invalidate_provider_health_snapshot_cache, remember_provider_health_snapshot_cache
from app.container import build_container
from app.services import responses_upstream as upstream


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_int(value: object, *, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except Exception:
        return default


def _selected_rows(rows: list[dict[str, object]], labels: list[str], probe_limit: int) -> list[dict[str, object]]:
    normalized = {str(item or "").strip() for item in labels if str(item or "").strip()}
    if normalized:
        return [row for row in rows if str(row.get("account_name") or "").strip() in normalized]
    if probe_limit > 0:
        return rows[:probe_limit]
    return rows


def _probe_one(row: dict[str, object], *, timeout_seconds: int) -> dict[str, object]:
    account_name = str(row.get("account_name") or "").strip()
    owner_email = str(row.get("owner_email") or "").strip()
    if not account_name:
        return {"account_name": "", "ok": False, "error": "account_name_missing"}
    if not owner_email:
        return {"account_name": account_name, "ok": False, "error": "owner_email_missing"}
    try:
        billing_result, _member_result = providers_route._refresh_onemin_api_account_compat(
            account_name=account_name,
            owner_email=owner_email,
            include_members=False,
            timeout_seconds=timeout_seconds,
            login_email=owner_email,
            login_password=providers_route._onemin_password(),
            proxy_retry_offset=0,
        )
        return {
            "account_name": account_name,
            "owner_email": owner_email,
            "ok": True,
            "remaining_credits": billing_result.get("remaining_credits"),
            "next_topup_at": billing_result.get("next_topup_at"),
        }
    except Exception as exc:
        return {
            "account_name": account_name,
            "owner_email": owner_email,
            "ok": False,
            "error": str(exc),
        }


def _slot_rows_from_accounts(accounts: list[object], provider_slots: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        credentials = [dict(item) for item in (account.get("credentials") or []) if isinstance(item, dict)]
        if not credentials:
            credentials = [{}]
        for credential in credentials:
            slot_env_name = str(
                credential.get("secret_env_name")
                or credential.get("slot_name")
                or account.get("account_id")
                or account.get("account_label")
                or ""
            ).strip()
            if not slot_env_name:
                continue
            free_credits = account.get("live_remaining_credits")
            if free_credits in (None, ""):
                free_credits = credential.get("remaining_credits")
            if free_credits in (None, ""):
                free_credits = account.get("remaining_credits")
            rows.append(
                {
                    "account_name": str(account.get("account_id") or account.get("account_label") or slot_env_name).strip(),
                    "slot_env_name": slot_env_name,
                    "secret_env_name": slot_env_name,
                    "slot_name": str(credential.get("slot_name") or "").strip(),
                    "state": str(credential.get("state") or account.get("status") or "").strip().lower() or "ready",
                    "slot_role": str(credential.get("active_role") or "").strip().lower() or "reserve",
                    "free_credits": free_credits,
                    "estimated_remaining_credits": account.get("estimated_remaining_credits"),
                    "remaining_credits": credential.get("remaining_credits")
                    if credential.get("remaining_credits") not in (None, "")
                    else account.get("remaining_credits"),
                    "detail": str(credential.get("last_error") or "").strip(),
                }
            )
    if rows:
        return rows
    return provider_slots


request = json.loads(os.environ["CODEXEA_ROUTE_REQUEST_JSON"])
container = build_container()
refresh_requested = bool(request.get("refresh"))
refresh_payload = None
probe_rows = [dict(item) for item in (request.get("account_rows") or []) if isinstance(item, dict)]
probe_rows = _selected_rows(
    probe_rows,
    list(request.get("account_labels") or []),
    _as_int(request.get("probe_limit"), default=0),
)
probe_enabled = bool(request.get("probe"))
probe_mode = str(request.get("probe_mode") or "off").strip() or "off"
probe_summary: dict[str, Any] = {
    "requested": probe_enabled,
    "mode": probe_mode,
    "partial": bool(request.get("probe_limit")),
    "attempted_count": 0,
    "ok_count": 0,
    "error_count": 0,
    "errors": [],
    "results": [],
    "last_probe_at": None,
}

if probe_enabled and probe_rows:
    timeout_seconds = max(5, _as_int(request.get("timeout_seconds"), default=300))
    max_workers = max(1, min(8, _as_int(request.get("max_workers"), default=4)))
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_probe_one, row, timeout_seconds=timeout_seconds) for row in probe_rows]
        for future in as_completed(futures):
            results.append(dict(future.result()))
    ok_rows = [row for row in results if bool(row.get("ok"))]
    error_rows = [row for row in results if not bool(row.get("ok"))]
    probe_summary = {
        "requested": True,
        "mode": probe_mode,
        "partial": bool(request.get("probe_limit")),
        "attempted_count": len(probe_rows),
        "ok_count": len(ok_rows),
        "error_count": len(error_rows),
        "errors": error_rows[:20],
        "results": results,
        "last_probe_at": _utc_now(),
    }
    invalidate_provider_health_snapshot_cache()

if refresh_requested:
    try:
        from app.runner import _run_scheduler_onemin_billing_refresh

        import logging

        refresh_payload = _run_scheduler_onemin_billing_refresh(container=container, log=logging.getLogger("ea-codexea-route"))
    except Exception as exc:
        refresh_payload = {"ran": False, "throttled": False, "throttle_seconds_remaining": 0.0, "throttle_reason": "", "browseract_attempted": 0, "browseract_refreshed": 0, "member_reconciled": 0, "api_attempted": 0, "api_rate_limited": False, "api_recovered": 0, "browseract_failed": 0, "errors": 1, "error": str(exc)}

provider_health = upstream._provider_health_report()
remember_provider_health_snapshot_cache(lightweight=False, payload=provider_health)
remember_provider_health_snapshot_cache(
    lightweight=True,
    payload=upstream._provider_health_report(lightweight=True),
)
aggregate = container.onemin_manager.aggregate_snapshot(
    provider_health=provider_health,
    binding_rows=[],
    principal_id="",
)
actual = container.onemin_manager.actual_credits_snapshot(
    provider_health=provider_health,
    binding_rows=[],
    principal_id="",
)
providers = provider_health.get("providers") if isinstance(provider_health.get("providers"), dict) else {}
onemin = providers.get("onemin") if isinstance(providers.get("onemin"), dict) else {}
provider_slots = [dict(item) for item in (onemin.get("slots") or []) if isinstance(item, dict)]
payload = {
    **aggregate,
    "provider_key": "onemin",
    "generated_at": _utc_now(),
    "source": str(os.environ.get("CODEXEA_ROUTE_SOURCE") or "").strip() or "unknown",
    "probe": probe_summary,
    "actual_credits": actual,
    "onemin_refresh": refresh_payload,
    "slots": _slot_rows_from_accounts(list(aggregate.get("accounts") or []), provider_slots),
}
print(json.dumps(payload))
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CodexEA route helper.")
    parser.add_argument("--onemin-aggregate", action="store_true", help="Return the live 1min aggregate payload.")
    parser.add_argument("--onemin-refresh", action="store_true", help="Run a scheduler-side 1min billing refresh before returning the payload.")
    parser.add_argument("--probe-all", action="store_true", help="Attempt a full live refresh before returning the aggregate.")
    parser.add_argument(
        "--probe-best-effort",
        action="store_true",
        help="Attempt a bounded live refresh before returning the aggregate.",
    )
    parser.add_argument("--billing", action="store_true", help="Accepted for compatibility; the aggregate already includes billing-derived fields.")
    parser.add_argument("--summary-json", action="store_true", help="Print bounded summary JSON without the full account corpus.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    parser.add_argument(
        "--account-label",
        action="append",
        dest="account_labels",
        default=[],
        help="Restrict live probing to specific ONEMIN_AI_API_KEY[_FALLBACK_n] labels.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument(
        "--probe-limit",
        type=int,
        default=DEFAULT_PROBE_LIMIT,
        help="Maximum number of accounts to refresh during best-effort live probing.",
    )
    parser.add_argument(
        "--telemetry-answer",
        nargs=argparse.REMAINDER,
        help="Accepted for CodexEA compatibility; exit 10 to fall through to normal handling.",
    )
    parser.add_argument("--send-telegram", action="store_true", help="Send a compact result summary to Telegram after a successful refresh.")
    parser.add_argument("--telegram-chat-id", help="Telegram chat_id used for optional result delivery.")
    parser.add_argument("--telegram-bot-token", help="Telegram bot token used for optional result delivery.")
    parser.add_argument("--telegram-timeout-seconds", type=int, default=30)
    return parser.parse_args()


def _route_source_sort_key(row: dict[str, object]) -> tuple[int, int, str]:
    account_name = str(row.get("account_name") or "").strip()
    if account_name == "ONEMIN_AI_API_KEY":
        return (0, 0, account_name)
    prefix = "ONEMIN_AI_API_KEY_FALLBACK_"
    if account_name.startswith(prefix):
        suffix = account_name[len(prefix):]
        if suffix.isdigit():
            return (1, int(suffix), account_name)
    return (2, 0, account_name)


def _fallback_number_from_slot(raw: object) -> int | None:
    normalized = str(raw or "").strip()
    env_prefix = "ONEMIN_AI_API_KEY_FALLBACK_"
    if normalized.startswith(env_prefix):
        suffix = normalized[len(env_prefix):]
        if suffix.isdigit() and int(suffix) >= 1:
            return int(suffix)
    match = re.fullmatch(r"fallback_?(\d+)", normalized.lower().replace(" ", "_").replace("-", "_"))
    if match is None:
        return None
    try:
        number = int(match.group(1))
    except Exception:
        return None
    return number if number >= 1 else None


def _normalize_manifest_account_rows(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("slots"), list):
            items = payload.get("slots") or []
        elif isinstance(payload.get("keys"), list):
            items = payload.get("keys") or []
        elif isinstance(payload.get("accounts"), list):
            items = payload.get("accounts") or []
        else:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    rows: list[dict[str, object]] = []
    seen_account_names: set[str] = set()
    next_fallback = 1
    for item in items:
        slot = ""
        account_name = ""
        owner_email = ""
        owner_name = ""
        if isinstance(item, str):
            # String manifests are secret-only pools. They still need stable probe labels.
            if not str(item or "").strip():
                continue
        elif isinstance(item, dict):
            slot = str(item.get("slot") or item.get("slot_name") or "").strip()
            account_name = str(item.get("account_name") or item.get("name") or "").strip()
            owner_email = str(item.get("owner_email") or item.get("email") or "").strip()
            owner_name = str(item.get("owner_name") or item.get("display_name") or "").strip()
        else:
            continue

        slot_number = _fallback_number_from_slot(slot) or _fallback_number_from_slot(account_name)
        if not account_name:
            if slot.lower() == "primary":
                account_name = "ONEMIN_AI_API_KEY"
            elif slot_number is not None:
                account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{slot_number}"
            else:
                while f"ONEMIN_AI_API_KEY_FALLBACK_{next_fallback}" in seen_account_names:
                    next_fallback += 1
                account_name = f"ONEMIN_AI_API_KEY_FALLBACK_{next_fallback}"
                next_fallback += 1

        if account_name in seen_account_names:
            continue
        seen_account_names.add(account_name)

        normalized_slot = "primary" if account_name == "ONEMIN_AI_API_KEY" else ""
        if not normalized_slot:
            derived_number = _fallback_number_from_slot(slot) or _fallback_number_from_slot(account_name)
            normalized_slot = f"fallback_{derived_number}" if derived_number is not None else account_name.lower()
        rows.append(
            {
                "slot": normalized_slot,
                "account_name": account_name,
                "owner_email": owner_email,
                "owner_name": owner_name,
            }
        )
    rows.sort(key=_route_source_sort_key)
    return rows


def _load_onemin_account_rows() -> list[dict[str, object]]:
    for candidate in _ledger_candidates():
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalized = _normalize_manifest_account_rows(payload)
        if normalized:
            return normalized
    return []


def _args_probe_mode(args: argparse.Namespace) -> str:
    if bool(args.probe_all):
        return "all"
    if bool(args.probe_best_effort):
        return "best_effort"
    return "off"


def _cooldown_now_epoch() -> float:
    return time.time()


def _cooldown_iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamped_cooldown_seconds(value: object, *, default: int = DEFAULT_COOLDOWN_SECONDS) -> int:
    try:
        seconds = int(float(str(value)))
    except Exception:
        seconds = int(default)
    return max(1, min(max(1, int(MAX_COOLDOWN_SECONDS)), seconds))


def _onemin_probe_cooldown_path() -> Path:
    explicit = str(os.environ.get("CODEXEA_ONEMIN_PROBE_COOLDOWN_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    state_dir = str(os.environ.get("CODEXEA_STATE_DIR") or "").strip()
    if state_dir:
        return Path(state_dir).expanduser() / "onemin_probe_cooldowns.json"
    cache_dir = str(os.environ.get("XDG_CACHE_HOME") or "").strip()
    if cache_dir:
        return Path(cache_dir).expanduser() / "codexea" / "onemin_probe_cooldowns.json"
    return Path.home() / ".cache" / "codexea" / "onemin_probe_cooldowns.json"


def _load_onemin_probe_cooldowns(*, now_epoch: float | None = None) -> dict[str, dict[str, object]]:
    now = _cooldown_now_epoch() if now_epoch is None else float(now_epoch)
    path = _onemin_probe_cooldown_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = payload.get("cooldowns") if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        return {}
    active: dict[str, dict[str, object]] = {}
    for raw_key, raw_value in rows.items():
        if not isinstance(raw_value, dict):
            continue
        key = str(raw_key or raw_value.get("account_name") or "").strip()
        if not key:
            continue
        try:
            until = float(raw_value.get("cooldown_until_epoch") or 0.0)
        except Exception:
            until = 0.0
        if until <= now:
            continue
        row = dict(raw_value)
        row["account_name"] = str(row.get("account_name") or key).strip()
        row["cooldown_until_epoch"] = until
        active[key] = row
    return active


def _write_onemin_probe_cooldowns(cooldowns: dict[str, dict[str, object]]) -> None:
    path = _onemin_probe_cooldown_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        sorted_rows = sorted(
            cooldowns.items(),
            key=lambda item: float(item[1].get("cooldown_until_epoch") or 0.0),
            reverse=True,
        )[: max(1, int(MAX_COOLDOWN_RECORDS))]
        payload = {
            "version": 1,
            "updated_at": _cooldown_iso(_cooldown_now_epoch()),
            "cooldowns": {key: value for key, value in sorted_rows},
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        return


def _retry_after_seconds_from_text(text: object) -> int:
    body = str(text or "")
    if not body:
        return 0
    for pattern in (
        r'"retryAfter"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?',
        r"\bretry[_ -]?after\b[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)",
        r"\btry again after\b[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)",
    ):
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return _clamped_cooldown_seconds(match.group(1))
    return 0


def _cooldown_seconds_for_probe_error(error: object) -> int:
    text = str(error or "")
    if not text:
        return 0
    retry_after = _retry_after_seconds_from_text(text)
    if retry_after > 0:
        return retry_after
    lowered = text.lower()
    if "429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
        return _clamped_cooldown_seconds(DEFAULT_COOLDOWN_SECONDS)
    return 0


def _cooldown_public_row(row: dict[str, object], *, now_epoch: float | None = None) -> dict[str, object]:
    now = _cooldown_now_epoch() if now_epoch is None else float(now_epoch)
    until = float(row.get("cooldown_until_epoch") or 0.0)
    return {
        "account_name": row.get("account_name"),
        "retry_after_seconds": row.get("retry_after_seconds"),
        "cooldown_remaining_seconds": max(0, int(round(until - now))),
        "cooldown_until": row.get("cooldown_until") or _cooldown_iso(until),
        "reason": row.get("reason"),
    }


def _apply_onemin_probe_cooldowns(request: dict[str, Any]) -> dict[str, object]:
    if not bool(request.get("probe")):
        return {"skipped": [], "active_count": 0}
    now = _cooldown_now_epoch()
    cooldowns = _load_onemin_probe_cooldowns(now_epoch=now)
    rows = [dict(item) for item in (request.get("account_rows") or []) if isinstance(item, dict)]
    kept: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for row in rows:
        account_name = str(row.get("account_name") or "").strip()
        cooldown = cooldowns.get(account_name) if account_name else None
        if cooldown:
            skipped.append(_cooldown_public_row(cooldown, now_epoch=now))
            continue
        kept.append(row)
    request["account_rows"] = kept
    return {
        "skipped": skipped[:20],
        "skipped_count": len(skipped),
        "active_count": len(cooldowns),
    }


def _record_onemin_probe_cooldowns_from_payload(payload: dict[str, Any]) -> list[dict[str, object]]:
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    if not probe:
        return []
    rows: list[dict[str, object]] = []
    seen_accounts: set[str] = set()
    for source_rows in (probe.get("errors") or [], probe.get("results") or []):
        for item in source_rows:
            if not isinstance(item, dict):
                continue
            account_name = str(item.get("account_name") or "").strip()
            if not account_name or account_name in seen_accounts:
                continue
            seen_accounts.add(account_name)
            rows.append(dict(item))
    now = _cooldown_now_epoch()
    active = _load_onemin_probe_cooldowns(now_epoch=now)
    new_rows: list[dict[str, object]] = []
    for row in rows:
        seconds = _cooldown_seconds_for_probe_error(row.get("error"))
        if seconds <= 0:
            continue
        account_name = str(row.get("account_name") or "").strip()
        if not account_name:
            continue
        until = now + float(seconds)
        record = {
            "account_name": account_name,
            "retry_after_seconds": seconds,
            "cooldown_until_epoch": until,
            "cooldown_until": _cooldown_iso(until),
            "reason": str(row.get("error") or "").strip()[:240],
            "last_seen_at": _cooldown_iso(now),
        }
        previous = active.get(account_name)
        if previous and float(previous.get("cooldown_until_epoch") or 0.0) > until:
            record = dict(previous)
        active[account_name] = record
        new_rows.append(_cooldown_public_row(record, now_epoch=now))
    if new_rows:
        _write_onemin_probe_cooldowns(active)
    return new_rows[:20]


def _finalize_onemin_probe_payload(payload: dict[str, Any], *, cooldown_state: dict[str, object]) -> dict[str, Any]:
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    if not probe:
        return payload
    new_rows = _record_onemin_probe_cooldowns_from_payload(payload)
    skipped = [dict(item) for item in (cooldown_state.get("skipped") or []) if isinstance(item, dict)]
    if skipped or new_rows:
        cooldown_summary = {
            "active_count": cooldown_state.get("active_count", 0),
            "skipped_count": cooldown_state.get("skipped_count", len(skipped)),
            "new_count": len(new_rows),
            "skipped": skipped,
            "new": new_rows,
        }
        probe["cooldown"] = cooldown_summary
        probe["cooldown_skipped_count"] = cooldown_summary["skipped_count"]
    payload["probe"] = probe
    return payload


def _build_route_request(args: argparse.Namespace, *, account_rows: list[dict[str, object]] | None = None) -> dict[str, Any]:
    account_labels = [str(item or "").strip() for item in (args.account_labels or []) if str(item or "").strip()]
    probe_mode = _args_probe_mode(args)
    probe_limit = 0
    if probe_mode == "best_effort" and not account_labels:
        probe_limit = max(0, int(args.probe_limit))
    resolved_account_rows: list[dict[str, object]] = []
    if probe_mode != "off":
        resolved_account_rows = list(account_rows if account_rows is not None else _load_onemin_account_rows())
    return {
        "probe": probe_mode != "off",
        "probe_mode": probe_mode,
        "refresh": bool(args.onemin_refresh),
        "timeout_seconds": int(args.timeout_seconds),
        "max_workers": int(args.max_workers),
        "probe_limit": probe_limit,
        "account_labels": account_labels,
        "account_rows": resolved_account_rows,
    }


def _command_timeout_seconds(args: argparse.Namespace, *, probe_mode: str) -> int:
    if probe_mode == "all":
        return max(60, int(args.timeout_seconds) * 4)
    if probe_mode == "best_effort":
        return max(30, int(args.timeout_seconds) * max(1, int(args.max_workers)) * 2)
    return max(45, int(args.timeout_seconds))


def _docker_backend_command(request: dict[str, Any]) -> list[str]:
    return [
        "docker",
        "exec",
        "-i",
        "-e",
        f"CODEXEA_ROUTE_REQUEST_JSON={json.dumps(request, separators=(',', ':'))}",
        "-e",
        "CODEXEA_ROUTE_SOURCE=ea_api_container",
        DEFAULT_EA_API_CONTAINER,
        "python",
        "-c",
        CONTAINER_SCRIPT,
    ]


def _local_app_tree_available() -> bool:
    return (APP_ROOT / "app" / "container.py").is_file() and (APP_ROOT / "app" / "api" / "routes").is_dir()


def _local_backend_command(request: dict[str, Any]) -> list[str]:
    python_bin = sys.executable or shutil.which("python3") or "python3"
    return [
        python_bin,
        "-c",
        CONTAINER_SCRIPT,
    ]


def _append_query(url: str, params: dict[str, str]) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value != "")
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def _status_url_to_runtime_telemetry_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or ""
    if path.endswith("/v1/codex/status"):
        path = path[: -len("/v1/codex/status")] + "/v1/runtime/lanes/telemetry"
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.query,
            parsed.fragment,
        )
    )


def _runtime_path_api_root(path: str) -> str:
    if not path:
        return ""
    if "/v1/" in path:
        return path.split("/v1/", 1)[0].rstrip("/")
    trimmed = path.rsplit("/", 1)[0]
    return trimmed.rstrip("/")


def _runtime_telemetry_url_to_provider_url(telemetry_url: str, endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(telemetry_url)
    api_root = _runtime_path_api_root(parsed.path or "")
    base = urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{api_root}/v1/providers/onemin/{endpoint}",
            "",
            "",
        )
    )
    return base


def _parse_billing_refresh_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ran": not bool(payload.get("refresh_throttled")),
        "throttled": bool(payload.get("refresh_throttled")),
        "throttle_seconds_remaining": payload.get("refresh_throttle_seconds_remaining"),
        "throttle_reason": payload.get("note") or "",
        "browseract_attempted": payload.get("billing_refresh_count"),
        "browseract_refreshed": payload.get("billing_refresh_count"),
        "member_reconciled": payload.get("member_reconciliation_count"),
        "api_attempted": payload.get("api_billing_refresh_count"),
        "api_rate_limited": bool(payload.get("api_rate_limited")),
        "api_recovered": payload.get("api_billing_refresh_count"),
        "errors": len(list(payload.get("errors") or [])),
    }


def _route_backend_order_preference() -> list[str]:
    raw = str(DEFAULT_ONEMIN_ROUTE_BACKEND_ORDER or "").strip()
    names = [item.strip().lower().replace("-", "_") for item in raw.split(",") if item.strip()]
    if not names:
        names = ["local_python", "docker", "http_runtime_telemetry"]
    normalized: list[str] = []
    allowed = {"local_python", "http_runtime_telemetry", "docker", "http", "ea_api_container"}
    for name in names:
        if name == "local":
            name = "local_python"
        if name == "runtime_telemetry":
            name = "http_runtime_telemetry"
        if name == "http":
            name = "http_runtime_telemetry"
        if name == "eaapi":
            name = "ea_api_container"
        if name not in allowed:
            continue
        if name not in normalized:
            normalized.append(name)
    if not normalized:
        normalized = ["local_python", "docker", "http_runtime_telemetry"]
    return normalized


def _http_backend_urls() -> list[str]:
    raw_candidates: list[str] = []
    explicit_telemetry_url = str(os.environ.get("CODEXEA_RUNTIME_TELEMETRY_URL") or "").strip()
    if explicit_telemetry_url:
        raw_candidates.append(explicit_telemetry_url)
    status_url = str(os.environ.get("CODEXEA_STATUS_URL") or "").strip()
    if status_url:
        raw_candidates.append(_status_url_to_runtime_telemetry_url(status_url))
    base_url = str(os.environ.get("EA_MCP_BASE_URL") or os.environ.get("EA_BASE_URL") or "").strip()
    if base_url:
        raw_candidates.append(f"{base_url.rstrip('/')}/v1/runtime/lanes/telemetry")

    urls: list[str] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        if not candidate:
            continue
        url = _append_query(candidate, {"window": "7d"})
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _http_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-EA-Principal-ID": str(os.environ.get("EA_MCP_PRINCIPAL_ID") or os.environ.get("EA_PRINCIPAL_ID") or "archon-codex-ea"),
    }
    token = str(os.environ.get("EA_MCP_API_TOKEN") or os.environ.get("EA_API_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-EA-Api-Token"] = token
        headers["X-API-Token"] = token
    return headers


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_payload_to_route_payload(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    aggregate = dict(payload.get("onemin_aggregate") or {})
    billing = dict(payload.get("onemin_billing_aggregate") or {})
    sum_free_credits = _first_non_empty(
        aggregate.get("sum_free_credits"),
        aggregate.get("global_estimated_free_credits_total"),
        billing.get("sum_free_credits"),
    )
    actual_free_credits = _first_non_empty(
        billing.get("actual_free_credits_total"),
        billing.get("sum_free_credits"),
        aggregate.get("actual_free_credits_total"),
        aggregate.get("global_actual_remaining_credits_total"),
    )
    live_remaining_credits = _first_non_empty(
        aggregate.get("live_remaining_credits_total"),
        aggregate.get("global_live_remaining_credits_total"),
        billing.get("live_remaining_credits_total"),
        aggregate.get("sum_free_credits"),
    )
    current_pace_burn = _first_non_empty(
        billing.get("current_pace_burn_credits_per_hour"),
        aggregate.get("current_pace_burn_credits_per_hour"),
    )
    hours_remaining = _first_non_empty(
        aggregate.get("hours_remaining_at_current_pace"),
        aggregate.get("global_estimated_hours_remaining_at_current_pace"),
        billing.get("hours_remaining_at_current_pace"),
    )
    return {
        **aggregate,
        "provider_key": "onemin",
        "generated_at": payload.get("generated_at") or _utc_now(),
        "source": source,
        "probe": {
            "requested": False,
            "mode": "off",
            "partial": False,
            "attempted_count": 0,
            "ok_count": 0,
            "error_count": 0,
            "errors": [],
            "results": [],
            "last_probe_at": None,
        },
        "actual_credits": billing,
        "slots": list(billing.get("slots") or aggregate.get("slots") or []),
        "sum_free_credits": sum_free_credits,
        "actual_free_credits_total": actual_free_credits,
        "actual_remaining_percent_total": billing.get("remaining_percent_total"),
        "live_remaining_credits_total": live_remaining_credits,
        "current_burn_credits_per_hour": current_pace_burn,
        "hours_remaining_at_current_pace": hours_remaining,
        "basis_summary": billing.get("basis_summary") or aggregate.get("basis_summary"),
    }


def _empty_onemin_aggregate(payload: dict[str, Any]) -> bool:
    zero_values = (0, 0.0, "0", "0.0", None, "")
    if payload.get("sum_free_credits") not in zero_values:
        return False
    if payload.get("live_remaining_credits_total") not in zero_values:
        return False
    if payload.get("actual_free_credits_total") not in zero_values:
        return False
    try:
        account_count = int(float(str(payload.get("account_count") or 0)))
    except Exception:
        account_count = 0
    if account_count > 0:
        return False
    if payload.get("slots"):
        return False
    return True


def _run_http_backend(*, request: dict[str, Any], timeout_seconds: int, backend_name: str) -> dict[str, Any]:
    if bool(request.get("probe")):
        raise RuntimeError(f"{backend_name}_does_not_support_live_probe")
    errors: list[str] = []
    for url in _http_backend_urls():
        if bool(request.get("refresh")):
            refresh_url = _runtime_telemetry_url_to_provider_url(url, "billing-refresh")
            refresh_body = json.dumps({"include_members": True, "include_provider_api": True}, separators=(",", ":")).encode(
                "utf-8"
            )
            headers = _http_headers()
            headers["Content-Type"] = "application/json"
            http_request = urllib.request.Request(
                refresh_url,
                data=refresh_body,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                    raw_payload = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
                errors.append(f"{refresh_url}:{exc.code}:{detail[:240]}")
                continue
            except Exception as exc:
                errors.append(f"{refresh_url}:{exc}")
                continue
            try:
                payload = json.loads(raw_payload or "{}")
            except json.JSONDecodeError as exc:
                errors.append(f"{refresh_url}:invalid_json:{raw_payload[:240]}")
                continue
            if not isinstance(payload, dict):
                errors.append(f"{refresh_url}:invalid_payload")
                continue
            mapped_payload = {
                "onemin_aggregate": dict(payload.get("aggregate_snapshot") or {}),
                "onemin_billing_aggregate": dict(payload.get("actual_credits_snapshot") or {}),
            }
            route_payload = _http_payload_to_route_payload(mapped_payload, source=backend_name)
            route_payload["onemin_refresh"] = _parse_billing_refresh_response(payload)
            return route_payload
        http_request = urllib.request.Request(url, headers=_http_headers(), method="GET")
        try:
            with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                raw_payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            errors.append(f"{url}:{exc.code}:{detail[:240]}")
            continue
        except Exception as exc:
            errors.append(f"{url}:{exc}")
            continue
        try:
            payload = json.loads(raw_payload or "{}")
        except json.JSONDecodeError as exc:
            errors.append(f"{url}:invalid_json:{raw_payload[:240]}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{url}:invalid_payload")
            continue
        route_payload = _http_payload_to_route_payload(payload, source=backend_name)
        if route_payload.get("sum_free_credits") in (None, "") and route_payload.get("actual_free_credits_total") in (None, ""):
            errors.append(f"{url}:missing_onemin_aggregate")
            continue
        return route_payload
    raise RuntimeError(f"{backend_name}_failed:" + " | ".join(errors or ["no_http_runtime_url"]))


def _run_backend_command(command: list[str], *, request: dict[str, Any], timeout_seconds: int, backend_name: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["CODEXEA_ROUTE_REQUEST_JSON"] = json.dumps(request, separators=(",", ":"))
    env["CODEXEA_ROUTE_SOURCE"] = backend_name
    if backend_name == "local_python":
        python_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{APP_ROOT}:{python_path}" if python_path else str(APP_ROOT)
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{backend_name}_timeout_after_{float(exc.timeout or timeout_seconds):.1f}s") from exc
    if completed.returncode != 0:
        detail = _redact_runtime_text((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(f"{backend_name}_failed:{completed.returncode}:{detail[:400]}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        detail = _redact_runtime_text((completed.stdout or completed.stderr or "").strip())
        raise RuntimeError(f"{backend_name}_invalid_json:{detail[:400]}") from exc
    if _empty_onemin_aggregate(payload):
        raise RuntimeError(f"{backend_name}_empty_onemin_aggregate")
    return payload


def _backend_attempts(request: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    attempts: list[tuple[str, str, list[str]]] = []
    known: dict[str, tuple[str, str, list[str]]] = {
        "ea_api_container": ("ea_api_container", "subprocess", _docker_backend_command(request)),
        "docker": ("ea_api_container", "subprocess", _docker_backend_command(request)),
        "http_runtime_telemetry": ("http_runtime_telemetry", "http", []),
        "local_python": ("local_python", "subprocess", _local_backend_command(request)),
    }
    for name in _route_backend_order_preference():
        if name in {"docker", "ea_api_container"}:
            if shutil.which("docker"):
                attempts.append(known[name])
            continue
        if name == "http_runtime_telemetry":
            if _http_backend_urls():
                attempts.append(known[name])
            continue
        if name == "local_python" and _local_app_tree_available():
            attempts.append(known[name])
    return attempts


def _run_backend_attempt(
    backend_name: str,
    backend_kind: str,
    command: list[str],
    *,
    request: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    if backend_kind == "http":
        return _run_http_backend(request=request, timeout_seconds=timeout_seconds, backend_name=backend_name)
    backend_timeout_seconds = timeout_seconds
    if backend_name in {"docker", "ea_api_container"}:
        backend_timeout_seconds = min(int(timeout_seconds), 10)
    return _run_backend_command(
        command,
        request=request,
        timeout_seconds=backend_timeout_seconds,
        backend_name=backend_name,
    )


def _run_live_onemin_aggregate(args: argparse.Namespace) -> dict[str, Any]:
    request = _build_route_request(args)
    cooldown_state = _apply_onemin_probe_cooldowns(request)
    probe_mode = str(request.get("probe_mode") or "off")
    timeout_seconds = _command_timeout_seconds(args, probe_mode=probe_mode)
    backend_attempts = _backend_attempts(request)
    if not backend_attempts:
        raise RuntimeError("route_probe_failed:no_available_backend")
    errors: list[str] = []
    live_probe_attempts = [attempt for attempt in backend_attempts if attempt[1] != "http"] if bool(request.get("probe")) else backend_attempts
    if bool(request.get("probe")) and not live_probe_attempts:
        errors.append("no_live_probe_backend_available")
    for backend_name, backend_kind, command in live_probe_attempts:
        try:
            payload = _run_backend_attempt(
                backend_name,
                backend_kind,
                command,
                request=request,
                timeout_seconds=timeout_seconds,
            )
            return _finalize_onemin_probe_payload(payload, cooldown_state=cooldown_state)
        except Exception as exc:
            errors.append(_backend_error_summary(exc))
    if bool(request.get("probe")):
        cached_request = dict(request)
        cached_request["probe"] = False
        cached_request["probe_mode"] = "off"
        cached_request["probe_limit"] = 0
        cached_backend_attempts = _backend_attempts(cached_request)
        for backend_name, backend_kind, command in cached_backend_attempts:
            try:
                payload = _run_backend_attempt(
                    backend_name,
                    backend_kind,
                    command,
                    request=cached_request,
                    timeout_seconds=max(20, int(args.timeout_seconds)),
                )
                payload_probe = dict(payload.get("probe") or {})
                payload_probe["requested"] = True
                payload_probe["mode"] = probe_mode
                payload_probe["degraded_to_cached"] = True
                payload_probe["backend_errors"] = errors
                payload["probe"] = payload_probe
                return _finalize_onemin_probe_payload(payload, cooldown_state=cooldown_state)
            except Exception as exc:
                errors.append(_backend_error_summary(exc))
    raise RuntimeError("route_probe_failed:" + " | ".join(errors))


def _fmt(value: object) -> str:
    if value in (None, ""):
        return "n/a"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def _print_onemin_summary(payload: dict[str, Any]) -> None:
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    print("1min.AI credits")
    print(f"Generated at: {_fmt(payload.get('generated_at'))}")
    print(f"Source: {_fmt(payload.get('source'))}")
    print(f"Billing-backed remaining total: {_fmt(payload.get('actual_free_credits_total'))}")
    print(f"Dispatchable live remaining total: {_fmt(payload.get('live_remaining_credits_total'))}")
    print(f"Repository aggregate total: {_fmt(payload.get('sum_free_credits'))}")
    print(f"Current burn credits/hour: {_fmt(payload.get('current_burn_credits_per_hour'))}")
    print(f"Hours remaining at current pace: {_fmt(payload.get('hours_remaining_at_current_pace'))}")
    if probe:
        print("")
        print("Live probe")
        print(f"Requested: {'yes' if probe.get('requested') else 'no'}")
        print(f"Mode: {_fmt(probe.get('mode'))}")
        print(f"Partial: {'yes' if probe.get('partial') else 'no'}")
        print(f"Attempted: {_fmt(probe.get('attempted_count'))}")
        print(f"Refreshed: {_fmt(probe.get('ok_count'))}")
        print(f"Errors: {_fmt(probe.get('error_count'))}")
        print(f"Last probe at: {_fmt(probe.get('last_probe_at'))}")
        if probe.get("degraded_to_cached"):
            print("Cached fallback: yes")
        cooldown = probe.get("cooldown") if isinstance(probe.get("cooldown"), dict) else {}
        if cooldown:
            print(f"Cooldown-skipped: {_fmt(cooldown.get('skipped_count'))}")
            print(f"Cooldown-new: {_fmt(cooldown.get('new_count'))}")
        errors = probe.get("errors") or []
        if errors:
            print("")
            print("Sample errors")
            for row in list(errors)[:5]:
                if not isinstance(row, dict):
                    continue
                print(f"- {_fmt(row.get('account_name'))}: {_fmt(row.get('error'))}")
        if cooldown and cooldown.get("skipped"):
            print("")
            print("Cooldown skipped")
            for row in list(cooldown.get("skipped") or [])[:5]:
                if not isinstance(row, dict):
                    continue
                print(
                    f"- {_fmt(row.get('account_name'))}: "
                    f"{_fmt(row.get('cooldown_remaining_seconds'))}s until {_fmt(row.get('cooldown_until'))}"
                )


def _summary_payload(payload: dict[str, Any], *, error_limit: int = 5) -> dict[str, Any]:
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    onemin_refresh = payload.get("onemin_refresh") if isinstance(payload.get("onemin_refresh"), dict) else None
    telegram_delivery = (
        payload.get("telegram_delivery") if isinstance(payload.get("telegram_delivery"), dict) else None
    )
    summary: dict[str, Any] = {
        "provider_key": payload.get("provider_key"),
        "generated_at": payload.get("generated_at"),
        "source": payload.get("source"),
        "actual_free_credits_total": payload.get("actual_free_credits_total"),
        "live_remaining_credits_total": payload.get("live_remaining_credits_total"),
        "sum_free_credits": payload.get("sum_free_credits"),
        "current_burn_credits_per_hour": payload.get("current_burn_credits_per_hour"),
        "hours_remaining_at_current_pace": payload.get("hours_remaining_at_current_pace"),
        "account_count": payload.get("account_count"),
        "slot_count": len(payload.get("slots") or []),
    }
    if onemin_refresh is not None:
        summary["onemin_refresh"] = {
            "ran": onemin_refresh.get("ran"),
            "throttled": onemin_refresh.get("throttled"),
            "throttle_seconds_remaining": onemin_refresh.get("throttle_seconds_remaining"),
            "throttle_reason": onemin_refresh.get("throttle_reason"),
            "browseract_attempted": onemin_refresh.get("browseract_attempted"),
            "browseract_refreshed": onemin_refresh.get("browseract_refreshed"),
            "member_reconciled": onemin_refresh.get("member_reconciled"),
            "api_attempted": onemin_refresh.get("api_attempted"),
            "api_rate_limited": onemin_refresh.get("api_rate_limited"),
            "api_recovered": onemin_refresh.get("api_recovered"),
            "errors": onemin_refresh.get("errors"),
        }
        if onemin_refresh.get("error"):
            summary["onemin_refresh"]["error"] = str(onemin_refresh.get("error"))
    if telegram_delivery is not None:
        summary["telegram_delivery"] = {
            "requested": telegram_delivery.get("requested"),
            "sent": telegram_delivery.get("sent"),
            "reason": telegram_delivery.get("reason"),
            "timeout_seconds": telegram_delivery.get("timeout_seconds"),
            "chat_id_present": telegram_delivery.get("chat_id_present"),
            "bot_token_present": telegram_delivery.get("bot_token_present"),
        }
        if telegram_delivery.get("sent"):
            summary["telegram_delivery"]["message_id"] = telegram_delivery.get("message_id")
            summary["telegram_delivery"]["chat_id"] = telegram_delivery.get("chat_id")
    if probe:
        cooldown = probe.get("cooldown") if isinstance(probe.get("cooldown"), dict) else {}
        summary["probe"] = {
            "requested": probe.get("requested"),
            "mode": probe.get("mode"),
            "partial": probe.get("partial"),
            "attempted_count": probe.get("attempted_count"),
            "ok_count": probe.get("ok_count"),
            "error_count": probe.get("error_count"),
            "last_probe_at": probe.get("last_probe_at"),
            "degraded_to_cached": probe.get("degraded_to_cached"),
            "sample_errors": [
                {
                    "account_name": row.get("account_name"),
                    "error": row.get("error"),
                }
                for row in list(probe.get("errors") or [])
                if isinstance(row, dict)
            ][:error_limit],
        }
        if cooldown:
            summary["probe"]["cooldown"] = {
                "active_count": cooldown.get("active_count"),
                "skipped_count": cooldown.get("skipped_count"),
                "new_count": cooldown.get("new_count"),
                "sample_skipped": [
                    {
                        "account_name": row.get("account_name"),
                        "cooldown_remaining_seconds": row.get("cooldown_remaining_seconds"),
                        "cooldown_until": row.get("cooldown_until"),
                    }
                    for row in list(cooldown.get("skipped") or [])
                    if isinstance(row, dict)
                ][:error_limit],
                "sample_new": [
                    {
                        "account_name": row.get("account_name"),
                        "retry_after_seconds": row.get("retry_after_seconds"),
                        "cooldown_until": row.get("cooldown_until"),
                    }
                    for row in list(cooldown.get("new") or [])
                    if isinstance(row, dict)
                ][:error_limit],
            }
    return summary


def _telegram_env_value(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip()


def _resolve_telegram_bot_token(args: argparse.Namespace) -> str:
    return str(
        getattr(args, "telegram_bot_token", "")
        or _telegram_env_value("CODEXEA_TELEGRAM_BOT_TOKEN")
        or _telegram_env_value("EA_TELEGRAM_BOT_TOKEN")
        or _telegram_env_value("TELEGRAM_BOT_TOKEN")
    ).strip()


def _resolve_telegram_chat_id_from_proactive_bindings(*, principal_id: str) -> str:
    principal = str(principal_id or "").strip()
    if not principal:
        return ""
    try:
        from app.services import proactive_telegram_binding as proactive_telegram_binding
    except Exception:
        return ""
    try:
        resolved = proactive_telegram_binding.resolve_proactive_telegram_chat_id(principal_id=principal)
    except Exception:
        return ""
    return str(resolved or "").strip()


def _resolve_telegram_target_from_ea_api_container(*, principal_id: str) -> dict[str, object]:
    principal = str(principal_id or "").strip()
    if not principal or not shutil.which("docker"):
        return {}
    script = (
        "import json, os\n"
        "from app.services.proactive_telegram_binding import resolve_proactive_telegram_target\n"
        "principal = os.environ.get('CODEXEA_TELEGRAM_RESOLVE_PRINCIPAL_ID', '')\n"
        "print(json.dumps(resolve_proactive_telegram_target(principal_id=principal), sort_keys=True))\n"
    )
    timeout_seconds = _env_int("CODEXEA_TELEGRAM_TARGET_RESOLVE_TIMEOUT_SECONDS", 30, minimum=1, maximum=60)
    try:
        completed = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"CODEXEA_TELEGRAM_RESOLVE_PRINCIPAL_ID={principal}",
                DEFAULT_EA_API_CONTAINER,
                "python",
                "-c",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception:
        return {}
    if completed.returncode != 0:
        return {}
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _telegram_resolution_principal_id() -> str:
    return (
        _telegram_env_value("EA_PROACTIVE_OODA_PRINCIPAL_ID")
        or _telegram_env_value("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID")
        or _telegram_env_value("EA_DEFAULT_PRINCIPAL_ID")
        or ""
    )


def _resolve_telegram_chat_id(args: argparse.Namespace) -> str:
    direct_chat_id = str(
        getattr(args, "telegram_chat_id", "")
        or _telegram_env_value("CODEXEA_TELEGRAM_CHAT_ID")
        or _telegram_env_value("EA_TELEGRAM_CHAT_ID")
        or _telegram_env_value("EA_TELEGRAM_DEFAULT_CHAT_ID")
        or _telegram_env_value("EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID")
        or _telegram_env_value("TELEGRAM_CHAT_ID")
    ).strip()
    if direct_chat_id:
        return direct_chat_id
    principal_id = _telegram_resolution_principal_id()
    binding_chat_id = _resolve_telegram_chat_id_from_proactive_bindings(principal_id=principal_id)
    if binding_chat_id:
        return binding_chat_id
    target = _resolve_telegram_target_from_ea_api_container(principal_id=principal_id)
    return str(target.get("chat_id") or "").strip()


def _to_bool_text(value: object, *, yes_value: str = "yes", no_value: str = "no") -> str:
    return yes_value if bool(value) else no_value


def _build_telegram_refresh_message(payload: dict[str, Any]) -> str:
    refresh_payload = payload.get("onemin_refresh") if isinstance(payload.get("onemin_refresh"), dict) else {}
    refresh_payload = dict(refresh_payload)
    lines: list[str] = []
    lines.append("1min.AI credit refresh")
    lines.append(f"Generated at: {_fmt(payload.get('generated_at'))}")
    lines.append(f"Source: {_fmt(payload.get('source'))}")
    lines.append(f"Billing-backed remaining: {_fmt(payload.get('actual_free_credits_total'))}")
    if refresh_payload:
        lines.append(f"Refresh ran: {_to_bool_text(refresh_payload.get('ran'))}")
        lines.append(f"Throttled: {_to_bool_text(refresh_payload.get('throttled'))}")
        throttle_reason = str(refresh_payload.get("throttle_reason") or "").strip()
        if refresh_payload.get("throttled") and throttle_reason:
            lines.append(f"Throttle reason: {throttle_reason}")
        lines.append(f"Throttle seconds remaining: {_fmt(refresh_payload.get('throttle_seconds_remaining'))}")
        lines.append(f"BrowserAct attempted: {_fmt(refresh_payload.get('browseract_attempted'))}")
        lines.append(f"BrowserAct refreshed: {_fmt(refresh_payload.get('browseract_refreshed'))}")
        lines.append(f"Members reconciled: {_fmt(refresh_payload.get('member_reconciled'))}")
        lines.append(f"API attempted: {_fmt(refresh_payload.get('api_attempted'))}")
        lines.append(f"API recovered: {_fmt(refresh_payload.get('api_recovered'))}")
        lines.append(f"Errors: {_fmt(refresh_payload.get('errors'))}")
        lines.append(f"API rate-limited: {_to_bool_text(refresh_payload.get('api_rate_limited'))}")
        if refresh_payload.get("error"):
            lines.append(f"Error: {_fmt(refresh_payload.get('error'))}")
    else:
        lines.append("Refresh requested: no")
    return "\n".join(lines)


def _send_telegram_message(payload: dict[str, str], *, timeout_seconds: float) -> dict[str, object]:
    bot_token = payload.get("bot_token", "").strip()
    request_payload = {
        "chat_id": payload.get("chat_id", "").strip(),
        "text": payload.get("text", "").strip(),
        "disable_web_page_preview": True,
    }
    body = json.dumps(request_payload).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=max(1, float(timeout_seconds))) as response:
        response_body = response.read().decode("utf-8")
    if not response_body:
        raise RuntimeError("telegram_response_empty")
    try:
        response_payload = json.loads(response_body)
    except json.JSONDecodeError:
        raise RuntimeError(f"telegram_invalid_json:{response_body[:200]}")
    if not isinstance(response_payload, dict) or not bool(response_payload.get("ok")):
        description = str((response_payload or {}).get("description") if isinstance(response_payload, dict) else "")
        raise RuntimeError(f"telegram_send_failed:{description or 'invalid_response'}")
    result_payload = response_payload.get("result")
    if not isinstance(result_payload, dict):
        raise RuntimeError("telegram_response_unexpected")
    return result_payload


def _build_telegram_delivery_request(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, object]:
    if not bool(args.send_telegram):
        return {
            "requested": False,
            "sent": False,
            "reason": "send_telegram_not_requested",
            "timeout_seconds": int(max(1, int(args.telegram_timeout_seconds))),
        }

    bot_token = _resolve_telegram_bot_token(args)
    if not bot_token:
        return {
            "requested": True,
            "sent": False,
            "reason": "telegram_bot_token_missing",
            "chat_id_present": False,
            "bot_token_present": False,
            "timeout_seconds": int(max(1, int(args.telegram_timeout_seconds))),
        }

    chat_id = _resolve_telegram_chat_id(args)
    if not chat_id:
        return {
            "requested": True,
            "sent": False,
            "reason": "telegram_chat_id_missing",
            "chat_id_present": False,
            "bot_token_present": bool(bot_token),
            "timeout_seconds": int(max(1, int(args.telegram_timeout_seconds))),
        }

    message = _build_telegram_refresh_message(payload)
    request_payload = {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    timeout_seconds = max(1, int(args.telegram_timeout_seconds))
    try:
        response = _send_telegram_message(request_payload, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return {
            "requested": True,
            "sent": False,
            "reason": str(exc).strip()[:200],
            "chat_id_present": bool(chat_id),
            "bot_token_present": bool(bot_token),
            "timeout_seconds": timeout_seconds,
        }
    return {
        "requested": True,
        "sent": True,
        "reason": "sent",
        "message_id": response.get("message_id"),
        "chat_id": str(response.get("chat", {}).get("id") or "").strip(),
        "chat_id_present": bool(response.get("chat", {}).get("id")),
        "bot_token_present": bool(bot_token),
        "timeout_seconds": timeout_seconds,
    }


def _print_telegram_delivery_status(delivery: dict[str, Any]) -> None:
    if not delivery:
        return
    if delivery.get("sent"):
        print("Telegram: sent")
        return
    reason = str(delivery.get("reason") or "not_sent").strip()
    print(f"Telegram: {reason}")


def main() -> int:
    args = _parse_args()
    if args.telemetry_answer is not None:
        return 10
    if not args.onemin_aggregate:
        print("unsupported_route", file=sys.stderr)
        return 2
    payload = _run_live_onemin_aggregate(args)
    if bool(args.send_telegram):
        payload["telegram_delivery"] = _build_telegram_delivery_request(args, payload)
    summary = _summary_payload(payload)

    if args.summary_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_onemin_summary(payload)
        if bool(args.send_telegram):
            _print_telegram_delivery_status(payload["telegram_delivery"])
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
