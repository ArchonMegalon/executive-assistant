from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_container
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.outbound_email_bounds import outbound_email_guard_summary
from app.settings import get_settings

router = APIRouter(tags=["system"])


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".codex-studio").exists():
            return parent
    return current.parents[4]


_REPO_ROOT = _repo_root()
_WHATSAPP_ACTION_PROCESSOR_READINESS_FILENAME = "whatsapp_web_action_processor_readiness.generated.json"
_WHATSAPP_ACTION_PROCESSOR_READINESS_PATH = (
    _REPO_ROOT / ".codex-studio" / "published" / _WHATSAPP_ACTION_PROCESSOR_READINESS_FILENAME
)
_WHATSAPP_RUNTIME_CONTAINERS = (
    "ea-whatsapp-web-session",
    "ea-whatsapp-web-action-processor",
    "ea-whatsapp-web-teable-sync",
)
_WHATSAPP_READINESS_RECEIPT_FRESH_SECONDS = 900
_WHATSAPP_WEB_SESSION_DEFAULT_BASE_URL = "http://127.0.0.1:8098"
_MEMORIAL_PREMIUM_LATENCY_BUDGET_MS = 750.0
_MEMORIAL_WATCH_LATENCY_BUDGET_MS = 1500.0


def _bool_str(value: object) -> str:
    return "true" if bool(value) else "false"


def _memorial_healthcheck_slug() -> str:
    return str(os.getenv("EA_HEALTHCHECK_MEMORIAL_SLUG") or "").strip()


