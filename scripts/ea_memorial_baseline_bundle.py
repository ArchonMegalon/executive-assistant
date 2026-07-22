#!/usr/bin/env python3
"""Create a retained, private, exact-Git Memorial API baseline bundle.

This module has no Docker, Compose, HTTP, deployment, or cleanup capability.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess  # nosec B404 - fixed executable and arguments
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

try:
    from scripts.plan_ea_memorial_api_baseline_normalization import (
        PlanError,
        validate_plan_payload,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script import
    from plan_ea_memorial_api_baseline_normalization import (  # type: ignore[no-redef]
        PlanError,
        validate_plan_payload,
    )


BUNDLE_CONTRACT = "ea.memorial_api_baseline_bundle.v3"
BUNDLE_VERSION = 3
BASELINE_RENDER_ENV_KEYS = frozenset(
    {
        "EA_MEMORIAL_DATA_HOST_PATH",
        "EA_MEMORIAL_IMAGE",
        "EA_MEMORIAL_RUNTIME_HOST_PATH",
        "EA_MEMORIAL_TRUSTED_PROXY_CIDRS",
        "EA_SOURCE_REVISION",
    }
)
COMPOSE_BLOB_PATHS = ("docker-compose.yml", "docker-compose.memorial.yml")
NORMALIZATION_OVERRIDE = "docker-compose.api-baseline-normalization.yml"
MANIFEST_NAME = "baseline-bundle-manifest.json"
RECOVERY_SEAL_CONTRACT = "ea.memorial_api_baseline_bundle_recovery_seal.v1"
_RENDER_ENV_MARKER = b"# ea-memorial-api-baseline-render-environment:v2\n"
GIT_EXECUTABLE = "/usr/bin/git"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
INFO_KEYS = {
    "bundle_path",
    "compose_files",
    "contract_name",
    "environment_files",
    "manifest_path",
    "manifest_sha256",
    "origin_main_commit",
    "plan_sha256",
    "source_revision",
    "version",
}
MANIFEST_KEYS = {
    "ancestry_ref",
    "bundle_path",
    "contract_name",
    "environment_files",
    "environment_key_count",
    "environment_key_set_sha256",
    "ordered_compose_files",
    "origin_main_commit",
    "plan_sha256",
    "render_environment_key_count",
    "render_environment_key_set_sha256",
    "source_revision",
    "trusted_environment_records_sha256",
    "version",
}
RECOVERY_SEAL_KEYS = {"contract_name", "manifest_sha256", "plan_sha256"}
FILE_KEYS = {
    "git_blob_id",
    "mode",
    "present",
    "relative_path",
    "sha256",
    "size_bytes",
}


class BaselineBundleError(RuntimeError):
    """A baseline bundle input or retained seal is untrusted."""


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[Any]: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(  # nosec B603 - fixed executable and arguments
            list(args),
            cwd=cwd,
            env=dict(env),
            check=False,
            capture_output=True,
        )
        if check and result.returncode:
            raise BaselineBundleError("fixed_git_command_failed")
        return result


def _valid_name(name: str) -> bool:
    return name in {".env", ".env.local"} or NAME_RE.fullmatch(name) is not None


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(value: object, reason: str) -> Path:
    raw = str(value or "")
    if (
        not raw
        or "\x00" in raw
        or raw.startswith("~")
        or not os.path.isabs(raw)
        or os.path.normpath(raw) != raw
    ):
        raise BaselineBundleError(reason)
    result = Path(raw)
    if result == Path("/") or ".." in result.parts:
        raise BaselineBundleError(reason)
    return result


def _open_dir(path: Path, *, private: bool, owner: bool = False) -> int:
    if any(
        not hasattr(os, name)
        for name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    ):
        raise BaselineBundleError("secure_open_primitives_missing")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            opened = os.fstat(next_descriptor)
            named = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                os.close(next_descriptor)
                raise BaselineBundleError("directory_identity_invalid")
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if owner and metadata.st_uid != os.geteuid():
            raise BaselineBundleError("directory_owner_invalid")
        if private and stat.S_IMODE(metadata.st_mode) != 0o700:
            raise BaselineBundleError("directory_mode_invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_object_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
    )


def _revalidate_directory(path: Path, descriptor: int, reason: str) -> None:
    before = os.fstat(descriptor)
    reopened = _open_dir(path, private=False, owner=True)
    try:
        after = os.fstat(reopened)
        if not stat.S_ISDIR(before.st_mode) or _directory_identity(
            before
        ) != _directory_identity(after):
            raise BaselineBundleError(reason)
    finally:
        os.close(reopened)


def _read_at(
    directory_fd: int,
    name: str,
    *,
    required: bool,
    reason: str,
    max_bytes: int = MAX_FILE_BYTES,
) -> tuple[bytes | None, dict[str, object]]:
    if not _valid_name(name):
        raise BaselineBundleError(reason + "_name_invalid")
    descriptor = -1
    try:
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            if required:
                raise BaselineBundleError(reason + "_missing") from None
            return None, {
                "git_blob_id": None,
                "mode": None,
                "present": False,
                "relative_path": name,
                "sha256": None,
                "size_bytes": None,
            }
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
            or before.st_size > max_bytes
            or (required and before.st_size == 0)
        ):
            raise BaselineBundleError(reason + "_untrusted")
        identity = _identity(before)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes or _identity(os.fstat(descriptor)) != identity:
                raise BaselineBundleError(reason + "_changed")
        after = os.fstat(descriptor)
        final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            total != before.st_size
            or _identity(after) != identity
            or _identity(final) != identity
        ):
            raise BaselineBundleError(reason + "_changed")
        raw = b"".join(chunks)
        return raw, {
            "git_blob_id": None,
            "mode": "0600",
            "present": True,
            "relative_path": name,
            "sha256": _sha(raw),
            "size_bytes": len(raw),
        }
    except BaselineBundleError:
        raise
    except OSError as exc:
        raise BaselineBundleError(reason + "_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_at(
    directory_fd: int, name: str, raw: bytes, *, blob_id: str | None = None
) -> dict[str, object]:
    if not _valid_name(name):
        raise BaselineBundleError("bundle_file_name_invalid")
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:  # pragma: no cover - kernel invariant
                raise BaselineBundleError("bundle_file_write_failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_size != len(raw)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise BaselineBundleError("bundle_file_identity_invalid")
        return {
            "git_blob_id": blob_id,
            "mode": "0600",
            "present": True,
            "relative_path": name,
            "sha256": _sha(raw),
            "size_bytes": len(raw),
        }
    except BaselineBundleError:
        raise
    except OSError as exc:
        raise BaselineBundleError("bundle_file_create_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _git_env() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_GRAFT_FILE": os.devnull,
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _repository_descriptor_cwd(descriptor: int) -> Path:
    path = Path(f"/proc/self/fd/{descriptor}")
    try:
        opened = os.fstat(descriptor)
        projected = os.stat(path, follow_symlinks=True)
    except OSError as exc:
        raise BaselineBundleError(
            "repository_descriptor_projection_unavailable"
        ) from exc
    if not stat.S_ISDIR(opened.st_mode) or _directory_object_identity(
        opened
    ) != _directory_object_identity(projected):
        raise BaselineBundleError("repository_descriptor_projection_invalid")
    return path


def _git_executable_identity() -> tuple[int, ...]:
    descriptor = -1
    try:
        if GIT_EXECUTABLE != "/usr/bin/git":
            raise BaselineBundleError("git_executable_path_invalid")
        named = os.stat(GIT_EXECUTABLE, follow_symlinks=False)
        descriptor = os.open(
            GIT_EXECUTABLE,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or opened.st_uid != 0
            or opened.st_gid != 0
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) & 0o022
            or not stat.S_IMODE(opened.st_mode) & 0o111
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise BaselineBundleError("git_executable_untrusted")
        return _identity(opened)
    except BaselineBundleError:
        raise
    except OSError as exc:
        raise BaselineBundleError("git_executable_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _stdout(result: subprocess.CompletedProcess[Any]) -> bytes:
    if isinstance(result.stdout, bytes):
        return result.stdout
    if isinstance(result.stdout, str):
        return result.stdout.encode("utf-8")
    raise BaselineBundleError("git_output_invalid")


def _git(
    runner: Runner, root: Path, args: Sequence[str]
) -> subprocess.CompletedProcess[Any]:
    return runner.run(
        [GIT_EXECUTABLE, "--no-replace-objects", *args],
        cwd=root,
        env=_git_env(),
        check=False,
    )


def _git_line(runner: Runner, root: Path, args: Sequence[str], reason: str) -> str:
    result = _git(runner, root, args)
    raw = _stdout(result)
    if result.returncode or len(raw) > 1024:
        raise BaselineBundleError(reason)
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise BaselineBundleError(reason) from exc
    if not value or "\n" in value or "\r" in value:
        raise BaselineBundleError(reason)
    return value


def _blob_digest(raw: bytes, object_id: str) -> str:
    payload = f"blob {len(raw)}\0".encode("ascii") + raw
    if len(object_id) == 40:
        return hashlib.sha1(  # nosec B324 - Git SHA-1 object verification
            payload, usedforsecurity=False
        ).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def _git_blobs(
    runner: Runner, root: Path, revision: str
) -> tuple[str, list[tuple[str, str, bytes]]]:
    resolved = _git_line(
        runner,
        root,
        ["rev-parse", "--verify", "--end-of-options", revision + "^{commit}"],
        "source_commit_unavailable",
    )
    if resolved != revision:
        raise BaselineBundleError("source_commit_identity_mismatch")
    origin_main_commit = _git_line(
        runner,
        root,
        [
            "rev-parse",
            "--verify",
            "--end-of-options",
            "origin/main^{commit}",
        ],
        "origin_main_commit_unavailable",
    )
    if not REVISION_RE.fullmatch(origin_main_commit):
        raise BaselineBundleError("origin_main_commit_invalid")
    ancestry = _git(
        runner,
        root,
        ["merge-base", "--is-ancestor", revision, origin_main_commit],
    )
    if ancestry.returncode:
        raise BaselineBundleError("source_commit_not_origin_main_ancestor")
    result: list[tuple[str, str, bytes]] = []
    for relative in COMPOSE_BLOB_PATHS:
        object_id = _git_line(
            runner,
            root,
            [
                "rev-parse",
                "--verify",
                "--end-of-options",
                revision + ":" + relative,
            ],
            "compose_blob_unavailable",
        )
        if not OBJECT_RE.fullmatch(object_id):
            raise BaselineBundleError("compose_blob_id_invalid")
        if (
            _git_line(
                runner,
                root,
                ["cat-file", "-t", object_id],
                "compose_blob_type_unavailable",
            )
            != "blob"
        ):
            raise BaselineBundleError("compose_object_not_blob")
        size = _git_line(
            runner,
            root,
            ["cat-file", "-s", object_id],
            "compose_blob_size_unavailable",
        )
        if not size.isdigit() or not 0 < int(size) <= MAX_FILE_BYTES:
            raise BaselineBundleError("compose_blob_size_invalid")
        read = _git(runner, root, ["cat-file", "blob", object_id])
        raw = _stdout(read)
        if (
            read.returncode
            or len(raw) != int(size)
            or _blob_digest(raw, object_id) != object_id
        ):
            raise BaselineBundleError("compose_blob_integrity_invalid")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BaselineBundleError("compose_blob_utf8_invalid") from exc
        result.append((relative, object_id, raw))
    return origin_main_commit, result


def _mapping_value(node: MappingNode, key: str, reason: str) -> Node | None:
    matches: list[Node] = []
    for raw_key, raw_value in node.value:
        if not isinstance(raw_key, ScalarNode):
            raise BaselineBundleError(reason)
        if raw_key.value == key:
            matches.append(raw_value)
    if len(matches) > 1:
        raise BaselineBundleError(reason)
    return matches[0] if matches else None


def _validate_compose_tree(root: Node, allowed_tagged_nodes: set[int]) -> None:
    seen: set[int] = set()

    def walk(node: Node) -> None:
        node_id = id(node)
        if node_id in seen:
            raise BaselineBundleError("compose_yaml_alias_invalid")
        seen.add(node_id)
        if not node.tag.startswith("tag:yaml.org,2002:"):
            if node_id not in allowed_tagged_nodes or node.tag not in {
                "!reset",
                "!override",
            }:
                raise BaselineBundleError("compose_yaml_tag_unsupported")
        if isinstance(node, MappingNode):
            keys: set[str] = set()
            for key, value in node.value:
                if (
                    not isinstance(key, ScalarNode)
                    or key.tag != "tag:yaml.org,2002:str"
                    or key.value == "<<"
                ):
                    raise BaselineBundleError("compose_yaml_merge_or_key_invalid")
                if key.value in keys:
                    raise BaselineBundleError("compose_yaml_duplicate_key")
                keys.add(key.value)
                walk(key)
                walk(value)
        elif isinstance(node, SequenceNode):
            for item in node.value:
                walk(item)
        elif not isinstance(node, ScalarNode):  # pragma: no cover - PyYAML nodes
            raise BaselineBundleError("compose_yaml_node_invalid")

    walk(root)


def _compose_environment_names(raw: bytes) -> tuple[set[str], bool]:
    """Extract keys from exact YAML nodes without constructing a lossy object."""
    try:
        documents = list(yaml.compose_all(raw.decode("utf-8"), Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise BaselineBundleError("compose_yaml_invalid") from exc
    if len(documents) != 1:
        raise BaselineBundleError("compose_document_count_invalid")
    root = documents[0]
    if not isinstance(root, MappingNode):
        raise BaselineBundleError("compose_root_invalid")
    if _mapping_value(root, "include", "compose_include_ambiguous") is not None:
        raise BaselineBundleError("compose_include_unsupported")
    services = _mapping_value(root, "services", "compose_services_ambiguous")
    if not isinstance(services, MappingNode) or services.tag != "tag:yaml.org,2002:map":
        raise BaselineBundleError("compose_services_invalid")
    for service_key, service_value in services.value:
        if not isinstance(service_key, ScalarNode):
            raise BaselineBundleError("compose_service_key_invalid")
        if isinstance(service_value, MappingNode):
            if (
                _mapping_value(service_value, "extends", "compose_extends_ambiguous")
                is not None
            ):
                raise BaselineBundleError("compose_extends_unsupported")
    api = _mapping_value(services, "ea-api", "compose_api_ambiguous")
    if not isinstance(api, MappingNode) or api.tag != "tag:yaml.org,2002:map":
        raise BaselineBundleError("compose_api_invalid")
    environment = _mapping_value(api, "environment", "compose_environment_ambiguous")
    allowed_tagged_nodes = {
        id(field_value)
        for _service_key, service_value in services.value
        if isinstance(service_value, MappingNode)
        for _field_key, field_value in service_value.value
        if field_value.tag in {"!reset", "!override"}
    }
    _validate_compose_tree(root, allowed_tagged_nodes)
    if environment is None:
        return set(), False
    names: set[str] = set()
    if isinstance(environment, SequenceNode):
        if environment.tag not in {
            "tag:yaml.org,2002:seq",
            "!reset",
            "!override",
        }:
            raise BaselineBundleError("compose_environment_tag_invalid")
        raw_names = []
        for item in environment.value:
            if not isinstance(item, ScalarNode) or item.tag != "tag:yaml.org,2002:str":
                raise BaselineBundleError("compose_environment_invalid")
            raw_names.append(item.value.split("=", 1)[0])
    elif isinstance(environment, MappingNode):
        if environment.tag not in {
            "tag:yaml.org,2002:map",
            "!reset",
            "!override",
        }:
            raise BaselineBundleError("compose_environment_tag_invalid")
        raw_names = []
        for item, _value in environment.value:
            if not isinstance(item, ScalarNode) or item.tag != "tag:yaml.org,2002:str":
                raise BaselineBundleError("compose_environment_invalid")
            raw_names.append(item.value)
    else:
        raise BaselineBundleError("compose_environment_invalid")
    for name in raw_names:
        if not ENV_NAME_RE.fullmatch(name):
            raise BaselineBundleError("compose_environment_name_invalid")
        if name in names:
            raise BaselineBundleError("compose_environment_duplicate")
        names.add(name)
    return names, environment.tag in {"!reset", "!override"}


def _explicit_environment_names(
    blobs: Sequence[tuple[str, str, bytes]],
) -> set[str]:
    names: set[str] = set()
    for _relative, _object_id, raw in blobs:
        layer, reset = _compose_environment_names(raw)
        if reset:
            names.clear()
        names.update(layer)
    return names


def _validate_dotenv_value(value: str) -> None:
    value = value.rstrip(" \t")
    if not value:
        return
    if value[0] not in {"'", '"'}:
        if "'" in value or '"' in value or value.endswith("\\"):
            raise BaselineBundleError("trusted_environment_quoting_invalid")
        return
    quote = value[0]
    index = 1
    while index < len(value):
        character = value[index]
        if quote == '"' and character == "\\":
            index += 1
            if index >= len(value) or value[index] not in {
                "\\",
                '"',
                "'",
                "$",
                "n",
                "r",
                "t",
            }:
                raise BaselineBundleError("trusted_environment_quoting_invalid")
        elif character == quote:
            trailing = value[index + 1 :].strip(" \t")
            if trailing and not trailing.startswith("#"):
                raise BaselineBundleError("trusted_environment_quoting_invalid")
            return
        index += 1
    raise BaselineBundleError("trusted_environment_multiline_invalid")


def _dotenv_names(raw: bytes) -> set[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BaselineBundleError("trusted_environment_utf8_invalid") from exc
    if any(character in text for character in ("\x00", "\x85", "\u2028", "\u2029")):
        raise BaselineBundleError("trusted_environment_control_invalid")
    names: set[str] = set()
    assignment = re.compile(
        r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$"
    )
    for physical in text.split("\n"):
        if "\r" in physical:
            if not physical.endswith("\r") or "\r" in physical[:-1]:
                raise BaselineBundleError("trusted_environment_line_invalid")
            physical = physical[:-1]
        candidate = physical.strip(" \t")
        if not candidate or candidate.startswith("#"):
            continue
        matched = assignment.fullmatch(physical)
        if matched is None:
            raise BaselineBundleError("trusted_environment_syntax_invalid")
        name, value = matched.groups()
        if name in names:
            raise BaselineBundleError("trusted_environment_duplicate")
        _validate_dotenv_value(value)
        names.add(name)
    return names


def _env_names(raw_files: Sequence[bytes]) -> set[str]:
    names: set[str] = set()
    for raw in raw_files:
        names.update(_dotenv_names(raw))
    return names


def _environment_record(relative_path: str, raw: bytes | None) -> dict[str, object]:
    if raw is None:
        return {
            "git_blob_id": None,
            "mode": None,
            "present": False,
            "relative_path": relative_path,
            "sha256": None,
            "size_bytes": None,
        }
    return {
        "git_blob_id": None,
        "mode": "0600",
        "present": True,
        "relative_path": relative_path,
        "sha256": _sha(raw),
        "size_bytes": len(raw),
    }


def _trusted_environment_records_digest(
    records: Sequence[Mapping[str, object]],
) -> str:
    if (
        len(records) != 2
        or [record.get("relative_path") for record in records] != [".env", ".env.local"]
        or not _record_valid(records[0], allow_absent=False)
        or not _record_valid(records[1], allow_absent=True)
    ):
        raise BaselineBundleError("trusted_environment_records_invalid")
    return _sha(_canonical_bytes([dict(record) for record in records]))


def _trusted_environment_names(env_raw: bytes, local_raw: bytes | None) -> set[str]:
    names = _env_names([env_raw, *([local_raw] if local_raw is not None else [])])
    if names & BASELINE_RENDER_ENV_KEYS:
        raise BaselineBundleError("trusted_environment_render_key_reserved")
    return names


def _validated_baseline_environment_names(
    names: Sequence[str] | set[str] | frozenset[str],
) -> set[str]:
    if isinstance(names, (str, bytes)):
        raise BaselineBundleError("baseline_environment_names_invalid")
    try:
        values = list(names)
    except (TypeError, ValueError) as exc:
        raise BaselineBundleError("baseline_environment_names_invalid") from exc
    if (
        any(
            not isinstance(name, str) or ENV_NAME_RE.fullmatch(name) is None
            for name in values
        )
        or len(set(values)) != len(values)
    ):
        raise BaselineBundleError("baseline_environment_names_invalid")
    return set(values)


def _validated_render_environment(
    render_environment: Mapping[str, str],
) -> dict[str, str]:
    try:
        keys = set(render_environment)
    except (TypeError, ValueError) as exc:
        raise BaselineBundleError("render_environment_schema_invalid") from exc
    if keys != BASELINE_RENDER_ENV_KEYS:
        raise BaselineBundleError("render_environment_schema_invalid")
    result: dict[str, str] = {}
    for key in sorted(BASELINE_RENDER_ENV_KEYS):
        try:
            value = render_environment[key]
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineBundleError("render_environment_schema_invalid") from exc
        if not isinstance(value, str) or not value:
            raise BaselineBundleError("render_environment_value_invalid")
        if "\\" in value or any(not character.isprintable() for character in value):
            raise BaselineBundleError("render_environment_value_unsafe")
        result[key] = value
    return result


def _render_environment_assignments(
    render_environment: Mapping[str, str],
) -> bytes:
    validated = _validated_render_environment(render_environment)
    lines = []
    for key in sorted(BASELINE_RENDER_ENV_KEYS):
        value = validated[key].replace("'", "\\'")
        lines.append(f"{key}='{value}'")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _augmented_environment_local(
    trusted_local: bytes | None, render_environment: Mapping[str, str]
) -> bytes:
    prefix = trusted_local or b""
    separator = b"" if not prefix or prefix.endswith(b"\n") else b"\n"
    return (
        prefix
        + separator
        + _RENDER_ENV_MARKER
        + _render_environment_assignments(render_environment)
    )


def _decode_render_environment_assignments(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BaselineBundleError("render_environment_utf8_invalid") from exc
    physical_lines = text.split("\n")
    ordered_keys = sorted(BASELINE_RENDER_ENV_KEYS)
    if physical_lines[-1:] != [""] or len(physical_lines) != len(ordered_keys) + 1:
        raise BaselineBundleError("render_environment_assignments_invalid")
    result: dict[str, str] = {}
    for key, line in zip(ordered_keys, physical_lines[:-1], strict=True):
        prefix = key + "='"
        if not line.startswith(prefix) or not line.endswith("'"):
            raise BaselineBundleError("render_environment_assignments_invalid")
        encoded = line[len(prefix) : -1]
        characters: list[str] = []
        index = 0
        while index < len(encoded):
            character = encoded[index]
            if character == "\\":
                index += 1
                if index >= len(encoded) or encoded[index] != "'":
                    raise BaselineBundleError("render_environment_assignments_invalid")
                characters.append("'")
            elif character == "'" or not character.isprintable():
                raise BaselineBundleError("render_environment_assignments_invalid")
            else:
                characters.append(character)
            index += 1
        result[key] = "".join(characters)
    return _validated_render_environment(result)


def _split_augmented_environment_local(
    raw: bytes,
) -> tuple[bytes, dict[str, str]]:
    marker_index = raw.rfind(_RENDER_ENV_MARKER)
    if marker_index < 0 or (marker_index > 0 and raw[marker_index - 1] != 0x0A):
        raise BaselineBundleError("render_environment_marker_invalid")
    trusted_prefix = raw[:marker_index]
    render_environment = _decode_render_environment_assignments(
        raw[marker_index + len(_RENDER_ENV_MARKER) :]
    )
    return trusted_prefix, render_environment


def _recovery_trusted_environment_record_digests(
    env_record: Mapping[str, object], trusted_local_prefix: bytes
) -> set[str]:
    local_candidates: list[bytes | None]
    if trusted_local_prefix:
        local_candidates = [trusted_local_prefix]
        if trusted_local_prefix.endswith(b"\n"):
            local_candidates.append(trusted_local_prefix[:-1])
    else:
        local_candidates = [None, b""]
    return {
        _trusted_environment_records_digest(
            [env_record, _environment_record(".env.local", candidate)]
        )
        for candidate in local_candidates
    }


def _override(names: Sequence[str]) -> bytes:
    lines = ["services:", "  ea-api:", "    env_file: !reset []"]
    if names:
        lines.append("    environment:")
        dollar = chr(36)
        lines.extend(f"      - {name}={dollar}{{{name}}}" for name in names)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _absent_at(directory_fd: int, name: str, reason: str) -> None:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BaselineBundleError(reason + "_unavailable") from exc
    raise BaselineBundleError(reason + "_presence_changed")


def _read_trusted_environment(
    trusted_root: Path,
) -> tuple[bytes, bytes | None, list[dict[str, object]]]:
    descriptor = _open_dir(trusted_root, private=True, owner=True)
    anchor = _directory_identity(os.fstat(descriptor))
    try:
        env_raw, env_record = _read_at(
            descriptor, ".env", required=True, reason="trusted_env"
        )
        local_raw, local_record = _read_at(
            descriptor,
            ".env.local",
            required=False,
            reason="trusted_env_local",
        )
        if local_raw is None:
            _absent_at(descriptor, ".env.local", "trusted_env_local")
        if _directory_identity(os.fstat(descriptor)) != anchor:
            raise BaselineBundleError("trusted_environment_root_changed")
        _revalidate_directory(
            trusted_root, descriptor, "trusted_environment_root_changed"
        )
        assert env_raw is not None
        return env_raw, local_raw, [env_record, local_record]
    finally:
        os.close(descriptor)


def _record_valid(record: object, *, allow_absent: bool) -> bool:
    if not isinstance(record, dict) or set(record) != FILE_KEYS:
        return False
    name = record.get("relative_path")
    if not isinstance(name, str) or not _valid_name(name):
        return False
    if record.get("present") is False and allow_absent:
        return all(
            record.get(key) is None
            for key in ("git_blob_id", "mode", "sha256", "size_bytes")
        )
    return (
        record.get("present") is True
        and record.get("mode") == "0600"
        and type(record.get("size_bytes")) is int
        and int(record["size_bytes"]) >= 0
        and isinstance(record.get("sha256"), str)
        and SHA_RE.fullmatch(str(record["sha256"])) is not None
        and (
            record.get("git_blob_id") is None
            or (
                isinstance(record.get("git_blob_id"), str)
                and OBJECT_RE.fullmatch(str(record["git_blob_id"])) is not None
            )
        )
    )


def _strict_manifest(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise BaselineBundleError("bundle_manifest_json_duplicate_key")
            result[key] = value
        return result

    def constant(_value: str) -> object:
        raise BaselineBundleError("bundle_manifest_json_nonfinite")

    try:
        loaded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except BaselineBundleError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise BaselineBundleError("bundle_manifest_json_invalid") from exc
    if not isinstance(loaded, dict):
        raise BaselineBundleError("bundle_manifest_json_invalid")
    return loaded


def _validate_bundle(path: Path) -> tuple[dict[str, Any], str]:
    directory_fd = _open_dir(path, private=True, owner=True)
    anchor = _directory_identity(os.fstat(directory_fd))
    try:
        raw, _record = _read_at(
            directory_fd,
            MANIFEST_NAME,
            required=True,
            reason="bundle_manifest",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        assert raw is not None
        manifest = _strict_manifest(raw)
        compose = manifest.get("ordered_compose_files")
        environment = manifest.get("environment_files")
        if (
            set(manifest) != MANIFEST_KEYS
            or manifest.get("contract_name") != BUNDLE_CONTRACT
            or type(manifest.get("version")) is not int
            or manifest.get("version") != BUNDLE_VERSION
            or manifest.get("ancestry_ref") != "origin/main"
            or manifest.get("bundle_path") != str(path)
            or not isinstance(manifest.get("plan_sha256"), str)
            or not SHA_RE.fullmatch(str(manifest.get("plan_sha256")))
            or not isinstance(manifest.get("source_revision"), str)
            or not REVISION_RE.fullmatch(str(manifest.get("source_revision")))
            or not isinstance(manifest.get("origin_main_commit"), str)
            or not REVISION_RE.fullmatch(str(manifest.get("origin_main_commit")))
            or type(manifest.get("environment_key_count")) is not int
            or int(manifest.get("environment_key_count")) < 0
            or not isinstance(manifest.get("environment_key_set_sha256"), str)
            or not SHA_RE.fullmatch(str(manifest.get("environment_key_set_sha256")))
            or type(manifest.get("render_environment_key_count")) is not int
            or manifest.get("render_environment_key_count")
            != len(BASELINE_RENDER_ENV_KEYS)
            or manifest.get("render_environment_key_set_sha256")
            != _sha(_canonical_bytes(sorted(BASELINE_RENDER_ENV_KEYS)))
            or not isinstance(manifest.get("trusted_environment_records_sha256"), str)
            or not SHA_RE.fullmatch(
                str(manifest.get("trusted_environment_records_sha256"))
            )
            or not isinstance(compose, list)
            or len(compose) != 3
            or not all(_record_valid(item, allow_absent=False) for item in compose)
            or not isinstance(environment, list)
            or len(environment) != 2
            or not all(_record_valid(item, allow_absent=False) for item in environment)
        ):
            raise BaselineBundleError("bundle_manifest_invalid")
        if [item["relative_path"] for item in compose] != [
            *COMPOSE_BLOB_PATHS,
            NORMALIZATION_OVERRIDE,
        ]:
            raise BaselineBundleError("bundle_compose_order_invalid")
        if [item["relative_path"] for item in environment] != [
            ".env",
            ".env.local",
        ]:
            raise BaselineBundleError("bundle_environment_order_invalid")
        if (
            any(item["git_blob_id"] is None for item in compose[:2])
            or compose[2]["git_blob_id"] is not None
            or environment[0]["present"] is not True
            or environment[1]["present"] is not True
            or any(item["git_blob_id"] is not None for item in environment)
        ):
            raise BaselineBundleError("bundle_source_binding_invalid")
        present_records = [
            *compose,
            *(item for item in environment if item["present"]),
        ]
        expected_names = {
            MANIFEST_NAME,
            *(str(item["relative_path"]) for item in present_records),
        }
        if set(os.listdir(directory_fd)) != expected_names:
            raise BaselineBundleError("bundle_unsealed_entry")
        for expected in present_records:
            content, current = _read_at(
                directory_fd,
                str(expected["relative_path"]),
                required=True,
                reason="bundle_artifact",
            )
            assert content is not None
            if (
                current["sha256"] != expected["sha256"]
                or current["size_bytes"] != expected["size_bytes"]
                or current["mode"] != expected["mode"]
            ):
                raise BaselineBundleError("bundle_artifact_seal_mismatch")
        if _directory_identity(os.fstat(directory_fd)) != anchor:
            raise BaselineBundleError("bundle_directory_changed")
        _revalidate_directory(path, directory_fd, "bundle_directory_changed")
        return manifest, _sha(raw)
    finally:
        os.close(directory_fd)


def _require_bundle_semantics(
    path: Path,
    manifest: Mapping[str, Any],
    *,
    origin_main_commit: str,
    blobs: Sequence[tuple[str, str, bytes]],
    authoritative_environment: tuple[
        bytes, bytes | None, Sequence[Mapping[str, object]]
    ]
    | None,
    authoritative_render_environment: Mapping[str, str] | None,
    authoritative_baseline_environment_names: set[str] | None,
) -> None:
    if manifest.get("origin_main_commit") != origin_main_commit:
        raise BaselineBundleError("existing_bundle_origin_main_mismatch")
    directory_fd = _open_dir(path, private=True, owner=True)
    anchor = _directory_identity(os.fstat(directory_fd))
    try:
        compose_records = manifest["ordered_compose_files"]
        for index, (relative, object_id, expected_raw) in enumerate(blobs):
            retained_raw, retained_record = _read_at(
                directory_fd,
                relative,
                required=True,
                reason="retained_compose",
            )
            assert retained_raw is not None
            recorded = compose_records[index]
            if (
                retained_raw != expected_raw
                or recorded["git_blob_id"] != object_id
                or recorded["sha256"] != _sha(expected_raw)
                or recorded["size_bytes"] != len(expected_raw)
                or retained_record["sha256"] != _sha(expected_raw)
                or retained_record["size_bytes"] != len(expected_raw)
            ):
                raise BaselineBundleError("existing_bundle_git_mismatch")

        environment_records = manifest["environment_files"]
        retained_env, retained_env_record = _read_at(
            directory_fd, ".env", required=True, reason="retained_env"
        )
        assert retained_env is not None
        retained_local, retained_local_record = _read_at(
            directory_fd,
            ".env.local",
            required=True,
            reason="retained_env_local",
        )
        assert retained_local is not None
        current_environment_records = [
            retained_env_record,
            retained_local_record,
        ]
        for current, recorded in zip(
            current_environment_records, environment_records, strict=True
        ):
            if current != recorded:
                raise BaselineBundleError("existing_bundle_environment_record_mismatch")

        trusted_local_prefix, retained_render_environment = (
            _split_augmented_environment_local(retained_local)
        )
        if authoritative_environment is not None:
            if (
                authoritative_render_environment is None
                or authoritative_baseline_environment_names is None
            ):
                raise BaselineBundleError("authoritative_render_environment_missing")
            baseline_environment_names = _validated_baseline_environment_names(
                authoritative_baseline_environment_names
            )
            trusted_env, trusted_local, trusted_records = authoritative_environment
            validated_render_environment = _validated_render_environment(
                authoritative_render_environment
            )
            if retained_render_environment != validated_render_environment:
                raise BaselineBundleError("existing_bundle_render_environment_mismatch")
            expected_local = _augmented_environment_local(
                trusted_local, validated_render_environment
            )
            if (
                retained_env != trusted_env
                or retained_local != expected_local
                or len(trusted_records) != 2
                or dict(trusted_records[0]) != retained_env_record
                or manifest["trusted_environment_records_sha256"]
                != _trusted_environment_records_digest(trusted_records)
            ):
                raise BaselineBundleError(
                    "existing_bundle_trusted_environment_mismatch"
                )
            trusted_names = _trusted_environment_names(trusted_env, trusted_local)
        else:
            if (
                authoritative_render_environment is not None
                or authoritative_baseline_environment_names is not None
            ):
                raise BaselineBundleError("authoritative_environment_missing")
            baseline_environment_names = None
            trusted_names = _trusted_environment_names(
                retained_env, trusted_local_prefix
            )
            if manifest["trusted_environment_records_sha256"] not in (
                _recovery_trusted_environment_record_digests(
                    retained_env_record, trusted_local_prefix
                )
            ):
                raise BaselineBundleError(
                    "existing_bundle_trusted_environment_mismatch"
                )

        available_env_only = (
            trusted_names
            - BASELINE_RENDER_ENV_KEYS
            - _explicit_environment_names(blobs)
        )
        retained_override, retained_override_record = _read_at(
            directory_fd,
            NORMALIZATION_OVERRIDE,
            required=True,
            reason="retained_override",
        )
        assert retained_override is not None
        retained_override_names, _reset = _compose_environment_names(
            retained_override
        )
        if baseline_environment_names is None:
            if not retained_override_names <= available_env_only:
                raise BaselineBundleError("existing_bundle_semantics_mismatch")
            env_only = sorted(retained_override_names)
        else:
            env_only = sorted(available_env_only & baseline_environment_names)
        expected_override = _override(env_only)
        recorded_override = compose_records[2]
        if (
            retained_override != expected_override
            or retained_override_record["sha256"] != _sha(expected_override)
            or retained_override_record["size_bytes"] != len(expected_override)
            or recorded_override["sha256"] != _sha(expected_override)
            or recorded_override["size_bytes"] != len(expected_override)
            or manifest["environment_key_count"] != len(env_only)
            or manifest["environment_key_set_sha256"]
            != _sha(_canonical_bytes(env_only))
            or manifest["render_environment_key_count"]
            != len(retained_render_environment)
            or manifest["render_environment_key_set_sha256"]
            != _sha(_canonical_bytes(sorted(retained_render_environment)))
        ):
            raise BaselineBundleError("existing_bundle_semantics_mismatch")
        if _directory_identity(os.fstat(directory_fd)) != anchor:
            raise BaselineBundleError("bundle_directory_changed")
        _revalidate_directory(path, directory_fd, "bundle_directory_changed")
    finally:
        os.close(directory_fd)


def _sealed_retained_blobs(
    path: Path, manifest: Mapping[str, Any]
) -> list[tuple[str, str, bytes]]:
    directory_fd = _open_dir(path, private=True, owner=True)
    anchor = _directory_identity(os.fstat(directory_fd))
    try:
        result: list[tuple[str, str, bytes]] = []
        for index, relative in enumerate(COMPOSE_BLOB_PATHS):
            raw, _record = _read_at(
                directory_fd,
                relative,
                required=True,
                reason="retained_compose",
            )
            assert raw is not None
            object_id = str(manifest["ordered_compose_files"][index]["git_blob_id"])
            if (
                not OBJECT_RE.fullmatch(object_id)
                or _blob_digest(raw, object_id) != object_id
            ):
                raise BaselineBundleError("retained_compose_object_mismatch")
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BaselineBundleError("retained_compose_utf8_invalid") from exc
            result.append((relative, object_id, raw))
        if _directory_identity(os.fstat(directory_fd)) != anchor:
            raise BaselineBundleError("bundle_directory_changed")
        _revalidate_directory(path, directory_fd, "bundle_directory_changed")
        return result
    finally:
        os.close(directory_fd)


def _info(manifest: Mapping[str, Any], manifest_sha: str) -> dict[str, Any]:
    root = Path(str(manifest["bundle_path"]))
    return {
        "bundle_path": str(root),
        "compose_files": [
            str(root / str(item["relative_path"]))
            for item in manifest["ordered_compose_files"]
        ],
        "contract_name": BUNDLE_CONTRACT,
        "environment_files": [
            str(root / str(item["relative_path"]))
            for item in manifest["environment_files"]
            if item["present"]
        ],
        "manifest_path": str(root / MANIFEST_NAME),
        "manifest_sha256": manifest_sha,
        "origin_main_commit": manifest["origin_main_commit"],
        "plan_sha256": manifest["plan_sha256"],
        "source_revision": manifest["source_revision"],
        "version": BUNDLE_VERSION,
    }


def _require_recovery_seal(
    recovery_seal: Mapping[str, object], *, plan_sha: str | None = None
) -> tuple[str, str]:
    if (
        set(recovery_seal) != RECOVERY_SEAL_KEYS
        or recovery_seal.get("contract_name") != RECOVERY_SEAL_CONTRACT
        or not isinstance(recovery_seal.get("manifest_sha256"), str)
        or not SHA_RE.fullmatch(str(recovery_seal.get("manifest_sha256")))
        or not isinstance(recovery_seal.get("plan_sha256"), str)
        or not SHA_RE.fullmatch(str(recovery_seal.get("plan_sha256")))
        or (plan_sha is not None and recovery_seal.get("plan_sha256") != plan_sha)
    ):
        raise BaselineBundleError("trusted_recovery_seal_invalid")
    return (
        str(recovery_seal["manifest_sha256"]),
        str(recovery_seal["plan_sha256"]),
    )


def require_baseline_bundle_seal(
    bundle_info: Mapping[str, object],
) -> dict[str, Any]:
    """Revalidate every retained artifact without consulting mutable inputs."""
    if set(bundle_info) != INFO_KEYS:
        raise BaselineBundleError("bundle_info_schema_invalid")
    path = _path(bundle_info.get("bundle_path"), "bundle_path_invalid")
    manifest, digest = _validate_bundle(path)
    current = _info(manifest, digest)
    if dict(bundle_info) != current:
        raise BaselineBundleError("bundle_info_seal_mismatch")
    return current


def require_recovery_baseline_bundle(
    *,
    bundle_path: Path,
    trusted_recovery_seal: Mapping[str, object],
) -> dict[str, Any]:
    """Recover an occupied retained bundle using only its external journal seal."""
    path = _path(bundle_path, "bundle_path_invalid")
    manifest_sha, plan_sha = _require_recovery_seal(trusted_recovery_seal)
    try:
        occupied = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        raise BaselineBundleError("trusted_recovery_bundle_missing") from None
    except OSError as exc:
        raise BaselineBundleError("trusted_recovery_bundle_unavailable") from exc
    if not stat.S_ISDIR(occupied.st_mode) or stat.S_ISLNK(occupied.st_mode):
        raise BaselineBundleError("bundle_path_occupied")
    manifest, digest = _validate_bundle(path)
    if digest != manifest_sha or manifest["plan_sha256"] != plan_sha:
        raise BaselineBundleError("trusted_recovery_seal_mismatch")
    retained_blobs = _sealed_retained_blobs(path, manifest)
    _require_bundle_semantics(
        path,
        manifest,
        origin_main_commit=str(manifest["origin_main_commit"]),
        blobs=retained_blobs,
        authoritative_environment=None,
        authoritative_render_environment=None,
        authoritative_baseline_environment_names=None,
    )
    return require_baseline_bundle_seal(_info(manifest, digest))


def _default_durable_check(path: Path) -> None:
    for temporary in (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm")):
        if path == temporary or temporary in path.parents:
            raise BaselineBundleError("bundle_parent_not_durable")


def _rename_noreplace(parent_fd: int, source_name: str, destination_name: str) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:  # pragma: no cover - non-Linux fail closed
        raise BaselineBundleError("renameat2_noreplace_unavailable") from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        parent_fd,
        os.fsencode(source_name),
        parent_fd,
        os.fsencode(destination_name),
        1,  # RENAME_NOREPLACE
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise BaselineBundleError("bundle_creation_race")
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise BaselineBundleError("renameat2_noreplace_unavailable")
    raise BaselineBundleError("bundle_publish_failed") from OSError(
        error, os.strerror(error)
    )


def _staging_directory(parent_fd: int, final_name: str) -> tuple[str, int]:
    for _attempt in range(8):
        final_digest = _sha(final_name.encode("ascii"))[:20]
        name = f".api-baseline-staging-{final_digest}-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            os.fchmod(descriptor, 0o700)
            metadata = os.fstat(descriptor)
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or (metadata.st_dev, metadata.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise BaselineBundleError("bundle_staging_identity_invalid")
            return name, descriptor
        except BaselineBundleError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise BaselineBundleError("bundle_staging_open_failed") from exc
    raise BaselineBundleError("bundle_staging_name_unavailable")


_TEST_HOOKS_TOKEN = object()


class _TestHooks:
    __slots__ = ("durable_root_check", "runner", "token")

    def __init__(
        self,
        token: object,
        *,
        runner: Runner | None,
        durable_root_check: Callable[[Path], None],
    ) -> None:
        if token is not _TEST_HOOKS_TOKEN:
            raise BaselineBundleError("test_hooks_authority_invalid")
        self.token = token
        self.runner = runner
        self.durable_root_check = durable_root_check


def _materialize_baseline_bundle(
    *,
    plan: Mapping[str, Any],
    repository_root: Path,
    bundle_parent: Path,
    render_environment: Mapping[str, str] | None,
    baseline_environment_names: Sequence[str] | set[str] | frozenset[str] | None,
    trusted_recovery_seal: Mapping[str, object] | None = None,
    test_hooks: _TestHooks | None,
) -> dict[str, Any]:
    """Create or securely reuse the deterministic plan-bound bundle.

    ``trusted_recovery_seal`` is accepted only for an already-published bundle.
    Its values must come from the durable pre-mutation recovery journal, never
    from the occupied bundle being checked.
    """
    try:
        validate_plan_payload(plan)
    except (PlanError, TypeError, ValueError) as exc:
        raise BaselineBundleError("baseline_plan_invalid") from exc
    revision = str(plan["source_requirements"]["expected_revision"])
    if not REVISION_RE.fullmatch(revision):
        raise BaselineBundleError("source_revision_invalid")
    plan_sha = _sha(_canonical_bytes(plan))
    recovery_manifest_sha: str | None = None
    if trusted_recovery_seal is not None:
        recovery_manifest_sha, _recovery_plan_sha = _require_recovery_seal(
            trusted_recovery_seal, plan_sha=plan_sha
        )
    fresh_render_environment: dict[str, str] | None = None
    fresh_baseline_environment_names: set[str] | None = None
    if trusted_recovery_seal is None:
        if render_environment is None:
            raise BaselineBundleError("render_environment_missing")
        if baseline_environment_names is None:
            raise BaselineBundleError("baseline_environment_names_missing")
        fresh_render_environment = _validated_render_environment(render_environment)
        fresh_baseline_environment_names = _validated_baseline_environment_names(
            baseline_environment_names
        )
        if (
            fresh_render_environment["EA_SOURCE_REVISION"] != revision
            or fresh_render_environment["EA_MEMORIAL_IMAGE"]
            != plan["source_requirements"]["expected_image_reference"]
        ):
            raise BaselineBundleError("render_environment_plan_mismatch")
    if test_hooks is not None and test_hooks.token is not _TEST_HOOKS_TOKEN:
        raise BaselineBundleError("test_hooks_authority_invalid")
    durable_root_check = (
        _default_durable_check if test_hooks is None else test_hooks.durable_root_check
    )

    parent = _path(bundle_parent, "bundle_parent_invalid")
    durable_root_check(parent)
    parent_fd = _open_dir(parent, private=True, owner=True)
    name = "api-baseline-v3-" + str(plan["plan_id"])
    if not NAME_RE.fullmatch(name):
        os.close(parent_fd)
        raise BaselineBundleError("bundle_name_invalid")
    bundle_path = parent / name
    try:
        try:
            occupied = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            occupied = None
        if recovery_manifest_sha is not None:
            if occupied is None:
                raise BaselineBundleError("trusted_recovery_bundle_missing")
            if not stat.S_ISDIR(occupied.st_mode):
                raise BaselineBundleError("bundle_path_occupied")
            recovered = require_recovery_baseline_bundle(
                bundle_path=bundle_path,
                trusted_recovery_seal=trusted_recovery_seal,
            )
            if (
                recovered["plan_sha256"] != plan_sha
                or recovered["source_revision"] != revision
            ):
                raise BaselineBundleError("existing_bundle_plan_mismatch")
            _revalidate_directory(parent, parent_fd, "bundle_parent_changed")
            return recovered

        if test_hooks is None or test_hooks.runner is None:
            runner: Runner = SubprocessRunner()
            git_identity = _git_executable_identity()
        else:
            runner = test_hooks.runner
            git_identity = None
        repository = _path(repository_root, "repository_root_invalid")
        repository_fd = _open_dir(repository, private=False, owner=True)
        repository_anchor = _directory_identity(os.fstat(repository_fd))
        try:
            repository_cwd = _repository_descriptor_cwd(repository_fd)
            origin_main_commit, blobs = _git_blobs(runner, repository_cwd, revision)
            if _directory_identity(os.fstat(repository_fd)) != repository_anchor:
                raise BaselineBundleError("repository_root_changed")
            _revalidate_directory(repository, repository_fd, "repository_root_changed")
        finally:
            os.close(repository_fd)
        if git_identity is not None and _git_executable_identity() != git_identity:
            raise BaselineBundleError("git_executable_changed")

        if occupied is not None:
            if not stat.S_ISDIR(occupied.st_mode):
                raise BaselineBundleError("bundle_path_occupied")
            manifest, digest = _validate_bundle(bundle_path)
            if (
                manifest["plan_sha256"] != plan_sha
                or manifest["source_revision"] != revision
            ):
                raise BaselineBundleError("existing_bundle_plan_mismatch")
            trusted_root = _path(
                plan["activation_condition"]["trusted_environment_root"],
                "trusted_environment_root_invalid",
            )
            authoritative_environment = _read_trusted_environment(trusted_root)
            _require_bundle_semantics(
                bundle_path,
                manifest,
                origin_main_commit=origin_main_commit,
                blobs=blobs,
                authoritative_environment=authoritative_environment,
                authoritative_render_environment=fresh_render_environment,
                authoritative_baseline_environment_names=(
                    fresh_baseline_environment_names
                ),
            )
            info = _info(manifest, digest)
            _revalidate_directory(parent, parent_fd, "bundle_parent_changed")
            return require_baseline_bundle_seal(info)

        trusted_root = _path(
            plan["activation_condition"]["trusted_environment_root"],
            "trusted_environment_root_invalid",
        )
        env_raw, local_raw, trusted_environment_records = _read_trusted_environment(
            trusted_root
        )
        trusted_names = _trusted_environment_names(env_raw, local_raw)
        assert fresh_render_environment is not None
        augmented_local_raw = _augmented_environment_local(
            local_raw, fresh_render_environment
        )
        env_only = sorted(
            (
                trusted_names
                - BASELINE_RENDER_ENV_KEYS
                - _explicit_environment_names(blobs)
            )
            & fresh_baseline_environment_names
        )
        override_raw = _override(env_only)

        staging_name, bundle_fd = _staging_directory(parent_fd, name)
        try:
            compose_records = [
                _write_at(bundle_fd, relative, raw, blob_id=object_id)
                for relative, object_id, raw in blobs
            ]
            compose_records.append(
                _write_at(bundle_fd, NORMALIZATION_OVERRIDE, override_raw)
            )
            copied_environment_records = [
                _write_at(bundle_fd, ".env", env_raw),
                _write_at(bundle_fd, ".env.local", augmented_local_raw),
            ]
            if copied_environment_records[0] != trusted_environment_records[0]:
                raise BaselineBundleError("environment_copy_identity_mismatch")
            manifest = {
                "ancestry_ref": "origin/main",
                "bundle_path": str(bundle_path),
                "contract_name": BUNDLE_CONTRACT,
                "environment_files": copied_environment_records,
                "environment_key_count": len(env_only),
                "environment_key_set_sha256": _sha(_canonical_bytes(env_only)),
                "ordered_compose_files": compose_records,
                "origin_main_commit": origin_main_commit,
                "plan_sha256": plan_sha,
                "render_environment_key_count": len(fresh_render_environment),
                "render_environment_key_set_sha256": _sha(
                    _canonical_bytes(sorted(fresh_render_environment))
                ),
                "source_revision": revision,
                "trusted_environment_records_sha256": (
                    _trusted_environment_records_digest(trusted_environment_records)
                ),
                "version": BUNDLE_VERSION,
            }
            manifest_raw = (
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            _write_at(bundle_fd, MANIFEST_NAME, manifest_raw)
            os.fsync(bundle_fd)
            os.fsync(parent_fd)
            staging_identity = _directory_object_identity(os.fstat(bundle_fd))
            _rename_noreplace(parent_fd, staging_name, name)
            published = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if _directory_object_identity(published) != staging_identity:
                raise BaselineBundleError("bundle_publish_identity_mismatch")
            _absent_at(parent_fd, staging_name, "bundle_staging")
            os.fsync(parent_fd)
            _revalidate_directory(parent, parent_fd, "bundle_parent_changed")
        finally:
            os.close(bundle_fd)
    finally:
        os.close(parent_fd)

    manifest, digest = _validate_bundle(bundle_path)
    _require_bundle_semantics(
        bundle_path,
        manifest,
        origin_main_commit=origin_main_commit,
        blobs=blobs,
        authoritative_environment=(
            env_raw,
            local_raw,
            trusted_environment_records,
        ),
        authoritative_render_environment=fresh_render_environment,
        authoritative_baseline_environment_names=fresh_baseline_environment_names,
    )
    return require_baseline_bundle_seal(_info(manifest, digest))


def materialize_baseline_bundle(
    *,
    plan: Mapping[str, Any],
    repository_root: Path,
    bundle_parent: Path,
    render_environment: Mapping[str, str] | None,
    baseline_environment_names: (
        Sequence[str] | set[str] | frozenset[str] | None
    ) = None,
    trusted_recovery_seal: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Production entry point with fixed Git and durability policy."""
    return _materialize_baseline_bundle(
        plan=plan,
        repository_root=repository_root,
        bundle_parent=bundle_parent,
        render_environment=render_environment,
        baseline_environment_names=baseline_environment_names,
        trusted_recovery_seal=trusted_recovery_seal,
        test_hooks=None,
    )


