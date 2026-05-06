#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "ea"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.services.browseract_ui_template_catalog import browseract_ui_template_spec
from app.services import responses_upstream as upstream
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from app.services.tool_execution_common import ToolExecutionError


LEDGER_CANDIDATES = (
    ROOT / "config" / "onemin_slot_owners.local.json",
    ROOT / "config" / "onemin_slot_owners.json",
)
WORKER_SCRIPT = ROOT / "scripts" / "browseract_template_service_worker.py"
ROTATE_SCRIPT = ROOT / "scripts" / "rotate_fastestvpn_proxy.sh"
DEFAULT_PAGE_URL = "https://app.1min.ai/billing-usage"
ENV_PLACEHOLDER_RE = re.compile(r"\$\{([^}:]+)(:-([^}]*))?\}")


@dataclass
class AccountRecord:
    slot: str
    account_label: str
    owner_email: str
    owner_name: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh 1min.AI balances through the BrowserAct billing page flow."
    )
    parser.add_argument(
        "--account-label",
        action="append",
        dest="account_labels",
        default=[],
        help="Specific ONEMIN_AI_API_KEY[_FALLBACK_n] label(s) to refresh. Defaults to every ledger slot.",
    )
    parser.add_argument(
        "--max-accounts",
        type=int,
        default=0,
        help="Limit the number of accounts processed after filtering. 0 means all.",
    )
    parser.add_argument(
        "--rotate-every",
        type=int,
        default=int(os.environ.get("ONEMIN_BROWSERACT_ROTATE_EVERY", "0") or "0"),
        help="Rotate the FastestVPN proxy after every N processed accounts. 0 disables periodic rotation.",
    )
    parser.add_argument(
        "--retry-challenge",
        type=int,
        default=int(os.environ.get("ONEMIN_BROWSERACT_RETRY_CHALLENGE", "1") or "1"),
        help="How many times to rotate and retry an account after a challenge/session/auth transport failure.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("ONEMIN_BROWSERACT_TIMEOUT_SECONDS", "180") or "180"),
        help="Per-account BrowserAct timeout.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=float(os.environ.get("ONEMIN_BROWSERACT_PAUSE_SECONDS", "0.5") or "0.5"),
        help="Pause between accounts to avoid back-to-back login bursts.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "state" / f"onemin_browseract_refresh_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json",
        help="Where to write the full run summary JSON.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an existing output JSON by skipping accounts that already have recorded results.",
    )
    return parser.parse_args()


