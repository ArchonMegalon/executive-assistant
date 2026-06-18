from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path("/docker/EA/scripts/materialize_memorial_room_audio_receipt.py")
    spec = importlib.util.spec_from_file_location("materialize_memorial_room_audio_receipt", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_room_audio_receipt_fails_closed_until_every_manual_check_is_present(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "fingerprint")

    args = module.argparse.Namespace(
        base_url="https://memorial.example.test",
        slug="manfred",
        output="",
        reviewer="",
        device_label="",
        speaker_label="",
        room_label="",
        notes="",
        manual_attestation_id="room-review-001",
        manual_attestation_signed_at="2026-06-18T12:00:00Z",
        manual_attestation_source="operator_room_review",
        require_public_origin=True,
        actual_device_checked=True,
        actual_speaker_checked=True,
        first_syllable_not_clipped=False,
        intelligibility_confirmed=True,
        answer_text_fallback_visible=True,
        no_internet_search_confirmed=True,
    )

    receipt = module.build_receipt(args)

    assert receipt["status"] == "fail"
    assert "reviewer_missing" in receipt["failed_codes"]
    assert "first_syllable_not_clipped_missing" in receipt["failed_codes"]


def test_room_audio_receipt_passes_for_complete_public_origin_check(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "fingerprint")

    args = module.argparse.Namespace(
        base_url="https://memorial.example.test",
        slug="manfred",
        output="",
        reviewer="Tibor",
        device_label="presentation laptop",
        speaker_label="room speaker",
        room_label="chapel",
        notes="audible and readable",
        manual_attestation_id="room-review-001",
        manual_attestation_signed_at="2026-06-18T12:00:00Z",
        manual_attestation_source="operator_room_review",
        require_public_origin=True,
        actual_device_checked=True,
        actual_speaker_checked=True,
        first_syllable_not_clipped=True,
        intelligibility_confirmed=True,
        answer_text_fallback_visible=True,
        no_internet_search_confirmed=True,
    )

    receipt = module.build_receipt(args)

    assert receipt["status"] == "pass"
    assert receipt["gold_claim_allowed"] is True
    assert receipt["source_git_head"] == "HEAD"
    assert receipt["source_tree_fingerprint"] == "fingerprint"
    assert receipt["proof_type"] == "manual_room_attestation"
    assert receipt["manual_attestation"]["attestation_id"] == "room-review-001"
    assert receipt["manual_attestation"]["ci_must_not_auto_assert"] is True


def test_room_audio_receipt_requires_manual_attestation(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_dirty", lambda: False)
    monkeypatch.setattr(module, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(module, "_source_tree_fingerprint", lambda: "fingerprint")

    args = module.argparse.Namespace(
        base_url="https://memorial.example.test",
        slug="manfred",
        output="",
        reviewer="Tibor",
        device_label="presentation laptop",
        speaker_label="room speaker",
        room_label="chapel",
        notes="audible and readable",
        manual_attestation_id="",
        manual_attestation_signed_at="",
        manual_attestation_source="operator_room_review",
        require_public_origin=True,
        actual_device_checked=True,
        actual_speaker_checked=True,
        first_syllable_not_clipped=True,
        intelligibility_confirmed=True,
        answer_text_fallback_visible=True,
        no_internet_search_confirmed=True,
    )

    receipt = module.build_receipt(args)

    assert receipt["status"] == "fail"
    assert "manual_attestation_id_missing" in receipt["failed_codes"]
    assert "manual_attestation_signed_at_missing" in receipt["failed_codes"]
