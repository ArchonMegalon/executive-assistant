from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "materialize_memorial_room_audio_attestation_packet.py"
    spec = importlib.util.spec_from_file_location("materialize_memorial_room_audio_attestation_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_room_audio_attestation_packet_is_manual_and_complete(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "HEAD")

    packet = module.build_packet(
        argparse.Namespace(base_url="https://memorial.example.test", slug="manfred", output=""),
        generated_at="2026-06-19T12:00:00Z",
    )

    assert packet["contract_name"] == "ea.memorial_room_audio_attestation_packet"
    assert packet["status"] == "ready"
    assert packet["source_git_head"] == "HEAD"
    assert packet["manual_only"] is True
    assert packet["ci_must_not_auto_assert"] is True
    assert packet["operator_command"] == "make materialize-memorial-room-audio-gold-clean"
    assert "make materialize-memorial-room-audio-gold-clean" in packet["receipt_command_template"]
    assert packet["proof_target"] == ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
    check_ids = {item["id"] for item in packet["required_checks"]}
    assert "normal_spoken_turn_confirmed" in check_ids
    assert "interruption_behavior_confirmed" in check_ids
    assert "retry_path_confirmed" in check_ids
    check_flags = {item["cli_flag"] for item in packet["required_checks"]}
    assert "--normal-spoken-turn-confirmed" in check_flags
    assert "--interruption-behavior-confirmed" in packet["required_cli_flags"]
    assert packet["required_env"]["MEMORIAL_PUBLIC_ORIGIN"] == "https://memorial.example.test"
    assert packet["required_env"]["MEMORIAL_PUBLIC_SLUG"] == "manfred"
    assert any("non-generic" in item for item in packet["operator_steps"])
    assert any("first syllable" in item.lower() for item in packet["acceptance"])


def test_room_audio_attestation_packet_main_writes_json(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "HEAD")
    output = tmp_path / "packet.json"
    monkeypatch.setattr(module, "DEFAULT_OUTPUT", output)

    assert module.main([]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["proof_target"] == ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
