from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from app.services.assistant_property_lane import (
    assistant_property_lane_enabled,
    assistant_property_signal_present,
)
from app.services.proactive_ooda_service import ProactiveSignal
from app.services.public_urls import ea_public_app_base_url


GOAL_ACTION_QUEUE_SIGNAL_SCHEMA = "ea.proactive_ooda.goal_action_queue_signal.v1"
DEFAULT_GOAL_ACTION_QUEUE_LIMIT = 1
DEFAULT_ALLOWED_OPERATOR_STREAMS = ("office_loop", "office_setup", "recovery")

_SENSITIVE_TRUE_KEYS = {
    "callback_tokens_exposed",
    "raw_acceptance_text_exposed",
    "raw_actor_identity_exposed",
    "raw_callback_token_exposed",
    "raw_chat_ids_exposed",
    "raw_client_id_exposed",
    "raw_client_secret_exposed",
    "raw_email_exposed",
    "raw_error_description_exposed",
    "raw_expected_google_email_exposed",
    "raw_object_reference_exposed",
    "raw_pair_url_exposed",
    "raw_private_context_exposed",
    "raw_public_share_url_exposed",
    "raw_qr_payload_exposed",
    "raw_secret_exposed",
    "raw_session_exposed",
    "raw_token_exposed",
    "raw_track_url_exposed",
    "raw_transcript_fields_exposed",
    "raw_voice_ids_exposed",
    "raw_whatsapp_session_ref_exposed",
}

_SAFE_EXTRA_LINK_KEYS = (
    "console_deep_link",
    "external_setup_url",
)


def load_goal_action_queue_signals(
    path: str | Path,
    *,
    limit: int = DEFAULT_GOAL_ACTION_QUEUE_LIMIT,
    public_base_url: str = "",
    allowed_operator_streams: tuple[str, ...] | str | None = None,
) -> tuple[ProactiveSignal, ...]:
    payload = _read_goal_posture(path)
    if not payload:
        return ()
    return goal_action_queue_signals(
        payload,
        limit=limit,
        public_base_url=public_base_url,
        allowed_operator_streams=allowed_operator_streams,
    )


def goal_action_queue_signals(
    posture: Mapping[str, Any],
    *,
    limit: int = DEFAULT_GOAL_ACTION_QUEUE_LIMIT,
    public_base_url: str = "",
    allowed_operator_streams: tuple[str, ...] | str | None = None,
) -> tuple[ProactiveSignal, ...]:
    rows = posture.get("operator_action_queue")
    if not isinstance(rows, list):
        return ()
    base_url = _normalized_base_url(public_base_url)
    source_fingerprint = str(posture.get("source_state_fingerprint") or "").strip()
    effective_allowed_streams = _effective_allowed_operator_streams(
        posture,
        allowed_operator_streams=allowed_operator_streams,
    )
    signals: list[ProactiveSignal] = []
    for raw_row in rows:
        if len(signals) >= max(int(limit or 0), 0):
            break
        if not isinstance(raw_row, Mapping):
            continue
        row = dict(raw_row)
        if _row_hidden_from_ea_property_boundary(row):
            continue
        if not _row_proactive_signal_allowed(row):
            continue
        if not _row_is_user_action(row):
            continue
        if _row_exposes_sensitive_material(row):
            continue
        if not _row_stream_allowed(row, allowed_operator_streams=effective_allowed_streams):
            continue
        signal = _signal_from_action_row(row, source_fingerprint=source_fingerprint, public_base_url=base_url)
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def _row_hidden_from_ea_property_boundary(row: Mapping[str, Any]) -> bool:
    if assistant_property_lane_enabled():
        return False
    return assistant_property_signal_present(
        row.get("key"),
        row.get("operator_stream"),
        row.get("title"),
        row.get("instruction"),
        row.get("required_next_receipt"),
        row.get("next_action"),
        row.get("next_action_href"),
        row.get("next_action_label"),
        row.get("console_deep_link"),
        row,
    )


def _row_proactive_signal_allowed(row: Mapping[str, Any]) -> bool:
    return row.get("proactive_signal_allowed") is True


