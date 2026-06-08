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
