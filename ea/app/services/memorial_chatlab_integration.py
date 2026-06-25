from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator


CONTRACT_NAME = "ea.memorial_chatlab_ltd_integration.v1"
CONTRACT_RECEIPT_NAME = "ea.memorial_chatlab_contract_receipt.v1"
ROUTE_SURFACE_CONTRACT_NAME = "ea.memorial_chatlab_route_surface.v1"
RUNTIME_PREFLIGHT_CONTRACT_NAME = "ea.memorial_chatlab_runtime_preflight.v1"
EXTERNAL_EVIDENCE_CONTRACT_NAME = "ea.memorial_chatlab_external_evidence_receipt.v1"

CHATLAB_ENV_NAMES = (
    "EA_MEMORIAL_CHATLAB_ENABLED",
    "EA_MEMORIAL_CHAT_LAB_ENABLED",
    "EA_MEMORIAL_CHATLAB_PROVIDER",
    "EA_MEMORIAL_CHAT_LAB_PROVIDER",
    "EA_MEMORIAL_CHATLAB_API_KEY",
    "EA_MEMORIAL_CHATLAB_API_URL",
    "EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME",
    "CHATLAB_API_KEY",
    "CHATLAB_API_URL",
    "EA_MEMORIAL_CHATLAB_EXTERNAL_EVIDENCE_RECEIPT",
)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def memorial_chatlab_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    if not normalized:
        return "memorial"
    return normalized


def _env_value(name: str, fallback: str = "") -> str:
    return str(os.environ.get(name) or os.environ.get(fallback) or "").strip()


def _env_flag(name: str, fallback: str = "") -> bool:
    raw = str(os.environ.get(name) or os.environ.get(fallback) or "").strip().lower()
    return raw in {"1", "true", "yes", "on", "enabled"}


def _provider_label(provider_key: str) -> str:
    normalized = str(provider_key or "").strip().lower()
    if normalized == "chatlab":
        return "ChatLab"
    if normalized == "chatplayground":
        return "ChatPlayground"
    return normalized.title()


def chatlab_provider_state() -> dict[str, object]:
    provider_key = _env_value("EA_MEMORIAL_CHATLAB_PROVIDER", "EA_MEMORIAL_CHAT_LAB_PROVIDER").lower()
    enabled = _env_flag("EA_MEMORIAL_CHATLAB_ENABLED", "EA_MEMORIAL_CHAT_LAB_ENABLED")
    api_key_present = bool(_env_value("EA_MEMORIAL_CHATLAB_API_KEY", "CHATLAB_API_KEY"))
    endpoint_present = bool(_env_value("EA_MEMORIAL_CHATLAB_API_URL", "CHATLAB_API_URL"))
    provider_configured = bool(enabled and provider_key and api_key_present and endpoint_present)
    runtime_opt_in = bool(provider_configured and _env_flag("EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME"))
    return {
        "enabled": enabled,
        "provider_key": provider_key,
        "provider_label": _provider_label(provider_key) if provider_key else "",
        "provider_configured": provider_configured,
        "api_key_present": api_key_present,
        "endpoint_present": endpoint_present,
        "runtime_opt_in": runtime_opt_in,
        "credential_values_exposed": False,
        "endpoint_value_exposed": False,
    }


def memorial_chatlab_contract() -> dict[str, object]:
    provider = chatlab_provider_state()
    provider_configured = bool(provider.get("provider_configured") is True)
    provider_runtime_allowed = bool(provider.get("runtime_opt_in") is True)
    integration_state = "fallback_first_party_chat"
    if provider_configured and provider_runtime_allowed:
        integration_state = "provider_runtime_available_but_not_authoritative"
    elif provider_configured:
        integration_state = "provider_configured_contract_only"
    return {
        "contract_name": CONTRACT_NAME,
        "integration_state": integration_state,
        "provider_key": str(provider.get("provider_key") or "") if provider_configured else "",
        "provider_label": str(provider.get("provider_label") or "") if provider_configured else "",
        "provider_configured": provider_configured,
        "provider_runtime_allowed": provider_runtime_allowed,
        "provider_truth_allowed": False,
        "provider_persona_truth_allowed": False,
        "provider_memory_write_allowed": False,
        "provider_guardrail_override_allowed": False,
        "raw_private_context_allowed": False,
        "gold_claim_allowed": False,
        "first_party_chat_remains_authoritative": True,
        "difficult_memory_guardrail_owner": "ea_first_party_memorial_chat",
        "required_next_receipts": ["chatlab_runtime_probe_receipt"],
    }


def memorial_chatlab_status_payload(*, slug: str) -> dict[str, object]:
    return {"slug": memorial_chatlab_slug(slug), "chatlab": memorial_chatlab_contract()}