def _signal_from_action_row(
    row: Mapping[str, Any],
    *,
    source_fingerprint: str,
    public_base_url: str,
) -> ProactiveSignal | None:
    key = _compact(str(row.get("key") or ""), 80)
    if not key:
        return None
    title = _compact(str(row.get("title") or key.replace("_", " ").title()), 140)
    instruction = _compact(str(row.get("instruction") or row.get("telegram_message") or ""), 220)
    required_next_receipt = _compact(str(row.get("required_next_receipt") or ""), 220)
    action_label = _compact(str(row.get("next_action_label") or row.get("next_action_form_label") or "Open action"), 120)
    action_href = _action_href(row, public_base_url=public_base_url)
    row_fingerprint = _row_fingerprint(row, source_fingerprint=source_fingerprint)
    source_ref = f"goal_action_queue:{key}:{row_fingerprint[:16]}"
    summary = instruction or f"Action needed: {title}."
    candidate_items = _candidate_items(row, action_label=action_label, action_href=action_href)
    links = _links(row, action_href=action_href, public_base_url=public_base_url)
    stage_summary = _compact(f"Action needed: {title}.", 180)
    approval_prompt = _compact(f"{action_label}: {instruction or title}", 220)
    if not candidate_items and not links and not approval_prompt:
        return None
    payload = {
        "schema": GOAL_ACTION_QUEUE_SIGNAL_SCHEMA,
        "queue_key": key,
        "operator_stream": _compact(str(row.get("operator_stream") or ""), 48),
        "source_state_fingerprint_hash": _hash_value(source_fingerprint) if source_fingerprint else "",
        "row_fingerprint": row_fingerprint,
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "raw_private_context_exposed": False,
        "raw_secret_exposed": False,
        "raw_token_exposed": False,
        "ooda_loop": {
            "reviewed": True,
            "summary": summary,
            "observe": {
                "summary": summary,
                "channel": "goal_action_queue",
            },
            "orient": {
                "summary": _compact(
                    "The goal posture already classified this as a user-action blocker and permits action-required delivery.",
                    220,
                ),
                "tags": tuple(
                    item
                    for item in (
                        "goal_posture",
                        "operator_action",
                        str(row.get("lens") or "").strip(),
                        str(row.get("operator_stream") or "").strip(),
                    )
                    if str(item or "").strip()
                ),
            },
            "decide": {
                "summary": approval_prompt,
                "approval_required": True,
                "recommended_actions": (approval_prompt,),
                "ignored_consequence": _ignored_consequence(row),
            },
            "act": {
                "summary": approval_prompt,
                "action_plan": _action_plan(row, action_label=action_label),
                "external_action_policy": _external_action_policy(),
                "stage": {
                    "kind": "internal_action",
                    "summary": stage_summary,
                    "artifacts": ["action_surface", "approval_prompt"],
                    "work_type": "record_internal_action",
                    "action_label": action_label,
                    "action_url": action_href,
                    "action_method": str(row.get("next_action_form_method") or row.get("next_action_method") or "get").strip().lower() or "get",
                    "candidate_items": [],
                    "links": links,
                    "approval_url": action_href,
                    "approval_prompt": approval_prompt,
                    "request_text": instruction or title,
                    "requirements": _requirements(row),
                    "constraints": _constraints(row),
                    "selection_criteria": ("operator action required", "use the provided action surface"),
                    "notes": _notes(row),
                },
            },
        },
    }
    return ProactiveSignal(
        source_ref=source_ref,
        signal_type="goal_action_queue",
        channel="goal_posture",
        title=title,
        summary=summary,
        counterparty="EA",
        external_id=source_ref,
        payload=payload,
    )


