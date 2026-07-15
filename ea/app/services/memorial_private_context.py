from __future__ import annotations

import copy
import errno
import hashlib
import hmac
import json
import os
import re
import stat
from pathlib import Path


PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
PRIVATE_CONTEXT_SCHEMA = "ea.memorial_private_context.v1"
PRIVATE_CONTEXT_DECLARATION = {"required": True, "schema": PRIVATE_CONTEXT_SCHEMA}
PRIVATE_OVERRIDE_FIELDS = (
    "audio_clips",
    "memory_cards",
    "candidate_recordings",
    "source_grounded_profile",
    "character_notes",
    "conversation_style",
    "external_sources",
    "memory_principal_id",
    "chat_models",
    "chat_model_default",
)
_COLLECTION_OVERRIDE_FIELDS = (
    "audio_clips",
    "memory_cards",
    "candidate_recordings",
    "source_grounded_profile",
    "character_notes",
    "external_sources",
    "chat_models",
)
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_MAX_CONTEXT_BYTES = 2 * 1024 * 1024
_MAX_COLLECTION_ITEMS = 512
_MAX_NOTE_CHARS = 12_000
_MAX_IDENTIFIER_CHARS = 240
_ALLOWED_PRIVATE_FILE_MODES = {0o400, 0o600}
_PUBLIC_PROJECTION_SNAPSHOT_FIELD = "__ea_public_memorial_projection__"


class MemorialPrivateContextError(ValueError):
    pass


def _safe_slug(value: object) -> str:
    slug = str(value or "").strip()
    if _SLUG_RE.fullmatch(slug) is None:
        raise MemorialPrivateContextError("memorial_private_context_slug_invalid")
    return slug


def _bounded_string(value: object, *, maximum: int, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
    ):
        raise MemorialPrivateContextError(code)
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MemorialPrivateContextError("memorial_private_context_invalid") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise MemorialPrivateContextError("memorial_private_context_invalid")
        payload[key] = value
    return payload


def _reject_nonfinite(_value: str) -> object:
    raise MemorialPrivateContextError("memorial_private_context_invalid")


