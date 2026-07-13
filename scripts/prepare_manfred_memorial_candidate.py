#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_projection.v2"
PROJECT_NAME_PREFIX = "ea-manfred-candidate-"
PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
HELPER_IMAGE = "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229"
PUBLIC_GIT_FILES = (
    "memorial.json",
    "archive_registry.json",
    "archive_registry.generated.json",
)
PRIVATE_METADATA_FILES = (
    PRIVATE_CONTEXT_FILENAME,
    "audio_identification_safe_profile.json",
    "llm_profile_notes.json",
    "mail_cluster_report.json",
    "ratings.json",
    "transcript_persona_workflow.md",
    "transcript_signal_report.json",
    "tts_voice.json",
    "voice_ab.json",
    "voice_ab_challengers.json",
    "voice_profile_manifest.json",
)
PUBLIC_ASSET_SUFFIXES = {
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".svg",
    ".wav",
    ".webp",
}
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024


def _validate_project_name(value: object) -> str:
    project = str(value or "").strip()
    suffix = project.removeprefix(PROJECT_NAME_PREFIX)
    if (
        project != project.lower()
        or project == "ea"
        or not project.startswith(PROJECT_NAME_PREFIX)
        or len(project) > 63
        or len(suffix) < 8
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*", suffix) is None
    ):
        raise ValueError("manfred_candidate_project_name_invalid")
    return project


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _commit(source_root: Path, ref: str) -> str:
    value = (
        _run(
            [
                "git",
                "rev-parse",
                "--verify",
                f"{str(ref or 'HEAD').strip()}^{{commit}}",
            ],
            cwd=source_root,
        )
        .decode("ascii")
        .strip()
        .lower()
    )
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("manfred_candidate_commit_invalid")
    return value


def _git_blob(source_root: Path, commit: str, path: str) -> bytes:
    return _run(["git", "show", f"{commit}:{path}"], cwd=source_root)


