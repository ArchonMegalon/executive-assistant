from __future__ import annotations

from pathlib import Path


def test_memorial_voice_stability_gate_passes_when_all_runs_pass(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_voice_stability_gate as stability

    def fake_build_receipt(**kwargs):
        return {
            "status": "pass",
            "failed_codes": [],
            "warned_codes": [],
            "metrics": {
                "direct_tts_f1": 1.0,
                "conversation_turn_audio_f1": 0.9,
            },
        }

    monkeypatch.setattr(stability, "build_receipt", fake_build_receipt)

    payload = stability.run_stability_gate(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        runs=3,
        require_stt=True,
    )

    assert payload["status"] == "pass"
    assert payload["runs_completed"] == 3
    assert payload["failed_runs"] == []
    assert payload["direct_tts_f1"]["min"] == 1.0
    assert payload["conversation_turn_audio_f1"]["mean"] == 0.9


def test_memorial_voice_stability_gate_fails_on_any_failed_run(tmp_path: Path, monkeypatch) -> None:
    import scripts.verify_memorial_voice_stability_gate as stability

    calls = {"count": 0}

    def fake_build_receipt(**kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            return {
                "status": "fail",
                "failed_codes": ["conversation_turn_audio_similarity_bad"],
                "warned_codes": [],
                "metrics": {"direct_tts_f1": 1.0, "conversation_turn_audio_f1": 0.4},
            }
        return {
            "status": "pass",
            "failed_codes": [],
            "warned_codes": [],
            "metrics": {"direct_tts_f1": 1.0, "conversation_turn_audio_f1": 0.9},
        }

    monkeypatch.setattr(stability, "build_receipt", fake_build_receipt)

    payload = stability.run_stability_gate(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        runs=3,
        require_stt=True,
    )

    assert payload["status"] == "fail"
    assert payload["failed_runs"] == [
        {
            "run": 2,
            "status": "fail",
            "failed_codes": ["conversation_turn_audio_similarity_bad"],
            "warned_codes": [],
        }
    ]
