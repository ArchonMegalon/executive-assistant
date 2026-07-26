#!/usr/bin/env python3
"""Capture an existing Blip Supabase session without exposing its credentials.

This is an operator-only, fail-closed bridge.  It is deliberately not a login
or account-recovery tool.  The caller must first confirm that the named
BrowserAct session belongs to the current operator and that any remote-assist
lockdown has ended.

The browser receives only an ephemeral RSA public key and public binding
context.  It reads one exact localStorage key and returns an AES-GCM ciphertext
whose one-time key is wrapped with RSA-OAEP.  Access and refresh credentials
are decrypted only in this process, are never placed in argv or an environment,
and reach the immutable runtime image only over stdin.

Even after a successful capture, this helper deliberately emits a nonfinal
``capture_complete`` receipt.  It cannot independently prove that no other
browser process retained the rotated token family; a separate governed
ownership gate is required before flagship evidence may treat the state as
exclusively transferred.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import resource
import secrets
import selectors
import signal
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SCHEMA = "ea.blipai.browseract-session-capture.v1"
CAPTURE_PAYLOAD_SCHEMA = "ea.blipai.supabase-session-envelope.v1"
CAPTURE_ALGORITHM = "RSA-OAEP-256+A256GCM"
CAPTURE_SENTINEL = "EA_BLIP_CAPTURE_ENVELOPE_V1:"
QUIESCENCE_CAS_SENTINEL = "EA_BLIP_CAPTURE_CAS_QUIESCED_V1:"
QUIESCENCE_SENTINEL = "EA_BLIP_CAPTURE_QUIESCED_V1:"
DOCKER_OK_SENTINEL = b"EA_BLIP_TOKEN_STATE_OK\n"

EXPECTED_ORIGIN = "https://www.blipai.app"
EXPECTED_ISSUER = "https://hqwmccawtepvundsgnil.supabase.co"
EXPECTED_STORAGE_KEY = "sb-hqwmccawtepvundsgnil-auth-token"
REFRESH_URL = (
    "https://hqwmccawtepvundsgnil.supabase.co"
    "/auth/v1/token?grant_type=refresh_token"
)
USER_URL = "https://hqwmccawtepvundsgnil.supabase.co/auth/v1/user"
DEFAULT_IMAGE_ID = (
    "sha256:7bf43b116c83a1dce1ab09ae64db62331861e7b936965074a897bf2499936796"
)
DEFAULT_STATE_DIR = Path(
    "/home/tibor/.local/share/ea-deploy/"
    "manfred-voice-blip-faf141a5-20260726t153127z/"
    "candidate-predeploy-20260726t1620z-p4/runtime/state"
)
FINAL_STATE_NAME = "memorial_blipai_shadow_stt_tokens.json"
CONTAINER_STATE_DIR = "/run/ea-memorial-state"

EXPECTED_RUNTIME_UID = 10001
EXPECTED_RUNTIME_GID = 10001
TOKEN_MAX_CHARS = 16_384
STORAGE_VALUE_MAX_CHARS = 48_000
BROWSER_STDOUT_MAX_BYTES = 64_000
BROWSER_STDERR_MAX_BYTES = 8_192
DOCKER_STDOUT_MAX_BYTES = 1_024
DOCKER_STDERR_MAX_BYTES = 4_096
REFRESH_RESPONSE_MAX_BYTES = 64_000
API_KEY_MAX_BYTES = 8_192
MIN_FRESH_SECONDS = 60
MAX_ACCESS_LIFETIME_SECONDS = 24 * 60 * 60
PROCESS_TIMEOUT_SECONDS = 60
CANONICAL_BROWSER_ACT_BIN = (
    "/home/tibor/.local/share/uv/tools/browser-act-cli/bin/browser-act"
)
CANONICAL_DOCKER_BIN = "/usr/bin/docker"

_SESSION_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_IMAGE_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_INVOCATION_NONCE_RE = re.compile(r"\A[A-Za-z0-9_-]{43}\Z")
_ENVELOPE_RE = re.compile(
    rb"\AEA_BLIP_CAPTURE_ENVELOPE_V1:([A-Za-z0-9_-]{100,63900})\n?\Z"
)
_SAFE_FILENAME_RE = re.compile(r"\A\.?[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")


class CaptureFailure(RuntimeError):
    """A constant, receipt-safe operator failure."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        self.evidence: dict[str, object] = {}
        super().__init__(self.code)


@dataclass(frozen=True, repr=False)
class SessionClaims:
    subject: str
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, repr=False)
class RefreshedMaterial:
    access_token: str
    refresh_token: str
    subject: str
    email: str


@dataclass(frozen=True, repr=False)
class AuthenticatedUser:
    subject: str
    email: str


@dataclass(frozen=True)
class CaptureConfig:
    session: str
    expected_email: str
    image_id: str
    state_dir: Path
    receipt_path: Path
    invocation_nonce: str
    supabase_api_key_file: Path | None
    operator_confirmed: bool
    dedicated_session_confirmed: bool


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: object, *, maximum: int, error: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2:
        raise CaptureFailure(error)
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
        raise CaptureFailure(error)
    try:
        decoded = base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
    except (ValueError, TypeError) as exc:
        raise CaptureFailure(error) from exc
    if (
        not decoded
        or len(decoded) > maximum
        or not hmac.compare_digest(_b64url_encode(decoded), value)
    ):
        raise CaptureFailure(error)
    return decoded


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _valid_token_text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > TOKEN_MAX_CHARS:
        raise CaptureFailure("captured_session_invalid")
    if any(ord(character) < 33 or ord(character) == 127 for character in value):
        raise CaptureFailure("captured_session_invalid")
    return value