def _safe_relative(value: object, *, suffix_required: bool = False) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("manfred_candidate_asset_path_invalid")
    path = Path(*pure.parts)
    if suffix_required and path.suffix.lower() not in PUBLIC_ASSET_SUFFIXES:
        raise ValueError("manfred_candidate_asset_type_forbidden")
    return path


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _copy_regular(
    source: Path, destination: Path, *, maximum: int, mode: int
) -> dict[str, object]:
    try:
        metadata = source.lstat()
    except OSError as exc:
        raise ValueError("manfred_candidate_source_asset_missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("manfred_candidate_source_asset_invalid")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise ValueError("manfred_candidate_source_asset_size_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = source.read_bytes()
    if len(content) != metadata.st_size:
        raise ValueError("manfred_candidate_source_asset_changed")
    destination.write_bytes(content)
    destination.chmod(mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _write_bytes(destination: Path, content: bytes, *, mode: int) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_bytes(content)
    destination.chmod(mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _load_private_context(
    source_root: Path, slug: str
) -> tuple[dict[str, object], bytes]:
    app_root = source_root / "ea"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from app.services.memorial_private_context import (  # noqa: PLC0415
        read_private_memorial_context_document,
    )

    return read_private_memorial_context_document(
        private_root=source_root / "memorial_data" / "private_memorial_profiles",
        slug=slug,
    )


def _declared_assets(
    public_payload: dict[str, object], private_overrides: dict[str, object]
) -> dict[Path, int]:
    merged = dict(public_payload)
    merged.update(private_overrides)
    assets: dict[Path, int] = {}

    def add(value: object, *, private: bool) -> None:
        if not str(value or "").strip():
            return
        assets[_safe_relative(value, suffix_required=True)] = (
            0o400 if private else 0o444
        )

    for field in ("audio_clips", "public_documents", "candidate_recordings"):
        rows = merged.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            visibility = str(row.get("visibility") or "").strip().lower()
            add(row.get("asset_relpath"), private=visibility != "public")
    for field in ("pwa_icon", "video_call_avatar"):
        row = merged.get(field)
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if "relpath" in str(key) or str(key).startswith("src_"):
                add(value, private=False)
    return assets


def _copy_archive(
    *, source_root: Path, commit: str, destination: Path
) -> list[dict[str, object]]:
    archive = _run(
        ["git", "archive", "--format=tar", commit, "memorial_archive/manfred/public"],
        cwd=source_root,
    )
    receipts: list[dict[str, object]] = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("manfred_candidate_archive_entry_invalid")
            relative = _safe_relative(member.name)
            prefix = Path("memorial_archive")
            try:
                projected = relative.relative_to(prefix)
            except ValueError as exc:
                raise ValueError("manfred_candidate_archive_path_invalid") from exc
            extracted = bundle.extractfile(member)
            if extracted is None:
                raise ValueError("manfred_candidate_archive_entry_invalid")
            content = extracted.read(MAX_ARCHIVE_BYTES + 1)
            total += len(content)
            if len(content) != member.size or total > MAX_ARCHIVE_BYTES:
                raise ValueError("manfred_candidate_archive_size_invalid")
            target = destination / projected
            info = _write_bytes(target, content, mode=0o444)
            receipts.append({"path": projected.as_posix(), **info})
    return sorted(receipts, key=lambda item: str(item["path"]))


def _tree_digest(root: Path) -> tuple[str, list[dict[str, object]]]:
    def directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_projection_root_invalid") from exc
    rows: list[dict[str, object]] = []
    try:
        root_metadata = os.fstat(root_descriptor)
        try:
            root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_projection_root_invalid") from exc
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_path_metadata.st_mode)
            or stat.S_IMODE(root_metadata.st_mode) != 0o550
            or (root_metadata.st_dev, root_metadata.st_ino)
            != (root_path_metadata.st_dev, root_path_metadata.st_ino)
        ):
            raise ValueError("manfred_candidate_projection_root_invalid")

        def walk(directory_descriptor: int, relative: tuple[str, ...]) -> None:
            before = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o550
            ):
                raise ValueError("manfred_candidate_projection_directory_mode_invalid")
            try:
                with os.scandir(directory_descriptor) as iterator:
                    entries = sorted(iterator, key=lambda row: row.name)
            except OSError as exc:
                raise ValueError("manfred_candidate_projection_entry_invalid") from exc
            for entry in entries:
                name = entry.name
                try:
                    initial = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_projection_changed_during_digest"
                    ) from exc
                projected = (*relative, name)
                if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                    try:
                        child_descriptor = os.open(
                            name,
                            directory_flags,
                            dir_fd=directory_descriptor,
                        )
                    except OSError as exc:
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        ) from exc
                    try:
                        opened = os.fstat(child_descriptor)
                        if (
                            directory_identity(initial) != directory_identity(opened)
                            or stat.S_IMODE(opened.st_mode) != 0o550
                        ):
                            raise ValueError(
                                "manfred_candidate_projection_changed_during_digest"
                            )
                        walk(child_descriptor, projected)
                        if directory_identity(opened) != directory_identity(
                            os.fstat(child_descriptor)
                        ):
                            raise ValueError(
                                "manfred_candidate_projection_changed_during_digest"
                            )
                    finally:
                        os.close(child_descriptor)
                    continue
                if not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode):
                    raise ValueError("manfred_candidate_projection_entry_invalid")
                if initial.st_nlink != 1:
                    raise ValueError("manfred_candidate_projection_file_links_invalid")
                mode = stat.S_IMODE(initial.st_mode)
                if mode not in {0o440, 0o444}:
                    raise ValueError("manfred_candidate_projection_file_mode_invalid")
                try:
                    file_descriptor = os.open(
                        name,
                        file_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_projection_changed_during_digest"
                    ) from exc
                try:
                    opened = os.fstat(file_descriptor)
                    if (
                        file_identity(initial) != file_identity(opened)
                        or not stat.S_ISREG(opened.st_mode)
                        or opened.st_nlink != 1
                    ):
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        )
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = os.read(file_descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                    final = os.fstat(file_descriptor)
                    if file_identity(opened) != file_identity(final) or size != int(
                        opened.st_size
                    ):
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        )
                finally:
                    os.close(file_descriptor)
                rows.append(
                    {
                        "path": PurePosixPath(*projected).as_posix(),
                        "sha256": digest.hexdigest(),
                        "size_bytes": size,
                        "mode": format(mode, "03o"),
                    }
                )
            if directory_identity(before) != directory_identity(
                os.fstat(directory_descriptor)
            ):
                raise ValueError("manfred_candidate_projection_changed_during_digest")

        walk(root_descriptor, ())
        final_root_metadata = os.fstat(root_descriptor)
        try:
            final_root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(
                "manfred_candidate_projection_changed_during_digest"
            ) from exc
        if directory_identity(root_metadata) != directory_identity(
            final_root_metadata
        ) or (final_root_metadata.st_dev, final_root_metadata.st_ino) != (
            final_root_path_metadata.st_dev,
            final_root_path_metadata.st_ino,
        ):
            raise ValueError("manfred_candidate_projection_changed_during_digest")
    finally:
        os.close(root_descriptor)
    encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _sha256(encoded), rows


