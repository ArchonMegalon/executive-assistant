from __future__ import annotations

from app.llm import ask_llm


DEFAULT_SYSTEM_PROMPT = "Du bist ein präziser Executive Assistant."


def ask_text(prompt: str, *, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    """Contract adapter for all feature-layer LLM requests."""
    return ask_llm(str(prompt), system_prompt=str(system_prompt))

