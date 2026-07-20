from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from app.services.memorial_voice_preview import (
    VoicePreviewSessionError,
    issue_memorial_voice_preview_session,
    preview_operator_binding,
    verify_memorial_voice_preview_session,
)


SOURCE_REVISION = "a" * 40
DEPLOYMENT_ID = "deploy-manfred-20260720-001"
SIGNING_SECRET = "memorial-preview-test-signing-secret-0000000000000000"
WRITE_TOKEN = "memorial-write-token-000000000000000000000000"
ROTATED_WRITE_TOKEN = "rotated-write-token-0000000000000000000000"
NOW = 1_784_566_800.0
NONCE = "preview-session-nonce-000000000000"


def _binding(*, write_token: str = WRITE_TOKEN) -> str:
    return preview_operator_binding(
        write_token=write_token,
        signing_secret=SIGNING_SECRET,
    )


def _issue(**overrides: object) -> str:
    values: dict[str, object] = {
        "source_revision": SOURCE_REVISION,
        "deployment_id": DEPLOYMENT_ID,
        "write_token": WRITE_TOKEN,
        "signing_secret": SIGNING_SECRET,
        "now": NOW,
        "nonce": NONCE,
    }
    values.update(overrides)
    return issue_memorial_voice_preview_session(**values)  # type: ignore[arg-type]


def _verify(token: object, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "source_revision": SOURCE_REVISION,
        "deployment_id": DEPLOYMENT_ID,
        "current_write_tokens": (WRITE_TOKEN,),
        "signing_secret": SIGNING_SECRET,
        "now": NOW + 1,
    }
    values.update(overrides)
    return verify_memorial_voice_preview_session(token, **values)  # type: ignore[arg-type]


def _blocked(reason: str) -> dict[str, object]:
    return {
        "preview_session_valid": False,
        "public_release_allowed": False,
        "reason": reason,
        "status": "blocked",
    }


def _payload(token: str) -> dict[str, object]:
    encoded = token.split(".")[1]
    return json.loads(
        base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    )


def _sign_raw_payload(raw_payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(raw_payload).decode("ascii").rstrip("=")
    purpose_key = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        b"ea.manfred_voice_preview.v1\0session-signature",
        hashlib.sha256,
    ).digest()
    signature = hmac.new(
        purpose_key,
        f"v1.{encoded}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"v1.{encoded}.{encoded_signature}"


def _sign_payload(payload: dict[str, object]) -> str:
    return _sign_raw_payload(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def test_preview_session_is_short_lived_and_exact_deployment_bound() -> None:
    token = _issue(ttl_seconds=600)

    result = _verify(token)

    assert result == {
        "preview_session_valid": True,
        "public_release_allowed": False,
        "deployment_id": DEPLOYMENT_ID,
        "expires_at": int(NOW) + 600,
        "memorial_slug": "manfred",
        "reason": "",
        "source_revision": SOURCE_REVISION,
        "status": "operator_preview",
    }
    assert "allowed" not in result
    assert "operator_binding" not in result
    assert WRITE_TOKEN not in token
    assert SIGNING_SECRET not in token


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"source_revision": "b" * 40}, "preview_session_deployment_binding_mismatch"),
        ({"deployment_id": "deploy-manfred-other"}, "preview_session_deployment_binding_mismatch"),
        ({"memorial_slug": "other"}, "preview_session_scope_mismatch"),
        ({"now": NOW + 600}, "preview_session_expired"),
    ],
)
def test_preview_session_rejects_wrong_scope_binding_or_expiry(
    overrides: dict[str, object], reason: str
) -> None:
    result = _verify(_issue(ttl_seconds=600), **overrides)

    assert result == _blocked(reason)


def test_preview_session_rejects_signature_and_payload_tampering() -> None:
    token = _issue()
    version, encoded, signature = token.split(".")
    tampered_signature = signature[:-1] + ("A" if signature[-1] != "A" else "B")
    assert _verify(f"{version}.{encoded}.{tampered_signature}") == _blocked(
        "preview_session_signature_invalid"
    )

    payload = _payload(token)
    payload["expires_at"] = int(payload["expires_at"]) + 30
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    assert _verify(f"{version}.{tampered_payload}.{signature}") == _blocked(
        "preview_session_signature_invalid"
    )


def test_preview_session_rejects_base64url_signature_pad_bit_alias() -> None:
    token = _issue()
    version, encoded, signature = token.split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    last_index = alphabet.index(signature[-1])
    alias = signature[:-1] + alphabet[last_index ^ 1]

    assert alias != signature
    assert base64.urlsafe_b64decode(alias + "=") == base64.urlsafe_b64decode(signature + "=")
    assert _verify(f"{version}.{encoded}.{alias}") == _blocked(
        "preview_session_signature_invalid"
    )


def test_preview_session_rejects_noncanonical_signed_payload() -> None:
    noncanonical = json.dumps(_payload(_issue()), indent=2).encode("utf-8")

    assert _verify(_sign_raw_payload(noncanonical)) == _blocked(
        "preview_session_schema_invalid"
    )


