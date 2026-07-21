#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.prepare_manfred_memorial_candidate import _validate_project_name


REGISTRY_SCHEMA = "ea.manfred_memorial_candidate_registry.v1"
RUNTIME_SCHEMA = "ea.manfred_memorial_candidate_runtime.v3"
RUNTIME_SCHEMAS = frozenset(
    {
        RUNTIME_SCHEMA,
        "ea.manfred_memorial_candidate_runtime.v4",
    }
)
MAX_REGISTRY_ENTRIES = 128
MAX_PENDING_ENTRIES = 16
MAX_JSON_BYTES = 1024 * 1024
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_LOCATOR = re.compile(r"ea-runtime:(?:manfred|memorial)-[0-9a-f]{40}")


def operator_state_root() -> Path:
    try:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError) as exc:
        raise RuntimeError("manfred_candidate_registry_operator_home_invalid") from exc
    if not home.is_absolute():
        raise RuntimeError("manfred_candidate_registry_operator_home_invalid")
    return home / ".local/state/ea"


def default_registry_path() -> Path:
    return operator_state_root() / "manfred-candidate-registry.json"


def _read_private_json(path: Path, *, missing_ok: bool = False) -> tuple[dict[str, object], str] | None:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
    if missing_ok and not os.path.lexists(absolute):
        return None
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_registry_path_invalid") from exc
    if resolved != absolute.absolute() or resolved.is_symlink():
        raise RuntimeError("manfred_candidate_registry_path_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_registry_path_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_JSON_BYTES
        ):
            raise RuntimeError("manfred_candidate_registry_file_invalid")
        content = b""
        while len(content) <= MAX_JSON_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_JSON_BYTES + 1 - len(content)))
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise RuntimeError("manfred_candidate_registry_file_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_candidate_registry_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_registry_json_invalid")
    return dict(payload), hashlib.sha256(content).hexdigest()


