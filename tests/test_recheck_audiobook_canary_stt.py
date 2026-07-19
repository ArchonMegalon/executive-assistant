from __future__ import annotations

import importlib.util
import json
import os
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


class FakeProvider:
    def __init__(self, *, response: dict[str, object], keys: tuple[str, ...] = ("secret-key",)) -> None:
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
    monkeypatch.setattr(recheck, "FORBIDDEN_OUTPUT_ROOTS", ())


def _binding_args(m4b: Path, manifest: Path) -> dict[str, object]:
    return {
        "expected_artifact_sha256": recheck._sha256_file(m4b),
        "expected_manifest_sha256": recheck._sha256_file(manifest),
        "expected_code_commit": TEST_COMMIT,
        "paid_call_authorized": True,
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
        ("contract_name", "/private/host/secret-contract", "fixture_manifest_contract_invalid"),
        ("language", "/home/tibor/secret-language", "fixture_manifest_language_invalid"),
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


def test_inventory_sha256_matches_exact_bytes(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    output.mkdir(mode=0o700)
    recheck.write_bundle(output_dir=output, receipt={"status": "review_required"})
    expected = recheck._sha256_file(output / "INVENTORY.json")
    assert (output / "INVENTORY.sha256").read_text().strip() == (
        f"{expected}  INVENTORY.json"
    )
    assert os.stat(output / "POINTER.json").st_nlink == 1
