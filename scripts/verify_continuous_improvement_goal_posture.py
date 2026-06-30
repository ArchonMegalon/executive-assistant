#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
KNOWN_STATUSES = {
    "pass",
    "ready_local_evidence",
    "ready_local_audit",
    "ready_local_direction",
    "ready_local_packet_pending_operator_acceptance",
    "partial_real_signal_to_decision_closure",
    "ready_for_live_epub_delivery_test",
    "audiobookshelf_imported",
    "mixed_local_progress",
    "ready_local_audit",
    "blocked_real_world_acceptance",
    "blocked_realtime_prerequisites",
    "blocked_stale_source_evidence",
    "blocked",
    "blocked_setup_required",
    "active_with_blockers",
    "command_backed_no_published_receipt",
    "missing_receipt",
    "waiting",
    "waiting_for_live_epub",
    "fail",
    "failed",
}
EXPECTED_COMPONENTS = {
    "deliver": {"promo_media", "manfred_speech", "telegram_audiobook", "whatsapp_audiobook"},
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
}
KNOWN_PROOF_STATUSES = {"pending_real_world_evidence", "satisfied"}
DELIVER_BLOCKER_PROOF_KEYS = {
    "deliver:manfred_speech": "manfred_stt_tts_realtime_conversation",
    "deliver:telegram_audiobook": "telegram_audiobook_live_delivery",
    "deliver:whatsapp_audiobook": "whatsapp_audiobook_live_delivery",
}
EXPECTED_PROOF_ACTION_SURFACES = {
    "morning_brief_operator_acceptance": ("/admin/actions/acceptance-evidence", "post"),
    "weekly_signal_to_decision_review_acceptance": ("/admin/actions/signal-to-decision-evidence", "post"),
    "proactive_ooda_packet_acceptance": ("/admin/proactive-ooda/approval", "get"),
    "fresh_host_teable_recovery_drill": ("/admin/goals", "get"),
    "telegram_business_signal_setup": ("/integrations/telegram", "get"),
    "manfred_stt_tts_realtime_conversation": ("/memorials/manfred/voice-config", "get"),
    "telegram_audiobook_live_delivery": ("/integrations/telegram", "get"),
    "whatsapp_audiobook_live_delivery": ("/integrations/whatsapp", "get"),
}
PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS = {
    "ea_proactive_ooda_gold_acceptance.generated.json",
    "ea_proactive_ooda_operator_status.generated.json",
}
TEABLE_RECOVERY_PROOF_RECEIPT_NAME = "teable_env_recovery_proof.generated.json"


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

    lenses = receipt.get("lenses")
    if not isinstance(lenses, list):
        return issues + ["lenses must be a list"]
    by_key = {str(lens.get("key") or ""): lens for lens in lenses if isinstance(lens, dict)}
    if sorted(by_key) != sorted(REQUIRED_LENSES):
        issues.append("receipt must contain exactly the required lenses")

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
            expected_source_count = 3 if key == "detect" else 1
            if len(sources) != expected_source_count:
                issues.append(f"{key} lens must have exactly {expected_source_count} source receipt(s)")
            for source in sources:
                path_text = str(source.get("path") or "").strip()
                if not path_text:
                    issues.append(f"{key} source receipt path missing")
                    continue
                source_path = repo_root / path_text
                if bool(source.get("present")) != source_path.exists():
                    issues.append(f"{key} source receipt presence drifted for {path_text}")
                if source_path.exists():
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
        if key == "deliver":
            components = list(lens.get("components") or [])
            component_keys = {str(component.get("key") or "") for component in components if isinstance(component, dict)}
            if component_keys != EXPECTED_COMPONENTS["deliver"]:
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
    if "Teable may mirror important proactive OODA facts and blockers, but it remains an admin projection rather than canonical truth." not in "\n".join(
        str(item) for item in list(receipt.get("rules") or [])
    ):
        issues.append("missing Teable projection rule for proactive OODA")
    required_next_receipts = set(str(item) for item in list(receipt.get("required_next_receipts") or []) if str(item).strip())
    operator_action_queue = list(receipt.get("operator_action_queue") or [])
    if required_next_receipts and not operator_action_queue:
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
            if not action_key:
                issues.append("operator_action_queue entries must include key")
            if action_key in queue_keys:
                issues.append(f"operator_action_queue duplicate key: {action_key}")
            queue_keys.add(action_key)
            if not str(row.get("next_action") or "").strip():
                issues.append(f"operator_action_queue entry missing next_action: {action_key}")
            if not str(row.get("next_action_href") or "").strip():
                issues.append(f"operator_action_queue entry missing next_action_href: {action_key}")
            if row.get("raw_private_context_exposed") is not False:
                issues.append(f"operator_action_queue must not expose raw private context: {action_key}")
            for private_key in ("raw_chat_ids_exposed", "raw_token_exposed", "raw_secret_exposed"):
                if row.get(private_key) is not False:
                    issues.append(f"operator_action_queue must not expose {private_key}: {action_key}")
            if row.get("raw_voice_ids_exposed") is not False:
                issues.append(f"operator_action_queue must not expose raw voice IDs: {action_key}")
            if row.get("callback_tokens_exposed") is not False:
                issues.append(f"operator_action_queue must not expose callback tokens: {action_key}")
            user_action_required = row.get("user_action_required") is True
            expected_delivery_policy = "action_required_only" if user_action_required else "queue_only"
            if row.get("delivery_policy") != expected_delivery_policy:
                issues.append(f"operator_action_queue delivery_policy mismatch: {action_key}")
            if row.get("telegram_push_allowed") is not user_action_required:
                issues.append(f"operator_action_queue telegram_push_allowed mismatch: {action_key}")
            if row.get("interruption_budget") != ("action_required" if user_action_required else "none"):
                issues.append(f"operator_action_queue interruption_budget mismatch: {action_key}")
            if row.get("quiet_hours_respected") is not True:
                issues.append(f"operator_action_queue quiet_hours_respected must be true: {action_key}")
            if row.get("non_action_progress_push_allowed") is not False:
                issues.append(f"operator_action_queue non-action progress push must be false: {action_key}")
            if row.get("irreversible_actions_consent_gated") is not True:
                issues.append(f"operator_action_queue irreversible actions must be consent-gated: {action_key}")
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
            if operator_delivery_policy.get("telegram_push_allowed_for_next_action") is not bool(
                first_action.get("telegram_push_allowed")
            ):
                issues.append("operator_delivery_policy.telegram_push_allowed_for_next_action must match first queue item")
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
        next_action_href = str(requirement.get("next_action_href") or "").strip()
        next_action_label = str(requirement.get("next_action_label") or "").strip()
        next_action_method = str(requirement.get("next_action_method") or "").strip().lower()
        if not next_action_href:
            issues.append(f"acceptance proof requirement {key or index} missing next_action_href")
        if not next_action_label:
            issues.append(f"acceptance proof requirement {key or index} missing next_action_label")
        if next_action_method not in {"get", "post"}:
            issues.append(f"acceptance proof requirement {key or index} has invalid next_action_method")
        expected_surface = EXPECTED_PROOF_ACTION_SURFACES.get(key)
        if key == "proactive_ooda_packet_acceptance" and status == "satisfied":
            expected_surface = ("/app/today", "get")
        if expected_surface:
            expected_href, expected_method = expected_surface
            if expected_href not in next_action_href:
                issues.append(f"acceptance proof requirement {key} next_action_href must target {expected_href}")
            if next_action_method != expected_method:
                issues.append(f"acceptance proof requirement {key} next_action_method must be {expected_method}")
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
            source_name = source_path.name
            if key == "proactive_ooda_packet_acceptance" and source_name in PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS:
                proactive_source_receipt_names.add(source_name)
            if bool(source.get("present")) != source_path.exists():
                issues.append(f"acceptance proof requirement {key or index} source receipt presence drifted for {path_text}")
            if key == "proactive_ooda_packet_acceptance" and source_name in PROACTIVE_OODA_FRESH_SOURCE_RECEIPTS:
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
    pending_proof_keys = {
        str(requirement.get("key") or "").strip()
        for requirement in acceptance_proof_requirements
        if isinstance(requirement, dict) and str(requirement.get("status") or "").strip() != "satisfied"
    }
    if queue_keys and queue_keys != pending_proof_keys:
        issues.append("operator_action_queue keys must match pending acceptance proof requirement keys")
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
        if proactive_status != "satisfied" and REQUIRED_PROACTIVE_OODA_RECEIPT not in required_next_receipts:
            issues.append("required_next_receipts must include proactive OODA Teable proof until proactive acceptance is satisfied")
        next_action = str(proactive_requirement.get("next_action") or "")
        if proactive_status == "satisfied":
            if next_action != "maintain_proactive_ooda_gold_acceptance_evidence":
                issues.append("satisfied proactive_ooda_packet_acceptance must maintain gold acceptance evidence")
        elif "record_proactive_ooda_approval_outcome" not in next_action and "tap_proactive_telegram_approval_button" not in next_action:
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
    if whatsapp_requirement and (whatsapp_blocked_stale or whatsapp_failed_playback):
        action_context = whatsapp_requirement.get("action_context")
        if not isinstance(action_context, dict):
            issues.append("blocked WhatsApp audiobook proof must include action_context")
        else:
            expected_kind = "stale_source_evidence_refresh" if whatsapp_blocked_stale else "public_share_playback_failure"
            if action_context.get("kind") != expected_kind:
                issues.append("blocked WhatsApp audiobook action_context kind mismatch")
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
            if whatsapp_failed_playback:
                if not str(action_context.get("instruction") or "").strip():
                    issues.append("failed WhatsApp audiobook playback must include repair instruction")
                if int(action_context.get("track_response_status") or 0) <= 0:
                    issues.append("failed WhatsApp audiobook playback must include track_response_status")
                if action_context.get("raw_public_share_url_exposed") is not False:
                    issues.append("failed WhatsApp audiobook playback must not expose raw public share URL")
                if action_context.get("raw_track_url_exposed") is not False:
                    issues.append("failed WhatsApp audiobook playback must not expose raw track URL")
            for private_key in ("raw_private_context_exposed", "raw_chat_ids_exposed", "raw_token_exposed", "raw_secret_exposed"):
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
