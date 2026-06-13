from __future__ import annotations

from pathlib import Path


def _generated_wav(seed: bytes) -> bytes:
    lead = b"\x00\x00" * 800
    tone = (seed * 2200)[:22400]
    tail = b"\x00\x00" * 1200
    pcm = lead + tone + tail
    return (
        b"RIFF"
        + int(36 + len(pcm)).to_bytes(4, "little")
        + b"WAVEfmt "
        + int(16).to_bytes(4, "little")
        + int(1).to_bytes(2, "little")
        + int(1).to_bytes(2, "little")
        + int(16000).to_bytes(4, "little")
        + int(32000).to_bytes(4, "little")
        + int(2).to_bytes(2, "little")
        + int(16).to_bytes(2, "little")
        + b"data"
        + int(len(pcm)).to_bytes(4, "little")
        + pcm
    )


def test_token_overlap_scores_reasonable_similarity() -> None:
    import scripts.validate_memorial_voice_loop as validator

    overlap = validator._token_overlap(
        "Ich antworte dir direkt und bleibe bei der Sache.",
        "Ich antworte direkt und bleibe bei der Sache.",
    )

    assert overlap["f1"] >= 0.8
    assert overlap["precision"] >= 0.8
    assert overlap["recall"] >= 0.7


def test_token_overlap_treats_jo_like_ja() -> None:
    import scripts.validate_memorial_voice_loop as validator

    overlap = validator._token_overlap(
        "Ja, ich bin da.",
        "Jo, ich bin da.",
    )

    assert overlap["f1"] == 1.0


def test_validate_memorial_voice_loop_passes_with_stubbed_endpoints(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    direct_wav = _generated_wav(b"Sprich ruhig weiter. Ich antworte dir direkt. ")
    answer_wav = _generated_wav(b"Ich antworte dir direkt und bleibe bei der Sache. ")

    def fake_post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
        if url.endswith("/chat"):
            if payload.get("question") == "Welches Wetter haben wir heute?":
                return 200, {
                    "answer": "Dazu habe ich keine Erinnerung.",
                    "fallback_reason": "present_world_guardrail",
                    "current_world_policy": "local_memories_and_conversation_only_no_internet_search",
                    "sources": [],
                }
            return 200, {"answer": "Ich antworte dir direkt und bleibe bei der Sache."}
        raise AssertionError(url)

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/speech-transcribe"):
            raw = bytes(payload)
            if b"Sprich ruhig weiter. Ich antworte dir direkt." in raw:
                return 200, {"transcript_text": "Sprich ruhig weiter. Ich antworte dir direkt.", "transcriber": "stub"}
            return 200, {
                "transcript_text": "Ich antworte dir direkt und bleibe bei der Sache.",
                "transcriber": "stub",
            }
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ich antworte dir direkt und bleibe bei der Sache.",
                "audio_base64": base64.b64encode(answer_wav).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        raise AssertionError(url)

    def fake_post_json_binary_response(url: str, payload: dict[str, object], *, timeout: float = 120.0):
        if payload.get("text") == "Sprich ruhig weiter. Ich antworte dir direkt.":
            return 200, direct_wav, "audio/wav"
        return 200, _generated_wav(str(payload.get("text") or "").encode("utf-8") or b"question"), "audio/wav"

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)
    monkeypatch.setattr(validator, "_post_json_binary_response", fake_post_json_binary_response)

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Sprich ruhig weiter. Ich antworte dir direkt.",
        conversation_question="Hallo Manfred, kannst du direkt mit mir reden?",
    )

    assert report.status == "pass"
    assert report.artifacts["direct_tts_audio"].endswith("manfred-direct-tts.wav")
    assert report.artifacts["conversation_turn_audio"].endswith("manfred-conversation-turn-answer.wav")
    assert any(item.code == "direct_tts_similarity_ok" for item in report.checks)
    assert any(item.code == "present_world_route_ok" for item in report.checks)
    assert any(item.code == "conversation_turn_audio_similarity_ok" for item in report.checks)


