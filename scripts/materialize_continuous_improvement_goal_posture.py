#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
DEFAULT_OFFICE_RECEIPT = ROOT / ".codex-studio/published/ea_office_loop_goal.generated.json"
DEFAULT_SIGNAL_RECEIPT = ROOT / ".codex-studio/published/ea_whole_project_signal_to_decision.generated.json"
DEFAULT_MEDIA_RECEIPT = ROOT / ".codex-studio/published/active_media_ltd_goal_bundle.generated.json"
DEFAULT_MANFRED_RECEIPT = ROOT / ".codex-studio/published/manfred_realtime_conversation_readiness.generated.json"
DEFAULT_QUALITY_RECEIPT = ROOT / ".codex-studio/published/ea_executive_assistant_quality_readiness.generated.json"
DEFAULT_ACCEPTANCE_RECEIPT = ROOT / ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json"
DEFAULT_TEABLE_RECOVERY_READINESS = ROOT / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
DEFAULT_TEABLE_RECOVERY_PROOF = ROOT / ".codex-studio/published/teable_env_recovery_proof.generated.json"
DEFAULT_PROACTIVE_OODA_OPERATOR_STATUS = ROOT / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
DEFAULT_PROACTIVE_OODA_GOLD_ACCEPTANCE = ROOT / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
DEFAULT_POCKET_AUDIO_ARCHIVE = ROOT / ".codex-studio/published/pocket_audio_archive_receipt.generated.json"
DEFAULT_TELEGRAM_BUSINESS_SIGNAL_READINESS = ROOT / ".codex-studio/published/telegram_business_signal_readiness.generated.json"
DEFAULT_TELEGRAM_AUDIOBOOK_READINESS = ROOT / ".codex-studio/published/telegram_audiobook_live_readiness.generated.json"
DEFAULT_TELEGRAM_AUDIOBOOK_DELIVERY = ROOT / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_INTAKE = ROOT / ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_BUNDLE = ROOT / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_DELIVERY = ROOT / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_SHARE = ROOT / ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_VOICE = ROOT / ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json"

BLOCKING_PREFIXES = ("blocked", "fail", "missing", "waiting", "error")
MORNING_BRIEF_ACCEPTANCE_RECEIPT = "real operator acceptance that the morning brief was worth reading"
WEEKLY_SIGNAL_REVIEW_ACCEPTANCE_RECEIPT = "real weekly signal-to-decision review acceptance receipt"
PROACTIVE_OODA_ACCEPTANCE_RECEIPT = (
    "real proactive OODA packet accepted with action-required-only routed delivery, approved-source or transcript signal, "
    "live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, "
    "current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
FRESH_HOST_TEABLE_RECOVERY_RECEIPT = "fresh-host Teable recovery drill receipt mirrored into the repo"
TELEGRAM_BUSINESS_SIGNAL_SETUP_RECEIPT = "Telegram Business/Secretary bot connected with allowlisted signal chats"
MANFRED_REALTIME_ACCEPTANCE_RECEIPT = "consented Manfred STT/TTS realtime conversation proof"
TELEGRAM_AUDIOBOOK_LIVE_DELIVERY_RECEIPT = "passing Telegram audiobook live delivery receipt"
WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_RECEIPT = "passing WhatsApp audiobook live delivery receipt"
EA_QUALITY_ACCEPTANCE_PROOFS = {
    "real_commitment_recovered_or_closed": {
        "key": "ea_real_commitment_recovered_or_closed",
        "title": "Real commitment recovered or closed",
        "required_next_receipt": "real commitment recovered or closed with an evidence receipt",
        "evidence_kind": "real_commitment_recovery_evidence",
        "next_action": "record_redacted_real_commitment_recovery_evidence",
        "instruction": "Record redacted evidence that a real commitment was recovered or closed.",
    },
    "real_approved_action_audited": {
        "key": "ea_real_approved_action_audited",
        "title": "Real approved outbound action audited",
        "required_next_receipt": "real approved outbound action with audit trail",
        "evidence_kind": "approved_outbound_action_audit_trail",
        "next_action": "record_redacted_approved_action_audit_evidence",
        "instruction": "Record redacted evidence for a real approved outbound action audit trail.",
    },
    "real_provider_failure_recovered": {
        "key": "ea_real_provider_failure_recovered",
        "title": "Real provider failure recovered",
        "required_next_receipt": "real provider failure recovered with operator-grade reason",
        "evidence_kind": "provider_failure_recovery_evidence",
        "next_action": "record_redacted_provider_failure_recovery_evidence",
        "instruction": "Record redacted evidence that a real provider failure was recovered with an operator-grade reason.",
    },
}

ACTION_SURFACES = {
    "record_redacted_operator_acceptance_for_real_morning_brief": {
        "href": "/admin/actions/acceptance-evidence",
        "label": "Record a real-use outcome",
        "method": "post",
    },
    "record_redacted_real_commitment_recovery_evidence": {
        "href": "/admin/actions/acceptance-evidence",
        "label": "Record a real-use outcome",
        "method": "post",
    },
    "record_redacted_approved_action_audit_evidence": {
        "href": "/admin/actions/acceptance-evidence",
        "label": "Record a real-use outcome",
        "method": "post",
    },
    "record_redacted_provider_failure_recovery_evidence": {
        "href": "/admin/actions/acceptance-evidence",
        "label": "Record a real-use outcome",
        "method": "post",
    },
    "record_weekly_signal_to_decision_review_acceptance": {
        "href": "/admin/actions/signal-to-decision-evidence",
        "label": "Record signal review evidence",
        "method": "post",
    },
    "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome": {
        "href": "/admin/proactive-ooda/approval",
        "label": "Open approval capture",
        "method": "get",
    },
    "maintain_proactive_ooda_gold_acceptance_evidence": {
        "href": "/app/today",
        "label": "Open Today",
        "method": "get",
    },
    "run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence": {
        "href": "/admin/goals",
        "label": "Open goal evidence",
        "method": "get",
    },
    "connect_telegram_business_secretary_bot_and_allowlist_chats": {
        "href": "/integrations/telegram",
        "label": "Open Telegram setup",
        "method": "get",
    },
    "capture_consented_manfred_stt_tts_realtime_proof": {
        "href": "/memorials/manfred/voice-config",
        "label": "Spoken conversation proof",
        "method": "get",
    },
    "choose_sent_replacement_voice_sample": {
        "href": "/integrations/telegram",
        "label": "Open Telegram",
        "method": "get",
    },
    "choose_one_telegram_audiobook_voice_sample": {
        "href": "/integrations/telegram",
        "label": "Open Telegram",
        "method": "get",
    },
    "capture_passing_telegram_audiobook_live_delivery_receipt": {
        "href": "/integrations/telegram",
        "label": "Open Telegram",
        "method": "get",
    },
    "capture_passing_whatsapp_audiobook_live_delivery_receipt": {
        "href": "/integrations/whatsapp",
        "label": "Open WhatsApp",
        "method": "get",
    },
}


def _query_href(path: str, **params: str) -> str:
    clean = {key: value for key, value in params.items() if str(value or "").strip()}
    return f"{path}?{urllib.parse.urlencode(clean)}" if clean else path


def _acceptance_form_href(proof_key: str) -> str:
    return _query_href("/admin/actions/acceptance-evidence", return_to="/admin/goals", proof_key=proof_key)


def _signal_form_href(evidence_part: str) -> str:
    return _query_href("/admin/actions/signal-to-decision-evidence", return_to="/admin/goals", evidence_part=evidence_part)


def _operator_form_surface(next_action: str, action_context: dict[str, Any]) -> dict[str, str]:
    surface = ACTION_SURFACES.get(next_action, {})
    href = str(surface.get("href") or "").strip()
    method = str(surface.get("method") or "").strip().lower()
    if href == "/admin/actions/acceptance-evidence":
        form_href = str(action_context.get("next_action_form_href") or "").strip()
        if not form_href:
            form_href = _acceptance_form_href(str(action_context.get("proof_key") or "").strip())
        return {
            "next_action_form_href": form_href,
            "next_action_form_label": str(surface.get("label") or "").strip(),
            "next_action_form_method": "get",
        }
    if href == "/admin/actions/signal-to-decision-evidence":
        form_href = str(action_context.get("next_action_form_href") or "").strip()
        if not form_href:
            form_href = _signal_form_href(str(action_context.get("evidence_part") or "review").strip())
        return {
            "next_action_form_href": form_href,
            "next_action_form_label": str(surface.get("label") or "").strip(),
            "next_action_form_method": "get",
        }
    return {
        "next_action_form_href": href if method == "get" else "",
        "next_action_form_label": str(surface.get("label") or "").strip() if method == "get" else "",
        "next_action_form_method": method if method == "get" else "",
    }


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path) -> str:
    return resolve_source_worktree_fingerprint(path)


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _compact(value: object, default: str = "missing") -> str:
    text = " ".join(str(value or "").split()).strip()
    return text or default