def _decode_jwt_claims(
    token: str,
    *,
    expected_email: str,
    expected_subject: str | None = None,
    require_fresh: bool,
    now: int | None = None,
) -> SessionClaims:
    safe_token = _valid_token_text(token)
    parts = safe_token.split(".")
    if len(parts) != 3 or not all(parts):
        raise CaptureFailure("captured_token_claims_invalid")
    try:
        header = json.loads(
            _b64url_decode(
                parts[0],
                maximum=4_096,
                error="captured_token_claims_invalid",
            ).decode("utf-8")
        )
        claims = json.loads(
            _b64url_decode(
                parts[1],
                maximum=16_384,
                error="captured_token_claims_invalid",
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("captured_token_claims_invalid") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise CaptureFailure("captured_token_claims_invalid")
    if str(header.get("alg") or "") not in {"HS256", "RS256", "ES256"}:
        raise CaptureFailure("captured_token_claims_invalid")

    issuer = claims.get("iss")
    audience = claims.get("aud")
    role = claims.get("role")
    email = claims.get("email")
    subject = claims.get("sub")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if (
        issuer != EXPECTED_ISSUER
        or audience != "authenticated"
        or role != "authenticated"
        or not isinstance(email, str)
        or not hmac.compare_digest(email.casefold(), expected_email.casefold())
        or not isinstance(subject, str)
        or not subject
        or len(subject) > 256
        or any(ord(character) < 33 or ord(character) == 127 for character in subject)
        or not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
    ):
        raise CaptureFailure("captured_token_claims_invalid")
    if expected_subject is not None and not hmac.compare_digest(subject, expected_subject):
        raise CaptureFailure("refreshed_token_claims_invalid")

    current = int(time.time()) if now is None else int(now)
    lifetime = expires_at - issued_at
    if (
        lifetime < MIN_FRESH_SECONDS
        or lifetime > MAX_ACCESS_LIFETIME_SECONDS
        or issued_at > current + MIN_FRESH_SECONDS
    ):
        raise CaptureFailure("captured_token_claims_invalid")
    not_before = claims.get("nbf")
    if (
        not_before is not None
        and (
            not isinstance(not_before, int)
            or isinstance(not_before, bool)
            or not_before > current + MIN_FRESH_SECONDS
        )
    ):
        raise CaptureFailure("captured_token_claims_invalid")
    if require_fresh and expires_at < current + MIN_FRESH_SECONDS:
        raise CaptureFailure("captured_access_token_stale")
    return SessionClaims(
        subject=subject,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _capture_aad(*, challenge: str, session: str) -> bytes:
    return _canonical_json_bytes(
        {
            "alg": CAPTURE_ALGORITHM,
            "challenge": challenge,
            "origin": EXPECTED_ORIGIN,
            "schema": CAPTURE_PAYLOAD_SCHEMA,
            "session": session,
            "storage_key": EXPECTED_STORAGE_KEY,
            "version": 1,
        }
    )


_BROWSER_CAPTURE_TEMPLATE = r"""
(async () => {
  "use strict";
  const publicKeyB64 = "__PUBLIC_KEY__";
  const aadB64 = "__AAD__";
  const expectedOrigin = "__EXPECTED_ORIGIN__";
  const storageKey = "__STORAGE_KEY__";
  const outputSentinel = "__SENTINEL__";
  const handoffKey = "__HANDOFF_KEY__";
  const maxStorageChars = __MAX_STORAGE_CHARS__;
  const maxTokenChars = __MAX_TOKEN_CHARS__;
  const encoder = new TextEncoder();
  const fail = () => { throw new Error("ea_blip_capture_unavailable"); };
  const fromB64u = (value) => {
    const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const raw = atob(padded);
    const output = new Uint8Array(raw.length);
    for (let index = 0; index < raw.length; index += 1) {
      output[index] = raw.charCodeAt(index);
    }
    return output;
  };
  const toB64u = (value) => {
    const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
    let raw = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) {
      raw += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    }
    return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  };
  const tokenOkay = (value) => (
    typeof value === "string"
    && value.length > 0
    && value.length <= maxTokenChars
    && !/[\u0000-\u0020\u007f]/.test(value)
  );

  if (location.origin !== expectedOrigin) fail();
  const raw = localStorage.getItem(storageKey);
  if (typeof raw !== "string" || raw.length < 2 || raw.length > maxStorageChars) fail();
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    fail();
  }
  const candidates = [
    parsed,
    parsed && parsed.currentSession,
    parsed && parsed.session,
    parsed && parsed.data && parsed.data.session,
    Array.isArray(parsed) ? parsed[0] : null,
    Array.isArray(parsed) ? parsed[1] : null,
  ];
  const auth = candidates.find((candidate) => (
    candidate
    && typeof candidate === "object"
    && tokenOkay(candidate.access_token)
    && tokenOkay(candidate.refresh_token)
  ));
  if (!auth || auth.access_token.split(".").length !== 3) fail();

  const aad = fromB64u(aadB64);
  let binding;
  try {
    binding = JSON.parse(new TextDecoder().decode(aad));
  } catch (_) {
    fail();
  }
  if (
    binding.alg !== "RSA-OAEP-256+A256GCM"
    || binding.version !== 1
    || binding.origin !== expectedOrigin
    || binding.storage_key !== storageKey
  ) fail();

  const plaintext = encoder.encode(JSON.stringify({
    access_token: auth.access_token,
    alg: binding.alg,
    challenge: binding.challenge,
    origin: location.origin,
    refresh_token: auth.refresh_token,
    schema: binding.schema,
    session: binding.session,
    storage_key: storageKey,
    version: binding.version,
  }));
  const publicKey = await crypto.subtle.importKey(
    "spki",
    fromB64u(publicKeyB64),
    {name: "RSA-OAEP", hash: "SHA-256"},
    false,
    ["encrypt"],
  );
  const aesKey = await crypto.subtle.generateKey(
    {name: "AES-GCM", length: 256},
    true,
    ["encrypt"],
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    {name: "AES-GCM", iv, additionalData: aad, tagLength: 128},
    aesKey,
    plaintext,
  );
  const rawAesKey = await crypto.subtle.exportKey("raw", aesKey);
  const wrappedKey = await crypto.subtle.encrypt(
    {name: "RSA-OAEP", label: aad},
    publicKey,
    rawAesKey,
  );
  const envelope = encoder.encode(JSON.stringify({
    alg: binding.alg,
    challenge: binding.challenge,
    ciphertext: toB64u(ciphertext),
    iv: toB64u(iv),
    version: binding.version,
    wrapped_key: toB64u(wrappedKey),
  }));
  if (
    Object.prototype.hasOwnProperty.call(globalThis, handoffKey)
    || localStorage.getItem(storageKey) !== raw
  ) fail();
  Object.defineProperty(globalThis, handoffKey, {
    value: Object.freeze({
      challenge: binding.challenge,
      origin: location.origin,
      raw,
      storage_key: storageKey,
    }),
    configurable: true,
    enumerable: false,
    writable: false,
  });
  if (
    localStorage.getItem(storageKey) !== raw
    || !globalThis[handoffKey]
    || globalThis[handoffKey].raw !== raw
  ) {
    delete globalThis[handoffKey];
    fail();
  }
  return outputSentinel + toB64u(envelope);
})()
""".strip()


def _browser_capture_program(
    *,
    public_key_der: bytes,
    aad: bytes,
    challenge: str,
) -> bytes:
    program = _BROWSER_CAPTURE_TEMPLATE
    replacements = {
        "__PUBLIC_KEY__": _b64url_encode(public_key_der),
        "__AAD__": _b64url_encode(aad),
        "__EXPECTED_ORIGIN__": EXPECTED_ORIGIN,
        "__STORAGE_KEY__": EXPECTED_STORAGE_KEY,
        "__SENTINEL__": CAPTURE_SENTINEL,
        "__HANDOFF_KEY__": _handoff_key(challenge),
        "__MAX_STORAGE_CHARS__": str(STORAGE_VALUE_MAX_CHARS),
        "__MAX_TOKEN_CHARS__": str(TOKEN_MAX_CHARS),
    }
    for marker, value in replacements.items():
        program = program.replace(marker, value)
    return (program + "\n").encode("utf-8")


def _quiescence_target(challenge: str) -> str:
    decoded = _b64url_decode(
        challenge,
        maximum=24,
        error="browser_quiescence_invalid",
    )
    if len(challenge) != 32 or len(decoded) != 24:
        raise CaptureFailure("browser_quiescence_invalid")
    return f"about:blank#ea-blip-capture-quiesced-{challenge}"


def _handoff_key(challenge: str) -> str:
    _quiescence_target(challenge)
    return f"__ea_blip_capture_handoff_{challenge}"


_BROWSER_QUIESCENCE_CAS_TEMPLATE = r"""
(() => {
  "use strict";
  const expectedOrigin = "__EXPECTED_ORIGIN__";
  const storageKey = "__STORAGE_KEY__";
  const handoffKey = "__HANDOFF_KEY__";
  const challenge = "__CHALLENGE__";
  const target = "__QUIESCENCE_TARGET__";
  const sentinel = "__CAS_SENTINEL__";
  const fail = () => { throw new Error("ea_blip_quiescence_unavailable"); };
  if (location.origin !== expectedOrigin) fail();
  const handoff = globalThis[handoffKey];
  if (
    !handoff
    || typeof handoff !== "object"
    || handoff.challenge !== challenge
    || handoff.origin !== expectedOrigin
    || handoff.storage_key !== storageKey
    || typeof handoff.raw !== "string"
    || localStorage.getItem(storageKey) !== handoff.raw
  ) {
    delete globalThis[handoffKey];
    fail();
  }
  localStorage.removeItem(storageKey);
  if (localStorage.getItem(storageKey) !== null) fail();
  delete globalThis[handoffKey];
  if (Object.prototype.hasOwnProperty.call(globalThis, handoffKey)) fail();
  setTimeout(() => location.replace(target), 0);
  return sentinel + challenge;
})()
""".strip()


def _browser_quiescence_cas_program(*, challenge: str) -> bytes:
    program = _BROWSER_QUIESCENCE_CAS_TEMPLATE
    replacements = {
        "__EXPECTED_ORIGIN__": EXPECTED_ORIGIN,
        "__STORAGE_KEY__": EXPECTED_STORAGE_KEY,
        "__HANDOFF_KEY__": _handoff_key(challenge),
        "__CHALLENGE__": challenge,
        "__QUIESCENCE_TARGET__": _quiescence_target(challenge),
        "__CAS_SENTINEL__": QUIESCENCE_CAS_SENTINEL,
    }
    for marker, value in replacements.items():
        program = program.replace(marker, value)
    return (program + "\n").encode("utf-8")


_BROWSER_QUIESCENCE_TEMPLATE = r"""
(async () => {
  "use strict";
  const target = "__QUIESCENCE_TARGET__";
  const storageKey = "__STORAGE_KEY__";
  const sentinel = "__QUIESCENCE_SENTINEL__";
  const challenge = "__CHALLENGE__";
  const deadline = Date.now() + 5000;
  while (location.href !== target && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  if (location.href !== target) {
    throw new Error("ea_blip_quiescence_unavailable");
  }
  let storageAbsent = false;
  try {
    storageAbsent = localStorage.getItem(storageKey) === null;
  } catch (_) {
    storageAbsent = true;
  }
  if (!storageAbsent) {
    throw new Error("ea_blip_quiescence_unavailable");
  }
  return sentinel + challenge;
})()
""".strip()


def _browser_quiescence_program(*, challenge: str) -> bytes:
    program = _BROWSER_QUIESCENCE_TEMPLATE
    replacements = {
        "__QUIESCENCE_TARGET__": _quiescence_target(challenge),
        "__STORAGE_KEY__": EXPECTED_STORAGE_KEY,
        "__QUIESCENCE_SENTINEL__": QUIESCENCE_SENTINEL,
        "__CHALLENGE__": challenge,
    }
    for marker, value in replacements.items():
        program = program.replace(marker, value)
    return (program + "\n").encode("utf-8")


def _child_hardening() -> None:
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _run_bounded_process(
    argv: list[str],
    *,
    stdin_bytes: bytes | bytearray,
    environment: dict[str, str],
    stdout_limit: int,
    stderr_limit: int,
    timeout: int,
    error: str,
) -> ProcessResult:
    deadline = time.monotonic() + max(1, int(timeout))
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(environment),
            close_fds=True,
            start_new_session=True,
            preexec_fn=_child_hardening,
        )
    except (OSError, ValueError) as exc:
        raise CaptureFailure(error) from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdin_descriptor = process.stdin.fileno()
    stdout_descriptor = process.stdout.fileno()
    stderr_descriptor = process.stderr.fileno()
    streams = {
        stdout_descriptor: (process.stdout, bytearray(), int(stdout_limit)),
        stderr_descriptor: (process.stderr, bytearray(), int(stderr_limit)),
    }
    selector = selectors.DefaultSelector()
    input_view = memoryview(stdin_bytes)
    input_offset = 0
    os.set_blocking(stdin_descriptor, False)
    if input_view:
        selector.register(
            process.stdin,
            selectors.EVENT_WRITE,
            data=("stdin", stdin_descriptor),
        )
    else:
        process.stdin.close()
    for descriptor, (stream, _buffer, _limit) in streams.items():
        os.set_blocking(descriptor, False)
        selector.register(
            stream,
            selectors.EVENT_READ,
            data=("output", descriptor),
        )
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CaptureFailure(error)
            events = selector.select(timeout=min(remaining, 0.25))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in list(selector.get_map().values())
                    if key.data[0] == "output"
                ]
                if not events:
                    raise CaptureFailure(error)
            for key, _mask in events:
                stream_kind, raw_descriptor = key.data
                descriptor = int(raw_descriptor)
                if stream_kind == "stdin":
                    try:
                        written = os.write(
                            descriptor,
                            input_view[input_offset : input_offset + 8_192],
                        )
                    except BlockingIOError:
                        continue
                    except (BrokenPipeError, OSError) as exc:
                        raise CaptureFailure(error) from exc
                    if written <= 0:
                        raise CaptureFailure(error)
                    input_offset += written
                    if input_offset == len(input_view):
                        selector.unregister(process.stdin)
                        process.stdin.close()
                    continue
                stream, buffer, limit = streams[descriptor]
                try:
                    chunk = os.read(descriptor, 8_192)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    continue
                buffer.extend(chunk)
                if len(buffer) > limit:
                    raise CaptureFailure(error)
        remaining = max(0.01, deadline - time.monotonic())
        returncode = process.wait(timeout=remaining)
    except (CaptureFailure, subprocess.TimeoutExpired) as exc:
        _kill_process_group(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if isinstance(exc, CaptureFailure):
            raise
        raise CaptureFailure(error) from exc
    finally:
        selector.close()
        input_view.release()
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()
        process.stderr.close()
    return ProcessResult(
        returncode=returncode,
        stdout=bytes(streams[stdout_descriptor][1]),
        stderr=bytes(streams[stderr_descriptor][1]),
    )


def _browser_environment() -> dict[str, str]:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH") or os.defpath,
    }
    for name in (
        "HOME",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_URL",
    ):
        value = str(os.environ.get(name) or "").strip()
        if value:
            environment[name] = value
    return environment


def _docker_environment() -> dict[str, str]:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH") or os.defpath,
    }
    for name in (
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "XDG_RUNTIME_DIR",
    ):
        value = str(os.environ.get(name) or "").strip()
        if value:
            environment[name] = value
    return environment


