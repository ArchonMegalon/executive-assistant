from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audiobook_stt_runtime_probe.py"
SPEC = importlib.util.spec_from_file_location("audiobook_stt_runtime_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

SOURCE_TOKENS = ["the", "lantern", "anna", "said", "is", "ready", "then", "begin"]
TRANSCRIPT = "The lantern is ready then Anna said begin"


class FakeProvider:
    def __init__(self, *, keys: tuple[str, ...] = ("runtime-secret",)) -> None:
        self.keys = keys
        self.upload_count = 0

    def _pocket_onemin_api_keys(self) -> tuple[str, ...]:
        return self.keys

    def _onemin_asset_upload(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["api_key"] == "runtime-secret"
        assert kwargs["payload"] == b"wav-bytes"
        self.upload_count += 1
        return {"fileContent": {"path": "private/runtime/asset"}}


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.payload[:limit] if limit >= 0 else self.payload


def _provider_response(*, transcript: str = TRANSCRIPT) -> dict[str, object]:
    return {
        "aiRecord": {
            "status": "SUCCESS",
            "teamUser": {"creditLimit": 1000, "usedCredit": 10},
            "aiRecordDetail": {"resultObject": [transcript]},
        }
    }


def test_runtime_probe_passes_without_exposing_transcript_or_key() -> None:
    provider = FakeProvider()
    inference_count = 0

    def urlopen(request: object, timeout: int) -> FakeResponse:
        nonlocal inference_count
        inference_count += 1
        assert timeout == 180
        assert getattr(request, "full_url", "") == probe.FEATURE_URL
        return FakeResponse(_provider_response())

    result = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
        urlopen=urlopen,
    )

    assert result["status"] == "pass"
    assert result["asset_upload_network_request_count"] == 1
    assert result["stt_inference_network_request_count"] == 1
    assert provider.upload_count == 1
    assert inference_count == 1
    assert result["transcript_token_count"] == 8
    assert result["book_token_overlap"] == 1.0
    serialized = json.dumps(result, sort_keys=True)
    assert "runtime-secret" not in serialized
    assert "private/runtime/asset" not in serialized
    assert TRANSCRIPT not in serialized


def test_runtime_probe_rejects_ambiguous_response_after_one_call() -> None:
    provider = FakeProvider()
    response = _provider_response()
    response["aiRecord"]["aiRecordDetail"]["responseObject"] = [TRANSCRIPT]

    result = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
        urlopen=lambda *_args, **_kwargs: FakeResponse(response),
    )

    assert result["status"] == "fail"
    assert result["error_code"] == "transcript_not_authoritative"
    assert result["asset_upload_network_request_count"] == 1
    assert result["stt_inference_network_request_count"] == 1
    assert result["transcript_sha256"] == ""


def test_runtime_probe_missing_key_performs_no_network() -> None:
    provider = FakeProvider(keys=())
    inference_count = 0

    def urlopen(*_args: object, **_kwargs: object) -> FakeResponse:
        nonlocal inference_count
        inference_count += 1
        return FakeResponse(_provider_response())

    result = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
        urlopen=urlopen,
    )

    assert result["error_code"] == "api_key_unavailable"
    assert result["asset_upload_network_request_count"] == 0
    assert result["stt_inference_network_request_count"] == 0
    assert provider.upload_count == 0
    assert inference_count == 0


def test_runtime_probe_inference_failure_has_exact_attempt_counts() -> None:
    provider = FakeProvider()

    def failing_urlopen(*_args: object, **_kwargs: object) -> FakeResponse:
        raise OSError("secret-provider-detail")

    result = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
        urlopen=failing_urlopen,
    )

    assert result["status"] == "fail"
    assert result["error_code"] == "stt_inference_OSError"
    assert result["asset_upload_network_request_count"] == 1
    assert result["stt_inference_network_request_count"] == 1
    assert "secret-provider-detail" not in json.dumps(result)


def test_runtime_probe_rejects_duplicate_provider_json_keys() -> None:
    provider = FakeProvider()
    raw = FakeResponse({})
    raw.payload = (
        b'{"aiRecord":{"status":"SUCCESS","status":"FAILURE",'
        b'"aiRecordDetail":{"resultObject":["text"]}}}'
    )

    result = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
        urlopen=lambda *_args, **_kwargs: raw,
    )

    assert result["status"] == "fail"
    assert result["error_code"] == "stt_inference_ValueError"
    assert result["asset_upload_network_request_count"] == 1
    assert result["stt_inference_network_request_count"] == 1


def test_runtime_probe_rejects_nonfinite_provider_json() -> None:
    provider = FakeProvider()
    raw = FakeResponse({})
    raw.payload = b'{"aiRecord":{"status":"SUCCESS","score":NaN}}'

    result = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
        urlopen=lambda *_args, **_kwargs: raw,
    )

    assert result["status"] == "fail"
    assert result["error_code"] == "stt_inference_ValueError"
    assert result["asset_upload_network_request_count"] == 1
    assert result["stt_inference_network_request_count"] == 1


@pytest.mark.parametrize(
    "nested_result",
    [
        '{"text":"The lantern is ready","text":"forged"}',
        '{"text":"The lantern is ready","confidence":NaN}',
        '{"text":"The lantern is ready","confidence":Infinity}',
    ],
)
def test_runtime_probe_rejects_ambiguous_nested_stringified_result_object(
    nested_result: str,
) -> None:
    response = {
        "aiRecord": {
            "status": "SUCCESS",
            "aiRecordDetail": {"resultObject": [nested_result]},
        }
    }

    assert probe._strict_transcript(response) == ""


def test_runtime_probe_rejects_unbounded_or_wrong_language_before_network() -> None:
    provider = FakeProvider()
    too_large = probe.run_probe(
        payload=b"x" * (probe.MAX_AUDIO_BYTES + 1),
        source_tokens=SOURCE_TOKENS,
        language="en",
        provider=provider,
    )
    wrong_language = probe.run_probe(
        payload=b"wav-bytes",
        source_tokens=SOURCE_TOKENS,
        language="/private/secret",
        provider=provider,
    )

    assert too_large["error_code"] == "audio_payload_invalid"
    assert wrong_language["error_code"] == "language_invalid"
    assert provider.upload_count == 0


def test_runtime_output_contract_is_exact() -> None:
    assert set(probe._base_result()) == probe.EXACT_OUTPUT_KEYS
