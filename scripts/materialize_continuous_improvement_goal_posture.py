#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

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
DEFAULT_GOOGLE_WORKSPACE_OAUTH_READINESS = ROOT / ".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json"
DEFAULT_PUSHBULLET_DELIVERY_READINESS = ROOT / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
DEFAULT_OPERATOR_READINESS = ROOT / ".codex-studio/published/ea_operator_readiness.generated.json"
DEFAULT_TELEGRAM_AUDIOBOOK_READINESS = ROOT / ".codex-studio/published/telegram_audiobook_live_readiness.generated.json"
DEFAULT_TELEGRAM_AUDIOBOOK_DELIVERY = ROOT / ".codex-studio/published/telegram_audiobook_live_delivery.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_INTAKE = ROOT / ".codex-studio/published/whatsapp_audiobook_local_intake_proof.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_BUNDLE = ROOT / ".codex-studio/published/whatsapp_audiobook_operator_proof_bundle.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_DELIVERY = ROOT / ".codex-studio/published/whatsapp_audiobook_live_delivery.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_SHARE = ROOT / ".codex-studio/published/whatsapp_audiobook_public_share_playback.generated.json"
DEFAULT_WHATSAPP_AUDIOBOOK_VOICE = ROOT / ".codex-studio/published/whatsapp_audiobook_live_voice_selection_shadow.generated.json"
DEFAULT_WHATSAPP_WEB_ACTION_PROCESSOR_READINESS = (
    ROOT / ".codex-studio/published/whatsapp_web_action_processor_readiness.generated.json"
)
DEFAULT_MYMEDIA_ALEXA_READINESS = ROOT / ".codex-studio/published/mymedia_alexa_readiness.generated.json"
RUNTIME_LEDGER_DIR_ENV = "EA_RESPONSES_PROVIDER_LEDGER_DIR"
RUNTIME_LEDGER_HOST_DIR_ENV = "EA_RESPONSES_PROVIDER_LEDGER_HOST_DIR"
DEFAULT_RUNTIME_LEDGER_DIR = Path("/data/provider-ledger")
RUNTIME_LEDGER_RECEIPT_ALIASES = {
    DEFAULT_PUSHBULLET_DELIVERY_READINESS.relative_to(ROOT).as_posix(): "pushbullet_readiness.generated.json",
}
RUNTIME_LEDGER_DOCKER_CONTAINERS = ("ea-scheduler", "ea-api")