def _decrypt_capture(
    *,
    private_key: rsa.RSAPrivateKey,
    aad: bytes,
    challenge: str,
    session: str,
    browser_output: bytes,
) -> tuple[str, str]:
    match = _ENVELOPE_RE.fullmatch(browser_output)
    if match is None:
        raise CaptureFailure("browser_capture_output_invalid")
    encoded_envelope = match.group(1).decode("ascii")
    try:
        envelope = json.loads(
            _b64url_decode(
                encoded_envelope,
                maximum=48_000,
                error="browser_capture_output_invalid",
            ).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("browser_capture_output_invalid") from exc
    if (
        not isinstance(envelope, dict)
        or set(envelope)
        != {"alg", "challenge", "ciphertext", "iv", "version", "wrapped_key"}
        or envelope.get("alg") != CAPTURE_ALGORITHM
        or envelope.get("challenge") != challenge
        or envelope.get("version") != 1
    ):
        raise CaptureFailure("browser_capture_output_invalid")

    wrapped_key = _b64url_decode(
        envelope.get("wrapped_key"),
        maximum=512,
        error="browser_capture_output_invalid",
    )
    iv = _b64url_decode(
        envelope.get("iv"),
        maximum=12,
        error="browser_capture_output_invalid",
    )
    ciphertext = _b64url_decode(
        envelope.get("ciphertext"),
        maximum=40_000,
        error="browser_capture_output_invalid",
    )
    if len(iv) != 12 or len(ciphertext) < 17:
        raise CaptureFailure("browser_capture_output_invalid")
    try:
        aes_key = private_key.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=aad,
            ),
        )
        if len(aes_key) != 32:
            raise ValueError("invalid_aes_key")
        plaintext = AESGCM(aes_key).decrypt(iv, ciphertext, aad)
        payload = json.loads(plaintext.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("browser_capture_decryption_failed") from exc
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "access_token",
            "alg",
            "challenge",
            "origin",
            "refresh_token",
            "schema",
            "session",
            "storage_key",
            "version",
        }
        or payload.get("alg") != CAPTURE_ALGORITHM
        or payload.get("challenge") != challenge
        or payload.get("origin") != EXPECTED_ORIGIN
        or payload.get("schema") != CAPTURE_PAYLOAD_SCHEMA
        or payload.get("session") != session
        or payload.get("storage_key") != EXPECTED_STORAGE_KEY
        or payload.get("version") != 1
    ):
        raise CaptureFailure("browser_capture_binding_invalid")
    return (
        _valid_token_text(payload.get("access_token")),
        _valid_token_text(payload.get("refresh_token")),
    )


