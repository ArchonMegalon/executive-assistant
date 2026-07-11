from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath

from app.services import memorial_family_contributions as family_contributions
from app.services.memorial_private_context import (
    PRIVATE_CONTEXT_FILENAME,
    MemorialPrivateContextError,
    decode_private_memorial_context_document,
    load_private_memorial_context,
    read_private_memorial_context_document,
)
from app.services.memorial_paths import (
    memorial_dir_candidates,
    private_profile_dir_candidates,
    repo_root,
)


INVENTORY_SCHEMA = "ea.memorial_flagship_recovery_inventory.v2"
REFERENCE_SCHEMA = "ea.memorial_flagship_recovery_references.v2"
_MAX_INVENTORY_BYTES = 512 * 1024 * 1024
_MAX_MEDIA_FILE_BYTES = 128 * 1024 * 1024
_MAX_MEDIA_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_FILE_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_JSON_FILE_BYTES = 8 * 1024 * 1024
_MAX_MEDIA_ITEMS = 100
_MAX_ARCHIVE_DOCUMENTS = 64
_MAX_ARCHIVE_ARTIFACTS = 256
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ARCHIVE_AUDIENCES = ("public", "family", "review")
_CONSENT_REFERENCE_FIELDS = (
    "voice_consent",
    "consent_basis",
    "synthetic_voice_clone_of_memorial_person",
    "voice_profile_id",
    "tts_mode",
    "tts_plugin",
    "tts_plugin_voice_id",
    "tts_base_voice_variant",
    "lang",
)
_ARCHIVE_REFERENCE_FIELDS = (
    "document_id",
    "title",
    "description",
    "version",
    "audience",
    "sensitivity",
    "source_sha256",
    "sha256",
)


def _safe_slug(value: str) -> str:
    slug = str(value or "").strip()
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("memorial_recovery_inventory_scope_invalid")
    return slug


def _default_public_root() -> Path:
    return memorial_dir_candidates()[0]


def _default_private_root() -> Path:
    return private_profile_dir_candidates()[0]


def _default_archive_root() -> Path:
    configured = str(os.getenv("EA_MEMORIAL_ARCHIVE_DIR") or "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else repo_root() / "memorial_archive"
    )


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _reject_symlink_components(path: Path, *, include_leaf: bool = True) -> None:
    absolute = _absolute(path)
    candidates = list(reversed(absolute.parents))
    if include_leaf:
        candidates.append(absolute)
    for candidate in candidates:
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("memorial_recovery_inventory_path_invalid") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("memorial_recovery_inventory_symlink_forbidden")


def _contained(root: Path, candidate: Path, *, allow_root: bool = False) -> Path:
    absolute_root = _absolute(root)
    absolute_candidate = _absolute(candidate)
    try:
        relative = absolute_candidate.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError("memorial_recovery_inventory_path_outside_root") from exc
    if (not allow_root and relative == Path(".")) or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("memorial_recovery_inventory_path_outside_root")
    _reject_symlink_components(absolute_candidate)
    return absolute_candidate


def _safe_relpath(value: object) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 500
        or "\\" in text
        or any(ord(char) < 32 for char in text)
    ):
        raise ValueError("memorial_recovery_inventory_relpath_invalid")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("memorial_recovery_inventory_relpath_invalid")
    return path.as_posix()


