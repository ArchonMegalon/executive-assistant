#!/usr/bin/env python3
"""Credential-bound 1min STT probe executed through ``docker exec``.

The WAV payload arrives on stdin. Provider credentials never leave the runtime
process. Only hashes, counts, overlap metrics, and bounded credit counters are
written to stdout; raw provider responses and transcript text are discarded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from typing import Any, Callable, Protocol


CONTRACT_NAME = "ea.audiobook_stt_runtime_probe.v1"
FEATURE_URL = "https://api.1min.ai/api/features"
MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
TOKEN_RE = re.compile(r"[a-z0-9\u00c0-\u024f]{2,}")
EXACT_OUTPUT_KEYS = frozenset(
    {
        "contract_name",
        "status",
        "error_code",
        "asset_upload_network_request_count",
        "stt_inference_network_request_count",
        "provider_usage_accounting_complete",
        "transcript_sha256",
        "transcript_token_count",
        "book_token_overlap",
        "book_unique_token_overlap",
        "credit_snapshot",
        "raw_provider_response_persisted",
        "raw_transcript_persisted",
        "api_key_exposed",
    }
)


class ProviderModule(Protocol):
    def _pocket_onemin_api_keys(self) -> tuple[str, ...]: ...

    def _onemin_asset_upload(
        self,
        *,
        api_key: str,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> dict[str, object]: ...


def _strict_json_loads(value: str | bytes) -> object:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = item
        return result

    return json.loads(
        value,
        object_pairs_hook=unique_object,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("non_finite_json")
        ),
    )


def _tokens(value: str) -> list[str]:
    return TOKEN_RE.findall(value.lower())


def _safe_used_credit(response: dict[str, object]) -> dict[str, int]:
    record = response.get("aiRecord")
    team_user = record.get("teamUser") if isinstance(record, dict) else None
    if not isinstance(team_user, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("creditLimit", "usedCredit"):
        value = team_user.get(key)
        if type(value) is int and value >= 0:
            result[f"aiRecord.teamUser.{key}"] = value
    return result


def _strict_transcript(response: dict[str, object]) -> str:
    record = response.get("aiRecord")
    if not isinstance(record, dict):
        return ""
    if str(record.get("status") or "").strip().upper() != "SUCCESS":
        return ""
    detail = record.get("aiRecordDetail")
    if not isinstance(detail, dict):
        return ""
    if detail.get("responseObject") not in (None, "", [], {}):
        return ""
    result = detail.get("resultObject")
    if not isinstance(result, list) or len(result) != 1:
        return ""
    item = result[0]
    if isinstance(item, str):
        value = item.strip()
        if not value:
            return ""
        if value.startswith(("{", "[")):
            try:
                item = _strict_json_loads(value)
            except (json.JSONDecodeError, ValueError):
                return ""
        else:
            return value
    if not isinstance(item, dict):
        return ""
    values = [
        str(item.get(key) or "").strip()
        for key in ("text", "transcript")
        if str(item.get(key) or "").strip()
    ]
    if len(values) != 1:
        return ""
    return values[0]


def _speech_to_text(
    *,
    api_key: str,
    audio_path: str,
    language: str,
    urlopen: Callable[..., Any],
) -> dict[str, object]:
    body = {
        "type": "SPEECH_TO_TEXT",
        "model": "whisper-1",
        "promptObject": {
            "audioUrl": audio_path,
            "response_format": "text",
            "language": language,
        },
    }
    request = urllib.request.Request(
        FEATURE_URL,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "EA-Audiobook-STT-Runtime-Probe/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("provider_response_too_large")
    parsed = _strict_json_loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("provider_response_not_object")
    return parsed


def _base_result() -> dict[str, object]:
    return {
        "contract_name": CONTRACT_NAME,
        "status": "fail",
        "error_code": "",
        "asset_upload_network_request_count": 0,
        "stt_inference_network_request_count": 0,
        "provider_usage_accounting_complete": True,
        "transcript_sha256": "",
        "transcript_token_count": 0,
        "book_token_overlap": 0.0,
        "book_unique_token_overlap": 0.0,
        "credit_snapshot": {},
        "raw_provider_response_persisted": False,
        "raw_transcript_persisted": False,
        "api_key_exposed": False,
    }


def run_probe(
    *,
    payload: bytes,
    source_tokens: list[str],
    language: str,
    provider: ProviderModule,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, object]:
    result = _base_result()
    if not payload or len(payload) > MAX_AUDIO_BYTES:
        result["error_code"] = "audio_payload_invalid"
        return result
    if language != "en":
        result["error_code"] = "language_invalid"
        return result
    normalized_source = [str(token).strip().lower() for token in source_tokens]
    if (
        not normalized_source
        or len(normalized_source) > 1000
        or any(TOKEN_RE.fullmatch(token) is None for token in normalized_source)
    ):
        result["error_code"] = "source_tokens_invalid"
        return result
    source_set = set(normalized_source)
    phase = "credential_resolution"
    try:
        keys = provider._pocket_onemin_api_keys()
        if not keys or not str(keys[0] or "").strip():
            result["error_code"] = "api_key_unavailable"
            return result
        api_key = str(keys[0]).strip()
        phase = "asset_upload"
        result["asset_upload_network_request_count"] = 1
        uploaded = provider._onemin_asset_upload(
            api_key=api_key,
            filename="audiobook-canary-sample.wav",
            content_type="audio/wav",
            payload=payload,
        )
        file_content = uploaded.get("fileContent")
        asset = uploaded.get("asset")
        audio_path = ""
        if isinstance(file_content, dict):
            audio_path = str(file_content.get("path") or "").strip()
        if not audio_path and isinstance(asset, dict):
            audio_path = str(asset.get("key") or "").strip()
        if not audio_path:
            result["error_code"] = "asset_path_missing"
            return result
        phase = "stt_inference"
        result["stt_inference_network_request_count"] = 1
        response = _speech_to_text(
            api_key=api_key,
            audio_path=audio_path,
            language=language,
            urlopen=urlopen,
        )
        result["credit_snapshot"] = _safe_used_credit(response)
        transcript = _strict_transcript(response)
        if not transcript:
            result["error_code"] = "transcript_not_authoritative"
            return result
        transcript_tokens = _tokens(transcript)
        transcript_unique = set(transcript_tokens)
        token_overlap = (
            sum(1 for token in transcript_tokens if token in source_set)
            / float(len(transcript_tokens))
            if transcript_tokens
            else 0.0
        )
        unique_overlap = (
            len(transcript_unique & source_set) / float(len(transcript_unique))
            if transcript_unique
            else 0.0
        )
        passed = (
            len(transcript_tokens) >= 8
            and token_overlap >= 0.55
            and unique_overlap >= 0.55
        )
        result.update(
            {
                "status": "pass" if passed else "fail",
                "error_code": "" if passed else "transcript_quality_threshold_failed",
                "transcript_sha256": hashlib.sha256(
                    transcript.encode("utf-8")
                ).hexdigest(),
                "transcript_token_count": len(transcript_tokens),
                "book_token_overlap": round(token_overlap, 4),
                "book_unique_token_overlap": round(unique_overlap, 4),
            }
        )
    except Exception as exc:
        result["error_code"] = f"{phase}_{type(exc).__name__}"
    return result


def _source_tokens_from_environment() -> list[str]:
    raw = str(os.environ.get("EA_STT_SOURCE_TOKENS_JSON") or "").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        return []
    return list(parsed)


def main() -> int:
    try:
        payload = sys.stdin.buffer.read(MAX_AUDIO_BYTES + 1)
        from app.product import service as provider

        result = run_probe(
            payload=payload,
            source_tokens=_source_tokens_from_environment(),
            language=str(os.environ.get("EA_STT_LANGUAGE") or "").strip(),
            provider=provider,
        )
    except Exception as exc:
        result = _base_result()
        result["provider_usage_accounting_complete"] = False
        result["error_code"] = f"probe_bootstrap_{type(exc).__name__}"
    if set(result) != EXACT_OUTPUT_KEYS:
        result = _base_result()
        result["provider_usage_accounting_complete"] = False
        result["error_code"] = "probe_output_contract_invalid"
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
