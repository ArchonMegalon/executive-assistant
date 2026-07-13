#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping
import uuid
import xml.etree.ElementTree as ET


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
DEFAULT_OUTPUT = Path(
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
)
CONTRACT_NAME = "ea.browser_workflow_proof"
CONTRACT_VERSION = 3
PRODUCT = "executive-assistant"
SURFACE = "browser_workflow_proof"
KIND = "proof_receipt"
GENERATED_BY = "scripts/materialize_ea_browser_workflow_proof.py"
TRUST_MODEL = "local_unsigned_process_evidence"
ENVIRONMENT_POLICY_NAME = "ea.browser_workflow_proof.hermetic"
ENVIRONMENT_POLICY_VERSION = 1
GIT_BIN = Path("/usr/bin/git")
MAX_JUNIT_BYTES = 1024 * 1024
MAX_OUTPUT_LINES = 40
SOURCE_BACKED_TEST_FILE = "tests/test_product_browser_journeys.py"
REAL_BROWSER_TEST_FILE = "tests/e2e/test_product_workflows.py"
SOURCE_STATE_STAGES = [
    "before_tests",
    "after_source",
    "after_browser",
    "before_publish",
]
SNAPSHOT_SEAL_ALGORITHM = "sha256-content-posix-stat-v1"
SNAPSHOT_SEAL_STAGES = ["before_source", "after_source", "after_browser"]
SNAPSHOT_READ_ONLY_ENFORCEMENT = (
    "owner_mode_bits_plus_content_stat_seal_and_inotify_watch"
)
SNAPSHOT_MUTATION_WATCH_ALGORITHM = "linux-inotify-v1"
SNAPSHOT_MUTATION_WATCH_STAGES = ["after_source", "after_browser"]
RUNNER_ROOT_KIND = "committed_mode_read_only_mutation_watched_snapshot"
SOURCE_BACKED_CASES = [
    "test_workspace_pages_render_seeded_product_objects",
    "test_browser_journey_updates_after_approval_and_commitment_closure",
    "test_browser_action_routes_match_rendered_forms",
    "test_browser_handoff_and_people_memory_actions_work",
]
REAL_BROWSER_CASES = [
    "test_activation_and_memo_flow_in_real_browser",
    "test_draft_and_commitment_workflows_in_real_browser",
]
DEPENDENCY_NAMES = ("playwright", "pytest", "uvicorn")

COMMON_ENVIRONMENT_TEMPLATE = {
    "PATH": "/usr/bin:/bin",
    "HOME": "{private_home}",
    "TMPDIR": "{private_tmp}",
    "TMP": "{private_tmp}",
    "TEMP": "{private_tmp}",
    "XDG_CACHE_HOME": "{private_xdg_cache}",
    "XDG_CONFIG_HOME": "{private_xdg_config}",
    "XDG_DATA_HOME": "{private_xdg_data}",
    "XDG_STATE_HOME": "{private_xdg_state}",
    "XDG_RUNTIME_DIR": "{private_xdg_runtime}",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "PYTHONPATH": "{snapshot_root}/ea:{snapshot_root}:{dependency_root}",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPYCACHEPREFIX": "{private_pycache}",
    "PYTHONHASHSEED": "0",
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "NO_PROXY": "127.0.0.1,localhost,::1",
}
BROWSER_ENVIRONMENT_TEMPLATE = {
    "PLAYWRIGHT_BROWSERS_PATH": "{browser_cache}",
    "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
    "EA_STORAGE_BACKEND": "memory",
    "EA_API_TOKEN": "",
    "EA_DEFAULT_PRINCIPAL_ID": "principal-default",
    "EA_ALLOW_LOOPBACK_NO_AUTH": "1",
    "EA_ENABLE_PUBLIC_SIDE_SURFACES": "0",
    "EA_ENABLE_PUBLIC_RESULTS": "0",
    "EA_ENABLE_PUBLIC_TOURS": "0",
}


