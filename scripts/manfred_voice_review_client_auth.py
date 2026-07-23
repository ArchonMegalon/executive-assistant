#!/usr/bin/env python3
"""Secure client-side handling for the short-lived Manfred review session."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


REVIEW_COOKIE_NAME = "ea_manfred_voice_review"
REVIEW_CONTRACT = "ea.manfred_voice_review.v1"
REVIEW_PURPOSE = "manfred_voice_review"
REVIEW_SLUG = "manfred"
REVIEW_REQUIRED_SCOPES = frozenset({"page", "warmup", "readiness", "realtime"})
REVIEW_ALLOWED_PUBLIC_ORIGINS = frozenset({"https://myexternalbrain.com"})
REVIEW_HTTP_USER_AGENT = "EA-Memorial-Review-Client/1.0"
MAX_TOKEN_BYTES = 4096
MIN_REMAINING_LIFETIME_SECONDS = 180
MAX_REMAINING_LIFETIME_SECONDS = 1800
MAX_COOKIE_FILE_AGE_SECONDS = 900
MAX_COOKIE_FILE_FUTURE_SKEW_SECONDS = 60
MAX_PRIVATE_RECEIPT_BYTES = 8 * 1024 * 1024
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SOURCE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ReviewSessionError(RuntimeError):
    """Raised without echoing review-session bearer material."""


def _https_origin(value: object, *, origin_only: bool) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise ReviewSessionError("review_session_origin_invalid") from exc
    hostname = str(parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or (
            origin_only
            and (
                parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            )
        )
    ):
        raise ReviewSessionError("review_session_origin_invalid")
    authority = hostname
    if ":" in hostname:
        authority = f"[{hostname}]"
    if port is not None and port != 443:
        authority = f"{authority}:{port}"
    return f"https://{authority}"


def normalized_https_origin(value: object) -> str:
    return _https_origin(value, origin_only=True)


def _https_url_origin(value: object) -> str:
    return _https_origin(value, origin_only=False)


def _open_parent_directory_nofollow(path: Path) -> tuple[int, str]:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ReviewSessionError("review_session_cookie_path_invalid")
    normalized = Path(os.path.normpath(os.fspath(path)))
    if normalized != path:
        raise ReviewSessionError("review_session_cookie_path_invalid")
    components = normalized.parts
    directory_fd = -1
    try:
        directory_fd = os.open(
            "/",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        for component in components[1:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        parent_stat = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ReviewSessionError("review_session_cookie_parent_unsafe")
        return directory_fd, components[-1]
    except OSError as exc:
        if directory_fd >= 0:
            os.close(directory_fd)
        raise ReviewSessionError(
            "review_session_cookie_path_unavailable"
        ) from exc
    except Exception:
        if directory_fd >= 0:
            os.close(directory_fd)
        raise


def _read_private_token(path: Path) -> str:
    directory_fd, filename = _open_parent_directory_nofollow(path)
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_TOKEN_BYTES + 1
        ):
            raise ReviewSessionError("review_session_cookie_file_unsafe")
        age_seconds = (
            time.time_ns() - int(before.st_mtime_ns)
        ) / 1_000_000_000.0
        if (
            age_seconds < -MAX_COOKIE_FILE_FUTURE_SKEW_SECONDS
            or age_seconds > MAX_COOKIE_FILE_AGE_SECONDS
        ):
            raise ReviewSessionError("review_session_cookie_file_stale")
        payload = bytearray()
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise ReviewSessionError("review_session_cookie_short_read")
            payload.extend(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ReviewSessionError("review_session_cookie_changed_during_read")
        after = os.fstat(descriptor)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or after.st_nlink != 1
            or stat.S_IMODE(after.st_mode) != 0o600
        ):
            raise ReviewSessionError("review_session_cookie_changed_during_read")
    except OSError as exc:
        raise ReviewSessionError("review_session_cookie_file_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_fd)
    raw = bytes(payload)
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    try:
        token = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReviewSessionError("review_session_cookie_token_invalid") from exc
    if (
        not token
        or len(token.encode("ascii")) > MAX_TOKEN_BYTES
        or _TOKEN_PATTERN.fullmatch(token) is None
    ):
        raise ReviewSessionError("review_session_cookie_token_invalid")
    return token


def _decode_base64url_segment(encoded: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(encoded + ("=" * (-len(encoded) % 4)))
    except Exception as exc:
        raise ReviewSessionError("review_session_cookie_token_invalid") from exc
    if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != encoded:
        raise ReviewSessionError("review_session_cookie_token_invalid")
    return raw


def _validate_token_envelope(token: object) -> tuple[str, str]:
    if (
        not isinstance(token, str)
        or not token
        or len(token.encode("utf-8")) > MAX_TOKEN_BYTES
        or _TOKEN_PATTERN.fullmatch(token) is None
    ):
        raise ReviewSessionError("review_session_cookie_token_invalid")
    encoded_claims, encoded_signature = token.split(".", 1)
    _decode_base64url_segment(encoded_claims)
    signature = _decode_base64url_segment(encoded_signature)
    if not signature:
        raise ReviewSessionError("review_session_cookie_token_invalid")
    return encoded_claims, encoded_signature


def _decode_claims(token: str) -> dict[str, object]:
    encoded, _encoded_signature = _validate_token_envelope(token)
    raw = _decode_base64url_segment(encoded)

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    try:
        claims = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("nonfinite_json_value")
            ),
        )
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise ReviewSessionError("review_session_cookie_claims_invalid") from exc
    if not isinstance(claims, dict):
        raise ReviewSessionError("review_session_cookie_claims_invalid")
    return claims


@dataclass(frozen=True)
class ReviewSessionClientAuth:
    origin: str
    slug: str
    source_revision: str
    image_id: str
    voice_identity_sha256: str
    expires_at: int
    _token: str = field(repr=False)

    def request_headers(self) -> dict[str, str]:
        return {
            "Cookie": f"{REVIEW_COOKIE_NAME}={self._token}",
            "Origin": self.origin,
        }

    def playwright_cookie(self) -> dict[str, object]:
        return {
            "name": REVIEW_COOKIE_NAME,
            "value": self._token,
            "url": f"{self.origin}/memorials/{self.slug}/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Strict",
        }

    def public_binding(self) -> dict[str, object]:
        return {
            "contract_name": REVIEW_CONTRACT,
            "access_mode": "private_review_session",
            "source_revision": self.source_revision,
            "image_id": self.image_id,
            "voice_identity_sha256": self.voice_identity_sha256,
            "expires_at_epoch": self.expires_at,
            "bearer_material_exposed": False,
        }


class _SameOriginReviewRedirectHandler(HTTPRedirectHandler):
    def __init__(self, expected_origin: str) -> None:
        super().__init__()
        origin = normalized_https_origin(expected_origin)
        if origin not in REVIEW_ALLOWED_PUBLIC_ORIGINS:
            raise ReviewSessionError("review_session_request_origin_invalid")
        self._expected_origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirect_url = urljoin(req.full_url, str(newurl or ""))
        try:
            redirect_origin = _https_url_origin(redirect_url)
        except ReviewSessionError as exc:
            raise URLError("review_session_cross_origin_redirect") from exc
        if redirect_origin != self._expected_origin:
            raise URLError("review_session_cross_origin_redirect")
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            redirect_url,
        )


def open_review_request(
    request: Request,
    *,
    expected_origin: str,
    timeout: float,
):
    origin = normalized_https_origin(expected_origin)
    if (
        origin not in REVIEW_ALLOWED_PUBLIC_ORIGINS
        or _https_url_origin(request.full_url) != origin
    ):
        raise ReviewSessionError("review_session_request_origin_invalid")
    request.add_header("User-Agent", REVIEW_HTTP_USER_AGENT)
    opener = build_opener(_SameOriginReviewRedirectHandler(origin))
    response = opener.open(request, timeout=timeout)
    try:
        if _https_url_origin(str(response.geturl() or "")) != origin:
            raise ReviewSessionError("review_session_response_origin_invalid")
    except Exception:
        response.close()
        raise
    return response


def parse_review_session_token(
    token: str,
    *,
    public_origin: str,
    slug: str,
    expected_source_revision: str = "",
    now: int | None = None,
) -> ReviewSessionClientAuth:
    origin = normalized_https_origin(public_origin)
    safe_slug = str(slug or "").strip()
    claims = _decode_claims(token)
    current_time = int(time.time()) if now is None else int(now)
    scopes = claims.get("scopes")
    expires_at = claims.get("expires_at")
    source_revision = str(claims.get("source_revision") or "")
    image_id = str(claims.get("image_id") or "")
    voice_identity_sha256 = str(claims.get("voice_identity_sha256") or "")
    if (
        origin not in REVIEW_ALLOWED_PUBLIC_ORIGINS
        or claims.get("contract_name") != REVIEW_CONTRACT
        or claims.get("purpose") != REVIEW_PURPOSE
        or claims.get("kind") != "session"
        or claims.get("slug") != REVIEW_SLUG
        or safe_slug != REVIEW_SLUG
        or claims.get("public_origin") != origin
        or not isinstance(scopes, list)
        or not REVIEW_REQUIRED_SCOPES.issubset(
            {str(scope) for scope in scopes if isinstance(scope, str)}
        )
        or type(expires_at) is not int
        or expires_at - current_time < MIN_REMAINING_LIFETIME_SECONDS
        or expires_at - current_time > MAX_REMAINING_LIFETIME_SECONDS
        or _SOURCE_REVISION_PATTERN.fullmatch(source_revision) is None
        or (
            expected_source_revision
            and source_revision != expected_source_revision
        )
        or _IMAGE_ID_PATTERN.fullmatch(image_id) is None
        or _SHA256_PATTERN.fullmatch(voice_identity_sha256) is None
    ):
        raise ReviewSessionError("review_session_cookie_binding_invalid")
    return ReviewSessionClientAuth(
        origin=origin,
        slug=safe_slug,
        source_revision=source_revision,
        image_id=image_id,
        voice_identity_sha256=voice_identity_sha256,
        expires_at=expires_at,
        _token=token,
    )


def load_review_session_auth(
    path: str | Path,
    *,
    public_origin: str,
    slug: str,
    expected_source_revision: str = "",
) -> ReviewSessionClientAuth:
    token = _read_private_token(Path(path))
    return parse_review_session_token(
        token,
        public_origin=public_origin,
        slug=slug,
        expected_source_revision=expected_source_revision,
    )


def write_private_review_session_token(path: str | Path, token: str) -> None:
    _validate_token_envelope(token)
    payload = token.encode("ascii") + b"\n"
    target = Path(path)
    directory_fd, filename = _open_parent_directory_nofollow(target)
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short_write")
            written += count
        os.fsync(descriptor)
        result = os.fstat(descriptor)
        if (
            not stat.S_ISREG(result.st_mode)
            or result.st_uid != os.geteuid()
            or result.st_nlink != 1
            or stat.S_IMODE(result.st_mode) != 0o600
            or result.st_size != len(payload)
        ):
            raise ReviewSessionError("review_session_cookie_output_unsafe")
        os.fsync(directory_fd)
    except FileExistsError as exc:
        raise ReviewSessionError("review_session_cookie_output_exists") from exc
    except OSError as exc:
        raise ReviewSessionError("review_session_cookie_output_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_fd)


def write_private_review_receipt_text(path: str | Path, rendered: str) -> None:
    try:
        payload = str(rendered).encode("utf-8") + b"\n"
    except UnicodeError as exc:
        raise ReviewSessionError("private_review_receipt_invalid") from exc
    if not 1 < len(payload) <= MAX_PRIVATE_RECEIPT_BYTES:
        raise ReviewSessionError("private_review_receipt_invalid")
    target = Path(path)
    directory_fd, filename = _open_parent_directory_nofollow(target)
    temporary_name = f".{filename}.tmp.{os.getpid()}.{os.urandom(12).hex()}"
    descriptor = -1
    temporary_created = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        temporary_created = True
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short_write")
            written += count
        os.fsync(descriptor)
        completed = os.fstat(descriptor)
        temporary = os.stat(
            temporary_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(completed.st_mode)
            or completed.st_uid != os.geteuid()
            or completed.st_nlink != 1
            or stat.S_IMODE(completed.st_mode) != 0o600
            or completed.st_size != len(payload)
            or (completed.st_dev, completed.st_ino)
            != (temporary.st_dev, temporary.st_ino)
        ):
            raise ReviewSessionError("private_review_receipt_output_unsafe")
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_created = False
        published = os.stat(
            filename,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_uid != os.geteuid()
            or published.st_nlink != 1
            or stat.S_IMODE(published.st_mode) != 0o600
            or published.st_size != len(payload)
            or (published.st_dev, published.st_ino)
            != (completed.st_dev, completed.st_ino)
        ):
            raise ReviewSessionError("private_review_receipt_output_unsafe")
        os.fsync(directory_fd)
    except ReviewSessionError:
        raise
    except OSError as exc:
        raise ReviewSessionError("private_review_receipt_output_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)