def _materialize_baseline_bundle_for_test(
    *,
    plan: Mapping[str, Any],
    repository_root: Path,
    bundle_parent: Path,
    render_environment: Mapping[str, str] | None,
    baseline_environment_names: (
        Sequence[str] | set[str] | frozenset[str] | None
    ) = None,
    test_runner: Runner | None,
    trusted_recovery_seal: Mapping[str, object] | None = None,
    durable_root_check: Callable[[Path], None],
) -> dict[str, Any]:
    hooks = _TestHooks(
        _TEST_HOOKS_TOKEN,
        runner=test_runner,
        durable_root_check=durable_root_check,
    )
    return _materialize_baseline_bundle(
        plan=plan,
        repository_root=repository_root,
        bundle_parent=bundle_parent,
        render_environment=render_environment,
        baseline_environment_names=baseline_environment_names,
        trusted_recovery_seal=trusted_recovery_seal,
        test_hooks=hooks,
    )


__all__ = [
    "BASELINE_RENDER_ENV_KEYS",
    "BUNDLE_CONTRACT",
    "BUNDLE_VERSION",
    "RECOVERY_SEAL_CONTRACT",
    "BaselineBundleError",
    "Runner",
    "SubprocessRunner",
    "materialize_baseline_bundle",
    "require_baseline_bundle_seal",
    "require_recovery_baseline_bundle",
]
