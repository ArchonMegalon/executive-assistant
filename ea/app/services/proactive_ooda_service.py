from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


ACTION_TERMS = (
    "action required",
    "approval",
    "approve",
    "asap",
    "book",
    "blocked",
    "blocking",
    "budget",
    "buy",
    "cancel",
    "compare",
    "contract",
    "deadline",
    "decide",
    "decision",
    "due",
    "escalat",
    "find",
    "follow up",
    "invoice",
    "launch",
    "legal",
    "meeting",
    "order",
    "overdue",
    "pay",
    "proposal",
    "renew",
    "research",
    "reply",
    "review",
    "risk",
    "schedule",
    "shop",
    "shopping",
    "sign",
    "today",
    "tomorrow",
    "urgent",
)

HIGH_URGENCY_TERMS = (
    "asap",
    "blocked",
    "blocking",
    "deadline",
    "overdue",
    "today",
    "urgent",
)

APPROVAL_TERMS = (
    "approval",
    "approve",
    "budget",
    "cancel",
    "contract",
    "legal",
    "pay",
    "sign",
)

DIRECT_REQUEST_TERMS = (
    "action required",
    "approval needed",
    "approve this",
    "bitte um",
    "can you",
    "could you",
    "find me",
    "formuliere",
    "i need you to",
    "ich brauche",
    "kannst du",
    "koenntest du",
    "please approve",
    "please reply",
    "please review",
    "please send",
    "reply to",
    "schick",
    "schicke",
    "schreib",
    "schreibe",
    "send me",
    "suche",
    "such mir",
)

STRONG_ACTION_TERMS = (
    "book",
    "buy",
    "cancel",
    "compare",
    "contract",
    "deadline",
    "due",
    "find",
    "follow up",
    "invoice",
    "legal",
    "order",
    "overdue",
    "pay",
    "proposal",
    "renew",
    "reply",
    "respond",
    "schedule",
    "shop",
    "sign",
)

REVIEW_CONTEXT_TERMS = (
    "budget",
    "contract",
    "decision",
    "invoice",
    "launch",
    "legal",
    "meeting",
    "option",
    "proposal",
    "provider",
    "renewal",
    "vendor",
)

OPERATIONAL_RISK_TERMS = (
    "alert",
    "blocked",
    "down",
    "failed",
    "failure",
    "incident",
    "offline",
    "outage",
    "urgent",
)

HIGH_CONFIDENCE_MAIL_ACTION_TERMS = (
    "action required",
    "approval needed",
    "contract",
    "deadline",
    "invoice due",
    "legal",
    "overdue",
    "payment overdue",
    "please approve",
    "requires approval",
    "sign",
)

LOW_SIGNAL_GMAIL_LABELS = {
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
}

LOW_SIGNAL_MAIL_TERMS = (
    "angebot",
    "beleg fuer ihre zahlung",
    "beleg für ihre zahlung",
    "bestellbestaetigung",
    "bestellbestätigung",
    "deal",
    "die schönsten",
    "hat ein update gepostet",
    "newsletter",
    "new post",
    "neu:",
    "order confirmation",
    "payment receipt",
    "posted an update",
    "promotion",
    "purchase receipt",
    "receipt for your payment",
    "sale",
    "thanks for your order",
    "unsubscribe",
    "update gepostet",
    "you paid",
    "zahlung an",
)

LOW_SIGNAL_STATUS_QUESTION_TERMS = (
    "any update",
    "did you find anything",
    "what did you find",
    "was hast du gefunden",
    "what did you get",
    "what happened",
)

STRUCTURED_STAGE_MATERIAL_KEYS = (
    "candidate_items",
    "candidates",
    "links",
    "draft",
    "draft_text",
    "request",
    "request_text",
    "user_request",
    "task_request",
    "draft_request_text",
    "cart_url",
    "approval_url",
    "booking_options",
    "research_query",
    "search_queries",
    "target_sites",
    "browser_task",
    "browser_action",
    "browser_execution",
    "browser_operations",
    "browser_login_url",
    "login_url",
    "site_url",
    "target_url",
)

STRUCTURED_BOOKKEEPING_MARKERS = (
    "commitment candidate",
    "interruption budget",
    "no additional ltd lane",
    "no commitment candidate was strong enough",
    "promotion candidates",
    "stage 1 commitment candidate",
)

SOURCE_HEALTH_SIGNAL_TYPES = {
    "proactive_source_health",
    "source_health",
}


@dataclass(frozen=True)
class ProactiveSignal:
    source_ref: str
    signal_type: str
    channel: str
    title: str
    summary: str
    counterparty: str = ""
    due_at: str | None = None
    external_id: str = ""
    payload: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "ProactiveSignal":
        return cls(
            source_ref=str(row.get("source_ref") or row.get("ref") or row.get("id") or "").strip(),
            signal_type=str(row.get("signal_type") or row.get("type") or "signal").strip(),
            channel=str(row.get("channel") or "workspace").strip(),
            title=str(row.get("title") or "").strip(),
            summary=str(row.get("summary") or row.get("body") or "").strip(),
            counterparty=str(row.get("counterparty") or row.get("from") or "").strip(),
            due_at=str(row.get("due_at") or "").strip() or None,
            external_id=str(row.get("external_id") or "").strip(),
            payload=row.get("payload") if isinstance(row.get("payload"), Mapping) else None,
        )

    def stable_ref(self) -> str:
        if self.source_ref:
            return self.source_ref
        raw = "\n".join((self.channel, self.signal_type, self.title, self.summary, self.external_id))
        return f"signal:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"

    def dedupe_marker(self) -> str:
        external = str(self.external_id or "").strip()
        return f"external_id:{external}" if external else ""


@dataclass(frozen=True)
class OodaInk:
    signal_ref: str
    priority: str
    observe: str
    orient: str
    decide: str
    act: str
    evidence: tuple[str, ...]
    approval_required: bool
    ignored_consequence: str
    notify: bool
    action_plan: tuple[str, ...] = ()
    stage_kind: str = ""
    stage_summary: str = ""
    stage_artifacts: tuple[str, ...] = ()
    stage_payload: Mapping[str, Any] | None = None
    approval_gate: str = ""
    external_action_policy: str = ""