def _capture_browser_session(config: CaptureConfig) -> tuple[str, str, str]:
    challenge = _b64url_encode(secrets.token_bytes(24))
    aad = _capture_aad(challenge=challenge, session=config.session)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public_key_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    program = _browser_capture_program(
        public_key_der=public_key_der,
        aad=aad,
        challenge=challenge,
    )
    result = _run_bounded_process(
        [
            CANONICAL_BROWSER_ACT_BIN,
            "--session",
            config.session,
            "eval",
            "--stdin",
        ],
        stdin_bytes=program,
        environment=_browser_environment(),
        stdout_limit=BROWSER_STDOUT_MAX_BYTES,
        stderr_limit=BROWSER_STDERR_MAX_BYTES,
        timeout=PROCESS_TIMEOUT_SECONDS,
        error="browser_capture_failed",
    )
    if result.returncode != 0 or result.stderr:
        raise CaptureFailure("browser_capture_failed")
    access_token, refresh_token = _decrypt_capture(
        private_key=private_key,
        aad=aad,
        challenge=challenge,
        session=config.session,
        browser_output=result.stdout,
    )
    return access_token, refresh_token, challenge


def _verify_browser_quiescence(config: CaptureConfig, *, challenge: str) -> None:
    result = _run_bounded_process(
        [
            CANONICAL_BROWSER_ACT_BIN,
            "--session",
            config.session,
            "eval",
            "--stdin",
        ],
        stdin_bytes=_browser_quiescence_program(challenge=challenge),
        environment=_browser_environment(),
        stdout_limit=1_024,
        stderr_limit=BROWSER_STDERR_MAX_BYTES,
        timeout=PROCESS_TIMEOUT_SECONDS,
        error="browser_quiescence_failed",
    )
    expected = f"{QUIESCENCE_SENTINEL}{challenge}\n".encode("ascii")
    if result.returncode != 0 or result.stderr or result.stdout != expected:
        raise CaptureFailure("browser_quiescence_failed")


def _quiesce_browser_session(config: CaptureConfig, *, challenge: str) -> None:
    result = _run_bounded_process(
        [
            CANONICAL_BROWSER_ACT_BIN,
            "--session",
            config.session,
            "eval",
            "--stdin",
        ],
        stdin_bytes=_browser_quiescence_cas_program(challenge=challenge),
        environment=_browser_environment(),
        stdout_limit=1_024,
        stderr_limit=BROWSER_STDERR_MAX_BYTES,
        timeout=PROCESS_TIMEOUT_SECONDS,
        error="browser_quiescence_failed",
    )
    expected = f"{QUIESCENCE_CAS_SENTINEL}{challenge}\n".encode("ascii")
    if result.returncode != 0 or result.stderr or result.stdout != expected:
        raise CaptureFailure("browser_quiescence_failed")


