#!/usr/bin/env python3
"""Run a bounded, redacted VocalLab account inventory probe.

The command performs authenticated GET requests only. The reserved synthetic
TTS switch fails closed until a durable account-global spend coordinator and
post-balance reconciliation are wired. Provider bodies, balances, keys, voice
IDs, and audio bytes are never written to the probe receipt or stdout.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import deque
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
from typing import Any, Callable, Mapping
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
import wave


_SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
_EA_PYTHON_ROOT = _SCRIPT_REPO_ROOT / "ea"
if str(_EA_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_EA_PYTHON_ROOT))

from app.services.audiobook_tts.providers.vocallab_schema import (  # noqa: E402
    VOCALLAB_GENERATION_PENDING,
    VOCALLAB_GENERATION_SUCCESS,
    VOCALLAB_MODEL_KEYS,
    VOCALLAB_VERIFICATION_SYNTHETIC_POINTS,
    VOCALLAB_VERIFICATION_SYNTHETIC_TEXT,
    VOCALLAB_VERIFICATION_SYNTHETIC_TEXT_SHA256,
    AccountObservation,
    ModelObservation,
    PingObservation,
    VocalLabSchemaError,
    VoiceObservation,
    parse_account,
    parse_generation,
    parse_models,
    parse_ping,
    parse_voices,
)


UTC = timezone.utc
ROOT = _SCRIPT_REPO_ROOT
OFFICIAL_BASE_URL = "https://api.vocallab.ai"
PROBE_CONTRACT = "ea.audiobook_vocallab_provider_probe.v1"
PROBE_VERSION = 1
API_CONTRACT_VERSION = "2026-08-12"
DEFAULT_OUTPUT = ROOT / ".runtime/vocallab-provider-probe.generated.json"
DEFAULT_KEY_FILE = ROOT / "config/vocallab_api_key"
DEFAULT_VERIFICATION_HMAC_KEY_FILE = (
    ROOT / "config/vocallab_verification_hmac_key"
)
CREDENTIAL_ROTATION_AUTHORITY_CONTRACT = (
    "ea.audiobook_vocallab_credential_rotation_authority.v1"
)
AUTHENTICATION_FIELD = "authentication"
PROVENANCE_CONTRACT = "ea.audiobook_vocallab_verification_provenance.v1"
PROVENANCE_VERSION = 1
PROVENANCE_ALGORITHM = "HMAC-SHA256"
PROVENANCE_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "algorithm",
        "signed_contract_name",
        "key_id_sha256",
        "payload_sha256",
        "hmac_sha256",
    }
)
SYNTHETIC_TEXT = VOCALLAB_VERIFICATION_SYNTHETIC_TEXT
SYNTHETIC_TEXT_SHA256 = VOCALLAB_VERIFICATION_SYNTHETIC_TEXT_SHA256
SYNTHETIC_TEXT_POINTS = VOCALLAB_VERIFICATION_SYNTHETIC_POINTS
SUPPORTED_MODELS = VOCALLAB_MODEL_KEYS
KEY_RE = re.compile(r"^vl_live_[A-Za-z0-9_-]{16,160}$")
PRIVATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
MAX_SECRET_BYTES = 1024
MIN_VERIFICATION_HMAC_KEY_BYTES = 32
MAX_VERIFICATION_HMAC_KEY_BYTES = 256
MAX_ENV_BYTES = 1024 * 1024
MAX_CREDENTIAL_ROTATION_AUTHORITY_BYTES = 16 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_AUDIO_BYTES = 32 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_POLL_INTERVAL_SECONDS = 2
DEFAULT_POLL_TIMEOUT_SECONDS = 180
DEFAULT_MINIMUM_REMAINING_POINTS = 3000
MINIMUM_REQUIRED_REMAINING_POINTS = 3000
DEFAULT_REQUESTS_PER_MINUTE = 30
RATE_LIMIT_WINDOW_SECONDS = 60.0
MINIMUM_SMOKE_WAV_DURATION_SECONDS = 0.08
class VocalLabProbeError(RuntimeError):
    """Stable, content-free provider probe failure."""


class VocalLabAuthenticationError(RuntimeError):
    """Stable authentication failure that never includes key material."""


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise VocalLabProbeError("provider_redirect_rejected")


def _utc_text(value: datetime | None = None) -> str:
    current = value or datetime.now(UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _check_private_parent_components(path: Path, *, reason: str) -> Path:
    """Reject symlinked path components and a mutable immediate parent."""

    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    try:
        for part in absolute.parts[1:-1]:
            current /= part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise VocalLabProbeError(reason)
        parent = absolute.parent.lstat()
    except VocalLabProbeError:
        raise
    except OSError as exc:
        raise VocalLabProbeError(reason) from exc
    if (
        stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        raise VocalLabProbeError(reason)
    return absolute


def _read_strict_owner_bytes(
    path: Path,
    *,
    minimum_bytes: int,
    maximum_bytes: int,
    reason: str,
) -> bytes:
    """Read one owner-authoritative file through a stable descriptor snapshot.

    The second identical read plus final identity check is the linearization
    point. Rotation must use owner-controlled atomic replacement. A
    non-cooperating same-UID writer is already able to read/replace signing
    material and is therefore outside this local file-integrity boundary.
    """

    if not hasattr(os, "O_NOFOLLOW"):
        raise VocalLabProbeError(reason)
    target = _check_private_parent_components(path, reason=reason)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise VocalLabProbeError(reason) from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_size < minimum_bytes
            or before.st_size > maximum_bytes
        ):
            raise VocalLabProbeError(reason)
        identity_fields = (
            "st_dev",
            "st_ino",
            "st_uid",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )

        def read_once() -> bytes:
            chunks: list[bytes] = []
            remaining = maximum_bytes + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)

        raw = read_once()
        middle = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        confirmation = read_once()
        after = os.fstat(descriptor)
        path_after = target.lstat()
        identity_before = tuple(
            getattr(before, field) for field in identity_fields
        )
        identity_middle = tuple(
            getattr(middle, field) for field in identity_fields
        )
        identity_after = tuple(
            getattr(after, field) for field in identity_fields
        )
        path_identity = tuple(
            getattr(path_after, field) for field in identity_fields
        )
        if (
            identity_before != identity_middle
            or identity_before != identity_after
            or identity_before != path_identity
            or len(raw) != before.st_size
            or len(confirmation) != before.st_size
            or len(raw) < minimum_bytes
            or len(raw) > maximum_bytes
            or not hmac.compare_digest(raw, confirmation)
        ):
            raise VocalLabProbeError(reason)
        return raw
    except OSError as exc:
        raise VocalLabProbeError(reason) from exc
    finally:
        os.close(descriptor)


def _validate_verification_hmac_key(key: bytes) -> None:
    if (
        not isinstance(key, bytes)
        or len(key) < MIN_VERIFICATION_HMAC_KEY_BYTES
        or len(key) > MAX_VERIFICATION_HMAC_KEY_BYTES
    ):
        raise VocalLabAuthenticationError("verification_authentication_invalid")


def load_verification_hmac_key(path: Path) -> bytes:
    """Load the dedicated binary HMAC key without following or reopening it."""

    return _read_strict_owner_bytes(
        path,
        minimum_bytes=MIN_VERIFICATION_HMAC_KEY_BYTES,
        maximum_bytes=MAX_VERIFICATION_HMAC_KEY_BYTES,
        reason="verification_hmac_key_invalid",
    )


def initialize_verification_hmac_key(path: Path) -> None:
    """Create the dedicated key once with no shell or stdout key material."""

    if not hasattr(os, "O_NOFOLLOW"):
        raise VocalLabProbeError("verification_hmac_key_create_failed")
    path = path.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise VocalLabProbeError("verification_hmac_key_create_failed") from exc
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = -1
    created_identity: tuple[int, int] | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        before = os.fstat(descriptor)
        created_identity = (before.st_dev, before.st_ino)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_size != 0
        ):
            raise VocalLabProbeError("verification_hmac_key_create_failed")
        key_material = secrets.token_bytes(MIN_VERIFICATION_HMAC_KEY_BYTES)
        offset = 0
        while offset < len(key_material):
            written = os.write(descriptor, key_material[offset:])
            if written <= 0:
                raise VocalLabProbeError("verification_hmac_key_create_failed")
            offset += written
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino) != created_identity
            or not stat.S_ISREG(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o600
            or after.st_uid != os.geteuid()
            or after.st_nlink != 1
            or after.st_size != MIN_VERIFICATION_HMAC_KEY_BYTES
        ):
            raise VocalLabProbeError("verification_hmac_key_create_failed")
        current = path.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or (current.st_dev, current.st_ino) != created_identity
            or current.st_nlink != 1
        ):
            raise VocalLabProbeError("verification_hmac_key_create_failed")
    except (OSError, VocalLabProbeError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
            descriptor = -1
        if created_identity is not None:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == created_identity:
                    path.unlink()
            except OSError:
                pass
        if isinstance(exc, VocalLabProbeError):
            raise
        raise VocalLabProbeError("verification_hmac_key_create_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _provenance_message(
    unsigned_payload: Mapping[str, object],
    *,
    signed_contract_name: str,
) -> bytes:
    return (
        b"ea-vocallab-verification-provenance-v1\x00"
        + signed_contract_name.encode("ascii")
        + b"\x00"
        + _canonical_bytes(unsigned_payload)
    )


def sign_authenticated_payload(
    payload: Mapping[str, object],
    *,
    hmac_key: bytes,
    signed_contract_name: str,
) -> dict[str, object]:
    """Return a canonical-signable copy with a domain-separated HMAC envelope."""

    _validate_verification_hmac_key(hmac_key)
    unsigned_payload = dict(payload)
    unsigned_payload.pop(AUTHENTICATION_FIELD, None)
    if unsigned_payload.get("contract_name") != signed_contract_name:
        raise VocalLabAuthenticationError("verification_authentication_invalid")
    try:
        canonical = _canonical_bytes(unsigned_payload)
        message = _provenance_message(
            unsigned_payload,
            signed_contract_name=signed_contract_name,
        )
    except (TypeError, UnicodeError, ValueError):
        raise VocalLabAuthenticationError(
            "verification_authentication_invalid"
        ) from None
    authentication = {
        "contract_name": PROVENANCE_CONTRACT,
        "version": PROVENANCE_VERSION,
        "algorithm": PROVENANCE_ALGORITHM,
        "signed_contract_name": signed_contract_name,
        "key_id_sha256": hashlib.sha256(hmac_key).hexdigest(),
        "payload_sha256": hashlib.sha256(canonical).hexdigest(),
        "hmac_sha256": hmac.new(hmac_key, message, hashlib.sha256).hexdigest(),
    }
    return {**unsigned_payload, AUTHENTICATION_FIELD: authentication}


def require_authenticated_payload(
    payload: Mapping[str, object],
    *,
    hmac_key: bytes,
    signed_contract_name: str,
) -> None:
    """Authenticate before callers inspect any provider or promotion fields."""

    _validate_verification_hmac_key(hmac_key)
    authentication = payload.get(AUTHENTICATION_FIELD)
    if (
        not isinstance(authentication, Mapping)
        or set(authentication) != PROVENANCE_KEYS
    ):
        raise VocalLabAuthenticationError("verification_authentication_invalid")
    unsigned_payload = dict(payload)
    unsigned_payload.pop(AUTHENTICATION_FIELD, None)
    try:
        canonical = _canonical_bytes(unsigned_payload)
        message = _provenance_message(
            unsigned_payload,
            signed_contract_name=signed_contract_name,
        )
    except (TypeError, UnicodeError, ValueError):
        raise VocalLabAuthenticationError(
            "verification_authentication_invalid"
        ) from None
    expected = {
        "contract_name": PROVENANCE_CONTRACT,
        "version": PROVENANCE_VERSION,
        "algorithm": PROVENANCE_ALGORITHM,
        "signed_contract_name": signed_contract_name,
        "key_id_sha256": hashlib.sha256(hmac_key).hexdigest(),
        "payload_sha256": hashlib.sha256(canonical).hexdigest(),
        "hmac_sha256": hmac.new(hmac_key, message, hashlib.sha256).hexdigest(),
    }
    for key, value in expected.items():
        actual = authentication.get(key)
        if type(actual) is not type(value):
            raise VocalLabAuthenticationError(
                "verification_authentication_invalid"
            )
        if isinstance(value, str):
            if not hmac.compare_digest(actual, value):
                raise VocalLabAuthenticationError(
                    "verification_authentication_invalid"
                )
        elif actual != value:
            raise VocalLabAuthenticationError(
                "verification_authentication_invalid"
            )


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    target = path.expanduser().absolute()
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise VocalLabProbeError("output_parent_invalid") from exc
    target = _check_private_parent_components(
        target,
        reason="output_parent_invalid",
    )
    parent_fd = -1
    descriptor = -1
    temporary = f".{target.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        parent_fd = os.open(
            target.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            existing = os.stat(
                target.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.geteuid()
            or stat.S_IMODE(existing.st_mode) != 0o600
            or existing.st_nlink != 1
        ):
            raise VocalLabProbeError("output_path_not_regular")
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        encoded = _canonical_bytes(payload)
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise VocalLabProbeError("output_write_failed")
            offset += written
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_nlink != 1
        ):
            raise VocalLabProbeError("output_write_failed")
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary,
            target.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary = ""
        os.fsync(parent_fd)
        installed = os.stat(
            target.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(installed.st_mode)
            or installed.st_uid != os.geteuid()
            or stat.S_IMODE(installed.st_mode) != 0o600
            or installed.st_nlink != 1
        ):
            raise VocalLabProbeError("output_write_failed")
    except VocalLabProbeError:
        raise
    except OSError as exc:
        raise VocalLabProbeError("output_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary and parent_fd >= 0:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
        if parent_fd >= 0:
            os.close(parent_fd)


def _read_owner_secret(path: Path, *, reason: str) -> str:
    try:
        raw = _read_strict_owner_bytes(
            path,
            minimum_bytes=1,
            maximum_bytes=MAX_SECRET_BYTES,
            reason=reason,
        )
        value = raw.decode("utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise VocalLabProbeError(reason) from exc
    if not value or "\n" in value or "\r" in value:
        raise VocalLabProbeError(reason)
    return value


def _read_private_env_values(path: Path) -> dict[str, str]:
    try:
        raw = _read_strict_owner_bytes(
            path,
            minimum_bytes=1,
            maximum_bytes=MAX_ENV_BYTES,
            reason="env_file_invalid",
        )
    except VocalLabProbeError:
        try:
            path.lstat()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise VocalLabProbeError("env_file_invalid") from exc
        raise
    try:
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise VocalLabProbeError("env_file_invalid") from exc
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"VOCALLAB_API_KEY", "VOCALLAB_API_KEY_FILE"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _load_api_key(key_file: Path | None, *, env_file: Path) -> str:
    process_value = os.environ.get("VOCALLAB_API_KEY", "").strip()
    if key_file is not None:
        configured = key_file
        if not configured.is_absolute():
            configured = ROOT / configured
        file_value = _read_owner_secret(configured, reason="api_key_file_invalid")
        if process_value and not hmac.compare_digest(process_value, file_value):
            raise VocalLabProbeError("api_key_sources_disagree")
        value = file_value
    else:
        value = process_value
        private_env = _read_private_env_values(env_file) if not value else {}
        if not value:
            value = private_env.get("VOCALLAB_API_KEY", "").strip()
        if not value:
            raw_path = os.environ.get("VOCALLAB_API_KEY_FILE", "").strip()
            if not raw_path:
                raw_path = private_env.get("VOCALLAB_API_KEY_FILE", "").strip()
            configured = Path(raw_path) if raw_path else DEFAULT_KEY_FILE
            if not configured.is_absolute():
                configured = ROOT / configured
            value = _read_owner_secret(configured, reason="api_key_file_invalid")
    if not KEY_RE.fullmatch(value):
        raise VocalLabProbeError("api_key_invalid")
    return value


def _load_credential_rotation_authority(
    path: Path,
    *,
    replacement_credential_binding_sha256: str,
    exposed_credential_binding_sha256: str | None = None,
) -> None:
    try:
        raw = _read_strict_owner_bytes(
            path,
            minimum_bytes=1,
            maximum_bytes=MAX_CREDENTIAL_ROTATION_AUTHORITY_BYTES,
            reason="credential_rotation_authority_invalid",
        )
    except VocalLabProbeError:
        raise
    if b"vl_live_" in raw:
        raise VocalLabProbeError("credential_rotation_authority_secret_exposed")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise VocalLabProbeError("credential_rotation_authority_invalid") from None
    expected_keys = {
        "contract_name",
        "version",
        "status",
        "exposed_credential_binding_sha256",
        "replacement_credential_binding_sha256",
        "exposed_key_revoked",
        "rotation_id_sha256",
        "approved_by_sha256",
    }
    digest_pattern = re.compile(r"^[0-9a-f]{64}$")
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise VocalLabProbeError("credential_rotation_authority_invalid")
    exposed = payload.get("exposed_credential_binding_sha256")
    replacement = payload.get("replacement_credential_binding_sha256")
    if (
        payload.get("contract_name") != CREDENTIAL_ROTATION_AUTHORITY_CONTRACT
        or type(payload.get("version")) is not int
        or payload.get("version") != 1
        or payload.get("status") != "pass"
        or not isinstance(exposed, str)
        or not digest_pattern.fullmatch(exposed)
        or (
            exposed_credential_binding_sha256 is not None
            and (
                not digest_pattern.fullmatch(exposed_credential_binding_sha256)
                or not hmac.compare_digest(
                    exposed,
                    exposed_credential_binding_sha256,
                )
            )
        )
        or not isinstance(replacement, str)
        or not digest_pattern.fullmatch(replacement)
        or not isinstance(replacement_credential_binding_sha256, str)
        or not digest_pattern.fullmatch(replacement_credential_binding_sha256)
        or not hmac.compare_digest(
            replacement,
            replacement_credential_binding_sha256,
        )
        or hmac.compare_digest(exposed, replacement)
        or payload.get("exposed_key_revoked") is not True
        or not isinstance(payload.get("rotation_id_sha256"), str)
        or not digest_pattern.fullmatch(str(payload.get("rotation_id_sha256", "")))
        or not isinstance(payload.get("approved_by_sha256"), str)
        or not digest_pattern.fullmatch(str(payload.get("approved_by_sha256", "")))
    ):
        raise VocalLabProbeError("credential_rotation_authority_invalid")


def _validate_base_url(value: str) -> str:
    parsed = urllib_parse.urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.vocallab.ai"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise VocalLabProbeError("base_url_not_official")
    return OFFICIAL_BASE_URL


class RollingWindowRateLimiter:
    """One account-wide limiter shared by every inventory, POST, and poll call."""

    def __init__(
        self,
        *,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            type(requests_per_minute) is not int
            or requests_per_minute <= 0
            or requests_per_minute > DEFAULT_REQUESTS_PER_MINUTE
        ):
            raise VocalLabProbeError("request_rate_limit_invalid")
        self._limit = requests_per_minute
        self._monotonic = monotonic
        self._sleep = sleep
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        while True:
            current = self._monotonic()
            cutoff = current - RATE_LIMIT_WINDOW_SECONDS
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) < self._limit:
                self._timestamps.append(current)
                return
            wait_seconds = RATE_LIMIT_WINDOW_SECONDS - (
                current - self._timestamps[0]
            )
            self._sleep(max(wait_seconds, 0.001))


class VocalLabProbeClient:
    """Small no-redirect client whose exceptions never contain provider bodies."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: int,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = _validate_base_url(base_url)
        self._timeout_seconds = timeout_seconds
        self.requests_per_minute = requests_per_minute
        self._opener = urllib_request.build_opener(_NoRedirectHandler())
        self._rate_limiter = RollingWindowRateLimiter(
            requests_per_minute=requests_per_minute,
            monotonic=monotonic,
            sleep=sleep,
        )

    @property
    def credential_binding_sha256(self) -> str:
        """Private high-entropy binding; never expose the bearer credential."""

        return hashlib.sha256(self._api_key.encode("utf-8")).hexdigest()

    def request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> tuple[int, object]:
        if not path.startswith("/api/v1/"):
            raise VocalLabProbeError("provider_path_invalid")
        self._rate_limiter.acquire()
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "ea-vocallab-verification/1",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        provider_request = urllib_request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(
                provider_request,
                timeout=self._timeout_seconds,
            ) as response:
                status_code = int(response.status)
                content_type = str(response.headers.get("Content-Type", ""))
                raw = response.read(MAX_JSON_BYTES + 1)
        except VocalLabProbeError:
            raise
        except urllib_error.HTTPError as exc:
            raise VocalLabProbeError(f"provider_http_{int(exc.code)}") from None
        except (urllib_error.URLError, TimeoutError, OSError):
            raise VocalLabProbeError("provider_transport_failed") from None
        if status_code < 200 or status_code >= 300:
            raise VocalLabProbeError(f"provider_http_{status_code}")
        if len(raw) > MAX_JSON_BYTES:
            raise VocalLabProbeError("provider_json_oversized")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise VocalLabProbeError("provider_content_type_invalid")
        try:
            parsed = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError):
            raise VocalLabProbeError("provider_json_invalid") from None
        if not isinstance(parsed, dict):
            raise VocalLabProbeError("provider_json_shape_invalid")
        return status_code, parsed