@dataclass(frozen=True)
class ProactiveOodaDigest:
    principal_id: str
    generated_at: str
    items: tuple[OodaInk, ...]
    notified_refs: tuple[str, ...]
    notified_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProactiveOodaRunReceipt:
    principal_id_hash: str
    generated_at: str
    dry_run: bool
    item_count: int
    notified_ref_hashes: tuple[str, ...]
    notification_status: str
    telegram_message_ids: tuple[str, ...]
    stage_packet_ref_hashes: tuple[str, ...] = ()
    stage_packet_error_count: int = 0
    safe_work_result_ref_hashes: tuple[str, ...] = ()
    safe_work_result_error_count: int = 0
    error_code: str = ""
    delivery_channel: str = ""
    delivery_transport: str = ""
    delivery_selected_by: str = ""
    delivery_recipient_hash: str = ""
    delivery_message_ids: tuple[str, ...] = ()
    delivery_outbox_id_hash: str = ""
    delivery_route_error: str = ""
    delivery_recovery_hint: str = ""
    delivery_next_action: str = ""
    approval_surface: Mapping[str, Any] | None = None
    delivery_guard: Mapping[str, Any] | None = None


class JsonOodaStateStore:
    INTERRUPTION_EVENTS_KEY = "_proactive_ooda_interruption_events"
    OPPORTUNITY_RULE_STATE_KEY = "_proactive_ooda_opportunity_rule_state"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load_notified_refs(self, principal_id: str) -> set[str]:
        payload = self._read()
        refs = payload.get(_state_key(principal_id), payload.get(principal_id, []))
        if not isinstance(refs, list):
            return set()
        return {str(item) for item in refs if str(item).strip()}

    def save_notified_refs(self, principal_id: str, refs: Iterable[str]) -> None:
        payload = self._read()
        payload[_state_key(principal_id)] = sorted({_state_key(str(item)) for item in refs if str(item).strip()})
        payload.pop(principal_id, None)
        self._write(payload)

    def load_interruption_events(self, principal_id: str) -> tuple[str, ...]:
        payload = self._read()
        bucket = payload.get(self.INTERRUPTION_EVENTS_KEY)
        if not isinstance(bucket, Mapping):
            return ()
        events = bucket.get(_state_key(principal_id), bucket.get(principal_id, []))
        if not isinstance(events, list):
            return ()
        return tuple(str(item).strip() for item in events if str(item).strip())

    def save_interruption_events(self, principal_id: str, events: Iterable[str]) -> None:
        payload = self._read()
        bucket = self._mapping_bucket(payload, self.INTERRUPTION_EVENTS_KEY)
        key = _state_key(principal_id)
        bucket[key] = [str(item).strip() for item in events if str(item).strip()]
        bucket.pop(principal_id, None)
        payload[self.INTERRUPTION_EVENTS_KEY] = bucket
        self._write(payload)

    def load_opportunity_rule_state(self, principal_id: str, rule_id: str) -> dict[str, Any]:
        payload = self._read()
        bucket = payload.get(self.OPPORTUNITY_RULE_STATE_KEY)
        if not isinstance(bucket, Mapping):
            return {}
        principal_bucket = bucket.get(_state_key(principal_id), bucket.get(principal_id, {}))
        if not isinstance(principal_bucket, Mapping):
            return {}
        state = principal_bucket.get(_state_key(rule_id), principal_bucket.get(rule_id, {}))
        return dict(state) if isinstance(state, Mapping) else {}

    def save_opportunity_rule_state(self, principal_id: str, rule_id: str, state: Mapping[str, Any]) -> None:
        payload = self._read()
        bucket = self._mapping_bucket(payload, self.OPPORTUNITY_RULE_STATE_KEY)
        principal_key = _state_key(principal_id)
        principal_bucket = bucket.get(principal_key)
        if not isinstance(principal_bucket, dict):
            principal_bucket = {}
        rule_key = _state_key(rule_id)
        principal_bucket[rule_key] = dict(state)
        principal_bucket.pop(rule_id, None)
        bucket[principal_key] = principal_bucket
        bucket.pop(principal_id, None)
        payload[self.OPPORTUNITY_RULE_STATE_KEY] = bucket
        self._write(payload)

    def _mapping_bucket(self, payload: Mapping[str, Any], key: str) -> dict[str, Any]:
        bucket = payload.get(key)
        return bucket if isinstance(bucket, dict) else {}

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ProactiveOodaService:
    def __init__(
        self,
        *,
        notify: Callable[[str, str], object] | None = None,
        state_store: JsonOodaStateStore | None = None,
        max_items: int = 5,
    ):
        self._notify = notify
        self._state_store = state_store
        self._max_items = max(max_items, 1)

    def build_digest(
        self,
        *,
        principal_id: str,
        signals: Iterable[ProactiveSignal | Mapping[str, Any]],
        already_notified_refs: set[str] | None = None,
    ) -> ProactiveOodaDigest:
        persisted_seen = set(already_notified_refs or set())
        run_seen: set[str] = set()
        items: list[OodaInk] = []
        notified_markers: list[str] = []
        for raw_signal in signals:
            signal = raw_signal if isinstance(raw_signal, ProactiveSignal) else ProactiveSignal.from_mapping(raw_signal)
            signal_ref = signal.stable_ref()
            signal_marker = signal.dedupe_marker()
            marker_persists = _persist_dedupe_marker_across_runs(signal, signal_marker)
            if _marker_seen(signal_ref, persisted_seen) or _marker_seen(signal_ref, run_seen):
                continue
            if _marker_seen(signal_marker, run_seen):
                continue
            if marker_persists and _marker_seen(signal_marker, persisted_seen):
                continue
            ink = self._orient_signal(signal)
            if not ink.notify:
                continue
            items.append(ink)
            _remember_marker(signal_ref, seen=run_seen, emitted=notified_markers)
            _remember_marker(
                signal_marker,
                seen=run_seen,
                emitted=notified_markers if marker_persists else None,
            )
            if len(items) >= self._max_items:
                break
        return ProactiveOodaDigest(
            principal_id=principal_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            items=tuple(items),
            notified_refs=tuple(item.signal_ref for item in items),
            notified_markers=tuple(dict.fromkeys(marker for marker in notified_markers if marker)),
        )

    def run(
        self,
        *,
        principal_id: str,
        signals: Iterable[ProactiveSignal | Mapping[str, Any]],
        dry_run: bool = False,
        safe_work_results: Iterable[Mapping[str, Any]] = (),
    ) -> tuple[ProactiveOodaDigest, object | None]:
        stored_refs = self._state_store.load_notified_refs(principal_id) if self._state_store else set()
        digest = self.build_digest(principal_id=principal_id, signals=signals, already_notified_refs=stored_refs)
        notification_result: object | None = None
        if digest.items and self._notify and not dry_run:
            notification_result = self._notify(
                principal_id,
                format_telegram_digest(digest, safe_work_results=safe_work_results),
            )
        if digest.notified_markers and self._state_store and not dry_run:
            self._state_store.save_notified_refs(principal_id, stored_refs.union(digest.notified_markers))
        return digest, notification_result

    def _orient_signal(self, signal: ProactiveSignal) -> OodaInk:
        if _is_internal_source_health_signal(signal) and not _source_health_requires_user_action(signal):
            return _suppressed_source_health_ink(signal)
        structured = _structured_ooda_ink(signal)
        if structured is not None:
            return structured
        text = " ".join((signal.title, signal.summary, signal.counterparty, signal.due_at or "")).lower()
        high_urgency = any(term in text for term in HIGH_URGENCY_TERMS)
        raw_approval_required = any(term in text for term in APPROVAL_TERMS)
        has_due = bool(signal.due_at)
        low_signal_mail = _is_low_signal_mail(signal, text=text) or _is_low_signal_product_commitment_candidate(
            signal,
            text=text,
        )
        high_confidence_mail_action = _has_high_confidence_mail_action(text)
        approval_required = raw_approval_required and not (low_signal_mail and not high_confidence_mail_action)
        notify = _has_nonstructured_actionable_intent(
            signal,
            text=text,
            approval_required=approval_required,
            has_due=has_due,
        )
        if low_signal_mail and not (has_due or high_confidence_mail_action):
            notify = False
            approval_required = False
        priority = "high" if high_urgency or approval_required else "normal"
        if not notify:
            priority = "low"
        observe = _compact(signal.title or signal.summary, 180)
        orient = _build_orient(signal, priority=priority, approval_required=approval_required)
        decide = _build_decide(signal, approval_required=approval_required)
        act = _build_act(signal, approval_required=approval_required)
        evidence = tuple(
            part
            for part in (
                f"{signal.channel}:{signal.stable_ref()}",
                f"type:{signal.signal_type}" if signal.signal_type else "",
                f"counterparty:{signal.counterparty}" if signal.counterparty else "",
                f"due:{signal.due_at}" if signal.due_at else "",
            )
            if part
        )
        return OodaInk(
            signal_ref=signal.stable_ref(),
            priority=priority,
            observe=observe,
            orient=orient,
            decide=decide,
            act=act,
            evidence=evidence,
            approval_required=approval_required,
            ignored_consequence=_build_ignored_consequence(signal, approval_required=approval_required),
            notify=notify,
            external_action_policy=_default_external_action_policy(approval_required=approval_required),
        )


