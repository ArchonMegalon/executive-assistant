from __future__ import annotations

import asyncio

from app.contracts.llm_gateway import ask_text as gateway_ask_text


def humanize_agent_report(report: str) -> str:
    raw = str(report or "").strip()
    if not raw:
        return raw
    lowered = raw.lower()
    if "no such file or directory: 'docker'" in lowered or "executable file not found" in lowered:
        return "⚠️ Execution backend is temporarily unavailable. Please try again in a moment."
    if (
        "api key expired" in lowered
        or "api_key_invalid" in lowered
        or "litellm.badrequesterror" in lowered
        or "vertex_ai_betaexception" in lowered
    ):
        return "⚠️ AI provider authentication failed. Please retry shortly while credentials refresh."
    if lowered.startswith("error:") or "badrequesterror" in lowered:
        return "⚠️ I could not complete that request right now. Please try again."
    return raw


async def ask_llm_text(prompt: str, *, tenant: str = "", person_id: str = "") -> str:
    return await asyncio.to_thread(
        gateway_ask_text,
        str(prompt),
        task_type="profile_summary",
        purpose="chat_assist",
        data_class="derived_summary",
        tenant=str(tenant or ""),
        person_id=str(person_id or ""),
    )
