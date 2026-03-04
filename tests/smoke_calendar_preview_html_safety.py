from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLL = ROOT / "ea/app/poll_listener.py"


def test_calendar_preview_html_safety_contract() -> None:
    src = POLL.read_text(encoding="utf-8")

    assert "📅 <b>Found Events:</b>" in src
    assert "start_txt = html.escape" in src
    assert "title_txt = html.escape" in src
    assert "lines.append(f'• {start_txt} - {title_txt}" in src
    assert "parse_mode='HTML'" in src

    print("[SMOKE][HOST][PASS] calendar preview html safety contract", flush=True)


if __name__ == "__main__":
    test_calendar_preview_html_safety_contract()