def _is_internal_source_health_signal(signal: ProactiveSignal) -> bool:
    signal_type = str(signal.signal_type or "").strip().lower()
    channel = str(signal.channel or "").strip().lower()
    source_ref = str(signal.source_ref or "").strip().lower()
    payload = signal.payload if isinstance(signal.payload, Mapping) else {}
    return bool(
        signal_type in SOURCE_HEALTH_SIGNAL_TYPES
        or (channel == "proactive_runtime" and source_ref.startswith("proactive_source_error:"))
        or isinstance(payload.get("source_health"), Mapping)
    )


def _source_health_requires_user_action(signal: ProactiveSignal) -> bool:
    payload = signal.payload if isinstance(signal.payload, Mapping) else {}
    health = payload.get("source_health") if isinstance(payload.get("source_health"), Mapping) else {}
    ooda_loop = payload.get("ooda_loop") if isinstance(payload.get("ooda_loop"), Mapping) else {}
    decide = ooda_loop.get("decide") if isinstance(ooda_loop.get("decide"), Mapping) else {}
    act = ooda_loop.get("act") if isinstance(ooda_loop.get("act"), Mapping) else {}
    return bool(
        payload.get("user_action_required") is True
        or dict(health).get("user_action_required") is True
        or dict(decide).get("user_action_required") is True
        or dict(act).get("user_action_required") is True
    )


def _suppressed_source_health_ink(signal: ProactiveSignal) -> OodaInk:
    return OodaInk(
        signal_ref=signal.stable_ref(),
        priority="low",
        observe=_compact(signal.title or signal.summary or "EA proactive source health changed.", 180),
        orient="Internal source-health telemetry is routed to operator status, not the user's OODA digest.",
        decide="",
        act="",
        evidence=tuple(
            part
            for part in (
                f"{signal.channel}:{signal.stable_ref()}",
                f"type:{signal.signal_type}" if signal.signal_type else "",
                "source_health:operator_telemetry",
            )
            if part
        ),
        approval_required=False,
        ignored_consequence="",
        notify=False,
        stage_kind="source_health",
        external_action_policy="Do not notify the user unless a source-health row explicitly requires user action.",
    )


def _structured_ooda_ink(signal: ProactiveSignal) -> OodaInk | None:
    payload = signal.payload if isinstance(signal.payload, Mapping) else {}
    ooda_loop = payload.get("ooda_loop") if isinstance(payload.get("ooda_loop"), Mapping) else None
    if not ooda_loop:
        return None

    observe_section = _structured_section(ooda_loop, "observe")
    orient_section = _structured_section(ooda_loop, "orient")
    decide_section = _structured_section(ooda_loop, "decide")
    act_section = _structured_section(ooda_loop, "act")

    observe = _compact(
        _first_structured_text(
            decide_section.get("summary"),
            observe_section.get("summary"),
            ooda_loop.get("summary"),
            signal.title,
            signal.summary,
        ),
        180,
    )
    orient = _sentence(
        _first_structured_text(
            orient_section.get("summary"),
            ooda_loop.get("summary"),
            signal.summary,
            _build_orient(signal, priority="normal", approval_required=False),
        )
    )
    recommended_actions = _string_list(decide_section.get("recommended_actions"))
    raw_act_summary = _first_structured_text(
        act_section.get("summary"),
        _first_list_item(recommended_actions),
    )
    approval_required = _structured_approval_required(signal, ooda_loop=ooda_loop, action_text=raw_act_summary)
    decision = _first_structured_text(
        decide_section.get("summary"),
        _first_list_item(recommended_actions),
        _build_decide(signal, approval_required=approval_required),
    )
    action = _first_structured_text(
        raw_act_summary,
        _build_act(signal, approval_required=approval_required),
    )
    action_plan = _string_list(act_section.get("action_plan")) or _string_list(decide_section.get("action_plan"))
    external_action_policy = _first_structured_text(
        act_section.get("external_action_policy"),
        act_section.get("guardrail"),
        decide_section.get("external_action_policy"),
        decide_section.get("guardrail"),
        _default_external_action_policy(approval_required=approval_required),
    )
    stage_section = act_section.get("stage") if isinstance(act_section.get("stage"), Mapping) else {}
    stage_kind = _first_structured_text(
        stage_section.get("kind"),
        stage_section.get("stage_kind"),
        stage_section.get("type"),
    )
    stage_summary = _first_structured_text(
        stage_section.get("summary"),
        stage_section.get("description"),
    )
    stage_artifacts = _string_list(stage_section.get("artifacts")) or _string_list(stage_section.get("expected_artifacts"))
    approval_gate = _first_structured_text(
        stage_section.get("approval_gate"),
        stage_section.get("external_action_policy"),
        stage_section.get("guardrail"),
        external_action_policy if stage_section else "",
    )
    stage_payload = _structured_stage_payload(
        stage_section,
        stage_kind=stage_kind,
        stage_summary=stage_summary,
        stage_artifacts=stage_artifacts,
        approval_gate=approval_gate,
    )
    combined_text = " ".join(
        (
            signal.title,
            signal.summary,
            observe,
            orient,
            decision,
            action,
            stage_kind,
            stage_summary,
            approval_gate,
            signal.due_at or "",
            " ".join(recommended_actions),
            " ".join(stage_artifacts),
        )
    ).lower()
    has_structured_action = bool(
        raw_act_summary
        or recommended_actions
        or _string_list(act_section.get("automated_actions"))
        or _string_list(act_section.get("executed_actions"))
        or _safe_positive_int(act_section.get("staged_candidate_count"))
        or _safe_positive_int(act_section.get("staged_draft_count"))
        or stage_kind
        or stage_summary
        or stage_artifacts
    )
    high_urgency = any(term in combined_text for term in HIGH_URGENCY_TERMS)
    notify = approval_required or has_structured_action or bool(signal.due_at) or any(
        term in combined_text for term in ACTION_TERMS
    )
    if _structured_stage_is_materialless_internal_review(
        signal,
        stage_payload=stage_payload,
        stage_kind=stage_kind,
        stage_summary=stage_summary,
        stage_artifacts=stage_artifacts,
        approval_gate=approval_gate,
        combined_text=combined_text,
    ):
        notify = False
    priority = "high" if high_urgency or approval_required else "normal"
    if not notify:
        priority = "low"

    return OodaInk(
        signal_ref=signal.stable_ref(),
        priority=priority,
        observe=observe,
        orient=orient,
        decide=_sentence(decision),
        act=_sentence(action),
        evidence=_structured_evidence(signal, ooda_loop=ooda_loop),
        approval_required=approval_required,
        ignored_consequence=_structured_ignored_consequence(signal, approval_required=approval_required),
        notify=notify,
        action_plan=action_plan[:4],
        stage_kind=stage_kind,
        stage_summary=stage_summary,
        stage_artifacts=stage_artifacts[:4],
        stage_payload=stage_payload,
        approval_gate=approval_gate,
        external_action_policy=external_action_policy,
    )


