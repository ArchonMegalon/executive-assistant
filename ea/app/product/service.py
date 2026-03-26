from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.parse
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from app.domain.models import ApprovalRequest, Commitment, DecisionWindow, DeadlineWindow, FollowUp, HumanTask, Stakeholder
from app.product.commercial import workspace_commercial_snapshot, workspace_plan_for_mode
from app.product.extractors import extract_commitment_candidates
from app.product.models import (
    BriefItem,
    CommitmentCandidate,
    CommitmentItem,
    DecisionItem,
    DecisionQueueItem,
    DraftCandidate,
    EvidenceItem,
    EvidenceRef,
    HandoffNote,
    HistoryEntry,
    PersonDetail,
    PersonProfile,
    ProductSnapshot,
    RuleItem,
    ThreadItem,
)
from app.product.projections import (
    commitment_item_from_commitment,
    commitment_item_from_follow_up,
    compact_text,
    contains_token,
    decision_item_from_window,
    due_bonus,
    evidence_items_from_objects,
    handoff_from_human_task,
    priority_weight,
    rule_items_from_workspace,
    simulate_rule,
    status_open,
    thread_items_from_objects,
)

if TYPE_CHECKING:
    from app.container import AppContainer


_TEMPERATURE_BY_IMPORTANCE = {
    "critical": "hot",
    "high": "warm",
    "medium": "steady",
    "low": "cool",
}
_COMMITMENT_KEY_RE = re.compile(r"[^a-z0-9]+")
_READY_PROVIDER_STATES = {"ready", "healthy"}
_DEGRADED_PROVIDER_STATES = {"degraded", "cooldown", "rate_limited", "quarantined", "quota_low", "throttled"}
_FAILED_PROVIDER_STATES = {"error", "failed", "auth_failed", "revoked", "deleted", "expired", "unavailable", "missing"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_past_due(value: str | None) -> bool:
    when = _parse_iso(value)
    if when is None:
        return False
    return when <= datetime.now(timezone.utc)


def _hours_since(value: str | None) -> int:
    when = _parse_iso(value)
    if when is None:
        return 0
    return max(int((datetime.now(timezone.utc) - when).total_seconds() // 3600), 0)


def _action_label(action_json: dict[str, object]) -> str:
    raw = str(action_json.get("action") or action_json.get("event_type") or "review").strip().replace("_", " ").replace(".", " ")
    return raw or "review"


def _search_tokens(value: str) -> tuple[str, ...]:
    normalized = _COMMITMENT_KEY_RE.sub(" ", str(value or "").strip().lower()).strip()
    if not normalized:
        return ()
    return tuple(part for part in normalized.split() if part)


def _search_score(*, tokens: tuple[str, ...], title: str = "", summary: str = "", extra: tuple[str, ...] = ()) -> float:
    if not tokens:
        return 0.0
    title_text = str(title or "").strip().lower()
    summary_text = str(summary or "").strip().lower()
    extra_text = " ".join(str(part or "").strip().lower() for part in extra if str(part or "").strip())
    score = 0.0
    full_query = " ".join(tokens)
    if full_query and title_text and full_query in title_text:
        score += 8.0
    if full_query and summary_text and full_query in summary_text:
        score += 4.0
    for token in tokens:
        if token in title_text:
            score += 5.0
        if token in summary_text:
            score += 3.0
        if extra_text and token in extra_text:
            score += 2.0
    return score


def _operator_id_from_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    local = normalized.split("@", 1)[0] if "@" in normalized else normalized
    slug = _COMMITMENT_KEY_RE.sub("-", local).strip("-")
    return f"operator-{slug or uuid4().hex[:6]}"


def _sign_channel_payload(*, secret: str, payload: dict[str, object]) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_channel_payload(*, secret: str, token: str) -> dict[str, object] | None:
    normalized = str(token or "").strip()
    if not normalized or "." not in normalized:
        return None
    payload_b64, signature = normalized.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(f"{payload_b64}{padding}".encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expires_at = _parse_iso(str(payload.get("expires_at") or "").strip())
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        return None
    return payload


class ProductService:
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    def _channel_action_secret(self) -> str:
        configured = str(self._container.settings.auth.api_token or "").strip()
        if configured:
            return configured
        fallback = str(self._container.settings.auth.default_principal_id or "").strip() or "ea-channel-loop"
        return f"{fallback}:channel-actions"

    def _record_product_event(
        self,
        *,
        principal_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        source_id: str = "",
        dedupe_key: str = "",
    ) -> None:
        event = self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type=event_type,
            payload=dict(payload or {}),
            source_id=source_id,
            dedupe_key=dedupe_key,
        )
        normalized_type = str(event_type or "").strip().lower()
        if normalized_type and not normalized_type.startswith("webhook_"):
            self._queue_webhook_deliveries(
                principal_id=principal_id,
                matched_event_type=normalized_type,
                payload=dict(payload or {}),
                source_id=str(source_id or event.observation_id or "").strip(),
            )

    def _stakeholder_lookup(self, principal_id: str) -> dict[str, Stakeholder]:
        rows = self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=200)
        return {row.stakeholder_id: row for row in rows}

    def _commitment_item_from_commitment(self, row: Commitment) -> CommitmentItem:
        return commitment_item_from_commitment(row)

    def _commitment_item_from_follow_up(self, row: FollowUp, stakeholders: dict[str, Stakeholder]) -> CommitmentItem:
        return commitment_item_from_follow_up(row, stakeholders)

    def _commitment_identity_key(self, *, title: str, counterparty: str = "") -> str:
        normalized_title = _COMMITMENT_KEY_RE.sub(" ", str(title or "").strip().lower()).strip()
        normalized_counterparty = _COMMITMENT_KEY_RE.sub(" ", str(counterparty or "").strip().lower()).strip()
        if normalized_counterparty:
            counterparty_parts = tuple(part for part in normalized_counterparty.split() if part)
            stripped = False
            suffixes: list[str] = [normalized_counterparty]
            for index in range(len(counterparty_parts), 0, -1):
                suffixes.append(" ".join(counterparty_parts[:index]))
            for suffix in suffixes:
                for prefix in (f" to {suffix}", f" for {suffix}", f" with {suffix}"):
                    if normalized_title.endswith(prefix):
                        normalized_title = normalized_title[: -len(prefix)].strip()
                        stripped = True
                        break
                if stripped:
                    break
            if not stripped:
                for suffix in suffixes:
                    if normalized_title.endswith(suffix):
                        normalized_title = normalized_title[: -len(suffix)].strip()
                        break
        return f"{normalized_title}|{normalized_counterparty}"

    def _append_unique_refs(self, current: object, *values: str) -> tuple[str, ...]:
        seen: set[str] = set()
        rows: list[str] = []
        if isinstance(current, (list, tuple)):
            for item in current:
                normalized = str(item or "").strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    rows.append(normalized)
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                rows.append(normalized)
        return tuple(rows)

    def _find_duplicate_commitment_ref(self, *, principal_id: str, title: str, counterparty: str = "") -> str:
        wanted = self._commitment_identity_key(title=title, counterparty=counterparty)
        if not wanted or wanted == "|":
            return ""
        stakeholders = self._stakeholder_lookup(principal_id)
        for row in self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=200, status=None):
            candidate = self._commitment_item_from_commitment(row)
            if self._commitment_identity_key(title=candidate.statement, counterparty=candidate.counterparty) == wanted:
                return candidate.id
        for row in self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=200, status=None):
            candidate = self._commitment_item_from_follow_up(row, stakeholders)
            if self._commitment_identity_key(title=candidate.statement, counterparty=candidate.counterparty) == wanted:
                return candidate.id
        return ""

    def _merge_candidate_into_existing(
        self,
        *,
        principal_id: str,
        duplicate_ref: str,
        candidate_id: str,
        title: str,
        details: str,
        due_at: str | None,
        counterparty: str,
        confidence: float,
    ) -> CommitmentItem | None:
        if duplicate_ref.startswith("commitment:"):
            current = self._container.memory_runtime.get_commitment(duplicate_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            merged_from_refs = self._append_unique_refs(source.get("merged_from_refs"), candidate_id)
            updated = self._container.memory_runtime.upsert_commitment(
                principal_id=principal_id,
                commitment_id=current.commitment_id,
                title=current.title,
                details=current.details if details.strip() in {"", current.details.strip()} else f"{current.details}\n\nMerged candidate: {details.strip()}".strip(),
                status="open" if not status_open(current.status) else current.status,
                priority=current.priority,
                due_at=due_at or current.due_at,
                source_json={
                    **source,
                    "counterparty": counterparty.strip() or str(source.get("counterparty") or ""),
                    "confidence": max(float(source.get("confidence") or 0.0), confidence),
                    "merged_from_refs": list(merged_from_refs),
                    "resolution_code": "" if not status_open(current.status) else str(source.get("resolution_code") or ""),
                    "resolution_reason": "" if not status_open(current.status) else str(source.get("resolution_reason") or ""),
                    "reopened_at": _now_iso() if not status_open(current.status) else str(source.get("reopened_at") or ""),
                },
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_merged" if status_open(current.status) else "commitment_reopened",
                payload={"candidate_id": candidate_id, "duplicate_of_ref": duplicate_ref, "title": title},
                source_id=current.commitment_id,
            )
            return self._commitment_item_from_commitment(updated)
        if duplicate_ref.startswith("follow_up:"):
            current = self._container.memory_runtime.get_follow_up(duplicate_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            merged_from_refs = self._append_unique_refs(source.get("merged_from_refs"), candidate_id)
            updated = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                follow_up_id=current.follow_up_id,
                stakeholder_ref=current.stakeholder_ref,
                topic=current.topic,
                status="open" if not status_open(current.status) else current.status,
                due_at=due_at or current.due_at,
                channel_hint=current.channel_hint,
                notes=current.notes if details.strip() in {"", current.notes.strip()} else f"{current.notes}\n\nMerged candidate: {details.strip()}".strip(),
                source_json={
                    **source,
                    "counterparty": counterparty.strip() or str(source.get("counterparty") or ""),
                    "confidence": max(float(source.get("confidence") or 0.0), confidence),
                    "merged_from_refs": list(merged_from_refs),
                    "resolution_code": "" if not status_open(current.status) else str(source.get("resolution_code") or ""),
                    "resolution_reason": "" if not status_open(current.status) else str(source.get("resolution_reason") or ""),
                    "reopened_at": _now_iso() if not status_open(current.status) else str(source.get("reopened_at") or ""),
                },
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_merged" if status_open(current.status) else "commitment_reopened",
                payload={"candidate_id": candidate_id, "duplicate_of_ref": duplicate_ref, "title": title},
                source_id=current.follow_up_id,
            )
            return self._commitment_item_from_follow_up(updated, self._stakeholder_lookup(principal_id))
        return None

    def _handoff_from_human_task(self, task: HumanTask) -> HandoffNote:
        return handoff_from_human_task(task)

    def _provider_summary(self, registry: dict[str, object]) -> dict[str, object]:
        provider_rows = [dict(row) for row in (registry.get("providers") or []) if isinstance(row, dict)]
        lane_rows = [dict(row) for row in (registry.get("lanes") or []) if isinstance(row, dict)]
        provider_state_by_key: dict[str, str] = {}
        ready_keys: list[str] = []
        degraded_keys: list[str] = []
        failed_keys: list[str] = []
        unknown_keys: list[str] = []
        for row in provider_rows:
            provider_key = str(row.get("provider_key") or "").strip()
            state = str(row.get("state") or row.get("health_state") or "unknown").strip().lower() or "unknown"
            if provider_key:
                provider_state_by_key[provider_key] = state
            if state in _READY_PROVIDER_STATES:
                ready_keys.append(provider_key or state)
            elif state in _DEGRADED_PROVIDER_STATES:
                degraded_keys.append(provider_key or state)
            elif state in _FAILED_PROVIDER_STATES:
                failed_keys.append(provider_key or state)
            else:
                unknown_keys.append(provider_key or state)
        lanes_with_fallback = 0
        degraded_primary_lanes = 0
        failover_ready_lanes = 0
        for row in lane_rows:
            hint_order = [str(value).strip() for value in (row.get("provider_hint_order") or []) if str(value).strip()]
            if len(hint_order) > 1:
                lanes_with_fallback += 1
            primary_state = str(row.get("primary_state") or "unknown").strip().lower() or "unknown"
            if primary_state in (_DEGRADED_PROVIDER_STATES | _FAILED_PROVIDER_STATES):
                degraded_primary_lanes += 1
                secondary_states = [provider_state_by_key.get(key, "unknown") for key in hint_order[1:]]
                if any(state in (_READY_PROVIDER_STATES | _DEGRADED_PROVIDER_STATES) for state in secondary_states):
                    failover_ready_lanes += 1
        if failed_keys or (provider_rows and not ready_keys and not degraded_keys):
            risk_state = "critical"
            risk_detail = "At least one provider lane is failed or no ready provider remains bound for this workspace."
        elif degraded_keys or degraded_primary_lanes:
            risk_state = "watch"
            risk_detail = "At least one provider or primary routing lane is degraded and needs operator attention."
        elif not provider_rows:
            risk_state = "attention"
            risk_detail = "No providers are currently bound for this workspace."
        else:
            risk_state = "healthy"
            risk_detail = "Provider routing and failover posture are stable for the current workspace."
        return {
            "ready_count": len(ready_keys),
            "degraded_count": len(degraded_keys),
            "failed_count": len(failed_keys),
            "unknown_count": len(unknown_keys),
            "ready_provider_keys": ready_keys[:8],
            "degraded_provider_keys": degraded_keys[:8],
            "failed_provider_keys": failed_keys[:8],
            "lanes_with_fallback": lanes_with_fallback,
            "degraded_primary_lanes": degraded_primary_lanes,
            "failover_ready_lanes": failover_ready_lanes,
            "risk_state": risk_state,
            "risk_detail": risk_detail,
        }

    def list_commitments(self, *, principal_id: str, limit: int = 50) -> tuple[CommitmentItem, ...]:
        stakeholders = self._stakeholder_lookup(principal_id)
        rows: list[CommitmentItem] = []
        for commitment in self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_commitment(commitment))
        for follow_up in self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_follow_up(follow_up, stakeholders))
        rows = [row for row in rows if status_open(row.status)]
        rows.sort(key=lambda row: (priority_weight(row.risk_level), due_bonus(row.due_at), row.statement.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_commitment(self, *, principal_id: str, commitment_ref: str) -> CommitmentItem | None:
        if commitment_ref.startswith("commitment:"):
            found = self._container.memory_runtime.get_commitment(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            return None if found is None else self._commitment_item_from_commitment(found)
        if commitment_ref.startswith("follow_up:"):
            found = self._container.memory_runtime.get_follow_up(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if found is None:
                return None
            return self._commitment_item_from_follow_up(found, self._stakeholder_lookup(principal_id))
        return None

    def _history_entries(self, *, principal_id: str, source_ids: tuple[str, ...] = (), limit: int = 20) -> tuple[HistoryEntry, ...]:
        wanted = {str(value).strip() for value in source_ids if str(value).strip()}
        rows: list[HistoryEntry] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id):
            if str(row.channel or "").strip() != "product":
                continue
            source_id = str(row.source_id or "").strip()
            payload = dict(row.payload or {})
            if wanted and source_id not in wanted and str(payload.get("person_id") or "").strip() not in wanted:
                continue
            rows.append(
                HistoryEntry(
                    event_type=str(row.event_type or ""),
                    created_at=str(row.created_at or ""),
                    source_id=source_id,
                    actor=str(payload.get("actor") or payload.get("reviewer") or payload.get("decided_by") or ""),
                    detail=str(payload.get("reason") or payload.get("surface") or payload.get("candidate_id") or ""),
                )
            )
        rows.sort(key=lambda item: (str(item.created_at or ""), str(item.event_type or "")), reverse=True)
        return tuple(rows[:limit])

    def get_commitment_history(self, *, principal_id: str, commitment_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        if ":" in commitment_ref:
            source_id = commitment_ref.split(":", 1)[1]
        else:
            source_id = commitment_ref
        return self._history_entries(principal_id=principal_id, source_ids=(source_id,), limit=limit)

    def _event_object_refs(self, *, source_id: str, payload: dict[str, object]) -> tuple[str, ...]:
        refs: list[str] = []
        for key in (
            "commitment_ref",
            "decision_ref",
            "thread_ref",
            "evidence_ref",
            "rule_ref",
            "handoff_ref",
            "draft_ref",
        ):
            value = str(payload.get(key) or "").strip()
            if value:
                refs.append(value)
        for key in ("commitment_refs", "decision_refs", "thread_refs", "evidence_refs", "rule_refs"):
            for value in (payload.get(key) or []):
                normalized = str(value or "").strip()
                if normalized:
                    refs.append(normalized)
        normalized_source = str(source_id or "").strip()
        if normalized_source:
            refs.append(normalized_source)
        return self._append_unique_refs(refs)

    def list_office_events(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        event_type: str = "",
        channel: str = "",
    ) -> tuple[dict[str, object], ...]:
        wanted_type = str(event_type or "").strip().lower()
        wanted_channel = str(channel or "").strip().lower()
        rows: list[dict[str, object]] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=max(limit * 4, 200), principal_id=principal_id):
            normalized_channel = str(row.channel or "").strip().lower()
            normalized_type = str(row.event_type or "").strip().lower()
            if wanted_channel and normalized_channel != wanted_channel:
                continue
            if wanted_type and normalized_type != wanted_type:
                continue
            payload = dict(row.payload or {})
            summary = (
                str(payload.get("summary") or "").strip()
                or str(payload.get("title") or "").strip()
                or str(payload.get("reason") or "").strip()
                or str(payload.get("text") or "").strip()
                or str(payload.get("surface") or "").strip()
                or normalized_type.replace("_", " ")
            )
            rows.append(
                {
                    "observation_id": str(row.observation_id or ""),
                    "channel": str(row.channel or ""),
                    "event_type": str(row.event_type or ""),
                    "created_at": str(row.created_at or ""),
                    "source_id": str(row.source_id or ""),
                    "external_id": str(row.external_id or ""),
                    "summary": summary[:220],
                    "object_refs": list(self._event_object_refs(source_id=str(row.source_id or ""), payload=payload)),
                    "payload": payload,
                }
            )
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("observation_id") or "")), reverse=True)
        return tuple(rows[:limit])

    def ingest_office_signal(
        self,
        *,
        principal_id: str,
        signal_type: str,
        channel: str = "office_api",
        title: str = "",
        summary: str = "",
        text: str = "",
        source_ref: str = "",
        external_id: str = "",
        counterparty: str = "",
        stakeholder_id: str = "",
        due_at: str | None = None,
        payload: dict[str, object] | None = None,
        actor: str = "",
    ) -> dict[str, object]:
        normalized_signal = str(signal_type or "").strip().lower()
        normalized_channel = str(channel or "office_api").strip().lower() or "office_api"
        summary_text = str(summary or "").strip()
        title_text = str(title or "").strip()
        source_text = str(text or "").strip() or " ".join(part for part in (title_text, summary_text) if part).strip()
        dedupe_parts = [
            "office-signal",
            principal_id,
            normalized_signal,
            str(external_id or "").strip(),
            str(source_ref or "").strip(),
            source_text[:80],
        ]
        dedupe_key = "|".join(part for part in dedupe_parts if part)
        staged = self.stage_extracted_commitments(
            principal_id=principal_id,
            text=source_text,
            counterparty=counterparty,
            due_at=due_at,
            kind="follow_up" if "follow" in normalized_signal or "meeting" in normalized_signal else "commitment",
            stakeholder_id=stakeholder_id,
        ) if source_text else ()
        payload_json = {
            "signal_type": normalized_signal,
            "title": title_text,
            "summary": summary_text,
            "text": source_text,
            "counterparty": str(counterparty or "").strip(),
            "stakeholder_id": str(stakeholder_id or "").strip(),
            "due_at": str(due_at or "").strip(),
            "actor": str(actor or "").strip() or "office_api",
            "staged_candidate_ids": [row.candidate_id for row in staged if str(row.candidate_id or "").strip()],
            **dict(payload or {}),
        }
        event = self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel=normalized_channel,
            event_type=f"office_signal_{normalized_signal}",
            payload=payload_json,
            source_id=str(source_ref or "").strip(),
            external_id=str(external_id or "").strip(),
            dedupe_key=dedupe_key,
        )
        self._queue_webhook_deliveries(
            principal_id=principal_id,
            matched_event_type=str(event.event_type or ""),
            payload=payload_json,
            source_id=str(source_ref or event.observation_id or "").strip(),
            external_id=str(external_id or "").strip(),
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="office_signal_ingested",
            payload={
                "signal_type": normalized_signal,
                "channel": normalized_channel,
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "staged_count": len(staged),
            },
            source_id=str(source_ref or event.observation_id or "").strip(),
        )
        return {
            "observation_id": str(event.observation_id or ""),
            "channel": str(event.channel or ""),
            "event_type": str(event.event_type or ""),
            "source_id": str(event.source_id or ""),
            "external_id": str(event.external_id or ""),
            "created_at": str(event.created_at or ""),
            "staged_candidates": [
                {
                    "candidate_id": row.candidate_id,
                    "title": row.title,
                    "details": row.details,
                    "source_text": row.source_text,
                    "confidence": row.confidence,
                    "suggested_due_at": row.suggested_due_at,
                    "counterparty": row.counterparty,
                    "status": row.status,
                    "kind": row.kind,
                    "stakeholder_id": row.stakeholder_id,
                    "duplicate_of_ref": row.duplicate_of_ref,
                    "merge_strategy": row.merge_strategy,
                }
                for row in staged
            ],
            "staged_count": len(staged),
        }

    def search_workspace(
        self,
        *,
        principal_id: str,
        query: str,
        limit: int = 20,
        operator_id: str = "",
    ) -> tuple[dict[str, object], ...]:
        tokens = _search_tokens(query)
        if not tokens:
            return ()
        rows: list[dict[str, object]] = []

        def add_result(
            *,
            id: str,
            kind: str,
            title: str,
            summary: str = "",
            href: str = "",
            secondary_label: str = "",
            related_object_refs: tuple[str, ...] = (),
            extra: tuple[str, ...] = (),
        ) -> None:
            score = _search_score(tokens=tokens, title=title, summary=summary, extra=extra)
            if score <= 0:
                return
            rows.append(
                {
                    "id": id,
                    "kind": kind,
                    "title": str(title or "").strip(),
                    "summary": str(summary or "").strip()[:220],
                    "href": href,
                    "score": score,
                    "secondary_label": secondary_label,
                    "related_object_refs": list(related_object_refs),
                }
            )

        for person in self.list_people(principal_id=principal_id, limit=max(limit * 2, 25)):
            add_result(
                id=person.id,
                kind="person",
                title=person.display_name,
                summary=f"{person.role_or_company} · {person.relationship_temperature} · {person.open_loops_count} open loops",
                href=f"/app/people/{urllib.parse.quote(person.id, safe='')}",
                secondary_label=person.relationship_temperature,
                related_object_refs=(person.id,),
                extra=tuple(person.themes) + tuple(person.risks) + (person.preferred_tone, person.role_or_company),
            )

        for thread in self.list_threads(principal_id=principal_id, limit=max(limit * 2, 25)):
            add_result(
                id=thread.id,
                kind="thread",
                title=thread.title,
                summary=thread.summary,
                href=f"/app/threads/{urllib.parse.quote(thread.id, safe='')}",
                secondary_label=thread.channel,
                related_object_refs=tuple(thread.related_commitment_ids) + tuple(thread.related_decision_ids),
                extra=tuple(thread.counterparties) + tuple(thread.draft_ids),
            )

        for commitment in self.list_commitments(principal_id=principal_id, limit=max(limit * 3, 40)):
            add_result(
                id=commitment.id,
                kind="commitment",
                title=commitment.statement,
                summary=f"{commitment.counterparty} · {commitment.status} · {commitment.risk_level}",
                href=f"/app/follow-ups?focus={urllib.parse.quote(commitment.id, safe='')}",
                secondary_label=commitment.status,
                related_object_refs=(commitment.id,),
                extra=(commitment.counterparty, commitment.owner, commitment.channel_hint, commitment.source_ref),
            )

        for decision in self.list_decisions(principal_id=principal_id, limit=max(limit * 2, 25)):
            add_result(
                id=decision.id,
                kind="decision",
                title=decision.title,
                summary=decision.summary,
                href=f"/app/decisions/{urllib.parse.quote(decision.id, safe='')}",
                secondary_label=decision.status,
                related_object_refs=tuple(decision.related_commitment_ids) + tuple(decision.linked_thread_ids),
                extra=tuple(decision.options) + tuple(decision.related_people) + (decision.recommendation, decision.next_action, decision.rationale),
            )

        for evidence in self.list_evidence(principal_id=principal_id, limit=max(limit * 2, 25), operator_id=operator_id):
            add_result(
                id=evidence.id,
                kind="evidence",
                title=evidence.label,
                summary=evidence.summary,
                href=f"/app/evidence/{urllib.parse.quote(evidence.id, safe='')}",
                secondary_label=evidence.source_type,
                related_object_refs=(evidence.id,),
                extra=(evidence.source_type,),
            )

        for rule in self.list_rules(principal_id=principal_id):
            add_result(
                id=rule.id,
                kind="rule",
                title=rule.label,
                summary=rule.summary,
                href=f"/app/rules/{urllib.parse.quote(rule.id, safe='')}",
                secondary_label=rule.scope,
                related_object_refs=(rule.id,),
                extra=(rule.scope, rule.current_value, rule.impact, rule.status, rule.simulated_effect),
            )

        rows.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("title") or "").lower(), str(item.get("id") or "")), reverse=True)
        return tuple(rows[:limit])

    def list_webhooks(self, *, principal_id: str, limit: int = 50) -> tuple[dict[str, object], ...]:
        configs: dict[str, dict[str, object]] = {}
        delivery_meta: dict[str, dict[str, object]] = {}
        for row in self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id):
            event_type = str(row.event_type or "").strip().lower()
            payload = dict(row.payload or {})
            if event_type == "webhook_registered":
                webhook_id = str(payload.get("webhook_id") or row.source_id or "").strip()
                if webhook_id and webhook_id not in configs:
                    configs[webhook_id] = {
                        "webhook_id": webhook_id,
                        "label": str(payload.get("label") or webhook_id).strip(),
                        "target_url": str(payload.get("target_url") or "").strip(),
                        "status": str(payload.get("status") or "active").strip() or "active",
                        "event_types": [str(item).strip().lower() for item in payload.get("event_types") or [] if str(item).strip()],
                        "created_at": str(payload.get("created_at") or row.created_at or ""),
                        "last_delivery_at": "",
                        "delivery_count": 0,
                    }
            elif event_type == "webhook_delivery_queued":
                webhook_id = str(payload.get("webhook_id") or "").strip()
                if not webhook_id:
                    continue
                slot = delivery_meta.setdefault(webhook_id, {"delivery_count": 0, "last_delivery_at": ""})
                slot["delivery_count"] = int(slot.get("delivery_count") or 0) + 1
                created_at = str(row.created_at or "")
                if created_at and created_at > str(slot.get("last_delivery_at") or ""):
                    slot["last_delivery_at"] = created_at
        rows: list[dict[str, object]] = []
        for webhook_id, config in configs.items():
            meta = delivery_meta.get(webhook_id, {})
            rows.append(
                {
                    **config,
                    "last_delivery_at": str(meta.get("last_delivery_at") or ""),
                    "delivery_count": int(meta.get("delivery_count") or 0),
                }
            )
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("webhook_id") or "")), reverse=True)
        return tuple(rows[:limit])

    def get_webhook(self, *, principal_id: str, webhook_id: str) -> dict[str, object] | None:
        normalized = str(webhook_id or "").strip()
        if not normalized:
            return None
        for row in self.list_webhooks(principal_id=principal_id, limit=200):
            if str(row.get("webhook_id") or "").strip() == normalized:
                return row
        return None

    def register_webhook(
        self,
        *,
        principal_id: str,
        label: str,
        target_url: str,
        event_types: tuple[str, ...] = (),
        status: str = "active",
    ) -> dict[str, object]:
        webhook_id = f"webhook_{uuid4().hex[:10]}"
        payload = {
            "webhook_id": webhook_id,
            "label": str(label or "").strip(),
            "target_url": str(target_url or "").strip(),
            "event_types": [str(item).strip().lower() for item in event_types if str(item).strip()],
            "status": str(status or "active").strip().lower() or "active",
            "created_at": _now_iso(),
        }
        self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type="webhook_registered",
            payload=payload,
            source_id=webhook_id,
            external_id=str(target_url or "").strip(),
            dedupe_key=f"{principal_id}|{webhook_id}",
        )
        found = self.get_webhook(principal_id=principal_id, webhook_id=webhook_id)
        return dict(found or payload)

    def _queue_single_webhook_delivery(
        self,
        *,
        principal_id: str,
        webhook: dict[str, object],
        matched_event_type: str,
        payload: dict[str, object],
        source_id: str = "",
        external_id: str = "",
        delivery_kind: str = "event",
    ) -> dict[str, object]:
        webhook_id = str(webhook.get("webhook_id") or "").strip()
        delivery_id = f"{webhook_id}:{matched_event_type}:{str(external_id or source_id or uuid4().hex[:8]).strip()}"
        event_payload = {
            "webhook_id": webhook_id,
            "label": str(webhook.get("label") or webhook_id).strip(),
            "target_url": str(webhook.get("target_url") or "").strip(),
            "matched_event_type": str(matched_event_type or "").strip().lower(),
            "delivery_kind": str(delivery_kind or "event").strip().lower() or "event",
            "status": "queued",
            "summary": str(payload.get("summary") or payload.get("title") or matched_event_type).strip(),
            "event_payload": dict(payload or {}),
        }
        event = self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type="webhook_delivery_queued",
            payload=event_payload,
            source_id=str(source_id or webhook_id).strip(),
            external_id=delivery_id,
            dedupe_key=delivery_id,
        )
        return {
            "delivery_id": delivery_id,
            "webhook_id": webhook_id,
            "label": str(event_payload.get("label") or "").strip(),
            "target_url": str(event_payload.get("target_url") or "").strip(),
            "matched_event_type": str(event_payload.get("matched_event_type") or "").strip(),
            "delivery_kind": str(event_payload.get("delivery_kind") or "event").strip(),
            "status": "queued",
            "created_at": str(event.created_at or ""),
            "source_id": str(source_id or webhook_id).strip(),
            "summary": str(event_payload.get("summary") or "").strip(),
            "payload": dict(payload or {}),
        }

    def _queue_webhook_deliveries(
        self,
        *,
        principal_id: str,
        matched_event_type: str,
        payload: dict[str, object],
        source_id: str = "",
        external_id: str = "",
        delivery_kind: str = "event",
    ) -> tuple[dict[str, object], ...]:
        normalized_type = str(matched_event_type or "").strip().lower()
        if not normalized_type:
            return ()
        rows: list[dict[str, object]] = []
        for webhook in self.list_webhooks(principal_id=principal_id, limit=100):
            if str(webhook.get("status") or "active").strip().lower() != "active":
                continue
            filters = tuple(str(item).strip().lower() for item in webhook.get("event_types") or [] if str(item).strip())
            if filters and normalized_type not in filters:
                continue
            rows.append(
                self._queue_single_webhook_delivery(
                    principal_id=principal_id,
                    webhook=webhook,
                    matched_event_type=normalized_type,
                    payload=payload,
                    source_id=source_id,
                    external_id=external_id,
                    delivery_kind=delivery_kind,
                )
            )
        return tuple(rows)

    def list_webhook_deliveries(
        self,
        *,
        principal_id: str,
        webhook_id: str = "",
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        wanted_webhook = str(webhook_id or "").strip()
        rows: list[dict[str, object]] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id):
            if str(row.event_type or "").strip().lower() != "webhook_delivery_queued":
                continue
            payload = dict(row.payload or {})
            current_webhook = str(payload.get("webhook_id") or "").strip()
            if wanted_webhook and current_webhook != wanted_webhook:
                continue
            rows.append(
                {
                    "delivery_id": str(row.external_id or ""),
                    "webhook_id": current_webhook,
                    "label": str(payload.get("label") or "").strip(),
                    "target_url": str(payload.get("target_url") or "").strip(),
                    "matched_event_type": str(payload.get("matched_event_type") or "").strip(),
                    "delivery_kind": str(payload.get("delivery_kind") or "event").strip(),
                    "status": str(payload.get("status") or "queued").strip(),
                    "created_at": str(row.created_at or ""),
                    "source_id": str(row.source_id or "").strip(),
                    "summary": str(payload.get("summary") or "").strip(),
                    "payload": dict(payload.get("event_payload") or {}),
                }
            )
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("delivery_id") or "")), reverse=True)
        return tuple(rows[:limit])

    def test_webhook(self, *, principal_id: str, webhook_id: str) -> dict[str, object] | None:
        webhook = self.get_webhook(principal_id=principal_id, webhook_id=webhook_id)
        if webhook is None:
            return None
        delivery = self._queue_single_webhook_delivery(
            principal_id=principal_id,
            webhook=webhook,
            matched_event_type="webhook_test_ping",
            payload={"summary": "Webhook test ping", "webhook_id": webhook_id},
            source_id=webhook_id,
            delivery_kind="test",
        )
        return {"webhook": webhook, "delivery": delivery}

    def list_workspace_invitations(
        self,
        *,
        principal_id: str,
        status: str = "",
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        wanted_status = str(status or "").strip().lower()
        invitations: dict[str, dict[str, object]] = {}
        rows = list(self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id))
        rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
        for row in rows:
            event_type = str(row.event_type or "").strip().lower()
            payload = dict(row.payload or {})
            invitation_id = str(payload.get("invitation_id") or row.source_id or "").strip()
            if not invitation_id:
                continue
            if event_type == "workspace_invitation_created":
                invitations[invitation_id] = {
                    "invitation_id": invitation_id,
                    "email": str(payload.get("email") or "").strip().lower(),
                    "role": str(payload.get("role") or "operator").strip().lower() or "operator",
                    "display_name": str(payload.get("display_name") or "").strip(),
                    "note": str(payload.get("note") or "").strip(),
                    "status": "pending",
                    "invited_by": str(payload.get("invited_by") or "").strip(),
                    "invited_at": str(payload.get("invited_at") or row.created_at or ""),
                    "expires_at": str(payload.get("expires_at") or "").strip(),
                    "accepted_at": "",
                    "accepted_by": "",
                    "revoked_at": "",
                    "invite_url": str(payload.get("invite_url") or "").strip(),
                    "invite_token": str(payload.get("invite_token") or "").strip(),
                    "operator_id": str(payload.get("operator_id") or "").strip(),
                }
            elif event_type == "workspace_invitation_accepted" and invitation_id in invitations:
                invitations[invitation_id].update(
                    {
                        "status": "accepted",
                        "accepted_at": str(payload.get("accepted_at") or row.created_at or ""),
                        "accepted_by": str(payload.get("accepted_by") or "").strip(),
                        "operator_id": str(payload.get("operator_id") or invitations[invitation_id].get("operator_id") or "").strip(),
                    }
                )
            elif event_type == "workspace_invitation_revoked" and invitation_id in invitations:
                invitations[invitation_id].update(
                    {
                        "status": "revoked",
                        "revoked_at": str(payload.get("revoked_at") or row.created_at or ""),
                    }
                )
        items = list(invitations.values())
        if wanted_status:
            items = [item for item in items if str(item.get("status") or "").strip().lower() == wanted_status]
        items.sort(key=lambda item: (str(item.get("invited_at") or ""), str(item.get("invitation_id") or "")), reverse=True)
        return tuple(items[:limit])

    def get_workspace_invitation(self, *, principal_id: str, invitation_id: str) -> dict[str, object] | None:
        normalized = str(invitation_id or "").strip()
        if not normalized:
            return None
        for row in self.list_workspace_invitations(principal_id=principal_id, limit=200):
            if str(row.get("invitation_id") or "").strip() == normalized:
                return row
        return None

    def create_workspace_invitation(
        self,
        *,
        principal_id: str,
        email: str,
        role: str,
        invited_by: str,
        display_name: str = "",
        note: str = "",
        expires_in_days: int = 14,
    ) -> dict[str, object]:
        normalized_email = str(email or "").strip().lower()
        normalized_role = str(role or "operator").strip().lower() or "operator"
        invitation_id = f"invite_{uuid4().hex[:10]}"
        expires_at = datetime.now(timezone.utc).timestamp() + max(int(expires_in_days), 1) * 86400
        token_payload = {
            "token_kind": "workspace_invitation",
            "principal_id": principal_id,
            "invitation_id": invitation_id,
            "email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
        invite_token = _sign_channel_payload(secret=self._channel_action_secret(), payload=token_payload)
        payload = {
            "invitation_id": invitation_id,
            "email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "note": str(note or "").strip(),
            "invited_by": str(invited_by or "").strip() or "workspace",
            "invited_at": _now_iso(),
            "expires_at": str(token_payload["expires_at"]),
            "invite_token": invite_token,
            "invite_url": f"/workspace-invites/{invite_token}",
            "operator_id": _operator_id_from_email(normalized_email) if normalized_role == "operator" else "",
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_invitation_created",
            payload=payload,
            source_id=invitation_id,
            dedupe_key=f"{principal_id}|{invitation_id}",
        )
        found = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        return dict(found or payload)

    def preview_workspace_invitation(self, *, token: str) -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._channel_action_secret(), token=token)
        if payload is None or str(payload.get("token_kind") or "").strip() != "workspace_invitation":
            return None
        principal_id = str(payload.get("principal_id") or "").strip()
        invitation_id = str(payload.get("invitation_id") or "").strip()
        if not principal_id or not invitation_id:
            return None
        current = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        if current is not None:
            return current
        return {
            "invitation_id": invitation_id,
            "email": str(payload.get("email") or "").strip().lower(),
            "role": str(payload.get("role") or "operator").strip().lower() or "operator",
            "display_name": str(payload.get("display_name") or "").strip(),
            "note": "",
            "status": "pending",
            "invited_by": "",
            "invited_at": "",
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "accepted_at": "",
            "accepted_by": "",
            "revoked_at": "",
            "invite_url": f"/workspace-invites/{token}",
            "invite_token": str(token or "").strip(),
            "operator_id": _operator_id_from_email(str(payload.get("email") or "").strip().lower()),
        }

    def accept_workspace_invitation(
        self,
        *,
        token: str,
        accepted_by: str,
        display_name: str = "",
        operator_id: str = "",
    ) -> dict[str, object] | None:
        raw_payload = _verify_channel_payload(secret=self._channel_action_secret(), token=token)
        if raw_payload is None or str(raw_payload.get("token_kind") or "").strip() != "workspace_invitation":
            return None
        preview = self.preview_workspace_invitation(token=token)
        if preview is None:
            return None
        if str(preview.get("status") or "").strip().lower() != "pending":
            return preview
        principal_id = str(raw_payload.get("principal_id") or "").strip()
        invitation_id = str(preview.get("invitation_id") or "").strip()
        role = str(preview.get("role") or "operator").strip().lower() or "operator"
        email = str(preview.get("email") or "").strip().lower()
        resolved_operator_id = str(operator_id or preview.get("operator_id") or "").strip()
        resolved_display_name = str(display_name or preview.get("display_name") or email or "Workspace Operator").strip()
        if role == "operator":
            if not resolved_operator_id:
                resolved_operator_id = _operator_id_from_email(email)
            existing = self._container.orchestrator.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if existing is None:
                status = self._container.onboarding.status(principal_id=principal_id)
                workspace = dict(status.get("workspace") or {})
                plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
                active = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=500)
                if len(active) >= plan.entitlements.operator_seats:
                    raise ValueError("operator_seat_limit_reached")
            self._container.orchestrator.upsert_operator_profile(
                principal_id=principal_id,
                operator_id=resolved_operator_id,
                display_name=resolved_display_name,
                roles=(role,),
                trust_tier="standard",
                status="active",
                notes=f"Accepted workspace invite for {email}.",
            )
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_invitation_accepted",
            payload={
                "invitation_id": invitation_id,
                "accepted_by": str(accepted_by or email or "workspace").strip() or "workspace",
                "accepted_at": _now_iso(),
                "operator_id": resolved_operator_id,
            },
            source_id=invitation_id,
            dedupe_key=f"{principal_id}|{invitation_id}|accepted",
        )
        return self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)

    def revoke_workspace_invitation(
        self,
        *,
        principal_id: str,
        invitation_id: str,
        actor: str,
    ) -> dict[str, object] | None:
        current = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        if current is None:
            return None
        if str(current.get("status") or "").strip().lower() == "revoked":
            return current
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_invitation_revoked",
            payload={
                "invitation_id": str(invitation_id or "").strip(),
                "revoked_at": _now_iso(),
                "revoked_by": str(actor or "").strip() or "workspace",
            },
            source_id=str(invitation_id or "").strip(),
            dedupe_key=f"{principal_id}|{invitation_id}|revoked",
        )
        return self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)

    def create_commitment(
        self,
        *,
        principal_id: str,
        title: str,
        details: str = "",
        due_at: str | None = None,
        priority: str = "medium",
        counterparty: str = "",
        owner: str = "office",
        kind: str = "commitment",
        stakeholder_id: str = "",
        channel_hint: str = "email",
    ) -> CommitmentItem:
        normalized_kind = str(kind or "commitment").strip().lower()
        if normalized_kind == "follow_up" and stakeholder_id.strip():
            row = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                stakeholder_ref=stakeholder_id.strip(),
                topic=title,
                status="open",
                due_at=due_at,
                channel_hint=channel_hint,
                notes=details,
                source_json={"source_type": "manual", "counterparty": counterparty, "owner": owner, "channel_hint": channel_hint, "confidence": 1.0},
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_created",
                payload={"kind": "follow_up", "title": title, "counterparty": counterparty, "due_at": due_at or ""},
                source_id=row.follow_up_id,
            )
            return self._commitment_item_from_follow_up(row, self._stakeholder_lookup(principal_id))
        row = self._container.memory_runtime.upsert_commitment(
            principal_id=principal_id,
            title=title,
            details=details,
            status="open",
            priority=priority,
            due_at=due_at,
            source_json={"source_type": "manual", "counterparty": counterparty, "owner": owner, "channel_hint": channel_hint, "confidence": 1.0},
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_created",
            payload={"kind": "commitment", "title": title, "counterparty": counterparty, "due_at": due_at or ""},
            source_id=row.commitment_id,
        )
        return self._commitment_item_from_commitment(row)

    def extract_commitments(
        self,
        *,
        text: str,
        counterparty: str = "",
        due_at: str | None = None,
    ) -> tuple[CommitmentCandidate, ...]:
        return extract_commitment_candidates(text, counterparty=counterparty, due_at=due_at)

    def _candidate_from_memory_row(self, row) -> CommitmentCandidate:  # type: ignore[no-untyped-def]
        fact = dict(getattr(row, "fact_json", {}) or {})
        duplicate_of_ref = str(fact.get("duplicate_of_ref") or "").strip()
        status = str(getattr(row, "status", "pending") or "pending")
        if duplicate_of_ref and status == "pending":
            status = "duplicate"
        return CommitmentCandidate(
            candidate_id=str(getattr(row, "candidate_id", "") or ""),
            title=str(fact.get("title") or getattr(row, "summary", "") or "Commitment candidate"),
            details=str(fact.get("details") or getattr(row, "summary", "") or ""),
            source_text=str(fact.get("source_text") or ""),
            confidence=float(getattr(row, "confidence", 0.5) or 0.5),
            suggested_due_at=str(fact.get("suggested_due_at") or "") or None,
            counterparty=str(fact.get("counterparty") or ""),
            status=status,
            kind=str(fact.get("kind") or "commitment"),
            stakeholder_id=str(fact.get("stakeholder_id") or ""),
            duplicate_of_ref=duplicate_of_ref,
            merge_strategy="merge" if duplicate_of_ref else "create",
        )

    def list_commitment_candidates(self, *, principal_id: str, limit: int = 20, status: str | None = None) -> tuple[CommitmentCandidate, ...]:
        rows = self._container.memory_runtime.list_candidates(limit=max(limit * 4, 50), status=None, principal_id=principal_id)
        filtered = [row for row in rows if str(getattr(row, "category", "") or "") == "product_commitment_candidate"]
        projected = tuple(self._candidate_from_memory_row(row) for row in filtered)
        if status is not None:
            wanted = str(status or "").strip().lower()
            projected = tuple(row for row in projected if str(row.status or "").strip().lower() == wanted)
        return tuple(projected[:limit])

    def get_commitment_candidate(self, *, principal_id: str, candidate_id: str) -> CommitmentCandidate | None:
        row = self._container.memory_runtime.get_candidate(candidate_id, principal_id=principal_id)
        if row is None or str(getattr(row, "category", "") or "") != "product_commitment_candidate":
            return None
        return self._candidate_from_memory_row(row)

    def stage_extracted_commitments(
        self,
        *,
        principal_id: str,
        text: str,
        counterparty: str = "",
        due_at: str | None = None,
        kind: str = "commitment",
        stakeholder_id: str = "",
    ) -> tuple[CommitmentCandidate, ...]:
        extracted = self.extract_commitments(text=text, counterparty=counterparty, due_at=due_at)
        staged: list[CommitmentCandidate] = []
        for candidate in extracted:
            duplicate_of_ref = self._find_duplicate_commitment_ref(
                principal_id=principal_id,
                title=candidate.title,
                counterparty=candidate.counterparty or counterparty,
            )
            row = self._container.memory_runtime.stage_candidate(
                principal_id=principal_id,
                category="product_commitment_candidate",
                summary=candidate.title,
                fact_json={
                    "title": candidate.title,
                    "details": candidate.details,
                    "source_text": candidate.source_text,
                    "suggested_due_at": candidate.suggested_due_at or "",
                    "counterparty": candidate.counterparty,
                    "kind": kind,
                    "stakeholder_id": stakeholder_id,
                    "duplicate_of_ref": duplicate_of_ref,
                },
                confidence=candidate.confidence,
                sensitivity="internal",
            )
            staged.append(self._candidate_from_memory_row(row))
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_candidate_duplicate_detected" if duplicate_of_ref else "commitment_candidate_staged",
                payload={"title": candidate.title, "kind": kind, "counterparty": candidate.counterparty, "duplicate_of_ref": duplicate_of_ref},
                source_id=row.candidate_id,
            )
        return tuple(staged)

    def accept_commitment_candidate(
        self,
        *,
        principal_id: str,
        candidate_id: str,
        reviewer: str,
        title: str = "",
        details: str = "",
        due_at: str | None = None,
        counterparty: str = "",
        kind: str = "",
        stakeholder_id: str = "",
    ) -> CommitmentItem | None:
        promoted = self._container.memory_runtime.promote_candidate(
            candidate_id,
            principal_id=principal_id,
            reviewer=reviewer,
            sharing_policy="private",
        )
        if promoted is None:
            return None
        candidate, _item = promoted
        fact = dict(candidate.fact_json or {})
        duplicate_of_ref = str(fact.get("duplicate_of_ref") or "").strip()
        if duplicate_of_ref:
            merged = self._merge_candidate_into_existing(
                principal_id=principal_id,
                duplicate_ref=duplicate_of_ref,
                candidate_id=candidate_id,
                title=title.strip() or str(fact.get("title") or candidate.summary or "Commitment"),
                details=details if details.strip() else str(fact.get("details") or ""),
                due_at=due_at if str(due_at or "").strip() else (str(fact.get("suggested_due_at") or "") or None),
                counterparty=counterparty.strip() or str(fact.get("counterparty") or ""),
                confidence=float(getattr(candidate, "confidence", 0.5) or 0.5),
            )
            if merged is not None:
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="commitment_candidate_accepted",
                    payload={
                        "candidate_id": candidate_id,
                        "reviewer": reviewer,
                        "title_override": title.strip(),
                        "due_at_override": str(due_at or "").strip(),
                        "counterparty_override": counterparty.strip(),
                        "kind_override": kind.strip(),
                        "merged_into_ref": duplicate_of_ref,
                    },
                    source_id=candidate_id,
                )
                return merged
        created = self.create_commitment(
            principal_id=principal_id,
            title=title.strip() or str(fact.get("title") or candidate.summary or "Commitment"),
            details=details if details.strip() else str(fact.get("details") or ""),
            due_at=due_at if str(due_at or "").strip() else (str(fact.get("suggested_due_at") or "") or None),
            counterparty=counterparty.strip() or str(fact.get("counterparty") or ""),
            owner="office",
            kind=kind.strip() or str(fact.get("kind") or "commitment"),
            stakeholder_id=stakeholder_id.strip() or str(fact.get("stakeholder_id") or ""),
            channel_hint="email",
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_candidate_accepted",
            payload={
                "candidate_id": candidate_id,
                "reviewer": reviewer,
                "title_override": title.strip(),
                "due_at_override": str(due_at or "").strip(),
                "counterparty_override": counterparty.strip(),
                "kind_override": kind.strip(),
            },
            source_id=candidate_id,
        )
        return created

    def resolve_commitment(
        self,
        *,
        principal_id: str,
        commitment_ref: str,
        action: str,
        actor: str,
        reason: str = "",
        reason_code: str = "",
        due_at: str | None = None,
    ) -> CommitmentItem | None:
        normalized = str(action or "").strip().lower()
        code = str(reason_code or "").strip().lower()
        if commitment_ref.startswith("commitment:"):
            current = self._container.memory_runtime.get_commitment(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            next_status = current.status
            event_type = "commitment_updated"
            if normalized in {"close", "done", "complete"}:
                next_status = "completed"
                event_type = "commitment_closed"
                code = code or "completed"
            elif normalized in {"drop", "dismiss", "cancel"}:
                next_status = "cancelled"
                event_type = "commitment_dropped"
                code = code or "no_longer_needed"
            elif normalized in {"defer", "snooze"}:
                next_status = "open"
                event_type = "commitment_deferred"
                code = code or "deferred"
            elif normalized in {"reopen"}:
                next_status = "open"
                event_type = "commitment_reopened"
            updated_source = {
                **source,
                "resolution_code": "" if normalized == "reopen" else code,
                "resolution_reason": "" if normalized == "reopen" else (reason or str(source.get("resolution_reason") or "")),
                "channel_hint": str(source.get("channel_hint") or "email"),
            }
            if normalized == "reopen":
                updated_source["reopened_at"] = _now_iso()
            updated = self._container.memory_runtime.upsert_commitment(
                principal_id=principal_id,
                commitment_id=current.commitment_id,
                title=current.title,
                details=current.details,
                status=next_status,
                priority=current.priority,
                due_at=due_at or current.due_at,
                source_json=updated_source,
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type=event_type,
                payload={"item_ref": commitment_ref, "action": normalized or "update", "actor": actor, "reason": reason or "", "reason_code": code},
                source_id=current.commitment_id,
            )
            return self._commitment_item_from_commitment(updated)
        if commitment_ref.startswith("follow_up:"):
            current = self._container.memory_runtime.get_follow_up(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            next_status = current.status
            event_type = "commitment_updated"
            if normalized in {"close", "done", "complete"}:
                next_status = "completed"
                event_type = "commitment_closed"
                code = code or "completed"
            elif normalized in {"drop", "dismiss", "cancel"}:
                next_status = "cancelled"
                event_type = "commitment_dropped"
                code = code or "no_longer_needed"
            elif normalized in {"defer", "snooze"}:
                next_status = "open"
                event_type = "commitment_deferred"
                code = code or "deferred"
            elif normalized in {"reopen"}:
                next_status = "open"
                event_type = "commitment_reopened"
            updated_source = {
                **source,
                "resolution_code": "" if normalized == "reopen" else code,
                "resolution_reason": "" if normalized == "reopen" else (reason or str(source.get("resolution_reason") or "")),
                "channel_hint": str(source.get("channel_hint") or current.channel_hint or "email"),
            }
            if normalized == "reopen":
                updated_source["reopened_at"] = _now_iso()
            updated = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                follow_up_id=current.follow_up_id,
                stakeholder_ref=current.stakeholder_ref,
                topic=current.topic,
                status=next_status,
                due_at=due_at or current.due_at,
                channel_hint=current.channel_hint,
                notes=current.notes if not reason else reason,
                source_json=updated_source,
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type=event_type,
                payload={"item_ref": commitment_ref, "action": normalized or "update", "actor": actor, "reason": reason or "", "reason_code": code},
                source_id=current.follow_up_id,
            )
            return self._commitment_item_from_follow_up(updated, self._stakeholder_lookup(principal_id))
        return None

    def reject_commitment_candidate(
        self,
        *,
        principal_id: str,
        candidate_id: str,
        reviewer: str,
    ) -> CommitmentCandidate | None:
        row = self._container.memory_runtime.reject_candidate(candidate_id, principal_id=principal_id, reviewer=reviewer)
        if row is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_candidate_rejected",
            payload={"candidate_id": candidate_id, "reviewer": reviewer},
            source_id=candidate_id,
        )
        return self._candidate_from_memory_row(row)

    def _queue_item_from_approval(self, row: ApprovalRequest) -> DecisionQueueItem:
        action_json = dict(row.requested_action_json or {})
        action_label = _action_label(action_json)
        summary = compact_text(
            action_json.get("content") or action_json.get("draft_text") or row.reason,
            fallback="Approval is waiting for a decision.",
        )
        return DecisionQueueItem(
            id=f"approval:{row.approval_id}",
            queue_kind="approve_draft",
            title=row.reason or f"Approve {action_label}",
            summary=summary,
            priority="high",
            deadline=row.expires_at,
            owner_role="principal",
            requires_principal=True,
            evidence_refs=(
                EvidenceRef(ref_id=f"approval:{row.approval_id}", label="Approval", source_type="approval", note=action_label),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id),
            ),
            resolution_state=row.status,
        )

    def _draft_from_approval(self, row: ApprovalRequest) -> DraftCandidate:
        action_json = dict(row.requested_action_json or {})
        return DraftCandidate(
            id=f"approval:{row.approval_id}",
            thread_ref=str(action_json.get("thread_ref") or row.session_id),
            recipient_summary=str(action_json.get("recipient") or action_json.get("to") or "Review required"),
            intent=_action_label(action_json),
            draft_text=compact_text(
                action_json.get("content") or action_json.get("draft_text") or row.reason,
                fallback="Approval-backed draft ready for review.",
                limit=500,
            ),
            tone=str(action_json.get("tone") or "review"),
            requires_approval=True,
            approval_status=row.status,
            provenance_refs=(
                EvidenceRef(ref_id=f"approval:{row.approval_id}", label="Approval request", source_type="approval", note=row.reason),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id),
            ),
            send_channel=str(action_json.get("channel") or "email"),
        )

    def list_drafts(self, *, principal_id: str, limit: int = 20) -> tuple[DraftCandidate, ...]:
        rows = self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit)
        return tuple(self._draft_from_approval(row) for row in rows[:limit])

    def approve_draft(self, *, principal_id: str, draft_ref: str, decided_by: str, reason: str) -> DraftCandidate | None:
        if not draft_ref.startswith("approval:"):
            return None
        approval_id = draft_ref.split(":", 1)[1]
        allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
        if approval_id not in allowed:
            return None
        decided = self._container.orchestrator.decide_approval(
            approval_id,
            decision="approved",
            decided_by=decided_by,
            reason=reason or "Approved from product draft queue.",
        )
        if decided is None:
            return None
        request, _ = decided
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_approved",
            payload={"draft_ref": draft_ref, "decided_by": decided_by, "reason": reason or ""},
            source_id=request.approval_id,
        )
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Approved draft",
            intent="approved",
            draft_text=compact_text(request.reason, fallback="Approved from product draft queue."),
            tone="approved",
            requires_approval=True,
            approval_status="approved",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(dict(request.requested_action_json or {}).get("channel") or "email"),
        )

    def reject_draft(self, *, principal_id: str, draft_ref: str, decided_by: str, reason: str) -> DraftCandidate | None:
        if not draft_ref.startswith("approval:"):
            return None
        approval_id = draft_ref.split(":", 1)[1]
        allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
        if approval_id not in allowed:
            return None
        decided = self._container.orchestrator.decide_approval(
            approval_id,
            decision="rejected",
            decided_by=decided_by,
            reason=reason or "Rejected from product draft queue.",
        )
        if decided is None:
            return None
        request, _ = decided
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_rejected",
            payload={"draft_ref": draft_ref, "decided_by": decided_by, "reason": reason or ""},
            source_id=request.approval_id,
        )
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Rejected draft",
            intent="rejected",
            draft_text=compact_text(request.reason, fallback="Rejected from product draft queue."),
            tone="rejected",
            requires_approval=True,
            approval_status="rejected",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(dict(request.requested_action_json or {}).get("channel") or "email"),
        )

    def _queue_item_from_human_task(self, row: HumanTask) -> DecisionQueueItem:
        summary = " · ".join(
            part
            for part in (
                compact_text(row.why_human, fallback="Human judgment is still required."),
                f"Role {row.role_required}" if row.role_required else "",
                f"Due {row.sla_due_at[:10]}" if row.sla_due_at else "",
            )
            if part
        )
        return DecisionQueueItem(
            id=f"human_task:{row.human_task_id}",
            queue_kind="assign_owner",
            title=row.brief,
            summary=summary,
            priority=row.priority,
            deadline=row.sla_due_at,
            owner_role=row.role_required,
            requires_principal=False,
            evidence_refs=(
                EvidenceRef(ref_id=f"human_task:{row.human_task_id}", label="Human task", source_type="human_task", note=row.task_type),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id or ""),
            ),
            resolution_state=row.status,
        )

    def _queue_item_from_commitment(self, row: CommitmentItem) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=row.id,
            queue_kind="close_commitment",
            title=row.statement,
            summary=compact_text(
                row.proof_refs[0].note if row.proof_refs else "",
                fallback="Commitment is still open and needs a visible next action.",
            ),
            priority=row.risk_level,
            deadline=row.due_at,
            owner_role=row.owner,
            requires_principal=False,
            evidence_refs=row.proof_refs,
            resolution_state=row.status,
        )

    def _queue_item_from_decision(self, row: DecisionWindow) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=f"decision:{row.decision_window_id}",
            queue_kind="choose_option",
            title=row.title,
            summary=compact_text(row.context or row.notes, fallback="Decision window is open."),
            priority=row.urgency,
            deadline=row.closes_at or row.opens_at,
            owner_role=row.authority_required,
            requires_principal=str(row.authority_required or "").strip().lower() in {"principal", "exec", "executive"},
            evidence_refs=(EvidenceRef(ref_id=f"decision:{row.decision_window_id}", label="Decision", source_type="decision", note=row.status),),
            resolution_state=row.status,
        )

    def _queue_item_from_deadline(self, row: DeadlineWindow) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=f"deadline:{row.window_id}",
            queue_kind="defer",
            title=row.title,
            summary=compact_text(row.notes, fallback="Deadline window is active."),
            priority=row.priority,
            deadline=row.end_at or row.start_at,
            owner_role="office",
            requires_principal=False,
            evidence_refs=(EvidenceRef(ref_id=f"deadline:{row.window_id}", label="Deadline", source_type="deadline", note=row.status),),
            resolution_state=row.status,
        )

    def list_queue(self, *, principal_id: str, limit: int = 30, operator_id: str = "") -> tuple[DecisionQueueItem, ...]:
        operator_key = str(operator_id or "").strip()
        items: list[DecisionQueueItem] = []
        items.extend(self._queue_item_from_approval(row) for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit))
        for row in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=limit):
            assigned = str(row.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            items.append(self._queue_item_from_human_task(row))
        items.extend(self._queue_item_from_commitment(row) for row in self.list_commitments(principal_id=principal_id, limit=limit))
        for row in self._container.memory_runtime.list_decision_windows(principal_id=principal_id, limit=limit, status=None):
            if status_open(row.status):
                items.append(self._queue_item_from_decision(row))
        for row in self._container.memory_runtime.list_deadline_windows(principal_id=principal_id, limit=limit, status=None):
            if status_open(row.status):
                items.append(self._queue_item_from_deadline(row))
        items = [item for item in items if status_open(item.resolution_state)]
        items.sort(key=lambda item: (priority_weight(item.priority), due_bonus(item.deadline), item.title.lower()), reverse=True)
        return tuple(items[:limit])

    def resolve_queue_item(
        self,
        *,
        principal_id: str,
        item_ref: str,
        action: str,
        actor: str,
        reason: str = "",
        reason_code: str = "",
        due_at: str | None = None,
    ) -> DecisionQueueItem | None:
        normalized = str(action or "").strip().lower()
        if item_ref.startswith("approval:"):
            decision = "approved" if normalized in {"approve", "approved", "close"} else "rejected"
            allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
            approval_id = item_ref.split(":", 1)[1]
            if approval_id not in allowed:
                return None
            decided = self._container.orchestrator.decide_approval(
                approval_id,
                decision=decision,
                decided_by=actor,
                reason=reason or f"{decision.capitalize()} from decision queue.",
            )
            if decided is None:
                return None
            request, decision_row = decided
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": decision, "actor": actor, "reason": reason or ""},
                source_id=request.approval_id,
            )
            updated = self._queue_item_from_approval(request)
            return DecisionQueueItem(
                id=updated.id,
                queue_kind=updated.queue_kind,
                title=updated.title,
                summary=updated.summary,
                priority=updated.priority,
                deadline=updated.deadline,
                owner_role=updated.owner_role,
                requires_principal=updated.requires_principal,
                evidence_refs=updated.evidence_refs,
                resolution_state=decision_row.decision,
            )
        if item_ref.startswith("commitment:"):
            updated = self.resolve_commitment(
                principal_id=principal_id,
                commitment_ref=item_ref,
                action=normalized,
                actor=actor,
                reason=reason,
                reason_code=reason_code,
                due_at=due_at,
            )
            return None if updated is None else self._queue_item_from_commitment(updated)
        if item_ref.startswith("follow_up:"):
            updated = self.resolve_commitment(
                principal_id=principal_id,
                commitment_ref=item_ref,
                action=normalized,
                actor=actor,
                reason=reason,
                reason_code=reason_code,
                due_at=due_at,
            )
            return None if updated is None else self._queue_item_from_commitment(updated)
        if item_ref.startswith("human_task:"):
            current = self._container.orchestrator.fetch_human_task(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            operator_id = str(current.assigned_operator_id or actor or "").strip()
            if normalized in {"assign", "claim"}:
                updated = self._container.orchestrator.assign_human_task(
                    current.human_task_id,
                    principal_id=principal_id,
                    operator_id=operator_id,
                    assignment_source="manual",
                    assigned_by_actor_id=actor,
                )
            else:
                updated = self._container.orchestrator.return_human_task(
                    current.human_task_id,
                    principal_id=principal_id,
                    operator_id=operator_id,
                    resolution=reason or "completed",
                    returned_payload_json={"action": normalized or "complete"},
                    provenance_json={"source": "product_queue"},
                )
            if updated is None:
                return None
            self._record_product_event(
                principal_id=principal_id,
                event_type="handoff_completed" if normalized not in {"assign", "claim"} else "handoff_assigned",
                payload={"item_ref": item_ref, "action": normalized or "complete", "actor": actor, "operator_id": operator_id},
                source_id=current.human_task_id,
            )
            return self._queue_item_from_human_task(updated)
        if item_ref.startswith("decision:"):
            current = self._container.memory_runtime.get_decision_window(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            next_status = "decided" if normalized in {"resolve", "close", "done", "complete"} else "open"
            if normalized in {"defer", "snooze", "reopen", "escalate"}:
                next_status = "open"
            next_authority = current.authority_required
            if normalized == "escalate":
                next_authority = "principal"
            updated = self._container.memory_runtime.upsert_decision_window(
                principal_id=principal_id,
                decision_window_id=current.decision_window_id,
                title=current.title,
                context=current.context,
                opens_at=current.opens_at,
                closes_at=due_at or current.closes_at,
                urgency=current.urgency,
                authority_required=next_authority,
                status=next_status,
                notes=reason or current.notes,
                source_json={
                    **source,
                    "resolution_reason": reason if normalized in {"resolve", "close", "done", "complete"} else "",
                    "resolved_by": actor if normalized in {"resolve", "close", "done", "complete"} else "",
                    "resolved_at": _now_iso() if normalized in {"resolve", "close", "done", "complete"} else "",
                    "reopened_by": actor if normalized == "reopen" else str(source.get("reopened_by") or ""),
                    "reopened_at": _now_iso() if normalized == "reopen" else str(source.get("reopened_at") or ""),
                    "escalation_reason": reason if normalized == "escalate" else "",
                    "escalated_by": actor if normalized == "escalate" else str(source.get("escalated_by") or ""),
                    "escalated_at": _now_iso() if normalized == "escalate" else str(source.get("escalated_at") or ""),
                },
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="decision_resolved" if normalized in {"resolve", "close", "done", "complete"} else ("decision_escalated" if normalized == "escalate" else ("decision_reopened" if normalized == "reopen" else "queue_resolved")),
                payload={"item_ref": item_ref, "action": normalized or "resolve", "actor": actor, "reason": reason or ""},
                source_id=current.decision_window_id,
            )
            return self._queue_item_from_decision(updated)
        if item_ref.startswith("deadline:"):
            current = self._container.memory_runtime.get_deadline_window(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            next_status = "elapsed" if normalized in {"resolve", "close", "done", "complete"} else "open"
            updated = self._container.memory_runtime.upsert_deadline_window(
                principal_id=principal_id,
                window_id=current.window_id,
                title=current.title,
                start_at=current.start_at,
                end_at=due_at or current.end_at,
                status=next_status,
                priority=current.priority,
                notes=reason or current.notes,
                source_json=dict(current.source_json or {}),
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": normalized or "resolve", "actor": actor, "reason": reason or ""},
                source_id=current.window_id,
            )
            return self._queue_item_from_deadline(updated)
        return None

    def _decision_item_from_window(self, row: DecisionWindow) -> DecisionItem:
        return decision_item_from_window(row)

    def list_decisions(
        self,
        *,
        principal_id: str,
        limit: int = 20,
        include_closed: bool = False,
    ) -> tuple[DecisionItem, ...]:
        rows = [
            self._decision_item_from_window(row)
            for row in self._container.memory_runtime.list_decision_windows(principal_id=principal_id, limit=limit, status=None)
            if include_closed or status_open(row.status)
        ]
        rows.sort(key=lambda row: (priority_weight(row.priority), due_bonus(row.due_at), row.title.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_decision(self, *, principal_id: str, decision_ref: str) -> DecisionItem | None:
        normalized = decision_ref.split(":", 1)[1] if decision_ref.startswith("decision:") else decision_ref
        found = self._container.memory_runtime.get_decision_window(normalized, principal_id=principal_id)
        if found is None:
            return None
        return self._decision_item_from_window(found)

    def get_decision_history(self, *, principal_id: str, decision_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        source_id = decision_ref.split(":", 1)[1] if ":" in decision_ref else decision_ref
        return self._history_entries(principal_id=principal_id, source_ids=(source_id,), limit=limit)

    def resolve_decision(
        self,
        *,
        principal_id: str,
        decision_ref: str,
        actor: str,
        action: str,
        reason: str = "",
        due_at: str | None = None,
    ) -> DecisionItem | None:
        item_ref = decision_ref if decision_ref.startswith("decision:") else f"decision:{decision_ref}"
        updated = self.resolve_queue_item(
            principal_id=principal_id,
            item_ref=item_ref,
            action=action,
            actor=actor,
            reason=reason,
            due_at=due_at,
        )
        if updated is None:
            return None
        return self.get_decision(principal_id=principal_id, decision_ref=item_ref)

    def list_threads(self, *, principal_id: str, limit: int = 20) -> tuple[ThreadItem, ...]:
        drafts = self.list_drafts(principal_id=principal_id, limit=max(limit, 20))
        commitments = self.list_commitments(principal_id=principal_id, limit=max(limit, 20))
        decisions = self.list_decisions(principal_id=principal_id, limit=max(limit, 20), include_closed=True)
        return thread_items_from_objects(drafts, commitments, decisions, limit=limit)

    def get_thread(self, *, principal_id: str, thread_ref: str) -> ThreadItem | None:
        normalized = thread_ref if thread_ref.startswith("thread:") else f"thread:{thread_ref}"
        for row in self.list_threads(principal_id=principal_id, limit=200):
            if row.id == normalized:
                return row
        return None

    def list_evidence(
        self,
        *,
        principal_id: str,
        limit: int = 40,
        operator_id: str = "",
    ) -> tuple[EvidenceItem, ...]:
        brief_items = self.list_brief_items(principal_id=principal_id, limit=max(limit, 12), operator_id=operator_id)
        queue_items = self.list_queue(principal_id=principal_id, limit=max(limit, 12), operator_id=operator_id)
        commitments = self.list_commitments(principal_id=principal_id, limit=max(limit, 12))
        drafts = self.list_drafts(principal_id=principal_id, limit=max(limit, 12))
        decisions = self.list_decisions(principal_id=principal_id, limit=max(limit, 12), include_closed=True)
        handoffs = self.list_handoffs(principal_id=principal_id, limit=max(limit, 12), operator_id=operator_id, status=None)
        threads = thread_items_from_objects(drafts, commitments, decisions, limit=max(limit, 12))
        return evidence_items_from_objects(
            brief_items=brief_items,
            queue_items=queue_items,
            commitments=commitments,
            drafts=drafts,
            decisions=decisions,
            handoffs=handoffs,
            threads=threads,
            limit=limit,
        )

    def get_evidence(self, *, principal_id: str, evidence_ref: str, operator_id: str = "") -> EvidenceItem | None:
        for row in self.list_evidence(principal_id=principal_id, limit=200, operator_id=operator_id):
            if row.id == evidence_ref:
                return row
        return None

    def _rules_diagnostics(self, *, principal_id: str) -> tuple[dict[str, object], dict[str, object]]:
        status = self._container.onboarding.status(principal_id=principal_id)
        workspace = dict(status.get("workspace") or {})
        selected_channels = tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip())
        plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
        operators = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
        seats_used = len(operators)
        seat_limit = int(plan.entitlements.operator_seats or 0)
        seat_overage = max(seats_used - seat_limit, 0)
        commercial_snapshot = workspace_commercial_snapshot(plan, seats_used=seats_used, selected_channels=selected_channels)
        return status, {
            "billing": dict(commercial_snapshot.get("billing") or {}),
            "entitlements": {
                "principal_seats": plan.entitlements.principal_seats,
                "operator_seats": plan.entitlements.operator_seats,
                "messaging_channels_enabled": plan.entitlements.messaging_channels_enabled,
                "audit_retention": plan.entitlements.audit_retention,
                "feature_flags": list(plan.entitlements.feature_flags),
            },
            "operators": {
                "active_count": seats_used,
                "seats_used": seats_used,
                "seats_remaining": max(seat_limit - seats_used, 0),
                "seat_overage": seat_overage,
            },
            "commercial": dict(commercial_snapshot.get("commercial") or {}),
        }

    def list_rules(self, *, principal_id: str) -> tuple[RuleItem, ...]:
        status, diagnostics = self._rules_diagnostics(principal_id=principal_id)
        return rule_items_from_workspace(status, diagnostics)

    def get_rule(self, *, principal_id: str, rule_id: str) -> RuleItem | None:
        for row in self.list_rules(principal_id=principal_id):
            if row.id == rule_id:
                return row
        return None

    def simulate_rule(self, *, principal_id: str, rule_id: str, proposed_value: str) -> RuleItem | None:
        current = self.get_rule(principal_id=principal_id, rule_id=rule_id)
        if current is None:
            return None
        _, diagnostics = self._rules_diagnostics(principal_id=principal_id)
        return simulate_rule(current, proposed_value=proposed_value, diagnostics=diagnostics)

    def _brief_item_from_queue(self, row: DecisionQueueItem, *, workspace_id: str) -> BriefItem:
        confidence = 0.7
        if row.id.startswith("approval:"):
            confidence = 0.95
        elif row.id.startswith("decision:"):
            confidence = 0.88
        elif row.id.startswith(("commitment:", "follow_up:")):
            confidence = 0.84
        return BriefItem(
            id=row.id,
            workspace_id=workspace_id,
            kind=row.queue_kind,
            title=row.title,
            summary=row.summary,
            score=float(priority_weight(row.priority) + due_bonus(row.deadline)),
            why_now=row.summary,
            evidence_refs=row.evidence_refs,
            related_people=(),
            related_commitment_ids=(row.id,) if row.queue_kind == "close_commitment" else (),
            recommended_action=row.queue_kind.replace("_", " "),
            status=row.resolution_state,
            confidence=confidence,
            object_ref=row.id,
            evidence_count=len(row.evidence_refs),
        )

    def _brief_item_from_decision(self, row: DecisionItem, *, workspace_id: str) -> BriefItem:
        why_now_parts = [
            str(row.sla_status or "").replace("_", " ").title(),
            row.impact_summary or row.summary,
        ]
        return BriefItem(
            id=f"brief:{row.id}",
            workspace_id=workspace_id,
            kind="decision",
            title=row.title,
            summary=row.summary,
            score=float(priority_weight(row.priority) + due_bonus(row.due_at) + 1),
            why_now=" · ".join(part for part in why_now_parts if part),
            evidence_refs=row.evidence_refs,
            related_people=row.related_people,
            related_commitment_ids=row.related_commitment_ids,
            recommended_action="resolve decision",
            status=row.status,
            confidence=0.9 if row.evidence_refs else 0.75,
            object_ref=row.id,
            evidence_count=len(row.evidence_refs),
        )

    def _brief_item_from_commitment(self, row: CommitmentItem, *, workspace_id: str) -> BriefItem:
        why_now_parts = [
            row.risk_level.replace("_", " ").title(),
            f"Due {row.due_at[:10]}" if row.due_at else "",
            row.counterparty,
        ]
        return BriefItem(
            id=f"brief:{row.id}",
            workspace_id=workspace_id,
            kind="commitment",
            title=row.statement,
            summary=row.proof_refs[0].note if row.proof_refs else row.statement,
            score=float(priority_weight(row.risk_level) + due_bonus(row.due_at)),
            why_now=" · ".join(part for part in why_now_parts if part),
            evidence_refs=row.proof_refs,
            related_people=(row.counterparty,) if row.counterparty else (),
            related_commitment_ids=(row.id,),
            recommended_action="close commitment",
            status=row.status,
            confidence=row.confidence,
            object_ref=row.id,
            evidence_count=len(row.proof_refs),
        )

    def _brief_item_from_handoff(self, row: HandoffNote, *, workspace_id: str) -> BriefItem:
        why_now_parts = [
            row.escalation_status.replace("_", " ").title(),
            f"Due {row.due_time[:10]}" if row.due_time else "",
            row.owner,
        ]
        return BriefItem(
            id=f"brief:{row.id}",
            workspace_id=workspace_id,
            kind="handoff",
            title=row.summary,
            summary=row.evidence_refs[0].note if row.evidence_refs else row.summary,
            score=float(priority_weight(row.escalation_status) + due_bonus(row.due_time)),
            why_now=" · ".join(part for part in why_now_parts if part),
            evidence_refs=row.evidence_refs,
            related_people=(row.owner,) if row.owner else (),
            related_commitment_ids=(),
            recommended_action="claim handoff" if row.status == "pending" else "review handoff",
            status=row.status,
            confidence=0.8 if row.evidence_refs else 0.65,
            object_ref=row.id,
            evidence_count=len(row.evidence_refs),
        )

    def list_brief_items(self, *, principal_id: str, limit: int = 20, operator_id: str = "") -> tuple[BriefItem, ...]:
        queue = self.list_queue(principal_id=principal_id, limit=max(limit, 8), operator_id=operator_id)
        decisions = self.list_decisions(principal_id=principal_id, limit=max(limit, 6))
        commitments = self.list_commitments(principal_id=principal_id, limit=max(limit, 6))
        handoffs = self.list_handoffs(principal_id=principal_id, limit=max(limit, 4), operator_id=operator_id, status=None)
        items: list[BriefItem] = []
        items.extend(self._brief_item_from_decision(row, workspace_id=principal_id) for row in decisions)
        items.extend(self._brief_item_from_commitment(row, workspace_id=principal_id) for row in commitments)
        items.extend(self._brief_item_from_handoff(row, workspace_id=principal_id) for row in handoffs)
        for row in queue:
            if row.id.startswith(("decision:", "commitment:", "follow_up:", "human_task:")):
                continue
            items.append(self._brief_item_from_queue(row, workspace_id=principal_id))
        deduped: dict[str, BriefItem] = {}
        for row in items:
            key = row.object_ref or row.id
            current = deduped.get(key)
            if current is None or (row.score, row.evidence_count, row.confidence) > (current.score, current.evidence_count, current.confidence):
                deduped[key] = row
        ordered = sorted(
            deduped.values(),
            key=lambda row: (row.score, row.evidence_count, row.confidence, row.title.lower()),
            reverse=True,
        )
        return tuple(ordered[:limit])

    def _person_profile(self, row: Stakeholder, *, open_loops_count: int) -> PersonProfile:
        themes = tuple(str(key).replace("_", " ") for key in dict(row.open_loops_json or {}).keys())
        risks = tuple(str(key).replace("_", " ") for key in dict(row.friction_points_json or {}).keys())
        importance_key = str(row.importance or "medium").strip().lower() or "medium"
        return PersonProfile(
            id=row.stakeholder_id,
            display_name=row.display_name,
            role_or_company=row.channel_ref or row.authority_level,
            importance_score=priority_weight(importance_key),
            relationship_temperature=_TEMPERATURE_BY_IMPORTANCE.get(importance_key, "steady"),
            open_loops_count=open_loops_count,
            latest_touchpoint_at=row.last_interaction_at,
            preferred_tone=row.tone_pref,
            themes=themes,
            risks=risks or (("open loops",) if open_loops_count else ()),
        )

    def list_people(self, *, principal_id: str, limit: int = 25) -> tuple[PersonProfile, ...]:
        stakeholders = list(self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=limit))
        follow_ups = list(self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=200, status=None))
        commitments = list(self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=200, status=None))
        rows: list[PersonProfile] = []
        for row in stakeholders:
            open_loops = len(dict(row.open_loops_json or {}))
            open_loops += sum(1 for follow_up in follow_ups if status_open(follow_up.status) and str(follow_up.stakeholder_ref or "") == row.stakeholder_id)
            open_loops += sum(1 for commitment in commitments if status_open(commitment.status) and row.display_name.lower() in str(commitment.details or "").lower())
            rows.append(self._person_profile(row, open_loops_count=open_loops))
        rows.sort(key=lambda row: (row.importance_score, row.open_loops_count, row.display_name.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_person(self, *, principal_id: str, person_id: str) -> PersonProfile | None:
        found = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if found is None:
            return None
        people = {row.id: row for row in self.list_people(principal_id=principal_id, limit=200)}
        return people.get(found.stakeholder_id, self._person_profile(found, open_loops_count=len(dict(found.open_loops_json or {}))))

    def get_person_detail(self, *, principal_id: str, person_id: str, operator_id: str = "") -> PersonDetail | None:
        profile = self.get_person(principal_id=principal_id, person_id=person_id)
        if profile is None:
            return None
        person_tokens = tuple(
            token
            for token in {
                profile.display_name,
                profile.role_or_company,
                profile.display_name.split(" ", 1)[0] if profile.display_name else "",
            }
            if str(token or "").strip()
        )

        def _matches(*values: str | None) -> bool:
            return any(contains_token(value, token) for token in person_tokens for value in values)

        commitments = tuple(
            row
            for row in self.list_commitments(principal_id=principal_id, limit=100)
            if _matches(row.statement, row.counterparty, row.owner, row.proof_refs[0].note if row.proof_refs else "")
        )
        drafts = tuple(
            row
            for row in self.list_drafts(principal_id=principal_id, limit=100)
            if _matches(row.recipient_summary, row.draft_text, row.intent)
        )
        queue_items = tuple(
            row
            for row in self.list_queue(principal_id=principal_id, limit=100, operator_id=operator_id)
            if _matches(
                row.title,
                row.summary,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        handoffs = tuple(
            row
            for row in self.list_handoffs(principal_id=principal_id, limit=100, operator_id=operator_id)
            if _matches(
                row.summary,
                row.owner,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        evidence: list[EvidenceRef] = []
        seen: set[str] = set()
        for refs in [*(row.proof_refs for row in commitments), *(row.provenance_refs for row in drafts), *(row.evidence_refs for row in queue_items), *(row.evidence_refs for row in handoffs)]:
            for ref in refs:
                if ref.ref_id in seen:
                    continue
                seen.add(ref.ref_id)
                evidence.append(ref)
        return PersonDetail(
            profile=profile,
            commitments=commitments,
            drafts=drafts,
            queue_items=queue_items,
            handoffs=handoffs,
            evidence_refs=tuple(evidence[:12]),
            history=self._history_entries(principal_id=principal_id, source_ids=(person_id,), limit=12),
        )

    def get_person_history(self, *, principal_id: str, person_id: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        return self._history_entries(principal_id=principal_id, source_ids=(person_id,), limit=limit)

    def correct_person_profile(
        self,
        *,
        principal_id: str,
        person_id: str,
        preferred_tone: str = "",
        add_theme: str = "",
        remove_theme: str = "",
        add_risk: str = "",
        remove_risk: str = "",
    ) -> PersonDetail | None:
        current = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if current is None:
            return None
        open_loops = dict(current.open_loops_json or {})
        risks = dict(current.friction_points_json or {})
        if add_theme.strip():
            open_loops[add_theme.strip().replace(" ", "_")] = True
        if remove_theme.strip():
            open_loops.pop(remove_theme.strip().replace(" ", "_"), None)
        if add_risk.strip():
            risks[add_risk.strip().replace(" ", "_")] = "user_corrected"
        if remove_risk.strip():
            risks.pop(remove_risk.strip().replace(" ", "_"), None)
        self._container.memory_runtime.upsert_stakeholder(
            principal_id=principal_id,
            stakeholder_id=current.stakeholder_id,
            display_name=current.display_name,
            channel_ref=current.channel_ref,
            authority_level=current.authority_level,
            importance=current.importance,
            response_cadence=current.response_cadence,
            tone_pref=preferred_tone.strip() or current.tone_pref,
            sensitivity=current.sensitivity,
            escalation_policy=current.escalation_policy,
            open_loops_json=open_loops,
            friction_points_json=risks,
            last_interaction_at=current.last_interaction_at,
            status=current.status,
            notes=current.notes,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="memory_corrected",
            payload={
                "person_id": person_id,
                "preferred_tone": preferred_tone.strip(),
                "add_theme": add_theme.strip(),
                "remove_theme": remove_theme.strip(),
                "add_risk": add_risk.strip(),
                "remove_risk": remove_risk.strip(),
            },
            source_id=current.stakeholder_id,
        )
        return self.get_person_detail(principal_id=principal_id, person_id=person_id)

    def list_handoffs(
        self,
        *,
        principal_id: str,
        limit: int = 20,
        operator_id: str = "",
        status: str | None = "pending",
    ) -> tuple[HandoffNote, ...]:
        operator_key = str(operator_id or "").strip()
        rows: list[HandoffNote] = []
        for task in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status=status, limit=limit):
            assigned = str(task.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            rows.append(self._handoff_from_human_task(task))
        rows.sort(key=lambda row: (priority_weight(row.escalation_status), due_bonus(row.due_time), row.summary.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_handoff(self, *, principal_id: str, handoff_ref: str) -> HandoffNote | None:
        if not str(handoff_ref or "").startswith("human_task:"):
            return None
        found = self._container.orchestrator.fetch_human_task(handoff_ref.split(":", 1)[1], principal_id=principal_id)
        if found is None:
            return None
        return self._handoff_from_human_task(found)

    def assign_handoff(self, *, principal_id: str, handoff_ref: str, operator_id: str, actor: str) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        updated = self._container.orchestrator.assign_human_task(
            handoff_ref.split(":", 1)[1],
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source="manual",
            assigned_by_actor_id=actor,
        )
        if updated is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_assigned",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def complete_handoff(
        self,
        *,
        principal_id: str,
        handoff_ref: str,
        operator_id: str,
        actor: str,
        resolution: str,
    ) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        updated = self._container.orchestrator.return_human_task(
            handoff_ref.split(":", 1)[1],
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=resolution or "completed",
            returned_payload_json={"source": "product_handoffs", "actor": actor},
            provenance_json={"source": "product_handoffs"},
        )
        if updated is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_completed",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor, "resolution": resolution},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def _queue_health(
        self,
        *,
        principal_id: str,
        operator_id: str = "",
    ) -> tuple[dict[str, object], tuple[HandoffNote, ...]]:
        operator_key = str(operator_id or "").strip()
        pending_tasks = list(self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=200))
        visible_tasks: list[HumanTask] = []
        for task in pending_tasks:
            assigned = str(task.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            visible_tasks.append(task)
        unclaimed_tasks = [task for task in visible_tasks if not str(task.assigned_operator_id or "").strip()]
        assigned_tasks = [task for task in visible_tasks if str(task.assigned_operator_id or "").strip()]
        sla_breaches = [task for task in visible_tasks if _is_past_due(task.sla_due_at)]
        approvals = list(self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=200))
        pending_delivery = list(self._container.channel_runtime.list_pending_delivery(limit=200, principal_id=principal_id))
        retrying_delivery = [row for row in pending_delivery if str(getattr(row, "status", "") or "").strip() == "retry"]
        delivery_errors = [row for row in pending_delivery if str(getattr(row, "last_error", "") or "").strip()]
        oldest_pending_delivery_hours = max((_hours_since(str(getattr(row, "created_at", "") or "")) for row in pending_delivery), default=0)
        highest_delivery_attempt_count = max((int(getattr(row, "attempt_count", 0) or 0) for row in pending_delivery), default=0)
        queue_items = self.list_queue(principal_id=principal_id, limit=100, operator_id=operator_id)
        waiting_on_principal = sum(1 for row in queue_items if row.requires_principal)
        at_risk_commitments = sum(1 for row in self.list_commitments(principal_id=principal_id, limit=100) if row.risk_level == "high")
        oldest_handoff_hours = max(
            (
                _hours_since(
                    str(
                        getattr(task, "created_at", None)
                        or getattr(task, "updated_at", None)
                        or getattr(task, "last_transition_at", None)
                        or ""
                    )
                )
                for task in visible_tasks
            ),
            default=0,
        )
        suggested_tasks = sorted(
            unclaimed_tasks,
            key=lambda row: (priority_weight(row.priority), due_bonus(row.sla_due_at), str(row.brief or "").lower()),
            reverse=True,
        )
        suggestion_rows = tuple(self._handoff_from_human_task(row) for row in suggested_tasks[:3])
        load_score = (
            (len(sla_breaches) * 5)
            + (len(unclaimed_tasks) * 2)
            + (len(approvals) * 2)
            + waiting_on_principal
            + at_risk_commitments
            + (len(retrying_delivery) * 3)
            + len(delivery_errors)
        )
        if sla_breaches or len(approvals) >= 3 or waiting_on_principal >= 4 or retrying_delivery:
            state = "critical"
            detail = "SLA breaches, approval backlog, or principal-gated work need active clearing."
        elif unclaimed_tasks or at_risk_commitments >= 2 or pending_delivery or delivery_errors:
            state = "watch"
            detail = "The queue is stable, but there is visible backlog that should be cleared before the next memo cycle."
        else:
            state = "healthy"
            detail = "The operator lane is clear enough to trust the current office loop."
        return (
            {
                "state": state,
                "detail": detail,
                "pending_handoffs": len(visible_tasks),
                "assigned_handoffs": len(assigned_tasks),
                "unclaimed_handoffs": len(unclaimed_tasks),
                "sla_breaches": len(sla_breaches),
                "pending_approvals": len(approvals),
                "waiting_on_principal": waiting_on_principal,
                "at_risk_commitments": at_risk_commitments,
                "pending_delivery": len(pending_delivery),
                "retrying_delivery": len(retrying_delivery),
                "delivery_errors": len(delivery_errors),
                "highest_delivery_attempt_count": highest_delivery_attempt_count,
                "oldest_handoff_age_hours": oldest_handoff_hours,
                "oldest_pending_delivery_age_hours": oldest_pending_delivery_hours,
                "load_score": load_score,
                "suggested_claims": len(suggestion_rows),
            },
            suggestion_rows,
        )

    def workspace_snapshot(self, *, principal_id: str, operator_id: str = "") -> ProductSnapshot:
        brief_items = self.list_brief_items(principal_id=principal_id, limit=8, operator_id=operator_id)
        queue_items = self.list_queue(principal_id=principal_id, limit=10, operator_id=operator_id)
        commitments = self.list_commitments(principal_id=principal_id, limit=10)
        commitment_candidates = self.list_commitment_candidates(principal_id=principal_id, limit=8)
        drafts = self.list_drafts(principal_id=principal_id, limit=8)
        decisions = self.list_decisions(principal_id=principal_id, limit=8)
        threads = self.list_threads(principal_id=principal_id, limit=8)
        people = self.list_people(principal_id=principal_id, limit=8)
        handoffs = self.list_handoffs(principal_id=principal_id, limit=8, operator_id=operator_id)
        completed_handoffs = self.list_handoffs(
            principal_id=principal_id,
            limit=6,
            operator_id=operator_id,
            status="returned",
        )
        queue_health, _suggestions = self._queue_health(principal_id=principal_id, operator_id=operator_id)
        evidence = self.list_evidence(principal_id=principal_id, limit=8, operator_id=operator_id)
        rules = self.list_rules(principal_id=principal_id)
        return ProductSnapshot(
            brief_items=brief_items,
            queue_items=queue_items,
            commitments=commitments,
            commitment_candidates=commitment_candidates,
            drafts=drafts,
            decisions=decisions,
            threads=threads,
            people=people,
            handoffs=handoffs,
            completed_handoffs=completed_handoffs,
            evidence=evidence,
            rules=rules,
            stats_json={
                "brief_items": len(brief_items),
                "queue_items": len(queue_items),
                "commitments": len(commitments),
                "commitment_candidates": len(commitment_candidates),
                "drafts": len(drafts),
                "decisions": len(decisions),
                "threads": len(threads),
                "people": len(people),
                "handoffs": len(handoffs),
                "completed_handoffs": len(completed_handoffs),
                "sla_breaches": int(queue_health.get("sla_breaches") or 0),
                "unclaimed_handoffs": int(queue_health.get("unclaimed_handoffs") or 0),
                "pending_approvals": int(queue_health.get("pending_approvals") or 0),
                "pending_delivery": int(queue_health.get("pending_delivery") or 0),
                "waiting_on_principal": int(queue_health.get("waiting_on_principal") or 0),
                "evidence": len(evidence),
                "rules": len(rules),
            },
        )

    def workspace_diagnostics(self, *, principal_id: str) -> dict[str, object]:
        status = self._container.onboarding.status(principal_id=principal_id)
        workspace = dict(status.get("workspace") or {})
        selected_channels = tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip())
        plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
        snapshot = self.workspace_snapshot(principal_id=principal_id)
        queue_health, assignment_suggestions = self._queue_health(principal_id=principal_id)
        readiness_ok, readiness_label = self._container.readiness.check()
        registry = self._container.provider_registry.registry_read_model(principal_id=principal_id)
        provider_summary = self._provider_summary(registry)
        operators = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
        product_events = [
            row
            for row in self._container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id)
            if str(row.channel or "").strip() == "product"
        ]
        event_rows = sorted(product_events, key=lambda row: str(row.created_at or ""))
        analytics_counts: dict[str, int] = {}
        activation_started_at = ""
        first_value_at = ""
        first_value_event = ""
        first_value_types = {"draft_approved", "commitment_created", "commitment_closed", "handoff_completed", "memory_corrected", "memo_opened"}
        for row in event_rows:
            analytics_counts[row.event_type] = int(analytics_counts.get(row.event_type, 0) or 0) + 1
            created_at = str(row.created_at or "").strip()
            if row.event_type == "activation_opened" and created_at and not activation_started_at:
                activation_started_at = created_at
            if row.event_type in first_value_types and created_at and not first_value_at:
                first_value_at = created_at
                first_value_event = row.event_type
        first_value_seconds: int | None = None
        if activation_started_at and first_value_at:
            try:
                started = datetime.fromisoformat(activation_started_at.replace("Z", "+00:00"))
                reached = datetime.fromisoformat(first_value_at.replace("Z", "+00:00"))
                first_value_seconds = max(int((reached - started).total_seconds()), 0)
            except Exception:
                first_value_seconds = None
        usage_stats = dict(snapshot.stats_json or {})
        seats_used = len(operators)
        seat_limit = int(plan.entitlements.operator_seats or 0)
        seats_remaining = max(seat_limit - seats_used, 0)
        seat_overage = max(seats_used - seat_limit, 0)
        commercial_snapshot = workspace_commercial_snapshot(plan, seats_used=seats_used, selected_channels=selected_channels)
        selected_messaging = [str(value) for value in (commercial_snapshot.get("commercial", {}).get("selected_messaging_channels") or []) if str(value).strip()]
        warnings = [str(value) for value in (commercial_snapshot.get("commercial", {}).get("warnings") or []) if str(value).strip()]
        blocked_actions = [str(value) for value in (commercial_snapshot.get("commercial", {}).get("blocked_actions") or []) if str(value).strip()]
        if not readiness_ok:
            warnings.append(str(readiness_label or "Runtime readiness needs attention."))
            blocked_actions.append("runtime_readiness")
        if str(provider_summary.get("risk_state") or "") in {"attention", "watch", "critical"}:
            warnings.append(str(provider_summary.get("risk_detail") or "Provider posture needs attention."))
        recommended_plan = plan
        if seat_overage or (selected_messaging and not plan.entitlements.messaging_channels_enabled):
            recommended_plan = workspace_plan_for_mode("team" if plan.plan_key == "pilot" else "executive_ops")
        health_score = 100
        if not readiness_ok:
            health_score -= 30
        provider_risk = str(provider_summary.get("risk_state") or "healthy")
        if provider_risk == "watch":
            health_score -= 15
        elif provider_risk in {"attention", "critical"}:
            health_score -= 30
        queue_state = str(queue_health.get("state") or "healthy")
        if queue_state == "watch":
            health_score -= 15
        elif queue_state == "critical":
            health_score -= 30
        health_score = max(health_score - min(int(queue_health.get("delivery_errors") or 0) * 3, 15), 0)
        memo_opened_count = int(analytics_counts.get("memo_opened") or 0)
        approval_requested_count = int(analytics_counts.get("approval_requested") or 0)
        draft_approved_count = int(analytics_counts.get("draft_approved") or 0)
        commitment_closed_count = int(analytics_counts.get("commitment_closed") or 0)
        memory_corrected_count = int(analytics_counts.get("memory_corrected") or 0)
        support_bundle_opened_count = int(analytics_counts.get("support_bundle_opened") or 0)
        current_commitments = int(usage_stats.get("commitments") or 0)
        current_queue_items = int(usage_stats.get("queue_items") or 0)
        memo_open_rate = 1.0 if memo_opened_count else 0.0
        approval_action_rate = (
            round(draft_approved_count / approval_requested_count, 2)
            if approval_requested_count
            else (1.0 if draft_approved_count else 0.0)
        )
        commitment_close_rate = round(commitment_closed_count / max(commitment_closed_count + current_commitments, 1), 2)
        correction_rate = round(memory_corrected_count / max(memo_opened_count, 1), 2)
        churn_risk = "low"
        if (first_value_seconds is None and current_queue_items >= 3) or memo_opened_count == 0:
            churn_risk = "watch"
        if (first_value_seconds is None and current_queue_items >= 5) or support_bundle_opened_count > memo_opened_count:
            churn_risk = "high"
        success_summary = (
            "Office loop is active."
            if churn_risk == "low"
            else "Activation needs help."
            if churn_risk == "high"
            else "Adoption needs attention."
        )
        return {
            "workspace": {
                "name": str(workspace.get("name") or "Executive Workspace"),
                "mode": str(workspace.get("mode") or "personal"),
                "region": str(workspace.get("region") or ""),
                "language": str(workspace.get("language") or ""),
                "timezone": str(workspace.get("timezone") or ""),
            },
            "selected_channels": list(selected_channels),
            "plan": {
                "plan_key": plan.plan_key,
                "display_name": plan.display_name,
                "unit_of_sale": plan.unit_of_sale,
            },
            "billing": dict(commercial_snapshot.get("billing") or {}),
            "entitlements": {
                "principal_seats": plan.entitlements.principal_seats,
                "operator_seats": plan.entitlements.operator_seats,
                "messaging_channels_enabled": plan.entitlements.messaging_channels_enabled,
                "audit_retention": plan.entitlements.audit_retention,
                "feature_flags": list(plan.entitlements.feature_flags),
            },
            "readiness": {
                "ready": readiness_ok,
                "detail": readiness_label,
                "health_score": health_score,
                "risk_state": "healthy" if health_score >= 85 else "watch" if health_score >= 60 else "critical",
            },
            "operators": {
                "active_count": seats_used,
                "seats_used": seats_used,
                "seats_remaining": seats_remaining,
                "seat_overage": seat_overage,
                "active_operator_ids": [str(row.operator_id or "") for row in operators if str(row.operator_id or "").strip()],
                "active_operator_names": [str(row.display_name or row.operator_id or "") for row in operators if str(row.display_name or row.operator_id or "").strip()],
            },
            "commercial": {
                **dict(commercial_snapshot.get("commercial") or {}),
                "warnings": warnings,
                "blocked_actions": blocked_actions,
                "recommended_plan_key": recommended_plan.plan_key,
                "recommended_plan_label": recommended_plan.display_name,
            },
            "providers": {
                "provider_count": int(registry.get("provider_count") or 0),
                "lane_count": int(registry.get("lane_count") or 0),
                **provider_summary,
            },
            "queue_health": {
                **queue_health,
                "assignment_suggestions": [
                    {
                        "id": row.id,
                        "summary": row.summary,
                        "owner": row.owner,
                        "due_time": row.due_time,
                        "escalation_status": row.escalation_status,
                    }
                    for row in assignment_suggestions
                ],
            },
            "usage": usage_stats,
            "analytics": {
                "counts": analytics_counts,
                "activation_started_at": activation_started_at,
                "first_value_at": first_value_at,
                "first_value_event": first_value_event,
                "time_to_first_value_seconds": first_value_seconds,
                "memo_open_rate": memo_open_rate,
                "approval_action_rate": approval_action_rate,
                "commitment_close_rate": commitment_close_rate,
                "correction_rate": correction_rate,
                "churn_risk": churn_risk,
                "success_summary": success_summary,
                "recent_events": [
                    {
                        "event_type": row.event_type,
                        "created_at": row.created_at,
                        "source_id": row.source_id,
                        "payload": dict(row.payload or {}),
                    }
                    for row in product_events[:12]
                ],
            },
        }

    def workspace_support_bundle(self, *, principal_id: str) -> dict[str, object]:
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        queue_health = dict(diagnostics.get("queue_health") or {})
        approvals = self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=25)
        approval_history = self._container.orchestrator.list_approval_history_for_principal(principal_id=principal_id, limit=25)
        human_tasks = self._container.orchestrator.list_human_tasks(principal_id=principal_id, status=None, limit=25)
        provider_registry = self._container.provider_registry.registry_read_model(principal_id=principal_id)
        pending_delivery = self._container.channel_runtime.list_pending_delivery(limit=25, principal_id=principal_id)
        return {
            "workspace": diagnostics["workspace"],
            "selected_channels": diagnostics["selected_channels"],
            "plan": diagnostics["plan"],
            "billing": diagnostics["billing"],
            "entitlements": diagnostics["entitlements"],
            "commercial": diagnostics["commercial"],
            "readiness": diagnostics["readiness"],
            "usage": diagnostics["usage"],
            "analytics": diagnostics["analytics"],
            "approvals": {
                "pending": [
                    {
                        "approval_id": row.approval_id,
                        "reason": row.reason,
                        "status": row.status,
                        "expires_at": row.expires_at,
                        "session_id": row.session_id,
                    }
                    for row in approvals
                ],
                "recent_decisions": [
                    {
                        "decision_id": row.decision_id,
                        "approval_id": row.approval_id,
                        "decision": row.decision,
                        "reason": row.reason,
                        "created_at": row.created_at,
                    }
                    for row in approval_history
                ],
            },
            "human_tasks": [
                {
                    "human_task_id": row.human_task_id,
                    "brief": row.brief,
                    "status": row.status,
                    "assignment_state": row.assignment_state,
                    "assigned_operator_id": row.assigned_operator_id,
                    "priority": row.priority,
                    "sla_due_at": row.sla_due_at,
                }
                for row in human_tasks
            ],
            "providers": {**provider_registry, **dict(diagnostics.get("providers") or {})},
            "queue_health": queue_health,
            "assignment_suggestions": list(queue_health.get("assignment_suggestions") or []),
            "pending_delivery": [
                {
                    "delivery_id": row.delivery_id,
                    "channel": row.channel,
                    "recipient": row.recipient,
                    "status": row.status,
                    "attempt_count": row.attempt_count,
                    "last_error": row.last_error,
                }
                for row in pending_delivery
            ],
            "recent_events": list(self.list_office_events(principal_id=principal_id, limit=20)),
        }

    def channel_loop_pack(self, *, principal_id: str, operator_id: str = "") -> dict[str, object]:
        snapshot = self.workspace_snapshot(principal_id=principal_id, operator_id=operator_id)
        operator_key = str(operator_id or "").strip()
        items: list[dict[str, str]] = []
        if snapshot.brief_items:
            memo = snapshot.brief_items[0]
            items.append(
                {
                    "title": "Morning memo",
                    "detail": memo.why_now or memo.summary or "Open the memo before the day fragments.",
                    "tag": "Memo",
                    "href": "/app/today",
                    "action_href": "/app/today",
                    "action_label": "Open memo",
                    "action_method": "get",
                }
            )
        if snapshot.drafts:
            draft = snapshot.drafts[0]
            items.append(
                {
                    "title": f"Approve draft for {draft.recipient_summary or 'next reply'}",
                    "detail": " · ".join(
                        part
                        for part in (
                            draft.intent.title(),
                            draft.send_channel,
                            draft.approval_status,
                        )
                        if part
                    )
                    or "Draft is waiting for approval.",
                    "tag": "Draft",
                    "href": "/app/inbox",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="draft",
                        object_ref=draft.id,
                        action="approve",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Approved from inline loop.",
                    ),
                    "action_label": "Approve now",
                    "action_method": "get",
                }
            )
        if snapshot.commitments:
            commitment = snapshot.commitments[0]
            items.append(
                {
                    "title": commitment.statement,
                    "detail": " · ".join(
                        part
                        for part in (
                            commitment.counterparty,
                            f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                            commitment.risk_level.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Commitment still needs a visible next action.",
                    "tag": "Commitment",
                    "href": f"/app/commitment-items/{commitment.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="close",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Closed from inline loop.",
                    ),
                    "action_label": "Close",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="defer",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Deferred from inline loop.",
                    ),
                    "secondary_action_label": "Defer",
                    "secondary_action_method": "get",
                }
            )
        if snapshot.handoffs:
            preferred_handoff = next((row for row in snapshot.handoffs if operator_key and row.owner == operator_key), snapshot.handoffs[0])
            action_href = self.channel_action_href(
                principal_id=principal_id,
                object_kind="handoff",
                object_ref=preferred_handoff.id,
                action="assign",
                return_to="/app/channel-loop",
                operator_id=operator_key or preferred_handoff.owner,
                reason="Claimed from inline loop.",
            )
            action_label = "Claim"
            if operator_key and preferred_handoff.owner == operator_key:
                action_href = self.channel_action_href(
                    principal_id=principal_id,
                    object_kind="handoff",
                    object_ref=preferred_handoff.id,
                    action="complete",
                    return_to="/app/channel-loop",
                    operator_id=operator_key,
                    reason="Completed from inline loop.",
                )
                action_label = "Complete"
            items.append(
                {
                    "title": preferred_handoff.summary,
                    "detail": " · ".join(
                        part
                        for part in (
                            preferred_handoff.owner,
                            f"Due {preferred_handoff.due_time[:10]}" if preferred_handoff.due_time else "",
                            preferred_handoff.escalation_status.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Handoff is waiting in the operator lane.",
                    "tag": "Handoff",
                    "href": f"/app/handoffs/{preferred_handoff.id}",
                    "action_href": action_href,
                    "action_label": action_label,
                    "action_method": "get",
                }
            )
        if snapshot.decisions:
            decision = snapshot.decisions[0]
            items.append(
                {
                    "title": decision.title,
                    "detail": " · ".join(
                        part
                        for part in (
                            decision.sla_status.replace("_", " ").title(),
                            decision.impact_summary or decision.summary,
                        )
                        if part
                    )
                    or "Decision remains open.",
                    "tag": "Decision",
                    "href": f"/app/decisions/{decision.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="decision",
                        object_ref=decision.id,
                        action="resolve",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Resolved from inline loop.",
                    ),
                    "action_label": "Resolve now",
                    "action_method": "get",
                    "secondary_action_href": f"/app/decisions/{decision.id}",
                    "secondary_action_label": "Review",
                    "secondary_action_method": "get",
                }
            )
        digests = self._channel_digests(snapshot=snapshot, operator_key=operator_key, principal_id=principal_id)
        return {
            "headline": "Inline loop",
            "summary": "Use a compact, mobile-safe surface for the memo, approvals, commitments, handoffs, and the next decision that still matters.",
            "items": items,
            "stats": {
                "memo_items": int(snapshot.stats_json.get("brief_items", 0) or 0),
                "pending_drafts": len(snapshot.drafts),
                "open_commitments": len(snapshot.commitments),
                "open_handoffs": len(snapshot.handoffs),
                "open_decisions": len(snapshot.decisions),
            },
            "digests": digests,
        }

    def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = "") -> dict[str, object] | None:
        pack = self.channel_loop_pack(principal_id=principal_id, operator_id=operator_id)
        wanted = str(digest_key or "").strip().lower()
        for row in list(pack.get("digests") or []):
            if str(row.get("key") or "").strip().lower() == wanted:
                return dict(row)
        return None

    def channel_digest_text(
        self,
        *,
        principal_id: str,
        digest_key: str,
        operator_id: str = "",
        base_url: str = "",
    ) -> str:
        digest = self.channel_digest_pack(principal_id=principal_id, digest_key=digest_key, operator_id=operator_id)
        if digest is None:
            return ""
        normalized_base = str(base_url or "").strip()

        def absolute(href: str) -> str:
            value = str(href or "").strip()
            if not value:
                return ""
            if "://" in value:
                return value
            if normalized_base:
                return urllib.parse.urljoin(normalized_base, value)
            return value

        lines: list[str] = [
            str(digest.get("headline") or "Channel digest").strip(),
            str(digest.get("summary") or "").strip(),
            str(digest.get("preview_text") or "").strip(),
            "",
        ]
        for index, item in enumerate(list(digest.get("items") or []), start=1):
            title = str(item.get("title") or f"Item {index}").strip()
            tag = str(item.get("tag") or "").strip()
            detail = str(item.get("detail") or "").strip()
            action_label = str(item.get("action_label") or "").strip()
            action_href = absolute(str(item.get("action_href") or "").strip())
            secondary_label = str(item.get("secondary_action_label") or "").strip()
            secondary_href = absolute(str(item.get("secondary_action_href") or "").strip())
            href = absolute(str(item.get("href") or "").strip())
            header = f"{index}. [{tag}] {title}" if tag else f"{index}. {title}"
            lines.append(header)
            if detail:
                lines.append(f"   {detail}")
            if action_label and action_href:
                lines.append(f"   {action_label}: {action_href}")
            if secondary_label and secondary_href:
                lines.append(f"   {secondary_label}: {secondary_href}")
            elif href:
                lines.append(f"   Open: {href}")
            lines.append("")
        return "\n".join(line for line in lines if line or (lines and line == ""))

    def _channel_digests(self, *, snapshot: ProductSnapshot, operator_key: str, principal_id: str) -> list[dict[str, object]]:
        at_risk_commitments = [
            item
            for item in snapshot.commitments
            if _is_past_due(item.due_at) or item.risk_level in {"high", "critical", "due_now"}
        ]
        open_decisions = [item for item in snapshot.decisions if item.status != "decided"]
        principal_queue = [item for item in snapshot.queue_items if item.requires_principal]
        assigned_handoffs = [item for item in snapshot.handoffs if operator_key and item.owner == operator_key]
        unclaimed_handoffs = [item for item in snapshot.handoffs if not str(item.owner or "").strip()]
        visible_handoffs = assigned_handoffs[:1] + unclaimed_handoffs[:2]
        if not visible_handoffs:
            visible_handoffs = list(snapshot.handoffs[:2])
        memo_items: list[dict[str, str]] = []
        for item in snapshot.brief_items[:2]:
            memo_items.append(
                {
                    "title": item.title,
                    "detail": item.why_now or item.summary or "Open the memo before the day fragments.",
                    "tag": item.kind.replace("_", " ").title() or "Memo",
                    "href": "/app/today",
                    "action_href": "/app/today",
                    "action_label": "Open memo",
                    "action_method": "get",
                }
            )
        if at_risk_commitments:
            commitment = at_risk_commitments[0]
            memo_items.append(
                {
                    "title": commitment.statement,
                    "detail": " · ".join(
                        part
                        for part in (
                            commitment.counterparty,
                            f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                            commitment.risk_level.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Commitment pressure needs a visible next action.",
                    "tag": "Commitment",
                    "href": f"/app/commitment-items/{commitment.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="close",
                        return_to="/app/channel-loop/memo",
                        operator_id=operator_key,
                        reason="Closed from morning memo digest.",
                    ),
                    "action_label": "Close",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="defer",
                        return_to="/app/channel-loop/memo",
                        operator_id=operator_key,
                        reason="Deferred from morning memo digest.",
                    ),
                    "secondary_action_label": "Defer",
                    "secondary_action_method": "get",
                }
            )
        approval_items: list[dict[str, str]] = []
        for draft in snapshot.drafts[:2]:
            approval_items.append(
                {
                    "title": f"Approve draft for {draft.recipient_summary or 'next reply'}",
                    "detail": " · ".join(
                        part for part in (draft.intent.title(), draft.send_channel, draft.approval_status) if part
                    )
                    or "Draft is waiting for approval.",
                    "tag": "Draft",
                    "href": "/app/inbox",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="draft",
                        object_ref=draft.id,
                        action="approve",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Approved from inline approvals digest.",
                    ),
                    "action_label": "Approve now",
                    "action_method": "get",
                }
            )
        for decision in open_decisions[:2]:
            approval_items.append(
                {
                    "title": decision.title,
                    "detail": " · ".join(
                        part
                        for part in (
                            decision.owner_role,
                            decision.sla_status.replace("_", " ").title(),
                            decision.impact_summary or decision.summary,
                        )
                        if part
                    )
                    or "Decision still needs a visible resolution.",
                    "tag": "Decision",
                    "href": f"/app/decisions/{decision.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="decision",
                        object_ref=decision.id,
                        action="resolve",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Resolved from inline approvals digest.",
                    ),
                    "action_label": "Resolve now",
                    "action_method": "get",
                    "secondary_action_href": f"/app/decisions/{decision.id}",
                    "secondary_action_label": "Review",
                    "secondary_action_method": "get",
                }
            )
        operator_items: list[dict[str, str]] = []
        for handoff in visible_handoffs:
            action_href = self.channel_action_href(
                principal_id=principal_id,
                object_kind="handoff",
                object_ref=handoff.id,
                action="assign",
                return_to="/app/channel-loop/operator",
                operator_id=operator_key or handoff.owner,
                reason="Claimed from operator digest.",
            )
            action_label = "Claim"
            if operator_key and handoff.owner == operator_key:
                action_href = self.channel_action_href(
                    principal_id=principal_id,
                    object_kind="handoff",
                    object_ref=handoff.id,
                    action="complete",
                    return_to="/app/channel-loop/operator",
                    operator_id=operator_key,
                    reason="Completed from operator digest.",
                )
                action_label = "Complete"
            operator_items.append(
                {
                    "title": handoff.summary,
                    "detail": " · ".join(
                        part
                        for part in (
                            handoff.owner or "Unclaimed",
                            f"Due {handoff.due_time[:10]}" if handoff.due_time else "",
                            handoff.escalation_status.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Handoff is waiting in the operator lane.",
                    "tag": "Handoff",
                    "href": f"/app/handoffs/{handoff.id}",
                    "action_href": action_href,
                    "action_label": action_label,
                    "action_method": "get",
                }
            )
        if snapshot.commitments:
            commitment = at_risk_commitments[0] if at_risk_commitments else snapshot.commitments[0]
            operator_items.append(
                {
                    "title": commitment.statement,
                    "detail": " · ".join(
                        part
                        for part in (
                            commitment.counterparty,
                            f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                            commitment.risk_level.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Commitment still needs an explicit owner and next step.",
                    "tag": "Commitment",
                    "href": f"/app/commitment-items/{commitment.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="close",
                        return_to="/app/channel-loop/operator",
                        operator_id=operator_key,
                        reason="Closed from operator digest.",
                    ),
                    "action_label": "Close",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="defer",
                        return_to="/app/channel-loop/operator",
                        operator_id=operator_key,
                        reason="Deferred from operator digest.",
                    ),
                    "secondary_action_label": "Defer",
                    "secondary_action_method": "get",
                }
            )
        return [
            {
                "key": "memo",
                "headline": "Morning memo digest",
                "summary": "Forward or open the ranked day brief from a mobile-safe surface.",
                "preview_text": f"{len(snapshot.brief_items)} memo items, {len(at_risk_commitments)} commitments at risk, {len(open_decisions)} open decisions.",
                "items": memo_items,
                "stats": {
                    "memo_items": len(snapshot.brief_items),
                    "at_risk_commitments": len(at_risk_commitments),
                    "open_decisions": len(open_decisions),
                },
            },
            {
                "key": "approvals",
                "headline": "Inline approvals",
                "summary": "Clear draft approvals and decision pressure without dropping into the full workspace.",
                "preview_text": f"{len(snapshot.drafts)} pending drafts and {len(principal_queue)} principal-backed queue items are waiting.",
                "items": approval_items,
                "stats": {
                    "pending_drafts": len(snapshot.drafts),
                    "principal_queue_items": len(principal_queue),
                    "open_decisions": len(open_decisions),
                },
            },
            {
                "key": "operator",
                "headline": "Operator handoff digest",
                "summary": "Claim, complete, and close the next office item from a compact operator surface.",
                "preview_text": f"{len(assigned_handoffs)} assigned handoffs, {len(unclaimed_handoffs)} unclaimed handoffs, {len(snapshot.commitments)} open commitments.",
                "items": operator_items,
                "stats": {
                    "assigned_handoffs": len(assigned_handoffs),
                    "unclaimed_handoffs": len(unclaimed_handoffs),
                    "open_commitments": len(snapshot.commitments),
                },
            },
        ]

    def channel_action_href(
        self,
        *,
        principal_id: str,
        object_kind: str,
        object_ref: str,
        action: str,
        return_to: str,
        operator_id: str = "",
        reason: str = "",
        expires_in_seconds: int = 60 * 60 * 24 * 7,
    ) -> str:
        expires_at = datetime.now(timezone.utc).timestamp() + max(int(expires_in_seconds), 300)
        payload = {
            "principal_id": str(principal_id or "").strip(),
            "object_kind": str(object_kind or "").strip(),
            "object_ref": str(object_ref or "").strip(),
            "action": str(action or "").strip(),
            "return_to": str(return_to or "/app/channel-loop").strip() or "/app/channel-loop",
            "operator_id": str(operator_id or "").strip(),
            "reason": str(reason or "").strip(),
            "issued_at": _now_iso(),
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
        token = _sign_channel_payload(secret=self._channel_action_secret(), payload=payload)
        return f"/app/channel-actions/{token}"

    def redeem_channel_action_token(
        self,
        *,
        token: str,
        actor: str = "",
        preferred_operator_id: str = "",
    ) -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._channel_action_secret(), token=token)
        if payload is None:
            return None
        principal_id = str(payload.get("principal_id") or "").strip()
        object_kind = str(payload.get("object_kind") or "").strip().lower()
        object_ref = str(payload.get("object_ref") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        return_to = str(payload.get("return_to") or "/sign-in").strip() or "/sign-in"
        reason = str(payload.get("reason") or "Resolved from channel action link.").strip() or "Resolved from channel action link."
        operator_id = str(preferred_operator_id or payload.get("operator_id") or "").strip()
        resolved_actor = str(actor or operator_id or principal_id or "channel_link").strip() or "channel_link"
        if not principal_id or not object_kind or not object_ref or not action:
            return None
        result: object | None = None
        if object_kind == "draft":
            result = self.approve_draft(
                principal_id=principal_id,
                draft_ref=object_ref,
                decided_by=resolved_actor,
                reason=reason,
            )
        elif object_kind == "queue":
            result = self.resolve_queue_item(
                principal_id=principal_id,
                item_ref=object_ref,
                action=action,
                actor=resolved_actor,
                reason=reason,
            )
        elif object_kind == "decision":
            result = self.resolve_decision(
                principal_id=principal_id,
                decision_ref=object_ref,
                actor=resolved_actor,
                action=action,
                reason=reason,
            )
        elif object_kind == "handoff":
            if not operator_id:
                active = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=1)
                operator_id = str(active[0].operator_id or "").strip() if active else ""
            if not operator_id:
                return None
            if action == "complete":
                result = self.complete_handoff(
                    principal_id=principal_id,
                    handoff_ref=object_ref,
                    operator_id=operator_id,
                    actor=resolved_actor,
                    resolution="completed",
                )
            else:
                result = self.assign_handoff(
                    principal_id=principal_id,
                    handoff_ref=object_ref,
                    operator_id=operator_id,
                    actor=resolved_actor,
                )
        if result is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="channel_action_redeemed",
            payload={
                "object_kind": object_kind,
                "object_ref": object_ref,
                "action": action,
                "actor": resolved_actor,
                "return_to": return_to,
            },
            source_id=object_ref,
            dedupe_key=f"{principal_id}|{object_kind}|{object_ref}|{action}|{token}",
        )
        return {
            "principal_id": principal_id,
            "object_kind": object_kind,
            "object_ref": object_ref,
            "action": action,
            "return_to": return_to,
            "actor": resolved_actor,
        }

    def record_surface_event(
        self,
        *,
        principal_id: str,
        event_type: str,
        surface: str,
        actor: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        normalized_type = str(event_type or "").strip().lower()
        normalized_surface = str(surface or "").strip().lower()
        if not normalized_type or not normalized_surface:
            return
        payload = {
            "surface": normalized_surface,
            "actor": str(actor or "").strip() or "browser",
        }
        if metadata:
            payload.update(dict(metadata))
        self._record_product_event(
            principal_id=principal_id,
            event_type=normalized_type,
            payload=payload,
            source_id=normalized_surface,
        )


def build_product_service(container: AppContainer) -> ProductService:
    return ProductService(container)
