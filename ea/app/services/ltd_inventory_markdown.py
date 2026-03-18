from __future__ import annotations

from datetime import date
from typing import Any


DISCOVERY_TRACKING_HEADING = "## Discovery Tracking"
SUMMARY_HEADING = "## Summary"
UPDATED_PREFIX = "Updated:"
SUMMARY_TOTAL_SUFFIX = "total LTD products tracked"
INVENTORY_SECTION_HEADINGS = (
    "## Non-AppSumo / Other LTDs",
    "## AppSumo LTDs",
)


def _normalize_service_name(value: object) -> str:
    return str(value or "").strip().strip("`")


def _inventory_services_json(inventory_output_json: dict[str, Any]) -> list[dict[str, Any]]:
    direct = inventory_output_json.get("services_json")
    if isinstance(direct, list):
        return [dict(row) for row in direct if isinstance(row, dict)]
    structured = inventory_output_json.get("structured_output_json")
    if isinstance(structured, dict):
        nested = structured.get("services_json")
        if isinstance(nested, list):
            return [dict(row) for row in nested if isinstance(row, dict)]
    return []


def _notes_for_service_row(row: dict[str, Any]) -> str:
    notes: list[str] = []
    plan_tier = str(row.get("plan_tier") or "").strip()
    if plan_tier:
        notes.append(f"Plan/Tier: {plan_tier}")
    facts_json = dict(row.get("facts_json") or {})
    status = str(facts_json.get("status") or row.get("status") or "").strip()
    if status:
        notes.append(f"Status: {status}")
    missing_fields = [
        str(value or "").strip()
        for value in (row.get("missing_fields") or [])
        if str(value or "").strip()
    ]
    if missing_fields:
        notes.append(f"Missing fields: {', '.join(missing_fields)}")
    live_discovery_error = str(row.get("live_discovery_error") or "").strip()
    if live_discovery_error:
        notes.append(f"Live discovery error: {live_discovery_error}")
    if not notes:
        notes.append("BrowserAct inventory refresh updated this row.")
    return "; ".join(notes)


def build_discovery_updates(inventory_output_json: dict[str, Any]) -> dict[str, list[str]]:
    updates: dict[str, list[str]] = {}
    for row in _inventory_services_json(inventory_output_json):
        service_name = _normalize_service_name(row.get("service_name"))
        if not service_name:
            continue
        updates[service_name.lower()] = [
            f"`{service_name}`",
            str(row.get("account_email") or "").strip(),
            f"`{str(row.get('discovery_status') or '').strip()}`" if str(row.get("discovery_status") or "").strip() else "",
            f"`{str(row.get('verification_source') or '').strip()}`" if str(row.get("verification_source") or "").strip() else "",
            str(row.get("last_verified_at") or "").strip(),
            _notes_for_service_row(row),
        ]
    return updates


def _parse_table_row(line: str, *, minimum_columns: int = 6) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    parts = [part.strip() for part in stripped.strip("|").split("|")]
    if len(parts) < minimum_columns:
        return None
    return parts[:minimum_columns]


def _format_row(parts: list[str]) -> str:
    return "| " + " | ".join(parts[:6]) + " |"


def _table_bounds(lines: list[str], *, heading: str) -> tuple[int, int]:
    try:
        heading_index = next(
            index
            for index, value in enumerate(lines)
            if value.strip() == heading
        )
    except StopIteration as exc:
        raise ValueError(f"{heading}_not_found") from exc

    try:
        table_start = next(
            index
            for index in range(heading_index + 1, len(lines))
            if lines[index].strip().startswith("|")
        )
    except StopIteration as exc:
        raise ValueError(f"{heading}_table_not_found") from exc

    table_end = table_start
    while table_end < len(lines) and lines[table_end].strip().startswith("|"):
        table_end += 1

    if table_end - table_start < 2:
        raise ValueError(f"{heading}_table_invalid")
    return table_start, table_end


