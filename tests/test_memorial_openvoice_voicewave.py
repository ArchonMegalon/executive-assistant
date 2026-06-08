from __future__ import annotations

from pathlib import Path

from app.services import memorial_openvoice


def test_voicewave_runtime_script_path_prefers_existing_container_path(monkeypatch) -> None:
    host_path = Path("/docker/EA/scripts/voicewave_memorial_voice.py")
    container_path = Path("/app/scripts/voicewave_memorial_voice.py")

    monkeypatch.setattr(
        memorial_openvoice,
        "_VOICEWAVE_SCRIPT_CANDIDATES",
        (host_path, container_path),
    )
    monkeypatch.setattr(Path, "is_file", lambda self: self == container_path)

    assert memorial_openvoice.voicewave_runtime_script_path() == container_path


def test_voicewave_runtime_script_path_falls_back_to_first_candidate(monkeypatch) -> None:
    first_path = Path("/docker/EA/scripts/voicewave_memorial_voice.py")
    second_path = Path("/app/scripts/voicewave_memorial_voice.py")

    monkeypatch.setattr(
        memorial_openvoice,
        "_VOICEWAVE_SCRIPT_CANDIDATES",
        (first_path, second_path),
    )
    monkeypatch.setattr(Path, "is_file", lambda self: False)

    assert memorial_openvoice.voicewave_runtime_script_path() == first_path


def test_voicewave_synthesize_request_uses_cached_audio(monkeypatch, tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    audio_path = cache_root / "cached.wav"
    meta_path = cache_root / "cached.json"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"cached-audio")
    meta_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("VOICEWAVE_LOGIN_EMAIL", "voicewave@example.com")
    monkeypatch.setenv("VOICEWAVE_LOGIN_PASSWORD", "secret")
    monkeypatch.setattr(memorial_openvoice, "_VOICEWAVE_CACHE_ROOT_CANDIDATES", (cache_root,))
    monkeypatch.setattr(
        memorial_openvoice,
        "_voicewave_cache_paths",
        lambda **kwargs: (audio_path, meta_path),
    )
    monkeypatch.setattr(
        memorial_openvoice,
        "voicewave_runtime_script_path",
        lambda: Path("/missing/script.py"),
    )

    payload, content_type = memorial_openvoice.voicewave_synthesize_request(
        text="Ich bin da.",
        voice_label="Manfred Hoza Memorial",
    )

    assert payload == b"cached-audio"
    assert content_type == "audio/wav"
