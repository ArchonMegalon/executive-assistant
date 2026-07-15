from __future__ import annotations

import argparse
import importlib
import json
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.materialize_memorial_voice_roundtrip_exit_gate",
        "scripts.materialize_memorial_room_audio_receipt",
    ],
)
def test_runtime_revision_probe_uses_bounded_canonical_memorial_json_request(
    monkeypatch,
    module_name: str,
) -> None:
    materializer = importlib.import_module(module_name)
    revision = "9" * 40
    opened: dict[str, object] = {}

    class _Response:
        headers = {materializer.RUNTIME_SOURCE_REVISION_HEADER: revision}

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def geturl(self) -> str:
            return "https://example.test/memorials/manfred.json"

        def getcode(self) -> int:
            return 200

        def read(self, limit: int) -> bytes:
            opened["read_limit"] = limit
            return b'{"slug":"manfred"}'

    class _Opener:
        def open(self, request, *, timeout: float):  # noqa: ANN001
            opened["url"] = request.full_url
            opened["timeout"] = timeout
            return _Response()

    monkeypatch.setattr(materializer, "build_opener", lambda *_handlers: _Opener())

    resolved, reason = materializer._probe_runtime_source_revision(
        base_url="https://example.test/",
        slug="manfred",
    )

    assert resolved == revision
    assert reason is None
    assert opened["url"] == "https://example.test/memorials/manfred.json"
    assert opened["timeout"] == materializer.RUNTIME_SOURCE_REVISION_TIMEOUT_SECONDS
    assert opened["read_limit"] == materializer.RUNTIME_SOURCE_REVISION_MAX_BODY_BYTES + 1


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.materialize_memorial_voice_roundtrip_exit_gate",
        "scripts.materialize_memorial_room_audio_receipt",
    ],
)
def test_runtime_revision_probe_rejects_cross_origin_final_url(
    monkeypatch,
    module_name: str,
) -> None:
    materializer = importlib.import_module(module_name)

    class _Response:
        headers = {materializer.RUNTIME_SOURCE_REVISION_HEADER: "9" * 40}

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def geturl(self) -> str:
            return "https://redirected.example/memorials/manfred.json"

        def getcode(self) -> int:
            return 200

        def read(self, _limit: int) -> bytes:
            raise AssertionError("cross-origin response body must not be read")

    class _Opener:
        def open(self, _request, *, timeout: float):
            del timeout
            return _Response()

    monkeypatch.setattr(materializer, "build_opener", lambda *_handlers: _Opener())

    resolved, reason = materializer._probe_runtime_source_revision(
        base_url="https://example.test",
        slug="manfred",
    )

    assert resolved is None
    assert reason == "cross_origin_final_url"


def test_source_revision_middleware_emits_only_valid_lowercase_revision(monkeypatch) -> None:
    from app.api import app as app_module

    revision = "a" * 40
    monkeypatch.setenv("EA_SOURCE_REVISION", revision)
    application = FastAPI()
    app_module.install_source_revision_header(application)

    @application.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(application) as client:
        response = client.get("/probe")

    assert response.status_code == 200
    assert response.headers["X-EA-Source-Revision"] == revision


@pytest.mark.parametrize("invalid_revision", ["", "A" * 40, "a" * 39, f"{'a' * 40} "])
def test_source_revision_middleware_omits_invalid_revision(monkeypatch, invalid_revision: str) -> None:
    from app.api import app as app_module

    monkeypatch.setenv("EA_SOURCE_REVISION", invalid_revision)
    application = FastAPI()
    app_module.install_source_revision_header(application)

    @application.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(application) as client:
        response = client.get("/probe")

    assert response.status_code == 200
    assert "X-EA-Source-Revision" not in response.headers


def test_manfred_image_build_passes_and_records_exact_source_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.build_manfred_memorial_image as builder

    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "b" * 40
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)

    def materialize_context(*, source_root: Path, commit: str, destination: Path) -> None:
        del source_root, commit
        dockerfile = destination / "ea" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    def record_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        commands.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(builder, "_materialize_tracked_context", materialize_context)
    monkeypatch.setattr(builder, "_run", record_run)
    monkeypatch.setattr(builder, "_ensure_dedicated_builder", lambda: False)
    monkeypatch.setattr(builder, "_prune_dedicated_builder_cache", lambda: None)
    listed_image_ids = iter((None, "sha256:image", "sha256:image"))
    monkeypatch.setattr(builder, "_listed_image_id", lambda _tag: next(listed_image_ids))
    monkeypatch.setattr(
        builder,
        "_image_inspection",
        lambda _tag, *, expected_commit: (
            "sha256:image",
            {"RootFS": {"Layers": ["sha256:layer"]}},
        ),
    )
    monkeypatch.setattr(builder, "_verify_image_filesystem", lambda _tag: None)

    receipt = builder.build_image(
        source_root=source_root,
        ref="HEAD",
        tag=f"ea-runtime:manfred-{commit}",
        receipt_path=tmp_path / "receipt.json",
    )

    build_command = next(
        command
        for command in commands
        if command[:3] == ["docker", "buildx", "build"]
    )
    build_arg_index = build_command.index("--build-arg")
    assert build_command[build_arg_index + 1] == f"EA_SOURCE_REVISION={commit}"
    assert receipt["schema"] == "ea.manfred_memorial_image_build.v2"
    assert receipt["runtime_source_revision"] == commit


