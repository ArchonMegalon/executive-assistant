from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    path = Path("/docker/EA/scripts/measure_memorial_live_browser.py")
    spec = importlib.util.spec_from_file_location("measure_memorial_live_browser", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pure_python_prompt_wav_bytes_returns_valid_wav() -> None:
    module = _load_module()

    payload = module._pure_python_prompt_wav_bytes("Hallo Manfred")

    assert payload.startswith(b"RIFF")
    assert b"WAVE" in payload[:16]
    assert len(payload) > 4096


def test_synthesized_prompt_wav_bytes_falls_back_without_host_binaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module, "_pure_python_prompt_wav_bytes", lambda text: b"fallback-wav")

    payload = module._synthesized_prompt_wav_bytes("Hallo Manfred")

    assert payload == b"fallback-wav"


def test_transcribe_stub_payload_returns_expected_browser_contract() -> None:
    module = _load_module()

    payload = module._transcribe_stub_payload("Hallo Manfred")

    assert payload == {
        "transcription_status": "transcribed",
        "transcript_text": "Hallo Manfred",
        "transcriber": "playwright_stub",
    }


def test_count_context_matches_returns_distinct_hits() -> None:
    module = _load_module()

    count, matches = module._count_context_matches(
        "Ja, ich bin da. Sag mir einfach, was dich beschaeftigt, dann reagiere ich direkt darauf.",
        module.DEFAULT_EXIT_GATE_CONTEXT_TOKENS,
    )

    assert count >= 4
    assert "ja" in matches
    assert "da" in matches
    assert "sag" in matches
    assert "reagiere" in matches


def test_semantic_profile_for_prompt_prefers_decision_lane() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt(
        "Kannst du mir in zwei Sätzen sagen, was in dir bei schwierigen Entscheidungen immer die wichtigste Frage war?"
    )

    assert profile["id"] == "decision_reflection"


def test_semantic_profile_for_prompt_detects_memorial_values_lane() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt("Was war dir bei Gerechtigkeit wichtig?")

    assert profile["id"] == "memorial_values"


def test_answer_satisfies_semantic_profile_requires_group_structure() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt(
        "Wie hast du damals für mich entschieden, wenn es einen moralischen Konflikt gab?"
    )
    passed, details = module._answer_satisfies_semantic_profile(
        "Da widerspreche ich. Nachgeben nur um des Friedens willen war nie meine Art. Wenn ich die Sache fuer falsch hielt, blieb ich bei meiner Haltung.",
        profile,
    )

    assert passed is True
    assert details["profile_id"] == "moral_conflict"
    assert details["group_match_count"] >= 2
    assert "widerspreche" in details["context_matches"]


def test_answer_satisfies_semantic_profile_rejects_generic_answer() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt(
        "Wie hast du damals fuer mich entschieden, wenn es einen moralischen Konflikt gab?"
    )
    passed, details = module._answer_satisfies_semantic_profile(
        "Ich bin da und antworte dir direkt darauf.",
        profile,
    )

    assert passed is False
    assert details["group_match_count"] < details["required_group_matches"]


def test_measure_script_avoids_networkidle_as_primary_page_gate() -> None:
    source = Path("/docker/EA/scripts/measure_memorial_live_browser.py").read_text(encoding="utf-8")

    assert 'wait_until="domcontentloaded"' in source
    assert 'page.wait_for_load_state("networkidle", timeout=5000)' in source
    assert "speech_transcribe_mode" in source
    assert "_realtime_stub_turn_init_script(prompt_text)" in source
    assert 'new MessageEvent("message"' in source
    assert '"turn_complete"' in source
    assert '"/realtime"' in source
    assert '"/conversation-turn"' not in source
    assert '"conversation_turn_payload"' in source
    assert '"audio_ready_for_ui"' in source
    assert '"answer_text_visible"' in source
    assert '"missing_visible_answer_text"' in source
    assert '"ui_audio_play_calls"' in source
    assert '"ui_audio_play_ended"' in source
    assert '"ui_audio_play_error"' in source
    assert '"answer_context_match_count"' in source
    assert '"answer_context_matches"' in source
    assert '"semantic_profile_id"' in source
    assert '"answer_semantic_group_match_count"' in source
    assert '"answer_semantic_matched_groups"' in source
    assert '"answer_semantic_passed"' in source
    assert '"first_answer_too_slow"' in source
    assert '"answer_semantics_failed"' in source
    assert '"warmup_preflight"' in source
    assert '"--exit-gate"' in source
    assert '"turn_error": turn_error[:240]' in source
    assert '--real-stt' in source
    assert '--gold-mode' in source
    assert '--require-public-origin' in source
    assert '"ea.memorial_realtime_browser_exit_gate"' in source
    assert '"speech_transcribe_mode"' in source


def test_prewarm_memorial_origin_reports_ready_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    calls: list[tuple[str, str]] = []

    def _fake_http_json(url: str, *, method: str = "GET", payload=None, timeout: float = 20.0):
        calls.append((method, url))
        if method == "POST":
            return 202, {"status": "queued"}
        return 200, {"warm": True, "voice_required": True, "voice_ready": True}

    monkeypatch.setattr(module, "_http_json", _fake_http_json)

    receipt = module._prewarm_memorial_origin("https://example.com", "manfred", timeout_seconds=0.1)

    assert receipt["ready"] is True
    assert receipt["request_status"] == 202
    assert receipt["status_code"] == 200
    assert ("POST", "https://example.com/memorials/manfred/warmup") in calls
    assert ("GET", "https://example.com/memorials/manfred/warmup-status") in calls


def test_browser_exit_gate_receipt_blocks_local_public_gold() -> None:
    module = _load_module()

    receipt = module._with_exit_gate_status(
        {
            "base_url": "http://127.0.0.1:8090",
            "answer_preview": "Ja, ich bin da. Sag mir einfach, was dich beschaeftigt.",
            "audio_payload_ready": True,
            "audio_ready_for_ui": True,
            "answer_text_visible": True,
            "ui_audio_play_calls": 1,
            "ui_audio_play_ended": 1,
            "answer_semantic_passed": True,
            "first_answer_ms": 900,
        },
        exit_gate=True,
        gold_mode=True,
        require_public_origin=True,
        max_first_answer_ms=4500,
    )

    assert receipt["contract_name"] == "ea.memorial_realtime_browser_exit_gate"
    assert receipt["status"] == "fail"
    assert "public_origin_required" in receipt["failed_codes"]


def test_wait_for_realtime_turn_tolerates_contexts_without_off() -> None:
    module = _load_module()

    class FakeSocket:
        url = "ws://127.0.0.1/memorials/manfred/realtime"

        def on(self, event_name, callback):
            assert event_name == "framereceived"
            callback(type("Frame", (), {"payload": '{"type":"turn_complete","turn_id":"turn_1"}'})())

    class FakeContext:
        def on(self, event_name, callback):
            assert event_name == "websocket"
            callback(FakeSocket())

    result = module._wait_for_realtime_turn(FakeContext(), "manfred", lambda: None, timeout_seconds=0.01)

    assert result["done"] is True
    assert result["turn_id"] == "turn_1"