def test_validate_memorial_voice_loop_rejects_present_world_search_sources(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    direct_wav = _generated_wav(b"Sprich ruhig weiter. Ich antworte dir direkt. ")
    answer_wav = _generated_wav(b"Ich ordne dir das aus aktuellen Quellen ein. ")

    def fake_post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
        if url.endswith("/chat"):
            if payload.get("question") == "Welches Wetter haben wir heute?":
                return 200, {
                    "answer": "Das sehe ich nicht aus mir heraus. Ich habe aber gerade aktuelle Quellen zum Wetter dazu gefunden. Stand jetzt sind es etwa 24 Grad.",
                    "fallback_reason": "present_world_search",
                    "sources": ["Wetter Wien heute | https://weather.example/wien"],
                }
            return 200, {"answer": "Ich ordne dir das aus aktuellen Quellen ein."}
        raise AssertionError(url)

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/speech-transcribe"):
            raw = bytes(payload)
            if b"Sprich ruhig weiter. Ich antworte dir direkt." in raw:
                return 200, {"transcript_text": "Sprich ruhig weiter. Ich antworte dir direkt.", "transcriber": "stub"}
            return 200, {"transcript_text": "Ich ordne dir das aus aktuellen Quellen ein.", "transcriber": "stub"}
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ich ordne dir das aus aktuellen Quellen ein.",
                "audio_base64": base64.b64encode(answer_wav).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        raise AssertionError(url)

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)
    monkeypatch.setattr(
        validator,
        "_post_json_binary_response",
        lambda *args, **kwargs: (200, direct_wav, "audio/wav"),
    )

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Sprich ruhig weiter. Ich antworte dir direkt.",
        conversation_question="Hallo Manfred, kannst du direkt mit mir reden?",
    )

    assert report.status == "fail"
    assert any(item.code == "present_world_search_forbidden" for item in report.checks)


def test_validate_memorial_voice_loop_fails_on_empty_transcript(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    wav_bytes = _generated_wav(b"0123")

    def fake_post_json(*args, **kwargs):
        payload = kwargs.get("payload")
        if payload is None and len(args) >= 2:
            payload = args[1]
        if isinstance(payload, dict) and payload.get("question") == "Welches Wetter haben wir heute?":
            return 200, {
                "answer": "Dazu habe ich keine Erinnerung.",
                "fallback_reason": "present_world_guardrail",
                "current_world_policy": "local_memories_and_conversation_only_no_internet_search",
                "sources": [],
            }
        return 200, {"answer": "Ich antworte dir direkt."}

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_json_binary_response", lambda *args, **kwargs: (200, wav_bytes, "audio/wav"))

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ich antworte dir direkt.",
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        return 200, {"transcript_text": "", "transcriber": "stub"}

    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Sprich ruhig weiter. Ich antworte dir direkt.",
        conversation_question="Hallo Manfred, kannst du direkt mit mir reden?",
    )

    assert report.status == "fail"
    assert any(item.code == "direct_tts_transcript_empty" for item in report.checks)


def test_validate_memorial_voice_loop_accepts_short_phrase_with_stt_filler(tmp_path: Path) -> None:
    import scripts.validate_memorial_voice_loop as validator

    report = validator.ValidationReport(slug="manfred", base_url="https://example.test", output_dir=str(tmp_path))

    validator._evaluate_similarity(report, code_prefix="short_audio", expected="Ja.", actual="Ja, okay.")

    assert report.status == "pass"
    assert any(item.code == "short_audio_short_phrase_ok" for item in report.checks)


def test_validate_memorial_voice_loop_passes_with_info_when_transcriber_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    direct_wav = _generated_wav(b"Sprich ruhig weiter. Ich antworte dir direkt. ")
    answer_wav = _generated_wav(b"Ich antworte dir direkt und bleibe bei der Sache. ")

    def fake_post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
        if url.endswith("/chat"):
            if payload.get("question") == "Welches Wetter haben wir heute?":
                return 200, {
                    "answer": "Dazu habe ich keine Erinnerung.",
                    "fallback_reason": "present_world_guardrail",
                    "current_world_policy": "local_memories_and_conversation_only_no_internet_search",
                    "sources": [],
                }
            return 200, {"answer": "Ich antworte dir direkt und bleibe bei der Sache."}
        raise AssertionError(url)

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/speech-transcribe"):
            return 503, {"error": {"code": "speech_transcriber_unavailable", "message": "speech_transcriber_unavailable"}}
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ich antworte dir direkt und bleibe bei der Sache.",
                "audio_base64": base64.b64encode(answer_wav).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        raise AssertionError(url)

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)
    monkeypatch.setattr(
        validator,
        "_post_json_binary_response",
        lambda *args, **kwargs: (200, direct_wav, "audio/wav"),
    )

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Sprich ruhig weiter. Ich antworte dir direkt.",
        conversation_question="Hallo Manfred, kannst du direkt mit mir reden?",
    )

    assert report.status == "pass"
    assert any(item.code == "direct_tts_transcriber_unavailable" for item in report.checks)
    assert any(item.code == "conversation_turn_transcriber_unavailable" for item in report.checks)
    assert any(item.code == "conversation_answer_text_reference_skipped" for item in report.checks)


