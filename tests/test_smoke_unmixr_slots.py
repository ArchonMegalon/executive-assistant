from __future__ import annotations

import importlib.util
import os
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "smoke_unmixr_slots.py"


def load_module():
    spec = importlib.util.spec_from_file_location("smoke_unmixr_slots", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clear_unmixr_env() -> None:
    for key in list(os.environ):
        if key == "UNMIXR_API_KEY" or key == "UNMIXR_API_KEYS" or key.startswith("UNMIXR_API_KEY_FALLBACK_"):
            os.environ.pop(key, None)


def test_dry_run_enumerates_dynamic_slots_without_provider_call(monkeypatch) -> None:
    module = load_module()
    clear_unmixr_env()
    monkeypatch.setenv("UNMIXR_API_KEY", "primary")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_7", "seventh")
    monkeypatch.setenv("UNMIXR_API_KEYS", "pool-a pool-b")

    result = module.smoke_slots(live=False, text="Hello", voice_id="voice", language="en-US")

    assert result["mode"] == "dry_run"
    assert result["liveProviderCalled"] is False
    assert result["slotCount"] == 4
    assert [row["slotName"] for row in result["slots"]] == [
        "UNMIXR_API_KEY",
        "UNMIXR_API_KEY_FALLBACK_7",
        "UNMIXR_API_KEYS_1",
        "UNMIXR_API_KEYS_2",
    ]
    assert result["secretsExposed"] is False


def test_live_smoke_forces_one_slot_and_hashes_audio(monkeypatch) -> None:
    module = load_module()
    clear_unmixr_env()
    monkeypatch.setenv("UNMIXR_API_KEY", "primary")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_1", "fallback")
    calls: list[str] = []

    def fake_synthesize_request(*, text: str, voice_id: str, lang: str):
        calls.append(",".join(sorted(key for key in os.environ if key.startswith("UNMIXR_API_KEY"))))
        return b"RIFF....WAVE", "audio/wav"

    monkeypatch.setattr(module.voice_runtime, "unmixr_synthesize_request", fake_synthesize_request)

    result = module.smoke_slots(
        live=True,
        text="Hello",
        voice_id="voice",
        language="en-US",
        only_slot="UNMIXR_API_KEY_FALLBACK_1",
    )

    assert result["mode"] == "live"
    assert result["passedSlotCount"] == 1
    assert result["slots"][0]["slotName"] == "UNMIXR_API_KEY_FALLBACK_1"
    assert result["slots"][0]["audioProduced"] is True
    assert result["slots"][0]["audioSha256"]
    assert calls == ["UNMIXR_API_KEY_FALLBACK_1"]


def test_load_env_file_adds_missing_keys_without_overriding_existing(monkeypatch, tmp_path: Path) -> None:
    module = load_module()
    clear_unmixr_env()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "UNMIXR_API_KEY=from-file\n"
        "UNMIXR_API_KEY_FALLBACK_3=third\n"
        "UNMIXR_LANGUAGE=en-US\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNMIXR_API_KEY", "existing")

    loaded = module.load_env_file(env_file)

    assert "UNMIXR_API_KEY" not in loaded
    assert "UNMIXR_API_KEY_FALLBACK_3" in loaded
    assert os.environ["UNMIXR_API_KEY"] == "existing"
    assert os.environ["UNMIXR_API_KEY_FALLBACK_3"] == "third"
