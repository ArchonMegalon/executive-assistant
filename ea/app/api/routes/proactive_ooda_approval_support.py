from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.api.routes.landing_object_support import _object_detail_row
from app.services.proactive_ooda_runtime_artifacts import current_packet_user_approval_surface


_APPROVAL_CAPTURE_PATH = "/admin/proactive-ooda/approval"
_INTERNAL_ACTION_WORK_TYPES = {"record_internal_action", "internal_action", "operator_action"}
_DEFAULT_ACTION_STREAMS = {"office_loop", "office_setup", "recovery"}
_INTERNAL_NOISE_ACTION_KEYS = {
    "proactive_ooda_packet_acceptance",
    "weekly_signal_to_decision_review_acceptance",
}
_INTERNAL_NOISE_NEXT_ACTIONS = {
    "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
    "record_proactive_ooda_approval_outcome",
    "record_weekly_signal_to_decision_review_acceptance",
}


def current_operator_action_head(*, posture: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(posture, Mapping):
        return {}
    rows = posture.get("operator_action_queue")
    if not isinstance(rows, list):
        return {}
    allowed_streams = _default_action_streams(posture)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if _row_is_real_operator_action(row, allowed_streams=allowed_streams):
            return _normalized_operator_action(row)
    return {}


def current_digest_notification_action(*, digest_receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(digest_receipt, Mapping):
        return {}
    rows = digest_receipt.get("notification_items")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        normalized = _normalized_operator_action(row)
        if normalized:
            return normalized
    return {}


def current_packet_fallback_operator_action(
    *,
    safe_work_result: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    staged_action_url: str,
) -> dict[str, Any]:
    if current_packet_user_approval_surface(stage_packet=stage_packet, safe_work_result=safe_work_result):
        return {}
    packet_summary = _packet_summary(safe_work_result=safe_work_result, stage_packet=stage_packet)
    recommended = _recommended_label(safe_work_result.get("recommended_option_or_draft"))
    detail = _operator_action_detail(
        safe_work_result=safe_work_result,
        stage_packet=stage_packet,
        packet_summary=packet_summary,
        recommended=recommended,
        staged_action_url=staged_action_url,
    )
    if not detail:
        return {}
    label = _current_packet_action_label(
        safe_work_result=safe_work_result,
        stage_packet=stage_packet,
        staged_action_url=staged_action_url,
        recommended=recommended,
    )
    return _normalized_operator_action(
        {
            "user_action_required": True,
            "next_action_label": label,
            "next_action_href": staged_action_url,
            "instruction": detail,
        }
    )


def approval_surface_fallback_operator_action(
    *,
    safe_work_result: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    staged_action_url: str,
    approval_surface_pending: bool,
    goal_posture: Mapping[str, Any] | None = None,
    digest_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_packet_action = current_packet_fallback_operator_action(
        safe_work_result=safe_work_result,
        stage_packet=stage_packet,
        staged_action_url=staged_action_url,
    )
    if approval_surface_pending:
        return current_packet_action
    digest_action = current_digest_notification_action(digest_receipt=digest_receipt)
    if digest_action:
        return digest_action
    live_action = current_operator_action_head(posture=goal_posture)
    if live_action:
        return live_action
    return current_packet_action


def _normalized_operator_action(action: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(action, Mapping):
        return {}
    label = str(
        action.get("next_action_label")
        or action.get("next_action_form_label")
        or action.get("title")
        or action.get("key")
        or "Open action"
    ).strip()
    href = str(
        action.get("next_action_form_href")
        or action.get("next_action_href")
        or action.get("console_deep_link")
        or ""
    ).strip()
    instruction = str(
        action.get("instruction")
        or action.get("telegram_message")
        or action.get("required_next_receipt")
        or label
    ).strip()
    if not instruction:
        return {}
    return {
        "user_action_required": True,
        "next_action_label": label or "Open action",
        "next_action_href": href,
        "instruction": instruction,
    }


def _default_action_streams(posture: Mapping[str, Any]) -> set[str]:
    policy = posture.get("operator_delivery_policy")
    if not isinstance(policy, Mapping):
        return set(_DEFAULT_ACTION_STREAMS)
    values = policy.get("default_action_digest_streams")
    if not isinstance(values, list):
        return set(_DEFAULT_ACTION_STREAMS)
    normalized = {str(item or "").strip() for item in values if str(item or "").strip()}
    return normalized or set(_DEFAULT_ACTION_STREAMS)


def _row_is_real_operator_action(row: Mapping[str, Any], *, allowed_streams: set[str]) -> bool:
    if row.get("user_action_required") is not True:
        return False
    if row.get("action_digest_eligible") is False:
        return False
    if str(row.get("delivery_policy") or "").strip() == "queue_only":
        return False
    if row.get("telegram_push_allowed") is False:
        return False
    if str(row.get("interruption_budget") or "").strip() in {"none", "queue_only"}:
        return False
    if str(row.get("default_action_digest_suppressed_reason") or "").strip():
        return False
    stream = str(row.get("operator_stream") or "").strip()
    if stream and "*" not in allowed_streams and stream not in allowed_streams:
        return False
    key = str(row.get("key") or "").strip()
    next_action = str(row.get("next_action") or "").strip()
    if key in _INTERNAL_NOISE_ACTION_KEYS or next_action in _INTERNAL_NOISE_NEXT_ACTIONS:
        return False
    return True


def build_proactive_ooda_approval_surface(
    *,
    safe_work_result: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    approval_outcome: Mapping[str, Any],
    fallback_operator_action: Mapping[str, Any] | None = None,
    approval_surface_pending: bool = True,
    approval_status: str,
    approval_source: str,
    packet_ref: str,
    staged_artifact_ref: str,
    staged_action_url: str,
    action_status: str = "",
    action_error: str = "",
    operator_context: bool = False,
) -> dict[str, Any]:
    recommended = _recommended_label(safe_work_result.get("recommended_option_or_draft"))
    evidence_rows = _evidence_rows(safe_work_result)
    current_verdict = _current_verdict_label(approval_outcome=approval_outcome, approval_status=approval_status)
    packet_summary = _packet_summary(safe_work_result=safe_work_result, stage_packet=stage_packet)
    if not approval_surface_pending:
        return _no_pending_approval_surface(
            current_verdict=current_verdict,
            fallback_operator_action=fallback_operator_action,
            action_status=action_status,
            action_error=action_error,
        )
    self_capture = _is_self_capture(
        safe_work_result=safe_work_result,
        staged_action_url=staged_action_url,
        recommended=recommended,
    )
    if self_capture:
        summary = (
            "No external approval is pending here. This page only records whether the current proactive "
            "packet was useful. Follow the operator action below if it still matters."
        )
    else:
        summary = "This page does not approve an external action. It only records whether the current proactive packet was useful."
    if action_status:
        tail = action_status.replace("_", " ")
        if action_error:
            tail = f"{tail} ({action_error.replace('_', ' ')})"
        summary = f"{summary} Last action: {tail}."

    object_rows = _decision_rows(
        self_capture=self_capture,
        safe_work_result=safe_work_result,
        stage_packet=stage_packet,
        packet_summary=packet_summary,
        recommended=recommended,
        staged_action_url=staged_action_url,
    )
    object_sections = []
    if evidence_rows:
        object_sections.append(
            {
                "eyebrow": "Evidence",
                "title": "What this packet was based on",
                "items": evidence_rows,
            }
        )

    default_source_kind = "operator" if operator_context else "principal"
    if self_capture:
        console_title = "Review proactive packet"
        object_title = "No external approval pending"
        object_summary = (
            "The current packet is an internal operator action. "
            "Use this page only to mark whether that packet was useful or noise."
        )
        object_ooda_title = "Actual next step"
        object_ooda_copy = (
            "Do the operator action if it still matters. "
            "Then use the form only to mark the packet useful, wrong, later, or noise."
        )
        object_sidebar_title = "Mark packet outcome"
        object_sidebar_copy = (
            "This form records only the packet verdict. "
            "Keep the note short and redacted."
        )
        form_eyebrow = "Packet verdict"
        form_title = "Mark useful or noise"
        form_copy = "This form does not execute the action below. It only records whether the packet was useful."
        submit_label = "Save packet verdict"
    else:
        console_title = "Record proactive packet verdict"
        object_title = "Proactive packet verdict"
        object_summary = (
            "Approve only if the packet itself was useful. "
            "Use Dismissed when it was just noise. The stored receipt is redacted."
        )
        object_ooda_title = "What you are deciding"
        object_ooda_copy = (
            "Approved means useful. Rejected means wrong. Deferred means later. "
            "Dismissed means noise."
        )
        object_sidebar_title = "Your verdict"
        object_sidebar_copy = (
            "Keep the note short and redacted. Do not paste raw private text, secrets, or full packet contents."
        )
        form_eyebrow = "Approval"
        form_title = "Save verdict"
        form_copy = "This only records the packet outcome. It does not purchase, book, send, post, or commit anything."
        submit_label = "Save verdict"
    return {
        "console_title": console_title,
        "console_summary": summary,
        "object_kind": "Proactive OODA",
        "object_title": object_title,
        "object_summary": object_summary,
        "object_meta": [
            {"label": "Current verdict", "value": current_verdict},
            *([{"label": "Saved from", "value": approval_source.replace("_", " ")}] if approval_source else []),
        ],
        "object_ooda_title": object_ooda_title,
        "object_ooda_copy": object_ooda_copy,
        "object_ooda_rows": object_rows,
        "object_sidebar_title": object_sidebar_title,
        "object_sidebar_copy": object_sidebar_copy,
        "object_sidebar_rows": [
            _object_detail_row("Current verdict", current_verdict, "Status"),
        ],
        "object_sections": object_sections,
        "object_sidebar_form": {
            "eyebrow": form_eyebrow,
            "title": form_title,
            "copy": form_copy,
            "method": "post",
            "action": "/admin/actions/proactive-ooda-evidence",
            "submit_label": submit_label,
            "fields": [
                {"type": "hidden", "name": "return_to", "value": _APPROVAL_CAPTURE_PATH},
                {
                    "type": "select",
                    "name": "outcome",
                    "label": "Outcome",
                    "options": [
                        {
                            "value": "approved",
                            "label": "Approved",
                            "selected": _outcome_selected(
                                option="approved",
                                approval_outcome=approval_outcome,
                                self_capture=self_capture,
                            ),
                        },
                        {
                            "value": "rejected",
                            "label": "Rejected",
                            "selected": _outcome_selected(
                                option="rejected",
                                approval_outcome=approval_outcome,
                                self_capture=self_capture,
                            ),
                        },
                        {
                            "value": "deferred",
                            "label": "Deferred / later",
                            "selected": _outcome_selected(
                                option="deferred",
                                approval_outcome=approval_outcome,
                                self_capture=self_capture,
                            ),
                        },
                        {
                            "value": "dismissed",
                            "label": "Dismissed / noise",
                            "selected": _outcome_selected(
                                option="dismissed",
                                approval_outcome=approval_outcome,
                                self_capture=self_capture,
                            ),
                        },
                    ],
                },
                {
                    "type": "textarea",
                    "name": "evidence",
                    "label": "Optional short note",
                    "value": "",
                    "placeholder": "Optional. Keep it short and redacted.",
                },
                {"type": "hidden", "name": "source_kind", "value": default_source_kind},
                {"type": "hidden", "name": "packet_ref", "value": packet_ref},
                {"type": "hidden", "name": "staged_artifact_ref", "value": staged_artifact_ref},
            ],
        },
    }


def _no_pending_approval_surface(
    *,
    current_verdict: str,
    fallback_operator_action: Mapping[str, Any] | None,
    action_status: str,
    action_error: str,
) -> dict[str, Any]:
    summary = "There is no live proactive packet waiting for explicit approval."
    if action_status:
        tail = action_status.replace("_", " ")
        if action_error:
            tail = f"{tail} ({action_error.replace('_', ' ')})"
        summary = f"{summary} Last action: {tail}."
    fallback_action = _fallback_operator_action_row(fallback_operator_action)
    object_ooda_title = "Current state"
    object_ooda_copy = "EA is not waiting for any consent-gated decision from you."
    object_ooda_rows = [
        _object_detail_row(
            "Current state",
            "Nothing needs approval right now.",
            "Clear",
        ),
    ]
    object_title = "No approval pending"
    object_summary = "There is no purchase, booking, send, post, cancellation, or commitment waiting for your approval."
    object_meta = [
        {"label": "Pending approvals", "value": "0"},
    ]
    object_sidebar_title = "No approval pending"
    object_sidebar_copy = "This page shows a verdict form only when a current proactive packet needs explicit approval."
    object_sidebar_rows = [
        _object_detail_row("Current verdict", current_verdict, "Status"),
    ]
    if fallback_action:
        action_label = fallback_action["label"] or "Open action"
        summary = f"Nothing needs approval here. Current action: {action_label}."
        object_title = f"Current action: {action_label}"
        object_summary = "Open the action below. This page does not record or accept an approval."
        object_meta.append({"label": "Action needed", "value": fallback_action["label"] or "Open action"})
        object_ooda_title = "Do this"
        object_ooda_copy = "Complete the action below if you want EA unstuck. Nothing on this page needs approval."
        object_ooda_rows = [
            _object_detail_row(
                "Do this",
                fallback_action["detail"],
                fallback_action["label"],
                href=fallback_action["href"] or None,
            ),
            _object_detail_row(
                "Approval state",
                "No proactive packet needs approval right now.",
                "Clear",
            ),
        ]
        object_sidebar_title = "No approval pending"
        object_sidebar_copy = "Open the action link. This page has no approval form."
        object_sidebar_rows = [
            _object_detail_row(
                "Action",
                fallback_action["detail"],
                fallback_action["label"],
                href=fallback_action["href"] or None,
            ),
            _object_detail_row("Pending approvals", "0", "Clear"),
        ]
    return {
        "console_title": "No approval pending" if fallback_action else "Nothing to approve",
        "console_summary": summary,
        "object_kind": "Proactive OODA",
        "object_title": object_title,
        "object_summary": object_summary,
        "object_meta": object_meta,
        "object_ooda_title": object_ooda_title,
        "object_ooda_copy": object_ooda_copy,
        "object_ooda_rows": object_ooda_rows,
        "object_sidebar_title": object_sidebar_title,
        "object_sidebar_copy": object_sidebar_copy,
        "object_sidebar_rows": object_sidebar_rows,
        "object_sections": [],
        "object_sidebar_form": {},
    }


def _fallback_operator_action_row(fallback_operator_action: Mapping[str, Any] | None) -> dict[str, str]:
    normalized = _normalized_operator_action(fallback_operator_action)
    if not normalized:
        return {}
    return {
        "detail": str(normalized.get("instruction") or "").strip(),
        "href": str(normalized.get("next_action_href") or "").strip(),
        "label": str(normalized.get("next_action_label") or "").strip(),
    }


def _decision_rows(
    *,
    self_capture: bool,
    safe_work_result: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    packet_summary: str,
    recommended: str,
    staged_action_url: str,
) -> list[dict[str, str]]:
    if self_capture:
        next_step_detail = _operator_action_detail(
            safe_work_result=safe_work_result,
            stage_packet=stage_packet,
            packet_summary=packet_summary,
            recommended=recommended,
            staged_action_url=staged_action_url,
        )
        return [
            _object_detail_row(
                "Actual next step",
                next_step_detail,
                "Action",
                href=staged_action_url or None,
            ),
            _object_detail_row(
                "What this page records",
                "Only the current proactive packet verdict. No purchase, booking, send, post, cancellation, or commitment will happen from this page.",
                "Scope",
            ),
            _object_detail_row(
                "How to mark it",
                "Approved means the reminder was useful. Dismissed means noise. Rejected means wrong. Deferred means later.",
                "Guide",
            ),
        ]
    rows = []
    if packet_summary:
        rows.append(_object_detail_row("Packet summary", packet_summary, "Decision"))
    if recommended:
        rows.append(_object_detail_row("Suggested next step", recommended, "Decision"))
    if staged_action_url:
        rows.append(
            _object_detail_row(
                "Open staged packet",
                staged_action_url,
                "Link",
                href=staged_action_url,
            )
        )
    if not rows:
        rows.append(
            _object_detail_row(
                "Packet summary",
                "The current proactive packet did not expose a concise decision summary.",
                "Waiting",
            )
        )
    return rows


def _operator_action_detail(
    *,
    safe_work_result: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    packet_summary: str,
    recommended: str,
    staged_action_url: str,
) -> str:
    stage = dict(stage_packet.get("stage") or {})
    payload = dict(stage.get("payload") or {})
    for value in (
        safe_work_result.get("approval_prompt"),
        payload.get("request_text"),
        payload.get("summary"),
        packet_summary,
        recommended,
        staged_action_url,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "The packet did not preserve a concise operator action."


def _current_packet_action_label(
    *,
    safe_work_result: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    staged_action_url: str,
    recommended: str,
) -> str:
    raw_recommended = safe_work_result.get("recommended_option_or_draft")
    if isinstance(raw_recommended, Mapping):
        raw_value = raw_recommended.get("value")
        if isinstance(raw_value, Mapping):
            for value in (
                raw_value.get("label"),
                raw_value.get("title"),
                raw_value.get("page_title"),
            ):
                text = str(value or "").strip()
                if text:
                    return text
    stage = dict(stage_packet.get("stage") or {})
    payload = dict(stage.get("payload") or {})
    for value in (
        payload.get("action_label"),
        payload.get("label"),
        recommended,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "Open action"


def _outcome_selected(
    *,
    option: str,
    approval_outcome: Mapping[str, Any],
    self_capture: bool,
) -> bool:
    current = str(approval_outcome.get("outcome") or "").strip()
    if current:
        return current == option
    if self_capture:
        return option == "deferred"
    return option == "approved"


def _is_self_capture(
    *,
    safe_work_result: Mapping[str, Any],
    staged_action_url: str,
    recommended: str,
) -> bool:
    work_type = str(safe_work_result.get("work_type") or "").strip().lower()
    url = str(staged_action_url or "").strip()
    recommended_text = str(recommended or "").strip().lower()
    return (
        work_type in _INTERNAL_ACTION_WORK_TYPES
        or url.endswith(_APPROVAL_CAPTURE_PATH)
        or "approval capture" in recommended_text
        or "packet verdict" in recommended_text
    )


def _packet_summary(*, safe_work_result: Mapping[str, Any], stage_packet: Mapping[str, Any]) -> str:
    stage = stage_packet.get("stage")
    if not isinstance(stage, Mapping):
        stage = {}
    for value in (
        safe_work_result.get("summary"),
        stage_packet.get("summary"),
        stage.get("summary"),
        stage.get("requested_outcome"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _current_verdict_label(*, approval_outcome: Mapping[str, Any], approval_status: str) -> str:
    if bool(approval_outcome.get("approval_outcome_recorded")):
        outcome = str(approval_outcome.get("outcome") or "").strip()
        if outcome:
            return outcome.replace("_", " ").title()
        return "Recorded"
    if approval_status == "stale_not_current":
        return "Saved only for an older packet"
    return "Not recorded yet"


def _recommended_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return str(value or "").strip()
    kind = str(value.get("kind") or "result").replace("_", " ").strip()
    raw = value.get("value")
    if isinstance(raw, Mapping):
        parts = [
            str(raw.get("label") or raw.get("title") or "").strip(),
            str(raw.get("page_title") or "").strip(),
            str(raw.get("url") or raw.get("link") or raw.get("href") or "").strip(),
        ]
        detail = " | ".join(part for part in parts if part)
        return f"{kind}: {detail}" if detail else kind
    detail = str(raw or "").strip()
    return f"{kind}: {detail}" if detail else kind


def _evidence_rows(safe_work_result: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ref in list(safe_work_result.get("evidence_refs") or []):
        if not isinstance(ref, Mapping):
            continue
        label = str(ref.get("label") or ref.get("kind") or "Evidence").strip()
        detail_parts = [
            str(ref.get("page_title") or "").strip(),
            str(ref.get("url") or "").strip(),
            "reachable" if ref.get("reachable") is True else "",
        ]
        rows.append(
            _object_detail_row(
                label,
                " · ".join(part for part in detail_parts if part) or "No detail",
                str(ref.get("kind") or "Evidence").strip() or "Evidence",
                href=str(ref.get("final_url") or ref.get("url") or "").strip(),
            )
        )
    return rows
