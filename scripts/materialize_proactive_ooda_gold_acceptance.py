#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

try:
    import scripts.ea_live_ops as ea_live_ops
except ModuleNotFoundError:  # pragma: no cover - script execution path
    import ea_live_ops
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface
from app.services.proactive_ooda_runtime_artifacts import display_path, load_runtime_artifact_bundle
from app.services.proactive_signal_discovery import (
    _ascii_fold_text as _signal_ascii_fold_text,
    _clean_text as _signal_clean_text,
    _transcript_has_action_intent,
)

DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json"
DEFAULT_OPERATOR_STATUS = ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
DEFAULT_STAGE_PACKET_DIR = ROOT / "state" / "proactive_ooda_stage_packets"
DEFAULT_SAFE_WORK_RESULT_DIR = ROOT / "state" / "proactive_ooda_safe_work_results"
DEFAULT_RUN_RECEIPT = ROOT / "state" / "proactive_ooda_latest_run.generated.json"
CONTRACT_NAME = "ea.proactive_ooda_gold_acceptance.v1"
RULES = [
    "This receipt proves proactive OODA gold only when routed delivery, assistant-grade source intent, live browse evidence, a chosen candidate, a staged reversible artifact, mirrored Teable projection, and a redacted approval outcome are all present.",
    "Irreversible purchases, bookings, cancellations, sent messages, posts, and commitments remain consent-gated even when proactive staging is automated.",
    "Website browser work must produce a redacted browser-action receipt; CAPTCHA, Cloudflare, MFA, passkey, or credential blockers require a human handoff and must not be counted as completed work.",
    "Raw packet text, private links, actor identity, packet refs, and staged artifact refs must stay out of this published receipt; only hashes and coarse status may appear.",
    "Teable remains an admin projection and audit mirror rather than canonical queue or product truth.",
]
_TRANSCRIPT_NOISE_MARKERS = (
    "background noise",
    "background talk",
    "hintergrund",
    "hintergrundgeraeusch",
    "hintergrundgerausch",
    "mikrofongeraeusch",
    "mikrofongerausche",
    "microphone noise",
    "mic noise",
)
_LANGUAGE_REFERENCE_MARKERS = (
    "deepl",
    "dictionary",
    "difference between",
    "german language",
    "google translate",
    "grammar",
    "how to say",
    "language lesson",
    "translate.",
    "translate/",
    "translation",
    "translator",
    "uebersetzer",
    "ubersetzer",
    "vocabulary",
)
_LANGUAGE_REQUEST_MARKERS = (
    "dictionary",
    "grammar",
    "language",
    "translate",
    "translation",
    "translator",
    "uebersetz",
    "ubersetz",
    "uebersetzer",
    "ubersetzer",
    "vocabulary",
    "woerterbuch",
    "worterbuch",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if value else ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _path_from_text(root: Path, value: str, *, default: Path | None = None) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return default
    path = Path(normalized)
    return path if path.is_absolute() else root / path


def _existing_approval_outcome(path: Path) -> dict[str, Any]:
    existing = _load_json(path)
    payload = existing.get("proofs") if isinstance(existing.get("proofs"), Mapping) else {}
    row = payload.get("approval_outcome") if isinstance(payload, Mapping) else {}
    return dict(row) if isinstance(row, Mapping) else {}


def _approval_hash_fields_present(row: Mapping[str, Any]) -> bool:
    return all(
        bool(str(row.get(key) or "").strip())
        for key in ("evidence_sha256", "actor_sha256", "packet_ref_sha256", "staged_artifact_sha256")
    )


def _sanitize_existing_approval_outcome(row: Mapping[str, Any]) -> dict[str, Any]:
    outcome = str(row.get("outcome") or "missing").strip().lower() or "missing"
    hashes_present = _approval_hash_fields_present(row)
    explicit_outcome = outcome not in {"", "missing"}
    recorded = hashes_present and (
        bool(row.get("approval_outcome_recorded")) or bool(row.get("accepted")) or explicit_outcome
    )
    accepted = recorded and bool(row.get("accepted")) and outcome in {"approved", "accepted"}
    status = "accepted_redacted" if accepted else "recorded_not_accepted" if recorded else "missing_or_invalid"
    return {
        "present": recorded,
        "accepted": accepted,
        "approval_outcome_recorded": recorded,
        "status": status,
        "outcome": outcome,
        "source_kind": str(row.get("source_kind") or "unknown").strip() or "unknown",
        "recorded_at": str(row.get("recorded_at") or "").strip(),
        "evidence_sha256": str(row.get("evidence_sha256") or "").strip(),
        "actor_sha256": str(row.get("actor_sha256") or "").strip(),
        "packet_ref_sha256": str(row.get("packet_ref_sha256") or "").strip(),
        "staged_artifact_sha256": str(row.get("staged_artifact_sha256") or "").strip(),
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
        "raw_staged_artifact_exposed": False,
    }


def _approval_outcome_row(
    *,
    output_path: Path,
    approval_outcome_input: Mapping[str, Any] | None,
    runtime_approval_outcome: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if approval_outcome_input:
        outcome = str(approval_outcome_input.get("outcome") or "").strip().lower()
        evidence = str(approval_outcome_input.get("evidence") or "").strip()
        actor = str(approval_outcome_input.get("actor") or "").strip()
        packet_ref = str(approval_outcome_input.get("packet_ref") or "").strip()
        staged_artifact_ref = str(approval_outcome_input.get("staged_artifact_ref") or "").strip()
        recorded = bool(outcome and evidence and actor and packet_ref and staged_artifact_ref)
        accepted = recorded and outcome in {"approved", "accepted"}
        status = "accepted_redacted" if accepted else "recorded_not_accepted" if recorded else "missing_or_invalid"
        return {
            "present": recorded,
            "accepted": accepted,
            "approval_outcome_recorded": recorded,
            "status": status,
            "outcome": outcome or "missing",
            "source_kind": str(approval_outcome_input.get("source_kind") or "unknown").strip() or "unknown",
            "recorded_at": str(approval_outcome_input.get("recorded_at") or _utc_now()).strip(),
            "evidence_sha256": _hash_value(evidence),
            "actor_sha256": _hash_value(actor),
            "packet_ref_sha256": _hash_value(packet_ref),
            "staged_artifact_sha256": _hash_value(staged_artifact_ref),
            "raw_evidence_exposed": False,
            "raw_actor_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_exposed": False,
        }
    if isinstance(runtime_approval_outcome, Mapping) and runtime_approval_outcome:
        return _sanitize_existing_approval_outcome(runtime_approval_outcome)
    return _sanitize_existing_approval_outcome(_existing_approval_outcome(output_path))


def _stage_packet_ref(stage_packet: Mapping[str, Any]) -> str:
    return _first_text(stage_packet.get("packet_ref"), stage_packet.get("packet_id"))


def _safe_work_result_ref(safe_work_result: Mapping[str, Any]) -> str:
    result_ref = _first_text(safe_work_result.get("result_ref"))
    if result_ref:
        return result_ref
    result_id = _first_text(safe_work_result.get("result_id"))
    return f"safe_work_result:{result_id}" if result_id else ""


def _run_receipt_matches_packet_artifacts(
    *,
    run_receipt: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> bool:
    if not run_receipt or not stage_packet or not safe_work_result:
        return False
    run_stage_hashes = {str(item or "").strip() for item in list(run_receipt.get("stage_packet_ref_hashes") or []) if str(item or "").strip()}
    run_safe_hashes = {
        str(item or "").strip()
        for item in list(run_receipt.get("safe_work_result_ref_hashes") or [])
        if str(item or "").strip()
    }
    stage_hash = _hash_value(_stage_packet_ref(stage_packet))
    safe_hash = _hash_value(_safe_work_result_ref(safe_work_result))
    return bool(stage_hash and safe_hash and stage_hash in run_stage_hashes and safe_hash in run_safe_hashes)


def _matching_auto_execute_results(
    *,
    run_receipt: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
    action: str = "",
    status: str = "",
) -> tuple[dict[str, Any], ...]:
    if not run_receipt or not stage_packet or not safe_work_result:
        return ()
    stage_hash = _hash_value(_stage_packet_ref(stage_packet))
    safe_hash = _hash_value(_safe_work_result_ref(safe_work_result))
    if not stage_hash or not safe_hash:
        return ()
    normalized_action = str(action or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    matched: list[dict[str, Any]] = []
    for row in list(run_receipt.get("auto_execute_results") or []):
        if not isinstance(row, Mapping):
            continue
        row_action = str(row.get("action") or "").strip().lower()
        row_status = str(row.get("status") or "").strip().lower()
        row_packet_hash = str(row.get("packet_ref_hash") or "").strip()
        row_safe_hash = str(row.get("safe_work_result_ref_hash") or "").strip()
        if row_packet_hash != stage_hash or row_safe_hash != safe_hash:
            continue
        if normalized_action and row_action != normalized_action:
            continue
        if normalized_status and row_status != normalized_status:
            continue
        matched.append(dict(row))
    return tuple(matched)


def _approval_outcome_matches_packet_artifacts(
    *,
    approval_row: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> bool:
    if not bool(approval_row.get("approval_outcome_recorded")):
        return False
    stage_hash = _hash_value(_stage_packet_ref(stage_packet))
    safe_hash = _hash_value(_safe_work_result_ref(safe_work_result))
    return bool(
        stage_hash
        and safe_hash
        and str(approval_row.get("packet_ref_sha256") or "").strip() == stage_hash
        and str(approval_row.get("staged_artifact_sha256") or "").strip() == safe_hash
    )


def _coherent_approval_outcome_row(
    *,
    approval_row: Mapping[str, Any],
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(approval_row or {})
    if not row:
        return {}
    if _approval_outcome_matches_packet_artifacts(
        approval_row=row,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    ):
        return row
    return {
        **row,
        "present": False,
        "accepted": False,
        "approval_outcome_recorded": False,
        "status": "missing_or_invalid",
    }


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _proof_row(*, present: bool, detail: dict[str, Any]) -> dict[str, Any]:
    payload = dict(detail)
    payload["present"] = bool(present)
    payload["status"] = "pass" if present else "blocked"
    return payload


def _folded_text(value: object) -> str:
    return _signal_ascii_fold_text(_signal_clean_text(str(value or ""))).strip().lower()


def _as_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _stage_payload_and_input(stage_packet: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    stage = _as_mapping(stage_packet.get("stage"))
    payload = _as_mapping(stage.get("payload"))
    safe_work_order = _as_mapping(stage_packet.get("safe_work_order"))
    input_contract = _as_mapping(safe_work_order.get("input_contract"))
    tool_hints = _as_mapping(safe_work_order.get("tool_hints"))
    return payload, input_contract, tool_hints


def _request_texts_for_quality(stage_packet: Mapping[str, Any]) -> list[str]:
    payload, input_contract, _tool_hints = _stage_payload_and_input(stage_packet)
    values: list[str] = []
    for source in (payload, input_contract):
        for key in ("draft_request_text", "research_query", "requested_outcome", "subject_hint"):
            values.extend(_string_list(source.get(key)))
        for key in ("search_queries", "notes"):
            values.extend(_string_list(source.get(key)))
    # Preserve order while removing exact duplicates. These strings are never published raw.
    return list(dict.fromkeys(value for value in values if value))


def _transcript_signal_adapter_hint(stage_packet: Mapping[str, Any]) -> str:
    payload, _input_contract, tool_hints = _stage_payload_and_input(stage_packet)
    return _first_text(payload.get("adapter_hint"), tool_hints.get("adapter_hint"))


def _text_is_noise_like(value: object) -> bool:
    folded = _folded_text(value)
    if not folded:
        return False
    if re.search(r"\[[^\]]*(?:geraeusch|gerausch|noise|hintergrund|background)[^\]]*\]", folded):
        return True
    return any(marker in folded for marker in _TRANSCRIPT_NOISE_MARKERS)


def _request_allows_language_reference(request_texts: list[str]) -> bool:
    folded = " ".join(_folded_text(value) for value in request_texts)
    return any(marker in folded for marker in _LANGUAGE_REQUEST_MARKERS)


def _candidate_text_for_quality(recommended: Mapping[str, Any]) -> str:
    value = recommended.get("value")
    if isinstance(value, Mapping):
        parts = [
            value.get("label"),
            value.get("title"),
            value.get("page_title"),
            value.get("snippet"),
            value.get("url"),
            value.get("final_url"),
            value.get("source_query"),
        ]
        return " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
    return str(value or "").strip()


def _candidate_is_language_reference(candidate_text: str) -> bool:
    folded = _folded_text(candidate_text)
    return any(marker in folded for marker in _LANGUAGE_REFERENCE_MARKERS)


def _safe_work_audit_issue_codes(audit: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for issue in list(audit.get("issues") or []):
        if isinstance(issue, Mapping):
            code = str(issue.get("code") or "").strip()
            if code:
                codes.append(code)
    return codes


def _assistant_grade_packet_quality_proof(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
    packet_artifacts_match_run_receipt: bool,
) -> tuple[dict[str, Any], bool]:
    issues: list[str] = []
    payload, input_contract, tool_hints = _stage_payload_and_input(stage_packet)
    request_texts = _request_texts_for_quality(stage_packet)
    adapter_hint = _transcript_signal_adapter_hint(stage_packet)
    transcript_signal = adapter_hint == "transcript_signal"
    if not packet_artifacts_match_run_receipt:
        issues.append("packet_artifacts_do_not_match_run_receipt")
    if transcript_signal:
        has_action_intent = any(_transcript_has_action_intent(_folded_text(text)) for text in request_texts)
        noise_like = any(_text_is_noise_like(text) for text in request_texts)
        if not has_action_intent:
            issues.append("transcript_signal_lacks_action_intent")
        if noise_like:
            issues.append("transcript_signal_noise_like_query")
    audit = _as_mapping(safe_work_result.get("audit"))
    audit_status = str(audit.get("status") or "").strip().lower()
    audit_issue_codes = _safe_work_audit_issue_codes(audit)
    if audit_status in {"blocked", "fail", "failed", "error"}:
        issues.append("safe_work_audit_not_pass")
    recommended = _as_mapping(safe_work_result.get("recommended_option_or_draft"))
    candidate_text = _candidate_text_for_quality(recommended)
    if candidate_text and _candidate_is_language_reference(candidate_text) and not _request_allows_language_reference(request_texts):
        issues.append("candidate_reference_page_not_aligned_with_request")
    quality_present = bool(stage_packet and safe_work_result and packet_artifacts_match_run_receipt and not issues)
    proof = _proof_row(
        present=quality_present,
        detail={
            "adapter_hint": adapter_hint,
            "stage_kind": str(_as_mapping(stage_packet.get("stage")).get("kind") or "").strip(),
            "work_type": _first_text(
                payload.get("work_type"),
                _as_mapping(stage_packet.get("safe_work_order")).get("work_type"),
                safe_work_result.get("work_type"),
            ),
            "transcript_signal": transcript_signal,
            "request_text_count": len(request_texts),
            "safe_work_audit_status": audit_status,
            "safe_work_audit_issue_codes": audit_issue_codes[:8],
            "recommended_kind": str(recommended.get("kind") or "").strip(),
            "recommended_candidate_hash": _hash_value(candidate_text),
            "request_allows_language_reference": _request_allows_language_reference(request_texts),
            "issues": list(dict.fromkeys(issues)),
            "raw_request_exposed": False,
            "raw_candidate_exposed": False,
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
        },
    )
    return proof, quality_present


def _browser_action_contract_proof(
    *,
    safe_work_result: Mapping[str, Any],
    packet_artifacts_match_run_receipt: bool,
) -> tuple[dict[str, Any], bool]:
    receipt = _as_mapping(safe_work_result.get("browser_action_receipt"))
    if not receipt:
        present = bool(safe_work_result) and packet_artifacts_match_run_receipt
        return (
            _proof_row(
                present=present,
                detail={
                    "required_for_selected_packet": False,
                    "browser_action_receipt_present": False,
                    "status": "not_required",
                    "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
                },
            ),
            present,
        )
    issues: list[str] = []
    handoff = _as_mapping(receipt.get("handoff"))
    security = _as_mapping(receipt.get("security"))
    policy = _as_mapping(receipt.get("policy"))
    privacy = _as_mapping(receipt.get("privacy"))
    blocker_code = _first_text(handoff.get("blocker_code"))
    status = _first_text(receipt.get("status"))
    irreversible_attempts = [str(item or "").strip() for item in list(policy.get("irreversible_actions_attempted") or []) if str(item or "").strip()]
    if str(receipt.get("schema") or "").strip() != "proactive_ooda.browser_action_receipt.v1":
        issues.append("browser_action_schema_invalid")
    if not packet_artifacts_match_run_receipt:
        issues.append("packet_artifacts_do_not_match_run_receipt")
    if privacy.get("raw_credentials_stored") is not False:
        issues.append("raw_credentials_storage_not_false")
    if privacy.get("raw_cookie_or_session_stored") is not False:
        issues.append("raw_browser_session_storage_not_false")
    if security.get("secret_values_stored") is not False:
        issues.append("secret_values_storage_not_false")
    if irreversible_attempts:
        issues.append("irreversible_browser_action_attempted")
    if status in {"blocked_human_handoff_required", "blocked_credentials_required"}:
        if receipt.get("user_action_required") is not True:
            issues.append("browser_handoff_missing_user_action_flag")
        if status == "blocked_human_handoff_required" and not blocker_code:
            issues.append("browser_handoff_missing_blocker_code")
    if status == "staged_for_user_decision" and not bool(receipt.get("staged_artifact_present")):
        issues.append("browser_staged_status_without_artifact")
    present = packet_artifacts_match_run_receipt and not issues
    return (
        _proof_row(
            present=present,
            detail={
                "required_for_selected_packet": True,
                "browser_action_receipt_present": True,
                "schema": str(receipt.get("schema") or "").strip(),
                "status": status,
                "user_action_required": bool(receipt.get("user_action_required")),
                "handoff_required": bool(handoff.get("required")),
                "blocker_code": blocker_code,
                "staged_artifact_present": bool(receipt.get("staged_artifact_present")),
                "irreversible_actions_attempted_count": len(irreversible_attempts),
                "raw_credentials_stored": bool(privacy.get("raw_credentials_stored")),
                "raw_cookie_or_session_stored": bool(privacy.get("raw_cookie_or_session_stored")),
                "secret_values_stored": bool(security.get("secret_values_stored")),
                "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
                "issues": list(dict.fromkeys(issues)),
            },
        ),
        present,
    )


def _summary_for_status(status: str, *, approval_capture_surface_ready: bool = False) -> str:
    if status == "pass":
        return "A proactive OODA packet has routed delivery, live browse evidence, a chosen candidate, a staged reversible artifact, mirrored Teable facts, and a redacted approved outcome."
    if status == "blocked_operator_runtime_posture":
        return "The proactive OODA packet proofs exist, but operator runtime posture is blocked and gold cannot be claimed until approved source health is restored."
    if status == "blocked_low_quality_packet_evidence":
        return "The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough to prove production readiness."
    if status == "blocked_not_accepted_under_ordinary_use":
        return "A proactive OODA packet was routed and staged, but the recorded outcome was not accepted under ordinary use."
    if status == "ready_for_approval_outcome_capture":
        if approval_capture_surface_ready:
            return "A proactive OODA packet has local gold-proof runtime evidence and a live Telegram approval capture surface; capture the redacted approval outcome next."
        return "A proactive OODA packet has local gold-proof runtime evidence; capture the redacted approval outcome next."
    return "Proactive OODA gold proof is still blocked because one or more packet-evidence links are missing."


def _operator_runtime_next_action(operator_status: Mapping[str, Any]) -> str:
    reason = str(operator_status.get("reason") or "").strip()
    if reason.startswith("google_workspace_signal_source_unhealthy:"):
        return "reauthorize_google_workspace_binding"
    return str(operator_status.get("next_action") or "repair_proactive_operator_runtime_posture").strip() or "repair_proactive_operator_runtime_posture"


def _next_action_surface_fields(action: str) -> dict[str, str]:
    surface = proactive_next_action_surface(action)
    return {
        "next_action_href": str(surface.get("href") or "").strip(),
        "next_action_label": str(surface.get("label") or "").strip(),
        "next_action_method": str(surface.get("method") or "").strip(),
    }


def _next_action(
    *,
    operator_runtime_ready: bool,
    operator_status: Mapping[str, Any],
    delivery_present: bool,
    action_required_delivery_present: bool,
    assistant_grade_present: bool,
    browser_action_contract_present: bool,
    browse_present: bool,
    chosen_present: bool,
    staged_present: bool,
    teable_present: bool,
    approval_row: Mapping[str, Any],
    approval_capture_surface_ready: bool,
) -> str:
    if not operator_runtime_ready:
        return _operator_runtime_next_action(operator_status)
    if not delivery_present:
        return "send_or_mirror_one_real_proactive_packet_with_routed_delivery_proof"
    if not assistant_grade_present:
        return "stage_fresh_assistant_grade_proactive_packet"
    if not browser_action_contract_present:
        return "repair_proactive_browser_action_handoff_contract"
    if not browse_present:
        return "collect_live_browse_backed_safe_work_result"
    if not chosen_present:
        return "stage_one_chosen_candidate_for_user_decision"
    if not staged_present:
        return "persist_one_reversible_staged_artifact"
    if not teable_present:
        return "mirror_the_proactive_packet_into_teable"
    if not bool(approval_row.get("approval_outcome_recorded")):
        if approval_capture_surface_ready:
            return "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
        return "record_proactive_ooda_approval_outcome"
    if not bool(approval_row.get("accepted")):
        return "improve_proactive_packet_quality_and_collect_a_new_acceptance_outcome"
    if not action_required_delivery_present:
        return "prove_proactive_delivery_only_notifies_for_user_action"
    return "maintain_proactive_ooda_gold_acceptance_evidence"


def _remaining_external_proofs(
    *,
    operator_runtime_ready: bool,
    delivery_present: bool,
    action_required_delivery_present: bool,
    assistant_grade_present: bool,
    browser_action_contract_present: bool,
    browse_present: bool,
    chosen_present: bool,
    staged_present: bool,
    teable_present: bool,
    approval_row: Mapping[str, Any],
) -> list[str]:
    remaining: list[str] = []
    if not operator_runtime_ready:
        remaining.append("healthy operator runtime posture across approved proactive sources")
    if not delivery_present:
        remaining.append("routed delivery proof for a real proactive OODA packet")
    if not action_required_delivery_present:
        remaining.append("action-required-only Telegram delivery proof for the proactive OODA packet")
    if not assistant_grade_present:
        remaining.append("assistant-grade source intent and candidate alignment for the proactive OODA packet")
    if not browser_action_contract_present:
        remaining.append("redacted browser-action handoff and consent contract for website tasks")
    if not browse_present:
        remaining.append("live browse evidence for a real proactive OODA packet")
    if not chosen_present:
        remaining.append("chosen candidate proof for a real proactive OODA packet")
    if not staged_present:
        remaining.append("staged reversible artifact proof for a real proactive OODA packet")
    if not teable_present:
        remaining.append("mirrored Teable projection for the proactive OODA packet")
    if not bool(approval_row.get("approval_outcome_recorded")):
        remaining.append("redacted explicit approval outcome for the proactive OODA packet")
    elif not bool(approval_row.get("accepted")):
        remaining.append("real proactive OODA packet accepted under ordinary use")
    return remaining


def _approval_capture_surface_receipt(
    *,
    operator_status: Mapping[str, Any],
    bundle: Mapping[str, Any],
    approval_outcome_path: Path | None,
    used_live_runtime_probe: bool,
) -> tuple[dict[str, Any], bool]:
    selected_channel = _first_text(
        dict(operator_status.get("delivery_route") or {}).get("selected_channel"),
        dict(operator_status.get("live_receipt") or {}).get("delivery_channel"),
    )
    callback_dir = bundle.get("approval_callback_dir")
    if not isinstance(callback_dir, Path) and approval_outcome_path is not None:
        callback_dir = approval_outcome_path.parent / "proactive_ooda_approval_callbacks"
    callback_dir_path = callback_dir if isinstance(callback_dir, Path) else None
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    if used_live_runtime_probe:
        callback_dir_exists = bool(bundle.get("approval_callback_dir_exists"))
        callback_dir_writable = bool(bundle.get("approval_callback_dir_writable"))
        callback_record_count = int(bundle.get("approval_callback_record_count") or 0)
        callback_pending_count = int(bundle.get("approval_callback_pending_count") or 0)
        callback_recorded_count = int(bundle.get("approval_callback_recorded_count") or 0)
        current_packet_callback_record_count = int(bundle.get("current_packet_callback_record_count") or 0)
        current_packet_callback_pending_count = int(bundle.get("current_packet_callback_pending_count") or 0)
        current_packet_callback_recorded_count = int(bundle.get("current_packet_callback_recorded_count") or 0)
        current_packet_live_callback_record_count = int(bundle.get("current_packet_live_callback_record_count") or 0)
        current_packet_live_pending_count = int(bundle.get("current_packet_live_pending_count") or 0)
        current_packet_callback_latest_status = str(bundle.get("current_packet_callback_latest_status") or "").strip()
        current_packet_callback_latest_expired = bool(bundle.get("current_packet_callback_latest_expired"))
    else:
        callback_dir_exists = bool(callback_dir_path and callback_dir_path.is_dir())
        callback_dir_writable = bool(callback_dir_path and _dir_writable(callback_dir_path))
        callback_record_count = int(bundle.get("approval_callback_record_count") or _callback_record_count(callback_dir_path))
        callback_pending_count = int(bundle.get("approval_callback_pending_count") or 0)
        callback_recorded_count = int(bundle.get("approval_callback_recorded_count") or 0)
        (
            current_packet_callback_record_count,
            current_packet_callback_pending_count,
            current_packet_callback_recorded_count,
            current_packet_live_callback_record_count,
            current_packet_live_pending_count,
            current_packet_callback_latest_status,
            current_packet_callback_latest_expired,
        ) = _matching_callback_stats(
            callback_dir_path,
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
        )
    callback_raw_pending_count = int(bundle.get("approval_callback_raw_pending_count") or callback_pending_count)
    callback_live_pending_count = int(bundle.get("approval_callback_live_pending_count") or callback_pending_count)
    callback_unexpired_pending_count = int(bundle.get("approval_callback_unexpired_pending_count") or callback_live_pending_count)
    callback_noncurrent_pending_count = int(bundle.get("approval_callback_noncurrent_pending_count") or 0)
    callback_stale_pending_count = int(bundle.get("approval_callback_stale_pending_count") or 0)
    callback_expired_pending_count = int(bundle.get("approval_callback_expired_pending_count") or callback_stale_pending_count)
    callback_expired_count = int(bundle.get("approval_callback_expired_count") or 0)
    callback_superseded_count = int(bundle.get("approval_callback_superseded_count") or 0)
    callback_terminal_count = int(
        bundle.get("approval_callback_terminal_count") or callback_recorded_count + callback_expired_count + callback_superseded_count
    )
    current_packet_callback_raw_pending_count = int(
        bundle.get("current_packet_callback_raw_pending_count") or current_packet_callback_pending_count
    )
    current_packet_callback_stale_pending_count = int(
        bundle.get("current_packet_callback_stale_pending_count")
        or max(current_packet_callback_pending_count - current_packet_live_pending_count, 0)
    )
    current_packet_callback_expired_pending_count = int(
        bundle.get("current_packet_callback_expired_pending_count") or current_packet_callback_stale_pending_count
    )
    current_packet_callback_expired_count = int(bundle.get("current_packet_callback_expired_count") or 0)
    current_packet_callback_superseded_count = int(bundle.get("current_packet_callback_superseded_count") or 0)
    ready = (
        selected_channel == "telegram"
        and approval_outcome_path is not None
        and callback_dir_path is not None
        and callback_dir_writable
        and current_packet_live_pending_count > 0
    )
    return (
        {
            "present": bool(approval_outcome_path or callback_dir_path),
            "ready": ready,
            "selected_channel": selected_channel,
            "approval_outcome_path": display_path(ROOT, approval_outcome_path),
            "callback_dir": display_path(ROOT, callback_dir_path),
            "callback_dir_exists": callback_dir_exists,
            "callback_dir_writable": callback_dir_writable,
            "callback_record_count": callback_record_count,
            "callback_pending_count": callback_pending_count,
            "callback_raw_pending_count": callback_raw_pending_count,
            "callback_live_pending_count": callback_live_pending_count,
            "callback_unexpired_pending_count": callback_unexpired_pending_count,
            "callback_noncurrent_pending_count": callback_noncurrent_pending_count,
            "callback_stale_pending_count": callback_stale_pending_count,
            "callback_expired_pending_count": callback_expired_pending_count,
            "callback_recorded_count": callback_recorded_count,
            "callback_expired_count": callback_expired_count,
            "callback_superseded_count": callback_superseded_count,
            "callback_terminal_count": callback_terminal_count,
            "current_packet_callback_record_count": current_packet_callback_record_count,
            "current_packet_callback_pending_count": current_packet_callback_pending_count,
            "current_packet_callback_raw_pending_count": current_packet_callback_raw_pending_count,
            "current_packet_callback_stale_pending_count": current_packet_callback_stale_pending_count,
            "current_packet_callback_expired_pending_count": current_packet_callback_expired_pending_count,
            "current_packet_callback_recorded_count": current_packet_callback_recorded_count,
            "current_packet_callback_expired_count": current_packet_callback_expired_count,
            "current_packet_callback_superseded_count": current_packet_callback_superseded_count,
            "current_packet_live_callback_record_count": current_packet_live_callback_record_count,
            "current_packet_live_pending_count": current_packet_live_pending_count,
            "current_packet_callback_latest_status": current_packet_callback_latest_status,
            "current_packet_callback_latest_expired": current_packet_callback_latest_expired,
            "source": "docker_compose_exec" if used_live_runtime_probe else "local_filesystem",
        },
        ready,
    )


def _callback_record_count(path: Path | None) -> int:
    if path is None or not path.is_dir():
        return 0
    try:
        return sum(1 for candidate in path.glob("*.json") if candidate.is_file())
    except Exception:
        return 0


def _dir_writable(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return probe.exists() and probe.is_dir() and os.access(probe, os.W_OK)
    except Exception:
        return False


def _matching_callback_stats(
    path: Path | None,
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> tuple[int, int, int, int, int, str, bool]:
    if path is None or not path.is_dir():
        return 0, 0, 0, 0, 0, "", False
    packet_ref = _stage_packet_ref(stage_packet)
    artifact_ref = _safe_work_result_ref(safe_work_result)
    if not packet_ref or not artifact_ref:
        return 0, 0, 0, 0, 0, "", False
    rows: list[dict[str, Any]] = []
    try:
        for candidate in path.glob("*.json"):
            if not candidate.is_file():
                continue
            payload = _load_json(candidate)
            if (
                str(payload.get("packet_ref") or "").strip() == packet_ref
                and str(payload.get("staged_artifact_ref") or "").strip() == artifact_ref
            ):
                rows.append(payload)
    except Exception:
        return 0, 0, 0, 0, 0, "", False
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    latest = rows[-1] if rows else {}
    live_rows = [row for row in rows if not _callback_expired(row)]
    live_pending_rows = [row for row in rows if str(row.get("status") or "").strip() == "pending" and not _callback_expired(row)]
    return (
        len(rows),
        sum(1 for row in rows if str(row.get("status") or "").strip() == "pending"),
        sum(1 for row in rows if str(row.get("status") or "").strip() in {"approved", "rejected", "deferred", "dismissed"}),
        len(live_rows),
        len(live_pending_rows),
        str(latest.get("status") or "").strip(),
        bool(latest) and _callback_expired(latest),
    )


def _callback_expired(row: Mapping[str, Any]) -> bool:
    text = str(row.get("expires_at") or "").strip()
    if not text:
        return False
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        expires_at = datetime.fromisoformat(normalized)
    except Exception:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _runtime_artifact_bundle(
    *,
    run_receipt_path: Path | None,
    stage_packet_dir: Path | None,
    safe_work_result_dir: Path | None,
    allow_live_runtime_probe: bool,
    allow_default_local_artifacts: bool,
) -> tuple[dict[str, Any], bool]:
    use_local_bundle = allow_default_local_artifacts or run_receipt_path is not None or stage_packet_dir is not None or safe_work_result_dir is not None
    local_bundle = (
        load_runtime_artifact_bundle(
            root=ROOT,
            state_path="state/proactive_ooda_notified.json",
            receipt_path=run_receipt_path or "",
            stage_packet_dir=stage_packet_dir or "",
            safe_work_result_dir=safe_work_result_dir or "",
        )
        if use_local_bundle
        else {}
    )
    local_complete = bool(local_bundle.get("run_receipt")) and bool(local_bundle.get("stage_packet")) and bool(local_bundle.get("safe_work_result"))
    if allow_live_runtime_probe:
        live_report = ea_live_ops.probe_proactive_artifacts(output_format="json")
        if bool(live_report.get("probe_ok")):
            live_bundle = {
        "run_receipt_path": _path_from_text(ROOT, str(live_report.get("run_receipt_path") or "")),
        "run_receipt": dict(live_report.get("run_receipt") or {}),
        "stage_packet_dir": _path_from_text(ROOT, str(live_report.get("stage_packet_dir") or "")),
        "safe_work_result_dir": _path_from_text(ROOT, str(live_report.get("safe_work_result_dir") or "")),
        "approval_outcome_path": _path_from_text(ROOT, str(live_report.get("approval_outcome_path") or "")),
        "approval_callback_dir": _path_from_text(ROOT, str(live_report.get("approval_callback_dir") or "")),
            "approval_callback_dir_exists": bool(live_report.get("approval_callback_dir_exists")),
            "approval_callback_dir_writable": bool(live_report.get("approval_callback_dir_writable")),
            "approval_callback_record_count": int(live_report.get("approval_callback_record_count") or 0),
            "approval_callback_pending_count": int(live_report.get("approval_callback_pending_count") or 0),
            "approval_callback_raw_pending_count": int(live_report.get("approval_callback_raw_pending_count") or live_report.get("approval_callback_pending_count") or 0),
            "approval_callback_live_pending_count": int(live_report.get("approval_callback_live_pending_count") or live_report.get("approval_callback_pending_count") or 0),
            "approval_callback_unexpired_pending_count": int(live_report.get("approval_callback_unexpired_pending_count") or 0),
            "approval_callback_noncurrent_pending_count": int(live_report.get("approval_callback_noncurrent_pending_count") or 0),
            "approval_callback_stale_pending_count": int(live_report.get("approval_callback_stale_pending_count") or 0),
            "approval_callback_expired_pending_count": int(live_report.get("approval_callback_expired_pending_count") or 0),
            "approval_callback_recorded_count": int(live_report.get("approval_callback_recorded_count") or 0),
            "approval_callback_expired_count": int(live_report.get("approval_callback_expired_count") or 0),
            "approval_callback_superseded_count": int(live_report.get("approval_callback_superseded_count") or 0),
            "approval_callback_terminal_count": int(live_report.get("approval_callback_terminal_count") or 0),
            "current_packet_callback_record_count": int(live_report.get("current_packet_callback_record_count") or 0),
            "current_packet_callback_pending_count": int(live_report.get("current_packet_callback_pending_count") or 0),
            "current_packet_callback_raw_pending_count": int(
                live_report.get("current_packet_callback_raw_pending_count") or live_report.get("current_packet_callback_pending_count") or 0
            ),
            "current_packet_callback_stale_pending_count": int(live_report.get("current_packet_callback_stale_pending_count") or 0),
            "current_packet_callback_expired_pending_count": int(live_report.get("current_packet_callback_expired_pending_count") or 0),
            "current_packet_callback_recorded_count": int(live_report.get("current_packet_callback_recorded_count") or 0),
            "current_packet_callback_expired_count": int(live_report.get("current_packet_callback_expired_count") or 0),
            "current_packet_callback_superseded_count": int(live_report.get("current_packet_callback_superseded_count") or 0),
            "current_packet_live_callback_record_count": int(live_report.get("current_packet_live_callback_record_count") or 0),
            "current_packet_live_pending_count": int(live_report.get("current_packet_live_pending_count") or 0),
            "current_packet_callback_latest_status": str(live_report.get("current_packet_callback_latest_status") or "").strip(),
            "current_packet_callback_latest_expired": bool(live_report.get("current_packet_callback_latest_expired")),
            "current_packet_callback_outcome": dict(live_report.get("current_packet_callback_outcome") or {}),
            "stage_packet_path": _path_from_text(ROOT, str(live_report.get("stage_packet_path") or "")),
            "stage_packet": dict(live_report.get("stage_packet") or {}),
            "safe_work_result_path": _path_from_text(ROOT, str(live_report.get("safe_work_result_path") or "")),
            "safe_work_result": dict(live_report.get("safe_work_result") or {}),
        "approval_outcome": dict(live_report.get("approval_outcome") or {}),
        "state_path": _path_from_text(ROOT, str(live_report.get("state_path") or "")),
            }
            if not live_bundle["approval_outcome"] and local_bundle.get("approval_outcome"):
                live_bundle["approval_outcome"] = dict(local_bundle.get("approval_outcome") or {})
                live_bundle["approval_outcome_path"] = local_bundle.get("approval_outcome_path")
            if bool(live_bundle["run_receipt"]) or bool(live_bundle["stage_packet"]) or bool(live_bundle["safe_work_result"]):
                return live_bundle, True
    if local_complete:
        return local_bundle, False
    return local_bundle, False


def _allow_default_local_artifacts(*paths: Path) -> bool:
    for path in paths:
        if not path.is_absolute():
            return True
        try:
            if path.is_relative_to(ROOT):
                return True
        except ValueError:
            continue
    return False


def materialize_proactive_ooda_gold_acceptance(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    operator_status_path: Path = DEFAULT_OPERATOR_STATUS,
    run_receipt_path: Path | None = None,
    stage_packet_dir: Path | None = None,
    safe_work_result_dir: Path | None = None,
    approval_outcome_path: Path | None = None,
    approval_outcome_input: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
    allow_live_runtime_probe: bool = False,
) -> dict[str, Any]:
    operator_status = _load_json(operator_status_path)
    allow_default_local_artifacts = _allow_default_local_artifacts(output_path, operator_status_path)
    bundle, used_live_runtime_probe = _runtime_artifact_bundle(
        run_receipt_path=run_receipt_path
        if run_receipt_path is not None
        else (DEFAULT_RUN_RECEIPT if allow_default_local_artifacts and DEFAULT_RUN_RECEIPT.exists() else None),
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        allow_live_runtime_probe=allow_live_runtime_probe,
        allow_default_local_artifacts=allow_default_local_artifacts,
    )
    run_path = bundle.get("run_receipt_path")
    run_receipt = dict(bundle.get("run_receipt") or {})
    resolved_stage_dir = bundle.get("stage_packet_dir")
    resolved_safe_dir = bundle.get("safe_work_result_dir")
    stage_path = bundle.get("stage_packet_path")
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_path = bundle.get("safe_work_result_path")
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    resolved_approval_outcome_path = approval_outcome_path or bundle.get("approval_outcome_path")
    runtime_approval_outcome = (
        _load_json(resolved_approval_outcome_path)
        if approval_outcome_path is not None
        else dict(bundle.get("approval_outcome") or {})
    )
    callback_approval_outcome = dict(bundle.get("current_packet_callback_outcome") or {})
    file_approval_row = _approval_outcome_row(
        output_path=output_path,
        approval_outcome_input=approval_outcome_input,
        runtime_approval_outcome=runtime_approval_outcome,
    )
    callback_approval_row = _approval_outcome_row(
        output_path=output_path,
        approval_outcome_input=None,
        runtime_approval_outcome=callback_approval_outcome,
    )
    packet_artifacts_match_run_receipt = _run_receipt_matches_packet_artifacts(
        run_receipt=run_receipt,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    file_approval_matches_current_packet = _approval_outcome_matches_packet_artifacts(
        approval_row=file_approval_row,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    callback_approval_matches_current_packet = _approval_outcome_matches_packet_artifacts(
        approval_row=callback_approval_row,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    approval_row_source = "approval_outcome_artifact"
    approval_row = file_approval_row
    if not file_approval_matches_current_packet and callback_approval_matches_current_packet:
        approval_row_source = "current_packet_callback"
        approval_row = callback_approval_row
    approval_row = _coherent_approval_outcome_row(
        approval_row=approval_row,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    approval_artifact_matches_current_packet = file_approval_matches_current_packet or callback_approval_matches_current_packet
    approval_capture_surface, approval_capture_surface_ready = _approval_capture_surface_receipt(
        operator_status=operator_status,
        bundle=bundle,
        approval_outcome_path=resolved_approval_outcome_path,
        used_live_runtime_probe=used_live_runtime_probe,
    )

    delivery_route = dict(operator_status.get("delivery_route") or {})
    live_receipt = dict(operator_status.get("live_receipt") or {})
    operator_status_state = str(operator_status.get("status") or "").strip()
    operator_runtime_ready = operator_status_state.startswith("ready")
    operator_runtime_next_action = str(operator_status.get("next_action") or "").strip()
    operator_runtime_proof = _proof_row(
        present=operator_runtime_ready,
        detail={
            "status": operator_status_state,
            "reason": str(operator_status.get("reason") or "").strip(),
            "next_action": operator_runtime_next_action,
            **_next_action_surface_fields(operator_runtime_next_action),
            "path": display_path(ROOT, operator_status_path),
        },
    )
    packet_run_sent = str(run_receipt.get("notification_status") or "").strip() == "sent" and int(run_receipt.get("item_count") or 0) > 0
    delivery_present = (
        bool(operator_status.get("delivery_route_ready"))
        and bool(operator_status.get("live_receipt_checked"))
        and bool(live_receipt.get("ok"))
        and packet_run_sent
        and packet_artifacts_match_run_receipt
    )
    delivery_proof = _proof_row(
        present=delivery_present,
        detail={
            "route_probe_source": str(operator_status.get("route_probe_source") or "").strip(),
            "route_probe_runtime_service": str(operator_status.get("route_probe_runtime_service") or "").strip(),
            "selected_channel": _first_text(delivery_route.get("selected_channel"), live_receipt.get("delivery_channel")),
            "route_ready": bool(operator_status.get("delivery_route_ready")),
            "live_receipt_checked": bool(operator_status.get("live_receipt_checked")),
            "live_receipt_ok": bool(live_receipt.get("ok")),
            "live_receipt_path": str(live_receipt.get("receipt_path") or "").strip(),
            "run_notification_status": str(run_receipt.get("notification_status") or "").strip(),
            "run_item_count": int(run_receipt.get("item_count") or 0),
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
            "delivery_route_error": str(operator_status.get("delivery_route_error") or "").strip(),
            "delivery_next_action": str(operator_status.get("delivery_next_action") or "").strip(),
        },
    )

    execution_receipt = dict(safe_work_result.get("execution_receipt") or {})
    page_checks = [dict(row) for row in list(execution_receipt.get("page_checks") or []) if isinstance(row, Mapping)]
    reachable_page_count = sum(1 for row in page_checks if row.get("reachable") is True)
    network_fetch_count = int(execution_receipt.get("network_fetch_count") or 0)
    network_fetch_success_count = int(execution_receipt.get("network_fetch_success_count") or 0)
    browse_present = network_fetch_count > 0 and network_fetch_success_count > 0 and reachable_page_count > 0
    browse_present = browse_present and packet_artifacts_match_run_receipt
    browse_proof = _proof_row(
        present=browse_present,
        detail={
            "network_fetch_count": network_fetch_count,
            "network_fetch_success_count": network_fetch_success_count,
            "reachable_page_check_count": reachable_page_count,
            "safe_work_result_path": display_path(ROOT, safe_path),
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
        },
    )

    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    recommended_value = dict(recommended.get("value") or {}) if isinstance(recommended.get("value"), Mapping) else {}
    recommended_label = _first_text(recommended_value.get("label"), recommended_value.get("title"), recommended.get("value"))
    recommended_url = _first_text(recommended_value.get("url"), recommended_value.get("link"), recommended_value.get("href"))
    chosen_present = bool(str(recommended.get("kind") or "").strip()) and bool(recommended_label or recommended_url)
    chosen_present = chosen_present and packet_artifacts_match_run_receipt
    chosen_candidate_proof = _proof_row(
        present=chosen_present,
        detail={
            "recommended_kind": str(recommended.get("kind") or "").strip(),
            "recommended_label_hash": _hash_value(recommended_label),
            "recommended_url_hash": _hash_value(recommended_url),
            "shortlist_count": len(list(safe_work_result.get("shortlist") or [])),
            "safe_work_result_path": display_path(ROOT, safe_path),
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
        },
    )

    safe_work_order = dict(stage_packet.get("safe_work_order") or {})
    handoff_policy = dict(safe_work_order.get("handoff_policy") or {})
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_work_approval = dict(safe_work_result.get("approval") or {})
    irreversible_attempts = list(execution_receipt.get("irreversible_actions_attempted") or [])
    approval_required = bool(stage_approval.get("required")) or bool(safe_work_approval.get("required"))
    safe_work_status = str(safe_work_result.get("status") or "").strip()
    staged_for_user_decision = safe_work_status == "staged_for_user_decision"
    browser_action_proof, browser_action_contract_present = _browser_action_contract_proof(
        safe_work_result=safe_work_result,
        packet_artifacts_match_run_receipt=packet_artifacts_match_run_receipt,
    )
    browser_handoff_requires_user_action = bool(
        safe_work_status == "blocked_human_handoff_required"
        and dict(safe_work_result.get("browser_action_receipt") or {}).get("user_action_required")
    )
    matching_auto_execute_results = _matching_auto_execute_results(
        run_receipt=run_receipt,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
        action="save_gmail_draft",
        status="executed",
    )
    matched_auto_execute_result = dict(matching_auto_execute_results[0]) if matching_auto_execute_results else {}
    staged_base_conditions = (
        bool(stage_packet)
        and bool(safe_work_result)
        and staged_for_user_decision
        and bool(handoff_policy.get("safe_to_execute_before_approval"))
        and bool(handoff_policy.get("external_actions_remain_staged_only"))
        and len(irreversible_attempts) == 0
        and packet_artifacts_match_run_receipt
    )
    staged_present = staged_base_conditions
    staged_proof = _proof_row(
        present=staged_present,
        detail={
            "stage_kind": str(dict(stage_packet.get("stage") or {}).get("kind") or "").strip(),
            "safe_work_status": str(safe_work_result.get("status") or "").strip(),
            "approval_required": approval_required,
            "staged_for_user_decision": staged_for_user_decision,
            "safe_to_execute_before_approval": bool(handoff_policy.get("safe_to_execute_before_approval")),
            "external_actions_remain_staged_only": bool(handoff_policy.get("external_actions_remain_staged_only")),
            "irreversible_actions_attempted_count": len(irreversible_attempts),
            "auto_execute_action": str(matched_auto_execute_result.get("action") or "").strip(),
            "auto_execute_status": str(matched_auto_execute_result.get("status") or "").strip(),
            "auto_execute_match_count": len(matching_auto_execute_results),
            "stage_packet_path": display_path(ROOT, stage_path),
            "safe_work_result_path": display_path(ROOT, safe_path),
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
        },
    )

    delivery_guard = dict(operator_status.get("delivery_guard") or {})
    delivery_state = str(delivery_guard.get("delivery_state") or "").strip()
    runtime_actionable_count = int(operator_status.get("runtime_actionable_count") or 0)
    sent_packet_had_user_action_surface = (
        (staged_for_user_decision or browser_handoff_requires_user_action)
        and bool(
            approval_required
            or str(matched_auto_execute_result.get("action") or "").strip()
            or str(safe_work_result.get("approval_prompt") or "").strip()
            or str(safe_work_result.get("staged_action_url") or "").strip()
        )
        and packet_artifacts_match_run_receipt
    )
    current_guard_is_quiet_without_action = (
        delivery_state == "no_actionable_items"
        and runtime_actionable_count == 0
        and not bool(delivery_guard.get("has_high_priority"))
    )
    action_required_delivery_present = bool(
        delivery_present
        and sent_packet_had_user_action_surface
        and current_guard_is_quiet_without_action
    )
    action_required_delivery_proof = _proof_row(
        present=action_required_delivery_present,
        detail={
            "selected_channel": _first_text(delivery_route.get("selected_channel"), live_receipt.get("delivery_channel")),
            "run_notification_status": str(run_receipt.get("notification_status") or "").strip(),
            "sent_packet_had_user_action_surface": sent_packet_had_user_action_surface,
            "staged_for_user_decision": staged_for_user_decision,
            "browser_handoff_requires_user_action": browser_handoff_requires_user_action,
            "approval_required": approval_required,
            "auto_execute_action": str(matched_auto_execute_result.get("action") or "").strip(),
            "current_delivery_state": delivery_state,
            "runtime_actionable_count": runtime_actionable_count,
            "current_guard_is_quiet_without_action": current_guard_is_quiet_without_action,
            "interruption_budget_exhausted": bool(delivery_guard.get("interruption_budget_exhausted")),
            "quiet_hours_active": bool(delivery_guard.get("quiet_hours_active")),
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
        },
    )
    assistant_grade_proof, assistant_grade_present = _assistant_grade_packet_quality_proof(
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
        packet_artifacts_match_run_receipt=packet_artifacts_match_run_receipt,
    )

    teable_sync = dict(run_receipt.get("teable_sync") or {})
    projection_summary = dict(teable_sync.get("projection_summary") or {})
    projection_tables = dict(projection_summary.get("tables") or {})
    packet_projection_present = any(
        int(dict(projection_tables.get(table_name) or {}).get("record_count") or 0) > 0
        for table_name in ("proactive_ooda_items", "proactive_ooda_safe_work")
    )
    approval_surface_projection_present = (
        int(dict(projection_tables.get("proactive_ooda_approval_surfaces") or {}).get("record_count") or 0) > 0
    )
    teable_present = (
        bool(teable_sync.get("sync_attempted"))
        and str(teable_sync.get("status") or "").strip() in {"synced", "partial"}
        and int(projection_summary.get("record_count") or 0) > 0
        and packet_artifacts_match_run_receipt
        and int(run_receipt.get("item_count") or 0) > 0
        and packet_projection_present
        and (not approval_capture_surface_ready or approval_surface_projection_present)
    )
    teable_proof = _proof_row(
        present=teable_present,
        detail={
            "run_receipt_present": bool(run_receipt),
            "run_receipt_path": display_path(ROOT, run_path),
            "sync_attempted": bool(teable_sync.get("sync_attempted")),
            "teable_status": str(teable_sync.get("status") or "").strip(),
            "projection_record_count": int(projection_summary.get("record_count") or 0),
            "packet_projection_present": packet_projection_present,
            "approval_capture_surface_ready": approval_capture_surface_ready,
            "approval_surface_projection_present": approval_surface_projection_present,
            "packet_artifacts_match_run_receipt": packet_artifacts_match_run_receipt,
            "missing_tables": [
                str(item or "").strip()
                for item in list(teable_sync.get("missing_tables") or [])
                if str(item or "").strip()
            ],
        },
    )

    runtime_proofs_complete = operator_runtime_ready and all(
        (
            delivery_present,
            assistant_grade_present,
            browser_action_contract_present,
            browse_present,
            chosen_present,
            staged_present,
            teable_present,
        )
    )
    if not operator_runtime_ready:
        status = "blocked_operator_runtime_posture"
    elif delivery_present and not assistant_grade_present:
        status = "blocked_low_quality_packet_evidence"
    elif runtime_proofs_complete and bool(approval_row.get("accepted")) and action_required_delivery_present:
        status = "pass"
    elif runtime_proofs_complete and bool(approval_row.get("accepted")):
        status = "blocked_missing_proactive_packet_evidence"
    elif runtime_proofs_complete and bool(approval_row.get("approval_outcome_recorded")):
        status = "blocked_not_accepted_under_ordinary_use"
    elif runtime_proofs_complete:
        status = "ready_for_approval_outcome_capture"
    else:
        status = "blocked_missing_proactive_packet_evidence"
    next_action = _next_action(
        operator_runtime_ready=operator_runtime_ready,
        operator_status=operator_status,
        delivery_present=delivery_present,
        action_required_delivery_present=action_required_delivery_present,
        assistant_grade_present=assistant_grade_present,
        browser_action_contract_present=browser_action_contract_present,
        browse_present=browse_present,
        chosen_present=chosen_present,
        staged_present=staged_present,
        teable_present=teable_present,
        approval_row=approval_row,
        approval_capture_surface_ready=approval_capture_surface_ready,
    )

    receipt = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_proactive_ooda_gold_acceptance.py",
        "source_git_head": _git_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": _source_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": display_path(ROOT, output_path),
        "status": status,
        "summary": _summary_for_status(status, approval_capture_surface_ready=approval_capture_surface_ready),
        "next_action": next_action,
        **_next_action_surface_fields(next_action),
        "goal_completion_claim_allowed": False,
        "gold_claim_allowed": status == "pass",
        "proofs": {
            "operator_runtime_posture": operator_runtime_proof,
            "routed_delivery": delivery_proof,
            "action_required_only_delivery": action_required_delivery_proof,
            "assistant_grade_packet_quality": assistant_grade_proof,
            "browser_action_contract": browser_action_proof,
            "live_browse_evidence": browse_proof,
            "chosen_candidate": chosen_candidate_proof,
            "staged_reversible_artifact": staged_proof,
            "teable_projection": teable_proof,
            "approval_outcome": approval_row,
        },
        "evidence_receipts": {
            "operator_status": {
                "present": bool(operator_status),
                "path": display_path(ROOT, operator_status_path),
                "contract_name": str(operator_status.get("contract_name") or "").strip(),
                "status": str(operator_status.get("status") or "").strip(),
                "generated_at": str(operator_status.get("generated_at") or "").strip(),
                "source_git_head": str(operator_status.get("source_git_head") or "").strip(),
                "source_state_fingerprint": str(operator_status.get("source_state_fingerprint") or "").strip(),
            },
            "run_receipt": {
                "present": bool(run_receipt),
                "path": display_path(ROOT, run_path),
                "notification_status": str(run_receipt.get("notification_status") or "").strip(),
                "source": "docker_compose_exec" if used_live_runtime_probe else "local_filesystem",
            },
            "stage_packet": {
                "present": bool(stage_packet),
                "path": display_path(ROOT, stage_path),
                "schema": str(stage_packet.get("schema") or "").strip(),
                "source": "docker_compose_exec" if used_live_runtime_probe else "local_filesystem",
            },
            "safe_work_result": {
                "present": bool(safe_work_result),
                "path": display_path(ROOT, safe_path),
                "schema": str(safe_work_result.get("schema") or "").strip(),
                "status": str(safe_work_result.get("status") or "").strip(),
                "source": "docker_compose_exec" if used_live_runtime_probe else "local_filesystem",
            },
            "approval_outcome": {
                "present": bool(approval_row.get("present")),
                "artifact_present": bool(runtime_approval_outcome or callback_approval_outcome),
                "path": display_path(ROOT, resolved_approval_outcome_path),
                "schema": str(
                    runtime_approval_outcome.get("schema")
                    or runtime_approval_outcome.get("contract_name")
                    or ("ea.proactive_ooda_telegram_approval_callback.v1" if callback_approval_outcome else "")
                ).strip(),
                "status": str(approval_row.get("status") or "").strip(),
                "artifact_status": str(runtime_approval_outcome.get("status") or "").strip(),
                "callback_outcome_present": bool(callback_approval_outcome),
                "callback_outcome_status": str(callback_approval_outcome.get("status") or "").strip(),
                "callback_outcome_used": approval_row_source == "current_packet_callback",
                "approval_outcome_source": approval_row_source,
                "approval_outcome_recorded": bool(approval_row.get("approval_outcome_recorded")),
                "accepted": bool(approval_row.get("accepted")),
                "packet_artifacts_match_current_packet": approval_artifact_matches_current_packet,
                "source": "docker_compose_exec" if used_live_runtime_probe else "local_filesystem",
            },
            "approval_capture_surface": approval_capture_surface,
        },
        "remaining_external_proofs": _remaining_external_proofs(
            operator_runtime_ready=operator_runtime_ready,
            delivery_present=delivery_present,
            action_required_delivery_present=action_required_delivery_present,
            assistant_grade_present=assistant_grade_present,
            browser_action_contract_present=browser_action_contract_present,
            browse_present=browse_present,
            chosen_present=chosen_present,
            staged_present=staged_present,
            teable_present=teable_present,
            approval_row=approval_row,
        ),
        "verifier_commands": [
            "make verify-proactive-ooda",
            "make verify-proactive-ooda-live-receipt",
            "make verify-proactive-ooda-operator-status",
            "make verify-proactive-ooda-gold-acceptance",
        ],
        "rules": RULES,
    }
    _write_json(output_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the proactive OODA gold-acceptance receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--operator-status-receipt", type=Path, default=DEFAULT_OPERATOR_STATUS)
    parser.add_argument("--run-receipt", type=Path)
    parser.add_argument("--stage-packet-dir", type=Path)
    parser.add_argument("--safe-work-result-dir", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    input_payload = _load_json(args.input) if args.input else {}
    approval_outcome_input = dict(input_payload.get("approval_outcome") or input_payload) if input_payload else None
    receipt = materialize_proactive_ooda_gold_acceptance(
        output_path=args.output,
        operator_status_path=args.operator_status_receipt,
        run_receipt_path=args.run_receipt,
        stage_packet_dir=args.stage_packet_dir,
        safe_work_result_dir=args.safe_work_result_dir,
        approval_outcome_input=approval_outcome_input,
        allow_live_runtime_probe=True,
    )
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
