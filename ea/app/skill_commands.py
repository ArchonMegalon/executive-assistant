from __future__ import annotations

import html
from typing import Any


async def handle_skill_command(
    *,
    tg,
    chat_id: int,
    command_text: str,
    tenant_name: str,
) -> None:
    from app.actions import create_action
    from app.skills.capability_router import build_capability_plan
    from app.skills.registry import list_skills, skill_or_raise

    tokens = str(command_text or "").strip().split()
    if len(tokens) < 2:
        skills = [str(row.get("key") or "") for row in list_skills()]
        avail = ", ".join(sorted([k for k in skills if k])) or "none"
        return await tg.send_message(
            chat_id,
            (
                "Usage: <code>/skill &lt;skill_key&gt; [operation] [notes]</code>\n\n"
                f"Available: <code>{html.escape(avail, quote=False)}</code>"
            ),
            parse_mode="HTML",
        )

    skill_key = str(tokens[1] or "").strip().lower()
    try:
        contract = skill_or_raise(skill_key)
    except Exception:
        return await tg.send_message(
            chat_id,
            f"⚠️ Unknown skill: <code>{html.escape(skill_key, quote=False)}</code>",
            parse_mode="HTML",
        )

    operation = str(tokens[2] or "").strip().lower() if len(tokens) >= 3 else (
        str(contract.operations[0]) if contract.operations else "plan"
    )
    if operation not in tuple(contract.operations):
        return await tg.send_message(
            chat_id,
            (
                f"⚠️ Unsupported operation for <code>{html.escape(skill_key, quote=False)}</code>.\n"
                f"Allowed: <code>{html.escape(', '.join(contract.operations), quote=False)}</code>"
            ),
            parse_mode="HTML",
        )

    notes = " ".join(tokens[3:]).strip()
    action_payload: dict[str, Any] = {"operation": operation, "payload": {}}
    if notes:
        action_payload["payload"]["notes"] = notes[:500]

    act_id = create_action(
        tenant=str(tenant_name or ""),
        action_type=f"skill:{skill_key}",
        payload=action_payload,
        days=2,
    )
    planning_task = str(getattr(contract, "planning_task_type", "") or "").strip().lower() or skill_key
    plan = build_capability_plan(planning_task)
    primary = str((plan or {}).get("primary") or "").strip()
    fallbacks = list((plan or {}).get("fallbacks") or [])
    lines = [
        f"🧩 <b>Skill queued:</b> <code>{html.escape(skill_key, quote=False)}</code> / <code>{html.escape(operation, quote=False)}</code>",
    ]
    if primary:
        lines.append(f"Primary capability: <code>{html.escape(primary, quote=False)}</code>")
    if fallbacks:
        lines.append(f"Fallbacks: <code>{html.escape(', '.join(str(x) for x in fallbacks), quote=False)}</code>")
    if notes:
        lines.append(f"Notes: {html.escape(notes[:160], quote=False)}")
    kb = {"inline_keyboard": [[{"text": "▶️ Execute Skill Plan", "callback_data": f"act:{act_id}"}]]}
    return await tg.send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb,
    )


__all__ = ["handle_skill_command"]
