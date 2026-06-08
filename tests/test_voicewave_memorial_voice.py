from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "voicewave_memorial_voice.py"
    spec = importlib.util.spec_from_file_location("voicewave_memorial_voice", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_catalog_summary_reports_visible_clone_names() -> None:
    module = _load_script()

    summary = module._catalog_summary(
        {
            "cloneCountLabel": "My Clones 1",
            "cloneNames": ["Manfred Hoza Memorial"],
            "cloneVisible": True,
            "selectedVoiceBefore": "Luna Smith",
            "url": "https://space.voicewave.ai/",
            "title": "VoiceWave Studio",
            "bodyText": "My Clones 1\nManfred Hoza Memorial\nUse",
            "warnings": [],
            "errors": [],
        },
        requested_voice_label="Manfred Hoza Memorial",
    )

    assert summary["provider_key"] == "voicewave"
    assert summary["mode"] == "catalog"
    assert summary["clone_visible"] is True
    assert summary["clone_names"] == ["Manfred Hoza Memorial"]


def test_clone_summary_includes_reference_hash(tmp_path: Path) -> None:
    module = _load_script()
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference-audio")

    summary = module._clone_summary(
        {
            "cloneAlreadyPresent": True,
            "cloneVisible": True,
            "cloneCountLabel": "My Clones 1",
            "cloneNames": ["Manfred Hoza Memorial"],
            "selectedVoiceBefore": "Luna Smith",
            "selectedVoiceAfter": "Manfred Hoza Memorial",
            "url": "https://space.voicewave.ai/",
            "title": "VoiceWave Studio",
            "bodyText": "Manfred Hoza Memorial ready.",
            "warnings": [],
            "errors": [],
        },
        voice_label="Manfred Hoza Memorial",
        reference_audio_path=reference,
    )

    assert summary["mode"] == "clone"
    assert summary["clone_already_present"] is True
    assert summary["clone_visible"] is True
    assert summary["selected_voice_after"] == "Manfred Hoza Memorial"
    assert summary["reference_audio_sha256"] == module._sha256_file(reference)


def test_render_summary_requires_downloaded_audio_file(tmp_path: Path) -> None:
    module = _load_script()
    audio = tmp_path / "render.wav"
    audio.write_bytes(b"wav-bytes")
    screenshot = tmp_path / "render.png"
    screenshot.write_bytes(b"png-bytes")

    summary = module._render_summary(
        {
            "downloadSuggestedFilename": "voicewave-ai.wav",
            "downloaded": True,
            "selectedVoiceBefore": "Luna Smith",
            "selectedVoiceAfter": "Manfred Hoza Memorial",
            "cloneVisible": True,
            "cloneCountLabel": "My Clones 1",
            "url": "https://space.voicewave.ai/",
            "title": "VoiceWave Studio",
            "bodyText": "Exported audio.",
            "warnings": [],
            "errors": [],
        },
        voice_label="Manfred Hoza Memorial",
        text="Ich bin da.",
        screenshot_path=screenshot,
        audio_path=audio,
    )

    assert summary["mode"] == "render"
    assert summary["downloaded"] is True
    assert summary["audio_size_bytes"] == len(b"wav-bytes")
    assert summary["audio_sha256"] == module._sha256_file(audio)
    assert summary["screenshot_path"] == screenshot.as_posix()


def test_write_json_persists_payload(tmp_path: Path) -> None:
    module = _load_script()
    path = tmp_path / "payload.json"
    payload = {"provider_key": "voicewave", "mode": "catalog"}
    module._write_json(path, payload)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload
