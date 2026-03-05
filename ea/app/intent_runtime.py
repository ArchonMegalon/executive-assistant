from __future__ import annotations

import os
import re
import time
from typing import Any, Callable

from app.actions import create_action
from app.briefings import get_val
from app.chat_assist import humanize_agent_report
from app.execution import (
    append_execution_event,
    attach_approval_gate_action,
    build_plan_steps,
    compile_intent_spec,
    create_approval_gate,
    create_execution_session,
    finalize_execution_session,
    mark_approval_gate_decision,
    mark_execution_session_running,
    mark_execution_step_status,
)
from app.gog import gog_scout
from app.memory import save_button_context
from app.planner.step_executor import run_reasoning_step
from app.poll_ui import build_dynamic_ui, clean_html_for_telegram


_PLANNER_PRE_EXEC_STEPS = {
    "collect_intake_context",
    "compile_prompt_pack",
    "prepare_draft_context",
    "prepare_multimodal_context",
    "analyze_trip_commitment",
    "compare_travel_options",
    "verify_payment_context",
    "gather_project_context",
    "review_health_context",
}


def _run_planner_pre_execution_steps(
    *,
    session_id: str,
    plan_steps: list[dict[str, Any]],
    intent_spec: dict[str, Any],
) -> None:
    if not session_id:
        return
    domain = str((intent_spec or {}).get("domain") or "")
    task_type = str((intent_spec or {}).get("task_type") or "")
    objective = str((intent_spec or {}).get("objective") or "")[:200]
    for row in list(plan_steps or []):
        step_key = str((row or {}).get("step_key") or "").strip()
        if step_key not in _PLANNER_PRE_EXEC_STEPS:
            continue
        mark_execution_step_status(
            session_id,
            step_key,
            "running",
            evidence={"domain": domain, "task_type": task_type},
        )
        mark_execution_step_status(
            session_id,
            step_key,
            "completed",
            result={
                "planner_step": step_key,
                "status": "deterministic_context_ready",
                "domain": domain,
                "task_type": task_type,
                "objective_preview": objective,
            },
        )
        append_execution_event(
            session_id,
            event_type="planner_context_step_completed",
            message=f"Planner pre-execution step completed: {step_key}",
            payload={"step_key": step_key, "domain": domain, "task_type": task_type},
        )


