from __future__ import annotations

import html
import json
import os
import re
from typing import Awaitable, Callable

BRAIN_FILE = "/attachments/brain.json"


def _safe_err(err: Exception) -> str:
    return html.escape(str(err), quote=False)


async def show_brain(*, tg, chat_id: int) -> None:
    try:
        if not os.path.exists(BRAIN_FILE):
            await tg.send_message(chat_id, "🧠 Brain is empty. Use /remember <text>.")
            return
        with open(BRAIN_FILE, "r", encoding="utf-8") as f:
            brain = json.load(f)
        if not brain:
            await tg.send_message(chat_id, "🧠 Brain is empty.")
            return
        lines = ["🧠 <b>Active Memories:</b>"]
        for key, value in brain.items():
            lines.append(f"• <b>{key}</b>: {value}")
        await tg.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
    except Exception as err:
        await tg.send_message(chat_id, f"⚠️ Brain error: {_safe_err(err)}")


async def remember_fact(
    *,
    tg,
    chat_id: int,
    tenant_name: str,
    command_text: str,
    ask_llm_text: Callable[..., Awaitable[str]],
) -> None:
    rem_text = str(command_text or "")[len("/remember") :].strip()
    if not rem_text:
        await tg.send_message(chat_id, "Usage: /remember <fact to remember>")
        return

    res = await tg.send_message(chat_id, "🧠 <i>Normalizing memory...</i>", parse_mode="HTML")
    try:
        prompt = (
            "Extract a short 3-5 word title and the core fact from this text. "
            "Return STRICT JSON: {\"title\": \"...\", \"fact\": \"...\"}. "
            f"Text: {rem_text}"
        )
        out = await ask_llm_text(
            prompt,
            tenant=str(tenant_name or ""),
            person_id=str(chat_id),
        )
        match = re.search(r"\{[\s\S]*\}", str(out or ""))
        if not match:
            await tg.edit_message_text(
                chat_id,
                res["message_id"],
                "⚠️ Failed to parse memory via AI.",
            )
            return

        data = json.loads(match.group(0))
        title = str(data.get("title") or "").strip()
        fact = str(data.get("fact") or "").strip()
        if not title or not fact:
            await tg.edit_message_text(
                chat_id,
                res["message_id"],
                "⚠️ Failed to parse memory via AI.",
            )
            return

        brain: dict[str, str] = {}
        if os.path.exists(BRAIN_FILE):
            with open(BRAIN_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    brain = {str(k): str(v) for k, v in loaded.items()}

        brain[title] = fact
        with open(BRAIN_FILE, "w", encoding="utf-8") as f:
            json.dump(brain, f, ensure_ascii=False)

        await tg.edit_message_text(
            chat_id,
            res["message_id"],
            f"✅ <b>Remembered:</b> {title}",
            parse_mode="HTML",
        )
    except Exception as err:
        await tg.edit_message_text(
            chat_id,
            res["message_id"],
            f"⚠️ Error saving memory: {_safe_err(err)}",
        )
