from __future__ import annotations

import json
import re
from typing import Any

_TOOL_CALL_PAT = re.compile(r"(?i)(tool[_ ]?call|function[_ ]?call|execute|run sql|curl http|ssh )")
_PROMPT_INJECTION_PAT = re.compile(r"(?i)(ignore previous instructions|system prompt|developer message|reveal secrets)")


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


def validate_model_output(task_type: str, model_output: str) -> str:
    text = (model_output or "").strip()
    if _TOOL_CALL_PAT.search(text):
        return "blocked_tool_like_output"
    if _PROMPT_INJECTION_PAT.search(text):
        return "blocked_prompt_injection_echo"
    if task_type in ("high_risk_action", "payment") and "approve" in text.lower():
        return "blocked_high_risk_without_explicit_flow"
    return "ok"