class _DuplicateJSONKey(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise _DuplicateJSONKey(key)
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    if type(payload) is not dict:
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _is_canonical_digest(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_canonical_revision(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is not None
    )


def _git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "XDG_CONFIG_HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run_git(root: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GIT_BIN.as_posix(), *arguments],
        cwd=root,
        env=_git_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


def _relative_output_exclusion(root: Path, output_path: Path | None) -> str | None:
    if output_path is None:
        return None
    absolute_root = root.resolve()
    absolute_output = output_path.resolve(strict=False)
    try:
        relative = absolute_output.relative_to(absolute_root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return f":(top,exclude,literal){relative.as_posix()}"


def _git_source_state(
    root: Path,
    *,
    excluded_output: Path | None = None,
) -> dict[str, Any]:
    revision_result = _run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"])
    tree_result = _run_git(root, ["rev-parse", "--verify", "HEAD^{tree}"])
    revision = str(revision_result.stdout or "").strip()
    tree = str(tree_result.stdout or "").strip()
    if (
        revision_result.returncode != 0
        or tree_result.returncode != 0
        or not _is_canonical_revision(revision)
        or not _is_canonical_revision(tree)
        or len(revision) != len(tree)
    ):
        raise RuntimeError("could not resolve canonical HEAD commit and tree")

    status_arguments = [
        "status",
        "--porcelain=v1",
        "--untracked-files=normal",
        "--",
        ".",
    ]
    exclusion = _relative_output_exclusion(root, excluded_output)
    if exclusion is not None:
        status_arguments.append(exclusion)
    status_result = _run_git(root, status_arguments)
    if status_result.returncode != 0:
        raise RuntimeError("could not inspect source worktree state")
    return {
        "revision": revision,
        "tree": tree,
        "dirty": bool(str(status_result.stdout or "").strip()),
    }


def _capture_source_sample(
    source_state: Callable[..., dict[str, Any]],
    root: Path,
    *,
    stage: str,
    excluded_output: Path | None,
) -> dict[str, Any]:
    observed = source_state(root, excluded_output=excluded_output)
    if not isinstance(observed, dict):
        raise RuntimeError("source state callback returned an invalid value")
    return {
        "stage": stage,
        "revision": observed.get("revision"),
        "tree": observed.get("tree"),
        "dirty": observed.get("dirty"),
    }


def _source_state_samples_are_exact(
    samples: object,
    *,
    expected_revision: str | None = None,
    expected_tree: str | None = None,
) -> bool:
    if type(samples) is not list or len(samples) != len(SOURCE_STATE_STAGES):
        return False
    revisions: list[str] = []
    trees: list[str] = []
    for stage, sample in zip(SOURCE_STATE_STAGES, samples, strict=True):
        if not isinstance(sample, dict) or sample.get("stage") != stage:
            return False
        revision = sample.get("revision")
        tree = sample.get("tree")
        if (
            not _is_canonical_revision(revision)
            or not _is_canonical_revision(tree)
            or len(revision) != len(tree)
            or sample.get("dirty") is not False
        ):
            return False
        revisions.append(revision)
        trees.append(tree)
    if len(set(revisions)) != 1 or len(set(trees)) != 1:
        return False
    return bool(
        (expected_revision is None or revisions[0] == expected_revision)
        and (expected_tree is None or trees[0] == expected_tree)
    )


def _archive_snapshot(
    root: Path,
    destination: Path,
    *,
    revision: str,
) -> Path:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    archive_path = destination.parent / "source.tar"
    with archive_path.open("wb") as archive_file:
        result = subprocess.run(
            [GIT_BIN.as_posix(), "archive", "--format=tar", revision],
            cwd=root,
            env=_git_environment(),
            stdout=archive_file,
            stderr=subprocess.PIPE,
            check=False,
        )
        archive_file.flush()
        os.fsync(archive_file.fileno())
    if result.returncode != 0:
        raise RuntimeError("could not create committed source archive")

    destination_resolved = destination.resolve()
    with tarfile.open(archive_path, mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            target = (destination / member.name).resolve(strict=False)
            try:
                target.relative_to(destination_resolved)
            except ValueError as exc:
                raise RuntimeError("git archive contained an unsafe path") from exc
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("git archive contained a non-file entry")
        archive.extractall(destination, members=members)
    archive_path.unlink()
    _make_tree_read_only(destination)
    return destination


def _make_tree_read_only(root: Path) -> None:
    for current_root, directories, files in os.walk(root, topdown=False):
        current = Path(current_root)
        for filename in files:
            (current / filename).chmod(0o444)
        for directory in directories:
            (current / directory).chmod(0o555)
    root.chmod(0o555)


def _snapshot_is_read_only(root: Path) -> bool:
    for current_root, directories, files in os.walk(root):
        current = Path(current_root)
        for name in [".", *directories, *files]:
            path = current if name == "." else current / name
            try:
                mode = stat.S_IMODE(path.stat().st_mode)
            except OSError:
                return False
            if mode & 0o222:
                return False
    return True


def _snapshot_filesystem_seal(root: Path) -> str:
    """Seal snapshot content and metadata around each execution lane.

    The receipt is explicitly local unsigned evidence, so this is not a
    signature. Content hashes bind the final bytes while inode and timestamp
    metadata detect ordinary replacements. A separate inotify watch records
    transient same-UID mutations even on coarse-timestamp filesystems.
    """

    rows: list[dict[str, object]] = []
    for current_root, directories, files in os.walk(root):
        directories.sort()
        files.sort()
        current = Path(current_root)
        paths = [current, *(current / name for name in files)]
        for path in paths:
            metadata = path.stat(follow_symlinks=False)
            relative = path.relative_to(root).as_posix() if path != root else "."
            rows.append(
                {
                    "path": relative,
                    "kind": "directory" if stat.S_ISDIR(metadata.st_mode) else "file",
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
                    "device": metadata.st_dev,
                    "inode": metadata.st_ino,
                    "size": metadata.st_size,
                    "mtime_ns": metadata.st_mtime_ns,
                    "ctime_ns": metadata.st_ctime_ns,
                    "content_sha256": (
                        _sha256_file(path) if stat.S_ISREG(metadata.st_mode) else None
                    ),
                }
            )
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_seal_samples_are_exact(samples: object) -> bool:
    if type(samples) is not list or len(samples) != len(SNAPSHOT_SEAL_STAGES):
        return False
    digests: list[str] = []
    for stage, sample in zip(SNAPSHOT_SEAL_STAGES, samples, strict=True):
        if (
            not isinstance(sample, dict)
            or set(sample) != {"stage", "sha256"}
            or sample.get("stage") != stage
            or not _is_canonical_digest(sample.get("sha256"))
        ):
            return False
        digests.append(sample["sha256"])
    return len(set(digests)) == 1


class _SnapshotMutationWatcher:
    _EVENT = struct.Struct("iIII")
    _IN_MODIFY = 0x00000002
    _IN_ATTRIB = 0x00000004
    _IN_CLOSE_WRITE = 0x00000008
    _IN_MOVED_FROM = 0x00000040
    _IN_MOVED_TO = 0x00000080
    _IN_CREATE = 0x00000100
    _IN_DELETE = 0x00000200
    _IN_DELETE_SELF = 0x00000400
    _IN_MOVE_SELF = 0x00000800
    _IN_Q_OVERFLOW = 0x00004000
    _MASK = (
        _IN_MODIFY
        | _IN_ATTRIB
        | _IN_CLOSE_WRITE
        | _IN_MOVED_FROM
        | _IN_MOVED_TO
        | _IN_CREATE
        | _IN_DELETE
        | _IN_DELETE_SELF
        | _IN_MOVE_SELF
    )

    def __init__(self, root: Path) -> None:
        self._libc = ctypes.CDLL(None, use_errno=True)
        init = self._libc.inotify_init1
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        add_watch = self._libc.inotify_add_watch
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        self._descriptor = init(os.O_NONBLOCK | os.O_CLOEXEC)
        if self._descriptor < 0:
            raise OSError(ctypes.get_errno(), "could not initialize snapshot inotify")
        try:
            directories = [Path(current) for current, _, _ in os.walk(root)]
            for directory in sorted(directories, key=lambda path: path.as_posix()):
                if (
                    add_watch(
                        self._descriptor,
                        os.fsencode(directory),
                        self._MASK,
                    )
                    < 0
                ):
                    raise OSError(
                        ctypes.get_errno(),
                        f"could not watch snapshot directory: {directory}",
                    )
            self.drain()
        except Exception:
            self.close()
            raise

    def drain(self) -> dict[str, object]:
        event_count = 0
        overflow = False
        while True:
            try:
                payload = os.read(self._descriptor, 1024 * 1024)
            except BlockingIOError:
                break
            if not payload:
                break
            offset = 0
            while offset < len(payload):
                if len(payload) - offset < self._EVENT.size:
                    raise RuntimeError("snapshot inotify returned a truncated event")
                _, mask, _, name_length = self._EVENT.unpack_from(payload, offset)
                offset += self._EVENT.size + name_length
                if offset > len(payload):
                    raise RuntimeError("snapshot inotify returned an invalid event")
                event_count += 1
                overflow = overflow or bool(mask & self._IN_Q_OVERFLOW)
        return {"event_count": event_count, "overflow": overflow}

    def close(self) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1


def _snapshot_mutation_samples_are_exact(samples: object) -> bool:
    if type(samples) is not list or len(samples) != len(SNAPSHOT_MUTATION_WATCH_STAGES):
        return False
    for stage, sample in zip(SNAPSHOT_MUTATION_WATCH_STAGES, samples, strict=True):
        if (
            not isinstance(sample, dict)
            or set(sample) != {"stage", "event_count", "overflow"}
            or sample.get("stage") != stage
            or type(sample.get("event_count")) is not int
            or sample.get("event_count") != 0
            or sample.get("overflow") is not False
        ):
            return False
    return True


def _make_tree_owner_writable(root: Path) -> None:
    for current_root, directories, files in os.walk(root):
        current = Path(current_root)
        current.chmod(0o700)
        for directory in directories:
            (current / directory).chmod(0o700)
        for filename in files:
            (current / filename).chmod(0o600)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_python_bin(root: Path) -> str:
    venv_python = root / ".venv" / "bin" / "python"
    candidate = venv_python if venv_python.exists() else Path(sys.executable)
    # Preserve the lexical venv launcher path. Resolving its symlink to the
    # system target would make Python skip the adjacent pyvenv.cfg.
    return Path(os.path.abspath(os.path.normpath(os.fspath(candidate)))).as_posix()


def _runtime_context(python_bin: str) -> tuple[dict[str, Any], Path]:
    invocation = Path(os.path.abspath(os.path.normpath(os.fspath(Path(python_bin)))))
    executable_target = invocation.resolve(strict=True)
    if not executable_target.is_file():
        raise RuntimeError("selected Python executable is not a regular file")
    probe_script = (
        "import importlib.metadata,json,platform,site,sys;"
        "sys.path.insert(0,site.getusersitepackages());"
        f"names={list(DEPENDENCY_NAMES)!r};"
        "versions={name:(importlib.metadata.version(name) "
        "if any(d.metadata.get('Name','').lower()==name for d in importlib.metadata.distributions()) "
        "else None) for name in names};"
        "print(json.dumps({'version':platform.python_version(),"
        "'dependency_root':site.getusersitepackages(),'dependencies':versions},sort_keys=True))"
    )
    probe = subprocess.run(
        [invocation.as_posix(), "-I", "-c", probe_script],
        env={
            "PATH": "/usr/bin:/bin",
            # ``site.getusersitepackages()`` is derived from HOME. Keep the
            # operator's canonical home while ``-I`` prevents implicit user
            # site loading; the probe adds that one dependency root explicitly.
            "HOME": _operator_home().as_posix(),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError("could not resolve canonical Python runtime identity")
    payload = json.loads(
        str(probe.stdout or ""),
        object_pairs_hook=_unique_json_object,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Python runtime identity probe returned invalid JSON")
    dependency_root = Path(str(payload.get("dependency_root") or "")).resolve(
        strict=False
    )
    dependencies = payload.get("dependencies")
    if (
        not isinstance(dependencies, dict)
        or set(dependencies) != set(DEPENDENCY_NAMES)
        or any(
            type(dependencies[name]) is not str or not dependencies[name]
            for name in DEPENDENCY_NAMES
        )
    ):
        raise RuntimeError("Python dependency identity is incomplete")
    identity = {
        "executable": invocation.as_posix(),
        "sha256": _sha256_file(executable_target),
        "version": str(payload.get("version") or ""),
        "dependency_root": dependency_root.as_posix(),
        "dependency_versions": {
            name: dependencies.get(name) for name in DEPENDENCY_NAMES
        },
    }
    return identity, dependency_root


def _operator_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)


def _browser_cache_path(operator_env: Mapping[str, str]) -> Path:
    configured = str(operator_env.get("PLAYWRIGHT_BROWSERS_PATH") or "")
    if configured and Path(configured).is_absolute():
        return Path(configured).resolve(strict=False)
    return (_operator_home() / ".cache" / "ms-playwright").resolve(strict=False)


def _environment_policy(real_browser: bool) -> dict[str, Any]:
    normalized_values = dict(COMMON_ENVIRONMENT_TEMPLATE)
    if real_browser:
        normalized_values.update(BROWSER_ENVIRONMENT_TEMPLATE)
    return {
        "name": ENVIRONMENT_POLICY_NAME,
        "version": ENVIRONMENT_POLICY_VERSION,
        "allowed_keys": sorted(normalized_values),
        "normalized_values": normalized_values,
        "explicit_plugins": [],
    }


def _child_environment(
    snapshot_root: Path,
    private_root: Path,
    *,
    dependency_root: Path,
    real_browser: bool,
    operator_env: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, Any]]:
    directories = {
        "private_home": private_root / "home",
        "private_tmp": private_root / "tmp",
        "private_xdg_cache": private_root / "xdg" / "cache",
        "private_xdg_config": private_root / "xdg" / "config",
        "private_xdg_data": private_root / "xdg" / "data",
        "private_xdg_state": private_root / "xdg" / "state",
        "private_xdg_runtime": private_root / "xdg" / "runtime",
        "private_pycache": private_root / "pycache",
    }
    for directory in directories.values():
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    values = {
        "PATH": "/usr/bin:/bin",
        "HOME": directories["private_home"].as_posix(),
        "TMPDIR": directories["private_tmp"].as_posix(),
        "TMP": directories["private_tmp"].as_posix(),
        "TEMP": directories["private_tmp"].as_posix(),
        "XDG_CACHE_HOME": directories["private_xdg_cache"].as_posix(),
        "XDG_CONFIG_HOME": directories["private_xdg_config"].as_posix(),
        "XDG_DATA_HOME": directories["private_xdg_data"].as_posix(),
        "XDG_STATE_HOME": directories["private_xdg_state"].as_posix(),
        "XDG_RUNTIME_DIR": directories["private_xdg_runtime"].as_posix(),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONPATH": os.pathsep.join(
            [
                (snapshot_root / "ea").as_posix(),
                snapshot_root.as_posix(),
                dependency_root.as_posix(),
            ]
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": directories["private_pycache"].as_posix(),
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "NO_PROXY": "127.0.0.1,localhost,::1",
    }
    if real_browser:
        values.update(
            {
                "PLAYWRIGHT_BROWSERS_PATH": _browser_cache_path(
                    operator_env
                ).as_posix(),
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                "EA_STORAGE_BACKEND": "memory",
                "EA_API_TOKEN": "",
                "EA_DEFAULT_PRINCIPAL_ID": "principal-default",
                "EA_ALLOW_LOOPBACK_NO_AUTH": "1",
                "EA_ENABLE_PUBLIC_SIDE_SURFACES": "0",
                "EA_ENABLE_PUBLIC_RESULTS": "0",
                "EA_ENABLE_PUBLIC_TOURS": "0",
            }
        )
    policy = _environment_policy(real_browser)
    if sorted(values) != policy["allowed_keys"]:
        raise RuntimeError("child environment does not match its allowlist")
    return values, policy


def _browser_identity(
    python_bin: str,
    environment: dict[str, str],
) -> dict[str, str] | None:
    probe_script = (
        "from playwright.sync_api import sync_playwright;"
        "p=sync_playwright().start();"
        "print(p.chromium.executable_path);"
        "p.stop()"
    )
    probe = subprocess.run(
        [python_bin, "-c", probe_script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    executable = Path(str(probe.stdout or "").strip()).resolve(strict=False)
    if not executable.is_file():
        return None
    return {
        "executable": executable.as_posix(),
        "sha256": _sha256_file(executable),
    }


def _expected_node_ids(test_file: str, cases: list[str]) -> list[str]:
    return [f"{test_file}::{case}" for case in cases]


def _normalized_argv_template(test_file: str, cases: list[str]) -> list[str]:
    return [
        "{python_executable}",
        "-m",
        "pytest",
        "-q",
        "-rXx",
        "--color=no",
        "-o",
        "addopts=",
        "-o",
        "xfail_strict=true",
        "-p",
        "no:cacheprovider",
        "--confcutdir",
        "{snapshot_root}",
        "--basetemp",
        "{private_basetemp}",
        "--junitxml={private_junit_xml}",
        *_expected_node_ids(test_file, cases),
    ]


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _strict_xml_count(value: object) -> int | None:
    if type(value) is not str or re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
        return None
    return int(value)


def _empty_junit_evidence() -> dict[str, Any]:
    return {
        "executed_count": 0,
        "passed_count": 0,
        "failed_count": 0,
        "error_count": 0,
        "skipped_count": 0,
        "xfail_count": 0,
        "xpass_count": 0,
        "executed_cases": [],
        "passed_cases": [],
        "junit_declared_tests_count": -1,
        "junit_declared_failure_count": -1,
        "junit_declared_error_count": -1,
        "junit_declared_skipped_count": -1,
        "junit_totals_consistent": False,
    }


def _derived_junit_totals(element: ET.Element) -> dict[str, int]:
    testcases = [
        child for child in element.iter() if _xml_local_name(child.tag) == "testcase"
    ]
    return {
        "tests": len(testcases),
        "failures": sum(
            any(_xml_local_name(child.tag) == "failure" for child in testcase)
            for testcase in testcases
        ),
        "errors": sum(
            any(_xml_local_name(child.tag) == "error" for child in testcase)
            for testcase in testcases
        ),
        "skipped": sum(
            any(_xml_local_name(child.tag) == "skipped" for child in testcase)
            for testcase in testcases
        ),
    }


def _declared_junit_totals(root: ET.Element) -> dict[str, Any]:
    invalid = {
        "junit_declared_tests_count": -1,
        "junit_declared_failure_count": -1,
        "junit_declared_error_count": -1,
        "junit_declared_skipped_count": -1,
        "junit_totals_consistent": False,
    }
    suites = [
        element
        for element in root.iter()
        if _xml_local_name(element.tag) == "testsuite"
    ]
    if not suites:
        return invalid
    declared_by_id: dict[int, dict[str, int]] = {}
    consistent = True
    for suite in suites:
        declared: dict[str, int] = {}
        for field in ("tests", "failures", "errors", "skipped"):
            count = _strict_xml_count(suite.attrib.get(field))
            if count is None:
                consistent = False
                break
            declared[field] = count
        if len(declared) != 4:
            continue
        declared_by_id[id(suite)] = declared
        if declared != _derived_junit_totals(suite):
            consistent = False
    top_suites = (
        [root]
        if _xml_local_name(root.tag) == "testsuite"
        else [child for child in root if _xml_local_name(child.tag) == "testsuite"]
    )
    if not top_suites or any(id(suite) not in declared_by_id for suite in top_suites):
        return invalid
    aggregate = {
        field: sum(declared_by_id[id(suite)][field] for suite in top_suites)
        for field in ("tests", "failures", "errors", "skipped")
    }
    derived = _derived_junit_totals(root)
    if aggregate != derived:
        consistent = False
    if _xml_local_name(root.tag) == "testsuites" and any(
        field in root.attrib for field in ("tests", "failures", "errors", "skipped")
    ):
        root_declared = {
            field: _strict_xml_count(root.attrib.get(field))
            for field in ("tests", "failures", "errors", "skipped")
        }
        if (
            any(value is None for value in root_declared.values())
            or root_declared != derived
        ):
            consistent = False
    return {
        "junit_declared_tests_count": aggregate["tests"],
        "junit_declared_failure_count": aggregate["failures"],
        "junit_declared_error_count": aggregate["errors"],
        "junit_declared_skipped_count": aggregate["skipped"],
        "junit_totals_consistent": consistent,
    }


def _parse_junit_xml(xml_text: str) -> dict[str, Any]:
    evidence = _empty_junit_evidence()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return evidence
    executed_cases: list[str] = []
    passed_cases: list[str] = []
    for testcase in (
        element for element in root.iter() if _xml_local_name(element.tag) == "testcase"
    ):
        name = str(testcase.attrib.get("name") or "")
        executed_cases.append(name)
        children = list(testcase)
        failures = [
            child for child in children if _xml_local_name(child.tag) == "failure"
        ]
        errors = [child for child in children if _xml_local_name(child.tag) == "error"]
        skips = [child for child in children if _xml_local_name(child.tag) == "skipped"]
        evidence["failed_count"] += len(failures)
        evidence["error_count"] += len(errors)
        if (
            failures
            and "XPASS"
            in " ".join(
                f"{child.attrib.get('message', '')} {child.text or ''}"
                for child in failures
            ).upper()
        ):
            evidence["xpass_count"] += 1
        if skips:
            skip_text = " ".join(
                f"{child.attrib.get('type', '')} {child.attrib.get('message', '')} {child.text or ''}"
                for child in skips
            ).lower()
            if "xfail" in skip_text:
                evidence["xfail_count"] += len(skips)
            else:
                evidence["skipped_count"] += len(skips)
        if not failures and not errors and not skips:
            passed_cases.append(name)
    evidence.update(
        {
            "executed_count": len(executed_cases),
            "passed_count": len(passed_cases),
            "executed_cases": executed_cases,
            "passed_cases": passed_cases,
        }
    )
    evidence.update(_declared_junit_totals(root))
    return evidence


def _parse_terminal_summary(summary: str, *, full_output: str = "") -> dict[str, int]:
    evidence = {
        "terminal_passed_count": -1,
        "terminal_xfail_count": -1,
        "terminal_xpass_count": -1,
    }
    line = summary.strip().strip("=").strip()
    match = re.fullmatch(
        r"(?P<outcomes>(?:[0-9]+ [A-Za-z]+)(?:, [0-9]+ [A-Za-z]+)*) "
        r"in [0-9]+(?:\.[0-9]+)?s",
        line,
    )
    if match is not None:
        parsed: dict[str, int] = {}
        valid = True
        for outcome in match.group("outcomes").split(", "):
            count_text, label = outcome.split(" ", 1)
            count = _strict_xml_count(count_text)
            label = label.lower()
            if (
                count is None
                or label in parsed
                or label not in {"passed", "xfailed", "xpassed"}
            ):
                valid = False
                break
            parsed[label] = count
        if valid:
            evidence = {
                "terminal_passed_count": parsed.get("passed", 0),
                "terminal_xfail_count": parsed.get("xfailed", 0),
                "terminal_xpass_count": parsed.get("xpassed", 0),
            }
    inspected = full_output or summary
    if re.search(r"\bxfail(?:ed)?\b", inspected, flags=re.IGNORECASE):
        evidence["terminal_xfail_count"] = max(1, evidence["terminal_xfail_count"])
    if re.search(r"\bxpass(?:ed)?\b", inspected, flags=re.IGNORECASE):
        evidence["terminal_xpass_count"] = max(1, evidence["terminal_xpass_count"])
    return evidence


def _terminal_summary(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _truncate_output(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()][
        :MAX_OUTPUT_LINES
    ]


def _extract_limitations(text: str) -> list[str]:
    lowered = text.lower()
    limitations: list[str] = []
    if "no module named 'uvicorn'" in lowered or 'no module named "uvicorn"' in lowered:
        limitations.append(
            "uvicorn is not installed in the selected Python environment"
        )
    if (
        "no module named 'playwright'" in lowered
        or 'no module named "playwright"' in lowered
    ):
        limitations.append(
            "playwright is not installed in the selected Python environment"
        )
    if "executable doesn't exist" in lowered or "browser_type.launch" in lowered:
        limitations.append("playwright browser binaries are not installed")
    return limitations


def _read_bounded_junit(path: Path) -> tuple[str, str, list[str]]:
    try:
        payload = path.read_bytes()
    except OSError:
        return "", hashlib.sha256(b"").hexdigest(), ["JUnit report is missing"]
    if len(payload) > MAX_JUNIT_BYTES:
        return "", hashlib.sha256(b"").hexdigest(), ["JUnit report exceeds 1 MiB"]
    try:
        xml_text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "", hashlib.sha256(payload).hexdigest(), ["JUnit report is not UTF-8"]
    return xml_text, hashlib.sha256(payload).hexdigest(), []


def _python_identity_is_complete(identity: object) -> bool:
    if not isinstance(identity, dict):
        return False
    dependencies = identity.get("dependency_versions")
    return bool(
        set(identity)
        == {
            "executable",
            "sha256",
            "version",
            "dependency_root",
            "dependency_versions",
        }
        and type(identity.get("executable")) is str
        and Path(identity["executable"]).is_absolute()
        and _is_canonical_digest(identity.get("sha256"))
        and type(identity.get("version")) is str
        and bool(identity.get("version"))
        and type(identity.get("dependency_root")) is str
        and Path(identity["dependency_root"]).is_absolute()
        and isinstance(dependencies, dict)
        and set(dependencies) == set(DEPENDENCY_NAMES)
        and all(
            type(dependencies[name]) is str and dependencies[name]
            for name in DEPENDENCY_NAMES
        )
    )


def _browser_identity_is_complete(identity: object) -> bool:
    return bool(
        isinstance(identity, dict)
        and set(identity) == {"executable", "sha256"}
        and type(identity.get("executable")) is str
        and Path(identity["executable"]).is_absolute()
        and _is_canonical_digest(identity.get("sha256"))
    )


def _structured_lane_evidence_is_exact(
    lane: dict[str, Any],
    *,
    test_file: str,
    cases: list[str],
    real_browser: bool,
) -> bool:
    expected_count = len(cases)
    zero_fields = (
        "failed_count",
        "error_count",
        "skipped_count",
        "xfail_count",
        "xpass_count",
        "terminal_xfail_count",
        "terminal_xpass_count",
        "junit_declared_failure_count",
        "junit_declared_error_count",
        "junit_declared_skipped_count",
    )
    return bool(
        lane.get("selection_mode") == "exact_node_ids"
        and lane.get("node_ids") == _expected_node_ids(test_file, cases)
        and lane.get("report_format") == "junit_xml_embedded"
        and lane.get("runner_root_kind") == RUNNER_ROOT_KIND
        and lane.get("snapshot_read_only") is True
        and lane.get("argv_template") == _normalized_argv_template(test_file, cases)
        and lane.get("environment_policy") == _environment_policy(real_browser)
        and type(lane.get("executed_count")) is int
        and lane.get("executed_count") == expected_count
        and type(lane.get("passed_count")) is int
        and lane.get("passed_count") == expected_count
        and type(lane.get("terminal_passed_count")) is int
        and lane.get("terminal_passed_count") == expected_count
        and type(lane.get("junit_declared_tests_count")) is int
        and lane.get("junit_declared_tests_count") == expected_count
        and all(
            type(lane.get(field)) is int and lane.get(field) == 0
            for field in zero_fields
        )
        and lane.get("junit_totals_consistent") is True
        and lane.get("executed_cases") == cases
        and lane.get("passed_cases") == cases
        and _python_identity_is_complete(lane.get("python_identity"))
        and (
            _browser_identity_is_complete(lane.get("browser_identity"))
            if real_browser
            else lane.get("browser_identity") is None
        )
    )


def _lane_is_exact_pass(
    lane: object,
    *,
    test_file: str,
    cases: list[str],
    real_browser: bool,
    run_id: str,
    source_revision: str,
    source_tree: str,
) -> bool:
    if not isinstance(lane, dict):
        return False
    return bool(
        lane.get("status") == "pass"
        and type(lane.get("exit_code")) is int
        and lane.get("exit_code") == 0
        and lane.get("run_id") == run_id
        and lane.get("trust_model") == TRUST_MODEL
        and lane.get("source_revision") == source_revision
        and lane.get("source_tree") == source_tree
        and lane.get("test_file") == test_file
        and lane.get("cases") == cases
        and _structured_lane_evidence_is_exact(
            lane,
            test_file=test_file,
            cases=cases,
            real_browser=real_browser,
        )
        and type(lane.get("limitations")) is list
        and not lane["limitations"]
        and type(lane.get("blocking_reasons")) is list
        and not lane["blocking_reasons"]
    )


def _run_pytest_cases(
    root: Path,
    *,
    python_bin: str,
    python_identity: dict[str, Any],
    dependency_root: Path,
    private_root: Path,
    operator_env: Mapping[str, str],
    test_file: str,
    cases: list[str],
    real_browser: bool,
    run_id: str,
    source_revision: str,
    source_tree: str,
    browser_identity_resolver: Callable[
        [str, dict[str, str]], dict[str, str] | None
    ] = _browser_identity,
) -> dict[str, Any]:
    if not _snapshot_is_read_only(root):
        raise RuntimeError("runner root is not an immutable snapshot")
    lane_name = "browser" if real_browser else "source"
    lane_private = private_root / lane_name
    lane_private.mkdir(mode=0o700, parents=True, exist_ok=False)
    environment, environment_policy = _child_environment(
        root,
        lane_private,
        dependency_root=dependency_root,
        real_browser=real_browser,
        operator_env=operator_env,
    )
    basetemp = lane_private / "pytest"
    junit_path = lane_private / "junit.xml"
    node_ids = _expected_node_ids(test_file, cases)
    command = [
        python_bin,
        "-m",
        "pytest",
        "-q",
        "-rXx",
        "--color=no",
        "-o",
        "addopts=",
        "-o",
        "xfail_strict=true",
        "-p",
        "no:cacheprovider",
        "--confcutdir",
        root.as_posix(),
        "--basetemp",
        basetemp.as_posix(),
        f"--junitxml={junit_path}",
        *node_ids,
    ]
    resolved_browser_identity = (
        browser_identity_resolver(python_bin, environment) if real_browser else None
    )
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_seconds = round(time.monotonic() - started, 3)
    combined_output = "\n".join(
        part
        for part in (str(result.stdout or "").strip(), str(result.stderr or "").strip())
        if part
    )
    xml_text, xml_sha256, junit_limitations = _read_bounded_junit(junit_path)
    junit_evidence = _parse_junit_xml(xml_text)
    terminal_summary = _terminal_summary(combined_output)
    terminal_evidence = _parse_terminal_summary(
        terminal_summary,
        full_output=combined_output,
    )
    if terminal_evidence["terminal_xpass_count"] > 0:
        junit_evidence["xpass_count"] = max(
            junit_evidence["xpass_count"],
            terminal_evidence["terminal_xpass_count"],
        )
    limitations = [*_extract_limitations(combined_output), *junit_limitations]
    lane: dict[str, Any] = {
        "status": "blocked",
        "run_id": run_id,
        "trust_model": TRUST_MODEL,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "test_file": test_file,
        "cases": list(cases),
        "selection_mode": "exact_node_ids",
        "node_ids": node_ids,
        "runner_root_kind": RUNNER_ROOT_KIND,
        "snapshot_read_only": True,
        "environment_policy": environment_policy,
        "argv_template": _normalized_argv_template(test_file, cases),
        "python_identity": python_identity,
        "browser_identity": resolved_browser_identity,
        "exit_code": result.returncode,
        "duration_seconds": duration_seconds,
        "output_excerpt": _truncate_output(combined_output),
        "terminal_summary": terminal_summary,
        "report_format": "junit_xml_embedded",
        "junit_xml": xml_text,
        "junit_xml_sha256": xml_sha256,
        "limitations": limitations,
        "blocking_reasons": [],
        **junit_evidence,
        **terminal_evidence,
    }
    evidence_exact = _structured_lane_evidence_is_exact(
        lane,
        test_file=test_file,
        cases=cases,
        real_browser=real_browser,
    )
    if type(result.returncode) is not int or result.returncode != 0:
        lane["blocking_reasons"].append(
            "pytest process did not exit with exact integer 0"
        )
    if not evidence_exact:
        lane["blocking_reasons"].append(
            "process, terminal, and JUnit evidence did not prove the exact cases"
        )
    if limitations:
        lane["blocking_reasons"].append("pytest lane reported limitations")
    if (
        type(result.returncode) is int
        and result.returncode == 0
        and evidence_exact
        and not limitations
        and not lane["blocking_reasons"]
    ):
        lane["status"] = "pass"
    elif real_browser and (
        lane["skipped_count"] > 0
        or lane["xfail_count"] > 0
        or lane["terminal_xfail_count"] > 0
    ):
        lane["status"] = "preview_only"
    return lane


def _blocked_lane_stub(test_file: str, cases: list[str], reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "test_file": test_file,
        "cases": list(cases),
        "blocking_reasons": [reason],
        "limitations": [reason],
    }


def build_receipt(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    output_path: Path | None = None,
    run_id: str | None = None,
    runner: Callable[..., dict[str, Any]] = _run_pytest_cases,
    source_state: Callable[..., dict[str, Any]] = _git_source_state,
    snapshot_builder: Callable[..., Path] = _archive_snapshot,
    runtime_resolver: Callable[[str], tuple[dict[str, Any], Path]] = _runtime_context,
    operator_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    seed = _load_json(root / seed_path)
    invocation_id = run_id or uuid.uuid4().hex
    if re.fullmatch(r"[0-9a-f]{32}", invocation_id) is None:
        raise ValueError("run_id must be canonical lowercase 128-bit hex")
    absolute_output = (
        _validated_output_path(root, output_path) if output_path is not None else None
    )
    samples: list[dict[str, Any]] = [
        _capture_source_sample(
            source_state,
            root,
            stage=SOURCE_STATE_STAGES[0],
            excluded_output=absolute_output,
        )
    ]
    source_revision = samples[0].get("revision")
    source_tree = samples[0].get("tree")
    initial_clean = bool(
        _is_canonical_revision(source_revision)
        and _is_canonical_revision(source_tree)
        and len(source_revision) == len(source_tree)
        and samples[0].get("dirty") is False
    )
    python_identity: dict[str, Any] | None = None
    snapshot_metadata = {
        "archive_format": "git_archive_tar",
        "read_only": False,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "seal_algorithm": SNAPSHOT_SEAL_ALGORITHM,
        "read_only_enforcement": SNAPSHOT_READ_ONLY_ENFORCEMENT,
        "seal_samples": [],
        "mutation_watch": {
            "algorithm": SNAPSHOT_MUTATION_WATCH_ALGORITHM,
            "samples": [],
        },
    }
    source_lane = _blocked_lane_stub(
        SOURCE_BACKED_TEST_FILE,
        SOURCE_BACKED_CASES,
        "original source was not clean",
    )
    browser_lane = _blocked_lane_stub(
        REAL_BROWSER_TEST_FILE,
        REAL_BROWSER_CASES,
        "original source was not clean",
    )

    if initial_clean:
        python_bin = _resolve_python_bin(root)
        python_identity, dependency_root = runtime_resolver(python_bin)
        with tempfile.TemporaryDirectory(prefix="ea-browser-proof-run-") as temp_dir:
            private_root = Path(temp_dir)
            private_root.chmod(0o700)
            snapshot_root = snapshot_builder(
                root,
                private_root / "snapshot",
                revision=source_revision,
            )
            if not _snapshot_is_read_only(snapshot_root):
                raise RuntimeError("committed snapshot was not read-only")
            snapshot_metadata["read_only"] = True
            seal_samples: list[dict[str, str]] = [
                {
                    "stage": SNAPSHOT_SEAL_STAGES[0],
                    "sha256": _snapshot_filesystem_seal(snapshot_root),
                }
            ]
            mutation_samples: list[dict[str, object]] = []
            mutation_watcher = _SnapshotMutationWatcher(snapshot_root)
            try:
                source_lane = runner(
                    snapshot_root,
                    python_bin=python_bin,
                    python_identity=python_identity,
                    dependency_root=dependency_root,
                    private_root=private_root,
                    operator_env=operator_env
                    if operator_env is not None
                    else os.environ,
                    test_file=SOURCE_BACKED_TEST_FILE,
                    cases=SOURCE_BACKED_CASES,
                    real_browser=False,
                    run_id=invocation_id,
                    source_revision=source_revision,
                    source_tree=source_tree,
                )
                mutation_samples.append(
                    {
                        "stage": SNAPSHOT_MUTATION_WATCH_STAGES[0],
                        **mutation_watcher.drain(),
                    }
                )
                seal_samples.append(
                    {
                        "stage": SNAPSHOT_SEAL_STAGES[1],
                        "sha256": _snapshot_filesystem_seal(snapshot_root),
                    }
                )
                samples.append(
                    _capture_source_sample(
                        source_state,
                        root,
                        stage=SOURCE_STATE_STAGES[1],
                        excluded_output=absolute_output,
                    )
                )
                browser_lane = runner(
                    snapshot_root,
                    python_bin=python_bin,
                    python_identity=python_identity,
                    dependency_root=dependency_root,
                    private_root=private_root,
                    operator_env=operator_env
                    if operator_env is not None
                    else os.environ,
                    test_file=REAL_BROWSER_TEST_FILE,
                    cases=REAL_BROWSER_CASES,
                    real_browser=True,
                    run_id=invocation_id,
                    source_revision=source_revision,
                    source_tree=source_tree,
                )
                mutation_samples.append(
                    {
                        "stage": SNAPSHOT_MUTATION_WATCH_STAGES[1],
                        **mutation_watcher.drain(),
                    }
                )
                seal_samples.append(
                    {
                        "stage": SNAPSHOT_SEAL_STAGES[2],
                        "sha256": _snapshot_filesystem_seal(snapshot_root),
                    }
                )
                snapshot_metadata["seal_samples"] = seal_samples
                snapshot_metadata["mutation_watch"]["samples"] = mutation_samples
                samples.append(
                    _capture_source_sample(
                        source_state,
                        root,
                        stage=SOURCE_STATE_STAGES[2],
                        excluded_output=absolute_output,
                    )
                )
            finally:
                mutation_watcher.close()
                _make_tree_owner_writable(snapshot_root)
    else:
        for stage in SOURCE_STATE_STAGES[1:3]:
            samples.append(
                _capture_source_sample(
                    source_state,
                    root,
                    stage=stage,
                    excluded_output=absolute_output,
                )
            )

    samples.append(
        _capture_source_sample(
            source_state,
            root,
            stage=SOURCE_STATE_STAGES[3],
            excluded_output=absolute_output,
        )
    )
    source_exact = _source_state_samples_are_exact(
        samples,
        expected_revision=source_revision
        if _is_canonical_revision(source_revision)
        else None,
        expected_tree=source_tree if _is_canonical_revision(source_tree) else None,
    )
    snapshot_exact = bool(
        snapshot_metadata.get("read_only") is True
        and _snapshot_seal_samples_are_exact(snapshot_metadata.get("seal_samples"))
        and isinstance(snapshot_metadata.get("mutation_watch"), dict)
        and _snapshot_mutation_samples_are_exact(
            snapshot_metadata["mutation_watch"].get("samples")
        )
    )
    source_pass = _lane_is_exact_pass(
        source_lane,
        test_file=SOURCE_BACKED_TEST_FILE,
        cases=SOURCE_BACKED_CASES,
        real_browser=False,
        run_id=invocation_id,
        source_revision=str(source_revision or ""),
        source_tree=str(source_tree or ""),
    )
    browser_pass = _lane_is_exact_pass(
        browser_lane,
        test_file=REAL_BROWSER_TEST_FILE,
        cases=REAL_BROWSER_CASES,
        real_browser=True,
        run_id=invocation_id,
        source_revision=str(source_revision or ""),
        source_tree=str(source_tree or ""),
    )
    blocking_reasons: list[str] = []
    limitations: list[str] = []
    if not source_pass:
        blocking_reasons.append("source-backed browser journey proof is not passing")
        limitations.extend(
            item
            for item in source_lane.get("limitations", [])
            if type(item) is str and item
        )
    if not browser_pass:
        blocking_reasons.append("real browser E2E proof is not passing")
        limitations.extend(
            item
            for item in browser_lane.get("limitations", [])
            if type(item) is str and item
        )
    if not source_exact:
        blocking_reasons.append(
            "original source revision, tree, or cleanliness changed during proof"
        )
    if not snapshot_exact:
        blocking_reasons.append("committed snapshot changed during proof execution")
    if (
        source_pass
        and browser_pass
        and source_exact
        and snapshot_exact
        and not limitations
    ):
        status = "pass"
        operator_summary = (
            "EA browser workflow proof is green for one clean committed, "
            "mode-read-only, content/stat-sealed, mutation-watched snapshot."
        )
    else:
        status = "blocked"
        operator_summary = "EA browser workflow proof is current but blocked by its local process evidence."
    return {
        "contract_name": CONTRACT_NAME,
        "product": PRODUCT,
        "surface": SURFACE,
        "version": CONTRACT_VERSION,
        "kind": KIND,
        "generated_at": _utc_now(),
        "generated_by": GENERATED_BY,
        "run_id": invocation_id,
        "trust_model": TRUST_MODEL,
        "environment_policy": {
            "name": ENVIRONMENT_POLICY_NAME,
            "version": ENVIRONMENT_POLICY_VERSION,
        },
        "source_revision": source_revision,
        "source_tree": source_tree,
        "source_worktree_dirty": any(
            sample.get("dirty") is not False for sample in samples
        ),
        "source_state_samples": samples,
        "snapshot": snapshot_metadata,
        "status": status,
        "operator_summary": operator_summary,
        "seed_source": seed_path.as_posix(),
        "release_claim_summary": str(
            (seed.get("release_claim") or {}).get("summary") or ""
        ).strip(),
        "expected_browser_signals": list(
            (seed.get("browser_workflow_proof") or {}).get("expected_browser_signals")
            or []
        ),
        "source_backed_journey_proof": source_lane,
        "real_browser_e2e_proof": browser_lane,
        "blocking_reasons": blocking_reasons,
        "current_limitations": sorted(set(limitations)),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    serialized = (
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_output_path(root: Path, output_path: Path) -> Path:
    """Permit only the canonical publication file or an external receipt path."""

    root = root.resolve(strict=True)
    lexical_output = Path(
        os.path.abspath(
            os.path.normpath(
                os.fspath(
                    output_path if output_path.is_absolute() else root / output_path
                )
            )
        )
    )
    resolved_output = lexical_output.resolve(strict=False)
    canonical_output = Path(
        os.path.abspath(os.path.normpath(os.fspath(root / DEFAULT_OUTPUT)))
    )
    lexical_inside = _path_is_within(lexical_output, root)
    resolved_inside = _path_is_within(resolved_output, root)
    if lexical_inside or resolved_inside:
        if lexical_output != canonical_output or resolved_output != canonical_output:
            raise ValueError(
                "in-repository proof output must be the canonical DEFAULT_OUTPUT; "
                "custom proof outputs must be outside the repository"
            )
        return canonical_output
    return resolved_output


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _truncate_receipt_in_place(path: Path) -> None:
    """Invalidate a prior receipt when its directory forbids unlink/replace."""

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise RuntimeError("existing proof output is not a regular file")
    if before.st_uid == os.geteuid() and not before.st_mode & stat.S_IWUSR:
        os.chmod(path, 0o600, follow_symlinks=False)
        before = path.lstat()
    flags = os.O_WRONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise RuntimeError("existing proof output changed during invalidation")
        os.ftruncate(descriptor, 0)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    after = path.lstat()
    if (
        not stat.S_ISREG(after.st_mode)
        or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
        or after.st_size != 0
    ):
        raise RuntimeError("existing proof output was not invalidated exactly")


def _invalidate_current_receipt(path: Path) -> None:
    """Remove any prior green receipt before attempting the blocked sentinel."""

    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _truncate_receipt_in_place(path)
    _fsync_directory(path.parent)


def _output_lock_path(output_path: Path, root: Path) -> Path:
    absolute_output = output_path.resolve(strict=False)
    digest = hashlib.sha256(absolute_output.as_posix().encode("utf-8")).hexdigest()
    candidates = [
        Path("/tmp/ea-browser-workflow-proof-locks"),
        Path("/var/tmp/ea-browser-workflow-proof-locks"),
        _operator_home() / ".cache" / "ea-browser-workflow-proof-locks",
    ]
    root = root.resolve(strict=True)
    for directory in candidates:
        resolved = directory.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
            resolved.chmod(0o700)
            return resolved / f"{digest}.lock"
    raise RuntimeError("could not place proof lock outside repository")


@contextmanager
def _locked_output(output_path: Path, root: Path) -> Iterator[None]:
    lock_path = _output_lock_path(output_path, root)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _sentinel_receipt(run_id: str) -> dict[str, Any]:
    return {
        "contract_name": CONTRACT_NAME,
        "version": CONTRACT_VERSION,
        "product": PRODUCT,
        "surface": SURFACE,
        "kind": KIND,
        "generated_at": _utc_now(),
        "generated_by": GENERATED_BY,
        "run_id": run_id,
        "trust_model": TRUST_MODEL,
        "status": "blocked",
        "phase": "materializing",
        "blocking_reasons": ["current browser proof invocation is materializing"],
    }


def _error_receipt(run_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "contract_name": CONTRACT_NAME,
        "version": CONTRACT_VERSION,
        "product": PRODUCT,
        "surface": SURFACE,
        "kind": KIND,
        "generated_at": _utc_now(),
        "generated_by": GENERATED_BY,
        "run_id": run_id,
        "trust_model": TRUST_MODEL,
        "status": "blocked",
        "phase": "error",
        "error_type": type(exc).__name__,
        "blocking_reasons": ["current browser proof invocation failed closed"],
    }


def materialize_and_publish(
    root: Path,
    *,
    seed_path: Path = DEFAULT_SEED,
    output_path: Path = DEFAULT_OUTPUT,
    builder: Callable[..., dict[str, Any]] = build_receipt,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    absolute_output = _validated_output_path(root, output_path)
    invocation_id = uuid.uuid4().hex
    with _locked_output(absolute_output, root):
        _invalidate_current_receipt(absolute_output)
        _atomic_write_json(absolute_output, _sentinel_receipt(invocation_id))
        try:
            receipt = builder(
                root,
                seed_path=seed_path,
                output_path=absolute_output,
                run_id=invocation_id,
            )
        except Exception as exc:
            receipt = _error_receipt(invocation_id, exc)
        _atomic_write_json(absolute_output, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the EA browser workflow proof receipt."
    )
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="EA repository root."
    )
    parser.add_argument(
        "--seed", type=Path, default=DEFAULT_SEED, help="EA flagship release seed."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to write the generated receipt.",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="Print the receipt JSON to stdout."
    )
    args = parser.parse_args()
    receipt = materialize_and_publish(
        args.root,
        seed_path=args.seed,
        output_path=args.output,
    )
    if args.stdout:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        output = args.output if args.output.is_absolute() else args.root / args.output
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": output.resolve(strict=False).as_posix(),
                    "receipt_status": receipt.get("status"),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
