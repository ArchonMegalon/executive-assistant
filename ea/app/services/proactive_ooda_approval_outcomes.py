from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


PROACTIVE_OODA_APPROVAL_OUTCOME_SCHEMA = "ea.proactive_ooda_approval_outcome.v1"
PROACTIVE_OODA_APPROVAL_OUTCOME_EVENT_TYPE = "proactive_ooda.approval_outcome"
PROACTIVE_OODA_APPROVAL_OUTCOME_FILENAME = "proactive_ooda_latest_approval_outcome.generated.json"


def default_proactive_ooda_artifact_dir(*, root: Path, preferred: Path | None = None) -> Path:
    candidates: list[Path] = []
    if preferred is not None:
        candidates.append(preferred)
    candidates.extend(
        [
            Path("/data/provider-ledger"),
            Path("/tmp/ea-proactive-ooda"),
        ]
    )
    for candidate in candidates:
        if _writable_path(candidate):
            return candidate
    return preferred or (root / "state")


def default_proactive_ooda_approval_outcome_path(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
) -> Path:
    receipt = _path_from_value(root, receipt_path)
    if receipt is not None:
        return default_proactive_ooda_artifact_dir(root=root, preferred=receipt.parent) / PROACTIVE_OODA_APPROVAL_OUTCOME_FILENAME
    state = _path_from_value(root, state_path)
    if state is not None:
        return default_proactive_ooda_artifact_dir(root=root, preferred=state.parent) / PROACTIVE_OODA_APPROVAL_OUTCOME_FILENAME
    return default_proactive_ooda_artifact_dir(root=root, preferred=root / "state") / PROACTIVE_OODA_APPROVAL_OUTCOME_FILENAME


def record_proactive_ooda_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    packet_ref: str,
    staged_artifact_ref: str,
    source_kind: str = "unknown",
    recorded_at: str | None = None,
    output_path: str | Path,
    database_url: str | None = None,
) -> dict[str, Any]:
    payload = build_proactive_ooda_approval_outcome_payload(
        principal_id=principal_id,
        outcome=outcome,
        evidence=evidence,
        actor=actor,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        source_kind=source_kind,
        recorded_at=recorded_at,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    observation_id = persist_proactive_ooda_approval_outcome_observation(
        principal_id=principal_id,
        payload=payload,
        database_url=database_url,
    )
    if observation_id:
        payload["observation_id"] = observation_id
    return payload


def build_proactive_ooda_approval_outcome_payload(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    packet_ref: str,
    staged_artifact_ref: str,
    source_kind: str = "unknown",
    recorded_at: str | None = None,
) -> dict[str, Any]:
    recorded = _utc_now() if not str(recorded_at or "").strip() else str(recorded_at).strip()
    normalized_outcome = _normalize_outcome(outcome)
    accepted = normalized_outcome in {"approved", "accepted"}
    evidence_sha = _hash_value(evidence)
    actor_sha = _hash_value(actor)
    packet_sha = _hash_value(packet_ref)
    artifact_sha = _hash_value(staged_artifact_ref)
    outcome_id = _outcome_id(
        principal_id=principal_id,
        outcome=normalized_outcome,
        recorded_at=recorded,
        evidence_sha=evidence_sha,
        actor_sha=actor_sha,
        packet_sha=packet_sha,
        artifact_sha=artifact_sha,
        source_kind=source_kind,
    )
    return {
        "schema": PROACTIVE_OODA_APPROVAL_OUTCOME_SCHEMA,
        "contract_name": PROACTIVE_OODA_APPROVAL_OUTCOME_SCHEMA,
        "event_type": PROACTIVE_OODA_APPROVAL_OUTCOME_EVENT_TYPE,
        "outcome_id": outcome_id,
        "principal_id_hash": _hash_value(principal_id),
        "approval_outcome_recorded": True,
        "accepted": accepted,
        "outcome": normalized_outcome,
        "status": "accepted_redacted" if accepted else "recorded_not_accepted",
        "source_kind": str(source_kind or "unknown").strip() or "unknown",
        "recorded_at": recorded,
        "evidence_sha256": evidence_sha,
        "actor_sha256": actor_sha,
        "packet_ref_sha256": packet_sha,
        "staged_artifact_sha256": artifact_sha,
        "packet_ref_kind": _artifact_kind(packet_ref),
        "staged_artifact_kind": _artifact_kind(staged_artifact_ref),
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
        "raw_staged_artifact_exposed": False,
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_evidence_exposed": False,
            "raw_actor_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_exposed": False,
        },
    }


