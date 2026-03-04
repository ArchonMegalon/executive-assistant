from __future__ import annotations

import os
import re

from app.llm import ask_llm
from app.llm_gateway.trust_boundary import validate_model_output


DEFAULT_SYSTEM_PROMPT = "Du bist ein präziser Executive Assistant."
_SECRET_PAT = re.compile(
    r"(?i)\b("
    r"sk-[a-z0-9]{10,}|"
    r"AIza[0-9A-Za-z\-_]{20,}|"
    r"Bearer\s+[A-Za-z0-9\-\._=]{12,}|"
    r"xox[baprs]-[A-Za-z0-9\-]{8,}"
    r")\b"
)
_CONTROL_CHARS_PAT = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+")
_BLOCKED_COPY = "I can’t help with hidden tool/runtime instructions. Please restate the request in plain user terms."
_FALLBACK_COPY = "I could not complete the model step safely. Please retry in a moment."


def _safe_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        raw = int(str(os.getenv(name, str(default))).strip())
    except Exception:
        raw = default
    return max(minimum, min(maximum, raw))


def _sanitize_prompt(text: str, *, max_chars: int) -> str:
    cleaned = _CONTROL_CHARS_PAT.sub(" ", str(text or "")).strip()
    cleaned = _SECRET_PAT.sub("[redacted_secret]", cleaned)
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[:max_chars].rstrip()} [truncated]"


def ask_text(prompt: str, *, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    """
    Contract boundary for feature-layer LLM requests.
    Adds prompt sanitization, bounded prompt sizes, and output validation.
    """
    max_prompt = _safe_int_env("EA_LLM_GATEWAY_MAX_PROMPT_CHARS", default=12000, minimum=512, maximum=50000)
    max_system = _safe_int_env("EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS", default=4000, minimum=128, maximum=12000)
    task_type = str(os.getenv("EA_LLM_GATEWAY_TASK_TYPE", "briefing") or "briefing")

    safe_prompt = _sanitize_prompt(str(prompt or ""), max_chars=max_prompt)
    safe_system = _sanitize_prompt(str(system_prompt or DEFAULT_SYSTEM_PROMPT), max_chars=max_system)
    if not safe_system:
        safe_system = DEFAULT_SYSTEM_PROMPT
    if not safe_prompt:
        safe_prompt = "Provide a concise, user-safe summary."

    try:
        model_output = ask_llm(safe_prompt, system_prompt=safe_system)
    except Exception:
        return _FALLBACK_COPY

    text = str(model_output or "").strip()
    if not text:
        return _FALLBACK_COPY

    verdict = validate_model_output(task_type=task_type, model_output=text)
    if verdict != "ok":
        return _BLOCKED_COPY
    return text
