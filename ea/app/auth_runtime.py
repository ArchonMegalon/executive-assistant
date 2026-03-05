from __future__ import annotations

import asyncio
import os
import re
import time
import traceback
from typing import Any

from app.briefings import get_val
from app.gog import docker_exec
from app.settings import settings


def _openclaw_candidates(tenant_cfg: dict[str, Any]) -> list[str]:
    configured = str(get_val(tenant_cfg, "openclaw_container", "") or "").strip()
    env_default = str(os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "") or "").strip()
    csv_fallback = str(os.environ.get("EA_OPENCLAW_FALLBACK_CONTAINERS", "") or "").strip()
    candidates: list[str] = []
    for raw in [configured, env_default]:
        c = str(raw or "").strip()
        if c and c not in candidates:
            candidates.append(c)
    if csv_fallback:
        for item in csv_fallback.split(","):
            c = str(item or "").strip()
            if c and c not in candidates:
                candidates.append(c)
    for c in ("openclaw-gateway-tibor", "openclaw-gateway-family-girschele", "openclaw-gateway-liz", "openclaw-gateway"):
        if c not in candidates:
            candidates.append(c)
    return candidates


async def trigger_auth_flow(
    *,
    tg,
    chat_id: int,
    email: str,
    tenant_cfg: dict[str, Any],
    scopes: str = "",
    auth_sessions,
    get_admin_chat_id_fn,
) -> None:
    res = await tg.send_message(chat_id, f"🔄 Generating secure OAuth link for <b>{email}</b>...", parse_mode="HTML")
    candidates = _openclaw_candidates(tenant_cfg or {})
    is_admin = bool(get_val(tenant_cfg, "is_admin", False)) or str(chat_id) == str(get_admin_chat_id_fn() or "")
    try:
        scopes_arg = "calendar" if "cal" in scopes else "gmail" if "mail" in scopes else "gmail,calendar,tasks"
        keyring_password = (
            getattr(settings, "gog_keyring_password", None)
            or os.environ.get("GOG_KEYRING_PASSWORD")
            or os.environ.get("EA_GOG_KEYRING_PASSWORD")
        )
        if not keyring_password:
            raise RuntimeError("Missing GOG_KEYRING_PASSWORD")
        last_output = ""
        for t_openclaw in candidates:
            try:
                await docker_exec(t_openclaw, ["pkill", "-f", "gog"], user="root", timeout_s=8.0)
                await asyncio.sleep(0.25)
                await docker_exec(t_openclaw, ["gog", "auth", "remove", email], user="root", timeout_s=10.0)
                await asyncio.sleep(0.25)
                out_str = await docker_exec(
                    t_openclaw,
                    ["gog", "auth", "add", email, "--services", scopes_arg, "--remote", "--step", "1"],
                    user="root",
                    extra_env={"GOG_KEYRING_PASSWORD": keyring_password},
                    timeout_s=18.0,
                )
                m_url = re.search("(https://accounts\\.google\\.com/[^\\s\"\\'><]+)", out_str)
                if m_url:
                    auth_sessions.set(
                        chat_id,
                        {"email": email, "openclaw": t_openclaw, "services": scopes_arg, "ts": time.time()},
                    )
                    admin_note = (
                        f"\n\n💡 <b>Admin Troubleshooting:</b>\nEnsure <code>{email}</code> "
                        "is a Test User in Google Cloud."
                        if is_admin
                        else ""
                    )
                    auth_msg = (
                        "🔗 <b>Authorization Required</b>\n\n"
                        f"1. 👉 <b><a href='{m_url.group(1).replace('&amp;', '&').strip()}'>"
                        "Click here to open Google Login</a></b> 👈\n"
                        f"2. Select <code>{email}</code>.\n"
                        "3. Copy the broken '127.0.0.1' URL from your browser and paste it here."
                        f"{admin_note}"
                    )
                    await tg.edit_message_text(
                        chat_id,
                        res["message_id"],
                        auth_msg,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    return
                last_output = out_str[-1200:]
            except Exception as loop_err:
                last_output = str(loop_err)[-1200:]
        ref = f"AUTH-{int(time.time())}"
        print(f"AUTH ERROR [{ref}] step1_no_url containers={candidates} output={last_output}", flush=True)
        await tg.edit_message_text(
            chat_id,
            res["message_id"],
            f"⚠️ <b>Auth Error.</b>\nReference: <code>{ref}</code>",
            parse_mode="HTML",
        )
    except Exception:
        ref = f"AUTH-{int(time.time())}"
        print(f"AUTH ERROR [{ref}] exception={traceback.format_exc()}", flush=True)
        await tg.edit_message_text(
            chat_id,
            res["message_id"],
            f"⚠️ <b>Auth Error.</b>\nReference: <code>{ref}</code>",
            parse_mode="HTML",
        )
