from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import capture_blipai_protected_password_session as module


EXPECTED_EMAIL = "operator@example.test"
IMAGE_ID = "sha256:" + ("a" * 64)
NONCE = "A" * 43


def _private(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _credentials(path: Path, *, email: str = EXPECTED_EMAIL) -> Path:
    return _private(
        path,
        "\n".join(
            (
                "UNRELATED=value",
                f"{module.USERNAME_KEY}={email}",
                f"{module.PASSWORD_KEY}=correct-horse-battery-staple",
                "",
            )
        ),
    )


def _config(tmp_path: Path, *, confirmed: bool = True) -> module.PasswordCaptureConfig:
    return module.PasswordCaptureConfig(
        credential_env_file=_credentials(tmp_path / ".env"),
        expected_email=EXPECTED_EMAIL,
        image_id=IMAGE_ID,
        state_dir=tmp_path / "state",
        receipt_path=tmp_path / "receipt.json",
        invocation_nonce=NONCE,
        supabase_api_key_file=_private(tmp_path / "anon-key", "public-key"),
        operator_confirmed=confirmed,
    )


def test_reads_exact_protected_credentials_and_ignores_unrelated_values(
    tmp_path: Path,
) -> None:
    credentials = module._read_credentials(
        _credentials(tmp_path / ".env"),
        expected_email=EXPECTED_EMAIL,
    )
    assert credentials.email == EXPECTED_EMAIL
    assert credentials.password == "correct-horse-battery-staple"


@pytest.mark.parametrize("mode", (0o400, 0o640, 0o644))
def test_credential_file_requires_exact_owner_only_mode(
    tmp_path: Path,
    mode: int,
) -> None:
    path = _credentials(tmp_path / ".env")
    path.chmod(mode)
    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._read_credentials(path, expected_email=EXPECTED_EMAIL)
    assert captured.value.code == "credential_file_invalid"


def test_credential_file_rejects_symlink(tmp_path: Path) -> None:
    real = _credentials(tmp_path / "real.env")
    linked = tmp_path / "linked.env"
    linked.symlink_to(real)
    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._read_credentials(linked, expected_email=EXPECTED_EMAIL)
    assert captured.value.code == "credential_file_invalid"


def test_credential_file_rejects_duplicate_required_key(tmp_path: Path) -> None:
    path = _credentials(tmp_path / ".env")
    path.write_text(
        path.read_text(encoding="utf-8")
        + f"{module.PASSWORD_KEY}=replacement\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._read_credentials(path, expected_email=EXPECTED_EMAIL)
    assert captured.value.code == "credential_file_invalid"


def test_credential_file_rejects_account_mismatch(tmp_path: Path) -> None:
    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._read_credentials(
            _credentials(tmp_path / ".env", email="other@example.test"),
            expected_email=EXPECTED_EMAIL,
        )
    assert captured.value.code == "credential_account_mismatch"


class _GrantResponse:
    def __init__(
        self,
        *,
        url: str = module.PASSWORD_GRANT_URL,
        content_type: str = "application/json",
    ) -> None:
        self.status = 200
        self._url = url
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _maximum: int) -> bytes:
        return json.dumps(
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "user": {"id": "subject-1", "email": EXPECTED_EMAIL},
            }
        ).encode("utf-8")


def test_password_grant_uses_exact_tls_request_without_proxy_or_redirect() -> None:
    observed: dict[str, Any] = {}

    class _Opener:
        def open(self, request, *, timeout: int):  # type: ignore[no-untyped-def]
            observed["url"] = request.full_url
            observed["method"] = request.get_method()
            observed["timeout"] = timeout
            observed["body"] = json.loads(bytes(request.data).decode("utf-8"))
            observed["api_key_present"] = bool(request.get_header("Apikey"))
            return _GrantResponse()

    def _factory(*handlers: object):
        observed["proxy_empty"] = any(
            getattr(handler, "proxies", None) == {} for handler in handlers
        )
        observed["redirect_blocked"] = any(
            isinstance(handler, module.capture._NoRedirectHandler)
            for handler in handlers
        )
        return _Opener()

    granted = module._password_grant_once(
        credentials=module.ProtectedCredentials(
            email=EXPECTED_EMAIL,
            password="correct-horse-battery-staple",
        ),
        api_key="public-anon-key",
        opener_factory=_factory,
    )

    assert observed == {
        "proxy_empty": True,
        "redirect_blocked": True,
        "url": module.PASSWORD_GRANT_URL,
        "method": "POST",
        "timeout": 20,
        "body": {
            "email": EXPECTED_EMAIL,
            "password": "correct-horse-battery-staple",
        },
        "api_key_present": True,
    }
    assert granted.subject == "subject-1"
    assert granted.email == EXPECTED_EMAIL


