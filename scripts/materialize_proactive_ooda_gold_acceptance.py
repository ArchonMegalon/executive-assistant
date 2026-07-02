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
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action

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


def _operator_status_snapshot_key(payload: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    row = dict(payload) if isinstance(payload, Mapping) else {}
    return (
        str(row.get("contract_name") or "").strip(),
        str(row.get("status") or "").strip(),
        str(row.get("generated_at") or "").strip(),
        str(row.get("source_git_head") or "").strip(),
        str(row.get("source_state_fingerprint") or "").strip(),
    )


def _refresh_operator_status_snapshot(*, path: Path, current: Mapping[str, Any]) -> dict[str, Any]:
    latest = _load_json(path)
    if not latest:
        return dict(current) if isinstance(current, Mapping) else {}
    if _operator_status_snapshot_key(latest) == _operator_status_snapshot_key(current):
        return dict(current) if isinstance(current, Mapping) else {}
    return latest


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


def _delivery_message_count(receipt: Mapping[str, Any]) -> int:
    values = receipt.get("delivery_message_ids")
    if not isinstance(values, list) or not values:
        values = receipt.get("telegram_message_ids")
    if not isinstance(values, list):
        return 0
    return len([item for item in values if str(item or "").strip()])


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


def _safe_work_texts_for_quality(safe_work_result: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    execution = _as_mapping(safe_work_result.get("execution_receipt"))
    values.extend(_string_list(execution.get("search_queries_used")))
    recommended = _as_mapping(safe_work_result.get("recommended_option_or_draft"))
    value = recommended.get("value")
    if isinstance(value, str):
        values.append(value)
    candidate = recommended.get("candidate")
    if isinstance(candidate, Mapping):
        for key in ("label", "title", "page_title", "snippet", "source_query"):
            values.extend(_string_list(candidate.get(key)))
    values.extend(_string_list(safe_work_result.get("summary")))
    return list(dict.fromkeys(value for value in values if str(value or "").strip()))


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


def _single_official_info_link_quality_issue(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
    recommended: Mapping[str, Any],
    work_type: str,
) -> str:
    if work_type not in {"compare_options", "research"}:
        return ""
    if str(recommended.get("kind") or "").strip() not in {"shortlist_candidate", "research_query"}:
        return ""
    shortlist = [dict(item) for item in list(safe_work_result.get("shortlist") or []) if isinstance(item, Mapping)]
    if len(shortlist) > 1:
        return ""
    value = recommended.get("value")
    candidate = dict(value) if isinstance(value, Mapping) else (dict(shortlist[0]) if shortlist else {})
    if not _candidate_is_generic_official_info_link(candidate):
        return ""
    if _explicit_request_asks_for_official_info(stage_packet):
        return ""
    criteria = _materiality_selection_criteria(stage_packet)
    if criteria and not _criteria_are_only_official_reversible_link(criteria):
        return ""
    if _candidate_has_decision_material(candidate):
        return ""
    return "single_official_info_link_not_decision_ready"


def _candidate_is_generic_official_info_link(candidate: Mapping[str, Any]) -> bool:
    source = _folded_text(_first_text(candidate.get("source"), candidate.get("candidate_source")))
    candidate_text = _folded_text(_candidate_text_for_quality({"value": dict(candidate)}))
    host = _host_from_url(_first_text(candidate.get("final_url"), candidate.get("url"), candidate.get("link"), candidate.get("href")))
    return bool(
        source in {"official_site", "official"}
        or "official information" in candidate_text
        or "information portal" in candidate_text
        or host.endswith(".gv.at")
        or host.endswith(".gv")
        or host.endswith(".gov")
        or host.endswith(".gov.at")
    )


def _host_from_url(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^[a-z]+://", "", text)
    return text.split("/", 1)[0].split("@")[-1].split(":", 1)[0].strip()


def _candidate_has_decision_material(candidate: Mapping[str, Any]) -> bool:
    emails = candidate.get("contact_emails")
    if str(candidate.get("contact_email") or "").strip():
        return True
    if isinstance(emails, list) and any(str(item or "").strip() for item in emails):
        return True
    for key in (
        "price",
        "price_value",
        "amount",
        "total",
        "availability",
        "in_stock",
        "delivery_days",
        "eta_days",
        "lead_time_days",
        "booking_url",
        "cart_url",
        "appointment_url",
        "contact_url",
    ):
        value = candidate.get(key)
        if isinstance(value, bool):
            if value:
                return True
            continue
        if str(value or "").strip():
            return True
    return False


def _materiality_selection_criteria(stage_packet: Mapping[str, Any]) -> tuple[str, ...]:
    payload, input_contract, _tool_hints = _stage_payload_and_input(stage_packet)
    values: list[str] = []
    for source in (payload, input_contract):
        for key in ("selection_criteria", "criteria"):
            values.extend(_string_list(source.get(key)))
    return tuple(dict.fromkeys(_folded_text(value) for value in values if str(value or "").strip()))


def _criteria_are_only_official_reversible_link(criteria: tuple[str, ...]) -> bool:
    if not criteria:
        return False
    allowed_markers = ("official", "source", "reversible", "link", "review", "public")
    material_markers = (
        "appointment",
        "availability",
        "book",
        "budget",
        "contact",
        "delivery",
        "draft",
        "email",
        "price",
        "provider",
        "quote",
        "termin",
        "vor ort",
    )
    return all(
        any(marker in criterion for marker in allowed_markers)
        and not any(marker in criterion for marker in material_markers)
        for criterion in criteria
    )


def _explicit_request_asks_for_official_info(stage_packet: Mapping[str, Any]) -> bool:
    payload, input_contract, _tool_hints = _stage_payload_and_input(stage_packet)
    values: list[str] = []
    for source in (payload, input_contract):
        for key in (
            "request",
            "request_text",
            "user_request",
            "task_request",
            "draft_request_text",
            "research_query",
            "search_queries",
            "subject_hint",
        ):
            values.extend(_string_list(source.get(key)))
    folded = " ".join(_folded_text(value) for value in values)
    return any(
        marker in folded
        for marker in (
            "official information",
            "official page",
            "official site",
            "official website",
            "official link",
            "information portal",
            "behoerde",
            "behorde",
            "magistrat",
            "stadt wien",
            "wien.gv",
        )
    )


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
    safe_work_texts = _safe_work_texts_for_quality(safe_work_result)
    adapter_hint = _transcript_signal_adapter_hint(stage_packet)
    transcript_signal = adapter_hint == "transcript_signal"
    if not packet_artifacts_match_run_receipt:
        issues.append("packet_artifacts_do_not_match_run_receipt")
    if transcript_signal:
        has_action_intent = any(_transcript_has_action_intent(_folded_text(text)) for text in (*request_texts, *safe_work_texts))
        raw_noise_like = any(_text_is_noise_like(text) for text in request_texts)
        safe_work_noise_like = any(_text_is_noise_like(text) for text in safe_work_texts)
        safe_work_clean_action_text_present = bool(safe_work_texts) and not safe_work_noise_like and any(
            _transcript_has_action_intent(_folded_text(text)) for text in safe_work_texts
        )
        if not has_action_intent:
            issues.append("transcript_signal_lacks_action_intent")
        if raw_noise_like and not safe_work_clean_action_text_present:
            issues.append("transcript_signal_noise_like_query")
    audit = _as_mapping(safe_work_result.get("audit"))
    audit_status = str(audit.get("status") or "").strip().lower()
    audit_issue_codes = _safe_work_audit_issue_codes(audit)
    if audit_status != "pass":
        issues.append("safe_work_audit_not_pass")
    recommended = _as_mapping(safe_work_result.get("recommended_option_or_draft"))
    candidate_text = _candidate_text_for_quality(recommended)
    if candidate_text and _candidate_is_language_reference(candidate_text) and not _request_allows_language_reference(request_texts):
        issues.append("candidate_reference_page_not_aligned_with_request")
    materiality_issue = _single_official_info_link_quality_issue(
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
        recommended=recommended,
        work_type=_first_text(
            payload.get("work_type"),
            _as_mapping(stage_packet.get("safe_work_order")).get("work_type"),
            safe_work_result.get("work_type"),
        ),
    )
    if materiality_issue:
        issues.append(materiality_issue)
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
            "safe_work_text_count": len(safe_work_texts),
            "safe_work_audit_status": audit_status,
            "safe_work_audit_issue_codes": audit_issue_codes[:8],
            "recommended_kind": str(recommended.get("kind") or "").strip(),
            "recommended_candidate_hash": _hash_value(candidate_text),
            "request_allows_language_reference": _request_allows_language_reference(request_texts),
            "shortlist_count": len(list(safe_work_result.get("shortlist") or [])),
            "decision_materiality_issue_code": materiality_issue,
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


def _summary_for_status(
    status: str,
    *,
    approval_capture_surface_ready: bool = False,
    approval_capture_telegram_ready: bool = False,
    approval_capture_manual_ready: bool = False,
) -> str:
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
            if approval_capture_manual_ready and not approval_capture_telegram_ready:
                return "A proactive OODA packet has local gold-proof runtime evidence and manual approval outcome capture is ready; capture the redacted approval outcome next."
            return "A proactive OODA packet has local gold-proof runtime evidence and a live Telegram approval capture surface; capture the redacted approval outcome next."
        return "A proactive OODA packet has local gold-proof runtime evidence; capture the redacted approval outcome next."
    return "Proactive OODA gold proof is still blocked because one or more packet-evidence links are missing."


def _operator_runtime_next_action(operator_status: Mapping[str, Any]) -> str:
    reason = str(operator_status.get("reason") or "").strip()
    if reason.startswith("google_workspace_signal_source_unhealthy:"):
        return "reauthorize_google_workspace_binding"
    source_ready, source_detail = _operator_runtime_source_coverage_posture(operator_status)
    if not source_ready:
        next_action = str(source_detail.get("next_action") or "").strip()
        if next_action:
            return next_action
    context_ready, context_detail = _operator_runtime_context_grounding_posture(operator_status)
    if not context_ready:
        next_action = str(context_detail.get("next_action") or "").strip()
        if next_action:
            return next_action
    safe_work_audit_ready, safe_work_audit_detail = _operator_runtime_safe_work_audit_posture(operator_status)
    if not safe_work_audit_ready:
        next_action = str(safe_work_audit_detail.get("next_action") or "").strip()
        if next_action:
            return next_action
    current_artifact_filter_ready, current_artifact_filter_detail = _operator_runtime_current_artifact_filter_posture(
        operator_status
    )
    if not current_artifact_filter_ready:
        next_action = str(current_artifact_filter_detail.get("next_action") or "").strip()
        if next_action:
            return next_action
    suppressed_projection_ready, suppressed_projection_detail = _operator_runtime_suppressed_projection_posture(
        operator_status
    )
    if not suppressed_projection_ready:
        next_action = str(suppressed_projection_detail.get("next_action") or "").strip()
        if next_action:
            return next_action
    return str(operator_status.get("next_action") or "repair_proactive_operator_runtime_posture").strip() or "repair_proactive_operator_runtime_posture"


def _operator_runtime_source_coverage_posture(operator_status: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    source_coverage = dict(operator_status.get("source_coverage") or {})
    if not source_coverage:
        operator_status_state = str(operator_status.get("status") or "").strip()
        legacy_ready = operator_status_state.startswith("ready")
        return (
            legacy_ready,
            {
                "source_coverage_checked": False,
                "source_coverage_status": "legacy_not_recorded",
                "source_coverage_ready": legacy_ready,
                "source_coverage_lane_count": 0,
                "source_coverage_observed_lane_count": 0,
                "source_coverage_missing_lane_keys": [],
                "source_coverage_missing_required_event_types": [],
                "source_coverage_legacy_compatibility": True,
                "next_action": "" if legacy_ready else "probe_proactive_source_coverage",
            },
        )
    lanes = [dict(row or {}) for row in list(source_coverage.get("lanes") or []) if isinstance(row, Mapping)]
    missing_lane_keys = [
        str(item).strip()
        for item in list(source_coverage.get("missing_lane_keys") or [])
        if str(item).strip()
    ]
    if not missing_lane_keys:
        missing_lane_keys = [
            str(row.get("key") or "").strip()
            for row in lanes
            if str(row.get("key") or "").strip() and not bool(row.get("observed"))
        ]
    lane_count = int(source_coverage.get("lane_count") or len(lanes) or 0)
    observed_lane_count = int(source_coverage.get("observed_lane_count") or 0)
    status = str(source_coverage.get("status") or "").strip()
    checked = bool(source_coverage.get("checked"))
    missing_required_event_types: list[str] = []
    next_action = ""
    for lane in lanes:
        if bool(lane.get("observed")):
            continue
        if not next_action:
            next_action = str(lane.get("next_action") or "").strip()
        for item in list(lane.get("missing_required_event_types") or []):
            text = str(item).strip()
            if text:
                missing_required_event_types.append(text)
    if not next_action:
        next_action = str(source_coverage.get("next_action") or "").strip()
    ready = checked and status == "ready" and lane_count > 0 and observed_lane_count >= lane_count and not missing_lane_keys
    detail: dict[str, Any] = {
        "source_coverage_checked": checked,
        "source_coverage_status": status,
        "source_coverage_ready": ready,
        "source_coverage_lane_count": lane_count,
        "source_coverage_observed_lane_count": observed_lane_count,
        "source_coverage_missing_lane_keys": missing_lane_keys,
        "source_coverage_missing_required_event_types": sorted(set(missing_required_event_types)),
        "next_action": next_action or "probe_proactive_source_coverage",
    }
    return (ready, detail)


def _operator_runtime_context_grounding_posture(operator_status: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    context = dict(operator_status.get("context_grounding") or {})
    if not context:
        return True, {
            "context_grounding_recorded": False,
            "context_grounding_grounded": False,
            "context_grounding_item_count": 0,
            "context_grounding_grounded_item_count": 0,
            "context_grounding_ungrounded_item_count": 0,
            "context_grounding_applied_context_count": 0,
            "context_grounding_recipient_location_count": 0,
            "context_grounding_ready": True,
            "next_action": "",
        }
    item_count = int(context.get("item_count") or 0)
    grounded = bool(context.get("grounded"))
    ready = item_count <= 0 or grounded
    return ready, {
        "context_grounding_recorded": True,
        "context_grounding_grounded": grounded,
        "context_grounding_ready": ready,
        "context_grounding_item_count": item_count,
        "context_grounding_grounded_item_count": int(context.get("grounded_item_count") or 0),
        "context_grounding_ungrounded_item_count": int(context.get("ungrounded_item_count") or 0),
        "context_grounding_applied_context_count": int(context.get("applied_context_count") or 0),
        "context_grounding_preference_count": int(context.get("preference_count") or 0),
        "context_grounding_requirement_count": int(context.get("requirement_count") or 0),
        "context_grounding_deadline_count": int(context.get("deadline_count") or 0),
        "context_grounding_candidate_assessment_count": int(context.get("candidate_assessment_count") or 0),
        "context_grounding_recipient_context_count": int(context.get("recipient_context_count") or 0),
        "context_grounding_recipient_location_count": int(context.get("recipient_location_count") or 0),
        "next_action": "" if ready else "repair_proactive_context_grounding",
    }


def _operator_runtime_safe_work_audit_posture(operator_status: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    safe_work_audit = dict(operator_status.get("safe_work_audit") or {})
    if not safe_work_audit:
        return True, {
            "safe_work_audit_recorded": False,
            "safe_work_audit_present": False,
            "safe_work_audit_ready": True,
            "safe_work_audit_status": "",
            "safe_work_audit_result_status": "",
            "safe_work_audit_issue_count": 0,
            "safe_work_audit_issue_codes": [],
            "safe_work_audit_delivery_allowed": False,
            "safe_work_audit_blocks_operator_followthrough": False,
            "next_action": "",
        }
    present = bool(safe_work_audit.get("present"))
    delivery_allowed = bool(safe_work_audit.get("delivery_allowed"))
    blocks_operator = bool(safe_work_audit.get("blocks_operator_followthrough"))
    ready = (not present) or delivery_allowed or not blocks_operator
    return ready, {
        "safe_work_audit_recorded": True,
        "safe_work_audit_present": present,
        "safe_work_audit_ready": ready,
        "safe_work_audit_status": str(safe_work_audit.get("audit_status") or "").strip(),
        "safe_work_audit_result_status": str(safe_work_audit.get("result_status") or "").strip(),
        "safe_work_audit_issue_count": int(safe_work_audit.get("issue_count") or 0),
        "safe_work_audit_issue_codes": [
            str(item or "").strip()
            for item in list(safe_work_audit.get("issue_codes") or [])
            if str(item or "").strip()
        ][:8],
        "safe_work_audit_delivery_allowed": delivery_allowed,
        "safe_work_audit_blocks_operator_followthrough": blocks_operator,
        "safe_work_audit_blocking_reason": str(safe_work_audit.get("blocking_reason") or "").strip(),
        "next_action": "" if ready else "repair_proactive_safe_work_audit",
    }


def _operator_runtime_current_artifact_filter_posture(operator_status: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    filtered = dict(operator_status.get("current_artifact_filter") or {})
    if not filtered:
        return True, {
            "current_artifact_filter_recorded": False,
            "current_artifact_filter_present": False,
            "current_artifact_filter_ready": True,
            "current_artifact_filter_requires_recovery": False,
            "current_artifact_filter_reason": "",
            "current_artifact_filter_issue_codes": [],
            "next_action": "",
        }
    requires_recovery = bool(filtered.get("requires_recovery"))
    ready = not requires_recovery
    return ready, {
        "current_artifact_filter_recorded": True,
        "current_artifact_filter_present": bool(filtered.get("present")),
        "current_artifact_filter_ready": ready,
        "current_artifact_filter_requires_recovery": requires_recovery,
        "current_artifact_filter_reason": str(filtered.get("reason") or "").strip(),
        "current_artifact_filter_blocking_reason": str(filtered.get("blocking_reason") or "").strip(),
        "current_artifact_filter_issue_codes": [
            str(item or "").strip()
            for item in list(filtered.get("issue_codes") or [])
            if str(item or "").strip()
        ][:8],
        "next_action": "" if ready else "repair_proactive_safe_work_audit",
    }


def _operator_runtime_suppressed_projection_posture(operator_status: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    suppressed = dict(operator_status.get("suppressed_projection") or {})
    if not suppressed:
        return True, {
            "suppressed_projection_recorded": False,
            "suppressed_projection_present": False,
            "suppressed_projection_ready": True,
            "suppressed_projection_requires_recovery": False,
            "suppressed_projection_status": "",
            "suppressed_projection_item_count": 0,
            "suppressed_projection_safe_work_review_count": 0,
            "suppressed_projection_reasons": [],
            "suppressed_projection_issue_codes": [],
            "suppressed_projection_inferred_from_packet_gap": False,
            "next_action": "",
        }
    requires_recovery = bool(suppressed.get("requires_recovery"))
    ready = not requires_recovery
    return ready, {
        "suppressed_projection_recorded": True,
        "suppressed_projection_present": bool(suppressed.get("present")),
        "suppressed_projection_ready": ready,
        "suppressed_projection_requires_recovery": requires_recovery,
        "suppressed_projection_status": str(suppressed.get("status") or "").strip(),
        "suppressed_projection_blocking_reason": str(suppressed.get("blocking_reason") or "").strip(),
        "suppressed_projection_item_count": int(suppressed.get("suppressed_item_count") or 0),
        "suppressed_projection_safe_work_review_count": int(
            suppressed.get("suppressed_safe_work_review_count") or 0
        ),
        "suppressed_projection_reasons": [
            str(item or "").strip()
            for item in list(suppressed.get("suppressed_projection_reasons") or [])
            if str(item or "").strip()
        ][:8],
        "suppressed_projection_issue_codes": [
            str(item or "").strip()
            for item in list(suppressed.get("suppressed_safe_work_issue_codes") or [])
            if str(item or "").strip()
        ][:12],
        "suppressed_projection_teable_status": str(suppressed.get("teable_status") or "").strip(),
        "suppressed_projection_record_count": int(suppressed.get("projection_record_count") or 0),
        "suppressed_projection_packet_record_count": int(
            suppressed.get("packet_projection_record_count") or 0
        ),
        "suppressed_projection_inferred_from_packet_gap": bool(
            suppressed.get("inferred_from_packet_projection_gap")
        ),
        "next_action": "" if ready else "repair_proactive_safe_work_audit",
    }


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
    approval_capture_readiness_present: bool,
    approval_row: Mapping[str, Any],
    approval_capture_surface_ready: bool,
    approval_capture_telegram_ready: bool,
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
    if not approval_capture_readiness_present:
        approval_capture = dict(operator_status.get("approval_capture") or {})
        return str(approval_capture.get("next_action") or "repair_proactive_approval_capture").strip() or "repair_proactive_approval_capture"
    if not bool(approval_row.get("approval_outcome_recorded")):
        if approval_capture_surface_ready and approval_capture_telegram_ready:
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
    approval_capture_readiness_present: bool,
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
    if not approval_capture_readiness_present:
        remaining.append("redacted approval-capture readiness for the proactive OODA packet")
    if not bool(approval_row.get("approval_outcome_recorded")):
        remaining.append("redacted explicit approval outcome for the proactive OODA packet")
    elif not bool(approval_row.get("accepted")):
        remaining.append("real proactive OODA packet accepted under ordinary use")
    return remaining


def _action_required_only_policy_probe() -> dict[str, Any]:
    low_value_research_request = {
        "packet_ref": "policy_probe:research",
        "staged_artifact_ref": "policy_probe:research_artifact",
        "approval_prompt": (
            "Approve whether EA should research further or change constraints. "
            "Research, compare, or draft only; require explicit approval before purchase, booking, "
            "cancellation, sending, posting, or commitment."
        ),
    }
    internal_proof_request = {
        "packet_ref": "policy_probe:proof",
        "staged_artifact_ref": "policy_probe:proof_artifact",
        "approval_prompt": "Approve whether EA should preserve this proof packet as the canonical live check.",
    }
    executable_draft_request = {
        "packet_ref": "policy_probe:draft",
        "staged_artifact_ref": "policy_probe:draft_artifact",
        "approval_prompt": "Approve whether EA should keep this saved Gmail draft as the chosen next step.",
        "approved_execution_mode": "record_outcome_only",
        "approved_action": "save_gmail_draft",
    }
    low_value_requires_action = approval_request_needs_telegram_user_action(low_value_research_request)
    internal_requires_action = approval_request_needs_telegram_user_action(internal_proof_request)
    executable_draft_requires_action = approval_request_needs_telegram_user_action(executable_draft_request)
    return {
        "checked": True,
        "status": "pass"
        if not low_value_requires_action and not internal_requires_action and executable_draft_requires_action
        else "blocked",
        "low_value_research_prompt_requires_user_action": low_value_requires_action,
        "internal_proof_packet_requires_user_action": internal_requires_action,
        "executable_draft_prompt_requires_user_action": executable_draft_requires_action,
        "raw_policy_prompt_exposed": False,
    }


def _approval_capture_readiness_proof(
    *,
    operator_status: Mapping[str, Any],
    approval_capture_surface: Mapping[str, Any] | None = None,
    required: bool,
    approval_outcome_recorded: bool,
    approval_outcome_matches_current_packet: bool,
) -> tuple[dict[str, Any], bool]:
    approval_capture = dict(operator_status.get("approval_capture") or {})
    approval_capture_surface = dict(
        approval_capture_surface
        if approval_capture_surface is not None
        else (operator_status.get("approval_capture_surface") or {})
    )
    privacy = dict(approval_capture.get("privacy") or {})
    checked = bool(approval_capture.get("checked"))
    raw_exposure = any(
        bool(privacy.get(key))
        for key in (
            "raw_callback_token_exposed",
            "raw_principal_id_exposed",
            "raw_chat_ref_exposed",
            "raw_packet_ref_exposed",
            "raw_staged_artifact_ref_exposed",
        )
    )
    live_callback_ready = bool(approval_capture.get("ready"))
    telegram_approval_surface_ready = bool(approval_capture_surface.get("telegram_approval_surface_ready"))
    manual_outcome_capture_ready = bool(
        approval_capture_surface.get("manual_outcome_capture_ready")
        and approval_capture_surface.get("current_packet_approval_request_recordable")
        and approval_capture_surface.get("ready")
    )
    ready = bool(live_callback_ready or manual_outcome_capture_ready)
    satisfied_by_recorded_outcome = bool(
        approval_outcome_recorded and approval_outcome_matches_current_packet and not raw_exposure
    )
    live_callback_present = bool(
        checked
        and bool(approval_capture.get("probe_ok"))
        and live_callback_ready
        and not raw_exposure
        and bool(approval_capture.get("current_packet_refs_present"))
        and int(approval_capture.get("current_packet_live_pending_count") or 0) > 0
        and int(approval_capture.get("current_packet_callback_record_count") or 0) > 0
        and bool(approval_capture.get("callback_principal_hash_present"))
        and int(approval_capture.get("candidate_principal_hash_count") or 0) > 0
        and bool(approval_capture.get("principal_match_ready"))
        and bool(approval_capture.get("telegram_binding_ready"))
        and bool(approval_capture.get("telegram_chat_ref_present"))
        and bool(approval_capture.get("telegram_bot_token_present"))
    )
    manual_capture_present = bool(manual_outcome_capture_ready and not raw_exposure)
    present = (
        satisfied_by_recorded_outcome
        or (not required and not checked)
        or live_callback_present
        or manual_capture_present
    )
    return (
        _proof_row(
            present=present,
            detail={
                "required": required,
                "checked": checked,
                "probe_ok": bool(approval_capture.get("probe_ok")),
                "ready": ready,
                "live_callback_ready": live_callback_ready,
                "live_callback_present": live_callback_present,
                "manual_capture_present": manual_capture_present,
                "approval_capture_surface_present": bool(approval_capture_surface.get("present")),
                "approval_capture_surface_ready": bool(approval_capture_surface.get("ready")),
                "approval_capture_surface_mode": str(approval_capture_surface.get("mode") or "").strip(),
                "telegram_approval_surface_ready": telegram_approval_surface_ready,
                "manual_outcome_capture_ready": manual_outcome_capture_ready,
                "current_packet_approval_request_recordable": bool(
                    approval_capture_surface.get("current_packet_approval_request_recordable")
                ),
                "satisfied_by_recorded_outcome": satisfied_by_recorded_outcome,
                "approval_outcome_recorded": approval_outcome_recorded,
                "approval_outcome_matches_current_packet": approval_outcome_matches_current_packet,
                "capture_status": str(approval_capture.get("status") or "").strip(),
                "source": str(approval_capture.get("source") or "").strip(),
                "observed_at": str(approval_capture.get("observed_at") or "").strip(),
                "blocking_reason": str(approval_capture.get("blocking_reason") or "").strip(),
                "next_action": str(approval_capture.get("next_action") or "").strip(),
                "current_packet_refs_present": bool(approval_capture.get("current_packet_refs_present")),
                "current_packet_callback_record_count": int(approval_capture.get("current_packet_callback_record_count") or 0),
                "current_packet_live_pending_count": int(approval_capture.get("current_packet_live_pending_count") or 0),
                "current_packet_callback_latest_status": str(
                    approval_capture.get("current_packet_callback_latest_status") or ""
                ).strip(),
                "callback_principal_hash_present": bool(approval_capture.get("callback_principal_hash_present")),
                "candidate_principal_hash_count": int(approval_capture.get("candidate_principal_hash_count") or 0),
                "principal_match_ready": bool(approval_capture.get("principal_match_ready")),
                "telegram_binding_ready": bool(approval_capture.get("telegram_binding_ready")),
                "telegram_chat_ref_present": bool(approval_capture.get("telegram_chat_ref_present")),
                "telegram_bot_token_present": bool(approval_capture.get("telegram_bot_token_present")),
                "raw_callback_token_exposed": bool(privacy.get("raw_callback_token_exposed")),
                "raw_principal_id_exposed": bool(privacy.get("raw_principal_id_exposed")),
                "raw_chat_ref_exposed": bool(privacy.get("raw_chat_ref_exposed")),
                "raw_packet_ref_exposed": bool(privacy.get("raw_packet_ref_exposed")),
                "raw_staged_artifact_ref_exposed": bool(privacy.get("raw_staged_artifact_ref_exposed")),
            },
        ),
        present,
    )


def _approval_capture_surface_receipt(
    *,
    operator_status: Mapping[str, Any],
    bundle: Mapping[str, Any],
    approval_outcome_path: Path | None,
    used_live_runtime_probe: bool,
) -> tuple[dict[str, Any], bool]:
    operator_surface = dict(operator_status.get("approval_capture_surface") or {})
    operator_capture = dict(operator_status.get("approval_capture") or {})
    selected_channel = _first_text(
        operator_surface.get("selected_channel"),
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
        current_packet_callback_latest_created_at = str(
            bundle.get("current_packet_callback_latest_created_at") or ""
        ).strip()
        current_packet_callback_latest_expires_at = str(
            bundle.get("current_packet_callback_latest_expires_at") or ""
        ).strip()
        current_packet_callback_latest_age_seconds = int(
            bundle.get("current_packet_callback_latest_age_seconds") or 0
        )
        current_packet_callback_latest_seconds_until_expiry = int(
            bundle.get("current_packet_callback_latest_seconds_until_expiry") or 0
        )
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
            current_packet_callback_latest_created_at,
            current_packet_callback_latest_expires_at,
            current_packet_callback_latest_age_seconds,
            current_packet_callback_latest_seconds_until_expiry,
        ) = _matching_callback_stats(
            callback_dir_path,
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
        )
    if current_packet_live_pending_count <= 0 and int(operator_surface.get("current_packet_live_pending_count") or 0) > 0:
        callback_dir_exists = bool(operator_surface.get("callback_dir_exists") or callback_dir_exists)
        callback_record_count = int(operator_surface.get("callback_record_count") or callback_record_count)
        callback_pending_count = int(operator_surface.get("callback_pending_count") or callback_pending_count)
        callback_recorded_count = int(operator_surface.get("callback_recorded_count") or callback_recorded_count)
        current_packet_callback_record_count = int(
            operator_surface.get("current_packet_callback_record_count") or current_packet_callback_record_count
        )
        current_packet_callback_pending_count = int(
            operator_surface.get("current_packet_callback_pending_count") or current_packet_callback_pending_count
        )
        current_packet_callback_recorded_count = int(
            operator_surface.get("current_packet_callback_recorded_count") or current_packet_callback_recorded_count
        )
        current_packet_live_callback_record_count = int(
            operator_surface.get("current_packet_live_callback_record_count") or current_packet_live_callback_record_count
        )
        current_packet_live_pending_count = int(operator_surface.get("current_packet_live_pending_count") or 0)
        current_packet_callback_latest_status = str(
            operator_surface.get("current_packet_callback_latest_status") or current_packet_callback_latest_status
        ).strip()
        current_packet_callback_latest_expired = bool(
            operator_surface.get("current_packet_callback_latest_expired")
        )
        current_packet_callback_latest_created_at = str(
            operator_surface.get("current_packet_callback_latest_created_at") or current_packet_callback_latest_created_at
        ).strip()
        current_packet_callback_latest_expires_at = str(
            operator_surface.get("current_packet_callback_latest_expires_at") or current_packet_callback_latest_expires_at
        ).strip()
        current_packet_callback_latest_age_seconds = int(
            operator_surface.get("current_packet_callback_latest_age_seconds") or current_packet_callback_latest_age_seconds
        )
        current_packet_callback_latest_seconds_until_expiry = int(
            operator_surface.get("current_packet_callback_latest_seconds_until_expiry")
            or current_packet_callback_latest_seconds_until_expiry
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
    current_packet_approval_request_recordable = bool(
        operator_surface.get("current_packet_approval_request_recordable")
    )
    telegram_approval_surface_candidate = bool(operator_surface.get("telegram_approval_surface_ready")) or (
        current_packet_live_pending_count > 0
    )
    telegram_approval_surface_ready = bool(
        telegram_approval_surface_candidate
        and bool(operator_capture.get("checked"))
    )
    manual_outcome_capture_ready = bool(
        operator_surface.get("manual_outcome_capture_ready") and current_packet_approval_request_recordable
    )
    ready = (
        selected_channel == "telegram"
        and approval_outcome_path is not None
        and callback_dir_path is not None
        and callback_dir_writable
        and (telegram_approval_surface_ready or manual_outcome_capture_ready)
    )
    mode = (
        "telegram_callback_pending"
        if telegram_approval_surface_ready
        else "manual_outcome_capture_ready"
        if manual_outcome_capture_ready
        else str(operator_surface.get("mode") or "").strip()
    )
    return (
        {
            "present": bool(approval_outcome_path or callback_dir_path),
            "ready": ready,
            "mode": mode,
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
            "current_packet_callback_latest_created_at": current_packet_callback_latest_created_at,
            "current_packet_callback_latest_expires_at": current_packet_callback_latest_expires_at,
            "current_packet_callback_latest_age_seconds": current_packet_callback_latest_age_seconds,
            "current_packet_callback_latest_seconds_until_expiry": current_packet_callback_latest_seconds_until_expiry,
            "current_packet_status": str(operator_surface.get("current_packet_status") or "").strip(),
            "current_packet_present": bool(operator_surface.get("current_packet_present")),
            "current_packet_approval_request_recordable": current_packet_approval_request_recordable,
            "approval_outcome_matches_current_packet": bool(
                operator_surface.get("approval_outcome_matches_current_packet")
            ),
            "telegram_approval_surface_ready": telegram_approval_surface_ready,
            "manual_outcome_capture_ready": manual_outcome_capture_ready,
            "source": "docker_compose_exec" if used_live_runtime_probe else "local_filesystem",
            "operator_surface_source": str(operator_surface.get("source") or "").strip(),
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
) -> tuple[int, int, int, int, int, str, bool, str, str, int, int]:
    if path is None or not path.is_dir():
        return 0, 0, 0, 0, 0, "", False, "", "", 0, 0
    packet_ref = _stage_packet_ref(stage_packet)
    artifact_ref = _safe_work_result_ref(safe_work_result)
    if not packet_ref or not artifact_ref:
        return 0, 0, 0, 0, 0, "", False, "", "", 0, 0
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
        return 0, 0, 0, 0, 0, "", False, "", "", 0, 0
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    latest = rows[-1] if rows else {}
    latest_created_at = str(latest.get("created_at") or "").strip()
    latest_expires_at = str(latest.get("expires_at") or "").strip()
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
        latest_created_at,
        latest_expires_at,
        _callback_age_seconds(latest_created_at),
        _callback_seconds_until(latest_expires_at),
    )


def _callback_expired(row: Mapping[str, Any]) -> bool:
    text = str(row.get("expires_at") or "").strip()
    if not text:
        return False
    expires_at = _parse_callback_datetime(text)
    if expires_at is None:
        return False
    return expires_at <= datetime.now(UTC)


def _callback_age_seconds(value: str) -> int:
    parsed = _parse_callback_datetime(value)
    if parsed is None:
        return 0
    return max(int((datetime.now(UTC) - parsed).total_seconds()), 0)


def _callback_seconds_until(value: str) -> int:
    parsed = _parse_callback_datetime(value)
    if parsed is None:
        return 0
    return max(int((parsed - datetime.now(UTC)).total_seconds()), 0)


def _parse_callback_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
            prefer_browse_backed_delivery=True,
        )
        if use_local_bundle
        else {}
    )
    local_complete = bool(local_bundle.get("run_receipt")) and bool(local_bundle.get("stage_packet")) and bool(local_bundle.get("safe_work_result"))
    if allow_live_runtime_probe:
        live_report = ea_live_ops.probe_proactive_artifacts(
            output_format="json",
            prefer_browse_backed_delivery=True,
        )
        if bool(live_report.get("probe_ok")):
            live_bundle = {
                "run_receipt_path": _path_from_text(ROOT, str(live_report.get("run_receipt_path") or "")),
                "run_receipt": dict(live_report.get("run_receipt") or {}),
                "action_required_only_quiet_receipt_path": _path_from_text(
                    ROOT,
                    str(live_report.get("action_required_only_quiet_receipt_path") or ""),
                ),
                "action_required_only_quiet_receipt": dict(
                    live_report.get("action_required_only_quiet_receipt") or {}
                ),
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
            "current_packet_callback_latest_created_at": str(live_report.get("current_packet_callback_latest_created_at") or "").strip(),
            "current_packet_callback_latest_expires_at": str(live_report.get("current_packet_callback_latest_expires_at") or "").strip(),
            "current_packet_callback_latest_age_seconds": int(live_report.get("current_packet_callback_latest_age_seconds") or 0),
            "current_packet_callback_latest_seconds_until_expiry": int(
                live_report.get("current_packet_callback_latest_seconds_until_expiry") or 0
            ),
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
    quiet_receipt_path = bundle.get("action_required_only_quiet_receipt_path")
    quiet_receipt = dict(bundle.get("action_required_only_quiet_receipt") or {})
    resolved_stage_dir = bundle.get("stage_packet_dir")
    resolved_safe_dir = bundle.get("safe_work_result_dir")
    operator_status = _refresh_operator_status_snapshot(path=operator_status_path, current=operator_status)
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
    approval_capture_telegram_ready = bool(approval_capture_surface.get("telegram_approval_surface_ready"))
    approval_capture_manual_ready = bool(approval_capture_surface.get("manual_outcome_capture_ready"))
    approval_capture_readiness_required = approval_capture_surface_ready and not bool(approval_row.get("approval_outcome_recorded"))
    approval_capture_readiness_proof, approval_capture_readiness_present = _approval_capture_readiness_proof(
        operator_status=operator_status,
        approval_capture_surface=approval_capture_surface,
        required=approval_capture_readiness_required,
        approval_outcome_recorded=bool(approval_row.get("approval_outcome_recorded")),
        approval_outcome_matches_current_packet=approval_artifact_matches_current_packet,
    )

    delivery_route = dict(operator_status.get("delivery_route") or {})
    live_receipt = dict(operator_status.get("live_receipt") or {})
    operator_status_state = str(operator_status.get("status") or "").strip()
    source_coverage_ready, source_coverage_detail = _operator_runtime_source_coverage_posture(operator_status)
    context_grounding_ready, context_grounding_detail = _operator_runtime_context_grounding_posture(operator_status)
    safe_work_audit_ready, safe_work_audit_detail = _operator_runtime_safe_work_audit_posture(operator_status)
    current_artifact_filter_ready, current_artifact_filter_detail = _operator_runtime_current_artifact_filter_posture(
        operator_status
    )
    suppressed_projection_ready, suppressed_projection_detail = _operator_runtime_suppressed_projection_posture(
        operator_status
    )
    operator_runtime_ready = (
        operator_status_state.startswith("ready")
        and source_coverage_ready
        and context_grounding_ready
        and safe_work_audit_ready
        and current_artifact_filter_ready
        and suppressed_projection_ready
    )
    operator_runtime_next_action = _operator_runtime_next_action(operator_status)
    operator_runtime_proof = _proof_row(
        present=operator_runtime_ready,
        detail={
            "status": operator_status_state,
            "reason": str(operator_status.get("reason") or "").strip(),
            "next_action": operator_runtime_next_action,
            **source_coverage_detail,
            **context_grounding_detail,
            **safe_work_audit_detail,
            **current_artifact_filter_detail,
            **suppressed_projection_detail,
            **_next_action_surface_fields(operator_runtime_next_action),
            "path": display_path(ROOT, operator_status_path),
        },
    )
    packet_run_sent = str(run_receipt.get("notification_status") or "").strip() == "sent" and int(run_receipt.get("item_count") or 0) > 0
    delivery_mirror = dict(run_receipt.get("delivery_mirror") or {})
    mirrored_delivery_present = (
        bool(operator_status.get("delivery_route_ready"))
        and str(run_receipt.get("notification_status") or "").strip() == "deferred"
        and str(run_receipt.get("error_code") or "").strip() == "mirrored_delivery_proof"
        and int(run_receipt.get("item_count") or 0) > 0
        and bool(delivery_mirror.get("enabled"))
        and str(delivery_mirror.get("mode") or "").strip() == "operator_safe_mirror"
        and bool(delivery_mirror.get("user_notification_suppressed"))
        and bool(delivery_mirror.get("approval_request_requires_user_action"))
        and packet_artifacts_match_run_receipt
    )
    sent_delivery_present = (
        bool(operator_status.get("delivery_route_ready"))
        and bool(operator_status.get("live_receipt_checked"))
        and bool(live_receipt.get("ok"))
        and packet_run_sent
        and packet_artifacts_match_run_receipt
    )
    delivery_present = bool(sent_delivery_present or mirrored_delivery_present)
    delivery_proof = _proof_row(
        present=delivery_present,
        detail={
            "delivery_mode": "telegram_sent" if sent_delivery_present else "operator_safe_mirror" if mirrored_delivery_present else "",
            "route_probe_source": str(operator_status.get("route_probe_source") or "").strip(),
            "route_probe_runtime_service": str(operator_status.get("route_probe_runtime_service") or "").strip(),
            "selected_channel": _first_text(delivery_route.get("selected_channel"), live_receipt.get("delivery_channel")),
            "route_ready": bool(operator_status.get("delivery_route_ready")),
            "live_receipt_checked": bool(operator_status.get("live_receipt_checked")),
            "live_receipt_ok": bool(live_receipt.get("ok")),
            "live_receipt_path": str(live_receipt.get("receipt_path") or "").strip(),
            "run_notification_status": str(run_receipt.get("notification_status") or "").strip(),
            "run_error_code": str(run_receipt.get("error_code") or "").strip(),
            "run_item_count": int(run_receipt.get("item_count") or 0),
            "sent_delivery_present": sent_delivery_present,
            "mirrored_delivery_present": mirrored_delivery_present,
            "mirror_mode": str(delivery_mirror.get("mode") or "").strip(),
            "mirror_user_notification_suppressed": bool(delivery_mirror.get("user_notification_suppressed")),
            "mirror_approval_request_requires_user_action": bool(
                delivery_mirror.get("approval_request_requires_user_action")
            ),
            "mirror_raw_notification_text_exposed": bool(delivery_mirror.get("raw_notification_text_exposed")),
            "mirror_raw_approval_prompt_exposed": bool(delivery_mirror.get("raw_approval_prompt_exposed")),
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
    quiet_receipt_message_count = _delivery_message_count(quiet_receipt)
    quiet_receipt_proves_action_required_only = (
        str(quiet_receipt.get("notification_status") or "").strip() == "deferred"
        and str(quiet_receipt.get("error_code") or "").strip() == "no_user_action_required"
        and int(quiet_receipt.get("item_count") or 0) > 0
        and not bool(quiet_receipt.get("dry_run"))
        and quiet_receipt_message_count == 0
    )
    action_required_policy_probe = _action_required_only_policy_probe()
    action_required_policy_pass = str(action_required_policy_probe.get("status") or "").strip() == "pass"
    action_required_delivery_present = bool(
        delivery_present
        and sent_packet_had_user_action_surface
        and action_required_policy_pass
        and (current_guard_is_quiet_without_action or quiet_receipt_proves_action_required_only)
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
            "quiet_receipt_present": bool(quiet_receipt),
            "quiet_receipt_path": display_path(ROOT, quiet_receipt_path),
            "quiet_receipt_notification_status": str(quiet_receipt.get("notification_status") or "").strip(),
            "quiet_receipt_error_code": str(quiet_receipt.get("error_code") or "").strip(),
            "quiet_receipt_item_count": int(quiet_receipt.get("item_count") or 0),
            "quiet_receipt_message_count": quiet_receipt_message_count,
            "quiet_receipt_proves_action_required_only": quiet_receipt_proves_action_required_only,
            "policy_probe_checked": bool(action_required_policy_probe.get("checked")),
            "policy_probe_status": str(action_required_policy_probe.get("status") or "").strip(),
            "low_value_research_prompt_requires_user_action": bool(
                action_required_policy_probe.get("low_value_research_prompt_requires_user_action")
            ),
            "internal_proof_packet_requires_user_action": bool(
                action_required_policy_probe.get("internal_proof_packet_requires_user_action")
            ),
            "executable_draft_prompt_requires_user_action": bool(
                action_required_policy_probe.get("executable_draft_prompt_requires_user_action")
            ),
            "raw_policy_prompt_exposed": bool(action_required_policy_probe.get("raw_policy_prompt_exposed")),
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
        and (not approval_capture_telegram_ready or approval_surface_projection_present)
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
            "approval_capture_telegram_surface_ready": approval_capture_telegram_ready,
            "approval_capture_manual_outcome_capture_ready": approval_capture_manual_ready,
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
            approval_capture_readiness_present,
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
        approval_capture_readiness_present=approval_capture_readiness_present,
        approval_row=approval_row,
        approval_capture_surface_ready=approval_capture_surface_ready,
        approval_capture_telegram_ready=approval_capture_telegram_ready,
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
        "summary": _summary_for_status(
            status,
            approval_capture_surface_ready=approval_capture_surface_ready,
            approval_capture_telegram_ready=approval_capture_telegram_ready,
            approval_capture_manual_ready=approval_capture_manual_ready,
        ),
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
            "approval_capture_readiness": approval_capture_readiness_proof,
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
            "approval_capture": dict(operator_status.get("approval_capture") or {}),
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
            approval_capture_readiness_present=approval_capture_readiness_present,
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
    parser.add_argument("--live-runtime-probe", action="store_true")
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
        allow_live_runtime_probe=bool(args.live_runtime_probe),
    )
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
