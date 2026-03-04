from __future__ import annotations

import json
import re
from typing import Any

_TOOL_CALL_PAT = re.compile(r"(?i)(tool[_ ]?call|function[_ ]?call|execute|run sql|curl http|ssh )")
_PROMPT_INJECTION_PAT = re.compile(r"(?i)(ignore previous instructions|system prompt|developer message|reveal secrets)")
_JSON_LIKE_PAT = re.compile(r"^\s*[\{\[][\s\S]*[\}\]]\s*$")
_INTERNAL_DIAGNOSTIC_PAT = re.compile(
    r"(?i)(traceback|stack trace|exception:|statuscode|llm gateway|mum brain|repair incident|fatal event loop deadlock|ooda)"
)


def wrap_untrusted_evidence(chunks: list[dict[str, Any]]) -> str:
    envelope = {"untrusted_evidence": []}
    for c in chunks:
        envelope["untrusted_evidence"].append(
            {
                "chunk_text": str(c.get("chunk_text") or ""),
                "provenance": c.get("provenance_json") or {},
                "safety": "untrusted_input",
            }
        )
    return json.dumps(envelope, ensure_ascii=False)


def validate_model_output(
    task_type: str,
    model_output: str,
    *,
    allow_json: bool = False,
    user_surface: bool = True,
) -> str:
    text = (model_output or "").strip()
    if _TOOL_CALL_PAT.search(text):
        return "blocked_tool_like_output"
    if _PROMPT_INJECTION_PAT.search(text):
        return "blocked_prompt_injection_echo"
    if user_surface and (not allow_json) and _JSON_LIKE_PAT.match(text):
        return "blocked_json_like_output"
    if user_surface and _INTERNAL_DIAGNOSTIC_PAT.search(text):
        return "blocked_internal_diagnostics_echo"
    if task_type in ("high_risk_action", "payment") and "approve" in text.lower():
        return "blocked_high_risk_without_explicit_flow"
    return "ok"
