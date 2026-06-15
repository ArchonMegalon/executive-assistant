from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.routes import public_memorials as shared
from app.api.routes import public_memorial_turn_support as turn_support


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
    payload = shared._load_memorial(slug)
    private_profile = shared._load_private_profile(slug)
    selected_model, _, _ = shared._resolve_memorial_chat_model(payload, private_profile, shared._text(body.get("llm_model")))
    container = getattr(request.app.state, "container", None)
    memory_runtime = getattr(container, "memory_runtime", None)
    question_text = shared._text(body.get("question"))
    personal_memory_context = shared._extract_personal_memory_request_context(request=request, body=body)
    difficult_memory_mode = shared._extract_difficult_memory_mode(request=request, body=body)
    shared._enforce_public_memorial_rate_limit("chat", request=request, context=personal_memory_context)
    if not difficult_memory_mode and shared._is_difficult_memory_question(question_text):
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
    if shared._is_memorial_ooda_question(question_text) and not answer.get("ooda"):
        answer["ooda"] = shared._memorial_ooda_struct(question_text)
    answer["personal_memory"] = shared._personal_memory_public_status(slug=slug, context=personal_memory_context)
    return JSONResponse(answer)


async def public_memorial_speech_transcribe(slug: str, request: Request) -> JSONResponse:
    return await turn_support.public_memorial_speech_transcribe(slug=slug, request=request)


async def public_memorial_speech_synthesize_help(slug: str) -> JSONResponse:
    return await turn_support.public_memorial_speech_synthesize_help(slug=slug)


async def public_memorial_speech_synthesize(slug: str, request: Request):
    return await turn_support.public_memorial_speech_synthesize(slug=slug, request=request)


async def public_memorial_conversation_turn(slug: str, request: Request) -> JSONResponse:
    return await turn_support.public_memorial_conversation_turn(slug=slug, request=request)