def _read_regular_file(path: Path, *, max_bytes: int) -> bytes:
    absolute = _absolute(path)
    _reject_symlink_components(absolute)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(absolute, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(errno.EINVAL, "regular file required")
        if metadata.st_size > max_bytes:
            raise ValueError("memorial_recovery_inventory_file_too_large")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("memorial_recovery_inventory_file_too_large")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("memorial_recovery_inventory_json_invalid") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("memorial_recovery_inventory_json_invalid")
        payload[key] = value
    return payload


def _reject_nonfinite(_value: str) -> object:
    raise ValueError("memorial_recovery_inventory_json_invalid")


def _decode_json_bytes(document: bytes) -> dict[str, object]:
    try:
        payload = json.loads(
            document.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError("memorial_recovery_inventory_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("memorial_recovery_inventory_json_invalid")
    return payload


def _read_json(
    path: Path, *, max_bytes: int = _MAX_JSON_FILE_BYTES
) -> tuple[dict[str, object], bytes]:
    document = _read_regular_file(path, max_bytes=max_bytes)
    return _decode_json_bytes(document), document


def _bounded_reference_value(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not isinstance(value, int):
            raise ValueError("memorial_recovery_inventory_reference_invalid")
        return value
    if isinstance(value, str) and len(value) <= 1000 and "\x00" not in value:
        return value
    raise ValueError("memorial_recovery_inventory_reference_invalid")


def _reference_fields(
    payload: dict[str, object], names: tuple[str, ...]
) -> dict[str, object]:
    references: dict[str, object] = {}
    for name in names:
        if name not in payload:
            continue
        value = payload[name]
        if name == "voice_consent" and isinstance(value, dict):
            consent: dict[str, object] = {}
            for field in (
                "status",
                "authorized_by",
                "authorized_at",
                "source_assets_reviewed",
                "revoked",
            ):
                if field in value:
                    consent[field] = _bounded_reference_value(value[field])
            scope = value.get("scope")
            if scope is not None:
                if (
                    not isinstance(scope, list)
                    or len(scope) > 20
                    or any(
                        not isinstance(item, str) or len(item) > 200 or "\x00" in item
                        for item in scope
                    )
                ):
                    raise ValueError("memorial_recovery_inventory_reference_invalid")
                consent["scope"] = list(scope)
            references[name] = consent
            continue
        references[name] = _bounded_reference_value(value)
    return references


def _file_entry(
    *, source_kind: str, relpath: str, visibility: str, content: bytes
) -> dict[str, object]:
    return {
        "source_kind": source_kind,
        "source_relpath": _safe_relpath(relpath),
        "visibility": "public" if visibility == "public" else "private",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "captured": True,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _private_context_inventory(
    *, slug: str, private_root: Path
) -> tuple[dict[str, object], dict[str, object]]:
    absent = {
        "present": False,
        "source_relpath": PRIVATE_CONTEXT_FILENAME,
        "sha256": "",
        "size_bytes": 0,
        "content_base64": "",
    }
    try:
        overrides, document = read_private_memorial_context_document(
            private_root=private_root,
            slug=slug,
        )
    except FileNotFoundError:
        return absent, {}
    except MemorialPrivateContextError as exc:
        raise ValueError("memorial_recovery_inventory_private_context_invalid") from exc
    return (
        {
            "present": True,
            "source_relpath": PRIVATE_CONTEXT_FILENAME,
            "sha256": hashlib.sha256(document).hexdigest(),
            "size_bytes": len(document),
            "content_base64": base64.b64encode(document).decode("ascii"),
        },
        overrides,
    )


def _source_media_inventory(
    *,
    slug: str,
    public_root: Path,
    private_root: Path,
    private_context_overrides: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    public_slug_root = _contained(public_root, public_root / slug)
    private_slug_root = _contained(private_root, private_root / slug)
    entries: list[dict[str, object]] = []
    captured_by_digest: dict[str, tuple[int, str]] = {}

    public_manifest = public_slug_root / "memorial.json"
    if public_manifest.exists():
        payload, _document = _read_json(public_manifest)
        audio_clips = payload.get("audio_clips") or []
        if not isinstance(audio_clips, list) or len(audio_clips) > _MAX_MEDIA_ITEMS:
            raise ValueError("memorial_recovery_inventory_source_media_invalid")
        for raw_item in audio_clips:
            if not isinstance(raw_item, dict) or not raw_item.get("asset_relpath"):
                continue
            relpath = _safe_relpath(raw_item["asset_relpath"])
            source = _contained(public_slug_root, public_slug_root / relpath)
            try:
                content = _read_regular_file(source, max_bytes=_MAX_MEDIA_FILE_BYTES)
            except (FileNotFoundError, OSError) as exc:
                raise ValueError(
                    "memorial_recovery_inventory_source_media_incomplete"
                ) from exc
            entry = _file_entry(
                source_kind="public_manifest",
                relpath=relpath,
                visibility=str(raw_item.get("visibility") or "private").strip().lower(),
                content=content,
            )
            entries.append(entry)
            captured_by_digest[str(entry["sha256"])] = (
                len(content),
                str(entry["content_base64"]),
            )

    if private_context_overrides is None:
        try:
            private_context = load_private_memorial_context(
                private_root=private_root,
                slug=slug,
            )
        except FileNotFoundError:
            private_context = {}
        except MemorialPrivateContextError as exc:
            raise ValueError("memorial_recovery_inventory_private_context_invalid") from exc
    else:
        private_context = dict(private_context_overrides)
    context_audio_clips = private_context.get("audio_clips") or []
    if not isinstance(context_audio_clips, list) or len(context_audio_clips) > _MAX_MEDIA_ITEMS:
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    for raw_item in context_audio_clips:
        if not isinstance(raw_item, dict) or not raw_item.get("asset_relpath"):
            continue
        relpath = _safe_relpath(raw_item["asset_relpath"])
        source = _contained(public_slug_root, public_slug_root / relpath)
        try:
            content = _read_regular_file(source, max_bytes=_MAX_MEDIA_FILE_BYTES)
        except (FileNotFoundError, OSError) as exc:
            raise ValueError("memorial_recovery_inventory_source_media_incomplete") from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest in captured_by_digest:
            entry = {
                "source_kind": "private_context",
                "source_relpath": relpath,
                "visibility": "public"
                if str(raw_item.get("visibility") or "private").strip().lower() == "public"
                else "private",
                "sha256": digest,
                "size_bytes": len(content),
                "captured": False,
                "content_base64": "",
            }
        else:
            entry = _file_entry(
                source_kind="private_context",
                relpath=relpath,
                visibility=str(raw_item.get("visibility") or "private").strip().lower(),
                content=content,
            )
            captured_by_digest[digest] = (len(content), str(entry["content_base64"]))
        entries.append(entry)

    voice_manifest_path = private_slug_root / "voice_profile_manifest.json"
    if voice_manifest_path.exists():
        voice_manifest, _document = _read_json(voice_manifest_path)
        audio_assets = voice_manifest.get("audio_assets") or []
        if not isinstance(audio_assets, list) or len(audio_assets) > _MAX_MEDIA_ITEMS:
            raise ValueError("memorial_recovery_inventory_source_media_invalid")
        for raw_item in audio_assets:
            if not isinstance(raw_item, dict) or not raw_item.get("asset_relpath"):
                continue
            relpath = _safe_relpath(raw_item["asset_relpath"])
            declared_digest = str(raw_item.get("sha256") or "").strip().lower()
            declared_size = raw_item.get("size_bytes")
            source = _contained(private_slug_root, private_slug_root / relpath)
            try:
                content = _read_regular_file(source, max_bytes=_MAX_MEDIA_FILE_BYTES)
            except FileNotFoundError:
                content = None
            except OSError as exc:
                raise ValueError(
                    "memorial_recovery_inventory_source_media_incomplete"
                ) from exc
            if content is not None:
                digest = hashlib.sha256(content).hexdigest()
                if declared_digest and not hmac.compare_digest(declared_digest, digest):
                    raise ValueError(
                        "memorial_recovery_inventory_source_media_digest_mismatch"
                    )
                if isinstance(declared_size, int) and declared_size != len(content):
                    raise ValueError(
                        "memorial_recovery_inventory_source_media_size_mismatch"
                    )
                if digest in captured_by_digest:
                    entry = {
                        "source_kind": "voice_profile",
                        "source_relpath": relpath,
                        "visibility": "private",
                        "sha256": digest,
                        "size_bytes": len(content),
                        "captured": False,
                        "content_base64": "",
                    }
                else:
                    entry = _file_entry(
                        source_kind="voice_profile",
                        relpath=relpath,
                        visibility="private",
                        content=content,
                    )
                    captured_by_digest[digest] = (
                        len(content),
                        str(entry["content_base64"]),
                    )
            else:
                if (
                    not _DIGEST_RE.fullmatch(declared_digest)
                    or declared_digest not in captured_by_digest
                ):
                    raise ValueError(
                        "memorial_recovery_inventory_source_media_incomplete"
                    )
                size, _encoded = captured_by_digest[declared_digest]
                if isinstance(declared_size, int) and declared_size != size:
                    raise ValueError(
                        "memorial_recovery_inventory_source_media_size_mismatch"
                    )
                entry = {
                    "source_kind": "voice_profile",
                    "source_relpath": relpath,
                    "visibility": "private",
                    "sha256": declared_digest,
                    "size_bytes": size,
                    "captured": False,
                    "content_base64": "",
                }
            entries.append(entry)

    if len(entries) > _MAX_MEDIA_ITEMS:
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    entries.sort(
        key=lambda item: (str(item["source_kind"]), str(item["source_relpath"]))
    )
    if len({(item["source_kind"], item["source_relpath"]) for item in entries}) != len(
        entries
    ):
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    return entries


def _archive_documents_inventory(
    *, slug: str, archive_root: Path
) -> list[dict[str, object]]:
    slug_root = _contained(archive_root, archive_root / slug)
    if not slug_root.exists():
        return []
    documents: list[dict[str, object]] = []
    artifact_count = 0
    for audience in _ARCHIVE_AUDIENCES:
        audience_root = _contained(slug_root, slug_root / audience)
        if not audience_root.exists():
            continue
        _reject_symlink_components(audience_root)
        try:
            children = sorted(os.scandir(audience_root), key=lambda entry: entry.name)
        except OSError as exc:
            raise ValueError("memorial_recovery_inventory_archive_invalid") from exc
        if len(children) > _MAX_ARCHIVE_DOCUMENTS:
            raise ValueError("memorial_recovery_inventory_archive_invalid")
        for child in children:
            if child.is_symlink():
                raise ValueError("memorial_recovery_inventory_symlink_forbidden")
            if not child.is_dir(follow_symlinks=False):
                continue
            if not _SLUG_RE.fullmatch(child.name):
                raise ValueError("memorial_recovery_inventory_archive_invalid")
            document_root = _contained(audience_root, audience_root / child.name)
            manifest_path = document_root / "manifest.json"
            try:
                manifest, manifest_document = _read_json(
                    manifest_path, max_bytes=1024 * 1024
                )
            except FileNotFoundError as exc:
                raise ValueError(
                    "memorial_recovery_inventory_archive_manifest_missing"
                ) from exc
            build_artifacts = manifest.get("build_artifacts") or {}
            if not isinstance(build_artifacts, dict) or len(build_artifacts) > 10:
                raise ValueError("memorial_recovery_inventory_archive_invalid")
            artifacts: list[dict[str, object]] = []
            artifact_relpaths: set[str] = set()
            for artifact_key, raw_relpath in sorted(build_artifacts.items()):
                if not isinstance(artifact_key, str) or not isinstance(
                    raw_relpath, str
                ):
                    raise ValueError("memorial_recovery_inventory_archive_invalid")
                relpath = _safe_relpath(raw_relpath)
                if relpath in artifact_relpaths:
                    raise ValueError("memorial_recovery_inventory_archive_invalid")
                artifact_relpaths.add(relpath)
                source = _contained(document_root, document_root / relpath)
                try:
                    content = _read_regular_file(
                        source, max_bytes=_MAX_ARCHIVE_FILE_BYTES
                    )
                except (FileNotFoundError, OSError) as exc:
                    raise ValueError(
                        "memorial_recovery_inventory_archive_artifact_missing"
                    ) from exc
                artifacts.append(
                    {
                        "artifact_key": artifact_key,
                        "relpath": relpath,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                )
                artifact_count += 1
                if artifact_count > _MAX_ARCHIVE_ARTIFACTS:
                    raise ValueError("memorial_recovery_inventory_archive_invalid")
            source_relpath = "source.md"
            if source_relpath in artifact_relpaths:
                raise ValueError("memorial_recovery_inventory_archive_invalid")
            source_path = _contained(document_root, document_root / source_relpath)
            try:
                source_content = _read_regular_file(
                    source_path, max_bytes=_MAX_ARCHIVE_FILE_BYTES
                )
            except (FileNotFoundError, OSError) as exc:
                raise ValueError(
                    "memorial_recovery_inventory_archive_source_missing"
                ) from exc
            artifacts.append(
                {
                    "artifact_key": "source_markdown",
                    "relpath": source_relpath,
                    "sha256": hashlib.sha256(source_content).hexdigest(),
                    "size_bytes": len(source_content),
                    "content_base64": base64.b64encode(source_content).decode("ascii"),
                }
            )
            artifact_count += 1
            if artifact_count > _MAX_ARCHIVE_ARTIFACTS:
                raise ValueError("memorial_recovery_inventory_archive_invalid")
            documents.append(
                {
                    "document_relpath": f"{audience}/{child.name}",
                    "manifest_sha256": hashlib.sha256(manifest_document).hexdigest(),
                    "manifest_reference": _reference_fields(
                        manifest, _ARCHIVE_REFERENCE_FIELDS
                    ),
                    "artifacts": artifacts,
                }
            )
            if len(documents) > _MAX_ARCHIVE_DOCUMENTS:
                raise ValueError("memorial_recovery_inventory_archive_invalid")
    documents.sort(key=lambda item: str(item["document_relpath"]))
    return documents


def _consent_voice_references(*, slug: str, private_root: Path) -> dict[str, object]:
    slug_root = _contained(private_root, private_root / slug)
    tts_path = slug_root / "tts_voice.json"
    voice_path = slug_root / "voice_profile_manifest.json"
    tts_reference: dict[str, object] = {"present": False, "sha256": "", "fields": {}}
    voice_reference: dict[str, object] = {
        "present": False,
        "sha256": "",
        "manifest_version": "",
        "voice_cloning_supported": False,
        "audio_assets": [],
    }
    if tts_path.exists():
        payload, document = _read_json(tts_path, max_bytes=256 * 1024)
        tts_reference = {
            "present": True,
            "sha256": hashlib.sha256(document).hexdigest(),
            "fields": _reference_fields(payload, _CONSENT_REFERENCE_FIELDS),
        }
    if voice_path.exists():
        payload, document = _read_json(voice_path, max_bytes=1024 * 1024)
        raw_assets = payload.get("audio_assets") or []
        if not isinstance(raw_assets, list) or len(raw_assets) > _MAX_MEDIA_ITEMS:
            raise ValueError("memorial_recovery_inventory_voice_reference_invalid")
        assets: list[dict[str, object]] = []
        for raw_item in raw_assets:
            if not isinstance(raw_item, dict) or not raw_item.get("asset_relpath"):
                continue
            digest = str(raw_item.get("sha256") or "").strip().lower()
            if not _DIGEST_RE.fullmatch(digest):
                raise ValueError("memorial_recovery_inventory_voice_reference_invalid")
            size = raw_item.get("size_bytes")
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or not 0 <= size <= _MAX_MEDIA_FILE_BYTES
            ):
                raise ValueError("memorial_recovery_inventory_voice_reference_invalid")
            assets.append(
                {
                    "asset_relpath": _safe_relpath(raw_item["asset_relpath"]),
                    "sha256": digest,
                    "size_bytes": size,
                    "kind": str(raw_item.get("kind") or "")[:100],
                    "analysis_status": str(raw_item.get("analysis_status") or "")[:100],
                }
            )
        assets.sort(key=lambda item: str(item["asset_relpath"]))
        policy = (
            payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        )
        voice_reference = {
            "present": True,
            "sha256": hashlib.sha256(document).hexdigest(),
            "manifest_version": str(payload.get("manifest_version") or "")[:100],
            "voice_cloning_supported": bool(policy.get("voice_cloning_supported")),
            "audio_assets": assets,
        }
    return {"tts_voice": tts_reference, "voice_profile": voice_reference}


def _family_contribution_state(
    *, slug: str, public_root: Path, private_root: Path
) -> dict[str, object]:
    private_path = _contained(
        private_root, private_root / slug / family_contributions.PRIVATE_FILENAME
    )
    public_path = _contained(
        public_root, public_root / slug / family_contributions.PUBLIC_FILENAME
    )
    private_payload: dict[str, object] | None = None
    public_payload: dict[str, object] | None = None
    if private_path.exists():
        private_payload, _document = _read_json(private_path)
        rows = private_payload.get("contributions")
        if (
            private_payload.get("schema") != family_contributions.PRIVATE_SCHEMA
            or private_payload.get("slug") != slug
            or not isinstance(rows, list)
            or len(rows) > family_contributions.MAX_CONTRIBUTIONS
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise ValueError("memorial_recovery_inventory_family_private_invalid")
    if public_path.exists():
        public_payload, _document = _read_json(public_path)
    if public_payload is not None and private_payload is None:
        raise ValueError("memorial_recovery_inventory_family_private_missing")
    if private_payload is not None:
        expected_cards = family_contributions._public_projection_rows(  # noqa: SLF001
            [dict(row) for row in private_payload["contributions"]]
        )
        if public_payload is None and expected_cards:
            raise ValueError("memorial_recovery_inventory_family_public_missing")
        if public_payload is not None and (
            set(public_payload) != {"schema", "slug", "generated_at", "memory_cards"}
            or public_payload.get("schema") != family_contributions.PUBLIC_SCHEMA
            or public_payload.get("slug") != slug
            or not isinstance(public_payload.get("generated_at"), str)
            or len(str(public_payload.get("generated_at") or "")) > 200
            or public_payload.get("memory_cards") != expected_cards
        ):
            raise ValueError("memorial_recovery_inventory_family_public_mismatch")
    return {
        "private_present": private_payload is not None,
        "private_sha256": hashlib.sha256(
            _canonical_json_bytes(private_payload)
        ).hexdigest()
        if private_payload is not None
        else "",
        "private_payload": private_payload,
        "public_present": public_payload is not None,
        "public_sha256": hashlib.sha256(
            _canonical_json_bytes(public_payload)
        ).hexdigest()
        if public_payload is not None
        else "",
        "public_payload": public_payload,
    }


def _inventory_payload(
    *,
    slug: str,
    public_root: Path,
    private_root: Path,
    archive_root: Path,
) -> dict[str, object]:
    private_context, private_context_overrides = _private_context_inventory(
        slug=slug,
        private_root=private_root,
    )
    return {
        "authority": {
            "scope": "ea_local_noncanonical_private_recovery",
            "restores_publication_state": False,
            "private_media_restore_root": "private_profile/recovered_source_media",
            "archive_restore_root": "memorial_archive/recovered_documents",
            "compatible_snapshot_schema": "ea.memorial_local_snapshot.v2",
        },
        "slug": slug,
        "source_media": _source_media_inventory(
            slug=slug,
            public_root=public_root,
            private_root=private_root,
            private_context_overrides=private_context_overrides,
        ),
        "private_context": private_context,
        "archive_documents": _archive_documents_inventory(
            slug=slug, archive_root=archive_root
        ),
        "consent_voice_references": _consent_voice_references(
            slug=slug, private_root=private_root
        ),
        "family_contributions": _family_contribution_state(
            slug=slug,
            public_root=public_root,
            private_root=private_root,
        ),
    }


def _validate_file_payload(entry: dict[str, object], *, media: bool) -> bytes | None:
    expected = {
        "source_kind",
        "source_relpath",
        "visibility",
        "sha256",
        "size_bytes",
        "captured",
        "content_base64",
    }
    if set(entry) != expected:
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    if entry["source_kind"] not in {"private_context", "public_manifest", "voice_profile"}:
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    _safe_relpath(entry["source_relpath"])
    if entry["visibility"] not in {"public", "private"} or not isinstance(
        entry["captured"], bool
    ):
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    digest = str(entry["sha256"])
    size = entry["size_bytes"]
    encoded = entry["content_base64"]
    limit = _MAX_MEDIA_FILE_BYTES if media else _MAX_ARCHIVE_FILE_BYTES
    if (
        not _DIGEST_RE.fullmatch(digest)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 <= size <= limit
        or not isinstance(encoded, str)
    ):
        raise ValueError("memorial_recovery_inventory_file_invalid")
    if not entry["captured"]:
        if encoded:
            raise ValueError("memorial_recovery_inventory_file_invalid")
        return None
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("memorial_recovery_inventory_file_invalid") from exc
    if base64.b64encode(content).decode("ascii") != encoded or len(content) != size:
        raise ValueError("memorial_recovery_inventory_file_invalid")
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest):
        raise ValueError("memorial_recovery_inventory_file_digest_mismatch")
    return content


def _validate_private_context_payload(
    entry: object, *, expected_slug: str
) -> bytes | None:
    if not isinstance(entry, dict) or set(entry) != {
        "present",
        "source_relpath",
        "sha256",
        "size_bytes",
        "content_base64",
    }:
        raise ValueError("memorial_recovery_inventory_private_context_invalid")
    if entry.get("source_relpath") != PRIVATE_CONTEXT_FILENAME or not isinstance(
        entry.get("present"), bool
    ):
        raise ValueError("memorial_recovery_inventory_private_context_invalid")
    if entry["present"] is False:
        if entry != {
            "present": False,
            "source_relpath": PRIVATE_CONTEXT_FILENAME,
            "sha256": "",
            "size_bytes": 0,
            "content_base64": "",
        }:
            raise ValueError("memorial_recovery_inventory_private_context_invalid")
        return None
    digest = str(entry.get("sha256") or "").strip().lower()
    size = entry.get("size_bytes")
    encoded = entry.get("content_base64")
    if (
        _DIGEST_RE.fullmatch(digest) is None
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 < size <= _MAX_JSON_FILE_BYTES
        or not isinstance(encoded, str)
    ):
        raise ValueError("memorial_recovery_inventory_private_context_invalid")
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("memorial_recovery_inventory_private_context_invalid") from exc
    if (
        base64.b64encode(content).decode("ascii") != encoded
        or len(content) != size
        or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest)
    ):
        raise ValueError("memorial_recovery_inventory_private_context_digest_mismatch")
    try:
        decode_private_memorial_context_document(content, expected_slug=expected_slug)
    except MemorialPrivateContextError as exc:
        raise ValueError("memorial_recovery_inventory_private_context_invalid") from exc
    return content


def _validate_inventory_payload(
    payload: object, *, expected_slug: str
) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {
        "authority",
        "slug",
        "source_media",
        "private_context",
        "archive_documents",
        "consent_voice_references",
        "family_contributions",
    }:
        raise ValueError("memorial_recovery_inventory_invalid")
    if payload.get("slug") != expected_slug:
        raise ValueError("memorial_recovery_inventory_scope_mismatch")
    expected_authority = {
        "scope": "ea_local_noncanonical_private_recovery",
        "restores_publication_state": False,
        "private_media_restore_root": "private_profile/recovered_source_media",
        "archive_restore_root": "memorial_archive/recovered_documents",
        "compatible_snapshot_schema": "ea.memorial_local_snapshot.v2",
    }
    if payload.get("authority") != expected_authority:
        raise ValueError("memorial_recovery_inventory_authority_invalid")

    _validate_private_context_payload(
        payload.get("private_context"),
        expected_slug=expected_slug,
    )

    media = payload.get("source_media")
    if (
        not isinstance(media, list)
        or len(media) > _MAX_MEDIA_ITEMS
        or any(not isinstance(item, dict) for item in media)
    ):
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    if media != sorted(
        media,
        key=lambda item: (
            str(item.get("source_kind")),
            str(item.get("source_relpath")),
        ),
    ):
        raise ValueError("memorial_recovery_inventory_source_media_order_invalid")
    if len(
        {(item.get("source_kind"), item.get("source_relpath")) for item in media}
    ) != len(media):
        raise ValueError("memorial_recovery_inventory_source_media_invalid")
    captured: dict[str, bytes] = {}
    media_total = 0
    for item in media:
        content = _validate_file_payload(item, media=True)
        if content is not None:
            captured[str(item["sha256"])] = content
            media_total += len(content)
            if media_total > _MAX_MEDIA_TOTAL_BYTES:
                raise ValueError("memorial_recovery_inventory_source_media_too_large")
    for item in media:
        if item["captured"] is False:
            referenced = captured.get(str(item["sha256"]))
            if referenced is None or len(referenced) != item["size_bytes"]:
                raise ValueError("memorial_recovery_inventory_source_media_incomplete")

    documents = payload.get("archive_documents")
    if (
        not isinstance(documents, list)
        or len(documents) > _MAX_ARCHIVE_DOCUMENTS
        or any(not isinstance(item, dict) for item in documents)
    ):
        raise ValueError("memorial_recovery_inventory_archive_invalid")
    if documents != sorted(
        documents, key=lambda item: str(item.get("document_relpath"))
    ):
        raise ValueError("memorial_recovery_inventory_archive_order_invalid")
    artifact_total = 0
    artifact_count = 0
    for document in documents:
        if set(document) != {
            "document_relpath",
            "manifest_sha256",
            "manifest_reference",
            "artifacts",
        }:
            raise ValueError("memorial_recovery_inventory_archive_invalid")
        _safe_relpath(document["document_relpath"])
        if not _DIGEST_RE.fullmatch(str(document["manifest_sha256"])) or not isinstance(
            document["manifest_reference"], dict
        ):
            raise ValueError("memorial_recovery_inventory_archive_invalid")
        artifacts = document["artifacts"]
        if not isinstance(artifacts, list) or any(
            not isinstance(item, dict) for item in artifacts
        ):
            raise ValueError("memorial_recovery_inventory_archive_invalid")
        for artifact in artifacts:
            if set(artifact) != {
                "artifact_key",
                "relpath",
                "sha256",
                "size_bytes",
                "content_base64",
            }:
                raise ValueError("memorial_recovery_inventory_archive_invalid")
            if (
                not isinstance(artifact["artifact_key"], str)
                or len(artifact["artifact_key"]) > 100
            ):
                raise ValueError("memorial_recovery_inventory_archive_invalid")
            _safe_relpath(artifact["relpath"])
            proxy = {
                "source_kind": "public_manifest",
                "source_relpath": artifact["relpath"],
                "visibility": "private",
                "sha256": artifact["sha256"],
                "size_bytes": artifact["size_bytes"],
                "captured": True,
                "content_base64": artifact["content_base64"],
            }
            content = _validate_file_payload(proxy, media=False)
            artifact_total += len(content or b"")
            artifact_count += 1
            if (
                artifact_total > _MAX_ARCHIVE_TOTAL_BYTES
                or artifact_count > _MAX_ARCHIVE_ARTIFACTS
            ):
                raise ValueError("memorial_recovery_inventory_archive_too_large")

    references = payload.get("consent_voice_references")
    if not isinstance(references, dict) or set(references) != {
        "tts_voice",
        "voice_profile",
    }:
        raise ValueError("memorial_recovery_inventory_reference_invalid")
    if len(_canonical_json_bytes(references)) > 1024 * 1024:
        raise ValueError("memorial_recovery_inventory_reference_invalid")

    state = payload.get("family_contributions")
    if not isinstance(state, dict) or set(state) != {
        "private_present",
        "private_sha256",
        "private_payload",
        "public_present",
        "public_sha256",
        "public_payload",
    }:
        raise ValueError("memorial_recovery_inventory_family_invalid")
    for scope in ("private", "public"):
        present = state[f"{scope}_present"]
        digest = state[f"{scope}_sha256"]
        value = state[f"{scope}_payload"]
        if not isinstance(present, bool) or (
            not present and (digest != "" or value is not None)
        ):
            raise ValueError("memorial_recovery_inventory_family_invalid")
        if present and (
            not isinstance(value, dict)
            or not _DIGEST_RE.fullmatch(str(digest))
            or not hmac.compare_digest(
                hashlib.sha256(_canonical_json_bytes(value)).hexdigest(), str(digest)
            )
        ):
            raise ValueError("memorial_recovery_inventory_family_digest_mismatch")
    if state["public_present"] and not state["private_present"]:
        raise ValueError("memorial_recovery_inventory_family_private_missing")
    if state["private_present"]:
        private_payload = state["private_payload"]
        assert isinstance(private_payload, dict)
        rows = private_payload.get("contributions")
        if (
            private_payload.get("schema") != family_contributions.PRIVATE_SCHEMA
            or private_payload.get("slug") != expected_slug
            or not isinstance(rows, list)
            or len(rows) > family_contributions.MAX_CONTRIBUTIONS
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise ValueError("memorial_recovery_inventory_family_private_invalid")
        expected_cards = family_contributions._public_projection_rows(
            [dict(row) for row in rows]
        )  # noqa: SLF001
        if expected_cards and not state["public_present"]:
            raise ValueError("memorial_recovery_inventory_family_public_missing")
        if state["public_present"]:
            public_payload = state["public_payload"]
            assert isinstance(public_payload, dict)
            if (
                set(public_payload)
                != {"schema", "slug", "generated_at", "memory_cards"}
                or public_payload.get("schema") != family_contributions.PUBLIC_SCHEMA
                or public_payload.get("slug") != expected_slug
                or not isinstance(public_payload.get("generated_at"), str)
                or len(str(public_payload.get("generated_at") or "")) > 200
                or public_payload.get("memory_cards") != expected_cards
            ):
                raise ValueError("memorial_recovery_inventory_family_public_mismatch")
    return payload


def _ensure_parent(root: Path, parent: Path, *, private: bool) -> None:
    absolute_root = _absolute(root)
    absolute_parent = _contained(absolute_root, parent, allow_root=True)
    absolute_root.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(absolute_root)
    relative = absolute_parent.relative_to(absolute_root)
    current = absolute_root
    for part in relative.parts:
        current = current / part
        current.mkdir(mode=0o700 if private else 0o755, exist_ok=True)
        _reject_symlink_components(current)
        if not current.is_dir():
            raise ValueError("memorial_recovery_inventory_path_invalid")
        os.chmod(current, 0o700 if private else 0o755, follow_symlinks=False)


def _atomic_write(path: Path, content: bytes, *, mode: int, root: Path) -> None:
    private = mode == 0o600
    _ensure_parent(root, path.parent, private=private)
    target = _contained(root, path)
    if os.path.lexists(target):
        raise FileExistsError(target)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
        directory_descriptor = os.open(
            target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _snapshot_root(*, slug: str, private_root: Path) -> Path:
    return _contained(private_root, private_root / slug / "recovery_snapshots")


def _load_verified_inventory(
    *,
    inventory_path: str,
    expected_slug: str,
    private_root: Path,
) -> tuple[dict[str, object], str, str]:
    slug = _safe_slug(expected_slug)
    source = Path(str(inventory_path or "").strip()).expanduser()
    if not str(inventory_path or "").strip():
        raise ValueError("memorial_recovery_inventory_file_invalid")
    root = _snapshot_root(slug=slug, private_root=private_root)
    source = _contained(root, source)
    if source.parent != _absolute(root):
        raise ValueError("memorial_recovery_inventory_file_invalid")
    document = _read_regular_file(source, max_bytes=_MAX_INVENTORY_BYTES)
    if stat.S_IMODE(source.stat().st_mode) & 0o077:
        raise ValueError("memorial_recovery_inventory_file_not_private")
    envelope = _decode_json_bytes(document)
    if (
        set(envelope) != {"schema", "payload_sha256", "payload"}
        or envelope.get("schema") != INVENTORY_SCHEMA
    ):
        raise ValueError("memorial_recovery_inventory_invalid")
    payload_sha256 = str(envelope.get("payload_sha256") or "")
    payload = _validate_inventory_payload(envelope.get("payload"), expected_slug=slug)
    actual_digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    if not _DIGEST_RE.fullmatch(payload_sha256) or not hmac.compare_digest(
        payload_sha256, actual_digest
    ):
        raise ValueError("memorial_recovery_inventory_payload_digest_mismatch")
    return payload, payload_sha256, hashlib.sha256(document).hexdigest()


def materialize_memorial_recovery_inventory(
    *,
    memorial_slug: str,
    destination_path: str,
    public_root: Path | None = None,
    private_root: Path | None = None,
    archive_root: Path | None = None,
) -> dict[str, object]:
    slug = _safe_slug(memorial_slug)
    public = _absolute(public_root or _default_public_root())
    private = _absolute(private_root or _default_private_root())
    archive = _absolute(archive_root or _default_archive_root())
    destination = Path(str(destination_path or "").strip()).expanduser()
    if not str(destination_path or "").strip():
        raise ValueError("memorial_recovery_inventory_destination_invalid")
    root = _snapshot_root(slug=slug, private_root=private)
    destination = _contained(root, destination)
    if destination.parent != _absolute(root):
        raise ValueError("memorial_recovery_inventory_destination_invalid")
    if os.path.lexists(destination):
        raise ValueError("memorial_recovery_inventory_destination_exists")
    payload = _inventory_payload(
        slug=slug, public_root=public, private_root=private, archive_root=archive
    )
    _validate_inventory_payload(payload, expected_slug=slug)
    payload_sha256 = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    envelope = {
        "schema": INVENTORY_SCHEMA,
        "payload_sha256": payload_sha256,
        "payload": payload,
    }
    document = _canonical_json_bytes(envelope) + b"\n"
    if len(document) > _MAX_INVENTORY_BYTES:
        raise ValueError("memorial_recovery_inventory_file_too_large")
    try:
        _atomic_write(destination, document, mode=0o600, root=private)
    except FileExistsError as exc:
        raise ValueError("memorial_recovery_inventory_destination_exists") from exc
    return {
        "schema": INVENTORY_SCHEMA,
        "memorial_slug": slug,
        "inventory_path": str(destination),
        "payload_sha256": payload_sha256,
        "inventory_file_sha256": hashlib.sha256(document).hexdigest(),
        "source_media_count": len(payload["source_media"]),
        "archive_document_count": len(payload["archive_documents"]),
        "private_context_present": bool(payload["private_context"]["present"]),
        "family_private_present": bool(
            payload["family_contributions"]["private_present"]
        ),
        "family_public_present": bool(
            payload["family_contributions"]["public_present"]
        ),
        "private_file_mode": "0600",
        "canonical_publication_state_included": False,
        "private_media_publication_performed": False,
    }


def verify_memorial_recovery_inventory(
    *,
    inventory_path: str,
    expected_memorial_slug: str,
    private_root: Path | None = None,
) -> dict[str, object]:
    private = _absolute(private_root or _default_private_root())
    payload, payload_sha256, file_sha256 = _load_verified_inventory(
        inventory_path=inventory_path,
        expected_slug=expected_memorial_slug,
        private_root=private,
    )
    family = payload["family_contributions"]
    return {
        "valid": True,
        "schema": INVENTORY_SCHEMA,
        "memorial_slug": payload["slug"],
        "payload_sha256": payload_sha256,
        "inventory_file_sha256": file_sha256,
        "source_media_count": len(payload["source_media"]),
        "archive_document_count": len(payload["archive_documents"]),
        "private_context_present": bool(payload["private_context"]["present"]),
        "family_private_present": bool(family["private_present"]),
        "family_public_present": bool(family["public_present"]),
        "canonical_publication_state_included": False,
        "private_media_publication_performed": False,
    }


def _restore_writes(
    *,
    payload: dict[str, object],
    public_root: Path,
    private_root: Path,
    archive_root: Path,
) -> list[tuple[Path, bytes, int, Path]]:
    slug = str(payload["slug"])
    writes: list[tuple[Path, bytes, int, Path]] = []
    private_context_content = _validate_private_context_payload(
        payload["private_context"],
        expected_slug=slug,
    )
    if private_context_content is not None:
        writes.append(
            (
                _contained(
                    private_root,
                    private_root / slug / PRIVATE_CONTEXT_FILENAME,
                ),
                private_context_content,
                0o600,
                private_root,
            )
        )
    captured = {
        str(item["sha256"]): base64.b64decode(
            str(item["content_base64"]), validate=True
        )
        for item in payload["source_media"]
        if item["captured"] is True
    }
    for item in payload["source_media"]:
        content = captured[str(item["sha256"])]
        relpath = _safe_relpath(item["source_relpath"])
        target = (
            private_root
            / slug
            / "recovered_source_media"
            / str(item["source_kind"])
            / relpath
        )
        writes.append((_contained(private_root, target), content, 0o600, private_root))
    for document in payload["archive_documents"]:
        document_relpath = _safe_relpath(document["document_relpath"])
        base = archive_root / slug / "recovered_documents" / document_relpath
        reference = {
            "schema": REFERENCE_SCHEMA,
            "slug": slug,
            "document_relpath": document_relpath,
            "source_manifest_sha256": document["manifest_sha256"],
            "manifest_reference": document["manifest_reference"],
        }
        writes.append(
            (
                _contained(archive_root, base / "manifest.reference.json"),
                _canonical_json_bytes(reference) + b"\n",
                0o600,
                archive_root,
            )
        )
        for artifact in document["artifacts"]:
            content = base64.b64decode(str(artifact["content_base64"]), validate=True)
            writes.append(
                (
                    _contained(archive_root, base / _safe_relpath(artifact["relpath"])),
                    content,
                    0o600,
                    archive_root,
                )
            )
    references = {
        "schema": REFERENCE_SCHEMA,
        "slug": slug,
        "consent_voice_references": payload["consent_voice_references"],
    }
    writes.append(
        (
            _contained(
                private_root, private_root / slug / "recovery_inventory.references.json"
            ),
            _canonical_json_bytes(references) + b"\n",
            0o600,
            private_root,
        )
    )
    state = payload["family_contributions"]
    if state["private_present"]:
        writes.append(
            (
                _contained(
                    private_root,
                    private_root / slug / family_contributions.PRIVATE_FILENAME,
                ),
                _canonical_json_bytes(state["private_payload"]) + b"\n",
                0o600,
                private_root,
            )
        )
    if state["public_present"]:
        writes.append(
            (
                _contained(
                    public_root,
                    public_root / slug / family_contributions.PUBLIC_FILENAME,
                ),
                _canonical_json_bytes(state["public_payload"]) + b"\n",
                0o644,
                public_root,
            )
        )
    unique: dict[str, tuple[Path, bytes, int, Path]] = {}
    for write in writes:
        key = str(write[0])
        if key in unique and unique[key][1:] != write[1:]:
            raise ValueError("memorial_recovery_inventory_restore_path_conflict")
        unique[key] = write
    return list(unique.values())


def restore_memorial_recovery_inventory(
    *,
    inventory_path: str,
    expected_memorial_slug: str,
    dry_run: bool = True,
    confirmed_payload_sha256: str = "",
    public_root: Path | None = None,
    private_root: Path | None = None,
    archive_root: Path | None = None,
) -> dict[str, object]:
    if not isinstance(dry_run, bool):
        raise ValueError("memorial_recovery_inventory_dry_run_invalid")
    slug = _safe_slug(expected_memorial_slug)
    public = _absolute(public_root or _default_public_root())
    private = _absolute(private_root or _default_private_root())
    archive = _absolute(archive_root or _default_archive_root())
    payload, payload_sha256, file_sha256 = _load_verified_inventory(
        inventory_path=inventory_path,
        expected_slug=slug,
        private_root=private,
    )
    if not dry_run:
        confirmation = str(confirmed_payload_sha256 or "")
        if not confirmation:
            raise ValueError("memorial_recovery_inventory_apply_confirmation_required")
        if not hmac.compare_digest(confirmation, payload_sha256):
            raise ValueError("memorial_recovery_inventory_apply_confirmation_mismatch")
    writes = _restore_writes(
        payload=payload, public_root=public, private_root=private, archive_root=archive
    )
    to_create: list[tuple[Path, bytes, int, Path]] = []
    existing: list[tuple[Path, bytes, int, Path]] = []
    for write in writes:
        path, content, mode, _root = write
        try:
            current = _read_regular_file(path, max_bytes=max(len(content), 1))
        except FileNotFoundError:
            to_create.append(write)
            continue
        except (OSError, ValueError) as exc:
            raise ValueError(
                "memorial_recovery_inventory_restore_target_invalid"
            ) from exc
        if not hmac.compare_digest(
            hashlib.sha256(current).digest(), hashlib.sha256(content).digest()
        ):
            raise ValueError("memorial_recovery_inventory_restore_target_conflict")
        existing.append(write)
    result = {
        "schema": INVENTORY_SCHEMA,
        "mode": "merge",
        "dry_run": dry_run,
        "memorial_slug": slug,
        "payload_sha256": payload_sha256,
        "inventory_file_sha256": file_sha256,
        "files_in_inventory": len(writes),
        "files_to_create": len(to_create),
        "files_existing": len(existing),
        "files_created": 0,
        "apply_confirmation_matched": not dry_run,
        "atomic_file_writes": True,
        "idempotent_merge": True,
        "private_context_present": bool(payload["private_context"]["present"]),
        "canonical_publication_state_restored": False,
        "private_media_published": False,
    }
    if dry_run:
        return result
    for path, content, mode, root in to_create:
        try:
            _atomic_write(path, content, mode=mode, root=root)
        except FileExistsError:
            try:
                raced = _read_regular_file(path, max_bytes=max(len(content), 1))
            except (OSError, ValueError) as exc:
                raise ValueError(
                    "memorial_recovery_inventory_restore_target_conflict"
                ) from exc
            if not hmac.compare_digest(
                hashlib.sha256(raced).digest(), hashlib.sha256(content).digest()
            ):
                raise ValueError("memorial_recovery_inventory_restore_target_conflict")
        os.chmod(path, mode, follow_symlinks=False)
        result["files_created"] = int(result["files_created"]) + 1
    for path, _content, mode, _root in existing:
        os.chmod(path, mode, follow_symlinks=False)
    return result