def _set_modes(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o550)
        elif path.is_file():
            current = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o440 if current & 0o044 == 0 else 0o444)
    root.chmod(0o550)


def _make_tree_removable(root: Path) -> None:
    if not root.exists():
        return
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)


def _install_or_verify_release(
    *,
    staging: Path,
    release_root: Path,
    projection_sha256: str,
    projected_files: list[dict[str, object]],
) -> None:
    if release_root.exists():
        if release_root.is_symlink() or not release_root.is_dir():
            raise ValueError("manfred_candidate_existing_release_invalid")
        try:
            existing_sha256, existing_files = _tree_digest(release_root)
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_existing_release_unverifiable") from exc
        if existing_sha256 != projection_sha256 or existing_files != projected_files:
            raise ValueError("manfred_candidate_existing_release_digest_mismatch")
        _make_tree_removable(staging)
        shutil.rmtree(staging)
        return
    os.replace(staging, release_root)


def _chown_for_runtime(paths: list[Path], *, uid: int, gid: int) -> None:
    if os.geteuid() == 0:
        for root in paths:
            os.chown(root, uid, gid)
            for path in root.rglob("*"):
                os.chown(path, uid, gid, follow_symlinks=False)
        return
    command = (
        "chown -R "
        + f"{uid}:{gid} "
        + " ".join(f"/target/{index}" for index in range(len(paths)))
    )
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0:0",
        "--read-only",
        "--pull",
        "never",
        "--entrypoint",
        "/bin/sh",
    ]
    for index, path in enumerate(paths):
        argv.extend(["--volume", f"{path.resolve()}:/target/{index}:rw"])
    argv.extend([HELPER_IMAGE, "-ec", command])
    _run(argv)


def _validate_public_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    try:
        parsed = urlparse(normalized)
    except ValueError as exc:
        raise ValueError("manfred_candidate_public_base_url_invalid") from exc
    host = str(parsed.hostname or "").strip().lower().strip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or parsed.path not in {"", "/"}
        or host in {"localhost", "127.0.0.1", "example.test", "example.invalid"}
        or host.endswith(".invalid")
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".test")
    ):
        raise ValueError("manfred_candidate_public_base_url_invalid")
    return normalized


def _image_revision(image: str) -> tuple[str, str]:
    if not image or image.lower() == "latest" or image.lower().endswith(":latest"):
        raise ValueError("manfred_candidate_image_tag_invalid")
    payload = json.loads(_run(["docker", "image", "inspect", image]))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("manfred_candidate_image_missing")
    row = payload[0]
    labels = dict((row.get("Config") or {}).get("Labels") or {})
    return str(row.get("Id") or ""), str(
        labels.get("org.opencontainers.image.revision") or ""
    )


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("manfred_candidate_env_permissions_invalid")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("manfred_candidate_env_invalid")
        key, value = line.split("=", 1)
        if not key or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in key
        ):
            raise ValueError("manfred_candidate_env_invalid")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("manfred_candidate_env_invalid")
        values[key] = value
    return values


