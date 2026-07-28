from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "refresh_memorial_unmixr_clone.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("refresh_memorial_unmixr_clone", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_refresh_reports_blocked_clone(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    seg = tmp_path / "seg.wav"
    seg.write_bytes(b"seg")
    monkeypatch.setattr(module._REFRESH_PACKET, "DEFAULT_SEGMENTS", (str(seg),))
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "build_packet",
        lambda **kwargs: {"slug": "manfred", "segments": [{"path": str(seg)}], "clone_attempt": {}},
    )
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "attempt_clone",
        lambda **kwargs: {"status": "blocked", "code": "unmixr_clone_blocked", "detail": "limit"},
    )

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet" / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation" / "report.json",
        apply_if_better=True,
    )

    assert result["status"] == "blocked"
    assert result["clone_attempt"]["code"] == "unmixr_clone_blocked"


def test_run_refresh_applies_new_winner(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    seg = tmp_path / "seg.wav"
    seg.write_bytes(b"seg")
    monkeypatch.setattr(module._REFRESH_PACKET, "DEFAULT_SEGMENTS", (str(seg),))
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "build_packet",
        lambda **kwargs: {"slug": "manfred", "segments": [{"path": str(seg)}], "clone_attempt": {}},
    )
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "attempt_clone",
        lambda **kwargs: {"status": "created", "voice_id": "new-voice"},
    )
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(json.dumps({"tts_plugin_voice_id": "old-voice"}), encoding="utf-8")
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)
    monkeypatch.setattr(
        module._COMPARE,
        "compare_unmixr_clones_two_stage",
        lambda **kwargs: {
            "winner": {"voice_id": "new-voice"},
            "recommended_config": {
                "tts_plugin": "unmixr_clone",
                "tts_plugin_voice_id": "new-voice",
                "voice_profile_id": "new-voice",
                "voice_label": "Manfred Hoza · Unmixr-Klon",
                "tts_base_voice_variant": "unmixr",
                "unmixr_speaking_rate": "medium",
                "unmixr_speaking_pitch": "medium",
                "unmixr_speaking_volume": "low",
                "tts_postprocess_profile": "unmixr_raw_preserve",
            },
        },
    )
    monkeypatch.setattr(module, "_write_live_volume_voice_config", lambda **kwargs: {"status": "updated"})
    monkeypatch.setattr(module, "_restart_ea_api", lambda: {"status": "restarted"})

    class _Report:
        status = "pass"

        @staticmethod
        def as_dict():
            return {"status": "pass"}

    monkeypatch.setattr(module._VALIDATE, "validate_memorial_voice_loop", lambda **kwargs: _Report())

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet" / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation" / "report.json",
        apply_if_better=True,
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert result["validation_status"] == "pass"
    assert payload["tts_plugin_voice_id"] == "new-voice"


def test_run_refresh_rolls_back_when_validation_fails(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    seg = tmp_path / "seg.wav"
    seg.write_bytes(b"seg")
    monkeypatch.setattr(module._REFRESH_PACKET, "DEFAULT_SEGMENTS", (str(seg),))
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "build_packet",
        lambda **kwargs: {"slug": "manfred", "segments": [{"path": str(seg)}], "clone_attempt": {}},
    )
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "attempt_clone",
        lambda **kwargs: {"status": "created", "voice_id": "new-voice"},
    )
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(json.dumps({"tts_plugin_voice_id": "old-voice"}), encoding="utf-8")
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)
    monkeypatch.setattr(
        module._COMPARE,
        "compare_unmixr_clones_two_stage",
        lambda **kwargs: {
            "winner": {"voice_id": "new-voice"},
            "recommended_config": {
                "tts_plugin": "unmixr_clone",
                "tts_plugin_voice_id": "new-voice",
                "voice_profile_id": "new-voice",
                "voice_label": "Manfred Hoza · Unmixr-Klon",
                "tts_base_voice_variant": "unmixr",
                "unmixr_speaking_rate": "medium",
                "unmixr_speaking_pitch": "medium",
                "unmixr_speaking_volume": "low",
                "tts_postprocess_profile": "unmixr_raw_preserve",
            },
        },
    )
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(module, "_write_live_volume_voice_config", lambda **kwargs: writes.append(kwargs) or {"status": "updated"})
    monkeypatch.setattr(module, "_restart_ea_api", lambda: {"status": "restarted"})

    class _Report:
        status = "fail"

        @staticmethod
        def as_dict():
            return {"status": "fail"}

    monkeypatch.setattr(module._VALIDATE, "validate_memorial_voice_loop", lambda **kwargs: _Report())

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet" / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation" / "report.json",
        apply_if_better=True,
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["applied"] is False
    assert result["rolled_back"] is True
    assert payload["tts_plugin_voice_id"] == "old-voice"
    assert len(writes) == 2


