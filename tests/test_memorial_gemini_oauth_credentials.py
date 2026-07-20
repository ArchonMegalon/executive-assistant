from __future__ import annotations

import concurrent.futures
import fcntl
import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest
import requests

from app.api.routes import public_memorials


class _OAuthResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: object | None = None,
        text: str = "",
        invalid_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._invalid_json = invalid_json

    def json(self) -> object:
        if self._invalid_json:
            raise ValueError("invalid json")
        return self._payload


@pytest.fixture()
def oauth_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    credential_dir = tmp_path / "gemini-oauth"
    credential_dir.mkdir(mode=0o700)
    credential_dir.chmod(0o700)
    target = credential_dir / "oauth_creds.json"
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_LIVE_OAUTH", "1")
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", str(target))
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("EA_MEMORIAL_GEMINI_OAUTH_FORCE_REFRESH", raising=False)
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_UNTIL",
        0.0,
    )
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_IDENTITY",
        None,
    )
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_REASON",
        "",
    )
    return target


def _write_secure_creds(target: Path, payload: dict[str, object]) -> None:
    target.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    target.chmod(0o600)


def _expired_creds(*, refreshed: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "access_token": "expired-access-token",
        "expiry_date": int((time.time() - 60) * 1000),
        "refresh_token": "refresh-token",
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/cloud-platform",
    }
    if refreshed:
        payload["ea_memorial_live_refreshed_at"] = "2026-07-19T00:00:00+00:00"
    return payload


def test_oauth_runtime_default_never_reads_operator_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()
    monkeypatch.setenv("HOME", str(operator_home))
    monkeypatch.delenv("EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH", raising=False)
    monkeypatch.delenv("EA_GEMINI_OAUTH_CREDS_PATH", raising=False)

    resolved = public_memorials._gemini_live_oauth_creds_path()

    assert resolved == Path(
        "/data/memorial-writable/state/gemini-oauth/oauth_creds.json"
    )
    assert operator_home not in resolved.parents


def test_secure_oauth_credential_round_trip_is_atomic_and_private(
    oauth_path: Path,
) -> None:
    original = _expired_creds()
    _write_secure_creds(oauth_path, original)
    original_inode = oauth_path.stat().st_ino

    assert public_memorials._load_gemini_live_oauth_creds() == original

    updated = {**original, "access_token": "new-access-token"}
    public_memorials._save_gemini_live_oauth_creds(updated)

    metadata = oauth_path.stat()
    assert metadata.st_ino != original_inode
    assert metadata.st_nlink == 1
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert public_memorials._load_gemini_live_oauth_creds() == updated
    assert sorted(path.name for path in oauth_path.parent.iterdir()) == [
        ".oauth_creds.lock",
        "oauth_creds.json"
    ]
    lock_metadata = (oauth_path.parent / ".oauth_creds.lock").stat()
    assert stat.S_ISREG(lock_metadata.st_mode)
    assert lock_metadata.st_nlink == 1
    assert lock_metadata.st_size == 0
    assert stat.S_IMODE(lock_metadata.st_mode) == 0o600
    assert lock_metadata.st_uid == os.geteuid()
    assert lock_metadata.st_gid == os.getegid()