def format_telegram_digest(
    digest: ProactiveOodaDigest,
    *,
    safe_work_results: Iterable[Mapping[str, Any]] = (),
) -> str:
    if not digest.items:
        return ""
    safe_results = tuple(dict(row) for row in safe_work_results if isinstance(row, Mapping))
    needs_decision = any(
        item.approval_required
        and not _safe_work_fail_closed(safe_results[index])
        for index, item in enumerate(digest.items)
        if index < len(safe_results)
    ) or any(
        item.approval_required
        for index, item in enumerate(digest.items)
        if index >= len(safe_results)
    )
    has_blocked_safe_work = any(_safe_work_fail_closed(result) for result in safe_results)
    if needs_decision:
        header = "EA needs your decision"
    elif has_blocked_safe_work:
        header = "EA needs follow-up"
    else:
        header = "EA staged a next step"
    lines = [header]
    for index, item in enumerate(digest.items, start=1):
        lines.extend(
            (
                "",
                f"{index}. {item.observe}",
            )
        )
        if index - 1 < len(safe_results):
            lines.extend(_safe_work_preview_lines(safe_results[index - 1]))
        else:
            decision_label = "Please decide" if item.approval_required else "Suggested decision"
            if item.decide:
                lines.append(f"{decision_label}: {item.decide}")
            if item.act:
                lines.append(f"EA will: {item.act}")
        if item.orient:
            lines.append(f"Why now: {item.orient}")
        if item.stage_summary and index - 1 >= len(safe_results):
            lines.append(f"Ready: {item.stage_summary}")
        guardrail = item.approval_gate or item.external_action_policy
        if guardrail:
            lines.append(f"Guardrail: {guardrail}")
        if item.ignored_consequence:
            lines.append(f"If skipped: {item.ignored_consequence}")
        if item.evidence:
            receipt_count = len(item.evidence)
            suffix = "" if receipt_count == 1 else "s"
            lines.append(f"Receipts: {receipt_count} source receipt{suffix} recorded.")
    return "\n".join(lines).strip()


def _safe_work_preview_lines(result: Mapping[str, Any]) -> list[str]:
    summary = _compact(str(result.get("summary") or ""), 220)
    if _safe_work_fail_closed(result):
        return _safe_work_blocked_preview_lines(result, summary=summary)
    recommended = _recommended_preview(result.get("recommended_option_or_draft"))
    staged_action_url = _compact(str(result.get("staged_action_url") or ""), 180)
    shortlist = _shortlist_preview(result.get("shortlist"))
    prompt = _compact(str(result.get("approval_prompt") or ""), 220)
    lines: list[str] = []
    if summary:
        lines.append(f"Ready: {summary}")
    if recommended:
        lines.append(f"Recommendation: {recommended}")
    if staged_action_url:
        lines.append(f"Open: {staged_action_url}")
    if shortlist:
        lines.append(f"Options: {shortlist}")
    if prompt:
        lines.append(f"Please decide: {prompt}")
    return lines


def _safe_work_blocked_preview_lines(result: Mapping[str, Any], *, summary: str) -> list[str]:
    execution = result.get("execution_receipt") if isinstance(result.get("execution_receipt"), Mapping) else {}
    stop_condition = _compact(str(dict(execution).get("stop_condition") or ""), 80)
    issue_codes = _safe_work_issue_codes(result)
    prompt = _compact(str(result.get("approval_prompt") or ""), 220)
    status = str(result.get("status") or "").strip()
    browser_receipt = result.get("browser_action_receipt") if isinstance(result.get("browser_action_receipt"), Mapping) else {}
    user_action_required = bool(dict(browser_receipt).get("user_action_required"))
    lines: list[str] = []
    if status == "blocked_human_handoff_required" and user_action_required and prompt:
        lines.append(f"Action needed: {prompt}")
    else:
        lines.append(f"Blocked: {summary or 'Safe work did not pass the pre-user quality gate.'}")
    if issue_codes:
        lines.append(f"Needs work: {', '.join(issue_codes[:4])}")
    if stop_condition:
        lines.append(f"Stop: {stop_condition}")
    return lines


