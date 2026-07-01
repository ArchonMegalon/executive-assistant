from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_state_head import resolve_source_state_head  # noqa: E402
from scripts.source_state_head import resolve_source_worktree_fingerprint  # noqa: E402
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_acceptance_evidence.generated.json"
DEFAULT_PROACTIVE_OODA_GOLD_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json"
COMMITMENT_CLOSURE_RECEIPT_CONTRACT = "ea.commitment_closure_evidence_receipt.v1"

REQUIRED_ACCEPTANCE_KEYS = [
    "real_daily_morning_brief_accepted",
    "real_decision_cleared",
    "real_commitment_recovered_or_closed",
    "real_approved_action_audited",
    "real_provider_failure_recovered",
]

REMAINING_PROOF_LABELS = {
    "real_daily_morning_brief_accepted": "real daily morning brief acceptance",
    "real_decision_cleared": "real decision cleared by the principal or operator",
    "real_commitment_recovered_or_closed": "real commitment recovered or closed with an evidence receipt",
    "real_approved_action_audited": "real approved outbound action with audit trail",
    "real_provider_failure_recovered": "real provider failure recovered with operator-grade reason",
}

ACCEPTANCE_CAPTURE_PATH = "/admin/actions/acceptance-evidence"
ACCEPTANCE_CAPTURE_METHOD = "POST"
ACCEPTANCE_CAPTURE_FORM_FIELDS = ["proof_key", "source_kind", "evidence", "object_ref"]
ACCEPTANCE_CAPTURE_LABEL = "Record a real-use outcome"
ACCEPTANCE_CAPTURE_FORM_METHOD = "GET"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _source_state_fields() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _empty_row() -> dict[str, Any]:
    return {
        "accepted": False,
        "status": "missing_or_invalid",
        "source_kind": "unknown",
        "recorded_at": "",
        "evidence_sha256": "",
        "actor_sha256": "",
        "object_ref_sha256": "",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }


def _normalized_existing_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _empty_row()
    normalized.update(dict(row or {}))
    if normalized.get("accepted") is True:
        normalized["status"] = "accepted_redacted"
    normalized["raw_evidence_exposed"] = False
    normalized["raw_actor_exposed"] = False
    normalized["raw_object_ref_exposed"] = False
    return normalized


def _row_from_proof(proof: dict[str, Any]) -> dict[str, Any]:
    accepted = bool(proof.get("accepted"))
    evidence = str(proof.get("evidence") or "")
    actor = str(proof.get("actor") or "")
    object_ref = str(proof.get("object_ref") or "")
    valid = accepted and bool(evidence and actor and object_ref)
    return {
        "accepted": valid,
        "status": "accepted_redacted" if valid else "missing_or_invalid",
        "source_kind": str(proof.get("source") or "unknown"),
        "recorded_at": str(proof.get("recorded_at") or ""),
        "evidence_sha256": _hash(evidence),
        "actor_sha256": _hash(actor),
        "object_ref_sha256": _hash(object_ref),
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }


def _row_from_redacted_hashes(
    *,
    source_kind: str,
    recorded_at: str,
    evidence_sha256: str,
    actor_sha256: str,
    object_ref_sha256: str,
) -> dict[str, Any]:
    valid = bool(evidence_sha256 and actor_sha256 and object_ref_sha256)
    return {
        "accepted": valid,
        "status": "accepted_redacted" if valid else "missing_or_invalid",
        "source_kind": source_kind,
        "recorded_at": recorded_at,
        "evidence_sha256": evidence_sha256,
        "actor_sha256": actor_sha256,
        "object_ref_sha256": object_ref_sha256,
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }


def _email_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return dict(payload)
    payload_json = row.get("payload_json")
    if isinstance(payload_json, dict):
        return dict(payload_json)
    return {}


def _event_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("created_at") or row.get("recorded_at") or row.get("updated_at") or "").strip()


def _event_type(row: dict[str, Any]) -> str:
    return str(row.get("event_type") or "").strip().lower()


def _payload_email(payload: dict[str, Any]) -> str:
    return _email_text(payload.get("recipient_email") or payload.get("email") or payload.get("account_email"))


def _preference_event_matches_email(row: dict[str, Any], recipient_email: str) -> bool:
    object_id = _email_text(row.get("object_id"))
    if object_id == recipient_email:
        return True
    interpreted = row.get("interpreted_signal_json")
    if not isinstance(interpreted, dict):
        return False
    for key in ("account_email", "email", "recipient_email", "primary_email"):
        if _email_text(interpreted.get(key)) == recipient_email:
            return True
    return False


