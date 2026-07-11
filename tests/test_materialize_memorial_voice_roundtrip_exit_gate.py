from __future__ import annotations

from pathlib import Path


def test_materialize_memorial_voice_roundtrip_has_validator_dependency() -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    assert hasattr(materializer.voice_loop, "validate_memorial_voice_loop")
    assert materializer.voice_loop.validate_memorial_voice_loop.__module__ == "scripts.validate_memorial_voice_loop"


def test_materialize_memorial_voice_roundtrip_exit_gate_fails_gold_latency(monkeypatch, tmp_path: Path) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    class _Report:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "pass",
                "metrics": {
                    "direct_tts_f1": 1.0,
                    "conversation_turn_audio_f1": 1.0,
                    "conversation_turn_total_ms": 9000,
                    "speech_transcribe_ms": 5000,
                },
                "checks": [{"status": "pass", "code": "present_world_route_ok"}],
                "artifacts": {},
            }

    monkeypatch.setattr(materializer.voice_loop, "validate_memorial_voice_loop", lambda **_: _Report())
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
    monkeypatch.setattr(materializer, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(materializer, "_source_tree_fingerprint", lambda: "fingerprint")
    monkeypatch.setattr(
        materializer,
        "_probe_runtime_source_revision",
        lambda **_: ("a" * 40, None),
    )
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )

    receipt = materializer.build_receipt(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Worum geht es?",
        conversation_question="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        present_world_question="Welches Wetter haben wir heute?",
        require_stt=True,
        gold_mode=True,
        require_public_origin=True,
        direct_min_f1=0.92,
        conversation_min_f1=0.90,
        max_conversation_turn_ms=4500.0,
        max_speech_transcribe_ms=2500.0,
        critical_tokens=("worum", "geht", "es"),
    )

    assert receipt["status"] == "fail"
    assert "conversation_turn_total_ms_above_gold_threshold" in receipt["failed_codes"]
    assert "speech_transcribe_ms_above_gold_threshold" in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False
    assert receipt["source_git_head"] == "HEAD"
    assert receipt["source_tree_fingerprint"] == "fingerprint"
    assert receipt["source_state_fingerprint"] == "worktree-fingerprint"
    assert receipt["runtime_source_revision"] == "a" * 40
    assert (
        receipt["source_state_fingerprint_semantics"]
        == "worktree_source_files_sha256_excluding_generated_only_paths"
    )


def test_materialize_memorial_voice_roundtrip_fails_closed_without_runtime_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    class _Report:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "pass",
                "metrics": {},
                "checks": [],
                "artifacts": {},
            }

    monkeypatch.setattr(materializer.voice_loop, "validate_memorial_voice_loop", lambda **_: _Report())
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
    monkeypatch.setattr(materializer, "_git_head", lambda: "a" * 40)
    monkeypatch.setattr(materializer, "_source_tree_fingerprint", lambda: "fingerprint")
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )
    monkeypatch.setattr(
        materializer,
        "_probe_runtime_source_revision",
        lambda **_: (None, "header_missing_or_invalid"),
    )

    receipt = materializer.build_receipt(
        slug="manfred",
        base_url="https://example.test",
        output_dir=tmp_path,
        direct_text="Worum geht es?",
        conversation_question="Kannst du mit mir sprechen?",
        present_world_question="Welches Wetter haben wir heute?",
        require_stt=True,
        gold_mode=True,
        require_public_origin=True,
    )

    assert receipt["status"] == "fail"
    assert receipt["runtime_source_revision"] is None
    assert materializer.RUNTIME_SOURCE_REVISION_FAILURE_CODE in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False


def test_materialize_memorial_voice_roundtrip_nonpublic_receipt_omits_runtime_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    class _Report:
        def as_dict(self) -> dict[str, object]:
            return {
                "status": "pass",
                "metrics": {},
                "checks": [],
                "artifacts": {},
            }

    monkeypatch.setattr(materializer.voice_loop, "validate_memorial_voice_loop", lambda **_: _Report())
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
    monkeypatch.setattr(materializer, "_git_head", lambda: "a" * 40)
    monkeypatch.setattr(materializer, "_source_tree_fingerprint", lambda: "fingerprint")
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )
    monkeypatch.setattr(
        materializer,
        "_probe_runtime_source_revision",
        lambda **_: (_ for _ in ()).throw(AssertionError("nonpublic receipt must not probe")),
    )

    receipt = materializer.build_receipt(
        slug="manfred",
        base_url="http://127.0.0.1:8090",
        output_dir=tmp_path,
        direct_text="Worum geht es?",
        conversation_question="Kannst du mit mir sprechen?",
        present_world_question="Welches Wetter haben wir heute?",
        require_stt=False,
        gold_mode=False,
        require_public_origin=False,
    )

    assert receipt["status"] == "pass"
    assert receipt["runtime_source_revision_required"] is False
    assert "runtime_source_revision" not in receipt