def _safe_work_fail_closed(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return False
    audit_receipt = result.get("audit_receipt") if isinstance(result.get("audit_receipt"), Mapping) else {}
    if bool(dict(audit_receipt).get("fail_closed")):
        return True
    quality_gate = result.get("quality_gate") if isinstance(result.get("quality_gate"), Mapping) else {}
    if str(dict(quality_gate).get("status") or "").strip().lower() == "review":
        return True
    execution = result.get("execution_receipt") if isinstance(result.get("execution_receipt"), Mapping) else {}
    if str(dict(execution).get("stop_condition") or "").strip().lower() == "quality_gate_failed":
        return True
    return False


def _safe_work_issue_codes(result: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for bucket_name in ("audit_receipt", "audit"):
        bucket = result.get(bucket_name) if isinstance(result.get(bucket_name), Mapping) else {}
        for issue in list(dict(bucket).get("issues") or []):
            if not isinstance(issue, Mapping):
                continue
            code = str(issue.get("code") or "").strip()
            if code:
                codes.append(code)
    return list(dict.fromkeys(codes))


def _recommended_preview(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _compact(str(value or ""), 180)
    kind = str(value.get("kind") or "result").replace("_", " ").strip()
    raw = value.get("value")
    if isinstance(raw, Mapping):
        label = _compact(str(raw.get("label") or raw.get("title") or ""), 80)
        url = _compact(str(raw.get("url") or raw.get("link") or raw.get("href") or ""), 120)
        title = _compact(str(raw.get("page_title") or ""), 80)
        parts = [part for part in (label, url, title) if part]
        detail = " - ".join(parts)
        if not detail:
            return kind
        if kind in {"result", "shortlist candidate"}:
            return detail
        return f"{kind}: {detail}"
    detail = _compact(str(raw or ""), 180)
    return f"{kind}: {detail}" if detail else kind


def _shortlist_preview(value: Any, *, limit: int = 2) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value[: max(int(limit or 1), 1)]:
        if not isinstance(item, Mapping):
            continue
        label = _compact(str(item.get("label") or item.get("title") or ""), 60) or "candidate"
        url = _compact(str(item.get("url") or item.get("link") or item.get("href") or ""), 100)
        reachability = ""
        if item.get("reachable") is True:
            reachability = "reachable"
        elif item.get("reachable") is False:
            reachability = "unreachable"
        page_title = _compact(str(item.get("page_title") or ""), 60)
        detail = ", ".join(part for part in (reachability, page_title) if part)
        candidate = f"{label} - {url}" if url else label
        if detail:
            candidate = f"{candidate} ({detail})"
        parts.append(candidate)
    return " | ".join(parts)


def digest_to_dict(digest: ProactiveOodaDigest) -> dict[str, Any]:
    return {
        "principal_id": digest.principal_id,
        "generated_at": digest.generated_at,
        "items": [asdict(item) for item in digest.items],
        "notified_refs": list(digest.notified_refs),
    }


def build_run_receipt(
    *,
    digest: ProactiveOodaDigest,
    dry_run: bool,
    notification_result: object | None = None,
    error_code: str = "",
    stage_packet_refs: Iterable[str] = (),
    stage_packet_error_count: int = 0,
    safe_work_result_refs: Iterable[str] = (),
    safe_work_result_error_count: int = 0,
    delivery_guard: Mapping[str, Any] | None = None,
) -> ProactiveOodaRunReceipt:
    status = "skipped_no_items"
    if dry_run:
        status = "dry_run"
    elif _is_deferred_error(error_code):
        status = "deferred"
    elif error_code:
        status = "failed"
    elif digest.items:
        status = "sent" if notification_result is not None else "not_sent"
    delivery_recovery = _resolve_delivery_recovery(notification_result, error_code=error_code)
    return ProactiveOodaRunReceipt(
        principal_id_hash=_hash_value(digest.principal_id),
        generated_at=digest.generated_at,
        dry_run=dry_run,
        item_count=len(digest.items),
        notified_ref_hashes=tuple(_hash_value(ref) for ref in digest.notified_refs),
        notification_status=status,
        telegram_message_ids=_extract_telegram_message_ids(notification_result),
        stage_packet_ref_hashes=tuple(_hash_value(ref) for ref in stage_packet_refs if str(ref).strip()),
        stage_packet_error_count=max(int(stage_packet_error_count or 0), 0),
        safe_work_result_ref_hashes=tuple(_hash_value(ref) for ref in safe_work_result_refs if str(ref).strip()),
        safe_work_result_error_count=max(int(safe_work_result_error_count or 0), 0),
        error_code=error_code,
        delivery_channel=_extract_delivery_channel(notification_result),
        delivery_transport=_extract_delivery_transport(notification_result),
        delivery_selected_by=_extract_delivery_selected_by(notification_result),
        delivery_recipient_hash=_extract_delivery_recipient_hash(notification_result),
        delivery_message_ids=_extract_delivery_message_ids(notification_result),
        delivery_outbox_id_hash=_extract_delivery_outbox_id_hash(notification_result),
        delivery_route_error=delivery_recovery["route_error"],
        delivery_recovery_hint=delivery_recovery["recovery_hint"],
        delivery_next_action=delivery_recovery["next_action"],
        approval_surface=_extract_approval_surface(notification_result),
        delivery_guard=dict(delivery_guard or {}) or None,
    )


def _is_deferred_error(value: str) -> bool:
    normalized = str(value or "").strip()
    return normalized.startswith("deferred_by_") or normalized in {
        "mirrored_delivery_proof",
        "no_decision_ready_safe_work",
        "no_user_action_required",
    }


def receipt_to_dict(receipt: ProactiveOodaRunReceipt) -> dict[str, Any]:
    return asdict(receipt)


def _extract_telegram_message_ids(notification_result: object | None) -> tuple[str, ...]:
    if notification_result is None:
        return ()
    if hasattr(notification_result, "telegram_message_ids"):
        return tuple(str(item) for item in getattr(notification_result, "telegram_message_ids") if str(item).strip())
    if hasattr(notification_result, "message_ids"):
        channel = _extract_delivery_channel(notification_result)
        return tuple(str(item) for item in getattr(notification_result, "message_ids") if str(item).strip()) if channel in {"", "telegram"} else ()
    if isinstance(notification_result, dict):
        channel = str(notification_result.get("channel") or notification_result.get("delivery_channel") or "").strip().lower()
        message_id = notification_result.get("message_id")
        if message_id is not None and channel in {"", "telegram"}:
            return (str(message_id),)
        if isinstance(notification_result.get("telegram_message_ids"), (list, tuple)):
            return tuple(str(item) for item in notification_result["telegram_message_ids"] if str(item).strip())
        if isinstance(notification_result.get("message_ids"), (list, tuple)) and channel in {"", "telegram"}:
            return tuple(str(item) for item in notification_result["message_ids"] if str(item).strip())
    return ()


def _extract_delivery_channel(notification_result: object | None) -> str:
    if notification_result is None:
        return ""
    if hasattr(notification_result, "channel"):
        return str(getattr(notification_result, "channel") or "").strip().lower()
    if isinstance(notification_result, dict):
        explicit = str(notification_result.get("channel") or notification_result.get("delivery_channel") or "").strip().lower()
        if explicit:
            return explicit
        if "message_id" in notification_result or "telegram_message_ids" in notification_result:
            return "telegram"
    if hasattr(notification_result, "chat_id") or hasattr(notification_result, "bot_key"):
        return "telegram"
    if hasattr(notification_result, "recipient") and hasattr(notification_result, "delivery_transport"):
        return "whatsapp"
    if hasattr(notification_result, "request_url"):
        return "whatsapp"
    return ""


def _extract_delivery_transport(notification_result: object | None) -> str:
    if notification_result is None:
        return ""
    if hasattr(notification_result, "delivery_transport"):
        return str(getattr(notification_result, "delivery_transport") or "").strip().lower()
    if isinstance(notification_result, dict):
        explicit = str(notification_result.get("delivery_transport") or "").strip().lower()
        if explicit:
            return explicit
    return _extract_delivery_channel(notification_result)


def _extract_delivery_selected_by(notification_result: object | None) -> str:
    if notification_result is None:
        return ""
    if hasattr(notification_result, "selected_by"):
        return str(getattr(notification_result, "selected_by") or "").strip().lower()
    if isinstance(notification_result, dict):
        return str(notification_result.get("selected_by") or "").strip().lower()
    return ""


def _extract_delivery_recipient_hash(notification_result: object | None) -> str:
    if notification_result is None:
        return ""
    if hasattr(notification_result, "recipient_ref_hash"):
        return str(getattr(notification_result, "recipient_ref_hash") or "").strip()
    if isinstance(notification_result, dict):
        return str(notification_result.get("recipient_ref_hash") or "").strip()
    return ""


def _extract_delivery_message_ids(notification_result: object | None) -> tuple[str, ...]:
    if notification_result is None:
        return ()
    if hasattr(notification_result, "message_ids"):
        return tuple(str(item) for item in getattr(notification_result, "message_ids") if str(item).strip())
    if isinstance(notification_result, dict):
        if isinstance(notification_result.get("delivery_message_ids"), (list, tuple)):
            return tuple(str(item) for item in notification_result["delivery_message_ids"] if str(item).strip())
        if isinstance(notification_result.get("message_ids"), (list, tuple)):
            return tuple(str(item) for item in notification_result["message_ids"] if str(item).strip())
        message_id = notification_result.get("message_id") or notification_result.get("id")
        if message_id is not None and str(message_id).strip():
            return (str(message_id),)
    return ()


def _extract_delivery_outbox_id_hash(notification_result: object | None) -> str:
    if notification_result is None:
        return ""
    if hasattr(notification_result, "outbox_delivery_id"):
        value = str(getattr(notification_result, "outbox_delivery_id") or "").strip()
        return _hash_value(value) if value else ""
    if isinstance(notification_result, dict):
        value = str(notification_result.get("outbox_delivery_id") or "").strip()
        return _hash_value(value) if value else ""
    return ""


def _extract_approval_surface(notification_result: object | None) -> dict[str, Any] | None:
    if notification_result is None:
        return None
    raw: Mapping[str, Any] | None = None
    if hasattr(notification_result, "approval_surface"):
        candidate = getattr(notification_result, "approval_surface")
        raw = candidate if isinstance(candidate, Mapping) else None
    elif isinstance(notification_result, dict):
        candidate = notification_result.get("approval_surface")
        raw = candidate if isinstance(candidate, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    message_ids = tuple(
        str(item or "").strip()
        for item in list(raw.get("message_ids") or [])
        if str(item or "").strip()
    )
    privacy = dict(raw.get("privacy") or {})
    normalized = {
        "present": bool(raw.get("present")),
        "channel": str(raw.get("channel") or "").strip().lower(),
        "status": str(raw.get("status") or "").strip().lower(),
        "callback_token_sha256": str(raw.get("callback_token_sha256") or "").strip(),
        "expires_at": str(raw.get("expires_at") or "").strip(),
        "packet_ref_sha256": str(raw.get("packet_ref_sha256") or "").strip(),
        "staged_artifact_sha256": str(raw.get("staged_artifact_sha256") or "").strip(),
        "approval_prompt_sha256": str(raw.get("approval_prompt_sha256") or "").strip(),
        "staged_action_url_sha256": str(raw.get("staged_action_url_sha256") or "").strip(),
        "inline_button_count": max(int(raw.get("inline_button_count") or 0), 0),
        "url_button_count": max(int(raw.get("url_button_count") or 0), 0),
        "message_ids": message_ids,
        "message_count": len(message_ids),
        "delivery_error_code": str(raw.get("delivery_error_code") or "").strip(),
        "privacy": {
            "raw_callback_token_stored": bool(privacy.get("raw_callback_token_stored")),
            "raw_packet_ref_stored": bool(privacy.get("raw_packet_ref_stored")),
            "raw_staged_artifact_ref_stored": bool(privacy.get("raw_staged_artifact_ref_stored")),
            "raw_approval_prompt_stored": bool(privacy.get("raw_approval_prompt_stored")),
            "raw_staged_action_url_stored": bool(privacy.get("raw_staged_action_url_stored")),
        },
    }
    return normalized if any(normalized.values()) else None


def _resolve_delivery_recovery(notification_result: object | None, *, error_code: str) -> dict[str, str]:
    route_error = ""
    recovery_hint = ""
    next_action = ""
    if notification_result is not None:
        if hasattr(notification_result, "route_error"):
            route_error = str(getattr(notification_result, "route_error") or "").strip()
            recovery_hint = str(getattr(notification_result, "recovery_hint") or "").strip()
            next_action = str(getattr(notification_result, "next_action") or "").strip()
        elif isinstance(notification_result, dict):
            route_error = str(notification_result.get("route_error") or "").strip()
            recovery_hint = str(notification_result.get("recovery_hint") or "").strip()
            next_action = str(notification_result.get("next_action") or "").strip()
    guidance_code = route_error or ("" if _is_deferred_error(error_code) else str(error_code or "").strip())
    if guidance_code and (not route_error or not recovery_hint or not next_action):
        from app.services.proactive_ooda_delivery import proactive_ooda_delivery_recovery

        guidance = proactive_ooda_delivery_recovery(guidance_code, ready=False)
        route_error = route_error or guidance.route_error
        recovery_hint = recovery_hint or guidance.recovery_hint
        next_action = next_action or guidance.next_action
    return {
        "route_error": route_error,
        "recovery_hint": recovery_hint,
        "next_action": next_action,
    }


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _state_key(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized.lower()):
        return normalized.lower()
    return _hash_value(normalized)


def _marker_seen(marker: str, seen: set[str]) -> bool:
    normalized = str(marker or "").strip()
    if not normalized:
        return False
    return any(candidate in seen for candidate in _marker_variants(normalized))


def _remember_marker(marker: str, *, seen: set[str], emitted: list[str] | None) -> None:
    normalized = str(marker or "").strip()
    if not normalized:
        return
    if emitted is not None:
        emitted.append(normalized)
    seen.update(_marker_variants(normalized))


def _marker_variants(marker: str) -> tuple[str, str]:
    normalized = str(marker or "").strip()
    return normalized, _state_key(normalized)


def _persist_dedupe_marker_across_runs(signal: ProactiveSignal, marker: str) -> bool:
    normalized_marker = str(marker or "").strip()
    if not normalized_marker:
        return False
    if not normalized_marker.startswith("external_id:"):
        return True
    source_ref = str(signal.source_ref or "").strip().lower()
    if source_ref.startswith("observation:"):
        return False
    return True


def _has_nonstructured_actionable_intent(
    signal: ProactiveSignal,
    *,
    text: str,
    approval_required: bool,
    has_due: bool,
) -> bool:
    if approval_required or has_due:
        return True
    if _is_low_signal_status_question(signal, text=text):
        return False
    if _contains_any(text, DIRECT_REQUEST_TERMS):
        return True
    if _contains_any(text, STRONG_ACTION_TERMS):
        return True
    if "review" in text and _contains_any(text, REVIEW_CONTEXT_TERMS):
        return True
    if _contains_any(text, HIGH_URGENCY_TERMS) and _contains_any(text, OPERATIONAL_RISK_TERMS):
        return True
    payload = signal.payload if isinstance(signal.payload, Mapping) else {}
    if payload.get("attachments") and _contains_any(text, ("invoice", "contract", "proposal", "quote", "angebot")):
        return True
    return False


def _is_low_signal_mail(signal: ProactiveSignal, *, text: str) -> bool:
    if str(signal.channel or "").strip().lower() != "gmail":
        return False
    payload = signal.payload if isinstance(signal.payload, Mapping) else {}
    labels = {str(item or "").strip().upper() for item in list(payload.get("labels") or []) if str(item or "").strip()}
    if labels.intersection(LOW_SIGNAL_GMAIL_LABELS):
        return True
    if str(payload.get("list_unsubscribe") or "").strip():
        return True
    if str(payload.get("auto_submitted") or "").strip():
        return True
    if str(payload.get("precedence") or "").strip().lower() in {"bulk", "junk", "list"}:
        return True
    return _contains_any(text, LOW_SIGNAL_MAIL_TERMS)


def _is_low_signal_status_question(signal: ProactiveSignal, *, text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip().lower()
    if not normalized:
        return False
    if _contains_any(normalized, LOW_SIGNAL_STATUS_QUESTION_TERMS):
        return True
    if not normalized.endswith("?"):
        return False
    signal_type = str(signal.signal_type or "").strip().lower()
    if signal_type not in {"pocket_transcript", "alexa_transcript", "telegram_message", "whatsapp_message"}:
        return False
    return normalized.startswith(("what did ", "did you ", "any update", "was hast ", "gibt es"))


def _is_low_signal_product_commitment_candidate(signal: ProactiveSignal, *, text: str) -> bool:
    if str(signal.channel or "").strip().lower() != "product":
        return False
    if str(signal.signal_type or "").strip().lower() != "commitment_candidate":
        return False
    return _contains_any(text, LOW_SIGNAL_MAIL_TERMS)


def _has_high_confidence_mail_action(text: str) -> bool:
    return _contains_any(text, HIGH_CONFIDENCE_MAIL_ACTION_TERMS) or _contains_any(text, DIRECT_REQUEST_TERMS)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    normalized = str(text or "").lower()
    for term in terms:
        normalized_term = str(term or "").strip().lower()
        if not normalized_term:
            continue
        if " " in normalized_term:
            if normalized_term in normalized:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized):
            return True
    return False


def _build_orient(signal: ProactiveSignal, *, priority: str, approval_required: bool) -> str:
    pieces = []
    if signal.counterparty:
        pieces.append(f"{signal.counterparty} is involved")
    if signal.due_at:
        pieces.append(f"there is a dated commitment at {signal.due_at}")
    pieces.append("this looks like an approval/commitment item" if approval_required else "this looks actionable")
    pieces.append(f"priority is {priority}")
    return "; ".join(pieces) + "."


def _build_decide(signal: ProactiveSignal, *, approval_required: bool) -> str:
    if approval_required:
        return "Put this in front of the user before any external action."
    if signal.due_at:
        return "Prepare the next step and keep the dated item on the user's radar."
    if "meeting" in f"{signal.title} {signal.summary}".lower():
        return "Extract the meeting intent and surface the next useful preparation step."
    return "Surface the smallest useful next step."


def _build_act(signal: ProactiveSignal, *, approval_required: bool) -> str:
    if approval_required:
        return "Ask for approval or a yes/no decision with the evidence attached."
    if signal.channel == "calendar":
        return "Send a short prep note or reminder."
    if signal.channel == "gmail":
        return "Draft a concise reply or follow-up, but do not send without instruction."
    return "Create a concise follow-up prompt for the user."


def _default_external_action_policy(*, approval_required: bool) -> str:
    if approval_required:
        return "Ask before any external send, purchase, booking, cancellation, or commitment."
    return "Prepare or draft only; require explicit approval for irreversible external action."


def _build_ignored_consequence(signal: ProactiveSignal, *, approval_required: bool) -> str:
    if approval_required:
        return "A decision may stall or money/legal commitments may move without a clear owner."
    if signal.due_at:
        return "The dated commitment may be missed."
    if signal.channel == "calendar":
        return "The user may enter the meeting without the relevant context."
    return "The thread may drift until it becomes urgent."


def _structured_section(ooda_loop: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = ooda_loop.get(name)
    return section if isinstance(section, Mapping) else {}


def _structured_stage_payload(
    stage_section: Mapping[str, Any],
    *,
    stage_kind: str,
    stage_summary: str,
    stage_artifacts: tuple[str, ...],
    approval_gate: str,
) -> Mapping[str, Any] | None:
    if not stage_section and not any((stage_kind, stage_summary, stage_artifacts, approval_gate)):
        return None
    payload: dict[str, Any] = {
        "kind": stage_kind,
        "summary": stage_summary,
        "artifacts": list(stage_artifacts),
        "approval_gate": approval_gate,
    }
    for key in (
        "status",
        "candidate_items",
        "candidates",
        "links",
        "draft",
        "draft_text",
        "draft_mode",
        "request",
        "request_text",
        "user_request",
        "task_request",
        "draft_request_text",
        "cart_url",
        "approval_url",
        "booking_options",
        "worker_hint",
        "adapter_hint",
        "constraints",
        "evidence_refs",
        "work_type",
        "safe_work_type",
        "task_type",
        "worker_task",
        "worker_status",
        "work_status",
        "research_query",
        "search_queries",
        "target_sites",
        "browser_task",
        "browser_action",
        "requires_browser_action",
        "requires_login",
        "browser_execution",
        "browser_blocker",
        "browser_operations",
        "browser_operations_attempted",
        "browser_login_url",
        "login_url",
        "site_url",
        "target_url",
        "credential_ref",
        "credential_id",
        "login_email",
        "browseract_username",
        "expected_account",
        "expected_account_email",
        "verify_account_context",
        "selection_criteria",
        "comparison_dimensions",
        "budget",
        "deadline",
        "delivery_window",
        "recipient_context",
        "recipient_email",
        "recipient",
        "delivery_recipient_email",
        "counterparty_email",
        "expected_counterparty_type",
        "expected_profession",
        "expected_vendor_type",
        "contact_channel_required",
        "final_surface_required",
        "source_relevance_requirements",
        "audit_requirements",
        "known_bad_source_patterns",
        "required_location",
        "geography_context",
        "stored_location_context",
        "required_locale",
        "account_ref",
        "account_identity",
        "site",
        "site_host",
        "locale",
        "currency",
        "quantity",
        "preferences",
        "requirements",
        "exclusions",
        "notes",
        "subject",
        "subject_hint",
        "post_approval_action",
        "auto_execute_action",
        "approved_action",
        "gmail_thread_id",
        "thread_id",
        "gmail_in_reply_to",
        "in_reply_to",
        "gmail_references",
        "references",
        "google_binding_id",
        "google_account_email",
        "account_email",
        "action_label",
        "action_url",
        "action_method",
        "approval_prompt",
    ):
        if key in stage_section:
            payload[key] = (
                _json_safe_without_browser_secrets(stage_section.get(key))
                if key in {"browser_task", "browser_action", "browser_execution"}
                else _json_safe(stage_section.get(key))
            )
    return payload


def _structured_stage_is_materialless_internal_review(
    signal: ProactiveSignal,
    *,
    stage_payload: Mapping[str, Any] | None,
    stage_kind: str,
    stage_summary: str,
    stage_artifacts: tuple[str, ...],
    approval_gate: str,
    combined_text: str,
) -> bool:
    if _structured_stage_has_decision_ready_material(stage_payload):
        return False
    has_stage_surface = any((stage_kind, stage_summary, stage_artifacts, approval_gate))
    has_bookkeeping_marker = any(marker in combined_text for marker in STRUCTURED_BOOKKEEPING_MARKERS)
    if not has_stage_surface and not has_bookkeeping_marker:
        return False
    channel = str(signal.channel or "").strip().lower()
    signal_type = str(signal.signal_type or "").strip().lower()
    if channel == "product" or signal_type in {"office_signal", "commitment_candidate"}:
        return True
    return has_bookkeeping_marker


def _structured_stage_has_decision_ready_material(stage_payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(stage_payload, Mapping):
        return False
    for key in STRUCTURED_STAGE_MATERIAL_KEYS:
        if key in stage_payload and _nonempty_stage_material(stage_payload.get(key)):
            return True
    return False


def _nonempty_stage_material(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_nonempty_stage_material(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_nonempty_stage_material(item) for item in value)
    return bool(str(value).strip())


def _first_structured_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            value = _first_list_item(_string_list(value))
        normalized = _compact(str(value or ""), 260)
        if normalized:
            return normalized
    return ""


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_compact(str(item or ""), 220) for item in value if str(item or "").strip())


def _first_list_item(values: Iterable[str]) -> str:
    for value in values:
        normalized = _compact(value, 220)
        if normalized:
            return normalized
    return ""


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    return str(value)


def _json_safe_without_browser_secrets(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(marker in lowered for marker in ("password", "token", "secret", "cookie", "session")):
                safe[f"{key_text}_present"] = bool(str(item or "").strip())
                continue
            safe[key_text] = _json_safe_without_browser_secrets(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [_json_safe_without_browser_secrets(item, depth=depth + 1) for item in value]
    return str(value)


def _structured_approval_required(signal: ProactiveSignal, *, ooda_loop: Mapping[str, Any], action_text: str) -> bool:
    for section_name in ("decide", "act", "orient", "ltd_review"):
        section = _structured_section(ooda_loop, section_name)
        for key in ("approval_required", "requires_approval", "needs_approval", "human_approval_required"):
            if key in section:
                return _truthy(section.get(key))
    text = " ".join((signal.title, signal.summary, action_text, signal.counterparty)).lower()
    return any(term in text for term in APPROVAL_TERMS)


def _structured_evidence(signal: ProactiveSignal, *, ooda_loop: Mapping[str, Any]) -> tuple[str, ...]:
    observe = _structured_section(ooda_loop, "observe")
    orient = _structured_section(ooda_loop, "orient")
    tags = _string_list(orient.get("tags"))
    evidence = [
        f"{signal.channel}:{signal.stable_ref()}",
        f"type:{signal.signal_type}" if signal.signal_type else "",
        f"counterparty:{signal.counterparty}" if signal.counterparty else "",
        f"due:{signal.due_at}" if signal.due_at else "",
        "ooda:reviewed" if _truthy(ooda_loop.get("reviewed")) else "",
        f"observed-channel:{observe.get('channel')}" if observe.get("channel") else "",
    ]
    evidence.extend(f"tag:{tag}" for tag in tags[:3])
    return tuple(item for item in evidence if item)


def _structured_ignored_consequence(signal: ProactiveSignal, *, approval_required: bool) -> str:
    payload = signal.payload if isinstance(signal.payload, Mapping) else {}
    ooda_loop = payload.get("ooda_loop") if isinstance(payload.get("ooda_loop"), Mapping) else {}
    for section_name in ("decide", "act", "orient"):
        section = _structured_section(ooda_loop, section_name)
        consequence = _first_structured_text(
            section.get("ignored_consequence"),
            section.get("risk_if_ignored"),
            section.get("consequence"),
        )
        if consequence:
            return _sentence(consequence)
    return _build_ignored_consequence(signal, approval_required=approval_required)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "required", "needed"}


def _safe_positive_int(value: Any) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _sentence(value: str) -> str:
    normalized = _compact(value, 260)
    if not normalized:
        return ""
    return normalized if normalized.endswith((".", "!", "?")) else f"{normalized}."


def _compact(value: str, limit: int) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
