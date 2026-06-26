from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.proactive_ooda_stage_packets import (
    FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL,
    SAFE_WORK_ORDER_SCHEMA,
)


SAFE_WORK_RESULT_SCHEMA = "proactive_ooda.safe_work_result.v1"


@dataclass(frozen=True)
class SafeWorkResultWriteResult:
    paths: tuple[str, ...]
    result_refs: tuple[str, ...]
    errors: tuple[str, ...] = ()


def default_safe_work_result_dir(stage_packet_dir: str | Path) -> Path:
    path = Path(stage_packet_dir)
    return path.parent / "proactive_ooda_safe_work_results"


def build_safe_work_result(packet: Mapping[str, Any], *, generated_at: str | None = None) -> dict[str, Any]:
    order = packet.get("safe_work_order") if isinstance(packet.get("safe_work_order"), Mapping) else {}
    input_contract = order.get("input_contract") if isinstance(order.get("input_contract"), Mapping) else {}
    stage = packet.get("stage") if isinstance(packet.get("stage"), Mapping) else {}
    stage_payload = stage.get("payload") if isinstance(stage.get("payload"), Mapping) else {}
    work_type = str(order.get("work_type") or "research").strip() or "research"
    candidate_items = _candidate_items(input_contract=input_contract, stage_payload=stage_payload)
    recommended = _recommended_option_or_draft(
        work_type=work_type,
        input_contract=input_contract,
        stage_payload=stage_payload,
        candidate_items=candidate_items,
    )
    has_material = bool(recommended.get("value") or candidate_items)
    result_id = _result_id(packet=packet, order=order, generated_at=generated_at or "")
    return {
        "schema": SAFE_WORK_RESULT_SCHEMA,
        "result_id": result_id,
        "result_ref": f"safe_work_result:{result_id}",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_packet_ref_hash": _hash_value(str(packet.get("packet_ref") or packet.get("packet_id") or "")),
        "work_order_id_hash": _hash_value(str(order.get("work_order_id") or "")),
        "work_order_schema": str(order.get("schema") or ""),
        "status": "staged_for_user_decision" if has_material else "blocked_needs_research_input",
        "work_type": work_type,
        "summary": _summary(packet=packet, order=order, recommended=recommended, has_material=has_material),
        "recommended_option_or_draft": recommended,
        "shortlist": candidate_items,
        "evidence_refs": _evidence_refs(input_contract=input_contract, stage_payload=stage_payload, candidate_items=candidate_items),
        "risks_or_tradeoffs": _risks_or_tradeoffs(input_contract=input_contract, stage_payload=stage_payload),
        "approval_prompt": _approval_prompt(packet=packet, order=order, recommended=recommended, has_material=has_material),
        "approval": {
            "required": True,
            "gate": str(order.get("approval_gate") or _approval_gate(packet) or "").strip(),
            "irreversible_actions_require_explicit_approval": True,
        },
        "execution_receipt": {
            "network_fetch_enabled": False,
            "external_actions_attempted": [],
            "irreversible_actions_attempted": [],
            "forbidden_without_explicit_approval": list(FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL),
            "safe_work_order_schema_valid": str(order.get("schema") or "") == SAFE_WORK_ORDER_SCHEMA,
        },
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_signal_ref_stored": False,
            "private_links_may_be_present": True,
        },
    }


