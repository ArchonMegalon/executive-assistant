from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.routes import public_memorials as shared
from app.api.routes import public_memorial_turn_support as turn_support


def _memorial_chat_answer_payload(*, slug: str, request: Request, body: dict[str, object]) -> dict[str, object]:
    payload = shared._load_memorial(slug)
    private_profile = shared._load_private_profile(slug)
    selected_model, _, _ = shared._resolve_memorial_chat_model(payload, private_profile, shared._text(body.get("llm_model")))
    container = getattr(request.app.state, "container", None)
    memory_runtime = getattr(container, "memory_runtime", None)
    question_text = shared._text(body.get("question"))
    personal_memory_context = shared._extract_personal_memory_request_context(request=request, body=body)
    difficult_memory_mode = shared._extract_difficult_memory_mode(request=request, body=body)
    shared._enforce_public_memorial_rate_limit("chat", request=request, context=personal_memory_context)
    if shared._is_memorial_current_speculation_question(question_text):
        answer = shared._memorial_chat_answer(
            payload,
            question_text,
            private_profile,
            requested_model=selected_model,
            slug=slug,
            memory_runtime=memory_runtime,
            personal_memory_context=personal_memory_context,
            difficult_memory_mode=difficult_memory_mode,
        )
    elif not difficult_memory_mode and shared._is_difficult_memory_question(question_text):
        answer = shared._memorial_chat_fallback_answer(
            payload,
            question_text,
            private_profile,
            slug=slug,
            memory_runtime=memory_runtime,
            llm_model=selected_model,
            fallback_reason="difficult_memory_guardrail",
            difficult_memory_mode=False,
        )
        answer["llm_model"] = selected_model
        answer["llm_provider"] = "memorial_guardrail"
        answer["llm_request_model"] = selected_model
        answer["llm_fallback_used"] = True
    elif shared._is_memorial_transcript_relationship_question(question_text) or shared._is_memorial_mail_practice_question(question_text):
        answer = shared._memorial_chat_fallback_answer(
            payload,
            question_text,
            private_profile,
            slug=slug,
            memory_runtime=memory_runtime,
            llm_model=selected_model,
            fallback_reason="mail_practice_guardrail" if shared._is_memorial_mail_practice_question(question_text) else "transcript_relationship_guardrail",
            difficult_memory_mode=difficult_memory_mode,
        )
    else:
        answer = shared._memorial_chat_answer(
            payload,
            question_text,
            private_profile,
            requested_model=selected_model,
            slug=slug,
            memory_runtime=memory_runtime,
            personal_memory_context=personal_memory_context,
            difficult_memory_mode=difficult_memory_mode,
        )
    shared._remember_personal_conversation_turn(
        slug=slug,
        context=personal_memory_context,
        question=question_text,
        answer=shared._text(answer.get("answer"), ""),
    )
    if (
        shared._is_memorial_ooda_question(question_text)
        and not shared._is_memorial_current_speculation_question(question_text)
        and not answer.get("ooda")
    ):
        answer["ooda"] = shared._memorial_ooda_struct(question_text)
    answer["personal_memory"] = shared._personal_memory_public_status(slug=slug, context=personal_memory_context)
    return answer


def _resolve_whatsapp_binding(*, principal_id: str, container, requested_binding_id: str):
    requested = str(requested_binding_id or "").strip()
    bindings = [
        row
        for row in container.tool_runtime.list_connector_bindings(principal_id=principal_id, limit=200)
        if str(row.connector_name or "").strip() in {"whatsapp_business", "whatsapp_export"}
    ]
    if requested:
        for row in bindings:
            if str(row.binding_id or "").strip() == requested:
                return row
        raise HTTPException(status_code=400, detail="whatsapp_binding_not_found")
    preferred_statuses = ("enabled", "planned", "imported", "ready")
    for status in preferred_statuses:
        for row in bindings:
            if str(row.status or "").strip().lower() == status:
                return row
    return bindings[0] if bindings else None


