from __future__ import annotations

import hashlib
import re
import time
from typing import Any


def _domain_from_text(text_lower: str) -> str:
    travel_keywords = ("trip", "flight", "hotel", "airport", "layover", "travel", "route", "itinerary")
    finance_keywords = ("pay", "invoice", "iban", "refund", "budget", "cost", "wire transfer", "bank transfer")
    travel_hit = any(k in text_lower for k in travel_keywords)
    finance_hit = any(k in text_lower for k in finance_keywords)
    if "transfer" in text_lower and any(k in text_lower for k in ("iban", "invoice", "payment", "wire", "bank")):
        finance_hit = True
    if travel_hit and not finance_hit:
        return "travel"
    if finance_hit and not travel_hit:
        return "finance"
    if travel_hit and finance_hit:
        # Prefer travel when finance wording is incidental to trip context.
        if any(k in text_lower for k in ("airport transfer", "hotel transfer", "route", "layover", "itinerary")):
            return "travel"
        return "finance"
    if "transfer" in text_lower:
        return "finance"
    if any(k in text_lower for k in ("meeting", "project", "deadline", "proposal", "roadmap", "deliverable")):
        return "project"
    if any(k in text_lower for k in ("health", "doctor", "therapy", "med", "appointment", "symptom")):
        return "health"
    return "general"


def _task_type_from_text(text_lower: str, *, domain: str, high_risk: bool, url_present: bool) -> str:
    if any(k in text_lower for k in ("research pass", "secondary research", "deep research")):
        return "run_secondary_research_pass"
    if any(k in text_lower for k in ("strategy pack", "strategy memo", "strategic options")):
        return "strategy_pack"
    if any(k in text_lower for k in ("feedback intake", "collect feedback", "feedback form")):
        return "feedback_intake"
    if any(k in text_lower for k in ("bridge event", "webhook ingest", "external event")):
        return "bridge_external_event"
    if any(k in text_lower for k in ("bridge action", "dispatch action", "external action")):
        return "bridge_external_action"
    if any(k in text_lower for k in ("polish", "humanize", "rewrite", "tone")):
        return "polish_human_tone"
    if any(k in text_lower for k in ("prompt pack", "compile prompt", "prompt template")):
        return "compile_prompt_pack"
    if any(k in text_lower for k in ("intake", "questionnaire", "form", "survey")):
        return "collect_structured_intake"
    if domain == "travel":
        if any(k in text_lower for k in ("route video", "arrival video", "render route")):
            return "route_video_render"
        if any(k in text_lower for k in ("reprice", "price drop", "optimize cost", "cheaper option")):
            return "optimize_trip_cost"
        if any(k in text_lower for k in ("book", "rebook", "reroute", "cancel", "layover", "risk", "rescue")):
            return "travel_rescue"
        return "trip_context_pack"
    if url_present and any(k in text_lower for k in ("summarize", "extract", "analyze", "review")):
        return "run_secondary_research_pass"
    if domain == "finance":
        if high_risk:
            return "approval_router"
        return "typed_safe_action"
    return ""


def compile_intent_spec_v2(
    *,
    text: str,
    tenant: str = "",
    chat_id: int | None = None,
    has_url: bool | None = None,
) -> dict[str, Any]:
    raw = str(text or "").strip()
    text_lower = raw.lower()
    url_present = bool(has_url) or bool(re.search(r"https?://", raw))
    high_risk_keywords = ("pay", "book", "cancel", "delete", "terminate", "sign", "approve")
    transfer_high_risk = False
    if "transfer" in text_lower and "airport transfer" not in text_lower and "hotel transfer" not in text_lower:
        transfer_high_risk = any(k in text_lower for k in ("iban", "bank", "wire", "invoice", "payment", "money"))
    high_risk = any(k in text_lower for k in high_risk_keywords) or transfer_high_risk
    question_like = raw.endswith("?") or any(
        w in text_lower for w in ("what", "why", "how", "when", "where", "summarize", "explain")
    )
    domain = _domain_from_text(text_lower)
    task_type = _task_type_from_text(
        text_lower,
        domain=domain,
        high_risk=high_risk,
        url_present=url_present,
    )
    deadline_hint = (
        "urgent"
        if any(k in text_lower for k in ("urgent", "asap", "today", "now", "immediately"))
        else "normal"
    )
    approval_class = "explicit_callback_required" if high_risk else "none"
    risk_class = "high_impact_action" if high_risk else "routine_assistive"
    deliverable_type = "answer_now" if question_like else "execute_or_plan"
    budget_class = "high_guardrail" if high_risk else "standard"
    evidence_requirements: list[str] = []
    if url_present:
        evidence_requirements.append("url_evidence")
    if domain == "finance":
        evidence_requirements.append("payment_context")
    if domain == "travel":
        evidence_requirements.append("travel_context")
    if not evidence_requirements:
        evidence_requirements.append("user_request_context")
    source_refs = re.findall(r"https?://[^\s]+", raw) if url_present else []
    objective = raw[:1200]
    commitment_key = ""
    if domain in {"travel", "finance", "project", "health"}:
        digest = hashlib.sha1(objective.encode("utf-8", errors="ignore")).hexdigest()[:12]
        commitment_key = f"{domain}:{str(tenant or '')}:{digest}"
    return {
        "intent_type": "url_analysis" if url_present else "free_text",
        "objective": objective,
        "domain": domain,
        "task_type": task_type,
        "deliverable": deliverable_type,
        "deliverable_type": deliverable_type,
        "autonomy_level": "approval_required" if high_risk else "assistive",
        "approval_class": approval_class,
        "risk_level": "high" if high_risk else "normal",
        "risk_class": risk_class,
        "budget_class": budget_class,
        "deadline_hint": deadline_hint,
        "has_url": url_present,
        "evidence_requirements": evidence_requirements,
        "source_refs": source_refs,
        "stakeholders": [],
        "output_contract": {"format": "telegram_message", "style": "concise", "max_chars": 3500},
        "commitment_key": commitment_key,
        "tenant": str(tenant or ""),
        "chat_id": int(chat_id) if chat_id is not None else None,
        "compiled_at_epoch_s": int(time.time()),
    }


__all__ = ["compile_intent_spec_v2"]