def test_validate_memorial_voice_loop_fails_when_required_stt_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    direct_wav = _generated_wav(b"Sprich ruhig weiter. Ich antworte dir direkt. ")
    answer_wav = _generated_wav(b"Ich antworte dir direkt und bleibe bei der Sache. ")

    def fake_post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
        if url.endswith("/chat"):
            if payload.get("question") == "Welches Wetter haben wir heute?":
                return 200, {
                    "answer": "Dazu habe ich keine Erinnerung.",
                    "fallback_reason": "present_world_guardrail",
                    "current_world_policy": "local_memories_and_conversation_only_no_internet_search",
                    "sources": [],
                }
            return 200, {"answer": "Ich antworte dir direkt und bleibe bei der Sache."}
        raise AssertionError(url)

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/speech-transcribe"):
            return 503, {"error": {"code": "speech_transcriber_unavailable", "message": "speech_transcriber_unavailable"}}
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ich antworte dir direkt und bleibe bei der Sache.",
                "audio_base64": base64.b64encode(answer_wav).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        raise AssertionError(url)

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)
    monkeypatch.setattr(validator, "_post_json_binary_response", lambda *args, **kwargs: (200, direct_wav, "audio/wav"))

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Sprich ruhig weiter. Ich antworte dir direkt.",
        conversation_question="Hallo Manfred, kannst du direkt mit mir reden?",
        require_stt=True,
    )

    assert report.status == "fail"
    assert any(item.status == "fail" and item.code == "direct_tts_transcriber_unavailable" for item in report.checks)


def test_validate_memorial_voice_loop_fails_when_present_world_question_drifts(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    wav_bytes = _generated_wav(b"Sprich ruhig weiter. Ich antworte dir direkt.")

    def fake_post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
        if payload.get("question") == "Welches Wetter haben wir heute?":
            return 200, {
                "answer": "Das Schach soll in der Familie bleiben.",
                "fallback_reason": "memorial_anchor_memory_guardrail",
            }
        return 200, {"answer": "Ja."}

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_json_binary_response", lambda *args, **kwargs: (200, wav_bytes, "audio/wav"))

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ja.",
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        return 200, {"transcript_text": "Ja.", "transcriber": "stub"}

    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Sprich ruhig weiter. Ich antworte dir direkt.",
        conversation_question="Hallo Manfred, kannst du direkt mit mir reden?",
    )

    assert report.status == "fail"
    assert any(item.code == "present_world_wrong_route" for item in report.checks)


def test_validate_memorial_voice_loop_gold_mode_rejects_critical_token_substitution(tmp_path: Path, monkeypatch) -> None:
    import scripts.validate_memorial_voice_loop as validator

    direct_wav = _generated_wav(b"Ich hoere dich gut. Sag mir bitte den Ort.")
    answer_wav = _generated_wav(b"Ich hoere dich gut. Sag mir bitte den Ort.")

    def fake_post_json(url: str, payload: dict[str, object], *, timeout: float = 90.0):
        if url.endswith("/chat"):
            if payload.get("question") == "Wie ist das Wetter heute?":
                return 200, {
                    "answer": "Dazu habe ich keine Erinnerung.",
                    "fallback_reason": "present_world_guardrail",
                    "current_world_policy": "local_memories_and_conversation_only_no_internet_search",
                    "sources": [],
                }
            return 200, {"answer": "Ich höre dich gut. Sag mir bitte den Ort."}
        raise AssertionError(url)

    def fake_post_binary(url: str, payload: bytes, *, content_type: str, timeout: float = 120.0):
        if url.endswith("/speech-transcribe"):
            return 200, {"transcript_text": "Ich höre dich gut. Sag mir bitte Geloren.", "transcriber": "stub"}
        if url.endswith("/conversation-turn"):
            import base64

            return 200, {
                "answer": "Ich höre dich gut. Sag mir bitte den Ort.",
                "audio_base64": base64.b64encode(answer_wav).decode("ascii"),
                "audio_content_type": "audio/wav",
            }
        raise AssertionError(url)

    monkeypatch.setattr(validator, "_post_json", fake_post_json)
    monkeypatch.setattr(validator, "_post_binary", fake_post_binary)
    monkeypatch.setattr(
        validator,
        "_post_json_binary_response",
        lambda *args, **kwargs: (200, direct_wav, "audio/wav"),
    )

    report = validator.validate_memorial_voice_loop(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Ich höre dich gut. Sag mir bitte den Ort.",
        conversation_question="Wie geht das weiter?",
        present_world_question="Wie ist das Wetter heute?",
        require_stt=True,
        gold_mode=True,
        critical_tokens=("Ort",),
    )

    assert report.status == "fail"
    assert any(item.code == "direct_tts_critical_tokens_missing" for item in report.checks)
