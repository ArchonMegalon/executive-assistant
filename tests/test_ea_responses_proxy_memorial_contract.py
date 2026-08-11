from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.responses import JSONResponse

from app.api.dependencies import RequestContext
from app.api.routes import responses
from app.services.responses_upstream import UpstreamResult
from scripts import ea_responses_proxy as proxy


ROOT = Path(__file__).resolve().parents[1]
MEMORIAL_TOKEN = "m" * 48
OPERATOR_TOKEN = "o" * 48


def _memorial_headers(**overrides: str) -> dict[str, str]:
    headers = {
        "X-EA-API-Token": MEMORIAL_TOKEN,
        "X-EA-Principal-ID": "memorial-service",
        "X-EA-Codex-Profile": "groundwork",
        "X-EA-Retention": "none",
        "Content-Type": "application/json",
    }
    headers.update(overrides)
    return headers


def _memorial_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": "ea-onemin-coder",
        "input": "Describe a verified memory without inventing details.",
        "max_output_tokens": 700,
        "store": False,
    }
    payload.update(overrides)
    return payload


def test_memorial_token_has_a_fixed_least_privilege_identity() -> None:
    result, error = proxy._authenticate_proxy_client(
        _memorial_headers(),
        operator_token=OPERATOR_TOKEN,
        no_retention_token=MEMORIAL_TOKEN,
        no_retention_principal_id="memorial-service",
        default_principal_id="operator-default",
    )

    assert error == ""
    assert result is not None
    assert result.scope == "no_retention_client"
    assert result.request_context == RequestContext(
        principal_id="memorial-service",
        authenticated=True,
        auth_source="no_retention_client_token",
    )


def test_memorial_token_file_must_be_private(tmp_path: Path) -> None:
    token_file = tmp_path / "memorial-token"
    token_file.write_text(f"{MEMORIAL_TOKEN}\n", encoding="utf-8")
    token_file.chmod(0o640)
    assert proxy._read_client_token_file(str(token_file)) == MEMORIAL_TOKEN

    token_file.chmod(0o644)
    with pytest.raises(RuntimeError, match="accessible by others"):
        proxy._read_client_token_file(str(token_file))


def test_memorial_token_rejects_scope_escalation() -> None:
    for headers in (
        _memorial_headers(**{"X-EA-Principal-ID": "someone-else"}),
        _memorial_headers(**{"X-EA-Codex-Profile": "core"}),
        _memorial_headers(**{"X-EA-Retention": "default"}),
        _memorial_headers(**{"X-EA-Onemin-Account": "preferred-account"}),
    ):
        result, error = proxy._authenticate_proxy_client(
            headers,
            operator_token=OPERATOR_TOKEN,
            no_retention_token=MEMORIAL_TOKEN,
            no_retention_principal_id="memorial-service",
            default_principal_id="operator-default",
        )

        assert result is None
        assert error == "no_retention_scope_invalid"


def test_memorial_payload_is_bounded_and_no_retention() -> None:
    assert proxy._no_retention_payload_error(_memorial_payload()) == ""
    assert (
        proxy._no_retention_payload_error(_memorial_payload(store=True))
        == "no_retention_policy_invalid"
    )
    assert (
        proxy._no_retention_payload_error(_memorial_payload(model="ea-coder-hard"))
        == "no_retention_model_invalid"
    )
    assert (
        proxy._no_retention_payload_error(_memorial_payload(stream=True))
        == "no_retention_payload_fields_invalid"
    )
    assert (
        proxy._no_retention_payload_error(_memorial_payload(max_output_tokens=True))
        == "no_retention_output_limit_invalid"
    )


def test_memorial_response_fails_closed_and_exposes_only_safe_metadata() -> None:
    upstream = JSONResponse(
        {
            "status": "completed",
            "model": "ea-onemin-coder",
            "input": [{"role": "user", "content": "private memory"}],
            "instructions": "private instruction",
            "reasoning": {"private": True},
            "output_text": "A grounded answer.",
            "metadata": {
                "upstream_provider": "onemin",
                "upstream_model": "verified-model",
                "provider_account_name": "private-account",
            },
        }
    )

    result = proxy._no_retention_response(upstream)
    payload = json.loads(result.body)

    assert result.status_code == 200
    assert payload["input"] == []
    assert payload["instructions"] is None
    assert payload["reasoning"] is None
    assert payload["metadata"] == {
        "upstream_provider": "onemin",
        "upstream_model": "verified-model",
        "ea_retention": "none",
        "ea_retention_contract": "no_response_storage_no_debug_v1",
    }

    failed = proxy._no_retention_response(
        JSONResponse(
            {
                "status": "completed",
                "model": "ea-onemin-coder",
                "metadata": {
                    "upstream_provider": "gemini_vortex",
                    "upstream_model": "fallback",
                },
            }
        )
    )
    assert failed.status_code == 502


def test_locked_no_debug_response_uses_only_requested_onemin_model(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _generate(**kwargs: object) -> UpstreamResult:
        observed.update(kwargs)
        return UpstreamResult(
            text="Grounded JSON",
            provider_key="onemin",
            model="verified-model",
        )

    def _unexpected_capture(**_kwargs: object) -> None:
        raise AssertionError("no-retention request reached debug capture")

    monkeypatch.setattr(responses, "_generate_upstream_text", _generate)
    monkeypatch.setattr(responses, "_capture_responses_debug", _unexpected_capture)
    monkeypatch.setattr(responses, "_write_responses_live_summary", _unexpected_capture)
    monkeypatch.setattr(responses, "_codex_profile", lambda *_args, **_kwargs: {})

    result = responses._run_response(
        _memorial_payload(input="status"),
        context=RequestContext(
            principal_id="memorial-service",
            authenticated=True,
            auth_source="no_retention_client_token",
        ),
        codex_profile="groundwork",
        lock_requested_model=True,
        allow_debug_capture=False,
    )

    payload = json.loads(result.body)
    assert result.status_code == 200
    assert observed["requested_model"] == "ea-onemin-coder"
    assert payload["metadata"]["upstream_provider"] == "onemin"


def test_compose_persists_private_ingress_and_secret_file_contract() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["ea-responses-proxy"]

    assert service["networks"]["public_ingress"] == {
        "ipv4_address": "${EA_PUBLIC_INGRESS_RESPONSES_PROXY_IPV4:-172.31.254.5}",
        "aliases": ["ea-onemin-manager"],
    }
    assert "default" in service["networks"]
    assert (
        "EA_RESPONSES_NO_RETENTION_CLIENT_TOKEN_FILE=/run/secrets/no_retention_client_token"
        in service["environment"]
    )
    secret_mount = next(
        volume
        for volume in service["volumes"]
        if isinstance(volume, dict)
        and volume.get("target") == "/run/secrets/no_retention_client_token"
    )
    assert secret_mount["read_only"] is True
    assert secret_mount["bind"]["create_host_path"] is False