def _status(payload: dict[str, Any], default: str = "missing_receipt") -> str:
    return _compact(payload.get("status"), default=default).lower()


def _is_blocking(status: str) -> bool:
    normalized = _compact(status).lower()
    return normalized.startswith(BLOCKING_PREFIXES) or normalized == "command_backed_no_published_receipt"


def _load_receipt(root: Path, path: Path) -> tuple[dict[str, Any], str]:
    payload = _json(path)
    if payload:
        return payload, _display_path(root, path)
    return {}, _display_path(root, path)


def _source_receipt(
    path_text: str,
    payload: dict[str, Any],
    *,
    current_source_head: str = "",
    current_source_fingerprint: str = "",
) -> dict[str, Any]:
    receipt = {
        "path": path_text,
        "present": bool(payload),
        "contract_name": _compact(payload.get("contract_name")),
        "status": _status(payload),
    }
    source_head = str(payload.get("source_git_head") or "").strip()
    source_fingerprint = str(payload.get("source_state_fingerprint") or "").strip()
    if source_head:
        receipt["source_git_head"] = source_head
    if source_fingerprint:
        receipt["source_state_fingerprint"] = source_fingerprint
    if current_source_head or current_source_fingerprint:
        receipt["source_fresh_to_current_source"] = bool(
            (source_head and current_source_head and source_head == current_source_head)
            or (source_fingerprint and current_source_fingerprint and source_fingerprint == current_source_fingerprint)
        )
    return receipt


def _lens(
    *,
    key: str,
    title: str,
    status: str,
    summary: str,
    next_action: str,
    verifier_commands: list[str],
    source_receipts: list[dict[str, Any]],
    components: list[dict[str, Any]] | None = None,
    status_class: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_class": status_class or ("blocking" if _is_blocking(status) else "progress"),
        "summary": summary,
        "next_action": next_action,
        "verifier_commands": verifier_commands,
        "source_receipts": source_receipts,
        "components": components or [],
    }


def _deliver_component(
    *,
    key: str,
    title: str,
    payload: dict[str, Any] | None = None,
    fallback_status: str = "missing_receipt",
    summary: str,
    next_action: str,
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    status = _status(payload or {}, default=fallback_status)
    source_statuses = [str(row.get("status") or "").strip().lower() for row in receipts]
    blocking_source_status = next((item for item in source_statuses if _is_blocking(item)), "")
    non_pass_source_status = next((item for item in source_statuses if item != "pass"), "")
    stale_source_evidence = any(
        bool(row.get("present")) and row.get("source_fresh_to_current_source") is not True
        for row in receipts
    )
    missing_source = any(not bool(row.get("present")) for row in receipts)
    if status == "pass":
        if blocking_source_status:
            status = blocking_source_status
        elif non_pass_source_status:
            status = non_pass_source_status
        elif missing_source:
            status = "missing_receipt"
        elif stale_source_evidence:
            status = "blocked_stale_source_evidence"
    if status == "blocked_stale_source_evidence":
        summary = (
            f"{summary} Source receipt evidence is stale or unstamped; refresh the component proof before claiming pass."
        )
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_class": "blocking" if _is_blocking(status) else "progress",
        "summary": summary,
        "next_action": next_action,
        "source_receipts": receipts,
    }


