from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


ACTION_TERMS = (
    "action required",
    "approval",
    "approve",
    "asap",
    "blocked",
    "blocking",
    "budget",
    "cancel",
    "contract",
    "deadline",
    "decide",
    "decision",
    "due",
    "escalat",
    "follow up",
    "invoice",
    "launch",
    "legal",
    "meeting",
    "overdue",
    "pay",
    "proposal",
    "reply",
    "review",
    "risk",
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


@dataclass(frozen=True)
class ProactiveOodaDigest:
    principal_id: str
    generated_at: str
    items: tuple[OodaInk, ...]
    notified_refs: tuple[str, ...]


@dataclass(frozen=True)
class ProactiveOodaRunReceipt:
    principal_id_hash: str
    generated_at: str
    dry_run: bool
    item_count: int
    notified_ref_hashes: tuple[str, ...]
    notification_status: str
    telegram_message_ids: tuple[str, ...]
    error_code: str = ""


class JsonOodaStateStore:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


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
        seen = set(already_notified_refs or set())
        items: list[OodaInk] = []
        for raw_signal in signals:
            signal = raw_signal if isinstance(raw_signal, ProactiveSignal) else ProactiveSignal.from_mapping(raw_signal)
            signal_ref = signal.stable_ref()
            if signal_ref in seen or _state_key(signal_ref) in seen:
                continue
            ink = self._orient_signal(signal)
            if not ink.notify:
                continue
            items.append(ink)
            seen.add(signal_ref)
            if len(items) >= self._max_items:
                break
        return ProactiveOodaDigest(
            principal_id=principal_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            items=tuple(items),
            notified_refs=tuple(item.signal_ref for item in items),
        )

    def run(
        self,
        *,
        principal_id: str,
        signals: Iterable[ProactiveSignal | Mapping[str, Any]],
        dry_run: bool = False,
    ) -> tuple[ProactiveOodaDigest, object | None]:
        stored_refs = self._state_store.load_notified_refs(principal_id) if self._state_store else set()
        digest = self.build_digest(principal_id=principal_id, signals=signals, already_notified_refs=stored_refs)
        notification_result: object | None = None
        if digest.items and self._notify and not dry_run:
            notification_result = self._notify(principal_id, format_telegram_digest(digest))
        if digest.notified_refs and self._state_store and not dry_run:
            self._state_store.save_notified_refs(principal_id, stored_refs.union(digest.notified_refs))
        return digest, notification_result

    def _orient_signal(self, signal: ProactiveSignal) -> OodaInk:
        structured = _structured_ooda_ink(signal)
        if structured is not None:
            return structured
        text = " ".join((signal.title, signal.summary, signal.counterparty, signal.due_at or "")).lower()
        action_score = sum(1 for term in ACTION_TERMS if term in text)
        high_urgency = any(term in text for term in HIGH_URGENCY_TERMS)
        approval_required = any(term in text for term in APPROVAL_TERMS)
        has_due = bool(signal.due_at)
        notify = action_score > 0 or has_due
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
    combined_text = " ".join(
        (
            signal.title,
            signal.summary,
            observe,
            orient,
            decision,
            action,
            signal.due_at or "",
            " ".join(recommended_actions),
        )
    ).lower()
    has_structured_action = bool(
        raw_act_summary
        or recommended_actions
        or _string_list(act_section.get("automated_actions"))
        or _string_list(act_section.get("executed_actions"))
        or _safe_positive_int(act_section.get("staged_candidate_count"))
        or _safe_positive_int(act_section.get("staged_draft_count"))
    )
    high_urgency = any(term in combined_text for term in HIGH_URGENCY_TERMS)
    notify = approval_required or has_structured_action or bool(signal.due_at) or any(
        term in combined_text for term in ACTION_TERMS
    )
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
    )


def format_telegram_digest(digest: ProactiveOodaDigest) -> str:
    if not digest.items:
        return ""
    lines = ["EA OODA"]
    for index, item in enumerate(digest.items, start=1):
        approval = "approval needed" if item.approval_required else "no approval needed"
        lines.extend(
            (
                "",
                f"{index}. {item.observe}",
                f"Priority: {item.priority}; {approval}",
                f"Why: {item.orient}",
                f"Decision: {item.decide}",
                f"Action: {item.act}",
                f"If ignored: {item.ignored_consequence}",
                f"Evidence: {', '.join(item.evidence)}",
            )
        )
    return "\n".join(lines).strip()


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
) -> ProactiveOodaRunReceipt:
    status = "skipped_no_items"
    if dry_run:
        status = "dry_run"
    elif error_code:
        status = "failed"
    elif digest.items:
        status = "sent" if notification_result is not None else "not_sent"
    return ProactiveOodaRunReceipt(
        principal_id_hash=_hash_value(digest.principal_id),
        generated_at=digest.generated_at,
        dry_run=dry_run,
        item_count=len(digest.items),
        notified_ref_hashes=tuple(_hash_value(ref) for ref in digest.notified_refs),
        notification_status=status,
        telegram_message_ids=_extract_telegram_message_ids(notification_result),
        error_code=error_code,
    )


def receipt_to_dict(receipt: ProactiveOodaRunReceipt) -> dict[str, Any]:
    return asdict(receipt)


def _extract_telegram_message_ids(notification_result: object | None) -> tuple[str, ...]:
    if notification_result is None:
        return ()
    if hasattr(notification_result, "message_ids"):
        return tuple(str(item) for item in getattr(notification_result, "message_ids") if str(item).strip())
    if isinstance(notification_result, dict):
        message_id = notification_result.get("message_id")
        if message_id is not None:
            return (str(message_id),)
        if isinstance(notification_result.get("message_ids"), (list, tuple)):
            return tuple(str(item) for item in notification_result["message_ids"] if str(item).strip())
    return ()


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _state_key(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized.lower()):
        return normalized.lower()
    return _hash_value(normalized)


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
