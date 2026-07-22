from __future__ import annotations

import urllib.parse

from app.services.public_urls import ea_public_app_base_url


DEFAULT_GOOGLE_REAUTH_RETURN_TO = "/app/settings/google"
DEFAULT_GOOGLE_REAUTH_SCOPE_BUNDLE = "full_workspace"
DEFAULT_GOOGLE_SYNC_RETURN_TO = "/app/settings/google"
DEFAULT_WHATSAPP_RECOVERY_PATH = "/integrations/whatsapp"
DEFAULT_APPROVAL_CAPTURE_PATH = "/admin/proactive-ooda/approval"
DEFAULT_APPROVAL_REISSUE_PATH = "/admin/actions/proactive-ooda-reissue"
DEFAULT_QUEUE_REVIEW_PATH = "/app/queue"
DEFAULT_POCKET_SYNC_PATH = "/app/api/signals/pocket/sync?limit=10"
DEFAULT_PROACTIVE_OODA_REVIEW_PATH = "/app/today"
DEFAULT_ADMIN_GOALS_PATH = "/admin/goals"


def _absolute_public_href(path: str, *, public_base_url: str = "") -> str:
    normalized_path = str(path or "").strip()
    if not normalized_path:
        return ""
    if normalized_path.startswith(("http://", "https://")):
        return normalized_path
    base_url = str(public_base_url or ea_public_app_base_url()).strip().rstrip("/")
    if not base_url:
        return normalized_path
    return urllib.parse.urljoin(f"{base_url}/", normalized_path.lstrip("/"))


def _surface(path: str, label: str, *, method: str = "get", public_base_url: str = "") -> dict[str, str]:
    return {
        "href": _absolute_public_href(path, public_base_url=public_base_url),
        "label": str(label or "").strip(),
        "method": str(method or "").strip().lower(),
    }


def proactive_next_action_surface(action: str, *, public_base_url: str = "") -> dict[str, str]:
    normalized = str(action or "").strip()
    if normalized in {
        "maintain_proactive_ooda_runtime",
        "wait_for_notification_cooldown",
        "repair_proactive_context_grounding",
        "refresh_relationship_and_occasion_sources",
        "sync_shopping_and_vendor_sources",
        "sync_commitment_and_deadline_sources",
        "refresh_principal_profile_context",
    }:
        return _surface(
            DEFAULT_PROACTIVE_OODA_REVIEW_PATH,
            "Open Today",
            public_base_url=public_base_url,
        )
    if normalized in {
        "review_proactive_draft_queue",
        "collect_live_browse_backed_safe_work_result",
        "stage_one_chosen_candidate_for_user_decision",
        "persist_one_reversible_staged_artifact",
        "stage_fresh_assistant_grade_proactive_packet",
        "repair_proactive_browser_action_handoff_contract",
        "improve_proactive_packet_quality_and_collect_a_new_acceptance_outcome",
        "complete_browser_handoff_then_resume_ooda_task",
    }:
        return _surface(
            DEFAULT_QUEUE_REVIEW_PATH,
            "Resume browser handoff" if normalized == "complete_browser_handoff_then_resume_ooda_task" else "Open queue",
            public_base_url=public_base_url,
        )
    if normalized == "reauthorize_google_workspace_binding":
        path = "/app/actions/google/connect?" + urllib.parse.urlencode(
            {
                "return_to": DEFAULT_GOOGLE_REAUTH_RETURN_TO,
                "scope_bundle": DEFAULT_GOOGLE_REAUTH_SCOPE_BUNDLE,
            }
        )
        return _surface(
            path,
            "Reconnect Google workspace",
            public_base_url=public_base_url,
        )
    if normalized in {
        "reauthorize_or_sync_google_workspace_sources",
        "sync_calendar_and_renewal_sources",
    }:
        path = "/app/actions/signals/google/sync?" + urllib.parse.urlencode(
            {"return_to": DEFAULT_GOOGLE_SYNC_RETURN_TO}
        )
        label = "Sync calendar signals" if normalized == "sync_calendar_and_renewal_sources" else "Sync Google workspace"
        return _surface(path, label, public_base_url=public_base_url)
    if normalized in {"scan_whatsapp_web_qr", "restore_whatsapp_web_session"}:
        return _surface(
            DEFAULT_WHATSAPP_RECOVERY_PATH,
            "Open WhatsApp pairing",
            public_base_url=public_base_url,
        )
    if normalized in {
        "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        "record_proactive_ooda_approval_outcome",
    }:
        return _surface(
            DEFAULT_APPROVAL_CAPTURE_PATH,
            "Record packet verdict",
            public_base_url=public_base_url,
        )
    if normalized == "repair_proactive_approval_capture":
        return _surface(
            DEFAULT_ADMIN_GOALS_PATH,
            "Open goals",
            public_base_url=public_base_url,
        )
    if normalized == "reissue_proactive_approval":
        return _surface(
            DEFAULT_APPROVAL_REISSUE_PATH,
            "Reissue approval prompt",
            method="post",
            public_base_url=public_base_url,
        )
    if normalized == "cleanup_proactive_approval_callbacks":
        return _surface(
            DEFAULT_ADMIN_GOALS_PATH,
            "Open goals",
            public_base_url=public_base_url,
        )
    if normalized == "repair_proactive_safe_work_audit":
        return _surface(
            DEFAULT_QUEUE_REVIEW_PATH,
            "Review safe work",
            public_base_url=public_base_url,
        )
    if normalized == "sync_pocket_ai_audio_transcripts":
        return _surface(
            DEFAULT_POCKET_SYNC_PATH,
            "Sync Pocket transcripts",
            method="post",
            public_base_url=public_base_url,
        )
    if normalized in {
        "verify_postgres_observation_source",
        "probe_proactive_source_coverage",
        "inspect_teable_projection",
        "inspect_pocket_sync_runtime",
        "repair_proactive_signal_source",
        "resume_onemin_direct_refresh",
        "resume_onemin_direct_refresh_after_cooldown",
        "review_onemin_refresh_errors_and_resume",
        "inspect_onemin_direct_refresh_runtime",
        "repair_onemin_owner_ledger_projection",
        "configure_onemin_default_password",
        "repair_provider_cost_routing",
        "mirror_the_proactive_packet_into_teable",
        "send_or_mirror_one_real_proactive_packet_with_routed_delivery_proof",
        "prove_proactive_delivery_only_notifies_for_user_action",
        "maintain_proactive_ooda_gold_acceptance_evidence",
        "repair_proactive_operator_runtime_posture",
    }:
        return _surface(
            DEFAULT_ADMIN_GOALS_PATH,
            "Open goals",
            public_base_url=public_base_url,
        )
    return {"href": "", "label": "", "method": ""}