def test_run_refresh_reports_blocked_compare(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    seg = tmp_path / "seg.wav"
    seg.write_bytes(b"seg")
    monkeypatch.setattr(module._REFRESH_PACKET, "DEFAULT_SEGMENTS", (str(seg),))
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "build_packet",
        lambda **kwargs: {"slug": "manfred", "segments": [{"path": str(seg)}], "clone_attempt": {}},
    )
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "attempt_clone",
        lambda **kwargs: {"status": "created", "voice_id": "new-voice"},
    )
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(json.dumps({"tts_plugin_voice_id": "old-voice"}), encoding="utf-8")
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)
    monkeypatch.setattr(
        module._COMPARE,
        "compare_unmixr_clones_two_stage",
        lambda **kwargs: {
            "blocked": {
                "status": "throttled",
                "retry_after_seconds": 4439,
            },
            "winner": {},
            "recommended_config": {},
        },
    )

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet" / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation" / "report.json",
        apply_if_better=True,
    )

    assert result["status"] == "blocked"
    assert result["blocked"]["retry_after_seconds"] == 4439
    assert result["applied"] is False


def test_run_refresh_resolves_runtime_voice_and_binds_candidate_accounts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    seg = tmp_path / "seg.wav"
    seg.write_bytes(b"seg")
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "build_packet",
        lambda **kwargs: {"slug": "manfred", "segments": []},
    )
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "attempt_clone",
        lambda **kwargs: {
            "status": "created",
            "voice_id": "new-voice",
            "account_slot": "UNMIXR_API_KEY_FALLBACK_2",
        },
    )
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(
        json.dumps(
            {
                "tts_plugin_voice_id": "${UNMIXR_VOICE_ID}",
                "unmixr_account_slot": "UNMIXR_API_KEY",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)
    monkeypatch.setenv("UNMIXR_VOICE_ID", "runtime-old-voice")
    compare_calls: list[dict[str, object]] = []

    def compare(**kwargs):
        compare_calls.append(dict(kwargs))
        return {
            "blocked": {"status": "quality_gate_failed"},
            "winner": {},
            "recommended_config": {},
        }

    monkeypatch.setattr(module._COMPARE, "compare_unmixr_clones_two_stage", compare)

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet" / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation" / "report.json",
        apply_if_better=True,
        segment_paths=[seg],
        account_slot="UNMIXR_API_KEY_FALLBACK_2",
    )

    assert result["status"] == "blocked"
    assert compare_calls[0]["voice_ids"] == [
        "runtime-old-voice",
        "new-voice",
    ]
    assert compare_calls[0]["account_slots_by_voice"] == {
        "runtime-old-voice": "UNMIXR_API_KEY",
        "new-voice": "UNMIXR_API_KEY_FALLBACK_2",
    }


def test_run_refresh_blocks_before_paid_clone_when_current_voice_is_unresolved(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    seg = tmp_path / "seg.wav"
    seg.write_bytes(b"seg")
    monkeypatch.setattr(
        module._REFRESH_PACKET,
        "build_packet",
        lambda **kwargs: {"slug": "manfred", "segments": []},
    )
    clone_called = False

    def attempt_clone(**kwargs):
        nonlocal clone_called
        clone_called = True
        return {"status": "created", "voice_id": "unexpected"}

    monkeypatch.setattr(module._REFRESH_PACKET, "attempt_clone", attempt_clone)
    config_path = tmp_path / "tts_voice.json"
    config_path.write_text(
        json.dumps({"tts_plugin_voice_id": "${UNMIXR_VOICE_ID}"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_voice_config_path", lambda slug: config_path)
    monkeypatch.setattr(module, "_resolve_runtime_reference", lambda value: "")

    result = module.run_refresh(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        voice_label="Refresh",
        packet_output_dir=tmp_path / "packet",
        packet_output_path=tmp_path / "packet" / "packet.json",
        compare_output_path=tmp_path / "compare.json",
        validation_output_dir=tmp_path / "validation",
        validation_output_path=tmp_path / "validation" / "report.json",
        apply_if_better=True,
        segment_paths=[seg],
    )

    assert result["status"] == "blocked"
    assert result["code"] == "current_voice_id_unresolved"
    assert clone_called is False
