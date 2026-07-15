from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "measure_memorial_live_browser.py"
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


def test_semantic_profile_for_generic_importance_prompt_uses_memorial_values_lane() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt("Was war Manfred wichtig?")

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


def test_answer_satisfies_contact_profile_rejects_narrowing_clarification() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt("Hallo Manfred, kannst du jetzt mit mir sprechen?")
    passed, details = module._answer_satisfies_semantic_profile(
        "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
        profile,
    )

    assert profile["id"] == "contact_opening"
    assert passed is False
    assert details["context_match_count"] >= 1


def test_should_accept_visible_answer_early_accepts_contact_ack() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt("Hallo Manfred, kannst du jetzt mit mir sprechen?")

    assert module._should_accept_visible_answer_early(
        profile,
        "Worum geht es?",
        ui_audio_ready=True,
    ) is True


def test_should_accept_visible_answer_early_rejects_non_contact_profile() -> None:
    module = _load_module()

    profile = module._semantic_profile_for_prompt("Was war dir bei Gerechtigkeit wichtig?")

    assert module._should_accept_visible_answer_early(
        profile,
        "Worum geht es?",
        ui_audio_ready=True,
    ) is False


def test_measure_script_avoids_networkidle_as_primary_page_gate() -> None:
    source = (ROOT / "scripts" / "measure_memorial_live_browser.py").read_text(encoding="utf-8")

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
    assert 'button.getAttribute("aria-pressed") === "true"' in source
    assert "button.click();" in source
    assert '"conversation_teardown_ok"' in source
    assert 'RuntimeError("conversation_teardown_failed")' in source
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


def test_prompt_wav_bytes_for_measure_prefers_memorial_speech_synthesize(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_http_bytes",
        lambda url, **kwargs: (200, b"memorial-wav", "audio/wav"),
    )
    monkeypatch.setattr(module, "_synthesized_prompt_wav_bytes", lambda text: b"fallback-wav")

    payload = module._prompt_wav_bytes_for_measure("https://example.com", "manfred", "Was war dir wichtig?")

    assert payload == b"memorial-wav"


def test_prompt_wav_bytes_for_measure_falls_back_when_synth_route_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_http_bytes",
        lambda url, **kwargs: (503, b"", "application/json"),
    )
    monkeypatch.setattr(module, "_synthesized_prompt_wav_bytes", lambda text: b"fallback-wav")

    payload = module._prompt_wav_bytes_for_measure("https://example.com", "manfred", "Was war dir wichtig?")

    assert payload == b"fallback-wav"


def test_browser_exit_gate_receipt_blocks_local_public_gold(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_source_state_head", lambda _root: "HEAD")
    monkeypatch.setattr(
        module,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )

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
    assert receipt["source_git_head"] == "HEAD"
    assert receipt["source_state_fingerprint"] == "worktree-fingerprint"
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )


@pytest.mark.parametrize(
    "origin_url",
    (
        "https://memorial.example.test",
        "https://memorial.internal",
        "https://memorial.local",
        "https://localhost",
    ),
)
def test_browser_public_origin_rejects_reserved_hostnames_without_dns(
    monkeypatch: pytest.MonkeyPatch,
    origin_url: str,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail(
            "reserved hostnames must be rejected before DNS resolution"
        ),
    )

    assert module._is_https_public_origin(origin_url) is False


def test_browser_public_origin_rejects_any_private_dns_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                module.socket.AF_INET,
                module.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 0),
            ),
            (
                module.socket.AF_INET,
                module.socket.SOCK_STREAM,
                6,
                "",
                ("10.23.45.67", 0),
            ),
        ],
    )

    assert (
        module._is_https_public_origin("https://memorial.public-origin.example.at")
        is False
    )


def test_browser_public_origin_fails_closed_on_dns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    def fail_resolution(*_args, **_kwargs):
        raise module.socket.gaierror("unit DNS failure")

    monkeypatch.setattr(module.socket, "getaddrinfo", fail_resolution)

    assert (
        module._is_https_public_origin("https://memorial.public-origin.example.at")
        is False
    )


def test_browser_public_origin_accepts_global_literal_and_global_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                module.socket.AF_INET,
                module.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 0),
            )
        ],
    )

    assert module._is_https_public_origin("https://8.8.8.8") is True
    assert (
        module._is_https_public_origin("https://memorial.public-origin.example.at")
        is True
    )


def _passing_browser_result(*, mode: str = "live") -> dict[str, object]:
    return {
        "base_url": "https://8.8.8.8",
        "slug": "manfred",
        "runtime_source_revision": "a" * 40,
        "speech_transcribe_mode": mode,
        "conversation_teardown_ok": True,
        "answer_preview": "Ja, ich bin da. Sag mir einfach, was dich beschaeftigt.",
        "audio_payload_ready": True,
        "audio_ready_for_ui": True,
        "answer_text_visible": True,
        "ui_audio_play_calls": 1,
        "ui_audio_play_ended": 1,
        "answer_semantic_passed": True,
        "first_answer_ms": 900,
    }


