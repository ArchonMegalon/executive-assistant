from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_briefing_uses_multi_dossier_compose() -> None:
    src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    assert "build_health_dossier" in src
    assert "build_project_dossier" in src
    assert "build_finance_commitment_dossier" in src
    assert "build_critical_actions(profile_ctx, dossiers, future_situations=future_situations)" in src
    assert "build_future_situations(" in src and "dossiers=dossiers" in src
    assert "build_readiness_dossier(" in src and "dossiers=dossiers" in src
    assert "No immediate action blocks detected right now." in src
    assert "Runtime confidence is reduced; urgent status may be incomplete." in src
    assert "Standard scan found no urgent items, but runtime confidence is reduced." not in src
    assert "No critical items require your immediate attention." not in src
    _pass("v1.19.2 multi-dossier compose wiring")


def test_briefing_diagnostics_not_appended_to_chat() -> None:
    src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    assert "⚙️ Diagnostics:" not in src
    assert "def _emit_internal_diagnostics(" in src
    _pass("v1.19.2 diagnostics-to-chat disabled")


def test_mumbrain_hidden_from_user_menu_by_default() -> None:
    poll_src = (ROOT / "ea/app/poll_listener.py").read_text(encoding="utf-8")
    menu_src = (ROOT / "ea/app/telegram_menu.py").read_text(encoding="utf-8")
    auth_src = (ROOT / "ea/app/auth_sessions.py").read_text(encoding="utf-8")
    assert "from app.telegram_menu import" in poll_src
    assert "from app.auth_sessions import AuthSessionStore" in poll_src
    assert "class AuthSessionStore" not in poll_src
    assert "def mumbrain_user_visible(" in menu_src
    assert "EA_EXPOSE_MUMBRAIN_MENU" in menu_src
    assert "This command is operator-only." in poll_src
    assert "class AuthSessionStore" in auth_src
    _pass("v1.19.2 calm menu surface")


if __name__ == "__main__":
    test_briefing_uses_multi_dossier_compose()
    test_briefing_diagnostics_not_appended_to_chat()
    test_mumbrain_hidden_from_user_menu_by_default()