def _read_goal_posture(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not str(candidate).strip() or not candidate.exists():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_is_user_action(row: Mapping[str, Any]) -> bool:
    return (
        row.get("user_action_required") is True
        and row.get("telegram_push_allowed") is True
        and str(row.get("delivery_policy") or "").strip() == "action_required_only"
    )


def _row_exposes_sensitive_material(row: Mapping[str, Any]) -> bool:
    for key in _SENSITIVE_TRUE_KEYS:
        if row.get(key) is True:
            return True
    return False


def _normalize_operator_streams(values: tuple[str, ...] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values = [part.strip() for part in values.split(",")]
    else:
        raw_values = [str(item or "").strip() for item in list(values or [])]
    aliases = {
        "default": DEFAULT_ALLOWED_OPERATOR_STREAMS,
        "office": DEFAULT_ALLOWED_OPERATOR_STREAMS,
        "office_only": DEFAULT_ALLOWED_OPERATOR_STREAMS,
        "office_loop": ("office_loop",),
        "office-loop": ("office_loop",),
        "office_setup": ("office_setup",),
        "office-setup": ("office_setup",),
        "recovery": ("recovery",),
        "media": ("media_archive",),
        "media_archive": ("media_archive",),
        "all": ("*",),
        "*": ("*",),
    }
    normalized: list[str] = []
    for value in raw_values:
        if not value:
            continue
        for item in aliases.get(value.lower(), (value,)):
            token = str(item or "").strip()
            if token and token not in normalized:
                normalized.append(token)
    return tuple(normalized)


def _effective_allowed_operator_streams(
    posture: Mapping[str, Any],
    *,
    allowed_operator_streams: tuple[str, ...] | str | None,
) -> tuple[str, ...]:
    configured = _normalize_operator_streams(allowed_operator_streams)
    if configured:
        return configured
    policy = posture.get("operator_delivery_policy")
    if isinstance(policy, Mapping):
        configured = _normalize_operator_streams(policy.get("default_action_digest_streams"))
        if configured:
            return configured
    return DEFAULT_ALLOWED_OPERATOR_STREAMS


def _row_stream_allowed(
    row: Mapping[str, Any],
    *,
    allowed_operator_streams: tuple[str, ...],
) -> bool:
    operator_stream = str(row.get("operator_stream") or "").strip()
    if not operator_stream:
        return True
    if "*" in set(allowed_operator_streams):
        return True
    return operator_stream in allowed_operator_streams


def _action_href(row: Mapping[str, Any], *, public_base_url: str) -> str:
    href = str(row.get("next_action_form_href") or row.get("next_action_href") or "").strip()
    return _absolute_href(href, public_base_url=public_base_url)


def _absolute_href(value: str, *, public_base_url: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    base_url = _normalized_base_url(public_base_url)
    if not base_url:
        return text
    return urllib.parse.urljoin(f"{base_url}/", text.lstrip("/"))


def _normalized_base_url(value: str) -> str:
    return str(value or ea_public_app_base_url() or "").strip().rstrip("/")


def _candidate_items(row: Mapping[str, Any], *, action_label: str, action_href: str) -> list[dict[str, str]]:
    if not action_href:
        return []
    item: dict[str, str] = {
        "label": action_label or "Open action",
        "url": action_href,
        "candidate_source": "goal_action_queue",
    }
    title = _compact(str(row.get("title") or ""), 120)
    if title:
        item["title"] = title
    return [item]


def _links(row: Mapping[str, Any], *, action_href: str, public_base_url: str) -> list[str]:
    links: list[str] = []
    if action_href:
        links.append(action_href)
    for key in _SAFE_EXTRA_LINK_KEYS:
        link = _absolute_href(str(row.get(key) or "").strip(), public_base_url=public_base_url)
        if link and link not in links:
            links.append(link)
    return links[:3]


def _action_plan(row: Mapping[str, Any], *, action_label: str) -> tuple[str, ...]:
    plan = [
        str(row.get("instruction") or "").strip(),
        action_label,
        "Rerun the relevant readiness receipt after completing the operator action.",
    ]
    return tuple(_compact(item, 180) for item in plan if _compact(item, 180))[:4]


def _requirements(row: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("required_next_receipt", "evidence_kind", "scope_bundle"):
        value = _compact(str(row.get(key) or ""), 180)
        if value:
            values.append(value)
    for item in list(row.get("missing_setup") or []):
        value = _compact(str(item or ""), 140)
        if value:
            values.append(value)
    return values[:6]


def _constraints(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "delivery_policy": "action_required_only",
        "quiet_hours_respected": row.get("quiet_hours_respected") is not False,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": row.get("irreversible_actions_consent_gated") is not False,
    }


def _notes(row: Mapping[str, Any]) -> str:
    note_parts = [
        _compact(str(row.get("telegram_message") or ""), 220),
        _compact(str(row.get("action_required_reason") or ""), 120),
    ]
    return " ".join(part for part in note_parts if part).strip()


def _ignored_consequence(row: Mapping[str, Any]) -> str:
    receipt = _compact(str(row.get("required_next_receipt") or ""), 140)
    if receipt:
        return f"Gold readiness remains blocked until EA records: {receipt}."
    return "Gold readiness remains blocked until this operator action is completed."


def _external_action_policy() -> str:
    return "Do not buy, book, send, cancel, post, or commit without explicit approval."


def _row_fingerprint(row: Mapping[str, Any], *, source_fingerprint: str) -> str:
    stable = {
        "key": str(row.get("key") or "").strip(),
        "kind": str(row.get("kind") or "").strip(),
        "operator_stream": str(row.get("operator_stream") or "").strip(),
        "next_action": str(row.get("next_action") or "").strip(),
        "next_action_href": str(row.get("next_action_href") or row.get("next_action_form_href") or "").strip(),
        "required_next_receipt": str(row.get("required_next_receipt") or "").strip(),
        "missing_setup": [str(item or "").strip() for item in list(row.get("missing_setup") or []) if str(item or "").strip()],
        "user_action_required": row.get("user_action_required") is True,
        "telegram_push_allowed": row.get("telegram_push_allowed") is True,
    }
    return _hash_value(json.dumps(stable, sort_keys=True, separators=(",", ":")))


def _compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