def _google_workspace_auth_action_row_from_bundle(bundle: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(bundle or {})
    principal_id = str(source.get("principal_id") or "").strip()
    recipient_email = _email_text(source.get("recipient_email"))
    if not principal_id or not recipient_email:
        return {}

    observations = [dict(row) for row in list(source.get("observations") or []) if isinstance(row, dict)]
    preference_events = [
        dict(row) for row in list(source.get("preference_evidence_events") or []) if isinstance(row, dict)
    ]
    preference_nodes = [dict(row) for row in list(source.get("preference_nodes") or []) if isinstance(row, dict)]

    sent_event: dict[str, Any] = {}
    sent_payload: dict[str, Any] = {}
    for row in observations:
        payload = _event_payload(row)
        if _event_type(row) != "google_connect_email_sent":
            continue
        if _payload_email(payload) != recipient_email:
            continue
        if str(payload.get("scope_bundle") or "").strip().lower() != "full_workspace":
            continue
        if not str(payload.get("provider") or "").strip():
            continue
        if not str(payload.get("access_session_id") or payload.get("session_id") or "").strip():
            continue
        sent_event = row
        sent_payload = payload
        break

    access_event: dict[str, Any] = {}
    access_payload: dict[str, Any] = {}
    expected_session_id = str(sent_payload.get("access_session_id") or "").strip()
    for row in observations:
        payload = _event_payload(row)
        if _event_type(row) != "workspace_access_session_issued":
            continue
        if _payload_email(payload) != recipient_email:
            continue
        if str(payload.get("source_kind") or "").strip().lower() != "google_connect_email":
            continue
        session_id = str(payload.get("session_id") or "").strip()
        if expected_session_id and session_id and session_id != expected_session_id:
            continue
        if not session_id and not expected_session_id:
            continue
        access_event = row
        access_payload = payload
        break

    request_event = next(
        (
            row
            for row in preference_events
            if _event_type(row)
            in {"explicit_work_google_workspace_intake_requested", "explicit_work_inbox_setup_request"}
            and str(row.get("domain") or "").strip().lower() in {"office_routing", "google_workspace"}
            and _preference_event_matches_email(row, recipient_email)
        ),
        {},
    )
    if not sent_event or not access_event or not request_event:
        return {}

    email_sha256 = _hash(recipient_email)
    session_id = str(sent_payload.get("access_session_id") or access_payload.get("session_id") or "").strip()
    session_sha256 = _hash(session_id)
    policy_node_keys = sorted(
        {
            str(row.get("key") or "").strip()
            for row in preference_nodes
            if str(row.get("domain") or "").strip().lower() in {"office_routing", "google_workspace"}
            and str(row.get("key") or "").strip()
            in {"primary_work_google_workspace_email", "work_inbox_signal_policy"}
        }
    )
    evidence_packet = {
        "contract_name": "ea.google_workspace_auth_action_observations.v1",
        "principal_sha256": _hash(principal_id),
        "recipient_email_sha256": email_sha256,
        "access_session_id_sha256": session_sha256,
        "request_event_type": _event_type(request_event),
        "request_recorded_at": _event_timestamp(request_event),
        "access_event_type": _event_type(access_event),
        "access_issued_at": _event_timestamp(access_event),
        "sent_event_type": _event_type(sent_event),
        "sent_at": _event_timestamp(sent_event),
        "scope_bundle": "full_workspace",
        "provider": str(sent_payload.get("provider") or "").strip().lower(),
        "policy_node_keys": policy_node_keys,
        "raw_email_exposed": False,
        "raw_payload_exposed": False,
    }
    row = _row_from_redacted_hashes(
        source_kind="google_workspace_auth_action_live_observation",
        recorded_at=_event_timestamp(sent_event),
        evidence_sha256=_hash(_canonical_json(evidence_packet)),
        actor_sha256=_hash(principal_id),
        object_ref_sha256=_hash(f"google_workspace_auth:{email_sha256}:{session_sha256}"),
    )
    if row.get("accepted") is True:
        row.update(
            {
                "derived_from_contract": "ea.google_workspace_auth_action_observations.v1",
                "derived_event_types": [
                    _event_type(request_event),
                    "workspace_access_session_issued",
                    "google_connect_email_sent",
                ],
                "scope_bundle": "full_workspace",
                "provider": str(sent_payload.get("provider") or "").strip().lower(),
                "policy_node_keys": policy_node_keys,
                "raw_email_exposed": False,
                "raw_payload_exposed": False,
                "claim_boundary": "proves_google_workspace_auth_email_action_was_delivered_and_audited_only",
            }
        )
    return row


def _payload_item_ref(payload: dict[str, Any]) -> str:
    return str(payload.get("item_ref") or payload.get("commitment_ref") or payload.get("object_ref") or "").strip()


def _commitment_closure_row_from_bundle(bundle: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(bundle or {})
    principal_id = str(source.get("principal_id") or "").strip()
    if not principal_id:
        return {}
    observations = [dict(row) for row in list(source.get("observations") or []) if isinstance(row, dict)]
    commitments = [dict(row) for row in list(source.get("commitments") or []) if isinstance(row, dict)]
    for commitment in commitments:
        commitment_id = str(commitment.get("commitment_id") or "").strip()
        if not commitment_id:
            continue
        status = str(commitment.get("status") or "").strip().lower()
        if status not in {"completed", "closed", "done"}:
            continue
        item_ref = f"commitment:{commitment_id}"
        closed_event: dict[str, Any] = {}
        closed_payload: dict[str, Any] = {}
        for row in observations:
            payload = _event_payload(row)
            if _event_type(row) != "commitment_closed":
                continue
            if str(row.get("source_id") or "").strip() != commitment_id and _payload_item_ref(payload) != item_ref:
                continue
            action = str(payload.get("action") or "").strip().lower()
            if action and action not in {"close", "done", "complete"}:
                continue
            if not str(payload.get("actor") or "").strip():
                continue
            closed_event = row
            closed_payload = payload
            break
        if not closed_event:
            continue
        created_event = next(
            (
                row
                for row in observations
                if _event_type(row) == "commitment_created"
                and str(row.get("source_id") or "").strip() == commitment_id
            ),
            {},
        )
        receipt_event: dict[str, Any] = {}
        receipt_payload: dict[str, Any] = {}
        for row in observations:
            payload = _event_payload(row)
            if _event_type(row) != "commitment_closure_evidence_receipt_recorded":
                continue
            if str(payload.get("contract_name") or "").strip() != COMMITMENT_CLOSURE_RECEIPT_CONTRACT:
                continue
            if _payload_item_ref(payload) != item_ref:
                continue
            if payload.get("raw_private_context_exposed") is not False:
                continue
            evidence_event_types = [
                str(value or "").strip()
                for value in list(payload.get("evidence_event_types") or [])
                if str(value or "").strip()
            ]
            if not evidence_event_types:
                continue
            receipt_event = row
            receipt_payload = payload
            break
        if not receipt_event:
            continue
        source_json = dict(commitment.get("source_json") or {})
        source_ref = str(source_json.get("source_ref") or receipt_payload.get("source_ref") or commitment_id).strip()
        actor = str(closed_payload.get("actor") or "").strip()
        evidence_event_types = sorted(
            {
                str(value or "").strip()
                for value in list(receipt_payload.get("evidence_event_types") or [])
                if str(value or "").strip()
            }
        )
        evidence_packet = {
            "contract_name": "ea.commitment_closure_observations.v1",
            "principal_sha256": _hash(principal_id),
            "commitment_ref_sha256": _hash(item_ref),
            "source_ref_sha256": _hash(source_ref),
            "created_event_type": _event_type(created_event),
            "created_at": _event_timestamp(created_event),
            "closed_event_type": _event_type(closed_event),
            "closed_at": _event_timestamp(closed_event) or str(commitment.get("updated_at") or "").strip(),
            "receipt_event_type": _event_type(receipt_event),
            "receipt_recorded_at": _event_timestamp(receipt_event),
            "status": status,
            "source_type": str(source_json.get("source_type") or "").strip(),
            "resolution_code": str(source_json.get("resolution_code") or closed_payload.get("reason_code") or "").strip(),
            "evidence_event_types": evidence_event_types,
            "raw_commitment_text_exposed": False,
            "raw_actor_exposed": False,
            "raw_private_context_exposed": False,
        }
        row = _row_from_redacted_hashes(
            source_kind="commitment_closure_live_observation",
            recorded_at=evidence_packet["closed_at"],
            evidence_sha256=_hash(_canonical_json(evidence_packet)),
            actor_sha256=_hash(actor),
            object_ref_sha256=_hash(f"commitment_closure:{_hash(item_ref)}:{_hash(source_ref)}"),
        )
        if row.get("accepted") is True:
            row.update(
                {
                    "derived_from_contract": "ea.commitment_closure_observations.v1",
                    "derived_event_types": [
                        value
                        for value in (
                            _event_type(created_event),
                            _event_type(closed_event),
                            _event_type(receipt_event),
                        )
                        if value
                    ],
                    "evidence_event_types": evidence_event_types,
                    "raw_commitment_text_exposed": False,
                    "raw_private_context_exposed": False,
                    "claim_boundary": "proves_one_real_internal_commitment_was_closed_with_redacted_evidence_receipt_only",
                }
            )
        return row
    return {}


def _receipt_sha256(payload: dict[str, Any]) -> str:
    return _hash(_canonical_json(payload)) if payload else ""


def _all_false(flags: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(flags.get(key) is False for key in keys)


def _provider_runtime_recovery_row_from_bundle(bundle: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(bundle or {})
    before_operator = dict(source.get("before_operator_status") or {})
    after_operator = dict(source.get("after_operator_status") or {})
    before_gold = dict(source.get("before_gold_acceptance") or {})
    after_gold = dict(source.get("after_gold_acceptance") or {})
    if before_operator.get("contract_name") != "ea.proactive_ooda_operator_status.v1":
        return {}
    if after_operator.get("contract_name") != "ea.proactive_ooda_operator_status.v1":
        return {}
    if before_gold.get("contract_name") != "ea.proactive_ooda_gold_acceptance.v1":
        return {}
    if after_gold.get("contract_name") != "ea.proactive_ooda_gold_acceptance.v1":
        return {}

    before_suppressed = dict(before_operator.get("suppressed_projection") or {})
    after_suppressed = dict(after_operator.get("suppressed_projection") or {})
    before_blocked = (
        str(before_operator.get("status") or "").strip() == "ready_with_recovery_action"
        and str(before_operator.get("operator_action_state") or "").strip() == "recovery_required"
        and before_suppressed.get("requires_recovery") is True
    ) or (
        str(before_gold.get("status") or "").strip() == "blocked_operator_runtime_posture"
        and str(before_gold.get("next_action") or "").strip() == "repair_proactive_safe_work_audit"
    )
    after_recovered = (
        str(after_operator.get("status") or "").strip() in {"ready_with_live_receipt", "ready_local_runtime"}
        and str(after_operator.get("operator_action_state") or "").strip() == "clear"
        and after_suppressed.get("requires_recovery") is False
        and str(after_gold.get("status") or "").strip() == "pass"
        and after_gold.get("gold_claim_allowed") is True
        and not list(after_gold.get("remaining_external_proofs") or [])
    )
    if not before_blocked or not after_recovered:
        return {}

    before_privacy = dict(before_suppressed.get("privacy") or {})
    after_privacy = dict(after_suppressed.get("privacy") or {})
    privacy_keys = (
        "raw_candidate_exposed",
        "raw_draft_text_exposed",
        "raw_packet_text_exposed",
        "raw_private_link_exposed",
    )
    if before_privacy and not _all_false(before_privacy, privacy_keys):
        return {}
    if after_privacy and not _all_false(after_privacy, privacy_keys):
        return {}

    before_operator_sha = _receipt_sha256(before_operator)
    after_operator_sha = _receipt_sha256(after_operator)
    before_gold_sha = _receipt_sha256(before_gold)
    after_gold_sha = _receipt_sha256(after_gold)
    if not all((before_operator_sha, after_operator_sha, before_gold_sha, after_gold_sha)):
        return {}
    evidence_packet = {
        "contract_name": "ea.provider_runtime_recovery_receipt_pair.v1",
        "before_operator_status": str(before_operator.get("status") or "").strip(),
        "before_operator_action_state": str(before_operator.get("operator_action_state") or "").strip(),
        "before_operator_next_action": str(before_operator.get("next_action") or "").strip(),
        "before_gold_status": str(before_gold.get("status") or "").strip(),
        "before_gold_next_action": str(before_gold.get("next_action") or "").strip(),
        "after_operator_status": str(after_operator.get("status") or "").strip(),
        "after_operator_action_state": str(after_operator.get("operator_action_state") or "").strip(),
        "after_operator_next_action": str(after_operator.get("next_action") or "").strip(),
        "after_gold_status": str(after_gold.get("status") or "").strip(),
        "after_gold_next_action": str(after_gold.get("next_action") or "").strip(),
        "before_operator_receipt_sha256": before_operator_sha,
        "after_operator_receipt_sha256": after_operator_sha,
        "before_gold_receipt_sha256": before_gold_sha,
        "after_gold_receipt_sha256": after_gold_sha,
        "recovery_reason": "suppressed_safe_work_projection_reclassified_as_non_material",
        "claim_scope": "proactive_runtime_operator_posture_recovery",
        "raw_private_context_exposed": False,
    }
    row = _row_from_redacted_hashes(
        source_kind="proactive_runtime_recovery_receipt_pair",
        recorded_at=str(after_operator.get("generated_at") or after_gold.get("generated_at") or "").strip(),
        evidence_sha256=_hash(_canonical_json(evidence_packet)),
        actor_sha256=_hash("codex_live_ops:proactive_runtime_recovery"),
        object_ref_sha256=_hash(f"provider_runtime_recovery:{before_operator_sha}:{after_operator_sha}"),
    )
    if row.get("accepted") is True:
        row.update(
            {
                "derived_from_contract": "ea.provider_runtime_recovery_receipt_pair.v1",
                "before_status": evidence_packet["before_operator_status"],
                "after_status": evidence_packet["after_operator_status"],
                "before_gold_status": evidence_packet["before_gold_status"],
                "after_gold_status": evidence_packet["after_gold_status"],
                "recovery_reason": evidence_packet["recovery_reason"],
                "raw_private_context_exposed": False,
                "claim_boundary": "proves_recovery_of_one_proactive_runtime_operator_posture_blocker_only",
            }
        )
    return row


def _load_provider_runtime_recovery_bundle(
    *,
    before_operator_status_path: str | Path,
    after_operator_status_path: str | Path,
    before_gold_acceptance_path: str | Path,
    after_gold_acceptance_path: str | Path,
) -> dict[str, Any]:
    paths = {
        "before_operator_status": Path(before_operator_status_path),
        "after_operator_status": Path(after_operator_status_path),
        "before_gold_acceptance": Path(before_gold_acceptance_path),
        "after_gold_acceptance": Path(after_gold_acceptance_path),
    }
    bundle: dict[str, Any] = {"status": "loaded"}
    for key, path in paths.items():
        if not str(path).strip() or not path.is_file():
            return {"status": "blocked", "reason": f"{key}_missing"}
        try:
            bundle[key] = _load(path)
        except Exception as exc:
            return {"status": "blocked", "reason": f"{key}_load_failed:{exc.__class__.__name__}"}
    return bundle


def _live_commitment_closure_bundle(
    *,
    database_url: str,
    principal_id: str,
    since_hours: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return {"status": "blocked", "reason": "database_url_missing"}
    try:
        import psycopg
    except Exception:
        return {"status": "blocked", "reason": "psycopg_missing"}
    principal = str(principal_id or "").strip()
    if not principal:
        return {"status": "blocked", "reason": "principal_missing"}
    bounded_timeout = max(0.5, min(15.0, float(timeout_seconds or 5.0)))
    bounded_since_hours = max(1, min(24 * 30, int(since_hours or 24)))
    statement_timeout_ms = int(bounded_timeout * 1000)
    try:
        with psycopg.connect(url, connect_timeout=max(1, int(bounded_timeout))) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"set statement_timeout = {statement_timeout_ms}")
                cursor.execute(
                    """
                    select commitment_id, title, status, source_json, created_at::text, updated_at::text
                    from commitments
                    where principal_id = %s
                      and status in ('completed', 'closed', 'done')
                      and updated_at >= now() - make_interval(hours => %s)
                    order by updated_at desc
                    limit 50
                    """,
                    (principal, bounded_since_hours),
                )
                commitments = [
                    {
                        "commitment_id": row[0],
                        "title": row[1],
                        "status": row[2],
                        "source_json": row[3] or {},
                        "created_at": row[4],
                        "updated_at": row[5],
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    select event_type, created_at::text, source_id, payload_json
                    from observation_events
                    where principal_id = %s
                      and event_type in (
                        'commitment_created',
                        'commitment_closed',
                        'commitment_closure_evidence_receipt_recorded'
                      )
                      and created_at >= now() - make_interval(hours => %s)
                    order by created_at desc
                    limit 200
                    """,
                    (principal, bounded_since_hours),
                )
                observations = [
                    {
                        "event_type": row[0],
                        "created_at": row[1],
                        "source_id": row[2],
                        "payload": row[3] or {},
                    }
                    for row in cursor.fetchall()
                ]
    except Exception as exc:
        return {"status": "blocked", "reason": f"database_query_failed:{exc.__class__.__name__}"}
    return {
        "status": "loaded",
        "principal_id": principal,
        "commitments": commitments,
        "observations": observations,
    }


def _live_google_workspace_auth_action_bundle(
    *,
    database_url: str,
    principal_id: str,
    recipient_email: str,
    since_hours: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return {"status": "blocked", "reason": "database_url_missing"}
    try:
        import psycopg
    except Exception:
        return {"status": "blocked", "reason": "psycopg_missing"}

    principal = str(principal_id or "").strip()
    recipient = _email_text(recipient_email)
    if not principal or not recipient:
        return {"status": "blocked", "reason": "principal_or_recipient_missing"}
    bounded_timeout = max(0.5, min(15.0, float(timeout_seconds or 5.0)))
    bounded_since_hours = max(1, min(24 * 14, int(since_hours or 24)))
    statement_timeout_ms = int(bounded_timeout * 1000)
    try:
        with psycopg.connect(url, connect_timeout=max(1, int(bounded_timeout))) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"set statement_timeout = {statement_timeout_ms}")
                cursor.execute(
                    """
                    select event_type, created_at::text, payload_json
                    from observation_events
                    where principal_id = %s
                      and event_type in ('google_connect_email_sent', 'workspace_access_session_issued')
                      and created_at >= now() - make_interval(hours => %s)
                    order by created_at desc
                    limit 100
                    """,
                    (principal, bounded_since_hours),
                )
                observations = [
                    {"event_type": row[0], "created_at": row[1], "payload": row[2] or {}}
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    select event_type, recorded_at::text, domain, object_type, object_id, source_ref,
                           interpreted_signal_json
                    from preference_evidence_events
                    where principal_id = %s
                      and person_id = 'self'
                      and event_type in (
                        'explicit_work_google_workspace_intake_requested',
                        'explicit_work_inbox_setup_request'
                      )
                      and recorded_at >= now() - make_interval(hours => %s)
                    order by recorded_at desc
                    limit 100
                    """,
                    (principal, bounded_since_hours),
                )
                preference_evidence_events = [
                    {
                        "event_type": row[0],
                        "recorded_at": row[1],
                        "domain": row[2],
                        "object_type": row[3],
                        "object_id": row[4],
                        "source_ref": row[5],
                        "interpreted_signal_json": row[6] or {},
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    select domain, category, key, value_json, updated_at::text
                    from preference_nodes
                    where principal_id = %s
                      and person_id = 'self'
                      and domain in ('office_routing', 'google_workspace')
                    order by updated_at desc
                    limit 100
                    """,
                    (principal,),
                )
                preference_nodes = [
                    {
                        "domain": row[0],
                        "category": row[1],
                        "key": row[2],
                        "value_json": row[3] or {},
                        "updated_at": row[4],
                    }
                    for row in cursor.fetchall()
                ]
    except Exception as exc:
        return {"status": "blocked", "reason": f"database_query_failed:{exc.__class__.__name__}"}
    return {
        "status": "loaded",
        "principal_id": principal,
        "recipient_email": recipient,
        "observations": observations,
        "preference_evidence_events": preference_evidence_events,
        "preference_nodes": preference_nodes,
    }


def _proactive_ooda_gold_decision_row(path: Path | None = None) -> dict[str, Any]:
    receipt_path = path or DEFAULT_PROACTIVE_OODA_GOLD_RECEIPT
    if not receipt_path.is_file():
        return {}
    try:
        receipt = _load(receipt_path)
    except Exception:
        return {}
    if receipt.get("contract_name") != "ea.proactive_ooda_gold_acceptance.v1":
        return {}
    if str(receipt.get("status") or "").strip() != "pass" or receipt.get("gold_claim_allowed") is not True:
        return {}
    approval = dict(dict(receipt.get("proofs") or {}).get("approval_outcome") or {})
    if approval.get("accepted") is not True or approval.get("approval_outcome_recorded") is not True:
        return {}
    evidence_sha256 = str(approval.get("evidence_sha256") or "").strip()
    actor_sha256 = str(approval.get("actor_sha256") or "").strip()
    packet_ref_sha256 = str(approval.get("packet_ref_sha256") or "").strip()
    staged_artifact_sha256 = str(approval.get("staged_artifact_sha256") or "").strip()
    object_ref_sha256 = _hash(f"proactive_ooda:{packet_ref_sha256}:{staged_artifact_sha256}")
    row = _row_from_redacted_hashes(
        source_kind="proactive_ooda_gold_acceptance",
        recorded_at=str(approval.get("recorded_at") or receipt.get("generated_at") or "").strip(),
        evidence_sha256=evidence_sha256,
        actor_sha256=actor_sha256,
        object_ref_sha256=object_ref_sha256,
    )
    if row.get("accepted") is True:
        row["derived_from_contract"] = "ea.proactive_ooda_gold_acceptance.v1"
        row["derived_from_receipt_sha256"] = _hash(receipt_path.read_text(encoding="utf-8"))
        row["claim_boundary"] = "proves_a_real_proactive_packet_decision_only"
    return row


def _acceptance_capture_surface() -> dict[str, Any]:
    return {
        "method": ACCEPTANCE_CAPTURE_METHOD,
        "path": ACCEPTANCE_CAPTURE_PATH,
        "form_method": ACCEPTANCE_CAPTURE_FORM_METHOD,
        "form_path": ACCEPTANCE_CAPTURE_PATH,
        "admin_only": True,
        "operator_context_required": True,
        "required_form_fields": ACCEPTANCE_CAPTURE_FORM_FIELDS,
        "prefill_query_fields": ["proof_key", "return_to"],
        "server_actor_source": "authenticated_operator_context",
        "raw_input_not_persisted": True,
        "stored_evidence_shape": "sha256_only",
        "privacy_contract": {
            "raw_acceptance_text_persisted": False,
            "raw_actor_identity_persisted": False,
            "raw_object_reference_persisted": False,
            "credential_values_persisted": False,
        },
        "claim_boundary": "capture_surface_collects_redacted_acceptance_evidence_only_not_goal_completion",
    }


def _acceptance_capture_form_href(proof_key: str, *, return_to: str = "/admin/goals") -> str:
    query = {"return_to": return_to}
    if proof_key:
        query["proof_key"] = proof_key
    return f"{ACCEPTANCE_CAPTURE_PATH}?{urllib.parse.urlencode(query)}"


def _acceptance_capture_requirement(key: str, row: dict[str, Any]) -> dict[str, Any]:
    accepted = dict(row or {}).get("accepted") is True
    user_action_required = not accepted
    return {
        "key": key,
        "label": REMAINING_PROOF_LABELS[key],
        "status": "accepted_redacted" if accepted else "pending_real_world_evidence",
        "accepted": accepted,
        "capture_method": ACCEPTANCE_CAPTURE_METHOD,
        "capture_path": ACCEPTANCE_CAPTURE_PATH,
        "form_method": ACCEPTANCE_CAPTURE_FORM_METHOD,
        "form_href": _acceptance_capture_form_href(key),
        "proof_key": key,
        "required_form_fields": ACCEPTANCE_CAPTURE_FORM_FIELDS,
        "server_actor_source": "authenticated_operator_context",
        "raw_input_not_persisted": True,
        "stored_evidence_shape": "sha256_only",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
        "user_action_required": user_action_required,
        "delivery_policy": "action_required_only" if user_action_required else "queue_only",
        "telegram_push_allowed": user_action_required,
        "interruption_budget": "action_required" if user_action_required else "none",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "next_action": (
            f"review_redacted_acceptance_evidence:{key}"
            if accepted
            else f"record_redacted_acceptance_evidence:{key}"
        ),
        "next_action_form_href": _acceptance_capture_form_href(key),
        "next_action_form_label": ACCEPTANCE_CAPTURE_LABEL,
        "next_action_form_method": ACCEPTANCE_CAPTURE_FORM_METHOD.lower(),
        "claim_boundary": "does_not_prove_good_executive_assistant_until_all_required_acceptance_keys_are_accepted",
    }


def acceptance_capture_requirements(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [_acceptance_capture_requirement(key, dict(rows.get(key) or {})) for key in REQUIRED_ACCEPTANCE_KEYS]


def _existing_rows(receipt_path: Path, preserve_existing: bool) -> dict[str, dict[str, Any]]:
    if not preserve_existing or not receipt_path.is_file():
        return {}
    try:
        existing = _load(receipt_path)
    except Exception:
        return {}
    rows = existing.get("acceptance_keys")
    return dict(rows) if isinstance(rows, dict) else {}


def _default_proactive_ooda_receipt_for_target(target: Path) -> Path | None:
    try:
        if target.resolve() == DEFAULT_RECEIPT.resolve():
            return DEFAULT_PROACTIVE_OODA_GOLD_RECEIPT
    except Exception:
        return None
    return None


def materialize_executive_assistant_acceptance_evidence(
    *,
    receipt_path: str | Path,
    input_payload: dict[str, Any] | None = None,
    generated_at: str = "",
    preserve_existing: bool = True,
    proactive_ooda_gold_receipt_path: str | Path | None = None,
    google_workspace_auth_action_bundle: dict[str, Any] | None = None,
    commitment_closure_bundle: dict[str, Any] | None = None,
    provider_runtime_recovery_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(receipt_path)
    rows: dict[str, dict[str, Any]] = {key: _empty_row() for key in REQUIRED_ACCEPTANCE_KEYS}
    for key, row in _existing_rows(target, preserve_existing).items():
        if key in rows and dict(row).get("accepted") is True:
            rows[key] = _normalized_existing_row(dict(row))
    for proof in list((input_payload or {}).get("proofs") or []):
        if not isinstance(proof, dict):
            continue
        key = str(proof.get("key") or "")
        if key in rows:
            rows[key] = _row_from_proof(proof)
    if rows["real_decision_cleared"].get("accepted") is not True:
        proactive_path = (
            Path(proactive_ooda_gold_receipt_path)
            if proactive_ooda_gold_receipt_path
            else _default_proactive_ooda_receipt_for_target(target)
        )
        if proactive_path is not None:
            proactive_decision_row = _proactive_ooda_gold_decision_row(proactive_path)
            if proactive_decision_row.get("accepted") is True:
                rows["real_decision_cleared"] = proactive_decision_row
    if rows["real_approved_action_audited"].get("accepted") is not True:
        approved_action_row = _google_workspace_auth_action_row_from_bundle(google_workspace_auth_action_bundle)
        if approved_action_row.get("accepted") is True:
            rows["real_approved_action_audited"] = approved_action_row
    if rows["real_commitment_recovered_or_closed"].get("accepted") is not True:
        commitment_closure_row = _commitment_closure_row_from_bundle(commitment_closure_bundle)
        if commitment_closure_row.get("accepted") is True:
            rows["real_commitment_recovered_or_closed"] = commitment_closure_row
    if rows["real_provider_failure_recovered"].get("accepted") is not True:
        provider_recovery_row = _provider_runtime_recovery_row_from_bundle(provider_runtime_recovery_bundle)
        if provider_recovery_row.get("accepted") is True:
            rows["real_provider_failure_recovered"] = provider_recovery_row
    accepted_keys = [key for key in REQUIRED_ACCEPTANCE_KEYS if rows[key].get("accepted") is True]
    blocked_keys = [key for key in REQUIRED_ACCEPTANCE_KEYS if key not in accepted_keys]
    status = (
        "ready_real_world_acceptance_evidence"
        if not blocked_keys
        else "partial_real_world_acceptance_evidence"
        if accepted_keys
        else "blocked_missing_real_world_acceptance_evidence"
    )
    next_proof_key = blocked_keys[0] if blocked_keys else ""
    next_action = "collect_redacted_real_world_acceptance_evidence" if blocked_keys else "review_good_executive_assistant_claim"
    receipt = {
        "contract_name": "ea.executive_assistant_acceptance_evidence.v1",
        "status": status,
        "generated_at": generated_at or _now(),
        "generated_by": "ea/scripts/materialize_executive_assistant_acceptance_evidence.py",
        **_source_state_fields(),
        "goal_completion_claim_allowed": False,
        "public_or_premium_claim_allowed": False,
        "acceptance_keys": rows,
        "acceptance_capture_surface": _acceptance_capture_surface(),
        "acceptance_capture_requirements": acceptance_capture_requirements(rows),
        "accepted_keys": accepted_keys,
        "blocked_keys": blocked_keys,
        "real_daily_use_verified": not blocked_keys,
        "real_principal_acceptance_verified": rows["real_daily_morning_brief_accepted"].get("accepted") is True,
        "real_operator_acceptance_verified": any(rows[key].get("accepted") is True for key in REQUIRED_ACCEPTANCE_KEYS if key != "real_daily_morning_brief_accepted"),
        "real_provider_recovery_verified": rows["real_provider_failure_recovered"].get("accepted") is True,
        "remaining_external_proofs": [REMAINING_PROOF_LABELS[key] for key in blocked_keys],
        "privacy": {
            "credential_values_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_private_context_exposed": False,
        },
        "source_input": {
            "provided": input_payload is not None,
            "google_workspace_auth_action_bundle_provided": google_workspace_auth_action_bundle is not None,
            "commitment_closure_bundle_provided": commitment_closure_bundle is not None,
            "provider_runtime_recovery_bundle_provided": provider_runtime_recovery_bundle is not None,
        },
        "rejected_input_count": 0,
        "next_action": next_action,
        "next_action_href": ACCEPTANCE_CAPTURE_PATH if blocked_keys else "",
        "next_action_label": ACCEPTANCE_CAPTURE_LABEL if blocked_keys else "",
        "next_action_method": ACCEPTANCE_CAPTURE_METHOD.lower() if blocked_keys else "",
        "next_action_form_href": _acceptance_capture_form_href(next_proof_key) if blocked_keys else "",
        "next_action_form_label": ACCEPTANCE_CAPTURE_LABEL if blocked_keys else "",
        "next_action_form_method": ACCEPTANCE_CAPTURE_FORM_METHOD.lower() if blocked_keys else "",
        "next_action_proof_key": next_proof_key,
        "operator_delivery_policy": {
            "action_required_only": True,
            "telegram_push_allowed_for_next_action": bool(blocked_keys),
            "next_action_requires_user": bool(blocked_keys),
            "next_action_delivery_policy": "action_required_only" if blocked_keys else "queue_only",
            "non_action_progress_push_allowed": False,
            "quiet_hours_respected": True,
            "irreversible_actions_consent_gated": True,
        },
    }
    _write(target, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize redacted Executive Assistant acceptance evidence.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--input")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--proactive-ooda-gold-receipt")
    parser.add_argument("--derive-google-workspace-auth-action", action="store_true")
    parser.add_argument("--google-auth-principal-id", default="")
    parser.add_argument("--google-auth-recipient-email", default="")
    parser.add_argument("--google-auth-since-hours", type=int, default=24)
    parser.add_argument("--derive-live-commitment-closure", action="store_true")
    parser.add_argument("--commitment-closure-principal-id", default="")
    parser.add_argument("--commitment-closure-since-hours", type=int, default=72)
    parser.add_argument("--derive-provider-runtime-recovery", action="store_true")
    parser.add_argument("--provider-recovery-before-operator-status", default="")
    parser.add_argument("--provider-recovery-after-operator-status", default="")
    parser.add_argument("--provider-recovery-before-gold-acceptance", default="")
    parser.add_argument("--provider-recovery-after-gold-acceptance", default="")
    parser.add_argument("--live-proof-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    input_payload = _load(args.input) if args.input else None
    google_workspace_auth_action_bundle = None
    commitment_closure_bundle = None
    provider_runtime_recovery_bundle = None
    if args.derive_google_workspace_auth_action:
        if not args.google_auth_principal_id or not args.google_auth_recipient_email:
            parser.error("--google-auth-principal-id and --google-auth-recipient-email are required")
        google_workspace_auth_action_bundle = _live_google_workspace_auth_action_bundle(
            database_url=args.database_url,
            principal_id=args.google_auth_principal_id,
            recipient_email=args.google_auth_recipient_email,
            since_hours=args.google_auth_since_hours,
            timeout_seconds=args.live_proof_timeout_seconds,
        )
    if args.derive_live_commitment_closure:
        if not args.commitment_closure_principal_id:
            parser.error("--commitment-closure-principal-id is required")
        commitment_closure_bundle = _live_commitment_closure_bundle(
            database_url=args.database_url,
            principal_id=args.commitment_closure_principal_id,
            since_hours=args.commitment_closure_since_hours,
            timeout_seconds=args.live_proof_timeout_seconds,
        )
    if args.derive_provider_runtime_recovery:
        required_paths = (
            args.provider_recovery_before_operator_status,
            args.provider_recovery_after_operator_status,
            args.provider_recovery_before_gold_acceptance,
            args.provider_recovery_after_gold_acceptance,
        )
        if not all(str(value or "").strip() for value in required_paths):
            parser.error("--provider-recovery-before/after operator/gold paths are required")
        provider_runtime_recovery_bundle = _load_provider_runtime_recovery_bundle(
            before_operator_status_path=args.provider_recovery_before_operator_status,
            after_operator_status_path=args.provider_recovery_after_operator_status,
            before_gold_acceptance_path=args.provider_recovery_before_gold_acceptance,
            after_gold_acceptance_path=args.provider_recovery_after_gold_acceptance,
        )
    receipt = materialize_executive_assistant_acceptance_evidence(
        receipt_path=args.receipt,
        input_payload=input_payload,
        generated_at=args.generated_at,
        preserve_existing=not args.reset,
        proactive_ooda_gold_receipt_path=args.proactive_ooda_gold_receipt,
        google_workspace_auth_action_bundle=google_workspace_auth_action_bundle,
        commitment_closure_bundle=commitment_closure_bundle,
        provider_runtime_recovery_bundle=provider_runtime_recovery_bundle,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