def _probe_public_memorial_surface(slug: str) -> dict[str, object]:
    from app.api.routes.public_memorial_surface_support import _public_memorial_surface_probe

    started = time.perf_counter()
    probe = _public_memorial_surface_probe(slug)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not str(probe.get("person_name") or "").strip():
        raise HTTPException(status_code=503, detail="not_live:memorial_surface_probe_incomplete")
    return {
        "slug": slug,
        "voice_plugin": str(probe.get("voice_plugin") or ""),
        "audio_clip_count": int(probe.get("audio_clip_count") or 0),
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _memorial_latency_posture(elapsed_ms: object) -> dict[str, object]:
    try:
        elapsed = float(elapsed_ms)
    except (TypeError, ValueError):
        return {
            "tier": "unknown",
            "budget_ms": int(_MEMORIAL_PREMIUM_LATENCY_BUDGET_MS),
            "operator_action_state": "action_required",
            "next_action": "rerun_memorial_probe_with_runtime_latency_capture",
        }
    if elapsed <= _MEMORIAL_PREMIUM_LATENCY_BUDGET_MS:
        return {
            "tier": "premium",
            "budget_ms": int(_MEMORIAL_PREMIUM_LATENCY_BUDGET_MS),
            "operator_action_state": "clear",
            "next_action": "maintain_memorial_voice_runtime",
        }
    if elapsed <= _MEMORIAL_WATCH_LATENCY_BUDGET_MS:
        return {
            "tier": "watch",
            "budget_ms": int(_MEMORIAL_PREMIUM_LATENCY_BUDGET_MS),
            "operator_action_state": "refresh_recommended",
            "next_action": "prewarm_or_recheck_memorial_voice_runtime",
        }
    return {
        "tier": "degraded",
        "budget_ms": int(_MEMORIAL_PREMIUM_LATENCY_BUDGET_MS),
        "operator_action_state": "action_required",
        "next_action": "optimize_memorial_voice_runtime_latency",
    }


def _request_host(request: Request) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip().lower()


def _request_header_host(request: Request) -> str:
    headers = getattr(request, "headers", {})
    return str(headers.get("host") or "").split(":", 1)[0].strip().lower()


def _local_operator_host(request: Request) -> bool:
    host = _request_header_host(request)
    return host in {"localhost", "127.0.0.1", "::1", "testclient", "testserver"}


def _private_or_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1", "testclient"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def _loopback_request(request: Request) -> bool:
    host = _request_host(request)
    if not host:
        return False
    if _private_or_loopback_host(host) and _local_operator_host(request):
        return True
    return _private_or_loopback_host(host) and host in {"127.0.0.1", "::1"}


def _public_surface_flags() -> dict[str, str]:
    settings = get_settings()
    return {
        "public_memorials_enabled": _bool_str(settings.public_memorials_enabled),
        "public_tours_enabled": _bool_str(settings.public_tours_enabled),
        "public_results_enabled": _bool_str(settings.public_results_enabled),
        "legacy_runtime_surfaces_enabled": _bool_str(settings.legacy_runtime_surfaces_enabled),
    }


def _truthy_query_value(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _memorial_probe_requested(
    request: Request,
    *,
    slug: str,
    memorial_runtime: dict[str, object],
) -> bool:
    if not _loopback_request(request):
        return False
    if not slug or not bool(memorial_runtime.get("route_mounted")):
        return False
    query_params = getattr(request, "query_params", None)
    if query_params is None:
        return False
    probe = str(query_params.get("probe") or "").strip().lower()
    if probe in {"memorial", "deep_memorial"}:
        return True
    return any(
        _truthy_query_value(query_params.get(key))
        for key in ("probe_memorial", "memorial_probe", "deep_probe")
    )


def _read_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _whatsapp_provider_ledger_dir() -> Path:
    ledger_dir = str(os.getenv("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "/data/provider-ledger").strip() or "/data/provider-ledger"
    return Path(ledger_dir)


def _whatsapp_action_processor_runtime_receipt_path() -> Path:
    configured = str(os.getenv("EA_WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_PATH") or "").strip()
    if configured:
        return Path(configured)
    return _whatsapp_provider_ledger_dir() / "provider-health-cache" / _WHATSAPP_ACTION_PROCESSOR_READINESS_FILENAME


def _whatsapp_action_processor_readiness_candidate_paths() -> tuple[Path, ...]:
    ordered: list[Path] = []
    for candidate in (
        _whatsapp_action_processor_runtime_receipt_path(),
        _WHATSAPP_ACTION_PROCESSOR_READINESS_PATH,
    ):
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


def _whatsapp_action_processor_readiness_receipt() -> tuple[Path, dict[str, object]]:
    candidates = _whatsapp_action_processor_readiness_candidate_paths()
    if not candidates:
        return _WHATSAPP_ACTION_PROCESSOR_READINESS_PATH, {}
    for candidate in candidates:
        payload = _read_json_file(candidate)
        if payload:
            return candidate, payload
    return candidates[0], {}


def _parse_iso8601_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds_since(value: object, *, now: datetime | None = None) -> int | None:
    parsed = _parse_iso8601_utc(value)
    if parsed is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - parsed).total_seconds()))


def _whatsapp_pairing_url(receipt: dict[str, object]) -> str:
    status = str(receipt.get("sidecar_status") or receipt.get("sidecar_health_status") or "").strip()
    if status != "qr_required":
        return ""
    session_ref = str(
        receipt.get("effective_session_ref")
        or receipt.get("sidecar_health_session_ref")
        or receipt.get("state_session_ref")
        or receipt.get("configured_session_ref")
        or ""
    ).strip()
    if not session_ref:
        return ""
    base_url = str(os.getenv("EA_WHATSAPP_WEB_SESSION_API_BASE_URL") or _WHATSAPP_WEB_SESSION_DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/sessions/{quote(session_ref, safe='')}/pair"


def _docker_container_health(names: tuple[str, ...]) -> dict[str, object]:
    if shutil.which("docker") is None:
        return {"source": "docker_unavailable", "containers": []}
    rows: list[dict[str, str]] = []
    try:
        for name in names:
            proc = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no_healthcheck{{end}}",
                    name,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2,
            )
            output = (proc.stdout or "").strip()
            if proc.returncode != 0 or not output:
                rows.append({"name": name, "status": "unknown", "health": "unknown"})
                continue
            parts = output.split()
            rows.append(
                {
                    "name": str(parts[0] if parts else name).lstrip("/"),
                    "status": str(parts[1] if len(parts) > 1 else "unknown"),
                    "health": str(parts[2] if len(parts) > 2 else "unknown"),
                }
            )
    except Exception:
        return {"source": "docker_probe_failed", "containers": rows}
    return {"source": "docker_inspect", "containers": rows}


def _whatsapp_operator_action_state(*, receipt_present: bool, receipt_fresh: bool, ready: bool, receipt: dict[str, object] | None = None) -> str:
    if not receipt_present:
        return "action_required"
    if not receipt_fresh:
        return "refresh_recommended"
    if ready:
        return "clear"
    payload = dict(receipt or {})
    if bool(payload.get("sidecar_qr_required")) and bool(payload.get("sidecar_qr_present")) and bool(payload.get("sidecar_qr_fresh")):
        return "pairing_required"
    if bool(payload.get("sidecar_qr_required")):
        return "refresh_recommended"
    return "action_required"


def _whatsapp_operator_recheck_after_seconds(operator_state: str) -> int:
    return {
        "action_required": 0,
        "pairing_required": 15,
        "refresh_recommended": 30,
        "clear": 120,
    }.get(str(operator_state or "").strip(), 60)


def _whatsapp_runtime_status() -> dict[str, object]:
    receipt_path, receipt = _whatsapp_action_processor_readiness_receipt()
    docker_health = _docker_container_health(_WHATSAPP_RUNTIME_CONTAINERS)
    if not receipt:
        operator_state = _whatsapp_operator_action_state(receipt_present=False, receipt_fresh=False, ready=False)
        return {
            "state": "unknown",
            "receipt_present": False,
            "receipt_path": str(receipt_path),
            "next_action": "materialize_whatsapp_web_action_processor_readiness",
            "operator_action_state": operator_state,
            "operator_recheck_after_seconds": _whatsapp_operator_recheck_after_seconds(operator_state),
            "container_health": docker_health,
        }
    ready = bool(receipt.get("ready"))
    receipt_age_seconds = _age_seconds_since(receipt.get("generated_at"))
    receipt_fresh = (
        receipt_age_seconds is not None
        and receipt_age_seconds <= _WHATSAPP_READINESS_RECEIPT_FRESH_SECONDS
    )
    receipt_next_action = str(receipt.get("next_action") or "")
    next_action = (
        "refresh_whatsapp_web_action_processor_readiness_receipt"
        if not receipt_fresh
        else receipt_next_action
    )
    operator_pairing_url = _whatsapp_pairing_url(receipt)
    operator_state = _whatsapp_operator_action_state(
        receipt_present=True,
        receipt_fresh=receipt_fresh,
        ready=ready,
        receipt=receipt,
    )
    return {
        "state": "ready" if ready else "blocked",
        "receipt_present": True,
        "receipt_path": str(receipt_path),
        "receipt_fresh": receipt_fresh,
        "receipt_age_seconds": receipt_age_seconds,
        "receipt_fresh_seconds": _WHATSAPP_READINESS_RECEIPT_FRESH_SECONDS,
        "contract_name": str(receipt.get("contract_name") or ""),
        "generated_at": str(receipt.get("generated_at") or ""),
        "status": str(receipt.get("status") or ""),
        "ready": ready,
        "reason": str(receipt.get("reason") or ""),
        "sidecar_ready": bool(receipt.get("sidecar_ready")),
        "sidecar_status": str(receipt.get("sidecar_status") or ""),
        "sidecar_health_status": str(receipt.get("sidecar_health_status") or ""),
        "sidecar_qr_required": bool(receipt.get("sidecar_qr_required")),
        "sidecar_qr_present": bool(receipt.get("sidecar_qr_present")),
        "sidecar_last_qr_at": str(receipt.get("sidecar_last_qr_at") or ""),
        "sidecar_qr_age_seconds": (
            int(receipt.get("sidecar_qr_age_seconds"))
            if receipt.get("sidecar_qr_age_seconds") is not None
            else None
        ),
        "sidecar_qr_fresh": bool(receipt.get("sidecar_qr_fresh")),
        "sidecar_qr_fresh_seconds": int(receipt.get("sidecar_qr_fresh_seconds") or 0),
        "operator_pairing_url": operator_pairing_url,
        "operator_pairing_note": (
            "Open this local pairing page and scan the WhatsApp Web QR code."
            if operator_pairing_url
            else ""
        ),
        "operator_action_state": operator_state,
        "operator_recheck_after_seconds": _whatsapp_operator_recheck_after_seconds(operator_state),
        "state_age_seconds": int(receipt.get("state_age_seconds") or 0),
        "next_action": next_action,
        "receipt_next_action": receipt_next_action,
        "container_health": docker_health,
    }


def _outbound_email_runtime_status() -> dict[str, object]:
    summary = outbound_email_guard_summary()
    status = str(summary.get("status") or "unknown").strip()
    if status == "guard_unavailable":
        operator_action_state = "action_required"
        next_action = "inspect_outbound_email_guard_state"
        recheck_after = 0
        state = "unknown"
    elif status == "disabled":
        operator_action_state = "action_required"
        next_action = "enable_outbound_email_bounds"
        recheck_after = 0
        state = "disabled"
    elif status == "bounded":
        operator_action_state = "clear"
        next_action = "wait_for_outbound_email_cooldown"
        recheck_after = 60
        state = "bounded"
    else:
        operator_action_state = "clear"
        next_action = "maintain_outbound_email_bounds"
        recheck_after = 300
        state = "clear"
    return {
        "state": state,
        "enabled": bool(summary.get("enabled")),
        "next_action": next_action,
        "operator_action_state": operator_action_state,
        "operator_recheck_after_seconds": recheck_after,
        "guard_status": status,
        "guard_path": str(summary.get("state_path") or ""),
        "guard_file_bytes": int(summary.get("guard_file_bytes") or 0),
        "entry_count": int(summary.get("entry_count") or 0),
        "attempt_count": int(summary.get("attempt_count") or 0),
        "active_cooldown_count": int(summary.get("active_cooldown_count") or 0),
        "active_window_budget_count": int(summary.get("active_window_budget_count") or 0),
        "most_recent_attempt_at": str(summary.get("most_recent_attempt_at") or ""),
        "categories": dict(summary.get("categories") or {}),
        "privacy": {
            "raw_recipient_exposed": False,
            "raw_subject_exposed": False,
        },
        "guard_error": str(summary.get("guard_error") or ""),
    }


def _route_mounted(request: Request, path: str) -> bool:
    scope = getattr(request, "scope", None)
    app = scope.get("app") if isinstance(scope, dict) else None
    routes = getattr(app, "routes", None)
    if not isinstance(routes, list):
        return False
    for route in routes:
        if str(getattr(route, "path", "") or "").strip() == path:
            return True
    return False


def _memorial_runtime_status(request: Request) -> dict[str, object]:
    settings = get_settings()
    slug = _memorial_healthcheck_slug()
    route_path = "/memorials/{slug}"
    route_mounted = _route_mounted(request, route_path)
    enabled = bool(settings.public_memorials_enabled)
    state = "disabled"
    next_action = ""
    if enabled and route_mounted:
        state = "mounted"
        next_action = "run_memorial_probe" if slug else "set_EA_HEALTHCHECK_MEMORIAL_SLUG_for_live_probe"
    elif enabled and not route_mounted:
        state = "enabled_unmounted"
        next_action = "start_runtime_with_memorial_overlay"
    elif (not enabled) and route_mounted:
        state = "mounted_without_flag"
        next_action = "align_runtime_flags_with_route_contract"
    else:
        state = "disabled"
        next_action = "start_runtime_with_memorial_overlay"
    return {
        "state": state,
        "configured_enabled": enabled,
        "route_mounted": route_mounted,
        "healthcheck_slug": slug,
        "route_path": route_path,
        "next_action": next_action,
    }


def _public_gate_projection(value: object) -> dict[str, object]:
    gate = dict(value) if isinstance(value, dict) else {}
    issues = gate.get("issues")
    issue_count = len(issues) if isinstance(issues, list) else 0
    projection: dict[str, object] = {
        "contract_name": str(gate.get("contract_name") or ""),
        "status": str(gate.get("status") or "error"),
        "issue_count": issue_count,
    }
    authority_posture = str(gate.get("authority_posture") or "").strip()
    if authority_posture:
        projection["authority_posture"] = authority_posture
    return projection


def _redact_release_authority(summary: dict[str, object]) -> dict[str, object]:
    return {
        "state": str(summary.get("state") or "missing"),
        "authority_posture": str(summary.get("authority_posture") or "missing_manifest"),
        "source": str(summary.get("source") or "manifest_fallback"),
        "gate": _public_gate_projection(summary.get("gate")),
        "deploy_context_gate": _public_gate_projection(summary.get("deploy_context_gate")),
    }


def _redact_runtime_supply_chain(summary: dict[str, object]) -> dict[str, object]:
    return {
        "state": str(summary.get("state") or "watch"),
        "gate": _public_gate_projection(summary.get("gate")),
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return await health()


@router.get("/health/live")
async def health_live(request: Request) -> dict[str, object]:
    slug = _memorial_healthcheck_slug()
    loopback = _loopback_request(request)
    memorial_runtime = _memorial_runtime_status(request)
    if not loopback:
        return {"status": "live"}
    payload: dict[str, object] = {
        "status": "live",
        "public_surface_flags": _public_surface_flags(),
        "memorial_runtime": memorial_runtime,
        "outbound_email_runtime": _outbound_email_runtime_status(),
        "whatsapp_runtime": _whatsapp_runtime_status(),
    }
    if not _memorial_probe_requested(request, slug=slug, memorial_runtime=memorial_runtime):
        payload["memorial_probe_mode"] = (
            "deferred"
            if slug and bool(memorial_runtime.get("route_mounted"))
            else "unavailable"
        )
        return payload
    probe = _probe_public_memorial_surface(slug)
    latency_posture = _memorial_latency_posture(probe.get("elapsed_ms"))
    payload.update(
        {
            "memorial_probe_mode": "explicit",
            "memorial_slug": str(probe["slug"]),
            "memorial_voice_plugin": str(probe["voice_plugin"]),
            "memorial_audio_clip_count": str(probe["audio_clip_count"]),
            "memorial_elapsed_ms": str(probe["elapsed_ms"]),
            "memorial_latency_tier": str(latency_posture["tier"]),
            "memorial_latency_budget_ms": str(latency_posture["budget_ms"]),
            "memorial_operator_action_state": str(latency_posture["operator_action_state"]),
            "memorial_latency_next_action": str(latency_posture["next_action"]),
        }
    )
    return payload


@router.get("/health/ready")
async def health_ready(container: AppContainer = Depends(get_container)) -> dict[str, str]:
    ready, reason = container.readiness.check()
    if not ready:
        raise HTTPException(status_code=503, detail=f"not_ready:{reason}")
    return {"status": "ready", "reason": reason}


@router.get("/version")
async def version(request: Request, container: AppContainer = Depends(get_container)) -> dict[str, object]:
    release_authority_summary = build_product_service(container).release_authority_summary()
    payload = {
        "app_name": container.settings.app_name,
        "version": container.settings.app_version,
        "role": container.settings.role,
        "storage_backend": container.settings.storage_backend,
        "release_authority_state": str(release_authority_summary.get("state") or "missing"),
        "release_authority_posture": str(release_authority_summary.get("authority_posture") or "missing_manifest"),
        "release_authority_source": str(release_authority_summary.get("source") or "manifest_fallback"),
        "release_manifest_generated_at": str(release_authority_summary.get("generated_at") or ""),
    }
    if not _loopback_request(request):
        return payload
    payload.update(
        {
            "repository": str(release_authority_summary.get("repository") or ""),
            "branch": str(release_authority_summary.get("branch") or ""),
            "tracking_branch": str(release_authority_summary.get("tracking_branch") or ""),
            "commit_sha": str(release_authority_summary.get("commit_sha") or ""),
            "source_remote_ref": str(release_authority_summary.get("source_remote_ref") or ""),
            "source_remote_ref_commit_sha": str(
                release_authority_summary.get("source_remote_ref_commit_sha") or ""
            ),
            "source_remote_ref_evidence": str(
                release_authority_summary.get("source_remote_ref_evidence") or ""
            ),
            "source_commit_reachable_from_remote_ref": (
                release_authority_summary.get("source_commit_reachable_from_remote_ref")
                is True
            ),
            "deployment_id": str(release_authority_summary.get("deployment_id") or ""),
            "deployment_id_source": str(release_authority_summary.get("deployment_id_source") or ""),
            "public_origin": str(release_authority_summary.get("public_origin") or ""),
            "public_origin_source": str(release_authority_summary.get("public_origin_source") or ""),
            "project_mode": str(release_authority_summary.get("project_mode") or ""),
        }
    )
    return payload


@router.get("/health/release-authority")
async def health_release_authority(request: Request, container: AppContainer = Depends(get_container)) -> dict[str, object]:
    product = build_product_service(container)
    release_authority_summary = product.release_authority_summary()
    runtime_supply_chain_summary = product.runtime_supply_chain_summary()
    if not _loopback_request(request):
        public_release = _redact_release_authority(release_authority_summary)
        public_supply_chain = _redact_runtime_supply_chain(runtime_supply_chain_summary)
        return {
            "release_authority": public_release,
            "release_authority_gate": dict(public_release.get("gate") or {}),
            "deploy_context_gate": dict(public_release.get("deploy_context_gate") or {}),
            "runtime_supply_chain": public_supply_chain,
            "runtime_supply_chain_gate": dict(public_supply_chain.get("gate") or {}),
        }
    return {
        "release_authority": release_authority_summary,
        "release_authority_gate": dict(release_authority_summary.get("gate") or {}),
        "deploy_context_gate": dict(release_authority_summary.get("deploy_context_gate") or {}),
        "runtime_supply_chain": runtime_supply_chain_summary,
        "runtime_supply_chain_gate": dict(runtime_supply_chain_summary.get("gate") or {}),
    }
