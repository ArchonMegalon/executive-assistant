from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


CallbackHandler = Callable[[dict[str, Any]], Awaitable[None]]
CommandHandler = Callable[[int, str, dict[str, Any]], Awaitable[None]]
IntentHandler = Callable[[int, dict[str, Any]], Awaitable[None]]


async def route_update(
    u_data: dict[str, Any],
    *,
    on_callback: CallbackHandler,
    on_command: CommandHandler,
    on_intent: IntentHandler,
) -> None:
    if "callback_query" in u_data:
        await on_callback(u_data["callback_query"])
        return

    msg = None
    if "message" in u_data:
        msg = u_data["message"]
    elif "channel_post" in u_data:
        msg = u_data["channel_post"]
    elif "edited_channel_post" in u_data:
        msg = u_data["edited_channel_post"]
    if not msg:
        return

    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return

    cmd_text = str(msg.get("text") or msg.get("caption") or "").strip()
    if cmd_text.startswith("/"):
        await on_command(int(chat_id), cmd_text, msg)
        return

    if msg.get("text") or msg.get("photo") or msg.get("document") or msg.get("voice") or msg.get("audio"):
        await on_intent(int(chat_id), msg)
