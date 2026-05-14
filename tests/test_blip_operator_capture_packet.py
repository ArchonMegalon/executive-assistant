from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ea"))
from app.services.operator_voice_capture_adapter import build_operator_capture_packet


def test_blip_operator_capture_packet_redacts_tokens_and_emails() -> None:
    packet = build_operator_capture_packet(
        transcript="Send this to the.girscheles@gmail.com and include teable_secret teable_accerWCzQZM46rplNBd_bTzVuzTZIwiyXIEk9qq0q+4bEmjAnj+3xGWJ6Tb7UTg=",
        capture_type="audit_note",
        target_repo="chummer6-hub",
    )

    assert packet.source == "blipai_voice_capture"
    assert "[redacted-email]" in packet.redacted_transcript
    assert "[redacted-token]" in packet.redacted_transcript
    assert "review_and_route" == packet.recommended_next_action
    assert "redaction_applied" in packet.risk_flags
