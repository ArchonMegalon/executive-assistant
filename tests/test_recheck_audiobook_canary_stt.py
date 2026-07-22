from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "recheck_audiobook_canary_stt.py"
SPEC = importlib.util.spec_from_file_location("recheck_audiobook_canary_stt", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
recheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recheck)


SOURCE_TEXT = "The Lantern\n\nAnna said, \u201cThe lantern is ready.\u201d"
TEST_COMMIT = "a" * 40
TEST_TREE = "b" * 40
RUNTIME_CONFIGURED_IMAGE = "ea-runtime:test"
RUNTIME_IMAGE_ID = "sha256:" + "f" * 64
RUNTIME_SOURCE_REVISION = "a" * 40


class FakeProvider:
    def __init__(
        self, *, response: dict[str, object], keys: tuple[str, ...] = ("secret-key",)
    ) -> None:
        self.response = response
        self.keys = keys
        self.upload_count = 0
        self.inference_count = 0

    def _pocket_onemin_api_keys(self) -> tuple[str, ...]:
        return self.keys

    def _onemin_asset_upload(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["content_type"] == "audio/wav"
        self.upload_count += 1
        return {"fileContent": {"path": "private/provider/path"}}

    def _onemin_speech_to_text(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["audio_path"] == "private/provider/path"
        self.inference_count += 1
        return self.response

    def _onemin_transcript_text(self, value: object) -> str:
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            return value[0]
        return ""


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    m4b = tmp_path / "canary.m4b"
    m4b.write_bytes(b"m4b-bytes")
    manifest = tmp_path / "fixture.json"
    text_sha256 = recheck._sha256_bytes(SOURCE_TEXT.encode("utf-8"))
    manifest.write_text(
        json.dumps(
            {
                "contract_name": "ea.audiobook_live_canary_fixture.v1",
                "language": "en",
                "language_tag": "en-US",
                "chapters": [
                    {
                        "canonical_expected_text": SOURCE_TEXT,
                        "canonical_expected_text_sha256": text_sha256,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return m4b, manifest


@pytest.fixture(autouse=True)
def _clean_source_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_git(*args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return TEST_COMMIT
        if args == ("rev-parse", "HEAD^{tree}"):
            return TEST_TREE
        if args == ("status", "--porcelain=v1", "--untracked-files=all"):
            return ""
        return ""

    monkeypatch.setattr(recheck, "_git_value", fake_git)
    monkeypatch.setattr(
        recheck,
        "_git_blob_bytes",
        lambda **_kwargs: recheck.RUNTIME_PROBE_PATH.read_bytes(),
    )
    monkeypatch.setattr(recheck, "FORBIDDEN_OUTPUT_ROOTS", ())


def _binding_args(m4b: Path, manifest: Path) -> dict[str, object]:
    return {
        "expected_artifact_sha256": recheck._sha256_file(m4b),
        "expected_manifest_sha256": recheck._sha256_file(manifest),
        "expected_code_commit": TEST_COMMIT,
        "paid_call_authorized": True,
    }


def _runtime_binding_args() -> dict[str, str]:
    return {
        "expected_runtime_configured_image": RUNTIME_CONFIGURED_IMAGE,
        "expected_runtime_image_id": RUNTIME_IMAGE_ID,
        "expected_runtime_source_revision": RUNTIME_SOURCE_REVISION,
    }


def _success_response(text: str = SOURCE_TEXT) -> dict[str, object]:
    return {
        "aiRecord": {
            "status": "SUCCESS",
            "teamUser": {"creditLimit": 100, "usedCredit": 7},
            "aiRecordDetail": {"resultObject": [text]},
        }
    }


def test_recheck_uses_exactly_one_upload_and_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m4b, manifest = _inputs(tmp_path)
    sample = b"RIFF" + b"sample" * 500
    monkeypatch.setattr(
        recheck,
        "_extract_sample",
        lambda *, source, output: output.write_bytes(sample),
    )
    provider = FakeProvider(response=_success_response())

    receipt = recheck.run_recheck(
        m4b_path=m4b,
        manifest_path=manifest,
        provider=provider,
        **_binding_args(m4b, manifest),
        generated_at="2026-07-19T20:00:00Z",
    )

    assert receipt["status"] == "review_required"
    assert receipt["machine_stt_status"] == "pass"
    assert receipt["machine_stt_gate_passed"] is True
    assert provider.upload_count == 1
    assert provider.inference_count == 1
    assert receipt["provider_usage"]["asset_upload_network_request_count"] == 1
    assert receipt["provider_usage"]["stt_inference_network_request_count"] == 1
    assert receipt["sample"]["persisted"] is False
    assert receipt["privacy"] == {
        "api_key_exposed": False,
        "raw_provider_ids_exposed": False,
        "raw_provider_response_persisted": False,
        "raw_transcript_persisted": False,
        "absolute_host_paths_exposed": False,
    }
    serialized = json.dumps(receipt, sort_keys=True)
    assert "secret-key" not in serialized
    assert "private/provider/path" not in serialized
    assert SOURCE_TEXT not in serialized
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize(
    "response",
    [
        {"aiRecord": {"aiRecordDetail": {"resultObject": [SOURCE_TEXT]}}},
        {
            "aiRecord": {
                "status": "PROCESSING",
                "aiRecordDetail": {"resultObject": [SOURCE_TEXT]},
            }
        },
        {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"resultObject": [SOURCE_TEXT, "metadata"]},
            }
        },
        {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {"resultObject": SOURCE_TEXT},
            }
        },
        {
            "aiRecord": {
                "status": "SUCCESS",
                "aiRecordDetail": {
                    "responseObject": [SOURCE_TEXT],
                    "resultObject": ["conflicting transcript"],
                },
            }
        },
    ],
)
def test_recheck_fails_closed_on_non_authoritative_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
) -> None:
    m4b, manifest = _inputs(tmp_path)
    monkeypatch.setattr(
        recheck,
        "_extract_sample",
        lambda *, source, output: output.write_bytes(b"sample" * 500),
    )
    provider = FakeProvider(response=response)

    receipt = recheck.run_recheck(
        m4b_path=m4b,
        manifest_path=manifest,
        provider=provider,
        **_binding_args(m4b, manifest),
    )

    assert receipt["status"] == "review_required"
    assert receipt["machine_stt_gate_passed"] is False
    assert provider.upload_count == 1
    assert provider.inference_count == 1
    assert receipt["transcript_sha256"] == ""


def test_recheck_without_key_performs_no_network(
    tmp_path: Path,
) -> None:
    m4b, manifest = _inputs(tmp_path)
    provider = FakeProvider(response=_success_response(), keys=())

    receipt = recheck.run_recheck(
        m4b_path=m4b,
        manifest_path=manifest,
        provider=provider,
        **_binding_args(m4b, manifest),
    )

    assert receipt["status"] == "review_required"
    assert provider.upload_count == 0
    assert provider.inference_count == 0
    assert receipt["provider_usage"]["asset_upload_network_request_count"] == 0
    assert receipt["provider_usage"]["stt_inference_network_request_count"] == 0


def test_bundle_is_private_portable_and_hash_bound(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    output.mkdir(mode=0o700)
    receipt = {
        "contract_name": recheck.CONTRACT_NAME,
        "status": "review_required",
        "machine_stt_gate_passed": True,
        "code_commit": "a" * 40,
        "artifact_sha256": "b" * 64,
    }

    pointer = recheck.write_bundle(output_dir=output, receipt=receipt)

    assert pointer["status"] == "review_required"
    assert pointer["machine_stt_gate_passed"] is True
    assert sorted(path.name for path in output.iterdir()) == [
        "INVENTORY.json",
        "INVENTORY.sha256",
        "POINTER.json",
        "validation.json",
    ]
    for path in output.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    serialized = "\n".join(path.read_text() for path in output.iterdir())
    assert str(tmp_path) not in serialized


def test_bundle_rejects_non_private_or_nonempty_directory(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="output_dir_not_private"):
        recheck.write_bundle(output_dir=public, receipt={"status": "review_required"})

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "existing").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="output_dir_not_empty"):
        recheck.write_bundle(output_dir=private, receipt={"status": "review_required"})


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    m4b, manifest = _inputs(tmp_path)
    link = tmp_path / "linked.m4b"
    link.symlink_to(m4b)
    with pytest.raises((OSError, ValueError)):
        recheck.run_recheck(
            m4b_path=link,
            manifest_path=manifest,
            provider=FakeProvider(response=_success_response()),
            **_binding_args(link, manifest),
        )


def test_missing_paid_call_authorization_blocks_before_network(tmp_path: Path) -> None:
    m4b, manifest = _inputs(tmp_path)
    provider = FakeProvider(response=_success_response())
    bindings = _binding_args(m4b, manifest)
    bindings["paid_call_authorized"] = False

    with pytest.raises(ValueError, match="one_paid_stt_call_not_authorized"):
        recheck.run_recheck(
            m4b_path=m4b,
            manifest_path=manifest,
            provider=provider,
            **bindings,
        )

    assert provider.upload_count == 0
    assert provider.inference_count == 0


def test_digest_or_source_mismatch_blocks_before_network(tmp_path: Path) -> None:
    m4b, manifest = _inputs(tmp_path)
    provider = FakeProvider(response=_success_response())

    with pytest.raises(ValueError, match="artifact_sha256_mismatch"):
        recheck.run_recheck(
            m4b_path=m4b,
            manifest_path=manifest,
            provider=provider,
            expected_artifact_sha256="0" * 64,
            expected_manifest_sha256=recheck._sha256_file(manifest),
            expected_code_commit=TEST_COMMIT,
            paid_call_authorized=True,
        )

    assert provider.upload_count == 0
    assert provider.inference_count == 0


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "contract_name",
            "/private/host/secret-contract",
            "fixture_manifest_contract_invalid",
        ),
        (
            "language",
            "/home/tibor/secret-language",
            "fixture_manifest_language_invalid",
        ),
        ("language_tag", "../../secret", "fixture_manifest_language_invalid"),
    ],
)
def test_manifest_contract_and_language_are_exact_before_network(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
) -> None:
    m4b, manifest = _inputs(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload[field] = value
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    provider = FakeProvider(response=_success_response())

    with pytest.raises(ValueError, match=reason):
        recheck.run_recheck(
            m4b_path=m4b,
            manifest_path=manifest,
            provider=provider,
            **_binding_args(m4b, manifest),
        )

    assert provider.upload_count == 0
    assert provider.inference_count == 0


def test_source_drift_after_paid_boundary_invalidates_machine_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m4b, manifest = _inputs(tmp_path)
    monkeypatch.setattr(
        recheck,
        "_extract_sample",
        lambda *, source, output: output.write_bytes(b"sample" * 500),
    )
    status_calls = 0

    def drifting_git(*args: str) -> str:
        nonlocal status_calls
        if args == ("rev-parse", "HEAD"):
            return TEST_COMMIT
        if args == ("rev-parse", "HEAD^{tree}"):
            return TEST_TREE
        if args == ("status", "--porcelain=v1", "--untracked-files=all"):
            status_calls += 1
            return "" if status_calls == 1 else "?? sitecustomize.py"
        return ""

    monkeypatch.setattr(recheck, "_git_value", drifting_git)
    provider = FakeProvider(response=_success_response())

    receipt = recheck.run_recheck(
        m4b_path=m4b,
        manifest_path=manifest,
        provider=provider,
        **_binding_args(m4b, manifest),
    )

    assert provider.upload_count == 1
    assert provider.inference_count == 1
    assert receipt["machine_stt_gate_passed"] is False
    assert receipt["machine_stt_status"] == "fail"
    assert receipt["source_state_stable_across_paid_boundary"] is False
    assert receipt["transcription_error_class"] == "source_state_changed_during_recheck"


def test_runtime_container_probe_can_close_only_machine_subgate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m4b, manifest = _inputs(tmp_path)
    monkeypatch.setattr(
        recheck,
        "_extract_sample",
        lambda *, source, output: output.write_bytes(b"sample" * 500),
    )
    observed: dict[str, object] = {}
    blob_requests: list[tuple[str, str, int]] = []

    def fake_git_blob_bytes(
        *, commit: str, relative_path: str, max_bytes: int
    ) -> bytes:
        blob_requests.append((commit, relative_path, max_bytes))
        return recheck.RUNTIME_PROBE_PATH.read_bytes()

    monkeypatch.setattr(recheck, "_git_blob_bytes", fake_git_blob_bytes)

    def fake_runtime_probe(
        **kwargs: object,
    ) -> tuple[dict[str, object], str, dict[str, object]]:
        observed.update(kwargs)
        return (
            {
                "contract_name": recheck.RUNTIME_PROBE_CONTRACT_NAME,
                "status": "pass",
                "error_code": "",
                "asset_upload_network_request_count": 1,
                "stt_inference_network_request_count": 1,
                "provider_usage_accounting_complete": True,
                "transcript_sha256": "c" * 64,
                "transcript_token_count": 8,
                "book_token_overlap": 1.0,
                "book_unique_token_overlap": 1.0,
                "credit_snapshot": {"aiRecord.teamUser.usedCredit": 12},
                "raw_provider_response_persisted": False,
                "raw_transcript_persisted": False,
                "api_key_exposed": False,
            },
            "d" * 64,
            {
                "container_id": "e" * 64,
                "image_id": RUNTIME_IMAGE_ID,
                "configured_image": RUNTIME_CONFIGURED_IMAGE,
                "source_revision": RUNTIME_SOURCE_REVISION,
                "running_before_probe": True,
            },
        )

    monkeypatch.setattr(recheck, "_run_runtime_probe", fake_runtime_probe)

    receipt = recheck.run_recheck(
        m4b_path=m4b,
        manifest_path=manifest,
        provider=None,
        runtime_container="ea-api",
        **_runtime_binding_args(),
        **_binding_args(m4b, manifest),
    )

    assert receipt["status"] == "review_required"
    assert receipt["machine_stt_gate_passed"] is True
    assert receipt["credential_execution_scope"] == "runtime_container"
    assert receipt["runtime_probe_sha256"] == "d" * 64
    assert receipt["runtime_container_identity"]["container_id"] == "e" * 64
    assert receipt["side_effects"]["runtime_container_process_executed"] is True
    assert receipt["provider_usage"]["accounting_complete"] is True
    assert observed["expected_probe_sha256"] == recheck._sha256_file(
        recheck.RUNTIME_PROBE_PATH
    )
    assert observed["expected_configured_image"] == RUNTIME_CONFIGURED_IMAGE
    assert observed["expected_image_id"] == RUNTIME_IMAGE_ID
    assert observed["expected_source_revision"] == RUNTIME_SOURCE_REVISION
    assert blob_requests == [
        (
            TEST_COMMIT,
            "scripts/audiobook_stt_runtime_probe.py",
            recheck.MAX_RUNTIME_PROBE_BYTES,
        )
    ]


def test_runtime_probe_transport_is_fixed_and_validates_exact_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe = {
        "contract_name": recheck.RUNTIME_PROBE_CONTRACT_NAME,
        "status": "pass",
        "error_code": "",
        "asset_upload_network_request_count": 1,
        "stt_inference_network_request_count": 1,
        "provider_usage_accounting_complete": True,
        "transcript_sha256": "c" * 64,
        "transcript_token_count": 8,
        "book_token_overlap": 1.0,
        "book_unique_token_overlap": 1.0,
        "credit_snapshot": {},
        "raw_provider_response_persisted": False,
        "raw_transcript_persisted": False,
        "api_key_exposed": False,
    }
    observed: dict[str, object] = {}

    def fake_run(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if args[1] == "inspect":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    ("e" * 64)
                    + "\nsha256:"
                    + ("f" * 64)
                    + "\nea-runtime:test\n"
                    + ("a" * 40)
                    + "\ntrue\n"
                ).encode("utf-8"),
                stderr=b"",
            )
        observed["args"] = args
        observed["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(safe).encode("utf-8"),
            stderr=b"ignored-secret-stderr",
        )

    monkeypatch.setattr(recheck.subprocess, "run", fake_run)
    result, digest, identity = recheck._run_runtime_probe(
        sample_bytes=b"sample-bytes",
        source_tokens=["the", "lantern"],
        language="en",
        container="ea-api",
        expected_probe_sha256=recheck._sha256_file(recheck.RUNTIME_PROBE_PATH),
        expected_configured_image=RUNTIME_CONFIGURED_IMAGE,
        expected_image_id=RUNTIME_IMAGE_ID,
        expected_source_revision=RUNTIME_SOURCE_REVISION,
    )

    assert result["status"] == "pass"
    assert recheck.DIGEST_HEX_RE.fullmatch(digest)
    assert identity["container_id"] == "e" * 64
    assert observed["input"] == b"sample-bytes"
    args = observed["args"]
    assert args[:6] == ["docker", "exec", "-i", "-w", "/app", "-e"]
    assert args[-4:-1] == ["python", "-B", "-c"]
    assert "ignored-secret-stderr" not in json.dumps(result)