async def public_memorial_chat_help(slug: str) -> JSONResponse:
    shared._load_memorial(slug)
    return JSONResponse(
        {
            "detail": "Use POST with JSON to chat with this memorial.",
            "method": "POST",
            "content_type": "application/json",
            "endpoint": f"/memorials/{slug}/chat",
            "example_body": {"question": "Wie hätte er Susanna schriftlich geschrieben?"},
            "page": f"/memorials/{slug}",
        }
    )


async def public_memorial_personal_memory_status(slug: str, request: Request) -> JSONResponse:
    shared._load_memorial(slug)
    context = shared._extract_personal_memory_request_context(request=request)
    return JSONResponse(shared._personal_memory_public_status(slug=slug, context=context))


async def public_memorial_personal_memory_forget(slug: str, request: Request) -> JSONResponse:
    shared._load_memorial(slug)
    context = shared._extract_personal_memory_request_context(request=request)
    scope = shared._text(context.get("scope"), "")
    if scope:
        store = shared._load_personal_memory_store(slug=slug, scope=scope)
        store["items"] = []
        store["frozen"] = False
        store["approved_voice_choice"] = ""
        shared._save_personal_memory_store(slug=slug, scope=scope, payload=store)
    return JSONResponse({"status": "forgotten", **shared._personal_memory_public_status(slug=slug, context=context)})


async def public_memorial_chat(slug: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    answer = _memorial_chat_answer_payload(slug=slug, request=request, body=body)
    return JSONResponse(answer)


async def public_memorial_whatsapp_draft(slug: str, request: Request, *, principal_id: str) -> JSONResponse:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_json")
    recipient = shared._text(body.get("recipient"))
    if not recipient:
        raise HTTPException(status_code=400, detail="recipient_required")
    question_text = shared._text(body.get("question"))
    if not question_text:
        raise HTTPException(status_code=400, detail="question_required")
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=500, detail="container_unavailable")
    answer = _memorial_chat_answer_payload(slug=slug, request=request, body=body)
    binding = _resolve_whatsapp_binding(
        principal_id=principal_id,
        container=container,
        requested_binding_id=shared._text(body.get("binding_id")),
    )
    binding_state = {
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "connector_name": str(getattr(binding, "connector_name", "") or ""),
        "external_account_ref": str(getattr(binding, "external_account_ref", "") or ""),
        "status": str(getattr(binding, "status", "") or ""),
    }
    if not binding_state["status"]:
        binding_state["status"] = "not_configured"
    metadata = dict(body.get("metadata") or {})
    metadata.update(
        {
            "principal_id": principal_id,
            "delivery_mode": "queued",
            "source": "memorial_whatsapp_draft",
            "memorial_slug": slug,
            "memorial_question": question_text,
            "memorial_route": shared._text(answer.get("route"), ""),
            "memorial_sources": list(answer.get("sources") or []),
            "whatsapp_binding_status": binding_state["status"],
            "connector_name": binding_state["connector_name"],
            "binding_id": binding_state["binding_id"],
            "external_account_ref": binding_state["external_account_ref"],
        }
    )
    row = container.channel_runtime.queue_delivery(
        principal_id=principal_id,
        channel="whatsapp",
        recipient=recipient,
        content=shared._text(answer.get("answer"), ""),
        metadata=metadata,
        idempotency_key=shared._text(body.get("idempotency_key"), ""),
    )
    return JSONResponse(
        {
            "status": row.status,
            "delivery_mode": "queued",
            "delivery_id": row.delivery_id,
            "channel": row.channel,
            "recipient": row.recipient,
            "principal_id": row.principal_id,
            "binding": binding_state,
            "question": question_text,
            "answer": shared._text(answer.get("answer"), ""),
            "sources": list(answer.get("sources") or []),
            "route": shared._text(answer.get("route"), ""),
        }
    )


async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    return await turn_support.public_memorial_speech_transcribe(slug=slug, request=request)


async def public_memorial_speech_synthesize_help(slug: str) -> JSONResponse:
    return await turn_support.public_memorial_speech_synthesize_help(slug=slug)


async def public_memorial_speech_synthesize(slug: str, request: Request):
    return await turn_support.public_memorial_speech_synthesize(slug=slug, request=request)


async def public_memorial_conversation_turn(slug: str, request: Request) -> JSONResponse:
    return await turn_support.public_memorial_conversation_turn(slug=slug, request=request)
