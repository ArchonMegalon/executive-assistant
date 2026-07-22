from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "compare_memorial_ltd_voice_outputs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("compare_memorial_ltd_voice_outputs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_required_unmixr_voice_id_fails_closed_without_runtime_value(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "unmixr_memorial_voice_id", lambda: "")

    with pytest.raises(RuntimeError, match="^unmixr_voice_id_missing$"):
        module._required_unmixr_voice_id()


def test_required_unmixr_voice_id_uses_private_runtime_value(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "unmixr_memorial_voice_id", lambda: "private-runtime-voice")

    assert module._required_unmixr_voice_id() == "private-runtime-voice"


def test_reference_audio_path_uses_private_profile_root(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.delenv("EA_MEMORIAL_LTD_REFERENCE_AUDIO", raising=False)
    monkeypatch.setattr(module, "private_profile_dir", lambda: tmp_path)

    assert module._reference_audio_path() == (
        tmp_path
        / "manfred"
        / "voice_profile"
        / "optimization"
        / "candidates"
        / "oSQ9FhFc4YI-01440s-28.wav"
    )


def test_compare_outputs_picks_higher_similarity(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_compare_prompt",
        lambda *, prompt, base_url, output_dir: {
            "prompt": prompt,
            "unmixr": {"similarity": 0.7, "transcript_text": prompt, "transcript_f1": 1.0},
            "voicewave": {"similarity": 0.4, "transcript_text": prompt, "transcript_f1": 1.0, "audio_path": str(output_dir / "voicewave.wav")},
        },
    )

    report = module.compare_outputs(
        base_url="http://127.0.0.1:8090",
        prompts=["Ja. Ich bin da.", "Rechtlich muss man die Dinge sauber unterscheiden."],
        output_dir=tmp_path,
    )

    assert report["winner"] == "unmixr"
    assert report["averages"]["unmixr_similarity"] == 0.7
    assert report["averages"]["voicewave_similarity"] == 0.4
    assert report["averages"]["unmixr_transcript_f1"] == 1.0
    assert report["averages"]["voicewave_transcript_f1"] == 1.0
    assert report["voicewave_backup_candidate"]["status"] == "blocked"


def test_voicewave_backup_candidate_marks_ready_for_clean_rows(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_compare_prompt",
        lambda *, prompt, base_url, output_dir: {
            "prompt": prompt,
            "unmixr": {"similarity": 0.7, "transcript_text": prompt, "transcript_f1": 1.0},
            "voicewave": {"similarity": 0.61, "transcript_text": prompt, "transcript_f1": 0.96, "audio_path": str(output_dir / "voicewave.wav")},
        },
    )

    report = module.compare_outputs(
        base_url="http://127.0.0.1:8090",
        prompts=["Ja. Ich bin da.", "Rechtlich muss man die Dinge sauber unterscheiden."],
        output_dir=tmp_path,
    )

    candidate = report["voicewave_backup_candidate"]
    assert candidate["status"] == "ready"
    assert candidate["drift_prompts"] == []


def test_compare_outputs_tolerates_blocked_unmixr_rows(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "_compare_prompt",
        lambda *, prompt, base_url, output_dir: {
            "prompt": prompt,
            "unmixr": {"similarity": 0.0, "transcript_text": "", "transcript_f1": 0.0, "status": "blocked", "detail": "Request was throttled"},
            "voicewave": {"similarity": 0.62, "transcript_text": prompt, "transcript_f1": 0.95, "audio_path": str(output_dir / "voicewave.wav")},
        },
    )

    report = module.compare_outputs(
        base_url="http://127.0.0.1:8090",
        prompts=["Ja. Ich bin da.", "Rechtlich muss man die Dinge sauber unterscheiden."],
        output_dir=tmp_path,
    )

    assert report["unmixr_status"] == "blocked"
    assert report["winner"] == "voicewave"
    assert report["voicewave_backup_candidate"]["status"] == "ready"