async def execute_approved_intent_action(
    *,
    tg,
    chat_id: int,
    tenant_name: str,
    tenant_cfg: dict[str, Any],
    action_payload: dict[str, Any],
    safe_err: Callable[[Any], str],
) -> dict[str, Any]:
    tenant_key = str(tenant_name or "")
    payload = dict(action_payload or {})
    session_id = str(payload.get("session_id") or "").strip()
    approval_gate_id = str(payload.get("approval_gate_id") or "").strip()
    prompt = str(payload.get("prompt") or "").strip()
    intent_text = str(payload.get("intent_text") or "").strip()
    if not prompt:
        prompt = f"EXECUTE: Answer or execute the user request: '{intent_text}'. Be concise."
    t_openclaw = get_val(
        tenant_cfg,
        "openclaw_container",
        os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "openclaw-gateway"),
    )
    active_res = await tg.send_message(chat_id, "✅ <b>Approval received. Executing request...</b>", parse_mode="HTML")

    async def _ui_updater(msg: str) -> None:
        try:
            await tg.edit_message_text(
                chat_id,
                active_res["message_id"],
                f"▶️ <b>{msg[:80]}...</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    if session_id:
        if approval_gate_id:
            mark_approval_gate_decision(
                approval_gate_id,
                decision_status="approved",
                decision_payload={
                    "source": "typed_action_callback",
                    "chat_id": int(chat_id),
                    "tenant": tenant_key,
                },
            )
        mark_execution_session_running(session_id)
        mark_execution_step_status(
            session_id,
            "safety_gate",
            "running",
            result={"gate_mode": "explicit_callback", "decision": "approval_received"},
        )
        mark_execution_step_status(
            session_id,
            "safety_gate",
            "completed",
            result={"gate_mode": "explicit_callback", "decision": "approved"},
        )
        append_execution_event(
            session_id,
            event_type="approval_granted",
            message="Explicit approval callback granted execution.",
            payload={"tenant": tenant_key, "approval_gate_id": approval_gate_id},
        )

    current_step = "execute_intent"
    try:
        if session_id:
            mark_execution_step_status(session_id, "execute_intent", "running")
        report = await run_reasoning_step(
            container=t_openclaw,
            prompt=prompt,
            google_account=get_val(tenant_cfg, "google_account", ""),
            ui_updater=_ui_updater,
            task_name="Intent: Approved Free Text",
            timeout_sec=240.0,
            runner=gog_scout,
        )
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "completed",
                result={"report_chars": len(str(report or ""))},
            )
        kb_dict = build_dynamic_ui(report, prompt, save_ctx=save_button_context)
        clean_rep = clean_html_for_telegram(
            re.sub(r"\[OPTIONS:.*?\]", "", humanize_agent_report(report)).replace("[YES/NO]", "")
        )
        if not clean_rep.strip() or clean_rep.strip() == "[]":
            clean_rep = "✅ Task executed successfully!"
        current_step = "render_reply"
        if session_id:
            mark_execution_step_status(session_id, "render_reply", "running")
        try:
            await tg.edit_message_text(
                chat_id,
                active_res["message_id"],
                f"🎯 <b>Result:</b>\n\n{clean_rep[:3500]}",
                parse_mode="HTML",
                reply_markup=kb_dict,
            )
        except Exception:
            plain_txt = (
                re.sub("<[^>]+>", "", clean_rep)
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
            )
            if len(plain_txt) > 4000:
                plain_txt = plain_txt[:4000] + "\n...[truncated]"
            await tg.edit_message_text(
                chat_id,
                active_res["message_id"],
                f"🎯 <b>Result:</b>\n\n{plain_txt}",
                parse_mode=None,
                reply_markup=kb_dict,
            )
        if session_id:
            mark_execution_step_status(
                session_id,
                "render_reply",
                "completed",
                result={"payload_chars": len(str(clean_rep or ""))},
            )
            finalize_execution_session(
                session_id,
                status="completed",
                outcome={
                    "result": "delivered",
                    "payload_chars": len(str(clean_rep or "")),
                    "report_chars": len(str(report or "")),
                    "approval_mode": "explicit_callback",
                },
            )
        return {
            "ok": True,
            "status": "completed",
            "text": f"🎯 <b>Result:</b>\n\n{clean_rep[:3500]}",
            "report_chars": len(str(report or "")),
        }
    except Exception as task_err:
        if session_id:
            mark_execution_step_status(
                session_id,
                current_step,
                "failed",
                error_text=safe_err(task_err),
            )
            append_execution_event(
                session_id,
                level="error",
                event_type="session_failed",
                message="Approved free-text execution failed.",
                payload={"step": current_step},
            )
            finalize_execution_session(
                session_id,
                status="failed",
                last_error=safe_err(task_err),
                outcome={"result": "failed", "failed_step": current_step, "approval_mode": "explicit_callback"},
            )
        return {"ok": False, "status": "failed", "text": f"❌ Agent Failed: {safe_err(task_err)}"}


