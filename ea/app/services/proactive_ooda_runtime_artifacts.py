from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from app.services.proactive_ooda_approval_outcomes import default_proactive_ooda_approval_outcome_path
from app.services.proactive_ooda_safe_work import default_safe_work_result_dir
from app.services.proactive_ooda_stage_packets import default_stage_packet_dir


RUN_RECEIPT_FILENAME = "proactive_ooda_latest_run.generated.json"
RUN_RECEIPT_DIRNAME = "proactive_ooda_run_receipts"
LEGACY_RUN_RECEIPT_FILENAMES = (
    "proactive_ooda_live_sent_receipt.json",
    "proactive_ooda_live_proof_receipt.json",
    "proactive_ooda_dry_receipt.json",
)
STAGE_PACKET_SCHEMA = "proactive_ooda.stage_packet.v1"
SAFE_WORK_RESULT_SCHEMA = "proactive_ooda.safe_work_result.v1"
_APPROVAL_CALLBACK_DECISION_STATUSES = {"approved", "rejected", "deferred", "dismissed"}
_APPROVAL_CALLBACK_TERMINAL_STATUSES = {*_APPROVAL_CALLBACK_DECISION_STATUSES, "expired", "superseded"}


def default_run_receipt_path(*, root: Path, state_path: str | Path) -> Path:
    path = Path(state_path)
    if not path.is_absolute():
        path = root / path
    return path.parent / RUN_RECEIPT_FILENAME


def default_run_receipt_dir(*, root: Path, state_path: str | Path, receipt_path: str | Path = "") -> Path:
    resolved_receipt_path = _path_from_value(
        root,
        receipt_path,
        default=default_run_receipt_path(root=root, state_path=state_path),
    )
    assert resolved_receipt_path is not None
    return resolved_receipt_path.parent / RUN_RECEIPT_DIRNAME


def resolve_runtime_artifact_paths(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
) -> dict[str, Path]:
    resolved_stage_dir = _path_from_value(
        root,
        stage_packet_dir,
        default=default_stage_packet_dir(root=root, state_path=state_path),
    )
    resolved_safe_dir = _path_from_value(
        root,
        safe_work_result_dir,
        default=default_safe_work_result_dir(resolved_stage_dir),
    )
    resolved_receipt_path = _path_from_value(
        root,
        receipt_path,
        default=default_run_receipt_path(root=root, state_path=state_path),
    )
    resolved_run_receipt_dir = default_run_receipt_dir(
        root=root,
        state_path=state_path,
        receipt_path=resolved_receipt_path,
    )
    resolved_approval_outcome_path = default_proactive_ooda_approval_outcome_path(
        root=root,
        state_path=state_path,
        receipt_path=resolved_receipt_path,
    )
    resolved_approval_callback_dir = resolved_approval_outcome_path.parent / "proactive_ooda_approval_callbacks"
    return {
        "run_receipt_path": resolved_receipt_path,
        "run_receipt_dir": resolved_run_receipt_dir,
        "stage_packet_dir": resolved_stage_dir,
        "safe_work_result_dir": resolved_safe_dir,
        "approval_outcome_path": resolved_approval_outcome_path,
        "approval_callback_dir": resolved_approval_callback_dir,
    }


