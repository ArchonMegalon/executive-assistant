from __future__ import annotations

from typing import Any


def build_inventory_execute_payload(
    *,
    binding_id: str,
    service_names: tuple[str, ...],
    requested_fields: tuple[str, ...],
    skill_key: str = "ltd_inventory_refresh",
    goal: str = "refresh LTD inventory facts",
    instructions: str = "",
    run_url: str = "",
) -> dict[str, object]:
    if not str(binding_id or "").strip():
        raise ValueError("binding_id_required")
    normalized_services = tuple(str(value or "").strip() for value in service_names if str(value or "").strip())
    if not normalized_services:
        raise ValueError("service_names_required")
    normalized_fields = tuple(str(value or "").strip() for value in requested_fields if str(value or "").strip())
    if not normalized_fields:
        normalized_fields = ("tier", "account_email", "status")
    payload: dict[str, object] = {
        "skill_key": str(skill_key or "").strip() or "ltd_inventory_refresh",
        "goal": str(goal or "").strip() or "refresh LTD inventory facts",
        "input_json": {
            "binding_id": str(binding_id or "").strip(),
            "service_names": list(normalized_services),
            "requested_fields": list(normalized_fields),
        },
    }
    normalized_instructions = str(instructions or "").strip()
    if normalized_instructions:
        payload["input_json"]["instructions"] = normalized_instructions
    normalized_run_url = str(run_url or "").strip()
    if normalized_run_url:
        payload["input_json"]["run_url"] = normalized_run_url
    return payload


def _extract_inventory_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    direct = value.get("services_json")
    if isinstance(direct, list):
        return dict(value)
    structured = value.get("structured_output_json")
    if isinstance(structured, dict):
        nested = structured.get("services_json")
        if isinstance(nested, list):
            return dict(structured)
    for key in ("output_json", "result_json", "result", "payload_json", "artifact_json"):
        nested = _extract_inventory_payload(value.get(key))
        if nested is not None:
            return nested
    return None


def extract_inventory_output_json(execute_response_json: dict[str, Any]) -> dict[str, Any]:
    extracted = _extract_inventory_payload(execute_response_json)
    if extracted is not None:
        return extracted
    status = str(execute_response_json.get("status") or "").strip()
    if status:
        raise ValueError(f"inventory_refresh_not_immediate:{status}")
    raise ValueError("inventory_payload_not_found")