def _read_api_key_file(path: Path) -> str:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    if not normalized.is_absolute():
        raise CaptureFailure("refresh_api_key_file_invalid")
    try:
        metadata = os.lstat(normalized)
    except OSError as exc:
        raise CaptureFailure("refresh_api_key_file_invalid") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size < 1
        or metadata.st_size > API_KEY_MAX_BYTES
    ):
        raise CaptureFailure("refresh_api_key_file_invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblock is None:
        raise CaptureFailure("refresh_api_key_file_invalid")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | nofollow
        | nonblock
    )
    try:
        descriptor = os.open(normalized, flags)
        try:
            opened_metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_metadata.st_mode)
                or opened_metadata.st_dev != metadata.st_dev
                or opened_metadata.st_ino != metadata.st_ino
                or opened_metadata.st_uid != metadata.st_uid
                or opened_metadata.st_gid != metadata.st_gid
                or opened_metadata.st_nlink != 1
                or stat.S_IMODE(opened_metadata.st_mode) != 0o600
                or opened_metadata.st_size != metadata.st_size
            ):
                raise CaptureFailure("refresh_api_key_file_invalid")
            encoded = os.read(descriptor, API_KEY_MAX_BYTES + 1)
            if os.read(descriptor, 1):
                raise CaptureFailure("refresh_api_key_file_invalid")
            final_metadata = os.fstat(descriptor)
            if (
                final_metadata.st_dev != opened_metadata.st_dev
                or final_metadata.st_ino != opened_metadata.st_ino
                or final_metadata.st_uid != opened_metadata.st_uid
                or final_metadata.st_gid != opened_metadata.st_gid
                or final_metadata.st_nlink != opened_metadata.st_nlink
                or final_metadata.st_mode != opened_metadata.st_mode
                or final_metadata.st_size != opened_metadata.st_size
                or final_metadata.st_mtime_ns != opened_metadata.st_mtime_ns
                or final_metadata.st_ctime_ns != opened_metadata.st_ctime_ns
            ):
                raise CaptureFailure("refresh_api_key_file_invalid")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise CaptureFailure("refresh_api_key_file_invalid") from exc
    try:
        value = encoded.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise CaptureFailure("refresh_api_key_file_invalid") from exc
    if (
        not value
        or len(value) > API_KEY_MAX_BYTES
        or any(ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        raise CaptureFailure("refresh_api_key_file_invalid")
    return value


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise urllib.error.HTTPError(
            request.full_url,
            code,
            "redirect_denied",
            headers,
            file_pointer,
        )


def _refresh_once(
    *,
    refresh_token: str,
    api_key: str,
    timeout: int = 20,
) -> RefreshedMaterial:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )
    body = _canonical_json_bytes({"refresh_token": refresh_token})
    request = urllib.request.Request(
        REFRESH_URL,
        method="POST",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "EA-Blip-Session-Capture/1.0",
            "apikey": api_key,
        },
    )
    try:
        with opener.open(request, timeout=max(1, int(timeout))) as response:
            if (
                int(response.status) != 200
                or response.geturl() != REFRESH_URL
                or not str(response.headers.get("Content-Type") or "")
                .lower()
                .startswith("application/json")
            ):
                raise CaptureFailure("refresh_failed")
            encoded = response.read(REFRESH_RESPONSE_MAX_BYTES + 1)
    except CaptureFailure:
        raise
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise CaptureFailure("refresh_failed") from exc
    if not encoded or len(encoded) > REFRESH_RESPONSE_MAX_BYTES:
        raise CaptureFailure("refresh_failed")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("refresh_failed") from exc
    user = payload.get("user") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or not isinstance(user, dict)
        or not isinstance(user.get("id"), str)
        or not user.get("id")
        or not isinstance(user.get("email"), str)
        or not user.get("email")
    ):
        raise CaptureFailure("refresh_failed")
    return RefreshedMaterial(
        access_token=_valid_token_text(payload.get("access_token")),
        refresh_token=_valid_token_text(payload.get("refresh_token")),
        subject=str(user["id"]),
        email=str(user["email"]),
    )


def _validate_user_once(
    *,
    access_token: str,
    api_key: str,
    timeout: int = 20,
) -> AuthenticatedUser:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=context),
    )
    request = urllib.request.Request(
        USER_URL,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "EA-Blip-Session-Capture/1.0",
            "apikey": api_key,
        },
    )
    try:
        with opener.open(request, timeout=max(1, int(timeout))) as response:
            if (
                int(response.status) != 200
                or response.geturl() != USER_URL
                or not str(response.headers.get("Content-Type") or "")
                .lower()
                .startswith("application/json")
            ):
                raise CaptureFailure("user_validation_failed")
            encoded = response.read(REFRESH_RESPONSE_MAX_BYTES + 1)
    except CaptureFailure:
        raise
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise CaptureFailure("user_validation_failed") from exc
    if not encoded or len(encoded) > REFRESH_RESPONSE_MAX_BYTES:
        raise CaptureFailure("user_validation_failed")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureFailure("user_validation_failed") from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("id"), str)
        or not payload.get("id")
        or not isinstance(payload.get("email"), str)
        or not payload.get("email")
    ):
        raise CaptureFailure("user_validation_failed")
    return AuthenticatedUser(
        subject=str(payload["id"]),
        email=str(payload["email"]),
    )


def _validate_user_session(
    *,
    access_token: str,
    api_key: str,
    expected_email: str,
    expected_subject: str,
    attempts: int = 2,
    validate_once: Callable[..., AuthenticatedUser] = _validate_user_once,
) -> None:
    last_failure: CaptureFailure | None = None
    for _attempt in range(max(1, min(int(attempts), 3))):
        try:
            user = validate_once(access_token=access_token, api_key=api_key)
            if (
                not hmac.compare_digest(user.subject, expected_subject)
                or not hmac.compare_digest(
                    user.email.casefold(),
                    expected_email.casefold(),
                )
            ):
                raise CaptureFailure("user_validation_failed")
            return
        except CaptureFailure as exc:
            last_failure = exc
    raise CaptureFailure("user_validation_failed") from last_failure


def _refresh_session(
    *,
    access_token: str,
    refresh_token: str,
    api_key: str,
    expected_email: str,
    expected_subject: str,
    refresh_once: Callable[..., RefreshedMaterial] = _refresh_once,
) -> tuple[str, str]:
    try:
        refreshed = refresh_once(
            refresh_token=refresh_token,
            api_key=api_key,
        )
    except CaptureFailure as exc:
        raise CaptureFailure("refresh_failed") from exc
    if (
        not hmac.compare_digest(refreshed.subject, expected_subject)
        or not hmac.compare_digest(
            refreshed.email.casefold(),
            expected_email.casefold(),
        )
    ):
        raise CaptureFailure("refreshed_token_claims_invalid")
    _decode_jwt_claims(
        refreshed.access_token,
        expected_email=expected_email,
        expected_subject=expected_subject,
        require_fresh=True,
    )
    if (
        hmac.compare_digest(refreshed.access_token, access_token)
        or hmac.compare_digest(refreshed.refresh_token, refresh_token)
    ):
        raise CaptureFailure("refreshed_token_claims_invalid")
    return refreshed.access_token, refreshed.refresh_token


