from __future__ import annotations

import asyncio
import html
import re
import time
from typing import Any, Awaitable, Callable

from app.briefings import get_val
from app.chat_assist import humanize_agent_report
from app.execution import (
    append_execution_event,
    build_plan_steps,
    compile_intent_spec,
    create_execution_session,
    finalize_execution_session,
    mark_execution_session_running,
    mark_execution_step_status,
)
from app.gog import gog_scout
from app.intake.calendar_events import normalize_extracted_calendar_events
from app.intake.calendar_import_result import build_calendar_import_response
from app.memory import get_button_context, save_button_context
from app.open_loops import OpenLoops
from app.poll_ui import build_dynamic_ui, clean_html_for_telegram
from app.skills.runtime_action_exec import execute_typed_action


def _safe_err(err: Any) -> str:
    return html.escape(str(err), quote=False)


def _dispatch_skill(
    *,
    skill_key: str,
    operation: str,
    tenant: str,
    chat_id: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.skills.router import dispatch_skill_operation

    return dispatch_skill_operation(
        skill_key=skill_key,
        operation=operation,
        tenant=tenant,
        chat_id=chat_id,
        payload=dict(payload or {}),
    )


async def _execute_typed_action_callback(
    *,
    tg,
    chat_id: int,
    tenant_name: str,
    action_row: dict[str, Any],
) -> None:
    action = dict(action_row or {})
    action_type = str(action.get("action_type") or "").strip() or "typed_action"
    intent_spec = compile_intent_spec(
        text=f"Execute typed action {action_type}",
        tenant=str(tenant_name or ""),
        chat_id=int(chat_id),
        has_url=False,
    )
    intent_spec["action_type"] = action_type
    plan_steps = build_plan_steps(intent_spec=intent_spec)
    session_id = create_execution_session(
        tenant=str(tenant_name or ""),
        chat_id=int(chat_id),
        intent_spec=intent_spec,
        plan_steps=plan_steps,
        source="typed_action_callback",
        correlation_id=(
            f"{tenant_name}:{chat_id}:typed_action:{str(action.get('id') or int(time.time() * 1000))}"
        ),
    )
    current_step = "compile_intent"
    if session_id:
        mark_execution_session_running(session_id)
        mark_execution_step_status(session_id, "compile_intent", "completed", result=intent_spec)
        append_execution_event(
            session_id,
            event_type="typed_action_received",
            message="Typed action callback execution started.",
            payload={"action_type": action_type},
        )
    try:
        if session_id and any(str((row or {}).get("step_key") or "") == "safety_gate" for row in plan_steps):
            mark_execution_step_status(
                session_id,
                "safety_gate",
                "running",
                result={"gate_mode": "typed_action", "reason": "approval-required intent class"},
            )
            mark_execution_step_status(
                session_id,
                "safety_gate",
                "completed",
                result={"gate_mode": "typed_action", "decision": "continue"},
            )
        current_step = "execute_intent"
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "running",
                evidence={"action_type": action_type},
            )
        executed = execute_typed_action(
            tenant_name=str(tenant_name or ""),
            chat_id=int(chat_id),
            action_row=action,
            dispatch_skill=_dispatch_skill,
        )
        result = executed.get("result") if isinstance(executed.get("result"), dict) else {}
        exec_ok = bool((result or {}).get("ok"))
        exec_status = "completed" if exec_ok else "failed"
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                exec_status,
                result={"action_status": (result or {}).get("status"), "ok": exec_ok},
            )
            append_execution_event(
                session_id,
                event_type="typed_action_executed",
                level="info" if exec_ok else "error",
                message="Typed action execution finished.",
                payload={"action_type": action_type, "ok": exec_ok, "status": (result or {}).get("status")},
            )

        text = str(executed.get("text") or "").strip() or "⚠️ Action execution produced no response."
        current_step = "render_reply"
        if session_id:
            mark_execution_step_status(
                session_id,
                "render_reply",
                "running",
                result={"payload_chars": len(text)},
            )
        await tg.send_message(chat_id, text, parse_mode="HTML")
        if session_id:
            mark_execution_step_status(
                session_id,
                "render_reply",
                "completed",
                result={"payload_chars": len(text)},
            )
            finalize_execution_session(
                session_id,
                status="completed" if exec_ok else "failed",
                outcome={
                    "result": "delivered",
                    "action_type": action_type,
                    "action_status": (result or {}).get("status"),
                    "ok": exec_ok,
                },
                last_error=None if exec_ok else str((result or {}).get("status") or "typed_action_failed"),
            )
        return None
    except Exception as err:
        if session_id:
            mark_execution_step_status(
                session_id,
                current_step,
                "failed",
                error_text=_safe_err(err),
            )
            finalize_execution_session(
                session_id,
                status="failed",
                outcome={"result": "failed", "action_type": action_type, "failed_step": current_step},
                last_error=_safe_err(err),
            )
        return await tg.send_message(chat_id, f"❌ Action execution failed: {_safe_err(err)}", parse_mode="HTML")