def persist_proactive_ooda_approval_outcome_observation(
    *,
    principal_id: str,
    payload: Mapping[str, Any],
    database_url: str | None = None,
) -> str:
    url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return ""
    try:
        import psycopg
    except Exception:
        return ""
    record = build_proactive_ooda_approval_outcome_observation(
        principal_id=principal_id,
        payload=payload,
    )
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into observation_events (
                        observation_id,
                        principal_id,
                        channel,
                        event_type,
                        payload_json,
                        created_at,
                        source_id,
                        external_id,
                        dedupe_key,
                        auth_context_json,
                        raw_payload_uri
                    )
                    values (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s)
                    on conflict (observation_id) do nothing
                    """,
                    (
                        record["observation_id"],
                        record["principal_id"],
                        record["channel"],
                        record["event_type"],
                        record["payload_json"],
                        record["created_at"],
                        record["source_id"],
                        record["external_id"],
                        record["dedupe_key"],
                        record["auth_context_json"],
                        record["raw_payload_uri"],
                    ),
                )
        return str(record["observation_id"])
    except Exception:
        return ""


def build_proactive_ooda_approval_outcome_observation(
    *,
    principal_id: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    dedupe_key = _observation_dedupe_key(payload)
    return {
        "observation_id": f"proactive-ooda-approval-outcome-{uuid4().hex}",
        "principal_id": principal_id,
        "channel": "system",
        "event_type": PROACTIVE_OODA_APPROVAL_OUTCOME_EVENT_TYPE,
        "payload_json": json.dumps(dict(payload), sort_keys=True),
        "created_at": str(payload.get("recorded_at") or _utc_now()).strip(),
        "source_id": "ea-proactive-ooda",
        "external_id": str(payload.get("outcome_id") or dedupe_key).strip(),
        "dedupe_key": dedupe_key,
        "auth_context_json": "{}",
        "raw_payload_uri": "",
    }


def _normalize_outcome(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"approve", "approved", "accept", "accepted"}:
        return "approved"
    if normalized in {"reject", "rejected", "deny", "denied", "decline", "declined"}:
        return "rejected"
    if normalized in {"defer", "deferred", "later"}:
        return "deferred"
    if normalized in {"dismiss", "dismissed"}:
        return "dismissed"
    return normalized or "missing"


def _artifact_kind(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("stage_packet:"):
        return "stage_packet"
    if normalized.startswith("safe_work_result:"):
        return "safe_work_result"
    return ""


def _outcome_id(
    *,
    principal_id: str,
    outcome: str,
    recorded_at: str,
    evidence_sha: str,
    actor_sha: str,
    packet_sha: str,
    artifact_sha: str,
    source_kind: str,
) -> str:
    material = "\n".join(
        (
            _hash_value(principal_id),
            str(outcome or ""),
            str(recorded_at or ""),
            str(evidence_sha or ""),
            str(actor_sha or ""),
            str(packet_sha or ""),
            str(artifact_sha or ""),
            str(source_kind or ""),
        )
    )
    return f"proactive-ooda-approval-{_hash_value(material)[:24]}"


def _observation_dedupe_key(payload: Mapping[str, Any]) -> str:
    material = "\n".join(
        (
            str(payload.get("outcome_id") or "").strip(),
            str(payload.get("outcome") or "").strip(),
            str(payload.get("recorded_at") or "").strip(),
            str(payload.get("evidence_sha256") or "").strip(),
            str(payload.get("actor_sha256") or "").strip(),
        )
    )
    return f"proactive-ooda-approval-outcome:{_hash_value(material)}"


def _path_from_value(root: Path, value: str | Path) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    path = Path(normalized)
    return path if path.is_absolute() else root / path


def _writable_path(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return os.access(probe, os.W_OK)
    except Exception:
        return False


def _hash_value(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