def _updated_markdown(updated_lines: list[str], *, trailing_newline: bool) -> str:
    return "\n".join(updated_lines) + ("\n" if trailing_newline else "")


def _replace_updated_stamp(markdown_text: str, *, refresh_date: str | None = None) -> str:
    updated_value = str(refresh_date or date.today().isoformat()).strip()
    if not updated_value:
        raise ValueError("refresh_date_required")
    lines = markdown_text.splitlines()
    try:
        updated_index = next(
            index
            for index, value in enumerate(lines)
            if value.strip().startswith(UPDATED_PREFIX)
        )
    except StopIteration as exc:
        raise ValueError("updated_line_not_found") from exc
    lines[updated_index] = f"{UPDATED_PREFIX} {updated_value}"
    return _updated_markdown(lines, trailing_newline=markdown_text.endswith("\n"))


def _count_inventory_rows(markdown_text: str) -> int:
    lines = markdown_text.splitlines()
    total = 0
    for heading in INVENTORY_SECTION_HEADINGS:
        table_start, table_end = _table_bounds(lines, heading=heading)
        for line in lines[table_start + 2 : table_end]:
            if _parse_table_row(line, minimum_columns=8) is not None:
                total += 1
    return total


def _replace_summary_total(markdown_text: str, *, total_count: int) -> str:
    lines = markdown_text.splitlines()
    try:
        summary_index = next(
            index
            for index, value in enumerate(lines)
            if value.strip() == SUMMARY_HEADING
        )
    except StopIteration as exc:
        raise ValueError("summary_heading_not_found") from exc
    try:
        total_index = next(
            index
            for index in range(summary_index + 1, len(lines))
            if SUMMARY_TOTAL_SUFFIX in lines[index]
        )
    except StopIteration as exc:
        raise ValueError("summary_total_line_not_found") from exc
    lines[total_index] = f"- `{total_count}` {SUMMARY_TOTAL_SUFFIX}"
    return _updated_markdown(lines, trailing_newline=markdown_text.endswith("\n"))


def update_discovery_tracking_table(markdown_text: str, inventory_output_json: dict[str, Any]) -> str:
    lines = markdown_text.splitlines()
    table_start, table_end = _table_bounds(lines, heading=DISCOVERY_TRACKING_HEADING)
    header_line = lines[table_start]
    separator_line = lines[table_start + 1]
    updates = build_discovery_updates(inventory_output_json)
    existing_service_keys: set[str] = set()
    rebuilt_rows: list[str] = []
    for line in lines[table_start + 2 : table_end]:
        parts = _parse_table_row(line)
        if parts is None:
            rebuilt_rows.append(line)
            continue
        service_name = _normalize_service_name(parts[0])
        if service_name:
            existing_service_keys.add(service_name.lower())
        update = updates.get(service_name.lower())
        if update is None:
            rebuilt_rows.append(line)
            continue
        rebuilt_rows.append(_format_row(update))

    for row in _inventory_services_json(inventory_output_json):
        service_name = _normalize_service_name(row.get("service_name"))
        if not service_name or service_name.lower() in existing_service_keys:
            continue
        update = updates.get(service_name.lower())
        if update is not None:
            rebuilt_rows.append(_format_row(update))

    updated_lines = (
        lines[:table_start]
        + [header_line, separator_line]
        + rebuilt_rows
        + lines[table_end:]
    )
    return _updated_markdown(updated_lines, trailing_newline=markdown_text.endswith("\n"))


def refresh_inventory_markdown(
    markdown_text: str,
    inventory_output_json: dict[str, Any],
    *,
    refresh_date: str | None = None,
) -> str:
    updated = update_discovery_tracking_table(markdown_text, inventory_output_json)
    updated = _replace_updated_stamp(updated, refresh_date=refresh_date)
    total_count = _count_inventory_rows(updated)
    return _replace_summary_total(updated, total_count=total_count)