def _acceptance_proof_requirement(
    *,
    key: str,
    title: str,
    lens: str,
    required_next_receipt: str,
    evidence_kind: str,
    capture_surfaces: list[str],
    next_action: str,
    claim_boundary: str,
    source_receipts: list[dict[str, Any]],
    status: str = "pending_real_world_evidence",
    action_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    surface = ACTION_SURFACES.get(next_action, {})
    context = dict(action_context or {})
    form_surface = _operator_form_surface(next_action, context)
    payload = {
        "key": key,
        "title": title,
        "lens": lens,
        "status": status,
        "required_next_receipt": required_next_receipt,
        "evidence_kind": evidence_kind,
        "capture_surfaces": [surface for surface in capture_surfaces if str(surface or "").strip()],
        "next_action": next_action,
        "next_action_href": str(surface.get("href") or "").strip(),
        "next_action_label": str(surface.get("label") or "").strip(),
        "next_action_method": str(surface.get("method") or "").strip(),
        **form_surface,
        "claim_boundary": claim_boundary,
        "source_receipts": source_receipts,
    }
    if context:
        payload["action_context"] = {**context, **form_surface}
    return payload


def _telegram_audiobook_action_context(receipt: dict[str, Any]) -> dict[str, Any]:
    pending_rows = [
        dict(row)
        for row in list(receipt.get("pending_user_selected_voice_jobs") or [])
        if isinstance(row, dict)
    ]
    if not pending_rows:
        return {}
    first = pending_rows[0]
    labels = [
        str(item).strip()
        for item in list(first.get("replacement_candidate_labels") or first.get("voice_choice_candidate_labels") or [])
        if str(item).strip()
    ]
    distinct_labels = []
    for label in labels:
        if label not in distinct_labels:
            distinct_labels.append(label)
    context = {
        "kind": "telegram_audiobook_voice_choice",
        "operator_action": str(receipt.get("next_action") or "").strip(),
        "candidate_count": int(first.get("replacement_candidate_count") or first.get("voice_choice_candidate_count") or 0),
        "candidate_labels": labels[:3],
        "candidate_label_count": len(labels),
        "distinct_candidate_label_count": len(distinct_labels),
        "candidate_labels_distinct": len(labels) == len(distinct_labels),
        "author_gender_signal": str(first.get("author_gender_signal") or "").strip(),
        "author_gender_match_count": int(first.get("author_gender_match_count") or 0),
        "author_gender_mismatch_count": int(first.get("author_gender_mismatch_count") or 0),
        "author_gender_matched_candidates_only": bool(first.get("author_gender_matched_candidates_only")),
        "voice_sample_delivery_status": str(first.get("voice_sample_delivery_status") or "").strip(),
        "voice_sample_delivery_sent_count": int(first.get("voice_sample_delivery_sent_count") or 0),
        "voice_sample_delivery_expected_count": int(first.get("voice_sample_delivery_expected_count") or 0),
        "raw_voice_ids_exposed": bool(first.get("raw_voice_ids_exposed")),
        "callback_tokens_exposed": bool(first.get("callback_tokens_exposed")),
    }
    operator_packet = dict(receipt.get("operator_action_packet") or {})
    if operator_packet:
        context.update(
            {
                "user_action_required": bool(operator_packet.get("user_action_required")),
                "instruction": str(operator_packet.get("instruction") or "").strip(),
                "sent_samples_cover_expected": bool(operator_packet.get("sent_samples_cover_expected")),
            }
        )
    duplicate_suppression = dict(receipt.get("duplicate_suppression") or {})
    if duplicate_suppression:
        context["duplicate_suppression"] = {
            "action_required_only": bool(duplicate_suppression.get("action_required_only")),
            "only_current_jobs_can_require_user_action": bool(
                duplicate_suppression.get("only_current_jobs_can_require_user_action")
            ),
            "superseded_duplicate_candidate_count": int(
                duplicate_suppression.get("superseded_duplicate_candidate_count") or 0
            ),
            "suppressed_pending_voice_duplicate_count": int(
                duplicate_suppression.get("suppressed_pending_voice_duplicate_count") or 0
            ),
            "active_pending_voice_job_count": int(duplicate_suppression.get("active_pending_voice_job_count") or 0),
            "duplicate_active_pending_source_key_count": int(
                duplicate_suppression.get("duplicate_active_pending_source_key_count") or 0
            ),
            "duplicate_active_pending_source_keys_sha256": list(
                duplicate_suppression.get("duplicate_active_pending_source_keys_sha256") or []
            ),
            "raw_voice_ids_exposed": bool(duplicate_suppression.get("raw_voice_ids_exposed")),
            "callback_tokens_exposed": bool(duplicate_suppression.get("callback_tokens_exposed")),
        }
    return {key: value for key, value in context.items() if value not in ("", [], None)}


def _manual_acceptance_action_context(
    *,
    instruction: str,
    proof_key: str = "",
    evidence_part: str = "",
    acceptance_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requirement: dict[str, Any] = {}
    accepted = False
    if acceptance_receipt and proof_key:
        for row in list(acceptance_receipt.get("acceptance_capture_requirements") or []):
            if isinstance(row, dict) and str(row.get("proof_key") or row.get("key") or "").strip() == proof_key:
                requirement = dict(row)
                break
        acceptance_row = dict(dict(acceptance_receipt.get("acceptance_keys") or {}).get(proof_key) or {})
        accepted = (
            requirement.get("accepted") is True
            or str(requirement.get("status") or "").strip() == "accepted_redacted"
            or acceptance_row.get("accepted") is True
            or str(acceptance_row.get("status") or "").strip() == "accepted_redacted"
        )
    user_action_required = not accepted
    context = {
        "kind": "real_world_acceptance_capture",
        "proof_key": proof_key,
        "evidence_part": evidence_part,
        "user_action_required": user_action_required,
        "instruction": instruction,
        "delivery_policy": "action_required_only" if user_action_required else "queue_only",
        "telegram_push_allowed": user_action_required,
        "interruption_budget": "action_required" if user_action_required else "none",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_acceptance_text_exposed": False,
        "raw_actor_identity_exposed": False,
        "raw_object_reference_exposed": False,
    }
    if str(requirement.get("next_action_form_href") or "").strip():
        context["next_action_form_href"] = str(requirement.get("next_action_form_href") or "").strip()
        context["next_action_form_label"] = str(requirement.get("next_action_form_label") or "").strip()
        context["next_action_form_method"] = str(requirement.get("next_action_form_method") or "").strip()
    elif proof_key:
        context["next_action_form_href"] = _acceptance_form_href(proof_key)
        context["next_action_form_label"] = "Record a real-use outcome"
        context["next_action_form_method"] = "get"
    elif evidence_part:
        context["next_action_form_href"] = _signal_form_href(evidence_part)
        context["next_action_form_label"] = "Record signal review evidence"
        context["next_action_form_method"] = "get"
    return {key: value for key, value in context.items() if value not in ("", [], None)}


def _acceptance_proof_status(acceptance_receipt: dict[str, Any], proof_key: str) -> str:
    if not proof_key:
        return "pending_real_world_evidence"
    for row in list(acceptance_receipt.get("acceptance_capture_requirements") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("proof_key") or row.get("key") or "").strip() != proof_key:
            continue
        if row.get("accepted") is True or str(row.get("status") or "").strip() == "accepted_redacted":
            return "satisfied"
    acceptance_row = dict(dict(acceptance_receipt.get("acceptance_keys") or {}).get(proof_key) or {})
    if acceptance_row.get("accepted") is True or str(acceptance_row.get("status") or "").strip() == "accepted_redacted":
        return "satisfied"
    return "pending_real_world_evidence"


def _ea_quality_acceptance_proof_requirements(
    *,
    acceptance_receipt: dict[str, Any],
    quality_receipt: dict[str, Any],
    acceptance_path: str,
    quality_path: str,
    current_source_head: str,
    current_source_fingerprint: str,
) -> list[dict[str, Any]]:
    if not acceptance_receipt:
        return []
    source_receipts = [
        _source_receipt(
            acceptance_path,
            acceptance_receipt,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
        _source_receipt(
            quality_path,
            quality_receipt,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
    ]
    requirements: list[dict[str, Any]] = []
    for proof_key, spec in EA_QUALITY_ACCEPTANCE_PROOFS.items():
        status = _acceptance_proof_status(acceptance_receipt, proof_key)
        requirements.append(
            _acceptance_proof_requirement(
                key=str(spec["key"]),
                title=str(spec["title"]),
                lens="prove",
                required_next_receipt=str(spec["required_next_receipt"]),
                evidence_kind=str(spec["evidence_kind"]),
                capture_surfaces=[acceptance_path, quality_path],
                next_action=str(spec["next_action"]),
                claim_boundary="does_not_prove_good_executive_assistant_until_all_required_acceptance_keys_are_accepted",
                source_receipts=source_receipts,
                status=status,
                action_context=_manual_acceptance_action_context(
                    instruction=str(spec["instruction"]),
                    proof_key=proof_key,
                    acceptance_receipt=acceptance_receipt,
                ),
            )
        )
    return requirements


def _manfred_realtime_action_context(receipt: dict[str, Any]) -> dict[str, Any]:
    attestation = dict(receipt.get("room_audio_attestation") or {})
    required_check_ids = [
        str(item).strip()
        for item in list(attestation.get("required_check_ids") or [])
        if str(item).strip()
    ]
    manual_only = attestation.get("manual_only") is True
    user_action_required = manual_only and str(attestation.get("status") or "").strip().lower() != "pass"
    context = {
        "kind": "manual_room_audio_attestation",
        "user_action_required": user_action_required,
        "instruction": "Collect the manual real-room audio attestation for the Manfred spoken conversation proof.",
        "delivery_policy": "action_required_only" if user_action_required else "queue_only",
        "telegram_push_allowed": user_action_required,
        "interruption_budget": "action_required" if user_action_required else "none",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "manual_only": manual_only,
        "ci_must_not_auto_assert": attestation.get("ci_must_not_auto_assert") is True,
        "required_check_ids": required_check_ids,
        "required_check_count": len(required_check_ids),
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_transcript_fields_exposed": False,
        "candidate_raw_text_fields_exposed": False,
    }
    return {key: value for key, value in context.items() if value not in ("", [], None)}


def _stale_source_action_context(*, receipts: list[dict[str, Any]], refresh_commands: list[str]) -> dict[str, Any]:
    stale_receipts = [
        Path(str(row.get("path") or "")).name
        for row in receipts
        if bool(row.get("present")) and row.get("source_fresh_to_current_source") is not True
    ]
    if not stale_receipts:
        return {}
    return {
        "kind": "stale_source_evidence_refresh",
        "user_action_required": False,
        "instruction": "Refresh source-stale proof receipts; do not ping the user for this automation-only evidence refresh.",
        "stale_source_receipts": stale_receipts,
        "refresh_commands": [command for command in refresh_commands if str(command or "").strip()],
        "delivery_policy": "queue_only",
        "telegram_push_allowed": False,
        "non_action_progress_push_allowed": False,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
    }


def _whatsapp_playback_failure_action_context(receipt: dict[str, Any]) -> dict[str, Any]:
    results = [dict(row) for row in list(receipt.get("results") or []) if isinstance(row, dict)]
    first = results[0] if results else {}
    return {
        "kind": "public_share_playback_failure",
        "user_action_required": False,
        "instruction": "Repair the WhatsApp/Audiobookshelf public-share playback route, then rerun the WhatsApp audiobook playback verifier.",
        "failed_playback_count": int(receipt.get("failed") or len([row for row in results if row.get("passed") is not True]) or 0),
        "attempted_playback_count": int(receipt.get("attempted") or len(results) or 0),
        "first_failure_reason": str(first.get("reason") or "").strip(),
        "track_response_status": int(first.get("track_response_status") or 0),
        "track_content_type": str(first.get("track_content_type") or "").strip(),
        "media_error": bool(first.get("media_error")),
        "media_error_code": int(first.get("media_error_code") or 0),
        "public_share_host": str(first.get("public_share_host") or "").strip(),
        "repair_commands": [
            "PYTHONPATH=ea python3 ea/scripts/verify_whatsapp_audiobook_public_share_playback.py",
            "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
            "python3 scripts/materialize_continuous_improvement_goal_posture.py",
            "python3 scripts/verify_continuous_improvement_goal_posture.py --pretty",
        ],
        "delivery_policy": "queue_only",
        "telegram_push_allowed": False,
        "non_action_progress_push_allowed": False,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
        "raw_public_share_url_exposed": False,
        "raw_track_url_exposed": False,
    }


def _whatsapp_live_playback_blocked(receipt: dict[str, Any], blocking_reasons: list[str]) -> bool:
    if not any(str(reason or "").startswith("deliver:whatsapp_audiobook=blocked") for reason in blocking_reasons):
        return False
    failed_codes = {
        str(code or "").strip()
        for code in list(receipt.get("failed_codes") or [])
        if str(code or "").strip()
    }
    selected_delivery = receipt.get("selected_delivery")
    if isinstance(selected_delivery, dict):
        failed_codes.update(
            str(code or "").strip()
            for code in list(selected_delivery.get("failed_codes") or [])
            if str(code or "").strip()
        )
    next_action = str(receipt.get("next_action") or "").strip()
    return "machine_playback_e2e_not_verified" in failed_codes or next_action == (
        "run_public_share_machine_playback_e2e_before_claiming_live_delivery"
    )


def _whatsapp_live_playback_blocked_action_context(
    *,
    live_receipt: dict[str, Any],
    playback_receipt: dict[str, Any],
) -> dict[str, Any]:
    playback_context = _whatsapp_playback_failure_action_context(playback_receipt)
    if playback_context.get("track_response_status") or playback_context.get("track_content_type"):
        return playback_context

    selected_delivery = live_receipt.get("selected_delivery")
    selected = dict(selected_delivery) if isinstance(selected_delivery, dict) else {}
    return {
        **playback_context,
        "failed_playback_count": 1,
        "attempted_playback_count": 1,
        "first_failure_reason": str(
            selected.get("machine_playback_e2e_reason") or live_receipt.get("blocking_reason") or ""
        ).strip(),
        "track_response_status": int(selected.get("machine_playback_e2e_track_response_status") or 0),
        "track_content_type": str(selected.get("machine_playback_e2e_track_content_type") or "").strip(),
        "media_error": bool(selected.get("machine_playback_e2e_media_error_present")),
        "media_error_code": int(selected.get("machine_playback_e2e_media_error_code") or 0),
        "public_share_host": str(selected.get("public_share_host") or "").strip(),
    }


def _operator_action_priority(requirement: dict[str, Any]) -> tuple[int, int, int, str]:
    action_context = dict(requirement.get("action_context") or {})
    key_priority = {
        "ea_real_commitment_recovered_or_closed": 0,
        "ea_real_approved_action_audited": 1,
        "ea_real_provider_failure_recovered": 2,
        "morning_brief_operator_acceptance": 3,
        "weekly_signal_to_decision_review_acceptance": 4,
        "telegram_audiobook_live_delivery": 10,
        "manfred_stt_tts_realtime_conversation": 11,
    }
    lens_priority = {
        "prove": 1,
        "detect": 2,
        "deliver": 3,
        "recover": 4,
        "decide": 5,
    }
    if action_context.get("user_action_required") is True:
        key = str(requirement.get("key") or "")
        return (0, lens_priority.get(str(requirement.get("lens") or ""), 9), key_priority.get(key, 99), key)
    key = str(requirement.get("key") or "")
    return (1, lens_priority.get(str(requirement.get("lens") or ""), 9), key_priority.get(key, 99), key)


def _operator_action_queue(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = [requirement for requirement in requirements if str(requirement.get("status") or "") != "satisfied"]
    result: list[dict[str, Any]] = []
    for requirement in sorted(pending, key=_operator_action_priority):
        action_context = dict(requirement.get("action_context") or {})
        user_action_required = bool(action_context.get("user_action_required"))
        row = {
            "key": str(requirement.get("key") or "").strip(),
            "title": str(requirement.get("title") or "").strip(),
            "lens": str(requirement.get("lens") or "").strip(),
            "evidence_kind": str(requirement.get("evidence_kind") or "").strip(),
            "next_action": str(requirement.get("next_action") or "").strip(),
            "next_action_href": str(requirement.get("next_action_href") or "").strip(),
            "next_action_label": str(requirement.get("next_action_label") or "").strip(),
            "next_action_method": str(requirement.get("next_action_method") or "").strip(),
            "next_action_form_href": str(requirement.get("next_action_form_href") or "").strip(),
            "next_action_form_label": str(requirement.get("next_action_form_label") or "").strip(),
            "next_action_form_method": str(requirement.get("next_action_form_method") or "").strip(),
            "required_next_receipt": str(requirement.get("required_next_receipt") or "").strip(),
            "user_action_required": user_action_required,
            "instruction": str(action_context.get("instruction") or "").strip(),
            "proof_key": str(action_context.get("proof_key") or "").strip(),
            "evidence_part": str(action_context.get("evidence_part") or "").strip(),
            "manual_only": bool(action_context.get("manual_only")),
            "ci_must_not_auto_assert": bool(action_context.get("ci_must_not_auto_assert")),
            "required_check_ids": [
                str(item).strip()
                for item in list(action_context.get("required_check_ids") or [])
                if str(item).strip()
            ],
            "required_check_count": int(action_context.get("required_check_count") or 0),
            "missing_setup": [
                str(item).strip()
                for item in list(action_context.get("missing_setup") or [])
                if str(item).strip()
            ],
            "stale_source_receipts": [
                str(item).strip()
                for item in list(action_context.get("stale_source_receipts") or [])
                if str(item).strip()
            ],
            "refresh_commands": [
                str(item).strip()
                for item in list(action_context.get("refresh_commands") or [])
                if str(item).strip()
            ],
            "repair_commands": [
                str(item).strip()
                for item in list(action_context.get("repair_commands") or [])
                if str(item).strip()
            ],
            "failed_playback_count": int(action_context.get("failed_playback_count") or 0),
            "attempted_playback_count": int(action_context.get("attempted_playback_count") or 0),
            "first_failure_reason": str(action_context.get("first_failure_reason") or "").strip(),
            "track_response_status": int(action_context.get("track_response_status") or 0),
            "track_content_type": str(action_context.get("track_content_type") or "").strip(),
            "media_error": bool(action_context.get("media_error")),
            "media_error_code": int(action_context.get("media_error_code") or 0),
            "public_share_host": str(action_context.get("public_share_host") or "").strip(),
            "setup_checklist": [
                dict(item)
                for item in list(action_context.get("setup_checklist") or [])
                if isinstance(item, dict)
            ],
            "telegram_message": str(action_context.get("telegram_message") or "").strip(),
            "candidate_count": int(action_context.get("candidate_count") or 0),
            "candidate_labels": [
                str(item).strip()
                for item in list(action_context.get("candidate_labels") or [])
                if str(item).strip()
            ],
            "candidate_label_count": int(action_context.get("candidate_label_count") or 0),
            "distinct_candidate_label_count": int(action_context.get("distinct_candidate_label_count") or 0),
            "candidate_labels_distinct": bool(action_context.get("candidate_labels_distinct")),
            "author_gender_signal": str(action_context.get("author_gender_signal") or "").strip(),
            "author_gender_match_count": int(action_context.get("author_gender_match_count") or 0),
            "author_gender_mismatch_count": int(action_context.get("author_gender_mismatch_count") or 0),
            "author_gender_matched_candidates_only": bool(action_context.get("author_gender_matched_candidates_only")),
            "voice_sample_delivery_status": str(action_context.get("voice_sample_delivery_status") or "").strip(),
            "voice_sample_delivery_sent_count": int(action_context.get("voice_sample_delivery_sent_count") or 0),
            "voice_sample_delivery_expected_count": int(action_context.get("voice_sample_delivery_expected_count") or 0),
            "sent_samples_cover_expected": bool(action_context.get("sent_samples_cover_expected")),
            "duplicate_suppression": dict(action_context.get("duplicate_suppression") or {}),
            "delivery_policy": "action_required_only" if user_action_required else "queue_only",
            "telegram_push_allowed": user_action_required,
            "interruption_budget": "action_required" if user_action_required else "none",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": bool(action_context.get("raw_chat_ids_exposed")),
            "raw_token_exposed": bool(action_context.get("raw_token_exposed")),
            "raw_secret_exposed": bool(action_context.get("raw_secret_exposed")),
            "raw_voice_ids_exposed": bool(action_context.get("raw_voice_ids_exposed")),
            "callback_tokens_exposed": bool(action_context.get("callback_tokens_exposed")),
            "raw_public_share_url_exposed": bool(action_context.get("raw_public_share_url_exposed")),
            "raw_track_url_exposed": bool(action_context.get("raw_track_url_exposed")),
            "raw_acceptance_text_exposed": bool(action_context.get("raw_acceptance_text_exposed")),
            "raw_actor_identity_exposed": bool(action_context.get("raw_actor_identity_exposed")),
            "raw_object_reference_exposed": bool(action_context.get("raw_object_reference_exposed")),
            "raw_transcript_fields_exposed": bool(action_context.get("raw_transcript_fields_exposed")),
            "candidate_raw_text_fields_exposed": bool(action_context.get("candidate_raw_text_fields_exposed")),
        }
        optional_context_keys = (
            "proof_key",
            "evidence_part",
            "manual_only",
            "ci_must_not_auto_assert",
            "required_check_ids",
            "required_check_count",
            "candidate_count",
            "candidate_labels",
            "candidate_label_count",
            "distinct_candidate_label_count",
            "candidate_labels_distinct",
            "author_gender_signal",
            "author_gender_match_count",
            "author_gender_mismatch_count",
            "author_gender_matched_candidates_only",
            "voice_sample_delivery_status",
            "voice_sample_delivery_sent_count",
            "voice_sample_delivery_expected_count",
            "sent_samples_cover_expected",
            "duplicate_suppression",
            "repair_commands",
            "failed_playback_count",
            "attempted_playback_count",
            "first_failure_reason",
            "track_response_status",
            "track_content_type",
            "media_error",
            "media_error_code",
            "public_share_host",
            "raw_public_share_url_exposed",
            "raw_track_url_exposed",
            "raw_acceptance_text_exposed",
            "raw_actor_identity_exposed",
            "raw_object_reference_exposed",
            "raw_transcript_fields_exposed",
            "candidate_raw_text_fields_exposed",
        )
        for optional_key in optional_context_keys:
            if optional_key not in action_context:
                row.pop(optional_key, None)
        result.append({key: value for key, value in row.items() if value not in ("", [], None)})
    return result


def _operator_delivery_policy(operator_action_queue: list[dict[str, Any]]) -> dict[str, Any]:
    first = dict(operator_action_queue[0]) if operator_action_queue else {}
    return {
        "action_required_only": True,
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "telegram_push_allowed_for_next_action": bool(first.get("telegram_push_allowed")),
        "next_action_requires_user": bool(first.get("user_action_required")),
        "next_action_delivery_policy": str(first.get("delivery_policy") or "queue_only").strip(),
    }


def _whatsapp_voice_shadow_required(receipt: dict[str, Any]) -> bool:
    if not receipt:
        return False
    reason = str(receipt.get("reason") or "").strip()
    if str(receipt.get("status") or "").strip() == "waiting" and reason == "waiting_whatsapp_voice_selection_job_not_found":
        return False
    return True


def build_goal_posture(
    *,
    root: Path = ROOT,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    current_source_head = _git_head(root)
    current_source_fingerprint = _source_fingerprint(root)
    office, office_path = _load_receipt(root, root / DEFAULT_OFFICE_RECEIPT.relative_to(ROOT))
    signal, signal_path = _load_receipt(root, root / DEFAULT_SIGNAL_RECEIPT.relative_to(ROOT))
    media, media_path = _load_receipt(root, root / DEFAULT_MEDIA_RECEIPT.relative_to(ROOT))
    manfred, manfred_path = _load_receipt(root, root / DEFAULT_MANFRED_RECEIPT.relative_to(ROOT))
    quality, quality_path = _load_receipt(root, root / DEFAULT_QUALITY_RECEIPT.relative_to(ROOT))
    acceptance, acceptance_path = _load_receipt(root, root / DEFAULT_ACCEPTANCE_RECEIPT.relative_to(ROOT))
    recovery, recovery_path = _load_receipt(root, root / DEFAULT_TEABLE_RECOVERY_READINESS.relative_to(ROOT))
    recovery_proof, recovery_proof_path = _load_receipt(root, root / DEFAULT_TEABLE_RECOVERY_PROOF.relative_to(ROOT))
    ooda_status, ooda_status_path = _load_receipt(root, root / DEFAULT_PROACTIVE_OODA_OPERATOR_STATUS.relative_to(ROOT))
    ooda_gold, ooda_gold_path = _load_receipt(root, root / DEFAULT_PROACTIVE_OODA_GOLD_ACCEPTANCE.relative_to(ROOT))
    pocket_audio, pocket_audio_path = _load_receipt(root, root / DEFAULT_POCKET_AUDIO_ARCHIVE.relative_to(ROOT))
    tg_business, tg_business_path = _load_receipt(root, root / DEFAULT_TELEGRAM_BUSINESS_SIGNAL_READINESS.relative_to(ROOT))
    tg_ready, tg_ready_path = _load_receipt(root, root / DEFAULT_TELEGRAM_AUDIOBOOK_READINESS.relative_to(ROOT))
    tg_live, tg_live_path = _load_receipt(root, root / DEFAULT_TELEGRAM_AUDIOBOOK_DELIVERY.relative_to(ROOT))
    wa_intake, wa_intake_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_INTAKE.relative_to(ROOT))
    wa_bundle, wa_bundle_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_BUNDLE.relative_to(ROOT))
    wa_live, wa_live_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_DELIVERY.relative_to(ROOT))
    wa_share, wa_share_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_SHARE.relative_to(ROOT))
    wa_voice, wa_voice_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_VOICE.relative_to(ROOT))

    detect_lens = _lens(
        key="detect",
        title="Signal ingest and prioritization",
        status=_status(signal),
        summary=(
            "Turn incoming signals into a bounded operator packet and proactive OODA shortlist that can become "
            "decision-ready packets instead of letting them pile up as ambient noise. Pocket/audio transcript ingest "
            f"is {_status(pocket_audio) or 'not_mirrored'}."
        ),
        next_action=_compact(signal.get("next_action"), default="review_weekly_signal_to_decision_packet_with_operator"),
        verifier_commands=[
            "make verify-whole-project-signal-to-decision-receipt",
            "python3 scripts/verify_pocket_audio_archive_receipt.py",
            "python3 scripts/verify_telegram_business_signal_readiness.py",
            "make verify-proactive-ooda",
        ],
        source_receipts=[
            _source_receipt(
                signal_path,
                signal,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
            _source_receipt(
                pocket_audio_path,
                pocket_audio,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
            _source_receipt(
                tg_business_path,
                tg_business,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
        ],
    )
    detect_lens["transcript_ingest_evidence"] = {
        "key": "pocket_ai_audio_transcripts",
        "status": _status(pocket_audio) or "missing",
        "transcript_ingest_ready": bool(pocket_audio.get("transcript_ingest_ready")),
        "evidence_mode": str(pocket_audio.get("evidence_mode") or "").strip(),
        "next_action": str(pocket_audio.get("next_action") or "sync_pocket_ai_audio_transcripts").strip(),
        "archive_audio_file_total": int(dict(pocket_audio.get("archive_files") or {}).get("audio_file_total") or 0),
        "archive_metadata_json_total": int(dict(pocket_audio.get("archive_files") or {}).get("metadata_json_total") or 0),
        "missing_transcript_total": int(
            dict(pocket_audio.get("database_index") or {}).get("latest_non_dismissed_missing_transcript_total") or 0
        ),
        "raw_transcript_text_exposed": bool(dict(pocket_audio.get("privacy") or {}).get("raw_transcript_text_exposed")),
        "raw_archive_root_exposed": bool(dict(pocket_audio.get("privacy") or {}).get("raw_archive_root_exposed")),
        "raw_credential_exposed": bool(dict(pocket_audio.get("privacy") or {}).get("raw_credential_exposed")),
    }
    detect_lens["telegram_business_signal_ingest"] = {
        "key": "telegram_business_secretary_bot",
        "status": _status(tg_business),
        "business_mode": bool(tg_business.get("business_mode")),
        "webhook_path": str(tg_business.get("webhook_path") or "").strip(),
        "allowed_updates": list(tg_business.get("allowed_updates") or []),
        "chat_allowlist_configured": bool(dict(tg_business.get("chat_allowlist") or {}).get("configured")),
        "bot_token_present": bool(dict(tg_business.get("bot_registry") or {}).get("token_present")),
        "ingest_secret_present": bool(dict(tg_business.get("bot_registry") or {}).get("ingest_secret_present")),
        "default_principal_present": bool(dict(tg_business.get("bot_registry") or {}).get("default_principal_present")),
        "raw_token_exposed": bool(dict(tg_business.get("privacy") or {}).get("raw_token_exposed")),
        "raw_secret_exposed": bool(dict(tg_business.get("privacy") or {}).get("raw_secret_exposed")),
        "raw_chat_ids_exposed": bool(dict(tg_business.get("privacy") or {}).get("raw_chat_ids_exposed")),
        "raw_webhook_url_exposed": bool(dict(tg_business.get("privacy") or {}).get("raw_webhook_url_exposed")),
        "next_action": str(
            dict(tg_business.get("operator_action") or {}).get("next_action")
            or "connect_telegram_business_secretary_bot_and_allowlist_chats"
        ).strip(),
    }

    decide_lens = _lens(
        key="decide",
        title="Decision and office-loop closure",
        status=_status(office),
        summary="Keep the morning brief, decision queue, commitment loop, and proactive OODA packet loop coherent enough to drive ordinary daily work and stage decision-ready approvals.",
        next_action=_compact(office.get("next_action"), default="collect_real_daily_office_loop_acceptance_evidence"),
        verifier_commands=[
            "make verify-office-loop-goal-receipt",
        ],
        source_receipts=[
            _source_receipt(
                office_path,
                office,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            )
        ],
    )

    tg_summary = (
        f"live delivery {_status(tg_live)}; readiness {_status(tg_ready)}"
        if tg_live or tg_ready
        else "Telegram audiobook live receipts are not mirrored."
    )
    wa_summary = (
        f"intake {_status(wa_intake)}; bundle {_status(wa_bundle)}; live {_status(wa_live)}; share {_status(wa_share)}; voice {_status(wa_voice)}"
        if wa_intake or wa_bundle or wa_live or wa_share or wa_voice
        else "WhatsApp audiobook receipts are not mirrored."
    )
    whatsapp_voice_shadow_required = _whatsapp_voice_shadow_required(wa_voice)
    whatsapp_component_receipts = [
        _source_receipt(
            wa_bundle_path,
            wa_bundle,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
        _source_receipt(
            wa_live_path,
            wa_live,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
        _source_receipt(
            wa_share_path,
            wa_share,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
    ]
    if whatsapp_voice_shadow_required:
        whatsapp_component_receipts.append(
            _source_receipt(
                wa_voice_path,
                wa_voice,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            )
        )

    deliver_components = [
        _deliver_component(
            key="promo_media",
            title="Promo and cinematic media",
            payload=media,
            summary="Premium public media must sound good, cover the runtime, and keep provider claims honest.",
            next_action=_compact(
                media.get("next_action"),
                default="collect_external_provider_and_public_route_proofs_before_any_gold_or_live_provider_claim",
            ),
            receipts=[
                _source_receipt(
                    media_path,
                    media,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            ],
        ),
        _deliver_component(
            key="manfred_speech",
            title="Manfred realtime speech",
            payload=manfred,
            summary=_compact(manfred.get("current_label"), default="Realtime conversation evidence is not mirrored."),
            next_action=_compact(
                manfred.get("next_action"),
                default="promote only a consented real captured STT fixture that passes the provider benchmark",
            ),
            receipts=[
                _source_receipt(
                    manfred_path,
                    manfred,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            ],
        ),
        _deliver_component(
            key="telegram_audiobook",
            title="Telegram audiobook delivery",
            payload=tg_live or tg_ready,
            summary=tg_summary,
            next_action="keep live Telegram audiobook delivery passing while widening playback acceptance evidence",
            receipts=[
                _source_receipt(
                    tg_ready_path,
                    tg_ready,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                ),
                _source_receipt(
                    tg_live_path,
                    tg_live,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                ),
            ],
        ),
        _deliver_component(
            key="whatsapp_audiobook",
            title="WhatsApp audiobook delivery",
            payload=wa_live or wa_bundle or wa_intake,
            summary=wa_summary,
            next_action="clear blocked WhatsApp live delivery and keep share-link playback plus voice-selection flow honest",
            receipts=whatsapp_component_receipts,
        ),
    ]

    deliver_has_blocker = any(_is_blocking(str(component.get("status") or "")) for component in deliver_components)
    deliver_status = "mixed_local_progress" if deliver_has_blocker else "ready_local_evidence"
    deliver_next_action = next(
        (
            _compact(component.get("next_action"))
            for component in deliver_components
            if _is_blocking(str(component.get("status") or ""))
        ),
        "keep user-facing delivery proofs current and human-reviewed",
    )
    deliver_lens = _lens(
        key="deliver",
        title="User-facing delivery",
        status=deliver_status,
        summary="Complete real user-facing loops across media, speech, and audiobook channels instead of stopping at local generation.",
        next_action=deliver_next_action,
        verifier_commands=[
            "make verify-active-media-ltd-goal-bundle",
            "make verify-manfred-realtime-conversation-readiness",
            "make verify-telegram-audiobook-live-readiness",
            "make verify-telegram-audiobook-live-delivery-receipt",
            "make verify-whatsapp-audiobook-local-intake-proof",
            "make verify-whatsapp-audiobook-operator-proof-bundle",
            "make verify-whatsapp-audiobook-live-delivery-receipt",
            "make verify-whatsapp-audiobook-public-share-playback",
        ],
        source_receipts=[],
        components=deliver_components,
        status_class="blocking" if deliver_has_blocker else "progress",
    )

    recovery_proof_status = _status(recovery_proof)
    recovery_source_receipts = [
        _source_receipt(
            recovery_path,
            recovery,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
        _source_receipt(
            recovery_proof_path,
            recovery_proof,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        ),
    ]
    recovery_proof_source_receipt = recovery_source_receipts[1]
    recovery_proof_fresh = bool(recovery_proof_source_receipt.get("source_fresh_to_current_source"))
    if recovery and recovery_proof_status == "pass" and recovery_proof_fresh:
        recover_lens = _lens(
            key="recover",
            title="Fresh-host recovery",
            status="pass",
            summary="Fresh-host-style Teable recovery proof is mirrored and passed with redacted evidence; keep it current when env/config recovery changes.",
            next_action="refresh_teable_recovery_proof_after_recovery_surface_or_secret_inventory_changes",
            verifier_commands=[
                "make verify-teable-env-recovery-readiness",
                "make materialize-teable-env-recovery-proof",
                "make verify-teable-env-recovery-proof",
                "make verify-env-teable-recovery",
                "make probe-teable-recovery",
                "make env-check-teable",
                "make env-fresh-host-teable",
                "make env-probe-teable",
            ],
            source_receipts=recovery_source_receipts,
        )
    elif recovery and recovery_proof_status == "pass":
        recover_lens = _lens(
            key="recover",
            title="Fresh-host recovery",
            status=_status(recovery),
            summary=(
                "A Teable recovery proof is mirrored and passed, but its source-state evidence is stale; "
                "refresh the recovery drill proof before keeping the recover lens at pass."
            ),
            next_action="refresh_teable_recovery_proof_after_recovery_surface_or_secret_inventory_changes",
            verifier_commands=[
                "make verify-teable-env-recovery-readiness",
                "make materialize-teable-env-recovery-proof",
                "make verify-teable-env-recovery-proof",
                "make verify-env-teable-recovery",
                "make probe-teable-recovery",
                "make env-check-teable",
                "make env-fresh-host-teable",
                "make env-probe-teable",
            ],
            source_receipts=recovery_source_receipts,
        )
    elif recovery:
        recover_lens = _lens(
            key="recover",
            title="Fresh-host recovery",
            status=_status(recovery),
            summary=_compact(
                recovery.get("summary"),
                default="Teable recovery readiness is mirrored locally, but fresh-host drill proof is still pending.",
            ),
            next_action=_compact(
                recovery.get("next_action"),
                default="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
            ),
            verifier_commands=[
                "make verify-teable-env-recovery-readiness",
                "make materialize-teable-env-recovery-proof",
                "make verify-teable-env-recovery-proof",
                "make verify-env-teable-recovery",
                "make probe-teable-recovery",
                "make env-check-teable",
                "make env-fresh-host-teable",
                "make env-probe-teable",
            ],
            source_receipts=recovery_source_receipts,
        )
    else:
        recover_lens = _lens(
            key="recover",
            title="Fresh-host recovery",
            status="command_backed_no_published_receipt",
            summary="Teable recovery has runnable operator commands, but no mirrored published recovery receipt is attached yet.",
            next_action="rehearse fresh-host Teable restore before widening claims",
            verifier_commands=[
                "make materialize-teable-env-recovery-proof",
                "make verify-teable-env-recovery-proof",
                "make probe-teable-recovery",
                "make env-check-teable",
                "make env-fresh-host-teable",
                "make verify-env-teable-recovery",
            ],
            source_receipts=[],
            status_class="blocking",
        )

    prove_lens = _lens(
        key="prove",
        title="Real-world acceptance and claim limits",
        status=_status(quality),
        summary="Keep local route confidence separate from real operator/principal acceptance before calling EA a good executive assistant.",
        next_action=_compact(
            quality.get("next_action"),
            default="collect real principal/operator acceptance that the morning brief was worth reading and one proactive OODA packet was worth approving",
        ),
        verifier_commands=[
            "make verify-executive-assistant-quality-readiness",
        ],
        source_receipts=[
            _source_receipt(
                quality_path,
                quality,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            )
        ],
    )

    lenses = [detect_lens, decide_lens, deliver_lens, recover_lens, prove_lens]
    blocking_reasons: list[str] = []
    for lens in lenses:
        if lens["key"] == "detect" and _is_blocking(_status(tg_business)):
            blocking_reasons.append(f"detect:telegram_business_signal={_status(tg_business)}")
        if lens["key"] == "deliver":
            for component in lens["components"]:
                component_status = _compact(component.get("status")).lower()
                if _is_blocking(component_status):
                    blocking_reasons.append(f"deliver:{component['key']}={component_status}")
        elif _is_blocking(str(lens["status"])):
            blocking_reasons.append(f"{lens['key']}={lens['status']}")

    if _status(quality) == "blocked_real_world_acceptance":
        overall_status = "blocked_real_world_acceptance"
    elif blocking_reasons:
        overall_status = "active_with_blockers"
    else:
        overall_status = "ready_local_direction"

    proactive_gold_status = _status(ooda_gold)
    proactive_gold_remaining = [
        str(item).strip()
        for item in list(ooda_gold.get("remaining_external_proofs") or [])
        if str(item).strip()
    ]
    proactive_gold_accepted = (
        proactive_gold_status == "pass"
        and bool(ooda_gold.get("gold_claim_allowed"))
        and not proactive_gold_remaining
        and bool(dict(dict(ooda_gold.get("proofs") or {}).get("approval_outcome") or {}).get("accepted"))
    )
    acceptance_proof_requirements = [
        _acceptance_proof_requirement(
            key="morning_brief_operator_acceptance",
            title="Morning brief operator acceptance",
            lens="prove",
            required_next_receipt=MORNING_BRIEF_ACCEPTANCE_RECEIPT,
            evidence_kind="real_operator_acceptance",
            capture_surfaces=[
                acceptance_path,
                quality_path,
            ],
            next_action="record_redacted_operator_acceptance_for_real_morning_brief",
            claim_boundary="does_not_prove_good_executive_assistant_until_real_operator_or_principal_acceptance_is_recorded",
            source_receipts=[
                _source_receipt(
                    acceptance_path,
                    acceptance,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                ),
                _source_receipt(
                    quality_path,
                    quality,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            ],
            status=_acceptance_proof_status(acceptance, "real_daily_morning_brief_accepted"),
            action_context=_manual_acceptance_action_context(
                instruction="Record redacted real-world acceptance evidence for the morning brief.",
                proof_key="real_daily_morning_brief_accepted",
                acceptance_receipt=acceptance,
            ),
        ),
        _acceptance_proof_requirement(
            key="weekly_signal_to_decision_review_acceptance",
            title="Weekly signal-to-decision review acceptance",
            lens="detect",
            required_next_receipt=WEEKLY_SIGNAL_REVIEW_ACCEPTANCE_RECEIPT,
            evidence_kind="real_review_acceptance",
            capture_surfaces=[signal_path],
            next_action="record_weekly_signal_to_decision_review_acceptance",
            claim_boundary="does_not_prove_signal_loop_value_until_a_real_operator_review_is_recorded",
            source_receipts=[
                _source_receipt(
                    signal_path,
                    signal,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            ],
            action_context=_manual_acceptance_action_context(
                instruction="Record redacted evidence that the weekly signal-to-decision review was actually reviewed.",
                evidence_part="review",
            ),
        ),
        _acceptance_proof_requirement(
            key="proactive_ooda_packet_acceptance",
            title="Proactive OODA packet approval outcome",
            lens="decide",
            required_next_receipt=PROACTIVE_OODA_ACCEPTANCE_RECEIPT,
            evidence_kind="approval_outcome",
            capture_surfaces=[ooda_gold_path, ooda_status_path],
            next_action=(
                "maintain_proactive_ooda_gold_acceptance_evidence"
                if proactive_gold_accepted
                else "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
            ),
            claim_boundary=(
                "does_not_prove_the_broader_executive_assistant_goal_until_other_real_world_acceptance_lenses_clear"
                if proactive_gold_accepted
                else "does_not_prove_assistant_grade_proactive_ooda_until_a_real_approval_outcome_is_captured"
            ),
            source_receipts=[
                _source_receipt(
                    ooda_gold_path,
                    ooda_gold,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                ),
                _source_receipt(
                    ooda_status_path,
                    ooda_status,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                ),
            ],
            status="satisfied" if proactive_gold_accepted else "pending_real_world_evidence",
        ),
    ]
    acceptance_proof_requirements.extend(
        _ea_quality_acceptance_proof_requirements(
            acceptance_receipt=acceptance,
            quality_receipt=quality,
            acceptance_path=acceptance_path,
            quality_path=quality_path,
            current_source_head=current_source_head,
            current_source_fingerprint=current_source_fingerprint,
        )
    )
    if str(recover_lens.get("status") or "").strip() != "pass":
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="fresh_host_teable_recovery_drill",
                title="Fresh-host Teable recovery drill",
                lens="recover",
                required_next_receipt=FRESH_HOST_TEABLE_RECOVERY_RECEIPT,
                evidence_kind="fresh_host_recovery_drill",
                capture_surfaces=[recovery_path, recovery_proof_path],
                next_action="run_shell_seeded_fresh_host_probe_and_mirror_drill_evidence",
                claim_boundary="does_not_prove_recovery_readiness_until_fresh_host_drill_evidence_is_mirrored",
                source_receipts=[
                    _source_receipt(
                        recovery_path,
                        recovery,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    ),
                    _source_receipt(
                        recovery_proof_path,
                        recovery_proof,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    ),
                ],
            )
        )
    if any(reason.startswith("detect:telegram_business_signal") for reason in blocking_reasons):
        tg_business_action = dict(tg_business.get("operator_action") or {})
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="telegram_business_signal_setup",
                title="Telegram Business signal ingest setup",
                lens="detect",
                required_next_receipt=TELEGRAM_BUSINESS_SIGNAL_SETUP_RECEIPT,
                evidence_kind="secretary_bot_signal_ingest_setup",
                capture_surfaces=[tg_business_path],
                next_action="connect_telegram_business_secretary_bot_and_allowlist_chats",
                claim_boundary="does_not_prove_telegram_business_signal_ingest_until_secretary_bot_is_connected_with_an_allowlisted_chat_and_business_webhook",
                action_context={
                    "user_action_required": bool(tg_business_action.get("user_action_required")),
                    "instruction": str(tg_business_action.get("instruction") or "").strip(),
                    "missing_setup": [
                        str(item).strip()
                        for item in list(tg_business_action.get("missing_setup") or [])
                        if str(item).strip()
                    ],
                    "setup_checklist": [
                        dict(item)
                        for item in list(tg_business_action.get("setup_checklist") or [])
                        if isinstance(item, dict)
                    ],
                    "telegram_message": str(tg_business_action.get("telegram_message") or "").strip(),
                    "raw_chat_ids_exposed": bool(tg_business_action.get("raw_chat_ids_exposed")),
                    "raw_token_exposed": bool(tg_business_action.get("raw_token_exposed")),
                    "raw_secret_exposed": bool(tg_business_action.get("raw_secret_exposed")),
                    "raw_voice_ids_exposed": False,
                    "callback_tokens_exposed": False,
                },
                source_receipts=[
                    _source_receipt(
                        tg_business_path,
                        tg_business,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    )
                ],
            )
        )
    if any(reason.startswith("deliver:manfred_speech") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="manfred_stt_tts_realtime_conversation",
                title="Consented Manfred realtime conversation proof",
                lens="deliver",
                required_next_receipt=MANFRED_REALTIME_ACCEPTANCE_RECEIPT,
                evidence_kind="consented_realtime_media_proof",
                capture_surfaces=[manfred_path],
                next_action="capture_consented_manfred_stt_tts_realtime_proof",
                claim_boundary="does_not_prove_realtime_speech_delivery_until_a_consented_room_conversation_receipt_passes",
                source_receipts=[
                    _source_receipt(
                        manfred_path,
                        manfred,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    )
                ],
                action_context=_manfred_realtime_action_context(manfred),
            )
        )
    if any(reason.startswith("deliver:telegram_audiobook") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="telegram_audiobook_live_delivery",
                title="Telegram audiobook live delivery receipt",
                lens="deliver",
                required_next_receipt=TELEGRAM_AUDIOBOOK_LIVE_DELIVERY_RECEIPT,
                evidence_kind="live_delivery_receipt",
                capture_surfaces=[tg_live_path, tg_ready_path],
                next_action=_compact(
                    tg_live.get("next_action") or tg_ready.get("next_action"),
                    default="capture_passing_telegram_audiobook_live_delivery_receipt",
                ),
                claim_boundary="does_not_prove_telegram_audiobook_delivery_until_live_delivery_and_playback_receipts_pass",
                action_context=_telegram_audiobook_action_context(tg_live),
                source_receipts=[
                    _source_receipt(
                        tg_live_path,
                        tg_live,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    ),
                    _source_receipt(
                        tg_ready_path,
                        tg_ready,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    ),
                ],
            )
        )
    if any(reason.startswith("deliver:whatsapp_audiobook") for reason in blocking_reasons):
        whatsapp_acceptance_receipts = [
            _source_receipt(
                wa_live_path,
                wa_live,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
            _source_receipt(
                wa_bundle_path,
                wa_bundle,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
            _source_receipt(
                wa_share_path,
                wa_share,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
        ]
        if whatsapp_voice_shadow_required:
            whatsapp_acceptance_receipts.append(
                _source_receipt(
                    wa_voice_path,
                    wa_voice,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            )
        whatsapp_action_context = {}
        if any(
            str(reason or "").startswith("deliver:whatsapp_audiobook=blocked_stale_source_evidence")
            for reason in blocking_reasons
        ):
            whatsapp_action_context = _stale_source_action_context(
                receipts=whatsapp_acceptance_receipts,
                refresh_commands=[
                    "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
                    "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
                    "PYTHONPATH=ea python3 ea/scripts/verify_whatsapp_audiobook_public_share_playback.py",
                    "python3 scripts/materialize_continuous_improvement_goal_posture.py",
                    "python3 scripts/verify_continuous_improvement_goal_posture.py --pretty",
                ],
            )
        elif any(str(reason or "").startswith("deliver:whatsapp_audiobook=failed") for reason in blocking_reasons):
            whatsapp_action_context = _whatsapp_playback_failure_action_context(wa_share)
        elif _whatsapp_live_playback_blocked(wa_live, blocking_reasons):
            whatsapp_action_context = _whatsapp_live_playback_blocked_action_context(
                live_receipt=wa_live,
                playback_receipt=wa_share,
            )
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="whatsapp_audiobook_live_delivery",
                title="WhatsApp audiobook live delivery receipt",
                lens="deliver",
                required_next_receipt=WHATSAPP_AUDIOBOOK_LIVE_DELIVERY_RECEIPT,
                evidence_kind="live_delivery_receipt",
                capture_surfaces=[wa_live_path, wa_bundle_path, wa_share_path, wa_voice_path],
                next_action="capture_passing_whatsapp_audiobook_live_delivery_receipt",
                claim_boundary="does_not_prove_whatsapp_delivery_until_live_delivery_and_playback_receipts_pass",
                source_receipts=whatsapp_acceptance_receipts,
                action_context=whatsapp_action_context,
            )
        )
    required_next_receipts = [
        str(requirement.get("required_next_receipt") or "").strip()
        for requirement in acceptance_proof_requirements
        if str(requirement.get("required_next_receipt") or "").strip()
        and str(requirement.get("status") or "").strip() != "satisfied"
    ]
    operator_action_queue = _operator_action_queue(acceptance_proof_requirements)
    next_operator_action = operator_action_queue[0] if operator_action_queue else {}
    operator_delivery_policy = _operator_delivery_policy(operator_action_queue)

    receipt = {
        "contract_name": "ea.continuous_improvement_goal_posture.v1",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_continuous_improvement_goal_posture.py",
        "source_git_head": current_source_head,
        "head_semantics": "source_state",
        "source_state_fingerprint": current_source_fingerprint,
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": _display_path(root, output_path),
        "goal_doc": ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md",
        "goal_shorthand": "Make EA the user's dependable executive operating system: paid-human-assistant-grade proactive OODA with transcript-aware ingest, auditor-passed decision-ready packets, staged follow-through, Teable-mirrored current/stale state, self-healing, and governed by owning truth planes rather than assistant-local lore.",
        "execution_lenses": [lens["key"] for lens in lenses],
        "overall_status": overall_status,
        "goal_completion_claim_allowed": False,
        "real_use_claim_allowed": overall_status == "ready_local_direction" and _status(quality) == "pass",
        "lenses": lenses,
        "blocking_reasons": blocking_reasons,
        "required_next_receipts": required_next_receipts,
        "acceptance_proof_requirements": acceptance_proof_requirements,
        "operator_action_queue": operator_action_queue,
        "operator_delivery_policy": operator_delivery_policy,
        "next_action": str(next_operator_action.get("next_action") or "").strip(),
        "next_action_href": str(next_operator_action.get("next_action_href") or "").strip(),
        "next_action_label": str(next_operator_action.get("next_action_label") or "").strip(),
        "next_action_method": str(next_operator_action.get("next_action_method") or "").strip(),
        "next_action_form_href": str(next_operator_action.get("next_action_form_href") or "").strip(),
        "next_action_form_label": str(next_operator_action.get("next_action_form_label") or "").strip(),
        "next_action_form_method": str(next_operator_action.get("next_action_form_method") or "").strip(),
        "next_action_key": str(next_operator_action.get("key") or "").strip(),
        "next_action_instruction": str(next_operator_action.get("instruction") or "").strip(),
        "rules": [
            "Local route receipts and operator commands may guide work, but they do not by themselves prove real daily usefulness.",
            "Irreversible purchases, bookings, cancellations, outbound commitments, and sent messages must stay consent-gated even when proactive OODA staging is automated.",
            "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something.",
            "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient.",
            "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved.",
            "The recover lens may use a mirrored local readiness receipt, but it must not claim pass until a source-fresh fresh-host Teable recovery drill receipt is mirrored.",
            "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth.",
            "The prove lens controls good-executive-assistant overclaims; if it is blocked, the goal stays open.",
        ],
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the long-running continuous-improvement goal posture receipt.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_path = args.output if args.output.is_absolute() else args.root / args.output
    receipt = build_goal_posture(root=args.root, output_path=output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