def _load_ledger_rows() -> list[AccountRecord]:
    for candidate in LEDGER_CANDIDATES:
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        rows = payload.get("slots") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        records: list[AccountRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            account_label = str(row.get("account_name") or "").strip()
            owner_email = str(row.get("owner_email") or "").strip()
            if not account_label or not owner_email:
                continue
            records.append(
                AccountRecord(
                    slot=str(row.get("slot") or "").strip(),
                    account_label=account_label,
                    owner_email=owner_email,
                    owner_name=str(row.get("owner_name") or "").strip(),
                )
            )
        if records:
            return records
    raise SystemExit("No 1min owner ledger with account labels and owner emails was found.")


def _selected_accounts(all_rows: list[AccountRecord], requested_labels: list[str], max_accounts: int) -> list[AccountRecord]:
    requested = {str(value or "").strip() for value in requested_labels if str(value or "").strip()}
    rows = [row for row in all_rows if not requested or row.account_label in requested]
    if max_accounts > 0:
        rows = rows[:max_accounts]
    return rows


def _browser_proxy_settings() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_name in (
        "EA_UI_BROWSER_PROXY_SERVER",
        "EA_UI_BROWSER_PROXY_POOL",
        "EA_UI_BROWSER_PROXY_USERNAME",
        "EA_UI_BROWSER_PROXY_PASSWORD",
        "EA_UI_BROWSER_PROXY_BYPASS",
    ):
        raw = str(os.environ.get(env_name) or "").strip()
        if raw:
            values[env_name] = _expand_env_placeholders(raw)
    return values


def _expand_env_placeholders(value: str) -> str:
    text = str(value or "")

    def _replace(match: re.Match[str]) -> str:
        key = str(match.group(1) or "").strip()
        default = str(match.group(3) or "")
        if not key:
            return match.group(0)
        resolved = os.environ.get(key)
        if resolved in (None, ""):
            resolved = default
        return str(resolved)

    return ENV_PLACEHOLDER_RE.sub(_replace, text)


def _sidecar_running(container_name: str) -> bool:
    completed = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip().lower() == "true"


def _effective_proxy_settings() -> dict[str, str]:
    values = _browser_proxy_settings()
    if "EA_UI_BROWSER_PROXY_SERVER" not in values and _sidecar_running("ea-fastestvpn-proxy"):
        proxy_port = str(os.environ.get("FASTESTVPN_PROXY_PORT") or "3128").strip() or "3128"
        values["EA_UI_BROWSER_PROXY_SERVER"] = f"http://ea-fastestvpn-proxy:{proxy_port}"
    return values


def _browser_proxy_pool(values: dict[str, str] | None = None) -> list[str]:
    selected = dict(values or _effective_proxy_settings())
    pool_raw = str(selected.get("EA_UI_BROWSER_PROXY_POOL") or "").strip()
    pool = [item.strip() for item in pool_raw.split(",") if item.strip()]
    server = str(selected.get("EA_UI_BROWSER_PROXY_SERVER") or "").strip()
    if server and server not in pool:
        pool.insert(0, server)
    return pool


def _proxy_service_name_for_url(proxy_url: str) -> str:
    host = str(urllib.parse.urlsplit(str(proxy_url or "").strip()).hostname or "").strip().lower()
    if host.startswith("ea-fastestvpn-proxy"):
        return host
    return ""


def _account_proxy_settings(account_label: str, *, retry_offset: int = 0) -> dict[str, str]:
    values = dict(_effective_proxy_settings())
    pool = _browser_proxy_pool(values)
    selected_server = str(values.get("EA_UI_BROWSER_PROXY_SERVER") or "").strip()
    selected_service_name = _proxy_service_name_for_url(selected_server)
    normalized_label = str(account_label or "").strip()
    if pool:
        if normalized_label:
            digest = hashlib.sha256(normalized_label.encode("utf-8")).digest()
            base_index = int.from_bytes(digest[:8], "big") % len(pool)
            selected_server = pool[(base_index + max(int(retry_offset), 0)) % len(pool)]
        else:
            selected_server = pool[max(int(retry_offset), 0) % len(pool)]
        selected_service_name = _proxy_service_name_for_url(selected_server)
        values["EA_UI_BROWSER_PROXY_POOL"] = ",".join(pool)
        values["EA_UI_BROWSER_PROXY_SERVER"] = selected_server
    if selected_service_name:
        values["EA_UI_BROWSER_PROXY_SERVICE_NAME"] = selected_service_name
    return values


def _effective_worker_env() -> dict[str, str]:
    worker_env = os.environ.copy()
    if not str(worker_env.get("EA_UI_SERVICE_DOCKER_NETWORK") or "").strip() and _sidecar_running("ea-fastestvpn-proxy"):
        worker_env["EA_UI_SERVICE_DOCKER_NETWORK"] = "ea_default"
    return worker_env


def _failure_code_from_exception(exc: Exception) -> str:
    lowered = str(exc or "").strip().lower()
    if "unable to find image" in lowered and "chummer-playwright" in lowered:
        return "playwright_image_missing"
    if "pull access denied" in lowered and "chummer-playwright" in lowered:
        return "playwright_image_missing"
    if "cannot find module 'playwright'" in lowered or 'cannot find module "playwright"' in lowered:
        return "playwright_module_missing"
    if "cannot connect to the docker daemon" in lowered:
        return "docker_unavailable"
    if "no space left on device" in lowered:
        return "disk_full"
    marker = "ui_lane_failure:"
    if marker in lowered:
        parts = [part for part in lowered.split(marker, 1)[1].split(":") if part]
        if parts:
            return parts[-1]
    return lowered or "worker_failed"


def _response_failure_detail(response: dict[str, Any]) -> str:
    structured = response.get("structured_output_json") if isinstance(response, dict) else {}
    structured = structured if isinstance(structured, dict) else {}
    fragments: list[str] = []
    for key in ("error", "body_text", "raw_text", "stderr_tail", "stdout_tail"):
        value = str(response.get(key) or "").strip()
        if value:
            fragments.append(value)
    for key in ("errors", "warnings"):
        values = response.get(key)
        if isinstance(values, list):
            fragments.extend(str(value or "").strip() for value in values if str(value or "").strip())
    for key in ("errors", "warnings"):
        values = structured.get(key)
        if isinstance(values, list):
            fragments.extend(str(value or "").strip() for value in values if str(value or "").strip())
    return "\n".join(fragments).strip()


def _failure_code_from_response(response: dict[str, Any]) -> str:
    structured = response.get("structured_output_json") if isinstance(response, dict) else {}
    structured = structured if isinstance(structured, dict) else {}
    explicit = str(
        response.get("ui_failure_code")
        or response.get("failure_code")
        or structured.get("ui_failure_code")
        or structured.get("failure_code")
        or ""
    ).strip().lower()
    if explicit:
        return explicit
    detail = _response_failure_detail(response)
    if detail:
        return _failure_code_from_exception(Exception(detail))
    return "worker_failed"


def _failed_worker_response_result(
    record: AccountRecord,
    *,
    response: dict[str, Any],
    duration_seconds: float,
    worker_returncode: int,
) -> dict[str, Any] | None:
    structured = response.get("structured_output_json") if isinstance(response, dict) else {}
    structured = structured if isinstance(structured, dict) else {}
    render_status = str(response.get("render_status") or structured.get("render_status") or "").strip().lower()
    if render_status not in {"failed", "worker_failed"}:
        return None
    failure_code = _failure_code_from_response(response)
    ui_failure_codes = {
        "auth_request_failed",
        "challenge_required",
        "challenge_loop",
        "invalid_credentials",
        "session_expired",
        "timeout",
    }
    return {
        "account_label": record.account_label,
        "owner_email": record.owner_email,
        "status": "ui_lane_failure" if failure_code in ui_failure_codes else "worker_failed",
        "failure_code": failure_code or "worker_failed",
        "duration_seconds": duration_seconds,
        "worker_returncode": worker_returncode,
        "error": _response_failure_detail(response)[:4000],
        "asset_path": str(response.get("asset_path") or ""),
        "screenshot_path": str(response.get("screenshot_path") or ""),
        "warnings": list(response.get("warnings") or []),
    }


def _ea_api_base_url() -> str:
    default_port = str(os.environ.get("EA_HOST_PORT") or os.environ.get("EA_PORT") or "8090").strip() or "8090"
    explicit = str(
        os.environ.get("EA_BASE_URL")
        or os.environ.get("EA_MCP_BASE_URL")
        or os.environ.get("EA_HOST")
        or ""
    ).strip()
    if explicit:
        if "://" not in explicit:
            explicit = f"http://{explicit}"
        parsed = urllib.parse.urlsplit(explicit)
        hostname = str(parsed.hostname or "").strip().lower()
        port = parsed.port or int(default_port)
        if hostname in {"0.0.0.0", "::", "[::]"}:
            explicit = urllib.parse.urlunsplit(
                (
                    parsed.scheme or "http",
                    f"127.0.0.1:{port}",
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
        elif parsed.port is None and hostname:
            explicit = urllib.parse.urlunsplit(
                (
                    parsed.scheme or "http",
                    f"{parsed.hostname}:{port}",
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
        return explicit.rstrip("/")
    return f"http://127.0.0.1:{default_port}"


def _persist_snapshot_via_ea_api(record: AccountRecord, *, normalized: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    token = str(os.environ.get("EA_API_TOKEN") or "").strip()
    if not token:
        return None, "ea_api_token_missing"
    payload = {
        "account_label": record.account_label,
        "source": "browseract.onemin_billing_usage.fastestvpn_refresh",
        "snapshot_json": dict(normalized or {}),
    }
    request = urllib.request.Request(
        url=f"{_ea_api_base_url()}/v1/providers/onemin/billing-snapshots",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-EA-Principal-ID": str(os.environ.get("EA_PRINCIPAL_ID") or "codex-fleet").strip() or "codex-fleet",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, f"ea_api_http_{exc.code}:{detail[:400]}"
    except Exception as exc:
        return None, f"ea_api_request_failed:{exc}"
    try:
        parsed = json.loads(body)
    except Exception as exc:
        return None, f"ea_api_invalid_json:{exc}"
    if not isinstance(parsed, dict):
        return None, "ea_api_invalid_payload"
    snapshot = parsed.get("snapshot")
    if not isinstance(snapshot, dict):
        return None, "ea_api_missing_snapshot"
    return snapshot, ""


def _rotate_proxy(*, service_name: str = "") -> dict[str, Any]:
    start = time.time()
    command = [str(ROTATE_SCRIPT)]
    normalized_service_name = str(service_name or "").strip()
    if normalized_service_name:
        command.extend(["--service", normalized_service_name])
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - start, 3),
        "service_name": normalized_service_name,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def _run_account(record: AccountRecord, *, timeout_seconds: int, proxy_retry_offset: int = 0) -> dict[str, Any]:
    password = str(os.environ.get("ONEMIN_DEFAULT_PASSWORD") or os.environ.get("BROWSERACT_PASSWORD") or "").strip()
    if not password:
        raise SystemExit("ONEMIN_DEFAULT_PASSWORD is not configured.")
    temp_root = Path(tempfile.mkdtemp(prefix=f"onemin_browseract_{record.account_label.lower()}_"))
    packet_path = temp_root / "packet.json"
    output_path = temp_root / "output.json"
    template_spec = browseract_ui_template_spec("onemin_billing_usage_reader_live")
    packet: dict[str, Any] = {
        "service_key": "onemin_billing_usage_refresh",
        "template_key": "onemin_billing_usage_reader_live",
        "result_title": f"{record.account_label} billing refresh",
        "login_email": record.owner_email,
        "login_password": password,
        "browseract_username": record.owner_email,
        "browseract_password": password,
        "timeout_seconds": timeout_seconds,
        "workflow_spec_json": template_spec,
    }
    proxy_values = _account_proxy_settings(record.account_label, retry_offset=proxy_retry_offset)
    if proxy_values.get("EA_UI_BROWSER_PROXY_SERVER"):
        packet["browser_proxy_server"] = proxy_values["EA_UI_BROWSER_PROXY_SERVER"]
    if proxy_values.get("EA_UI_BROWSER_PROXY_USERNAME"):
        packet["browser_proxy_username"] = proxy_values["EA_UI_BROWSER_PROXY_USERNAME"]
    if proxy_values.get("EA_UI_BROWSER_PROXY_PASSWORD"):
        packet["browser_proxy_password"] = proxy_values["EA_UI_BROWSER_PROXY_PASSWORD"]
    if proxy_values.get("EA_UI_BROWSER_PROXY_BYPASS"):
        packet["browser_proxy_bypass"] = proxy_values["EA_UI_BROWSER_PROXY_BYPASS"]
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    started = time.time()
    completed = subprocess.run(
        [sys.executable, str(WORKER_SCRIPT), "--packet-path", str(packet_path)],
        cwd=str(ROOT),
        env=_effective_worker_env(),
        capture_output=True,
        text=True,
        check=False,
        timeout=max(timeout_seconds + 30, 60),
    )
    duration_seconds = round(time.time() - started, 3)
    response: dict[str, Any] | None = None
    if output_path.exists():
        try:
            response = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            response = None
    if response is None:
        stdout_text = str(completed.stdout or "").strip()
        if stdout_text:
            for line in reversed(stdout_text.splitlines()):
                candidate = line.strip()
                if not candidate:
                    continue
                try:
                    maybe = json.loads(candidate)
                except Exception:
                    continue
                if isinstance(maybe, dict):
                    response = maybe
                    break
    if response is None:
        return {
            "account_label": record.account_label,
            "owner_email": record.owner_email,
            "status": "worker_failed",
            "failure_code": "worker_failed",
            "duration_seconds": duration_seconds,
            "worker_returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
            "proxy_server": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVER") or ""),
            "proxy_service_name": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVICE_NAME") or ""),
        }
    failed_response = _failed_worker_response_result(
        record,
        response=response,
        duration_seconds=duration_seconds,
        worker_returncode=completed.returncode,
    )
    if failed_response is not None:
        failed_response["proxy_server"] = str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVER") or "")
        failed_response["proxy_service_name"] = str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVICE_NAME") or "")
        return failed_response
    try:
        BrowserActToolAdapter._raise_for_ui_lane_failure(
            payload=dict(response or {}),
            backend="onemin_billing_usage",
        )
        normalized = BrowserActToolAdapter._normalize_onemin_billing_payload(
            response=dict(response or {}),
            source_url=DEFAULT_PAGE_URL,
            account_label=record.account_label,
        )
        persisted_snapshot = None
        persisted_error = ""
        try:
            persisted_snapshot, persisted_error = _persist_snapshot_via_ea_api(
                record,
                normalized=normalized,
            )
            if persisted_snapshot is None:
                persisted_snapshot = upstream.record_onemin_billing_snapshot(
                    account_name=record.account_label,
                    snapshot_json=normalized,
                    source="browseract.onemin_billing_usage.fastestvpn_refresh",
                )
                if persisted_error:
                    persisted_error = f"{persisted_error}; local_process_fallback"
        except Exception as exc:  # pragma: no cover - best effort state sync
            persisted_error = str(exc)
        basis = str(normalized.get("basis") or "").strip()
        if basis == "page_seen_but_unparsed" or normalized.get("remaining_credits") is None:
            return {
                "account_label": record.account_label,
                "owner_email": record.owner_email,
                "status": "ui_lane_failure",
                "failure_code": "page_seen_but_unparsed",
                "duration_seconds": duration_seconds,
                "worker_returncode": completed.returncode,
                "remaining_credits": normalized.get("remaining_credits"),
                "max_credits": normalized.get("max_credits"),
                "plan_name": normalized.get("plan_name"),
                "billing_cycle": normalized.get("billing_cycle"),
                "subscription_status": normalized.get("subscription_status"),
                "daily_bonus_available": normalized.get("daily_bonus_available"),
                "daily_bonus_credits": normalized.get("daily_bonus_credits"),
                "basis": basis,
                "result_url": str(response.get("editor_url") or response.get("source_url") or ""),
                "asset_path": str(response.get("asset_path") or ""),
                "screenshot_path": str(response.get("screenshot_path") or ""),
                "warnings": list(response.get("warnings") or []),
                "persisted_snapshot": persisted_snapshot,
                "persisted_error": persisted_error,
                "error": "billing page was reached but credits could not be parsed",
                "proxy_server": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVER") or ""),
                "proxy_service_name": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVICE_NAME") or ""),
            }
        return {
            "account_label": record.account_label,
            "owner_email": record.owner_email,
            "status": "ok",
            "failure_code": "",
            "duration_seconds": duration_seconds,
            "worker_returncode": completed.returncode,
            "remaining_credits": normalized.get("remaining_credits"),
            "max_credits": normalized.get("max_credits"),
            "plan_name": normalized.get("plan_name"),
            "billing_cycle": normalized.get("billing_cycle"),
            "subscription_status": normalized.get("subscription_status"),
            "daily_bonus_available": normalized.get("daily_bonus_available"),
            "daily_bonus_credits": normalized.get("daily_bonus_credits"),
            "basis": normalized.get("basis"),
            "result_url": str(response.get("editor_url") or response.get("source_url") or ""),
            "asset_path": str(response.get("asset_path") or ""),
            "screenshot_path": str(response.get("screenshot_path") or ""),
            "warnings": list(response.get("warnings") or []),
            "persisted_snapshot": persisted_snapshot,
            "persisted_error": persisted_error,
            "proxy_server": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVER") or ""),
            "proxy_service_name": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVICE_NAME") or ""),
        }
    except ToolExecutionError as exc:
        return {
            "account_label": record.account_label,
            "owner_email": record.owner_email,
            "status": "ui_lane_failure",
            "failure_code": _failure_code_from_exception(exc),
            "duration_seconds": duration_seconds,
            "worker_returncode": completed.returncode,
            "error": str(exc),
            "asset_path": str(response.get("asset_path") or ""),
            "screenshot_path": str(response.get("screenshot_path") or ""),
            "warnings": list(response.get("warnings") or []),
            "proxy_server": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVER") or ""),
            "proxy_service_name": str(proxy_values.get("EA_UI_BROWSER_PROXY_SERVICE_NAME") or ""),
        }


def _load_existing_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _processed_account_labels(summary: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for row in (summary.get("results") or []):
        if not isinstance(row, dict):
            continue
        account_label = str(row.get("account_label") or "").strip()
        if account_label:
            labels.add(account_label)
    return labels


def _account_exception_result(record: AccountRecord, *, attempts: int, exc: Exception) -> dict[str, Any]:
    failure_code = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "unexpected_exception"
    result: dict[str, Any] = {
        "account_label": record.account_label,
        "owner_email": record.owner_email,
        "status": "worker_failed",
        "failure_code": failure_code,
        "attempt": attempts,
        "remaining_credits": 0,
        "error": str(exc),
    }
    if isinstance(exc, subprocess.TimeoutExpired):
        result["timeout_seconds"] = getattr(exc, "timeout", 0)
        stdout_text = str(getattr(exc, "stdout", "") or "").strip()
        stderr_text = str(getattr(exc, "stderr", "") or "").strip()
        if stdout_text:
            result["stdout_tail"] = stdout_text[-4000:]
        if stderr_text:
            result["stderr_tail"] = stderr_text[-4000:]
    return result


def _write_summary(path: Path, summary: dict[str, Any], *, started: float) -> dict[str, Any]:
    persisted = dict(summary)
    successes = [row for row in (persisted.get("results") or []) if isinstance(row, dict) and row.get("status") == "ok"]
    failures = [row for row in (persisted.get("results") or []) if isinstance(row, dict) and row.get("status") != "ok"]
    total_remaining = sum(int(row.get("remaining_credits") or 0) for row in successes)
    persisted["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    persisted["duration_seconds"] = round(time.time() - started, 3)
    persisted["success_count"] = len(successes)
    persisted["failure_count"] = len(failures)
    persisted["processed_count"] = len(successes) + len(failures)
    persisted["total_remaining_credits"] = total_remaining
    persisted["failure_code_counts"] = {
        code: sum(1 for row in failures if row.get("failure_code") == code)
        for code in sorted({str(row.get("failure_code") or "") for row in failures if str(row.get("failure_code") or "")})
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
    return persisted


def main() -> int:
    args = _parse_args()
    all_rows = _load_ledger_rows()
    accounts = _selected_accounts(all_rows, args.account_labels, args.max_accounts)
    if not accounts:
        raise SystemExit("No matching 1min accounts were selected.")

    started = time.time()
    summary: dict[str, Any] = _load_existing_summary(args.output_json) if args.resume else {}
    if summary:
        summary["results"] = [row for row in (summary.get("results") or []) if isinstance(row, dict)]
        summary["rotations"] = [row for row in (summary.get("rotations") or []) if isinstance(row, dict)]
        summary["resumed"] = True
        summary["resumed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    else:
        summary = {
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
            "results": [],
            "rotations": [],
            "resumed": False,
        }
    summary["proxy_server"] = str(_effective_proxy_settings().get("EA_UI_BROWSER_PROXY_SERVER") or "").strip()
    summary["proxy_pool"] = _browser_proxy_pool()
    summary["worker_docker_network"] = str(_effective_worker_env().get("EA_UI_SERVICE_DOCKER_NETWORK") or "").strip()
    summary["rotate_every"] = args.rotate_every
    summary["retry_challenge"] = args.retry_challenge
    summary["timeout_seconds"] = args.timeout_seconds
    summary["pause_seconds"] = args.pause_seconds
    summary["total_accounts_requested"] = len(accounts)
    processed_labels = _processed_account_labels(summary)
    pending_accounts = [record for record in accounts if record.account_label not in processed_labels]
    summary["resumed_skip_count"] = max(0, len(accounts) - len(pending_accounts))
    rotation_failure_codes = {"challenge_required", "session_expired", "auth_request_failed", "timeout"}

    for index, record in enumerate(pending_accounts, start=1):
        print(f"[onemin-refresh] {index}/{len(accounts)} {record.account_label} ({record.owner_email})", flush=True)
        attempts = 0
        result: dict[str, Any] | None = None
        while attempts <= args.retry_challenge:
            attempts += 1
            try:
                result = _run_account(
                    record,
                    timeout_seconds=args.timeout_seconds,
                    proxy_retry_offset=max(attempts - 1, 0),
                )
                result["attempt"] = attempts
            except Exception as exc:
                result = _account_exception_result(record, attempts=attempts, exc=exc)
            rotation_service_name = str(result.get("proxy_service_name") or "").strip()
            if result.get("status") == "ok":
                break
            if str(result.get("failure_code") or "") not in rotation_failure_codes:
                break
            if attempts > args.retry_challenge:
                break
            rotation = _rotate_proxy(service_name=rotation_service_name)
            rotation["reason"] = f"{record.account_label}:{result.get('failure_code')}:retry"
            summary["rotations"].append(rotation)
            _write_summary(args.output_json, summary, started=started)
            time.sleep(max(args.pause_seconds, 1.0))
        assert result is not None
        summary["results"].append(result)
        _write_summary(args.output_json, summary, started=started)
        if args.rotate_every > 0 and index < len(pending_accounts) and index % args.rotate_every == 0:
            rotation = _rotate_proxy(service_name=rotation_service_name)
            rotation["reason"] = f"batch:{index}"
            summary["rotations"].append(rotation)
            _write_summary(args.output_json, summary, started=started)
        if args.pause_seconds > 0 and index < len(pending_accounts):
            time.sleep(args.pause_seconds)

    summary = _write_summary(args.output_json, summary, started=started)
    print(
        json.dumps(
            {
                "output_json": str(args.output_json),
                "success_count": summary["success_count"],
                "failure_count": summary["failure_count"],
                "total_remaining_credits": summary["total_remaining_credits"],
                "duration_seconds": summary["duration_seconds"],
                "failure_code_counts": summary["failure_code_counts"],
                "resumed_skip_count": summary.get("resumed_skip_count", 0),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if int(summary.get("failure_count") or 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