_CONTAINER_STATE_HELPER = r"""
import hmac
import json
import os
import stat
import sys
from pathlib import Path

EXPECTED_UID = 10001
EXPECTED_GID = 10001
EXPECTED_ROOT = Path("/run/ea-memorial-state")

def target_metadata_valid(path, *, allow_absent):
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return bool(allow_absent)
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == EXPECTED_UID
        and metadata.st_gid == EXPECTED_GID
        and metadata.st_nlink == 1
        and stat.S_IMODE(metadata.st_mode) == 0o600
    )

ok = False
try:
    from app.api.routes import public_memorials as memorials

    if os.geteuid() != EXPECTED_UID or os.getegid() != EXPECTED_GID:
        raise ValueError("runtime_identity_invalid")
    raw = sys.stdin.buffer.read(65537)
    if not raw or len(raw) > 65536:
        raise ValueError("stdin_invalid")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"access_token", "refresh_token"}:
        raise ValueError("payload_invalid")
    access_token = payload["access_token"]
    refresh_token = payload["refresh_token"]
    configured_path = Path(
        os.environ["EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH"]
    )
    state_path = memorials._memorial_blipai_token_state_path()
    if (
        state_path != configured_path
        or configured_path.parent != EXPECTED_ROOT
        or configured_path.name in {"", ".", ".."}
    ):
        raise ValueError("state_path_invalid")
    parent_metadata = os.lstat(EXPECTED_ROOT)
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != EXPECTED_UID
        or parent_metadata.st_gid != EXPECTED_GID
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        or not target_metadata_valid(state_path, allow_absent=True)
    ):
        raise ValueError("state_metadata_invalid")
    ok = memorials._save_memorial_blipai_token_state(access_token, refresh_token)
    loaded = memorials._load_memorial_blipai_token_state() if ok else {}
    ok = bool(
        ok
        and target_metadata_valid(state_path, allow_absent=False)
        and isinstance(loaded, dict)
        and hmac.compare_digest(str(loaded.get("access_token") or ""), access_token)
        and hmac.compare_digest(str(loaded.get("refresh_token") or ""), refresh_token)
    )
    if ok and os.environ.get("EA_BLIP_CAPTURE_REMOVE_AFTER_SAVE") == "1":
        os.unlink(state_path)
        parent_descriptor = os.open(
            state_path.parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        ok = not os.path.lexists(state_path)
except BaseException:
    ok = False

sys.stdout.write("EA_BLIP_TOKEN_STATE_OK\n" if ok else "EA_BLIP_TOKEN_STATE_FAIL\n")
raise SystemExit(0 if ok else 23)
""".strip()


def _validate_image_id(value: str) -> str:
    if _IMAGE_RE.fullmatch(str(value or "")) is None:
        raise CaptureFailure("exact_image_id_invalid")
    return value