def _endpoint(
    client: VocalLabProbeClient,
    path: str,
) -> tuple[dict[str, object], object | None, str | None]:
    try:
        status_code, payload = client.request_json("GET", path)
    except VocalLabProbeError as exc:
        return {"status": "blocked", "http_status": 0}, None, str(exc)
    return {"status": "pass", "http_status": status_code}, payload, None


def _validate_wav(audio: bytes, *, expected_sample_rate: int) -> None:
    if len(audio) <= 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise VocalLabProbeError("generation_audio_invalid")
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            frame_count = handle.getnframes()
            channel_count = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            if (
                frame_count <= 0
                or channel_count not in (1, 2)
                or sample_rate != expected_sample_rate
                or sample_width not in (1, 2, 3, 4)
                or handle.getcomptype() != "NONE"
                or frame_count / sample_rate < MINIMUM_SMOKE_WAV_DURATION_SECONDS
            ):
                raise VocalLabProbeError("generation_audio_invalid")
            frames = handle.readframes(frame_count)
            if (
                len(frames) != frame_count * channel_count * sample_width
                or not any(frames)
            ):
                raise VocalLabProbeError("generation_audio_invalid")
    except (EOFError, wave.Error):
        raise VocalLabProbeError("generation_audio_invalid") from None


def _decode_audio(value: object, *, max_audio_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise VocalLabProbeError("generation_audio_missing")
    encoded = value
    if value.startswith("data:"):
        prefix, separator, encoded = value.partition(",")
        if separator != "," or prefix.lower() not in (
            "data:audio/wav;base64",
            "data:audio/x-wav;base64",
        ):
            raise VocalLabProbeError("generation_data_url_invalid")
    if len(encoded) > ((max_audio_bytes + 2) // 3) * 4 + 4:
        raise VocalLabProbeError("generation_audio_oversized")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise VocalLabProbeError("generation_audio_invalid") from None
    if not audio or len(audio) > max_audio_bytes:
        raise VocalLabProbeError("generation_audio_oversized")
    return audio


def _perform_synthetic_smoke(
    client: VocalLabProbeClient,
    *,
    voice_id: str,
    poll_interval_seconds: int,
    poll_timeout_seconds: int,
    max_audio_bytes: int,
) -> dict[str, object]:
    payload = {
        "text": SYNTHETIC_TEXT,
        "voice": voice_id,
        "model": "v-pro",
        "speed": 1.0,
        "temperature": 0.7,
        "format": "WAV",
        "sample_rate": 44100,
    }
    _, response = client.request_json("POST", "/api/v1/tts", payload)
    try:
        generation = parse_generation(response, expected_model="v-pro")
    except VocalLabSchemaError:
        raise VocalLabProbeError("generation_response_invalid") from None
    generation_id = generation.generation_id

    deadline = time.monotonic() + poll_timeout_seconds
    while not generation.audio_base64:
        if generation.status not in VOCALLAB_GENERATION_PENDING:
            if generation.status not in VOCALLAB_GENERATION_SUCCESS:
                raise VocalLabProbeError("generation_failed_known")
            raise VocalLabProbeError("generation_audio_missing")
        if time.monotonic() >= deadline:
            raise VocalLabProbeError("generation_poll_timeout")
        time.sleep(poll_interval_seconds)
        quoted = urllib_parse.quote(generation_id, safe="")
        _, response = client.request_json("GET", f"/api/v1/tts/{quoted}")
        try:
            generation = parse_generation(
                response,
                expected_model="v-pro",
                expected_generation_id=generation_id,
            )
        except VocalLabSchemaError:
            raise VocalLabProbeError("generation_response_invalid") from None

    if generation.status not in (
        VOCALLAB_GENERATION_PENDING | VOCALLAB_GENERATION_SUCCESS
    ):
        if generation.status not in VOCALLAB_GENERATION_SUCCESS:
            raise VocalLabProbeError("generation_failed_known")
        raise VocalLabProbeError("generation_status_invalid")
    audio = _decode_audio(
        generation.audio_base64,
        max_audio_bytes=max_audio_bytes,
    )
    _validate_wav(audio, expected_sample_rate=44100)
    points_used = generation.points_used
    if type(points_used) is not int or points_used != SYNTHETIC_TEXT_POINTS:
        raise VocalLabProbeError("generation_points_invalid")
    return {
        "requested": True,
        "status": "pass",
        "source_text_sha256": SYNTHETIC_TEXT_SHA256,
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "content_type": "audio/wav",
        "sample_rate": 44100,
        "points_used": points_used,
        "generation_id_sha256": hashlib.sha256(
            generation_id.encode("utf-8")
        ).hexdigest(),
        "charge_state": "charged",
    }


def probe_provider(
    client: VocalLabProbeClient,
    *,
    hmac_key: bytes,
    allow_synthetic_tts: bool = False,
    voice_id: str = "",
    minimum_remaining_points: int = DEFAULT_MINIMUM_REMAINING_POINTS,
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    poll_timeout_seconds: int = DEFAULT_POLL_TIMEOUT_SECONDS,
    max_audio_bytes: int = DEFAULT_MAX_AUDIO_BYTES,
    credential_rotation_required: bool = True,
    credential_production_eligible: bool = False,
    credential_rotation_evidence_verified: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    if (
        type(minimum_remaining_points) is not int
        or minimum_remaining_points < MINIMUM_REQUIRED_REMAINING_POINTS
    ):
        raise VocalLabProbeError("minimum_remaining_points_below_policy")
    if (
        type(requests_per_minute) is not int
        or requests_per_minute <= 0
        or requests_per_minute > DEFAULT_REQUESTS_PER_MINUTE
    ):
        raise VocalLabProbeError("request_rate_limit_invalid")
    if getattr(client, "requests_per_minute", None) != requests_per_minute:
        raise VocalLabProbeError("request_rate_limit_mismatch")
    if (
        type(credential_rotation_required) is not bool
        or type(credential_production_eligible) is not bool
        or type(credential_rotation_evidence_verified) is not bool
        or credential_rotation_required == credential_production_eligible
        or credential_production_eligible
        != credential_rotation_evidence_verified
    ):
        raise VocalLabProbeError("credential_posture_invalid")
    credential_binding_sha256 = getattr(
        client, "credential_binding_sha256", ""
    )
    if (
        not isinstance(credential_binding_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", credential_binding_sha256)
    ):
        raise VocalLabProbeError("credential_binding_invalid")
    if allow_synthetic_tts:
        # The inventory lane has no durable, account-global charge coordinator.
        # Keep spending impossible until the probe can persist pre-POST state,
        # recover a known generation by GET only, and reconcile post balance.
        raise VocalLabProbeError("synthetic_tts_spending_lane_disabled")
    blockers: list[str] = []
    if credential_rotation_required:
        blockers.append("credential:rotation_required")
    if not credential_production_eligible:
        blockers.append("credential:production_ineligible")
    endpoint_payloads: dict[str, object | None] = {}
    endpoint_projections: dict[str, dict[str, object]] = {}
    for name, path in (
        ("ping", "/api/v1/ping"),
        ("account", "/api/v1/me"),
        ("models", "/api/v1/models"),
        ("voices", "/api/v1/voices"),
    ):
        projection, payload, failure = _endpoint(client, path)
        endpoint_projections[name] = projection
        endpoint_payloads[name] = payload
        if failure:
            blockers.append(f"{name}:{failure}")

    def mark_invalid_provider_response(name: str) -> None:
        endpoint_projections[name] = {
            **endpoint_projections[name],
            "status": "blocked",
        }
        blockers.append(f"{name}:invalid_provider_response")

    ping_observation: PingObservation | None = None
    account_observation: AccountObservation | None = None
    model_observations: tuple[ModelObservation, ...] = ()
    voice_observations: tuple[VoiceObservation, ...] = ()
    if endpoint_payloads["ping"] is not None:
        try:
            ping_observation = parse_ping(endpoint_payloads["ping"])
        except VocalLabSchemaError:
            mark_invalid_provider_response("ping")
    if endpoint_payloads["account"] is not None:
        try:
            account_observation = parse_account(endpoint_payloads["account"])
        except VocalLabSchemaError:
            mark_invalid_provider_response("account")
    if endpoint_payloads["models"] is not None:
        try:
            model_observations = parse_models(endpoint_payloads["models"])
        except VocalLabSchemaError:
            mark_invalid_provider_response("models")
    if endpoint_payloads["voices"] is not None:
        try:
            voice_observations = parse_voices(endpoint_payloads["voices"])
        except VocalLabSchemaError:
            mark_invalid_provider_response("voices")

    is_pro = account_observation is not None
    is_studio = account_observation is not None
    points = account_observation.points if account_observation is not None else None
    balance_consistent = (
        ping_observation is not None
        and account_observation is not None
        and ping_observation.points == account_observation.points
    )
    if (
        ping_observation is not None
        and account_observation is not None
        and not balance_consistent
    ):
        endpoint_projections["account"] = {
            **endpoint_projections["account"],
            "status": "blocked",
        }
        blockers.append("account:balance_inconsistent")
    balance_sufficient = (
        balance_consistent
        and points is not None
        and points >= minimum_remaining_points + SYNTHETIC_TEXT_POINTS
    )

    discovered_model_keys = {model.key for model in model_observations}
    models = [
        model for model in SUPPORTED_MODELS if model in discovered_model_keys
    ]
    model_count = len(model_observations)

    private_voice_ids = frozenset(
        voice.provider_voice_id for voice in voice_observations
    )
    discovered_voice_hashes = tuple(
        sorted(
            hashlib.sha256(voice_id.encode("utf-8")).hexdigest()
            for voice_id in private_voice_ids
        )
    )
    voice_count = len(voice_observations)
    if voice_count <= 0:
        blockers.append("voices:empty")

    smoke: dict[str, object] = {
        "requested": allow_synthetic_tts,
        "status": "not_run",
        "source_text_sha256": SYNTHETIC_TEXT_SHA256,
        "audio_sha256": "",
        "content_type": "",
        "sample_rate": 0,
        "points_used": 0,
        "generation_id_sha256": "",
        "charge_state": "not_charged",
    }
    post_count = 0
    if not allow_synthetic_tts:
        blockers.append("smoke:explicit_spend_not_authorized")
    elif not balance_sufficient:
        blockers.append("smoke:balance_reserve_unverified")
    elif voice_count <= 0:
        blockers.append("smoke:no_discovered_voice")
    elif not voice_id or voice_id not in private_voice_ids:
        blockers.append("smoke:voice_not_in_discovery_inventory")
    else:
        post_count = 1
        try:
            smoke = _perform_synthetic_smoke(
                client,
                voice_id=voice_id,
                poll_interval_seconds=poll_interval_seconds,
                poll_timeout_seconds=poll_timeout_seconds,
                max_audio_bytes=max_audio_bytes,
            )
        except VocalLabProbeError as exc:
            smoke["status"] = "blocked"
            smoke["charge_state"] = "unknown"
            blockers.append(f"smoke:{exc}")

    blockers = sorted(set(blockers))
    unsigned_receipt = {
        "contract_name": PROBE_CONTRACT,
        "version": PROBE_VERSION,
        "status": "pass" if not blockers else "blocked",
        "generated_at": _utc_text(generated_at),
        "provider": "vocallab",
        "api_contract_version": API_CONTRACT_VERSION,
        "credential_binding_sha256": credential_binding_sha256,
        "credential_rotation_required": credential_rotation_required,
        "credential_production_eligible": credential_production_eligible,
        "api_key_present": True,
        "api_key_exposed": False,
        "request_policy": {
            "default_spend_authorized": False,
            "synthetic_tts_requested": allow_synthetic_tts,
            "post_count": post_count,
            "post_retry_count": 0,
            "minimum_remaining_points": minimum_remaining_points,
            "requests_per_minute": requests_per_minute,
        },
        "ping": endpoint_projections["ping"],
        "account": {
            **endpoint_projections["account"],
            "is_pro": is_pro,
            "is_studio": is_studio,
            "balance_reported": points is not None,
            "balance_sufficient_for_smoke": balance_sufficient,
        },
        "models": {
            **endpoint_projections["models"],
            "keys": models,
            "model_count": model_count,
        },
        "voices": {
            **endpoint_projections["voices"],
            "voice_count": voice_count,
            "discovered_voice_hashes": list(discovered_voice_hashes),
            "raw_voice_ids_exposed": False,
        },
        "smoke": smoke,
        "blockers": blockers,
        "secrets_exposed": False,
        "manuscript_text_exposed": False,
        "raw_response_bodies_exposed": False,
    }
    return sign_authenticated_payload(
        unsigned_receipt,
        hmac_key=hmac_key,
        signed_contract_name=PROBE_CONTRACT,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _minimum_reserve(value: str) -> int:
    parsed = int(value)
    if parsed < MINIMUM_REQUIRED_REMAINING_POINTS:
        raise argparse.ArgumentTypeError(
            f"value must be at least {MINIMUM_REQUIRED_REMAINING_POINTS}"
        )
    return parsed


def _requests_per_minute(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed > DEFAULT_REQUESTS_PER_MINUTE:
        raise argparse.ArgumentTypeError(
            f"value must be between 1 and {DEFAULT_REQUESTS_PER_MINUTE}"
        )
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EA_AUDIOBOOK_VOCALLAB_BASE_URL", OFFICIAL_BASE_URL),
    )
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--credential-rotation-authority-file", type=Path)
    parser.add_argument(
        "--verification-hmac-key-file",
        type=Path,
        default=DEFAULT_VERIFICATION_HMAC_KEY_FILE,
    )
    parser.add_argument(
        "--initialize-verification-hmac-key",
        action="store_true",
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--allow-synthetic-tts", action="store_true")
    parser.add_argument("--voice-id-file", type=Path)
    parser.add_argument(
        "--timeout-seconds",
        type=_positive_int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=_positive_int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=_positive_int,
        default=DEFAULT_POLL_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--max-audio-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_AUDIO_BYTES,
    )
    parser.add_argument(
        "--minimum-remaining-points",
        type=_minimum_reserve,
        default=DEFAULT_MINIMUM_REMAINING_POINTS,
    )
    parser.add_argument(
        "--requests-per-minute",
        type=_requests_per_minute,
        default=DEFAULT_REQUESTS_PER_MINUTE,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.initialize_verification_hmac_key:
        try:
            if args.allow_synthetic_tts or args.voice_id_file is not None:
                raise VocalLabProbeError(
                    "verification_hmac_key_initialize_mode_invalid"
                )
            initialize_verification_hmac_key(args.verification_hmac_key_file)
        except VocalLabProbeError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
            return 2
        print(
            json.dumps(
                {
                    "ok": True,
                    "created": True,
                    "key_file": str(args.verification_hmac_key_file),
                },
                sort_keys=True,
            )
        )
        return 0
    try:
        verification_hmac_key = load_verification_hmac_key(
            args.verification_hmac_key_file
        )
        if args.allow_synthetic_tts:
            raise VocalLabProbeError("synthetic_tts_spending_lane_disabled")
        if args.allow_synthetic_tts != (args.voice_id_file is not None):
            raise VocalLabProbeError("synthetic_tts_requires_voice_id_file")
        voice_id = ""
        if args.voice_id_file is not None:
            voice_id = _read_owner_secret(
                args.voice_id_file,
                reason="voice_id_file_invalid",
            )
            if not PRIVATE_ID_RE.fullmatch(voice_id):
                raise VocalLabProbeError("voice_id_file_invalid")
        api_key = _load_api_key(args.key_file, env_file=args.env_file)
        client = VocalLabProbeClient(
            api_key=api_key,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            requests_per_minute=args.requests_per_minute,
        )
        rotation_evidence_verified = False
        if args.credential_rotation_authority_file is not None:
            if args.key_file is None:
                raise VocalLabProbeError("credential_rotation_authority_invalid")
            # The protected rotation authority retains the content-free binding
            # for the revoked credential. Requiring the revoked bearer secret
            # itself would make safe secret destruction impossible.
            _load_credential_rotation_authority(
                args.credential_rotation_authority_file,
                replacement_credential_binding_sha256=(
                    client.credential_binding_sha256
                ),
            )
            rotation_evidence_verified = True
        receipt = probe_provider(
            client,
            hmac_key=verification_hmac_key,
            allow_synthetic_tts=args.allow_synthetic_tts,
            voice_id=voice_id,
            minimum_remaining_points=args.minimum_remaining_points,
            requests_per_minute=args.requests_per_minute,
            poll_interval_seconds=args.poll_interval_seconds,
            poll_timeout_seconds=args.poll_timeout_seconds,
            max_audio_bytes=args.max_audio_bytes,
            credential_rotation_required=not rotation_evidence_verified,
            credential_production_eligible=rotation_evidence_verified,
            credential_rotation_evidence_verified=rotation_evidence_verified,
        )
        _write_private_json(args.output, receipt)
    except (VocalLabProbeError, VocalLabAuthenticationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "status": receipt["status"],
                "output": str(args.output),
                "blockers": receipt["blockers"],
                "synthetic_tts_requested": args.allow_synthetic_tts,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
