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
    brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    compose_src = (ROOT / "ea/app/intelligence/human_compose.py").read_text(encoding="utf-8")
    acq_src = (ROOT / "ea/app/intelligence/source_acquisition.py").read_text(encoding="utf-8")
    assert "build_health_dossier" in brief_src
    assert "build_household_ops_dossier" in brief_src
    assert "build_project_dossier" in brief_src
    assert "build_finance_commitment_dossier" in brief_src
    assert "build_critical_actions(profile_ctx, dossiers, future_situations=future_situations)" in brief_src
    assert "build_future_situations(" in brief_src and "dossiers=dossiers" in brief_src
    assert "build_readiness_dossier(" in brief_src and "dossiers=dossiers" in brief_src
    assert "from app.intelligence.human_compose import compose_briefing_html" in brief_src
    assert "from app.intelligence.source_acquisition import collect_briefing_sources" in brief_src
    assert "No immediate action blocks detected right now." in compose_src
    assert "Runtime confidence is reduced; urgent status may be incomplete." in compose_src
    assert "No critical items require your immediate attention." not in compose_src
    assert "Risk urgency:" in compose_src
    assert "Decision window:" in compose_src
    assert "def collect_briefing_sources(" in acq_src
    _pass("v1.19.2 multi-dossier compose wiring")


def test_briefing_diagnostics_not_appended_to_chat() -> None:
    src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    poll_src = (ROOT / "ea/app/poll_listener.py").read_text(encoding="utf-8")
    assert "⚙️ Diagnostics:" not in src
    assert "def _emit_internal_diagnostics(" in src
    assert "EA_RENDER_DIAGNOSTIC_TO_CHAT" not in poll_src
    assert "⚙️ <b>OODA Diagnostic (Rendering):</b>" not in poll_src
    _pass("v1.19.2 diagnostics-to-chat disabled")


def test_mumbrain_hidden_from_user_menu_by_default() -> None:
    poll_src = (ROOT / "ea/app/poll_listener.py").read_text(encoding="utf-8")
    menu_src = (ROOT / "ea/app/telegram_menu.py").read_text(encoding="utf-8")
    auth_src = (ROOT / "ea/app/auth_sessions.py").read_text(encoding="utf-8")
    assist_src = (ROOT / "ea/app/chat_assist.py").read_text(encoding="utf-8")
    delivery_src = (ROOT / "ea/app/briefing_delivery_sessions.py").read_text(encoding="utf-8")
    security_src = (ROOT / "ea/app/message_security.py").read_text(encoding="utf-8")
    preferences_src = (ROOT / "ea/app/newspaper/preferences.py").read_text(encoding="utf-8")
    assert "from app.telegram_menu import" in poll_src
    assert "from app.auth_sessions import AuthSessionStore" in poll_src
    assert "from app.chat_assist import ask_llm_text as _ask_llm_text, humanize_agent_report as _humanize_agent_report" in poll_src
    assert "from app.message_security import check_security, household_confidence_for_message as _household_confidence_for_message, message_document_ref as _message_document_ref" in poll_src
    assert "from app.briefing_delivery_sessions import create_briefing_delivery_session, activate_briefing_delivery_session" in poll_src
    assert "from app.newspaper.preferences import build_preference_snapshot" in poll_src
    assert "def _create_briefing_delivery_session(" not in poll_src
    assert "def _activate_delivery_session(" not in poll_src
    assert "def _household_confidence_for_message(" not in poll_src
    assert "def _message_document_ref(" not in poll_src
    assert "async def check_security(" not in poll_src
    assert "async def _preference_snapshot(" not in poll_src
    assert "async def _collect_briefing_articles(" not in poll_src
    assert "def _briefing_newspaper_html(" not in poll_src
    assert "class AuthSessionStore" not in poll_src
    assert "def _humanize_agent_report(" not in poll_src
    assert "def _ask_llm_text(" not in poll_src
    assert "def mumbrain_user_visible(" in menu_src
    assert "EA_EXPOSE_MUMBRAIN_MENU" in menu_src
    assert "This command is operator-only." in poll_src
    assert "class AuthSessionStore" in auth_src
    assert "def ask_llm_text(" in assist_src
    assert "def humanize_agent_report(" in assist_src
    assert "def create_briefing_delivery_session(" in delivery_src
    assert "def activate_briefing_delivery_session(" in delivery_src
    assert "def household_confidence_for_message(" in security_src
    assert "def message_document_ref(" in security_src
    assert "async def check_security(" in security_src
    assert "def build_preference_snapshot(" in preferences_src
    _pass("v1.19.2 calm menu surface")


if __name__ == "__main__":
    test_briefing_uses_multi_dossier_compose()
    test_briefing_diagnostics_not_appended_to_chat()
    test_mumbrain_hidden_from_user_menu_by_default()
