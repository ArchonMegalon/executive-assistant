from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class WebhookVerification:
    ok: bool
    reason: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def hedy_webhook_signature(body: bytes, secret: str, *, timestamp: str) -> str:
    payload = str(timestamp or "").encode("utf-8") + b"." + bytes(body or b"")
    return "sha256=" + hmac.new(str(secret or "").encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_hedy_webhook_signature(
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
    expected = hedy_webhook_signature(body, secret, timestamp=timestamp)
    if not hmac.compare_digest(str(signature_header or "").strip(), expected):
        return WebhookVerification(ok=False, reason="webhook_signature_mismatch")
    if str(timestamp or "").strip():
        try:
            observed = datetime.fromtimestamp(int(str(timestamp or "").strip()), tz=timezone.utc)
        except ValueError:
            return WebhookVerification(ok=False, reason="webhook_timestamp_invalid")
        delta = abs(((now or _utc_now()) - observed).total_seconds())
        if delta > max(int(tolerance_seconds or 300), 1):
            return WebhookVerification(ok=False, reason="webhook_timestamp_outside_tolerance")
    return WebhookVerification(ok=True, reason="pass")


def build_hedy_meeting_review_packet(
    payload: dict[str, object],
    *,
    principal_id: str,
    workspace_id: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    generated_at = now or _utc_now()
    session = dict(payload.get("session") or {})
    if not bool(session.get("recording_consent_confirmed")):
        return {
            "contract_name": "ea.hedy_meeting_evidence.v1",
            "status": "privacy_blocked",
            "blocking_reason": "recording_consent_required",
            "principal_id": str(principal_id or "").strip(),
            "workspace_id": str(workspace_id or "").strip(),
            "provider": "hedy.ai",
            "evidence_candidates": [],
            "commitment_candidates": [],
            "decision_candidates": [],
            "people_memory_candidates": [],
            "draft_candidates": [],
            "ea_review_objects": [],
            "memory_write_allowed": False,
            "commitment_write_allowed": False,
            "decision_write_allowed": False,
            "publication_allowed": False,
            "followup_send_allowed": False,
        }
    transcript = str(session.get("transcript") or "").strip()
    summary = str(session.get("summary") or "").strip()
    retention_until = (generated_at + timedelta(days=90)).isoformat()
    evidence_candidates = []
    if transcript:
        evidence_candidates.append(
            {
                "object_type": "evidence",
                "data_classification": "restricted",
                "content": transcript,
                "retention_until": retention_until,
            }
        )
    if summary:
        evidence_candidates.append(
            {
                "object_type": "evidence",
                "data_classification": "restricted",
                "content": summary,
                "retention_until": retention_until,
            }
        )
    commitment_candidates = [
        {
            "object_type": "commitment_candidate",
            "status": "review_required",
            "title": str(item.get("title") or "").strip(),
            "assignee": str(item.get("assignee") or "").strip(),
            "due_at": str(item.get("due_at") or "").strip(),
        }
        for item in list(session.get("action_items") or [])
        if str(dict(item or {}).get("title") or "").strip()
    ]
    decision_candidates = [
        {
            "object_type": "decision_candidate",
            "authority_required": "principal",
            "question": str(item.get("question") or "").strip(),
            "options": [str(option).strip() for option in list(item.get("options") or []) if str(option).strip()],
            "priority": str(item.get("priority") or "").strip(),
        }
        for item in list(session.get("decisions") or [])
        if str(dict(item or {}).get("question") or "").strip()
    ]
    people_memory_candidates = [
        {
            "object_type": "people_memory_candidate",
            "display_name": str(item.get("name") or "").strip(),
            "role": str(item.get("role") or "").strip(),
            "promotion_allowed_without_review": False,
        }
        for item in list(session.get("participants") or [])
        if str(dict(item or {}).get("name") or "").strip()
    ]
    draft_candidates = [
        {
            "object_type": "draft_candidate",
            "recipient": str(item.get("recipient") or "").strip(),
            "draft_text": str(item.get("draft_text") or "").strip(),
            "requires_approval": True,
            "send_allowed_without_approval": False,
        }
        for item in list(session.get("follow_ups") or [])
        if str(dict(item or {}).get("draft_text") or "").strip()
    ]
    review_objects = [*evidence_candidates, *commitment_candidates, *decision_candidates, *people_memory_candidates, *draft_candidates]
    idempotency_key = _sha256_text(
        "|".join(
            (
                str(payload.get("event_id") or "").strip(),
                str(session.get("id") or "").strip(),
                str(principal_id or "").strip(),
            )
        )
    )
    return {
        "contract_name": "ea.hedy_meeting_evidence.v1",
        "packet_id": f"hedy-packet-{idempotency_key[:12]}",
        "idempotency_key": idempotency_key,
        "status": "review_required",
        "principal_id": str(principal_id or "").strip(),
        "workspace_id": str(workspace_id or "").strip(),
        "provider": "hedy.ai",
        "evidence_candidates": evidence_candidates,
        "commitment_candidates": commitment_candidates,
        "decision_candidates": decision_candidates,
        "people_memory_candidates": people_memory_candidates,
        "draft_candidates": draft_candidates,
        "ea_review_objects": review_objects,
        "memory_write_allowed": False,
        "commitment_write_allowed": False,
        "decision_write_allowed": False,
        "publication_allowed": False,
        "followup_send_allowed": False,
    }


class HedyMeetingEvidenceService:
    def __init__(self, *, webhook_secret: str, clock=None, tolerance_seconds: int = 300) -> None:
        self._webhook_secret = str(webhook_secret or "").strip()
        self._clock = clock or _utc_now
        self._tolerance_seconds = max(int(tolerance_seconds or 300), 1)
        self._packets: dict[str, dict[str, object]] = {}

    @property
    def ingested_count(self) -> int:
        return len(self._packets)

    def ingest_webhook(
        self,
        *,
        body: bytes,
        headers: dict[str, object],
        principal_id: str,
        workspace_id: str = "",
    ) -> dict[str, object]:
        timestamp = str(headers.get("x-hedy-timestamp") or "").strip()
        signature = str(headers.get("x-hedy-signature") or "").strip()
        verification = verify_hedy_webhook_signature(
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
        packet = build_hedy_meeting_review_packet(
            payload,
            principal_id=principal_id,
            workspace_id=workspace_id,
            now=self._clock(),
        )
        packet["webhook_verification"] = {"status": "pass", "reason": verification.reason}
        key = str(packet.get("idempotency_key") or "").strip()
        existing = self._packets.get(key)
        if existing is not None:
            duplicate = dict(existing)
            duplicate["ingest_status"] = "duplicate"
            duplicate["idempotent_replay"] = True
            return duplicate
        packet["ingest_status"] = "created"
        packet["idempotent_replay"] = False
        self._packets[key] = dict(packet)
        return packet