def test_runtime_probe_transport_rejects_false_pass_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    false_pass = {
        "contract_name": recheck.RUNTIME_PROBE_CONTRACT_NAME,
        "status": "pass",
        "error_code": "",
        "asset_upload_network_request_count": 0,
        "stt_inference_network_request_count": 0,
        "provider_usage_accounting_complete": True,
        "transcript_sha256": "c" * 64,
        "transcript_token_count": 8,
        "book_token_overlap": 1.0,
        "book_unique_token_overlap": 1.0,
        "credit_snapshot": {},
        "raw_provider_response_persisted": False,
        "raw_transcript_persisted": False,
        "api_key_exposed": False,
    }

    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if args[1] == "inspect":
            stdout = (
                ("e" * 64)
                + "\nsha256:"
                + ("f" * 64)
                + "\nea-runtime:test\n"
                + ("a" * 40)
                + "\ntrue\n"
            ).encode("utf-8")
        else:
            stdout = json.dumps(false_pass).encode("utf-8")
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(recheck.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="runtime_probe_pass_contract_invalid"):
        recheck._run_runtime_probe(
            sample_bytes=b"sample-bytes",
            source_tokens=["the", "lantern"],
            language="en",
            container="ea-api",
            expected_probe_sha256=recheck._sha256_file(recheck.RUNTIME_PROBE_PATH),
            expected_configured_image=RUNTIME_CONFIGURED_IMAGE,
            expected_image_id=RUNTIME_IMAGE_ID,
            expected_source_revision=RUNTIME_SOURCE_REVISION,
        )


