from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.services.proactive_ooda_service import OodaInk, ProactiveOodaDigest


STAGE_PACKET_SCHEMA = "proactive_ooda.stage_packet.v1"
SAFE_WORK_ORDER_SCHEMA = "proactive_ooda.safe_work_order.v1"

ALLOWED_BEFORE_APPROVAL = (
    "research",
    "compare_options",
    "draft",
    "prepare_shortlist",
    "prepare_cart_or_link",
    "prepare_booking_candidate",
)
FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL = (
    "purchase",
    "book",
    "cancel",
    "send_external_message",
    "post",
    "commit",
)


@dataclass(frozen=True)
class StagePacketWriteResult:
    paths: tuple[str, ...]
    packet_refs: tuple[str, ...]
    errors: tuple[str, ...] = ()


def default_stage_packet_dir(*, root: Path, state_path: str | Path) -> Path:
    path = Path(state_path)
    if not path.is_absolute():
        path = root / path
    return path.parent / "proactive_ooda_stage_packets"


def build_stage_packets(digest: ProactiveOodaDigest) -> tuple[dict[str, Any], ...]:
    return tuple(_stage_packet(digest, item=item, index=index) for index, item in enumerate(digest.items, start=1))


def persist_stage_packets(*, digest: ProactiveOodaDigest, output_dir: str | Path) -> StagePacketWriteResult:
    packets = build_stage_packets(digest)
    if not packets:
        return StagePacketWriteResult(paths=(), packet_refs=())
    target = Path(output_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return StagePacketWriteResult(paths=(), packet_refs=(), errors=(f"stage_packet_dir:{exc.__class__.__name__}",))
    paths: list[str] = []
    refs: list[str] = []
    errors: list[str] = []
    for packet in packets:
        packet_ref = str(packet.get("packet_ref") or "")
        try:
            path = target / f"{packet['packet_id']}.json"
            path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths.append(str(path))
            refs.append(packet_ref)
        except Exception as exc:
            errors.append(f"{packet_ref}:{exc.__class__.__name__}")
    return StagePacketWriteResult(paths=tuple(paths), packet_refs=tuple(refs), errors=tuple(errors))


def _stage_packet(digest: ProactiveOodaDigest, *, item: OodaInk, index: int) -> dict[str, Any]:
    packet_id = _packet_id(digest=digest, item=item, index=index)
    stage_payload = dict(item.stage_payload or {})
    stage_kind = item.stage_kind or str(stage_payload.get("kind") or "").strip() or _default_stage_kind(item)
    stage_summary = item.stage_summary or str(stage_payload.get("summary") or "").strip() or item.act
    stage_artifacts = tuple(item.stage_artifacts) or _string_tuple(stage_payload.get("artifacts"))
    approval_gate = item.approval_gate or str(stage_payload.get("approval_gate") or "").strip() or item.external_action_policy
    safe_work_order = _safe_work_order(
        packet_id=packet_id,
        item=item,
        stage_kind=stage_kind,
        stage_summary=stage_summary,
        stage_artifacts=stage_artifacts,
        stage_payload=stage_payload,
        approval_gate=approval_gate,
    )
    return {
        "schema": STAGE_PACKET_SCHEMA,
        "packet_id": packet_id,
        "packet_ref": f"stage_packet:{packet_id}",
        "status": "staged",
        "generated_at": digest.generated_at,
        "principal_id_hash": _hash_value(digest.principal_id),
        "signal_ref_hash": _hash_value(item.signal_ref),
        "item_index": index,
        "priority": item.priority,
        "observe": item.observe,
        "orient": item.orient,
        "decide": item.decide,
        "act": item.act,
        "action_plan": list(item.action_plan),
        "stage": {
            "kind": stage_kind,
            "summary": stage_summary,
            "artifacts": list(stage_artifacts),
            "payload": _json_safe(stage_payload),
        },
        "safe_work_order": safe_work_order,
        "approval": {
            "required": bool(item.approval_required),
            "gate": approval_gate,
            "external_action_policy": item.external_action_policy,
            "irreversible_actions_require_explicit_approval": True,
        },
        "ignored_consequence": item.ignored_consequence,
        "evidence_count": len(item.evidence),
        "evidence_hashes": [_hash_value(value) for value in item.evidence],
        "execution_policy": {
            "allowed_before_approval": list(ALLOWED_BEFORE_APPROVAL),
            "forbidden_without_explicit_approval": list(FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL),
        },
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_signal_ref_stored": False,
            "raw_evidence_refs_stored": False,
        },
    }


