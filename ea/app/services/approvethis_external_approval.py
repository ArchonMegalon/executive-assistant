from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone


_FORBIDDEN_SOURCE_TYPES = {"raw_gmail", "customer_support_ticket"}
_SECRET_MARKERS = ("api_key=", "sk_live_", "secret-token")


@dataclass(frozen=True)
class WebhookVerification:
    ok: bool
    reason: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _contains_secret(value: object) -> bool:
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def approvethis_webhook_signature(body: bytes, secret: str, *, timestamp: str) -> str:
    payload = str(timestamp or "").encode("utf-8") + b"." + bytes(body or b"")
    digest = hmac.new(str(secret or "").encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_approvethis_webhook_signature(
    *,
    body: bytes,
    signature_header: str,
    secret: str,
    timestamp: str = "",
    now: datetime | None = None,
    tolerance_seconds: int = 300,
) -> WebhookVerification:
    if not str(secret or "").strip():
        return WebhookVerification(ok=False, reason="webhook_secret_required")
    expected = approvethis_webhook_signature(body, secret, timestamp=timestamp)
    if not hmac.compare_digest(str(signature_header or "").strip(), expected):
        return WebhookVerification(ok=False, reason="webhook_signature_mismatch")
    if str(timestamp or "").strip():
        try:
            observed = datetime.fromtimestamp(int(str(timestamp or "").strip()), tz=timezone.utc)
        except ValueError:
            return WebhookVerification(ok=False, reason="webhook_timestamp_invalid")
        current = now or _utc_now()
        delta = abs((current - observed).total_seconds())
        if delta > max(int(tolerance_seconds or 300), 1):
            return WebhookVerification(ok=False, reason="webhook_timestamp_outside_tolerance")
    return WebhookVerification(ok=True, reason="pass")


def build_approvethis_external_request(
    decision: dict[str, object],
    *,
    principal_id: str,
    external_approver_contact: str,
    workspace_id: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    normalized_decision = dict(decision or {})
    summary = str(normalized_decision.get("summary") or "").strip()
    source_type = str(normalized_decision.get("source_type") or "").strip()
    classification = str(normalized_decision.get("data_classification") or "internal").strip().lower()
    options = [str(item).strip() for item in list(normalized_decision.get("options") or []) if str(item).strip()]
    blocking_reasons: list[str] = []
    provider_content_redacted = False
    if str(normalized_decision.get("scope") or "").strip() != "bounded_decision":
        blocking_reasons.append("bounded_ea_decision_required")
    if classification in {"restricted", "board_private", "private"}:
        blocking_reasons.append("private_decision_not_external_transportable")
        provider_content_redacted = True
        options = []
        summary = ""
    if source_type in _FORBIDDEN_SOURCE_TYPES:
        blocking_reasons.append(f"forbidden_decision_source_type_{source_type}")
    if _contains_secret(summary):
        blocking_reasons.append("secret_marker_detected")
        provider_content_redacted = True
        options = []
        summary = ""
    status = "provider_request_ready" if not blocking_reasons else "blocked"
    blocking_reason = blocking_reasons[0] if blocking_reasons else ""
    return {
        "contract_name": "ea.approvethis_external_approval.v1",
        "status": status,
        "blocking_reason": blocking_reason,
        "blocking_reasons": blocking_reasons,
        "requested_at": (now or _utc_now()).isoformat(),
        "principal_id": str(principal_id or "").strip(),
        "workspace_id": str(workspace_id or "").strip(),
        "ea_decision_id": str(normalized_decision.get("decision_id") or "").strip(),
        "decision_title": str(normalized_decision.get("title") or "").strip(),
        "decision_summary": summary,
        "source_sha256": _sha256_text(json.dumps(normalized_decision, sort_keys=True)),
        "approver_contact_sha256": _sha256_text(external_approver_contact),
        "options": options,
        "external_transport_allowed": status == "provider_request_ready",
        "approval_truth_allowed": False,
        "downstream_action_allowed": False,
        "internal_queue_replaced": False,
        "provider_content_redacted": provider_content_redacted,
        "provider_request": {
            "status": "ready" if status == "provider_request_ready" else "blocked",
            "content_redacted": provider_content_redacted,
            "approver_contact_sha256": _sha256_text(external_approver_contact),
        },
        "validation": {
            "approval_truth_owner": "ea",
            "external_provider_data_boundary": "pass" if "private_decision_not_external_transportable" not in blocking_reasons else "fail",
            "downstream_action": "blocked",
        },
    }


class ApproveThisExternalApprovalService:
    def __init__(
        self,
        *,
        webhook_secret: str,
        clock=None,
        tolerance_seconds: int = 300,
    ) -> None:
        self._webhook_secret = str(webhook_secret or "").strip()
        self._clock = clock or _utc_now
        self._tolerance_seconds = max(int(tolerance_seconds or 300), 1)
        self._results: dict[str, dict[str, object]] = {}

    @property
    def result_count(self) -> int:
        return len(self._results)

    def ingest_webhook(
        self,
        *,
        body: bytes,
        headers: dict[str, object],
        request_packet: dict[str, object],
    ) -> dict[str, object]:
        timestamp = str(headers.get("x-approvethis-timestamp") or "").strip()
        signature = str(headers.get("x-approvethis-signature") or "").strip()
        verification = verify_approvethis_webhook_signature(
            body=body,
            signature_header=signature,
            secret=self._webhook_secret,
            timestamp=timestamp,
            now=self._clock(),
            tolerance_seconds=self._tolerance_seconds,
        )
        if not verification.ok:
            raise PermissionError(verification.reason)
        payload = json.loads(body.decode("utf-8"))
        if str(payload.get("ea_decision_id") or "").strip() != str(request_packet.get("ea_decision_id") or "").strip():
            raise ValueError("approvethis_decision_scope_mismatch")
        result_key = str(payload.get("event_id") or payload.get("provider_request_id") or "").strip()
        existing = self._results.get(result_key)
        if existing is not None:
            duplicate = dict(existing)
            duplicate["ingest_status"] = "duplicate"
            duplicate["idempotent_replay"] = True
            return duplicate
        result = {
            "contract_name": "ea.approvethis_external_approval_result.v1",
            "result_id": f"approvethis-result-{result_key or 'unknown'}",
            "status": "evidence_recorded",
            "provider_status": str(payload.get("status") or "").strip(),
            "ingest_status": "created",
            "idempotent_replay": False,
            "webhook_verification": {"status": "pass", "reason": verification.reason},
            "evidence": {
                "source_type": "approvethis_external_approval",
                "provider_request_id": str(payload.get("provider_request_id") or "").strip(),
                "decision_id": str(payload.get("ea_decision_id") or "").strip(),
            },
            "ea_decision_update": {
                "status": "ready_for_ea_apply",
                "requires_final_policy_gate": True,
            },
            "validation": {"downstream_action": "blocked"},
            "approval_truth_allowed": False,
            "downstream_action_allowed": False,
            "final_policy_required": True,
        }
        self._results[result_key] = dict(result)
        return result
