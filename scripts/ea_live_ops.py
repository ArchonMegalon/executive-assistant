#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (ROOT / "ea", ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _load_dotenv_if_present(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        os.environ[key] = normalized


_load_dotenv_if_present(ROOT / ".env")

import check_whatsapp_web_session_readiness as readiness_script  # noqa: E402
from app.container import build_container  # noqa: E402
from app.services import whatsapp_web_session_delivery  # noqa: E402
from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight  # noqa: E402
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface  # noqa: E402
from app.services.responses_upstream import _provider_health_report  # noqa: E402


DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_READINESS_RECEIPT_FILENAME = "whatsapp_web_action_processor_readiness.generated.json"
DEFAULT_READINESS_RECEIPT_PATH = ROOT / ".codex-studio" / "published" / DEFAULT_READINESS_RECEIPT_FILENAME
DEFAULT_RUNTIME_CONTAINER = "ea-api"
DEFAULT_PROACTIVE_OODA_COMPOSE_FILE = ROOT / "docker-compose.yml"
DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE = "ea-proactive-ooda"

PROACTIVE_SOURCE_COVERAGE_LANES: tuple[dict[str, str], ...] = (
    {
        "key": "postgres_observations",
        "label": "Postgres observations",
        "next_action": "verify_postgres_observation_source",
    },
    {
        "key": "google_workspace",
        "label": "Google workspace",
        "next_action": "reauthorize_or_sync_google_workspace_sources",
    },
    {
        "key": "pocket_ai_audio_transcripts",
        "label": "Pocket.ai audio transcripts",
        "next_action": "sync_pocket_ai_audio_transcripts",
    },
    {
        "key": "calendar_and_renewal_signals",
        "label": "Calendar and renewal signals",
        "next_action": "sync_calendar_and_renewal_sources",
    },
    {
        "key": "relationship_and_occasion_signals",
        "label": "Relationship and occasion signals",
        "next_action": "refresh_relationship_and_occasion_sources",
    },
    {
        "key": "shopping_and_vendor_signals",
        "label": "Shopping and vendor signals",
        "next_action": "sync_shopping_and_vendor_sources",
    },
    {
        "key": "commitment_and_deadline_signals",
        "label": "Commitment and deadline signals",
        "next_action": "sync_commitment_and_deadline_sources",
    },
    {
        "key": "durable_profile_and_location_context",
        "label": "Durable profile and location context",
        "next_action": "refresh_principal_profile_context",
    },
)
PROACTIVE_SOURCE_COVERAGE_LANE_KEYS = tuple(row["key"] for row in PROACTIVE_SOURCE_COVERAGE_LANES)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _default_whatsapp_principal_id() -> str:
    return _env("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID") or _env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", "principal-default")


def _default_proactive_principal_id() -> str:
    return _env("EA_PROACTIVE_OODA_PRINCIPAL_ID") or _env("EA_DEFAULT_PRINCIPAL_ID") or _default_whatsapp_principal_id()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _normalize_phone_hint(value: object) -> str:
    raw = str(value or "").strip()
    return raw if raw in {"*", "default"} else _digits(raw)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _read_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _runtime_readiness_receipt_path() -> Path:
    configured = _env("EA_WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_PATH")
    if configured:
        return Path(configured)
    ledger_dir = _env("EA_RESPONSES_PROVIDER_LEDGER_DIR", "/data/provider-ledger") or "/data/provider-ledger"
    return Path(ledger_dir) / "provider-health-cache" / DEFAULT_READINESS_RECEIPT_FILENAME


def _whatsapp_readiness_receipt() -> dict[str, object]:
    ordered: list[Path] = []
    for candidate in (_runtime_readiness_receipt_path(), DEFAULT_READINESS_RECEIPT_PATH):
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate in ordered:
        payload = _read_json_file(candidate)
        if payload:
            return payload
    return {}


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(stdout or "").strip())
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _compact_text(value: object, *, limit: int = 140) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if len(text) <= max(int(limit or 1), 1):
        return text
    clipped = max(int(limit or 1) - 3, 1)
    return f"{text[:clipped].rstrip()}..."


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _proactive_source_row_terms(row: Mapping[str, object]) -> set[str]:
    terms: set[str] = set()
    for key in ("channel", "event_type"):
        value = str(row.get(key) or "").strip().lower()
        if value:
            terms.add(value)
    for key in ("payload_keys", "hints"):
        for value in _string_list(row.get(key)):
            normalized = value.strip().lower()
            if normalized:
                terms.add(normalized)
    return terms


def _terms_contain(terms: set[str], *needles: str) -> bool:
    return any(needle in term for term in terms for needle in needles)


def _proactive_source_lane_matches(row: Mapping[str, object], lane_key: str) -> bool:
    terms = _proactive_source_row_terms(row)
    channel = str(row.get("channel") or "").strip().lower()
    event_type = str(row.get("event_type") or "").strip().lower()
    if lane_key == "google_workspace":
        return _terms_contain(terms, "google_workspace", "gmail", "google", "calendar")
    if lane_key == "pocket_ai_audio_transcripts":
        return (
            event_type == "pocket_recording_archive_indexed"
            or _terms_contain(terms, "pocket_ai_audio_transcripts", "pocket", "recording", "transcript")
        )
    if lane_key == "calendar_and_renewal_signals":
        return _terms_contain(terms, "calendar_and_renewal_signals", "calendar", "renewal", "subscription", "appointment")
    if lane_key == "relationship_and_occasion_signals":
        return _terms_contain(
            terms,
            "relationship_and_occasion_signals",
            "relationship",
            "occasion",
            "birthday",
            "anniversary",
            "family",
        )
    if lane_key == "shopping_and_vendor_signals":
        return _terms_contain(
            terms,
            "shopping_and_vendor_signals",
            "shopping",
            "vendor",
            "supplier",
            "provider",
            "purchase",
            "amazon",
            "draft",
            "shortlist",
        )
    if lane_key == "commitment_and_deadline_signals":
        return _terms_contain(
            terms,
            "commitment_and_deadline_signals",
            "commitment",
            "deadline",
            "due",
            "followup",
            "follow-up",
            "appointment",
            "booking",
        )
    if lane_key == "durable_profile_and_location_context":
        return _terms_contain(
            terms,
            "durable_profile_and_location_context",
            "profile",
            "preference",
            "location",
            "locality",
            "address",
            "context",
        )
    if lane_key == "postgres_observations":
        return bool(channel or event_type)
    return False


def _latest_observed_at(rows: list[Mapping[str, object]]) -> str:
    return max((str(row.get("created_at") or "").strip() for row in rows if str(row.get("created_at") or "").strip()), default="")


def _event_types(rows: list[Mapping[str, object]]) -> list[str]:
    values = sorted({str(row.get("event_type") or "").strip() for row in rows if str(row.get("event_type") or "").strip()})
    return values[:8]


def _proactive_source_coverage_report(
    *,
    principal_id: str,
    rows: list[Mapping[str, object]],
    observation_repository: str,
    observed_at: str,
    observation_limit: int,
    source: str = "docker_compose_exec",
) -> dict[str, object]:
    repository = str(observation_repository or "").strip()
    row_count = len(rows)
    lanes: list[dict[str, object]] = []
    for lane in PROACTIVE_SOURCE_COVERAGE_LANES:
        lane_key = str(lane["key"])
        if lane_key == "postgres_observations":
            matched = list(rows) if "postgres" in repository.lower() else []
        else:
            matched = [row for row in rows if _proactive_source_lane_matches(row, lane_key)]
        observed = bool(matched)
        lanes.append(
            {
                "key": lane_key,
                "label": str(lane["label"]),
                "status": "observed" if observed else "not_observed",
                "observed": observed,
                "record_count": len(matched),
                "latest_observed_at": _latest_observed_at(matched),
                "evidence_event_types": _event_types(matched),
                "next_action": "" if observed else str(lane["next_action"]),
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            }
        )
    missing_lane_keys = [str(row["key"]) for row in lanes if not bool(row.get("observed"))]
    observed_lane_count = len(lanes) - len(missing_lane_keys)
    status = "ready" if not missing_lane_keys else "ready_with_gaps" if row_count > 0 else "no_recent_observations"
    return {
        "probe_ok": True,
        "checked": True,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "source": source,
        "observed_at": observed_at,
        "observation_repository": repository,
        "observation_limit": int(observation_limit or 0),
        "observation_row_count": row_count,
        "lane_count": len(lanes),
        "observed_lane_count": observed_lane_count,
        "missing_lane_keys": missing_lane_keys,
        "lanes": lanes,
        "privacy": {
            "raw_rows_exposed": False,
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_credential_exposed": False,
            "source_ids_hashed": True,
        },
    }


