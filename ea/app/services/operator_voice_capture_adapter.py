from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import re
from typing import Any


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b(?:sk-|teable_|eyJ[a-zA-Z0-9._-]{20,})[A-Za-z0-9._=+-]*\b")


@dataclass(frozen=True)
class OperatorCapturePacket:
    packet_id: str
    source: str
    capture_type: str
    redacted_transcript: str
    structured_summary: str
    risk_flags: tuple[str, ...]
    target_repo: str
    recommended_next_action: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def redact_operator_transcript(transcript: str) -> str:
    redacted = EMAIL_RE.sub("[redacted-email]", transcript)
    redacted = TOKEN_RE.sub("[redacted-token]", redacted)
    return redacted


def build_operator_capture_packet(*, transcript: str, capture_type: str, target_repo: str) -> OperatorCapturePacket:
    redacted = redact_operator_transcript(transcript)
    risks: list[str] = []
    if redacted != transcript:
        risks.append("redaction_applied")
    if "sourcebook" in transcript.lower():
        risks.append("sourcebook_reference")
    summary = redacted.strip().split(".")[0].strip() or redacted.strip()[:180]
    digest = hashlib.sha256(f"{capture_type}\n{target_repo}\n{redacted}".encode("utf-8")).hexdigest()[:16]
    return OperatorCapturePacket(
        packet_id=f"operator_capture_{digest}",
        source="blipai_voice_capture",
        capture_type=capture_type,
        redacted_transcript=redacted,
        structured_summary=summary,
        risk_flags=tuple(risks),
        target_repo=target_repo,
        recommended_next_action="review_and_route",
    )
