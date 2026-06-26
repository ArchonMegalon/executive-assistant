from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.services.proactive_ooda_service import OodaInk, ProactiveOodaDigest


STAGE_PACKET_SCHEMA = "proactive_ooda.stage_packet.v1"


@dataclass(frozen=True)
class StagePacketWriteResult:
    paths: tuple[str, ...]
    packet_refs: tuple[str, ...]
    errors: tuple[str, ...] = ()


def default_stage_packet_dir(*, root: Path, state_path: str | Path) -> Path:
    path = Path(state_path)
    if not path.is_absolute():
        path = root / path
    return path.parent / "proactive_ooda_stage_packets"


def build_stage_packets(digest: ProactiveOodaDigest) -> tuple[dict[str, Any], ...]:
    return tuple(_stage_packet(digest, item=item, index=index) for index, item in enumerate(digest.items, start=1))


def persist_stage_packets(*, digest: ProactiveOodaDigest, output_dir: str | Path) -> StagePacketWriteResult:
    packets = build_stage_packets(digest)
    if not packets:
        return StagePacketWriteResult(paths=(), packet_refs=())
    target = Path(output_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return StagePacketWriteResult(paths=(), packet_refs=(), errors=(f"stage_packet_dir:{exc.__class__.__name__}",))
    paths: list[str] = []
    refs: list[str] = []
    errors: list[str] = []
    for packet in packets:
        packet_ref = str(packet.get("packet_ref") or "")
        try:
            path = target / f"{packet['packet_id']}.json"
            path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths.append(str(path))
            refs.append(packet_ref)
        except Exception as exc:
            errors.append(f"{packet_ref}:{exc.__class__.__name__}")
    return StagePacketWriteResult(paths=tuple(paths), packet_refs=tuple(refs), errors=tuple(errors))


def _stage_packet(digest: ProactiveOodaDigest, *, item: OodaInk, index: int) -> dict[str, Any]:
    packet_id = _packet_id(digest=digest, item=item, index=index)
    stage_payload = dict(item.stage_payload or {})
    stage_kind = item.stage_kind or str(stage_payload.get("kind") or "").strip() or _default_stage_kind(item)
    stage_summary = item.stage_summary or str(stage_payload.get("summary") or "").strip() or item.act
    stage_artifacts = tuple(item.stage_artifacts) or _string_tuple(stage_payload.get("artifacts"))
    approval_gate = item.approval_gate or str(stage_payload.get("approval_gate") or "").strip() or item.external_action_policy
    return {
        "schema": STAGE_PACKET_SCHEMA,
        "packet_id": packet_id,
        "packet_ref": f"stage_packet:{packet_id}",
        "status": "staged",
        "generated_at": digest.generated_at,
        "principal_id_hash": _hash_value(digest.principal_id),
        "signal_ref_hash": _hash_value(item.signal_ref),
        "item_index": index,
        "priority": item.priority,
        "observe": item.observe,
        "orient": item.orient,
        "decide": item.decide,
        "act": item.act,
        "action_plan": list(item.action_plan),
        "stage": {
            "kind": stage_kind,
            "summary": stage_summary,
            "artifacts": list(stage_artifacts),
            "payload": _json_safe(stage_payload),
        },
        "approval": {
            "required": bool(item.approval_required),
            "gate": approval_gate,
            "external_action_policy": item.external_action_policy,
            "irreversible_actions_require_explicit_approval": True,
        },
        "ignored_consequence": item.ignored_consequence,
        "evidence_count": len(item.evidence),
        "evidence_hashes": [_hash_value(value) for value in item.evidence],
        "execution_policy": {
            "allowed_before_approval": [
                "research",
                "compare_options",
                "draft",
                "prepare_shortlist",
                "prepare_cart_or_link",
                "prepare_booking_candidate",
            ],
            "forbidden_without_explicit_approval": [
                "purchase",
                "book",
                "cancel",
                "send_external_message",
                "post",
                "commit",
            ],
        },
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_signal_ref_stored": False,
            "raw_evidence_refs_stored": False,
        },
    }


def _packet_id(*, digest: ProactiveOodaDigest, item: OodaInk, index: int) -> str:
    material = "|".join((digest.generated_at, digest.principal_id, item.signal_ref, str(index)))
    return f"proactive-ooda-stage-{_hash_value(material)[:24]}"


def _default_stage_kind(item: OodaInk) -> str:
    if item.approval_required:
        return "approval_packet"
    if item.action_plan:
        return "research_packet"
    return "decision_packet"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    return str(value)


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