def test_oauth_runtime_fails_closed_while_provisioner_lock_is_held(
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    assert public_memorials._load_gemini_live_oauth_creds()
    lock_path = oauth_path.parent / ".oauth_creds.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        loaded, reason = (
            public_memorials._load_gemini_live_oauth_creds_with_reason()
        )
        token, status = (
            public_memorials._gemini_live_oauth_access_token_with_status()
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert loaded == {}
    assert reason == "credential_lock_busy"
    assert token == ""
    assert status["state"] == "unavailable"
    assert status["reason"] == "credential_lock_busy"


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o644])
def test_oauth_loader_rejects_non_private_modes(
    oauth_path: Path,
    mode: int,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    oauth_path.chmod(mode)

    assert public_memorials._load_gemini_live_oauth_creds() == {}


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("refresh_token", "", "credential_refresh_token_invalid"),
        ("token_type", "Basic", "credential_token_type_invalid"),
        ("scope", "openid email", "credential_scope_invalid"),
        ("access_token", "", "credential_access_token_invalid"),
        ("expiry_date", True, "credential_expiry_invalid"),
        ("expiry_date", 1.5, "credential_expiry_invalid"),
        ("expiry_date", 4_102_444_800_001, "credential_expiry_invalid"),
    ],
)
def test_oauth_loader_enforces_provisioner_credential_contract(
    oauth_path: Path,
    field: str,
    value: object,
    reason: str,
) -> None:
    payload = _expired_creds()
    payload[field] = value
    _write_secure_creds(oauth_path, payload)

    loaded, load_reason = (
        public_memorials._load_gemini_live_oauth_creds_with_reason()
    )

    assert loaded == {}
    assert load_reason == reason


def test_oauth_loader_accepts_refresh_only_provisioner_contract(
    oauth_path: Path,
) -> None:
    payload = _expired_creds()
    payload.pop("access_token")
    payload.pop("expiry_date")
    _write_secure_creds(oauth_path, payload)

    assert public_memorials._load_gemini_live_oauth_creds() == payload


def test_oauth_loader_rejects_symlink_hardlink_and_oversized_inputs(
    oauth_path: Path,
) -> None:
    source = oauth_path.parent / "source.json"
    _write_secure_creds(source, _expired_creds())
    oauth_path.symlink_to(source)
    assert public_memorials._load_gemini_live_oauth_creds() == {}

    oauth_path.unlink()
    os.link(source, oauth_path)
    assert public_memorials._load_gemini_live_oauth_creds() == {}

    oauth_path.unlink()
    source.unlink()
    oauth_path.write_bytes(
        b"x" * (public_memorials._MEMORIAL_GEMINI_OAUTH_CREDS_MAX_BYTES + 1)
    )
    oauth_path.chmod(0o600)
    assert public_memorials._load_gemini_live_oauth_creds() == {}