def _docker_compose_exec_json(
    *,
    compose_file: str,
    service: str,
    command: list[str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], str, str]:
    completed = subprocess.run(
        ["docker", "compose", "-f", compose_file, "exec", "-T", service, *command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    return (
        int(completed.returncode or 0),
        _json_from_stdout(str(completed.stdout or "")),
        str(completed.stdout or ""),
        str(completed.stderr or ""),
    )


def _http_error_payload(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        payload = {}
    result = dict(payload) if isinstance(payload, dict) else {}
    result.setdefault("status_code", int(getattr(exc, "code", 0) or 0))
    result.setdefault("reason", str(result.get("reason") or getattr(exc, "reason", "") or type(exc).__name__))
    return result


def _runtime_container_name() -> str:
    return _env("EA_RUNTIME_CONTAINER", DEFAULT_RUNTIME_CONTAINER)


def _runtime_container_preflight() -> dict[str, object]:
    container = _runtime_container_name()
    if not container:
        return {}
    code = (
        "import json\n"
        "from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight\n"
        "print(json.dumps(audiobook_runtime_preflight(), sort_keys=True))\n"
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "python3", "-c", code],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(str(proc.stdout or "").strip())
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _container():
    return build_container()


def _provider_display_name(provider_key: str) -> str:
    try:
        state = _container().provider_registry.binding_state(provider_key)
    except Exception:
        state = None
    if state is not None and str(state.display_name or "").strip():
        return str(state.display_name)
    return provider_key.replace("_", " ")


def _normalize_provider_key(value: object) -> str:
    fallback = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    try:
        registry = _container().provider_registry
        normalizer = getattr(registry, "_normalize_provider_key", None)
    except Exception:
        return fallback
    if callable(normalizer):
        normalized = str(normalizer(value) or "").strip()
        return normalized or fallback
    return fallback


def _operator_text_for_provider(report: dict[str, object]) -> str:
    pieces = [
        f"provider={report.get('provider_key')}",
        f"state={report.get('status')}",
    ]
    if report.get("account_label"):
        pieces.append(f"account={report['account_label']}")
    if report.get("remaining") not in (None, "") and report.get("unit"):
        pieces.append(f"remaining={report['remaining']} {report['unit']}")
    if report.get("refresh_at"):
        pieces.append(f"refresh_at={report['refresh_at']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _unmixr_runtime_operational_status(preflight: dict[str, object]) -> str:
    provider_payload = dict(preflight.get("provider") or {})
    checks = {
        str(row.get("key") or "").strip(): str(row.get("status") or "").strip()
        for row in preflight.get("checks") or []
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    }
    blocking_checks = (
        "telegram_audiobook_enabled",
        "jobs_root_durable",
        "jobs_root_writable",
        "external_tts_enabled",
        "unmixr_auto_render_enabled",
        "voice_catalog_configured",
    )
    if any(checks.get(key) == "fail" for key in blocking_checks):
        return "fail"
    if int(provider_payload.get("voice_catalog_count") or 0) < int(provider_payload.get("voice_audition_min_candidates") or 3):
        return "fail"
    if int(provider_payload.get("api_key_slot_count") or 0) <= 0:
        return "fail"
    return "pass"


def probe_provider(provider: str, *, output_format: str = "json") -> dict[str, object]:
    provider_key = _normalize_provider_key(provider)
    if provider_key == "onemin":
        provider_health = _provider_health_report()
        aggregate = _container().onemin_manager.aggregate_snapshot(
            provider_health=provider_health,
            binding_rows=[],
            principal_id="",
        )
        accounts = [dict(row) for row in aggregate.get("accounts") or [] if isinstance(row, dict)]
        latest_snapshot = max(
            (str(row.get("last_billing_snapshot_at") or "").strip() for row in accounts if str(row.get("last_billing_snapshot_at") or "").strip()),
            default="",
        )
        next_topup = min(
            (str(row.get("next_topup_at") or "").strip() for row in accounts if str(row.get("next_topup_at") or "").strip()),
            default="",
        )
        report = {
            "provider_key": "onemin",
            "display_name": _provider_display_name("onemin"),
            "status": str(aggregate.get("state") or "unknown").strip() or "unknown",
            "remaining": aggregate.get("live_remaining_credits_total", aggregate.get("sum_free_credits")),
            "unit": "credits",
            "refresh_at": next_topup or latest_snapshot,
            "observed_at": latest_snapshot or "",
            "account_label": "",
            "source": "app.services.responses_upstream._provider_health_report + onemin_manager.aggregate_snapshot",
            "raw": {
                "account_count": aggregate.get("account_count"),
                "live_positive_balance_account_count": aggregate.get("live_positive_balance_account_count"),
                "estimated_hours_remaining_at_current_pace": aggregate.get("estimated_hours_remaining_at_current_pace"),
                "scope": aggregate.get("scope"),
            },
        }
    elif provider_key == "unmixr":
        preflight = _runtime_container_preflight() or audiobook_runtime_preflight()
        provider_payload = dict(preflight.get("provider") or {})
        report = {
            "provider_key": "unmixr",
            "display_name": _provider_display_name("unmixr"),
            "status": _unmixr_runtime_operational_status(preflight),
            "remaining": provider_payload.get("api_key_slot_count"),
            "unit": "configured_api_key_slots",
            "refresh_at": "",
            "observed_at": str(preflight.get("observed_at") or "").strip(),
            "account_label": "",
            "source": str(preflight.get("contract_name") or "ea.telegram_epub_audiobook_runtime_preflight.v1"),
            "raw": {
                "voice_catalog_count": provider_payload.get("voice_catalog_count"),
                "voice_discovery_enabled": provider_payload.get("voice_discovery_enabled"),
                "unmixr_auto_render_enabled": provider_payload.get("unmixr_auto_render_enabled"),
                "voice_audition_min_candidates": provider_payload.get("voice_audition_min_candidates"),
                "runtime_container": _runtime_container_name(),
                "preflight_status": str(preflight.get("status") or "").strip(),
                "preflight_failed_checks": list(preflight.get("failed_checks") or []),
                "preflight_warned_checks": list(preflight.get("warned_checks") or []),
            },
        }
    else:
        state = _container().provider_registry.binding_state(provider_key)
        report = {
            "provider_key": provider_key,
            "display_name": _provider_display_name(provider_key),
            "status": str(getattr(state, "state", "") or getattr(state, "status", "") or "unknown").strip() or "unknown",
            "remaining": None,
            "unit": "",
            "refresh_at": "",
            "observed_at": str(getattr(state, "updated_at", "") or "").strip(),
            "account_label": "",
            "source": "provider_registry.binding_state",
            "raw": {
                "enabled": bool(getattr(state, "enabled", False)),
                "executable": bool(getattr(state, "executable", False)),
                "health_state": str(getattr(state, "health_state", "") or "").strip(),
                "capabilities": list(getattr(state, "capabilities", ()) or ()),
            },
        }
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_provider(report)
    return report


def probe_proactive_route(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    receipt_path: str = "",
    timeout_seconds: float = 30.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    artifact_probe: dict[str, object] = {}
    if not effective_compose_file or not effective_runtime_service:
        next_action = "configure_proactive_runtime_probe"
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": next_action,
            "route_report": {},
            "live_receipt": {},
            "live_receipt_checked": False,
        }
        report.update(_next_action_surface_fields(next_action))
        if output_format == "operator":
            report["operator_text"] = "proactive route probe failed; configure runtime probe inputs"
        return report

    route_code, route_payload, route_stdout, route_stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=[
            "python",
            "/app/scripts/verify_proactive_ooda.py",
            "--principal-id",
            str(principal_id or "").strip(),
            "--skip-observation-source",
            "--no-require-source",
            "--no-require-telegram",
        ],
        timeout_seconds=timeout_seconds,
    )
    if not route_payload:
        next_action = "inspect_proactive_runtime_container"
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_route_probe_failed:exit_{route_code}",
            "next_action": next_action,
            "route_report": {},
            "live_receipt": {},
            "live_receipt_checked": False,
            "stderr_excerpt": route_stderr.strip()[:200],
            "stdout_excerpt": route_stdout.strip()[:200],
        }
        report.update(_next_action_surface_fields(next_action))
        if output_format == "operator":
            report["operator_text"] = f"proactive route probe failed; inspect {effective_runtime_service}"
        return report

    effective_receipt_path = str(receipt_path or "").strip()
    try:
        artifact_probe = probe_proactive_artifacts(
            compose_file=effective_compose_file,
            runtime_service=effective_runtime_service,
            timeout_seconds=timeout_seconds,
            output_format="json",
        )
    except Exception:
        artifact_probe = {}
    if not effective_receipt_path:
        if bool(artifact_probe.get("probe_ok")) and str(artifact_probe.get("run_receipt_path") or "").strip():
            effective_receipt_path = str(artifact_probe.get("run_receipt_path") or "").strip()

    receipt_command = [
        "python",
        "/app/scripts/verify_proactive_ooda_live_receipt.py",
    ]
    if effective_receipt_path:
        receipt_command.extend(["--receipt-path", effective_receipt_path])
    _, live_receipt_payload, _, _ = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=receipt_command,
        timeout_seconds=timeout_seconds,
    )
    delivery_route = dict(route_payload.get("delivery_route") or {})
    delivery_guard = dict(route_payload.get("delivery_guard") or {})
    runtime_errors = [str(item).strip() for item in list(route_payload.get("errors") or []) if str(item).strip()]
    route_ready = bool(delivery_route.get("ready"))
    route_error = str(delivery_route.get("route_error") or "").strip()
    delivery_state = str(delivery_guard.get("delivery_state") or "").strip()
    deferred_reason = str(delivery_guard.get("deferred_reason") or "").strip()
    if delivery_state == "deferred":
        status = "deferred"
    elif runtime_errors or route_payload.get("ok") is False:
        status = "blocked_local_runtime"
    elif route_ready and route_error:
        status = "ready_with_recovery_action"
    elif route_ready:
        status = "ready"
    else:
        status = "blocked"
    followthrough_next_action = _proactive_approval_followthrough_next_action(
        artifact_probe=artifact_probe,
        route_ready=route_ready,
        selected_channel=str(delivery_route.get("selected_channel") or "").strip(),
        live_receipt_payload=live_receipt_payload,
    )
    route_next_action = str(delivery_route.get("next_action") or "").strip()
    guard_next_action = _proactive_guard_next_action(deferred_reason)
    runtime_next_action = _proactive_runtime_error_next_action(runtime_errors)
    live_receipt_next_action = str(live_receipt_payload.get("delivery_next_action") or "").strip()
    if delivery_state == "deferred":
        next_action = str(
            guard_next_action
            or route_next_action
            or runtime_next_action
            or live_receipt_next_action
            or "inspect_proactive_delivery_route"
        ).strip()
    elif runtime_errors or route_payload.get("ok") is False:
        next_action = str(
            runtime_next_action
            or route_next_action
            or live_receipt_next_action
            or "repair_proactive_runtime_inputs"
        ).strip()
    else:
        next_action = str(
            followthrough_next_action
            or route_next_action
            or guard_next_action
            or runtime_next_action
            or live_receipt_next_action
            or "inspect_proactive_delivery_route"
        ).strip()
    blocking_reason = str(route_error or deferred_reason or (runtime_errors[0] if runtime_errors else "") or "").strip()
    report = {
        "probe_ok": True,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": "docker_compose_exec",
        "delivery_route_ready": route_ready,
        "selected_channel": str(delivery_route.get("selected_channel") or "").strip(),
        "selected_transport": str(delivery_route.get("selected_transport") or "").strip(),
        "selected_by": str(delivery_route.get("selected_by") or "").strip(),
        "available_channels": [str(item or "").strip() for item in list(delivery_route.get("available_channels") or []) if str(item or "").strip()],
        "blocking_reason": blocking_reason,
        "recovery_hint": str(delivery_route.get("recovery_hint") or "").strip(),
        "next_action": next_action,
        "approval_capture_surface_ready": bool(artifact_probe.get("current_packet_live_pending_count") or 0) > 0,
        "approval_capture_surface_pending_count": int(artifact_probe.get("current_packet_live_pending_count") or 0),
        "route_report": route_payload,
        "live_receipt": live_receipt_payload,
        "live_receipt_checked": bool(live_receipt_payload),
    }
    report.update(_next_action_surface_fields(next_action))
    if output_format == "operator":
        route_label = str(delivery_route.get("selected_channel") or "none").strip() or "none"
        recovery = str(delivery_route.get("recovery_hint") or "").strip()
        tail = f"; next={next_action}" if next_action else ""
        if recovery:
            tail = f"{tail}; recovery={recovery}"
        report["operator_text"] = (
            f"proactive_route status={status}; route={route_label}; "
            f"ready={str(route_ready).lower()}; source=docker_compose_exec{tail}"
        )
    return report


def _proactive_guard_next_action(reason: str) -> str:
    normalized = str(reason or "").strip()
    if normalized == "deferred_by_operator_pause":
        return "clear_proactive_operator_pause"
    if normalized == "deferred_by_quiet_hours":
        return "resume_after_quiet_hours"
    if normalized == "deferred_by_interruption_budget":
        return "wait_for_interruption_budget_window"
    if normalized == "deferred_by_unarmed_send":
        return "arm_proactive_send_for_live_delivery"
    return ""


def _proactive_runtime_error_next_action(errors: list[str]) -> str:
    first = str(errors[0] if errors else "").strip()
    if first.startswith("google_workspace_signal_source_unhealthy:"):
        return "reauthorize_google_workspace_binding"
    if first:
        return "repair_proactive_runtime_inputs"
    return ""


def _next_action_surface_fields(action: str) -> dict[str, str]:
    surface = proactive_next_action_surface(action)
    return {
        "next_action_href": str(surface.get("href") or "").strip(),
        "next_action_label": str(surface.get("label") or "").strip(),
        "next_action_method": str(surface.get("method") or "").strip(),
    }


def _proactive_approval_followthrough_next_action(
    *,
    artifact_probe: Mapping[str, object],
    route_ready: bool,
    selected_channel: str,
    live_receipt_payload: Mapping[str, object],
) -> str:
    if not route_ready:
        return ""
    if str(selected_channel or "").strip() != "telegram":
        return ""
    if not bool(live_receipt_payload.get("ok")):
        return ""
    if int(artifact_probe.get("current_packet_live_pending_count") or 0) <= 0:
        return ""
    return "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"


def _sha256_text(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _approval_outcome_matches_current_packet(
    *,
    approval_outcome: Mapping[str, object],
    stage_packet: Mapping[str, object],
    safe_work_result: Mapping[str, object],
) -> bool:
    if not bool(approval_outcome.get("approval_outcome_recorded")):
        return False
    packet_ref = _proactive_stage_packet_ref(stage_packet)
    staged_artifact_ref = _proactive_staged_artifact_ref(safe_work_result)
    expected_packet_hash = _sha256_text(packet_ref)
    expected_artifact_hash = _sha256_text(staged_artifact_ref)
    outcome_packet_hash = str(approval_outcome.get("packet_ref_sha256") or "").strip()
    outcome_artifact_hash = str(approval_outcome.get("staged_artifact_sha256") or "").strip()
    if not outcome_packet_hash and not outcome_artifact_hash:
        return False
    if outcome_packet_hash and outcome_packet_hash != expected_packet_hash:
        return False
    if outcome_artifact_hash and outcome_artifact_hash != expected_artifact_hash:
        return False
    return bool((outcome_packet_hash and expected_packet_hash) or (outcome_artifact_hash and expected_artifact_hash))


def _proactive_current_packet_summary(
    *,
    stage_packet: Mapping[str, object],
    safe_work_result: Mapping[str, object],
    approval_outcome: Mapping[str, object],
    current_packet_callback_outcome: Mapping[str, object] | None = None,
    current_packet_live_pending_count: int,
    current_packet_callback_record_count: int,
    current_packet_callback_latest_status: str,
) -> dict[str, object]:
    stage = dict(stage_packet.get("stage") or {}) if isinstance(stage_packet, Mapping) else {}
    stage_payload = dict(stage.get("payload") or {}) if isinstance(stage.get("payload"), Mapping) else {}
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {}) if isinstance(safe_work_result, Mapping) else {}
    recommended_value = dict(recommended.get("value") or {}) if isinstance(recommended.get("value"), Mapping) else {}
    shortlist = [dict(row) for row in list(safe_work_result.get("shortlist") or []) if isinstance(row, Mapping)]
    outcome_recorded = _approval_outcome_matches_current_packet(
        approval_outcome=approval_outcome,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    if not outcome_recorded and current_packet_callback_outcome:
        outcome_recorded = _approval_outcome_matches_current_packet(
            approval_outcome=current_packet_callback_outcome,
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
        )
    if outcome_recorded:
        status = str(approval_outcome.get("status") or "recorded").strip() or "recorded"
    elif int(current_packet_live_pending_count or 0) > 0:
        status = "pending_approval"
    elif int(current_packet_callback_record_count or 0) > 0:
        status = str(current_packet_callback_latest_status or "callback_recorded").strip() or "callback_recorded"
    elif stage_packet or safe_work_result:
        status = "staged"
    else:
        status = "missing"
    recommended_label = _compact_text(
        recommended_value.get("label")
        or recommended_value.get("title")
        or recommended.get("value")
        or "",
        limit=80,
    )
    recommended_url = _compact_text(
        recommended_value.get("final_url")
        or recommended_value.get("url")
        or recommended_value.get("link")
        or safe_work_result.get("staged_action_url")
        or stage_payload.get("approval_url")
        or "",
        limit=180,
    )
    return {
        "present": bool(stage_packet or safe_work_result),
        "status": status,
        "packet_ref": _proactive_stage_packet_ref(stage_packet),
        "staged_artifact_ref": _proactive_staged_artifact_ref(safe_work_result),
        "observe": _compact_text(stage_packet.get("observe"), limit=160),
        "decide": _compact_text(stage_packet.get("decide"), limit=160),
        "act": _compact_text(stage_packet.get("act"), limit=160),
        "stage_kind": _compact_text(stage.get("kind"), limit=60),
        "stage_summary": _compact_text(stage.get("summary") or safe_work_result.get("summary"), limit=180),
        "approval_prompt": _compact_text(
            safe_work_result.get("approval_prompt")
            or stage_payload.get("approval_prompt")
            or "",
            limit=220,
        ),
        "recommended_label": recommended_label,
        "recommended_url": recommended_url,
        "staged_action_url": _compact_text(
            safe_work_result.get("staged_action_url")
            or stage_payload.get("approval_url")
            or "",
            limit=180,
        ),
        "shortlist_count": len(shortlist),
        "approval_outcome_matches_current_packet": outcome_recorded,
    }


def probe_proactive_artifacts(
    *,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 30.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive artifact probe failed; configure runtime probe inputs"
        return report

    command = [
        "python",
        "-c",
        (
            "import json, os\n"
            "from datetime import datetime, timezone\n"
            "from pathlib import Path\n"
            "from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle\n"
            "from app.services.proactive_ooda_telegram_approval import default_proactive_ooda_telegram_approval_callback_dir\n"
            "root = Path('/app')\n"
            "state_path = os.getenv('EA_PROACTIVE_OODA_STATE_PATH') or '/data/provider-ledger/proactive_ooda_notified.json'\n"
            "receipt_path = os.getenv('EA_PROACTIVE_OODA_RECEIPT_PATH') or ''\n"
            "stage_packet_dir = os.getenv('EA_PROACTIVE_OODA_STAGE_PACKET_DIR') or ''\n"
            "safe_work_result_dir = os.getenv('EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR') or ''\n"
            "bundle = load_runtime_artifact_bundle(root=root, state_path=state_path, receipt_path=receipt_path, stage_packet_dir=stage_packet_dir, safe_work_result_dir=safe_work_result_dir)\n"
            "callback_dir = default_proactive_ooda_telegram_approval_callback_dir(root=root, state_path=state_path, receipt_path=receipt_path)\n"
            "def _text(path):\n"
            "    return '' if path is None else path.as_posix()\n"
            "def _dir_writable(path):\n"
            "    probe = path if path.exists() else path.parent\n"
            "    while not probe.exists() and probe != probe.parent:\n"
            "        probe = probe.parent\n"
            "    try:\n"
            "        return os.access(probe, os.W_OK)\n"
            "    except Exception:\n"
            "        return False\n"
            "def _expires_at_ts(value):\n"
            "    text = str(value or '').strip()\n"
            "    if not text:\n"
            "        return 0.0\n"
            "    if text.endswith('Z'):\n"
            "        text = text[:-1] + '+00:00'\n"
            "    try:\n"
            "        return datetime.fromisoformat(text).timestamp()\n"
            "    except Exception:\n"
            "        return 0.0\n"
            "now_ts = datetime.now(timezone.utc).timestamp()\n"
            "def _is_live(row):\n"
            "    expires = _expires_at_ts(row.get('expires_at'))\n"
            "    return expires <= 0.0 or expires > now_ts\n"
            "def _is_live_pending(row):\n"
            "    return str(row.get('status') or '').strip() == 'pending' and _is_live(row)\n"
            "def _status(row):\n"
            "    return str(row.get('status') or '').strip().lower()\n"
            "def _matches_current(row):\n"
            "    return (\n"
            "        bool(current_packet_ref and current_artifact_ref)\n"
            "        and str(row.get('packet_ref') or '').strip() == current_packet_ref\n"
            "        and str(row.get('staged_artifact_ref') or '').strip() == current_artifact_ref\n"
            "    )\n"
            "callback_rows = []\n"
            "if callback_dir.is_dir():\n"
            "    for candidate in callback_dir.glob('*.json'):\n"
            "        try:\n"
            "            payload = json.loads(candidate.read_text(encoding='utf-8'))\n"
            "        except Exception:\n"
            "            continue\n"
            "        if isinstance(payload, dict):\n"
            "            callback_rows.append(payload)\n"
            "stage_packet = dict(bundle.get('stage_packet') or {})\n"
            "safe_work_result = dict(bundle.get('safe_work_result') or {})\n"
            "current_packet_ref = str(stage_packet.get('packet_ref') or stage_packet.get('packet_id') or '').strip()\n"
            "current_artifact_ref = str(safe_work_result.get('result_ref') or '').strip()\n"
            "if not current_artifact_ref:\n"
            "    result_id = str(safe_work_result.get('result_id') or '').strip()\n"
            "    current_artifact_ref = f'safe_work_result:{result_id}' if result_id else ''\n"
            "current_packet_rows = [\n"
            "    row for row in callback_rows\n"
            "    if str(row.get('packet_ref') or '').strip() == current_packet_ref\n"
            "    and str(row.get('staged_artifact_ref') or '').strip() == current_artifact_ref\n"
            "]\n"
            "current_packet_rows.sort(key=lambda row: str(row.get('created_at') or ''))\n"
            "current_packet_latest = current_packet_rows[-1] if current_packet_rows else {}\n"
            "pending_rows = [row for row in callback_rows if _status(row) == 'pending']\n"
            "current_live_pending_rows = [row for row in current_packet_rows if _is_live_pending(row)]\n"
            "unexpired_pending_rows = [row for row in pending_rows if _is_live(row)]\n"
            "expired_pending_rows = [row for row in pending_rows if not _is_live(row)]\n"
            "noncurrent_pending_rows = [row for row in pending_rows if not _matches_current(row)]\n"
            "stale_pending_rows = [row for row in pending_rows if (not _is_live(row)) or (not _matches_current(row))]\n"
            "recorded_rows = [row for row in callback_rows if _status(row) in ('approved','rejected','deferred','dismissed')]\n"
            "expired_rows = [row for row in callback_rows if _status(row) == 'expired']\n"
            "superseded_rows = [row for row in callback_rows if _status(row) == 'superseded']\n"
            "terminal_rows = [row for row in callback_rows if _status(row) in ('approved','rejected','deferred','dismissed','expired','superseded')]\n"
            "current_pending_rows = [row for row in current_packet_rows if _status(row) == 'pending']\n"
            "current_expired_pending_rows = [row for row in current_pending_rows if not _is_live(row)]\n"
            "current_expired_rows = [row for row in current_packet_rows if _status(row) == 'expired']\n"
            "current_superseded_rows = [row for row in current_packet_rows if _status(row) == 'superseded']\n"
            "print(json.dumps({\n"
            "  'probe_ok': True,\n"
            "  'state_path': _text(bundle.get('state_path')),\n"
            "  'run_receipt_path': _text(bundle.get('run_receipt_path')),\n"
            "  'stage_packet_dir': _text(bundle.get('stage_packet_dir')),\n"
            "  'safe_work_result_dir': _text(bundle.get('safe_work_result_dir')),\n"
            "  'approval_outcome_path': _text(bundle.get('approval_outcome_path')),\n"
            "  'approval_callback_dir': _text(callback_dir),\n"
            "  'approval_callback_dir_exists': callback_dir.is_dir(),\n"
            "  'approval_callback_dir_writable': _dir_writable(callback_dir),\n"
            "  'approval_callback_record_count': len(callback_rows),\n"
            "  'approval_callback_pending_count': len(current_live_pending_rows),\n"
            "  'approval_callback_raw_pending_count': len(pending_rows),\n"
            "  'approval_callback_live_pending_count': len(current_live_pending_rows),\n"
            "  'approval_callback_unexpired_pending_count': len(unexpired_pending_rows),\n"
            "  'approval_callback_noncurrent_pending_count': len(noncurrent_pending_rows),\n"
            "  'approval_callback_expired_pending_count': len(expired_pending_rows),\n"
            "  'approval_callback_stale_pending_count': len(stale_pending_rows),\n"
            "  'approval_callback_recorded_count': len(recorded_rows),\n"
            "  'approval_callback_expired_count': len(expired_rows),\n"
            "  'approval_callback_superseded_count': len(superseded_rows),\n"
            "  'approval_callback_terminal_count': len(terminal_rows),\n"
            "  'current_packet_callback_record_count': len(current_packet_rows),\n"
            "  'current_packet_callback_pending_count': len(current_pending_rows),\n"
            "  'current_packet_callback_raw_pending_count': len(current_pending_rows),\n"
            "  'current_packet_callback_expired_pending_count': len(current_expired_pending_rows),\n"
            "  'current_packet_callback_stale_pending_count': len(current_expired_pending_rows),\n"
            "  'current_packet_callback_recorded_count': sum(1 for row in current_packet_rows if _status(row) in ('approved','rejected','deferred','dismissed')),\n"
            "  'current_packet_callback_expired_count': len(current_expired_rows),\n"
            "  'current_packet_callback_superseded_count': len(current_superseded_rows),\n"
            "  'current_packet_live_callback_record_count': sum(1 for row in current_packet_rows if _is_live(row)),\n"
            "  'current_packet_live_pending_count': sum(1 for row in current_packet_rows if _is_live_pending(row)),\n"
            "  'current_packet_callback_latest_status': str(current_packet_latest.get('status') or '').strip(),\n"
            "  'current_packet_callback_latest_expired': bool(current_packet_latest) and (not _is_live(current_packet_latest)),\n"
            "  'current_packet_callback_outcome': bundle.get('current_packet_callback_outcome') or {},\n"
            "  'stage_packet_path': _text(bundle.get('stage_packet_path')),\n"
            "  'safe_work_result_path': _text(bundle.get('safe_work_result_path')),\n"
            "  'run_receipt': bundle.get('run_receipt') or {},\n"
            "  'stage_packet': bundle.get('stage_packet') or {},\n"
            "  'safe_work_result': bundle.get('safe_work_result') or {},\n"
            "  'approval_outcome': bundle.get('approval_outcome') or {},\n"
            "}, sort_keys=True))\n"
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_artifact_probe_failed:exit_{code}",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive artifact probe failed; inspect {effective_runtime_service}"
        return report

    report = {
        "probe_ok": True,
        "status": "ok",
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": "docker_compose_exec",
        "state_path": str(payload.get("state_path") or "").strip(),
        "run_receipt_path": str(payload.get("run_receipt_path") or "").strip(),
        "stage_packet_dir": str(payload.get("stage_packet_dir") or "").strip(),
        "safe_work_result_dir": str(payload.get("safe_work_result_dir") or "").strip(),
        "approval_outcome_path": str(payload.get("approval_outcome_path") or "").strip(),
        "approval_callback_dir": str(payload.get("approval_callback_dir") or "").strip(),
        "approval_callback_dir_exists": bool(payload.get("approval_callback_dir_exists")),
        "approval_callback_dir_writable": bool(payload.get("approval_callback_dir_writable")),
        "approval_callback_record_count": int(payload.get("approval_callback_record_count") or 0),
        "approval_callback_pending_count": int(payload.get("approval_callback_pending_count") or 0),
        "approval_callback_raw_pending_count": int(payload.get("approval_callback_raw_pending_count") or payload.get("approval_callback_pending_count") or 0),
        "approval_callback_live_pending_count": int(payload.get("approval_callback_live_pending_count") or payload.get("approval_callback_pending_count") or 0),
        "approval_callback_unexpired_pending_count": int(payload.get("approval_callback_unexpired_pending_count") or payload.get("approval_callback_live_pending_count") or 0),
        "approval_callback_noncurrent_pending_count": int(payload.get("approval_callback_noncurrent_pending_count") or 0),
        "approval_callback_expired_pending_count": int(payload.get("approval_callback_expired_pending_count") or 0),
        "approval_callback_stale_pending_count": int(payload.get("approval_callback_stale_pending_count") or 0),
        "approval_callback_recorded_count": int(payload.get("approval_callback_recorded_count") or 0),
        "approval_callback_expired_count": int(payload.get("approval_callback_expired_count") or 0),
        "approval_callback_superseded_count": int(payload.get("approval_callback_superseded_count") or 0),
        "approval_callback_terminal_count": int(payload.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": int(payload.get("current_packet_callback_record_count") or 0),
        "current_packet_callback_pending_count": int(payload.get("current_packet_callback_pending_count") or 0),
        "current_packet_callback_raw_pending_count": int(
            payload.get("current_packet_callback_raw_pending_count") or payload.get("current_packet_callback_pending_count") or 0
        ),
        "current_packet_callback_expired_pending_count": int(payload.get("current_packet_callback_expired_pending_count") or 0),
        "current_packet_callback_stale_pending_count": int(payload.get("current_packet_callback_stale_pending_count") or 0),
        "current_packet_callback_recorded_count": int(payload.get("current_packet_callback_recorded_count") or 0),
        "current_packet_callback_expired_count": int(payload.get("current_packet_callback_expired_count") or 0),
        "current_packet_callback_superseded_count": int(payload.get("current_packet_callback_superseded_count") or 0),
        "current_packet_live_callback_record_count": int(payload.get("current_packet_live_callback_record_count") or 0),
        "current_packet_live_pending_count": int(payload.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_latest_status": str(payload.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(payload.get("current_packet_callback_latest_expired")),
        "current_packet_callback_outcome": dict(payload.get("current_packet_callback_outcome") or {}),
        "stage_packet_path": str(payload.get("stage_packet_path") or "").strip(),
        "safe_work_result_path": str(payload.get("safe_work_result_path") or "").strip(),
        "run_receipt": dict(payload.get("run_receipt") or {}),
        "stage_packet": dict(payload.get("stage_packet") or {}),
        "safe_work_result": dict(payload.get("safe_work_result") or {}),
        "approval_outcome": dict(payload.get("approval_outcome") or {}),
    }
    report["current_packet"] = _proactive_current_packet_summary(
        stage_packet=dict(report.get("stage_packet") or {}),
        safe_work_result=dict(report.get("safe_work_result") or {}),
        approval_outcome=dict(report.get("approval_outcome") or {}),
        current_packet_callback_outcome=dict(report.get("current_packet_callback_outcome") or {}),
        current_packet_live_pending_count=int(report.get("current_packet_live_pending_count") or 0),
        current_packet_callback_record_count=int(report.get("current_packet_callback_record_count") or 0),
        current_packet_callback_latest_status=str(report.get("current_packet_callback_latest_status") or "").strip(),
    )
    report["approval_outcome_matches_current_packet"] = bool(
        dict(report.get("current_packet") or {}).get("approval_outcome_matches_current_packet")
    )
    if output_format == "operator":
        current_packet = dict(report.get("current_packet") or {})
        detail_parts = [
            f"packet_status={str(current_packet.get('status') or '').strip() or 'missing'}",
        ]
        if str(current_packet.get("decide") or "").strip():
            detail_parts.append(f"decide={str(current_packet.get('decide') or '').strip()}")
        if str(current_packet.get("recommended_label") or "").strip():
            detail_parts.append(f"recommend={str(current_packet.get('recommended_label') or '').strip()}")
        if str(current_packet.get("staged_action_url") or "").strip():
            detail_parts.append(f"link={str(current_packet.get('staged_action_url') or '').strip()}")
        report["operator_text"] = (
            "proactive_artifacts "
            f"run_receipt={str(bool(report['run_receipt'])).lower()} "
            f"stage_packet={str(bool(report['stage_packet'])).lower()} "
            f"safe_work_result={str(bool(report['safe_work_result'])).lower()} "
            f"approval_outcome={str(bool(report['approval_outcome'])).lower()} "
            f"approval_outcome_current={str(bool(report['approval_outcome_matches_current_packet'])).lower()} "
            f"approval_surface={str(bool(report['approval_callback_dir_writable'] and report['approval_callback_dir'] and int(report['current_packet_live_pending_count']) > 0)).lower()} "
            f"callback_records={int(report['approval_callback_record_count'])} "
            f"callback_live_pending={int(report['approval_callback_live_pending_count'])} "
            f"callback_stale_pending={int(report['approval_callback_stale_pending_count'])} "
            f"callback_noncurrent_pending={int(report['approval_callback_noncurrent_pending_count'])} "
            f"callback_expired={int(report['approval_callback_expired_count'])} "
            f"callback_superseded={int(report['approval_callback_superseded_count'])} "
            f"current_packet_callbacks={int(report['current_packet_callback_record_count'])} "
            f"current_packet_live_pending={int(report['current_packet_live_pending_count'])} "
            + " ".join(detail_parts)
        )
    return report


def probe_proactive_gmail_draft(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    state_path: str = "",
    receipt_path: str = "",
    stage_packet_dir: str = "",
    safe_work_result_dir: str = "",
    timeout_seconds: float = 30.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = "proactive_gmail_draft probe failed; configure runtime probe inputs"
        return report

    command = [
        "python",
        "-c",
        (
            "import json, sys\n"
            "from app.container import build_container\n"
            "from app.services.proactive_ooda_telegram_approval import inspect_latest_telegram_gmail_draft_followthrough\n"
            "from app.services.proactive_telegram_binding import resolve_proactive_telegram_chat_id\n"
            "from app.services.telegram_delivery import resolve_primary_telegram_binding\n"
            "payload = json.loads(sys.argv[1])\n"
            "container = build_container()\n"
            "report = inspect_latest_telegram_gmail_draft_followthrough(\n"
            "    container=container,\n"
            "    principal_id=str(payload.get('principal_id') or '').strip(),\n"
            "    state_path=str(payload.get('state_path') or '').strip(),\n"
            "    receipt_path=str(payload.get('receipt_path') or '').strip(),\n"
            "    stage_packet_dir=str(payload.get('stage_packet_dir') or '').strip(),\n"
            "    safe_work_result_dir=str(payload.get('safe_work_result_dir') or '').strip(),\n"
            ")\n"
            "binding = resolve_primary_telegram_binding(container.tool_runtime, principal_id=str(payload.get('principal_id') or '').strip())\n"
            "metadata = dict(getattr(binding, 'auth_metadata_json', {}) or {}) if binding is not None else {}\n"
            "primary_chat_id = str(metadata.get('default_chat_ref') or getattr(binding, 'external_account_ref', '') or '').strip() if binding is not None else ''\n"
            "report.update({\n"
            "    'telegram_primary_binding_principal_id': str(getattr(binding, 'principal_id', '') or '').strip() if binding is not None else '',\n"
            "    'telegram_primary_chat_id': primary_chat_id,\n"
            "    'telegram_proactive_chat_id': resolve_proactive_telegram_chat_id(principal_id=str(payload.get('principal_id') or '').strip()),\n"
            "})\n"
            "print(json.dumps(report, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "state_path": str(state_path or "").strip(),
                "receipt_path": str(receipt_path or "").strip(),
                "stage_packet_dir": str(stage_packet_dir or "").strip(),
                "safe_work_result_dir": str(safe_work_result_dir or "").strip(),
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_gmail_draft_probe_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = f"proactive_gmail_draft probe failed; inspect {effective_runtime_service}"
        return report

    reason = str(payload.get("reason") or "").strip()
    next_action = _proactive_gmail_draft_next_action(reason)
    next_action_surface = dict(payload.get("next_action_surface") or {})
    if not next_action_surface and next_action:
        next_action_surface = _next_action_surface_fields(next_action)
    report = {
        "probe_ok": True,
        "status": str(payload.get("status") or "").strip() or "unknown",
        "principal_id": str(principal_id or "").strip(),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": "docker_compose_exec",
        "staged_principal_id": str(payload.get("principal_id") or "").strip(),
        "packet_ref": str(payload.get("packet_ref") or "").strip(),
        "staged_artifact_ref": str(payload.get("staged_artifact_ref") or "").strip(),
        "source_observation_id": str(payload.get("source_observation_id") or "").strip(),
        "source_created_at": str(payload.get("source_created_at") or "").strip(),
        "action": str(payload.get("action") or "").strip(),
        "work_type": str(payload.get("work_type") or "").strip(),
        "blocking_reason": reason,
        "recipient_email_present": bool(str(payload.get("recipient_email") or "").strip()),
        "draft_body_present": bool(payload.get("draft_body_present")),
        "subject": str(payload.get("subject") or "").strip(),
        "google_binding_id": str(payload.get("google_binding_id") or "").strip(),
        "google_binding_principal_id": str(payload.get("google_binding_principal_id") or "").strip(),
        "google_account_email": str(payload.get("google_account_email") or "").strip(),
        "expected_google_account_email": str(payload.get("expected_google_account_email") or "").strip(),
        "google_token_status": str(payload.get("google_token_status") or "").strip(),
        "google_reauth_required_reason": str(payload.get("google_reauth_required_reason") or "").strip(),
        "google_gmail_draft_scope_present": bool(payload.get("google_gmail_draft_scope_present")),
        "google_account_count": int(payload.get("google_account_count") or 0),
        "execution_observation_present": bool(payload.get("execution_observation_present")),
        "execution_status": str(payload.get("execution_status") or "").strip(),
        "execution_saved_at": str(payload.get("execution_saved_at") or "").strip(),
        "recipient_email_hash_present": bool(payload.get("recipient_email_sha256_present")),
        "gmail_draft_id_hash_present": bool(payload.get("gmail_draft_id_sha256_present")),
        "gmail_message_id_hash_present": bool(payload.get("gmail_message_id_sha256_present")),
        "draft_folder_url_hash_present": bool(payload.get("draft_folder_url_sha256_present")),
        "raw_execution_payload_exposed": bool(payload.get("raw_execution_payload_exposed")),
        "telegram_primary_binding_principal_id": str(payload.get("telegram_primary_binding_principal_id") or "").strip(),
        "telegram_primary_chat_id": str(payload.get("telegram_primary_chat_id") or "").strip(),
        "telegram_proactive_chat_id": str(payload.get("telegram_proactive_chat_id") or "").strip(),
        "next_action": next_action,
        "next_action_href": str(next_action_surface.get("href") or "").strip(),
        "next_action_label": str(next_action_surface.get("label") or "").strip(),
        "next_action_method": str(next_action_surface.get("method") or "").strip(),
        "raw": payload,
    }
    if output_format == "operator":
        pieces = [
            f"proactive_gmail_draft status={report['status']}",
            f"action={str(report.get('action') or '').strip() or 'none'}",
        ]
        if str(report.get("google_account_email") or "").strip():
            pieces.append(f"account={report['google_account_email']}")
        if str(report.get("expected_google_account_email") or "").strip():
            pieces.append(f"expected={report['expected_google_account_email']}")
        if str(report.get("google_token_status") or "").strip():
            pieces.append(f"token={report['google_token_status']}")
        if bool(report.get("execution_observation_present")):
            pieces.append(f"execution={str(report.get('execution_status') or '').strip() or 'recorded'}")
        if bool(report.get("gmail_draft_id_hash_present")):
            pieces.append("draft_hash=true")
        if str(report.get("telegram_proactive_chat_id") or "").strip():
            pieces.append(f"proactive_chat={report['telegram_proactive_chat_id']}")
        if str(report.get("blocking_reason") or "").strip():
            pieces.append(f"reason={report['blocking_reason']}")
        if str(report.get("next_action") or "").strip():
            pieces.append(f"next={report['next_action']}")
        report["operator_text"] = "; ".join(pieces)
    return report


def _proactive_stage_packet_ref(stage_packet: Mapping[str, object]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _proactive_staged_artifact_ref(safe_work_result: Mapping[str, object]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _normalize_proactive_outcome(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"approve", "approved", "accept", "accepted"}:
        return "approved"
    if normalized in {"reject", "rejected", "deny", "denied", "decline", "declined"}:
        return "rejected"
    if normalized in {"defer", "deferred", "later"}:
        return "deferred"
    if normalized in {"dismiss", "dismissed"}:
        return "dismissed"
    return normalized or "missing"


def _proactive_gmail_draft_next_action(reason: str) -> str:
    normalized = str(reason or "").strip().lower()
    if normalized in {
        "google_oauth_binding_not_found",
        "google_oauth_invalid_grant",
        "google_oauth_refresh_failed",
        "google_oauth_account_mismatch",
        "google_gmail_draft_scope_missing",
        "google_gmail_refresh_token_missing",
        "google_gmail_access_token_missing",
        "google_gmail_sender_missing",
    }:
        return "reauthorize_google_workspace_binding"
    if normalized in {"approved_stage_packet_missing", "approved_safe_work_result_missing", "staged_refs_missing"}:
        return "inspect_proactive_runtime_artifacts"
    if normalized == "approved_draft_body_missing":
        return "inspect_proactive_runtime_artifacts"
    return ""


def probe_proactive_source_coverage(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    observation_limit: int = 400,
    timeout_seconds: float = 30.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "checked": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
            "lanes": [],
            "missing_lane_keys": list(PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = "proactive_source_coverage probe failed; configure runtime probe inputs"
        return report

    limit = max(1, min(5000, int(observation_limit or 400)))
    command = [
        "python",
        "-c",
        (
            "import hashlib, json, sys\n"
            "from app.container import build_container\n"
            "payload = json.loads(sys.argv[1])\n"
            "principal_id = str(payload.get('principal_id') or '').strip()\n"
            "limit = max(1, min(5000, int(payload.get('observation_limit') or 400)))\n"
            "container = build_container()\n"
            "runtime = container.channel_runtime\n"
            "repo = getattr(runtime, '_observations', None)\n"
            "def _sha(value):\n"
            "    text = str(value or '').strip()\n"
            "    return hashlib.sha256(text.encode('utf-8')).hexdigest() if text else ''\n"
            "def _walk(value):\n"
            "    if isinstance(value, dict):\n"
            "        for key, item in value.items():\n"
            "            yield str(key or '')\n"
            "            yield from _walk(item)\n"
            "    elif isinstance(value, (list, tuple, set)):\n"
            "        for item in value:\n"
            "            yield from _walk(item)\n"
            "    elif isinstance(value, (str, int, float, bool)):\n"
            "        yield str(value or '')\n"
            "def _hints(row, payload):\n"
            "    text = ' '.join([str(getattr(row, 'channel', '') or ''), str(getattr(row, 'event_type', '') or ''), str(getattr(row, 'source_id', '') or ''), str(getattr(row, 'external_id', '') or ''), ' '.join(_walk(payload))]).lower()\n"
            "    specs = {\n"
            "        'google_workspace': ('google', 'gmail', 'calendar', 'workspace'),\n"
            "        'pocket_ai_audio_transcripts': ('pocket', 'pocket.ai', 'recording', 'transcript'),\n"
            "        'calendar_and_renewal_signals': ('calendar', 'renewal', 'subscription', 'appointment'),\n"
            "        'relationship_and_occasion_signals': ('relationship', 'occasion', 'birthday', 'anniversary', 'wife', 'family'),\n"
            "        'shopping_and_vendor_signals': ('shopping', 'vendor', 'supplier', 'provider', 'purchase', 'amazon', 'shortlist', 'draft'),\n"
            "        'commitment_and_deadline_signals': ('commitment', 'deadline', 'due', 'followup', 'follow-up', 'appointment', 'booking'),\n"
            "        'durable_profile_and_location_context': ('profile', 'preference', 'location', 'locality', 'address', 'context'),\n"
            "    }\n"
            "    return sorted(key for key, needles in specs.items() if any(needle in text for needle in needles))\n"
            "rows = []\n"
            "for row in runtime.list_recent_observations(limit=limit, principal_id=principal_id):\n"
            "    row_payload = dict(getattr(row, 'payload', {}) or {})\n"
            "    rows.append({\n"
            "        'channel': str(getattr(row, 'channel', '') or '').strip(),\n"
            "        'event_type': str(getattr(row, 'event_type', '') or '').strip(),\n"
            "        'created_at': str(getattr(row, 'created_at', '') or '').strip(),\n"
            "        'payload_keys': sorted(str(key) for key in row_payload.keys()),\n"
            "        'hints': _hints(row, row_payload),\n"
            "        'source_id_sha256_present': bool(_sha(getattr(row, 'source_id', '') or '')),\n"
            "        'external_id_sha256_present': bool(_sha(getattr(row, 'external_id', '') or '')),\n"
            "        'raw_payload_exposed': False,\n"
            "    })\n"
            "print(json.dumps({\n"
            "    'probe_ok': True,\n"
            "    'observation_repository': type(repo).__name__ if repo is not None else '',\n"
            "    'rows': rows,\n"
            "}, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "observation_limit": limit,
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            "probe_ok": False,
            "checked": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_source_coverage_probe_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
            "lanes": [],
            "missing_lane_keys": list(PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = f"proactive_source_coverage probe failed; inspect {effective_runtime_service}"
        return report

    rows = [dict(row) for row in list(payload.get("rows") or []) if isinstance(row, Mapping)]
    report = _proactive_source_coverage_report(
        principal_id=str(principal_id or "").strip(),
        rows=rows,
        observation_repository=str(payload.get("observation_repository") or "").strip(),
        observed_at=observed_at,
        observation_limit=limit,
    )
    missing_next_action = next(
        (str(dict(lane).get("next_action") or "").strip() for lane in list(report.get("lanes") or []) if not bool(dict(lane).get("observed"))),
        "",
    )
    report.update(
        {
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "blocking_reason": "",
            "next_action": missing_next_action,
        }
    )
    report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
    if output_format == "operator":
        missing = [str(item) for item in list(report.get("missing_lane_keys") or [])]
        missing_text = ",".join(missing[:4])
        if len(missing) > 4:
            missing_text += f"+{len(missing) - 4}"
        report["operator_text"] = (
            f"proactive_source_coverage status={report['status']}; "
            f"observed={int(report['observed_lane_count'])}/{int(report['lane_count'])}; "
            f"rows={int(report['observation_row_count'])}; missing={missing_text or 'none'}"
        )
    return report


def _pocket_transcript_sync_next_action(reason: str) -> str:
    normalized = str(reason or "").strip()
    detail = normalized.split(":", 1)[1].strip() if ":" in normalized else normalized
    if detail == "pocket_api_key_missing":
        return "configure_pocket_api_key"
    if detail.startswith("pocket_api_http_429:") or normalized.startswith("RuntimeError:pocket_api_http_429:"):
        return "retry_pocket_sync_after_provider_cooldown"
    if detail.startswith("pocket_api_unreachable:") or normalized.startswith("RuntimeError:pocket_api_unreachable:"):
        return "inspect_pocket_api_connectivity"
    if normalized:
        return "inspect_pocket_sync_runtime"
    return ""


def sync_pocket_transcripts(
    *,
    principal_id: str,
    mode: str = "incremental",
    limit: int = 10,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 120.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    normalized_mode = str(mode or "incremental").strip().lower()
    if normalized_mode not in {"incremental", "backfill"}:
        normalized_mode = "incremental"
    bounded_limit = max(0 if normalized_mode == "backfill" else 1, min(int(limit or 10), 250 if normalized_mode == "backfill" else 100))
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "synced": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "mode": normalized_mode,
            "limit": bounded_limit,
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_archive_path_exposed": False,
            "raw_credential_exposed": False,
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = "pocket_transcript_sync status=probe_failed; next=configure_proactive_runtime_probe"
        return report

    command = [
        "python",
        "-c",
        (
            "import json, os, sys\n"
            "from app.container import build_container\n"
            "from app.product.service import build_product_service\n"
            "payload = json.loads(sys.argv[1])\n"
            "os.environ['EA_POCKET_ASSISTANT_AUTO_ACTIONS'] = 'manual_followup,none'\n"
            "os.environ['EA_POCKET_ASSISTANT_DANGEROUS_AUTO_ACTIONS'] = ''\n"
            "container = build_container()\n"
            "service = build_product_service(container)\n"
            "def _safe_reason(exc):\n"
            "    text = ' '.join(str(exc or '').split())[:200]\n"
            "    for secret_name in ('POCKET_API_KEY', 'EA_POCKET_API_KEY'):\n"
            "        secret = str(os.environ.get(secret_name) or '').strip()\n"
            "        if secret:\n"
            "            text = text.replace(secret, '[redacted]')\n"
            "    return f'{type(exc).__name__}:{text}' if text else type(exc).__name__\n"
            "principal_id = str(payload.get('principal_id') or '').strip()\n"
            "actor = str(payload.get('actor') or 'ea-live-ops').strip()\n"
            "mode = str(payload.get('mode') or 'incremental').strip()\n"
            "limit = int(payload.get('limit') or 10)\n"
            "keys = (\n"
            "    'generated_at','mode','total','synced_total','deduplicated_total','suppressed_total','failed_total',\n"
            "    'recording_total','staging_suppressed_total','archived_total','archive_dismissed_total','archive_failed_total',\n"
            "    'teable_index_status','teable_index_blocked_reason','teable_index_row_total','teable_index_sync_attempted',\n"
            "    'preference_evidence_total','preference_evidence_applied_total','assistant_trigger_total',\n"
            "    'assistant_trigger_executed_total','assistant_trigger_blocked_total','cursor_used','cursor_persisted',\n"
            "    'cursor_updated_at','cursor_recording_id','cursor_advanced','scan_truncated','location_matched_total',\n"
            "    'location_unmatched_total'\n"
            ")\n"
            "try:\n"
            "    if mode == 'backfill':\n"
            "        result = service.backfill_pocket_recordings(principal_id=principal_id, actor=actor, limit=limit)\n"
            "    else:\n"
            "        result = service.sync_pocket_recordings(principal_id=principal_id, actor=actor, limit=limit)\n"
            "    summary = {key: result.get(key) for key in keys if key in result}\n"
            "    print(json.dumps({\n"
            "        'ok': True,\n"
            "        'summary': summary,\n"
            "        'assistant_auto_actions': 'manual_followup,none',\n"
            "        'dangerous_auto_actions_enabled': False,\n"
            "    }, sort_keys=True))\n"
            "except RuntimeError as exc:\n"
            "    print(json.dumps({\n"
            "        'ok': False,\n"
            "        'reason': _safe_reason(exc),\n"
            "        'assistant_auto_actions': 'manual_followup,none',\n"
            "        'dangerous_auto_actions_enabled': False,\n"
            "    }, sort_keys=True))\n"
            "except Exception as exc:\n"
            "    print(json.dumps({\n"
            "        'ok': False,\n"
            "        'reason': _safe_reason(exc),\n"
            "        'assistant_auto_actions': 'manual_followup,none',\n"
            "        'dangerous_auto_actions_enabled': False,\n"
            "    }, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "actor": "ea-live-ops",
                "mode": normalized_mode,
                "limit": bounded_limit,
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            "probe_ok": False,
            "synced": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "mode": normalized_mode,
            "limit": bounded_limit,
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_pocket_transcript_sync_failed:exit_{code}",
            "next_action": "inspect_pocket_sync_runtime",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_archive_path_exposed": False,
            "raw_credential_exposed": False,
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = f"pocket_transcript_sync status=probe_failed; next=inspect_pocket_sync_runtime"
        return report

    summary = dict(payload.get("summary") or {})
    reason = str(payload.get("reason") or "").strip()
    ok = bool(payload.get("ok"))
    failed_total = int(summary.get("failed_total") or 0)
    archive_failed_total = int(summary.get("archive_failed_total") or 0)
    recording_total = int(summary.get("recording_total") or 0)
    teable_status = str(summary.get("teable_index_status") or "").strip()
    teable_blocked_reason = str(summary.get("teable_index_blocked_reason") or "").strip()
    if not ok:
        status = "throttled" if "pocket_api_http_429:" in reason else "blocked"
    elif failed_total or archive_failed_total or teable_status == "blocked":
        status = "completed_with_gaps"
    elif recording_total == 0:
        status = "no_new_recordings"
    else:
        status = "synced"
    next_action = _pocket_transcript_sync_next_action(reason)
    if ok and status == "completed_with_gaps":
        next_action = "inspect_pocket_sync_runtime"
    if ok and status in {"synced", "no_new_recordings"}:
        next_action = "probe_proactive_source_coverage"
    if teable_status == "blocked" and teable_blocked_reason:
        next_action = "inspect_teable_projection"
    report = {
        "probe_ok": True,
        "synced": ok,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "mode": normalized_mode,
        "limit": bounded_limit,
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": "docker_compose_exec",
        "blocking_reason": reason or teable_blocked_reason,
        "next_action": next_action,
        "recording_total": recording_total,
        "synced_total": int(summary.get("synced_total") or 0),
        "deduplicated_total": int(summary.get("deduplicated_total") or 0),
        "suppressed_total": int(summary.get("suppressed_total") or 0),
        "failed_total": failed_total,
        "archived_total": int(summary.get("archived_total") or 0),
        "archive_dismissed_total": int(summary.get("archive_dismissed_total") or 0),
        "archive_failed_total": archive_failed_total,
        "teable_index_status": teable_status,
        "teable_index_row_total": int(summary.get("teable_index_row_total") or 0),
        "teable_index_sync_attempted": bool(summary.get("teable_index_sync_attempted")),
        "assistant_trigger_total": int(summary.get("assistant_trigger_total") or 0),
        "assistant_trigger_executed_total": int(summary.get("assistant_trigger_executed_total") or 0),
        "assistant_trigger_blocked_total": int(summary.get("assistant_trigger_blocked_total") or 0),
        "assistant_auto_actions": str(payload.get("assistant_auto_actions") or "").strip(),
        "dangerous_auto_actions_enabled": bool(payload.get("dangerous_auto_actions_enabled")),
        "cursor_used": bool(summary.get("cursor_used")),
        "cursor_persisted": bool(summary.get("cursor_persisted")),
        "cursor_advanced": bool(summary.get("cursor_advanced")),
        "scan_truncated": bool(summary.get("scan_truncated")),
        "location_matched_total": int(summary.get("location_matched_total") or 0),
        "location_unmatched_total": int(summary.get("location_unmatched_total") or 0),
        "raw_payload_exposed": False,
        "raw_transcript_text_exposed": False,
        "raw_archive_path_exposed": False,
        "raw_credential_exposed": False,
    }
    report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
    if output_format == "operator":
        pieces = [
            f"pocket_transcript_sync status={status}",
            f"mode={normalized_mode}",
            f"recordings={recording_total}",
            f"synced={int(report['synced_total'])}",
            f"archived={int(report['archived_total'])}",
            f"teable={teable_status or 'unknown'}",
        ]
        if reason or teable_blocked_reason:
            pieces.append(f"reason={reason or teable_blocked_reason}")
        if str(report.get("next_action") or "").strip():
            pieces.append(f"next={report['next_action']}")
        report["operator_text"] = "; ".join(pieces)
    return report


def record_proactive_approval(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str = "operator-cli",
    source_kind: str = "operator",
    packet_ref: str = "",
    staged_artifact_ref: str = "",
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    artifact_probe = probe_proactive_artifacts(
        compose_file=effective_compose_file,
        runtime_service=effective_runtime_service,
        timeout_seconds=timeout_seconds,
        output_format="json",
    )
    normalized_outcome = _normalize_proactive_outcome(outcome)
    resolved_packet_ref = str(packet_ref or "").strip() or _proactive_stage_packet_ref(dict(artifact_probe.get("stage_packet") or {}))
    resolved_staged_artifact_ref = str(staged_artifact_ref or "").strip() or _proactive_staged_artifact_ref(
        dict(artifact_probe.get("safe_work_result") or {})
    )
    base_report: dict[str, object] = {
        "recorded": False,
        "reason": "",
        "principal_id": str(principal_id or "").strip(),
        "outcome": normalized_outcome,
        "accepted": normalized_outcome == "approved",
        "evidence_present": bool(str(evidence or "").strip()),
        "actor": str(actor or "").strip(),
        "source_kind": str(source_kind or "").strip() or "operator",
        "packet_ref": resolved_packet_ref,
        "staged_artifact_ref": resolved_staged_artifact_ref,
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "artifact_probe": artifact_probe,
        "approval_capture_surface_ready": bool(artifact_probe.get("current_packet_live_pending_count") or 0) > 0,
        "approval_capture_surface_pending_count": int(artifact_probe.get("current_packet_live_pending_count") or 0),
    }
    if not bool(artifact_probe.get("probe_ok")):
        report = {
            **base_report,
            "reason": "artifact_probe_failed",
            "blocking_reason": str(artifact_probe.get("blocking_reason") or "artifact_probe_failed").strip(),
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_approval status=probe_failed; next=inspect_proactive_runtime_artifacts"
        return report
    if not resolved_packet_ref or not resolved_staged_artifact_ref:
        report = {
            **base_report,
            "reason": "current_runtime_packet_unresolved",
            "blocking_reason": "current_runtime_packet_unresolved",
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_approval status=unresolved; next=inspect_proactive_runtime_artifacts"
        return report
    if dry_run:
        report = {
            **base_report,
            "reason": "dry_run",
            "next_action": "run_without_dry_run_to_record_outcome",
        }
        if output_format == "operator":
            report["operator_text"] = (
                "proactive_approval status=dry_run; "
                f"outcome={normalized_outcome}; packet_ref={resolved_packet_ref}"
            )
        return report

    command = [
        "python",
        "-c",
        (
            "import json, sys\n"
            "from pathlib import Path\n"
            "for value in ('/app', '/app/ea', '/app/scripts'):\n"
            "    if value not in sys.path:\n"
            "        sys.path.insert(0, value)\n"
            "from app.services.proactive_ooda_approval_capture import finalize_proactive_ooda_approval_outcome\n"
            "payload = json.loads(sys.argv[1])\n"
            "result = finalize_proactive_ooda_approval_outcome(**payload)\n"
            "def _jsonify(value):\n"
            "    if isinstance(value, Path):\n"
            "        return value.as_posix()\n"
            "    if isinstance(value, dict):\n"
            "        return {k: _jsonify(v) for k, v in value.items()}\n"
            "    if isinstance(value, (list, tuple)):\n"
            "        return [_jsonify(v) for v in value]\n"
            "    return value\n"
            "print(json.dumps(_jsonify(result), sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "outcome": normalized_outcome,
                "evidence": str(evidence or "").strip(),
                "actor": str(actor or "").strip(),
                "packet_ref": resolved_packet_ref,
                "staged_artifact_ref": resolved_staged_artifact_ref,
                "source_kind": str(source_kind or "").strip() or "operator",
                "state_path": str(artifact_probe.get("state_path") or "").strip(),
                "receipt_path": str(artifact_probe.get("run_receipt_path") or "").strip(),
                "stage_packet_dir": str(artifact_probe.get("stage_packet_dir") or "").strip(),
                "safe_work_result_dir": str(artifact_probe.get("safe_work_result_dir") or "").strip(),
                "approval_outcome_path": str(artifact_probe.get("approval_outcome_path") or "").strip(),
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            **base_report,
            "reason": f"record_failed:exit_{code}",
            "blocking_reason": f"record_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive_approval status=record_failed; next=inspect {effective_runtime_service}"
        return report

    approval_outcome = dict(payload.get("approval_outcome") or {})
    teable_sync = dict(payload.get("teable_sync") or {})
    report = {
        **base_report,
        "recorded": bool(approval_outcome.get("approval_outcome_recorded")),
        "reason": "recorded" if bool(approval_outcome.get("approval_outcome_recorded")) else "record_not_confirmed",
        "accepted": bool(approval_outcome.get("accepted")),
        "approval_outcome": approval_outcome,
        "approval_outcome_id": str(approval_outcome.get("outcome_id") or "").strip(),
        "approval_outcome_status": str(approval_outcome.get("status") or "").strip(),
        "approval_outcome_path": str(payload.get("approval_outcome_path") or "").strip(),
        "operator_status_path": str(payload.get("operator_status_path") or "").strip(),
        "gold_acceptance_path": str(payload.get("gold_acceptance_path") or "").strip(),
        "teable_sync": teable_sync,
    }
    if output_format == "operator":
        teable_status = str(teable_sync.get("status") or "unknown").strip() or "unknown"
        report["operator_text"] = (
            "proactive_approval status=recorded; "
            f"outcome={normalized_outcome}; accepted={str(bool(approval_outcome.get('accepted'))).lower()}; "
            f"teable={teable_status}"
        )
    return report


def reissue_proactive_approval(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    force: bool = False,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    artifact_probe = probe_proactive_artifacts(
        compose_file=effective_compose_file,
        runtime_service=effective_runtime_service,
        timeout_seconds=timeout_seconds,
        output_format="json",
    )
    base_report: dict[str, object] = {
        "sent": False,
        "reason": "",
        "principal_id": str(principal_id or "").strip(),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "artifact_probe": artifact_probe,
        "approval_capture_surface_ready_before": bool(artifact_probe.get("current_packet_live_pending_count") or 0) > 0,
        "approval_capture_surface_pending_count_before": int(artifact_probe.get("current_packet_live_pending_count") or 0),
    }
    if not bool(artifact_probe.get("probe_ok")):
        report = {
            **base_report,
            "reason": "artifact_probe_failed",
            "blocking_reason": str(artifact_probe.get("blocking_reason") or "artifact_probe_failed").strip(),
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_approval_reissue status=probe_failed; next=inspect_proactive_runtime_artifacts"
        return report

    command = [
        "python",
        "/app/scripts/reissue_proactive_ooda_approval.py",
        "--principal-id",
        str(principal_id or "").strip(),
        "--state-path",
        str(artifact_probe.get("state_path") or "").strip(),
        "--receipt-path",
        str(artifact_probe.get("run_receipt_path") or "").strip(),
        "--stage-packet-dir",
        str(artifact_probe.get("stage_packet_dir") or "").strip(),
        "--safe-work-result-dir",
        str(artifact_probe.get("safe_work_result_dir") or "").strip(),
    ]
    if dry_run:
        command.append("--dry-run")
    if force:
        command.append("--force")
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            **base_report,
            "reason": f"reissue_failed:exit_{code}",
            "blocking_reason": f"reissue_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive_approval_reissue status=failed; next=inspect {effective_runtime_service}"
        return report
    status = str(payload.get("status") or "").strip()
    report = {
        **base_report,
        "sent": status == "sent",
        "reason": str(payload.get("reason") or status or "unknown").strip(),
        "status": status,
        "message_count": int(payload.get("message_count") or 0),
        "message_ids": [
            str(item or "").strip()
            for item in list(payload.get("message_ids") or [])
            if str(item or "").strip()
        ],
        "approval_surface": dict(payload.get("approval_surface") or {}),
        "packet_ref_sha256": str(payload.get("packet_ref_sha256") or "").strip(),
        "staged_artifact_ref_sha256": str(payload.get("staged_artifact_ref_sha256") or "").strip(),
        "approval_prompt_sha256": str(payload.get("approval_prompt_sha256") or "").strip(),
        "staged_action_url_sha256": str(payload.get("staged_action_url_sha256") or "").strip(),
        "has_staged_action_url": bool(payload.get("has_staged_action_url")),
        "stage_kind": str(payload.get("stage_kind") or "").strip(),
        "safe_work_status": str(payload.get("safe_work_status") or "").strip(),
    }
    if output_format == "operator":
        report["operator_text"] = (
            "proactive_approval_reissue "
            f"status={status or 'unknown'} "
            f"sent={str(status == 'sent').lower()} "
            f"messages={int(report['message_count'])} "
            f"surface={str(bool(dict(report.get('approval_surface') or {}).get('present'))).lower()}"
        )
    return report


def _load_whatsapp_binding(args: argparse.Namespace):
    binding_path = str(getattr(args, "binding_json", "") or "").strip()
    database_url = str(args.database_url or _env("DATABASE_URL")).strip()
    binding_id = str(args.binding_id or "").strip()
    principal_id = str(args.principal_id or "").strip()
    if binding_path:
        payload = readiness_script._load_json_file(binding_path)
        binding = readiness_script._binding_from_json(payload, binding_id=binding_id)
        if binding is None and readiness_script._should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
            binding = readiness_script._latest_enabled_binding_from_json(payload)
        if binding is not None:
            return binding
    if not database_url:
        return None
    binding = readiness_script._binding_from_postgres(
        database_url,
        binding_id=binding_id,
        principal_id=principal_id,
    )
    if binding is None and readiness_script._should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
        binding = readiness_script._binding_from_postgres(database_url, binding_id="", principal_id="")
    return binding


def _session_headers_from_binding(binding: Any | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        token = str(config.get("token") or "").strip()
        header_name = str(config.get("auth_header_name") or "Authorization").strip() or "Authorization"
        header_prefix = str(config.get("auth_header_prefix") or "").strip()
    else:
        token = _env("EA_WHATSAPP_WEB_SESSION_API_TOKEN")
        header_name = _env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization") or "Authorization"
        header_prefix = _env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer ")
    if token:
        headers[header_name] = f"{header_prefix}{token}".strip()
    return headers


def _session_api_base_url(binding: Any | None, explicit_base_url: str = "") -> str:
    if str(explicit_base_url or "").strip():
        return str(explicit_base_url).rstrip("/")
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        template = str(config.get("endpoint_template") or "").strip()
        if "/sessions/" in template:
            return template.split("/sessions/", 1)[0].rstrip("/")
    return _env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL).rstrip("/")


def _whatsapp_delivery_config(binding: Any | None) -> dict[str, Any]:
    if binding is None:
        return {}
    try:
        return dict(whatsapp_web_session_delivery.resolve_whatsapp_web_session_delivery_config(binding))
    except Exception:
        return {}


def _session_ref(binding: Any | None, explicit_session_ref: str = "") -> str:
    if str(explicit_session_ref or "").strip():
        return str(explicit_session_ref).strip()
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        configured = str(config.get("session_ref") or "").strip()
        if configured:
            return configured
    env_value = _env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF")
    if env_value:
        return env_value
    receipt = _whatsapp_readiness_receipt()
    return str(receipt.get("effective_session_ref") or receipt.get("session_ref") or "").strip()


def _sidecar_get(*, binding: Any | None, suffix: str, session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return _request_json(
        method="GET",
        url=f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}",
        headers=_session_headers_from_binding(binding),
        timeout=timeout_seconds,
    )


def _sidecar_post(*, binding: Any | None, suffix: str, body: dict[str, object], session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return _request_json(
        method="POST",
        url=f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}",
        headers=_session_headers_from_binding(binding),
        body=body,
        timeout=timeout_seconds,
    )


def _match_route(route: dict[str, object], phone_hint: str) -> bool:
    normalized_hint = _normalize_phone_hint(phone_hint)
    if normalized_hint in {"", "*", "default"}:
        return str(route.get("route_key") or "").strip() in {"default", "*"}
    candidates = {
        _digits(route.get("inbound_number_digits")),
        _digits(route.get("route_key")),
    }
    return any(candidate.endswith(normalized_hint) for candidate in candidates if candidate)


def _recent_chat_ref_for_hint(conversations_payload: dict[str, object], phone_hint: str) -> str:
    return _recent_conversation_match(conversations_payload, phone_hint).get("chat_ref", "")


def _recent_sender_digits_for_hint(conversations_payload: dict[str, object], phone_hint: str) -> str:
    return _recent_conversation_match(conversations_payload, phone_hint, include_outbound_sender_digits=True).get("sender_digits", "")


def _recent_conversation_match(
    conversations_payload: dict[str, object],
    phone_hint: str,
    *,
    include_outbound_sender_digits: bool = False,
) -> dict[str, str]:
    normalized_hint = _normalize_phone_hint(phone_hint)
    if not normalized_hint or normalized_hint in {"*", "default"}:
        return {}
    matches: list[tuple[str, str, str]] = []
    for conversation in conversations_payload.get("conversations") or []:
        if not isinstance(conversation, dict):
            continue
        chat_ref = str(conversation.get("chat_ref") or "").strip()
        if not chat_ref:
            continue
        sender_candidates = {
            _digits(conversation.get("recipient")),
        }
        latest_message_timestamp = ""
        for message in conversation.get("messages") or []:
            if isinstance(message, dict):
                message_timestamp = str(message.get("message_timestamp") or "").strip()
                if message_timestamp > latest_message_timestamp:
                    latest_message_timestamp = message_timestamp
                direction = str(message.get("direction") or "").strip().lower()
                from_me = bool(message.get("from_me"))
                if include_outbound_sender_digits or (not from_me and direction != "outbound"):
                    sender_candidates.add(_digits(message.get("sender_digits")))
        matched_sender = next(
            (candidate for candidate in sorted(sender_candidates) if candidate and candidate.endswith(normalized_hint)),
            "",
        )
        if matched_sender:
            sort_timestamp = str(
                conversation.get("updated_at")
                or conversation.get("last_message_at")
                or conversation.get("timestamp")
                or latest_message_timestamp
                or ""
            ).strip()
            matches.append(
                (
                    sort_timestamp,
                    chat_ref,
                    matched_sender,
                )
            )
    matches.sort()
    if not matches:
        return {}
    _, chat_ref, sender_digits = matches[-1]
    return {"chat_ref": chat_ref, "sender_digits": sender_digits}


def resolve_whatsapp(phone_hint: str, *, args: argparse.Namespace) -> dict[str, object]:
    binding = _load_whatsapp_binding(args)
    normalized_hint = _normalize_phone_hint(phone_hint)
    routes_payload = _sidecar_get(
        binding=binding,
        suffix="heyy-ai-routes",
        session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
        session_ref=str(getattr(args, "session_ref", "") or "").strip(),
        timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
    )
    try:
        conversations_payload = _sidecar_get(
            binding=binding,
            suffix="conversations?take=50&messages=1&fetch_timeout_ms=5000",
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    except urllib.error.HTTPError as exc:
        conversations_payload = _http_error_payload(exc)
    routes = [dict(row) for row in routes_payload.get("routes") or [] if isinstance(row, dict)]
    matched_routes = [row for row in routes if _match_route(row, phone_hint)]
    recent_sender_digits = _recent_sender_digits_for_hint(conversations_payload, phone_hint)
    if recent_sender_digits:
        narrowed_routes = [
            row
            for row in matched_routes
            if _digits(row.get("inbound_number_digits") or row.get("route_key")).endswith(recent_sender_digits)
        ]
        if len(narrowed_routes) == 1:
            matched_routes = narrowed_routes
    route = matched_routes[0] if len(matched_routes) == 1 else {}
    recipient_digits = _digits(route.get("inbound_number_digits") or route.get("route_key") or recent_sender_digits)
    if not route and normalized_hint and recipient_digits == normalized_hint:
        recipient_digits = ""
    recipient_payload: dict[str, Any] = {}
    if recipient_digits:
        try:
            recipient_payload = _sidecar_get(
                binding=binding,
                suffix=f"recipients/{urllib.parse.quote(recipient_digits, safe='')}",
                session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
                session_ref=str(getattr(args, "session_ref", "") or "").strip(),
                timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
            )
        except Exception as exc:
            recipient_payload = {"registered": False, "reason": type(exc).__name__}
    chat_ref = str(recipient_payload.get("chat_ref") or "").strip() or _recent_chat_ref_for_hint(conversations_payload, phone_hint)
    conversations_ready = bool(conversations_payload.get("ok", True))
    sidecar_reason = str(conversations_payload.get("reason") or "").strip()
    status = (
        "resolved"
        if route
        else "ambiguous"
        if len(matched_routes) > 1
        else "unresolved"
    )
    if not conversations_ready and status != "resolved":
        status = "blocked"
    return {
        "status": status,
        "reason": sidecar_reason if not conversations_ready else "",
        "phone_hint": str(phone_hint or ""),
        "recipient_digits": recipient_digits,
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        "session_ref": _session_ref(binding, str(getattr(args, "session_ref", "") or "").strip()),
        "route_key": str(route.get("route_key") or "").strip(),
        "ai_key": str(route.get("ai_key") or "").strip(),
        "ai_name": str(route.get("ai_name") or "").strip(),
        "auto_reply_enabled": bool(route.get("auto_reply_enabled")) if route else False,
        "chat_ref": chat_ref,
        "registered": bool(recipient_payload.get("registered")),
        "resolution_method": str(recipient_payload.get("resolution_method") or "").strip(),
        "chat_id_kind": str(recipient_payload.get("chat_id_kind") or "").strip(),
        "conversation_lookup_ready": conversations_ready,
        "conversation_lookup_status": str(conversations_payload.get("status") or "").strip(),
        "conversation_lookup_status_code": int(conversations_payload.get("status_code") or 0),
        "candidate_count": len(matched_routes),
        "candidates": [
            {
                "route_key": str(item.get("route_key") or "").strip(),
                "inbound_number_digits": str(item.get("inbound_number_digits") or "").strip(),
                "ai_key": str(item.get("ai_key") or "").strip(),
                "ai_name": str(item.get("ai_name") or "").strip(),
            }
            for item in matched_routes[:5]
        ],
    }


def _operator_whatsapp_sidecar_body(*, resolution: dict[str, object], text: str) -> dict[str, object]:
    body: dict[str, object] = {
        "text": str(text or ""),
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }
    chat_ref = str(resolution.get("chat_ref") or "").strip()
    recipient_digits = str(resolution.get("recipient_digits") or "").strip()
    if chat_ref:
        body["chat_ref"] = chat_ref
    elif recipient_digits:
        body["to"] = recipient_digits
    return body


def send_whatsapp(*, phone_hint: str, text: str, args: argparse.Namespace) -> dict[str, object]:
    resolution = resolve_whatsapp(phone_hint, args=args)
    binding = _load_whatsapp_binding(args)
    recipient_digits = str(resolution.get("recipient_digits") or "").strip()
    chat_ref = str(resolution.get("chat_ref") or "").strip()
    if not recipient_digits:
        return {
            "sent": False,
            "reason": "recipient_unresolved",
            "resolution": resolution,
        }
    if bool(getattr(args, "dry_run", False)):
        return {
            "sent": False,
            "reason": "dry_run",
            "resolution": resolution,
            "binding_id": str(getattr(binding, "binding_id", "") or ""),
            "principal_id": str(getattr(binding, "principal_id", "") or ""),
            "recipient_digits": recipient_digits,
        }
    payload = _sidecar_post(
        binding=binding,
        suffix="messages",
        body=_operator_whatsapp_sidecar_body(resolution=resolution, text=text),
        session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
        session_ref=str(getattr(args, "session_ref", "") or "").strip(),
        timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
    )
    if not bool(payload.get("ok", True)) and chat_ref and recipient_digits and str(payload.get("reason") or "").strip() == "chat_ref_not_found":
        payload = _sidecar_post(
            binding=binding,
            suffix="messages",
            body={
                "to": recipient_digits,
                "text": str(text or ""),
                "pre_reply_delay_min_seconds": 0,
                "pre_reply_delay_max_seconds": 0,
                "typing_delay_ms": 0,
                "typing_delay_ms_per_character": 0,
                "typing_status_enabled": False,
            },
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    message_ids = [str(value or "").strip() for value in payload.get("message_ids") or [] if str(value or "").strip()]
    return {
        "sent": bool(payload.get("ok", True)),
        "reason": "sent" if bool(payload.get("ok", True)) else str(payload.get("reason") or "send_failed").strip(),
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        "recipient_digits": recipient_digits,
        "delivery_transport": "whatsapp_web_session_sidecar",
        "message_ids": message_ids,
        "request_url_present": True,
        "chat_ref_used": bool(chat_ref),
        "resolution": resolution,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic EA live-ops provider probing and WhatsApp operator delivery.")
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--binding-json", default=_env("EA_WHATSAPP_WEB_READINESS_BINDING_JSON"))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "ea-whatsapp-web-session"))
    parser.add_argument("--principal-id", default=_default_whatsapp_principal_id())
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"))
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe-provider", help="Probe a live provider state.")
    probe.add_argument("--provider", required=True)
    probe.add_argument("--format", choices=("json", "operator"), default="json")

    proactive_route = subparsers.add_parser("probe-proactive-route", help="Probe the live proactive OODA delivery route.")
    proactive_route.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_route.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_route.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_route.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_route.add_argument("--receipt-path", default=_env("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH"))

    proactive_artifacts = subparsers.add_parser("probe-proactive-artifacts", help="Probe the live proactive OODA runtime artifacts.")
    proactive_artifacts.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_artifacts.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_artifacts.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))

    proactive_gmail_draft = subparsers.add_parser(
        "probe-proactive-gmail-draft",
        help="Probe the live Telegram to Gmail draft followthrough lane for the current staged proactive action.",
    )
    proactive_gmail_draft.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_gmail_draft.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_gmail_draft.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_gmail_draft.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_gmail_draft.add_argument("--state-path", default=_env("EA_PROACTIVE_OODA_STATE_PATH"))
    proactive_gmail_draft.add_argument("--receipt-path", default=_env("EA_PROACTIVE_OODA_RECEIPT_PATH"))
    proactive_gmail_draft.add_argument("--stage-packet-dir", default=_env("EA_PROACTIVE_OODA_STAGE_PACKET_DIR"))
    proactive_gmail_draft.add_argument("--safe-work-result-dir", default=_env("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR"))

    proactive_source_coverage = subparsers.add_parser(
        "probe-proactive-source-coverage",
        help="Probe sanitized live source coverage for proactive OODA signal lanes.",
    )
    proactive_source_coverage.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_source_coverage.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_source_coverage.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_source_coverage.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_source_coverage.add_argument("--observation-limit", type=int, default=400)

    pocket_sync = subparsers.add_parser(
        "sync-pocket-transcripts",
        help="Run an operator-safe Pocket.ai transcript sync in the live EA runtime.",
    )
    pocket_sync.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    pocket_sync.add_argument("--format", choices=("json", "operator"), default="json")
    pocket_sync.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    pocket_sync.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    pocket_sync.add_argument("--mode", choices=("incremental", "backfill"), default="incremental")
    pocket_sync.add_argument("--limit", type=int, default=10)

    proactive_approval = subparsers.add_parser(
        "record-proactive-approval",
        help="Record the explicit approval outcome for the current live proactive OODA packet.",
    )
    proactive_approval.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_approval.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_approval.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_approval.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_approval.add_argument("--outcome", required=True)
    proactive_approval.add_argument("--evidence", required=True)
    proactive_approval.add_argument("--actor", default="operator-cli")
    proactive_approval.add_argument("--source-kind", default="operator")
    proactive_approval.add_argument("--packet-ref", default="")
    proactive_approval.add_argument("--staged-artifact-ref", default="")
    proactive_approval.add_argument("--dry-run", action="store_true")

    proactive_reissue = subparsers.add_parser(
        "reissue-proactive-approval",
        help="Reissue Telegram approval buttons for the current staged proactive OODA packet.",
    )
    proactive_reissue.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_reissue.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_reissue.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_reissue.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_reissue.add_argument("--dry-run", action="store_true")
    proactive_reissue.add_argument("--force", action="store_true")

    resolve = subparsers.add_parser("resolve-whatsapp", help="Resolve a WhatsApp recipient from a partial phone hint.")
    resolve.add_argument("--phone-hint", required=True)

    send = subparsers.add_parser("send-whatsapp", help="Send a factual operator update over WhatsApp Web.")
    send.add_argument("--phone-hint", required=True)
    send.add_argument("--text", required=True)
    send.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "probe-provider":
        report = probe_provider(args.provider, output_format=args.format)
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0
    if args.command == "probe-proactive-route":
        report = probe_proactive_route(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            receipt_path=str(args.receipt_path or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 15.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-artifacts":
        report = probe_proactive_artifacts(
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 15.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-gmail-draft":
        report = probe_proactive_gmail_draft(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            state_path=str(args.state_path or "").strip(),
            receipt_path=str(args.receipt_path or "").strip(),
            stage_packet_dir=str(args.stage_packet_dir or "").strip(),
            safe_work_result_dir=str(args.safe_work_result_dir or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 15.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-source-coverage":
        report = probe_proactive_source_coverage(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            observation_limit=int(args.observation_limit or 400),
            timeout_seconds=float(args.timeout_seconds or 15.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "sync-pocket-transcripts":
        report = sync_pocket_transcripts(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            mode=str(args.mode or "incremental").strip(),
            limit=int(args.limit or 10),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 120.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) and str(report.get("status") or "") not in {"blocked", "probe_failed"} else 2
    if args.command == "record-proactive-approval":
        report = record_proactive_approval(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            outcome=str(args.outcome or "").strip(),
            evidence=str(args.evidence or "").strip(),
            actor=str(args.actor or "").strip(),
            source_kind=str(args.source_kind or "").strip(),
            packet_ref=str(args.packet_ref or "").strip(),
            staged_artifact_ref=str(args.staged_artifact_ref or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 15.0),
            dry_run=bool(getattr(args, "dry_run", False)),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("recorded")) or str(report.get("reason") or "") == "dry_run" else 2
    if args.command == "reissue-proactive-approval":
        report = reissue_proactive_approval(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 15.0),
            dry_run=bool(getattr(args, "dry_run", False)),
            force=bool(getattr(args, "force", False)),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if str(report.get("status") or "").strip() in {"sent", "already_live_pending", "already_decided", "dry_run"} else 2
    if args.command == "resolve-whatsapp":
        report = resolve_whatsapp(args.phone_hint, args=args)
        print(_json_dumps(report))
        return 0 if str(report.get("status") or "") == "resolved" else 2
    if args.command == "send-whatsapp":
        report = send_whatsapp(phone_hint=args.phone_hint, text=args.text, args=args)
        print(_json_dumps(report))
        return 0 if bool(report.get("sent")) or str(report.get("reason") or "") == "dry_run" else 2
    raise RuntimeError(f"unsupported_command:{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
