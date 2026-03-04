from __future__ import annotations

import re
import urllib.parse
from typing import Callable


def clean_html_for_telegram(text: str) -> str:
    if not text:
        return ""
    rendered = (
        text.replace("<br>", "\n")
        .replace("<br/>", "\n")
        .replace("</p>", "\n\n")
        .replace("<p>", "")
        .replace("<ul>", "")
        .replace("</ul>", "")
        .replace("<ol>", "")
        .replace("</ol>", "")
        .replace("<li>", "• ")
        .replace("</li>", "\n")
        .replace("<h1>", "\n\n<b>")
        .replace("</h1>", "</b>\n")
        .replace("<h2>", "\n\n<b>")
        .replace("</h2>", "</b>\n")
        .replace("<strong>", "<b>")
        .replace("</strong>", "</b>")
        .replace("<em>", "<i>")
        .replace("</em>", "</i>")
        .replace("<html>", "")
        .replace("</html>", "")
        .replace("<body>", "")
        .replace("</body>", "")
        .replace("<div>", "")
        .replace("</div>", "")
    )
    rendered = re.sub(r"&(?![A-Za-z0-9#]+;)", "&amp;", rendered)

    def _whitelist_tag(match: re.Match[str]) -> str:
        tag = match.group(1).lower()
        if tag in {"b", "i", "a", "code", "pre", "s", "u"}:
            return match.group(0)
        return ""

    rendered = re.sub(r"</?([a-zA-Z0-9]+)[^>]*>", _whitelist_tag, rendered)
    return re.sub(r"\n{3,}", "\n\n", rendered).strip()


def build_dynamic_ui(
    report_text: str,
    context_prompt: str,
    *,
    save_ctx: Callable[[str], str],
    fwd_name: str | None = None,
) -> dict | None:
    keyboard: list[list[dict[str, str]]] = []
    if fwd_name:
        lower_name = str(fwd_name).lower()
        if "liz" in lower_name or "elisabeth" in lower_name:
            keyboard.append(
                [
                    {
                        "text": f"🤖 Ask to reply to {fwd_name}",
                        "callback_data": f"fwd_liz:{save_ctx(report_text)}",
                    }
                ]
            )
        else:
            keyboard.append(
                [
                    {
                        "text": f"📤 Forward to {fwd_name}",
                        "url": f"https://t.me/share/url?url={urllib.parse.quote('Antwort:\n' + report_text)}",
                    }
                ]
            )

    options_match = re.search(r"\[OPTIONS:\s*(.+?)\]", str(report_text or ""))
    if options_match:
        options = [opt.strip() for opt in options_match.group(1).split("|") if opt.strip()][:5]
        for opt in options:
            lowered = opt.lower()
            rejected = any(
                marker in lowered
                for marker in ["do not", "no", "cancel", "stop", "abort", "skip"]
            )
            if rejected:
                callback_text = (
                    f"CONTINUING TASK:\n{context_prompt[:1500]}\n\n"
                    f"User selected: {opt}. REJECTED. Propose alternatives."
                )
            else:
                callback_text = (
                    f"CONTINUING TASK:\n{context_prompt[:1500]}\n\n"
                    f"User selected: {opt}. Proceed."
                )
            keyboard.append(
                [
                    {
                        "text": f"🎯 {opt}",
                        "callback_data": f"act:{save_ctx(callback_text)}",
                    }
                ]
            )
    return {"inline_keyboard": keyboard} if keyboard else None