def test_browser_gold_receipt_requires_real_stt(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "tree")
    monkeypatch.setattr(module, "resolve_source_worktree_fingerprint", lambda _root: "state")

    receipt = module._with_exit_gate_status(
        _passing_browser_result(mode="transcript_injected"),
        exit_gate=True,
        gold_mode=True,
        require_public_origin=True,
        max_first_answer_ms=4500,
    )

    assert receipt["status"] == "fail"
    assert "gold_requires_real_stt" in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False


def test_browser_gold_receipt_requires_public_origin_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "tree")
    monkeypatch.setattr(module, "resolve_source_worktree_fingerprint", lambda _root: "state")

    receipt = module._with_exit_gate_status(
        _passing_browser_result(),
        exit_gate=True,
        gold_mode=True,
        require_public_origin=False,
        max_first_answer_ms=4500,
    )

    assert receipt["status"] == "fail"
    assert "gold_requires_public_origin_flag" in receipt["failed_codes"]


def test_browser_gold_receipt_accepts_only_https_live_public_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "tree")
    monkeypatch.setattr(module, "resolve_source_worktree_fingerprint", lambda _root: "state")

    receipt = module._with_exit_gate_status(
        _passing_browser_result(),
        exit_gate=True,
        gold_mode=True,
        require_public_origin=True,
        max_first_answer_ms=4500,
    )

    assert receipt["status"] == "pass"
    assert receipt["failed_codes"] == []
    assert receipt["gold_claim_allowed"] is True
    assert receipt["launch_proof_scope"] == "real_public_microphone"


def test_browser_exit_gate_fails_when_conversation_teardown_is_unproven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "tree")
    monkeypatch.setattr(
        module,
        "resolve_source_worktree_fingerprint",
        lambda _root: "state",
    )
    result = _passing_browser_result()
    result["conversation_teardown_ok"] = False

    receipt = module._with_exit_gate_status(
        result,
        exit_gate=True,
        gold_mode=True,
        require_public_origin=True,
        max_first_answer_ms=4500,
    )

    assert receipt["status"] == "fail"
    assert "conversation_teardown_failed" in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False


def test_browser_gold_receipt_requires_runtime_source_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "tree")
    monkeypatch.setattr(module, "resolve_source_worktree_fingerprint", lambda _root: "state")
    result = _passing_browser_result()
    result.pop("runtime_source_revision")

    receipt = module._with_exit_gate_status(
        result,
        exit_gate=True,
        gold_mode=True,
        require_public_origin=True,
        max_first_answer_ms=4500,
    )

    assert receipt["status"] == "fail"
    assert "runtime_source_revision_missing_or_invalid" in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False


def test_browser_cli_rejects_gold_without_real_stt_before_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_measure",
        lambda *_args, **_kwargs: pytest.fail("measurement must not run for invalid gold flags"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure_memorial_live_browser.py",
            "--base-url",
            "https://memorial.example.test",
            "--gold-mode",
            "--require-public-origin",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2


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


def test_chromium_startup_retry_survives_transient_target_closed_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    attempts = 0
    delays: list[float] = []

    class FakeChromium:
        def launch(self, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal attempts
            attempts += 1
            if attempts < 4:
                raise RuntimeError("TargetClosedError: signal=SIGTRAP")
            return {"browser": "ready", "kwargs": kwargs}

    fake_playwright = type("FakePlaywright", (), {"chromium": FakeChromium()})()
    monkeypatch.setattr(module.time, "sleep", lambda seconds: delays.append(seconds))

    browser, successful_attempt, launch_errors = module._launch_chromium_with_startup_retry(
        fake_playwright,
        headless=True,
    )

    assert browser["browser"] == "ready"
    assert successful_attempt == 4
    assert len(launch_errors) == 3
    assert delays == [0.75, 1.5, 3.0]


def test_short_playwright_tmpdir_avoids_long_inherited_path_and_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    inherited = "/tmp/pytest-of-tibor/" + ("deeply-nested-exit-gate/" * 6)
    monkeypatch.setenv("TMPDIR", inherited)

    with module._short_playwright_tmpdir() as browser_tmpdir:
        assert str(browser_tmpdir).startswith("/tmp/ea-pw-")
        assert len(str(browser_tmpdir)) < 64
        assert module.os.environ["TMPDIR"] == str(browser_tmpdir)

    assert module.os.environ["TMPDIR"] == inherited


def test_preferred_answer_preview_prefers_final_payload_answer_over_streamed_draft() -> None:
    module = _load_module()

    preferred = module._preferred_answer_preview(
        "Sag mir den konkreten Punkt noch etwas enger. Dann antworte ich dir direkt darauf und nicht allgemein drum herum.",
        {
            "answer": "Nein, das greift zu kurz. Die Sache musste fuer mich juristisch und im Grundsatz stimmen. Ein bequemer Weg, der das Prinzip verbiegt, ist am Ende nur eine elegante Form des Ausweichens.",
        },
    )

    assert "konkreten punkt" not in preferred.lower()
    assert "juristisch" in preferred.lower()