@pytest.mark.parametrize(
    ("url", "content_type"),
    (
        ("https://example.test/redirected", "application/json"),
        (module.PASSWORD_GRANT_URL, "text/html"),
    ),
)
def test_password_grant_rejects_redirect_or_wrong_content_type(
    url: str,
    content_type: str,
) -> None:
    class _Opener:
        def open(self, _request, *, timeout: int):  # type: ignore[no-untyped-def]
            assert timeout == 20
            return _GrantResponse(url=url, content_type=content_type)

    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._password_grant_once(
            credentials=module.ProtectedCredentials(
                email=EXPECTED_EMAIL,
                password="correct-horse-battery-staple",
            ),
            api_key="public-anon-key",
            opener_factory=lambda *_handlers: _Opener(),
        )
    assert captured.value.code == "password_grant_failed"


def test_run_capture_rotates_once_and_saves_only_rotated_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.state_dir.mkdir(mode=0o700)
    granted = module.capture.RefreshedMaterial(
        access_token="grant-access",
        refresh_token="grant-refresh",
        subject="subject-1",
        email=EXPECTED_EMAIL,
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(module, "_validate_config", lambda value: value)
    monkeypatch.setattr(module.capture, "_read_api_key_file", lambda _path: "anon")
    monkeypatch.setattr(module, "_password_grant_once", lambda **_kwargs: granted)
    monkeypatch.setattr(
        module.capture,
        "_decode_jwt_claims",
        lambda *_args, **_kwargs: SimpleNamespace(subject="subject-1"),
    )
    monkeypatch.setattr(
        module.capture,
        "_preflight_runtime_state",
        lambda *_args, **_kwargs: observed.setdefault("preflight", True),
    )
    monkeypatch.setattr(
        module.capture,
        "_refresh_session",
        lambda **_kwargs: ("rotated-access", "rotated-refresh"),
    )
    monkeypatch.setattr(
        module.capture,
        "_validate_user_session",
        lambda **_kwargs: observed.setdefault("validated", True),
    )

    def _save(_config, *, access_token: str, refresh_token: str) -> None:
        observed["saved"] = (access_token, refresh_token)

    monkeypatch.setattr(module.capture, "_save_runtime_state_with_retries", _save)

    receipt = module._run_capture(config)

    assert receipt["status"] == "capture_complete"
    assert receipt["local_refresh"] == "single_attempt_pass"
    assert receipt["rotated_overwrite_save_reload"] == "pass"
    assert observed["saved"] == ("rotated-access", "rotated-refresh")
    assert receipt["browser_received_credentials"] is False
    serialized = json.dumps(receipt)
    assert "correct-horse" not in serialized
    assert EXPECTED_EMAIL not in serialized
    assert os.fspath(config.credential_env_file) not in serialized


def test_run_capture_failure_receipt_never_contains_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.state_dir.mkdir(mode=0o700)
    monkeypatch.setattr(module, "_validate_config", lambda value: value)
    monkeypatch.setattr(module.capture, "_read_api_key_file", lambda _path: "anon")
    monkeypatch.setattr(
        module.capture,
        "_preflight_runtime_state",
        lambda *_args, **_kwargs: None,
    )

    def _fail(**_kwargs):
        raise module.PasswordCaptureFailure("password_grant_failed")

    monkeypatch.setattr(module, "_password_grant_once", _fail)
    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._run_capture(config)
    receipt = module._failure_receipt(
        config=config,
        code=captured.value.code,
        evidence=captured.value.evidence,
    )
    serialized = json.dumps(receipt)
    assert receipt["status"] == "fail"
    assert receipt["error_code"] == "password_grant_failed"
    assert "correct-horse" not in serialized
    assert EXPECTED_EMAIL not in serialized
    assert os.fspath(config.credential_env_file) not in serialized


def test_confirmation_is_mandatory_before_any_runtime_or_network_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, confirmed=False)
    touched = False

    def _touched(*_args, **_kwargs):
        nonlocal touched
        touched = True

    monkeypatch.setattr(module.capture, "_read_api_key_file", _touched)
    with pytest.raises(module.PasswordCaptureFailure) as captured:
        module._run_capture(config)
    assert captured.value.code == "operator_credential_confirmation_required"
    assert touched is False


def test_failure_receipt_is_nonfinal_and_secret_free(tmp_path: Path) -> None:
    config = _config(tmp_path)
    receipt = module._failure_receipt(
        config=config,
        code="password_grant_failed",
        evidence={"runtime_preflight": "pass"},
    )
    assert receipt["status"] == "fail"
    assert receipt["runtime_preflight"] == "pass"
    assert receipt["runtime_secrets_included"] is False
    assert receipt["credential_metadata_included"] is False
    assert receipt["token_family_ownership"] == "not_proven"
