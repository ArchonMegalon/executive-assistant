from __future__ import annotations

import os


def mumbrain_user_visible() -> bool:
    raw = str(os.getenv("EA_EXPOSE_MUMBRAIN_MENU", "false")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def bot_commands() -> list[dict]:
    commands = [
        {"command": "brief", "description": "Executive briefing + personal newspaper PDF"},
        {"command": "auth", "description": "Authorize Google account/services"},
        {"command": "briefpdf", "description": "Standalone article PDF"},
        {"command": "articlespdf", "description": "Alias for article PDF"},
        {"command": "remember", "description": "Store memory fact"},
        {"command": "brain", "description": "Show stored memory"},
        {"command": "menu", "description": "Show all commands"},
        {"command": "help", "description": "Show all commands"},
        {"command": "start", "description": "Start and show command menu"},
    ]
    if mumbrain_user_visible():
        commands.insert(6, {"command": "mumbrain", "description": "Operator health status"})
    return commands


def menu_text() -> str:
    txt = (
        "📋 <b>Command Menu</b>\n\n"
        "• <code>/brief</code> - Executive briefing + personal newspaper PDF\n"
        "• <code>/auth [email]</code> - Authenticate Google services\n"
        "• <code>/briefpdf</code> - Standalone interesting-articles PDF\n"
        "• <code>/articlespdf</code> - Alias for <code>/briefpdf</code>\n"
        "• <code>/remember &lt;text&gt;</code> - Save a memory fact\n"
        "• <code>/brain</code> - Show saved memory\n"
        "• <code>/menu</code> or <code>/help</code> - Show this menu"
    )
    if mumbrain_user_visible():
        txt = txt.replace(
            "• <code>/menu</code> or <code>/help</code> - Show this menu",
            "• <code>/mumbrain</code> - Operator health status\n"
            "• <code>/menu</code> or <code>/help</code> - Show this menu",
        )
    return txt
