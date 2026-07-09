#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json"
REQUIRED_LENSES = ["detect", "decide", "deliver", "recover", "prove"]
GOOGLE_REAUTH_ACTION_HREF = (
    "/app/actions/google/connect?return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
)
KNOWN_STATUSES = {
    "pass",
    "ready_local_evidence",
    "ready_local_audit",
    "ready_local_direction",
    "ready_local_packet_pending_operator_acceptance",
    "ready_for_good_executive_assistant_claim_review",
    "partial_real_signal_to_decision_closure",
    "ready_for_live_epub_delivery_test",
    "ready_configured",
    "ready_live_verified",
    "ready",
    "audiobookshelf_imported",
    "mixed_local_progress",
    "ready_local_audit",
    "blocked_real_world_acceptance",
    "blocked_realtime_prerequisites",
    "blocked_stale_source_evidence",
    "blocked",
    "blocked_setup_required",
    "blocked_pairing_required",
    "blocked_runtime_unavailable",
    "blocked_console_unreachable",
    "blocked_watch_folder_missing",
    "blocked_watch_folder_error",
    "blocked_external_access_not_ready",
    "blocked_connection_pending",
    "blocked_connection_not_ready",
    "ready_library_scan_in_progress",
    "blocked_library_scan_pending",
    "blocked_library_empty",
    "active_with_blockers",
    "command_backed_no_published_receipt",
    "missing_receipt",
    "waiting",
    "waiting_for_live_epub",
    "probe_failed",
    "unknown",
    "fail",
    "failed",
}
BASE_DELIVER_COMPONENTS = {"promo_media", "manfred_speech", "telegram_audiobook", "whatsapp_audiobook"}
PUSHBULLET_RECEIPT_NAME = "ea_pushbullet_delivery_readiness.generated.json"
PUSHBULLET_RUNTIME_RECEIPT_NAME = "pushbullet_readiness.generated.json"
MYMEDIA_RECEIPT_NAME = "mymedia_alexa_readiness.generated.json"
OPERATOR_READINESS_RECEIPT_NAME = "ea_operator_readiness.generated.json"
EXPECTED_COMPONENTS = {
    "deliver": BASE_DELIVER_COMPONENTS,
}
REQUIRED_PROACTIVE_OODA_RECEIPT = (
    "real proactive OODA packet accepted with action-required-only routed delivery, approved-source or transcript signal, "
    "live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, "
    "current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
FRESH_HOST_TEABLE_RECOVERY_RECEIPT = "fresh-host Teable recovery drill receipt mirrored into the repo"
REQUIRED_PROOF_FIELDS = {
    "key",
    "title",
    "lens",
    "status",
    "required_next_receipt",
    "evidence_kind",
    "capture_surfaces",
    "next_action",
    "claim_boundary",
    "source_receipts",
    "next_action_href",
    "next_action_label",
    "next_action_method",
    "next_action_form_href",
    "next_action_form_label",
    "next_action_form_method",
}
KNOWN_PROOF_STATUSES = {"pending_real_world_evidence", "satisfied"}
DELIVER_BLOCKER_PROOF_KEYS = {
    "deliver:manfred_speech": "manfred_stt_tts_realtime_conversation",
    "deliver:telegram_audiobook": "telegram_audiobook_live_delivery",
    "deliver:whatsapp_audiobook": "whatsapp_audiobook_live_delivery",
    "deliver:pushbullet_delivery": "pushbullet_delivery_setup",
    "deliver:mymedia_alexa": "mymedia_alexa_setup",
}
EXPECTED_PROOF_ACTION_SURFACES = {
    "morning_brief_operator_acceptance": ("/admin/actions/acceptance-evidence", "post"),
    "ea_real_commitment_recovered_or_closed": ("/admin/actions/acceptance-evidence", "post"),
    "ea_real_approved_action_audited": ("/admin/actions/acceptance-evidence", "post"),
    "ea_real_provider_failure_recovered": ("/admin/actions/acceptance-evidence", "post"),
    "weekly_signal_to_decision_review_acceptance": ("/admin/actions/signal-to-decision-evidence", "post"),
    "proactive_ooda_packet_acceptance": ("/admin/proactive-ooda/approval", "get"),
    "fresh_host_teable_recovery_drill": ("/admin/goals", "get"),
    "telegram_business_signal_setup": ("/integrations/telegram", "get"),
    "google_workspace_oauth_setup": (GOOGLE_REAUTH_ACTION_HREF, "get"),
    "pushbullet_delivery_setup": ("https://www.pushbullet.com/#settings/account", "get"),
    "manfred_stt_tts_realtime_conversation": ("/memorials/manfred/voice-config", "get"),
    "telegram_audiobook_live_delivery": ("/integrations/telegram", "get"),
    "whatsapp_audiobook_live_delivery": ("/integrations/whatsapp", "get"),
}
EXPECTED_PROOF_FORM_SURFACES = {
    "morning_brief_operator_acceptance": ("/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_daily_morning_brief_accepted", "get"),
    "ea_real_commitment_recovered_or_closed": ("/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_commitment_recovered_or_closed", "get"),
    "ea_real_approved_action_audited": ("/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_approved_action_audited", "get"),
    "ea_real_provider_failure_recovered": ("/admin/actions/acceptance-evidence?return_to=%2Fadmin%2Fgoals&proof_key=real_provider_failure_recovered", "get"),
    "weekly_signal_to_decision_review_acceptance": ("/admin/actions/signal-to-decision-evidence?return_to=%2Fadmin%2Fgoals&evidence_part=review", "get"),
    "proactive_ooda_packet_acceptance": ("/admin/proactive-ooda/approval", "get"),
    "fresh_host_teable_recovery_drill": ("/admin/goals", "get"),
    "telegram_business_signal_setup": ("/integrations/telegram", "get"),
    "google_workspace_oauth_setup": (GOOGLE_REAUTH_ACTION_HREF, "get"),
    "pushbullet_delivery_setup": ("https://www.pushbullet.com/#settings/account", "get"),
    "manfred_stt_tts_realtime_conversation": ("/memorials/manfred/voice-config", "get"),
    "telegram_audiobook_live_delivery": ("/integrations/telegram", "get"),
    "whatsapp_audiobook_live_delivery": ("/integrations/whatsapp", "get"),
}
PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS = {
    "ea_proactive_ooda_gold_acceptance.generated.json",
    "ea_proactive_ooda_operator_status.generated.json",
}
CHEAP_PROVIDER_ORDER = ["onemin", "magixai", "gemini_vortex"]
HARD_PROVIDER_ORDER = ["onemin", "magixai", "gemini_vortex"]
TEABLE_RECOVERY_PROOF_RECEIPT_NAME = "teable_env_recovery_proof.generated.json"
EA_QUALITY_ACCEPTANCE_PROOF_KEYS = {
    "real_commitment_recovered_or_closed": "ea_real_commitment_recovered_or_closed",
    "real_approved_action_audited": "ea_real_approved_action_audited",
    "real_provider_failure_recovered": "ea_real_provider_failure_recovered",
}
KNOWN_OPERATOR_STREAMS = {"office_loop", "office_setup", "recovery", "media_memorial"}
DEFAULT_ACTION_DIGEST_STREAMS = ["office_loop", "office_setup", "recovery"]
_OPERATOR_READINESS_OBSERVED_AT_RE = re.compile(r"(^|;\s*)observed_at=[^;]+")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    return bool(recorded and current_head and recorded == current_head)


def _infer_root(path: Path) -> Path:
    resolved = path.resolve()
    for marker in (".codex-studio", ".codex-design"):
        if marker in resolved.parts:
            marker_index = resolved.parts.index(marker)
            return Path(*resolved.parts[:marker_index])
    return ROOT


def _source_ref_is_runtime_backed(path_text: str) -> bool:
    text = str(path_text or "").strip()
    return text.startswith("docker-exec:") or text.startswith("docker:")


def _source_ref_name(path_text: str) -> str:
    text = str(path_text or "").strip()
    if not text:
        return ""
    if _source_ref_is_runtime_backed(text):
        return text.rsplit("/", 1)[-1]
    return Path(text).name


def _source_ref_present(repo_root: Path, path_text: str) -> bool:
    text = str(path_text or "").strip()
    if _source_ref_is_runtime_backed(text):
        return True
    return (repo_root / text).exists()


def _normalize_operator_readiness_summary(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = _OPERATOR_READINESS_OBSERVED_AT_RE.sub(r"\1", text)
    normalized = re.sub(r";\s*;", ";", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" ;")


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path | None = None) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"continuous-improvement goal posture missing or invalid: {path}"]
    repo_root = root or _infer_root(path)

    if receipt.get("contract_name") != "ea.continuous_improvement_goal_posture.v1":
        issues.append("contract_name must be ea.continuous_improvement_goal_posture.v1")
    if receipt.get("goal_doc") != ".codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md":
        issues.append("goal_doc must point at the continuous-improvement goal doc")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    if "governed by owning truth planes" not in str(receipt.get("goal_shorthand") or ""):
        issues.append("goal_shorthand drifted away from the governed north-star wording")
    if "proactive ooda" not in str(receipt.get("goal_shorthand") or "").lower():
        issues.append("goal_shorthand must keep the proactive OODA posture explicit")
    shorthand = str(receipt.get("goal_shorthand") or "").lower()
    if "1min.ai-first background routing" not in shorthand:
        issues.append("goal_shorthand must keep cost-aware 1min.ai-first background routing explicit")
    if "gemini/vertex token telemetry" not in shorthand:
        issues.append("goal_shorthand must keep Gemini/Vertex token telemetry explicit")

    current_head = _git_head(repo_root)
    current_fingerprint = _source_fingerprint(repo_root)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if not recorded_head:
        issues.append("goal posture receipt missing source_git_head")
    elif current_head and not _fresh_enough(recorded_head, current_head=current_head) and not fingerprint_matches:
        issues.append("goal posture receipt is stale relative to current HEAD")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("goal posture source_state_fingerprint_semantics drifted")
    if not recorded_fingerprint:
        issues.append("goal posture receipt missing source_state_fingerprint")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("goal posture receipt is stale relative to current source fingerprint")

    execution_lenses = list(receipt.get("execution_lenses") or [])
    if execution_lenses != REQUIRED_LENSES:
        issues.append("execution_lenses must stay ordered as detect/decide/deliver/recover/prove")

    overall_status = str(receipt.get("overall_status") or "").strip()
    top_level_status = str(receipt.get("status") or "").strip()
    if not top_level_status:
        issues.append("top-level status missing")
    elif overall_status and top_level_status != overall_status:
        issues.append("top-level status must mirror overall_status")

    lenses = receipt.get("lenses")
    if not isinstance(lenses, list):
        return issues + ["lenses must be a list"]
    by_key = {str(lens.get("key") or ""): lens for lens in lenses if isinstance(lens, dict)}
    if sorted(by_key) != sorted(REQUIRED_LENSES):
        issues.append("receipt must contain exactly the required lenses")

    decide_lens = by_key.get("decide") or {}
    top_level_provider_cost_control = receipt.get("provider_cost_control")
    if top_level_provider_cost_control != decide_lens.get("provider_cost_control"):
        issues.append("top-level provider_cost_control must mirror decide.provider_cost_control")
    top_level_provider_cost_pressure = receipt.get("provider_cost_pressure")
    if top_level_provider_cost_pressure != decide_lens.get("provider_cost_pressure"):
        issues.append("top-level provider_cost_pressure must mirror decide.provider_cost_pressure")

    for key in REQUIRED_LENSES:
        lens = by_key.get(key) or {}
        status = str(lens.get("status") or "").strip()
        if not status:
            issues.append(f"{key} lens status missing")
        elif status not in KNOWN_STATUSES:
            issues.append(f"{key} lens status uses unknown value: {status}")
        commands = list(lens.get("verifier_commands") or [])
        if not commands:
            issues.append(f"{key} lens must list verifier commands")
        if key in {"detect", "decide", "prove"}:
            sources = list(lens.get("source_receipts") or [])
            expected_source_count = 5 if key == "detect" else 1
            if len(sources) != expected_source_count:
                issues.append(f"{key} lens must have exactly {expected_source_count} source receipt(s)")
            for source in sources:
                path_text = str(source.get("path") or "").strip()
                if not path_text:
                    issues.append(f"{key} source receipt path missing")
                    continue
                source_path = repo_root / path_text
                source_present = _source_ref_present(repo_root, path_text)
                if bool(source.get("present")) != source_present:
                    issues.append(f"{key} source receipt presence drifted for {path_text}")
                if source_present and not _source_ref_is_runtime_backed(path_text) and source_path.exists():
                    payload = _json(source_path)
                    source_status = str(source.get("status") or "").strip().lower()
                    payload_status = str(payload.get("status") or "missing_receipt").strip().lower()
                    if source_status != payload_status:
                        issues.append(f"{key} source receipt status drifted for {path_text}")
                    primary_source = source is sources[0]
                    if primary_source and status != source_status:
                        issues.append(f"{key} lens status must mirror {path_text}")
        if key == "detect":
            transcript_evidence = lens.get("transcript_ingest_evidence")
            if not isinstance(transcript_evidence, dict):
                issues.append("detect lens must include transcript_ingest_evidence")
            else:
                if transcript_evidence.get("key") != "pocket_ai_audio_transcripts":
                    issues.append("detect transcript_ingest_evidence key must be pocket_ai_audio_transcripts")
                for privacy_key in ("raw_transcript_text_exposed", "raw_archive_root_exposed", "raw_credential_exposed"):
                    if transcript_evidence.get(privacy_key) is not False:
                        issues.append(f"detect transcript_ingest_evidence.{privacy_key} must be false")
                if str(transcript_evidence.get("status") or "").strip() == "pass":
                    if transcript_evidence.get("transcript_ingest_ready") is not True:
                        issues.append("passing transcript_ingest_evidence requires transcript_ingest_ready=true")
                    if int(transcript_evidence.get("missing_transcript_total") or 0) != 0:
                        issues.append("passing transcript_ingest_evidence requires missing_transcript_total=0")
                if not any("verify_pocket_audio_archive_receipt.py" in str(command) for command in commands):
                    issues.append("detect lens verifier_commands must include pocket archive receipt verifier")
                if not any("verify_telegram_business_signal_readiness.py" in str(command) for command in commands):
                    issues.append("detect lens verifier_commands must include Telegram Business readiness verifier")
                if not any("verify_google_workspace_oauth_readiness.py" in str(command) for command in commands):
                    issues.append("detect lens verifier_commands must include Google Workspace OAuth readiness verifier")
                if not any("verify_ea_operator_readiness.py" in str(command) for command in commands):
                    issues.append("detect lens verifier_commands must include operator readiness verifier")
            operator_readiness = lens.get("operator_readiness_aggregate")
            if not isinstance(operator_readiness, dict):
                issues.append("detect lens must include operator_readiness_aggregate")
            else:
                if operator_readiness.get("key") != "ea_operator_readiness_aggregate":
                    issues.append("detect operator_readiness_aggregate key must be ea_operator_readiness_aggregate")
                for privacy_key in (
                    "raw_component_payload_exposed",
                    "raw_delivery_token_exposed",
                    "raw_qr_artifact_exposed",
                    "raw_chat_ref_exposed",
                ):
                    if operator_readiness.get(privacy_key) is not False:
                        issues.append(f"operator_readiness_aggregate must not expose {privacy_key}")
                for count_key in (
                    "component_count",
                    "blocked_count",
                    "probe_failed_count",
                    "supplemental_attention_count",
                    "supplemental_blocked_count",
                    "supplemental_probe_failed_count",
                ):
                    if int(operator_readiness.get(count_key) or 0) < 0:
                        issues.append(f"operator_readiness_aggregate {count_key} must be non-negative")
                component_keys = operator_readiness.get("component_keys") or []
                steering_component_keys = operator_readiness.get("steering_component_keys") or []
                attention_component_keys = operator_readiness.get("attention_component_keys") or []
                supplemental_attention_component_keys = operator_readiness.get("supplemental_attention_component_keys") or []
                supplemental_next_actions = operator_readiness.get("supplemental_next_actions") or []
                if not isinstance(component_keys, list) or any(not str(item).strip() for item in component_keys):
                    issues.append("operator_readiness_aggregate component_keys must be a list of non-empty strings")
                if not isinstance(steering_component_keys, list) or any(not str(item).strip() for item in steering_component_keys):
                    issues.append("operator_readiness_aggregate steering_component_keys must be a list of non-empty strings")
                if not isinstance(attention_component_keys, list) or any(
                    not str(item).strip() for item in attention_component_keys
                ):
                    issues.append(
                        "operator_readiness_aggregate attention_component_keys must be a list of non-empty strings"
                    )
                if not isinstance(supplemental_attention_component_keys, list) or any(
                    not str(item).strip() for item in supplemental_attention_component_keys
                ):
                    issues.append(
                        "operator_readiness_aggregate supplemental_attention_component_keys must be a list of non-empty strings"
                    )
                if not isinstance(supplemental_next_actions, list):
                    issues.append("operator_readiness_aggregate supplemental_next_actions must be a list")
                operator_source = next(
                    (
                        dict(source)
                        for source in sources
                        if isinstance(source, dict)
                        and Path(str(source.get("path") or "")).name == OPERATOR_READINESS_RECEIPT_NAME
                    ),
                    {},
                )
                if not operator_source:
                    issues.append("detect lens must cite the operator readiness receipt")
                else:
                    operator_source_path_text = str(operator_source.get("path") or "").strip()
                    operator_source_path = repo_root / operator_source_path_text if operator_source_path_text else None
                    operator_source_present = bool(operator_source.get("present"))
                    if not operator_source_present:
                        if str(operator_readiness.get("status") or "").strip() != "missing_receipt":
                            issues.append(
                                "operator_readiness_aggregate status must be missing_receipt when the source receipt is absent"
                            )
                        if operator_readiness.get("ready") is not False:
                            issues.append(
                                "operator_readiness_aggregate ready must be false when the source receipt is absent"
                            )
                        if str(operator_readiness.get("pairing_probe_mode") or "").strip():
                            issues.append(
                                "operator_readiness_aggregate pairing_probe_mode must be empty when the source receipt is absent"
                            )
                        if int(operator_readiness.get("component_count") or 0) != 0:
                            issues.append(
                                "operator_readiness_aggregate component_count must be zero when the source receipt is absent"
                            )
                        if int(operator_readiness.get("blocked_count") or 0) != 0:
                            issues.append(
                                "operator_readiness_aggregate blocked_count must be zero when the source receipt is absent"
                            )
                        if int(operator_readiness.get("probe_failed_count") or 0) != 0:
                            issues.append(
                                "operator_readiness_aggregate probe_failed_count must be zero when the source receipt is absent"
                            )
                        if int(operator_readiness.get("supplemental_attention_count") or 0) != 0:
                            issues.append(
                                "operator_readiness_aggregate supplemental_attention_count must be zero when the source receipt is absent"
                            )
                        if int(operator_readiness.get("supplemental_blocked_count") or 0) != 0:
                            issues.append(
                                "operator_readiness_aggregate supplemental_blocked_count must be zero when the source receipt is absent"
                            )
                        if int(operator_readiness.get("supplemental_probe_failed_count") or 0) != 0:
                            issues.append(
                                "operator_readiness_aggregate supplemental_probe_failed_count must be zero when the source receipt is absent"
                            )
                        if component_keys:
                            issues.append(
                                "operator_readiness_aggregate component_keys must be empty when the source receipt is absent"
                            )
                        if steering_component_keys:
                            issues.append(
                                "operator_readiness_aggregate steering_component_keys must be empty when the source receipt is absent"
                            )
                        if attention_component_keys:
                            issues.append(
                                "operator_readiness_aggregate attention_component_keys must be empty when the source receipt is absent"
                            )
                        if supplemental_attention_component_keys:
                            issues.append(
                                "operator_readiness_aggregate supplemental_attention_component_keys must be empty when the source receipt is absent"
                            )
                        if str(operator_readiness.get("next_action") or "").strip():
                            issues.append(
                                "operator_readiness_aggregate next_action must be empty when the source receipt is absent"
                            )
                        if supplemental_next_actions:
                            issues.append(
                                "operator_readiness_aggregate supplemental_next_actions must be empty when the source receipt is absent"
                            )
                        if str(operator_readiness.get("summary") or "").strip():
                            issues.append(
                                "operator_readiness_aggregate summary must be empty when the source receipt is absent"
                            )
                    elif operator_source_path and operator_source_path.exists():
                        operator_payload = _json(operator_source_path)
                        expected_component_keys = [
                            str(item).strip()
                            for item in list(operator_payload.get("component_keys") or [])
                            if str(item).strip()
                        ]
                        expected_steering_component_keys = [
                            str(item).strip()
                            for item in list(operator_payload.get("steering_component_keys") or [])
                            if str(item).strip()
                        ]
                        expected_attention_component_keys = [
                            str(item).strip()
                            for item in list(operator_payload.get("attention_component_keys") or [])
                            if str(item).strip()
                        ]
                        expected_supplemental_attention_component_keys = [
                            str(item).strip()
                            for item in list(operator_payload.get("supplemental_attention_component_keys") or [])
                            if str(item).strip()
                        ]
                        expected_supplemental_next_actions = [
                            {
                                "component_key": str(dict(item).get("component_key") or "").strip(),
                                "action": str(dict(item).get("action") or "").strip(),
                                "href": str(dict(item).get("href") or "").strip(),
                                "label": str(dict(item).get("label") or "").strip(),
                                "method": str(dict(item).get("method") or "").strip(),
                                "reason": str(dict(item).get("reason") or "").strip(),
                            }
                            for item in list(operator_payload.get("supplemental_next_actions") or [])
                            if isinstance(item, dict) and str(dict(item).get("component_key") or "").strip()
                        ]
                        if str(operator_readiness.get("status") or "").strip() != str(
                            operator_payload.get("status") or "missing_receipt"
                        ).strip().lower():
                            issues.append(
                                "operator_readiness_aggregate status must mirror operator readiness receipt"
                            )
                        if bool(operator_readiness.get("ready")) != bool(operator_payload.get("ready")):
                            issues.append(
                                "operator_readiness_aggregate ready must mirror operator readiness receipt"
                            )
                        if str(operator_readiness.get("pairing_probe_mode") or "").strip() != str(
                            operator_payload.get("pairing_probe_mode") or ""
                        ).strip():
                            issues.append(
                                "operator_readiness_aggregate pairing_probe_mode must mirror operator readiness receipt"
                            )
                        if int(operator_readiness.get("component_count") or 0) != int(
                            operator_payload.get("component_count") or 0
                        ):
                            issues.append(
                                "operator_readiness_aggregate component_count must mirror operator readiness receipt"
                            )
                        if int(operator_readiness.get("blocked_count") or 0) != int(
                            operator_payload.get("blocked_count") or 0
                        ):
                            issues.append(
                                "operator_readiness_aggregate blocked_count must mirror operator readiness receipt"
                            )
                        if int(operator_readiness.get("probe_failed_count") or 0) != int(
                            operator_payload.get("probe_failed_count") or 0
                        ):
                            issues.append(
                                "operator_readiness_aggregate probe_failed_count must mirror operator readiness receipt"
                            )
                        if int(operator_readiness.get("supplemental_attention_count") or 0) != int(
                            operator_payload.get("supplemental_attention_count") or 0
                        ):
                            issues.append(
                                "operator_readiness_aggregate supplemental_attention_count must mirror operator readiness receipt"
                            )
                        if int(operator_readiness.get("supplemental_blocked_count") or 0) != int(
                            operator_payload.get("supplemental_blocked_count") or 0
                        ):
                            issues.append(
                                "operator_readiness_aggregate supplemental_blocked_count must mirror operator readiness receipt"
                            )
                        if int(operator_readiness.get("supplemental_probe_failed_count") or 0) != int(
                            operator_payload.get("supplemental_probe_failed_count") or 0
                        ):
                            issues.append(
                                "operator_readiness_aggregate supplemental_probe_failed_count must mirror operator readiness receipt"
                            )
                        if component_keys != expected_component_keys:
                            issues.append(
                                "operator_readiness_aggregate component_keys must mirror operator readiness receipt"
                            )
                        if steering_component_keys != expected_steering_component_keys:
                            issues.append(
                                "operator_readiness_aggregate steering_component_keys must mirror operator readiness receipt"
                            )
                        if attention_component_keys != expected_attention_component_keys:
                            issues.append(
                                "operator_readiness_aggregate attention_component_keys must mirror operator readiness receipt"
                            )
                        if supplemental_attention_component_keys != expected_supplemental_attention_component_keys:
                            issues.append(
                                "operator_readiness_aggregate supplemental_attention_component_keys must mirror operator readiness receipt"
                            )
                        if str(operator_readiness.get("next_action") or "").strip() != str(
                            operator_payload.get("next_action") or ""
                        ).strip():
                            issues.append(
                                "operator_readiness_aggregate next_action must mirror operator readiness receipt"
                            )
                        if supplemental_next_actions != expected_supplemental_next_actions:
                            issues.append(
                                "operator_readiness_aggregate supplemental_next_actions must mirror operator readiness receipt"
                            )
                        if _normalize_operator_readiness_summary(operator_readiness.get("summary")) != _normalize_operator_readiness_summary(
                            operator_payload.get("summary")
                        ):
                            issues.append(
                                "operator_readiness_aggregate summary must mirror operator readiness receipt"
                            )
        if key == "decide":
            provider_cost = lens.get("provider_cost_control")
            if not isinstance(provider_cost, dict):
                issues.append("decide lens must include provider_cost_control")
            else:
                if provider_cost.get("status") != "active_cost_control":
                    issues.append("decide provider_cost_control status must be active_cost_control")
                if provider_cost.get("primary_background_provider") != "onemin":
                    issues.append("decide provider_cost_control primary background provider must be onemin")
                if list(provider_cost.get("default_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_control default provider order drifted")
                if list(provider_cost.get("fast_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_control fast provider order drifted")
                if list(provider_cost.get("cheap_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_control cheap provider order drifted")
                if list(provider_cost.get("groundwork_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_control groundwork provider order drifted")
                if list(provider_cost.get("hard_provider_order") or [])[:3] != HARD_PROVIDER_ORDER:
                    issues.append("decide provider_cost_control hard provider order drifted")
                if "groundwork" not in list(provider_cost.get("cost_sensitive_lanes") or []):
                    issues.append("decide provider_cost_control must include groundwork as cost-sensitive")
                if provider_cost.get("onemin_preferred_when_speed_is_not_critical") is not True:
                    issues.append("decide provider_cost_control must prefer 1min.ai when speed is not critical")
                if provider_cost.get("onemin_preferred_whenever_usable") is not True:
                    issues.append("decide provider_cost_control must prefer 1min.ai whenever usable")
                if provider_cost.get("gemini_provider_key") != "gemini_vortex":
                    issues.append("decide provider_cost_control Gemini provider key drifted")
                if provider_cost.get("gemini_token_tracking_required") is not True:
                    issues.append("decide provider_cost_control must require Gemini token tracking")
                if provider_cost.get("gemini_dispatch_ledger") != "provider_dispatch_events.jsonl":
                    issues.append("decide provider_cost_control dispatch ledger drifted")
                if (
                    provider_cost.get("gemini_live_pressure_probe_command")
                    != "python3 scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format json"
                ):
                    issues.append("decide provider_cost_control Gemini live pressure probe command missing")
                if provider_cost.get("gemini_live_pressure_probe_source") != "runtime_container_exec:provider_ledger_cache":
                    issues.append("decide provider_cost_control Gemini live pressure probe source missing")
                if provider_cost.get("gemini_soft_cap_env") != "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H":
                    issues.append("decide provider_cost_control Gemini soft-cap env drifted")
                if provider_cost.get("gemini_soft_cap_window_env") != "EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS":
                    issues.append("decide provider_cost_control Gemini soft-cap window env drifted")
                if (
                    provider_cost.get("gemini_soft_cap_action")
                    != "remove_gemini_vortex_from_cost_gated_background_candidate_lists"
                ):
                    issues.append("decide provider_cost_control Gemini soft-cap action drifted")
                if provider_cost.get("explicit_gemini_requests_allowed") is not True:
                    issues.append("decide provider_cost_control must keep explicit Gemini requests allowed")
                if (
                    provider_cost.get("billing_truth_boundary")
                    != "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
                ):
                    issues.append("decide provider_cost_control billing truth boundary missing")
                for privacy_key in (
                    "raw_provider_secret_exposed",
                    "raw_prompt_or_response_text_exposed",
                    "raw_google_cloud_billing_account_exposed",
                ):
                    if provider_cost.get(privacy_key) is not False:
                        issues.append(f"decide provider_cost_control must not expose {privacy_key}")
            provider_pressure = lens.get("provider_cost_pressure")
            if not isinstance(provider_pressure, dict):
                issues.append("decide lens must include provider_cost_pressure")
            else:
                if provider_pressure.get("present") is not True:
                    issues.append("decide provider_cost_pressure must be present")
                if provider_pressure.get("checked") is not True:
                    issues.append("decide provider_cost_pressure must be checked")
                if provider_pressure.get("primary_background_provider") != "onemin":
                    issues.append("decide provider_cost_pressure primary background provider must be onemin")
                if list(provider_pressure.get("provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_pressure provider order drifted")
                if list(provider_pressure.get("fast_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_pressure fast provider order drifted")
                if list(provider_pressure.get("cheap_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_pressure cheap provider order drifted")
                if list(provider_pressure.get("groundwork_provider_order") or [])[:3] != CHEAP_PROVIDER_ORDER:
                    issues.append("decide provider_cost_pressure groundwork provider order drifted")
                if list(provider_pressure.get("hard_provider_order") or [])[:3] != HARD_PROVIDER_ORDER:
                    issues.append("decide provider_cost_pressure hard provider order drifted")
                if provider_pressure.get("onemin_preferred_when_speed_is_not_critical") is not True:
                    issues.append("decide provider_cost_pressure must prefer 1min.ai when speed is not critical")
                if provider_pressure.get("onemin_preferred_whenever_usable") is not True:
                    issues.append("decide provider_cost_pressure must prefer 1min.ai whenever usable")
                if provider_pressure.get("gemini_provider_key") != "gemini_vortex":
                    issues.append("decide provider_cost_pressure Gemini provider key drifted")
                if (
                    provider_pressure.get("gemini_billing_truth_boundary")
                    != "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
                ):
                    issues.append("decide provider_cost_pressure Gemini billing truth boundary missing")
                for token_key in ("gemini_24h_request_count", "gemini_24h_tokens_in", "gemini_24h_tokens_out", "gemini_24h_total_tokens"):
                    if int(provider_pressure.get(token_key) or 0) < 0:
                        issues.append(f"decide provider_cost_pressure {token_key} must be non-negative")
                if provider_pressure.get("gemini_background_cost_gate") not in {"open", "closed", "unlimited"}:
                    issues.append("decide provider_cost_pressure Gemini background cost gate missing")
                if provider_pressure.get("explicit_gemini_requests_allowed") is not True:
                    issues.append("decide provider_cost_pressure must keep explicit Gemini requests allowed")
                for privacy_key in (
                    "raw_provider_secret_exposed",
                    "raw_prompt_or_response_text_exposed",
                    "raw_google_cloud_billing_account_exposed",
                    "raw_provider_slots_exposed",
                ):
                    if provider_pressure.get(privacy_key) is not False:
                        issues.append(f"decide provider_cost_pressure must not expose {privacy_key}")
        if key == "deliver":
            components = list(lens.get("components") or [])
            component_keys = {str(component.get("key") or "") for component in components if isinstance(component, dict)}
            expected_components = set(EXPECTED_COMPONENTS["deliver"])
            pushbullet_receipt_path = repo_root / ".codex-studio/published" / PUSHBULLET_RECEIPT_NAME
            mymedia_receipt_path = repo_root / ".codex-studio/published" / MYMEDIA_RECEIPT_NAME
            if pushbullet_receipt_path.exists():
                expected_components.add("pushbullet_delivery")
            if mymedia_receipt_path.exists():
                expected_components.add("mymedia_alexa")
            for component in components:
                if not isinstance(component, dict):
                    continue
                component_key = str(component.get("key") or "").strip()
                source_names = {
                    _source_ref_name(str(source.get("path") or ""))
                    for source in list(component.get("source_receipts") or [])
                    if isinstance(source, dict)
                }
                if {PUSHBULLET_RECEIPT_NAME, PUSHBULLET_RUNTIME_RECEIPT_NAME} & source_names:
                    expected_components.add("pushbullet_delivery")
                if MYMEDIA_RECEIPT_NAME in source_names:
                    expected_components.add("mymedia_alexa")
            if component_keys != expected_components:
                issues.append("deliver lens components drifted")
            for component in components:
                if not isinstance(component, dict):
                    issues.append("deliver lens components must be objects")
                    continue
                component_key = str(component.get("key") or "").strip() or "unknown"
                component_status = str(component.get("status") or "").strip()
                if not component_status:
                    issues.append(f"deliver component status missing for {component_key}")
                elif component_status not in KNOWN_STATUSES:
                    issues.append(f"deliver component status uses unknown value for {component_key}: {component_status}")
                component_sources = list(component.get("source_receipts") or [])
                if component_status == "pass":
                    if not component_sources:
                        issues.append(f"deliver component pass requires source receipts for {component_key}")
                    for source in component_sources:
                        if not isinstance(source, dict):
                            issues.append(f"deliver component source receipts must be objects for {component_key}")
                            continue
                        source_status = str(source.get("status") or "").strip().lower()
                        if source_status != "pass":
                            issues.append(
                                f"deliver component pass requires every source receipt to pass for {component_key}: {source_status}"
                            )
                        if source.get("source_fresh_to_current_source") is not True:
                            issues.append(f"deliver component pass requires source-fresh receipts for {component_key}")
                if component_key == "pushbullet_delivery":
                    for privacy_key in ("raw_email_exposed", "raw_token_exposed"):
                        if component.get(privacy_key) is not False:
                            issues.append(f"pushbullet delivery component must not expose {privacy_key}")
                    source_names = {
                        _source_ref_name(str(source.get("path") or ""))
                        for source in component_sources
                        if isinstance(source, dict)
                    }
                    if not ({PUSHBULLET_RECEIPT_NAME, PUSHBULLET_RUNTIME_RECEIPT_NAME} & source_names):
                        issues.append("pushbullet delivery component must cite the Pushbullet readiness receipt")
                    if component_status == "blocked_setup_required":
                        missing_setup = [
                            str(item).strip()
                            for item in list(component.get("missing_setup") or [])
                            if str(item).strip()
                        ]
                        if not missing_setup:
                            issues.append("blocked Pushbullet delivery component must include missing_setup")
                        if component.get("pushbullet_note_delivery_ready") is not False:
                            issues.append("blocked Pushbullet delivery component must not claim delivery ready")
                if component_key == "mymedia_alexa":
                    for privacy_key in (
                        "raw_refresh_token_exposed",
                        "raw_paired_user_exposed",
                        "raw_watch_folder_paths_exposed",
                        "raw_public_ip_exposed",
                        "raw_pairing_resume_url_exposed",
                    ):
                        if component.get(privacy_key) is not False:
                            issues.append(f"My Media component must not expose {privacy_key}")
                    source_names = {
                        Path(str(source.get("path") or "")).name
                        for source in component_sources
                        if isinstance(source, dict)
                    }
                    if MYMEDIA_RECEIPT_NAME not in source_names:
                        issues.append("My Media component must cite the My Media readiness receipt")
                    if component.get("echo_playback_claim_allowed") is not False:
                        issues.append("My Media component must not claim real Echo playback readiness")
                    if component.get("pairing_resume_ready") and not str(component.get("pairing_resume_command") or "").strip():
                        issues.append("My Media component pairing resume state requires a resume command")
                    if component.get("telegram_delivery_ready") not in {True, False}:
                        issues.append("My Media component must expose telegram_delivery_ready as a boolean")
                    if component.get("telegram_delivery_ready") is not True and not str(component.get("telegram_delivery_reason") or "").strip():
                        issues.append("My Media component must explain Telegram delivery repair when telegram_delivery_ready is false")
            if status not in {"mixed_local_progress", "ready_local_evidence", "pass"}:
                issues.append("deliver lens must stay conservative (mixed_local_progress, ready_local_evidence, or pass)")
        if key == "recover":
            sources = list(lens.get("source_receipts") or [])
            if not sources:
                if status != "command_backed_no_published_receipt":
                    issues.append("recover lens without a source receipt must stay command-backed")
            else:
                if len(sources) not in {1, 2}:
                    issues.append("recover lens must have one readiness receipt and optional proof receipt")
                source_names = {Path(str(source.get("path") or "")).name for source in sources if isinstance(source, dict)}
                if "teable_env_recovery_readiness.generated.json" not in source_names:
                    issues.append("recover lens must include the Teable recovery readiness receipt")
                proof_present = TEABLE_RECOVERY_PROOF_RECEIPT_NAME in source_names
                proof_source_fresh = False
                source_statuses: list[str] = []
                for source in sources:
                    if not isinstance(source, dict):
                        issues.append("recover source receipts must be objects")
                        continue
                    path_text = str(source.get("path") or "").strip()
                    if not path_text:
                        issues.append("recover source receipt path missing")
                        continue
                    source_path = repo_root / path_text
                    if bool(source.get("present")) != source_path.exists():
                        issues.append(f"recover source receipt presence drifted for {path_text}")
                    payload_status = "missing_receipt"
                    if source_path.exists():
                        payload = _json(source_path)
                        source_status = str(source.get("status") or "").strip().lower()
                        payload_status = str(payload.get("status") or "missing_receipt").strip().lower()
                        if source_status != payload_status:
                            issues.append(f"recover source receipt status drifted for {path_text}")
                    if Path(path_text).name == TEABLE_RECOVERY_PROOF_RECEIPT_NAME:
                        proof_source_fresh = bool(source.get("source_fresh_to_current_source"))
                    source_statuses.append(payload_status)
                if status == "pass":
                    if not proof_present:
                        issues.append("recover lens pass requires a mirrored Teable recovery proof receipt")
                    if "pass" not in source_statuses:
                        issues.append("recover lens pass requires a pass recovery proof receipt")
                    if not proof_source_fresh:
                        issues.append("recover lens pass requires a source-fresh Teable recovery proof receipt")
                elif status not in {"ready_local_audit", "blocked"}:
                    issues.append("recover lens with mirrored receipts must stay ready_local_audit, blocked, or pass")
                elif str(status).lower() not in source_statuses:
                    issues.append("recover lens non-pass status must mirror one of its source receipts")
                if status not in {"ready_local_audit", "blocked", "pass"}:
                    issues.append("recover lens with a mirrored receipt must stay conservative")

    blocking_reasons = [str(item) for item in list(receipt.get("blocking_reasons") or []) if str(item).strip()]
    if by_key.get("prove", {}).get("status") == "blocked_real_world_acceptance" and receipt.get("overall_status") != "blocked_real_world_acceptance":
        issues.append("overall_status must stay blocked_real_world_acceptance while the prove lens is blocked_real_world_acceptance")
    if "The recover lens may use a mirrored local readiness receipt, but it must not claim pass until a source-fresh fresh-host Teable recovery drill receipt is mirrored." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing recover rule about source-fresh mirrored Teable recovery receipts")
    if "Irreversible purchases, bookings, cancellations, outbound commitments, and sent messages must stay consent-gated even when proactive OODA staging is automated." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing proactive OODA consent-gate rule")
    if "Telegram is an action surface, not a progress log; proactive delivery must stay quiet unless the user needs to approve, choose, unblock, review, or answer something." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing action-required-only Telegram rule")
    if "Proactive OODA packets must pass a context/provider-fit auditor before user delivery; reachable URLs, extracted email addresses, or generic search hits are not sufficient." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing proactive OODA auditor-before-delivery rule")
    if "Pocket.ai or other consented audio transcripts may feed OODA only as approved signals with privacy, retention, source, and current/stale status preserved." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing transcript-ingest rule")
    if "Provider-cost governance is part of the goal: whenever a lane can route through the active 1min.ai manager it should prefer 1min.ai first, Gemini/Vertex usage must be token-tracked, and Gemini soft caps may remove it from background candidate lists without blocking explicit Gemini requests." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing provider-cost governance rule")
    if "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing Teable projection rule for proactive OODA")
    required_next_receipts = set(str(item) for item in list(receipt.get("required_next_receipts") or []) if str(item).strip())
    acceptance_proof_requirements = list(receipt.get("acceptance_proof_requirements") or [])
    pending_visible_proof_keys = {
        str(requirement.get("key") or "").strip()
        for requirement in acceptance_proof_requirements
        if isinstance(requirement, dict)
        and str(requirement.get("status") or "").strip() != "satisfied"
        and dict(requirement.get("action_context") or {}).get("operator_queue_visible") is not False
    }
    operator_action_queue = list(receipt.get("operator_action_queue") or [])
    if pending_visible_proof_keys and not operator_action_queue:
        issues.append("operator_action_queue must be present while required_next_receipts is nonempty")
    operator_delivery_policy = receipt.get("operator_delivery_policy")
    if not isinstance(operator_delivery_policy, dict):
        issues.append("operator_delivery_policy must be present")
        operator_delivery_policy = {}
    else:
        if operator_delivery_policy.get("action_required_only") is not True:
            issues.append("operator_delivery_policy.action_required_only must be true")
        if operator_delivery_policy.get("non_action_progress_push_allowed") is not False:
            issues.append("operator_delivery_policy.non_action_progress_push_allowed must be false")
        if operator_delivery_policy.get("quiet_hours_respected") is not True:
            issues.append("operator_delivery_policy.quiet_hours_respected must be true")
        if operator_delivery_policy.get("irreversible_actions_consent_gated") is not True:
            issues.append("operator_delivery_policy.irreversible_actions_consent_gated must be true")
        if list(operator_delivery_policy.get("default_action_digest_streams") or []) != DEFAULT_ACTION_DIGEST_STREAMS:
            issues.append("operator_delivery_policy.default_action_digest_streams drifted")
    queue_keys: set[str] = set()
    if operator_action_queue:
        first_action = dict(operator_action_queue[0]) if isinstance(operator_action_queue[0], dict) else {}
        if not first_action:
            issues.append("operator_action_queue entries must be objects")
        else:
            for key, receipt_key in (
                ("next_action", "next_action"),
                ("next_action_href", "next_action_href"),
                ("next_action_label", "next_action_label"),
                ("next_action_method", "next_action_method"),
                ("next_action_form_href", "next_action_form_href"),
                ("next_action_form_label", "next_action_form_label"),
                ("next_action_form_method", "next_action_form_method"),
                ("key", "next_action_key"),
                ("instruction", "next_action_instruction"),
            ):
                if str(first_action.get(key) or "").strip() != str(receipt.get(receipt_key) or "").strip():
                    issues.append(f"top-level {receipt_key} must match first operator_action_queue item")
        for row in operator_action_queue:
            if not isinstance(row, dict):
                issues.append("operator_action_queue entries must be objects")
                continue
            action_key = str(row.get("key") or "").strip()
            user_action_required = row.get("user_action_required") is True
            if not action_key:
                issues.append("operator_action_queue entries must include key")
            if action_key in queue_keys:
                issues.append(f"operator_action_queue duplicate key: {action_key}")
            queue_keys.add(action_key)
            operator_stream = str(row.get("operator_stream") or "").strip()
            if not operator_stream:
                issues.append(f"operator_action_queue entries must include operator_stream: {action_key}")
            elif operator_stream not in KNOWN_OPERATOR_STREAMS:
                issues.append(f"operator_action_queue uses unknown operator_stream: {action_key}:{operator_stream}")
            if not str(row.get("next_action") or "").strip():
                issues.append(f"operator_action_queue entry missing next_action: {action_key}")
            if not str(row.get("next_action_href") or "").strip():
                issues.append(f"operator_action_queue entry missing next_action_href: {action_key}")
            if user_action_required and not str(row.get("next_action_form_href") or "").strip():
                issues.append(f"operator_action_queue entry missing next_action_form_href: {action_key}")
            if user_action_required and str(row.get("next_action_form_method") or "").strip().lower() != "get":
                issues.append(f"operator_action_queue entry next_action_form_method must be get: {action_key}")
            if row.get("raw_private_context_exposed") is not False:
                issues.append(f"operator_action_queue must not expose raw private context: {action_key}")
            for private_key in ("raw_chat_ids_exposed", "raw_token_exposed", "raw_secret_exposed"):
                if row.get(private_key) is not False:
                    issues.append(f"operator_action_queue must not expose {private_key}: {action_key}")
            if "raw_email_exposed" in row and row.get("raw_email_exposed") is not False:
                issues.append(f"operator_action_queue must not expose raw_email_exposed: {action_key}")
            for google_private_key in (
                "raw_expected_google_email_exposed",
                "raw_observed_google_email_exposed",
                "raw_client_id_exposed",
                "raw_client_secret_exposed",
                "raw_error_description_exposed",
            ):
                if google_private_key in row and row.get(google_private_key) is not False:
                    issues.append(f"operator_action_queue must not expose {google_private_key}: {action_key}")
            for acceptance_private_key in (
                "raw_acceptance_text_exposed",
                "raw_actor_identity_exposed",
                "raw_object_reference_exposed",
                "raw_transcript_fields_exposed",
                "candidate_raw_text_fields_exposed",
            ):
                if acceptance_private_key in row and row.get(acceptance_private_key) is not False:
                    issues.append(f"operator_action_queue must not expose {acceptance_private_key}: {action_key}")
            for whatsapp_private_key in (
                "raw_public_share_url_exposed",
                "raw_track_url_exposed",
                "raw_pair_url_exposed",
                "raw_qr_payload_exposed",
                "raw_whatsapp_session_ref_exposed",
            ):
                if whatsapp_private_key in row and row.get(whatsapp_private_key) is not False:
                    issues.append(f"operator_action_queue must not expose {whatsapp_private_key}: {action_key}")
            if row.get("raw_voice_ids_exposed") is not False:
                issues.append(f"operator_action_queue must not expose raw voice IDs: {action_key}")
            if row.get("callback_tokens_exposed") is not False:
                issues.append(f"operator_action_queue must not expose callback tokens: {action_key}")
            requirement = next(
                (
                    dict(item)
                    for item in acceptance_proof_requirements
                    if isinstance(item, dict) and str(item.get("key") or "").strip() == action_key
                ),
                {},
            )
            action_context = (
                dict(requirement.get("action_context") or {})
                if isinstance(requirement.get("action_context"), dict)
                else {}
            )
            expected_delivery_policy = "action_required_only" if user_action_required else "queue_only"
            if row.get("delivery_policy") != expected_delivery_policy:
                issues.append(f"operator_action_queue delivery_policy mismatch: {action_key}")
            expected_telegram_push_allowed = (
                action_context.get("telegram_push_allowed")
                if isinstance(action_context.get("telegram_push_allowed"), bool)
                else user_action_required
            )
            if row.get("telegram_push_allowed") is not expected_telegram_push_allowed:
                issues.append(f"operator_action_queue telegram_push_allowed mismatch: {action_key}")
            expected_action_digest_eligible = bool(
                user_action_required
                and row.get("delivery_policy") == "action_required_only"
                and row.get("telegram_push_allowed") is True
                and operator_stream in DEFAULT_ACTION_DIGEST_STREAMS
            )
            if row.get("action_digest_eligible") is not expected_action_digest_eligible:
                issues.append(f"operator_action_queue action_digest_eligible mismatch: {action_key}")
            suppressed_reason = str(row.get("default_action_digest_suppressed_reason") or "").strip()
            if expected_action_digest_eligible:
                if suppressed_reason:
                    issues.append(f"digest-eligible queue row must not carry suppression reason: {action_key}")
            elif user_action_required and operator_stream not in DEFAULT_ACTION_DIGEST_STREAMS:
                if suppressed_reason != "operator_stream_not_in_default_action_digest":
                    issues.append(f"default digest stream suppression reason mismatch: {action_key}")
            if row.get("interruption_budget") != ("action_required" if user_action_required else "none"):
                issues.append(f"operator_action_queue interruption_budget mismatch: {action_key}")
            if row.get("quiet_hours_respected") is not True:
                issues.append(f"operator_action_queue quiet_hours_respected must be true: {action_key}")
            if row.get("non_action_progress_push_allowed") is not False:
                issues.append(f"operator_action_queue non-action progress push must be false: {action_key}")
            if row.get("irreversible_actions_consent_gated") is not True:
                issues.append(f"operator_action_queue irreversible actions must be consent-gated: {action_key}")
            if action_key in {
                "morning_brief_operator_acceptance",
                "weekly_signal_to_decision_review_acceptance",
                *EA_QUALITY_ACCEPTANCE_PROOF_KEYS.values(),
            }:
                if row.get("user_action_required") is not True:
                    issues.append(f"real-world acceptance capture must require user action: {action_key}")
                if row.get("delivery_policy") != "action_required_only":
                    issues.append(f"real-world acceptance capture must be action-required only: {action_key}")
                if action_key == "weekly_signal_to_decision_review_acceptance":
                    if row.get("telegram_push_allowed") is not False:
                        issues.append("weekly signal review proof capture must stay out of Telegram pushes")
                    if str(row.get("default_action_digest_suppressed_reason") or "").strip() != "telegram_push_not_allowed":
                        issues.append("weekly signal review proof capture must explain digest suppression")
                elif row.get("telegram_push_allowed") is not True:
                    issues.append(f"real-world acceptance capture may push only as an action-required item: {action_key}")
                if row.get("non_action_progress_push_allowed") is not False:
                    issues.append(f"real-world acceptance capture must not allow progress pushes: {action_key}")
            if action_key == "manfred_stt_tts_realtime_conversation":
                if row.get("manual_only") is True:
                    if row.get("user_action_required") is not True:
                        issues.append("manual Manfred room attestation must require user action")
                    if row.get("delivery_policy") != "action_required_only":
                        issues.append("manual Manfred room attestation must be action-required only")
                    if row.get("telegram_push_allowed") is not True:
                        issues.append("manual Manfred room attestation may push only as an action-required item")
                    if row.get("ci_must_not_auto_assert") is not True:
                        issues.append("manual Manfred room attestation must preserve ci_must_not_auto_assert")
                    if int(row.get("required_check_count") or 0) <= 0:
                        issues.append("manual Manfred room attestation must include required_check_count")
            if row.get("stale_source_receipts"):
                if user_action_required:
                    issues.append(f"stale source refresh must not require user action: {action_key}")
                if row.get("telegram_push_allowed") is not False:
                    issues.append(f"stale source refresh must not allow Telegram push: {action_key}")
                refresh_commands = list(row.get("refresh_commands") or [])
                if not refresh_commands:
                    issues.append(f"stale source refresh must include refresh_commands: {action_key}")
                if not any("verify_continuous_improvement_goal_posture.py" in str(command) for command in refresh_commands):
                    issues.append(f"stale source refresh must include continuous posture verification: {action_key}")
        if isinstance(operator_delivery_policy, dict) and first_action:
            digest_eligible_count = sum(
                1
                for row in operator_action_queue
                if isinstance(row, dict) and row.get("action_digest_eligible") is True
            )
            digest_suppressed_count = sum(
                1
                for row in operator_action_queue
                if isinstance(row, dict)
                and row.get("user_action_required") is True
                and row.get("action_digest_eligible") is not True
            )
            if int(operator_delivery_policy.get("default_action_digest_eligible_count") or 0) != digest_eligible_count:
                issues.append("operator_delivery_policy.default_action_digest_eligible_count must match queue")
            if int(operator_delivery_policy.get("default_action_digest_suppressed_count") or 0) != digest_suppressed_count:
                issues.append("operator_delivery_policy.default_action_digest_suppressed_count must match queue")
            if operator_delivery_policy.get("telegram_push_allowed_for_next_action") is not bool(
                first_action.get("telegram_push_allowed")
            ):
                issues.append("operator_delivery_policy.telegram_push_allowed_for_next_action must match first queue item")
            if operator_delivery_policy.get("next_action_digest_eligible") is not bool(
                first_action.get("action_digest_eligible")
            ):
                issues.append("operator_delivery_policy.next_action_digest_eligible must match first queue item")
            if operator_delivery_policy.get("next_action_requires_user") is not bool(first_action.get("user_action_required")):
                issues.append("operator_delivery_policy.next_action_requires_user must match first queue item")
            if str(operator_delivery_policy.get("next_action_delivery_policy") or "").strip() != str(
                first_action.get("delivery_policy") or ""
            ).strip():
                issues.append("operator_delivery_policy.next_action_delivery_policy must match first queue item")
    acceptance_proof_requirements = receipt.get("acceptance_proof_requirements")
    if not isinstance(acceptance_proof_requirements, list) or not acceptance_proof_requirements:
        issues.append("acceptance_proof_requirements must be a non-empty list")
        acceptance_proof_requirements = []
    proof_receipts: set[str] = set()
    proof_keys: set[str] = set()
    proof_by_key: dict[str, dict[str, Any]] = {}
    proactive_source_receipt_names: set[str] = set()
    for index, requirement in enumerate(acceptance_proof_requirements):
        if not isinstance(requirement, dict):
            issues.append(f"acceptance_proof_requirements[{index}] must be an object")
            continue
        missing_fields = sorted(field for field in REQUIRED_PROOF_FIELDS if field not in requirement)
        if missing_fields:
            issues.append(f"acceptance proof requirement missing fields at index {index}: {', '.join(missing_fields)}")
        key = str(requirement.get("key") or "").strip()
        if not key:
            issues.append(f"acceptance proof requirement key missing at index {index}")
        elif key in proof_keys:
            issues.append(f"duplicate acceptance proof requirement key: {key}")
        else:
            proof_keys.add(key)
            proof_by_key[key] = requirement
        lens = str(requirement.get("lens") or "").strip()
        if lens not in REQUIRED_LENSES:
            issues.append(f"acceptance proof requirement {key or index} uses unknown lens: {lens}")
        status = str(requirement.get("status") or "").strip()
        if status not in KNOWN_PROOF_STATUSES:
            issues.append(f"acceptance proof requirement {key or index} uses unknown status: {status}")
        required_receipt = str(requirement.get("required_next_receipt") or "").strip()
        if required_receipt and status != "satisfied":
            proof_receipts.add(required_receipt)
        else:
            if not required_receipt:
                issues.append(f"acceptance proof requirement {key or index} missing required_next_receipt")
        capture_surfaces = [
            str(surface or "").strip()
            for surface in list(requirement.get("capture_surfaces") or [])
            if str(surface or "").strip()
        ]
        if not capture_surfaces:
            issues.append(f"acceptance proof requirement {key or index} must list capture_surfaces")
        if "does_not_prove" not in str(requirement.get("claim_boundary") or ""):
            issues.append(f"acceptance proof requirement {key or index} must keep an explicit does_not_prove claim boundary")
        if not str(requirement.get("evidence_kind") or "").strip():
            issues.append(f"acceptance proof requirement {key or index} missing evidence_kind")
        if not str(requirement.get("next_action") or "").strip():
            issues.append(f"acceptance proof requirement {key or index} missing next_action")
        action_context = (
            dict(requirement.get("action_context") or {})
            if isinstance(requirement.get("action_context"), dict)
            else {}
        )
        proactive_user_action_required = (
            key == "proactive_ooda_packet_acceptance"
            and action_context.get("user_action_required") is True
        )
        next_action_href = str(requirement.get("next_action_href") or "").strip()
        next_action_label = str(requirement.get("next_action_label") or "").strip()
        next_action_method = str(requirement.get("next_action_method") or "").strip().lower()
        next_action_form_href = str(requirement.get("next_action_form_href") or "").strip()
        next_action_form_label = str(requirement.get("next_action_form_label") or "").strip()
        next_action_form_method = str(requirement.get("next_action_form_method") or "").strip().lower()
        if not next_action_href:
            issues.append(f"acceptance proof requirement {key or index} missing next_action_href")
        if not next_action_label:
            issues.append(f"acceptance proof requirement {key or index} missing next_action_label")
        if next_action_method not in {"get", "post"}:
            issues.append(f"acceptance proof requirement {key or index} has invalid next_action_method")
        if proactive_user_action_required and not next_action_form_href:
            issues.append(f"acceptance proof requirement {key or index} missing next_action_form_href")
        if proactive_user_action_required and not next_action_form_label:
            issues.append(f"acceptance proof requirement {key or index} missing next_action_form_label")
        if proactive_user_action_required and next_action_form_method != "get":
            issues.append(f"acceptance proof requirement {key or index} next_action_form_method must be get")
        expected_surface = EXPECTED_PROOF_ACTION_SURFACES.get(key)
        if key == "proactive_ooda_packet_acceptance" and status == "satisfied":
            expected_surface = ("/app/today", "get")
        if key == "proactive_ooda_packet_acceptance" and not proactive_user_action_required:
            expected_surface = None
        if (
            key == "proactive_ooda_packet_acceptance"
            and str(requirement.get("next_action") or "").strip() == "stage_fresh_assistant_grade_proactive_packet"
        ):
            expected_surface = ("/app/queue", "get")
        if (
            key == "telegram_audiobook_live_delivery"
            and str(requirement.get("next_action") or "").strip()
            == "send_missing_telegram_audiobook_voice_samples_before_user_choice"
        ):
            expected_surface = ("/app/channel-loop", "get")
        if expected_surface:
            expected_href, expected_method = expected_surface
            if expected_href not in next_action_href:
                issues.append(f"acceptance proof requirement {key} next_action_href must target {expected_href}")
            if next_action_method != expected_method:
                issues.append(f"acceptance proof requirement {key} next_action_method must be {expected_method}")
        expected_form_surface = EXPECTED_PROOF_FORM_SURFACES.get(key)
        if key == "proactive_ooda_packet_acceptance" and status == "satisfied":
            expected_form_surface = ("/app/today", "get")
        if key == "proactive_ooda_packet_acceptance" and not proactive_user_action_required:
            expected_form_surface = None
        if (
            key == "proactive_ooda_packet_acceptance"
            and str(requirement.get("next_action") or "").strip() == "stage_fresh_assistant_grade_proactive_packet"
        ):
            expected_form_surface = ("/app/queue", "get")
        if (
            key == "telegram_audiobook_live_delivery"
            and str(requirement.get("next_action") or "").strip()
            == "send_missing_telegram_audiobook_voice_samples_before_user_choice"
        ):
            expected_form_surface = ("/app/channel-loop", "get")
        if expected_form_surface:
            expected_form_href, expected_form_method = expected_form_surface
            if expected_form_href not in next_action_form_href:
                issues.append(f"acceptance proof requirement {key} next_action_form_href must target {expected_form_href}")
            if next_action_form_method != expected_form_method:
                issues.append(f"acceptance proof requirement {key} next_action_form_method must be {expected_form_method}")
        sources = list(requirement.get("source_receipts") or [])
        if not sources:
            issues.append(f"acceptance proof requirement {key or index} must include source_receipts")
        for source in sources:
            if not isinstance(source, dict):
                issues.append(f"acceptance proof requirement {key or index} source_receipts must be objects")
                continue
            path_text = str(source.get("path") or "").strip()
            if not path_text:
                issues.append(f"acceptance proof requirement {key or index} source receipt path missing")
                continue
            source_path = repo_root / path_text
            source_name = _source_ref_name(path_text)
            if key == "proactive_ooda_packet_acceptance" and source_name in PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS:
                proactive_source_receipt_names.add(source_name)
            source_present = _source_ref_present(repo_root, path_text)
            if bool(source.get("present")) != source_present:
                issues.append(f"acceptance proof requirement {key or index} source receipt presence drifted for {path_text}")
            if key == "proactive_ooda_packet_acceptance" and source_name in PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS:
                if not source_present or _source_ref_is_runtime_backed(path_text):
                    if not source_present:
                        issues.append(f"proactive_ooda_packet_acceptance source receipt missing: {path_text}")
                    continue
                if not source_path.exists():
                    issues.append(f"proactive_ooda_packet_acceptance source receipt missing: {path_text}")
                    continue
                source_payload = _json(source_path)
                source_head = str(source.get("source_git_head") or source_payload.get("source_git_head") or "").strip()
                source_fingerprint = str(
                    source.get("source_state_fingerprint")
                    or source_payload.get("source_state_fingerprint")
                    or ""
                ).strip()
                source_fingerprint_matches = bool(
                    current_fingerprint and source_fingerprint and source_fingerprint == current_fingerprint
                )
                if not source_head:
                    issues.append(f"proactive_ooda_packet_acceptance source receipt missing source_git_head: {path_text}")
                elif current_head and source_head != current_head and not source_fingerprint_matches:
                    issues.append(f"proactive_ooda_packet_acceptance source receipt stale: {path_text}")
                if (
                    current_head
                    and "source_fresh_to_current_source" in source
                    and source.get("source_fresh_to_current_source") is not True
                    and not source_fingerprint_matches
                ):
                    issues.append(f"proactive_ooda_packet_acceptance source receipt freshness flag false: {path_text}")
    if proof_receipts != required_next_receipts:
        issues.append("acceptance_proof_requirements must cover every required_next_receipts item exactly")
    if queue_keys and queue_keys != pending_visible_proof_keys:
        issues.append("operator_action_queue keys must match pending acceptance proof requirement keys")
    acceptance_receipt_path = repo_root / ".codex-studio/published/ea_executive_assistant_acceptance_evidence.generated.json"
    acceptance_receipt = _json(acceptance_receipt_path)
    acceptance_rows = dict(acceptance_receipt.get("acceptance_keys") or {})
    if acceptance_rows:
        for acceptance_key, proof_key in EA_QUALITY_ACCEPTANCE_PROOF_KEYS.items():
            row = dict(acceptance_rows.get(acceptance_key) or {})
            accepted = row.get("accepted") is True or str(row.get("status") or "").strip() == "accepted_redacted"
            requirement = proof_by_key.get(proof_key)
            if not requirement:
                issues.append(f"pending EA quality acceptance key must have proof requirement: {proof_key}")
                continue
            requirement_status = str(requirement.get("status") or "").strip()
            if accepted and requirement_status != "satisfied":
                issues.append(f"accepted EA quality proof must be satisfied: {proof_key}")
            if not accepted:
                if requirement_status != "pending_real_world_evidence":
                    issues.append(f"pending EA quality proof must stay pending: {proof_key}")
                action_context = (
                    dict(requirement.get("action_context") or {})
                    if isinstance(requirement.get("action_context"), dict)
                    else {}
                )
                if action_context.get("operator_queue_visible") is not False and proof_key not in queue_keys:
                    issues.append(f"pending EA quality proof must appear in operator_action_queue: {proof_key}")
    missing_proactive_sources = sorted(PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS - proactive_source_receipt_names)
    if missing_proactive_sources:
        issues.append(f"proactive_ooda_packet_acceptance missing source receipts: {', '.join(missing_proactive_sources)}")
    for blocker_prefix, proof_key in DELIVER_BLOCKER_PROOF_KEYS.items():
        if any(reason.startswith(blocker_prefix) for reason in blocking_reasons) and proof_key not in proof_by_key:
            issues.append(f"active blocker {blocker_prefix} must have acceptance proof requirement {proof_key}")
    proactive_requirement = proof_by_key.get("proactive_ooda_packet_acceptance") or {}
    if not proactive_requirement:
        issues.append("acceptance_proof_requirements must include proactive_ooda_packet_acceptance")
    else:
        if proactive_requirement.get("required_next_receipt") != REQUIRED_PROACTIVE_OODA_RECEIPT:
            issues.append("proactive_ooda_packet_acceptance must cover the proactive OODA proof receipt")
        if proactive_requirement.get("evidence_kind") != "approval_outcome":
            issues.append("proactive_ooda_packet_acceptance evidence_kind must be approval_outcome")
        proactive_status = str(proactive_requirement.get("status") or "").strip()
        proactive_action_context = (
            dict(proactive_requirement.get("action_context") or {})
            if isinstance(proactive_requirement.get("action_context"), dict)
            else {}
        )
        proactive_user_action_required = proactive_action_context.get("user_action_required") is True
        if proactive_status != "satisfied" and REQUIRED_PROACTIVE_OODA_RECEIPT not in required_next_receipts:
            issues.append("required_next_receipts must include proactive OODA Teable proof until proactive acceptance is satisfied")
        next_action = str(proactive_requirement.get("next_action") or "")
        if proactive_status == "satisfied":
            if next_action != "maintain_proactive_ooda_gold_acceptance_evidence":
                issues.append("satisfied proactive_ooda_packet_acceptance must maintain gold acceptance evidence")
        elif proactive_user_action_required and (
            "record_proactive_ooda_approval_outcome" not in next_action
            and "tap_proactive_telegram_approval_button" not in next_action
            and next_action != "stage_fresh_assistant_grade_proactive_packet"
        ):
            issues.append("proactive_ooda_packet_acceptance must point at the Telegram approval outcome capture")
        capture_surfaces = " ".join(str(surface or "") for surface in list(proactive_requirement.get("capture_surfaces") or []))
        if "ea_proactive_ooda_gold_acceptance.generated.json" not in capture_surfaces:
            issues.append("proactive_ooda_packet_acceptance must cite the gold acceptance receipt capture surface")
    recovery_requirement = proof_by_key.get("fresh_host_teable_recovery_drill") or {}
    recover_lens_status = str((by_key.get("recover") or {}).get("status") or "").strip().lower()
    if recover_lens_status != "pass":
        if not recovery_requirement:
            issues.append("acceptance_proof_requirements must include fresh_host_teable_recovery_drill until recover passes")
        elif recovery_requirement.get("required_next_receipt") != FRESH_HOST_TEABLE_RECOVERY_RECEIPT:
            issues.append("fresh_host_teable_recovery_drill must cover the fresh-host recovery receipt")
    if recovery_requirement:
        capture_surfaces = " ".join(str(surface or "") for surface in list(recovery_requirement.get("capture_surfaces") or []))
        if "teable_env_recovery_readiness.generated.json" not in capture_surfaces:
            issues.append("fresh_host_teable_recovery_drill must cite the Teable recovery readiness surface")
    elif FRESH_HOST_TEABLE_RECOVERY_RECEIPT in required_next_receipts:
        issues.append("required_next_receipts includes the Teable recovery receipt without a matching acceptance proof requirement")
    telegram_business = dict((by_key.get("detect") or {}).get("telegram_business_signal_ingest") or {})
    if telegram_business:
        if telegram_business.get("raw_token_exposed") is not False:
            issues.append("telegram_business_signal_ingest must not expose raw token")
        if telegram_business.get("raw_secret_exposed") is not False:
            issues.append("telegram_business_signal_ingest must not expose raw secret")
        if telegram_business.get("raw_chat_ids_exposed") is not False:
            issues.append("telegram_business_signal_ingest must not expose raw chat IDs")
        if telegram_business.get("raw_webhook_url_exposed") is not False:
            issues.append("telegram_business_signal_ingest must not expose raw webhook URL")
        allowed_updates = list(telegram_business.get("allowed_updates") or [])
        if allowed_updates and allowed_updates != [
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        ]:
            issues.append("telegram_business_signal_ingest allowed_updates must be Telegram Business-only")
    telegram_business_requirement = proof_by_key.get("telegram_business_signal_setup") or {}
    business_blocked = any(reason.startswith("detect:telegram_business_signal") for reason in blocking_reasons)
    if business_blocked and not telegram_business_requirement:
        issues.append("blocked Telegram Business signal ingest must have telegram_business_signal_setup proof requirement")
    if telegram_business_requirement:
        capture_surfaces = " ".join(str(surface or "") for surface in list(telegram_business_requirement.get("capture_surfaces") or []))
        if "telegram_business_signal_readiness.generated.json" not in capture_surfaces:
            issues.append("telegram_business_signal_setup must cite the Telegram Business readiness surface")
        if telegram_business_requirement.get("evidence_kind") != "secretary_bot_signal_ingest_setup":
            issues.append("telegram_business_signal_setup evidence_kind mismatch")
        action_context = telegram_business_requirement.get("action_context")
        strict_business_action = isinstance(action_context, dict) and action_context.get("user_action_required") is True
        if business_blocked and strict_business_action:
            if not isinstance(action_context, dict):
                issues.append("blocked telegram_business_signal_setup must include action_context")
            else:
                missing_setup = [
                    str(item).strip()
                    for item in list(action_context.get("missing_setup") or [])
                    if str(item).strip()
                ]
                if not missing_setup:
                    issues.append("blocked telegram_business_signal_setup action_context must include missing_setup")
                setup_checklist = action_context.get("setup_checklist")
                if not isinstance(setup_checklist, list) or not setup_checklist:
                    issues.append("blocked telegram_business_signal_setup action_context must include setup_checklist")
                elif missing_setup:
                    checklist_keys = {
                        str(dict(item).get("key") or "").strip()
                        for item in setup_checklist
                        if isinstance(item, dict)
                    }
                    for missing_key in missing_setup:
                        if missing_key not in checklist_keys:
                            issues.append(f"telegram_business_signal_setup setup_checklist missing key: {missing_key}")
                if not str(action_context.get("telegram_message") or "").strip():
                    issues.append("blocked telegram_business_signal_setup action_context must include telegram_message")
                for private_key in ("raw_chat_ids_exposed", "raw_token_exposed", "raw_secret_exposed"):
                    if action_context.get(private_key) is not False:
                        issues.append(f"telegram_business_signal_setup action_context must not expose {private_key}")
            business_queue_row = next(
                (
                    dict(row)
                    for row in operator_action_queue
                    if isinstance(row, dict) and str(row.get("key") or "").strip() == "telegram_business_signal_setup"
                ),
                {},
            )
            if not business_queue_row:
                issues.append("blocked telegram_business_signal_setup must appear in operator_action_queue")
            else:
                if not business_queue_row.get("setup_checklist"):
                    issues.append("telegram_business_signal_setup queue row must include setup_checklist")
                if not business_queue_row.get("telegram_message"):
                    issues.append("telegram_business_signal_setup queue row must include telegram_message")
                for private_key in ("raw_chat_ids_exposed", "raw_token_exposed", "raw_secret_exposed"):
                    if business_queue_row.get(private_key) is not False:
                        issues.append(f"telegram_business_signal_setup queue row must not expose {private_key}")
    google_oauth = dict((by_key.get("detect") or {}).get("google_workspace_oauth_readiness") or {})
    if google_oauth:
        for private_key in (
            "raw_expected_google_email_exposed",
            "raw_observed_google_email_exposed",
            "raw_client_secret_exposed",
            "raw_access_token_exposed",
            "raw_refresh_token_exposed",
            "raw_error_description_exposed",
        ):
            if google_oauth.get(private_key) is not False:
                issues.append(f"google_workspace_oauth_readiness must not expose {private_key}")
        if str(google_oauth.get("scope_bundle") or "").strip() and str(google_oauth.get("scope_bundle") or "").strip() != "full_workspace":
            issues.append("google_workspace_oauth_readiness scope_bundle must be full_workspace when present")
        if str(google_oauth.get("auth_link_template") or "").strip() and "/app/actions/google/connect?" not in str(
            google_oauth.get("auth_link_template") or ""
        ):
            issues.append("google_workspace_oauth_readiness auth_link_template must target Google connect action")
        if str(google_oauth.get("console_deep_link") or "").strip() and not str(
            google_oauth.get("console_deep_link") or ""
        ).startswith("https://console.cloud.google.com/auth/audience"):
            issues.append("google_workspace_oauth_readiness console_deep_link must target Google Auth Platform Audience")
    google_oauth_requirement = proof_by_key.get("google_workspace_oauth_setup") or {}
    google_oauth_blocked = any(reason.startswith("detect:google_workspace_oauth") for reason in blocking_reasons)
    if google_oauth_blocked and not google_oauth_requirement:
        issues.append("blocked Google Workspace OAuth readiness must have google_workspace_oauth_setup proof requirement")
    if google_oauth_requirement:
        capture_surfaces = " ".join(str(surface or "") for surface in list(google_oauth_requirement.get("capture_surfaces") or []))
        if "ea_google_workspace_oauth_readiness.generated.json" not in capture_surfaces:
            issues.append("google_workspace_oauth_setup must cite the Google Workspace OAuth readiness surface")
        if google_oauth_requirement.get("evidence_kind") != "google_workspace_oauth_test_user_setup":
            issues.append("google_workspace_oauth_setup evidence_kind mismatch")
        expected_google_next_action = str(google_oauth.get("next_action") or "").strip()
        if (
            expected_google_next_action
            and str(google_oauth_requirement.get("next_action") or "").strip() != expected_google_next_action
        ):
            issues.append("google_workspace_oauth_setup next_action must mirror OAuth readiness next_action")
        action_context = google_oauth_requirement.get("action_context")
        strict_google_action = isinstance(action_context, dict) and action_context.get("user_action_required") is True
        if google_oauth_blocked and strict_google_action:
            if not isinstance(action_context, dict):
                issues.append("blocked google_workspace_oauth_setup must include action_context")
            else:
                missing_setup = [
                    str(item).strip()
                    for item in list(action_context.get("missing_setup") or [])
                    if str(item).strip()
                ]
                if not missing_setup:
                    issues.append("blocked google_workspace_oauth_setup action_context must include missing_setup")
                setup_checklist = action_context.get("setup_checklist")
                if not isinstance(setup_checklist, list) or not setup_checklist:
                    issues.append("blocked google_workspace_oauth_setup action_context must include setup_checklist")
                elif missing_setup:
                    checklist_keys = {
                        str(dict(item).get("key") or "").strip()
                        for item in setup_checklist
                        if isinstance(item, dict)
                    }
                    for missing_key in missing_setup:
                        if missing_key not in checklist_keys:
                            issues.append(f"google_workspace_oauth_setup setup_checklist missing key: {missing_key}")
                if "oauth_test_user_missing_or_app_unverified" in missing_setup:
                    if not str(action_context.get("console_deep_link") or "").startswith(
                        "https://console.cloud.google.com/auth/audience"
                    ):
                        issues.append("google_workspace_oauth_setup must include Google Auth Platform console_deep_link")
                    if "/app/actions/google/connect?" not in str(action_context.get("auth_link_template") or ""):
                        issues.append("google_workspace_oauth_setup must include redacted auth_link_template")
                if not str(action_context.get("telegram_message") or "").strip():
                    issues.append("blocked google_workspace_oauth_setup action_context must include telegram_message")
                for private_key in (
                    "raw_expected_google_email_exposed",
                    "raw_observed_google_email_exposed",
                    "raw_client_id_exposed",
                    "raw_client_secret_exposed",
                    "raw_error_description_exposed",
                    "raw_chat_ids_exposed",
                    "raw_token_exposed",
                    "raw_secret_exposed",
                ):
                    if action_context.get(private_key) is not False:
                        issues.append(f"google_workspace_oauth_setup action_context must not expose {private_key}")
            google_queue_row = next(
                (
                    dict(row)
                    for row in operator_action_queue
                    if isinstance(row, dict) and str(row.get("key") or "").strip() == "google_workspace_oauth_setup"
                ),
                {},
            )
            if not google_queue_row:
                issues.append("blocked google_workspace_oauth_setup must appear in operator_action_queue")
            else:
                if (
                    expected_google_next_action
                    and str(google_queue_row.get("next_action") or "").strip() != expected_google_next_action
                ):
                    issues.append("google_workspace_oauth_setup queue row next_action must mirror OAuth readiness next_action")
                if not google_queue_row.get("setup_checklist"):
                    issues.append("google_workspace_oauth_setup queue row must include setup_checklist")
                if not str(google_queue_row.get("console_deep_link") or "").startswith(
                    "https://console.cloud.google.com/auth/audience"
                ):
                    issues.append("google_workspace_oauth_setup queue row must include console_deep_link")
                if "/app/actions/google/connect?" not in str(google_queue_row.get("auth_link_template") or ""):
                    issues.append("google_workspace_oauth_setup queue row must include redacted auth_link_template")
                if not google_queue_row.get("telegram_message"):
                    issues.append("google_workspace_oauth_setup queue row must include telegram_message")
                for private_key in (
                    "raw_expected_google_email_exposed",
                    "raw_observed_google_email_exposed",
                    "raw_client_id_exposed",
                    "raw_client_secret_exposed",
                    "raw_error_description_exposed",
                    "raw_chat_ids_exposed",
                    "raw_token_exposed",
                    "raw_secret_exposed",
                ):
                    if google_queue_row.get(private_key) is not False:
                        issues.append(f"google_workspace_oauth_setup queue row must not expose {private_key}")
    pushbullet_requirement = proof_by_key.get("pushbullet_delivery_setup") or {}
    pushbullet_blocked = any(reason.startswith("deliver:pushbullet_delivery") for reason in blocking_reasons)
    if pushbullet_blocked and not pushbullet_requirement:
        issues.append("blocked Pushbullet delivery readiness must have pushbullet_delivery_setup proof requirement")
    if pushbullet_requirement:
        capture_surfaces = " ".join(str(surface or "") for surface in list(pushbullet_requirement.get("capture_surfaces") or []))
        if (
            PUSHBULLET_RECEIPT_NAME not in capture_surfaces
            and PUSHBULLET_RUNTIME_RECEIPT_NAME not in capture_surfaces
        ):
            issues.append("pushbullet_delivery_setup must cite the Pushbullet readiness surface")
        if pushbullet_requirement.get("evidence_kind") != "delivery_channel_setup":
            issues.append("pushbullet_delivery_setup evidence_kind mismatch")
        action_context = pushbullet_requirement.get("action_context")
        if pushbullet_blocked:
            if not isinstance(action_context, dict):
                issues.append("blocked pushbullet_delivery_setup must include action_context")
            else:
                if action_context.get("kind") != "pushbullet_delivery_setup":
                    issues.append("pushbullet_delivery_setup action_context kind mismatch")
                if action_context.get("user_action_required") is not True:
                    issues.append("blocked pushbullet_delivery_setup must require user action")
                if action_context.get("telegram_push_allowed") is not True:
                    issues.append("pushbullet_delivery_setup may push only as an action-required item")
                if str(action_context.get("delivery_policy") or "").strip() != "action_required_only":
                    issues.append("pushbullet_delivery_setup delivery_policy must be action_required_only")
                missing_setup = [
                    str(item).strip()
                    for item in list(action_context.get("missing_setup") or [])
                    if str(item).strip()
                ]
                if not missing_setup:
                    issues.append("blocked pushbullet_delivery_setup action_context must include missing_setup")
                setup_checklist = action_context.get("setup_checklist")
                if not isinstance(setup_checklist, list) or not setup_checklist:
                    issues.append("blocked pushbullet_delivery_setup action_context must include setup_checklist")
                if not str(action_context.get("telegram_message") or "").strip():
                    issues.append("blocked pushbullet_delivery_setup action_context must include telegram_message")
                if not str(action_context.get("external_setup_url") or "").startswith("https://www.pushbullet.com/"):
                    issues.append("pushbullet_delivery_setup action_context must include Pushbullet setup URL")
                for private_key in ("raw_email_exposed", "raw_token_exposed", "raw_secret_exposed", "raw_chat_ids_exposed"):
                    if action_context.get(private_key) is not False:
                        issues.append(f"pushbullet_delivery_setup action_context must not expose {private_key}")
            pushbullet_queue_row = next(
                (
                    dict(row)
                    for row in operator_action_queue
                    if isinstance(row, dict) and str(row.get("key") or "").strip() == "pushbullet_delivery_setup"
                ),
                {},
            )
            if not pushbullet_queue_row:
                issues.append("blocked pushbullet_delivery_setup must appear in operator_action_queue")
            else:
                if pushbullet_queue_row.get("user_action_required") is not True:
                    issues.append("pushbullet_delivery_setup queue row must require user action")
                if pushbullet_queue_row.get("telegram_push_allowed") is not True:
                    issues.append("pushbullet_delivery_setup queue row must allow action-required Telegram push")
                if not pushbullet_queue_row.get("missing_setup"):
                    issues.append("pushbullet_delivery_setup queue row must include missing_setup")
                if not str(pushbullet_queue_row.get("external_setup_url") or "").startswith("https://www.pushbullet.com/"):
                    issues.append("pushbullet_delivery_setup queue row must include Pushbullet setup URL")
                for private_key in ("raw_email_exposed", "raw_token_exposed", "raw_secret_exposed", "raw_chat_ids_exposed"):
                    if pushbullet_queue_row.get(private_key) is not False:
                        issues.append(f"pushbullet_delivery_setup queue row must not expose {private_key}")
    mymedia_requirement = proof_by_key.get("mymedia_alexa_setup") or {}
    mymedia_blocked = any(reason.startswith("deliver:mymedia_alexa") for reason in blocking_reasons)
    deliver_components = list(dict(by_key.get("deliver") or {}).get("components") or [])
    mymedia_deliver_component = next(
        (
            dict(component)
            for component in deliver_components
            if isinstance(component, dict) and str(component.get("key") or "").strip() == "mymedia_alexa"
        ),
        {},
    )
    if mymedia_blocked and not mymedia_requirement:
        issues.append("blocked My Media readiness must have mymedia_alexa_setup proof requirement")
    if mymedia_requirement:
        capture_surfaces = " ".join(str(surface or "") for surface in list(mymedia_requirement.get("capture_surfaces") or []))
        if MYMEDIA_RECEIPT_NAME not in capture_surfaces:
            issues.append("mymedia_alexa_setup must cite the My Media readiness surface")
        if mymedia_requirement.get("evidence_kind") != "delivery_channel_setup":
            issues.append("mymedia_alexa_setup evidence_kind mismatch")
        action_context = mymedia_requirement.get("action_context")
        if mymedia_blocked:
            if not isinstance(action_context, dict):
                issues.append("blocked mymedia_alexa_setup must include action_context")
            else:
                if action_context.get("kind") != "mymedia_alexa_setup":
                    issues.append("mymedia_alexa_setup action_context kind mismatch")
                if action_context.get("user_action_required") is not True:
                    issues.append("blocked mymedia_alexa_setup must require user action")
                if action_context.get("telegram_push_allowed") is not True:
                    issues.append("mymedia_alexa_setup may push only as an action-required item")
                if str(action_context.get("delivery_policy") or "").strip() != "action_required_only":
                    issues.append("mymedia_alexa_setup delivery_policy must be action_required_only")
                if not str(action_context.get("instruction") or "").strip():
                    issues.append("blocked mymedia_alexa_setup must include instruction")
                missing_setup = [
                    str(item).strip()
                    for item in list(action_context.get("missing_setup") or [])
                    if str(item).strip()
                ]
                if not missing_setup:
                    issues.append("blocked mymedia_alexa_setup action_context must include missing_setup")
                setup_checklist = action_context.get("setup_checklist")
                if not isinstance(setup_checklist, list) or not setup_checklist:
                    issues.append("blocked mymedia_alexa_setup action_context must include setup_checklist")
                if not str(action_context.get("telegram_message") or "").strip():
                    issues.append("blocked mymedia_alexa_setup action_context must include telegram_message")
                if action_context.get("echo_playback_claim_allowed") is not False:
                    issues.append("mymedia_alexa_setup action_context must not claim real Echo playback")
                if action_context.get("pairing_resume_ready") and not str(action_context.get("pairing_resume_command") or "").strip():
                    issues.append("mymedia_alexa_setup resume-ready context must include pairing_resume_command")
                if action_context.get("telegram_delivery_ready") not in {True, False}:
                    issues.append("blocked mymedia_alexa_setup action_context must include telegram_delivery_ready")
                if action_context.get("telegram_delivery_ready") is not True and not str(
                    action_context.get("telegram_delivery_reason") or ""
                ).strip():
                    issues.append("blocked mymedia_alexa_setup action_context must explain Telegram delivery repair")
                if mymedia_deliver_component:
                    if action_context.get("telegram_delivery_ready") is not mymedia_deliver_component.get("telegram_delivery_ready"):
                        issues.append("mymedia_alexa_setup action_context telegram_delivery_ready must match deliver component")
                    if str(action_context.get("telegram_delivery_transport") or "").strip() != str(
                        mymedia_deliver_component.get("telegram_delivery_transport") or ""
                    ).strip():
                        issues.append("mymedia_alexa_setup action_context telegram_delivery_transport must match deliver component")
                    if str(action_context.get("telegram_delivery_reason") or "").strip() != str(
                        mymedia_deliver_component.get("telegram_delivery_reason") or ""
                    ).strip():
                        issues.append("mymedia_alexa_setup action_context telegram_delivery_reason must match deliver component")
                for private_key in (
                    "raw_refresh_token_exposed",
                    "raw_paired_user_exposed",
                    "raw_watch_folder_paths_exposed",
                    "raw_public_ip_exposed",
                    "raw_pairing_resume_url_exposed",
                    "raw_chat_ids_exposed",
                    "raw_token_exposed",
                    "raw_secret_exposed",
                ):
                    if action_context.get(private_key) is not False:
                        issues.append(f"mymedia_alexa_setup action_context must not expose {private_key}")
            mymedia_queue_row = next(
                (
                    dict(row)
                    for row in operator_action_queue
                    if isinstance(row, dict) and str(row.get("key") or "").strip() == "mymedia_alexa_setup"
                ),
                {},
            )
            if not mymedia_queue_row:
                issues.append("blocked mymedia_alexa_setup must appear in operator_action_queue")
            else:
                if mymedia_queue_row.get("user_action_required") is not True:
                    issues.append("mymedia_alexa_setup queue row must require user action")
                if mymedia_queue_row.get("telegram_push_allowed") is not True:
                    issues.append("mymedia_alexa_setup queue row must allow action-required Telegram push")
                if not mymedia_queue_row.get("missing_setup"):
                    issues.append("mymedia_alexa_setup queue row must include missing_setup")
                if not str(mymedia_queue_row.get("instruction") or "").strip():
                    issues.append("mymedia_alexa_setup queue row must include instruction")
                if mymedia_queue_row.get("echo_playback_claim_allowed") is not False:
                    issues.append("mymedia_alexa_setup queue row must not claim real Echo playback")
                if mymedia_queue_row.get("pairing_resume_ready") and not str(mymedia_queue_row.get("pairing_resume_command") or "").strip():
                    issues.append("mymedia_alexa_setup queue row resume-ready state must include pairing_resume_command")
                if mymedia_queue_row.get("telegram_delivery_ready") not in {True, False}:
                    issues.append("mymedia_alexa_setup queue row must include telegram_delivery_ready")
                if mymedia_queue_row.get("telegram_delivery_ready") is not True and not str(
                    mymedia_queue_row.get("telegram_delivery_reason") or ""
                ).strip():
                    issues.append("mymedia_alexa_setup queue row must explain Telegram delivery repair")
                if action_context:
                    if mymedia_queue_row.get("telegram_delivery_ready") is not action_context.get("telegram_delivery_ready"):
                        issues.append("mymedia_alexa_setup queue row telegram_delivery_ready must match action_context")
                    if str(mymedia_queue_row.get("telegram_delivery_transport") or "").strip() != str(
                        action_context.get("telegram_delivery_transport") or ""
                    ).strip():
                        issues.append("mymedia_alexa_setup queue row telegram_delivery_transport must match action_context")
                    if str(mymedia_queue_row.get("telegram_delivery_reason") or "").strip() != str(
                        action_context.get("telegram_delivery_reason") or ""
                    ).strip():
                        issues.append("mymedia_alexa_setup queue row telegram_delivery_reason must match action_context")
                for private_key in (
                    "raw_refresh_token_exposed",
                    "raw_paired_user_exposed",
                    "raw_watch_folder_paths_exposed",
                    "raw_public_ip_exposed",
                    "raw_pairing_resume_url_exposed",
                    "raw_chat_ids_exposed",
                    "raw_token_exposed",
                    "raw_secret_exposed",
                ):
                    if mymedia_queue_row.get(private_key) is not False:
                        issues.append(f"mymedia_alexa_setup queue row must not expose {private_key}")
    telegram_requirement = proof_by_key.get("telegram_audiobook_live_delivery") or {}
    if telegram_requirement:
        capture_surfaces = " ".join(str(surface or "") for surface in list(telegram_requirement.get("capture_surfaces") or []))
        if "telegram_audiobook_live_delivery.generated.json" not in capture_surfaces:
            issues.append("telegram_audiobook_live_delivery must cite the Telegram audiobook live delivery surface")
        action_context = telegram_requirement.get("action_context")
        if action_context is not None:
            if not isinstance(action_context, dict):
                issues.append("telegram_audiobook_live_delivery action_context must be an object when present")
            else:
                if action_context.get("raw_voice_ids_exposed") is not False:
                    issues.append("telegram_audiobook_live_delivery action_context must not expose raw voice IDs")
                if action_context.get("callback_tokens_exposed") is not False:
                    issues.append("telegram_audiobook_live_delivery action_context must not expose callback tokens")
                if action_context.get("kind") == "telegram_audiobook_voice_choice":
                    if not str(action_context.get("operator_action") or "").strip():
                        issues.append("telegram audiobook voice choice action_context must include operator_action")
                    candidate_count = int(action_context.get("candidate_count") or 0)
                    if candidate_count <= 0:
                        issues.append("telegram audiobook voice choice action_context must include candidate_count")
                    if action_context.get("user_action_required") is True:
                        candidate_labels = [
                            str(item).strip()
                            for item in list(action_context.get("candidate_labels") or [])
                            if str(item).strip()
                        ]
                        if not candidate_labels:
                            issues.append("telegram audiobook voice choice action_context must include candidate labels")
                        if action_context.get("candidate_labels_distinct") is not True:
                            issues.append("telegram audiobook voice choice action_context must prove candidate labels are distinct")
                        if int(action_context.get("distinct_candidate_label_count") or 0) != len(set(candidate_labels)):
                            issues.append("telegram audiobook voice choice distinct label count mismatch")
                        author_gender_signal = str(action_context.get("author_gender_signal") or "").strip()
                        if author_gender_signal in {"male", "female"}:
                            if action_context.get("author_gender_matched_candidates_only") is not True:
                                issues.append(
                                    "telegram audiobook voice choice must use only author-gender-matched candidates when author signal is known"
                                )
                            if int(action_context.get("author_gender_mismatch_count") or 0) != 0:
                                issues.append("telegram audiobook voice choice must not expose mismatched author-gender samples")
                            if int(action_context.get("author_gender_match_count") or 0) < candidate_count:
                                issues.append("telegram audiobook voice choice author-gender match count must cover candidates")
                        if action_context.get("sent_samples_cover_expected") is not True:
                            issues.append("telegram audiobook voice choice must prove sent samples cover expected samples")
                    duplicate_suppression = action_context.get("duplicate_suppression")
                    if not isinstance(duplicate_suppression, dict):
                        issues.append("telegram audiobook voice choice action_context must include duplicate_suppression")
                    else:
                        if duplicate_suppression.get("action_required_only") is not True:
                            issues.append("telegram audiobook duplicate_suppression must keep action_required_only=true")
                        if duplicate_suppression.get("only_current_jobs_can_require_user_action") is not True:
                            issues.append(
                                "telegram audiobook duplicate_suppression must keep only_current_jobs_can_require_user_action=true"
                            )
                        if duplicate_suppression.get("raw_voice_ids_exposed") is not False:
                            issues.append("telegram audiobook duplicate_suppression must not expose raw voice IDs")
                        if duplicate_suppression.get("callback_tokens_exposed") is not False:
                            issues.append("telegram audiobook duplicate_suppression must not expose callback tokens")
                        if int(duplicate_suppression.get("duplicate_active_pending_source_key_count") or 0) != 0:
                            issues.append(
                                "telegram audiobook duplicate_suppression must not leave duplicate active pending source keys"
                            )
                        if int(duplicate_suppression.get("active_pending_voice_job_count") or 0) <= 0:
                            issues.append("telegram audiobook duplicate_suppression must include active pending voice jobs")
                telegram_queue_row = next(
                    (
                        dict(row)
                        for row in operator_action_queue
                        if isinstance(row, dict) and str(row.get("key") or "").strip() == "telegram_audiobook_live_delivery"
                    ),
                    {},
                )
                if telegram_queue_row and telegram_queue_row.get("user_action_required") is True:
                    if telegram_queue_row.get("candidate_labels_distinct") is not True:
                        issues.append("telegram audiobook queue row must prove candidate labels are distinct")
                    if telegram_queue_row.get("sent_samples_cover_expected") is not True:
                        issues.append("telegram audiobook queue row must prove sent samples cover expected samples")
                    queue_author_gender_signal = str(telegram_queue_row.get("author_gender_signal") or "").strip()
                    if queue_author_gender_signal in {"male", "female"}:
                        if telegram_queue_row.get("author_gender_matched_candidates_only") is not True:
                            issues.append("telegram audiobook queue row must preserve author-gender matched candidate proof")
                        if int(telegram_queue_row.get("author_gender_mismatch_count") or 0) != 0:
                            issues.append("telegram audiobook queue row must not carry author-gender mismatched samples")
                    queue_duplicate_suppression = telegram_queue_row.get("duplicate_suppression")
                    if not isinstance(queue_duplicate_suppression, dict):
                        issues.append("telegram audiobook queue row must include duplicate_suppression")

    whatsapp_requirement = proof_by_key.get("whatsapp_audiobook_live_delivery") or {}
    whatsapp_blocked_stale = any(
        reason.startswith("deliver:whatsapp_audiobook=blocked_stale_source_evidence") for reason in blocking_reasons
    )
    whatsapp_failed_playback = any(reason.startswith("deliver:whatsapp_audiobook=failed") for reason in blocking_reasons)
    whatsapp_action_context = whatsapp_requirement.get("action_context") if whatsapp_requirement else {}
    whatsapp_blocked_playback = (
        isinstance(whatsapp_action_context, dict)
        and whatsapp_action_context.get("kind") == "public_share_playback_failure"
    )
    whatsapp_sidecar_pairing = (
        isinstance(whatsapp_action_context, dict)
        and whatsapp_action_context.get("kind") == "whatsapp_web_sidecar_pairing_required"
    )
    if whatsapp_requirement and (
        whatsapp_blocked_stale or whatsapp_failed_playback or whatsapp_blocked_playback or whatsapp_sidecar_pairing
    ):
        action_context = whatsapp_requirement.get("action_context")
        if not isinstance(action_context, dict):
            issues.append("blocked WhatsApp audiobook proof must include action_context")
        else:
            if whatsapp_sidecar_pairing:
                expected_kind = "whatsapp_web_sidecar_pairing_required"
            elif whatsapp_blocked_stale:
                expected_kind = "stale_source_evidence_refresh"
            else:
                expected_kind = "public_share_playback_failure"
            if action_context.get("kind") != expected_kind:
                issues.append("blocked WhatsApp audiobook action_context kind mismatch")
            if whatsapp_sidecar_pairing:
                if action_context.get("user_action_required") is not True:
                    issues.append("WhatsApp sidecar pairing must require user action")
                if action_context.get("telegram_push_allowed") is not True:
                    issues.append("WhatsApp sidecar pairing may push only as an action-required item")
                if str(action_context.get("delivery_policy") or "").strip() != "action_required_only":
                    issues.append("WhatsApp sidecar pairing delivery_policy must be action_required_only")
                if not str(action_context.get("instruction") or "").strip():
                    issues.append("WhatsApp sidecar pairing must include instruction")
                if "whatsapp_web_sidecar_pairing" not in [
                    str(item).strip() for item in list(action_context.get("missing_setup") or []) if str(item).strip()
                ]:
                    issues.append("WhatsApp sidecar pairing must identify missing_setup")
                if str(action_context.get("sidecar_status") or "").strip() != "qr_required":
                    issues.append("WhatsApp sidecar pairing must preserve sidecar_status=qr_required")
                if action_context.get("sidecar_qr_required") is not True:
                    issues.append("WhatsApp sidecar pairing must preserve sidecar_qr_required=true")
                pair_url_scope = str(action_context.get("pair_url_scope") or "").strip()
                if pair_url_scope != "public" and action_context.get("pair_url_actionable_from_telegram") is not False:
                    issues.append("non-public WhatsApp pair URLs must not be actionable from Telegram")
                queue_row = next(
                    (
                        dict(row)
                        for row in operator_action_queue
                        if isinstance(row, dict) and str(row.get("key") or "").strip() == "whatsapp_audiobook_live_delivery"
                    ),
                    {},
                )
                if not queue_row:
                    issues.append("WhatsApp sidecar pairing must appear in operator_action_queue")
                else:
                    if queue_row.get("user_action_required") is not True:
                        issues.append("WhatsApp sidecar pairing queue row must require user action")
                    if queue_row.get("telegram_push_allowed") is not True:
                        issues.append("WhatsApp sidecar pairing queue row must allow action-required Telegram push")
                    if str(queue_row.get("delivery_policy") or "").strip() != "action_required_only":
                        issues.append("WhatsApp sidecar pairing queue row delivery_policy must be action_required_only")
                    if str(queue_row.get("sidecar_status") or "").strip() != "qr_required":
                        issues.append("WhatsApp sidecar pairing queue row must preserve sidecar_status=qr_required")
                    if queue_row.get("sidecar_qr_required") is not True:
                        issues.append("WhatsApp sidecar pairing queue row must preserve sidecar_qr_required=true")
                    if str(queue_row.get("pair_url_scope") or "").strip() != "public" and queue_row.get(
                        "pair_url_actionable_from_telegram"
                    ) is not False:
                        issues.append("non-public WhatsApp pair URL queue row must not be actionable from Telegram")
            else:
                if action_context.get("user_action_required") is not False:
                    issues.append("blocked WhatsApp audiobook repair must not require user action")
                if action_context.get("telegram_push_allowed") is not False:
                    issues.append("blocked WhatsApp audiobook repair must not allow Telegram push")
            if whatsapp_blocked_stale:
                stale_receipts = [str(item).strip() for item in list(action_context.get("stale_source_receipts") or []) if str(item).strip()]
                if not stale_receipts:
                    issues.append("stale WhatsApp audiobook refresh must identify stale_source_receipts")
                refresh_commands = [str(item).strip() for item in list(action_context.get("refresh_commands") or []) if str(item).strip()]
                if not refresh_commands:
                    issues.append("stale WhatsApp audiobook refresh must include refresh_commands")
                if not any("materialize_whatsapp_audiobook_live_delivery_receipt.py" in command for command in refresh_commands):
                    issues.append("stale WhatsApp audiobook refresh must include live delivery materializer")
            if whatsapp_failed_playback or whatsapp_blocked_playback:
                if not str(action_context.get("instruction") or "").strip():
                    issues.append("WhatsApp audiobook playback repair must include repair instruction")
                if int(action_context.get("track_response_status") or 0) <= 0:
                    issues.append("WhatsApp audiobook playback repair must include track_response_status")
                if action_context.get("raw_public_share_url_exposed") is not False:
                    issues.append("WhatsApp audiobook playback repair must not expose raw public share URL")
                if action_context.get("raw_track_url_exposed") is not False:
                    issues.append("WhatsApp audiobook playback repair must not expose raw track URL")
            for private_key in (
                "raw_private_context_exposed",
                "raw_chat_ids_exposed",
                "raw_token_exposed",
                "raw_secret_exposed",
                "raw_pair_url_exposed",
                "raw_qr_payload_exposed",
                "raw_whatsapp_session_ref_exposed",
            ):
                if action_context.get(private_key) is not False:
                    issues.append(f"blocked WhatsApp audiobook action_context must not expose {private_key}")
    if by_key.get("recover", {}).get("status") == "command_backed_no_published_receipt" and "recover=command_backed_no_published_receipt" not in blocking_reasons:
        issues.append("blocking_reasons must include the command-backed recover posture")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the continuous-improvement goal posture receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