def _write_json(path: Path, payload: dict[str, object]) -> dict[str, object]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _text_values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)


def sensitive_value_exposed(value: object) -> bool:
    patterns = (
        re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
        re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
        re.compile(r"\bsecret_[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
        re.compile(r"\bsk-[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
        re.compile(r"\btest-chatlab-key\b", re.IGNORECASE),
        re.compile(r"\broute-surface-secret-key\b", re.IGNORECASE),
        re.compile(r"\bhttps?://chatlab(?:-route)?\.example\.test\b", re.IGNORECASE),
    )
    for text in _text_values(value):
        if any(pattern.search(text) for pattern in patterns):
            return True
    return False


def materialize_chatlab_contract_receipt(
    *,
    receipt_path: Path,
    slug: str,
    generated_at: str | None = None,
) -> dict[str, object]:
    contract = memorial_chatlab_contract()
    provider = chatlab_provider_state()
    provider_configured = bool(contract.get("provider_configured") is True)
    receipt = {
        "contract_name": CONTRACT_RECEIPT_NAME,
        "generated_by": "ea/scripts/materialize_memorial_chatlab_contract_receipt.py",
        "generated_at": generated_at or now_iso(),
        "slug": memorial_chatlab_slug(slug),
        "status": "configured_contract_only" if provider_configured else "ready_fallback_contract",
        "provider_key": str(contract.get("provider_key") or ""),
        "provider_label": str(contract.get("provider_label") or ""),
        "provider_configured": provider_configured,
        "provider_enabled": bool(provider.get("enabled") is True),
        "runtime_probe_required": False,
        "provider_ready": False,
        "live_provider_runtime_verified": False,
        "provider_truth_allowed": False,
        "persona_truth_allowed": False,
        "memory_truth_allowed": False,
        "publication_allowed": False,
        "raw_private_context_exposed": False,
        "boundaries": {
            "first_party_chat_authoritative": True,
            "provider_may_transport_only_after_separate_runtime_receipt": True,
            "provider_may_not_write_memory_or_guardrails": True,
        },
        "chatlab_contract": contract,
    }
    return _write_json(receipt_path, receipt)


def verify_memorial_chatlab_contract_receipt(path: Path) -> dict[str, object]:
    receipt = _json(path)
    issues: list[str] = []
    if not receipt:
        issues.append("memorial_chatlab_receipt_missing_or_invalid")
    if receipt.get("contract_name") != CONTRACT_RECEIPT_NAME:
        issues.append("memorial_chatlab_contract_name_invalid")
    if receipt.get("provider_ready") is True:
        issues.append("memorial_chatlab_provider_ready_overclaim")
    if receipt.get("publication_allowed") is True:
        issues.append("memorial_chatlab_publication_overclaim")
    contract = dict(receipt.get("chatlab_contract") or {})
    if contract.get("provider_truth_allowed") is True:
        issues.append("memorial_chatlab_nested_provider_truth_overclaim")
    if contract.get("first_party_chat_remains_authoritative") is not True:
        issues.append("memorial_chatlab_first_party_not_authoritative")
    if sensitive_value_exposed(receipt):
        issues.append("memorial_chatlab_sensitive_value_exposed")
    return {
        "status": "fail" if issues else "pass",
        "issues": issues,
        "receipt": Path(path).as_posix(),
    }


@contextmanager
def _patched_chatlab_env(values: dict[str, str]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in CHATLAB_ENV_NAMES}
    for name in CHATLAB_ENV_NAMES:
        os.environ.pop(name, None)
    os.environ.update(values)
    try:
        yield
    finally:
        for name in CHATLAB_ENV_NAMES:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def materialize_chatlab_route_surface(
    *,
    receipt_path: Path,
    slug: str,
    generated_at: str | None = None,
) -> dict[str, object]:
    safe_slug = memorial_chatlab_slug(slug)
    with _patched_chatlab_env({}):
        fallback = memorial_chatlab_status_payload(slug=safe_slug)
    with _patched_chatlab_env(
        {
            "EA_MEMORIAL_CHATLAB_ENABLED": "1",
            "EA_MEMORIAL_CHATLAB_PROVIDER": "chatlab",
            "EA_MEMORIAL_CHATLAB_API_KEY": "route-surface-secret-key",
            "EA_MEMORIAL_CHATLAB_API_URL": "https://chatlab-route.example.test",
        }
    ):
        configured = memorial_chatlab_status_payload(slug=safe_slug)
    fallback_chatlab = dict(dict(fallback.get("chatlab") or {}))
    configured_chatlab = dict(dict(configured.get("chatlab") or {}))
    receipt = {
        "contract_name": ROUTE_SURFACE_CONTRACT_NAME,
        "generated_by": "ea/scripts/materialize_memorial_chatlab_route_surface.py",
        "generated_at": generated_at or now_iso(),
        "slug": safe_slug,
        "status": "ready",
        "provider_ready": False,
        "route": f"/memorials/{safe_slug}/chatlab/status",
        "route_checks": {
            "fallback_first_party_state": fallback_chatlab.get("integration_state") == "fallback_first_party_chat",
            "configured_contract_only_state": configured_chatlab.get("integration_state") == "provider_configured_contract_only",
            "configured_runtime_disallowed": configured_chatlab.get("provider_runtime_allowed") is False,
            "first_party_authoritative": configured_chatlab.get("first_party_chat_remains_authoritative") is True,
        },
        "snapshots": {
            "fallback_first_party_chat": {"response": fallback},
            "configured_contract_only": {"response": configured},
        },
    }
    return _write_json(receipt_path, receipt)


def verify_memorial_chatlab_route_surface(path: Path) -> dict[str, object]:
    receipt = _json(path)
    issues: list[str] = []
    if not receipt:
        issues.append("chatlab_route_receipt_missing_or_invalid")
    if receipt.get("contract_name") != ROUTE_SURFACE_CONTRACT_NAME:
        issues.append("chatlab_route_contract_name_invalid")
    if receipt.get("provider_ready") is True:
        issues.append("chatlab_route_provider_ready_overclaim")
    snapshots = dict(receipt.get("snapshots") or {})
    configured = dict(dict(dict(snapshots.get("configured_contract_only") or {}).get("response") or {}).get("chatlab") or {})
    if configured.get("provider_truth_allowed") is True:
        issues.append("chatlab_route_nested_provider_truth_overclaim")
    if sensitive_value_exposed(receipt):
        issues.append("chatlab_route_sensitive_value_exposed")
    return {
        "status": "fail" if issues else "pass",
        "issues": issues,
        "receipt": Path(path).as_posix(),
    }


def _evidence_item(raw: str) -> dict[str, object]:
    text = str(raw or "").strip()
    return {
        "present": bool(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
        "chars": len(text),
        "redacted": True,
    }


def write_chatlab_external_evidence_receipt(
    *,
    output_path: Path,
    slug: str,
    provider_key: str,
    account_capability_evidence: str = "",
    runtime_probe_evidence: str = "",
    no_private_context_evidence: str = "",
    guardrail_preservation_evidence: str = "",
    observed_at: str | None = None,
) -> dict[str, object]:
    evidence = {
        "account_capability": _evidence_item(account_capability_evidence),
        "runtime_probe": _evidence_item(runtime_probe_evidence),
        "no_private_context_upload": _evidence_item(no_private_context_evidence),
        "guardrail_preservation": _evidence_item(guardrail_preservation_evidence),
    }
    complete = all(dict(item).get("present") is True for item in evidence.values())
    receipt = {
        "contract_name": EXTERNAL_EVIDENCE_CONTRACT_NAME,
        "generated_by": "ea/scripts/materialize_memorial_chatlab_external_evidence.py",
        "generated_at": now_iso(),
        "observed_at": observed_at or now_iso(),
        "slug": memorial_chatlab_slug(slug),
        "provider_key": str(provider_key or "").strip().lower(),
        "status": "pass" if complete else "incomplete",
        "raw_evidence_redacted": True,
        "evidence": evidence,
    }
    return _write_json(output_path, receipt)


def _load_external_evidence(path: Path | None) -> dict[str, object]:
    if path is None:
        raw = str(os.environ.get("EA_MEMORIAL_CHATLAB_EXTERNAL_EVIDENCE_RECEIPT") or "").strip()
        path = Path(raw).expanduser() if raw else None
    if not path:
        return {"status": "missing", "path": ""}
    payload = _json(Path(path).expanduser())
    if not payload:
        return {"status": "missing", "path": Path(path).as_posix()}
    if payload.get("contract_name") != EXTERNAL_EVIDENCE_CONTRACT_NAME:
        return {"status": "invalid", "path": Path(path).as_posix()}
    return {**payload, "path": Path(path).as_posix()}


def _base_runtime_receipts() -> dict[str, dict[str, object]]:
    return {
        "chatlab_account_capability_receipt": {"status": "not_run", "redacted": True},
        "chatlab_runtime_probe_receipt": {"status": "not_run", "redacted": True},
        "chatlab_no_private_context_upload_receipt": {"status": "pass_policy", "redacted": True},
        "chatlab_guardrail_preservation_receipt": {"status": "pass_policy", "redacted": True},
    }


def chatlab_runtime_preflight(
    *,
    slug: str,
    generated_at: str | None = None,
    external_evidence_path: Path | None = None,
) -> dict[str, object]:
    provider = chatlab_provider_state()
    contract = memorial_chatlab_contract()
    receipts = _base_runtime_receipts()
    failed_checks: list[str] = []
    warned_checks: list[str] = []
    enabled = bool(provider.get("enabled") is True)
    provider_key = str(provider.get("provider_key") or "")
    if enabled:
        if not provider_key:
            failed_checks.append("provider_key_present_when_enabled")
        if provider.get("api_key_present") is not True:
            failed_checks.append("api_key_present_when_enabled")
        if provider.get("endpoint_present") is not True:
            failed_checks.append("endpoint_present_when_enabled")

    evidence = _load_external_evidence(external_evidence_path)
    evidence_status = str(evidence.get("status") or "")
    evidence_passed = evidence_status == "pass"
    if evidence_passed:
        receipts["chatlab_account_capability_receipt"]["status"] = "pass_redacted_external_evidence"
        receipts["chatlab_runtime_probe_receipt"]["status"] = "pass_redacted_external_evidence"
        receipts["chatlab_no_private_context_upload_receipt"]["status"] = "pass_redacted_external_evidence"
        receipts["chatlab_guardrail_preservation_receipt"]["status"] = "pass_redacted_external_evidence"
    else:
        warned_checks.append("runtime_probe_receipt_present")

    if failed_checks:
        status = "fail"
        readiness_state = "configured_missing_provider_requirements"
    elif evidence_passed:
        status = "pass"
        readiness_state = "configured_runtime_evidence_redacted"
    elif provider.get("provider_configured") is True and provider.get("runtime_opt_in") is True:
        status = "warn"
        readiness_state = "configured_runtime_probe_pending"
    elif provider.get("provider_configured") is True:
        status = "warn"
        readiness_state = "configured_contract_only"
    else:
        status = "warn"
        readiness_state = "fallback_first_party_chat"

    return {
        "contract_name": RUNTIME_PREFLIGHT_CONTRACT_NAME,
        "generated_by": "ea/scripts/materialize_memorial_chatlab_runtime_preflight.py",
        "generated_at": generated_at or now_iso(),
        "slug": memorial_chatlab_slug(slug),
        "status": status,
        "readiness_state": readiness_state,
        "provider_ready": False,
        "live_provider_runtime_verified": False,
        "provider_truth_allowed": False,
        "memory_truth_allowed": False,
        "publication_allowed": False,
        "provider": provider,
        "chatlab_contract": contract,
        "receipts": receipts,
        "external_evidence": {
            "status": evidence_status or "missing",
            "path": str(evidence.get("path") or ""),
            "raw_evidence_redacted": bool(evidence.get("raw_evidence_redacted") is True),
        },
        "failed_checks": failed_checks,
        "warned_checks": warned_checks,
    }


def write_chatlab_runtime_preflight(
    *,
    output_path: Path,
    slug: str,
    generated_at: str | None = None,
    external_evidence_path: Path | None = None,
) -> dict[str, object]:
    receipt = chatlab_runtime_preflight(
        slug=slug,
        generated_at=generated_at,
        external_evidence_path=external_evidence_path,
    )
    return _write_json(output_path, receipt)


def verify_chatlab_runtime_preflight(path: Path) -> dict[str, object]:
    receipt = _json(path)
    issues: list[str] = []
    if not receipt:
        issues.append("chatlab_preflight_missing_or_invalid")
    if receipt.get("contract_name") != RUNTIME_PREFLIGHT_CONTRACT_NAME:
        issues.append("chatlab_preflight_contract_name_invalid")
    status = str(receipt.get("status") or "").strip()
    if status not in {"pass", "warn"}:
        issues.append("chatlab_preflight_status_not_pass_or_warn")
    for check in list(receipt.get("failed_checks") or []):
        if str(check or "").strip():
            issues.append(f"chatlab_preflight_failed_check:{str(check).strip()}")
    if receipt.get("provider_ready") is True:
        issues.append("chatlab_preflight_provider_ready_overclaim")
    if receipt.get("live_provider_runtime_verified") is True:
        issues.append("chatlab_preflight_live_runtime_overclaim")
    receipts = dict(receipt.get("receipts") or {})
    runtime_probe = dict(receipts.get("chatlab_runtime_probe_receipt") or {})
    if str(runtime_probe.get("status") or "").strip() == "provider_runtime_verified":
        issues.append("chatlab_preflight_runtime_probe_overclaim")
    contract = dict(receipt.get("chatlab_contract") or {})
    if contract.get("provider_memory_write_allowed") is True:
        issues.append("chatlab_preflight_nested_memory_write_overclaim")
    if sensitive_value_exposed(receipt):
        issues.append("chatlab_preflight_sensitive_value_exposed")
    return {
        "status": "fail" if issues else "pass",
        "issues": issues,
        "preflight": Path(path).as_posix(),
    }
