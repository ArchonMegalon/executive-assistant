from __future__ import annotations

import json
from pathlib import Path


class _PassingReport:
    def as_dict(self) -> dict[str, object]:
        return {
            "status": "pass",
            "metrics": {
                "direct_tts_f1": 1.0,
                "conversation_turn_audio_f1": 1.0,
                "conversation_turn_total_ms": 900,
                "speech_transcribe_ms": 500,
            },
            "checks": [
                {
                    "status": "pass",
                    "code": "present_world_route_ok",
                }
            ],
            "artifacts": {},
        }


def _private_review_session(materializer, *, revision: str, token: str):
    return materializer.ReviewSessionClientAuth(
        origin="https://myexternalbrain.com",
        slug="manfred",
        source_revision=revision,
        image_id=f"sha256:{'b' * 64}",
        voice_identity_sha256="c" * 64,
        expires_at=2_000_000_000,
        _token=token,
    )


def test_materialize_memorial_voice_roundtrip_has_validator_dependency() -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    assert hasattr(materializer.voice_loop, "validate_memorial_voice_loop")
    assert materializer.voice_loop.validate_memorial_voice_loop.__module__ == "scripts.validate_memorial_voice_loop"


def test_runtime_revision_probe_identifies_initial_and_redirected_requests(
    monkeypatch,
) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    revision = "a" * 40
    observed_user_agents: list[str | None] = []

    class Response:
        headers = {materializer.RUNTIME_SOURCE_REVISION_HEADER: revision}

        def geturl(self) -> str:
            return "https://myexternalbrain.com/memorials/manfred.json"

        def getcode(self) -> int:
            return 200

        def read(self, _size: int) -> bytes:
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class Opener:
        def __init__(self, handler) -> None:
            self.handler = handler

        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            assert timeout == materializer.RUNTIME_SOURCE_REVISION_TIMEOUT_SECONDS
            observed_user_agents.append(request.get_header("User-agent"))
            redirected = self.handler.redirect_request(
                request,
                None,
                307,
                "Temporary Redirect",
                {},
                "/memorials/manfred.json",
            )
            observed_user_agents.append(redirected.get_header("User-agent"))
            return Response()

    monkeypatch.setattr(
        materializer,
        "build_opener",
        lambda handler: Opener(handler),
    )

    assert materializer._probe_runtime_source_revision(
        base_url="https://myexternalbrain.com",
        slug="manfred",
        request_headers={"User-Agent": "blocked-client"},
    ) == (revision, None)
    assert observed_user_agents == [
        materializer.REVIEW_HTTP_USER_AGENT,
        materializer.REVIEW_HTTP_USER_AGENT,
    ]


def test_private_review_roundtrip_propagates_auth_but_receipt_exposes_only_safe_binding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    revision = "a" * 40
    raw_token = "super-secret-review-token"
    review_session = _private_review_session(
        materializer,
        revision=revision,
        token=raw_token,
    )
    validator_calls: list[dict[str, object]] = []
    probe_calls: list[dict[str, object]] = []

    def fake_validate(**kwargs):
        validator_calls.append(kwargs)
        return _PassingReport()

    def fake_probe(**kwargs):
        probe_calls.append(kwargs)
        return revision, None

    monkeypatch.setattr(
        materializer.voice_loop,
        "validate_memorial_voice_loop",
        fake_validate,
    )
    monkeypatch.setattr(
        materializer,
        "_probe_runtime_source_revision",
        fake_probe,
    )
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
    monkeypatch.setattr(materializer, "_git_head", lambda: revision)
    monkeypatch.setattr(
        materializer,
        "_source_tree_fingerprint",
        lambda: "fingerprint",
    )
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )

    receipt = materializer.build_receipt(
        slug="manfred",
        base_url="https://myexternalbrain.com",
        output_dir=tmp_path,
        direct_text="Worum geht es?",
        conversation_question="Hallo Manfred, kannst du mit mir sprechen?",
        present_world_question="Welches Wetter haben wir heute?",
        require_stt=True,
        gold_mode=True,
        require_public_origin=True,
        review_session=review_session,
    )

    expected_headers = review_session.request_headers()
    assert validator_calls == [
        {
            "slug": "manfred",
            "base_url": "https://myexternalbrain.com",
            "output_dir": tmp_path,
            "direct_text": "Worum geht es?",
            "conversation_question": "Hallo Manfred, kannst du mit mir sprechen?",
            "present_world_question": "Welches Wetter haben wir heute?",
            "require_stt": True,
            "gold_mode": True,
            "direct_min_f1": 0.92,
            "conversation_min_f1": 0.90,
            "critical_tokens": (),
            "request_headers": expected_headers,
        }
    ]
    assert probe_calls == [
        {
            "base_url": "https://myexternalbrain.com",
            "slug": "manfred",
            "request_headers": expected_headers,
        }
    ]
    assert receipt["status"] == "pass"
    assert receipt["runtime_source_revision"] == revision
    assert receipt["access_mode"] == "private_review_session"
    assert receipt["evidence_scope"] == "private_authenticated_review"
    assert receipt["review_session_authenticated"] is True
    assert receipt["review_session_binding"] == review_session.public_binding()
    assert receipt["gold_claim_allowed"] is False
    assert receipt["private_review_evidence_allowed"] is True

    rendered = json.dumps(receipt, sort_keys=True)
    assert raw_token not in rendered
    assert "ea_manfred_voice_review" not in rendered
    assert '"Cookie"' not in rendered
    assert '"Origin"' not in rendered
    assert "request_headers" not in rendered
    assert "review-session-cookie-file" not in rendered


def test_private_review_roundtrip_is_not_release_evidence_when_dirty_or_revision_mismatched(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.materialize_memorial_voice_roundtrip_exit_gate as materializer

    revision = "a" * 40
    review_session = _private_review_session(
        materializer,
        revision=revision,
        token="private-review-token",
    )
    monkeypatch.setattr(
        materializer.voice_loop,
        "validate_memorial_voice_loop",
        lambda **_kwargs: _PassingReport(),
    )
    monkeypatch.setattr(materializer, "_git_head", lambda: revision)
    monkeypatch.setattr(
        materializer,
        "_source_tree_fingerprint",
        lambda: "fingerprint",
    )
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )

    for dirty, runtime_revision in (
        (True, revision),
        (False, "d" * 40),
    ):
        monkeypatch.setattr(
            materializer,
            "_git_dirty",
            lambda dirty=dirty: dirty,
        )
        monkeypatch.setattr(
            materializer,
            "_probe_runtime_source_revision",
            lambda runtime_revision=runtime_revision, **_kwargs: (
                runtime_revision,
                None,
            ),
        )
        receipt = materializer.build_receipt(
            slug="manfred",
            base_url="https://myexternalbrain.com",
            output_dir=tmp_path,
            direct_text="Worum geht es?",
            conversation_question="Hallo Manfred",
            present_world_question="Welches Wetter haben wir heute?",
            require_stt=True,
            gold_mode=True,
            require_public_origin=True,
            review_session=review_session,
        )

        assert receipt["gold_claim_allowed"] is False
        assert receipt["private_review_evidence_allowed"] is False


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