def test_oauth_save_rejects_insecure_directory_and_target(
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    oauth_path.parent.chmod(0o755)
    with pytest.raises(
        public_memorials._GeminiLiveOAuthCredentialError,
        match="gemini_oauth_credential_directory_insecure",
    ):
        public_memorials._save_gemini_live_oauth_creds(_expired_creds())

    oauth_path.parent.chmod(0o700)
    oauth_path.unlink()
    source = oauth_path.parent / "source.json"
    _write_secure_creds(source, _expired_creds())
    oauth_path.symlink_to(source)
    with pytest.raises(
        public_memorials._GeminiLiveOAuthCredentialError,
        match="gemini_oauth_credential_target_insecure",
    ):
        public_memorials._save_gemini_live_oauth_creds(_expired_creds())


def test_refresh_persists_once_and_subsequent_calls_reuse_token(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    calls: list[dict[str, object]] = []

    def post(*_args: object, **kwargs: object) -> _OAuthResponse:
        calls.append(dict(kwargs))
        return _OAuthResponse(
            payload={
                "access_token": "fresh-access-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        )

    monkeypatch.setattr(public_memorials.requests, "post", post)

    assert public_memorials._gemini_live_oauth_access_token() == (
        "fresh-access-token"
    )
    assert public_memorials._gemini_live_oauth_access_token() == (
        "fresh-access-token"
    )
    assert len(calls) == 1
    persisted = public_memorials._load_gemini_live_oauth_creds()
    assert persisted["access_token"] == "fresh-access-token"
    assert persisted["refresh_token"] == "refresh-token"
    assert persisted.get("ea_memorial_live_refreshed_at")
    assert "ea_memorial_live_refresh_failed_at" not in persisted


def test_refresh_failure_never_returns_expired_token_and_cooldown_is_durable(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds(refreshed=True))
    call_count = 0

    def post(*_args: object, **_kwargs: object) -> _OAuthResponse:
        nonlocal call_count
        call_count += 1
        return _OAuthResponse(
            status_code=500,
            payload={},
            text="provider-response-must-not-be-logged",
        )

    monkeypatch.setattr(public_memorials.requests, "post", post)

    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert call_count == 1
    persisted = public_memorials._load_gemini_live_oauth_creds()
    assert persisted["ea_memorial_live_refresh_failed_reason"] == "http_500"

    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_UNTIL",
        0.0,
    )
    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert call_count == 1
    assert "provider-response-must-not-be-logged" not in caplog.text
    assert "expired-access-token" not in caplog.text
    assert "refresh-token" not in caplog.text


def test_refresh_persistence_failure_fails_closed_without_retry_storm(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    call_count = 0

    def post(*_args: object, **_kwargs: object) -> _OAuthResponse:
        nonlocal call_count
        call_count += 1
        return _OAuthResponse(
            payload={
                "access_token": "must-not-be-returned",
                "expires_in": 3600,
            }
        )

    def fail_save(_creds: dict[str, object]) -> None:
        raise public_memorials._GeminiLiveOAuthCredentialError(
            "gemini_oauth_credential_write_failed"
        )

    monkeypatch.setattr(public_memorials.requests, "post", post)
    monkeypatch.setattr(public_memorials, "_save_gemini_live_oauth_creds", fail_save)

    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert call_count == 1
    assert "persistence failed" in caplog.text
    assert "must-not-be-returned" not in caplog.text
    assert "refresh-token" not in caplog.text


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (_OAuthResponse(invalid_json=True), "response_json_invalid"),
        (_OAuthResponse(payload=[]), "response_payload_invalid"),
        (_OAuthResponse(payload={}), "missing_access_token"),
        (
            _OAuthResponse(
                payload={
                    "access_token": "must-not-persist",
                    "token_type": "Basic",
                }
            ),
            "response_token_type_invalid",
        ),
        (
            _OAuthResponse(
                payload={
                    "access_token": "must-not-persist",
                    "scope": "openid email",
                }
            ),
            "response_scope_invalid",
        ),
        (
            _OAuthResponse(
                payload={
                    "access_token": "must-not-persist",
                    "expires_in": 10**12,
                }
            ),
            "refreshed_credential_invalid",
        ),
    ],
)
def test_invalid_refresh_responses_persist_failure_cooldown(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
    response: _OAuthResponse,
    reason: str,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    call_count = 0

    def post(*_args: object, **_kwargs: object) -> _OAuthResponse:
        nonlocal call_count
        call_count += 1
        return response

    monkeypatch.setattr(public_memorials.requests, "post", post)

    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert public_memorials._gemini_live_oauth_access_token() == ""
    assert call_count == 1
    assert public_memorials._load_gemini_live_oauth_creds()[
        "ea_memorial_live_refresh_failed_reason"
    ] == reason


def test_concurrent_expired_token_requests_perform_one_refresh(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    call_count = 0
    call_lock = threading.Lock()

    def post(*_args: object, **_kwargs: object) -> _OAuthResponse:
        nonlocal call_count
        with call_lock:
            call_count += 1
        time.sleep(0.02)
        return _OAuthResponse(
            payload={
                "access_token": "single-refreshed-token",
                "expires_in": 3600,
            }
        )

    monkeypatch.setattr(public_memorials.requests, "post", post)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        tokens = list(
            executor.map(
                lambda _index: public_memorials._gemini_live_oauth_access_token(),
                range(8),
            )
        )

    assert tokens == ["single-refreshed-token"] * 8
    assert call_count == 1


def test_request_exception_persists_failure_without_secret_logging(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())

    def post(*_args: object, **_kwargs: object) -> _OAuthResponse:
        raise requests.RequestException("refresh-token must not be logged")

    monkeypatch.setattr(public_memorials.requests, "post", post)

    assert public_memorials._gemini_live_oauth_access_token() == ""
    persisted = public_memorials._load_gemini_live_oauth_creds()
    assert persisted["ea_memorial_live_refresh_failed_reason"] == (
        "request_exception"
    )
    assert "refresh-token" not in caplog.text


def test_force_refresh_bypasses_durable_and_process_cooldowns(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
) -> None:
    failed = _expired_creds(refreshed=True)
    failed["ea_memorial_live_refresh_failed_at"] = time.time()
    failed["ea_memorial_live_refresh_failed_reason"] = "http_401"
    _write_secure_creds(oauth_path, failed)
    monkeypatch.setenv("EA_MEMORIAL_GEMINI_OAUTH_FORCE_REFRESH", "1")
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_UNTIL",
        time.monotonic() + 600,
    )
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_IDENTITY",
        public_memorials._gemini_live_oauth_current_identity(),
    )
    monkeypatch.setattr(
        public_memorials,
        "_MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_REASON",
        "credential_state_write_failed",
    )
    calls = 0

    def post(*_args: object, **_kwargs: object) -> _OAuthResponse:
        nonlocal calls
        calls += 1
        return _OAuthResponse(
            payload={"access_token": "forced-token", "expires_in": 3600}
        )

    monkeypatch.setattr(public_memorials.requests, "post", post)

    assert public_memorials._gemini_live_oauth_access_token() == "forced-token"
    assert calls == 1
    persisted = public_memorials._load_gemini_live_oauth_creds()
    assert "ea_memorial_live_refresh_failed_at" not in persisted
    assert public_memorials._MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_UNTIL == 0.0


def test_process_cooldown_clears_when_credential_identity_changes(
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds(refreshed=True))
    public_memorials._gemini_live_oauth_set_process_failure_cooldown(
        reason="credential_state_write_failed"
    )
    assert (
        public_memorials._gemini_live_oauth_process_failure_cooldown_remaining()
        > 0.0
    )

    repaired = {
        "access_token": "repaired-token",
        "expiry_date": int((time.time() + 3600) * 1000),
        "refresh_token": "repaired-refresh-token",
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "ea_memorial_live_refreshed_at": "2026-07-20T00:00:00+00:00",
    }
    public_memorials._save_gemini_live_oauth_creds(repaired)

    token, status = public_memorials._gemini_live_oauth_access_token_with_status()
    assert token == "repaired-token"
    assert status["state"] == "ready"
    assert public_memorials._MEMORIAL_GEMINI_OAUTH_PROCESS_FAILURE_UNTIL == 0.0


def test_credential_status_is_actionable_and_secret_free(
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    oauth_path.chmod(0o644)

    token, status = public_memorials._gemini_live_oauth_access_token_with_status()

    assert token == ""
    assert status == {
        "mode": "",
        "state": "unavailable",
        "reason": "credential_mode_insecure",
        "cooldown_remaining_seconds": 0.0,
    }
    rendered = json.dumps(status, sort_keys=True)
    assert "expired-access-token" not in rendered
    assert "refresh-token" not in rendered


def test_atomic_save_detects_post_replace_content_change(
    monkeypatch: pytest.MonkeyPatch,
    oauth_path: Path,
) -> None:
    _write_secure_creds(oauth_path, _expired_creds())
    real_open = public_memorials.os.open
    tampered = False

    def racing_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal tampered
        if (
            not tampered
            and path == oauth_path.name
            and dir_fd is not None
            and not flags & os.O_DIRECTORY
        ):
            tampered = True
            oauth_path.write_text('{"access_token":"tampered"}\n', encoding="utf-8")
            oauth_path.chmod(0o600)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(public_memorials.os, "open", racing_open)

    with pytest.raises(
        public_memorials._GeminiLiveOAuthCredentialError,
        match="gemini_oauth_credential_persisted_content_changed",
    ):
        public_memorials._save_gemini_live_oauth_creds(
            {**_expired_creds(), "access_token": "expected-token"}
        )
    assert tampered is True