async def handle_callback_command(
    *,
    tg,
    cb: dict[str, Any],
    check_security: Callable[[int], Awaitable[tuple[str, dict[str, Any] | None]]],
    auth_sessions,
    trigger_auth_flow: Callable[[int, str, dict[str, Any], str], Awaitable[None]],
) -> None:
    chat_id = cb.get("message", {}).get("chat", {}).get("id")
    tenant_name, tenant_cfg = await check_security(chat_id)
    if not tenant_cfg:
        return await tg.answer_callback_query(cb["id"], text="Unauthorized.", show_alert=True)

    if cb["data"] == "cmd_auth_custom":
        await tg.answer_callback_query(cb["id"])
        return await tg.send_message(chat_id, "Type: <code>/auth your.email@gmail.com</code>", parse_mode="HTML")

    if cb["data"].startswith("auth_cb:"):
        ctx_id = cb["data"].split(":")[1]
        payload = get_button_context(ctx_id)
        try:
            await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        if not payload:
            return await tg.send_message(chat_id, "⚠️ Auth session expired. Please type /auth again.")
        try:
            scope_type, email = payload.split("|", 1)
        except ValueError:
            return await tg.send_message(chat_id, "⚠️ Invalid auth payload.")
        if scope_type == "cancel":
            auth_sessions.clear(chat_id)
            return await tg.send_message(chat_id, "🛑 Auth cancelled.")
        await trigger_auth_flow(chat_id, email, tenant_cfg, scopes=scope_type)
        return

    if cb["data"] == "clear_shopping":
        OpenLoops.clear_shopping(tenant_name)
        try:
            await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        return await tg.send_message(chat_id, "✅ <b>Shopping List marked as Done.</b>", parse_mode="HTML")

    if cb["data"].startswith("mark_paid:"):
        OpenLoops.remove_payment(tenant_name, cb["data"].split(":")[1])
        try:
            await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        return await tg.send_message(chat_id, "✅ <b>Rechnung als bezahlt markiert.</b>", parse_mode="HTML")

    if cb["data"].startswith("drop_pay:"):
        OpenLoops.remove_payment(tenant_name, cb["data"].split(":")[1])
        try:
            await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        return await tg.send_message(chat_id, "🗑️ <b>Zahlungs-Loop gelöscht.</b>", parse_mode="HTML")

    if cb["data"].startswith("exec_cal:"):
        cid = cb["data"].split(":")[1]
        cal_data = OpenLoops.get_calendar(tenant_name, cid)
        if cal_data:
            OpenLoops.remove_calendar(tenant_name, cid)
            try:
                await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
            except Exception:
                pass
            from app.briefings import safe_gog
            from app.calendar_store import create_import, commit_import

            t_openclaw = get_val(tenant_cfg, "openclaw_container", "")
            t_account = get_val(tenant_cfg, "google_account", "")
            imported = 0
            failed = 0
            normalized_events: list[dict[str, str]] = []
            persisted = 0
            persist_status = "not_attempted"
            persist_err = ""
            events_for_import = normalize_extracted_calendar_events(cal_data.get("events") or [])
            if not events_for_import:
                await tg.send_message(
                    chat_id,
                    "⚠️ <b>Calendar Import Failed.</b>\nNo valid event timestamps were found in this request.",
                    parse_mode="HTML",
                )
                return
            for ev in events_for_import:
                try:
                    await safe_gog(
                        t_openclaw,
                        [
                            "calendar",
                            "events",
                            "add",
                            str(ev.get("title", "")),
                            "--start",
                            str(ev.get("start", "")),
                            "--end",
                            str(ev.get("end", "")),
                            "--location",
                            str(ev.get("location", "")),
                            "--calendar",
                            "Executive Assistant",
                        ],
                        t_account,
                        timeout=10.0,
                    )
                    imported += 1
                    normalized_events.append(
                        {
                            "title": str(ev.get("title", "")),
                            "start_ts": str(ev.get("start", "")),
                            "end_ts": str(ev.get("end", "")),
                            "location": str(ev.get("location", "")),
                            "notes": "",
                        }
                    )
                except Exception:
                    failed += 1

            if normalized_events:
                try:
                    imp_id = create_import(
                        tenant=tenant_name,
                        source_type="telegram_image_import",
                        source_id=f"exec_cal:{cid}",
                        filename="open_loop_import",
                        extracted={"normalized_events": normalized_events},
                        preview="Imported via Open Loops execute",
                    )
                    persisted, persist_status = commit_import(tenant_name, imp_id)
                except Exception as err:
                    persist_status = "failed"
                    persist_err = str(err)[:120]

            total = len(events_for_import)
            response = build_calendar_import_response(
                imported=imported,
                total=total,
                persisted=persisted,
                persist_status=persist_status,
                failed=failed,
                persist_err=persist_err,
            )
            await tg.send_message(chat_id, response.text, parse_mode=response.parse_mode)
        return

    if cb["data"].startswith("drop_cal:"):
        cid = cb["data"].split(":")[1]
        OpenLoops.remove_calendar(tenant_name, cid)
        await tg.answer_callback_query(cb["id"], text="Import Dropped!")
        try:
            await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        return await tg.send_message(chat_id, "🛑 <b>Calendar Import Discarded.</b>", parse_mode="HTML")

    if cb["data"].startswith("act:"):
        action_id = cb["data"][4:]
        rich_prompt = get_button_context(action_id)
        if not rich_prompt:
            from app.actions import consume_action

            typed_action = consume_action(str(tenant_name or ""), str(action_id or ""))
            if typed_action:
                try:
                    await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
                except Exception:
                    pass
                await tg.answer_callback_query(cb["id"], text="Executing...")
                return await _execute_typed_action_callback(
                    tg=tg,
                    chat_id=int(chat_id),
                    tenant_name=str(tenant_name or ""),
                    action_row=dict(typed_action if isinstance(typed_action, dict) else {}),
                )
            return await tg.answer_callback_query(cb["id"], text="⚠️ Action expired.", show_alert=True)
        btn_txt = "Task"
        for row in cb.get("message", {}).get("reply_markup", {}).get("inline_keyboard", []):
            for btn in row:
                if btn.get("callback_data") == cb.get("data"):
                    btn_txt = btn.get("text", "Task")
        try:
            await tg.edit_message_reply_markup(chat_id, cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        await tg.answer_callback_query(cb["id"], text="Executing...")
        clean_btn = btn_txt.replace("✅", "").replace("⚙️", "").replace("🎯", "").strip()
        is_rejection = any((w in clean_btn.lower() for w in ["do not", "no", "cancel", "stop", "reject", "abort", "skip"]))
        if is_rejection:
            enhanced_prompt = f"EXECUTE: {rich_prompt}\nCRITICAL UPDATE: The user REJECTED the previous proposal."
        else:
            enhanced_prompt = (
                f"EXECUTE: {rich_prompt}\nCRITICAL INSTRUCTIONS:\n1. Use google account '{get_val(tenant_cfg, 'google_account', '')}'."
            )
        legacy_current_step = "compile_intent"
        legacy_intent = compile_intent_spec(
            text=f"Execute button context action: {clean_btn}",
            tenant=str(tenant_name or ""),
            chat_id=int(chat_id),
            has_url=bool(re.search(r"https?://", str(rich_prompt or ""), flags=re.IGNORECASE)),
        )
        legacy_intent["action_type"] = "legacy_button_context"
        legacy_intent["action_id"] = str(action_id or "")
        legacy_plan_steps = build_plan_steps(intent_spec=legacy_intent)
        legacy_session_id = create_execution_session(
            tenant=str(tenant_name or ""),
            chat_id=int(chat_id),
            intent_spec=legacy_intent,
            plan_steps=legacy_plan_steps,
            source="button_context_action",
            correlation_id=f"{tenant_name}:{chat_id}:button_action:{str(action_id or int(time.time() * 1000))}",
        )
        if legacy_session_id:
            mark_execution_session_running(legacy_session_id)
            mark_execution_step_status(legacy_session_id, "compile_intent", "completed", result=legacy_intent)
            append_execution_event(
                legacy_session_id,
                event_type="button_action_received",
                message="Legacy button-context action execution started.",
                payload={"action_id": str(action_id or ""), "button": clean_btn},
            )
        res = await tg.send_message(
            chat_id,
            f"🚀 <b>Executing:</b> {clean_btn}...\n\n▶️ <b>Analyzing task requirements...</b>",
            parse_mode="HTML",
        )

        async def _ui_updater(msg: str) -> None:
            try:
                await tg.edit_message_text(
                    chat_id,
                    res["message_id"],
                    f"🚀 <b>Executing:</b> {clean_btn}...\n\n▶️ <b>{msg[:80]}...</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception:
                pass

        try:
            if legacy_session_id and any(str((row or {}).get("step_key") or "") == "safety_gate" for row in legacy_plan_steps):
                mark_execution_step_status(
                    legacy_session_id,
                    "safety_gate",
                    "running",
                    result={"gate_mode": "legacy_button", "reason": "approval-required intent class"},
                )
                mark_execution_step_status(
                    legacy_session_id,
                    "safety_gate",
                    "completed",
                    result={"gate_mode": "legacy_button", "decision": "continue"},
                )
            legacy_current_step = "execute_intent"
            if legacy_session_id:
                mark_execution_step_status(
                    legacy_session_id,
                    "execute_intent",
                    "running",
                    evidence={"button": clean_btn, "action_id": str(action_id or "")},
                )
            report = await asyncio.wait_for(
                gog_scout(
                    get_val(tenant_cfg, "openclaw_container", ""),
                    enhanced_prompt,
                    get_val(tenant_cfg, "google_account", ""),
                    _ui_updater,
                    task_name=f"Button: {clean_btn}",
                ),
                timeout=240.0,
            )
            if legacy_session_id:
                mark_execution_step_status(
                    legacy_session_id,
                    "execute_intent",
                    "completed",
                    result={"report_chars": len(str(report or "")), "report_empty": not bool(str(report or "").strip())},
                )
            kb_dict = build_dynamic_ui(report, enhanced_prompt, save_ctx=save_button_context)
            clean_rep = clean_html_for_telegram(
                re.sub(r"\[OPTIONS:.*?\]", "", humanize_agent_report(report)).replace("[YES/NO]", "")
            )
            if not clean_rep.strip() or clean_rep.strip() == "[]":
                clean_rep = "✅ Task executed successfully!"
            legacy_current_step = "render_reply"
            if legacy_session_id:
                mark_execution_step_status(
                    legacy_session_id,
                    "render_reply",
                    "running",
                    result={"payload_chars": len(clean_rep)},
                )
            try:
                await tg.edit_message_text(
                    chat_id,
                    res["message_id"],
                    f"🎯 <b>Result:</b>\n\n{clean_rep[:3500]}",
                    parse_mode="HTML",
                    reply_markup=kb_dict,
                )
            except Exception:
                await tg.edit_message_text(
                    chat_id,
                    res["message_id"],
                    f"🎯 <b>Result:</b>\n\n{_safe_err(clean_rep).strip()[:3500]}",
                    reply_markup=kb_dict,
                )
            if legacy_session_id:
                mark_execution_step_status(
                    legacy_session_id,
                    "render_reply",
                    "completed",
                    result={"payload_chars": len(clean_rep)},
                )
                finalize_execution_session(
                    legacy_session_id,
                    status="completed",
                    outcome={
                        "result": "delivered",
                        "action_type": "legacy_button_context",
                        "button": clean_btn,
                    },
                )
        except Exception as task_err:
            if legacy_session_id:
                mark_execution_step_status(
                    legacy_session_id,
                    legacy_current_step,
                    "failed",
                    error_text=_safe_err(task_err),
                )
                finalize_execution_session(
                    legacy_session_id,
                    status="failed",
                    outcome={
                        "result": "failed",
                        "action_type": "legacy_button_context",
                        "failed_step": legacy_current_step,
                    },
                    last_error=_safe_err(task_err),
                )
            await tg.send_message(chat_id, f"❌ Task Failed: {_safe_err(task_err)}")