def _write_env(
    *,
    path: Path,
    image: str,
    release_root: Path,
    runtime_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    rotate_secrets: bool = False,
) -> None:
    current = _parse_env(path)
    postgres_password = (
        "" if rotate_secrets else current.get("EA_MANFRED_POSTGRES_PASSWORD", "")
    ) or secrets.token_hex(32)
    api_token = (
        "" if rotate_secrets else current.get("EA_API_TOKEN", "")
    ) or secrets.token_urlsafe(48)
    signing_secret = (
        "" if rotate_secrets else current.get("EA_SIGNING_SECRET", "")
    ) or secrets.token_urlsafe(64)
    values = {
        "EA_MANFRED_COMPOSE_PROJECT": _validate_project_name(project_name),
        "EA_MANFRED_IMAGE": image,
        "EA_MANFRED_ENV_FILE": str(path.resolve()),
        "EA_MANFRED_RELEASE_ROOT": str(release_root.resolve()),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root.resolve()),
        "EA_MANFRED_HOST_PORT": str(host_port),
        "EA_MANFRED_POSTGRES_PASSWORD": postgres_password,
        "DATABASE_URL": f"postgresql://ea:{postgres_password}@postgres:5432/ea",
        "EA_API_TOKEN": api_token,
        "EA_SIGNING_SECRET": signing_secret,
        "EA_PUBLIC_APP_BASE_URL": public_base_url,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            for key in sorted(values):
                handle.write(f"{key}={values[key]}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def prepare_candidate(
    *,
    source_root: Path,
    ref: str,
    image: str,
    deploy_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    runtime_uid: int = 10001,
    runtime_gid: int = 10001,
    rotate_secrets: bool = False,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    deploy_root = deploy_root.expanduser().resolve()
    if not 1024 <= host_port <= 65535:
        raise ValueError("manfred_candidate_host_port_invalid")
    project_name = _validate_project_name(project_name)
    public_base_url = _validate_public_base_url(public_base_url)
    commit = _commit(source_root, ref)
    image_id, image_commit = _image_revision(image)
    if image_commit != commit:
        raise ValueError("manfred_candidate_image_revision_mismatch")

    slug = "manfred"
    public_documents: dict[str, bytes] = {}
    for name in PUBLIC_GIT_FILES:
        public_documents[name] = _git_blob(
            source_root,
            commit,
            f"memorial_data/public_memorials/{slug}/{name}",
        )
    try:
        public_payload = json.loads(public_documents["memorial.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manfred_candidate_public_manifest_invalid") from exc
    if not isinstance(public_payload, dict) or public_payload.get("slug") != slug:
        raise ValueError("manfred_candidate_public_manifest_invalid")
    private_overrides, private_document = _load_private_context(source_root, slug)

    releases_root = deploy_root / "releases"
    receipts_root = deploy_root / "receipts"
    runtime_root = deploy_root / "runtime"
    releases_root.mkdir(parents=True, exist_ok=True)
    receipts_root.mkdir(parents=True, exist_ok=True)
    staging = releases_root / f".{commit[:12]}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(mode=0o700)
    try:
        public_root = staging / "public_memorials" / slug
        private_root = staging / "private_memorial_profiles" / slug
        archive_root = staging / "memorial_archive"
        file_receipts: list[dict[str, object]] = []
        for name, content in public_documents.items():
            info = _write_bytes(public_root / name, content, mode=0o444)
            file_receipts.append({"path": f"public_memorials/{slug}/{name}", **info})
        public_source = source_root / "memorial_data" / "public_memorials" / slug
        for relative, mode in sorted(
            _declared_assets(public_payload, private_overrides).items(),
            key=lambda item: item[0].as_posix(),
        ):
            info = _copy_regular(
                public_source / relative,
                public_root / relative,
                maximum=MAX_ASSET_BYTES,
                mode=mode,
            )
            file_receipts.append(
                {"path": f"public_memorials/{slug}/{relative.as_posix()}", **info}
            )

        private_source = (
            source_root / "memorial_data" / "private_memorial_profiles" / slug
        )
        for name in PRIVATE_METADATA_FILES:
            source = private_source / name
            if name == PRIVATE_CONTEXT_FILENAME:
                info = _write_bytes(private_root / name, private_document, mode=0o400)
            elif source.exists():
                info = _copy_regular(
                    source, private_root / name, maximum=8 * 1024 * 1024, mode=0o400
                )
            else:
                continue
            file_receipts.append(
                {"path": f"private_memorial_profiles/{slug}/{name}", **info}
            )

        voice_manifest_path = private_source / "voice_profile_manifest.json"
        if voice_manifest_path.is_file():
            voice_manifest = json.loads(voice_manifest_path.read_text(encoding="utf-8"))
            for item in list(voice_manifest.get("audio_assets") or []):
                if not isinstance(item, dict):
                    continue
                relative_value = str(item.get("asset_relpath") or "").strip()
                if not relative_value.startswith("voice_profile/"):
                    continue
                relative = _safe_relative(relative_value, suffix_required=True)
                info = _copy_regular(
                    private_source / relative,
                    private_root / relative,
                    maximum=MAX_ASSET_BYTES,
                    mode=0o400,
                )
                file_receipts.append(
                    {
                        "path": f"private_memorial_profiles/{slug}/{relative.as_posix()}",
                        **info,
                    }
                )
        curated = Path("voice_profile/curated/unmixr-challenger-youtube-v5.wav")
        if (private_source / curated).is_file():
            info = _copy_regular(
                private_source / curated,
                private_root / curated,
                maximum=MAX_ASSET_BYTES,
                mode=0o400,
            )
            file_receipts.append(
                {
                    "path": f"private_memorial_profiles/{slug}/{curated.as_posix()}",
                    **info,
                }
            )

        archive_receipts = _copy_archive(
            source_root=source_root,
            commit=commit,
            destination=archive_root,
        )
        file_receipts.extend(
            {
                "path": f"memorial_archive/{row['path']}",
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            for row in archive_receipts
        )
        _set_modes(staging)
        projection_sha256, projected_files = _tree_digest(staging)
        release_id = f"{commit[:12]}-{projection_sha256[:12]}"
        release_root = releases_root / release_id
        _install_or_verify_release(
            staging=staging,
            release_root=release_root,
            projection_sha256=projection_sha256,
            projected_files=projected_files,
        )

        public_contributions = runtime_root / "public-contributions"
        private_contributions = runtime_root / "private-contributions"
        state_root = runtime_root / "state"
        for path, mode in (
            (public_contributions, 0o700),
            (private_contributions, 0o700),
            (state_root, 0o700),
        ):
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                path.chmod(mode)
        operator_gid = os.getgid()
        _chown_for_runtime([release_root], uid=runtime_uid, gid=operator_gid)
        _chown_for_runtime(
            [public_contributions, private_contributions, state_root],
            uid=runtime_uid,
            gid=runtime_gid,
        )

        env_path = deploy_root / "candidate.env"
        _write_env(
            path=env_path,
            image=image,
            release_root=release_root,
            runtime_root=runtime_root,
            public_base_url=public_base_url,
            host_port=host_port,
            project_name=project_name,
            rotate_secrets=rotate_secrets,
        )
        created_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "pass",
            "created_at": created_at,
            "commit": commit,
            "image": image,
            "image_id": image_id,
            "release_id": release_id,
            "release_root": str(release_root),
            "runtime_root": str(runtime_root),
            "env_file": str(env_path),
            "host_port": host_port,
            "compose_project": project_name,
            "projection_sha256": projection_sha256,
            "private_context_sha256": _sha256(private_document),
            "file_count": len(projected_files),
            "projection_bytes": sum(int(row["size_bytes"]) for row in projected_files),
            "tracked_public_manifest": True,
            "tracked_public_archive_only": True,
            "private_context_in_image": False,
            "provider_credentials_in_candidate_env": False,
            "candidate_secrets_rotated": rotate_secrets,
            "runtime_uid": runtime_uid,
            "runtime_gid": runtime_gid,
            "projection_operator_gid": operator_gid,
            "spatial_handoff_included": False,
        }
        _atomic_receipt(receipts_root / f"{release_id}.json", receipt)
        return receipt
    finally:
        if staging.exists():
            _make_tree_removable(staging)
            shutil.rmtree(staging)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a private, hash-receipted Manfred Memorial candidate projection."
    )
    parser.add_argument(
        "--source-root", default=str(Path(__file__).resolve().parents[1])
    )
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--deploy-root",
        default=str(Path("~/.local/share/ea-deploy/manfred-memorial")),
    )
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--host-port", type=int, default=18090)
    parser.add_argument(
        "--project-name",
        required=True,
        help="Unique ea-manfred-candidate-<deployment> Compose project name.",
    )
    parser.add_argument("--rotate-secrets", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = prepare_candidate(
            source_root=Path(args.source_root),
            ref=args.ref,
            image=args.image,
            deploy_root=Path(args.deploy_root),
            public_base_url=args.public_base_url,
            host_port=args.host_port,
            project_name=args.project_name,
            rotate_secrets=args.rotate_secrets,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "private_material_included": False,
                    "provider_credentials_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
