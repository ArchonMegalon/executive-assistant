#!/usr/bin/env python3
"""Governed, fail-closed capacity recovery for a Manfred candidate build.

The controller has six explicit phases:

* ``plan`` is read-only and prints the exact identities that are eligible.
* ``prepare-root-attest`` emits a hash-bound, read-only root preflight request.
* ``seal-intent`` accepts only a matching successful root attestation.
* ``apply-user`` consumes that immutable intent, performs only user-scoped
  mutations, and emits a hash-bound root handoff.
* ``apply-root`` consumes that handoff and removes only the attested finite
  root-candidate prefix.  It never removes candidate roots, runtime state,
  contributions, receipts, or Docker resources.
* ``finalize`` links the receipts and verifies the disk target.

No phase broadens its target set when capacity remains insufficient.  In
particular, this module has no Docker system/image/volume prune primitive.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Iterator, Sequence


if __name__ == "__main__" and os.geteuid() == 0:
    print(
        '{"reason":"manfred_capacity_use_standalone_root_applier","status":"fail"}',
        file=sys.stderr,
    )
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parents[1]
ROOT_APPLIER_PATH = ROOT / "scripts/apply_manfred_memorial_capacity_handoff.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_manfred_memorial_image import (  # noqa: E402
    BUILDX_BUILDER_DRIVER,
    BUILDX_BUILDER_ENDPOINT,
    BUILDX_BUILDER_NAME,
    BUILDX_BUILDER_NODE_NAME,
    MINIMUM_ROOT_FREE_BYTES,
    _exclusive_build_lock,
)
from scripts.manfred_candidate_fleet_lock import (  # noqa: E402
    hold_candidate_fleet_lock,
)
from scripts.manfred_candidate_registry import (  # noqa: E402
    REGISTRY_SCHEMA,
    RUNTIME_SCHEMA_V5,
    _read_private_json as _read_registry_json,
    _receipt_entry,
    _registry_payload,
    _validated_registry,
    compact_candidate_registry,
    default_registry_path,
)
from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    RECEIPT_SCHEMA as PROJECTION_SCHEMA,
    _tree_digest as _projection_tree_digest,
    _validate_project_name,
)


PLAN_SCHEMA = "ea.manfred_memorial_build_capacity.plan.v3"
PLAN_PROBE_SCHEMA = "ea.manfred_memorial_build_capacity.plan_probe.v3"
ROOT_ATTEST_REQUEST_SCHEMA = (
    "ea.manfred_memorial_build_capacity.root_attest_request.v3"
)
ROOT_ATTESTATION_SCHEMA = "ea.manfred_memorial_build_capacity.root_attestation.v3"
INTENT_SCHEMA = "ea.manfred_memorial_build_capacity.intent.v3"
USER_RECEIPT_SCHEMA = "ea.manfred_memorial_build_capacity.user_receipt.v3"
ROOT_HANDOFF_SCHEMA = "ea.manfred_memorial_build_capacity.root_handoff.v3"
ROOT_RECEIPT_SCHEMA = "ea.manfred_memorial_build_capacity.root_receipt.v3"
COMPLETION_SCHEMA = "ea.manfred_memorial_build_capacity.completion.v3"
VSCODE_JOURNAL_SCHEMA = "ea.manfred_memorial_build_capacity.vscode_journal.v3"
VSCODE_COMPLETE_SCHEMA = "ea.manfred_memorial_build_capacity.vscode_complete.v3"

TARGET_HEADROOM_BYTES = 256 * 1024**2
TARGET_ROOT_FREE_BYTES = MINIMUM_ROOT_FREE_BYTES + TARGET_HEADROOM_BYTES
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_TREE_FILES = 200_000
MAX_TREE_ENTRIES = MAX_TREE_FILES + 1
MAX_TREE_BYTES = 4 * 1024**3
MAX_PINNED_TOOL_BYTES = 256 * 1024**2
MAX_PROJECTIONS = 64
EXPECTED_PROJECTION_COUNT = 26
MAX_PROCESS_REFERENCES = 64
MAX_PROCESS_COUNT = 32_768
MAX_PROCESS_CMDLINE_BYTES = 4 * 1024 * 1024
MAX_PROCESS_MAPS_BYTES = 32 * 1024 * 1024
MAX_MOUNTINFO_BYTES = 4 * 1024 * 1024
MAX_MOUNTINFO_ENTRIES = 32_768
CAPACITY_LOCK_NAME = "ea-manfred-build-capacity.lock"
DOCKER_BINARY = "/usr/bin/docker"
BUILDX_BINARY = "/usr/libexec/docker/cli-plugins/docker-buildx"
DOTNET_BINARY = "/usr/lib/dotnet/dotnet"
NODE_BINARY = "/usr/bin/node"
NPM_CLI = "/usr/lib/node_modules/npm/bin/npm-cli.js"
PYTHON_EXECUTABLE = "/usr/bin/python3.12"
GIT_BINARY = "/usr/bin/git"
SUDO_BINARY = "/usr/bin/sudo"
LOCAL_DOCKER_HOST = "unix:///var/run/docker.sock"
BUILD_CACHE_PRUNE_ARGV = (
    BUILDX_BINARY,
    "prune",
    "--builder",
    BUILDX_BUILDER_NAME,
    "--all",
    "--force",
)
CACHE_MUTATION_COMMANDS = (
    (
        "nuget_http",
        (DOTNET_BINARY, "nuget", "locals", "http-cache", "--clear"),
    ),
    (
        "nuget_global_packages",
        (DOTNET_BINARY, "nuget", "locals", "global-packages", "--clear"),
    ),
    (
        "npm_content_cache",
        (NODE_BINARY, NPM_CLI, "cache", "clean", "--force"),
    ),
    (
        "pip_cache",
        (PYTHON_EXECUTABLE, "-I", "-m", "pip", "cache", "purge"),
    ),
)
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
BUILDKIT_ID = re.compile(r"[a-z0-9]{20,80}")
VSCODE_SERVER_NAME = re.compile(r"Stable-([0-9a-f]{40})")
PROJECTION_ROOT_NAME = re.compile(r"candidate-[a-z0-9][a-z0-9-]{7,119}")
EXPECTED_CANDIDATE_PROJECT = "ea-manfred-candidate-c75e8785"
EXPECTED_CANDIDATE_REVISION = "c75e878587f8290f47f37b385cbde6f0d1c076a8"
EXPECTED_CANDIDATE_IMAGE = f"ea-runtime:manfred-{EXPECTED_CANDIDATE_REVISION}"
EXPECTED_CANDIDATE_IMAGE_ID = (
    "sha256:4987b4971b482f6c3923ac79672bfce08ce42ff57b2af1f292556d805917058c"
)
LIVE_COMPOSE_PROJECT = "ea"
LIVE_API_SERVICE = "ea-api"
DEPLOY_ROOT_RELATIVE = Path(".local/share/ea-deploy/manfred-memorial")
ROOT_RECEIPT_DIRECTORY = Path("/var/lib/ea/manfred-root-receipts")
ROOT_RECEIPT_NAME = re.compile(
    r"manfred-capacity-[0-9a-z][0-9a-z-]{0,80}\.v3\.json"
)
MAX_PROCESS_FDS = 4096
MAX_ROOT_CANDIDATES = 64
MAX_VSCODE_ROOT_ENTRIES = 65
DELETION_STATUSES = {"removed", "recovered_removed", "already_removed_verified"}
PRESERVED_STATUSES = {
    "preserved_capacity_ready",
    "preserved_not_authorized",
    "preserved_referenced",
}

# These are the complete, finite non-projection root candidates.  The byte
# values are retained only as dated operator observations; eligibility and all
# capacity arithmetic use freshly recomputed TreeEvidence.  No parent or
# sibling discovery is permitted.
ROOT_TEMP_CANDIDATE_SPECS = (
    (
        "temp:chummer6-ui-desktop-build:nuget-packages",
        Path("/tmp/chummer6-ui-desktop-build/nuget-packages"),
        672_432_128,
    ),
    (
        "temp:chummer6-ui-desktop-build:dotnet-nuget",
        Path("/tmp/chummer6-ui-desktop-build/dotnet-home/.local/share/NuGet"),
        169_037_824,
    ),
    (
        "temp:chummer-ai:nuget-http-cache",
        Path("/tmp/chummer-ai/.local/share/NuGet/http-cache"),
        504_786_944,
    ),
    (
        "temp:chummer-hub-dotnet-10.0.103",
        Path("/tmp/chummer-hub-dotnet-10.0.103"),
        654_213_120,
    ),
    (
        "temp:chummer-powershell-7.4.6",
        Path("/tmp/chummer-powershell-7.4.6"),
        184_401_920,
    ),
    (
        "temp:chummer-stage-candidate-debug",
        Path("/tmp/chummer-stage-candidate-debug"),
        260_050_944,
    ),
    (
        "temp:chummer-hub-eta-audit-pytest",
        Path("/tmp/chummer-hub-eta-audit-pytest"),
        59_281_408,
    ),
    (
        "temp:chummer-core-engine:vexp",
        Path("/tmp/chummer-core-engine/.vexp"),
        99_655_680,
    ),
    (
        "temp:chummer-core-engine:aider-tags-v4",
        Path("/tmp/chummer-core-engine/.aider.tags.cache.v4"),
        18_305_024,
    ),
    (
        "temp:chummer-hub-registry:vexp",
        Path("/tmp/chummer-hub-registry/.vexp"),
        22_073_344,
    ),
)

ROOT_INSTALLER_CODE = r'''import hashlib
import os
import stat
import sys
import tempfile


def fail(reason):
    raise SystemExit(reason)


if os.geteuid() != 0 or len(sys.argv) != 16:
    fail("manfred_capacity_installer_arguments_invalid")
try:
    operator_uid = int(sys.argv[1])
except ValueError:
    fail("manfred_capacity_installer_operator_invalid")
if operator_uid < 1:
    fail("manfred_capacity_installer_operator_invalid")
sudo_uid = os.environ.get("SUDO_UID", "")
if not sudo_uid.isascii() or not sudo_uid.isdecimal() or int(sudo_uid) != operator_uid:
    fail("manfred_capacity_installer_sudo_identity_invalid")
installer_sha256 = sys.argv[15]
try:
    command_line = open("/proc/self/cmdline", "rb", buffering=0).read(131073)
except OSError:
    fail("manfred_capacity_installer_identity_invalid")
if len(command_line) > 131072:
    fail("manfred_capacity_installer_identity_invalid")
parts = command_line.split(b"\0")
try:
    code = parts[parts.index(b"-c") + 1]
except (ValueError, IndexError):
    fail("manfred_capacity_installer_identity_invalid")
if hashlib.sha256(code).hexdigest() != installer_sha256:
    fail("manfred_capacity_installer_identity_invalid")

specifications = (
    (sys.argv[2], "applier.py", sys.argv[3], sys.argv[4], 0o500, False),
    (sys.argv[5], "controller.py", sys.argv[6], sys.argv[7], 0o400, False),
    (sys.argv[8], "handoff.json", sys.argv[9], sys.argv[10], 0o400, True),
    (sys.argv[11], "user-receipt.json", sys.argv[12], sys.argv[13], 0o400, True),
)
root_receipt = sys.argv[14]
stage = tempfile.mkdtemp(prefix="ea-manfred-capacity.", dir="/root")
os.chmod(stage, 0o700)
stage_descriptor = os.open(
    stage,
    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
)
stage_status = os.fstat(stage_descriptor)
if stage_status.st_uid != 0 or stat.S_IMODE(stage_status.st_mode) != 0o700:
    fail("manfred_capacity_installer_stage_invalid")


def stage_file(source, name, raw_size, expected_sha256, target_mode, private):
    try:
        expected_size = int(raw_size)
    except ValueError:
        fail("manfred_capacity_installer_source_invalid")
    if (
        not os.path.isabs(source)
        or os.path.realpath(source) != source
        or not 1 <= expected_size <= 4 * 1024 * 1024
        or len(expected_sha256) != 64
        or any(value not in "0123456789abcdef" for value in expected_sha256)
    ):
        fail("manfred_capacity_installer_source_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    source_descriptor = os.open(source, flags)
    target_descriptor = -1
    try:
        before = os.fstat(source_descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != operator_uid
            or before.st_nlink != 1
            or before.st_size != expected_size
            or stat.S_IMODE(before.st_mode) & 0o022
            or (private and stat.S_IMODE(before.st_mode) != 0o600)
        ):
            fail("manfred_capacity_installer_source_invalid")
        target_descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            target_mode,
            dir_fd=stage_descriptor,
        )
        os.fchown(target_descriptor, 0, 0)
        os.fchmod(target_descriptor, target_mode)
        digest = hashlib.sha256()
        copied = 0
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            copied += len(chunk)
            if copied > expected_size:
                fail("manfred_capacity_installer_source_changed")
            view = memoryview(chunk)
            while view:
                written = os.write(target_descriptor, view)
                if written <= 0:
                    fail("manfred_capacity_installer_stage_invalid")
                view = view[written:]
        after = os.fstat(source_descriptor)
        if (
            copied != expected_size
            or digest.hexdigest() != expected_sha256
            or (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            fail("manfred_capacity_installer_source_changed")
        os.fsync(target_descriptor)
    finally:
        os.close(source_descriptor)
        if target_descriptor >= 0:
            os.close(target_descriptor)
    staged = os.path.join(stage, name)
    staged_descriptor = os.open(staged, flags)
    try:
        staged_status = os.fstat(staged_descriptor)
        staged_digest = hashlib.sha256()
        staged_size = 0
        while True:
            chunk = os.read(staged_descriptor, 1024 * 1024)
            if not chunk:
                break
            staged_digest.update(chunk)
            staged_size += len(chunk)
        staged_after = os.fstat(staged_descriptor)
        if (
            not stat.S_ISREG(staged_status.st_mode)
            or staged_status.st_uid != 0
            or staged_status.st_gid != 0
            or staged_status.st_nlink != 1
            or stat.S_IMODE(staged_status.st_mode) != target_mode
            or staged_size != expected_size
            or staged_digest.hexdigest() != expected_sha256
            or (
                staged_status.st_dev,
                staged_status.st_ino,
                staged_status.st_mode,
                staged_status.st_uid,
                staged_status.st_gid,
                staged_status.st_nlink,
                staged_status.st_size,
                staged_status.st_mtime_ns,
                staged_status.st_ctime_ns,
            )
            != (
                staged_after.st_dev,
                staged_after.st_ino,
                staged_after.st_mode,
                staged_after.st_uid,
                staged_after.st_gid,
                staged_after.st_nlink,
                staged_after.st_size,
                staged_after.st_mtime_ns,
                staged_after.st_ctime_ns,
            )
        ):
            fail("manfred_capacity_installer_stage_invalid")
    finally:
        os.close(staged_descriptor)
    return staged


staged = [stage_file(*row) for row in specifications]
os.fsync(stage_descriptor)
os.close(stage_descriptor)
argv = [
    "/usr/bin/python3.12",
    "-I",
    staged[0],
    "--operator-uid",
    str(operator_uid),
    "--handoff",
    staged[2],
    "--handoff-source",
    sys.argv[8],
    "--handoff-sha256",
    sys.argv[10],
    "--user-receipt",
    staged[3],
    "--user-receipt-source",
    sys.argv[11],
    "--user-receipt-sha256",
    sys.argv[13],
    "--root-receipt",
    root_receipt,
    "--root-applier-sha256",
    sys.argv[4],
    "--controller-copy",
    staged[1],
    "--installer-sha256",
    installer_sha256,
    "--stage-path",
    stage,
]
os.execve(
    "/usr/bin/python3.12",
    argv,
    {
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    },
)
'''
ROOT_INSTALLER_SHA256 = hashlib.sha256(ROOT_INSTALLER_CODE.encode("utf-8")).hexdigest()

FORBIDDEN_MUTATION_PREFIXES = (
    (DOCKER_BINARY, "--host", LOCAL_DOCKER_HOST, "system", "prune"),
    (DOCKER_BINARY, "--host", LOCAL_DOCKER_HOST, "builder", "prune"),
    (DOCKER_BINARY, "--host", LOCAL_DOCKER_HOST, "image", "prune"),
    (DOCKER_BINARY, "--host", LOCAL_DOCKER_HOST, "volume", "prune"),
    (DOCKER_BINARY, "--host", LOCAL_DOCKER_HOST, "network", "prune"),
)
PROTECTED_PATH_LABELS = (
    "manfred_top_level_runtime",
    "manfred_top_level_releases",
    "manfred_receipts",
    "manfred_private_narration",
    "candidate_runtime",
    "candidate_receipts",
    "candidate_environment",
    "playwright_cache",
    "codexea_cache",
    "ea_releases",
    "trash",
    "vscode_active_data",
    "vscode_extensions",
)
PINNED_TOOL_PATHS = (
    SUDO_BINARY,
    DOCKER_BINARY,
    BUILDX_BINARY,
    DOTNET_BINARY,
    NODE_BINARY,
    NPM_CLI,
    PYTHON_EXECUTABLE,
    GIT_BINARY,
)
MUTATION_HELPER_PATHS = (
    ROOT / "scripts/build_manfred_memorial_image.py",
    ROOT / "scripts/manfred_candidate_fleet_lock.py",
    ROOT / "scripts/manfred_candidate_registry.py",
    ROOT / "scripts/prepare_manfred_memorial_candidate.py",
)


@dataclass(frozen=True)
class TreeEvidence:
    path: str
    exists: bool
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    file_count: int
    apparent_bytes: int
    allocated_bytes: int
    manifest_sha256: str
    nlink: int = 0
    entry_count: int = 0
    root_kind: str = "directory"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "file_count": self.file_count,
            "apparent_bytes": self.apparent_bytes,
            "allocated_bytes": self.allocated_bytes,
            "manifest_sha256": self.manifest_sha256,
            "nlink": self.nlink,
            "entry_count": self.entry_count,
            "root_kind": self.root_kind,
        }


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(payload: object) -> bytes:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if not encoded or len(encoded) > MAX_JSON_BYTES:
        raise RuntimeError("manfred_capacity_receipt_size_invalid")
    return encoded


def _operator_identity(uid: int | None = None) -> tuple[int, Path]:
    operator_uid = os.getuid() if uid is None else uid
    if type(operator_uid) is not int or operator_uid < 1:
        raise RuntimeError("manfred_capacity_operator_uid_invalid")
    try:
        home = Path(pwd.getpwuid(operator_uid).pw_dir)
    except (KeyError, OSError) as exc:
        raise RuntimeError("manfred_capacity_operator_home_invalid") from exc
    if not home.is_absolute() or home.resolve(strict=True) != home:
        raise RuntimeError("manfred_capacity_operator_home_invalid")
    status = home.stat()
    if not stat.S_ISDIR(status.st_mode) or status.st_uid != operator_uid:
        raise RuntimeError("manfred_capacity_operator_home_invalid")
    return operator_uid, home


def _safe_environment(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "DOCKER_HOST": LOCAL_DOCKER_HOST,
    }


def _resolved_command(argv: tuple[str, ...]) -> tuple[str, ...]:
    if not argv:
        raise RuntimeError("manfred_capacity_command_invalid")
    if argv[:2] == ("docker", "buildx"):
        return (BUILDX_BINARY, *argv[2:])
    if argv[0] == "docker":
        return (DOCKER_BINARY, "--host", LOCAL_DOCKER_HOST, *argv[1:])
    if argv[0] == "dotnet":
        return (DOTNET_BINARY, *argv[1:])
    if argv[0] == "npm":
        return (NODE_BINARY, NPM_CLI, *argv[1:])
    if argv[0] == "git":
        return (GIT_BINARY, *argv[1:])
    allowed = {
        DOCKER_BINARY,
        BUILDX_BINARY,
        DOTNET_BINARY,
        NODE_BINARY,
        PYTHON_EXECUTABLE,
        GIT_BINARY,
    }
    if argv[0] in allowed:
        return argv
    raise RuntimeError("manfred_capacity_command_binary_unpinned")


def _bounded_run(
    argv: Sequence[str],
    *,
    home: Path,
    mutation: bool = False,
    timeout: int = 60,
    cwd: Path | None = None,
) -> bytes:
    requested = tuple(str(value) for value in argv)
    if not requested or any(not value or "\x00" in value for value in requested):
        raise RuntimeError("manfred_capacity_command_invalid")
    command = _resolved_command(requested)
    if mutation and not _mutation_command_allowed(command):
        raise RuntimeError("manfred_capacity_mutation_command_forbidden")
    if any(command[: len(prefix)] == prefix for prefix in FORBIDDEN_MUTATION_PREFIXES):
        raise RuntimeError("manfred_capacity_global_prune_forbidden")
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=_safe_environment(home),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("manfred_capacity_command_failed") from exc
    if (
        len(completed.stdout) > MAX_COMMAND_OUTPUT_BYTES
        or len(completed.stderr) > MAX_COMMAND_OUTPUT_BYTES
    ):
        raise RuntimeError("manfred_capacity_command_output_invalid")
    return completed.stdout


def _mutation_command_allowed(argv: tuple[str, ...]) -> bool:
    if argv == BUILD_CACHE_PRUNE_ARGV:
        return True
    if argv in {command for _name, command in CACHE_MUTATION_COMMANDS}:
        return True
    if argv == (
        DOCKER_BINARY,
        "--host",
        LOCAL_DOCKER_HOST,
        "image",
        "rm",
        EXPECTED_CANDIDATE_IMAGE_ID,
    ):
        return True
    return False


def _source_sha256(path: Path | None = None) -> str:
    source = Path(path or __file__)
    try:
        status = source.stat()
        content = source.read_bytes()
    except OSError as exc:
        raise RuntimeError("manfred_capacity_producer_invalid") from exc
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) & 0o022
        or len(content) > MAX_JSON_BYTES * 2
    ):
        raise RuntimeError("manfred_capacity_producer_invalid")
    return _sha256(content)


def _controller_evidence(*, uid: int) -> dict[str, object]:
    path = Path(__file__).resolve(strict=True)
    status = path.stat()
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != uid
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) & 0o022
        or not 1 <= status.st_size <= MAX_JSON_BYTES * 2
    ):
        raise RuntimeError("manfred_capacity_producer_invalid")
    return {
        "path": str(path),
        "sha256": _source_sha256(path),
        "size_bytes": status.st_size,
        "owner_uid": status.st_uid,
        "mode": stat.S_IMODE(status.st_mode),
    }


def _root_applier_evidence(*, uid: int) -> dict[str, object]:
    try:
        resolved = ROOT_APPLIER_PATH.resolve(strict=True)
        status = resolved.stat()
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_applier_invalid") from exc
    if (
        resolved != ROOT_APPLIER_PATH
        or not stat.S_ISREG(status.st_mode)
        or status.st_uid != uid
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) & 0o022
        or not 1 <= status.st_size <= MAX_JSON_BYTES * 2
    ):
        raise RuntimeError("manfred_capacity_root_applier_invalid")
    return {
        "path": str(resolved),
        "sha256": _source_sha256(resolved),
        "size_bytes": status.st_size,
        "owner_uid": uid,
        "mode": stat.S_IMODE(status.st_mode),
        "stdlib_only": True,
        "repo_imports": False,
    }


def _root_installer_evidence() -> dict[str, object]:
    return {
        "delivery": "sudo_inline_stdlib_stager_v2",
        "sudo_path": SUDO_BINARY,
        "interpreter_path": PYTHON_EXECUTABLE,
        "code_sha256": ROOT_INSTALLER_SHA256,
        "code_size_bytes": len(ROOT_INSTALLER_CODE.encode("utf-8")),
        "stdlib_only": True,
        "root_stage_parent": "/root",
        "root_stage_mode": 0o700,
        "sudo_uid_required": True,
        "literal_argv_only": True,
        "operator_authorized_inline_bootstrap": True,
        "unreviewed_command_string_authenticated": False,
        "user_writable_root_interpreted_file": False,
    }


def _mutation_helper_evidence(*, uid: int) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for path in MUTATION_HELPER_PATHS:
        if path.resolve(strict=True) != path:
            raise RuntimeError("manfred_capacity_mutation_helper_invalid")
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != uid
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) & 0o022
                or not 1 <= before.st_size <= MAX_JSON_BYTES * 2
            ):
                raise RuntimeError("manfred_capacity_mutation_helper_invalid")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(descriptor)
            if size != before.st_size or (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise RuntimeError("manfred_capacity_mutation_helper_changed")
        finally:
            os.close(descriptor)
        evidence.append(
            {
                "path": str(path),
                "device": before.st_dev,
                "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode),
                "uid": before.st_uid,
                "gid": before.st_gid,
                "nlink": before.st_nlink,
                "size_bytes": before.st_size,
                "sha256": digest.hexdigest(),
            }
        )
    return evidence


def _pinned_toolchain_evidence() -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for raw_path in PINNED_TOOL_PATHS:
        path = Path(raw_path)
        if path.resolve(strict=True) != path:
            raise RuntimeError("manfred_capacity_tool_binary_invalid")
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != 0
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) & 0o022
                or not 1 <= before.st_size <= MAX_PINNED_TOOL_BYTES
            ):
                raise RuntimeError("manfred_capacity_tool_binary_invalid")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(descriptor)
            if size != before.st_size or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise RuntimeError("manfred_capacity_tool_binary_changed")
        finally:
            os.close(descriptor)
        evidence.append(
            {
                "path": str(path),
                "device": before.st_dev,
                "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode),
                "uid": before.st_uid,
                "gid": before.st_gid,
                "size_bytes": before.st_size,
                "sha256": digest.hexdigest(),
            }
        )
    return evidence


def _trusted_parent(path: Path, *, expected_owner: int) -> tuple[Path, Path]:
    absolute = path.expanduser()
    absolute = absolute if absolute.is_absolute() else Path.cwd() / absolute
    try:
        parent = absolute.parent.resolve(strict=True)
        status = parent.stat()
    except OSError as exc:
        raise RuntimeError("manfred_capacity_output_parent_invalid") from exc
    destination = parent / absolute.name
    if (
        destination != absolute.absolute()
        or not stat.S_ISDIR(status.st_mode)
        or status.st_uid != expected_owner
        or stat.S_IMODE(status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_capacity_output_parent_invalid")
    return destination, parent


def _validate_root_receipt_destination(path: Path, *, operator_uid: int) -> Path:
    try:
        operator_gid = pwd.getpwuid(operator_uid).pw_gid
        absolute = path if path.is_absolute() else Path.cwd() / path
        parent = absolute.parent.resolve(strict=True)
        status = parent.stat()
    except (KeyError, OSError) as exc:
        raise RuntimeError("manfred_capacity_root_receipt_parent_invalid") from exc
    destination = parent / absolute.name
    if (
        destination != absolute.absolute()
        or parent != ROOT_RECEIPT_DIRECTORY
        or ROOT_RECEIPT_NAME.fullmatch(destination.name) is None
        or os.path.lexists(destination)
        or not stat.S_ISDIR(status.st_mode)
        or status.st_uid != 0
        or status.st_gid != operator_gid
        or stat.S_IMODE(status.st_mode) & 0o022
        or stat.S_IMODE(status.st_mode) & 0o050 != 0o050
    ):
        raise RuntimeError("manfred_capacity_root_receipt_parent_invalid")
    return destination


def _atomic_new_json(path: Path, payload: dict[str, object], *, owner: int) -> str:
    encoded = _json_bytes(payload)
    destination, parent = _trusted_parent(path, expected_owner=owner)
    if os.path.lexists(destination):
        raise RuntimeError("manfred_capacity_output_exists")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=parent
    )
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != owner
            or status.st_nlink != 1
            or stat.S_IMODE(status.st_mode) != 0o600
        ):
            raise RuntimeError("manfred_capacity_output_invalid")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination, follow_symlinks=False)
        published = True
        Path(temporary).unlink()
        temporary = ""
        directory_descriptor = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError as exc:
        raise RuntimeError("manfred_capacity_output_exists") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()
        if published and not destination.exists():
            raise RuntimeError("manfred_capacity_output_write_failed")
    loaded, digest = _read_private_json(destination, expected_owner=owner)
    if loaded != payload:
        raise RuntimeError("manfred_capacity_output_write_failed")
    return digest


def _read_private_json(
    path: Path,
    *,
    expected_owner: int,
) -> tuple[dict[str, object], str]:
    absolute = path.expanduser()
    absolute = absolute if absolute.is_absolute() else Path.cwd() / absolute
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_receipt_path_invalid") from exc
    if resolved != absolute.absolute() or resolved.is_symlink():
        raise RuntimeError("manfred_capacity_receipt_path_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_receipt_path_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_owner
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 1 <= before.st_size <= MAX_JSON_BYTES
        ):
            raise RuntimeError("manfred_capacity_receipt_file_invalid")
        content = b""
        while len(content) <= MAX_JSON_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_JSON_BYTES + 1 - len(content)))
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        if len(content) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RuntimeError("manfred_capacity_receipt_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_receipt_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_capacity_receipt_json_invalid")
    return dict(payload), _sha256(content)


def _read_root_receipt(path: Path, *, operator_uid: int) -> tuple[dict[str, object], str]:
    try:
        operator_gid = pwd.getpwuid(operator_uid).pw_gid
    except (KeyError, OSError) as exc:
        raise RuntimeError("manfred_capacity_root_receipt_identity_invalid") from exc
    absolute = path.expanduser()
    absolute = absolute if absolute.is_absolute() else Path.cwd() / absolute
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_receipt_path_invalid") from exc
    if resolved != absolute.absolute() or resolved.is_symlink():
        raise RuntimeError("manfred_capacity_root_receipt_path_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_receipt_path_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_gid != operator_gid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o640
            or not 1 <= before.st_size <= MAX_JSON_BYTES
        ):
            raise RuntimeError("manfred_capacity_root_receipt_identity_invalid")
        content = b""
        while len(content) <= MAX_JSON_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_JSON_BYTES + 1 - len(content)))
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        if len(content) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RuntimeError("manfred_capacity_root_receipt_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_receipt_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_capacity_root_receipt_json_invalid")
    return dict(payload), _sha256(content)


@contextlib.contextmanager
def _capacity_lock(uid: int, *, create: bool = True) -> Iterator[dict[str, object]]:
    directory = Path("/run/user") / str(uid)
    directory_descriptor = -1
    lock_descriptor = -1
    locked = False
    try:
        directory_descriptor = os.open(
            directory,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        directory_status = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(directory_status.st_mode)
            or directory_status.st_uid != uid
            or stat.S_IMODE(directory_status.st_mode) & 0o022
        ):
            raise RuntimeError("manfred_capacity_lock_directory_invalid")
        flags = os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT
        lock_descriptor = os.open(
            CAPACITY_LOCK_NAME, flags, 0o600, dir_fd=directory_descriptor
        )
        lock_status = os.fstat(lock_descriptor)
        if (
            not stat.S_ISREG(lock_status.st_mode)
            or lock_status.st_uid != uid
            or lock_status.st_nlink != 1
            or stat.S_IMODE(lock_status.st_mode) != 0o600
        ):
            raise RuntimeError("manfred_capacity_lock_invalid")
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeError("manfred_capacity_lock_held") from exc
            raise RuntimeError("manfred_capacity_lock_unavailable") from exc
        yield {
            "scope": "manfred_build_capacity",
            "lock_file": CAPACITY_LOCK_NAME,
            "exclusive": True,
            "nonblocking": True,
            "owner_uid": uid,
        }
    except OSError as exc:
        raise RuntimeError("manfred_capacity_lock_unavailable") from exc
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        if lock_descriptor >= 0:
            os.close(lock_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def _root_free_bytes() -> int:
    try:
        value = os.statvfs("/").f_bavail * os.statvfs("/").f_frsize
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_stat_invalid") from exc
    if type(value) is not int or value < 0:
        raise RuntimeError("manfred_capacity_root_stat_invalid")
    return value


@dataclass(frozen=True)
class MountInfoEntry:
    mount_id: int
    parent_id: int
    device_major: int
    device_minor: int
    mount_point: Path
    filesystem_type: str


def _decode_mountinfo_path(raw: bytes) -> Path:
    decoded = bytearray()
    index = 0
    allowed_escapes = {b"011": 0o11, b"012": 0o12, b"040": 0o40, b"134": 0o134}
    while index < len(raw):
        if raw[index] != 0x5C:
            decoded.append(raw[index])
            index += 1
            continue
        escaped = raw[index + 1 : index + 4]
        value = allowed_escapes.get(escaped)
        if value is None:
            raise RuntimeError("manfred_capacity_mount_inventory_invalid")
        decoded.append(value)
        index += 4
    path = Path(os.fsdecode(bytes(decoded)))
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeError("manfred_capacity_mount_inventory_invalid")
    return path


def _mountinfo_entries() -> tuple[MountInfoEntry, ...]:
    try:
        content = _bounded_process_read(
            Path("/proc/self/mountinfo"), maximum=MAX_MOUNTINFO_BYTES
        )
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("manfred_capacity_mount_inventory_invalid") from exc
    lines = content.splitlines()
    if not lines or len(lines) > MAX_MOUNTINFO_ENTRIES:
        raise RuntimeError("manfred_capacity_mount_inventory_invalid")
    entries: list[MountInfoEntry] = []
    mount_ids: set[int] = set()
    for line in lines:
        if not line or b"\0" in line or line.count(b" - ") != 1:
            raise RuntimeError("manfred_capacity_mount_inventory_invalid")
        left, right = line.split(b" - ", 1)
        left_fields = left.split(b" ")
        right_fields = right.split(b" ")
        if len(left_fields) < 6 or len(right_fields) < 3:
            raise RuntimeError("manfred_capacity_mount_inventory_invalid")
        try:
            mount_id = int(left_fields[0])
            parent_id = int(left_fields[1])
            major_raw, separator, minor_raw = left_fields[2].partition(b":")
            if separator != b":" or not major_raw or not minor_raw:
                raise ValueError
            device_major = int(major_raw)
            device_minor = int(minor_raw)
            filesystem_type = right_fields[0].decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("manfred_capacity_mount_inventory_invalid") from exc
        if (
            mount_id < 1
            or parent_id < 0
            or device_major < 0
            or device_minor < 0
            or mount_id in mount_ids
            or not filesystem_type
        ):
            raise RuntimeError("manfred_capacity_mount_inventory_invalid")
        mount_ids.add(mount_id)
        entries.append(
            MountInfoEntry(
                mount_id=mount_id,
                parent_id=parent_id,
                device_major=device_major,
                device_minor=device_minor,
                mount_point=_decode_mountinfo_path(left_fields[4]),
                filesystem_type=filesystem_type,
            )
        )
    if not any(entry.mount_point == Path("/") for entry in entries):
        raise RuntimeError("manfred_capacity_mount_inventory_invalid")
    return tuple(entries)


def _assert_mount_confinement_against(
    path: Path,
    *,
    entries: tuple[MountInfoEntry, ...],
    expected_device: int | None = None,
    allow_missing: bool = False,
) -> int:
    if ".." in path.parts:
        raise RuntimeError("manfred_capacity_path_symlink_invalid")
    absolute = path.absolute()
    exists = os.path.lexists(absolute)
    try:
        resolved = absolute.resolve(strict=exists)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("manfred_capacity_path_symlink_invalid") from exc
    if resolved != absolute:
        raise RuntimeError("manfred_capacity_path_symlink_invalid")
    current = Path(absolute.anchor)
    missing_component_seen = False
    for component in absolute.parts[1:]:
        current /= component
        if not os.path.lexists(current):
            missing_component_seen = True
            if not allow_missing:
                raise RuntimeError("manfred_capacity_mount_boundary_invalid")
            continue
        if missing_component_seen:
            raise RuntimeError("manfred_capacity_path_symlink_invalid")
        try:
            component_status = os.lstat(current)
        except OSError as exc:
            raise RuntimeError("manfred_capacity_path_symlink_invalid") from exc
        if stat.S_ISLNK(component_status.st_mode):
            raise RuntimeError("manfred_capacity_path_symlink_invalid")
    probe = absolute
    if not os.path.lexists(probe):
        if not allow_missing:
            raise RuntimeError("manfred_capacity_mount_boundary_invalid")
        while not os.path.lexists(probe):
            parent = probe.parent
            if parent == probe:
                raise RuntimeError("manfred_capacity_mount_boundary_invalid")
            probe = parent
    try:
        status = os.lstat(probe)
        root_status = os.lstat("/")
    except OSError as exc:
        raise RuntimeError("manfred_capacity_mount_boundary_invalid") from exc
    if (
        status.st_dev != root_status.st_dev
        or (expected_device is not None and status.st_dev != expected_device)
    ):
        raise RuntimeError("manfred_capacity_tree_device_changed")
    root_devices = {
        (entry.device_major, entry.device_minor)
        for entry in entries
        if entry.mount_point == Path("/")
    }
    observed_root_device = (os.major(root_status.st_dev), os.minor(root_status.st_dev))
    if observed_root_device not in root_devices:
        raise RuntimeError("manfred_capacity_mount_inventory_invalid")
    for entry in entries:
        mount_point = entry.mount_point
        if mount_point == Path("/"):
            continue
        if (
            mount_point == absolute
            or mount_point in absolute.parents
            or absolute in mount_point.parents
        ):
            raise RuntimeError("manfred_capacity_mount_boundary_invalid")
    return status.st_dev


def _assert_mount_confinement(
    path: Path,
    *,
    expected_device: int | None = None,
    allow_missing: bool = False,
) -> int:
    return _assert_mount_confinement_against(
        path,
        entries=_mountinfo_entries(),
        expected_device=expected_device,
        allow_missing=allow_missing,
    )


def _assert_vscode_rename_confinement(
    source: Path,
    destination: Path,
    *,
    expected_device: int,
    journal_path: Path,
    complete_path: Path,
) -> None:
    entries = _mountinfo_entries()
    _assert_mount_confinement_against(
        source,
        entries=entries,
        expected_device=expected_device,
    )
    _assert_mount_confinement_against(
        destination,
        entries=entries,
        expected_device=expected_device,
        allow_missing=True,
    )
    for auxiliary_path in (journal_path, complete_path):
        _assert_mount_confinement_against(
            auxiliary_path,
            entries=entries,
            expected_device=expected_device,
            allow_missing=True,
        )


def _bounded_scandir(
    path: Path | str,
    *,
    maximum: int,
    error: str,
) -> list[os.DirEntry[str]]:
    """Enumerate at most ``maximum`` entries before sorting in memory."""

    if type(maximum) is not int or maximum < 0:
        raise RuntimeError(error)
    entries: list[os.DirEntry[str]] = []
    iterator: object | None = None
    try:
        iterator = os.scandir(path)
        for entry in iterator:
            if len(entries) >= maximum:
                raise RuntimeError(error)
            entries.append(entry)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(error) from exc
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
    entries.sort(key=lambda entry: entry.name)
    return entries


def _tree_evidence(
    path: Path,
    *,
    allowed_owners: set[int],
    hash_content: bool,
    require_read_only: bool = False,
    missing_ok: bool = False,
) -> TreeEvidence:
    absolute = path.absolute()
    if not os.path.lexists(absolute):
        if not missing_ok:
            raise RuntimeError("manfred_capacity_tree_missing")
        _assert_mount_confinement(absolute, allow_missing=True)
        return TreeEvidence(
            str(absolute),
            False,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            _sha256(b"absent\n"),
            nlink=0,
            entry_count=0,
        )
    confined_device = _assert_mount_confinement(absolute)
    root_status = os.lstat(absolute)
    if (
        not stat.S_ISDIR(root_status.st_mode)
        or root_status.st_dev != confined_device
        or root_status.st_uid not in allowed_owners
        or (require_read_only and stat.S_IMODE(root_status.st_mode) & 0o222)
    ):
        raise RuntimeError("manfred_capacity_tree_identity_invalid")
    rows: list[bytes] = []
    file_count = 0
    entry_count = 1
    apparent = 0
    allocated = 0
    stack = [(absolute, Path("."))]
    while stack:
        current, relative = stack.pop()
        current_status = os.lstat(current)
        if current_status.st_dev != root_status.st_dev:
            raise RuntimeError("manfred_capacity_tree_device_changed")
        if (
            not stat.S_ISDIR(current_status.st_mode)
            or current_status.st_uid not in allowed_owners
            or (require_read_only and stat.S_IMODE(current_status.st_mode) & 0o222)
        ):
            raise RuntimeError("manfred_capacity_tree_identity_invalid")
        allocated += current_status.st_blocks * 512
        rows.append(
            (
                f"d\0{relative.as_posix()}\0{stat.S_IMODE(current_status.st_mode):o}"
                f"\0{current_status.st_uid}\0{current_status.st_gid}"
                f"\0{current_status.st_nlink}\n"
            ).encode("utf-8")
        )
        entries = _bounded_scandir(
            current,
            maximum=MAX_TREE_ENTRIES - entry_count,
            error="manfred_capacity_tree_too_large",
        )
        for entry in reversed(entries):
            child = current / entry.name
            child_relative = relative / entry.name
            status = os.lstat(child)
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise RuntimeError("manfred_capacity_tree_too_large")
            if stat.S_ISDIR(status.st_mode):
                if status.st_dev != root_status.st_dev:
                    raise RuntimeError("manfred_capacity_tree_device_changed")
                stack.append((child, child_relative))
                continue
            if status.st_dev != root_status.st_dev:
                raise RuntimeError("manfred_capacity_tree_device_changed")
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_uid not in allowed_owners
                or status.st_nlink != 1
                or (require_read_only and stat.S_IMODE(status.st_mode) & 0o222)
            ):
                raise RuntimeError("manfred_capacity_tree_identity_invalid")
            file_count += 1
            if (
                status.st_size < 0
                or status.st_size > MAX_TREE_BYTES - apparent
            ):
                raise RuntimeError("manfred_capacity_tree_too_large")
            apparent += status.st_size
            allocated += status.st_blocks * 512
            if file_count > MAX_TREE_FILES:
                raise RuntimeError("manfred_capacity_tree_too_large")
            digest = "metadata-only"
            if hash_content:
                content_digest = hashlib.sha256()
                flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(child, flags)
                try:
                    opened = os.fstat(descriptor)
                    if (
                        opened.st_dev != status.st_dev
                        or opened.st_ino != status.st_ino
                        or opened.st_size != status.st_size
                        or opened.st_mtime_ns != status.st_mtime_ns
                    ):
                        raise RuntimeError("manfred_capacity_tree_changed")
                    hashed_size = 0
                    while True:
                        chunk = os.read(descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        content_digest.update(chunk)
                        hashed_size += len(chunk)
                        if hashed_size > status.st_size:
                            raise RuntimeError("manfred_capacity_tree_changed")
                    after = os.fstat(descriptor)
                    if (
                        opened.st_size,
                        opened.st_mtime_ns,
                        opened.st_ino,
                    ) != (after.st_size, after.st_mtime_ns, after.st_ino) or (
                        hashed_size != opened.st_size
                    ):
                        raise RuntimeError("manfred_capacity_tree_changed")
                finally:
                    os.close(descriptor)
                digest = content_digest.hexdigest()
            rows.append(
                (
                    f"f\0{child_relative.as_posix()}\0{stat.S_IMODE(status.st_mode):o}"
                    f"\0{status.st_uid}\0{status.st_gid}\0{status.st_nlink}"
                    f"\0{status.st_size}\0{digest}\n"
                ).encode("utf-8")
            )
    manifest = hashlib.sha256()
    for row in sorted(rows):
        manifest.update(row)
    _assert_mount_confinement(absolute, expected_device=root_status.st_dev)
    return TreeEvidence(
        str(absolute),
        True,
        root_status.st_dev,
        root_status.st_ino,
        stat.S_IMODE(root_status.st_mode),
        root_status.st_uid,
        root_status.st_gid,
        file_count,
        apparent,
        allocated,
        manifest.hexdigest(),
        nlink=root_status.st_nlink,
        entry_count=entry_count,
    )


def _parse_size_floor(value: object) -> int:
    text = str(value or "").strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kmgtpe]?i?b)", text, re.I)
    if match is None:
        raise RuntimeError("manfred_capacity_size_invalid")
    multipliers = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "pb": 1000**5,
        "eb": 1000**6,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "pib": 1024**5,
        "eib": 1024**6,
    }
    try:
        number = Decimal(match.group(1)) * multipliers[match.group(2).lower()]
        result = int(number.to_integral_value(rounding=ROUND_FLOOR))
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise RuntimeError("manfred_capacity_size_invalid") from exc
    if result < 0:
        raise RuntimeError("manfred_capacity_size_invalid")
    return result


def _json_output(raw: bytes, *, error: str) -> object:
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(error) from exc


def _builder_inspection(home: Path) -> dict[str, object]:
    listing = _bounded_run(
        [
            "docker",
            "buildx",
            "ls",
            "--no-trunc",
            "--format",
            "{{.Name}}\t{{.DriverEndpoint}}",
        ],
        home=home,
    )
    try:
        lines = listing.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_capacity_builder_listing_invalid") from exc
    matches: list[str] = []
    for line in lines:
        if not line:
            continue
        name, separator, driver = line.partition("\t")
        if separator != "\t" or not name or not driver or "\t" in driver:
            raise RuntimeError("manfred_capacity_builder_listing_invalid")
        if name == BUILDX_BUILDER_NAME:
            matches.append(driver)
    if matches != [BUILDX_BUILDER_DRIVER]:
        raise RuntimeError("manfred_capacity_builder_identity_invalid")

    inspection = _bounded_run(
        ["docker", "buildx", "inspect", BUILDX_BUILDER_NAME], home=home
    )
    try:
        rendered = inspection.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_capacity_builder_inspection_invalid") from exc
    builder_fields: dict[str, str] = {}
    nodes: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_nodes = False
    for raw_line in rendered.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "Nodes:":
            if in_nodes:
                raise RuntimeError("manfred_capacity_builder_inspection_invalid")
            in_nodes = True
            continue
        key, separator, value = stripped.partition(":")
        if separator != ":":
            continue
        key = key.strip()
        value = value.strip()
        if not in_nodes:
            if key in {"Name", "Driver"}:
                if key in builder_fields or not value:
                    raise RuntimeError("manfred_capacity_builder_inspection_invalid")
                builder_fields[key] = value
        elif key == "Name":
            current = {"Name": value}
            nodes.append(current)
        elif key == "Endpoint":
            if current is None or "Endpoint" in current:
                raise RuntimeError("manfred_capacity_builder_inspection_invalid")
            current["Endpoint"] = value
    if builder_fields != {
        "Name": BUILDX_BUILDER_NAME,
        "Driver": BUILDX_BUILDER_DRIVER,
    } or nodes != [
        {"Name": BUILDX_BUILDER_NODE_NAME, "Endpoint": BUILDX_BUILDER_ENDPOINT}
    ]:
        raise RuntimeError("manfred_capacity_builder_identity_invalid")

    container_name = f"buildx_buildkit_{BUILDX_BUILDER_NODE_NAME}"
    volume_name = f"{container_name}_state"
    raw_container = _bounded_run(
        ["docker", "container", "inspect", container_name], home=home
    )
    container_rows = _json_output(
        raw_container, error="manfred_capacity_builder_container_invalid"
    )
    if not isinstance(container_rows, list) or len(container_rows) != 1:
        raise RuntimeError("manfred_capacity_builder_container_invalid")
    container = container_rows[0]
    if not isinstance(container, dict):
        raise RuntimeError("manfred_capacity_builder_container_invalid")
    identifier = str(container.get("Id") or "")
    image_id = str(container.get("Image") or "")
    state = container.get("State")
    mounts = container.get("Mounts")
    if (
        HEX_64.fullmatch(identifier) is None
        or IMAGE_ID.fullmatch(image_id) is None
        or container.get("Name") != f"/{container_name}"
        or not isinstance(state, dict)
        or state.get("Running") is not True
        or not isinstance(mounts, list)
        or len(mounts) != 1
    ):
        raise RuntimeError("manfred_capacity_builder_container_invalid")
    mount = mounts[0]
    if not isinstance(mount, dict) or {
        "Type": mount.get("Type"),
        "Name": mount.get("Name"),
        "Destination": mount.get("Destination"),
        "RW": mount.get("RW"),
    } != {
        "Type": "volume",
        "Name": volume_name,
        "Destination": "/var/lib/buildkit",
        "RW": True,
    }:
        raise RuntimeError("manfred_capacity_builder_container_invalid")
    raw_volume = _bounded_run(
        ["docker", "volume", "inspect", volume_name], home=home
    )
    volume_rows = _json_output(raw_volume, error="manfred_capacity_builder_volume_invalid")
    if not isinstance(volume_rows, list) or len(volume_rows) != 1:
        raise RuntimeError("manfred_capacity_builder_volume_invalid")
    volume = volume_rows[0]
    if (
        not isinstance(volume, dict)
        or volume.get("Name") != volume_name
        or volume.get("Driver") != "local"
        or volume.get("Scope") != "local"
        or not Path(str(volume.get("Mountpoint") or "")).is_absolute()
        or volume.get("Labels") not in (None, {})
        or volume.get("Options") not in (None, {})
    ):
        raise RuntimeError("manfred_capacity_builder_volume_invalid")

    raw_usage = _bounded_run(
        [
            "docker",
            "buildx",
            "du",
            "--builder",
            BUILDX_BUILDER_NAME,
            "--format",
            "json",
        ],
        home=home,
    )
    records: list[dict[str, object]] = []
    for line in raw_usage.splitlines():
        if not line:
            continue
        row = _json_output(line, error="manfred_capacity_builder_usage_invalid")
        if not isinstance(row, dict):
            raise RuntimeError("manfred_capacity_builder_usage_invalid")
        record_id = str(row.get("ID") or "")
        if (
            BUILDKIT_ID.fullmatch(record_id) is None
            or row.get("Reclaimable") is not True
            or type(row.get("Shared")) is not bool
        ):
            raise RuntimeError("manfred_capacity_builder_usage_not_fully_reclaimable")
        records.append(
            {
                "id": record_id,
                "size_floor_bytes": _parse_size_floor(row.get("Size")),
                "reclaimable": True,
            }
        )
    if len(records) > MAX_TREE_FILES or len({row["id"] for row in records}) != len(
        records
    ):
        raise RuntimeError("manfred_capacity_builder_usage_invalid")
    records.sort(key=lambda row: str(row["id"]))
    usage_bytes = _json_bytes(records)
    return {
        "name": BUILDX_BUILDER_NAME,
        "driver": BUILDX_BUILDER_DRIVER,
        "node": BUILDX_BUILDER_NODE_NAME,
        "endpoint": BUILDX_BUILDER_ENDPOINT,
        "container_name": container_name,
        "container_id": identifier,
        "container_image_id": image_id,
        "volume_name": volume_name,
        "record_count": len(records),
        "records_sha256": _sha256(usage_bytes),
        "reclaimable_floor_bytes": sum(
            int(row["size_floor_bytes"]) for row in records
        ),
        "all_records_reclaimable": True,
        "global_cache_prune": False,
    }


def _docker_filtered_lines(argv: list[str], *, home: Path) -> list[str]:
    raw = _bounded_run(argv, home=home)
    try:
        lines = [line.strip() for line in raw.decode("utf-8", errors="strict").splitlines()]
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_capacity_docker_output_invalid") from exc
    return [line for line in lines if line]


def _project_resources(project: str, *, home: Path) -> dict[str, list[str]]:
    try:
        normalized = _validate_project_name(project)
    except ValueError as exc:
        raise RuntimeError("manfred_capacity_candidate_project_invalid") from exc
    label = f"label=com.docker.compose.project={normalized}"
    containers = _docker_filtered_lines(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            label,
        ],
        home=home,
    )
    networks = _docker_filtered_lines(
        ["docker", "network", "ls", "--quiet", "--no-trunc", "--filter", label],
        home=home,
    )
    volumes = _docker_filtered_lines(
        ["docker", "volume", "ls", "--quiet", "--filter", label], home=home
    )
    return {"containers": containers, "networks": networks, "volumes": volumes}


def _require_project_absent(project: str, *, home: Path) -> dict[str, object]:
    resources = _project_resources(project, home=home)
    if any(resources.values()):
        raise RuntimeError("manfred_capacity_candidate_resources_present")
    return {
        "project": project,
        "containers": [],
        "networks": [],
        "volumes": [],
        "resources_absent": True,
    }


def _expected_empty_registry_sha256() -> str:
    return _sha256(_json_bytes(_registry_payload([], [])))


def _candidate_evidence(
    *,
    home: Path,
    registry_path: Path,
    protected_image_ids: set[str],
) -> dict[str, object]:
    loaded = _read_registry_json(registry_path)
    if loaded is None:
        raise RuntimeError("manfred_capacity_candidate_registry_missing")
    registry, registry_sha256 = loaded
    entries, pending = _validated_registry(registry)
    if registry.get("schema") != REGISTRY_SCHEMA or len(entries) != 1 or pending:
        raise RuntimeError("manfred_capacity_candidate_registry_not_single_stale")
    runtime, observed_entry, identity = _receipt_entry(Path(entries[0]["receipt_path"]))
    if observed_entry != entries[0] or identity.get("schema") != RUNTIME_SCHEMA_V5:
        raise RuntimeError("manfred_capacity_candidate_receipt_invalid")
    project = str(identity.get("project") or "")
    revision = str(identity.get("revision") or "")
    image_id = str(identity.get("image_id") or "")
    image_tag = str(identity.get("image") or "")
    if (
        project != EXPECTED_CANDIDATE_PROJECT
        or revision != EXPECTED_CANDIDATE_REVISION
        or image_id != EXPECTED_CANDIDATE_IMAGE_ID
        or image_tag != EXPECTED_CANDIDATE_IMAGE
        or runtime.get("promotion_authority") is not False
        or runtime.get("live_ea_api_unchanged") is not True
        or runtime.get("provider_credentials_present") is not False
        or runtime.get("provider_calls_performed") is not False
    ):
        raise RuntimeError("manfred_capacity_candidate_receipt_invalid")
    absence = _require_project_absent(project, home=home)
    ancestor = _docker_filtered_lines(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"ancestor={image_id}",
        ],
        home=home,
    )
    if ancestor:
        raise RuntimeError("manfred_capacity_candidate_image_referenced")
    raw_image = _bounded_run(
        ["docker", "image", "inspect", image_id], home=home
    )
    image_rows = _json_output(raw_image, error="manfred_capacity_candidate_image_invalid")
    if not isinstance(image_rows, list) or len(image_rows) != 1:
        raise RuntimeError("manfred_capacity_candidate_image_invalid")
    image = image_rows[0]
    config = image.get("Config") if isinstance(image, dict) else None
    labels = config.get("Labels") if isinstance(config, dict) else None
    if (
        not isinstance(image, dict)
        or image.get("Id") != image_id
        or image.get("RepoTags") != [image_tag]
        or image.get("RepoDigests") not in (None, [])
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != revision
        or image_id in protected_image_ids
    ):
        raise RuntimeError("manfred_capacity_candidate_image_invalid")
    raw_df = _bounded_run(
        ["docker", "system", "df", "--verbose", "--format", "json"], home=home
    )
    df_payload = _json_output(raw_df, error="manfred_capacity_docker_df_invalid")
    images = df_payload.get("Images") if isinstance(df_payload, dict) else None
    matches = [row for row in images or [] if isinstance(row, dict) and row.get("ID") == image_id]
    if len(matches) != 1 or str(matches[0].get("Containers")) != "0":
        raise RuntimeError("manfred_capacity_candidate_image_usage_invalid")
    unique_floor = _parse_size_floor(matches[0].get("UniqueSize"))
    return {
        "project": project,
        "revision": revision,
        "image_tag": image_tag,
        "image_id": image_id,
        "image_unique_floor_bytes": unique_floor,
        "image_aliases": [image_tag],
        "registry_path": str(registry_path),
        "registry_sha256_before": registry_sha256,
        "registry_sha256_after": _expected_empty_registry_sha256(),
        "receipt_path": entries[0]["receipt_path"],
        "receipt_sha256": entries[0]["receipt_sha256"],
        "resource_absence": absence,
        "promotion_authority": False,
        "live_image_protected": True,
        "other_zero_container_images_protected": True,
    }


def _process_error_is_vanished(exc: OSError) -> bool:
    return exc.errno in {errno.ENOENT, errno.ESRCH}


def _bounded_process_read(path: Path, *, maximum: int) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise RuntimeError("manfred_capacity_process_inventory_unbounded")
    finally:
        os.close(descriptor)


def _controller_process_inventory(uid: int) -> dict[str, object]:
    """Return bounded aggregate health without claiming unreadable refs are absent."""

    try:
        process_entries = _bounded_scandir(
            Path("/proc"),
            maximum=MAX_PROCESS_COUNT,
            error="manfred_capacity_process_inventory_unbounded",
        )
    except RuntimeError:
        return {
            "status": "degraded",
            "same_uid_process_count": 0,
            "unreadable_process_count": 0,
            "unbounded_process_count": 0,
            "process_enumeration_complete": False,
            "process_identities_included": False,
        }
    same_uid_count = 0
    unreadable_count = 0
    unbounded_count = 0
    for entry in process_entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        process_root = Path(entry.path)
        try:
            if process_root.stat().st_uid != uid:
                continue
        except OSError as exc:
            if _process_error_is_vanished(exc):
                continue
            unreadable_count += 1
            continue
        same_uid_count += 1
        degraded = False
        unbounded = False
        try:
            _bounded_process_read(
                process_root / "cmdline", maximum=MAX_PROCESS_CMDLINE_BYTES
            )
            for name in ("exe", "cwd", "root"):
                os.readlink(process_root / name)
            _bounded_process_read(
                process_root / "maps", maximum=MAX_PROCESS_MAPS_BYTES
            )
            with os.scandir(process_root / "fd") as iterator:
                descriptors = []
                for descriptor in iterator:
                    if len(descriptors) >= MAX_PROCESS_FDS:
                        raise RuntimeError(
                            "manfred_capacity_process_fd_inventory_unbounded"
                        )
                    descriptors.append(descriptor)
            for descriptor in descriptors:
                try:
                    os.readlink(descriptor.path)
                except OSError as exc:
                    if not _process_error_is_vanished(exc):
                        raise
        except RuntimeError:
            degraded = True
            unbounded = True
        except OSError as exc:
            if not _process_error_is_vanished(exc):
                degraded = True
        if degraded:
            unreadable_count += 1
        if unbounded:
            unbounded_count += 1
    return {
        "status": "complete" if unreadable_count == 0 else "degraded",
        "same_uid_process_count": same_uid_count,
        "unreadable_process_count": unreadable_count,
        "unbounded_process_count": unbounded_count,
        "process_enumeration_complete": True,
        "process_identities_included": False,
    }


def _controller_inventory_error(exc: RuntimeError) -> bool:
    return str(exc) in {
        "manfred_capacity_active_tool_inventory_invalid",
        "manfred_capacity_active_tools_unbounded",
        "manfred_capacity_process_inventory_invalid",
        "manfred_capacity_process_inventory_unbounded",
        "manfred_capacity_process_fd_inventory_unbounded",
        "manfred_capacity_process_references_unbounded",
    }


def _process_references(path: Path, *, uid: int) -> list[dict[str, object]]:
    prefix = str(path.absolute())
    references: list[dict[str, object]] = []
    process_entries = _bounded_scandir(
        Path("/proc"),
        maximum=MAX_PROCESS_COUNT,
        error="manfred_capacity_process_inventory_unbounded",
    )
    for entry in process_entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        process_root = Path(entry.path)
        try:
            if process_root.stat().st_uid != uid:
                continue
        except OSError as exc:
            if _process_error_is_vanished(exc):
                continue
            raise RuntimeError("manfred_capacity_process_inventory_invalid") from exc
        kinds: set[str] = set()
        for name in ("exe", "cwd", "root"):
            try:
                target = os.readlink(process_root / name)
            except OSError as exc:
                if _process_error_is_vanished(exc):
                    continue
                raise RuntimeError(
                    "manfred_capacity_process_inventory_invalid"
                ) from exc
            if target == prefix or target.startswith(f"{prefix}/"):
                kinds.add(name)
        try:
            command = _bounded_process_read(
                process_root / "cmdline", maximum=MAX_PROCESS_CMDLINE_BYTES
            )
        except OSError as exc:
            if _process_error_is_vanished(exc):
                command = b""
            else:
                raise RuntimeError(
                    "manfred_capacity_process_inventory_invalid"
                ) from exc
        if prefix.encode("utf-8") in command:
            kinds.add("cmdline")
        try:
            maps = _bounded_process_read(
                process_root / "maps", maximum=MAX_PROCESS_MAPS_BYTES
            )
        except OSError as exc:
            if _process_error_is_vanished(exc):
                maps = b""
            else:
                raise RuntimeError(
                    "manfred_capacity_process_inventory_invalid"
                ) from exc
        if prefix.encode("utf-8") in maps:
            kinds.add("maps")
        fd_root = process_root / "fd"
        try:
            with os.scandir(fd_root) as iterator:
                descriptors = []
                for descriptor in iterator:
                    if len(descriptors) >= MAX_PROCESS_FDS:
                        raise RuntimeError(
                            "manfred_capacity_process_fd_inventory_unbounded"
                        )
                    descriptors.append(descriptor)
        except OSError as exc:
            if _process_error_is_vanished(exc):
                descriptors = []
            else:
                raise RuntimeError(
                    "manfred_capacity_process_inventory_invalid"
                ) from exc
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor.path)
            except OSError as exc:
                if _process_error_is_vanished(exc):
                    continue
                raise RuntimeError(
                    "manfred_capacity_process_inventory_invalid"
                ) from exc
            if target == prefix or target.startswith(f"{prefix}/"):
                kinds.add("fd")
                break
        if kinds:
            references.append({"pid": int(entry.name), "kinds": sorted(kinds)})
            if len(references) > MAX_PROCESS_REFERENCES:
                raise RuntimeError("manfred_capacity_process_references_unbounded")
    return sorted(references, key=lambda row: int(row["pid"]))


def _active_tool_processes(uid: int, tokens: set[str]) -> list[int]:
    matches: list[int] = []
    process_entries = _bounded_scandir(
        Path("/proc"),
        maximum=MAX_PROCESS_COUNT,
        error="manfred_capacity_active_tools_unbounded",
    )
    for entry in process_entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        root = Path(entry.path)
        try:
            if root.stat().st_uid != uid:
                continue
            command = _bounded_process_read(
                root / "cmdline", maximum=MAX_PROCESS_CMDLINE_BYTES
            )
            parts = [
                Path(value.decode("utf-8", errors="ignore")).name.lower()
                for value in command.split(b"\0")
                if value
            ]
        except OSError as exc:
            if _process_error_is_vanished(exc):
                continue
            raise RuntimeError(
                "manfred_capacity_active_tool_inventory_invalid"
            ) from exc
        if any(part in tokens for part in parts):
            matches.append(int(entry.name))
    if len(matches) > MAX_PROCESS_REFERENCES:
        raise RuntimeError("manfred_capacity_active_tools_unbounded")
    return sorted(matches)


def _decode_single_path(raw: bytes, *, error: str) -> Path:
    try:
        lines = [line.strip() for line in raw.decode("utf-8", errors="strict").splitlines() if line.strip()]
    except UnicodeDecodeError as exc:
        raise RuntimeError(error) from exc
    if len(lines) != 1:
        raise RuntimeError(error)
    path = Path(lines[0]).expanduser()
    if not path.is_absolute():
        raise RuntimeError(error)
    return path


def _official_cache_paths(*, home: Path) -> dict[str, Path]:
    raw_nuget = _bounded_run(
        ["dotnet", "nuget", "locals", "all", "--list"], home=home
    )
    try:
        nuget_lines = [
            line.strip()
            for line in raw_nuget.decode("utf-8", errors="strict").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_capacity_nuget_paths_invalid") from exc
    nuget_paths: dict[str, Path] = {}
    for line in nuget_lines:
        name, separator, value = line.partition(":")
        if separator != ":" or not name or not value.strip():
            raise RuntimeError("manfred_capacity_nuget_paths_invalid")
        if name in nuget_paths:
            raise RuntimeError("manfred_capacity_nuget_paths_invalid")
        nuget_paths[name] = Path(value.strip())
    expected_nuget = {
        "http-cache": home / ".local/share/NuGet/http-cache",
        "global-packages": home / ".nuget/packages",
    }
    if any(nuget_paths.get(name) != path for name, path in expected_nuget.items()):
        raise RuntimeError("manfred_capacity_nuget_paths_invalid")

    npm_root = _decode_single_path(
        _bounded_run(["npm", "config", "get", "cache"], home=home),
        error="manfred_capacity_npm_path_invalid",
    )
    if npm_root != home / ".npm":
        raise RuntimeError("manfred_capacity_npm_path_invalid")
    pip_root = _decode_single_path(
        _bounded_run(
            [PYTHON_EXECUTABLE, "-I", "-m", "pip", "cache", "dir"],
            home=home,
        ),
        error="manfred_capacity_pip_path_invalid",
    )
    if pip_root != home / ".cache/pip":
        raise RuntimeError("manfred_capacity_pip_path_invalid")
    return {
        "nuget_http": expected_nuget["http-cache"],
        "nuget_global_packages": expected_nuget["global-packages"],
        "npm_content_cache": npm_root / "_cacache",
        "pip_cache": pip_root,
    }


def _cache_evidence(
    *,
    home: Path,
    uid: int,
    process_inventory: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    official_paths = _official_cache_paths(home=home)
    mutation_commands = dict(CACHE_MUTATION_COMMANDS)
    inventory = (
        process_inventory
        if process_inventory is not None
        else _controller_process_inventory(uid)
    )

    specifications = (
        (
            "nuget_http",
            official_paths["nuget_http"],
            mutation_commands["nuget_http"],
            {"nuget", "restore", "msbuild"},
        ),
        (
            "nuget_global_packages",
            official_paths["nuget_global_packages"],
            mutation_commands["nuget_global_packages"],
            {"nuget", "restore", "msbuild"},
        ),
        (
            "npm_content_cache",
            official_paths["npm_content_cache"],
            mutation_commands["npm_content_cache"],
            {"npx", "cache", "install", "ci", "add", "update"},
        ),
        (
            "pip_cache",
            official_paths["pip_cache"],
            mutation_commands["pip_cache"],
            {
                "pip",
                "pip3",
                "pip3.12",
            },
        ),
    )
    caches: list[dict[str, object]] = []
    for name, path, argv, tokens in specifications:
        evidence = _tree_evidence(
            path,
            allowed_owners={uid},
            hash_content=False,
            missing_ok=True,
        )
        active: list[int] = []
        availability = "process_inventory_unavailable"
        eligible = False
        if inventory.get("status") == "complete":
            try:
                active = sorted(
                    set(_active_tool_processes(uid, set(tokens)))
                    | {
                        int(row["pid"])
                        for row in _process_references(path, uid=uid)
                    }
                )
            except RuntimeError as exc:
                if not _controller_inventory_error(exc):
                    raise
                inventory["status"] = "degraded"
                inventory["process_enumeration_complete"] = False
            else:
                eligible = not active
                availability = "eligible" if eligible else "active_process"
        caches.append(
            {
                "name": name,
                "tree": evidence.as_dict(),
                "clear_argv": list(argv),
                "active_processes": [],
                "active_process_count": len(active),
                "active_process_identities_redacted": True,
                "eligible": eligible,
                "user_eligible": eligible,
                "availability": availability,
                "eligible_reclaim_floor_bytes": (
                    evidence.allocated_bytes if eligible else 0
                ),
                "root_candidate": (
                    evidence.exists
                    and not eligible
                    and availability == "process_inventory_unavailable"
                ),
                "root_reclaim_floor_bytes": (
                    evidence.allocated_bytes
                    if evidence.exists
                    and not eligible
                    and availability == "process_inventory_unavailable"
                    else 0
                ),
                "root_classification": "rebuildable_operator_cache",
                "process_inventory_status": (
                    "complete" if availability != "process_inventory_unavailable" else "degraded"
                ),
                "official_cache_contract": True,
            }
        )
    return caches


def _vscode_evidence(
    *,
    home: Path,
    uid: int,
    process_inventory: dict[str, object] | None = None,
) -> dict[str, object]:
    server_root = home / ".vscode-server/cli/servers"
    inventory = (
        process_inventory
        if process_inventory is not None
        else _controller_process_inventory(uid)
    )
    root_status = server_root.stat()
    cli_status = server_root.parent.stat()
    if (
        not stat.S_ISDIR(root_status.st_mode)
        or root_status.st_uid != uid
        or not stat.S_ISDIR(cli_status.st_mode)
        or cli_status.st_uid != uid
        or stat.S_IMODE(cli_status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_capacity_vscode_root_invalid")
    server_paths: list[Path] = []
    preserved_metadata: list[dict[str, object]] = []
    for entry in _bounded_scandir(
        server_root,
        maximum=MAX_VSCODE_ROOT_ENTRIES,
        error="manfred_capacity_vscode_root_invalid",
    ):
        if entry.name == "lru.json":
            metadata = os.stat(entry.path, follow_symlinks=False)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != uid
                or metadata.st_gid != os.getgid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o644
                or not 1 <= metadata.st_size <= 4096
            ):
                raise RuntimeError("manfred_capacity_vscode_metadata_invalid")
            preserved_metadata.append(
                {
                    "name": "lru.json",
                    "mode": 0o644,
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
                    "nlink": 1,
                    "size_bytes": metadata.st_size,
                    "content_in_receipt": False,
                    "preserved": True,
                }
            )
            continue
        if not entry.is_dir(follow_symlinks=False):
            raise RuntimeError("manfred_capacity_vscode_root_invalid")
        if VSCODE_SERVER_NAME.fullmatch(entry.name) is None:
            raise RuntimeError("manfred_capacity_vscode_server_name_invalid")
        path = Path(entry.path)
        server_paths.append(path)
    if len(preserved_metadata) != 1:
        raise RuntimeError("manfred_capacity_vscode_metadata_invalid")
    if inventory.get("status") != "complete":
        root_candidates = [
            _tree_evidence(
                path,
                allowed_owners={uid},
                hash_content=True,
                missing_ok=False,
            )
            for path in server_paths
        ]
        if len(root_candidates) != 2:
            root_candidates = []
        else:
            root_candidates.sort(
                key=lambda row: (-row.allocated_bytes, row.path)
            )
        return {
            "server_root": str(server_root),
            "server_count": len(server_paths),
            "active_server": None,
            "inactive_server": None,
            "inactive_tree": None,
            "journal_entry_count": 0,
            "journal_entries_sha256": None,
            "journal_payload_bytes": 0,
            "process_references": None,
            "process_inventory_status": "degraded",
            "eligible": False,
            "user_eligible": False,
            "availability": "process_inventory_unavailable",
            "eligible_reclaim_floor_bytes": 0,
            "root_candidate": bool(root_candidates),
            "root_candidate_trees": [row.as_dict() for row in root_candidates],
            "root_reclaim_floor_bytes": (
                max(row.allocated_bytes for row in root_candidates)
                if root_candidates
                else 0
            ),
            "root_selection_limit": 1,
            "root_classification": "rebuildable_inactive_vscode_server",
            "preserved_metadata_entries": preserved_metadata,
            "data_preserved": True,
            "extensions_preserved": True,
            "tokens_preserved": True,
        }
    servers: list[tuple[Path, bool]] = []
    try:
        for path in server_paths:
            servers.append((path, bool(_process_references(path, uid=uid))))
    except RuntimeError as exc:
        if not _controller_inventory_error(exc):
            raise
        inventory["status"] = "degraded"
        inventory["process_enumeration_complete"] = False
        return {
            "server_root": str(server_root),
            "server_count": len(server_paths),
            "active_server": None,
            "inactive_server": None,
            "inactive_tree": None,
            "journal_entry_count": 0,
            "journal_entries_sha256": None,
            "journal_payload_bytes": 0,
            "process_references": None,
            "process_inventory_status": "degraded",
            "eligible": False,
            "user_eligible": False,
            "availability": "process_inventory_unavailable",
            "eligible_reclaim_floor_bytes": 0,
            "root_candidate": False,
            "root_candidate_trees": [],
            "root_reclaim_floor_bytes": 0,
            "root_selection_limit": 1,
            "root_classification": "rebuildable_inactive_vscode_server",
            "preserved_metadata_entries": preserved_metadata,
            "data_preserved": True,
            "extensions_preserved": True,
            "tokens_preserved": True,
        }
    active = [path for path, referenced in servers if referenced]
    inactive = [path for path, referenced in servers if not referenced]
    if len(active) != 1 or len(inactive) != 1:
        raise RuntimeError("manfred_capacity_vscode_topology_invalid")
    target = _tree_evidence(
        inactive[0], allowed_owners={uid}, hash_content=True, missing_ok=False
    )
    journal_entries = _vscode_journal_entries(inactive[0], uid=uid)
    repeated = _tree_evidence(
        inactive[0], allowed_owners={uid}, hash_content=True, missing_ok=False
    )
    if repeated != target:
        raise RuntimeError("manfred_capacity_vscode_tree_changed")
    quarantine = inactive[0].parent / (
        f".ea-capacity-{target.manifest_sha256[:16]}.retired"
    )
    recovery_token = _sha256(
        f"{inactive[0]}\0{target.manifest_sha256}".encode("utf-8")
    )[:24]
    journal_path = server_root.parent / (
        f".ea-capacity-vscode-{recovery_token}.journal.v3.json"
    )
    complete_path = server_root.parent / (
        f".ea-capacity-vscode-{recovery_token}.complete.v3.json"
    )
    for guarded_path in (quarantine, journal_path, complete_path):
        _assert_mount_confinement(
            guarded_path,
            expected_device=target.device,
            allow_missing=True,
        )
    journal = {
        "schema": VSCODE_JOURNAL_SCHEMA,
        "created_at": _utc_now(),
        "operator_uid": uid,
        "target_path": str(inactive[0]),
        "quarantine_path": str(quarantine),
        "manifest_sha256": target.manifest_sha256,
        "entries": journal_entries,
        "entry_count": len(journal_entries),
        "target_broadened": False,
    }
    journal_bytes = _json_bytes(journal)
    return {
        "server_root": str(server_root),
        "server_count": len(server_paths),
        "active_server": active[0].name,
        "inactive_server": inactive[0].name,
        "inactive_tree": target.as_dict(),
        "journal_entry_count": len(journal_entries),
        "journal_entries_sha256": _sha256(_json_bytes(journal_entries)),
        "journal_payload_bytes": len(journal_bytes),
        "process_references": [],
        "process_inventory_status": "complete",
        "eligible": True,
        "user_eligible": True,
        "availability": "eligible",
        "eligible_reclaim_floor_bytes": target.allocated_bytes,
        "root_candidate": False,
        "root_candidate_trees": [],
        "root_reclaim_floor_bytes": 0,
        "root_selection_limit": 1,
        "root_classification": "rebuildable_inactive_vscode_server",
        "preserved_metadata_entries": preserved_metadata,
        "data_preserved": True,
        "extensions_preserved": True,
        "tokens_preserved": True,
    }


def _temp_root_candidate_evidence(*, uid: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for action_id, path, observation in ROOT_TEMP_CANDIDATE_SPECS:
        evidence: TreeEvidence | None = None
        availability = "eligible"
        try:
            evidence = _tree_evidence(
                path,
                allowed_owners={0, uid},
                hash_content=True,
                missing_ok=True,
            )
        except RuntimeError as exc:
            if str(exc) not in {
                "manfred_capacity_tree_identity_invalid",
                "manfred_capacity_tree_device_changed",
                "manfred_capacity_tree_unreadable",
                "manfred_capacity_tree_too_large",
                "manfred_capacity_mount_boundary_invalid",
                "manfred_capacity_path_symlink_invalid",
            }:
                raise
            availability = "unsafe_tree_excluded"
        root_identity: dict[str, object] | None = None
        if os.path.lexists(path):
            status = os.lstat(path)
            root_identity = {
                "path": str(path),
                "device": status.st_dev,
                "inode": status.st_ino,
                "uid": status.st_uid,
                "gid": status.st_gid,
                "mode": stat.S_IMODE(status.st_mode),
                "nlink": status.st_nlink,
                "kind": (
                    "directory"
                    if stat.S_ISDIR(status.st_mode)
                    else "symlink"
                    if stat.S_ISLNK(status.st_mode)
                    else "other"
                ),
            }
        exists = bool(evidence is not None and evidence.exists)
        if evidence is not None and not evidence.exists:
            availability = "absent"
        rows.append(
            {
                "action_id": action_id,
                "kind": "rebuildable_temp_tree",
                "classification": "exact_rebuildable_temporary_output",
                "path": str(path),
                "tree": evidence.as_dict() if evidence is not None else None,
                "root_identity": root_identity,
                "user_eligible": False,
                "root_candidate": exists,
                "root_reclaim_floor_bytes": (
                    evidence.allocated_bytes if exists and evidence is not None else 0
                ),
                "availability": availability,
                "reported_observation_bytes": observation,
                "capacity_source": "live_tree_evidence",
                "parent_preserved": True,
                "protected_overlap": False,
                "selection_group": None,
                "selection_limit": None,
            }
        )
    return rows


def _finite_root_candidates(
    *,
    caches: list[dict[str, object]],
    vscode: dict[str, object],
    projections: list[dict[str, object]],
    temp_candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for projection in projections:
        tree = dict(projection.get("tree") or {})
        rows.append(
            {
                "action_id": f"projection:{projection.get('release_id')}",
                "kind": "candidate_release_projection",
                "classification": "receipt_valid_rebuildable_projection",
                "path": str(projection.get("path") or ""),
                "tree": tree,
                "projection": dict(projection),
                "user_eligible": False,
                "root_candidate": True,
                "root_reclaim_floor_bytes": int(tree.get("allocated_bytes") or 0),
                "reported_observation_bytes": None,
                "capacity_source": "live_tree_evidence",
                "parent_preserved": True,
                "protected_overlap": False,
                "selection_group": None,
                "selection_limit": None,
            }
        )
    for cache in caches:
        if cache.get("root_candidate") is not True:
            continue
        tree = dict(cache.get("tree") or {})
        rows.append(
            {
                "action_id": f"cache:{cache.get('name')}",
                "kind": "operator_cache_tree",
                "classification": "rebuildable_operator_cache",
                "path": str(tree.get("path") or ""),
                "tree": tree,
                "cache_name": str(cache.get("name") or ""),
                "user_eligible": bool(cache.get("user_eligible")),
                "root_candidate": bool(cache.get("root_candidate")),
                "root_reclaim_floor_bytes": int(
                    cache.get("root_reclaim_floor_bytes") or 0
                ),
                "reported_observation_bytes": None,
                "capacity_source": "live_tree_evidence",
                "parent_preserved": True,
                "protected_overlap": False,
                "selection_group": None,
                "selection_limit": None,
            }
        )
    vscode_trees = sorted(
        (dict(row) for row in list(vscode.get("root_candidate_trees") or [])),
        key=lambda row: (
            -int(row.get("allocated_bytes") or 0),
            str(row.get("path") or ""),
        ),
    )
    for tree_index, raw_tree in enumerate(vscode_trees):
        tree = dict(raw_tree)
        rows.append(
            {
                "action_id": f"vscode:{Path(str(tree.get('path') or '')).name}",
                "kind": "vscode_server_tree",
                "classification": "rebuildable_inactive_vscode_server",
                "path": str(tree.get("path") or ""),
                "tree": tree,
                "user_eligible": False,
                "root_candidate": bool(vscode.get("root_candidate")),
                "root_reclaim_floor_bytes": int(tree.get("allocated_bytes") or 0),
                "reported_observation_bytes": None,
                "capacity_source": "live_tree_evidence",
                "parent_preserved": True,
                "protected_overlap": False,
                "selection_group": "vscode_inactive_one",
                "selection_order": tree_index,
                "selection_limit": 1,
                "extensions_preserved": True,
                "tokens_preserved": True,
            }
        )
    rows.extend(
        dict(row) for row in temp_candidates if row.get("root_candidate") is True
    )
    if len(rows) > MAX_ROOT_CANDIDATES:
        raise RuntimeError("manfred_capacity_root_candidate_inventory_unbounded")
    paths = [Path(str(row.get("path") or "")) for row in rows]
    action_ids = [str(row.get("action_id") or "") for row in rows]
    if (
        any(not path.is_absolute() or ".." in path.parts for path in paths)
        or len(set(paths)) != len(paths)
        or len(set(action_ids)) != len(action_ids)
        or any(not value for value in action_ids)
        or any(
            left == right
            or left in right.parents
            or right in left.parents
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        )
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    return rows


def _projection_receipt(path: Path, *, uid: int) -> tuple[dict[str, object], str]:
    return _read_private_json(path, expected_owner=uid)


def _projection_evidence(
    *,
    source_root: Path,
    deploy_root: Path,
    home: Path,
    uid: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    deploy_root = deploy_root.resolve(strict=True)
    deploy_status = deploy_root.stat()
    if (
        not stat.S_ISDIR(deploy_status.st_mode)
        or deploy_status.st_uid != uid
        or stat.S_IMODE(deploy_status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_capacity_deploy_root_invalid")
    eligible: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    roots = _bounded_scandir(
        deploy_root,
        maximum=MAX_TREE_ENTRIES,
        error="manfred_capacity_projection_count_unbounded",
    )
    for root_entry in roots:
        if not root_entry.is_dir(follow_symlinks=False):
            continue
        if PROJECTION_ROOT_NAME.fullmatch(root_entry.name) is None:
            continue
        candidate_root = Path(root_entry.path)
        candidate_status = candidate_root.stat()
        if candidate_status.st_uid != uid or stat.S_IMODE(candidate_status.st_mode) != 0o700:
            exclusions.append({"path": str(candidate_root), "reason": "candidate_root_identity_invalid"})
            continue
        releases = candidate_root / "releases"
        if not releases.is_dir():
            continue
        for release_entry in _bounded_scandir(
            releases,
            maximum=MAX_TREE_ENTRIES,
            error="manfred_capacity_projection_count_unbounded",
        ):
            if not release_entry.is_dir(follow_symlinks=False) or release_entry.name.startswith("."):
                continue
            release_root = Path(release_entry.path)
            receipt_path = candidate_root / "receipts" / f"{release_entry.name}.json"
            try:
                receipt, receipt_sha256 = _projection_receipt(receipt_path, uid=uid)
                project = _validate_project_name(receipt.get("compose_project"))
                commit = str(receipt.get("commit") or "")
                raw_runtime_uid = receipt.get("runtime_uid")
                if (
                    receipt.get("schema") != PROJECTION_SCHEMA
                    or receipt.get("status") != "pass"
                    or receipt.get("release_id") != release_entry.name
                    or receipt.get("release_root") != str(release_root)
                    or receipt.get("runtime_root") != str(candidate_root / "runtime")
                    or HEX_40.fullmatch(commit) is None
                    or type(raw_runtime_uid) is not int
                    or raw_runtime_uid < 1
                    or receipt.get("release_authority_promotion_authority") is not False
                    or receipt.get("release_authority_runtime_clear") is not True
                ):
                    raise RuntimeError("projection_receipt_invalid")
                spatial_path = Path(str(receipt.get("spatial_receipt_path") or ""))
                if (
                    spatial_path.parent != candidate_root / "receipts"
                    or spatial_path.name != f"{release_entry.name}.spatial.json"
                ):
                    raise RuntimeError("spatial_receipt_path_invalid")
                _, spatial_sha = _projection_receipt(spatial_path, uid=uid)
                if spatial_sha != receipt.get("spatial_receipt_sha256"):
                    raise RuntimeError("spatial_receipt_changed")
                tree_digest, files = _projection_tree_digest(release_root)
                if (
                    tree_digest != receipt.get("projection_sha256")
                    or len(files) != receipt.get("file_count")
                    or sum(int(row["size_bytes"]) for row in files)
                    != receipt.get("projection_bytes")
                ):
                    raise RuntimeError("projection_tree_changed")
                tree = _tree_evidence(
                    release_root,
                    allowed_owners={raw_runtime_uid},
                    hash_content=True,
                    require_read_only=True,
                )
                _bounded_run(
                    ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                    home=home,
                    cwd=source_root,
                )
                absence = _require_project_absent(project, home=home)
                eligible.append(
                    {
                        "path": str(release_root),
                        "candidate_root": str(candidate_root),
                        "release_id": release_entry.name,
                        "project": project,
                        "commit": commit,
                        "receipt_path": str(receipt_path),
                        "receipt_sha256": receipt_sha256,
                        "spatial_receipt_path": str(spatial_path),
                        "spatial_receipt_sha256": spatial_sha,
                        "projection_sha256": tree_digest,
                        "projection_bytes": receipt["projection_bytes"],
                        "runtime_uid": raw_runtime_uid,
                        "release_authority_promotion_authority": False,
                        "release_authority_runtime_clear": True,
                        "tree": tree.as_dict(),
                        "resource_absence": absence,
                        "process_references": None,
                        "root_revalidation_required": True,
                        "process_reference_check": "root_revalidation_required",
                        "runtime_preserved": True,
                        "receipts_preserved": True,
                        "candidate_root_preserved": True,
                    }
                )
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                exclusions.append(
                    {
                        "path": str(release_root),
                        "reason": (
                            str(exc)
                            if re.fullmatch(r"[a-z0-9_]{1,120}", str(exc))
                            else "projection_not_eligible"
                        ),
                    }
                )
    if len(eligible) > MAX_PROJECTIONS:
        raise RuntimeError("manfred_capacity_projection_count_unbounded")
    eligible.sort(key=lambda row: (str(row["commit"]), str(row["path"])))
    exclusions.sort(key=lambda row: str(row["path"]))
    if len(eligible) != EXPECTED_PROJECTION_COUNT:
        raise RuntimeError("manfred_capacity_projection_set_changed")
    return eligible, exclusions


def _protected_image_ids(
    *, home: Path, explicit: Sequence[str]
) -> set[str]:
    protected: set[str] = set()
    for value in explicit:
        normalized = str(value or "").lower()
        if IMAGE_ID.fullmatch(normalized) is None:
            raise RuntimeError("manfred_capacity_protected_image_invalid")
        protected.add(normalized)
    live_ids = _docker_filtered_lines(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={LIVE_COMPOSE_PROJECT}",
            "--filter",
            f"label=com.docker.compose.service={LIVE_API_SERVICE}",
        ],
        home=home,
    )
    if not live_ids:
        raise RuntimeError("manfred_capacity_live_api_missing")
    if any(HEX_64.fullmatch(value) is None for value in live_ids):
        raise RuntimeError("manfred_capacity_live_api_inventory_invalid")
    raw = _bounded_run(
        ["docker", "container", "inspect", *sorted(set(live_ids))], home=home
    )
    rows = _json_output(raw, error="manfred_capacity_live_api_inventory_invalid")
    if not isinstance(rows, list) or len(rows) != len(set(live_ids)):
        raise RuntimeError("manfred_capacity_live_api_inventory_invalid")
    for row in rows:
        image_id = str(row.get("Image") or "") if isinstance(row, dict) else ""
        if IMAGE_ID.fullmatch(image_id) is None:
            raise RuntimeError("manfred_capacity_live_api_inventory_invalid")
        protected.add(image_id)
    return protected


def redacted_plan_probe(
    *,
    source_root: Path,
    deploy_root: Path,
    registry_path: Path,
    protected_image_ids: Sequence[str] = (),
) -> dict[str, object]:
    """Run the complete read-only plan and expose only bounded smoke evidence."""

    plan = discover_plan(
        source_root=source_root,
        deploy_root=deploy_root,
        registry_path=registry_path,
        protected_image_ids=protected_image_ids,
    )
    protected = list(plan["protected_image_ids"])
    projections = list(plan["projections"])
    vscode = dict(plan["vscode"])
    process_inventory = dict(plan["controller_process_inventory"])
    unavailable = dict(plan["unavailable_user_actions"])
    return {
        "schema": PLAN_PROBE_SCHEMA,
        "status": "pass",
        "plan_sha256": plan["plan_sha256"],
        "root_free_bytes_before": plan["root_free_bytes_before"],
        "target_root_free_bytes": plan["target_root_free_bytes"],
        "required_reclaim_bytes": plan["required_reclaim_bytes"],
        "user_eligible_reclaim_floor_bytes": plan[
            "user_eligible_reclaim_floor_bytes"
        ],
        "root_revalidation_reclaim_floor_bytes": plan[
            "root_revalidation_reclaim_floor_bytes"
        ],
        "root_candidate_reclaim_floor_bytes": plan[
            "root_candidate_reclaim_floor_bytes"
        ],
        "root_candidate_count": plan["root_candidate_count"],
        "unsafe_temp_candidate_exclusion_count": plan[
            "unsafe_temp_candidate_exclusion_count"
        ],
        "root_attestation_required_before_user_mutation": plan[
            "root_attestation_required_before_user_mutation"
        ],
        "eligible_reclaim_floor_bytes": plan["eligible_reclaim_floor_bytes"],
        "eligible_capacity_deficit_bytes": plan[
            "eligible_capacity_deficit_bytes"
        ],
        "eligible_capacity_sufficient": plan["eligible_capacity_sufficient"],
        "projection_count": len(projections),
        "projection_set_sha256": _sha256(
            _json_bytes(sorted(str(dict(row)["path"]) for row in projections))
        ),
        "protected_image_count": len(protected),
        "protected_image_set_sha256": _sha256(_json_bytes(sorted(protected))),
        "vscode_journal_entry_count": vscode["journal_entry_count"],
        "vscode_journal_payload_bytes": vscode["journal_payload_bytes"],
        "vscode_journal_entries_sha256": vscode["journal_entries_sha256"],
        "vscode_action_eligible": vscode["eligible"],
        "controller_process_inventory_degraded": (
            process_inventory["status"] == "degraded"
        ),
        "controller_unreadable_process_count": process_inventory[
            "unreadable_process_count"
        ],
        "unavailable_cache_action_count": unavailable["cache_count"],
        "unavailable_vscode_action_count": unavailable["vscode_count"],
        "unavailable_user_action_count": unavailable["total_count"],
        "live_compose_project": LIVE_COMPOSE_PROJECT,
        "live_api_service": LIVE_API_SERVICE,
        "identities_redacted": True,
        "mutation_performed": False,
        "secrets_included": False,
    }


def _plan_digest_payload(plan: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in plan.items() if key != "plan_sha256"}


def _with_plan_digest(plan: dict[str, object]) -> dict[str, object]:
    payload = dict(plan)
    payload.pop("plan_sha256", None)
    payload["plan_sha256"] = _sha256(_json_bytes(payload))
    return payload


def _root_candidate_floor(rows: list[dict[str, object]]) -> int:
    floor = 0
    grouped: dict[str, list[int]] = {}
    for row in rows:
        if row.get("root_candidate") is not True:
            continue
        value = row.get("root_reclaim_floor_bytes")
        if type(value) is not int or value < 0:
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        group = row.get("selection_group")
        if group is None:
            floor += value
        elif group == "vscode_inactive_one" and row.get("selection_limit") == 1:
            grouped.setdefault(group, []).append(value)
        else:
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    floor += sum(max(values) for values in grouped.values() if values)
    return floor


def _validate_root_candidate_inventory(
    plan: dict[str, object],
    *,
    caches: list[dict[str, object]],
    vscode: dict[str, object],
    projections: list[dict[str, object]],
) -> int:
    operator_uid = plan.get("operator_uid")
    if type(operator_uid) is not int or operator_uid < 1:
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    raw_rows = plan.get("root_candidates")
    if (
        not isinstance(raw_rows, list)
        or not 1 <= len(raw_rows) <= MAX_ROOT_CANDIDATES
        or any(not isinstance(row, dict) for row in raw_rows)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    rows = [dict(row) for row in raw_rows]
    expected_ids = [
        f"projection:{row.get('release_id')}" for row in projections
    ]
    expected_ids.extend(
        f"cache:{row.get('name')}"
        for row in caches
        if row.get("root_candidate") is True
    )
    vscode_trees = sorted(
        (dict(row) for row in list(vscode.get("root_candidate_trees") or [])),
        key=lambda row: (
            -int(row.get("allocated_bytes") or 0),
            str(row.get("path") or ""),
        ),
    )
    expected_ids.extend(
        f"vscode:{Path(str(dict(tree).get('path') or '')).name}"
        for tree in vscode_trees
        if isinstance(tree, dict)
    )
    raw_temp_inventory = plan.get("temp_root_candidate_inventory")
    if (
        not isinstance(raw_temp_inventory, list)
        or len(raw_temp_inventory) != len(ROOT_TEMP_CANDIDATE_SPECS)
        or any(not isinstance(row, dict) for row in raw_temp_inventory)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    temp_inventory = [dict(row) for row in raw_temp_inventory]
    if [str(row.get("action_id") or "") for row in temp_inventory] != [
        action_id for action_id, _path, _bytes in ROOT_TEMP_CANDIDATE_SPECS
    ] or [Path(str(row.get("path") or "")) for row in temp_inventory] != [
        path for _action_id, path, _bytes in ROOT_TEMP_CANDIDATE_SPECS
    ]:
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    for row, (action_id, path, observation) in zip(
        temp_inventory, ROOT_TEMP_CANDIDATE_SPECS, strict=True
    ):
        tree = row.get("tree")
        if (
            row.get("action_id") != action_id
            or row.get("path") != str(path)
            or row.get("reported_observation_bytes") != observation
            or row.get("capacity_source") != "live_tree_evidence"
        ):
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        if isinstance(tree, dict):
            if (
                tree.get("path") != str(path)
                or type(tree.get("exists")) is not bool
                or row.get("root_candidate") is not bool(tree.get("exists"))
                or row.get("root_reclaim_floor_bytes")
                != (
                    int(tree.get("allocated_bytes") or 0)
                    if tree.get("exists") is True
                    else 0
                )
                or row.get("availability")
                != ("eligible" if tree.get("exists") is True else "absent")
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        elif (
            tree is not None
            or row.get("root_candidate") is not False
            or row.get("root_reclaim_floor_bytes") != 0
            or row.get("availability") != "unsafe_tree_excluded"
            or not isinstance(row.get("root_identity"), dict)
            or dict(row["root_identity"]).get("path") != str(path)
            or dict(row["root_identity"]).get("kind")
            not in {"directory", "symlink", "other"}
            or any(
                type(dict(row["root_identity"]).get(key)) is not int
                or int(dict(row["root_identity"])[key]) < 0
                for key in ("device", "inode", "uid", "gid", "mode", "nlink")
            )
        ):
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    present_temp_paths = {
        Path(str(dict(row).get("path") or ""))
        for row in temp_inventory
        if row.get("root_candidate") is True
    }
    expected_ids.extend(
        action_id
        for action_id, path, _bytes in ROOT_TEMP_CANDIDATE_SPECS
        if path in present_temp_paths
    )
    action_ids = [str(row.get("action_id") or "") for row in rows]
    paths = [Path(str(row.get("path") or "")) for row in rows]
    if (
        action_ids != expected_ids
        or len(set(action_ids)) != len(action_ids)
        or len(set(paths)) != len(paths)
        or any(not path.is_absolute() or ".." in path.parts for path in paths)
        or any(
            left == right
            or left in right.parents
            or right in left.parents
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        )
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    exact_temp = {
        action_id: (path, observation)
        for action_id, path, observation in ROOT_TEMP_CANDIDATE_SPECS
    }
    allowed_kinds = {
        "candidate_release_projection",
        "operator_cache_tree",
        "vscode_server_tree",
        "rebuildable_temp_tree",
    }
    for row in rows:
        tree = row.get("tree")
        action_id = str(row.get("action_id") or "")
        kind = row.get("kind")
        path = Path(str(row.get("path") or ""))
        if (
            kind not in allowed_kinds
            or not isinstance(tree, dict)
            or tree.get("path") != str(path)
            or tree.get("root_kind") != "directory"
            or type(tree.get("exists")) is not bool
            or type(tree.get("device")) is not int
            or type(tree.get("inode")) is not int
            or type(tree.get("mode")) is not int
            or type(tree.get("uid")) is not int
            or type(tree.get("gid")) is not int
            or type(tree.get("nlink")) is not int
            or type(tree.get("file_count")) is not int
            or type(tree.get("entry_count")) is not int
            or type(tree.get("apparent_bytes")) is not int
            or type(tree.get("allocated_bytes")) is not int
            or any(
                int(tree[key]) < 0
                for key in (
                    "device",
                    "inode",
                    "mode",
                    "uid",
                    "gid",
                    "nlink",
                    "file_count",
                    "entry_count",
                    "apparent_bytes",
                    "allocated_bytes",
                )
            )
            or HEX_64.fullmatch(str(tree.get("manifest_sha256") or "")) is None
            or int(tree["nlink"]) < 2
            or int(tree["entry_count"]) < 1
            or type(row.get("user_eligible")) is not bool
            or type(row.get("root_candidate")) is not bool
            or row.get("capacity_source") != "live_tree_evidence"
            or row.get("parent_preserved") is not True
            or row.get("protected_overlap") is not False
            or row.get("root_reclaim_floor_bytes")
            != (
                int(tree["allocated_bytes"])
                if row.get("root_candidate") is True
                else 0
            )
            or (row.get("root_candidate") is True and tree.get("exists") is not True)
            or (row.get("user_eligible") is True and row.get("root_candidate") is True)
        ):
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        if kind == "candidate_release_projection":
            projection = row.get("projection")
            if (
                not isinstance(projection, dict)
                or type(projection.get("runtime_uid")) is not int
                or int(projection["runtime_uid"]) < 1
                or int(projection["runtime_uid"]) == operator_uid
                or tree.get("uid") != projection.get("runtime_uid")
                or projection.get("release_authority_promotion_authority")
                is not False
                or projection.get("release_authority_runtime_clear") is not True
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        elif tree.get("uid") not in {0, operator_uid}:
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        if kind == "rebuildable_temp_tree":
            expected = exact_temp.get(action_id)
            if (
                expected is None
                or path != expected[0]
                or row.get("reported_observation_bytes") != expected[1]
                or row.get("classification")
                != "exact_rebuildable_temporary_output"
                or row.get("root_candidate") is not bool(tree["exists"])
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        elif row.get("reported_observation_bytes") is not None:
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    expected_rows = _finite_root_candidates(
        caches=caches,
        vscode=vscode,
        projections=projections,
        temp_candidates=temp_inventory,
    )
    if rows != expected_rows:
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    return _root_candidate_floor(rows)


def _recomputed_plan_capacity(plan: dict[str, object]) -> dict[str, object]:
    try:
        root_free = plan["root_free_bytes_before"]
        builder = plan["builder"]
        candidate = plan["candidate"]
        caches = plan["caches"]
        vscode = plan["vscode"]
        projections = plan["projections"]
        root_candidates = plan["root_candidates"]
        process_inventory = plan["controller_process_inventory"]
        unavailable = plan["unavailable_user_actions"]
        if (
            type(root_free) is not int
            or root_free < 0
            or not isinstance(builder, dict)
            or not isinstance(candidate, dict)
            or not isinstance(caches, list)
            or not isinstance(vscode, dict)
            or not isinstance(projections, list)
            or not isinstance(root_candidates, list)
            or not isinstance(process_inventory, dict)
            or not isinstance(unavailable, dict)
        ):
            raise ValueError
        builder_floor = builder.get("reclaimable_floor_bytes")
        candidate_floor = candidate.get("image_unique_floor_bytes")
        if (
            type(builder_floor) is not int
            or builder_floor < 0
            or type(candidate_floor) is not int
            or candidate_floor < 0
        ):
            raise ValueError
        expected_cache_names = (
            "nuget_http",
            "nuget_global_packages",
            "npm_content_cache",
            "pip_cache",
        )
        if (
            len(caches) != len(expected_cache_names)
            or tuple(str(dict(row).get("name") or "") for row in caches)
            != expected_cache_names
        ):
            raise ValueError
        cache_floor = 0
        unavailable_cache_count = 0
        cache_mutation_commands = dict(CACHE_MUTATION_COMMANDS)
        for raw in caches:
            if not isinstance(raw, dict):
                raise ValueError
            tree = raw.get("tree")
            eligible = raw.get("eligible")
            floor = raw.get("eligible_reclaim_floor_bytes")
            active_count = raw.get("active_process_count")
            if (
                not isinstance(tree, dict)
                or type(tree.get("allocated_bytes")) is not int
                or int(tree["allocated_bytes"]) < 0
                or type(eligible) is not bool
                or type(floor) is not int
                or type(active_count) is not int
                or active_count < 0
                or raw.get("active_processes") != []
                or raw.get("active_process_identities_redacted") is not True
                or raw.get("official_cache_contract") is not True
                or raw.get("user_eligible") is not eligible
                or type(raw.get("root_candidate")) is not bool
                or type(raw.get("root_reclaim_floor_bytes")) is not int
                or not isinstance(raw.get("clear_argv"), list)
                or tuple(str(value) for value in raw["clear_argv"])
                != cache_mutation_commands.get(str(raw.get("name") or ""))
            ):
                raise ValueError
            if eligible:
                if (
                    raw.get("availability") != "eligible"
                    or raw.get("process_inventory_status") != "complete"
                    or active_count != 0
                    or floor != int(tree["allocated_bytes"])
                    or raw.get("root_candidate") is not False
                    or raw.get("root_reclaim_floor_bytes") != 0
                ):
                    raise ValueError
                cache_floor += floor
            else:
                if (
                    raw.get("availability")
                    not in {"active_process", "process_inventory_unavailable"}
                    or floor != 0
                    or raw.get("root_candidate")
                    is not (
                        raw.get("availability") == "process_inventory_unavailable"
                        and tree.get("exists") is True
                    )
                    or raw.get("root_reclaim_floor_bytes")
                    != (
                        int(tree["allocated_bytes"])
                        if raw.get("root_candidate") is True
                        else 0
                    )
                    or (
                        raw.get("availability") == "active_process"
                        and (
                            raw.get("process_inventory_status") != "complete"
                            or active_count < 1
                        )
                    )
                    or (
                        raw.get("availability")
                        == "process_inventory_unavailable"
                        and raw.get("process_inventory_status") != "degraded"
                    )
                ):
                    raise ValueError
                unavailable_cache_count += 1
        vscode_eligible = vscode.get("eligible")
        vscode_floor = vscode.get("eligible_reclaim_floor_bytes")
        if type(vscode_eligible) is not bool or type(vscode_floor) is not int:
            raise ValueError
        if (
            vscode.get("user_eligible") is not vscode_eligible
            or type(vscode.get("root_candidate")) is not bool
            or not isinstance(vscode.get("root_candidate_trees"), list)
            or type(vscode.get("root_reclaim_floor_bytes")) is not int
            or vscode.get("root_selection_limit") != 1
        ):
            raise ValueError
        if vscode_eligible:
            tree = vscode.get("inactive_tree")
            if (
                vscode.get("availability") != "eligible"
                or vscode.get("process_inventory_status") != "complete"
                or not isinstance(tree, dict)
                or type(tree.get("allocated_bytes")) is not int
                or int(tree["allocated_bytes"]) < 0
                or vscode_floor != int(tree["allocated_bytes"])
                or vscode.get("process_references") != []
                or not isinstance(vscode.get("active_server"), str)
                or not isinstance(vscode.get("inactive_server"), str)
                or type(vscode.get("journal_entry_count")) is not int
                or not 1
                <= int(vscode["journal_entry_count"])
                <= MAX_TREE_FILES + 1
                or type(vscode.get("journal_payload_bytes")) is not int
                or not 1 <= int(vscode["journal_payload_bytes"]) <= MAX_JSON_BYTES
                or HEX_64.fullmatch(
                    str(vscode.get("journal_entries_sha256") or "")
                )
                is None
                or vscode.get("root_candidate") is not False
                or vscode.get("root_candidate_trees") != []
                or vscode.get("root_reclaim_floor_bytes") != 0
            ):
                raise ValueError
        else:
            if (
                vscode.get("availability") != "process_inventory_unavailable"
                or vscode.get("process_inventory_status") != "degraded"
                or vscode_floor != 0
                or vscode.get("inactive_tree") is not None
                or vscode.get("active_server") is not None
                or vscode.get("inactive_server") is not None
                or vscode.get("journal_entry_count") != 0
                or vscode.get("journal_payload_bytes") != 0
                or vscode.get("journal_entries_sha256") is not None
                or vscode.get("process_references") is not None
                or (
                    vscode.get("root_candidate") is True
                    and (
                        len(vscode.get("root_candidate_trees")) != 2
                        or list(vscode.get("root_candidate_trees"))
                        != sorted(
                            (
                                dict(row)
                                for row in vscode.get("root_candidate_trees")
                            ),
                            key=lambda row: (
                                -int(row.get("allocated_bytes") or 0),
                                str(row.get("path") or ""),
                            ),
                        )
                        or vscode.get("root_reclaim_floor_bytes")
                        != int(
                            dict(vscode.get("root_candidate_trees")[0])[
                                "allocated_bytes"
                            ]
                        )
                    )
                )
                or (
                    vscode.get("root_candidate") is False
                    and (
                        vscode.get("root_candidate_trees") != []
                        or vscode.get("root_reclaim_floor_bytes") != 0
                    )
                )
            ):
                raise ValueError
        for raw in projections:
            if not isinstance(raw, dict):
                raise ValueError
            tree = raw.get("tree")
            if (
                raw.get("root_revalidation_required") is not True
                or raw.get("process_reference_check")
                != "root_revalidation_required"
                or raw.get("process_references") is not None
                or not isinstance(tree, dict)
                or type(tree.get("allocated_bytes")) is not int
                or int(tree["allocated_bytes"]) < 0
            ):
                raise ValueError
        inventory_status = process_inventory.get("status")
        inventory_counts = (
            process_inventory.get("same_uid_process_count"),
            process_inventory.get("unreadable_process_count"),
            process_inventory.get("unbounded_process_count"),
        )
        if (
            inventory_status not in {"complete", "degraded"}
            or any(type(value) is not int or value < 0 for value in inventory_counts)
            or any(int(value) > MAX_PROCESS_COUNT for value in inventory_counts)
            or type(process_inventory.get("process_enumeration_complete")) is not bool
            or process_inventory.get("process_identities_included") is not False
            or (
                inventory_status == "complete"
                and (
                    inventory_counts[1:] != (0, 0)
                    or process_inventory.get("process_enumeration_complete") is not True
                )
            )
            or (
                inventory_status == "degraded"
                and any(bool(row.get("eligible")) for row in caches)
            )
            or (inventory_status == "degraded" and vscode_eligible)
        ):
            raise ValueError
        unavailable_vscode_count = int(not vscode_eligible)
        if unavailable != {
            "cache_count": unavailable_cache_count,
            "vscode_count": unavailable_vscode_count,
            "total_count": unavailable_cache_count + unavailable_vscode_count,
            "identities_included": False,
        }:
            raise ValueError
        user_floor = builder_floor + candidate_floor + cache_floor + vscode_floor
        root_floor = _validate_root_candidate_inventory(
            plan,
            caches=[dict(row) for row in caches],
            vscode=vscode,
            projections=[dict(row) for row in projections],
        )
        eligible_floor = user_floor + root_floor
        required = max(0, TARGET_ROOT_FREE_BYTES - root_free)
        deficit = max(0, required - eligible_floor)
        return {
            "required_reclaim_bytes": required,
            "user_eligible_reclaim_floor_bytes": user_floor,
            "root_revalidation_reclaim_floor_bytes": root_floor,
            "root_candidate_reclaim_floor_bytes": root_floor,
            "eligible_reclaim_floor_bytes": eligible_floor,
            "eligible_capacity_deficit_bytes": deficit,
            "eligible_capacity_sufficient": deficit == 0,
        }
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("manfred_capacity_plan_scope_invalid") from None


def _validate_plan(plan: dict[str, object], *, producer_sha256: str) -> None:
    if plan.get("schema") != PLAN_SCHEMA or plan.get("producer_sha256") != producer_sha256:
        raise RuntimeError("manfred_capacity_plan_invalid")
    expected = _sha256(_json_bytes(_plan_digest_payload(plan)))
    if plan.get("plan_sha256") != expected:
        raise RuntimeError("manfred_capacity_plan_digest_invalid")
    if plan.get("target_root_free_bytes") != TARGET_ROOT_FREE_BYTES:
        raise RuntimeError("manfred_capacity_plan_target_invalid")
    recomputed_capacity = _recomputed_plan_capacity(plan)
    if any(plan.get(key) != value for key, value in recomputed_capacity.items()):
        raise RuntimeError("manfred_capacity_plan_capacity_invalid")
    projections = plan.get("projections")
    candidate = plan.get("candidate")
    vscode = plan.get("vscode")
    producer = plan.get("producer")
    root_applier = plan.get("root_applier")
    root_installer = plan.get("root_installer")
    operator_uid = plan.get("operator_uid")
    operator_home = Path(str(plan.get("operator_home") or ""))
    expected_deploy_root = operator_home / DEPLOY_ROOT_RELATIVE
    toolchain = plan.get("pinned_toolchain")
    mutation_helpers = plan.get("mutation_helpers")
    caches = plan.get("caches")
    expected_cache_paths = (
        operator_home / ".local/share/NuGet/http-cache",
        operator_home / ".nuget/packages",
        operator_home / ".npm/_cacache",
        operator_home / ".cache/pip",
    )
    cache_paths = (
        tuple(
            Path(str(dict(dict(row).get("tree") or {}).get("path") or ""))
            for row in caches
        )
        if isinstance(caches, list) and all(isinstance(row, dict) for row in caches)
        else ()
    )
    expected_vscode_root = operator_home / ".vscode-server/cli/servers"
    vscode_tree = (
        dict(vscode.get("inactive_tree") or {}) if isinstance(vscode, dict) else {}
    )
    vscode_active = str(vscode.get("active_server") or "") if isinstance(vscode, dict) else ""
    vscode_inactive = (
        str(vscode.get("inactive_server") or "") if isinstance(vscode, dict) else ""
    )
    vscode_scope_valid = bool(
        isinstance(vscode, dict)
        and vscode.get("server_root") == str(expected_vscode_root)
        and type(vscode.get("server_count")) is int
        and 0 <= int(vscode["server_count"]) <= 64
        and (
            (
                vscode.get("eligible") is True
                and vscode.get("server_count") == 2
                and VSCODE_SERVER_NAME.fullmatch(vscode_active) is not None
                and VSCODE_SERVER_NAME.fullmatch(vscode_inactive) is not None
                and vscode_active != vscode_inactive
                and Path(str(vscode_tree.get("path") or ""))
                == expected_vscode_root / vscode_inactive
            )
            or (
                vscode.get("eligible") is False
                and not vscode_tree
                and not vscode_active
                and not vscode_inactive
            )
        )
    )
    projection_identities = (
        [
            (
                str(row.get("path") or ""),
                str(row.get("candidate_root") or ""),
                str(row.get("release_id") or ""),
            )
            for row in projections
        ]
        if isinstance(projections, list)
        and all(isinstance(row, dict) for row in projections)
        else []
    )
    if (
        not isinstance(projections, list)
        or len(projections) != EXPECTED_PROJECTION_COUNT
        or any(not isinstance(row, dict) for row in projections)
        or any(not all(identity) for identity in projection_identities)
        or len(set(projection_identities)) != len(projection_identities)
        or len({row[0] for row in projection_identities}) != len(projection_identities)
        or len({row[1] for row in projection_identities}) != len(projection_identities)
        or len({row[2] for row in projection_identities}) != len(projection_identities)
        or not isinstance(candidate, dict)
        or candidate.get("project") != EXPECTED_CANDIDATE_PROJECT
        or candidate.get("revision") != EXPECTED_CANDIDATE_REVISION
        or candidate.get("image_id") != EXPECTED_CANDIDATE_IMAGE_ID
        or candidate.get("image_tag") != EXPECTED_CANDIDATE_IMAGE
        or HEX_64.fullmatch(str(candidate.get("receipt_sha256") or "")) is None
        or not isinstance(vscode, dict)
        or cache_paths != expected_cache_paths
        or not vscode_scope_valid
        or type(operator_uid) is not int
        or operator_uid < 1
        or not isinstance(producer, dict)
        or producer.get("path") != plan.get("producer_path")
        or producer.get("sha256") != producer_sha256
        or producer.get("owner_uid") != operator_uid
        or type(producer.get("size_bytes")) is not int
        or not 1 <= int(producer["size_bytes"]) <= MAX_JSON_BYTES * 2
        or type(producer.get("mode")) is not int
        or int(producer["mode"]) & 0o022
        or not isinstance(root_applier, dict)
        or root_applier.get("owner_uid") != operator_uid
        or HEX_64.fullmatch(str(root_applier.get("sha256") or "")) is None
        or type(root_applier.get("size_bytes")) is not int
        or not 1 <= int(root_applier["size_bytes"]) <= MAX_JSON_BYTES * 2
        or type(root_applier.get("mode")) is not int
        or int(root_applier["mode"]) & 0o022
        or root_applier.get("stdlib_only") is not True
        or root_applier.get("repo_imports") is not False
        or root_installer != _root_installer_evidence()
        or not isinstance(mutation_helpers, list)
        or len(mutation_helpers) != len(MUTATION_HELPER_PATHS)
        or [
            str(dict(row).get("path") or "")
            for row in mutation_helpers
            if isinstance(row, dict)
        ]
        != [str(path) for path in MUTATION_HELPER_PATHS]
        or any(
            not isinstance(row, dict)
            or row.get("uid") != operator_uid
            or row.get("nlink") != 1
            or type(row.get("mode")) is not int
            or int(row["mode"]) & 0o022
            or type(row.get("size_bytes")) is not int
            or not 1 <= int(row["size_bytes"]) <= MAX_JSON_BYTES * 2
            or HEX_64.fullmatch(str(row.get("sha256") or "")) is None
            for row in mutation_helpers
        )
        or not operator_home.is_absolute()
        or plan.get("deploy_root") != str(expected_deploy_root)
        or not isinstance(toolchain, list)
        or [
            str(dict(row).get("path") or "")
            for row in toolchain
            if isinstance(row, dict)
        ]
        != list(PINNED_TOOL_PATHS)
        or len(toolchain) != len(PINNED_TOOL_PATHS)
        or plan.get("docker_host") != LOCAL_DOCKER_HOST
        or plan.get("docker_context_inherited") is not False
        or plan.get("global_docker_prune_allowed") is not False
        or plan.get("other_zero_container_images_mutable") is not False
        or plan.get("candidate_roots_removed") is not False
        or plan.get("runtime_or_receipts_removed") is not False
        or plan.get("root_candidate_count")
        != len(list(plan.get("root_candidates") or []))
        or plan.get("root_candidate_scope") != "finite_exact_paths_only"
        or plan.get("root_attestation_required_before_user_mutation") is not True
        or plan.get("unsafe_temp_candidate_exclusion_count")
        != sum(
            dict(row).get("availability") == "unsafe_tree_excluded"
            for row in list(plan.get("temp_root_candidate_inventory") or [])
            if isinstance(row, dict)
        )
    ):
        raise RuntimeError("manfred_capacity_plan_scope_invalid")


def discover_plan(
    *,
    source_root: Path,
    deploy_root: Path,
    registry_path: Path,
    protected_image_ids: Sequence[str] = (),
    operator_uid: int | None = None,
) -> dict[str, object]:
    uid, home = _operator_identity(operator_uid)
    if os.geteuid() != uid:
        raise RuntimeError("manfred_capacity_plan_must_run_as_operator")
    source_root = source_root.resolve(strict=True)
    expected_deploy_root = (home / DEPLOY_ROOT_RELATIVE).resolve(strict=True)
    if deploy_root.resolve(strict=True) != expected_deploy_root:
        raise RuntimeError("manfred_capacity_deploy_root_invalid")
    deploy_root = expected_deploy_root
    if not (source_root / ".git").exists():
        raise RuntimeError("manfred_capacity_source_root_invalid")
    producer = _controller_evidence(uid=uid)
    producer_sha256 = str(producer["sha256"])
    root_applier = _root_applier_evidence(uid=uid)
    root_installer = _root_installer_evidence()
    mutation_helpers = _mutation_helper_evidence(uid=uid)
    toolchain = _pinned_toolchain_evidence()
    with _capacity_lock(uid) as capacity_lock:
        root_free = _root_free_bytes()
        with _exclusive_build_lock():
            builder = _builder_inspection(home)
        with hold_candidate_fleet_lock() as fleet_lock:
            if fleet_lock is None:  # pragma: no cover - non-skip acquisition
                raise RuntimeError("manfred_capacity_candidate_fleet_lock_held")
            protected = _protected_image_ids(home=home, explicit=protected_image_ids)
            candidate = _candidate_evidence(
                home=home,
                registry_path=registry_path,
                protected_image_ids=protected,
            )
            projections, projection_exclusions = _projection_evidence(
                source_root=source_root,
                deploy_root=deploy_root,
                home=home,
                uid=uid,
            )
        process_inventory = _controller_process_inventory(uid)
        caches = _cache_evidence(
            home=home,
            uid=uid,
            process_inventory=process_inventory,
        )
        vscode = _vscode_evidence(
            home=home,
            uid=uid,
            process_inventory=process_inventory,
        )
        if process_inventory.get("status") != "complete":
            for cache in caches:
                cache["eligible"] = False
                cache["user_eligible"] = False
                cache["availability"] = "process_inventory_unavailable"
                cache["eligible_reclaim_floor_bytes"] = 0
                tree = dict(cache.get("tree") or {})
                cache["root_candidate"] = tree.get("exists") is True
                cache["root_reclaim_floor_bytes"] = (
                    int(tree.get("allocated_bytes") or 0)
                    if cache["root_candidate"]
                    else 0
                )
                cache["process_inventory_status"] = "degraded"

        for cache in caches:
            if cache.get("root_candidate") is not True:
                continue
            path = Path(str(dict(cache.get("tree") or {}).get("path") or ""))
            full_evidence = _tree_evidence(
                path,
                allowed_owners={uid},
                hash_content=True,
                missing_ok=False,
            )
            cache["tree"] = full_evidence.as_dict()
            cache["root_reclaim_floor_bytes"] = full_evidence.allocated_bytes

        temp_candidates = _temp_root_candidate_evidence(uid=uid)
        root_candidates = _finite_root_candidates(
            caches=caches,
            vscode=vscode,
            projections=projections,
            temp_candidates=temp_candidates,
        )

    cache_floor = sum(int(row["eligible_reclaim_floor_bytes"]) for row in caches)
    vscode_floor = int(vscode["eligible_reclaim_floor_bytes"])
    user_reclaim_floor = (
        int(builder["reclaimable_floor_bytes"])
        + int(candidate["image_unique_floor_bytes"])
        + cache_floor
        + vscode_floor
    )
    root_revalidation_floor = _root_candidate_floor(root_candidates)
    reclaim_floor = user_reclaim_floor + root_revalidation_floor
    required_reclaim = max(0, TARGET_ROOT_FREE_BYTES - root_free)
    capacity_deficit = max(0, required_reclaim - reclaim_floor)
    unavailable_cache_count = sum(not bool(row["eligible"]) for row in caches)
    unavailable_vscode_count = int(not bool(vscode["eligible"]))
    protected_digest = _sha256(_json_bytes(sorted(protected)))
    plan = {
        "schema": PLAN_SCHEMA,
        "created_at": _utc_now(),
        "producer_sha256": producer_sha256,
        "producer_path": producer["path"],
        "producer": producer,
        "root_applier": root_applier,
        "root_installer": root_installer,
        "mutation_helpers": mutation_helpers,
        "pinned_toolchain": toolchain,
        "docker_host": LOCAL_DOCKER_HOST,
        "docker_context_inherited": False,
        "operator_uid": uid,
        "operator_home": str(home),
        "source_root": str(source_root),
        "deploy_root": str(deploy_root.resolve(strict=True)),
        "root_free_bytes_before": root_free,
        "build_minimum_root_free_bytes": MINIMUM_ROOT_FREE_BYTES,
        "target_headroom_bytes": TARGET_HEADROOM_BYTES,
        "target_root_free_bytes": TARGET_ROOT_FREE_BYTES,
        "required_reclaim_bytes": required_reclaim,
        "user_eligible_reclaim_floor_bytes": user_reclaim_floor,
        "root_revalidation_reclaim_floor_bytes": root_revalidation_floor,
        "root_candidate_reclaim_floor_bytes": root_revalidation_floor,
        "eligible_reclaim_floor_bytes": reclaim_floor,
        "eligible_capacity_deficit_bytes": capacity_deficit,
        "eligible_capacity_sufficient": capacity_deficit == 0,
        "controller_process_inventory": dict(process_inventory),
        "unavailable_user_actions": {
            "cache_count": unavailable_cache_count,
            "vscode_count": unavailable_vscode_count,
            "total_count": unavailable_cache_count + unavailable_vscode_count,
            "identities_included": False,
        },
        "capacity_lock": capacity_lock,
        "fleet_lock": dict(fleet_lock),
        "build_lock": {
            "scope": "manfred_image_build",
            "exclusive": True,
            "nonblocking": True,
        },
        "builder": builder,
        "candidate": candidate,
        "caches": caches,
        "vscode": vscode,
        "projections": projections,
        "temp_root_candidate_inventory": temp_candidates,
        "root_candidates": root_candidates,
        "root_candidate_count": len(root_candidates),
        "unsafe_temp_candidate_exclusion_count": sum(
            row.get("availability") == "unsafe_tree_excluded"
            for row in temp_candidates
        ),
        "root_candidate_scope": "finite_exact_paths_only",
        "root_attestation_required_before_user_mutation": True,
        "projection_count": len(projections),
        "projection_exclusions": projection_exclusions,
        "protected_image_ids": sorted(protected),
        "protected_image_ids_sha256": protected_digest,
        "protected_paths": list(PROTECTED_PATH_LABELS),
        "mutation_scope": [
            "dedicated_builder_reclaimable_cache",
            "official_operator_caches",
            "one_inactive_vscode_server",
            "one_registered_non_promotion_candidate_image",
            "receipt_valid_candidate_release_projections",
            "finite_root_attested_rebuildable_cache_and_temp_trees",
        ],
        "global_docker_prune_allowed": False,
        "other_zero_container_images_mutable": False,
        "candidate_roots_removed": False,
        "runtime_or_receipts_removed": False,
        "secrets_included": False,
    }
    return _with_plan_digest(plan)


def _root_candidate_set_sha256(plan: dict[str, object]) -> str:
    return _sha256(_json_bytes(list(plan.get("root_candidates") or [])))


def _root_attest_request_payload(
    *,
    plan: dict[str, object],
    request_path: Path,
    root_attestation_path: Path,
) -> dict[str, object]:
    producer = dict(plan["producer"])
    applier = dict(plan["root_applier"])
    return {
        "schema": ROOT_ATTEST_REQUEST_SCHEMA,
        "created_at": _utc_now(),
        "producer_sha256": plan["producer_sha256"],
        "producer_path": plan["producer_path"],
        "producer_source": producer,
        "root_applier_path": applier["path"],
        "root_applier_sha256": applier["sha256"],
        "root_applier_source": applier,
        "root_applier_stdlib_only": True,
        "root_installer": dict(plan["root_installer"]),
        "root_installer_sha256": ROOT_INSTALLER_SHA256,
        "root_stage_contract": {
            "parent": "/root",
            "mode": 0o700,
            "applier_name": "applier.py",
            "applier_mode": 0o500,
            "controller_name": "controller.py",
            "controller_mode": 0o400,
            "handoff_name": "handoff.json",
            "handoff_mode": 0o400,
            "user_receipt_name": "user-receipt.json",
            "user_receipt_mode": 0o400,
        },
        "operator_uid": plan["operator_uid"],
        "operator_home": plan["operator_home"],
        "deploy_root": plan["deploy_root"],
        "request_source_path": str(request_path.absolute()),
        "root_attestation_path": str(root_attestation_path.absolute()),
        "plan_sha256": plan["plan_sha256"],
        "root_candidate_set_sha256": _root_candidate_set_sha256(plan),
        "root_candidate_count": len(list(plan["root_candidates"])),
        "root_candidates": list(plan["root_candidates"]),
        "projection_count": len(list(plan["projections"])),
        "projections": list(plan["projections"]),
        "user_eligible_reclaim_floor_bytes": plan[
            "user_eligible_reclaim_floor_bytes"
        ],
        "guaranteed_user_reclaim_floor_bytes": 0,
        "target_root_free_bytes": plan["target_root_free_bytes"],
        "preflight_scope": "complete_finite_root_candidate_union",
        "two_sample_required": True,
        "all_process_fields_required": [
            "cwd",
            "root",
            "exe",
            "fd",
            "maps",
            "cmdline",
            "environ",
            "mountinfo",
        ],
        "target_broadening_allowed": False,
        "mutation_authorized": False,
        "secrets_included": False,
    }


def _root_attest_installer_argv(
    *,
    uid: int,
    plan: dict[str, object],
    request_evidence: dict[str, object],
    root_attestation_path: Path,
) -> list[str]:
    producer = dict(plan["producer"])
    applier = dict(plan["root_applier"])
    request_path = str(request_evidence["path"])
    request_size = str(request_evidence["size_bytes"])
    request_sha = str(request_evidence["sha256"])
    return [
        SUDO_BINARY,
        "--",
        PYTHON_EXECUTABLE,
        "-I",
        "-c",
        ROOT_INSTALLER_CODE,
        str(uid),
        str(applier["path"]),
        str(applier["size_bytes"]),
        str(applier["sha256"]),
        str(producer["path"]),
        str(producer["size_bytes"]),
        str(producer["sha256"]),
        request_path,
        request_size,
        request_sha,
        request_path,
        request_size,
        request_sha,
        str(root_attestation_path),
        ROOT_INSTALLER_SHA256,
    ]


def prepare_root_attestation(
    *,
    plan_path: Path,
    request_path: Path,
    root_attestation_path: Path,
) -> dict[str, object]:
    uid, _home = _operator_identity()
    if os.geteuid() != uid:
        raise RuntimeError("manfred_capacity_root_attest_prepare_requires_operator")
    plan, plan_file_sha256 = _read_private_json(plan_path, expected_owner=uid)
    _validate_plan(plan, producer_sha256=_source_sha256())
    if plan.get("eligible_capacity_sufficient") is not True:
        raise RuntimeError("manfred_capacity_plan_insufficient")
    request_path, _parent = _trusted_parent(request_path, expected_owner=uid)
    root_attestation_path = _validate_root_receipt_destination(
        root_attestation_path, operator_uid=uid
    )
    request = _root_attest_request_payload(
        plan=plan,
        request_path=request_path,
        root_attestation_path=root_attestation_path,
    )
    request_sha = _atomic_new_json(request_path, request, owner=uid)
    request_evidence = _private_source_evidence(
        request_path,
        expected_uid=uid,
        expected_sha256=request_sha,
    )
    return {
        "schema": ROOT_ATTEST_REQUEST_SCHEMA,
        "status": "root_attestation_required",
        "plan_path": str(plan_path.resolve(strict=True)),
        "plan_file_sha256": plan_file_sha256,
        "plan_sha256": plan["plan_sha256"],
        "request_path": str(request_path.resolve(strict=True)),
        "request_sha256": request_sha,
        "root_attestation_path": str(root_attestation_path),
        "root_attest_argv": _root_attest_installer_argv(
            uid=uid,
            plan=plan,
            request_evidence=request_evidence,
            root_attestation_path=root_attestation_path,
        ),
        "mutation_performed": False,
        "secrets_included": False,
    }


def _validated_root_attestation(
    *,
    path: Path,
    plan: dict[str, object],
    operator_uid: int,
) -> tuple[dict[str, object], str]:
    receipt, digest = _read_root_receipt(path, operator_uid=operator_uid)
    action_ids = [
        str(dict(row).get("action_id") or "")
        for row in list(plan.get("root_candidates") or [])
    ]
    eligible_ids = receipt.get("eligible_root_action_ids")
    authorized_ids = receipt.get("authorized_root_action_ids")
    rows_by_id = {
        str(dict(row).get("action_id") or ""): dict(row)
        for row in list(plan.get("root_candidates") or [])
        if isinstance(row, dict)
    }
    if (
        receipt.get("schema") != ROOT_ATTESTATION_SCHEMA
        or receipt.get("status") != "root_candidates_sufficient"
        or receipt.get("operator_uid") != operator_uid
        or receipt.get("plan_sha256") != plan.get("plan_sha256")
        or receipt.get("producer_sha256") != plan.get("producer_sha256")
        or receipt.get("root_applier_sha256")
        != dict(plan.get("root_applier") or {}).get("sha256")
        or receipt.get("root_installer") != plan.get("root_installer")
        or receipt.get("root_installer_sha256") != ROOT_INSTALLER_SHA256
        or receipt.get("root_candidate_set_sha256")
        != _root_candidate_set_sha256(plan)
        or receipt.get("root_candidate_count") != len(action_ids)
        or not isinstance(eligible_ids, list)
        or not isinstance(authorized_ids, list)
        or any(type(value) is not str for value in eligible_ids + authorized_ids)
        or len(set(eligible_ids)) != len(eligible_ids)
        or len(set(authorized_ids)) != len(authorized_ids)
        or any(value not in action_ids for value in eligible_ids)
        or authorized_ids != eligible_ids[: len(authorized_ids)]
        or type(receipt.get("eligible_root_reclaim_floor_bytes")) is not int
        or int(receipt["eligible_root_reclaim_floor_bytes"]) < 0
        or type(receipt.get("authorized_root_reclaim_floor_bytes")) is not int
        or int(receipt["authorized_root_reclaim_floor_bytes"]) < 0
        or int(receipt["eligible_root_reclaim_floor_bytes"])
        != sum(
            int(rows_by_id[value]["root_reclaim_floor_bytes"])
            for value in eligible_ids
        )
        or int(receipt["authorized_root_reclaim_floor_bytes"])
        != sum(
            int(rows_by_id[value]["root_reclaim_floor_bytes"])
            for value in authorized_ids
        )
        or receipt.get("guaranteed_user_reclaim_floor_bytes") != 0
        or receipt.get("root_authorization_basis")
        != "all_finite_eligible_candidates"
        or (
            type(receipt.get("root_free_bytes_at_attestation")) is int
            and int(receipt["root_free_bytes_at_attestation"])
            < TARGET_ROOT_FREE_BYTES
            and authorized_ids != eligible_ids
        )
        or type(receipt.get("root_free_bytes_at_attestation")) is not int
        or int(receipt["root_free_bytes_at_attestation"]) < 0
        or receipt.get("target_root_free_bytes") != TARGET_ROOT_FREE_BYTES
        or int(receipt["root_free_bytes_at_attestation"])
        + int(plan["user_eligible_reclaim_floor_bytes"])
        + int(receipt["authorized_root_reclaim_floor_bytes"])
        < TARGET_ROOT_FREE_BYTES
        or receipt.get("global_preflight_complete") is not True
        or receipt.get("two_sample_stable") is not True
        or receipt.get("all_process_fields_readable") is not True
        or receipt.get("all_host_mounts_inventoried") is not True
        or receipt.get("all_docker_mounts_inventoried") is not True
        or receipt.get("mutation_performed") is not False
        or receipt.get("target_broadened") is not False
        or receipt.get("secrets_included") is not False
    ):
        raise RuntimeError("manfred_capacity_root_attestation_invalid")
    return receipt, digest


def _intent_payload(
    plan: dict[str, object],
    *,
    root_attestation_path: Path,
    root_attestation: dict[str, object],
    root_attestation_sha256: str,
) -> dict[str, object]:
    _validate_plan(plan, producer_sha256=_source_sha256())
    return {
        "schema": INTENT_SCHEMA,
        "created_at": _utc_now(),
        "producer_sha256": plan["producer_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "operator_uid": plan["operator_uid"],
        "target_root_free_bytes": plan["target_root_free_bytes"],
        "plan": plan,
        "root_attestation_path": str(root_attestation_path.resolve(strict=True)),
        "root_attestation_sha256": root_attestation_sha256,
        "root_attestation": root_attestation,
        "root_attestation_required_before_user_mutation": True,
        "mutation_authority": "exact_plan_only",
        "resume_semantics": "absent_exact_target_is_authorized_postcondition",
        "target_broadening_allowed": False,
        "secrets_included": False,
    }


def seal_intent(
    *,
    plan_path: Path,
    root_attestation_path: Path,
    intent_path: Path,
) -> dict[str, object]:
    uid, _home = _operator_identity()
    if os.geteuid() != uid:
        raise RuntimeError("manfred_capacity_seal_requires_operator")
    plan, plan_file_sha256 = _read_private_json(plan_path, expected_owner=uid)
    _validate_plan(plan, producer_sha256=_source_sha256())
    root_attestation, root_attestation_sha256 = _validated_root_attestation(
        path=root_attestation_path,
        plan=plan,
        operator_uid=uid,
    )
    intent = _intent_payload(
        plan,
        root_attestation_path=root_attestation_path,
        root_attestation=root_attestation,
        root_attestation_sha256=root_attestation_sha256,
    )
    intent_sha256 = _atomic_new_json(intent_path, intent, owner=uid)
    return {
        "schema": INTENT_SCHEMA,
        "status": "sealed_for_separate_apply",
        "plan_path": str(plan_path.resolve(strict=True)),
        "plan_file_sha256": plan_file_sha256,
        "plan_sha256": plan["plan_sha256"],
        "root_attestation_path": str(root_attestation_path.resolve(strict=True)),
        "root_attestation_sha256": root_attestation_sha256,
        "intent_path": str(intent_path.resolve(strict=True)),
        "intent_sha256": intent_sha256,
        "mutation_performed": False,
        "review_required_before_apply": True,
        "secrets_included": False,
    }


def _load_intent(path: Path, *, uid: int) -> tuple[dict[str, object], str, dict[str, object]]:
    intent, digest = _read_private_json(path, expected_owner=uid)
    plan = intent.get("plan")
    root_attestation = intent.get("root_attestation")
    if (
        intent.get("schema") != INTENT_SCHEMA
        or intent.get("producer_sha256") != _source_sha256()
        or not isinstance(plan, dict)
        or intent.get("plan_sha256") != plan.get("plan_sha256")
        or intent.get("target_broadening_allowed") is not False
        or intent.get("root_attestation_required_before_user_mutation") is not True
        or not isinstance(root_attestation, dict)
    ):
        raise RuntimeError("manfred_capacity_intent_invalid")
    _validate_plan(dict(plan), producer_sha256=_source_sha256())
    root_attestation_path = Path(str(intent.get("root_attestation_path") or ""))
    observed_attestation, observed_sha = _validated_root_attestation(
        path=root_attestation_path,
        plan=dict(plan),
        operator_uid=uid,
    )
    if (
        observed_attestation != root_attestation
        or observed_sha != intent.get("root_attestation_sha256")
    ):
        raise RuntimeError("manfred_capacity_root_attestation_changed")
    return intent, digest, dict(plan)


def _tree_matches(expected: dict[str, object], observed: TreeEvidence) -> bool:
    return observed.as_dict() == expected


def _vscode_journal_entries(path: Path, *, uid: int) -> list[dict[str, object]]:
    root = path.absolute()
    root_device = _assert_mount_confinement(root)
    entries: list[dict[str, object]] = []
    file_count = 0
    entry_count = 1
    apparent_bytes = 0
    stack = [(root, Path("."))]
    while stack:
        current, relative = stack.pop()
        status = os.lstat(current)
        if (
            not stat.S_ISDIR(status.st_mode)
            or status.st_uid != uid
            or status.st_dev != root_device
        ):
            raise RuntimeError("manfred_capacity_vscode_tree_changed")
        entries.append(
            {
                "path": relative.as_posix(),
                "kind": "directory",
                "device": status.st_dev,
                "inode": status.st_ino,
                "mode": stat.S_IMODE(status.st_mode),
                "uid": status.st_uid,
                "gid": status.st_gid,
            }
        )
        children = _bounded_scandir(
            current,
            maximum=MAX_TREE_ENTRIES - entry_count,
            error="manfred_capacity_vscode_tree_changed",
        )
        for child in reversed(children):
            child_path = current / child.name
            child_relative = relative / child.name
            metadata = os.lstat(child_path)
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise RuntimeError("manfred_capacity_vscode_tree_changed")
            if stat.S_ISDIR(metadata.st_mode):
                if metadata.st_dev != root_device:
                    raise RuntimeError("manfred_capacity_vscode_tree_changed")
                stack.append((child_path, child_relative))
                continue
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != uid
                or metadata.st_nlink != 1
                or metadata.st_dev != root_device
                or metadata.st_size < 0
                or metadata.st_size > MAX_TREE_BYTES - apparent_bytes
            ):
                raise RuntimeError("manfred_capacity_vscode_tree_changed")
            descriptor = os.open(
                child_path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                opened = os.fstat(descriptor)
                identity = (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_mode,
                    opened.st_uid,
                    opened.st_gid,
                    opened.st_nlink,
                    opened.st_size,
                    opened.st_mtime_ns,
                    opened.st_ctime_ns,
                )
                if identity != (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_uid,
                    metadata.st_gid,
                    metadata.st_nlink,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                ):
                    raise RuntimeError("manfred_capacity_vscode_tree_changed")
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if size > metadata.st_size:
                        raise RuntimeError("manfred_capacity_vscode_tree_changed")
                after = os.fstat(descriptor)
                if identity != (
                    after.st_dev,
                    after.st_ino,
                    after.st_mode,
                    after.st_uid,
                    after.st_gid,
                    after.st_nlink,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ) or size != opened.st_size:
                    raise RuntimeError("manfred_capacity_vscode_tree_changed")
            finally:
                os.close(descriptor)
            file_count += 1
            apparent_bytes += size
            if file_count > MAX_TREE_FILES:
                raise RuntimeError("manfred_capacity_vscode_tree_changed")
            entries.append(
                {
                    "path": child_relative.as_posix(),
                    "kind": "file",
                    "device": metadata.st_dev,
                    "inode": metadata.st_ino,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "uid": metadata.st_uid,
                    "gid": metadata.st_gid,
                    "nlink": metadata.st_nlink,
                    "size_bytes": size,
                    "sha256": digest.hexdigest(),
                }
            )
    entries.sort(key=lambda row: str(row["path"]))
    _assert_mount_confinement(root, expected_device=root_device)
    return entries


def _vscode_remaining_entries_valid(
    expected: list[dict[str, object]], observed: list[dict[str, object]]
) -> bool:
    if (
        not expected
        or len({str(row.get("path") or "") for row in expected}) != len(expected)
        or len({str(row.get("path") or "") for row in observed}) != len(observed)
    ):
        return False
    expected_by_path = {str(row["path"]): row for row in expected}
    return all(expected_by_path.get(str(row.get("path") or "")) == row for row in observed)


def _vscode_journal_payload_valid(
    journal: dict[str, object],
    *,
    path: Path,
    quarantine: Path,
    expected: dict[str, object],
    journal_contract: dict[str, object],
    uid: int,
) -> bool:
    rows = journal.get("entries")
    return (
        journal.get("schema") == VSCODE_JOURNAL_SCHEMA
        and journal.get("target_path") == str(path)
        and journal.get("quarantine_path") == str(quarantine)
        and journal.get("manifest_sha256") == expected.get("manifest_sha256")
        and journal.get("operator_uid") == uid
        and journal.get("target_broadened") is False
        and isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        and journal.get("entry_count") == len(rows)
        and 1 <= len(rows) <= MAX_TREE_FILES + 1
        and journal_contract.get("journal_entry_count") == len(rows)
        and journal_contract.get("journal_entries_sha256")
        == _sha256(_json_bytes(rows))
        and journal_contract.get("journal_payload_bytes")
        == len(_json_bytes(journal))
    )


def _unlink_vscode_journaled(
    path: Path,
    *,
    confinement_root: Path,
    expected_device: int,
    relative: Path,
    expected_by_path: dict[str, dict[str, object]],
    uid: int,
    remaining_entries: list[int] | None = None,
    remaining_bytes: list[int] | None = None,
) -> None:
    if remaining_entries is None:
        remaining_entries = [len(expected_by_path)]
    if remaining_bytes is None:
        remaining_bytes = [
            sum(
                int(row.get("size_bytes") or 0)
                for row in expected_by_path.values()
                if row.get("kind") == "file"
            )
        ]
    _assert_mount_confinement(
        confinement_root,
        expected_device=expected_device,
    )
    relative_text = relative.as_posix()
    expected = expected_by_path.get(relative_text)
    status = os.lstat(path)
    observed_directory = {
        "path": relative_text,
        "kind": "directory",
        "device": status.st_dev,
        "inode": status.st_ino,
        "mode": stat.S_IMODE(status.st_mode),
        "uid": status.st_uid,
        "gid": status.st_gid,
    }
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != uid
        or status.st_dev != expected_device
        or expected != observed_directory
    ):
        raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
    children = _bounded_scandir(
        path,
        maximum=remaining_entries[0],
        error="manfred_capacity_vscode_remaining_set_invalid",
    )
    for child in children:
        remaining_entries[0] -= 1
        if remaining_entries[0] < 0:
            raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
        child_path = Path(child.path)
        child_relative = relative / child.name
        metadata = os.lstat(child_path)
        if stat.S_ISDIR(metadata.st_mode):
            if metadata.st_dev != expected_device:
                raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
            _unlink_vscode_journaled(
                child_path,
                confinement_root=confinement_root,
                expected_device=expected_device,
                relative=child_relative,
                expected_by_path=expected_by_path,
                uid=uid,
                remaining_entries=remaining_entries,
                remaining_bytes=remaining_bytes,
            )
            continue
        descriptor = os.open(
            child_path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_size < 0
                or opened.st_size > MAX_TREE_BYTES
                or opened.st_size > remaining_bytes[0]
            ):
                raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                if size > opened.st_size:
                    raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        observed_file = {
            "path": child_relative.as_posix(),
            "kind": "file",
            "device": opened.st_dev,
            "inode": opened.st_ino,
            "mode": stat.S_IMODE(opened.st_mode),
            "uid": opened.st_uid,
            "gid": opened.st_gid,
            "nlink": opened.st_nlink,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != uid
            or opened.st_nlink != 1
            or opened.st_dev != expected_device
            or (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_uid,
                opened.st_gid,
                opened.st_nlink,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or size != opened.st_size
            or expected_by_path.get(child_relative.as_posix()) != observed_file
        ):
            raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
        remaining_bytes[0] -= size
        current_child = os.lstat(child_path)
        if (current_child.st_dev, current_child.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
        _assert_mount_confinement(
            confinement_root,
            expected_device=expected_device,
        )
        os.unlink(child_path)
    current = os.lstat(path)
    if (current.st_dev, current.st_ino) != (status.st_dev, status.st_ino):
        raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
    _assert_mount_confinement(
        confinement_root,
        expected_device=expected_device,
    )
    os.rmdir(path)


def _secure_remove_tree(
    path: Path,
    *,
    expected: dict[str, object],
    journal_contract: dict[str, object],
    uid: int,
) -> str:
    expected_device = expected.get("device")
    if type(expected_device) is not int or expected_device < 1:
        raise RuntimeError("manfred_capacity_vscode_tree_changed")
    parent = path.parent
    parent_status = parent.stat()
    trusted_parent_status = parent.parent.stat()
    if (
        parent_status.st_uid != uid
        or trusted_parent_status.st_uid != uid
        or stat.S_IMODE(trusted_parent_status.st_mode) & 0o022
        or parent_status.st_dev != expected_device
        or trusted_parent_status.st_dev != expected_device
    ):
        raise RuntimeError("manfred_capacity_vscode_parent_invalid")
    quarantine = parent / f".ea-capacity-{expected['manifest_sha256'][:16]}.retired"
    recovery_token = _sha256(
        f"{path}\0{expected['manifest_sha256']}".encode("utf-8")
    )[:24]
    journal_path = parent.parent / (
        f".ea-capacity-vscode-{recovery_token}.journal.v3.json"
    )
    complete_path = parent.parent / (
        f".ea-capacity-vscode-{recovery_token}.complete.v3.json"
    )
    source_exists = os.path.lexists(path)
    quarantine_exists = os.path.lexists(quarantine)
    _assert_mount_confinement(
        path,
        expected_device=expected_device,
        allow_missing=not source_exists,
    )
    _assert_mount_confinement(
        quarantine,
        expected_device=expected_device,
        allow_missing=not quarantine_exists,
    )
    _assert_mount_confinement(
        journal_path,
        expected_device=expected_device,
        allow_missing=True,
    )
    _assert_mount_confinement(
        complete_path,
        expected_device=expected_device,
        allow_missing=True,
    )
    journal_loaded = (
        _read_private_json(journal_path, expected_owner=uid)
        if os.path.lexists(journal_path)
        else None
    )
    complete_loaded = (
        _read_private_json(complete_path, expected_owner=uid)
        if os.path.lexists(complete_path)
        else None
    )
    if source_exists and quarantine_exists:
        raise RuntimeError("manfred_capacity_vscode_recovery_ambiguous")
    if complete_loaded is not None:
        if journal_loaded is None or source_exists or quarantine_exists:
            raise RuntimeError("manfred_capacity_vscode_journal_invalid")
        journal, journal_sha = journal_loaded
        complete, _complete_sha = complete_loaded
        if (
            not _vscode_journal_payload_valid(
                journal,
                path=path,
                quarantine=quarantine,
                expected=expected,
                journal_contract=journal_contract,
                uid=uid,
            )
            or complete.get("schema") != VSCODE_COMPLETE_SCHEMA
            or complete.get("journal_sha256") != journal_sha
            or complete.get("target_path") != str(path)
            or complete.get("status") != "tree_removed"
        ):
            raise RuntimeError("manfred_capacity_vscode_journal_invalid")
        return "already_removed_verified"
    if not source_exists and not quarantine_exists:
        if journal_loaded is None:
            return "already_absent"
        journal, journal_sha = journal_loaded
        if not _vscode_journal_payload_valid(
            journal,
            path=path,
            quarantine=quarantine,
            expected=expected,
            journal_contract=journal_contract,
            uid=uid,
        ):
            raise RuntimeError("manfred_capacity_vscode_journal_invalid")
        complete = {
            "schema": VSCODE_COMPLETE_SCHEMA,
            "created_at": _utc_now(),
            "journal_sha256": journal_sha,
            "target_path": str(path),
            "status": "tree_removed",
            "target_broadened": False,
        }
        _assert_mount_confinement(
            complete_path,
            expected_device=expected_device,
            allow_missing=True,
        )
        _atomic_new_json(complete_path, complete, owner=uid)
        return "recovered_removed"

    started_from_source = source_exists
    if source_exists:
        observed = _tree_evidence(
            path, allowed_owners={uid}, hash_content=True, missing_ok=False
        )
        if not _tree_matches(expected, observed):
            raise RuntimeError("manfred_capacity_vscode_tree_changed")
        entries = _vscode_journal_entries(path, uid=uid)
        repeated = _tree_evidence(
            path, allowed_owners={uid}, hash_content=True, missing_ok=False
        )
        if not _tree_matches(expected, repeated):
            raise RuntimeError("manfred_capacity_vscode_tree_changed")
        if journal_loaded is None:
            journal = {
                "schema": VSCODE_JOURNAL_SCHEMA,
                "created_at": _utc_now(),
                "operator_uid": uid,
                "target_path": str(path),
                "quarantine_path": str(quarantine),
                "manifest_sha256": expected["manifest_sha256"],
                "entries": entries,
                "entry_count": len(entries),
                "target_broadened": False,
            }
            if not _vscode_journal_payload_valid(
                journal,
                path=path,
                quarantine=quarantine,
                expected=expected,
                journal_contract=journal_contract,
                uid=uid,
            ):
                raise RuntimeError("manfred_capacity_vscode_journal_contract_changed")
            _assert_mount_confinement(
                journal_path,
                expected_device=expected_device,
                allow_missing=True,
            )
            journal_sha = _atomic_new_json(journal_path, journal, owner=uid)
        else:
            journal, journal_sha = journal_loaded
            if (
                not _vscode_journal_payload_valid(
                    journal,
                    path=path,
                    quarantine=quarantine,
                    expected=expected,
                    journal_contract=journal_contract,
                    uid=uid,
                )
                or journal.get("entries") != entries
            ):
                raise RuntimeError("manfred_capacity_vscode_journal_invalid")
        if _process_references(path, uid=uid):
            raise RuntimeError("manfred_capacity_vscode_server_active")
        _assert_vscode_rename_confinement(
            path,
            quarantine,
            expected_device=expected_device,
            journal_path=journal_path,
            complete_path=complete_path,
        )
        os.rename(path, quarantine)
        directory_descriptor = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    else:
        if journal_loaded is None:
            raise RuntimeError("manfred_capacity_vscode_journal_missing")
        journal, journal_sha = journal_loaded
        if not _vscode_journal_payload_valid(
            journal,
            path=path,
            quarantine=quarantine,
            expected=expected,
            journal_contract=journal_contract,
            uid=uid,
        ):
            raise RuntimeError("manfred_capacity_vscode_journal_invalid")

    expected_entries = [dict(row) for row in list(journal["entries"])]
    remaining_entries = _vscode_journal_entries(quarantine, uid=uid)
    if not _vscode_remaining_entries_valid(expected_entries, remaining_entries):
        raise RuntimeError("manfred_capacity_vscode_remaining_set_invalid")
    if _process_references(quarantine, uid=uid):
        raise RuntimeError("manfred_capacity_vscode_server_active")
    _assert_mount_confinement(quarantine, expected_device=expected_device)
    _unlink_vscode_journaled(
        quarantine,
        confinement_root=quarantine,
        expected_device=expected_device,
        relative=Path("."),
        expected_by_path={str(row["path"]): row for row in expected_entries},
        uid=uid,
    )
    directory_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    complete = {
        "schema": VSCODE_COMPLETE_SCHEMA,
        "created_at": _utc_now(),
        "journal_sha256": journal_sha,
        "target_path": str(path),
        "status": "tree_removed",
        "target_broadened": False,
    }
    _assert_mount_confinement(
        complete_path,
        expected_device=expected_device,
        allow_missing=True,
    )
    _atomic_new_json(complete_path, complete, owner=uid)
    return "removed" if started_from_source else "recovered_removed"


def _post_cache_tree(cache: dict[str, object], *, uid: int) -> TreeEvidence:
    expected = dict(cache["tree"])
    return _tree_evidence(
        Path(str(expected["path"])),
        allowed_owners={uid},
        hash_content=False,
        missing_ok=True,
    )


def _builder_identity(evidence: dict[str, object]) -> dict[str, object]:
    keys = (
        "name",
        "driver",
        "node",
        "endpoint",
        "container_name",
        "container_id",
        "container_image_id",
        "volume_name",
    )
    return {key: evidence.get(key) for key in keys}


def _apply_builder(plan: dict[str, object], *, home: Path) -> dict[str, object]:
    expected = dict(plan["builder"])
    with _exclusive_build_lock():
        before = _builder_inspection(home)
        if _builder_identity(before) != _builder_identity(expected):
            raise RuntimeError("manfred_capacity_builder_changed")
        if before["record_count"] == 0:
            return {
                "status": "already_empty",
                "before": before,
                "after": before,
                "mutation_command_count": 0,
            }
        if before != expected:
            raise RuntimeError("manfred_capacity_builder_changed")
        _bounded_run(BUILD_CACHE_PRUNE_ARGV, home=home, mutation=True, timeout=300)
        after = _builder_inspection(home)
        if (
            after["name"] != expected["name"]
            or after["driver"] != expected["driver"]
            or after["node"] != expected["node"]
            or after["endpoint"] != expected["endpoint"]
            or after["container_id"] != expected["container_id"]
            or after["container_image_id"] != expected["container_image_id"]
            or after["volume_name"] != expected["volume_name"]
            or after["record_count"] != 0
            or after["reclaimable_floor_bytes"] != 0
        ):
            raise RuntimeError("manfred_capacity_builder_prune_incomplete")
    return {
        "status": "pruned",
        "before": before,
        "after": after,
        "mutation_command_count": 1,
        "global_cache_pruned": False,
    }


def _apply_caches(plan: dict[str, object], *, home: Path, uid: int) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for raw_cache in list(plan["caches"]):
        if not isinstance(raw_cache, dict):
            raise RuntimeError("manfred_capacity_cache_plan_invalid")
        cache = dict(raw_cache)
        if cache.get("eligible") is not True:
            results.append(_skipped_cache(cache))
            continue
        expected = dict(cache["tree"])
        path = Path(str(expected["path"]))
        before = _tree_evidence(
            path, allowed_owners={uid}, hash_content=False, missing_ok=True
        )
        if before.exists and not _tree_matches(expected, before):
            if bool(expected.get("exists")) and before.allocated_bytes < int(
                expected["allocated_bytes"]
            ):
                results.append(
                    {
                        "name": cache["name"],
                        "status": "recovered_cleared_postcondition",
                        "before_allocated_bytes": int(expected["allocated_bytes"]),
                        "after_allocated_bytes": before.allocated_bytes,
                        "mutation_command_count": 0,
                    }
                )
                continue
            raise RuntimeError("manfred_capacity_cache_changed")
        if not before.exists or before.allocated_bytes == 0:
            results.append(
                {
                    "name": cache["name"],
                    "status": "already_empty",
                    "before_allocated_bytes": before.allocated_bytes,
                    "after_allocated_bytes": before.allocated_bytes,
                    "mutation_command_count": 0,
                }
            )
            continue
        tokens = {
            "nuget_http": {"nuget", "restore", "msbuild"},
            "nuget_global_packages": {"nuget", "restore", "msbuild"},
            "npm_content_cache": {"npx", "cache", "install", "ci", "add", "update"},
            "pip_cache": {
                "pip",
                "pip3",
                "pip3.12",
            },
        }.get(str(cache["name"]))
        if (
            tokens is None
            or _active_tool_processes(uid, tokens)
            or _process_references(path, uid=uid)
        ):
            raise RuntimeError("manfred_capacity_cache_tool_active")
        argv = tuple(str(value) for value in list(cache["clear_argv"]))
        expected_argv = dict(CACHE_MUTATION_COMMANDS).get(str(cache["name"]))
        if argv != expected_argv or not _mutation_command_allowed(argv):
            raise RuntimeError("manfred_capacity_cache_command_invalid")
        current_paths = _official_cache_paths(home=home)
        if current_paths.get(str(cache["name"])) != path:
            raise RuntimeError("manfred_capacity_cache_path_changed")
        _assert_mount_confinement(path, expected_device=before.device)
        _bounded_run(argv, home=home, mutation=True, timeout=300)
        after = _post_cache_tree(cache, uid=uid)
        if after.allocated_bytes >= before.allocated_bytes:
            raise RuntimeError("manfred_capacity_cache_clear_incomplete")
        results.append(
            {
                "name": cache["name"],
                "status": "cleared",
                "before_allocated_bytes": before.allocated_bytes,
                "after_allocated_bytes": after.allocated_bytes,
                "mutation_command_count": 1,
            }
        )
    return results


def _apply_vscode(plan: dict[str, object], *, uid: int) -> dict[str, object]:
    vscode = dict(plan["vscode"])
    if vscode.get("eligible") is not True:
        return _skipped_vscode(plan)
    expected = dict(vscode["inactive_tree"])
    path = Path(str(expected["path"]))
    status = _secure_remove_tree(
        path,
        expected=expected,
        journal_contract=vscode,
        uid=uid,
    )
    if os.path.lexists(path):
        raise RuntimeError("manfred_capacity_vscode_remove_incomplete")
    return {
        "status": status,
        "path": str(path),
        "allocated_bytes_reclaimed": int(expected["allocated_bytes"]),
    }


def _current_registry_sha256(path: Path) -> str:
    loaded = _read_registry_json(path)
    if loaded is None:
        raise RuntimeError("manfred_capacity_candidate_registry_missing")
    _validated_registry(loaded[0])
    return loaded[1]


def _image_exists(image_id: str, *, home: Path) -> bool:
    if IMAGE_ID.fullmatch(image_id) is None:
        raise RuntimeError("manfred_capacity_candidate_image_invalid")
    lines = _docker_filtered_lines(
        ["docker", "image", "ls", "--no-trunc", "--quiet", image_id],
        home=home,
    )
    if not lines:
        return False
    if sorted(set(lines)) != [image_id]:
        raise RuntimeError("manfred_capacity_candidate_image_invalid")
    return True


def _apply_candidate(plan: dict[str, object], *, home: Path) -> dict[str, object]:
    candidate = dict(plan["candidate"])
    registry_path = Path(str(candidate["registry_path"]))
    image_id = str(candidate["image_id"])
    with hold_candidate_fleet_lock() as lock:
        if lock is None:  # pragma: no cover - non-skip acquisition
            raise RuntimeError("manfred_capacity_candidate_fleet_lock_held")
        current_registry = _current_registry_sha256(registry_path)
        if current_registry not in {
            candidate["registry_sha256_before"],
            candidate["registry_sha256_after"],
        }:
            raise RuntimeError("manfred_capacity_candidate_registry_changed")
        _require_project_absent(str(candidate["project"]), home=home)
        image_present = _image_exists(image_id, home=home)
        image_removed = False
        if image_present:
            refreshed = _candidate_evidence(
                home=home,
                registry_path=registry_path,
                protected_image_ids=set(str(value) for value in plan["protected_image_ids"]),
            )
            if refreshed != candidate:
                raise RuntimeError("manfred_capacity_candidate_changed")
            _bounded_run(
                ["docker", "image", "rm", image_id],
                home=home,
                mutation=True,
                timeout=300,
            )
            if _image_exists(image_id, home=home):
                raise RuntimeError("manfred_capacity_candidate_image_remove_incomplete")
            image_removed = True
        if current_registry == candidate["registry_sha256_before"]:
            compact = compact_candidate_registry(set(), registry_path=registry_path)
            if compact.get("before_count") != 1 or compact.get("after_count") != 0:
                raise RuntimeError("manfred_capacity_candidate_registry_compaction_invalid")
        if _current_registry_sha256(registry_path) != candidate["registry_sha256_after"]:
            raise RuntimeError("manfred_capacity_candidate_registry_compaction_invalid")
    return {
        "status": "retired",
        "image_removed": image_removed,
        "image_absent": True,
        "registry_compacted": True,
        "historical_receipt_preserved": True,
        "lock": dict(lock),
    }


def _root_handoff_payload(
    *,
    intent_path: Path,
    intent_sha256: str,
    user_receipt_path: Path,
    root_handoff_path: Path,
    root_receipt_path: Path,
    plan: dict[str, object],
    root_attestation: dict[str, object],
    root_attestation_path: Path,
    root_attestation_sha256: str,
) -> dict[str, object]:
    projections = list(plan["projections"])
    producer = dict(plan["producer"])
    root_applier = dict(plan["root_applier"])
    root_installer = dict(plan["root_installer"])
    return {
        "schema": ROOT_HANDOFF_SCHEMA,
        "created_at": _utc_now(),
        "producer_sha256": plan["producer_sha256"],
        "producer_path": plan["producer_path"],
        "producer_source": producer,
        "root_applier_path": root_applier["path"],
        "root_applier_sha256": root_applier["sha256"],
        "root_applier_source": root_applier,
        "root_applier_stdlib_only": True,
        "root_installer": root_installer,
        "root_installer_sha256": ROOT_INSTALLER_SHA256,
        "root_stage_contract": {
            "parent": "/root",
            "mode": 0o700,
            "applier_name": "applier.py",
            "applier_mode": 0o500,
            "controller_name": "controller.py",
            "controller_mode": 0o400,
            "handoff_name": "handoff.json",
            "handoff_mode": 0o400,
            "user_receipt_name": "user-receipt.json",
            "user_receipt_mode": 0o400,
        },
        "operator_uid": plan["operator_uid"],
        "operator_home": plan["operator_home"],
        "deploy_root": plan["deploy_root"],
        "intent_path": str(intent_path.resolve(strict=True)),
        "intent_sha256": intent_sha256,
        "handoff_source_path": str(root_handoff_path.absolute()),
        "user_receipt_path": str(user_receipt_path.absolute()),
        "root_receipt_path": str(root_receipt_path.absolute()),
        "plan_sha256": plan["plan_sha256"],
        "root_attestation_path": str(root_attestation_path.resolve(strict=True)),
        "root_attestation_sha256": root_attestation_sha256,
        "root_attestation": root_attestation,
        "root_candidate_set_sha256": _root_candidate_set_sha256(plan),
        "target_root_free_bytes": plan["target_root_free_bytes"],
        "projection_count": len(projections),
        "projections": projections,
        "root_candidate_count": len(list(plan["root_candidates"])),
        "root_candidates": list(plan["root_candidates"]),
        "authorized_root_action_ids": list(
            root_attestation["authorized_root_action_ids"]
        ),
        "delete_scope": "attested_finite_root_candidate_prefix_only",
        "candidate_roots_removed": False,
        "runtime_removed": False,
        "receipts_removed": False,
        "environment_files_removed": False,
        "target_broadening_allowed": False,
        "secrets_included": False,
    }


def _private_source_evidence(
    path: Path,
    *,
    expected_uid: int,
    expected_sha256: str,
) -> dict[str, object]:
    absolute = path.absolute()
    if absolute.resolve(strict=True) != absolute:
        raise RuntimeError("manfred_capacity_bootstrap_source_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if size > MAX_JSON_BYTES:
                raise RuntimeError("manfred_capacity_bootstrap_source_invalid")
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_uid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 1 <= size <= MAX_JSON_BYTES
            or digest.hexdigest() != expected_sha256
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            raise RuntimeError("manfred_capacity_bootstrap_source_invalid")
    finally:
        os.close(descriptor)
    return {
        "path": str(absolute),
        "size_bytes": size,
        "sha256": expected_sha256,
        "owner_uid": expected_uid,
        "mode": 0o600,
    }


def _root_installer_argv(
    *,
    uid: int,
    plan: dict[str, object],
    handoff: dict[str, object],
    handoff_evidence: dict[str, object],
    user_receipt_evidence: dict[str, object],
    root_receipt_path: Path,
) -> list[str]:
    producer = dict(plan["producer"])
    applier = dict(plan["root_applier"])
    if (
        dict(plan["root_installer"]) != _root_installer_evidence()
        or handoff.get("root_installer_sha256") != ROOT_INSTALLER_SHA256
        or handoff_evidence.get("path") != handoff.get("handoff_source_path")
        or user_receipt_evidence.get("path") != handoff.get("user_receipt_path")
    ):
        raise RuntimeError("manfred_capacity_bootstrap_evidence_invalid")
    return [
        SUDO_BINARY,
        "--",
        PYTHON_EXECUTABLE,
        "-I",
        "-c",
        ROOT_INSTALLER_CODE,
        str(uid),
        str(applier["path"]),
        str(applier["size_bytes"]),
        str(applier["sha256"]),
        str(producer["path"]),
        str(producer["size_bytes"]),
        str(producer["sha256"]),
        str(handoff_evidence["path"]),
        str(handoff_evidence["size_bytes"]),
        str(handoff_evidence["sha256"]),
        str(user_receipt_evidence["path"]),
        str(user_receipt_evidence["size_bytes"]),
        str(user_receipt_evidence["sha256"]),
        str(root_receipt_path),
        ROOT_INSTALLER_SHA256,
    ]


def _preserved_builder(plan: dict[str, object]) -> dict[str, object]:
    return {
        "status": "preserved_capacity_ready",
        "planned_identity": _builder_identity(dict(plan["builder"])),
        "mutation_command_count": 0,
        "global_cache_pruned": False,
    }


def _preserved_cache(raw: dict[str, object]) -> dict[str, object]:
    tree = dict(raw.get("tree") or {})
    return {
        "name": str(raw.get("name") or ""),
        "status": "preserved_capacity_ready",
        "planned_allocated_bytes": int(tree.get("allocated_bytes") or 0),
        "mutation_command_count": 0,
    }


def _skipped_cache(raw: dict[str, object]) -> dict[str, object]:
    tree = dict(raw.get("tree") or {})
    availability = str(raw.get("availability") or "")
    status = (
        "preserved_active_process"
        if availability == "active_process"
        else "preserved_process_inventory_unavailable"
    )
    return {
        "name": str(raw.get("name") or ""),
        "status": status,
        "planned_allocated_bytes": int(tree.get("allocated_bytes") or 0),
        "eligible_reclaim_floor_bytes": 0,
        "mutation_command_count": 0,
    }


def _preserved_vscode(plan: dict[str, object]) -> dict[str, object]:
    vscode = dict(plan["vscode"])
    tree = dict(vscode.get("inactive_tree") or {})
    return {
        "status": "preserved_capacity_ready",
        "path": str(tree["path"]) if tree else None,
        "planned_allocated_bytes": int(tree.get("allocated_bytes") or 0),
        "allocated_bytes_reclaimed": 0,
    }


def _skipped_vscode(plan: dict[str, object]) -> dict[str, object]:
    vscode = dict(plan["vscode"])
    return {
        "status": "preserved_process_inventory_unavailable",
        "path": None,
        "planned_allocated_bytes": 0,
        "allocated_bytes_reclaimed": 0,
        "mutation_command_count": 0,
        "availability": vscode.get("availability"),
    }


def _preserved_candidate(plan: dict[str, object]) -> dict[str, object]:
    candidate = dict(plan["candidate"])
    return {
        "status": "preserved_capacity_ready",
        "image_id": str(candidate["image_id"]),
        "image_removed": False,
        "registry_compacted": False,
        "historical_receipt_preserved": True,
        "mutation_command_count": 0,
    }


def _apply_user_actions(
    plan: dict[str, object], *, home: Path, uid: int
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
    dict[str, object],
    int,
    int,
    list[str],
    list[str],
]:
    target = int(plan["target_root_free_bytes"])
    if target != TARGET_ROOT_FREE_BYTES:
        raise RuntimeError("manfred_capacity_plan_target_invalid")
    current_free = _root_free_bytes()
    before_free = current_free
    capacity_latched = current_free >= target
    preserved: list[str] = []
    unavailable: list[str] = []

    def capacity_ready_before_mutation() -> bool:
        nonlocal capacity_latched, current_free
        if capacity_latched:
            return True
        current_free = _root_free_bytes()
        if current_free >= target:
            capacity_latched = True
        return capacity_latched

    if capacity_ready_before_mutation():
        builder = _preserved_builder(plan)
        preserved.append("builder")
    else:
        builder = _apply_builder(plan, home=home)
        current_free = _root_free_bytes()
        capacity_latched = current_free >= target

    caches: list[dict[str, object]] = []
    for raw in list(plan["caches"]):
        if not isinstance(raw, dict):
            raise RuntimeError("manfred_capacity_cache_plan_invalid")
        cache = dict(raw)
        if capacity_latched:
            caches.append(_preserved_cache(cache))
            preserved.append(f"cache:{cache.get('name')}")
            continue
        if cache.get("eligible") is not True:
            caches.append(_skipped_cache(cache))
            unavailable.append(f"cache:{cache.get('name')}")
            continue
        if capacity_ready_before_mutation():
            caches.append(_preserved_cache(cache))
            preserved.append(f"cache:{cache.get('name')}")
            continue
        applied = _apply_caches({"caches": [cache]}, home=home, uid=uid)
        if len(applied) != 1:
            raise RuntimeError("manfred_capacity_cache_result_invalid")
        caches.append(applied[0])
        current_free = _root_free_bytes()
        capacity_latched = current_free >= target

    if capacity_latched:
        vscode = _preserved_vscode(plan)
        preserved.append("vscode")
    elif dict(plan["vscode"]).get("eligible") is not True:
        vscode = _skipped_vscode(plan)
        unavailable.append("vscode")
    elif capacity_ready_before_mutation():
        vscode = _preserved_vscode(plan)
        preserved.append("vscode")
    else:
        vscode = _apply_vscode(plan, uid=uid)
        current_free = _root_free_bytes()
        capacity_latched = current_free >= target

    if capacity_ready_before_mutation():
        candidate = _preserved_candidate(plan)
        preserved.append("candidate")
    else:
        candidate = _apply_candidate(plan, home=home)
        current_free = _root_free_bytes()
        capacity_latched = current_free >= target

    if capacity_latched:
        final_free = _root_free_bytes()
        if final_free < target:
            raise RuntimeError("manfred_capacity_drift_after_ready")
        current_free = final_free

    return (
        builder,
        caches,
        vscode,
        candidate,
        before_free,
        current_free,
        preserved,
        unavailable,
    )


def _load_matching_handoff(
    path: Path,
    *,
    uid: int,
    expected: dict[str, object],
) -> tuple[dict[str, object], str]:
    observed, digest = _read_private_json(path, expected_owner=uid)
    comparison = dict(expected)
    comparison["created_at"] = observed.get("created_at")
    if observed != comparison:
        raise RuntimeError("manfred_capacity_root_handoff_changed")
    return observed, digest


def apply_user(
    *,
    intent_path: Path,
    user_receipt_path: Path,
    root_handoff_path: Path,
    root_receipt_path: Path,
) -> dict[str, object]:
    uid, home = _operator_identity()
    if os.geteuid() != uid:
        raise RuntimeError("manfred_capacity_user_apply_must_not_run_as_root")
    with _capacity_lock(uid):
        if not os.path.lexists(intent_path):
            raise RuntimeError("manfred_capacity_reviewed_intent_required")
        _intent, intent_sha256, plan = _load_intent(intent_path, uid=uid)
        root_attestation = dict(_intent["root_attestation"])
        root_attestation_path = Path(str(_intent["root_attestation_path"]))
        root_attestation_sha256 = str(_intent["root_attestation_sha256"])
        if not bool(plan.get("eligible_capacity_sufficient")):
            raise RuntimeError("manfred_capacity_plan_insufficient")
        if _root_applier_evidence(uid=uid) != plan.get("root_applier"):
            raise RuntimeError("manfred_capacity_root_applier_changed")
        if (
            _controller_evidence(uid=uid) != plan.get("producer")
            or plan.get("root_installer") != _root_installer_evidence()
            or _mutation_helper_evidence(uid=uid) != plan.get("mutation_helpers")
            or _pinned_toolchain_evidence() != plan.get("pinned_toolchain")
            or plan.get("docker_host") != LOCAL_DOCKER_HOST
            or plan.get("docker_context_inherited") is not False
        ):
            raise RuntimeError("manfred_capacity_toolchain_changed")
        user_receipt_path, _ = _trusted_parent(user_receipt_path, expected_owner=uid)
        root_handoff_path, _ = _trusted_parent(root_handoff_path, expected_owner=uid)
        if (
            len(
                {
                    str(intent_path.absolute()),
                    str(user_receipt_path),
                    str(root_handoff_path),
                    str(root_receipt_path),
                    str(root_attestation_path),
                }
            )
            != 5
        ):
            raise RuntimeError("manfred_capacity_output_exists_or_aliases")
        if os.path.lexists(user_receipt_path):
            receipt, receipt_sha256 = _read_private_json(
                user_receipt_path, expected_owner=uid
            )
            status = receipt.get("status")
            if (
                receipt.get("schema") != USER_RECEIPT_SCHEMA
                or receipt.get("operator_uid") != uid
                or receipt.get("intent_sha256") != intent_sha256
                or receipt.get("plan_sha256") != plan.get("plan_sha256")
                or receipt.get("producer_sha256") != plan.get("producer_sha256")
                or receipt.get("root_attestation_path")
                != str(root_attestation_path.resolve(strict=True))
                or receipt.get("root_attestation_sha256")
                != root_attestation_sha256
                or receipt.get("root_actions_performed") is not False
                or receipt.get("projection_deletion_performed") is not False
                or receipt.get("root_candidate_deletion_performed") is not False
                or receipt.get("target_broadened") is not False
            ):
                raise RuntimeError("manfred_capacity_user_receipt_changed")
            returned_root_apply_argv: list[str] = []
            if status == "root_handoff_required":
                root_receipt_path = _validate_root_receipt_destination(
                    root_receipt_path, operator_uid=uid
                )
                expected_handoff = _root_handoff_payload(
                    intent_path=intent_path,
                    intent_sha256=intent_sha256,
                    user_receipt_path=user_receipt_path,
                    root_handoff_path=root_handoff_path,
                    root_receipt_path=root_receipt_path,
                    plan=plan,
                    root_attestation=root_attestation,
                    root_attestation_path=root_attestation_path,
                    root_attestation_sha256=root_attestation_sha256,
                )
                handoff, handoff_sha256 = _load_matching_handoff(
                    root_handoff_path,
                    uid=uid,
                    expected=expected_handoff,
                )
                if (
                    receipt.get("root_handoff_required") is not True
                    or receipt.get("root_handoff_path") != str(root_handoff_path)
                    or receipt.get("root_handoff_sha256") != handoff_sha256
                    or receipt.get("root_receipt_path") != str(root_receipt_path)
                    or receipt.get("root_apply_argv") is not None
                    or receipt.get("root_apply_argv_persisted") is not False
                    or receipt.get("root_installer") != plan.get("root_installer")
                    or receipt.get("root_installer_sha256") != ROOT_INSTALLER_SHA256
                    or receipt.get("projection_deletion_authorized") is not True
                    or receipt.get("root_candidate_deletion_authorized") is not True
                ):
                    raise RuntimeError("manfred_capacity_user_receipt_changed")
                returned_root_apply_argv = _root_installer_argv(
                    uid=uid,
                    plan=plan,
                    handoff=handoff,
                    handoff_evidence=_private_source_evidence(
                        root_handoff_path,
                        expected_uid=uid,
                        expected_sha256=handoff_sha256,
                    ),
                    user_receipt_evidence=_private_source_evidence(
                        user_receipt_path,
                        expected_uid=uid,
                        expected_sha256=receipt_sha256,
                    ),
                    root_receipt_path=root_receipt_path,
                )
            elif status == "capacity_ready_no_root_actions":
                if (
                    receipt.get("root_handoff_required") is not False
                    or receipt.get("root_handoff_path") is not None
                    or receipt.get("root_handoff_sha256") is not None
                    or receipt.get("root_receipt_path") is not None
                    or receipt.get("root_apply_argv") != []
                    or receipt.get("root_apply_argv_persisted") is not True
                    or receipt.get("projection_deletion_authorized") is not False
                    or receipt.get("root_candidate_deletion_authorized") is not False
                    or _root_free_bytes() < int(plan["target_root_free_bytes"])
                ):
                    raise RuntimeError("manfred_capacity_user_receipt_changed")
            else:
                raise RuntimeError("manfred_capacity_user_receipt_changed")
            return {
                **receipt,
                "root_apply_argv": returned_root_apply_argv,
                "receipt_path": str(user_receipt_path),
                "receipt_sha256": receipt_sha256,
                "resumed": True,
            }
        (
            builder,
            caches,
            vscode,
            candidate,
            before_free,
            after_free,
            preserved_user_actions,
            unavailable_user_actions,
        ) = _apply_user_actions(plan, home=home, uid=uid)
        root_handoff_required = after_free < int(plan["target_root_free_bytes"])
        handoff_sha256: str | None = None
        resolved_handoff_path: str | None = None
        handoff: dict[str, object] | None = None
        if root_handoff_required:
            root_receipt_path = _validate_root_receipt_destination(
                root_receipt_path, operator_uid=uid
            )
            handoff = _root_handoff_payload(
                intent_path=intent_path,
                intent_sha256=intent_sha256,
                user_receipt_path=user_receipt_path,
                root_handoff_path=root_handoff_path,
                root_receipt_path=root_receipt_path,
                plan=plan,
                root_attestation=root_attestation,
                root_attestation_path=root_attestation_path,
                root_attestation_sha256=root_attestation_sha256,
            )
            if os.path.lexists(root_handoff_path):
                handoff, handoff_sha256 = _load_matching_handoff(
                    root_handoff_path,
                    uid=uid,
                    expected=handoff,
                )
            else:
                handoff_sha256 = _atomic_new_json(
                    root_handoff_path, handoff, owner=uid
                )
            resolved_handoff_path = str(root_handoff_path.resolve(strict=True))
        elif os.path.lexists(root_handoff_path):
            raise RuntimeError("manfred_capacity_stale_root_handoff")
        receipt = {
            "schema": USER_RECEIPT_SCHEMA,
            "status": (
                "root_handoff_required"
                if root_handoff_required
                else "capacity_ready_no_root_actions"
            ),
            "created_at": _utc_now(),
            "producer_sha256": plan["producer_sha256"],
            "operator_uid": uid,
            "intent_path": str(intent_path.resolve(strict=True)),
            "intent_sha256": intent_sha256,
            "plan_sha256": plan["plan_sha256"],
            "root_attestation_path": str(root_attestation_path.resolve(strict=True)),
            "root_attestation_sha256": root_attestation_sha256,
            "root_handoff_path": resolved_handoff_path,
            "root_handoff_sha256": handoff_sha256,
            "root_receipt_path": (
                str(root_receipt_path.absolute()) if root_handoff_required else None
            ),
            "root_apply_argv": None if root_handoff_required else [],
            "root_apply_argv_persisted": False if root_handoff_required else True,
            "root_installer": (
                dict(plan["root_installer"]) if root_handoff_required else None
            ),
            "root_installer_sha256": (
                ROOT_INSTALLER_SHA256 if root_handoff_required else None
            ),
            "root_handoff_required": root_handoff_required,
            "root_free_bytes_before": before_free,
            "root_free_bytes_after": after_free,
            "builder": builder,
            "caches": caches,
            "vscode": vscode,
            "candidate": candidate,
            "user_action_order": [
                "builder",
                *[f"cache:{dict(row).get('name')}" for row in list(plan["caches"])],
                "vscode",
                "candidate",
            ],
            "preserved_capacity_ready_actions": preserved_user_actions,
            "preserved_unavailable_actions": unavailable_user_actions,
            "capacity_latched": after_free >= int(plan["target_root_free_bytes"]),
            "global_docker_prune_performed": False,
            "other_images_removed": False,
            "root_actions_performed": False,
            "projection_deletion_authorized": root_handoff_required,
            "root_candidate_deletion_authorized": root_handoff_required,
            "projection_deletion_performed": False,
            "root_candidate_deletion_performed": False,
            "projections_preserved_count": (
                0 if root_handoff_required else len(list(plan["projections"]))
            ),
            "target_broadened": False,
            "secrets_included": False,
        }
        receipt_sha256 = _atomic_new_json(user_receipt_path, receipt, owner=uid)
        returned_root_apply_argv: list[str] = []
        if root_handoff_required:
            if handoff is None or handoff_sha256 is None:
                raise RuntimeError("manfred_capacity_root_handoff_invalid")
            handoff_evidence = _private_source_evidence(
                root_handoff_path,
                expected_uid=uid,
                expected_sha256=handoff_sha256,
            )
            user_receipt_evidence = _private_source_evidence(
                user_receipt_path,
                expected_uid=uid,
                expected_sha256=receipt_sha256,
            )
            returned_root_apply_argv = _root_installer_argv(
                uid=uid,
                plan=plan,
                handoff=handoff,
                handoff_evidence=handoff_evidence,
                user_receipt_evidence=user_receipt_evidence,
                root_receipt_path=root_receipt_path,
            )
        return {
            **receipt,
            "root_apply_argv": returned_root_apply_argv,
            "root_apply_argv_persisted": not root_handoff_required,
            "receipt_path": str(user_receipt_path),
            "receipt_sha256": receipt_sha256,
        }




def finalize(
    *,
    intent_path: Path,
    user_receipt_path: Path,
    root_receipt_path: Path | None,
    completion_receipt_path: Path,
) -> dict[str, object]:
    uid, _home = _operator_identity()
    if os.geteuid() != uid:
        raise RuntimeError("manfred_capacity_finalize_requires_operator")
    intent, intent_sha = _read_private_json(intent_path, expected_owner=uid)
    user, user_sha = _read_private_json(user_receipt_path, expected_owner=uid)
    intent_plan = dict(intent.get("plan") or {})
    intended_paths = [
        str(dict(row).get("path") or "")
        for row in list(intent_plan.get("projections") or [])
    ]
    intended_root_candidates = [
        dict(row)
        for row in list(intent_plan.get("root_candidates") or [])
        if isinstance(row, dict)
    ]
    intended_root_action_ids = [
        str(row.get("action_id") or "") for row in intended_root_candidates
    ]
    target = intent.get("target_root_free_bytes")
    if (
        intent.get("schema") != INTENT_SCHEMA
        or user.get("schema") != USER_RECEIPT_SCHEMA
        or user.get("intent_sha256") != intent_sha
        or user.get("plan_sha256") != intent.get("plan_sha256")
        or user.get("producer_sha256") != intent.get("producer_sha256")
        or type(target) is not int
        or target != TARGET_ROOT_FREE_BYTES
        or len(intended_paths) != EXPECTED_PROJECTION_COUNT
        or not intended_root_action_ids
        or len(set(intended_root_action_ids)) != len(intended_root_action_ids)
        or intent.get("root_attestation_required_before_user_mutation") is not True
        or not isinstance(intent.get("root_attestation"), dict)
        or user.get("root_attestation_path") != intent.get("root_attestation_path")
        or user.get("root_attestation_sha256")
        != intent.get("root_attestation_sha256")
        or user.get("root_actions_performed") is not False
        or user.get("target_broadened") is not False
    ):
        raise RuntimeError("manfred_capacity_receipt_chain_invalid")

    root_sha: str | None = None
    resolved_root_receipt_path: str | None = None
    root_stage = "not_required"
    root_status = user.get("status")
    if root_status == "capacity_ready_no_root_actions":
        if (
            root_receipt_path is not None
            or user.get("root_handoff_required") is not False
            or user.get("root_handoff_path") is not None
            or user.get("root_handoff_sha256") is not None
            or user.get("root_receipt_path") is not None
            or user.get("root_apply_argv") != []
            or user.get("root_apply_argv_persisted") is not True
            or user.get("root_installer") is not None
            or user.get("root_installer_sha256") is not None
            or user.get("projection_deletion_authorized") is not False
            or user.get("root_candidate_deletion_authorized") is not False
            or user.get("projection_deletion_performed") is not False
            or user.get("root_candidate_deletion_performed") is not False
            or user.get("projections_preserved_count") != len(intended_paths)
            or type(user.get("root_free_bytes_after")) is not int
            or int(user["root_free_bytes_after"]) < target
        ):
            raise RuntimeError("manfred_capacity_receipt_chain_invalid")
    elif root_status == "root_handoff_required":
        if (
            root_receipt_path is None
            or user.get("root_handoff_required") is not True
            or user.get("root_receipt_path") != str(root_receipt_path.absolute())
            or user.get("root_apply_argv") is not None
            or user.get("root_apply_argv_persisted") is not False
            or user.get("root_installer") != intent_plan.get("root_installer")
            or user.get("root_installer_sha256") != ROOT_INSTALLER_SHA256
        ):
            raise RuntimeError("manfred_capacity_receipt_chain_invalid")
        root, root_sha = _read_root_receipt(root_receipt_path, operator_uid=uid)
        resolved_root_receipt_path = str(root_receipt_path.resolve(strict=True))
        root_actions = list(root.get("actions") or [])
        observed_paths = [
            str(dict(row).get("path") or "")
            for row in root_actions
            if isinstance(row, dict)
        ]
        observed_action_ids = [
            str(dict(row).get("action_id") or "")
            for row in root_actions
            if isinstance(row, dict)
        ]
        statuses = [
            str(dict(row).get("status") or "")
            for row in root_actions
            if isinstance(row, dict)
        ]
        removed_count = sum(
            status in DELETION_STATUSES
            and dict(row).get("kind") == "candidate_release_projection"
            for row, status in zip(root_actions, statuses, strict=True)
        )
        root_deleted_count = sum(status in DELETION_STATUSES for status in statuses)
        preserved_count = sum(
            dict(row).get("kind") == "candidate_release_projection"
            and status in PRESERVED_STATUSES
            for row, status in zip(root_actions, statuses, strict=True)
        )
        root_stage_path = Path(str(root.get("root_stage_path") or ""))
        staged_applier = dict(root.get("staged_root_applier") or {})
        staged_controller = dict(root.get("staged_controller") or {})
        staged_handoff = dict(root.get("staged_handoff") or {})
        staged_user = dict(root.get("staged_user_receipt") or {})
        if (
            root.get("schema") != ROOT_RECEIPT_SCHEMA
            or root.get("status") != "capacity_ready"
            or root.get("intent_sha256") != intent_sha
            or root.get("user_receipt_sha256") != user_sha
            or root.get("handoff_sha256") != user.get("root_handoff_sha256")
            or root.get("producer_sha256") != intent.get("producer_sha256")
            or root.get("root_applier_sha256")
            != dict(intent_plan.get("root_applier") or {}).get("sha256")
            or root.get("root_installer") != intent_plan.get("root_installer")
            or root.get("root_installer_sha256") != ROOT_INSTALLER_SHA256
            or root.get("user_writable_root_interpreted_file") is not False
            or root.get("inline_installer_execution_trust_boundary") is not True
            or root.get("handoff_path") != user.get("root_handoff_path")
            or root.get("user_receipt_path")
            != str(user_receipt_path.resolve(strict=True))
            or not root_stage_path.is_absolute()
            or root_stage_path.parent != Path("/root")
            or root.get("root_stage_mode") != 0o700
            or root.get("root_stage_nlink") != 2
            or staged_applier.get("path") != str(root_stage_path / "applier.py")
            or staged_applier.get("sha256")
            != dict(intent_plan.get("root_applier") or {}).get("sha256")
            or staged_applier.get("mode") != 0o500
            or staged_applier.get("owner_uid") != 0
            or staged_controller.get("path")
            != str(root_stage_path / "controller.py")
            or staged_controller.get("sha256") != intent.get("producer_sha256")
            or staged_controller.get("mode") != 0o400
            or staged_controller.get("owner_uid") != 0
            or staged_handoff.get("path") != str(root_stage_path / "handoff.json")
            or staged_handoff.get("sha256") != user.get("root_handoff_sha256")
            or staged_handoff.get("mode") != 0o400
            or staged_handoff.get("owner_uid") != 0
            or staged_user.get("path")
            != str(root_stage_path / "user-receipt.json")
            or staged_user.get("sha256") != user_sha
            or staged_user.get("mode") != 0o400
            or staged_user.get("owner_uid") != 0
            or root.get("projection_count") != len(intended_paths)
            or root.get("root_candidate_count") != len(intended_root_candidates)
            or observed_action_ids != intended_root_action_ids
            or observed_paths
            != [str(row.get("path") or "") for row in intended_root_candidates]
            or len(root_actions) != len(observed_paths)
            or any(
                status
                not in {
                    "removed",
                    "recovered_removed",
                    "already_removed_verified",
                    "already_absent",
                    "preserved_capacity_ready",
                    "preserved_not_authorized",
                    "preserved_referenced",
                }
                for status in statuses
            )
            or root.get("projection_deletion_performed") is not bool(removed_count)
            or root.get("root_candidate_deletion_performed")
            is not bool(root_deleted_count)
            or root.get("projections_preserved_count") != preserved_count
            or root.get("root_attestation_path")
            != intent.get("root_attestation_path")
            or root.get("root_attestation_sha256")
            != intent.get("root_attestation_sha256")
            or root.get("root_candidate_set_sha256")
            != _root_candidate_set_sha256(intent_plan)
            or root.get("authorized_root_action_ids")
            != dict(intent.get("root_attestation") or {}).get(
                "authorized_root_action_ids"
            )
            or root.get("global_preflight_complete_before_mutation") is not True
            or root.get("target_broadened") is not False
            or root.get("docker_mutations_performed") is not False
            or root.get("candidate_roots_removed") is not False
            or root.get("runtime_removed") is not False
            or root.get("receipts_removed") is not False
        ):
            raise RuntimeError("manfred_capacity_receipt_chain_invalid")
        root_stage = "receipt_verified"
    else:
        raise RuntimeError("manfred_capacity_receipt_chain_invalid")

    final_free = _root_free_bytes()
    if final_free < target:
        raise RuntimeError("manfred_capacity_final_target_not_met")
    completion = {
        "schema": COMPLETION_SCHEMA,
        "status": "pass",
        "created_at": _utc_now(),
        "producer_sha256": intent["producer_sha256"],
        "intent_path": str(intent_path.resolve(strict=True)),
        "intent_sha256": intent_sha,
        "user_receipt_path": str(user_receipt_path.resolve(strict=True)),
        "user_receipt_sha256": user_sha,
        "root_stage": root_stage,
        "root_receipt_path": resolved_root_receipt_path,
        "root_receipt_sha256": root_sha,
        "target_root_free_bytes": target,
        "final_root_free_bytes": final_free,
        "build_admission_authorized": True,
        "projection_deletion_performed": (
            False if root_stage == "not_required" else bool(root["projection_deletion_performed"])
        ),
        "root_candidate_deletion_performed": (
            False
            if root_stage == "not_required"
            else bool(root["root_candidate_deletion_performed"])
        ),
        "target_broadened": False,
        "global_docker_prune_performed": False,
        "other_images_removed": False,
        "candidate_roots_removed": False,
        "runtime_removed": False,
        "receipts_removed": False,
        "secrets_included": False,
    }
    completion_sha = _atomic_new_json(completion_receipt_path, completion, owner=uid)
    return {
        **completion,
        "receipt_path": str(completion_receipt_path),
        "receipt_sha256": completion_sha,
    }


def _add_discovery_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument(
        "--deploy-root",
        type=Path,
        default=Path.home() / ".local/share/ea-deploy/manfred-memorial",
    )
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument(
        "--protected-image-id",
        action="append",
        default=[],
        help="additional immutable image ID; may be repeated",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    plan_parser = modes.add_parser("plan", help="discover and print an immutable plan")
    _add_discovery_arguments(plan_parser)
    probe_parser = modes.add_parser(
        "probe-live-plan",
        help="run the complete plan and print only bounded, redacted smoke evidence",
    )
    _add_discovery_arguments(probe_parser)
    attest_parser = modes.add_parser(
        "prepare-root-attest",
        help="prepare one hash-bound root preflight request without mutation",
    )
    attest_parser.add_argument("--plan-file", type=Path, required=True)
    attest_parser.add_argument("--request", type=Path, required=True)
    attest_parser.add_argument("--root-attestation", type=Path, required=True)
    seal_parser = modes.add_parser(
        "seal-intent",
        help="seal a reviewed plan plus root attestation for apply-user",
    )
    seal_parser.add_argument("--plan-file", type=Path, required=True)
    seal_parser.add_argument("--root-attestation", type=Path, required=True)
    seal_parser.add_argument("--intent", type=Path, required=True)
    user_parser = modes.add_parser(
        "apply-user",
        help="apply an already sealed and reviewed intent; never auto-discovers",
    )
    user_parser.add_argument("--intent", type=Path, required=True)
    user_parser.add_argument("--user-receipt", type=Path, required=True)
    user_parser.add_argument("--root-handoff", type=Path, required=True)
    user_parser.add_argument("--root-receipt", type=Path, required=True)
    final_parser = modes.add_parser(
        "finalize", help="verify the receipt chain and the capacity target"
    )
    final_parser.add_argument("--intent", type=Path, required=True)
    final_parser.add_argument("--user-receipt", type=Path, required=True)
    final_parser.add_argument("--root-receipt", type=Path, default=None)
    final_parser.add_argument("--completion-receipt", type=Path, required=True)
    return parser


def _registry_argument(value: Path | None) -> Path:
    return Path(value) if value is not None else default_registry_path()


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if os.geteuid() == 0:
            raise RuntimeError("manfred_capacity_use_standalone_root_applier")
        if arguments.mode == "plan":
            result = discover_plan(
                source_root=arguments.source_root,
                deploy_root=arguments.deploy_root,
                registry_path=_registry_argument(arguments.registry),
                protected_image_ids=arguments.protected_image_id,
            )
        elif arguments.mode == "probe-live-plan":
            result = redacted_plan_probe(
                source_root=arguments.source_root,
                deploy_root=arguments.deploy_root,
                registry_path=_registry_argument(arguments.registry),
                protected_image_ids=arguments.protected_image_id,
            )
        elif arguments.mode == "prepare-root-attest":
            result = prepare_root_attestation(
                plan_path=arguments.plan_file,
                request_path=arguments.request,
                root_attestation_path=arguments.root_attestation,
            )
        elif arguments.mode == "seal-intent":
            result = seal_intent(
                plan_path=arguments.plan_file,
                root_attestation_path=arguments.root_attestation,
                intent_path=arguments.intent,
            )
        elif arguments.mode == "apply-user":
            result = apply_user(
                intent_path=arguments.intent,
                user_receipt_path=arguments.user_receipt,
                root_handoff_path=arguments.root_handoff,
                root_receipt_path=arguments.root_receipt,
            )
        elif arguments.mode == "finalize":
            result = finalize(
                intent_path=arguments.intent,
                user_receipt_path=arguments.user_receipt,
                root_receipt_path=arguments.root_receipt,
                completion_receipt_path=arguments.completion_receipt,
            )
        else:  # pragma: no cover - argparse enforces this
            raise RuntimeError("manfred_capacity_mode_invalid")
        print(json.dumps(result, sort_keys=True))
        return 0
    except RuntimeError as exc:
        reason = str(exc)
        if re.fullmatch(r"[a-z0-9_]{1,160}", reason) is None:
            reason = "manfred_capacity_failed"
        print(
            json.dumps({"status": "fail", "reason": reason}, sort_keys=True),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
