#!/usr/bin/env python3
"""Rotate a Blip Supabase session from a protected credential file.

This is the fail-closed alternative when the provider's browser checkpoint
rejects the already-authorized local browser.  Credential and token values are
never accepted through argv or the process environment.  The helper reads one
owner-only dotenv file, performs one password grant followed by exactly one
refresh-token rotation, validates the resulting account, and sends the final
pair to the immutable runtime image over stdin.
"""

from __future__ import annotations

import argparse
import ctypes
import hmac
import json
import os
import resource
import secrets
import ssl
import stat
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import capture_blipai_browseract_session as capture
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts import capture_blipai_browseract_session as capture


SCHEMA = "ea.blipai.protected-password-session-capture.v1"
PASSWORD_GRANT_URL = (
    "https://hqwmccawtepvundsgnil.supabase.co"
    "/auth/v1/token?grant_type=password"
)
USERNAME_KEY = "BLIPAI_APP_USERNAME"
PASSWORD_KEY = "BLIPAI_APP_PASSWORD"
MAX_CREDENTIAL_FILE_BYTES = 1_048_576
MAX_PASSWORD_CHARS = 4_096
PR_SET_DUMPABLE = 4


class PasswordCaptureFailure(RuntimeError):
    """A constant, receipt-safe password capture failure."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        self.evidence: dict[str, object] = {}
        super().__init__(self.code)


@dataclass(frozen=True, repr=False)
class ProtectedCredentials:
    email: str
    password: str


@dataclass(frozen=True)
class PasswordCaptureConfig:
    credential_env_file: Path
    expected_email: str
    image_id: str
    state_dir: Path
    receipt_path: Path
    invocation_nonce: str
    supabase_api_key_file: Path
    operator_confirmed: bool


def _harden_process() -> None:
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (OSError, ValueError) as exc:
        raise PasswordCaptureFailure("process_hardening_failed") from exc
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = int(libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0))
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise PasswordCaptureFailure("process_hardening_failed") from exc
    if result != 0:
        raise PasswordCaptureFailure("process_hardening_failed")


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _secure_file_bytes(path: Path, *, error: str) -> bytearray:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        metadata = os.lstat(normalized)
    except OSError as exc:
        raise PasswordCaptureFailure(error) from exc
    if (
        not normalized.is_absolute()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size < 1
        or metadata.st_size > MAX_CREDENTIAL_FILE_BYTES
    ):
        raise PasswordCaptureFailure(error)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblock is None:
        raise PasswordCaptureFailure(error)
    descriptor = -1
    try:
        descriptor = os.open(
            normalized,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | nofollow
            | nonblock,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_uid != metadata.st_uid
            or opened.st_gid != metadata.st_gid
            or opened.st_nlink != metadata.st_nlink
            or opened.st_mode != metadata.st_mode
            or opened.st_size != metadata.st_size
        ):
            raise PasswordCaptureFailure(error)
        encoded = bytearray()
        while len(encoded) <= MAX_CREDENTIAL_FILE_BYTES:
            chunk = os.read(
                descriptor,
                min(65_536, MAX_CREDENTIAL_FILE_BYTES + 1 - len(encoded)),
            )
            if not chunk:
                break
            encoded.extend(chunk)
        final = os.fstat(descriptor)
        if (
            not encoded
            or len(encoded) > MAX_CREDENTIAL_FILE_BYTES
            or final.st_dev != opened.st_dev
            or final.st_ino != opened.st_ino
            or final.st_uid != opened.st_uid
            or final.st_gid != opened.st_gid
            or final.st_nlink != opened.st_nlink
            or final.st_mode != opened.st_mode
            or final.st_size != opened.st_size
            or final.st_mtime_ns != opened.st_mtime_ns
            or final.st_ctime_ns != opened.st_ctime_ns
        ):
            _wipe(encoded)
            raise PasswordCaptureFailure(error)
        return encoded
    except OSError as exc:
        raise PasswordCaptureFailure(error) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _dotenv_value(encoded: bytearray, key: str) -> str:
    prefix = key.encode("ascii") + b"="
    matches: list[bytes] = []
    for raw_line in bytes(encoded).splitlines():
        if raw_line.startswith(prefix):
            matches.append(raw_line[len(prefix) :])
    if len(matches) != 1:
        raise PasswordCaptureFailure("credential_file_invalid")
    try:
        value = matches[0].decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise PasswordCaptureFailure("credential_file_invalid") from exc
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]
    if (
        not value
        or len(value) > MAX_PASSWORD_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PasswordCaptureFailure("credential_file_invalid")
    return value


def _read_credentials(path: Path, *, expected_email: str) -> ProtectedCredentials:
    encoded = _secure_file_bytes(path, error="credential_file_invalid")
    try:
        email = _dotenv_value(encoded, USERNAME_KEY)
        password = _dotenv_value(encoded, PASSWORD_KEY)
    finally:
        _wipe(encoded)
    if not hmac.compare_digest(email.casefold(), expected_email.casefold()):
        raise PasswordCaptureFailure("credential_account_mismatch")
    return ProtectedCredentials(email=email, password=password)


def _password_grant_once(
    *,
    credentials: ProtectedCredentials,
    api_key: str,
    timeout: int = 20,
    opener_factory: Callable[..., object] = urllib.request.build_opener,
) -> capture.RefreshedMaterial:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = opener_factory(
        urllib.request.ProxyHandler({}),
        capture._NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )
    body = bytearray(
        capture._canonical_json_bytes(
            {"email": credentials.email, "password": credentials.password}
        )
    )
    response_bytes = bytearray()
    try:
        request = urllib.request.Request(
            PASSWORD_GRANT_URL,
            method="POST",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "EA-Blip-Protected-Password-Capture/1.0",
                "apikey": api_key,
            },
        )
        try:
            with opener.open(
                request,
                timeout=max(1, min(int(timeout), 60)),
            ) as response:
                if (
                    int(response.status) != 200
                    or response.geturl() != PASSWORD_GRANT_URL
                    or not str(response.headers.get("Content-Type") or "")
                    .lower()
                    .startswith("application/json")
                ):
                    raise PasswordCaptureFailure("password_grant_failed")
                response_bytes.extend(
                    response.read(capture.REFRESH_RESPONSE_MAX_BYTES + 1)
                )
        except PasswordCaptureFailure:
            raise
        except (
            OSError,
            TimeoutError,
            urllib.error.URLError,
            urllib.error.HTTPError,
        ) as exc:
            raise PasswordCaptureFailure("password_grant_failed") from exc
        if (
            not response_bytes
            or len(response_bytes) > capture.REFRESH_RESPONSE_MAX_BYTES
        ):
            raise PasswordCaptureFailure("password_grant_failed")
        try:
            payload = json.loads(response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PasswordCaptureFailure("password_grant_failed") from exc
        user = payload.get("user") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or not isinstance(user, dict)
            or not isinstance(user.get("id"), str)
            or not user.get("id")
            or not isinstance(user.get("email"), str)
            or not user.get("email")
        ):
            raise PasswordCaptureFailure("password_grant_failed")
        return capture.RefreshedMaterial(
            access_token=capture._valid_token_text(payload.get("access_token")),
            refresh_token=capture._valid_token_text(payload.get("refresh_token")),
            subject=str(user["id"]),
            email=str(user["email"]),
        )
    finally:
        _wipe(body)
        _wipe(response_bytes)


def _validate_config(config: PasswordCaptureConfig) -> PasswordCaptureConfig:
    if not config.operator_confirmed:
        raise PasswordCaptureFailure("operator_credential_confirmation_required")
    if (
        not config.expected_email
        or len(config.expected_email) > 320
        or "@" not in config.expected_email
        or any(
            ord(character) < 33 or ord(character) == 127
            for character in config.expected_email
        )
    ):
        raise PasswordCaptureFailure("expected_account_invalid")
    try:
        image_id = capture._validate_image_id(config.image_id)
        state_dir = capture._validate_state_dir(config.state_dir)
        receipt_path = capture._validate_new_receipt_destination(config.receipt_path)
        invocation_nonce = capture._validate_invocation_nonce(
            config.invocation_nonce
        )
        capture._validate_canonical_executable(
            capture.CANONICAL_DOCKER_BIN,
            allowed_uids=frozenset({0, os.geteuid()}),
            error="docker_executable_invalid",
        )
    except capture.CaptureFailure as exc:
        raise PasswordCaptureFailure(exc.code) from exc
    return PasswordCaptureConfig(
        credential_env_file=config.credential_env_file,
        expected_email=config.expected_email,
        image_id=image_id,
        state_dir=state_dir,
        receipt_path=receipt_path,
        invocation_nonce=invocation_nonce,
        supabase_api_key_file=config.supabase_api_key_file,
        operator_confirmed=config.operator_confirmed,
    )


def _capture_config(config: PasswordCaptureConfig) -> capture.CaptureConfig:
    return capture.CaptureConfig(
        session="protected-password-grant",
        expected_email=config.expected_email,
        image_id=config.image_id,
        state_dir=config.state_dir,
        receipt_path=config.receipt_path,
        invocation_nonce=config.invocation_nonce,
        supabase_api_key_file=config.supabase_api_key_file,
        operator_confirmed=True,
        dedicated_session_confirmed=True,
    )


def _run_capture(config: PasswordCaptureConfig) -> dict[str, object]:
    progress: dict[str, object] = {
        "runtime_preflight": "unproven",
        "password_grant": "unproven",
        "local_refresh": "unproven",
        "provider_validation": "unproven",
        "rotated_overwrite_save_reload": "unproven",
    }
    try:
        config = _validate_config(config)
        try:
            api_key = capture._read_api_key_file(config.supabase_api_key_file)
        except capture.CaptureFailure as exc:
            raise PasswordCaptureFailure(exc.code) from exc
        credentials = _read_credentials(
            config.credential_env_file,
            expected_email=config.expected_email,
        )
        runtime_config = _capture_config(config)
        try:
            capture._preflight_runtime_state(
                runtime_config,
                nonce=capture._b64url_encode(secrets.token_bytes(18)),
            )
        except capture.CaptureFailure as exc:
            raise PasswordCaptureFailure(exc.code) from exc
        progress["runtime_preflight"] = "pass"

        granted = _password_grant_once(credentials=credentials, api_key=api_key)
        if (
            not hmac.compare_digest(
                granted.email.casefold(),
                config.expected_email.casefold(),
            )
        ):
            raise PasswordCaptureFailure("credential_account_mismatch")
        try:
            claims = capture._decode_jwt_claims(
                granted.access_token,
                expected_email=config.expected_email,
                expected_subject=granted.subject,
                require_fresh=True,
            )
        except capture.CaptureFailure as exc:
            raise PasswordCaptureFailure(exc.code) from exc
        progress["password_grant"] = "pass"

        try:
            rotated_access, rotated_refresh = capture._refresh_session(
                access_token=granted.access_token,
                refresh_token=granted.refresh_token,
                api_key=api_key,
                expected_email=config.expected_email,
                expected_subject=claims.subject,
            )
        except capture.CaptureFailure as exc:
            raise PasswordCaptureFailure(exc.code) from exc
        progress["local_refresh"] = "single_attempt_pass"

        try:
            capture._validate_user_session(
                access_token=rotated_access,
                api_key=api_key,
                expected_email=config.expected_email,
                expected_subject=claims.subject,
            )
        except capture.CaptureFailure as exc:
            raise PasswordCaptureFailure(exc.code) from exc
        progress["provider_validation"] = "user_endpoint"

        try:
            capture._save_runtime_state_with_retries(
                runtime_config,
                access_token=rotated_access,
                refresh_token=rotated_refresh,
            )
        except capture.CaptureFailure as exc:
            raise PasswordCaptureFailure(exc.code) from exc
        progress["rotated_overwrite_save_reload"] = "pass"
        return {
            "schema": SCHEMA,
            "status": "capture_complete",
            "generated_at_utc": capture._utc_now(),
            "invocation_nonce": config.invocation_nonce,
            "credential_source": "protected_dotenv",
            "credential_file_validation": "owner_only_stable_regular_file",
            "expected_account_match": True,
            **progress,
            "provider_session_rotation": "password_grant_then_single_refresh",
            "provider_transport": "exact_tls_no_proxy_no_redirect",
            "exact_image_id": config.image_id,
            "runtime_state_target": capture.FINAL_STATE_NAME,
            "runtime_save_reload": "pass",
            "browser_dependency": "not_used",
            "browser_received_credentials": False,
            "token_family_ownership": (
                "new_password_grant_rotated_once_no_browser_copy"
            ),
            "separate_ownership_gate_required": False,
            "runtime_secrets_included": False,
            "credential_metadata_included": False,
        }
    except PasswordCaptureFailure as exc:
        exc.evidence.update(progress)
        raise


def _failure_receipt(
    *,
    config: PasswordCaptureConfig,
    code: str,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    safe = dict(evidence or {})
    image_id = (
        config.image_id
        if capture._IMAGE_RE.fullmatch(str(config.image_id or ""))
        else capture.DEFAULT_IMAGE_ID
    )
    return {
        "schema": SCHEMA,
        "status": "fail",
        "generated_at_utc": capture._utc_now(),
        "error_code": str(code),
        "invocation_nonce": (
            config.invocation_nonce
            if capture._INVOCATION_NONCE_RE.fullmatch(
                str(config.invocation_nonce or "")
            )
            else "unproven"
        ),
        "credential_source": "protected_dotenv",
        "credential_file_validation": "unproven",
        "expected_account_match": False,
        "runtime_preflight": safe.get("runtime_preflight", "unproven"),
        "password_grant": safe.get("password_grant", "unproven"),
        "local_refresh": safe.get("local_refresh", "unproven"),
        "provider_validation": safe.get("provider_validation", "unproven"),
        "rotated_overwrite_save_reload": safe.get(
            "rotated_overwrite_save_reload",
            "unproven",
        ),
        "provider_session_rotation": "unproven",
        "provider_transport": "exact_tls_no_proxy_no_redirect",
        "exact_image_id": image_id,
        "runtime_state_target": capture.FINAL_STATE_NAME,
        "runtime_save_reload": "unproven",
        "browser_dependency": "not_used",
        "browser_received_credentials": False,
        "token_family_ownership": "not_proven",
        "separate_ownership_gate_required": True,
        "runtime_secrets_included": False,
        "credential_metadata_included": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rotate one Blip session from an owner-only dotenv file into the "
            "exact immutable memorial runtime state."
        )
    )
    parser.add_argument("--credential-env-file", required=True)
    parser.add_argument("--expected-email", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--invocation-nonce", required=True)
    parser.add_argument("--supabase-api-key-file", required=True)
    parser.add_argument(
        "--operator-confirmed-protected-credential-use",
        action="store_true",
        help=(
            "Required acknowledgement that the operator authorized the exact "
            "protected Blip credential record for this session rotation."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = PasswordCaptureConfig(
        credential_env_file=Path(args.credential_env_file),
        expected_email=str(args.expected_email),
        image_id=str(args.image_id),
        state_dir=Path(args.state_dir),
        receipt_path=Path(args.receipt),
        invocation_nonce=str(args.invocation_nonce),
        supabase_api_key_file=Path(args.supabase_api_key_file),
        operator_confirmed=bool(
            args.operator_confirmed_protected_credential_use
        ),
    )
    try:
        _harden_process()
        receipt = _run_capture(config)
        return_code = 0
    except PasswordCaptureFailure as exc:
        receipt = _failure_receipt(
            config=config,
            code=exc.code,
            evidence=exc.evidence,
        )
        return_code = 1
    except BaseException:
        receipt = _failure_receipt(
            config=config,
            code="unexpected_capture_failure",
        )
        return_code = 1
    try:
        capture._write_receipt(config.receipt_path, receipt)
    except capture.CaptureFailure:
        receipt = _failure_receipt(
            config=config,
            code="receipt_write_failed",
        )
        return_code = 1
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