async def handle_free_text_intent(
    *,
    tg,
    chat_id: int,
    tenant_name: str,
    text: str,
    tenant_cfg: dict[str, Any],
    safe_err: Callable[[Any], str],
) -> None:
    text_lower = str(text or "").lower()
    tenant_key = str(tenant_name or "")
    t_openclaw = get_val(
        tenant_cfg,
        "openclaw_container",
        os.environ.get("EA_DEFAULT_OPENCLAW_CONTAINER", "openclaw-gateway"),
    )
    active_res = await tg.send_message(chat_id, "▶️ <b>Analyzing request...</b>", parse_mode="HTML")
    urls = re.findall(r"(https?://[^\s]+)", text)
    intent_spec = compile_intent_spec(text=text, tenant=tenant_key, chat_id=chat_id, has_url=bool(urls))
    plan_steps = build_plan_steps(intent_spec=intent_spec)
    session_id = create_execution_session(
        tenant=tenant_key,
        chat_id=chat_id,
        intent_spec=intent_spec,
        plan_steps=plan_steps,
        source="telegram_free_text",
        correlation_id=f"{tenant_key}:{chat_id}:{int(time.time() * 1000)}",
    )
    current_step = "compile_intent"
    if session_id:
        mark_execution_session_running(session_id)
        mark_execution_step_status(session_id, "compile_intent", "completed", result=intent_spec)
        append_execution_event(
            session_id,
            event_type="intent_compiled",
            message="Intent compiled from free-text request.",
            payload={"domain": intent_spec.get("domain"), "intent_type": intent_spec.get("intent_type")},
        )
    if urls and any((w in text_lower for w in ["read", "scrape", "summarize", "check", "extract", "what"])):
        from app.tools.browseract import scrape_url

        try:
            await tg.edit_message_text(
                chat_id,
                active_res["message_id"],
                "🌐 <b>Scraping website with BrowserAct...</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        current_step = "gather_evidence"
        if session_id:
            mark_execution_step_status(
                session_id,
                "gather_evidence",
                "running",
                evidence={"url": urls[0]},
            )
        try:
            scraped_data = await scrape_url(urls[0])
        except Exception as scrape_err:
            if session_id:
                mark_execution_step_status(
                    session_id,
                    "gather_evidence",
                    "failed",
                    error_text=safe_err(scrape_err),
                    evidence={"url": urls[0]},
                )
                append_execution_event(
                    session_id,
                    level="error",
                    event_type="evidence_failed",
                    message="URL evidence scrape failed.",
                    payload={"url": urls[0]},
                )
            raise
        if session_id:
            mark_execution_step_status(
                session_id,
                "gather_evidence",
                "completed",
                evidence={"url": urls[0], "snippet_chars": len(str(scraped_data)[:3000])},
            )
            append_execution_event(
                session_id,
                event_type="evidence_collected",
                message="URL evidence collected for intent execution.",
                payload={"url": urls[0]},
            )
        prompt = (
            "EXECUTE: The user sent a link. I scraped it for you using BrowserAct. "
            f"Here is the website content:\n\n{str(scraped_data)[:3000]}\n\n"
            f"User request: '{text}'. Be concise."
        )
    else:
        prompt = f"EXECUTE: Answer or execute the user request: '{text}'. Be concise."

    async def _ui_updater(msg: str) -> None:
        try:
            await tg.edit_message_text(
                chat_id,
                active_res["message_id"],
                f"▶️ <b>{msg[:80]}...</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    requires_approval = bool((intent_spec or {}).get("autonomy_level") == "approval_required")
    if session_id:
        _run_planner_pre_execution_steps(
            session_id=session_id,
            plan_steps=list(plan_steps or []),
            intent_spec=dict(intent_spec or {}),
        )
    if requires_approval:
        action_id = ""
        approval_gate_id = ""
        if session_id:
            mark_execution_step_status(
                session_id,
                "safety_gate",
                "running",
                result={"gate_mode": "explicit_callback", "reason": "high_risk_intent"},
            )
            approval_gate_id = str(
                create_approval_gate(
                    session_id=str(session_id or ""),
                    tenant=tenant_key,
                    chat_id=int(chat_id),
                    approval_class=str((intent_spec or {}).get("approval_class") or "explicit_callback_required"),
                    decision_payload={
                        "intent_text": str(text or "")[:500],
                        "domain": str((intent_spec or {}).get("domain") or ""),
                    },
                )
                or ""
            )
        try:
            action_id = create_action(
                tenant=tenant_key,
                action_type="intent:approval_execute",
                payload={
                    "session_id": str(session_id or ""),
                    "approval_gate_id": str(approval_gate_id or ""),
                    "intent_text": str(text or "")[:2000],
                    "prompt": str(prompt or "")[:8000],
                    "tenant": tenant_key,
                    "chat_id": int(chat_id),
                },
                days=1,
                session_id=str(session_id or "") if session_id else None,
                approval_gate_id=str(approval_gate_id or "") if approval_gate_id else None,
            )
        except Exception:
            action_id = ""
        if approval_gate_id and action_id:
            attach_approval_gate_action(approval_gate_id, action_id)
        elif approval_gate_id and not action_id:
            mark_approval_gate_decision(
                approval_gate_id,
                decision_status="staging_failed",
                decision_payload={"reason": "typed_action_create_failed"},
            )
        if session_id:
            mark_execution_step_status(
                session_id,
                "safety_gate",
                "completed",
                result={
                    "gate_mode": "explicit_callback",
                    "decision": "awaiting_approval",
                    "action_id": action_id,
                    "approval_gate_id": approval_gate_id,
                },
            )
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "queued",
                result={
                    "blocked_reason": "awaiting_approval",
                    "action_id": action_id,
                    "approval_gate_id": approval_gate_id,
                },
            )
            append_execution_event(
                session_id,
                event_type="approval_requested",
                message="High-risk free-text intent staged for explicit approval callback.",
                payload={"action_id": action_id, "approval_gate_id": approval_gate_id, "tenant": tenant_key},
            )
            finalize_execution_session(
                session_id,
                status="partial",
                outcome={
                    "result": "awaiting_approval",
                    "action_id": action_id,
                    "approval_gate_id": approval_gate_id,
                    "approval_mode": "explicit_callback",
                },
            )
        kb = (
            {"inline_keyboard": [[{"text": "✅ Approve & Run", "callback_data": f"act:{action_id}"}]]}
            if action_id
            else None
        )
        prompt_txt = (
            "🔐 <b>Approval required.</b>\n\n"
            "This request includes high-risk intent. Tap <b>Approve & Run</b> to execute."
        )
        if not action_id:
            prompt_txt += "\n\n⚠️ Could not stage approval action. Please retry."
        await tg.edit_message_text(
            chat_id,
            active_res["message_id"],
            prompt_txt,
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    try:
        current_step = "execute_intent"
        if session_id:
            mark_execution_step_status(session_id, "execute_intent", "running")
        report = await run_reasoning_step(
            container=t_openclaw,
            prompt=prompt,
            google_account=get_val(tenant_cfg, "google_account", ""),
            ui_updater=_ui_updater,
            task_name="Intent: Free Text",
            timeout_sec=240.0,
            runner=gog_scout,
        )
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "completed",
                result={"report_chars": len(str(report or ""))},
            )
        kb_dict = build_dynamic_ui(report, prompt, save_ctx=save_button_context)
        clean_rep = clean_html_for_telegram(
            re.sub(r"\[OPTIONS:.*?\]", "", humanize_agent_report(report)).replace("[YES/NO]", "")
        )
        if not clean_rep.strip() or clean_rep.strip() == "[]":
            clean_rep = "✅ Task executed successfully!"
        current_step = "render_reply"
        if session_id:
            mark_execution_step_status(session_id, "render_reply", "running")
        try:
            await tg.edit_message_text(
                chat_id,
                active_res["message_id"],
                f"🎯 <b>Result:</b>\n\n{clean_rep[:3500]}",
                parse_mode="HTML",
                reply_markup=kb_dict,
            )
        except Exception:
            plain_txt = (
                re.sub("<[^>]+>", "", clean_rep)
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
            )
            if len(plain_txt) > 4000:
                plain_txt = plain_txt[:4000] + "\n...[truncated]"
            try:
                await tg.edit_message_text(
                    chat_id,
                    active_res["message_id"],
                    f"🎯 <b>Result:</b>\n\n{plain_txt}",
                    parse_mode=None,
                    reply_markup=kb_dict,
                )
            except Exception:
                pass
        if session_id:
            mark_execution_step_status(
                session_id,
                "render_reply",
                "completed",
                result={"payload_chars": len(str(clean_rep or ""))},
            )
            finalize_execution_session(
                session_id,
                status="completed",
                outcome={
                    "result": "delivered",
                    "payload_chars": len(str(clean_rep or "")),
                    "report_chars": len(str(report or "")),
                },
            )
    except Exception as task_err:
        if session_id:
            mark_execution_step_status(
                session_id,
                current_step,
                "failed",
                error_text=safe_err(task_err),
            )
            append_execution_event(
                session_id,
                level="error",
                event_type="session_failed",
                message="Free-text execution failed.",
                payload={"step": current_step},
            )
            finalize_execution_session(
                session_id,
                status="failed",
                last_error=safe_err(task_err),
                outcome={"result": "failed", "failed_step": current_step},
            )
        await tg.edit_message_text(
            chat_id,
            active_res["message_id"],
            f"❌ Agent Failed: {safe_err(task_err)}",
            parse_mode="HTML",
        )


__all__ = ["handle_free_text_intent", "execute_approved_intent_action"]