OPERATOR_STREAM_OFFICE_LOOP = "office_loop"
OPERATOR_STREAM_OFFICE_SETUP = "office_setup"
OPERATOR_STREAM_RECOVERY = "recovery"
OPERATOR_STREAM_MEDIA_MEMORIAL = "media_memorial"
DEFAULT_ACTION_DIGEST_STREAMS = (
    OPERATOR_STREAM_OFFICE_LOOP,
    OPERATOR_STREAM_OFFICE_SETUP,
    OPERATOR_STREAM_RECOVERY,
)
DEFAULT_GOOGLE_REAUTH_RETURN_TO = "/app/settings/google"
DEFAULT_GOOGLE_REAUTH_SCOPE_BUNDLE = "full_workspace"
DEFAULT_GOOGLE_REAUTH_ACTION_HREF = "/app/actions/google/connect?" + urllib.parse.urlencode(
    {
        "return_to": DEFAULT_GOOGLE_REAUTH_RETURN_TO,
        "scope_bundle": DEFAULT_GOOGLE_REAUTH_SCOPE_BUNDLE,
    }
)
GOOGLE_REAUTH_NEXT_ACTIONS = {
    "add_google_oauth_test_user_and_retry_full_workspace_auth",
    "retry_full_workspace_auth_with_approved_account",
    "retry_full_workspace_auth_with_expected_account",
    "reauthorize_google_workspace_binding",
}

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
GOOGLE_WORKSPACE_OAUTH_SETUP_RECEIPT = "Google Workspace OAuth test-user or verified app access for Full Workspace auth"
PUSHBULLET_DELIVERY_SETUP_RECEIPT = "Pushbullet delivery clients configured and live-verifiable for action-required delivery"
MYMEDIA_ALEXA_SETUP_RECEIPT = (
    "passing My Media for Alexa readiness receipt with pairing complete, watch-folder posture repaired, and no blocked runtime state"
)
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
        "label": "Record packet verdict",
        "method": "get",
    },
    "record_proactive_ooda_approval_outcome": {
        "href": "/admin/proactive-ooda/approval",
        "label": "Record packet verdict",
        "method": "get",
    },
    "stage_fresh_assistant_grade_proactive_packet": {
        "href": "/app/queue",
        "label": "Open queue",
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
    "add_google_oauth_test_user_and_retry_full_workspace_auth": {
        "href": DEFAULT_GOOGLE_REAUTH_ACTION_HREF,
        "label": "Open Google setup",
        "method": "get",
    },
    "retry_full_workspace_auth_with_approved_account": {
        "href": DEFAULT_GOOGLE_REAUTH_ACTION_HREF,
        "label": "Retry Google auth",
        "method": "get",
    },
    "retry_full_workspace_auth_with_expected_account": {
        "href": DEFAULT_GOOGLE_REAUTH_ACTION_HREF,
        "label": "Retry Google auth",
        "method": "get",
    },
    "reauthorize_google_workspace_binding": {
        "href": DEFAULT_GOOGLE_REAUTH_ACTION_HREF,
        "label": "Reconnect Google workspace",
        "method": "get",
    },
    "create_missing_pushbullet_access_tokens": {
        "href": "https://www.pushbullet.com/#settings/account",
        "label": "Open Pushbullet account settings",
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
    "choose_explicit_replacement_voice_or_restore_selected_provider": {
        "href": "/integrations/telegram",
        "label": "Open Telegram",
        "method": "get",
    },
    "choose_one_telegram_audiobook_voice_sample": {
        "href": "/integrations/telegram",
        "label": "Open Telegram",
        "method": "get",
    },
    "send_missing_telegram_audiobook_voice_samples_before_user_choice": {
        "href": "/app/channel-loop",
        "label": "Open channel loop",
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
    explicit_form_href = str(action_context.get("next_action_form_href") or "").strip()
    explicit_form_label = str(action_context.get("next_action_form_label") or "").strip()
    explicit_form_method = str(action_context.get("next_action_form_method") or "").strip().lower()
    if explicit_form_href and explicit_form_method == "get":
        return {
            "next_action_form_href": explicit_form_href,
            "next_action_form_label": explicit_form_label,
            "next_action_form_method": "get",
        }
    surface = ACTION_SURFACES.get(next_action, {})
    href = str(surface.get("href") or "").strip()
    method = str(surface.get("method") or "").strip().lower()
    if href == "/admin/actions/acceptance-evidence":
        form_href = str(action_context.get("next_action_form_href") or "").strip()
        if not form_href:
            form_href = _acceptance_form_href(str(action_context.get("proof_key") or "").strip())
        return {
            "next_action_form_href": form_href,
            "next_action_form_label": str(
                action_context.get("next_action_form_label") or surface.get("label") or ""
            ).strip(),
            "next_action_form_method": "get",
        }
    if href == "/admin/actions/signal-to-decision-evidence":
        form_href = str(action_context.get("next_action_form_href") or "").strip()
        if not form_href:
            form_href = _signal_form_href(str(action_context.get("evidence_part") or "review").strip())
        return {
            "next_action_form_href": form_href,
            "next_action_form_label": str(
                action_context.get("next_action_form_label") or surface.get("label") or ""
            ).strip(),
            "next_action_form_method": "get",
        }
    return {
        "next_action_form_href": href if method == "get" else "",
        "next_action_form_label": str(surface.get("label") or "").strip() if method == "get" else "",
        "next_action_form_method": method if method == "get" else "",
    }


def _canonical_next_action_href(
    next_action: str,
    *,
    action_href: str,
    form_surface: dict[str, str],
) -> str:
    if next_action not in GOOGLE_REAUTH_NEXT_ACTIONS:
        return action_href
    form_href = str(form_surface.get("next_action_form_href") or "").strip()
    form_method = str(form_surface.get("next_action_form_method") or "").strip().lower()
    if form_href and form_method == "get":
        return form_href
    return action_href


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


def _text(value: object) -> str:
    return _compact(value, default="")


def _status(payload: dict[str, Any], default: str = "missing_receipt") -> str:
    return _compact(payload.get("status"), default=default).lower()


def _provider_cost_control_from_office(office: dict[str, Any]) -> dict[str, Any]:
    posture = dict(office.get("provider_cost_routing_posture") or {})
    if not posture and not office:
        posture = {
            "status": "active_cost_control",
            "background_routing": {
                "primary_background_provider": "onemin",
                "primary_background_provider_label": "1min.ai",
                "default_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "fast_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
                "cost_sensitive_lanes": ["groundwork", "fast", "overflow", "review", "review_light", "audit"],
                "onemin_preferred_when_speed_is_not_critical": True,
                "onemin_preferred_whenever_usable": True,
            },
            "gemini_vertex": {
                "provider_key": "gemini_vortex",
                "token_tracking_required": True,
                "dispatch_ledger": "provider_dispatch_events.jsonl",
                "live_pressure_probe_command": "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json",
                "live_pressure_probe_source": "runtime_container_exec:provider_ledger_cache",
                "soft_cap_env": "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H",
                "soft_cap_window_env": "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS",
                "soft_cap_action": "remove_gemini_vortex_from_cost_gated_background_candidate_lists",
                "explicit_gemini_requests_allowed": True,
                "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
            },
            "privacy": {
                "raw_provider_secret_exposed": False,
                "raw_prompt_or_response_text_exposed": False,
                "raw_google_cloud_billing_account_exposed": False,
            },
        }
    background = dict(posture.get("background_routing") or {})
    gemini = dict(posture.get("gemini_vertex") or {})
    privacy = dict(posture.get("privacy") or {})
    return {
        "status": str(posture.get("status") or "missing").strip(),
        "source": "ea_office_loop_goal.provider_cost_routing_posture",
        "primary_background_provider": str(background.get("primary_background_provider") or "").strip(),
        "primary_background_provider_label": str(background.get("primary_background_provider_label") or "").strip(),
        "default_provider_order": [
            str(item).strip()
            for item in list(background.get("default_provider_order") or [])
            if str(item).strip()
        ],
        "fast_provider_order": [
            str(item).strip()
            for item in list(background.get("fast_provider_order") or [])
            if str(item).strip()
        ],
        "cheap_provider_order": [
            str(item).strip()
            for item in list(background.get("cheap_provider_order") or [])
            if str(item).strip()
        ],
        "groundwork_provider_order": [
            str(item).strip()
            for item in list(background.get("groundwork_provider_order") or [])
            if str(item).strip()
        ],
        "hard_provider_order": [
            str(item).strip()
            for item in list(background.get("hard_provider_order") or [])
            if str(item).strip()
        ],
        "cost_sensitive_lanes": [
            str(item).strip()
            for item in list(background.get("cost_sensitive_lanes") or [])
            if str(item).strip()
        ],
        "onemin_preferred_when_speed_is_not_critical": bool(
            background.get("onemin_preferred_when_speed_is_not_critical")
        ),
        "onemin_preferred_whenever_usable": bool(background.get("onemin_preferred_whenever_usable")),
        "gemini_provider_key": str(gemini.get("provider_key") or "").strip(),
        "gemini_token_tracking_required": bool(gemini.get("token_tracking_required")),
        "gemini_dispatch_ledger": str(gemini.get("dispatch_ledger") or "").strip(),
        "gemini_live_pressure_probe_command": str(gemini.get("live_pressure_probe_command") or "").strip(),
        "gemini_live_pressure_probe_source": str(gemini.get("live_pressure_probe_source") or "").strip(),
        "gemini_soft_cap_env": str(gemini.get("soft_cap_env") or "").strip(),
        "gemini_soft_cap_window_env": str(gemini.get("soft_cap_window_env") or "").strip(),
        "gemini_soft_cap_action": str(gemini.get("soft_cap_action") or "").strip(),
        "explicit_gemini_requests_allowed": bool(gemini.get("explicit_gemini_requests_allowed")),
        "billing_truth_boundary": str(gemini.get("billing_truth_boundary") or "").strip(),
        "raw_provider_secret_exposed": bool(privacy.get("raw_provider_secret_exposed")),
        "raw_prompt_or_response_text_exposed": bool(privacy.get("raw_prompt_or_response_text_exposed")),
        "raw_google_cloud_billing_account_exposed": bool(privacy.get("raw_google_cloud_billing_account_exposed")),
    }


def _provider_cost_pressure_from_operator_status(ooda_status: dict[str, Any]) -> dict[str, Any]:
    provider_cost = dict(ooda_status.get("provider_cost_pressure") or {})
    if not provider_cost:
        return {
            "present": False,
            "checked": False,
            "status": "missing",
            "source": "",
            "observed_at": "",
            "primary_background_provider": "",
            "provider_order": [],
            "fast_provider_order": [],
            "cheap_provider_order": [],
            "groundwork_provider_order": [],
            "hard_provider_order": [],
            "onemin_preferred_when_speed_is_not_critical": False,
            "onemin_preferred_whenever_usable": False,
            "onemin_usable": False,
            "onemin_ready_slots": 0,
            "gemini_provider_key": "gemini_vortex",
            "gemini_24h_total_tokens": 0,
            "gemini_24h_soft_cap_tokens": 0,
            "gemini_background_cost_gate": "",
            "requires_recovery": False,
            "raw_provider_secret_exposed": False,
            "raw_prompt_or_response_text_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
            "raw_provider_slots_exposed": False,
        }
    gemini = dict(provider_cost.get("gemini_token_tracking") or {})
    window_24h = dict(gemini.get("24h") or {})
    privacy = dict(provider_cost.get("privacy") or {})
    return {
        "present": True,
        "checked": bool(provider_cost.get("checked")),
        "status": str(provider_cost.get("status") or "").strip(),
        "source": str(provider_cost.get("source") or "").strip(),
        "observed_at": str(provider_cost.get("observed_at") or "").strip(),
        "primary_background_provider": str(provider_cost.get("primary_background_provider") or "").strip(),
        "provider_order": [
            str(item).strip()
            for item in list(provider_cost.get("provider_order") or [])
            if str(item).strip()
        ],
        "fast_provider_order": [
            str(item).strip()
            for item in list(provider_cost.get("fast_provider_order") or [])
            if str(item).strip()
        ],
        "cheap_provider_order": [
            str(item).strip()
            for item in list(provider_cost.get("cheap_provider_order") or [])
            if str(item).strip()
        ],
        "groundwork_provider_order": [
            str(item).strip()
            for item in list(provider_cost.get("groundwork_provider_order") or [])
            if str(item).strip()
        ],
        "hard_provider_order": [
            str(item).strip()
            for item in list(provider_cost.get("hard_provider_order") or [])
            if str(item).strip()
        ],
        "cost_sensitive_lanes": [
            str(item).strip()
            for item in list(provider_cost.get("cost_sensitive_lanes") or [])
            if str(item).strip()
        ],
        "onemin_preferred_when_speed_is_not_critical": bool(
            provider_cost.get("onemin_preferred_when_speed_is_not_critical")
        ),
        "onemin_preferred_whenever_usable": bool(provider_cost.get("onemin_preferred_whenever_usable")),
        "onemin_usable": bool(provider_cost.get("onemin_usable")),
        "onemin_ready_slots": int(provider_cost.get("onemin_ready_slots") or 0),
        "onemin_configured_slots": int(provider_cost.get("onemin_configured_slots") or 0),
        "gemini_provider_key": str(provider_cost.get("gemini_provider_key") or "gemini_vortex").strip(),
        "gemini_billing_truth_boundary": str(gemini.get("billing_truth_boundary") or "").strip(),
        "gemini_24h_request_count": int(window_24h.get("request_count") or 0),
        "gemini_24h_tokens_in": int(window_24h.get("tokens_in") or 0),
        "gemini_24h_tokens_out": int(window_24h.get("tokens_out") or 0),
        "gemini_24h_total_tokens": int(window_24h.get("total_tokens") or 0),
        "gemini_24h_soft_cap_tokens": int(window_24h.get("soft_cap_tokens") or 0),
        "gemini_24h_state": str(window_24h.get("state") or "").strip(),
        "gemini_soft_cap_percent_24h": gemini.get("soft_cap_percent_24h"),
        "gemini_background_cost_gate": str(gemini.get("background_cost_gate") or "").strip(),
        "explicit_gemini_requests_allowed": bool(gemini.get("explicit_gemini_requests_allowed")),
        "routing_decision": str(provider_cost.get("routing_decision") or "").strip(),
        "requires_recovery": bool(provider_cost.get("requires_recovery")),
        "raw_provider_secret_exposed": bool(privacy.get("raw_provider_secret_exposed")),
        "raw_prompt_or_response_text_exposed": bool(privacy.get("raw_prompt_or_response_text_exposed")),
        "raw_google_cloud_billing_account_exposed": bool(privacy.get("raw_google_cloud_billing_account_exposed")),
        "raw_provider_slots_exposed": bool(privacy.get("raw_provider_slots_exposed")),
    }


@lru_cache(maxsize=1)
def _ea_live_ops_module() -> Any:
    script_path = Path(__file__).resolve().parent / "ea_live_ops.py"
    repo_root = script_path.parent.parent
    for candidate in (repo_root / "ea", repo_root, script_path.parent):
        candidate_text = candidate.as_posix()
        if candidate.exists() and candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)
    spec = importlib.util.spec_from_file_location("ea_live_ops_goal_posture_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ea_live_ops_script_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _provider_cost_pressure_needs_live_probe(provider_cost: dict[str, Any]) -> bool:
    if not provider_cost:
        return True
    if not bool(provider_cost.get("checked")):
        return True
    if not str(provider_cost.get("primary_background_provider") or "").strip():
        return True
    if not list(provider_cost.get("provider_order") or []):
        return True
    gemini = dict(provider_cost.get("gemini_token_tracking") or {})
    if not str(gemini.get("billing_truth_boundary") or "").strip():
        return True
    if not str(gemini.get("background_cost_gate") or "").strip():
        return True
    if gemini.get("explicit_gemini_requests_allowed") is not True:
        return True
    return False


def _live_provider_cost_pressure_probe(*, timeout_seconds: float = 20.0) -> dict[str, Any]:
    try:
        module = _ea_live_ops_module()
        payload = module.probe_provider_cost_pressure(
            window="24h",
            output_format="json",
            timeout_seconds=float(timeout_seconds),
        )
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _provider_cost_pressure_from_live_probe(probe: dict[str, Any]) -> dict[str, Any]:
    if not probe:
        return {}
    gemini = dict(probe.get("gemini_token_tracking") or {})
    window_24h = dict(gemini.get("24h") or {})
    privacy = dict(probe.get("privacy") or {})
    return {
        "present": True,
        "checked": True,
        "status": str(probe.get("status") or "").strip(),
        "source": str(probe.get("source") or "").strip(),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "primary_background_provider": str(probe.get("primary_background_provider") or "").strip(),
        "provider_order": [
            str(item).strip()
            for item in list(probe.get("provider_order") or [])
            if str(item).strip()
        ],
        "fast_provider_order": [
            str(item).strip()
            for item in list(probe.get("fast_provider_order") or [])
            if str(item).strip()
        ],
        "cheap_provider_order": [
            str(item).strip()
            for item in list(probe.get("cheap_provider_order") or [])
            if str(item).strip()
        ],
        "groundwork_provider_order": [
            str(item).strip()
            for item in list(probe.get("groundwork_provider_order") or [])
            if str(item).strip()
        ],
        "hard_provider_order": [
            str(item).strip()
            for item in list(probe.get("hard_provider_order") or [])
            if str(item).strip()
        ],
        "cost_sensitive_lanes": [
            str(item).strip()
            for item in list(probe.get("cost_sensitive_lanes") or [])
            if str(item).strip()
        ],
        "onemin_preferred_when_speed_is_not_critical": bool(
            probe.get("onemin_preferred_when_speed_is_not_critical")
        ),
        "onemin_preferred_whenever_usable": bool(probe.get("onemin_preferred_whenever_usable")),
        "onemin_usable": bool(probe.get("onemin_usable")),
        "onemin_ready_slots": int(probe.get("onemin_ready_slots") or 0),
        "onemin_configured_slots": int(probe.get("onemin_configured_slots") or 0),
        "gemini_provider_key": str(probe.get("gemini_provider_key") or "gemini_vortex").strip(),
        "gemini_24h_request_count": int(window_24h.get("request_count") or 0),
        "gemini_24h_tokens_in": int(window_24h.get("tokens_in") or 0),
        "gemini_24h_tokens_out": int(window_24h.get("tokens_out") or 0),
        "gemini_24h_total_tokens": int(window_24h.get("total_tokens") or 0),
        "gemini_24h_soft_cap_tokens": int(window_24h.get("soft_cap_tokens") or 0),
        "gemini_24h_state": str(window_24h.get("state") or "").strip(),
        "gemini_soft_cap_percent_24h": gemini.get("soft_cap_percent_24h"),
        "gemini_background_cost_gate": str(gemini.get("background_cost_gate") or "").strip(),
        "explicit_gemini_requests_allowed": bool(gemini.get("explicit_gemini_requests_allowed")),
        "gemini_billing_truth_boundary": str(gemini.get("billing_truth_boundary") or "").strip(),
        "requires_recovery": bool(probe.get("requires_recovery")),
        "raw_provider_secret_exposed": bool(privacy.get("raw_provider_secret_exposed")),
        "raw_prompt_or_response_text_exposed": bool(privacy.get("raw_prompt_or_response_text_exposed")),
        "raw_google_cloud_billing_account_exposed": bool(privacy.get("raw_google_cloud_billing_account_exposed")),
        "raw_provider_slots_exposed": bool(privacy.get("raw_provider_slots_exposed")),
    }


def _decide_provider_cost_pressure(
    ooda_status: dict[str, Any],
    *,
    live_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operator_status_projection = _provider_cost_pressure_from_operator_status(ooda_status)
    if not _provider_cost_pressure_needs_live_probe(dict(ooda_status.get("provider_cost_pressure") or {})):
        return operator_status_projection
    live_projection = _provider_cost_pressure_from_live_probe(live_probe or {})
    if live_projection.get("checked") is True:
        return live_projection
    return operator_status_projection


def _is_blocking(status: str) -> bool:
    normalized = _compact(status).lower()
    return (
        normalized.startswith(BLOCKING_PREFIXES)
        or normalized in {"command_backed_no_published_receipt", "ready_retry_required", "ready_manual_console_check"}
    )


def _load_receipt(root: Path, path: Path) -> tuple[dict[str, Any], str]:
    published_candidates = [path]
    runtime_candidates: list[Path] = []
    allow_docker_runtime_fallback = root.resolve() == ROOT.resolve()
    try:
        relative_key = path.relative_to(root).as_posix()
    except ValueError:
        relative_key = ""
    runtime_filename = RUNTIME_LEDGER_RECEIPT_ALIASES.get(relative_key, "")
    if runtime_filename:
        runtime_dirs: list[Path] = []
        for env_name in (RUNTIME_LEDGER_HOST_DIR_ENV, RUNTIME_LEDGER_DIR_ENV):
            configured_dir = str(os.environ.get(env_name) or "").strip()
            if configured_dir:
                runtime_dirs.append(Path(configured_dir))
        runtime_dirs.append(DEFAULT_RUNTIME_LEDGER_DIR)
        if allow_docker_runtime_fallback:
            for container_name in RUNTIME_LEDGER_DOCKER_CONTAINERS:
                try:
                    result = subprocess.run(
                        [
                            "docker",
                            "inspect",
                            "--format",
                            "{{range .Mounts}}{{if eq .Destination \"/data/provider-ledger\"}}{{.Source}}{{println}}{{end}}{{end}}",
                            container_name,
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                except Exception:
                    result = None
                if result and result.returncode == 0:
                    for raw_line in result.stdout.splitlines():
                        candidate = str(raw_line or "").strip()
                        if candidate:
                            runtime_dirs.append(Path(candidate))
        docker_volume_root = Path("/var/lib/docker/volumes")
        try:
            docker_volume_dirs = sorted(docker_volume_root.glob("*ea_provider_ledger*/_data"))
        except (OSError, PermissionError):
            docker_volume_dirs = []
        runtime_dirs.extend(docker_volume_dirs)
        seen_runtime_dirs: set[Path] = set()
        for base_dir in runtime_dirs:
            if base_dir in seen_runtime_dirs:
                continue
            seen_runtime_dirs.add(base_dir)
            candidate = base_dir / runtime_filename
            if candidate not in runtime_candidates:
                runtime_candidates.append(candidate)

    def _select_best(candidates: list[Path]) -> tuple[dict[str, Any], Path | None]:
        selected_payload: dict[str, Any] = {}
        selected_path: Path | None = None
        selected_generated_at = ""
        selected_mtime = -1.0
        for candidate in candidates:
            payload = _json(candidate)
            if not payload:
                continue
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                mtime = -1.0
            generated_at = str(payload.get("generated_at") or "").strip()
            if (
                not selected_payload
                or generated_at > selected_generated_at
                or (generated_at == selected_generated_at and mtime > selected_mtime)
            ):
                selected_payload = payload
                selected_path = candidate
                selected_generated_at = generated_at
                selected_mtime = mtime
        return selected_payload, selected_path

    def _select_best_container_runtime_payload(filename: str) -> tuple[dict[str, Any], str]:
        selected_payload: dict[str, Any] = {}
        selected_ref = ""
        selected_generated_at = ""
        for container_name in RUNTIME_LEDGER_DOCKER_CONTAINERS:
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        container_name,
                        "sh",
                        "-lc",
                        f"cat /data/provider-ledger/{filename}",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except Exception:
                continue
            if result.returncode != 0:
                continue
            try:
                payload = json.loads(result.stdout)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            generated_at = str(payload.get("generated_at") or "").strip()
            if not selected_payload or generated_at > selected_generated_at:
                selected_payload = payload
                selected_ref = f"docker-exec:{container_name}:/data/provider-ledger/{filename}"
                selected_generated_at = generated_at
        return selected_payload, selected_ref

    runtime_payload, runtime_path = _select_best(runtime_candidates)
    if runtime_payload and runtime_path is not None:
        return runtime_payload, _display_path(root, runtime_path)
    if runtime_filename and allow_docker_runtime_fallback:
        docker_payload, docker_ref = _select_best_container_runtime_payload(runtime_filename)
        if docker_payload and docker_ref:
            return docker_payload, docker_ref

    selected_payload, selected_path = _select_best(published_candidates)
    if selected_payload and selected_path is not None:
        return selected_payload, _display_path(root, selected_path)
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
    action_href = str(context.get("next_action_href") or surface.get("href") or "").strip()
    action_href = _canonical_next_action_href(
        next_action,
        action_href=action_href,
        form_surface=form_surface,
    )
    action_label = str(context.get("next_action_label") or surface.get("label") or "").strip()
    action_method = str(context.get("next_action_method") or surface.get("method") or "").strip()
    if context and action_href:
        context["next_action_href"] = action_href
    payload = {
        "key": key,
        "title": title,
        "lens": lens,
        "status": status,
        "required_next_receipt": required_next_receipt,
        "evidence_kind": evidence_kind,
        "capture_surfaces": [surface for surface in capture_surfaces if str(surface or "").strip()],
        "next_action": next_action,
        "next_action_href": action_href,
        "next_action_label": action_label,
        "next_action_method": action_method,
        **form_surface,
        "claim_boundary": claim_boundary,
        "source_receipts": source_receipts,
    }
    if context:
        payload["action_context"] = {**context, **form_surface}
    return payload


def _next_action_surface(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "next_action": _text(payload.get("next_action")),
        "next_action_href": _text(payload.get("next_action_href")),
        "next_action_label": _text(payload.get("next_action_label")),
        "next_action_method": _text(payload.get("next_action_method")),
    }


def _preferred_action_surface(*surfaces: dict[str, str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    fallback_same_action: dict[str, str] = {}
    for surface in surfaces:
        action = _text(surface.get("next_action"))
        if not action:
            continue
        if not selected:
            selected = {
                "next_action": action,
                "next_action_href": _text(surface.get("next_action_href")),
                "next_action_label": _text(surface.get("next_action_label")),
                "next_action_method": _text(surface.get("next_action_method")),
            }
            continue
        if action == selected["next_action"] and not fallback_same_action:
            fallback_same_action = {
                "next_action": action,
                "next_action_href": _text(surface.get("next_action_href")),
                "next_action_label": _text(surface.get("next_action_label")),
                "next_action_method": _text(surface.get("next_action_method")),
            }
    if not selected:
        return {}
    if fallback_same_action:
        for key in ("next_action_href", "next_action_label", "next_action_method"):
            selected[key] = _text(selected.get(key)) or _text(fallback_same_action.get(key))
    return selected


def _prefer_operator_runtime_surface_for_blocked_proactive_followthrough(
    *,
    gold_status: str,
    gold_surface: dict[str, str],
    operator_surface: dict[str, str],
) -> bool:
    if gold_status != "blocked_operator_runtime_posture":
        return False
    operator_action = _text(operator_surface.get("next_action"))
    if not operator_action:
        return False
    gold_action = _text(gold_surface.get("next_action"))
    return gold_action in {"", "repair_proactive_operator_runtime_posture"}


def _background_source_health_recovery_allows_proactive_followthrough(
    proactive_operator: dict[str, Any],
) -> bool:
    if str(proactive_operator.get("status") or "").strip() != "ready_with_recovery_action":
        return False
    if str(proactive_operator.get("delivery_route_error") or "").strip():
        return False
    live_receipt = dict(proactive_operator.get("live_receipt") or {})
    if live_receipt and not bool(live_receipt.get("ok")):
        return False
    source_health = dict(proactive_operator.get("source_health") or {})
    if not bool(source_health.get("present")):
        return False
    if not bool(source_health.get("operator_action_required")):
        return False
    if bool(source_health.get("user_action_required")):
        return False
    issues = [dict(item) for item in list(source_health.get("issues") or []) if isinstance(item, dict)]
    if not issues:
        return False
    if any(bool(issue.get("user_action_required")) for issue in issues):
        return False
    return True


def _proactive_ooda_action_context(
    *,
    proactive_gold: dict[str, Any],
    proactive_operator: dict[str, Any],
    proactive_gold_accepted: bool,
) -> dict[str, Any]:
    gold_status = str(proactive_gold.get("status") or "").strip()
    operator_runtime_status = str(proactive_operator.get("status") or "").strip()
    gold_surface = _next_action_surface(proactive_gold)
    operator_surface = _next_action_surface(proactive_operator)
    approval_capture = dict(
        proactive_operator.get("approval_capture_surface")
        or proactive_operator.get("approval_capture")
        or {}
    )
    approval_capture_user_action_known = "current_packet_user_action_required" in approval_capture
    approval_capture_user_action_required = bool(approval_capture.get("current_packet_user_action_required"))
    selected_surface = _preferred_action_surface(
        gold_surface,
        operator_surface,
    )
    operator_followthrough_runtime_ready = (
        operator_runtime_status == "ready_with_live_receipt"
        or _background_source_health_recovery_allows_proactive_followthrough(proactive_operator)
    )
    live_followthrough_action_present = (
        str(operator_surface.get("next_action") or "").strip()
        == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
        or str(gold_surface.get("next_action") or "").strip()
        == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    )
    operator_pending_approval_ready = (
        operator_followthrough_runtime_ready
        and live_followthrough_action_present
        and bool(approval_capture.get("ready"))
        and bool(approval_capture.get("telegram_approval_surface_ready"))
        and bool(approval_capture.get("manual_outcome_capture_ready"))
        and bool(approval_capture.get("current_packet_present"))
        and (approval_capture_user_action_required if approval_capture_user_action_known else True)
        and int(approval_capture.get("current_packet_live_pending_count") or 0) == 1
        and str(approval_capture.get("current_packet_callback_latest_status") or "").strip() == "pending"
    )
    operator_manual_approval_ready = (
        operator_followthrough_runtime_ready
        and bool(approval_capture.get("ready"))
        and bool(approval_capture.get("manual_outcome_capture_ready"))
        and bool(approval_capture.get("current_packet_present"))
        and (approval_capture_user_action_required if approval_capture_user_action_known else True)
        and str(gold_surface.get("next_action") or "").strip() == "record_proactive_ooda_approval_outcome"
    )
    operator_approval_followthrough_ready = operator_pending_approval_ready or operator_manual_approval_ready
    if gold_status == "blocked_operator_runtime_posture" and operator_approval_followthrough_ready:
        selected_surface = _preferred_action_surface(operator_surface, gold_surface)
    elif _prefer_operator_runtime_surface_for_blocked_proactive_followthrough(
        gold_status=gold_status,
        gold_surface=gold_surface,
        operator_surface=operator_surface,
    ):
        selected_surface = _preferred_action_surface(operator_surface, gold_surface)
    next_action = (
        str(selected_surface.get("next_action") or "").strip()
        or ("maintain_proactive_ooda_gold_acceptance_evidence" if proactive_gold_accepted else "")
        or "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    )
    approval = dict(dict(proactive_gold.get("proofs") or {}).get("approval_outcome") or {})
    approval_capture_expires_at = str(approval_capture.get("current_packet_callback_latest_expires_at") or "").strip()
    approval_action_required = (
        not proactive_gold_accepted
        and operator_approval_followthrough_ready
        and next_action
        in {
            "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
            "record_proactive_ooda_approval_outcome",
        }
        and gold_status in {"ready_for_approval_outcome_capture", "blocked_operator_runtime_posture"}
        and not bool(approval.get("approval_outcome_recorded"))
    )
    approval_followthrough_meta_only = (
        not approval_action_required
        and next_action
        in {
            "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
            "record_proactive_ooda_approval_outcome",
            "repair_proactive_approval_capture",
        }
    )
    instruction = str(
        proactive_gold.get("summary")
        or proactive_operator.get("summary")
        or "Advance the proactive OODA lane to the next truthful proof step."
    ).strip()
    if approval_action_required:
        instruction = "Record the approval outcome for the current proactive OODA packet."
        if approval_capture_expires_at:
            instruction = (
                "Record the approval outcome for the current proactive OODA packet before "
                f"{approval_capture_expires_at}."
            )
    return {
        "kind": "proactive_ooda_acceptance_followthrough",
        "user_action_required": approval_action_required,
        "instruction": instruction,
        "gold_status": gold_status,
        "operator_runtime_status": operator_runtime_status,
        "approval_outcome_recorded": bool(approval.get("approval_outcome_recorded")),
        "approval_outcome_accepted": bool(approval.get("accepted")),
        "approval_capture_ready": bool(approval_capture.get("ready")),
        "approval_capture_manual_outcome_capture_ready": bool(approval_capture.get("manual_outcome_capture_ready")),
        "approval_capture_telegram_surface_ready": bool(approval_capture.get("telegram_approval_surface_ready")),
        "approval_capture_current_packet_user_action_required": approval_capture_user_action_required,
        "approval_capture_selected_channel": str(approval_capture.get("selected_channel") or "").strip(),
        "approval_capture_live_pending_count": int(approval_capture.get("current_packet_live_pending_count") or 0),
        "approval_capture_latest_status": str(approval_capture.get("current_packet_callback_latest_status") or "").strip(),
        "approval_capture_latest_expires_at": approval_capture_expires_at,
        "remaining_external_proofs": [
            str(item).strip()
            for item in list(proactive_gold.get("remaining_external_proofs") or [])
            if str(item).strip()
        ],
        "next_action": next_action,
        "next_action_href": str(selected_surface.get("next_action_href") or "").strip(),
        "next_action_label": str(selected_surface.get("next_action_label") or "").strip(),
        "next_action_method": str(selected_surface.get("next_action_method") or "").strip(),
        "delivery_policy": "action_required_only" if approval_action_required else "queue_only",
        "operator_queue_visible": not approval_followthrough_meta_only,
        "telegram_push_allowed": False,
        "interruption_budget": "action_required" if approval_action_required else "none",
        "notification_policy": "exclusive_head" if approval_action_required else "default",
        "telegram_message": (
            f"Action needed: {instruction}" if approval_action_required else ""
        ),
        "console_deep_link": str(selected_surface.get("next_action_href") or "").strip() if approval_action_required else "",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
        "raw_pair_url_exposed": False,
        "raw_qr_payload_exposed": False,
        "raw_whatsapp_session_ref_exposed": False,
    }


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


def _signal_review_action_context(signal_receipt: dict[str, Any]) -> dict[str, Any]:
    packet = dict(signal_receipt.get("operator_action_packet") or {})
    if not packet:
        context = _manual_acceptance_action_context(
            instruction="Record redacted evidence that the weekly signal-to-decision review was actually reviewed.",
            evidence_part="review",
        )
        if context.get("user_action_required") is True:
            context["telegram_push_allowed"] = False
            context["notification_policy"] = "queue_only_proof"
        return context
    privacy_flags = {
        "raw_private_context_exposed": bool(packet.get("raw_private_context_exposed")),
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_acceptance_text_exposed": bool(packet.get("raw_acceptance_text_exposed")),
        "raw_actor_identity_exposed": bool(packet.get("raw_actor_identity_exposed")),
        "raw_object_reference_exposed": bool(packet.get("raw_object_reference_exposed")),
    }
    context = {
        "kind": "real_world_acceptance_capture",
        "source_action_packet_present": True,
        "source_action_packet_status": str(packet.get("status") or "").strip(),
        "action_required_reason": str(packet.get("action_required_reason") or "").strip(),
        "evidence_part": str(
            packet.get("next_action_evidence_part") or signal_receipt.get("next_action_evidence_part") or "review"
        ).strip(),
        "user_action_required": bool(packet.get("user_action_required")),
        "instruction": str(packet.get("instruction") or "").strip(),
        "next_action_href": str(packet.get("next_action_href") or "").strip(),
        "next_action_label": str(packet.get("next_action_label") or "").strip(),
        "next_action_method": str(packet.get("next_action_method") or "").strip(),
        "next_action_form_href": str(packet.get("next_action_form_href") or "").strip(),
        "next_action_form_label": str(packet.get("next_action_form_label") or "").strip(),
        "next_action_form_method": str(packet.get("next_action_form_method") or "").strip(),
        "required_form_fields": [
            str(item).strip()
            for item in list(packet.get("required_form_fields") or [])
            if str(item).strip()
        ],
        "accepted_parts": {
            "review": bool(dict(packet.get("accepted_parts") or {}).get("review")),
            "followthrough": bool(dict(packet.get("accepted_parts") or {}).get("followthrough")),
        },
        "delivery_policy": str(packet.get("delivery_policy") or "action_required_only").strip(),
        "telegram_push_allowed": False,
        "interruption_budget": str(packet.get("interruption_budget") or "action_required").strip(),
        "quiet_hours_respected": bool(packet.get("quiet_hours_respected")),
        "non_action_progress_push_allowed": bool(packet.get("non_action_progress_push_allowed")),
        "irreversible_actions_consent_gated": bool(packet.get("irreversible_actions_consent_gated")),
        "claim_boundary": str(packet.get("claim_boundary") or "").strip(),
        "telegram_message": str(packet.get("telegram_message") or "").strip(),
        "notification_policy": "queue_only_proof",
        **privacy_flags,
    }
    if not context["instruction"]:
        context["instruction"] = "Record redacted evidence that the weekly signal-to-decision review was actually reviewed."
    if not context["telegram_message"]:
        if context["evidence_part"] == "followthrough":
            context["telegram_message"] = (
                "Action needed: record the signal-to-decision follow-through outcome. "
                "Open the evidence form and save a short redacted outcome note."
            )
        else:
            context["telegram_message"] = (
                "Action needed: record that you reviewed the weekly signal-to-decision packet. "
                "Open the evidence form and save a short redacted review note."
            )
    return {key: value for key, value in context.items() if value not in ("", [], None)}


def _signal_review_acceptance_status(signal_receipt: dict[str, Any]) -> str:
    return "satisfied" if bool(signal_receipt.get("real_weekly_operator_review_accepted")) else "pending_real_world_evidence"


def _pushbullet_delivery_action_context(receipt: dict[str, Any]) -> dict[str, Any]:
    action = dict(receipt.get("operator_action") or {})
    coverage = dict(receipt.get("client_coverage") or action.get("client_coverage") or {})
    relay = dict(receipt.get("relay") or {})
    live_probes = [dict(item) for item in list(receipt.get("live_probes") or []) if isinstance(item, dict)]
    default_client_ref = str(
        action.get("default_client_ref")
        or receipt.get("default_client_ref")
        or ""
    ).strip()
    default_client_ref_present = bool(
        action.get("default_client_ref_present")
        if action.get("default_client_ref_present") is not None
        else receipt.get("default_client_ref_present")
    )
    default_client_ref_resolves = bool(
        action.get("default_client_ref_resolves")
        if action.get("default_client_ref_resolves") is not None
        else receipt.get("default_client_ref_resolves")
    )
    missing_setup = [
        str(item).strip()
        for item in list(action.get("missing_setup") or receipt.get("missing_setup") or [])
        if str(item).strip()
    ]
    required_client_keys = [
        str(item).strip()
        for item in list(receipt.get("required_client_keys") or [])
        if str(item).strip()
    ]
    token_required_client_keys = [
        str(item).strip()
        for item in list(receipt.get("token_required_client_keys") or required_client_keys)
        if str(item).strip()
    ]
    missing_client_keys = [
        str(item).strip()
        for item in list(coverage.get("missing_client_keys") or [])
        if str(item).strip()
    ] or [
        item.removeprefix("pushbullet_client_missing:").strip()
        for item in missing_setup
        if item.startswith("pushbullet_client_missing:") and item.removeprefix("pushbullet_client_missing:").strip()
    ]
    token_missing_client_keys = [
        str(item).strip()
        for item in list(coverage.get("missing_token_keys") or [])
        if str(item).strip()
    ] or [
        item.removeprefix("pushbullet_token_missing:").strip()
        for item in missing_setup
        if item.startswith("pushbullet_token_missing:") and item.removeprefix("pushbullet_token_missing:").strip()
    ]
    live_probe_failed_client_keys = [
        item.removeprefix("pushbullet_live_probe_failed:").strip()
        for item in missing_setup
        if item.startswith("pushbullet_live_probe_failed:") and item.removeprefix("pushbullet_live_probe_failed:").strip()
    ]
    account_mismatch_client_keys = [
        str(item.get("client_key") or "").strip()
        for item in live_probes
        if str(item.get("client_key") or "").strip()
        and (
            str(item.get("reason") or "").strip() == "pushbullet_account_email_mismatch"
            or item.get("expected_email_matches") is False
        )
    ]
    relay_distinct_clients_required = "pushbullet_relay_distinct_clients_required" in missing_setup
    relay_distinct_accounts_required = "pushbullet_relay_distinct_accounts_required" in missing_setup
    relay_primary_client_key = str(relay.get("primary_client_key") or "").strip()
    relay_secondary_client_key = str(relay.get("secondary_client_key") or "").strip()
    relay_resolved_primary_client_key = str(relay.get("resolved_primary_client_key") or "").strip()
    relay_resolved_secondary_client_key = str(relay.get("resolved_secondary_client_key") or "").strip()
    relay_distinct_client_keys_ready = bool(relay.get("distinct_client_keys_ready"))
    relay_distinct_account_hashes_ready = bool(relay.get("distinct_account_hashes_ready"))
    setup_url = str(receipt.get("account_settings_url") or action.get("next_action_href") or "").strip()
    setup_checklist = [
        dict(item)
        for item in list(action.get("setup_checklist") or [])
        if isinstance(item, dict)
    ]
    checklist_keys = {
        str(item.get("key") or "").strip()
        for item in setup_checklist
        if str(item.get("key") or "").strip()
    }
    if not setup_checklist and missing_setup:
        setup_checklist = [
            {
                "key": "create_pushbullet_access_token",
                "label": "Create Pushbullet access token",
                "how": "Open Pushbullet account settings, create an access token for the intended account, store it in the configured PB_TOKEN_* env var, then rerun the readiness receipt.",
            }
        ]
        checklist_keys = {"create_pushbullet_access_token"}
    if relay_distinct_clients_required and "configure_pushbullet_relay_clients" not in checklist_keys:
        setup_checklist.insert(
            0,
            {
                "key": "configure_pushbullet_relay_clients",
                "label": "Separate relay accounts",
                "how": "Configure a separate primary/default Pushbullet account for the relay and keep Elisabeth on her own Pushbullet account. Do not point both relay sides at the same account.",
            },
        )
        checklist_keys.add("configure_pushbullet_relay_clients")
    if relay_distinct_accounts_required and "verify_pushbullet_relay_accounts" not in checklist_keys:
        setup_checklist.append(
            {
                "key": "verify_pushbullet_relay_accounts",
                "label": "Verify relay account split",
                "how": "Confirm the primary/default relay token and the Elisabeth relay token belong to different Pushbullet accounts, then rerun the readiness receipt.",
            }
        )
        checklist_keys.add("verify_pushbullet_relay_accounts")
    clients = [dict(item) for item in list(receipt.get("clients") or []) if isinstance(item, dict)]
    token_env_by_client = {
        str(item.get("client_key") or "").strip(): str(item.get("token_env") or "").strip()
        for item in clients
        if str(item.get("client_key") or "").strip() and str(item.get("token_env") or "").strip()
    }
    def _token_env_for_client_key(key: str) -> str:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return ""
        if (
            normalized_key == "default"
            and default_client_ref
            and default_client_ref_resolves
            and default_client_ref != "default"
        ):
            alias_env = token_env_by_client.get(default_client_ref, "")
            if alias_env:
                return alias_env
        return token_env_by_client.get(normalized_key, "") or (
            "PB_TOKEN" if normalized_key == "default" else f"PB_TOKEN_{normalized_key.upper()}"
        )

    token_envs = [
        str(item.get("token_env") or "").strip()
        for item in clients
        if str(item.get("token_env") or "").strip()
    ]
    for key in token_required_client_keys:
        expected_token_env = _token_env_for_client_key(key)
        if expected_token_env not in token_envs:
            token_envs.append(expected_token_env)
    missing_token_envs = []
    for key in token_missing_client_keys:
        expected_token_env = _token_env_for_client_key(key)
        if expected_token_env and expected_token_env not in missing_token_envs:
            missing_token_envs.append(expected_token_env)
    for client_key in account_mismatch_client_keys:
        expected_token_env = _token_env_for_client_key(client_key)
        if expected_token_env and expected_token_env not in missing_token_envs:
            missing_token_envs.append(expected_token_env)
    for client_key in account_mismatch_client_keys:
        checklist_key = f"reissue_pushbullet_token:{client_key}"
        if checklist_key in checklist_keys:
            continue
        token_env = _token_env_for_client_key(client_key)
        token_suffix = f" in {token_env}" if token_env else ""
        setup_checklist.append(
            {
                "key": checklist_key,
                "label": f"Reissue {client_key} token",
                "how": f"Sign in to the intended {client_key} Pushbullet account, create a fresh access token{token_suffix}, replace the configured value, then rerun the readiness receipt.",
            }
        )
        checklist_keys.add(checklist_key)
    if live_probe_failed_client_keys and "verify_pushbullet_account_match" not in checklist_keys:
        setup_checklist.append(
            {
                "key": "verify_pushbullet_account_match",
                "label": "Verify token account match",
                "how": "Rerun the Pushbullet readiness receipt with the live probe enabled and confirm every configured token belongs to its intended Pushbullet account.",
            }
        )
        checklist_keys.add("verify_pushbullet_account_match")
    instruction = str(action.get("instruction") or "").strip()
    if not instruction:
        if relay_distinct_clients_required and account_mismatch_client_keys:
            instruction = (
                "Configure separate Pushbullet relay accounts for the primary/default route and Elisabeth, "
                "reissue the mismatched Elisabeth token from the intended account, then rerun the readiness receipt."
            )
        elif relay_distinct_clients_required:
            instruction = (
                "Configure separate Pushbullet relay accounts for the primary/default route and Elisabeth, "
                "then rerun the readiness receipt."
            )
        elif account_mismatch_client_keys:
            instruction = (
                "Reissue the mismatched Pushbullet token from the intended account, then rerun the readiness receipt."
            )
        else:
            instruction = "Create missing Pushbullet access tokens for configured delivery clients, then rerun readiness."
    action_required_reason = str(action.get("action_required_reason") or "").strip()
    if not action_required_reason:
        reasons: list[str] = []
        if relay_distinct_clients_required:
            reasons.append("pushbullet_relay_distinct_clients_required")
        if relay_distinct_accounts_required:
            reasons.append("pushbullet_relay_distinct_accounts_required")
        if account_mismatch_client_keys:
            reasons.append("pushbullet_account_email_mismatch")
        if live_probe_failed_client_keys and not account_mismatch_client_keys:
            reasons.append("pushbullet_live_probe_failed")
        action_required_reason = ",".join(reasons[:3])
    telegram_message = str(action.get("telegram_message") or "").strip()
    if not telegram_message and missing_setup:
        env_suffix = f" Missing token env: {', '.join(missing_token_envs[:3])}." if missing_token_envs else ""
        if relay_distinct_clients_required and account_mismatch_client_keys:
            telegram_message = (
                "Action needed: Pushbullet relay is blocked. The primary/default route and Elisabeth currently resolve "
                "to the same Pushbullet account, and the Elisabeth token belongs to a different account than configured. "
                "Create a separate primary/default Pushbullet token, reissue the Elisabeth token from the intended "
                f"account, then rerun the Pushbullet readiness receipt.{env_suffix}"
            )
        elif relay_distinct_clients_required:
            telegram_message = (
                "Action needed: Pushbullet relay is blocked. The primary/default route and Elisabeth currently resolve "
                "to the same Pushbullet account. Configure separate accounts for both relay sides, then rerun the "
                f"Pushbullet readiness receipt.{env_suffix}"
            )
        elif account_mismatch_client_keys:
            mismatch_label = ", ".join(account_mismatch_client_keys[:3])
            telegram_message = (
                "Action needed: Pushbullet delivery is not ready. The configured token belongs to a different "
                f"Pushbullet account than expected for: {mismatch_label}. Reissue the token from the intended account, "
                f"then rerun the Pushbullet readiness receipt.{env_suffix}"
            )
        else:
            missing_label = ", ".join(missing_setup[:3])
            suffix = f" Missing: {missing_label}." if missing_label else ""
            telegram_message = (
                "Action needed: Pushbullet delivery is not ready. Configure the expected Pushbullet clients, create "
                f"missing access tokens, then rerun the Pushbullet readiness receipt.{suffix}{env_suffix}"
            )
    return {
        "kind": "pushbullet_delivery_setup",
        "user_action_required": bool(action.get("user_action_required") or missing_setup),
        "instruction": instruction,
        "action_required_reason": action_required_reason,
        "missing_setup": missing_setup,
        "setup_checklist": setup_checklist,
        "required_client_keys": required_client_keys,
        "token_required_client_keys": token_required_client_keys,
        "default_client_ref": default_client_ref,
        "default_client_ref_present": default_client_ref_present,
        "default_client_ref_resolves": default_client_ref_resolves,
        "missing_client_keys": missing_client_keys,
        "token_missing_client_keys": token_missing_client_keys,
        "live_probe_failed_client_keys": live_probe_failed_client_keys,
        "account_mismatch_client_keys": account_mismatch_client_keys,
        "multi_client_expected": bool(receipt.get("multi_client_expected") or coverage.get("multi_client_expected")),
        "pushbullet_client_count": int(receipt.get("client_count") or len(clients) or 0),
        "pushbullet_token_envs": token_envs,
        "pushbullet_missing_token_envs": missing_token_envs,
        "pushbullet_note_delivery_ready": bool(dict(receipt.get("delivery_claim") or {}).get("pushbullet_note_delivery_ready")),
        "multi_client_delivery_ready": bool(
            dict(receipt.get("delivery_claim") or {}).get("multi_client_delivery_ready")
        ),
        "live_token_account_verified": bool(dict(receipt.get("delivery_claim") or {}).get("live_token_account_verified")),
        "relay_primary_client_key": relay_primary_client_key,
        "relay_secondary_client_key": relay_secondary_client_key,
        "relay_resolved_primary_client_key": relay_resolved_primary_client_key,
        "relay_resolved_secondary_client_key": relay_resolved_secondary_client_key,
        "relay_distinct_clients_required": relay_distinct_clients_required,
        "relay_distinct_accounts_required": relay_distinct_accounts_required,
        "relay_distinct_client_keys_ready": relay_distinct_client_keys_ready,
        "relay_distinct_account_hashes_ready": relay_distinct_account_hashes_ready,
        "external_setup_url": setup_url,
        "telegram_message": telegram_message,
        "notification_policy": "default",
        "delivery_policy": str(action.get("delivery_policy") or "action_required_only").strip(),
        "telegram_push_allowed": bool(action.get("telegram_push_allowed") or missing_setup),
        "interruption_budget": str(action.get("interruption_budget") or "action_required").strip(),
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": bool(action.get("raw_private_context_exposed")),
        "raw_chat_ids_exposed": False,
        "raw_email_exposed": bool(action.get("raw_email_exposed") or dict(receipt.get("privacy") or {}).get("raw_email_exposed")),
        "raw_token_exposed": bool(action.get("raw_token_exposed") or dict(receipt.get("privacy") or {}).get("raw_token_exposed")),
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
    }


def _mymedia_alexa_action_context(receipt: dict[str, Any]) -> dict[str, Any]:
    operator_action = dict(receipt.get("operator_action") or {})
    pairing_telegram_delivery = dict(receipt.get("pairing_telegram_delivery") or {})
    telegram_delivery = dict(pairing_telegram_delivery.get("telegram_delivery") or {})
    probe = dict(receipt.get("probe") or {})
    next_action = str(
        operator_action.get("next_action")
        or receipt.get("next_action")
        or "complete_amazon_pairing_for_mymedia"
    ).strip()
    next_action_href = str(
        operator_action.get("next_action_href")
        or receipt.get("next_action_href")
        or ""
    ).strip()
    next_action_label = str(
        operator_action.get("next_action_label")
        or receipt.get("next_action_label")
        or "Open My Media setup"
    ).strip()
    next_action_method = str(
        operator_action.get("next_action_method")
        or receipt.get("next_action_method")
        or "get"
    ).strip().lower() or "get"
    reason = str(receipt.get("reason") or probe.get("reason") or "mymedia_not_ready").strip()
    pairing_resume_ready = bool(receipt.get("pairing_resume_ready"))
    pairing_resume_command = str(receipt.get("pairing_resume_command") or "").strip()
    instruction = {
        "enter_mymedia_amazon_pairing_code": (
            "Read the current Amazon security code, submit it through the saved My Media pairing handoff, then rerun "
            "the My Media readiness receipt."
        ),
        "approve_mymedia_amazon_consent": (
            "Resume the saved My Media pairing handoff, approve the Amazon consent surface, then rerun the My Media "
            "readiness receipt."
        ),
        "complete_amazon_pairing_for_mymedia": (
            "Open the My Media setup surface, complete the Amazon account pairing, then rerun the My Media readiness "
            "receipt."
        ),
        "complete_amazon_pairing_then_rescan_library": (
            "Complete the Amazon pairing first, then rerun the My Media readiness receipt so the library can rescan."
        ),
        "add_mymedia_watch_folder": (
            "Add the intended media watch folder in My Media, allow indexing to finish, then rerun the readiness "
            "receipt."
        ),
        "repair_mymedia_watch_folder": (
            "Repair the configured My Media watch folder path or permissions, then rerun the readiness receipt."
        ),
        "configure_mymedia_external_access": (
            "Repair the My Media external-access mode so Alexa can reach the server, then rerun the readiness receipt."
        ),
        "repair_mymedia_public_console_route": (
            "Repair the Cloudflare-backed My Media public console route, then rerun the readiness receipt."
        ),
        "inspect_mymedia_public_console_route": (
            "Inspect the Cloudflare-backed My Media public console route, repair the broken step, then rerun the "
            "readiness receipt."
        ),
        "inspect_mymedia_public_console_origin": (
            "Inspect the My Media public console origin target, repair the broken step, then rerun the readiness receipt."
        ),
        "inspect_mymedia_public_console_access": (
            "Inspect the My Media public console access policy, repair the broken step, then rerun the readiness receipt."
        ),
        "inspect_mymedia_amazon_connection": (
            "Inspect the My Media/Amazon connection state, repair the blocked step, then rerun the readiness receipt."
        ),
        "rescan_mymedia_library": (
            "Rescan the My Media library and rerun the readiness receipt after indexing settles."
        ),
        "inspect_mymedia_console_api": (
            "Repair the My Media console/API reachability issue, then rerun the readiness receipt."
        ),
        "repair_mymedia_console_api": (
            "Repair the My Media console/API reachability issue, then rerun the readiness receipt."
        ),
        "start_mymedia_alexa_container": (
            "Start the My Media container or restore its runtime, then rerun the readiness receipt."
        ),
    }.get(
        next_action,
        "Repair the blocked My Media runtime step, then rerun the readiness receipt.",
    )
    setup_checklist: list[dict[str, Any]] = []
    if pairing_resume_ready and pairing_resume_command:
        setup_checklist.append(
            {
                "key": "resume_saved_pairing_handoff",
                "label": "Resume the saved pairing handoff",
                "how": pairing_resume_command,
            }
        )
    elif next_action == "enter_mymedia_amazon_pairing_code":
        setup_checklist.append(
            {
                "key": "trigger_fresh_pairing_handoff",
                "label": "Trigger a fresh My Media pairing handoff",
                "how": "make trigger-mymedia-amazon-pairing",
            }
        )
    setup_checklist.extend(
        [
            {
                "key": "refresh_mymedia_runtime_receipt",
                "label": "Refresh My Media runtime posture",
                "how": "make verify-mymedia-alexa-readiness",
            }
        ]
    )
    repair_commands = []
    if pairing_resume_ready and pairing_resume_command:
        repair_commands.append(pairing_resume_command)
    elif next_action in {"enter_mymedia_amazon_pairing_code", "approve_mymedia_amazon_consent"}:
        repair_commands.append("make trigger-mymedia-amazon-pairing")
    public_surface_ready = bool(probe.get("public_surface_ready"))
    public_surface_reason = str(probe.get("public_surface_reason") or "").strip()
    public_surface_status = str(probe.get("public_surface_status") or "").strip()
    if bool(probe.get("public_surface_configured")) and not public_surface_ready:
        if public_surface_reason and public_surface_reason not in {reason}:
            missing_setup = [reason, public_surface_reason] if reason else [public_surface_reason]
        else:
            missing_setup = [reason] if reason else []
        setup_checklist.append(
            {
                "key": "repair_mymedia_public_console_route",
                "label": "Repair My Media public console route",
                "how": "make repair-mymedia-public-surface",
            }
        )
        repair_commands.append("make repair-mymedia-public-surface")
    else:
        missing_setup = [reason] if reason else []
    telegram_delivery_ready = bool(operator_action.get("telegram_delivery_ready"))
    telegram_delivery_transport = str(
        pairing_telegram_delivery.get("delivery_transport") or telegram_delivery.get("delivery_transport") or ""
    ).strip()
    telegram_delivery_reason = (
        ""
        if telegram_delivery_ready
        else str(
            telegram_delivery.get("readiness_reason")
            or telegram_delivery.get("reason")
            or pairing_telegram_delivery.get("delivery_reason")
            or ""
        ).strip()
    )
    telegram_delivery_next_action = str(telegram_delivery.get("next_action") or "").strip()
    telegram_delivery_next_action_href = str(telegram_delivery.get("next_action_href") or "").strip()
    telegram_delivery_next_action_label = str(telegram_delivery.get("next_action_label") or "").strip()
    telegram_delivery_next_action_method = str(telegram_delivery.get("next_action_method") or "").strip()
    if not telegram_delivery_ready:
        telegram_repair_how = (
            telegram_delivery_next_action_label
            or telegram_delivery_next_action_href
            or telegram_delivery_next_action
            or telegram_delivery_reason
            or "Repair the Telegram delivery binding and rerun the My Media readiness receipt."
        )
        setup_checklist.append(
            {
                "key": "repair_mymedia_pairing_telegram_handoff",
                "label": "Repair My Media Telegram handoff delivery",
                "how": telegram_repair_how,
            }
        )
    repair_commands.extend(
        [
            "make materialize-mymedia-alexa-readiness",
            "make verify-mymedia-alexa-readiness",
            "python3 scripts/materialize_continuous_improvement_goal_posture.py",
            "python3 scripts/verify_continuous_improvement_goal_posture.py --pretty",
        ]
    )
    telegram_message = (
        "Action needed: My Media for Alexa is not ready. "
        f"Current blocker: {reason}. "
        "Finish the blocked setup step, then rerun the My Media readiness receipt."
    )
    context = {
        "kind": "mymedia_alexa_setup",
        "user_action_required": bool(operator_action.get("user_action_required") or not bool(receipt.get("ready"))),
        "instruction": instruction,
        "missing_setup": missing_setup,
        "setup_checklist": setup_checklist,
        "repair_commands": repair_commands,
        "telegram_message": telegram_message,
        "next_action_href": next_action_href,
        "next_action_label": next_action_label,
        "next_action_method": next_action_method,
        "next_action_form_href": next_action_href if next_action_method == "get" else "",
        "next_action_form_label": next_action_label if next_action_method == "get" else "",
        "next_action_form_method": next_action_method if next_action_method == "get" else "",
        "external_setup_url": next_action_href,
        "pairing_resume_ready": pairing_resume_ready,
        "pairing_resume_command": pairing_resume_command,
        "echo_playback_claim_allowed": bool(receipt.get("echo_playback_claim_allowed")),
        "telegram_delivery_ready": telegram_delivery_ready,
        "telegram_delivery_transport": telegram_delivery_transport,
        "telegram_delivery_reason": telegram_delivery_reason,
        "telegram_delivery_next_action": telegram_delivery_next_action,
        "telegram_delivery_next_action_href": telegram_delivery_next_action_href,
        "telegram_delivery_next_action_label": telegram_delivery_next_action_label,
        "telegram_delivery_next_action_method": telegram_delivery_next_action_method,
        "delivery_policy": str(operator_action.get("delivery_policy") or "action_required_only").strip(),
        "telegram_push_allowed": bool(operator_action.get("user_action_required") or not bool(receipt.get("ready"))),
        "interruption_budget": str(operator_action.get("interruption_budget") or "action_required").strip(),
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "raw_private_context_exposed": bool(operator_action.get("raw_private_context_exposed")),
        "raw_chat_ids_exposed": False,
        "raw_email_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_refresh_token_exposed": bool(dict(receipt.get("privacy") or {}).get("raw_refresh_token_exposed")),
        "raw_paired_user_exposed": bool(dict(receipt.get("privacy") or {}).get("raw_paired_user_exposed")),
        "raw_watch_folder_paths_exposed": bool(
            dict(receipt.get("privacy") or {}).get("raw_watch_folder_paths_exposed")
        ),
        "raw_public_ip_exposed": bool(dict(receipt.get("privacy") or {}).get("raw_public_ip_exposed")),
        "raw_pairing_resume_url_exposed": bool(
            dict(receipt.get("privacy") or {}).get("raw_pairing_resume_url_exposed")
        ),
        "public_console_surface_ready": public_surface_ready,
        "public_console_surface_status": public_surface_status,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
    }
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
        "raw_pair_url_exposed": False,
        "raw_qr_payload_exposed": False,
        "raw_whatsapp_session_ref_exposed": False,
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
        "raw_pair_url_exposed": False,
        "raw_qr_payload_exposed": False,
        "raw_whatsapp_session_ref_exposed": False,
    }


def _whatsapp_live_playback_blocked(receipt: dict[str, Any], blocking_reasons: list[str]) -> bool:
    if not any(str(reason or "").startswith("deliver:whatsapp_audiobook=blocked") for reason in blocking_reasons):
        return False
    selected_delivery = receipt.get("selected_delivery")
    selected = dict(selected_delivery) if isinstance(selected_delivery, dict) else {}
    public_share_ready = (
        str(selected.get("public_share_status") or "").strip() == "public_share_ready"
        and bool(selected.get("public_share_url_present"))
    )
    if not public_share_ready:
        return False
    failed_codes = {
        str(code or "").strip()
        for code in list(receipt.get("failed_codes") or [])
        if str(code or "").strip()
    }
    failed_codes.update(
        str(code or "").strip()
        for code in list(selected.get("failed_codes") or [])
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


def _whatsapp_sidecar_pairing_required(
    *,
    readiness_receipt: dict[str, Any],
    bundle_receipt: dict[str, Any],
) -> bool:
    if not readiness_receipt and not bundle_receipt:
        return False
    readiness_reasons = {
        str(item or "").strip()
        for item in list(readiness_receipt.get("reasons") or [])
        if str(item or "").strip()
    }
    bundle_readiness = dict(bundle_receipt.get("live_readiness") or {})
    bundle_inbox = dict(bundle_receipt.get("live_sidecar_inbox") or {})
    sidecar_status = str(
        readiness_receipt.get("sidecar_status")
        or bundle_inbox.get("session_status")
        or bundle_readiness.get("sidecar_status")
        or ""
    ).strip()
    sidecar_qr_required = (
        readiness_receipt.get("sidecar_qr_required") is True
        or sidecar_status == "qr_required"
        or bundle_inbox.get("session_status") == "qr_required"
    )
    sidecar_not_ready = (
        "sidecar_not_ready" in readiness_reasons
        or str(readiness_receipt.get("reason") or "").strip() == "sidecar_not_ready"
        or str(bundle_readiness.get("reason") or "").strip() == "sidecar_not_ready"
        or bundle_readiness.get("sidecar_ready") is False
        or readiness_receipt.get("sidecar_ready") is False
    )
    return sidecar_not_ready and sidecar_qr_required


def _whatsapp_sidecar_pairing_action_context(
    *,
    readiness_receipt: dict[str, Any],
    bundle_receipt: dict[str, Any],
) -> dict[str, Any]:
    if not _whatsapp_sidecar_pairing_required(
        readiness_receipt=readiness_receipt,
        bundle_receipt=bundle_receipt,
    ):
        return {}

    bundle_readiness = dict(bundle_receipt.get("live_readiness") or {})
    bundle_inbox = dict(bundle_receipt.get("live_sidecar_inbox") or {})
    sidecar_status = str(
        readiness_receipt.get("sidecar_status")
        or bundle_inbox.get("session_status")
        or bundle_readiness.get("sidecar_status")
        or ""
    ).strip()
    session_api_host_kind = str(bundle_inbox.get("session_api_host_kind") or "").strip()
    pair_url_scope = str(readiness_receipt.get("pair_url_scope") or "").strip()
    if not pair_url_scope and session_api_host_kind in {"loopback", "localhost", "host_local"}:
        pair_url_scope = "host_local"
    pair_url_actionable_from_telegram = (
        readiness_receipt.get("pair_url_actionable_from_telegram") is True and pair_url_scope == "public"
    )
    instruction = (
        "Pair the WhatsApp Web sidecar from the WhatsApp integration, then rerun the WhatsApp audiobook delivery checks."
    )
    telegram_message = (
        "Action needed for EA WhatsApp: pair the WhatsApp Web sidecar. Open the WhatsApp integration locally; "
        "EA will not send host-local pair URLs or QR payloads through Telegram."
    )
    return {
        "kind": "whatsapp_web_sidecar_pairing_required",
        "user_action_required": True,
        "instruction": instruction,
        "missing_setup": ["whatsapp_web_sidecar_pairing"],
        "setup_checklist": [
            {
                "id": "open_whatsapp_integration",
                "label": "Open WhatsApp setup",
                "status": "action_required",
            },
            {
                "id": "pair_whatsapp_web_sidecar",
                "label": "Scan or refresh the WhatsApp Web pairing QR",
                "status": "action_required",
            },
            {
                "id": "rerun_delivery_checks",
                "label": "Rerun WhatsApp audiobook delivery checks",
                "status": "pending_after_pairing",
            },
        ],
        "telegram_message": telegram_message,
        "runtime_readiness_reason": str(
            readiness_receipt.get("reason") or bundle_readiness.get("reason") or "sidecar_not_ready"
        ).strip(),
        "sidecar_status": sidecar_status,
        "sidecar_qr_required": True,
        "sidecar_qr_present": bool(readiness_receipt.get("sidecar_qr_present")),
        "sidecar_qr_fresh": bool(readiness_receipt.get("sidecar_qr_fresh")),
        "sidecar_qr_age_seconds": int(readiness_receipt.get("sidecar_qr_age_seconds") or 0),
        "pair_url_scope": pair_url_scope,
        "pair_url_actionable_from_telegram": pair_url_actionable_from_telegram,
        "repair_commands": [
            "python3 scripts/materialize_whatsapp_web_action_processor_readiness.py",
            "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py",
            "PYTHONPATH=ea python3 ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py",
            "python3 scripts/materialize_continuous_improvement_goal_posture.py",
            "python3 scripts/verify_continuous_improvement_goal_posture.py --pretty",
        ],
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "non_action_progress_push_allowed": False,
        "raw_private_context_exposed": False,
        "raw_chat_ids_exposed": False,
        "raw_token_exposed": False,
        "raw_secret_exposed": False,
        "raw_voice_ids_exposed": False,
        "callback_tokens_exposed": False,
        "raw_pair_url_exposed": False,
        "raw_qr_payload_exposed": False,
        "raw_whatsapp_session_ref_exposed": False,
    }


def _operator_action_priority(requirement: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    action_context = dict(requirement.get("action_context") or {})
    key = str(requirement.get("key") or "")
    key_priority = {
        "ea_real_commitment_recovered_or_closed": 0,
        "ea_real_approved_action_audited": 1,
        "ea_real_provider_failure_recovered": 2,
        "morning_brief_operator_acceptance": 3,
        "weekly_signal_to_decision_review_acceptance": 4,
        "google_workspace_oauth_setup": 5,
        "pushbullet_delivery_setup": 6,
        "mymedia_alexa_setup": 7,
        "telegram_audiobook_live_delivery": 10,
        "manfred_stt_tts_realtime_conversation": 11,
        "whatsapp_audiobook_live_delivery": 12,
    }
    lens_priority = {
        "prove": 1,
        "detect": 2,
        "deliver": 3,
        "recover": 4,
        "decide": 5,
    }
    proactive_approval_followthrough_gate = (
        key == "proactive_ooda_packet_acceptance"
        and action_context.get("user_action_required") is True
        and bool(action_context.get("approval_capture_ready"))
        and str(requirement.get("next_action") or "").strip()
        in {
            "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
            "record_proactive_ooda_approval_outcome",
        }
    )
    meta_followthrough_priority = 1 if key == "weekly_signal_to_decision_review_acceptance" else 0
    if action_context.get("user_action_required") is True:
        return (
            0,
            0 if proactive_approval_followthrough_gate else 1,
            meta_followthrough_priority,
            lens_priority.get(str(requirement.get("lens") or ""), 9),
            key_priority.get(key, 99),
            key,
        )
    return (
        1,
        1,
        meta_followthrough_priority,
        lens_priority.get(str(requirement.get("lens") or ""), 9),
        key_priority.get(key, 99),
        key,
    )


def _operator_stream_for_requirement(requirement: dict[str, Any]) -> str:
    key = str(requirement.get("key") or "").strip()
    lens = str(requirement.get("lens") or "").strip()
    if key in {
        "proactive_ooda_packet_acceptance",
        "morning_brief_operator_acceptance",
        "weekly_signal_to_decision_review_acceptance",
        "ea_real_commitment_recovered_or_closed",
        "ea_real_approved_action_audited",
        "ea_real_provider_failure_recovered",
    }:
        return OPERATOR_STREAM_OFFICE_LOOP
    if key in {
        "telegram_business_signal_setup",
        "google_workspace_oauth_setup",
        "pushbullet_delivery_setup",
    }:
        return OPERATOR_STREAM_OFFICE_SETUP
    if key == "fresh_host_teable_recovery_drill" or lens == "recover":
        return OPERATOR_STREAM_RECOVERY
    if key in {
        "mymedia_alexa_setup",
        "manfred_stt_tts_realtime_conversation",
        "telegram_audiobook_live_delivery",
        "whatsapp_audiobook_live_delivery",
    }:
        return OPERATOR_STREAM_MEDIA_MEMORIAL
    if lens == "deliver":
        return OPERATOR_STREAM_MEDIA_MEMORIAL
    return OPERATOR_STREAM_OFFICE_LOOP


def _operator_action_queue(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = [requirement for requirement in requirements if str(requirement.get("status") or "") != "satisfied"]
    result: list[dict[str, Any]] = []
    for requirement in sorted(pending, key=_operator_action_priority):
        action_context = dict(requirement.get("action_context") or {})
        if action_context.get("operator_queue_visible") is False:
            continue
        user_action_required = bool(action_context.get("user_action_required"))
        explicit_telegram_push_allowed = action_context.get("telegram_push_allowed")
        operator_stream = _operator_stream_for_requirement(requirement)
        delivery_policy = "action_required_only" if user_action_required else "queue_only"
        telegram_push_allowed = (
            explicit_telegram_push_allowed
            if isinstance(explicit_telegram_push_allowed, bool)
            else user_action_required
        )
        action_digest_eligible = bool(
            user_action_required
            and delivery_policy == "action_required_only"
            and telegram_push_allowed
            and operator_stream in DEFAULT_ACTION_DIGEST_STREAMS
        )
        row = {
            "key": str(requirement.get("key") or "").strip(),
            "operator_stream": operator_stream,
            "kind": str(action_context.get("kind") or "").strip(),
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
            "action_required_reason": str(action_context.get("action_required_reason") or "").strip(),
            "source_action_packet_present": bool(action_context.get("source_action_packet_present")),
            "source_action_packet_status": str(action_context.get("source_action_packet_status") or "").strip(),
            "required_form_fields": [
                str(item).strip()
                for item in list(action_context.get("required_form_fields") or [])
                if str(item).strip()
            ],
            "accepted_parts": dict(action_context.get("accepted_parts") or {}),
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
            "runtime_readiness_reason": str(action_context.get("runtime_readiness_reason") or "").strip(),
            "sidecar_status": str(action_context.get("sidecar_status") or "").strip(),
            "sidecar_qr_required": bool(action_context.get("sidecar_qr_required")),
            "sidecar_qr_present": bool(action_context.get("sidecar_qr_present")),
            "sidecar_qr_fresh": bool(action_context.get("sidecar_qr_fresh")),
            "sidecar_qr_age_seconds": int(action_context.get("sidecar_qr_age_seconds") or 0),
            "pair_url_scope": str(action_context.get("pair_url_scope") or "").strip(),
            "pair_url_actionable_from_telegram": bool(action_context.get("pair_url_actionable_from_telegram")),
            "setup_checklist": [
                dict(item)
                for item in list(action_context.get("setup_checklist") or [])
                if isinstance(item, dict)
            ],
            "telegram_message": str(action_context.get("telegram_message") or "").strip(),
            "console_deep_link": str(action_context.get("console_deep_link") or "").strip(),
            "auth_link_template": str(action_context.get("auth_link_template") or "").strip(),
            "scope_bundle": str(action_context.get("scope_bundle") or "").strip(),
            "expected_google_email_present": bool(action_context.get("expected_google_email_present")),
            "expected_google_email_sha256": str(action_context.get("expected_google_email_sha256") or "").strip(),
            "expected_google_domain": str(action_context.get("expected_google_domain") or "").strip(),
            "observed_google_email_present": bool(action_context.get("observed_google_email_present")),
            "observed_google_email_sha256": str(action_context.get("observed_google_email_sha256") or "").strip(),
            "observed_google_domain": str(action_context.get("observed_google_domain") or "").strip(),
            "observed_google_account_matches_expected": bool(
                action_context.get("observed_google_account_matches_expected")
            ),
            "external_setup_url": str(action_context.get("external_setup_url") or "").strip(),
            "notification_policy": str(action_context.get("notification_policy") or "").strip(),
            "required_client_keys": [
                str(item).strip()
                for item in list(action_context.get("required_client_keys") or [])
                if str(item).strip()
            ],
            "token_missing_client_keys": [
                str(item).strip()
                for item in list(action_context.get("token_missing_client_keys") or [])
                if str(item).strip()
            ],
            "missing_client_keys": [
                str(item).strip()
                for item in list(action_context.get("missing_client_keys") or [])
                if str(item).strip()
            ],
            "multi_client_expected": bool(action_context.get("multi_client_expected")),
            "pushbullet_client_count": int(action_context.get("pushbullet_client_count") or 0),
            "pushbullet_token_envs": [
                str(item).strip()
                for item in list(action_context.get("pushbullet_token_envs") or [])
                if str(item).strip()
            ],
            "pushbullet_missing_token_envs": [
                str(item).strip()
                for item in list(action_context.get("pushbullet_missing_token_envs") or [])
                if str(item).strip()
            ],
            "pushbullet_note_delivery_ready": bool(action_context.get("pushbullet_note_delivery_ready")),
            "multi_client_delivery_ready": bool(action_context.get("multi_client_delivery_ready")),
            "live_token_account_verified": bool(action_context.get("live_token_account_verified")),
            "pairing_resume_ready": bool(action_context.get("pairing_resume_ready")),
            "pairing_resume_command": str(action_context.get("pairing_resume_command") or "").strip(),
            "echo_playback_claim_allowed": bool(action_context.get("echo_playback_claim_allowed")),
            "telegram_delivery_ready": bool(action_context.get("telegram_delivery_ready")),
            "telegram_delivery_transport": str(action_context.get("telegram_delivery_transport") or "").strip(),
            "telegram_delivery_reason": str(action_context.get("telegram_delivery_reason") or "").strip(),
            "telegram_delivery_next_action": str(action_context.get("telegram_delivery_next_action") or "").strip(),
            "telegram_delivery_next_action_href": str(action_context.get("telegram_delivery_next_action_href") or "").strip(),
            "telegram_delivery_next_action_label": str(action_context.get("telegram_delivery_next_action_label") or "").strip(),
            "telegram_delivery_next_action_method": str(action_context.get("telegram_delivery_next_action_method") or "").strip(),
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
            "delivery_policy": delivery_policy,
            "telegram_push_allowed": telegram_push_allowed,
            "action_digest_eligible": action_digest_eligible,
            "proactive_signal_allowed": action_digest_eligible,
            "default_action_digest_suppressed_reason": (
                ""
                if action_digest_eligible
                else "not_user_action_required"
                if not user_action_required
                else "telegram_push_not_allowed"
                if not telegram_push_allowed
                else "operator_stream_not_in_default_action_digest"
                if operator_stream not in DEFAULT_ACTION_DIGEST_STREAMS
                else "delivery_policy_not_action_required_only"
            ),
            "interruption_budget": "action_required" if user_action_required else "none",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": bool(action_context.get("raw_chat_ids_exposed")),
            "raw_email_exposed": bool(action_context.get("raw_email_exposed")),
            "raw_token_exposed": bool(action_context.get("raw_token_exposed")),
            "raw_secret_exposed": bool(action_context.get("raw_secret_exposed")),
            "raw_refresh_token_exposed": bool(action_context.get("raw_refresh_token_exposed")),
            "raw_paired_user_exposed": bool(action_context.get("raw_paired_user_exposed")),
            "raw_watch_folder_paths_exposed": bool(action_context.get("raw_watch_folder_paths_exposed")),
            "raw_public_ip_exposed": bool(action_context.get("raw_public_ip_exposed")),
            "raw_expected_google_email_exposed": bool(action_context.get("raw_expected_google_email_exposed")),
            "raw_observed_google_email_exposed": bool(action_context.get("raw_observed_google_email_exposed")),
            "raw_client_id_exposed": bool(action_context.get("raw_client_id_exposed")),
            "raw_client_secret_exposed": bool(action_context.get("raw_client_secret_exposed")),
            "raw_error_description_exposed": bool(action_context.get("raw_error_description_exposed")),
            "raw_voice_ids_exposed": bool(action_context.get("raw_voice_ids_exposed")),
            "callback_tokens_exposed": bool(action_context.get("callback_tokens_exposed")),
            "raw_public_share_url_exposed": bool(action_context.get("raw_public_share_url_exposed")),
            "raw_track_url_exposed": bool(action_context.get("raw_track_url_exposed")),
            "raw_acceptance_text_exposed": bool(action_context.get("raw_acceptance_text_exposed")),
            "raw_actor_identity_exposed": bool(action_context.get("raw_actor_identity_exposed")),
            "raw_object_reference_exposed": bool(action_context.get("raw_object_reference_exposed")),
            "raw_transcript_fields_exposed": bool(action_context.get("raw_transcript_fields_exposed")),
            "candidate_raw_text_fields_exposed": bool(action_context.get("candidate_raw_text_fields_exposed")),
            "raw_pair_url_exposed": bool(action_context.get("raw_pair_url_exposed")),
            "raw_pairing_resume_url_exposed": bool(action_context.get("raw_pairing_resume_url_exposed")),
            "raw_qr_payload_exposed": bool(action_context.get("raw_qr_payload_exposed")),
            "raw_whatsapp_session_ref_exposed": bool(action_context.get("raw_whatsapp_session_ref_exposed")),
        }
        optional_context_keys = (
            "kind",
            "action_required_reason",
            "source_action_packet_present",
            "source_action_packet_status",
            "required_form_fields",
            "accepted_parts",
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
            "console_deep_link",
            "auth_link_template",
            "scope_bundle",
            "expected_google_email_present",
            "expected_google_email_sha256",
            "expected_google_domain",
            "observed_google_email_present",
            "observed_google_email_sha256",
            "observed_google_domain",
            "observed_google_account_matches_expected",
            "external_setup_url",
            "notification_policy",
            "required_client_keys",
            "missing_client_keys",
            "token_missing_client_keys",
            "multi_client_expected",
            "pushbullet_client_count",
            "pushbullet_token_envs",
            "pushbullet_missing_token_envs",
            "pushbullet_note_delivery_ready",
            "multi_client_delivery_ready",
            "live_token_account_verified",
            "pairing_resume_ready",
            "pairing_resume_command",
            "echo_playback_claim_allowed",
            "telegram_delivery_ready",
            "telegram_delivery_transport",
            "telegram_delivery_reason",
            "telegram_delivery_next_action",
            "telegram_delivery_next_action_href",
            "telegram_delivery_next_action_label",
            "telegram_delivery_next_action_method",
            "failed_playback_count",
            "attempted_playback_count",
            "first_failure_reason",
            "track_response_status",
            "track_content_type",
            "media_error",
            "media_error_code",
            "public_share_host",
            "runtime_readiness_reason",
            "sidecar_status",
            "sidecar_qr_required",
            "sidecar_qr_present",
            "sidecar_qr_fresh",
            "sidecar_qr_age_seconds",
            "pair_url_scope",
            "pair_url_actionable_from_telegram",
            "raw_public_share_url_exposed",
            "raw_track_url_exposed",
            "raw_email_exposed",
            "raw_refresh_token_exposed",
            "raw_paired_user_exposed",
            "raw_watch_folder_paths_exposed",
            "raw_public_ip_exposed",
            "raw_pair_url_exposed",
            "raw_pairing_resume_url_exposed",
            "raw_qr_payload_exposed",
            "raw_whatsapp_session_ref_exposed",
            "raw_acceptance_text_exposed",
            "raw_actor_identity_exposed",
            "raw_object_reference_exposed",
            "raw_transcript_fields_exposed",
            "candidate_raw_text_fields_exposed",
            "raw_expected_google_email_exposed",
            "raw_observed_google_email_exposed",
            "raw_client_id_exposed",
            "raw_client_secret_exposed",
            "raw_error_description_exposed",
        )
        for optional_key in optional_context_keys:
            if optional_key not in action_context:
                row.pop(optional_key, None)
        result.append({key: value for key, value in row.items() if value not in ("", [], None)})
    return result


def _operator_delivery_policy(operator_action_queue: list[dict[str, Any]]) -> dict[str, Any]:
    first = dict(operator_action_queue[0]) if operator_action_queue else {}
    digest_eligible_rows = [
        row for row in operator_action_queue if isinstance(row, dict) and row.get("action_digest_eligible") is True
    ]
    digest_suppressed_rows = [
        row
        for row in operator_action_queue
        if isinstance(row, dict)
        and row.get("user_action_required") is True
        and row.get("action_digest_eligible") is not True
    ]
    return {
        "action_required_only": True,
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
        "default_action_digest_streams": list(DEFAULT_ACTION_DIGEST_STREAMS),
        "default_action_digest_eligible_count": len(digest_eligible_rows),
        "default_action_digest_suppressed_count": len(digest_suppressed_rows),
        "telegram_push_allowed_for_next_action": bool(first.get("telegram_push_allowed")),
        "next_action_digest_eligible": bool(first.get("action_digest_eligible")),
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
    provider_cost_pressure_probe: Callable[[], dict[str, Any]] | None = None,
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
    google_oauth, google_oauth_path = _load_receipt(root, root / DEFAULT_GOOGLE_WORKSPACE_OAUTH_READINESS.relative_to(ROOT))
    pushbullet, pushbullet_path = _load_receipt(root, root / DEFAULT_PUSHBULLET_DELIVERY_READINESS.relative_to(ROOT))
    operator_readiness, operator_readiness_path = _load_receipt(root, root / DEFAULT_OPERATOR_READINESS.relative_to(ROOT))
    tg_ready, tg_ready_path = _load_receipt(root, root / DEFAULT_TELEGRAM_AUDIOBOOK_READINESS.relative_to(ROOT))
    tg_live, tg_live_path = _load_receipt(root, root / DEFAULT_TELEGRAM_AUDIOBOOK_DELIVERY.relative_to(ROOT))
    wa_intake, wa_intake_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_INTAKE.relative_to(ROOT))
    wa_bundle, wa_bundle_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_BUNDLE.relative_to(ROOT))
    wa_live, wa_live_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_DELIVERY.relative_to(ROOT))
    wa_share, wa_share_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_SHARE.relative_to(ROOT))
    wa_voice, wa_voice_path = _load_receipt(root, root / DEFAULT_WHATSAPP_AUDIOBOOK_VOICE.relative_to(ROOT))
    wa_runtime, wa_runtime_path = _load_receipt(
        root,
        root / DEFAULT_WHATSAPP_WEB_ACTION_PROCESSOR_READINESS.relative_to(ROOT),
    )
    mymedia, mymedia_path = _load_receipt(root, root / DEFAULT_MYMEDIA_ALEXA_READINESS.relative_to(ROOT))
    live_provider_cost_pressure: dict[str, Any] = {}
    if provider_cost_pressure_probe is not None or root.resolve() == ROOT.resolve():
        probe = provider_cost_pressure_probe or _live_provider_cost_pressure_probe
        live_provider_cost_pressure = dict(probe() or {})

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
            "python3 scripts/verify_google_workspace_oauth_readiness.py",
            "python3 scripts/verify_ea_operator_readiness.py",
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
            _source_receipt(
                google_oauth_path,
                google_oauth,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            ),
            _source_receipt(
                operator_readiness_path,
                operator_readiness,
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
    detect_lens["google_workspace_oauth_readiness"] = {
        "key": "google_workspace_full_workspace_oauth",
        "status": _status(google_oauth),
        "scope_bundle": str(google_oauth.get("scope_bundle") or "").strip(),
        "blocker_kind": str(google_oauth.get("blocker_kind") or "").strip(),
        "expected_google_email_present": bool(dict(google_oauth.get("expected_google_account") or {}).get("present")),
        "expected_google_email_sha256": str(
            dict(google_oauth.get("expected_google_account") or {}).get("email_sha256") or ""
        ).strip(),
        "observed_google_email_present": bool(dict(google_oauth.get("observed_google_account") or {}).get("present")),
        "observed_google_email_sha256": str(
            dict(google_oauth.get("observed_google_account") or {}).get("email_sha256") or ""
        ).strip(),
        "observed_google_account_matches_expected": bool(
            dict(google_oauth.get("observed_google_account") or {}).get("matches_expected")
        ),
        "oauth_project_id": str(dict(google_oauth.get("oauth_client") or {}).get("client_project_id") or "").strip(),
        "oauth_project_number": str(
            dict(google_oauth.get("oauth_client") or {}).get("client_project_number") or ""
        ).strip(),
        "console_deep_link": str(google_oauth.get("console_deep_link") or "").strip(),
        "auth_link_template": str(google_oauth.get("auth_link_template") or "").strip(),
        "raw_expected_google_email_exposed": bool(
            dict(google_oauth.get("privacy") or {}).get("raw_expected_google_email_exposed")
        ),
        "raw_observed_google_email_exposed": bool(
            dict(google_oauth.get("privacy") or {}).get("raw_observed_google_email_exposed")
        ),
        "raw_client_secret_exposed": bool(dict(google_oauth.get("privacy") or {}).get("raw_client_secret_exposed")),
        "raw_access_token_exposed": bool(dict(google_oauth.get("privacy") or {}).get("raw_access_token_exposed")),
        "raw_refresh_token_exposed": bool(dict(google_oauth.get("privacy") or {}).get("raw_refresh_token_exposed")),
        "raw_error_description_exposed": bool(
            dict(google_oauth.get("privacy") or {}).get("raw_error_description_exposed")
        ),
        "next_action": str(
            dict(google_oauth.get("operator_action") or {}).get("next_action")
            or "add_google_oauth_test_user_and_retry_full_workspace_auth"
        ).strip(),
    }
    detect_lens["operator_readiness_aggregate"] = {
        "key": "ea_operator_readiness_aggregate",
        "status": _status(operator_readiness) or "missing",
        "ready": bool(operator_readiness.get("ready")),
        "pairing_probe_mode": str(operator_readiness.get("pairing_probe_mode") or "").strip(),
        "component_count": int(operator_readiness.get("component_count") or 0),
        "blocked_count": int(operator_readiness.get("blocked_count") or 0),
        "probe_failed_count": int(operator_readiness.get("probe_failed_count") or 0),
        "supplemental_attention_count": int(operator_readiness.get("supplemental_attention_count") or 0),
        "supplemental_blocked_count": int(operator_readiness.get("supplemental_blocked_count") or 0),
        "supplemental_probe_failed_count": int(operator_readiness.get("supplemental_probe_failed_count") or 0),
        "component_keys": [
            str(item).strip()
            for item in list(operator_readiness.get("component_keys") or [])
            if str(item).strip()
        ],
        "steering_component_keys": [
            str(item).strip()
            for item in list(operator_readiness.get("steering_component_keys") or [])
            if str(item).strip()
        ],
        "attention_component_keys": [
            str(item).strip()
            for item in list(operator_readiness.get("attention_component_keys") or [])
            if str(item).strip()
        ],
        "supplemental_attention_component_keys": [
            str(item).strip()
            for item in list(operator_readiness.get("supplemental_attention_component_keys") or [])
            if str(item).strip()
        ],
        "next_action": str(operator_readiness.get("next_action") or "").strip(),
        "supplemental_next_actions": [
            {
                "component_key": str(dict(item).get("component_key") or "").strip(),
                "action": str(dict(item).get("action") or "").strip(),
                "href": str(dict(item).get("href") or "").strip(),
                "label": str(dict(item).get("label") or "").strip(),
                "method": str(dict(item).get("method") or "").strip(),
                "reason": str(dict(item).get("reason") or "").strip(),
            }
            for item in list(operator_readiness.get("supplemental_next_actions") or [])
            if isinstance(item, dict) and str(dict(item).get("component_key") or "").strip()
        ],
        "summary": str(operator_readiness.get("summary") or "").strip(),
        "raw_component_payload_exposed": bool(dict(operator_readiness.get("privacy") or {}).get("raw_component_payload_exposed")),
        "raw_delivery_token_exposed": bool(dict(operator_readiness.get("privacy") or {}).get("raw_delivery_token_exposed")),
        "raw_qr_artifact_exposed": bool(dict(operator_readiness.get("privacy") or {}).get("raw_qr_artifact_exposed")),
        "raw_chat_ref_exposed": bool(dict(operator_readiness.get("privacy") or {}).get("raw_chat_ref_exposed")),
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
    decide_lens["provider_cost_control"] = _provider_cost_control_from_office(office)
    decide_lens["provider_cost_pressure"] = _decide_provider_cost_pressure(
        ooda_status,
        live_probe=live_provider_cost_pressure,
    )

    tg_summary = (
        f"live delivery {_status(tg_live)}; readiness {_status(tg_ready)}"
        if tg_live or tg_ready
        else "Telegram audiobook live receipts are not mirrored."
    )
    wa_summary = (
        f"runtime {_status(wa_runtime)}; intake {_status(wa_intake)}; bundle {_status(wa_bundle)}; live {_status(wa_live)}; share {_status(wa_share)}; voice {_status(wa_voice)}"
        if wa_runtime or wa_intake or wa_bundle or wa_live or wa_share or wa_voice
        else "WhatsApp audiobook receipts are not mirrored."
    )
    whatsapp_voice_shadow_required = _whatsapp_voice_shadow_required(wa_voice)
    whatsapp_component_receipts = []
    if wa_runtime:
        whatsapp_component_receipts.append(
            _source_receipt(
                wa_runtime_path,
                wa_runtime,
                current_source_head=current_source_head,
                current_source_fingerprint=current_source_fingerprint,
            )
        )
    whatsapp_component_receipts.extend(
        [
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
    )
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
    if pushbullet:
        pushbullet_component = _deliver_component(
            key="pushbullet_delivery",
            title="Pushbullet action-required delivery",
            payload=pushbullet,
            summary=(
                f"Pushbullet clients: {int(pushbullet.get('client_count') or 0)} configured; "
                f"missing setup: {len(list(pushbullet.get('missing_setup') or []))}."
            ),
            next_action=str(
                dict(pushbullet.get("operator_action") or {}).get("next_action")
                or "create_missing_pushbullet_access_tokens"
            ).strip(),
            receipts=[
                _source_receipt(
                    pushbullet_path,
                    pushbullet,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            ],
        )
        pushbullet_component.update(
            {
                "client_count": int(pushbullet.get("client_count") or 0),
                "required_client_keys": [
                    str(item).strip()
                    for item in list(pushbullet.get("required_client_keys") or [])
                    if str(item).strip()
                ],
                "missing_setup": [
                    str(item).strip()
                    for item in list(pushbullet.get("missing_setup") or [])
                    if str(item).strip()
                ],
                "pushbullet_note_delivery_ready": bool(
                    dict(pushbullet.get("delivery_claim") or {}).get("pushbullet_note_delivery_ready")
                ),
                "live_token_account_verified": bool(
                    dict(pushbullet.get("delivery_claim") or {}).get("live_token_account_verified")
                ),
                "raw_email_exposed": bool(dict(pushbullet.get("privacy") or {}).get("raw_email_exposed")),
                "raw_token_exposed": bool(dict(pushbullet.get("privacy") or {}).get("raw_token_exposed")),
            }
        )
        deliver_components.append(pushbullet_component)
    if mymedia:
        mymedia_component = _deliver_component(
            key="mymedia_alexa",
            title="My Media for Alexa",
            payload=mymedia,
            summary=(
                f"My Media runtime {_status(mymedia)}; pairing resume "
                f"{'ready' if bool(mymedia.get('pairing_resume_ready')) else 'not_ready'}."
            ),
            next_action=str(
                dict(mymedia.get("operator_action") or {}).get("next_action")
                or mymedia.get("next_action")
                or "complete_amazon_pairing_for_mymedia"
            ).strip(),
            receipts=[
                _source_receipt(
                    mymedia_path,
                    mymedia,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            ],
        )
        mymedia_component.update(
            {
                "pairing_resume_ready": bool(mymedia.get("pairing_resume_ready")),
                "pairing_resume_command": str(mymedia.get("pairing_resume_command") or "").strip(),
                "echo_playback_claim_allowed": bool(mymedia.get("echo_playback_claim_allowed")),
                "telegram_delivery_ready": bool(dict(mymedia.get("operator_action") or {}).get("telegram_delivery_ready")),
                "telegram_delivery_transport": str(
                    dict(mymedia.get("pairing_telegram_delivery") or {}).get("delivery_transport") or ""
                ).strip(),
                "telegram_delivery_reason": (
                    ""
                    if bool(dict(mymedia.get("operator_action") or {}).get("telegram_delivery_ready"))
                    else str(
                        dict(mymedia.get("pairing_telegram_delivery") or {}).get("delivery_reason")
                        or dict(dict(mymedia.get("pairing_telegram_delivery") or {}).get("telegram_delivery") or {}).get(
                            "readiness_reason"
                        )
                        or dict(dict(mymedia.get("pairing_telegram_delivery") or {}).get("telegram_delivery") or {}).get(
                            "reason"
                        )
                        or ""
                    ).strip()
                ),
                "raw_refresh_token_exposed": bool(dict(mymedia.get("privacy") or {}).get("raw_refresh_token_exposed")),
                "raw_paired_user_exposed": bool(dict(mymedia.get("privacy") or {}).get("raw_paired_user_exposed")),
                "raw_watch_folder_paths_exposed": bool(
                    dict(mymedia.get("privacy") or {}).get("raw_watch_folder_paths_exposed")
                ),
                "raw_public_ip_exposed": bool(dict(mymedia.get("privacy") or {}).get("raw_public_ip_exposed")),
                "raw_pairing_resume_url_exposed": bool(
                    dict(mymedia.get("privacy") or {}).get("raw_pairing_resume_url_exposed")
                ),
            }
        )
        deliver_components.append(mymedia_component)

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
            "make verify-mymedia-alexa-readiness",
            "python3 scripts/verify_pushbullet_delivery_readiness.py",
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
        if lens["key"] == "detect" and google_oauth and _is_blocking(_status(google_oauth)):
            blocking_reasons.append(f"detect:google_workspace_oauth={_status(google_oauth)}")
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
    proactive_context = _proactive_ooda_action_context(
        proactive_gold=ooda_gold,
        proactive_operator=ooda_status,
        proactive_gold_accepted=proactive_gold_accepted,
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
            status=_signal_review_acceptance_status(signal),
            action_context=_signal_review_action_context(signal),
        ),
        _acceptance_proof_requirement(
            key="proactive_ooda_packet_acceptance",
            title="Proactive OODA packet approval outcome",
            lens="decide",
            required_next_receipt=PROACTIVE_OODA_ACCEPTANCE_RECEIPT,
            evidence_kind="approval_outcome",
            capture_surfaces=[ooda_gold_path, ooda_status_path],
            next_action=str(proactive_context.get("next_action") or "").strip()
            or (
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
            action_context=proactive_context,
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
    if any(reason.startswith("detect:google_workspace_oauth") for reason in blocking_reasons):
        google_oauth_action = dict(google_oauth.get("operator_action") or {})
        google_oauth_next_action = str(
            google_oauth_action.get("next_action") or "add_google_oauth_test_user_and_retry_full_workspace_auth"
        ).strip()
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="google_workspace_oauth_setup",
                title="Google Workspace OAuth test-user setup",
                lens="detect",
                required_next_receipt=GOOGLE_WORKSPACE_OAUTH_SETUP_RECEIPT,
                evidence_kind="google_workspace_oauth_test_user_setup",
                capture_surfaces=[google_oauth_path],
                next_action=google_oauth_next_action,
                claim_boundary="does_not_prove_google_workspace_signal_ingest_until_full_workspace_oauth_can_complete_for_the_requested_account",
                action_context={
                    "user_action_required": bool(google_oauth_action.get("user_action_required")),
                    "instruction": str(google_oauth_action.get("instruction") or "").strip(),
                    "next_action_href": str(google_oauth_action.get("next_action_href") or "").strip(),
                    "next_action_label": str(google_oauth_action.get("next_action_label") or "").strip(),
                    "next_action_method": str(google_oauth_action.get("next_action_method") or "").strip(),
                    "missing_setup": [
                        str(item).strip()
                        for item in list(google_oauth_action.get("missing_setup") or [])
                        if str(item).strip()
                    ],
                    "setup_checklist": [
                        dict(item)
                        for item in list(google_oauth_action.get("setup_checklist") or [])
                        if isinstance(item, dict)
                    ],
                    "telegram_message": str(google_oauth_action.get("telegram_message") or "").strip(),
                    "console_deep_link": str(google_oauth_action.get("console_deep_link") or "").strip(),
                    "auth_link_template": str(google_oauth_action.get("auth_link_template") or "").strip(),
                    "scope_bundle": str(google_oauth_action.get("scope_bundle") or "").strip(),
                    "expected_google_email_present": bool(google_oauth_action.get("expected_google_email_present")),
                    "expected_google_email_sha256": str(
                        google_oauth_action.get("expected_google_email_sha256") or ""
                    ).strip(),
                    "expected_google_domain": str(google_oauth_action.get("expected_google_domain") or "").strip(),
                    "observed_google_email_present": bool(
                        google_oauth_action.get("observed_google_email_present")
                    ),
                    "observed_google_email_sha256": str(
                        google_oauth_action.get("observed_google_email_sha256") or ""
                    ).strip(),
                    "observed_google_domain": str(google_oauth_action.get("observed_google_domain") or "").strip(),
                    "observed_google_account_matches_expected": bool(
                        google_oauth_action.get("observed_google_account_matches_expected")
                    ),
                    "raw_expected_google_email_exposed": bool(
                        google_oauth_action.get("raw_expected_google_email_exposed")
                    ),
                    "raw_observed_google_email_exposed": bool(
                        google_oauth_action.get("raw_observed_google_email_exposed")
                    ),
                    "raw_client_id_exposed": bool(google_oauth_action.get("raw_client_id_exposed")),
                    "raw_client_secret_exposed": bool(google_oauth_action.get("raw_client_secret_exposed")),
                    "raw_error_description_exposed": bool(
                        google_oauth_action.get("raw_error_description_exposed")
                    ),
                    "raw_chat_ids_exposed": False,
                    "raw_token_exposed": bool(google_oauth_action.get("raw_token_exposed")),
                    "raw_secret_exposed": bool(google_oauth_action.get("raw_secret_exposed")),
                    "raw_voice_ids_exposed": False,
                    "callback_tokens_exposed": False,
                },
                source_receipts=[
                    _source_receipt(
                        google_oauth_path,
                        google_oauth,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    )
                ],
            )
        )
    if any(reason.startswith("deliver:pushbullet_delivery") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="pushbullet_delivery_setup",
                title="Pushbullet delivery setup",
                lens="deliver",
                required_next_receipt=PUSHBULLET_DELIVERY_SETUP_RECEIPT,
                evidence_kind="delivery_channel_setup",
                capture_surfaces=[pushbullet_path],
                next_action="create_missing_pushbullet_access_tokens",
                claim_boundary="does_not_prove_action_required_pushbullet_delivery_until_required_clients_are_configured_and_live_verifiable",
                action_context=_pushbullet_delivery_action_context(pushbullet),
                source_receipts=[
                    _source_receipt(
                        pushbullet_path,
                        pushbullet,
                        current_source_head=current_source_head,
                        current_source_fingerprint=current_source_fingerprint,
                    )
                ],
            )
        )
    if any(reason.startswith("deliver:mymedia_alexa") for reason in blocking_reasons):
        acceptance_proof_requirements.append(
            _acceptance_proof_requirement(
                key="mymedia_alexa_setup",
                title="My Media for Alexa setup",
                lens="deliver",
                required_next_receipt=MYMEDIA_ALEXA_SETUP_RECEIPT,
                evidence_kind="delivery_channel_setup",
                capture_surfaces=[mymedia_path],
                next_action=str(
                    dict(mymedia.get("operator_action") or {}).get("next_action")
                    or mymedia.get("next_action")
                    or "complete_amazon_pairing_for_mymedia"
                ).strip(),
                claim_boundary=(
                    "does_not_prove_real_echo_playback_until_mymedia_pairing_is_complete_and_a_real_device_playback_"
                    "receipt_exists"
                ),
                action_context=_mymedia_alexa_action_context(mymedia),
                source_receipts=[
                    _source_receipt(
                        mymedia_path,
                        mymedia,
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
        whatsapp_acceptance_receipts = []
        if wa_runtime:
            whatsapp_acceptance_receipts.append(
                _source_receipt(
                    wa_runtime_path,
                    wa_runtime,
                    current_source_head=current_source_head,
                    current_source_fingerprint=current_source_fingerprint,
                )
            )
        whatsapp_acceptance_receipts.extend(
            [
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
        )
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
        sidecar_action_context = _whatsapp_sidecar_pairing_action_context(
            readiness_receipt=wa_runtime,
            bundle_receipt=wa_bundle,
        )
        if sidecar_action_context:
            whatsapp_action_context = sidecar_action_context
        elif any(
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
                capture_surfaces=[wa_runtime_path, wa_live_path, wa_bundle_path, wa_share_path, wa_voice_path],
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
        "goal_shorthand": "Make EA the user's dependable executive operating system: paid-human-assistant-grade proactive OODA with transcript-aware ingest, auditor-passed decision-ready packets, staged follow-through, Teable-mirrored current/stale state, cost-aware 1min.ai-first background routing with Gemini/Vertex token telemetry, self-healing, and governed by owning truth planes rather than assistant-local lore.",
        "execution_lenses": [lens["key"] for lens in lenses],
        "status": overall_status,
        "overall_status": overall_status,
        "goal_completion_claim_allowed": False,
        "real_use_claim_allowed": overall_status == "ready_local_direction" and _status(quality) == "pass",
        "lenses": lenses,
        "provider_cost_control": dict(decide_lens.get("provider_cost_control") or {}),
        "provider_cost_pressure": dict(decide_lens.get("provider_cost_pressure") or {}),
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
            "Provider-cost governance is part of the goal: whenever a lane can route through the active 1min.ai manager it should prefer 1min.ai first, Gemini/Vertex usage must be token-tracked, and Gemini soft caps may remove it from background candidate lists without blocking explicit Gemini requests.",
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