def test_preview_session_rejects_duplicate_signed_fields() -> None:
    canonical = json.dumps(
        _payload(_issue()),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    duplicate = canonical[:-1] + ',"source_revision":"' + SOURCE_REVISION + '"}'

    assert _verify(_sign_raw_payload(duplicate.encode("utf-8"))) == _blocked(
        "preview_session_payload_invalid"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_release_allowed", True),
        ("readiness_allowed", True),
        ("gold_claim_allowed", True),
        ("release_authority", "pass"),
        ("deploy_permit", "attacker-selected"),
    ],
)
def test_preview_session_rejects_signed_authority_field_injection(
    field: str,
    value: object,
) -> None:
    payload = _payload(_issue())
    payload[field] = value

    assert _verify(_sign_payload(payload)) == _blocked("preview_session_schema_invalid")


@pytest.mark.parametrize(
    "nonce",
    [
        123,
        "too-short",
        "x" * 23,
        "x" * 161,
        "preview-session-nonce-with-equals=",
        "preview-session-nonce-with-unicode-ö",
    ],
)
def test_preview_session_rejects_invalid_signed_nonce(nonce: object) -> None:
    payload = _payload(_issue())
    payload["nonce"] = nonce

    assert _verify(_sign_payload(payload)) == _blocked("preview_session_nonce_invalid")


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"source_revision": "bad"}, "preview_session_source_revision_invalid"),
        ({"source_revision": "A" * 40}, "preview_session_source_revision_invalid"),
        ({"deployment_id": "local-fallback"}, "preview_session_deployment_id_invalid"),
        ({"deployment_id": "local_fallback"}, "preview_session_deployment_id_invalid"),
        (
            {"deployment_id": "deployment_id_local_fallback"},
            "preview_session_deployment_id_invalid",
        ),
        ({"deployment_id": "deploy-manfred-ö"}, "preview_session_deployment_id_invalid"),
        ({"write_token": "bad"}, "preview_operator_token_invalid"),
        ({"ttl_seconds": 16}, "preview_session_ttl_invalid"),
        ({"ttl_seconds": 901}, "preview_session_ttl_invalid"),
        ({"memorial_slug": "other"}, "preview_session_slug_invalid"),
        ({"nonce": 123}, "preview_session_nonce_invalid"),
        ({"nonce": "preview-session-nonce-with-ö"}, "preview_session_nonce_invalid"),
    ],
)
def test_preview_session_issuance_fails_closed(
    kwargs: dict[str, object], reason: str
) -> None:
    with pytest.raises(VoicePreviewSessionError, match=reason):
        _issue(**kwargs)


def test_preview_session_is_bound_to_current_write_token_rotation() -> None:
    token = _issue()

    assert _verify(
        token,
        current_write_tokens=(ROTATED_WRITE_TOKEN, WRITE_TOKEN),
    )["preview_session_valid"] is True
    assert _verify(
        token,
        current_write_tokens=(ROTATED_WRITE_TOKEN,),
    ) == _blocked("preview_session_operator_binding_mismatch")
    assert _verify(token, current_write_tokens=()) == _blocked(
        "preview_session_operator_binding_invalid"
    )
    assert _verify(token, current_write_tokens=WRITE_TOKEN) == _blocked(
        "preview_session_operator_binding_invalid"
    )


def test_preview_session_binding_is_derived_not_caller_selected() -> None:
    token = _issue(write_token=ROTATED_WRITE_TOKEN)
    payload = _payload(token)

    assert payload["operator_binding"] == _binding(write_token=ROTATED_WRITE_TOKEN)
    assert payload["operator_binding"] != _binding()
    assert _verify(
        token,
        current_write_tokens=(ROTATED_WRITE_TOKEN,),
    )["preview_session_valid"] is True


@pytest.mark.parametrize(
    "token",
    [
        None,
        "☃",
        "v1.☃." + "A" * 43,
        "v1." + "A" * 20 + "." + "☃" * 43,
        "v1.." + "A" * 43,
        "v2." + "A" * 20 + "." + "A" * 43,
        "x" * 4097,
    ],
)
def test_preview_session_rejects_untrusted_unicode_and_malformed_input_without_raising(
    token: object,
) -> None:
    result = _verify(token)

    assert result["preview_session_valid"] is False
    assert result["public_release_allowed"] is False
    assert result["status"] == "blocked"


def test_preview_session_rejects_noncanonical_whitespace_alias() -> None:
    token = _issue()

    assert _verify(f" {token} ")["preview_session_valid"] is False


def test_preview_session_rejects_rotated_signing_secret_and_unicode_deploy_binding() -> None:
    token = _issue()

    assert _verify(
        token,
        signing_secret="rotated-preview-signing-secret-000000000000000000",
    ) == _blocked("preview_session_signature_invalid")
    assert _verify(token, deployment_id="deploy-manfred-ö") == _blocked(
        "preview_session_deployment_binding_invalid"
    )


def test_operator_binding_requires_strong_inputs_and_never_echoes_token() -> None:
    with pytest.raises(VoicePreviewSessionError, match="preview_operator_token_invalid"):
        preview_operator_binding(
            write_token="short",
            signing_secret=SIGNING_SECRET,
        )
    binding = _binding()
    assert len(binding) == 64
    assert WRITE_TOKEN not in binding
