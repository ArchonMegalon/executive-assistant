from __future__ import annotations

from pathlib import Path


def test_materialize_memorial_voice_roundtrip_exit_gate_fails_gold_latency(monkeypatch, tmp_path: Path) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    class _Report:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "pass",
                "metrics": {
                    "direct_tts_f1": 1.0,
                    "conversation_turn_audio_f1": 1.0,
                    "conversation_turn_total_ms": 9000,
                    "speech_transcribe_ms": 5000,
                },
                "checks": [{"status": "pass", "code": "present_world_route_ok"}],
                "artifacts": {},
            }

    monkeypatch.setattr(materializer.voice_loop, "validate_memorial_voice_loop", lambda **_: _Report())
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
    monkeypatch.setattr(materializer, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(materializer, "_source_tree_fingerprint", lambda: "fingerprint")

    receipt = materializer.build_receipt(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Worum geht es?",
        conversation_question="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        present_world_question="Welches Wetter haben wir heute?",
        require_stt=True,
        gold_mode=True,
        require_public_origin=True,
        direct_min_f1=0.92,
        conversation_min_f1=0.90,
        max_conversation_turn_ms=4500.0,
        max_speech_transcribe_ms=2500.0,
        critical_tokens=("worum", "geht", "es"),
    )

    assert receipt["status"] == "fail"
    assert "conversation_turn_total_ms_above_gold_threshold" in receipt["failed_codes"]
    assert "speech_transcribe_ms_above_gold_threshold" in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False