def build_safe_work_results(packets: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(build_safe_work_result(packet) for packet in packets)


def persist_safe_work_results(
    *,
    stage_packet_dir: str | Path,
    result_dir: str | Path | None = None,
    limit: int = 100,
) -> SafeWorkResultWriteResult:
    packets, load_errors = load_stage_packets(stage_packet_dir=stage_packet_dir, limit=limit)
    target = Path(result_dir) if result_dir is not None else default_safe_work_result_dir(stage_packet_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return SafeWorkResultWriteResult(paths=(), result_refs=(), errors=(*load_errors, f"safe_work_result_dir:{exc.__class__.__name__}"))
    paths: list[str] = []
    refs: list[str] = []
    errors = list(load_errors)
    for packet in packets:
        try:
            result = build_safe_work_result(packet)
            path = target / f"{result['result_id']}.json"
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths.append(str(path))
            refs.append(str(result["result_ref"]))
        except Exception as exc:
            packet_ref = str(packet.get("packet_ref") or packet.get("packet_id") or "unknown")
            errors.append(f"{packet_ref}:{exc.__class__.__name__}")
    return SafeWorkResultWriteResult(paths=tuple(paths), result_refs=tuple(refs), errors=tuple(errors))


def load_stage_packets(*, stage_packet_dir: str | Path, limit: int = 100) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    root = Path(stage_packet_dir)
    if not root.exists():
        return (), (f"stage_packet_dir_missing:{root}",)
    packets: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json"))[: max(int(limit or 1), 1)]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path.name}:{exc.__class__.__name__}")
            continue
        if isinstance(payload, dict):
            packets.append(payload)
        else:
            errors.append(f"{path.name}:packet_not_object")
    return tuple(packets), tuple(errors)


def _candidate_items(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("candidate_items", "candidates", "booking_options"):
        value = input_contract.get(key, stage_payload.get(key))
        items = _object_list(value)
        if items:
            return items
    links = _string_list(input_contract.get("links", stage_payload.get("links")))
    target_sites = _string_list(input_contract.get("target_sites", stage_payload.get("target_sites")))
    return [{"label": _label_from_url(url), "url": url} for url in (*links, *target_sites)]


def _recommended_option_or_draft(
    *,
    work_type: str,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if work_type == "draft":
        draft = stage_payload.get("draft_text") or stage_payload.get("draft")
        return {"kind": "draft_text", "value": _json_safe(draft), "source": "stage_payload"} if draft else {}
    if work_type == "prepare_booking_candidate":
        candidate = candidate_items[0] if candidate_items else {}
        return {"kind": "booking_candidate", "value": candidate, "source": "stage_payload"} if candidate else {}
    if work_type == "prepare_cart_or_link":
        value = (
            stage_payload.get("cart_url")
            or stage_payload.get("approval_url")
            or _first_url(candidate_items)
            or _first_url(_object_list(input_contract.get("links")))
        )
        return {"kind": "reversible_cart_or_link", "value": value, "source": "stage_payload"} if value else {}
    if candidate_items:
        return {"kind": "shortlist_candidate", "value": candidate_items[0], "source": "stage_payload"}
    query = input_contract.get("research_query") or _first_string(input_contract.get("search_queries"))
    return {"kind": "research_query", "value": str(query).strip(), "source": "input_contract"} if str(query or "").strip() else {}


def _summary(*, packet: Mapping[str, Any], order: Mapping[str, Any], recommended: Mapping[str, Any], has_material: bool) -> str:
    if has_material:
        outcome = str(order.get("requested_outcome") or "").strip()
        return outcome or "Safe work produced a reversible result for user approval."
    stage = packet.get("stage") if isinstance(packet.get("stage"), Mapping) else {}
    return str(stage.get("summary") or "Safe work needs additional research input before a recommendation can be staged.").strip()


def _evidence_refs(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(candidate_items, start=1):
        url = str(item.get("url") or item.get("link") or "").strip()
        label = str(item.get("label") or item.get("title") or f"candidate-{index}").strip()
        refs.append({"kind": "candidate", "label": label, "url": url, "url_hash": _hash_value(url) if url else ""})
    for url in _string_list(input_contract.get("target_sites", stage_payload.get("target_sites"))):
        if not any(ref.get("url") == url for ref in refs):
            refs.append({"kind": "target_site", "label": _label_from_url(url), "url": url, "url_hash": _hash_value(url)})
    return refs


def _risks_or_tradeoffs(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> list[str]:
    values = []
    for key in ("risks", "risk", "tradeoffs", "constraints", "exclusions"):
        raw = input_contract.get(key, stage_payload.get(key))
        if isinstance(raw, Mapping):
            values.extend(f"{name}: {value}" for name, value in raw.items())
        elif isinstance(raw, (list, tuple)):
            values.extend(str(item).strip() for item in raw if str(item).strip())
        elif str(raw or "").strip():
            values.append(str(raw).strip())
    return values


def _approval_prompt(
    *,
    packet: Mapping[str, Any],
    order: Mapping[str, Any],
    recommended: Mapping[str, Any],
    has_material: bool,
) -> str:
    gate = str(order.get("approval_gate") or _approval_gate(packet) or "Explicit approval required before any irreversible action.").strip()
    if has_material:
        kind = str(recommended.get("kind") or "result").replace("_", " ")
        return f"Approve whether EA should proceed with this staged {kind}. {gate}"
    return f"Approve whether EA should research further or change constraints. {gate}"


def _approval_gate(packet: Mapping[str, Any]) -> str:
    approval = packet.get("approval") if isinstance(packet.get("approval"), Mapping) else {}
    return str(approval.get("gate") or approval.get("external_action_policy") or "").strip()


def _object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _first_string(value: Any) -> str:
    for item in _string_list(value):
        return item
    return ""


def _first_url(items: list[dict[str, Any]]) -> str:
    for item in items:
        for key in ("url", "link", "href"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
    return ""


def _label_from_url(url: str) -> str:
    normalized = str(url or "").strip()
    return normalized.split("//", 1)[-1].split("/", 1)[0] or normalized or "link"


def _result_id(*, packet: Mapping[str, Any], order: Mapping[str, Any], generated_at: str) -> str:
    material = "|".join(
        (
            str(packet.get("packet_id") or packet.get("packet_ref") or ""),
            str(order.get("work_order_id") or ""),
            generated_at,
        )
    )
    return f"proactive-ooda-safe-work-{_hash_value(material)[:24]}"


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