def _validate_state_dir(path: Path) -> Path:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    if "," in os.fspath(normalized) or any(
        ord(character) < 33 or ord(character) == 127
        for character in os.fspath(normalized)
    ):
        raise CaptureFailure("runtime_state_dir_invalid")
    try:
        resolved = normalized.resolve(strict=True)
        metadata = os.lstat(normalized)
    except OSError as exc:
        raise CaptureFailure("runtime_state_dir_invalid") from exc
    if (
        resolved != normalized
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != EXPECTED_RUNTIME_UID
        or metadata.st_gid != EXPECTED_RUNTIME_GID
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise CaptureFailure("runtime_state_dir_invalid")
    return normalized


def _wipe_bytearray(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _docker_write_state(
    config: CaptureConfig,
    *,
    access_token: str,
    refresh_token: str,
    target_name: str,
    remove_after_save: bool,
) -> None:
    if _SAFE_FILENAME_RE.fullmatch(target_name) is None or "/" in target_name:
        raise CaptureFailure("runtime_state_target_invalid")
    container_target = f"{CONTAINER_STATE_DIR}/{target_name}"
    mount = (
        f"type=bind,src={os.fspath(config.state_dir)},"
        f"dst={CONTAINER_STATE_DIR}"
    )
    argv = [
        CANONICAL_DOCKER_BIN,
        "run",
        "--interactive",
        "--rm",
        "--pull=never",
        "--network=none",
        f"--user={EXPECTED_RUNTIME_UID}:{EXPECTED_RUNTIME_GID}",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--log-driver=none",
        "--pids-limit=64",
        "--memory=384m",
        "--cpus=1",
        "--mount",
        mount,
        "--env",
        f"EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH={container_target}",
        "--env",
        f"EA_BLIP_CAPTURE_REMOVE_AFTER_SAVE={'1' if remove_after_save else '0'}",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONUNBUFFERED=1",
        "--workdir",
        "/app",
        "--entrypoint",
        "python",
        config.image_id,
        "-c",
        _CONTAINER_STATE_HELPER,
    ]
    encoded = bytearray(
        _canonical_json_bytes(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
        )
    )
    try:
        result = _run_bounded_process(
            argv,
            stdin_bytes=encoded,
            environment=_docker_environment(),
            stdout_limit=DOCKER_STDOUT_MAX_BYTES,
            stderr_limit=DOCKER_STDERR_MAX_BYTES,
            timeout=PROCESS_TIMEOUT_SECONDS,
            error="runtime_state_write_failed",
        )
    finally:
        _wipe_bytearray(encoded)
    if (
        result.returncode != 0
        or result.stdout != DOCKER_OK_SENTINEL
        or result.stderr
    ):
        raise CaptureFailure("runtime_state_write_failed")


def _preflight_runtime_state(config: CaptureConfig, *, nonce: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_-]{24}", nonce) is None:
        raise CaptureFailure("runtime_preflight_invalid")
    suffix = nonce
    target_name = f".blipai-capture-preflight-{suffix}.json"
    _docker_write_state(
        config,
        access_token=f"preflight-access-{suffix}",
        refresh_token=f"preflight-refresh-{suffix}",
        target_name=target_name,
        remove_after_save=True,
    )


def _save_runtime_state_with_retries(
    config: CaptureConfig,
    *,
    access_token: str,
    refresh_token: str,
    attempts: int = 2,
) -> None:
    last_failure: CaptureFailure | None = None
    for _attempt in range(max(1, min(int(attempts), 3))):
        try:
            _docker_write_state(
                config,
                access_token=access_token,
                refresh_token=refresh_token,
                target_name=FINAL_STATE_NAME,
                remove_after_save=False,
            )
            return
        except CaptureFailure as exc:
            last_failure = exc
    raise CaptureFailure("runtime_state_write_failed") from last_failure


def _validate_canonical_executable(
    path_text: str,
    *,
    allowed_uids: frozenset[int],
    error: str,
) -> None:
    path = Path(path_text)
    if not path.is_absolute():
        raise CaptureFailure(error)
    try:
        resolved = path.resolve(strict=True)
        metadata = os.stat(resolved)
    except OSError as exc:
        raise CaptureFailure(error) from exc
    if (
        resolved != path
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid not in allowed_uids
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise CaptureFailure(error)


def _validate_invocation_nonce(value: str) -> str:
    if _INVOCATION_NONCE_RE.fullmatch(str(value or "")) is None:
        raise CaptureFailure("invocation_nonce_invalid")
    decoded = _b64url_decode(
        value,
        maximum=32,
        error="invocation_nonce_invalid",
    )
    if len(decoded) != 32:
        raise CaptureFailure("invocation_nonce_invalid")
    return value


def _validate_new_receipt_destination(path: Path) -> Path:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    try:
        parent = normalized.parent.resolve(strict=True)
        parent_metadata = os.lstat(parent)
    except OSError as exc:
        raise CaptureFailure("receipt_destination_invalid") from exc
    if (
        parent != normalized.parent
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) & 0o022
    ):
        raise CaptureFailure("receipt_destination_invalid")
    try:
        os.lstat(normalized)
    except FileNotFoundError:
        return normalized
    except OSError as exc:
        raise CaptureFailure("receipt_destination_invalid") from exc
    raise CaptureFailure("receipt_destination_exists")


def _validate_config(config: CaptureConfig) -> CaptureConfig:
    if not config.operator_confirmed:
        raise CaptureFailure("operator_session_confirmation_required")
    if not config.dedicated_session_confirmed:
        raise CaptureFailure("dedicated_session_confirmation_required")
    if _SESSION_RE.fullmatch(config.session) is None:
        raise CaptureFailure("browser_session_name_invalid")
    if (
        not config.expected_email
        or len(config.expected_email) > 320
        or "@" not in config.expected_email
        or any(
            ord(character) < 33 or ord(character) == 127
            for character in config.expected_email
        )
    ):
        raise CaptureFailure("expected_account_invalid")
    invocation_nonce = _validate_invocation_nonce(config.invocation_nonce)
    _validate_canonical_executable(
        CANONICAL_BROWSER_ACT_BIN,
        allowed_uids=frozenset({os.geteuid()}),
        error="browser_executable_invalid",
    )
    _validate_canonical_executable(
        CANONICAL_DOCKER_BIN,
        allowed_uids=frozenset({0, os.geteuid()}),
        error="docker_executable_invalid",
    )
    if config.supabase_api_key_file is None:
        raise CaptureFailure("supabase_api_key_required")
    image_id = _validate_image_id(config.image_id)
    state_dir = _validate_state_dir(config.state_dir)
    receipt_path = _validate_new_receipt_destination(config.receipt_path)
    return CaptureConfig(
        session=config.session,
        expected_email=config.expected_email,
        image_id=image_id,
        state_dir=state_dir,
        receipt_path=receipt_path,
        invocation_nonce=invocation_nonce,
        supabase_api_key_file=config.supabase_api_key_file,
        operator_confirmed=config.operator_confirmed,
        dedicated_session_confirmed=config.dedicated_session_confirmed,
    )


def _run_capture(config: CaptureConfig) -> dict[str, object]:
    progress: dict[str, object] = {
        "browser_capture": "unproven",
        "browser_session_quiescence": "unproven",
        "runtime_preflight": "unproven",
        "protected_original_save_reload": "unproven",
        "local_refresh": "unproven",
        "provider_validation": "unproven",
        "rotated_overwrite_save_reload": "unproven",
        "protected_runtime_provider_currentness": "unproven",
    }
    try:
        config = _validate_config(config)
        if config.supabase_api_key_file is None:  # pragma: no cover
            raise CaptureFailure("supabase_api_key_required")
        api_key = _read_api_key_file(config.supabase_api_key_file)

        preflight_nonce = _b64url_encode(secrets.token_bytes(18))
        _preflight_runtime_state(config, nonce=preflight_nonce)
        progress["runtime_preflight"] = "pass"

        access_token, refresh_token, challenge = _capture_browser_session(config)
        progress["browser_capture"] = "encrypted_and_bound"
        captured_claims = _decode_jwt_claims(
            access_token,
            expected_email=config.expected_email,
            require_fresh=False,
        )

        _save_runtime_state_with_retries(
            config,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        progress["protected_original_save_reload"] = "pass"
        progress["protected_runtime_provider_currentness"] = (
            "captured_original_saved_not_yet_provider_validated"
        )

        _quiesce_browser_session(config, challenge=challenge)
        _verify_browser_quiescence(config, challenge=challenge)
        progress["browser_session_quiescence"] = (
            "exact_storage_cas_cleared_and_page_replaced"
        )

        provider_validation = ""
        if captured_claims.expires_at < int(time.time()) + MIN_FRESH_SECONDS:
            progress["local_refresh"] = "single_attempt_started_result_unproven"
            progress["protected_runtime_provider_currentness"] = (
                "unknown_after_refresh_attempt"
            )
            access_token, refresh_token = _refresh_session(
                access_token=access_token,
                refresh_token=refresh_token,
                api_key=api_key,
                expected_email=config.expected_email,
                expected_subject=captured_claims.subject,
            )
            provider_validation = "refresh"
            progress["local_refresh"] = "pass"
            progress["provider_validation"] = provider_validation
            progress["protected_runtime_provider_currentness"] = (
                "rotated_pair_in_process_not_yet_saved"
            )
            _save_runtime_state_with_retries(
                config,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            progress["rotated_overwrite_save_reload"] = "pass"
            progress["protected_runtime_provider_currentness"] = (
                "rotated_pair_saved_and_reloaded"
            )
        else:
            _decode_jwt_claims(
                access_token,
                expected_email=config.expected_email,
                expected_subject=captured_claims.subject,
                require_fresh=True,
            )
            _validate_user_session(
                access_token=access_token,
                api_key=api_key,
                expected_email=config.expected_email,
                expected_subject=captured_claims.subject,
            )
            provider_validation = "user_endpoint"
            progress["local_refresh"] = "not_needed"
            progress["provider_validation"] = provider_validation
            progress["rotated_overwrite_save_reload"] = "not_needed"
            progress["protected_runtime_provider_currentness"] = (
                "captured_original_provider_validated"
            )

        return {
            "schema": SCHEMA,
            "status": "capture_complete",
            "generated_at_utc": _utc_now(),
            "invocation_nonce": config.invocation_nonce,
            "capture_protocol": CAPTURE_ALGORITHM,
            **progress,
            "capture_helper_persisted_browser_output": False,
            "browser_tool_output_retention": "not_asserted",
            "dedicated_session_operator_confirmation": "present",
            "expected_origin": EXPECTED_ORIGIN,
            "storage_key": EXPECTED_STORAGE_KEY,
            "exact_image_id": config.image_id,
            "runtime_state_target": FINAL_STATE_NAME,
            "runtime_save_reload": "pass",
            "token_family_ownership": "not_independently_proven",
            "separate_ownership_gate_required": True,
            "runtime_secrets_included": False,
            "credential_metadata_included": False,
        }
    except CaptureFailure as exc:
        exc.evidence.update(progress)
        raise


def _failure_receipt(
    *,
    config: CaptureConfig,
    code: str,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    safe_evidence = dict(evidence or {})
    image_id = (
        config.image_id
        if _IMAGE_RE.fullmatch(str(config.image_id or ""))
        else DEFAULT_IMAGE_ID
    )
    return {
        "schema": SCHEMA,
        "status": "fail",
        "generated_at_utc": _utc_now(),
        "error_code": code,
        "invocation_nonce": (
            config.invocation_nonce
            if _INVOCATION_NONCE_RE.fullmatch(str(config.invocation_nonce or ""))
            else "unproven"
        ),
        "capture_protocol": CAPTURE_ALGORITHM,
        "browser_capture": safe_evidence.get("browser_capture", "unproven"),
        "capture_helper_persisted_browser_output": False,
        "browser_tool_output_retention": "not_asserted",
        "browser_session_quiescence": safe_evidence.get(
            "browser_session_quiescence",
            "unproven",
        ),
        "dedicated_session_operator_confirmation": (
            "present" if config.dedicated_session_confirmed else "absent"
        ),
        "expected_origin": EXPECTED_ORIGIN,
        "storage_key": EXPECTED_STORAGE_KEY,
        "exact_image_id": image_id,
        "runtime_state_target": FINAL_STATE_NAME,
        "runtime_preflight": safe_evidence.get(
            "runtime_preflight",
            "unproven",
        ),
        "protected_original_save_reload": safe_evidence.get(
            "protected_original_save_reload",
            "unproven",
        ),
        "local_refresh": safe_evidence.get("local_refresh", "unproven"),
        "provider_validation": safe_evidence.get(
            "provider_validation",
            "unproven",
        ),
        "rotated_overwrite_save_reload": safe_evidence.get(
            "rotated_overwrite_save_reload",
            "unproven",
        ),
        "protected_runtime_provider_currentness": safe_evidence.get(
            "protected_runtime_provider_currentness",
            "unproven",
        ),
        "runtime_save_reload": (
            "protected_original_pass"
            if safe_evidence.get("protected_original_save_reload") == "pass"
            else "unproven"
        ),
        "token_family_ownership": "not_proven",
        "separate_ownership_gate_required": True,
        "runtime_secrets_included": False,
        "credential_metadata_included": False,
    }


def _write_receipt(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
    ).encode("utf-8") + b"\n"
    try:
        normalized = _validate_new_receipt_destination(path)
    except CaptureFailure as exc:
        raise CaptureFailure("receipt_write_failed") from exc
    parent = normalized.parent

    parent_descriptor = os.open(
        parent,
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    temporary_name = f".blip-capture-receipt.{secrets.token_hex(12)}.tmp"
    descriptor = -1
    final_created = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise CaptureFailure("receipt_write_failed")
            remaining = remaining[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary_name,
            normalized.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        final_created = True
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        temporary_name = ""
        os.fsync(parent_descriptor)
        final_descriptor = os.open(
            normalized.name,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        try:
            final_metadata = os.fstat(final_descriptor)
            verified = bytearray()
            while len(verified) <= len(encoded):
                chunk = os.read(
                    final_descriptor,
                    min(8_192, len(encoded) + 1 - len(verified)),
                )
                if not chunk:
                    break
                verified.extend(chunk)
            if (
                not stat.S_ISREG(final_metadata.st_mode)
                or final_metadata.st_uid != os.geteuid()
                or final_metadata.st_nlink != 1
                or stat.S_IMODE(final_metadata.st_mode) != 0o600
                or bytes(verified) != encoded
            ):
                raise CaptureFailure("receipt_write_failed")
        finally:
            os.close(final_descriptor)
    except (OSError, CaptureFailure) as exc:
        if final_created:
            try:
                os.unlink(normalized.name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except OSError:
                pass
        if isinstance(exc, CaptureFailure):
            raise
        raise CaptureFailure("receipt_write_failed") from exc
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except OSError:
                pass
        os.close(parent_descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture one existing Blip Supabase session through an encrypt-first "
            "BrowserAct eval and persist it with the exact networkless runtime image."
        )
    )
    parser.add_argument("--session", required=True)
    parser.add_argument("--expected-email", required=True)
    parser.add_argument("--image-id", default=DEFAULT_IMAGE_ID)
    parser.add_argument("--state-dir", default=os.fspath(DEFAULT_STATE_DIR))
    parser.add_argument("--receipt", required=True)
    parser.add_argument(
        "--invocation-nonce",
        required=True,
        help=(
            "Caller-issued canonical base64url encoding of exactly 32 random "
            "bytes; the receipt path must not already exist."
        ),
    )
    parser.add_argument("--supabase-api-key-file")
    parser.add_argument(
        "--operator-confirmed-session-owned-and-remote-assist-released",
        action="store_true",
        help=(
            "Required acknowledgement that this BrowserAct session is owned by "
            "the current operator and no remote-assist lockdown remains active."
        ),
    )
    parser.add_argument(
        "--operator-confirmed-dedicated-session-and-no-other-blip-tabs",
        action="store_true",
        help=(
            "Required acknowledgement that the named session is dedicated to "
            "this transfer, every other Blip page/tab in the shared browser "
            "profile is closed, and this page may be cleared and navigated away."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = CaptureConfig(
        session=str(args.session),
        expected_email=str(args.expected_email),
        image_id=str(args.image_id),
        state_dir=Path(args.state_dir),
        receipt_path=Path(args.receipt),
        invocation_nonce=str(args.invocation_nonce),
        supabase_api_key_file=(
            Path(args.supabase_api_key_file)
            if args.supabase_api_key_file
            else None
        ),
        operator_confirmed=bool(
            args.operator_confirmed_session_owned_and_remote_assist_released
        ),
        dedicated_session_confirmed=bool(
            args.operator_confirmed_dedicated_session_and_no_other_blip_tabs
        ),
    )
    try:
        receipt = _run_capture(config)
        return_code = 0
    except CaptureFailure as exc:
        receipt = _failure_receipt(
            config=config,
            code=exc.code,
            evidence=exc.evidence,
        )
        return_code = 1
    except BaseException:
        receipt = _failure_receipt(config=config, code="unexpected_capture_failure")
        return_code = 1
    try:
        _write_receipt(config.receipt_path, receipt)
    except CaptureFailure:
        receipt = _failure_receipt(config=config, code="receipt_write_failed")
        return_code = 1
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