def load_runtime_artifact_bundle(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
) -> dict[str, Any]:
    paths = resolve_runtime_artifact_paths(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    primary_run_receipt_path = paths["run_receipt_path"]
    primary_run_receipt = _load_json(primary_run_receipt_path)
    run_receipt_dir = paths["run_receipt_dir"]
    resolved_stage_dir = paths["stage_packet_dir"]
    resolved_safe_dir = paths["safe_work_result_dir"]
    approval_outcome_path = paths["approval_outcome_path"]
    approval_callback_dir = paths["approval_callback_dir"]
    approval_outcome = _load_json(approval_outcome_path)
    _, run_receipt_for_artifacts = choose_best_run_receipt_for_artifact_selection(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
    )
    run_stage_dir = _path_from_value(
        root,
        str(
            run_receipt_for_artifacts.get("stage_packet_output_dir")
            or primary_run_receipt.get("stage_packet_output_dir")
            or ""
        ),
    )
    run_safe_dir = _path_from_value(
        root,
        str(
            run_receipt_for_artifacts.get("safe_work_result_output_dir")
            or primary_run_receipt.get("safe_work_result_output_dir")
            or ""
        ),
    )
    if run_stage_dir is not None and not stage_packet_dir:
        resolved_stage_dir = run_stage_dir
    if run_safe_dir is not None and not safe_work_result_dir:
        resolved_safe_dir = run_safe_dir
    preferred_pair = choose_stage_and_safe_work_for_run_receipt(
        stage_packet_dir=resolved_stage_dir,
        safe_work_result_dir=resolved_safe_dir,
        run_receipt=run_receipt_for_artifacts,
    )
    if preferred_pair is None:
        stage_packet_path, stage_packet, safe_work_result_path, safe_work_result = choose_stage_and_safe_work(
            stage_packet_dir=resolved_stage_dir,
            safe_work_result_dir=resolved_safe_dir,
        )
    else:
        stage_packet_path, stage_packet, safe_work_result_path, safe_work_result = preferred_pair
    run_receipt_path, run_receipt = choose_run_receipt(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    callback_summary = approval_callback_runtime_summary(
        approval_callback_dir=approval_callback_dir,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    return {
        "state_path": _path_from_value(root, state_path),
        "run_receipt_path": run_receipt_path,
        "run_receipt_dir": run_receipt_dir,
        "run_receipt": run_receipt,
        "stage_packet_dir": resolved_stage_dir,
        "safe_work_result_dir": resolved_safe_dir,
        "stage_packet_path": stage_packet_path,
        "stage_packet": stage_packet,
        "safe_work_result_path": safe_work_result_path,
        "safe_work_result": safe_work_result,
        "approval_outcome_path": approval_outcome_path,
        "approval_outcome": approval_outcome,
        "approval_callback_dir": approval_callback_dir,
        **callback_summary,
    }


def choose_best_run_receipt_for_artifact_selection(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
) -> tuple[Path | None, dict[str, Any]]:
    best = _best_run_receipt_candidate(
        _run_receipt_candidates(
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
        )
    )
    if best is None:
        return primary_run_receipt_path, primary_run_receipt
    return best[0], best[1]


def approval_callback_runtime_summary(
    *,
    approval_callback_dir: Path,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> dict[str, Any]:
    callback_rows = _approval_callback_rows(approval_callback_dir)
    current_packet_rows = _matching_approval_callback_rows(
        callback_rows,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    latest_current_packet = current_packet_rows[-1] if current_packet_rows else {}
    pending_rows = [row for row in callback_rows if _approval_callback_status(row) == "pending"]
    expired_pending_rows = [row for row in pending_rows if _approval_callback_expired(row)]
    unexpired_pending_rows = [row for row in pending_rows if not _approval_callback_expired(row)]
    recorded_rows = [row for row in callback_rows if _approval_callback_status(row) in _APPROVAL_CALLBACK_DECISION_STATUSES]
    expired_rows = [row for row in callback_rows if _approval_callback_status(row) == "expired"]
    superseded_rows = [row for row in callback_rows if _approval_callback_status(row) == "superseded"]
    terminal_rows = [row for row in callback_rows if _approval_callback_status(row) in _APPROVAL_CALLBACK_TERMINAL_STATUSES]
    current_pending_rows = [row for row in current_packet_rows if _approval_callback_status(row) == "pending"]
    current_expired_pending_rows = [row for row in current_pending_rows if _approval_callback_expired(row)]
    current_expired_rows = [row for row in current_packet_rows if _approval_callback_status(row) == "expired"]
    current_superseded_rows = [row for row in current_packet_rows if _approval_callback_status(row) == "superseded"]
    current_decision_rows = [
        row for row in current_packet_rows if _approval_callback_status(row) in _APPROVAL_CALLBACK_DECISION_STATUSES
    ]
    noncurrent_pending_rows = [row for row in pending_rows if not _approval_callback_matches_current(row, current_packet_rows)]
    live_current_packet_rows = [row for row in current_packet_rows if not _approval_callback_expired(row)]
    live_pending_current_packet_rows = [
        row
        for row in current_packet_rows
        if _approval_callback_status(row) == "pending" and not _approval_callback_expired(row)
    ]
    stale_pending_rows = [
        row
        for row in pending_rows
        if _approval_callback_expired(row) or not _approval_callback_matches_current(row, current_packet_rows)
    ]
    return {
        "approval_callback_dir_exists": approval_callback_dir.is_dir(),
        "approval_callback_dir_writable": _dir_writable(approval_callback_dir),
        "approval_callback_record_count": len(callback_rows),
        "approval_callback_pending_count": len(live_pending_current_packet_rows),
        "approval_callback_raw_pending_count": len(pending_rows),
        "approval_callback_live_pending_count": len(live_pending_current_packet_rows),
        "approval_callback_unexpired_pending_count": len(unexpired_pending_rows),
        "approval_callback_noncurrent_pending_count": len(noncurrent_pending_rows),
        "approval_callback_expired_pending_count": len(expired_pending_rows),
        "approval_callback_stale_pending_count": len(stale_pending_rows),
        "approval_callback_recorded_count": len(recorded_rows),
        "approval_callback_expired_count": len(expired_rows),
        "approval_callback_superseded_count": len(superseded_rows),
        "approval_callback_terminal_count": len(terminal_rows),
        "current_packet_callback_record_count": len(current_packet_rows),
        "current_packet_callback_pending_count": len(current_pending_rows),
        "current_packet_callback_raw_pending_count": len(current_pending_rows),
        "current_packet_callback_expired_pending_count": len(current_expired_pending_rows),
        "current_packet_callback_stale_pending_count": len(current_expired_pending_rows),
        "current_packet_callback_recorded_count": len(current_decision_rows),
        "current_packet_callback_expired_count": len(current_expired_rows),
        "current_packet_callback_superseded_count": len(current_superseded_rows),
        "current_packet_live_callback_record_count": len(live_current_packet_rows),
        "current_packet_live_pending_count": len(live_pending_current_packet_rows),
        "current_packet_callback_latest_status": str(latest_current_packet.get("status") or "").strip(),
        "current_packet_callback_latest_expired": bool(latest_current_packet) and _approval_callback_expired(latest_current_packet),
        "current_packet_callback_outcome": _approval_callback_outcome_row(
            current_decision_rows[-1] if current_decision_rows else {},
        ),
    }


def choose_stage_and_safe_work(
    *,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
) -> tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]]:
    stage_packets = latest_payloads(stage_packet_dir, schema=STAGE_PACKET_SCHEMA)
    safe_work_results = latest_payloads(safe_work_result_dir, schema=SAFE_WORK_RESULT_SCHEMA)
    stage_by_hash = {_packet_ref_hash(payload): (path, payload) for path, payload, _mtime in stage_packets}

    best_score: tuple[int, int, int, float] | None = None
    best_pair: tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]] | None = None
    for safe_path, safe_payload, safe_mtime in safe_work_results:
        stage_path: Path | None = None
        stage_payload: dict[str, Any] = {}
        packet_hash = str(safe_payload.get("source_packet_ref_hash") or "").strip()
        if packet_hash and packet_hash in stage_by_hash:
            stage_path, stage_payload = stage_by_hash[packet_hash]
        score = _stage_safe_pair_score(stage_payload, safe_payload, safe_mtime)
        if best_score is None or score > best_score:
            best_score = score
            best_pair = (stage_path, stage_payload, safe_path, safe_payload)
    if best_pair is not None:
        return best_pair
    if stage_packets:
        stage_path, stage_payload, _mtime = stage_packets[0]
        return stage_path, stage_payload, None, {}
    return None, {}, None, {}


def choose_stage_and_safe_work_for_run_receipt(
    *,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
    run_receipt: Mapping[str, Any],
) -> tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]] | None:
    stage_hashes, safe_hashes = _run_receipt_ref_hash_sets(run_receipt)
    if not stage_hashes or not safe_hashes:
        return None

    stage_packets = latest_payloads(stage_packet_dir, schema=STAGE_PACKET_SCHEMA)
    safe_work_results = latest_payloads(safe_work_result_dir, schema=SAFE_WORK_RESULT_SCHEMA)
    stage_by_hash = {_packet_ref_hash(payload): (path, payload) for path, payload, _mtime in stage_packets}

    best_score: tuple[int, int, int, float] | None = None
    best_pair: tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]] | None = None
    for safe_path, safe_payload, safe_mtime in safe_work_results:
        packet_hash = str(safe_payload.get("source_packet_ref_hash") or "").strip()
        safe_hash = _safe_work_result_ref_hash(safe_payload)
        if not packet_hash or packet_hash not in stage_hashes or safe_hash not in safe_hashes:
            continue
        if packet_hash not in stage_by_hash:
            continue
        stage_path, stage_payload = stage_by_hash[packet_hash]
        score = _stage_safe_pair_score(stage_payload, safe_payload, safe_mtime)
        if best_score is None or score > best_score:
            best_score = score
            best_pair = (stage_path, stage_payload, safe_path, safe_payload)
    return best_pair