def _safe_work_order(
    *,
    packet_id: str,
    item: OodaInk,
    stage_kind: str,
    stage_summary: str,
    stage_artifacts: tuple[str, ...],
    stage_payload: Mapping[str, Any],
    approval_gate: str,
) -> dict[str, Any]:
    work_type = _work_type(stage_payload=stage_payload, stage_kind=stage_kind, stage_summary=stage_summary, item=item)
    return {
        "schema": SAFE_WORK_ORDER_SCHEMA,
        "work_order_id": f"safe_work:{packet_id}",
        "status": _worker_status(stage_payload),
        "work_type": work_type,
        "requested_outcome": stage_summary or item.act,
        "primary_allowed_operation": work_type,
        "allowed_operations": list(ALLOWED_BEFORE_APPROVAL),
        "forbidden_without_explicit_approval": list(FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL),
        "approval_gate": approval_gate,
        "tool_hints": _tool_hints(stage_payload),
        "input_contract": _work_input_contract(stage_payload=stage_payload, stage_artifacts=stage_artifacts),
        "output_contract": {
            "return_status": "staged_for_user_decision",
            "must_include": [
                "summary",
                "recommended_option_or_draft",
                "evidence_refs",
                "risks_or_tradeoffs",
                "approval_prompt",
            ],
            "may_include": [
                "shortlist",
                "reversible_cart_or_link",
                "booking_candidate",
                "draft_text",
                "comparison_table",
            ],
            "must_not_include": [
                "completed_purchase",
                "completed_booking",
                "sent_external_message",
                "committed_cancellation",
            ],
        },
        "handoff_policy": {
            "human_approval_required_before_irreversible_action": True,
            "safe_to_execute_before_approval": True,
            "external_actions_remain_staged_only": True,
        },
    }


def _work_type(*, stage_payload: Mapping[str, Any], stage_kind: str, stage_summary: str, item: OodaInk) -> str:
    explicit = _normalized_work_type(
        stage_payload.get("work_type")
        or stage_payload.get("safe_work_type")
        or stage_payload.get("task_type")
        or stage_payload.get("worker_task")
    )
    if explicit:
        return explicit
    kind = _normalized_work_type(stage_kind)
    if kind:
        return kind
    if stage_payload.get("booking_options"):
        return "prepare_booking_candidate"
    if stage_payload.get("cart_url"):
        return "prepare_cart_or_link"
    if stage_payload.get("draft") or stage_payload.get("draft_text"):
        return "draft"
    if stage_payload.get("candidate_items") or stage_payload.get("candidates"):
        return "compare_options"
    combined = f"{stage_summary} {item.act} {' '.join(item.action_plan)}".lower()
    if "booking" in combined or "reservation" in combined:
        return "prepare_booking_candidate"
    if "cart" in combined or "basket" in combined or "checkout" in combined:
        return "prepare_cart_or_link"
    if "draft" in combined or "reply" in combined:
        return "draft"
    if "shortlist" in combined:
        return "prepare_shortlist"
    if "compare" in combined or "option" in combined:
        return "compare_options"
    return "research"


def _normalized_work_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "research": "research",
        "browse": "research",
        "browser_research": "research",
        "compare": "compare_options",
        "comparison": "compare_options",
        "compare_options": "compare_options",
        "shortlist": "prepare_shortlist",
        "prepare_shortlist": "prepare_shortlist",
        "draft": "draft",
        "draft_reply": "draft",
        "message_draft": "draft",
        "prepare_draft": "draft",
        "cart": "prepare_cart_or_link",
        "basket": "prepare_cart_or_link",
        "cart_draft": "prepare_cart_or_link",
        "shopping": "prepare_cart_or_link",
        "prepare_cart": "prepare_cart_or_link",
        "prepare_cart_or_link": "prepare_cart_or_link",
        "booking": "prepare_booking_candidate",
        "booking_candidate": "prepare_booking_candidate",
        "reservation": "prepare_booking_candidate",
        "prepare_booking": "prepare_booking_candidate",
        "prepare_booking_candidate": "prepare_booking_candidate",
    }
    return aliases.get(normalized, "")


def _worker_status(stage_payload: Mapping[str, Any]) -> str:
    normalized = str(stage_payload.get("worker_status") or stage_payload.get("work_status") or "queued").strip().lower()
    return normalized if normalized in {"queued", "ready", "in_progress", "blocked", "done"} else "queued"


def _tool_hints(stage_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "worker_hint": str(stage_payload.get("worker_hint") or "").strip(),
        "adapter_hint": str(stage_payload.get("adapter_hint") or "").strip(),
    }


def _work_input_contract(*, stage_payload: Mapping[str, Any], stage_artifacts: tuple[str, ...]) -> dict[str, Any]:
    keys = (
        "research_query",
        "search_queries",
        "target_sites",
        "links",
        "candidate_items",
        "candidates",
        "booking_options",
        "draft_mode",
        "request",
        "request_text",
        "user_request",
        "task_request",
        "draft_request_text",
        "draft_text",
        "draft",
        "constraints",
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
    )
    inputs = {key: _json_safe(stage_payload.get(key)) for key in keys if key in stage_payload}
    inputs["expected_artifacts"] = list(stage_artifacts)
    inputs["private_payload_available"] = bool(inputs)
    return inputs


def _packet_id(*, digest: ProactiveOodaDigest, item: OodaInk, index: int) -> str:
    # Keep deferred retries stable so quiet-hours/pause loops refresh in place.
    material = "|".join((digest.principal_id, item.signal_ref))
    return f"proactive-ooda-stage-{_hash_value(material)[:24]}"


def _default_stage_kind(item: OodaInk) -> str:
    if item.approval_required:
        return "approval_packet"
    if item.action_plan:
        return "research_packet"
    return "decision_packet"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


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


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