def _ensure_private_parent(path: Path) -> Path:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
    parent = absolute.parent
    try:
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        resolved = parent.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_registry_parent_invalid") from exc
    if (
        resolved != parent.absolute()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_candidate_registry_parent_invalid")
    return resolved / absolute.name


def _atomic_registry(path: Path, payload: dict[str, object]) -> None:
    destination = _ensure_private_parent(path)
    if os.path.lexists(destination):
        _read_private_json(destination)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o600)
        directory_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _receipt_entry(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    loaded = _read_private_json(path)
    if loaded is None:  # pragma: no cover - missing_ok is false
        raise RuntimeError("manfred_candidate_registry_receipt_missing")
    payload, digest = loaded
    if payload.get("schema") not in RUNTIME_SCHEMAS or payload.get("status") != "pass":
        raise RuntimeError("manfred_candidate_registry_receipt_invalid")
    try:
        project = _validate_project_name(payload.get("compose_project"))
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_registry_receipt_invalid") from exc
    observed_at = str(payload.get("observed_at") or "")
    image_id = str(payload.get("image_id") or "")
    try:
        _validated_timestamp(observed_at)
    except RuntimeError as exc:
        raise RuntimeError("manfred_candidate_registry_receipt_invalid") from exc
    if IMAGE_ID.fullmatch(image_id) is None:
        raise RuntimeError("manfred_candidate_registry_receipt_invalid")
    resolved = Path(path).expanduser().resolve(strict=True)
    return payload, {
        "project": project,
        "receipt_path": str(resolved),
        "receipt_sha256": digest,
        "observed_at": observed_at,
        "image_id": image_id,
    }


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validated_timestamp(value: object) -> str:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_registry_pending_invalid") from exc
    return text


def _normalized_pending(
    *,
    project: object,
    port: object,
    receipt_path: object,
    image: object,
    image_id: object,
    revision: object,
    created_at: object,
) -> dict[str, object]:
    try:
        normalized_project = _validate_project_name(project)
        normalized_port = int(port)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_candidate_registry_pending_invalid") from exc
    path = Path(str(receipt_path or "")).expanduser()
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    normalized_path = str(path)
    normalized_image = str(image or "")
    normalized_image_id = str(image_id or "")
    normalized_revision = str(revision or "")
    if (
        not 1024 <= normalized_port <= 65535
        or IMAGE_LOCATOR.fullmatch(normalized_image) is None
        or IMAGE_ID.fullmatch(normalized_image_id) is None
        or HEX_40.fullmatch(normalized_revision) is None
        or normalized_image not in {
            f"ea-runtime:manfred-{normalized_revision}",
            f"ea-runtime:memorial-{normalized_revision}",
        }
    ):
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    return {
        "project": normalized_project,
        "port": normalized_port,
        "receipt_path": normalized_path,
        "image": normalized_image,
        "image_id": normalized_image_id,
        "revision": normalized_revision,
        "created_at": _validated_timestamp(created_at),
    }


def _validated_entries(payload: dict[str, object]) -> list[dict[str, str]]:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise RuntimeError("manfred_candidate_registry_schema_invalid")
    raw_entries = payload.get("entries")
    if (
        not isinstance(raw_entries, list)
        or len(raw_entries) > MAX_REGISTRY_ENTRIES
        or payload.get("entry_count") != len(raw_entries)
    ):
        raise RuntimeError("manfred_candidate_registry_entries_invalid")
    entries: list[dict[str, str]] = []
    projects: set[str] = set()
    paths: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != {
            "project",
            "receipt_path",
            "receipt_sha256",
            "observed_at",
            "image_id",
        }:
            raise RuntimeError("manfred_candidate_registry_entries_invalid")
        try:
            project = _validate_project_name(raw.get("project"))
        except ValueError as exc:
            raise RuntimeError("manfred_candidate_registry_entries_invalid") from exc
        entry = {
            "project": project,
            "receipt_path": str(raw.get("receipt_path") or ""),
            "receipt_sha256": str(raw.get("receipt_sha256") or ""),
            "observed_at": str(raw.get("observed_at") or ""),
            "image_id": str(raw.get("image_id") or ""),
        }
        if (
            project in projects
            or entry["receipt_path"] in paths
            or HEX_64.fullmatch(entry["receipt_sha256"]) is None
            or IMAGE_ID.fullmatch(entry["image_id"]) is None
            or not Path(entry["receipt_path"]).is_absolute()
            or Path(entry["receipt_path"]).resolve(strict=False)
            != Path(entry["receipt_path"])
        ):
            raise RuntimeError("manfred_candidate_registry_entries_invalid")
        try:
            _validated_timestamp(entry["observed_at"])
        except RuntimeError as exc:
            raise RuntimeError("manfred_candidate_registry_entries_invalid") from exc
        projects.add(project)
        paths.add(entry["receipt_path"])
        entries.append(entry)
    return entries


def _validated_pending(payload: dict[str, object]) -> list[dict[str, object]]:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise RuntimeError("manfred_candidate_registry_schema_invalid")
    raw_pending = payload.get("pending", [])
    pending_count = payload.get("pending_count", len(raw_pending) if isinstance(raw_pending, list) else -1)
    if (
        not isinstance(raw_pending, list)
        or len(raw_pending) > MAX_PENDING_ENTRIES
        or pending_count != len(raw_pending)
    ):
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    pending: list[dict[str, object]] = []
    projects: set[str] = set()
    ports: set[int] = set()
    paths: set[str] = set()
    expected_keys = {
        "project",
        "port",
        "receipt_path",
        "image",
        "image_id",
        "revision",
        "created_at",
    }
    for raw in raw_pending:
        if not isinstance(raw, dict) or set(raw) != expected_keys:
            raise RuntimeError("manfred_candidate_registry_pending_invalid")
        entry = _normalized_pending(**raw)
        project = str(entry["project"])
        port = int(entry["port"])
        receipt_path = str(entry["receipt_path"])
        if project in projects or port in ports or receipt_path in paths:
            raise RuntimeError("manfred_candidate_registry_pending_invalid")
        projects.add(project)
        ports.add(port)
        paths.add(receipt_path)
        pending.append(entry)
    return sorted(pending, key=lambda row: (str(row["created_at"]), str(row["project"])))


def _registry_payload(
    entries: list[dict[str, str]], pending: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema": REGISTRY_SCHEMA,
        "entry_count": len(entries),
        "entries": entries,
        "pending_count": len(pending),
        "pending": pending,
    }


def _validated_registry(
    payload: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    entries = _validated_entries(payload)
    pending = _validated_pending(payload)
    if {entry["project"] for entry in entries}.intersection(
        str(entry["project"]) for entry in pending
    ):
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    return entries, pending


def register_candidate_pending(
    *,
    project: str,
    port: int,
    receipt_path: Path,
    image: str,
    image_id: str,
    revision: str,
    registry_path: Path | None = None,
) -> dict[str, object]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    entry = _normalized_pending(
        project=project,
        port=port,
        receipt_path=str(Path(receipt_path).expanduser().resolve()),
        image=image,
        image_id=image_id,
        revision=revision,
        created_at=_utc_now(),
    )
    if any(row["project"] == entry["project"] for row in entries):
        raise RuntimeError("manfred_candidate_registry_project_already_registered")
    if any(
        row["project"] == entry["project"]
        or row["port"] == entry["port"]
        or row["receipt_path"] == entry["receipt_path"]
        for row in pending
    ):
        raise RuntimeError("manfred_candidate_registry_pending_exists")
    if len(pending) >= MAX_PENDING_ENTRIES:
        raise RuntimeError("manfred_candidate_registry_pending_full")
    pending.append(entry)
    pending.sort(key=lambda row: (str(row["created_at"]), str(row["project"])))
    _atomic_registry(path, _registry_payload(entries, pending))
    return {
        "schema": REGISTRY_SCHEMA,
        "project": entry["project"],
        "created_at": entry["created_at"],
        "pending_registered": True,
    }


def clear_candidate_pending(
    project: str, *, registry_path: Path | None = None
) -> dict[str, object]:
    try:
        normalized = _validate_project_name(project)
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_registry_pending_invalid") from exc
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return {
            "schema": REGISTRY_SCHEMA,
            "project": normalized,
            "pending_cleared": False,
        }
    entries, pending = _validated_registry(loaded[0])
    retained = [row for row in pending if row["project"] != normalized]
    cleared = len(retained) != len(pending)
    if cleared:
        _atomic_registry(path, _registry_payload(entries, retained))
    return {
        "schema": REGISTRY_SCHEMA,
        "project": normalized,
        "pending_cleared": cleared,
    }


def registered_candidate_pending(
    *, registry_path: Path | None = None
) -> list[dict[str, object]]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return []
    _entries, pending = _validated_registry(loaded[0])
    return pending


def register_candidate_receipt(
    receipt_path: Path,
    *,
    registry_path: Path | None = None,
) -> dict[str, object]:
    _payload, entry = _receipt_entry(receipt_path)
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    matching_pending = [
        row for row in pending if row["project"] == entry["project"]
    ]
    if matching_pending:
        intent = matching_pending[0]
        try:
            receipt_port = int(_payload.get("candidate_port"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("manfred_candidate_registry_pending_mismatch") from exc
        if (
            str(intent["receipt_path"]) != str(entry["receipt_path"])
            or str(intent["image"]) != str(_payload.get("image") or "")
            or str(intent["image_id"]) != str(_payload.get("image_id") or "")
            or str(intent["revision"])
            != str(_payload.get("image_source_revision") or "")
            or int(intent["port"]) != receipt_port
        ):
            raise RuntimeError("manfred_candidate_registry_pending_mismatch")
    entries = [row for row in entries if row["project"] != entry["project"]]
    if len(entries) >= MAX_REGISTRY_ENTRIES:
        raise RuntimeError("manfred_candidate_registry_full")
    entries.append({key: str(value) for key, value in entry.items()})
    entries.sort(key=lambda row: (row["observed_at"], row["project"]))
    pending = [row for row in pending if row["project"] != entry["project"]]
    payload = _registry_payload(entries, pending)
    _atomic_registry(path, payload)
    return {
        "schema": REGISTRY_SCHEMA,
        "project": entry["project"],
        "receipt_sha256": entry["receipt_sha256"],
        "registered": True,
    }


def registered_candidate_receipts(
    *, registry_path: Path | None = None
) -> list[Path]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return []
    entries, _pending = _validated_registry(loaded[0])
    paths: list[Path] = []
    for entry in entries:
        receipt_path = Path(entry["receipt_path"])
        _payload, observed = _receipt_entry(receipt_path)
        if observed != entry:
            raise RuntimeError("manfred_candidate_registry_receipt_changed")
        paths.append(receipt_path)
    return paths


def compact_candidate_registry(
    active_projects: set[str],
    *,
    registry_path: Path | None = None,
) -> dict[str, object]:
    normalized: set[str] = set()
    for project in active_projects:
        try:
            normalized.add(_validate_project_name(project))
        except ValueError as exc:
            raise RuntimeError("manfred_candidate_registry_active_project_invalid") from exc
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    retained = [entry for entry in entries if entry["project"] in normalized]
    if {entry["project"] for entry in retained} != normalized:
        raise RuntimeError("manfred_candidate_registry_active_receipt_missing")
    for entry in retained:
        _payload, observed = _receipt_entry(Path(entry["receipt_path"]))
        if observed != entry:
            raise RuntimeError("manfred_candidate_registry_receipt_changed")
    _atomic_registry(
        path,
        _registry_payload(retained, pending),
    )
    return {
        "schema": REGISTRY_SCHEMA,
        "before_count": len(entries),
        "after_count": len(retained),
        "active_projects": sorted(normalized),
        "historical_receipts_deleted": False,
    }
