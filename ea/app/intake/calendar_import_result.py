from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalendarImportResponse:
    text: str
    parse_mode: str = "HTML"
    is_error: bool = False


def build_calendar_import_response(
    *,
    imported: int,
    total: int,
    persisted: int,
    persist_status: str,
    failed: int,
    persist_err: str = "",
) -> CalendarImportResponse:
    imported_i = max(0, int(imported))
    total_i = max(0, int(total))
    persisted_i = max(0, int(persisted))
    failed_i = max(0, int(failed))
    status = str(persist_status or "").strip().lower()
    commit_ok = bool(total_i > 0 and status == "committed")

    if imported_i == total_i and total_i > 0 and commit_ok:
        if persisted_i >= imported_i:
            return CalendarImportResponse(
                text=(
                    "✅ <b>Calendar Events Imported.</b>\n"
                    f"Imported remotely: <b>{imported_i}/{total_i}</b>\n"
                    f"Persisted locally: <b>{persisted_i}</b>"
                ),
                is_error=False,
            )
        if persisted_i > 0:
            return CalendarImportResponse(
                text=(
                    "✅ <b>Calendar Events Imported.</b>\n"
                    f"Imported remotely: <b>{imported_i}/{total_i}</b>\n"
                    f"Persisted locally: <b>{persisted_i}</b>\n"
                    "ℹ️ Some events were already present locally and were deduplicated."
                ),
                is_error=False,
            )
        return CalendarImportResponse(
            text=(
                "✅ <b>Calendar Events Imported.</b>\n"
                f"Imported remotely: <b>{imported_i}/{total_i}</b>\n"
                "Persisted locally: <b>0</b>\n"
                "ℹ️ All imported events were already present locally and were deduplicated."
            ),
            is_error=False,
        )

    if imported_i > 0 and commit_ok:
        note = ""
        if persisted_i < imported_i:
            note = "\nℹ️ Some events were deduplicated locally."
        return CalendarImportResponse(
            text=(
                "⚠️ <b>Calendar Import Partial.</b>\n"
                f"Imported remotely: <b>{imported_i}/{total_i}</b>\n"
                f"Persisted locally: <b>{persisted_i}</b>\n"
                f"Remote failures: <b>{failed_i}</b>{note}"
            ),
            is_error=False,
        )

    reason = f"Local commit status: <b>{status or 'unknown'}</b>."
    if persist_err:
        reason += f"\n<code>{str(persist_err)[:240]}</code>"
    auth_hint = "\nPlease run <code>/auth</code> and retry." if imported_i == 0 else ""
    return CalendarImportResponse(
        text=(
            "❌ <b>Calendar Import Failed.</b>\n"
            f"Imported remotely: <b>{imported_i}/{total_i}</b>\n"
            f"Persisted locally: <b>{persisted_i}</b>\n"
            f"{reason}{auth_hint}"
        ),
        is_error=True,
    )

