from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ea/app/watchdog.py"
POLL_SRC = ROOT / "ea/app/poll_listener.py"


def test_sentinel_user_message_contract() -> None:
    src = SRC.read_text(encoding="utf-8")
    poll_src = POLL_SRC.read_text(encoding="utf-8")

    # Throttling contract: persist across restarts and honor configured interval.
    assert "def sentinel_alert_throttled()" in src
    assert "EA_SENTINEL_ALERT_MIN_INTERVAL_SEC" in src
    assert "EA_SENTINEL_HEARTBEAT_TIMEOUT_SEC" in src
    assert "EA_SENTINEL_STARTUP_GRACE_SEC" in src
    assert "EA_SENTINEL_EXIT_ON_STALL" in src
    assert ".sentinel_last_alert.json" in src
    assert "time.monotonic()" in src
    assert "from app.watchdog import heartbeat_pinger, mark_heartbeat, start_watchdog_thread" in poll_src
    assert "start_watchdog_thread(" in poll_src

    # User-facing copy should be concise and reassuring, not internal diagnostics.
    assert "⚠️ <b>Temporary interruption</b>" in src
    assert "No action is needed from you." in src
    assert "please resend it in about a minute." in src

    # Regression guard: do not leak internal fatal/deadlock phrasing to Telegram.
    forbidden = (
        "Assistant AI suffered a fatal event loop deadlock",
        "fatal event loop deadlock",
        "Sentinel Alert",
    )
    for phrase in forbidden:
        assert phrase not in src, phrase

    print("[SMOKE][HOST][PASS] sentinel user-message contract")


if __name__ == "__main__":
    test_sentinel_user_message_contract()