def test_manfred_image_inspection_rejects_source_revision_environment_mismatch(monkeypatch) -> None:
    import scripts.build_manfred_memorial_image as builder

    expected_commit = "c" * 40
    inspection = [
        {
            "Id": "sha256:image",
            "Config": {
                "Labels": {"org.opencontainers.image.revision": expected_commit},
                "Env": [f"EA_SOURCE_REVISION={'d' * 40}"],
            },
        }
    ]
    monkeypatch.setattr(
        builder,
        "_run",
        lambda _argv: subprocess.CompletedProcess(
            _argv,
            0,
            stdout=json.dumps(inspection).encode("utf-8"),
            stderr=b"",
        ),
    )

    with pytest.raises(RuntimeError, match="manfred_image_source_revision_environment_mismatch"):
        builder._image_inspection("ea-runtime:manfred-test", expected_commit=expected_commit)


def _room_args() -> argparse.Namespace:
    return argparse.Namespace(
        base_url="https://example.test",
        slug="manfred",
        reviewer="Family reviewer",
        device_label="Lenovo ThinkPad X1 Carbon gen 11",
        speaker_label="Bose SoundLink Flex serial ending 1234",
        room_label="Vienna living room north wall",
        notes="Normal listening distance with the room otherwise quiet.",
        manual_attestation_id="family-room-review-2026-07-11",
        manual_attestation_signed_at="2026-07-11T10:00:00Z",
        manual_attestation_source="operator_room_review",
        require_public_origin=True,
        actual_device_checked=True,
        actual_speaker_checked=True,
        first_syllable_not_clipped=True,
        intelligibility_confirmed=True,
        answer_text_fallback_visible=True,
        no_internet_search_confirmed=True,
        normal_spoken_turn_confirmed=True,
        interruption_behavior_confirmed=True,
        retry_path_confirmed=True,
    )


def test_public_room_receipt_fails_closed_without_runtime_revision(monkeypatch) -> None:
    import scripts.materialize_memorial_room_audio_receipt as materializer

    monkeypatch.setattr(materializer, "_git_head", lambda: "e" * 40)
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
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

    receipt = materializer.build_receipt(_room_args())

    assert receipt["status"] == "fail"
    assert receipt["runtime_source_revision"] is None
    assert materializer.RUNTIME_SOURCE_REVISION_FAILURE_CODE in receipt["failed_codes"]
    assert receipt["gold_claim_allowed"] is False


def test_public_room_receipt_records_valid_runtime_revision(monkeypatch) -> None:
    import scripts.materialize_memorial_room_audio_receipt as materializer

    revision = "f" * 40
    monkeypatch.setattr(materializer, "_git_head", lambda: revision)
    monkeypatch.setattr(materializer, "_git_dirty", lambda: False)
    monkeypatch.setattr(materializer, "_source_tree_fingerprint", lambda: "fingerprint")
    monkeypatch.setattr(
        materializer,
        "resolve_source_worktree_fingerprint",
        lambda _root: "worktree-fingerprint",
    )
    monkeypatch.setattr(
        materializer,
        "_probe_runtime_source_revision",
        lambda **_: (revision, None),
    )

    receipt = materializer.build_receipt(_room_args())

    assert receipt["status"] == "pass"
    assert receipt["runtime_source_revision"] == revision
    assert receipt["gold_claim_allowed"] is True


def test_candidate_runtime_revision_probe_reads_image_bound_header(monkeypatch) -> None:
    import scripts.run_manfred_memorial_candidate as candidate

    revision = "1" * 40

    class _Response:
        status = 200
        headers = {"X-EA-Source-Revision": revision}

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(
        candidate.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(),
    )

    assert (
        candidate._candidate_runtime_source_revision("http://127.0.0.1:18090")
        == revision
    )
    assert candidate.RECEIPT_SCHEMA == "ea.manfred_memorial_candidate_runtime.v4"
