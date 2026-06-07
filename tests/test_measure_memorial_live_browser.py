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


def test_measure_script_avoids_networkidle_as_primary_page_gate() -> None:
    source = Path("/docker/EA/scripts/measure_memorial_live_browser.py").read_text(encoding="utf-8")

    assert 'wait_until="domcontentloaded"' in source
    assert 'page.wait_for_load_state("networkidle", timeout=5000)' in source
    assert "speech_transcribe_mode" in source
    assert 'window.sendRealtimeTurn({ text: String(promptText || "") })' in source
    assert '"turn_error": turn_error[:240]' in source
    assert '--real-stt' in source
