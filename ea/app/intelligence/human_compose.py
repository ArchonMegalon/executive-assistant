from __future__ import annotations

from typing import Any, Iterable

from app.intelligence.modes import mode_label


def _sanitize_telegram_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _score_band(score: int | float) -> str:
    value = int(score or 0)
    if value >= 75:
        return "high"
    if value >= 45:
        return "medium"
    return "low"


def _decision_label(score: int | float) -> str:
    value = int(score or 0)
    if value >= 75:
        return "act now"
    if value >= 45:
        return "soon"
    return "monitor"


def _iter_actions(items: Iterable[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    for item in items:
        val = str(item or "").strip()
        if not val:
            continue
        out.append(val)
        if len(out) >= limit:
            break
    return out


def compose_briefing_html(
    *,
    compose_mode: str,
    critical: Any,
    readiness: Any,
    prep_plan: Any,
    ranked_epics: list[Any],
    epic_deltas: list[str],
    llm_obj: dict[str, Any],
    loops_txt: str,
    confidence_note: str | None,
) -> tuple[str, list[str]]:
    html_out = "🎩 <b>Executive Action Briefing</b>\n\n"
    html_out += f"<i>Mode:</i> {_sanitize_telegram_html(mode_label(compose_mode))}\n\n"

    immediate_actions = _iter_actions(getattr(critical, "actions", ()), limit=4)
    if immediate_actions:
        html_out += "<b>Immediate Action:</b>\n"
        for action in immediate_actions:
            html_out += f"• {_sanitize_telegram_html(action)}\n"
        exposure_score = int(getattr(critical, "exposure_score", 0) or 0)
        decision_score = int(getattr(critical, "decision_window_score", 0) or 0)
        if exposure_score or decision_score:
            html_out += (
                f"<i>Risk urgency:</i> {_sanitize_telegram_html(_score_band(exposure_score).title())} | "
                f"<i>Decision window:</i> {_sanitize_telegram_html(_decision_label(decision_score).title())}\n"
            )
        evidence = _iter_actions(getattr(critical, "evidence", ()), limit=2)
        if evidence:
            html_out += f"<i>Signal source:</i> {_sanitize_telegram_html(' | '.join(evidence))}\n"
        html_out += "\n"

    blockers = _iter_actions(getattr(readiness, "blockers", ()), limit=2)
    if blockers:
        html_out += "<b>Why It Matters:</b>\n"
        for blocker in blockers:
            html_out += f"• {_sanitize_telegram_html(blocker)}\n"
        html_out += "\n"

    if ranked_epics:
        html_out += "<b>Active Epics:</b>\n"
        for epic in ranked_epics[:3]:
            title = _sanitize_telegram_html(str(getattr(epic, "title", "") or "Epic"))
            status = _sanitize_telegram_html(str(getattr(epic, "status", "") or "watch"))
            summary = _sanitize_telegram_html(str(getattr(epic, "summary", "") or ""))
            unresolved = int(getattr(epic, "unresolved_count", 0) or 0)
            follow_up = f"{unresolved} open item(s) need follow-up" if unresolved > 0 else "on track"
            html_out += (
                f"• <b>{title}</b> ({status})"
                f" | {_sanitize_telegram_html(follow_up)}\n"
            )
            if summary:
                html_out += f"  └ <i>{summary}</i>\n"
        html_out += "\n"

    if epic_deltas:
        html_out += "<b>What Changed:</b>\n"
        for line in _iter_actions(epic_deltas, limit=3):
            html_out += f"• {_sanitize_telegram_html(line)}\n"
        html_out += "\n"

    readiness_status = str(getattr(readiness, "status", "") or "watch").title()
    readiness_score = int(getattr(readiness, "score", 0) or 0)
    html_out += f"<b>Readiness:</b> {_sanitize_telegram_html(readiness_status)} (score {readiness_score}/100)\n"
    watch_items = _iter_actions(getattr(readiness, "watch_items", ()), limit=2)
    if watch_items:
        html_out += "<i>Watch:</i> " + _sanitize_telegram_html(" | ".join(watch_items)) + "\n"

    prep_actions = _iter_actions(getattr(prep_plan, "actions", ()), limit=4)
    if prep_actions:
        html_out += "<b>Preparation Plan:</b>\n"
        for step in prep_actions:
            html_out += f"• {_sanitize_telegram_html(step)}\n"
    prep_note = str(getattr(prep_plan, "confidence_note", "") or "").strip()
    if prep_note:
        html_out += f"<i>Confidence:</i> {_sanitize_telegram_html(prep_note)}\n"
    html_out += "\n"

    html_out += str(loops_txt or "")

    options: list[str] = []
    seen_btns: set[str] = set()
    emails = list((llm_obj or {}).get("emails") or [])
    if emails:
        html_out += "<b>Requires Attention:</b>\n"
        for entry in emails:
            sender = _sanitize_telegram_html(str((entry or {}).get("sender", "Unknown")))
            subject = _sanitize_telegram_html(str((entry or {}).get("subject", "")))
            reason = _sanitize_telegram_html(str((entry or {}).get("churchill_action", "")))
            html_out += f"• <b>{sender}</b>: <i>{subject}</i>\n  └ <i>{reason}</i>\n\n"
            btn = str((entry or {}).get("action_button") or "").strip()
            if not btn or "option" in btn.lower():
                continue
            key = btn.lower()
            if key in seen_btns:
                continue
            seen_btns.add(key)
            options.append(btn)
    else:
        if immediate_actions:
            html_out += "<i>No additional inbox-critical items after deterministic critical scan.</i>\n\n"
        elif confidence_note:
            html_out += "<i>Runtime confidence is reduced; urgent status may be incomplete. Please verify high-impact commitments.</i>\n\n"
        else:
            html_out += "<i>No immediate action blocks detected right now.</i>\n\n"

    calendar_summary = str((llm_obj or {}).get("calendar_summary", "No upcoming events."))
    html_out += f"<b>Calendars:</b>\n{_sanitize_telegram_html(calendar_summary)}"
    return html_out, options[:5]