def _encoded_overrides(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(PRIVATE_OVERRIDE_FIELDS):
        raise MemorialPrivateContextError("memorial_private_context_overrides_invalid")
    encoded = dict(value)
    raw_notes = encoded.get("character_notes")
    if not isinstance(raw_notes, list):
        raise MemorialPrivateContextError("memorial_private_context_overrides_invalid")
    notes: list[dict[str, str]] = []
    for item in raw_notes:
        if isinstance(item, str):
            note = item
        elif isinstance(item, dict) and set(item) == {"note"}:
            note = item.get("note")
        else:
            raise MemorialPrivateContextError(
                "memorial_private_context_overrides_invalid"
            )
        notes.append(
            {
                "note": _bounded_string(
                    note,
                    maximum=_MAX_NOTE_CHARS,
                    code="memorial_private_context_overrides_invalid",
                )
            }
        )
    encoded["character_notes"] = notes
    return _validated_stored_overrides(encoded)


def _validated_stored_overrides(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(PRIVATE_OVERRIDE_FIELDS):
        raise MemorialPrivateContextError("memorial_private_context_overrides_invalid")
    overrides = dict(value)
    for field in _COLLECTION_OVERRIDE_FIELDS:
        collection = overrides.get(field)
        if (
            not isinstance(collection, list)
            or len(collection) > _MAX_COLLECTION_ITEMS
            or any(not isinstance(item, dict) for item in collection)
        ):
            raise MemorialPrivateContextError(
                "memorial_private_context_overrides_invalid"
            )
    for item in overrides["character_notes"]:
        if set(item) != {"note"}:
            raise MemorialPrivateContextError(
                "memorial_private_context_overrides_invalid"
            )
        _bounded_string(
            item.get("note"),
            maximum=_MAX_NOTE_CHARS,
            code="memorial_private_context_overrides_invalid",
        )
    for item in overrides["chat_models"]:
        if set(item) != {"llm_model", "label"}:
            raise MemorialPrivateContextError(
                "memorial_private_context_overrides_invalid"
            )
        _bounded_string(
            item.get("llm_model"),
            maximum=_MAX_IDENTIFIER_CHARS,
            code="memorial_private_context_overrides_invalid",
        )
        _bounded_string(
            item.get("label"),
            maximum=_MAX_IDENTIFIER_CHARS,
            code="memorial_private_context_overrides_invalid",
        )
    if not isinstance(overrides.get("conversation_style"), dict):
        raise MemorialPrivateContextError("memorial_private_context_overrides_invalid")
    for field in ("memory_principal_id", "chat_model_default"):
        _bounded_string(
            overrides.get(field),
            maximum=_MAX_IDENTIFIER_CHARS,
            code="memorial_private_context_overrides_invalid",
        )
    _canonical_json_bytes(overrides)
    return overrides


def _decoded_overrides(stored: dict[str, object]) -> dict[str, object]:
    decoded = dict(stored)
    decoded["character_notes"] = [
        str(item["note"]) for item in stored["character_notes"]
    ]
    return decoded


def private_context_payload(
    *, slug: str, overrides: dict[str, object]
) -> dict[str, object]:
    safe_slug = _safe_slug(slug)
    encoded = _encoded_overrides(overrides)
    return {
        "schema": PRIVATE_CONTEXT_SCHEMA,
        "slug": safe_slug,
        "overrides_sha256": hashlib.sha256(_canonical_json_bytes(encoded)).hexdigest(),
        "overrides": encoded,
    }


def private_context_path(*, private_root: Path, slug: str) -> Path:
    safe_slug = _safe_slug(slug)
    root = Path(private_root).expanduser().resolve()
    parent = (root / safe_slug).resolve()
    if root not in parent.parents:
        raise MemorialPrivateContextError("memorial_private_context_path_invalid")
    return parent / PRIVATE_CONTEXT_FILENAME


def _read_private_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        code = (
            "memorial_private_context_path_invalid"
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}
            else "memorial_private_context_unreadable"
        )
        raise MemorialPrivateContextError(code) from exc
    try:
        metadata = os.fstat(descriptor)
        mode = stat.S_IMODE(metadata.st_mode)
        if not stat.S_ISREG(metadata.st_mode):
            raise MemorialPrivateContextError("memorial_private_context_file_invalid")
        if mode not in _ALLOWED_PRIVATE_FILE_MODES:
            raise MemorialPrivateContextError(
                "memorial_private_context_permissions_invalid"
            )
        if metadata.st_size <= 0 or metadata.st_size > _MAX_CONTEXT_BYTES:
            raise MemorialPrivateContextError("memorial_private_context_invalid")
        chunks: list[bytes] = []
        remaining = _MAX_CONTEXT_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        document = b"".join(chunks)
        if (
            not document
            or len(document) > _MAX_CONTEXT_BYTES
            or len(document) != metadata.st_size
        ):
            raise MemorialPrivateContextError("memorial_private_context_invalid")
        return document
    finally:
        os.close(descriptor)


def decode_private_memorial_context_document(
    document: bytes, *, expected_slug: str
) -> dict[str, object]:
    safe_slug = _safe_slug(expected_slug)
    if (
        not isinstance(document, bytes)
        or not document
        or len(document) > _MAX_CONTEXT_BYTES
    ):
        raise MemorialPrivateContextError("memorial_private_context_invalid")
    try:
        payload = json.loads(
            document.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except MemorialPrivateContextError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemorialPrivateContextError("memorial_private_context_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "slug",
        "overrides_sha256",
        "overrides",
    }:
        raise MemorialPrivateContextError("memorial_private_context_invalid")
    if (
        payload.get("schema") != PRIVATE_CONTEXT_SCHEMA
        or payload.get("slug") != safe_slug
    ):
        raise MemorialPrivateContextError("memorial_private_context_scope_invalid")
    stored = _validated_stored_overrides(payload.get("overrides"))
    expected_digest = str(payload.get("overrides_sha256") or "").strip().lower()
    actual_digest = hashlib.sha256(_canonical_json_bytes(stored)).hexdigest()
    if _DIGEST_RE.fullmatch(expected_digest) is None or not hmac.compare_digest(
        expected_digest, actual_digest
    ):
        raise MemorialPrivateContextError("memorial_private_context_digest_invalid")
    return _decoded_overrides(stored)


def read_private_memorial_context_document(
    *, private_root: Path, slug: str
) -> tuple[dict[str, object], bytes]:
    safe_slug = _safe_slug(slug)
    path = private_context_path(private_root=private_root, slug=safe_slug)
    document = _read_private_regular_file(path)
    overrides = decode_private_memorial_context_document(
        document, expected_slug=safe_slug
    )
    return overrides, document


def load_private_memorial_context(
    *, private_root: Path, slug: str
) -> dict[str, object]:
    overrides, _document = read_private_memorial_context_document(
        private_root=private_root,
        slug=slug,
    )
    return overrides


def private_context_declared(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    declaration = payload.get("private_context")
    return isinstance(declaration, dict) and declaration == PRIVATE_CONTEXT_DECLARATION


def public_memorial_projection_source(
    payload: dict[str, object],
) -> dict[str, object]:
    """Return the pre-overlay public source when private context was merged."""
    snapshot = payload.get(_PUBLIC_PROJECTION_SNAPSHOT_FIELD)
    if isinstance(snapshot, dict):
        return dict(snapshot)
    return payload


def merge_private_memorial_context(
    *, public_payload: dict[str, object], private_root: Path, slug: str
) -> dict[str, object]:
    supplied = dict(public_payload) if isinstance(public_payload, dict) else {}
    existing_snapshot = supplied.get(_PUBLIC_PROJECTION_SNAPSHOT_FIELD)
    public_only = (
        copy.deepcopy(existing_snapshot)
        if isinstance(existing_snapshot, dict)
        else supplied
    )
    public_only.pop(_PUBLIC_PROJECTION_SNAPSHOT_FIELD, None)
    if not private_context_declared(public_only):
        return public_only
    try:
        overrides = load_private_memorial_context(private_root=private_root, slug=slug)
    except (FileNotFoundError, OSError, MemorialPrivateContextError):
        return public_only
    merged = dict(public_only)
    merged[_PUBLIC_PROJECTION_SNAPSHOT_FIELD] = copy.deepcopy(public_only)
    for field in PRIVATE_OVERRIDE_FIELDS:
        merged[field] = overrides[field]
    return merged
