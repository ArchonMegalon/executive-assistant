from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))


def test_calendar_import_response_contract() -> None:
    from app.intake.calendar_import_result import build_calendar_import_response

    full = build_calendar_import_response(
        imported=5,
        total=5,
        persisted=5,
        persist_status="committed",
        failed=0,
    )
    assert full.is_error is False
    assert "✅ <b>Calendar Events Imported.</b>" in full.text
    assert "Imported remotely: <b>5/5</b>" in full.text

    dedup_all = build_calendar_import_response(
        imported=5,
        total=5,
        persisted=0,
        persist_status="committed",
        failed=0,
    )
    assert dedup_all.is_error is False
    assert "already present locally and were deduplicated" in dedup_all.text
    assert "/auth" not in dedup_all.text

    fail_remote = build_calendar_import_response(
        imported=0,
        total=5,
        persisted=0,
        persist_status="failed",
        failed=5,
        persist_err="auth denied",
    )
    assert fail_remote.is_error is True
    assert "Please run <code>/auth</code> and retry." in fail_remote.text

    partial = build_calendar_import_response(
        imported=3,
        total=5,
        persisted=2,
        persist_status="committed",
        failed=2,
    )
    assert partial.is_error is False
    assert "⚠️ <b>Calendar Import Partial.</b>" in partial.text
    assert "Remote failures: <b>2</b>" in partial.text

    print("[SMOKE][HOST][PASS] calendar import result contract", flush=True)


if __name__ == "__main__":
    test_calendar_import_response_contract()

