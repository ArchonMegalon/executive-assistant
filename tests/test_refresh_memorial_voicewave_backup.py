from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "ea" / "scripts" / "refresh_memorial_voicewave_backup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("refresh_memorial_voicewave_backup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_refresh_records_blocked_candidate(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module._COMPARE,
        "compare_outputs",
        lambda **kwargs: {
            "winner": "unmixr",
            "averages": {
                "unmixr_similarity": 0.7,
                "voicewave_similarity": 0.41,
                "unmixr_transcript_f1": 1.0,
                "voicewave_transcript_f1": 0.62,
            },
            "voicewave_backup_candidate": {
                "status": "blocked",
                "reason": "voicewave_backup_gate_failed",
                "average_similarity": 0.41,
                "average_transcript_f1": 0.62,
                "min_transcript_f1": 0.55,
                "drift_prompts": ["Ja. Ich bin da."],
            },
        },
    )

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        prompts=["Ja. Ich bin da."],
        compare_output_dir=tmp_path / "compare",
        compare_output_path=tmp_path / "compare.generated.json",
        apply_metadata=False,
    )

    assert result["status"] == "blocked"
    assert result["applied_metadata"] is False
    assert result["voicewave_backup_candidate"]["reason"] == "voicewave_backup_gate_failed"


def test_run_refresh_reports_compare_failure_as_blocked(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(json.dumps({"tts_plugin": "unmixr_clone"}), encoding="utf-8")
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)

    def _raise(**kwargs):
        raise RuntimeError("Request was throttled. Expected available in 2022 seconds.:429")

    monkeypatch.setattr(module._COMPARE, "compare_outputs", _raise)

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        prompts=["Ja. Ich bin da."],
        compare_output_dir=tmp_path / "compare",
        compare_output_path=tmp_path / "compare.generated.json",
        apply_metadata=True,
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["applied_metadata"] is True
    assert result["voicewave_backup_candidate"]["reason"] == "compare_failed"
    assert "throttled" in result["voicewave_backup_candidate"]["detail"].lower()
    assert payload["tts_backup_candidates"]["voicewave"]["reason"] == "compare_failed"


def test_run_refresh_persists_ready_candidate_metadata(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(json.dumps({"tts_plugin": "unmixr_clone"}), encoding="utf-8")
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)
    monkeypatch.setattr(
        module._COMPARE,
        "compare_outputs",
        lambda **kwargs: {
            "winner": "unmixr",
            "averages": {
                "unmixr_similarity": 0.7,
                "voicewave_similarity": 0.61,
                "unmixr_transcript_f1": 1.0,
                "voicewave_transcript_f1": 0.95,
            },
            "voicewave_backup_candidate": {
                "status": "ready",
                "reason": "",
                "average_similarity": 0.61,
                "average_transcript_f1": 0.95,
                "min_transcript_f1": 0.92,
                "drift_prompts": [],
            },
        },
    )

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        prompts=["Ja. Ich bin da."],
        compare_output_dir=tmp_path / "compare",
        compare_output_path=tmp_path / "compare.generated.json",
        apply_metadata=True,
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert result["status"] == "ready"
    assert result["applied_metadata"] is True
    assert payload["tts_backup_candidates"]["voicewave"]["status"] == "ready"
    assert payload["tts_backup_candidates"]["voicewave"]["voice_label"] == "Manfred Hoza Memorial"