def test_runtime_probe_rejects_transient_source_swap_even_when_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_path = tmp_path / "audiobook_stt_runtime_probe.py"
    authorized = b"print('authorized')\n"
    swapped = b"print('transient unauthorized source')\n"
    probe_path.write_bytes(authorized)
    probe_path.chmod(0o600)
    monkeypatch.setattr(recheck, "RUNTIME_PROBE_PATH", probe_path)
    original_reader = recheck._read_regular_file

    def swap_for_read(path: Path, *, max_bytes: int, reason: str) -> bytes:
        assert path == probe_path
        probe_path.write_bytes(swapped)
        try:
            return original_reader(path, max_bytes=max_bytes, reason=reason)
        finally:
            probe_path.write_bytes(authorized)

    monkeypatch.setattr(recheck, "_read_regular_file", swap_for_read)
    subprocess_calls: list[list[str]] = []
    monkeypatch.setattr(
        recheck.subprocess,
        "run",
        lambda args, **_kwargs: subprocess_calls.append(list(args)),
    )

    with pytest.raises(ValueError, match="runtime_probe_sha256_mismatch"):
        recheck._run_runtime_probe(
            sample_bytes=b"sample-bytes",
            source_tokens=["the", "lantern"],
            language="en",
            container="ea-api",
            expected_probe_sha256=recheck._sha256_bytes(authorized),
            expected_configured_image=RUNTIME_CONFIGURED_IMAGE,
            expected_image_id=RUNTIME_IMAGE_ID,
            expected_source_revision=RUNTIME_SOURCE_REVISION,
        )

    assert probe_path.read_bytes() == authorized
    assert subprocess_calls == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "expected_runtime_configured_image",
            "",
            "expected_runtime_configured_image_invalid",
        ),
        (
            "expected_runtime_configured_image",
            "/tmp/ea-runtime:test",
            "expected_runtime_configured_image_invalid",
        ),
        (
            "expected_runtime_configured_image",
            "../ea-runtime:test",
            "expected_runtime_configured_image_invalid",
        ),
        (
            "expected_runtime_configured_image",
            "file:///tmp/ea-runtime",
            "expected_runtime_configured_image_invalid",
        ),
        (
            "expected_runtime_image_id",
            "/var/lib/docker/image",
            "expected_runtime_image_id_invalid",
        ),
        (
            "expected_runtime_source_revision",
            "../../source",
            "expected_runtime_source_revision_invalid",
        ),
    ],
)
def test_runtime_expectations_reject_missing_or_path_like_values_before_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
    reason: str,
) -> None:
    m4b, manifest = _inputs(tmp_path)
    monkeypatch.setattr(
        recheck,
        "_extract_sample",
        lambda **_kwargs: pytest.fail("sample extraction must not start"),
    )
    runtime_bindings = _runtime_binding_args()
    runtime_bindings[field] = value

    with pytest.raises(ValueError, match=reason):
        recheck.run_recheck(
            m4b_path=m4b,
            manifest_path=manifest,
            provider=None,
            runtime_container="ea-api",
            **runtime_bindings,
            **_binding_args(m4b, manifest),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_configured_image", "ea-runtime:other"),
        ("expected_image_id", "sha256:" + "d" * 64),
        ("expected_source_revision", "b" * 40),
    ],
)
def test_runtime_probe_rejects_exact_identity_mismatch_before_exec(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(args))
        assert args[1] == "inspect"
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                ("e" * 64)
                + "\n"
                + RUNTIME_IMAGE_ID
                + "\n"
                + RUNTIME_CONFIGURED_IMAGE
                + "\n"
                + RUNTIME_SOURCE_REVISION
                + "\ntrue\n"
            ).encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(recheck.subprocess, "run", fake_run)
    expectations = {
        "expected_configured_image": RUNTIME_CONFIGURED_IMAGE,
        "expected_image_id": RUNTIME_IMAGE_ID,
        "expected_source_revision": RUNTIME_SOURCE_REVISION,
    }
    expectations[field] = value

    with pytest.raises(RuntimeError, match="runtime_probe_container_identity_mismatch"):
        recheck._run_runtime_probe(
            sample_bytes=b"sample-bytes",
            source_tokens=["the", "lantern"],
            language="en",
            container="ea-api",
            expected_probe_sha256=recheck._sha256_file(recheck.RUNTIME_PROBE_PATH),
            **expectations,
        )

    assert len(calls) == 1
    assert calls[0][:2] == ["docker", "inspect"]


def test_inventory_sha256_matches_exact_bytes(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    output.mkdir(mode=0o700)
    recheck.write_bundle(output_dir=output, receipt={"status": "review_required"})
    expected = recheck._sha256_file(output / "INVENTORY.json")
    assert (output / "INVENTORY.sha256").read_text().strip() == (
        f"{expected}  INVENTORY.json"
    )
    assert os.stat(output / "POINTER.json").st_nlink == 1