def choose_run_receipt(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
    stage_packet: dict[str, Any],
    safe_work_result: dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    if not stage_packet and not safe_work_result:
        if primary_run_receipt:
            return primary_run_receipt_path, primary_run_receipt
        fallback = _best_run_receipt_candidate(
            _run_receipt_candidates(
                primary_run_receipt_path=primary_run_receipt_path,
                primary_run_receipt=primary_run_receipt,
                run_receipt_dir=run_receipt_dir,
            )
        )
        return (fallback[0], fallback[1]) if fallback is not None else (primary_run_receipt_path, primary_run_receipt)

    stage_hash = _packet_ref_hash(stage_packet)
    safe_hash = _safe_work_result_ref_hash(safe_work_result)
    best_match = _best_run_receipt_candidate(
        _run_receipt_candidates(
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
        ),
        stage_packet_ref_hash=stage_hash,
        safe_work_result_ref_hash=safe_hash,
    )
    if best_match is not None:
        return best_match[0], best_match[1]
    return primary_run_receipt_path, primary_run_receipt


def display_path(root: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def latest_payloads(path: Path, *, schema: str) -> list[tuple[Path, dict[str, Any], float]]:
    if not path.is_dir():
        return []
    rows: list[tuple[Path, dict[str, Any], float]] = []
    for candidate in path.glob("*.json"):
        payload = _load_json(candidate)
        if not payload or str(payload.get("schema") or "").strip() != schema:
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((candidate, payload, mtime))
    rows.sort(key=lambda item: (item[2], item[0].name), reverse=True)
    return rows


def latest_run_receipts(path: Path) -> list[tuple[Path, dict[str, Any], float]]:
    if not path.is_dir():
        return []
    rows: list[tuple[Path, dict[str, Any], float]] = []
    for candidate in path.glob("*.json"):
        payload = _load_json(candidate)
        if not payload:
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((candidate, payload, mtime))
    rows.sort(key=lambda item: (item[2], item[0].name), reverse=True)
    return rows


def _path_from_value(root: Path, value: str | Path, *, default: Path | None = None) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return default
    path = Path(normalized)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _packet_ref_hash(packet: dict[str, Any]) -> str:
    packet_ref = str(packet.get("packet_ref") or packet.get("packet_id") or "").strip()
    return hashlib.sha256(packet_ref.encode("utf-8")).hexdigest() if packet_ref else ""


def _safe_work_result_ref_hash(safe_work_result: dict[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if not result_ref:
        result_id = str(safe_work_result.get("result_id") or "").strip()
        result_ref = f"safe_work_result:{result_id}" if result_id else ""
    return hashlib.sha256(result_ref.encode("utf-8")).hexdigest() if result_ref else ""


def _run_receipt_candidates(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
) -> list[tuple[Path | None, dict[str, Any], float]]:
    rows: list[tuple[Path | None, dict[str, Any], float]] = []
    seen_paths: set[str] = set()

    def _add(path: Path | None, payload: dict[str, Any], *, mtime: float = 0.0) -> None:
        key = "" if path is None else path.as_posix()
        if key in seen_paths or not payload:
            return
        seen_paths.add(key)
        rows.append((path, payload, mtime))

    if primary_run_receipt_path is not None:
        mtime = 0.0
        try:
            if primary_run_receipt_path.exists():
                mtime = primary_run_receipt_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        _add(primary_run_receipt_path, primary_run_receipt, mtime=mtime)

    for candidate_path, payload, mtime in latest_run_receipts(run_receipt_dir):
        _add(candidate_path, payload, mtime=mtime)

    state_dir = run_receipt_dir.parent
    for filename in LEGACY_RUN_RECEIPT_FILENAMES:
        candidate_path = state_dir / filename
        if not candidate_path.exists():
            continue
        _add(candidate_path, _load_json(candidate_path), mtime=_safe_mtime(candidate_path))

    return rows


def _best_run_receipt_candidate(
    candidates: list[tuple[Path | None, dict[str, Any], float]],
    *,
    stage_packet_ref_hash: str = "",
    safe_work_result_ref_hash: str = "",
) -> tuple[Path | None, dict[str, Any], float] | None:
    best: tuple[Path | None, dict[str, Any], float] | None = None
    best_score: tuple[int, int, int, int, int, float] | None = None
    require_packet_match = bool(stage_packet_ref_hash and safe_work_result_ref_hash)
    for path, payload, mtime in candidates:
        packet_match = _run_receipt_matches_artifacts(
            payload,
            stage_packet_ref_hash=stage_packet_ref_hash,
            safe_work_result_ref_hash=safe_work_result_ref_hash,
        )
        if require_packet_match and not packet_match:
            continue
        message_count = _message_id_count(payload)
        notification_status = str(payload.get("notification_status") or "").strip().lower()
        item_count = int(payload.get("item_count") or 0)
        teable_sync = dict(payload.get("teable_sync") or {})
        score = (
            1 if packet_match else 0,
            1 if notification_status == "sent" and item_count > 0 and message_count > 0 else 0,
            1 if item_count > 0 else 0,
            1 if notification_status == "sent" else 0,
            1 if str(teable_sync.get("status") or "").strip() in {"synced", "partial"} else 0,
            mtime,
        )
        if best_score is None or score > best_score:
            best = (path, payload, mtime)
            best_score = score
    return best


def _run_receipt_matches_artifacts(
    payload: dict[str, Any],
    *,
    stage_packet_ref_hash: str,
    safe_work_result_ref_hash: str,
) -> bool:
    if not stage_packet_ref_hash or not safe_work_result_ref_hash:
        return False
    stage_hashes, safe_hashes = _run_receipt_ref_hash_sets(payload)
    return stage_packet_ref_hash in stage_hashes and safe_work_result_ref_hash in safe_hashes


def _run_receipt_ref_hash_sets(payload: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    stage_hashes = {str(item or "").strip() for item in list(payload.get("stage_packet_ref_hashes") or []) if str(item or "").strip()}
    safe_hashes = {
        str(item or "").strip()
        for item in list(payload.get("safe_work_result_ref_hashes") or [])
        if str(item or "").strip()
    }
    return stage_hashes, safe_hashes


def _message_id_count(payload: dict[str, Any]) -> int:
    values = payload.get("delivery_message_ids")
    if not isinstance(values, list) or not values:
        values = payload.get("telegram_message_ids")
    if not isinstance(values, list):
        return 0
    return len([item for item in values if str(item or "").strip()])


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _approval_callback_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for candidate in sorted(path.glob("*.json")):
        payload = _load_json(candidate)
        if payload:
            rows.append(payload)
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows


def _approval_callback_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "").strip().lower()


def _approval_callback_outcome_row(row: Mapping[str, Any]) -> dict[str, Any]:
    status = _approval_callback_status(row)
    if status not in _APPROVAL_CALLBACK_DECISION_STATUSES:
        return {}
    packet_hash = str(row.get("packet_ref_sha256") or "").strip()
    staged_artifact_hash = str(row.get("staged_artifact_ref_sha256") or row.get("staged_artifact_sha256") or "").strip()
    actor_hash = str(row.get("actor_sha256") or "").strip()
    evidence_hash = str(
        row.get("evidence_sha256")
        or row.get("approval_prompt_sha256")
        or row.get("message_id_sha256")
        or row.get("callback_token_sha256")
        or ""
    ).strip()
    recorded = bool(packet_hash and staged_artifact_hash and actor_hash and evidence_hash)
    accepted = recorded and status == "approved"
    return {
        "present": recorded,
        "accepted": accepted,
        "approval_outcome_recorded": recorded,
        "status": "accepted_redacted" if accepted else "recorded_not_accepted" if recorded else "missing_or_invalid",
        "outcome": "approved" if status == "approved" else status,
        "source_kind": "telegram_button",
        "recorded_at": str(row.get("decided_at") or row.get("updated_at") or row.get("created_at") or "").strip(),
        "evidence_sha256": evidence_hash,
        "actor_sha256": actor_hash,
        "packet_ref_sha256": packet_hash,
        "staged_artifact_sha256": staged_artifact_hash,
        "approval_outcome_id": str(row.get("approval_outcome_id") or "").strip(),
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
        "raw_staged_artifact_exposed": False,
    }


def _approval_callback_matches_current(row: Mapping[str, Any], current_packet_rows: list[dict[str, Any]]) -> bool:
    return any(row is current or row == current for current in current_packet_rows)


def _matching_approval_callback_rows(
    rows: list[dict[str, Any]],
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    packet_ref = _stage_packet_ref(stage_packet)
    staged_artifact_ref = _safe_work_result_ref(safe_work_result)
    if not packet_ref or not staged_artifact_ref:
        return []
    return [
        row
        for row in rows
        if str(row.get("packet_ref") or "").strip() == packet_ref
        and str(row.get("staged_artifact_ref") or "").strip() == staged_artifact_ref
    ]


def _stage_packet_ref(stage_packet: Mapping[str, Any]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _safe_work_result_ref(safe_work_result: Mapping[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _approval_callback_expired(row: Mapping[str, Any]) -> bool:
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


def _dir_writable(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return probe.exists() and probe.is_dir() and __import__("os").access(probe, __import__("os").W_OK)
    except Exception:
        return False


def _browse_score(safe_work_result: dict[str, Any]) -> int:
    execution_receipt = dict(safe_work_result.get("execution_receipt") or {})
    network_fetch_success_count = int(execution_receipt.get("network_fetch_success_count") or 0)
    reachable_page_count = sum(
        1
        for row in list(execution_receipt.get("page_checks") or [])
        if isinstance(row, dict) and row.get("reachable") is True
    )
    return 1 if network_fetch_success_count > 0 and reachable_page_count > 0 else 0


def _chosen_candidate_present(safe_work_result: dict[str, Any]) -> bool:
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    if not str(recommended.get("kind") or "").strip():
        return False
    value = recommended.get("value")
    if isinstance(value, dict):
        return bool(str(value.get("label") or value.get("title") or value.get("url") or value.get("href") or "").strip())
    return bool(str(value or "").strip())


def _staged_for_decision(safe_work_result: dict[str, Any], stage_packet: dict[str, Any]) -> bool:
    if str(safe_work_result.get("status") or "").strip() != "staged_for_user_decision":
        return False
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_approval = dict(safe_work_result.get("approval") or {})
    return bool(stage_approval.get("required")) or bool(safe_approval.get("required"))


def _stage_safe_pair_score(
    stage_packet: dict[str, Any],
    safe_work_result: dict[str, Any],
    mtime: float,
) -> tuple[int, int, int, float]:
    browse_score = _browse_score(safe_work_result)
    chosen_score = 1 if _chosen_candidate_present(safe_work_result) else 0
    staged_score = 1 if _staged_for_decision(safe_work_result, stage_packet) else 0
    return (browse_score, chosen_score, staged_score, mtime)
