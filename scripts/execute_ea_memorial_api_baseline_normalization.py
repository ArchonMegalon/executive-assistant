#!/usr/bin/env python3
"""Governed, crash-safe normalization of the live ``ea-api`` Compose baseline.

The lane recreates only ``ea-api`` from a retained exact-Git/private-environment
bundle. Its one allowed semantic change is the three Compose topology labels;
the image, runtime configuration, ingress, public network, and public edge must
remain byte-for-byte equivalent under their secret-free identity projections.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

try:
    from scripts.deploy_ea_memorial import (
        API_SERVICE,
        MAX_HTTP_BODY_BYTES,
        PROJECT_NAME,
        DeployError,
        HttpResponse,
        MemorialDeployLane,
        Runner,
        _NoRedirectHandler,
        _memorial_rollback_environment,
        _mount_identities,
        _validate_public_origin,
    )
    from scripts.deploy_ea_memorial_joint import (
        CLOUDFLARED_CONTAINER,
        JOINT_DEPLOY_OPERATOR_ANCHOR,
    )
    from scripts.ea_memorial_baseline_bundle import (
        BASELINE_RENDER_ENV_KEYS,
        BUNDLE_CONTRACT,
        BUNDLE_VERSION,
        RUNTIME_DIRECTORY,
        RUNTIME_ENV_FILE,
        RUNTIME_LOCAL_ENV_FILE,
        BaselineBundleError,
        materialize_baseline_bundle,
        require_baseline_bundle_seal,
        require_recovery_baseline_bundle,
    )
    from scripts.ea_memorial_normalization_journal import (
        PUBLIC_EDGE_IDENTITY_SCHEMA,
        PUBLIC_EDGE_PROBES,
        TERMINAL_RECEIPT_CONTRACT_NAME,
        NormalizationJournalError,
        NormalizationRecoveryJournal,
        deterministic_rollback_tag,
        terminal_observation,
        terminal_receipt_payload,
    )
    from scripts.ea_memorial_recovery_interlock import (
        MemorialRecoveryInterlockError,
        default_joint_recovery_journal_path,
        require_joint_recovery_absent,
    )
    from scripts.ea_memorial_runtime_identity import (
        RuntimeIdentityError,
        cloudflared_runtime_projection,
        memorial_api_runtime_projection,
        public_network_semantic_projection,
        runtime_comparison_report,
    )
    from scripts.plan_ea_memorial_api_baseline_normalization import (
        COLOCATED_LEGACY_COMPOSE_FILES,
        COLOCATED_LEGACY_ENV_CONDITION,
        PlanError,
        SPLIT_BASELINE_CONDITION,
        validate_plan_payload,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from deploy_ea_memorial import (  # type: ignore[no-redef]
        API_SERVICE,
        MAX_HTTP_BODY_BYTES,
        PROJECT_NAME,
        DeployError,
        HttpResponse,
        MemorialDeployLane,
        Runner,
        _NoRedirectHandler,
        _memorial_rollback_environment,
        _mount_identities,
        _validate_public_origin,
    )
    from deploy_ea_memorial_joint import (  # type: ignore[no-redef]
        CLOUDFLARED_CONTAINER,
        JOINT_DEPLOY_OPERATOR_ANCHOR,
    )
    from ea_memorial_baseline_bundle import (  # type: ignore[no-redef]
        BASELINE_RENDER_ENV_KEYS,
        BUNDLE_CONTRACT,
        BUNDLE_VERSION,
        RUNTIME_DIRECTORY,
        RUNTIME_ENV_FILE,
        RUNTIME_LOCAL_ENV_FILE,
        BaselineBundleError,
        materialize_baseline_bundle,
        require_baseline_bundle_seal,
        require_recovery_baseline_bundle,
    )
    from ea_memorial_normalization_journal import (  # type: ignore[no-redef]
        PUBLIC_EDGE_IDENTITY_SCHEMA,
        PUBLIC_EDGE_PROBES,
        TERMINAL_RECEIPT_CONTRACT_NAME,
        NormalizationJournalError,
        NormalizationRecoveryJournal,
        deterministic_rollback_tag,
        terminal_observation,
        terminal_receipt_payload,
    )
    from ea_memorial_recovery_interlock import (  # type: ignore[no-redef]
        MemorialRecoveryInterlockError,
        default_joint_recovery_journal_path,
        require_joint_recovery_absent,
    )
    from ea_memorial_runtime_identity import (  # type: ignore[no-redef]
        RuntimeIdentityError,
        cloudflared_runtime_projection,
        memorial_api_runtime_projection,
        public_network_semantic_projection,
        runtime_comparison_report,
    )
    from plan_ea_memorial_api_baseline_normalization import (  # type: ignore[no-redef]
        COLOCATED_LEGACY_COMPOSE_FILES,
        COLOCATED_LEGACY_ENV_CONDITION,
        PlanError,
        SPLIT_BASELINE_CONDITION,
        validate_plan_payload,
    )


ROOT = Path(__file__).resolve().parents[1]
RECEIPT_CONTRACT = TERMINAL_RECEIPT_CONTRACT_NAME
OPERATION_RECEIPT_CONTRACT = "ea.memorial_api_baseline_normalization_operation.v2"
PREFLIGHT_RECEIPT_CONTRACT = "ea.memorial_api_baseline_normalization_preflight.v2"
PREFLIGHT_RECEIPT_VERSION = 2
PUBLIC_NETWORK = "ea_public_ingress"
NORMALIZATION_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.memorial.yml",
    "docker-compose.api-baseline-normalization.yml",
)
TOPOLOGY_LABELS = (
    "com.docker.compose.project.working_dir",
    "com.docker.compose.project.config_files",
    "com.docker.compose.project.environment_file",
)
CONFIG_HASH_LABEL = "com.docker.compose.config-hash"
REVISION_LABEL = "org.opencontainers.image.revision"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TRANSACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
MAX_PRIVATE_JSON_BYTES = 2 * 1024 * 1024
MAX_DOCKER_JSON_BYTES = 32 * 1024 * 1024
MAX_LEGACY_ENV_LABEL_FILE_BYTES = 2 * 1024 * 1024
DOCKER_TRANSPORT_ENV = frozenset(
    {
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "SSH_AUTH_SOCK",
        "XDG_RUNTIME_DIR",
    }
)
SAFE_PUBLIC_HEADERS = (
    "Cache-Control",
    "Content-Type",
    "Location",
    "Referrer-Policy",
    "X-Content-Type-Options",
    "X-EA-Source-Revision",
    "X-Robots-Tag",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _private_json_bytes(value: object) -> bytes:
    try:
        raw = (
            json.dumps(
                value,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise DeployError("normalization_private_json_invalid") from exc
    if not 0 < len(raw) <= MAX_PRIVATE_JSON_BYTES:
        raise DeployError("normalization_private_json_size_invalid")
    return raw


def _rename_noreplace(
    directory_fd: int, source_name: str, destination_name: str
) -> None:
    """Atomically publish one private entry without an overwrite fallback."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as exc:
        raise DeployError("normalization_noreplace_unavailable") from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd,
        os.fsencode(source_name),
        directory_fd,
        os.fsencode(destination_name),
        1,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), destination_name)
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
        raise DeployError("normalization_noreplace_unavailable")
    raise DeployError("normalization_noreplace_failed") from OSError(
        error, os.strerror(error)
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normal_absolute_path(value: object, *, reason: str) -> Path:
    raw = str(value or "")
    if (
        not raw
        or "\x00" in raw
        or raw.startswith("~")
        or not os.path.isabs(raw)
        or os.path.normpath(raw) != raw
    ):
        raise DeployError(reason)
    path = Path(raw)
    if path == Path("/") or ".." in path.parts:
        raise DeployError(reason)
    return path


def _strict_json(raw: bytes, *, reason: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("non-finite number")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise DeployError(reason) from exc
    if not isinstance(value, dict):
        raise DeployError(reason)
    return value


def _normalization_public_snapshot(
    url: str,
    timeout_seconds: float,
    method: str,
) -> HttpResponse:
    """Capture any bounded HTTP status without following redirects."""
    if method not in {"GET", "HEAD"}:
        raise DeployError("normalization_public_method_invalid")
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            "User-Agent": "EA-Memorial-Baseline-Normalizer/1.0",
        },
    )
    response: Any
    try:
        response = urllib.request.build_opener(_NoRedirectHandler()).open(
            request, timeout=timeout_seconds
        )
    except urllib.error.HTTPError as exc:
        if not 100 <= int(exc.code or 0) <= 599:
            raise DeployError("normalization_public_status_invalid") from exc
        response = exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(
            f"normalization_public_probe_failed:{type(exc).__name__}"
        ) from exc
    try:
        body = b"" if method == "HEAD" else response.read(MAX_HTTP_BODY_BYTES + 1)
        if len(body) > MAX_HTTP_BODY_BYTES:
            raise DeployError("normalization_public_body_too_large")
        status = int(getattr(response, "status", 0) or response.getcode() or 0)
        if not 100 <= status <= 599:
            raise DeployError("normalization_public_status_invalid")
        return HttpResponse(
            status=status,
            content_type=str(response.headers.get("Content-Type") or "").strip(),
            body=body,
            headers={
                name: str(response.headers.get(name) or "").strip()
                for name in SAFE_PUBLIC_HEADERS
            },
        )
    finally:
        response.close()


class ApiBaselineNormalizationLane(MemorialDeployLane):
    """Normalize only API Compose labels under the existing global API lock."""

    def __init__(
        self,
        *,
        plan_path: Path,
        bundle_parent: Path,
        public_origin: str,
        preflight_only: bool = False,
        root: Path = ROOT,
        env: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        public_snapshot: Callable[[str, float, str], HttpResponse] = (
            _normalization_public_snapshot
        ),
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        wait_seconds: float = 90.0,
        poll_seconds: float = 2.0,
        request_timeout_seconds: float = 10.0,
        operational_receipt_dir: Path | None = None,
        global_lock_path: Path | None = None,
        durable_root_check: Callable[[Path], None] | None = None,
        bundle_materializer: Callable[..., dict[str, Any]] = (
            materialize_baseline_bundle
        ),
        bundle_seal_validator: Callable[[Mapping[str, object]], dict[str, Any]] = (
            require_baseline_bundle_seal
        ),
        recovery_bundle_validator: Callable[..., dict[str, Any]] = (
            require_recovery_baseline_bundle
        ),
        journal_factory: Callable[..., Any] = NormalizationRecoveryJournal,
        joint_path_resolver: Callable[..., Path] = (
            default_joint_recovery_journal_path
        ),
        joint_absence_check: Callable[[Path | None], None] = (
            require_joint_recovery_absent
        ),
        api_projector: Callable[[Mapping[str, Any]], dict[str, object]] = (
            memorial_api_runtime_projection
        ),
        cloudflared_projector: Callable[[Mapping[str, Any]], dict[str, object]] = (
            cloudflared_runtime_projection
        ),
        network_projector: Callable[[Mapping[str, Any]], dict[str, object]] = (
            public_network_semantic_projection
        ),
        comparison_report: Callable[
            [Mapping[str, object], Mapping[str, object]], dict[str, object]
        ] = runtime_comparison_report,
        terminal_observation_builder: Callable[..., dict[str, Any]] = (
            terminal_observation
        ),
        terminal_receipt_builder: Callable[..., dict[str, Any]] = (
            terminal_receipt_payload
        ),
        now: Callable[[], str] = _utc_now,
    ) -> None:
        selected_root = root.resolve()
        caller_env = dict(os.environ if env is None else env)
        constructor_env: dict[str, str] = {}
        deployment_id = caller_env.get("EA_DEPLOYMENT_ID")
        if deployment_id is not None:
            constructor_env["EA_DEPLOYMENT_ID"] = deployment_id
        for key in sorted(DOCKER_TRANSPORT_ENV):
            value = caller_env.get(key)
            if value is not None:
                constructor_env[key] = value
        super_kwargs: dict[str, Any] = {
            "root": selected_root,
            "env": constructor_env,
            "load_release_env_file": False,
            "runner": runner,
            "wait_seconds": wait_seconds,
            "poll_seconds": poll_seconds,
            "request_timeout_seconds": request_timeout_seconds,
            "receipt_dir": (
                operational_receipt_dir
                or selected_root
                / ".runtime"
                / "deployments"
                / "memorial-normalization-operations"
            ),
            "global_lock_path": global_lock_path,
        }
        if sleep is not None:
            super_kwargs["sleep"] = sleep
        if monotonic is not None:
            super_kwargs["monotonic"] = monotonic
        if durable_root_check is not None:
            super_kwargs["durable_root_check"] = durable_root_check
        super().__init__(**super_kwargs)
        if TRANSACTION_ID_RE.fullmatch(self.deployment_id) is None:
            raise DeployError("normalization_operation_id_invalid")
        self.receipt: dict[str, Any] = {
            "contract_name": OPERATION_RECEIPT_CONTRACT,
            "operation_id": self.deployment_id,
            "started_at": _utc_now(),
            "status": "running",
            "service_scope": [API_SERVICE],
            "ingress_mutation_scope": [],
            "promotion_authority": False,
            "candidate_authority": False,
            "checks": [],
        }
        # Caller-supplied fresh-work inputs are not validated until after the
        # canonical journal has been read.  Recovery is plan/bundle/origin-free.
        self.plan_path = plan_path
        self.bundle_parent = bundle_parent
        self.requested_public_origin = str(public_origin or "")
        self.public_origin = ""
        self.preflight_only = bool(preflight_only)
        self.public_snapshot = public_snapshot
        self.bundle_materializer = bundle_materializer
        self.bundle_seal_validator = bundle_seal_validator
        self.recovery_bundle_validator = recovery_bundle_validator
        self.journal = journal_factory(operator_anchor=self.root)
        self.joint_path_resolver = joint_path_resolver
        self.joint_absence_check = joint_absence_check
        self.api_projector = api_projector
        self.cloudflared_projector = cloudflared_projector
        self.network_projector = network_projector
        self.comparison_report = comparison_report
        self.terminal_observation_builder = terminal_observation_builder
        self.terminal_receipt_builder = terminal_receipt_builder
        self.now = now
        self.compose_process_env = self._sanitized_docker_environment()
        self.release_env = dict(self.compose_process_env)
        self.transaction_receipt_path = (
            self.root / ".runtime" / (f"{self.deployment_id}.json")
        )
        runtime_directory = (self.root / ".runtime").resolve()
        if (
            self.receipt_dir == runtime_directory
            or self.receipt_path == self.transaction_receipt_path
        ):
            raise DeployError("normalization_operational_receipt_path_reserved")
        self._operational_receipt_identity: tuple[int, ...] | None = None
        self._operational_receipt_raw: bytes | None = None

    def _sanitized_docker_environment(self) -> dict[str, str]:
        try:
            root_metadata = self.root.lstat()
            account_home = Path(pwd.getpwuid(root_metadata.st_uid).pw_dir)
            home_metadata = account_home.lstat()
        except (KeyError, OSError) as exc:
            raise DeployError("normalization_account_home_unavailable") from exc
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or not account_home.is_absolute()
            or ".." in account_home.parts
            or not stat.S_ISDIR(home_metadata.st_mode)
            or stat.S_ISLNK(home_metadata.st_mode)
            or home_metadata.st_uid != root_metadata.st_uid
            or stat.S_IMODE(home_metadata.st_mode) & 0o022
        ):
            raise DeployError("normalization_account_home_invalid")
        result = {
            "HOME": str(account_home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
        }
        for key in sorted(DOCKER_TRANSPORT_ENV):
            value = self.env.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or "\x00" in value:
                raise DeployError("normalization_docker_environment_invalid")
            result[key] = value
        if any(key.startswith("EA_") or key.startswith("COMPOSE_") for key in result):
            raise DeployError("normalization_docker_environment_invalid")
        return result

    @contextmanager
    def _global_lock(self) -> Iterator[None]:
        if self._global_lock_handle is not None:
            raise DeployError("normalization_global_lock_nested")
        self._global_lock_handle = self._open_lock(
            self.global_lock_path,
            busy_reason="memorial_api_deployment_already_running",
        )
        try:
            try:
                os.stat(self.receipt_path, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise DeployError(
                    "normalization_operation_receipt_indeterminate"
                ) from exc
            else:
                raise DeployError("normalization_operation_id_already_used")
            self._lock_handle = self._open_lock(
                self.lock_path,
                busy_reason="normalization_operation_already_running",
            )
            yield
        finally:
            self._release_lock()

    def _require_joint_recovery_absent(self) -> None:
        try:
            joint_path = self.joint_path_resolver(
                operator_anchor=JOINT_DEPLOY_OPERATOR_ANCHOR
            )
            self.joint_absence_check(joint_path)
        except MemorialRecoveryInterlockError as exc:
            raise DeployError(str(exc)) from exc

    def execute(self) -> dict[str, Any]:
        """Run recovery first, or execute a fresh preflight/normalization."""
        with self._global_lock():
            active = self.journal.read()
            if active is not None:
                if self.preflight_only:
                    raise DeployError("normalization_recovery_active")
                self._write_receipt()
                self._require_joint_recovery_absent()
                return self._recover(active)
            self._write_receipt()
            self._require_joint_recovery_absent()
            self._require_path_entry_absent(
                self.transaction_receipt_path,
                reason="normalization_terminal_receipt_already_exists",
                require_private_parent=True,
            )
            prepared = self._prepare_fresh()
            if self.preflight_only:
                return self._preflight_receipt(prepared)
            return self._normalize(prepared)

    @staticmethod
    def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
        )

    def _open_absolute_directory(
        self,
        path: Path,
        *,
        require_private: bool,
        reason: str,
    ) -> tuple[int, tuple[int, ...]]:
        selected = _normal_absolute_path(path, reason=reason)
        required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
        if any(not hasattr(os, name) for name in required):
            raise DeployError(f"{reason}_secure_open_unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = -1
        try:
            descriptor = os.open("/", flags)
            for component in selected.parts[1:]:
                named = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                child = os.open(component, flags, dir_fd=descriptor)
                opened = os.fstat(child)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or stat.S_ISLNK(named.st_mode)
                    or self._directory_identity(named)
                    != self._directory_identity(opened)
                ):
                    os.close(child)
                    raise DeployError(reason)
                os.close(descriptor)
                descriptor = child
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode) or (
                require_private
                and (
                    metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o700
                )
            ):
                raise DeployError(reason)
            return descriptor, self._directory_identity(metadata)
        except DeployError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise DeployError(reason) from exc

    def _revalidate_absolute_directory(
        self,
        path: Path,
        expected: tuple[int, ...],
        *,
        require_private: bool,
        reason: str,
    ) -> None:
        descriptor, current = self._open_absolute_directory(
            path, require_private=require_private, reason=reason
        )
        try:
            if current != expected:
                raise DeployError(reason)
        finally:
            os.close(descriptor)

    def _read_private_file(
        self,
        path: Path,
        *,
        reason: str,
        max_bytes: int = MAX_PRIVATE_JSON_BYTES,
    ) -> bytes:
        selected = _normal_absolute_path(path, reason=f"{reason}_path_invalid")
        parent_fd, parent_identity = self._open_absolute_directory(
            selected.parent,
            require_private=True,
            reason=f"{reason}_parent_untrusted",
        )
        descriptor = -1
        try:
            named = os.stat(selected.name, dir_fd=parent_fd, follow_symlinks=False)
            descriptor = os.open(
                selected.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
            before = os.fstat(descriptor)
            identity = (
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
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                or not 0 < before.st_size <= max_bytes
            ):
                raise DeployError(f"{reason}_untrusted")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            final = os.stat(selected.name, dir_fd=parent_fd, follow_symlinks=False)
            final_identity = (
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
            if (
                remaining
                or len(raw) != before.st_size
                or final_identity != identity
                or (final.st_dev, final.st_ino) != (before.st_dev, before.st_ino)
                or final.st_size != before.st_size
                or final.st_mtime_ns != before.st_mtime_ns
                or final.st_ctime_ns != before.st_ctime_ns
            ):
                raise DeployError(f"{reason}_changed")
            self._revalidate_absolute_directory(
                selected.parent,
                parent_identity,
                require_private=True,
                reason=f"{reason}_parent_changed",
            )
            return raw
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason}_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent_fd)

    @staticmethod
    def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_nlink,
        )

    def _read_private_entry_at(
        self,
        directory_fd: int,
        name: str,
        *,
        reason: str,
    ) -> tuple[bytes, tuple[int, ...]]:
        descriptor = -1
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            before = os.fstat(descriptor)
            stable_before = (
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
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                or not 0 < before.st_size <= MAX_PRIVATE_JSON_BYTES
            ):
                raise DeployError(f"{reason}_untrusted")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
            linked = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            stable_after = (
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
            if (
                remaining
                or len(raw) != before.st_size
                or stable_after != stable_before
                or (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise DeployError(f"{reason}_changed")
            return raw, self._file_identity(after)
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason}_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _write_all(descriptor: int, raw: bytes) -> None:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise DeployError("normalization_private_write_failed")
            remaining = remaining[written:]

    def _publish_private_noreplace(
        self,
        path: Path,
        raw: bytes,
        *,
        reason: str,
        idempotent: bool,
    ) -> tuple[str, tuple[int, ...]]:
        selected = _normal_absolute_path(path, reason=f"{reason}_path_invalid")
        directory_fd, directory_identity = self._open_absolute_directory(
            selected.parent,
            require_private=True,
            reason=f"{reason}_directory_untrusted",
        )
        digest = _sha256(raw)
        temporary_name = f".{selected.name}.publish.{digest}"
        temporary_created = False
        descriptor = -1
        try:
            try:
                existing_raw, existing_identity = self._read_private_entry_at(
                    directory_fd, selected.name, reason=reason
                )
            except DeployError as exc:
                if not isinstance(exc.__cause__, FileNotFoundError):
                    raise
            else:
                if not idempotent or existing_raw != raw:
                    raise DeployError(f"{reason}_already_exists")
                self._revalidate_absolute_directory(
                    selected.parent,
                    directory_identity,
                    require_private=True,
                    reason=f"{reason}_directory_changed",
                )
                return digest, existing_identity

            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                temporary_created = True
                os.fchmod(descriptor, 0o600)
                self._write_all(descriptor, raw)
                os.fsync(descriptor)
                created = os.fstat(descriptor)
                linked = os.stat(
                    temporary_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(created.st_mode)
                    or created.st_uid != os.geteuid()
                    or created.st_nlink != 1
                    or stat.S_IMODE(created.st_mode) != 0o600
                    or created.st_size != len(raw)
                    or (linked.st_dev, linked.st_ino)
                    != (created.st_dev, created.st_ino)
                ):
                    raise DeployError(f"{reason}_temporary_untrusted")
                os.close(descriptor)
                descriptor = -1
            except FileExistsError:
                temporary_raw, _identity = self._read_private_entry_at(
                    directory_fd,
                    temporary_name,
                    reason=f"{reason}_temporary",
                )
                if temporary_raw != raw:
                    raise DeployError(f"{reason}_temporary_not_owned")
            try:
                _rename_noreplace(directory_fd, temporary_name, selected.name)
                temporary_created = False
            except FileExistsError:
                existing_raw, existing_identity = self._read_private_entry_at(
                    directory_fd, selected.name, reason=reason
                )
                if not idempotent or existing_raw != raw:
                    raise DeployError(f"{reason}_already_exists")
                try:
                    stale_raw, _identity = self._read_private_entry_at(
                        directory_fd,
                        temporary_name,
                        reason=f"{reason}_temporary",
                    )
                    if stale_raw != raw:
                        raise DeployError(f"{reason}_temporary_not_owned")
                    os.unlink(temporary_name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except FileNotFoundError:
                    pass
                self._revalidate_absolute_directory(
                    selected.parent,
                    directory_identity,
                    require_private=True,
                    reason=f"{reason}_directory_changed",
                )
                return digest, existing_identity
            os.fsync(directory_fd)
            published_raw, published_identity = self._read_private_entry_at(
                directory_fd, selected.name, reason=reason
            )
            if published_raw != raw:
                raise DeployError(f"{reason}_publish_mismatch")
            self._revalidate_absolute_directory(
                selected.parent,
                directory_identity,
                require_private=True,
                reason=f"{reason}_directory_changed",
            )
            return digest, published_identity
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason}_write_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_created:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except OSError:
                    pass
            os.close(directory_fd)

    def _rewrite_operational_receipt(self, raw: bytes) -> None:
        expected_identity = self._operational_receipt_identity
        expected_raw = self._operational_receipt_raw
        if expected_identity is None or expected_raw is None:
            raise DeployError("normalization_operational_receipt_not_owned")
        directory_fd, directory_identity = self._open_absolute_directory(
            self.receipt_dir,
            require_private=True,
            reason="normalization_operational_receipt_directory_untrusted",
        )
        descriptor = -1
        try:
            named = os.stat(
                self.receipt_path.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            descriptor = os.open(
                self.receipt_path.name,
                os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            before = os.fstat(descriptor)
            if (
                self._file_identity(before) != expected_identity
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
                or before.st_size != len(expected_raw)
            ):
                raise DeployError("normalization_operational_receipt_not_owned")
            current = bytearray()
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                current.extend(chunk)
                remaining -= len(chunk)
            immediately_before = os.stat(
                self.receipt_path.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if (
                remaining
                or bytes(current) != expected_raw
                or self._file_identity(os.fstat(descriptor)) != expected_identity
                or self._file_identity(immediately_before) != expected_identity
            ):
                raise DeployError("normalization_operational_receipt_changed")
            if raw != expected_raw:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.ftruncate(descriptor, 0)
                self._write_all(descriptor, raw)
            os.fsync(descriptor)
            final = os.fstat(descriptor)
            linked = os.stat(
                self.receipt_path.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if (
                self._file_identity(final) != expected_identity
                or self._file_identity(linked) != expected_identity
                or final.st_size != len(raw)
            ):
                raise DeployError("normalization_operational_receipt_changed")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.read(descriptor, len(raw) + 1) != raw:
                raise DeployError("normalization_operational_receipt_changed")
            os.fsync(directory_fd)
            self._revalidate_absolute_directory(
                self.receipt_dir,
                directory_identity,
                require_private=True,
                reason="normalization_operational_receipt_directory_changed",
            )
            self._operational_receipt_raw = raw
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(
                "normalization_operational_receipt_write_unavailable"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_fd)

    def _write_receipt(self) -> None:
        """Publish/update only the owned, non-authoritative operation receipt."""
        raw = _private_json_bytes(self.receipt)
        if self._operational_receipt_identity is None:
            _digest, identity = self._publish_private_noreplace(
                self.receipt_path,
                raw,
                reason="normalization_operational_receipt",
                idempotent=False,
            )
            self._operational_receipt_identity = identity
            self._operational_receipt_raw = raw
            return
        self._rewrite_operational_receipt(raw)

    def _journal_bound_terminal_receipt_path(
        self, value: object, *, transaction_id: object
    ) -> Path:
        path = _normal_absolute_path(
            value, reason="normalization_terminal_receipt_path_invalid"
        )
        normalized_id = str(transaction_id or "")
        if (
            TRANSACTION_ID_RE.fullmatch(normalized_id) is None
            or path.parent != self.root / ".runtime"
            or path.name != f"{normalized_id}.json"
        ):
            raise DeployError("normalization_terminal_receipt_path_invalid")
        return path

    def _write_terminal_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        receipt_path: Path,
    ) -> str:
        raw = _private_json_bytes(dict(receipt))
        digest, _identity = self._publish_private_noreplace(
            receipt_path,
            raw,
            reason="normalization_terminal_receipt",
            idempotent=True,
        )
        return digest

    def _read_terminal_receipt(
        self, *, receipt_path: Path
    ) -> tuple[dict[str, Any], bytes, str]:
        raw = self._read_private_file(
            receipt_path,
            reason="normalization_terminal_receipt",
        )
        return (
            _strict_json(raw, reason="normalization_terminal_receipt_json_invalid"),
            raw,
            _sha256(raw),
        )

    def _read_plan(self) -> dict[str, Any]:
        payload = _strict_json(
            self._read_private_file(self.plan_path, reason="normalization_plan"),
            reason="normalization_plan_json_invalid",
        )
        try:
            validate_plan_payload(payload)
        except PlanError as exc:
            raise DeployError("normalization_plan_invalid") from exc
        return payload

    def _require_path_entry_absent(
        self,
        path: Path,
        *,
        reason: str,
        require_private_parent: bool = False,
    ) -> None:
        selected = _normal_absolute_path(path, reason=f"{reason}_path_invalid")
        parent_fd, parent_identity = self._open_absolute_directory(
            selected.parent,
            require_private=require_private_parent,
            reason=f"{reason}_parent_untrusted",
        )
        try:
            try:
                os.stat(selected.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise DeployError(f"{reason}_indeterminate") from exc
            else:
                raise DeployError(reason)
            self._revalidate_absolute_directory(
                selected.parent,
                parent_identity,
                require_private=require_private_parent,
                reason=f"{reason}_parent_changed",
            )
            try:
                os.stat(selected.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise DeployError(f"{reason}_indeterminate") from exc
            else:
                raise DeployError(reason)
            self._revalidate_absolute_directory(
                selected.parent,
                parent_identity,
                require_private=require_private_parent,
                reason=f"{reason}_parent_changed",
            )
            return
        finally:
            os.close(parent_fd)

    def _run_sanitized(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            list(args),
            cwd=cwd or self.root,
            env=self.compose_process_env,
            check=check,
        )

    def _completed_json(
        self, completed: subprocess.CompletedProcess[str], *, reason: str
    ) -> Any:
        raw = str(completed.stdout or "").encode("utf-8")
        if not 0 < len(raw) <= MAX_DOCKER_JSON_BYTES:
            raise DeployError(f"{reason}_size_invalid")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise DeployError(reason) from exc

    def _inspect_container_raw(self, name: str) -> dict[str, Any]:
        value = self._completed_json(
            self._run_sanitized(["docker", "container", "inspect", name]),
            reason=f"normalization_container_inspect_invalid:{name}",
        )
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise DeployError(f"normalization_container_inspect_invalid:{name}")
        return dict(value[0])

    def _inspect_network_raw(self) -> dict[str, Any]:
        value = self._completed_json(
            self._run_sanitized(["docker", "network", "inspect", PUBLIC_NETWORK]),
            reason="normalization_public_network_inspect_invalid",
        )
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise DeployError("normalization_public_network_inspect_invalid")
        return dict(value[0])

    def _inspect_image_optional(self, reference: str) -> dict[str, Any] | None:
        completed = self._run_sanitized(
            ["docker", "image", "inspect", reference], check=False
        )
        if completed.returncode != 0:
            normalized = f"{completed.stdout}\n{completed.stderr}".lower()
            if "no such image" in normalized or "no such object" in normalized:
                return None
            raise DeployError("normalization_image_inspect_failed")
        value = self._completed_json(
            completed, reason="normalization_image_inspect_invalid"
        )
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise DeployError("normalization_image_inspect_invalid")
        return dict(value[0])

    def _docker_daemon_identity(self) -> str:
        completed = self._run_sanitized(["docker", "info", "--format", "{{json .ID}}"])
        raw = str(completed.stdout or "").strip()
        if not 2 <= len(raw.encode("utf-8")) <= 2048:
            raise DeployError("normalization_docker_daemon_identity_invalid")
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise DeployError("normalization_docker_daemon_identity_invalid") from exc
        if (
            not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > 1024
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise DeployError("normalization_docker_daemon_identity_invalid")
        return value

    def _compose_prefix(self, bundle: Mapping[str, Any]) -> list[str]:
        bundle_root = _normal_absolute_path(
            bundle.get("bundle_path"), reason="normalization_bundle_path_invalid"
        )
        compose_files = [
            _normal_absolute_path(item, reason="normalization_bundle_compose_invalid")
            for item in list(bundle.get("compose_files") or [])
        ]
        environment_files = [
            _normal_absolute_path(item, reason="normalization_bundle_env_invalid")
            for item in list(bundle.get("environment_files") or [])
        ]
        runtime_environment_files = [
            _normal_absolute_path(
                item,
                reason="normalization_bundle_runtime_env_invalid",
            )
            for item in list(bundle.get("runtime_environment_files") or [])
        ]
        expected_compose = [bundle_root / name for name in NORMALIZATION_COMPOSE_FILES]
        expected_environment = [bundle_root / ".env"]
        if len(environment_files) == 2:
            expected_environment.append(bundle_root / ".env.local")
        expected_runtime_environment = [
            bundle_root / RUNTIME_DIRECTORY / RUNTIME_ENV_FILE,
            bundle_root / RUNTIME_DIRECTORY / RUNTIME_LOCAL_ENV_FILE,
        ]
        if (
            compose_files != expected_compose
            or environment_files != expected_environment
            or len(environment_files) not in {1, 2}
            or runtime_environment_files != expected_runtime_environment
        ):
            raise DeployError("normalization_bundle_layout_invalid")
        prefix = [
            "docker",
            "compose",
            "--project-name",
            PROJECT_NAME,
            "--project-directory",
            str(bundle_root),
        ]
        for env_file in environment_files:
            prefix.extend(["--env-file", str(env_file)])
        for compose_file in compose_files:
            prefix.extend(["-f", str(compose_file)])
        return prefix

    def _require_fresh_bundle_parent(self, bundle: Mapping[str, Any]) -> None:
        bundle_root = _normal_absolute_path(
            bundle.get("bundle_path"), reason="normalization_bundle_path_invalid"
        )
        expected_parent = _normal_absolute_path(
            self.bundle_parent, reason="bundle_parent_invalid"
        )
        if bundle_root.parent != expected_parent:
            raise DeployError("normalization_fresh_bundle_parent_mismatch")

    def _reseal_bundle(self, bundle: Mapping[str, Any]) -> dict[str, Any]:
        try:
            sealed = self.bundle_seal_validator(bundle)
        except BaselineBundleError as exc:
            raise DeployError("normalization_bundle_seal_invalid") from exc
        if dict(bundle) != sealed:
            raise DeployError("normalization_bundle_seal_changed")
        return sealed

    def _render_bundle_compose(
        self,
        bundle: Mapping[str, Any],
        *,
        expected_image_reference: str,
        expected_config_hash: str,
        reseal_bundle: Callable[[Mapping[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        if (
            self._run_sanitized(
                ["docker", "compose", "version"], check=False
            ).returncode
            != 0
        ):
            raise DeployError("normalization_docker_compose_unavailable")
        sealed = reseal_bundle(bundle)
        if sealed != dict(bundle):
            raise DeployError("normalization_bundle_seal_changed")
        prefix = self._compose_prefix(sealed)

        def run_sealed(suffix: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if reseal_bundle(sealed) != sealed:
                raise DeployError("normalization_bundle_seal_changed")
            try:
                completed = self._run_sanitized([*prefix, *suffix])
            except BaseException as action_error:
                try:
                    if reseal_bundle(sealed) != sealed:
                        raise DeployError("normalization_bundle_seal_changed")
                except BaseException as seal_error:
                    raise action_error.with_traceback(
                        action_error.__traceback__
                    ) from seal_error
                raise
            if reseal_bundle(sealed) != sealed:
                raise DeployError("normalization_bundle_seal_changed")
            return completed

        rendered = self._completed_json(
            run_sealed(["config", "--format", "json"]),
            reason="normalization_compose_render_invalid",
        )
        if not isinstance(rendered, dict) or rendered.get("name") not in {
            None,
            PROJECT_NAME,
        }:
            raise DeployError("normalization_compose_render_invalid")
        services = rendered.get("services")
        api = services.get(API_SERVICE) if isinstance(services, dict) else None
        if (
            not isinstance(api, dict)
            or str(api.get("image") or "") != expected_image_reference
            or api.get("pull_policy") != "never"
        ):
            raise DeployError("normalization_compose_api_contract_invalid")
        hash_output = (
            run_sealed(["config", "--hash", API_SERVICE]).stdout.strip().split()
        )
        if len(hash_output) == 1:
            rendered_hash = hash_output[0]
        elif len(hash_output) == 2 and hash_output[0] == API_SERVICE:
            rendered_hash = hash_output[1]
        else:
            raise DeployError("normalization_compose_hash_invalid")
        if (
            not SHA256_RE.fullmatch(rendered_hash)
            or rendered_hash != expected_config_hash
        ):
            raise DeployError("normalization_compose_hash_mismatch")
        return {
            "prefix": prefix,
            "rendered_config_hash": rendered_hash,
            "rendered_service_image": str(api["image"]),
            "pull_policy": "never",
            "service_scope": [API_SERVICE],
        }

    @staticmethod
    def _require_ready_container(
        inspection: Mapping[str, Any],
        *,
        name: str,
        require_health: bool,
    ) -> None:
        state = inspection.get("State")
        if not isinstance(state, Mapping):
            raise DeployError(f"normalization_container_state_invalid:{name}")
        health_value = state.get("Health")
        health = (
            str(health_value.get("Status") or "")
            if isinstance(health_value, Mapping)
            else ""
        )
        if (
            state.get("Running") is not True
            or state.get("Restarting") is not False
            or (require_health and health != "healthy")
            or (not require_health and health not in {"", "healthy"})
        ):
            raise DeployError(f"normalization_container_not_ready:{name}")

    @staticmethod
    def _response_header_digest(response: HttpResponse) -> str:
        raw_headers = response.headers
        if raw_headers is None:
            raw_headers = {}
        if not isinstance(raw_headers, Mapping):
            raise DeployError("normalization_public_headers_invalid")
        normalized: dict[str, str] = {}
        for raw_name, raw_value in raw_headers.items():
            if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                raise DeployError("normalization_public_headers_invalid")
            name = raw_name.strip().lower()
            value = raw_value.strip()
            if (
                not name
                or "\x00" in name
                or "\x00" in value
                or any(
                    ord(character) < 32 or ord(character) == 127 for character in name
                )
                or any(
                    ord(character) < 32 or ord(character) == 127 for character in value
                )
                or len(name.encode("utf-8")) > 256
                or len(value.encode("utf-8")) > 8192
            ):
                raise DeployError("normalization_public_headers_invalid")
            if name in normalized:
                raise DeployError("normalization_public_headers_invalid")
            normalized[name] = value
        content_type = str(response.content_type or "").strip()
        if (
            "\x00" in content_type
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in content_type
            )
            or len(content_type.encode("utf-8")) > 8192
        ):
            raise DeployError("normalization_public_headers_invalid")
        if "content-type" in normalized and normalized["content-type"] != content_type:
            raise DeployError("normalization_public_headers_invalid")
        normalized["content-type"] = content_type
        selected = {
            name.lower(): normalized.get(name.lower(), "")
            for name in SAFE_PUBLIC_HEADERS
        }
        return _sha256(_canonical_bytes(selected))

    def _capture_public_edge_once(self, public_origin: str) -> dict[str, Any]:
        probes: dict[str, Any] = {}
        for label, path in PUBLIC_EDGE_PROBES:
            for method in ("GET", "HEAD"):
                response = self.public_snapshot(
                    f"{public_origin}{path}",
                    self.request_timeout_seconds,
                    method,
                )
                if (
                    type(response.status) is not int
                    or not 100 <= response.status <= 599
                    or not isinstance(response.body, bytes)
                    or len(response.body) > MAX_HTTP_BODY_BYTES
                    or (method == "HEAD" and response.body != b"")
                ):
                    raise DeployError("normalization_public_response_invalid")
                probes[f"{label}_{method.lower()}"] = {
                    "method": method,
                    "path": path,
                    "status": response.status,
                    "body_sha256": _sha256(response.body),
                    "headers_sha256": self._response_header_digest(response),
                }
        return {
            "schema": PUBLIC_EDGE_IDENTITY_SCHEMA,
            "origin": public_origin,
            "probes": probes,
        }

    def _capture_stable_public_edge(self, public_origin: str) -> dict[str, Any]:
        first = self._capture_public_edge_once(public_origin)
        second = self._capture_public_edge_once(public_origin)
        if first != second:
            raise DeployError("normalization_public_edge_unstable")
        return first

    def _capture_runtime_evidence(self, public_origin: str) -> dict[str, Any]:
        api_raw = self._inspect_container_raw(API_SERVICE)
        self._require_ready_container(api_raw, name=API_SERVICE, require_health=True)
        cloudflared_raw = self._inspect_container_raw(CLOUDFLARED_CONTAINER)
        self._require_ready_container(
            cloudflared_raw,
            name=CLOUDFLARED_CONTAINER,
            require_health=False,
        )
        network_raw = self._inspect_network_raw()
        try:
            api_identity = self.api_projector(api_raw)
            cloudflared_identity = self.cloudflared_projector(cloudflared_raw)
            public_network_identity = self.network_projector(network_raw)
        except RuntimeIdentityError as exc:
            raise DeployError("normalization_runtime_identity_invalid") from exc
        return {
            "api_raw": api_raw,
            "api_identity": api_identity,
            "cloudflared_raw": cloudflared_raw,
            "cloudflared_identity": cloudflared_identity,
            "public_network_raw": network_raw,
            "public_network_identity": public_network_identity,
            "docker_daemon_identity": self._docker_daemon_identity(),
            "public_edge_identity": self._capture_stable_public_edge(public_origin),
        }

    def _compare_runtime_evidence(
        self,
        expected: Mapping[str, Any],
        observed: Mapping[str, Any],
        *,
        expected_api_topology: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            api_report = self.comparison_report(
                expected["api_identity"], observed["api_identity"]
            )
            cloudflared_report = self.comparison_report(
                expected["cloudflared_identity"],
                observed["cloudflared_identity"],
            )
        except (KeyError, RuntimeIdentityError) as exc:
            raise DeployError("normalization_runtime_comparison_invalid") from exc
        expected_api = expected.get("api_identity")
        observed_api = observed.get("api_identity")
        if not isinstance(expected_api, Mapping) or not isinstance(
            observed_api, Mapping
        ):
            raise DeployError("normalization_runtime_comparison_invalid")
        baseline_topology = expected_api.get("topology_label_evidence")
        observed_topology = observed_api.get("topology_label_evidence")
        required_topology = (
            baseline_topology
            if expected_api_topology is None
            else dict(expected_api_topology)
        )
        if (
            api_report.get("match") is not True
            or cloudflared_report.get("match") is not True
            or observed_topology != required_topology
            or observed.get("public_network_identity")
            != expected.get("public_network_identity")
            or observed.get("docker_daemon_identity")
            != expected.get("docker_daemon_identity")
            or observed.get("public_edge_identity")
            != expected.get("public_edge_identity")
        ):
            raise DeployError("normalization_runtime_identity_mismatch")
        return {
            "api_domain_sha256": api_report.get("observed_domain_sha256"),
            "cloudflared_domain_sha256": cloudflared_report.get(
                "observed_domain_sha256"
            ),
            "api_topology_label_evidence": observed_topology,
            "public_network_identity_sha256": _sha256(
                _canonical_bytes(observed["public_network_identity"])
            ),
            "public_edge_identity_sha256": _sha256(
                _canonical_bytes(observed["public_edge_identity"])
            ),
            "docker_daemon_identity_sha256": _sha256(
                str(observed["docker_daemon_identity"]).encode("utf-8")
            ),
        }

    def _fresh_public_origin(self) -> str:
        origin = _validate_public_origin(
            self.requested_public_origin,
            allowed_hosts=self.allowed_public_hosts,
        )
        self.public_origin = origin
        return origin

    def _git_process_environment(self) -> dict[str, str]:
        result = dict(self.compose_process_env)
        result.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_GRAFT_FILE": os.devnull,
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        return result

    def _run_git(
        self, args: Sequence[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            ["/usr/bin/git", *args],
            cwd=self.root,
            env=self._git_process_environment(),
            check=check,
        )

    def _clean_current_main(self) -> dict[str, str]:
        self.durable_root_check(self.root)
        status = self._run_git(
            ["status", "--porcelain=v1", "--untracked-files=all"]
        ).stdout
        if status:
            raise DeployError("normalization_source_worktree_dirty")
        branch = self._run_git(
            ["symbolic-ref", "--quiet", "--short", "HEAD"]
        ).stdout.strip()
        upstream = self._run_git(
            [
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ]
        ).stdout.strip()
        head = self._run_git(["rev-parse", "--verify", "HEAD"]).stdout.strip()
        origin_main = self._run_git(
            ["rev-parse", "--verify", "refs/remotes/origin/main"]
        ).stdout.strip()
        if (
            branch != "main"
            or upstream != "origin/main"
            or not REVISION_RE.fullmatch(head)
            or not REVISION_RE.fullmatch(origin_main)
            or head != origin_main
        ):
            raise DeployError("normalization_source_main_not_current")
        ancestor = self._run_git(
            ["merge-base", "--is-ancestor", head, "refs/remotes/origin/main"],
            check=False,
        )
        if ancestor.returncode != 0:
            raise DeployError("normalization_source_ancestry_invalid")
        return {
            "branch": branch,
            "upstream": upstream,
            "head": head,
            "origin_main": origin_main,
        }

    @staticmethod
    def _container_environment_value(inspection: Mapping[str, Any], name: str) -> str:
        config = inspection.get("Config")
        entries = config.get("Env") if isinstance(config, Mapping) else None
        if not isinstance(entries, list):
            raise DeployError("normalization_live_environment_invalid")
        matches: list[str] = []
        for entry in entries:
            if not isinstance(entry, str) or "\x00" in entry or "=" not in entry:
                raise DeployError("normalization_live_environment_invalid")
            key, value = entry.split("=", 1)
            if key == name:
                matches.append(value)
        if len(matches) != 1:
            raise DeployError("normalization_live_source_revision_invalid")
        return matches[0]

    @staticmethod
    def _legacy_environment_label_evidence(path: Path) -> dict[str, object]:
        selected = _normal_absolute_path(
            path,
            reason="normalization_recorded_environment_path_invalid",
        )
        try:
            parent = selected.parent.lstat()
            observed = selected.lstat()
        except OSError as exc:
            raise DeployError(
                "normalization_recorded_environment_unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_ISLNK(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) & 0o022
            or not stat.S_ISREG(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_size <= 0
            or observed.st_size > MAX_LEGACY_ENV_LABEL_FILE_BYTES
        ):
            raise DeployError("normalization_recorded_environment_untrusted")
        return {
            "device": int(observed.st_dev),
            "inode": int(observed.st_ino),
            "mode": "0600",
            "mtime_ns": int(observed.st_mtime_ns),
            "size_bytes": int(observed.st_size),
        }

    def _validate_live_split_baseline(
        self,
        *,
        plan: Mapping[str, Any],
        repository: Mapping[str, str],
        api_raw: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        activation = plan.get("activation_condition")
        source = plan.get("source_requirements")
        if not isinstance(activation, Mapping) or not isinstance(source, Mapping):
            raise DeployError("normalization_plan_invalid")
        condition = str(activation.get("condition") or "")
        expected_revision = str(source.get("expected_revision") or "")
        expected_image_id = str(source.get("expected_image_id") or "")
        expected_image_reference = str(source.get("expected_image_reference") or "")
        current_head = str(repository.get("head") or "")
        if not REVISION_RE.fullmatch(expected_revision) or not REVISION_RE.fullmatch(
            current_head
        ):
            raise DeployError("normalization_plan_source_revision_mismatch")
        exact_commit = self._run_git(
            ["cat-file", "-e", f"{expected_revision}^{{commit}}"],
            check=False,
        )
        if exact_commit.returncode != 0:
            raise DeployError("normalization_plan_source_revision_missing")
        ancestor = self._run_git(
            ["merge-base", "--is-ancestor", expected_revision, current_head],
            check=False,
        )
        if ancestor.returncode != 0:
            raise DeployError("normalization_plan_source_revision_not_ancestor")
        inspection = (
            dict(api_raw)
            if api_raw is not None
            else self._inspect_container_raw(API_SERVICE)
        )
        self._require_ready_container(inspection, name=API_SERVICE, require_health=True)
        config = inspection.get("Config")
        if not isinstance(config, Mapping):
            raise DeployError("normalization_live_api_config_invalid")
        labels = config.get("Labels")
        if not isinstance(labels, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in labels.items()
        ):
            raise DeployError("normalization_live_api_labels_invalid")
        recorded_root = _normal_absolute_path(
            activation.get("recorded_working_dir"),
            reason="normalization_recorded_working_dir_invalid",
        )
        external_files = list(activation.get("ordered_external_config_files") or [])
        external_root = _normal_absolute_path(
            activation.get("external_config_root"),
            reason="normalization_external_config_root_invalid",
        )
        if condition == SPLIT_BASELINE_CONDITION:
            expected_external_files = [
                str(external_root / "docker-compose.yml"),
                str(external_root / "docker-compose.memorial.yml"),
            ]
            layout_valid = (
                recorded_root != external_root
                and activation.get("recorded_environment_expectation") == "missing"
            )
        elif condition == COLOCATED_LEGACY_ENV_CONDITION:
            expected_external_files = [
                str(external_root / name)
                for name in COLOCATED_LEGACY_COMPOSE_FILES
            ]
            layout_valid = (
                recorded_root == external_root
                and activation.get("recorded_environment_expectation")
                == "legacy_private_file_present_unread"
            )
        else:
            raise DeployError("normalization_baseline_condition_invalid")
        if (
            not layout_valid
            or external_files != expected_external_files
            or any(not isinstance(item, str) for item in external_files)
        ):
            raise DeployError("normalization_external_compose_labels_invalid")
        expected_environment_label = str(recorded_root / ".env")
        config_hash = str(labels.get(CONFIG_HASH_LABEL) or "")
        if (
            labels.get("com.docker.compose.project") != PROJECT_NAME
            or labels.get("com.docker.compose.service") != API_SERVICE
            or labels.get("com.docker.compose.project.working_dir")
            != str(recorded_root)
            or labels.get("com.docker.compose.project.config_files")
            != ",".join(external_files)
            or labels.get("com.docker.compose.project.environment_file")
            != expected_environment_label
            or not SHA256_RE.fullmatch(config_hash)
            or str(config.get("Image") or "") != expected_image_reference
            or str(inspection.get("Image") or "") != expected_image_id
            or self._container_environment_value(inspection, "EA_SOURCE_REVISION")
            != expected_revision
        ):
            raise DeployError("normalization_live_split_baseline_mismatch")
        # Historical Compose paths are label evidence only; never open their
        # mutable bytes. Split baselines require the old environment path to be
        # absent. The co-located legacy baseline admits only a private regular
        # file and records metadata so any concurrent change fails revalidation.
        recorded_environment_evidence: dict[str, object] = {}
        if condition == SPLIT_BASELINE_CONDITION:
            self._require_path_entry_absent(
                recorded_root / ".env",
                reason="normalization_recorded_environment_not_absent",
            )
        else:
            recorded_environment_evidence = (
                self._legacy_environment_label_evidence(recorded_root / ".env")
            )
        image = self._inspect_image_optional(expected_image_reference)
        if image is None:
            raise DeployError("normalization_expected_image_missing")
        image_config = image.get("Config")
        image_labels = (
            image_config.get("Labels") if isinstance(image_config, Mapping) else None
        )
        if (
            str(image.get("Id") or "") != expected_image_id
            or not isinstance(image_labels, Mapping)
            or image_labels.get(REVISION_LABEL) != expected_revision
        ):
            raise DeployError("normalization_image_source_triplet_mismatch")
        return {
            "api_raw": inspection,
            "config_hash": config_hash,
            "expected_revision": expected_revision,
            "expected_image_id": expected_image_id,
            "expected_image_reference": expected_image_reference,
            "baseline_condition": condition,
            "recorded_working_dir": str(recorded_root),
            "recorded_environment_label": expected_environment_label,
            "recorded_environment_evidence": recorded_environment_evidence,
            "ordered_external_config_files": external_files,
        }

    def _require_rollback_tag_absent(self) -> str:
        rollback_tag = deterministic_rollback_tag(self.deployment_id)
        if self._inspect_image_optional(rollback_tag) is not None:
            raise DeployError("normalization_rollback_tag_already_exists")
        return rollback_tag

    def _private_fresh_bundle_parent(self) -> Path:
        parent = _normal_absolute_path(
            self.bundle_parent, reason="bundle_parent_invalid"
        )
        self.durable_root_check(parent)
        descriptor, _identity = self._open_absolute_directory(
            parent,
            require_private=True,
            reason="normalization_bundle_parent_untrusted",
        )
        os.close(descriptor)
        self.bundle_parent = parent
        return parent

    @staticmethod
    def _require_bundle_repository_binding(
        bundle: Mapping[str, Any], repository: Mapping[str, str]
    ) -> None:
        head = str(repository.get("head") or "")
        origin_main = str(repository.get("origin_main") or "")
        if (
            not REVISION_RE.fullmatch(head)
            or origin_main != head
            or bundle.get("origin_main_commit") != head
        ):
            raise DeployError("normalization_bundle_origin_main_mismatch")

    def _materialize_fresh_bundle(
        self,
        plan: Mapping[str, Any],
        bundle_parent: Path,
        repository: Mapping[str, str],
        render_environment: Mapping[str, str],
        baseline_environment_names: frozenset[str],
    ) -> dict[str, Any]:
        try:
            bundle = self.bundle_materializer(
                plan=plan,
                repository_root=self.root,
                bundle_parent=bundle_parent,
                render_environment=render_environment,
                baseline_environment_names=baseline_environment_names,
            )
        except BaselineBundleError as exc:
            raise DeployError("normalization_bundle_materialization_failed") from exc
        sealed = self._reseal_bundle(bundle)
        self._require_fresh_bundle_parent(sealed)
        source = plan.get("source_requirements")
        expected_revision = (
            str(source.get("expected_revision") or "")
            if isinstance(source, Mapping)
            else ""
        )
        if sealed.get("source_revision") != expected_revision:
            raise DeployError("normalization_bundle_source_revision_mismatch")
        self._require_bundle_repository_binding(sealed, repository)
        return sealed

    @staticmethod
    def _live_bundle_render_environment(
        live: Mapping[str, Any],
    ) -> dict[str, str]:
        inspection = live.get("api_raw")
        if not isinstance(inspection, Mapping):
            raise DeployError("normalization_live_api_config_invalid")
        config = inspection.get("Config")
        if not isinstance(config, Mapping):
            raise DeployError("normalization_live_api_config_invalid")
        expected_revision = str(live.get("expected_revision") or "")
        expected_image_reference = str(live.get("expected_image_reference") or "")
        derived = _memorial_rollback_environment(
            config=config,
            mount_identities=_mount_identities(inspection),
            image_reference=expected_image_reference,
        )
        selected = {name: derived[name] for name in sorted(BASELINE_RENDER_ENV_KEYS)}
        if (
            set(selected) != BASELINE_RENDER_ENV_KEYS
            or selected.get("EA_SOURCE_REVISION") != expected_revision
            or selected.get("EA_MEMORIAL_IMAGE") != expected_image_reference
        ):
            raise DeployError("normalization_live_render_environment_invalid")
        return selected

    @staticmethod
    def _live_bundle_environment_names(
        live: Mapping[str, Any],
    ) -> frozenset[str]:
        inspection = live.get("api_raw")
        config = inspection.get("Config") if isinstance(inspection, Mapping) else None
        entries = config.get("Env") if isinstance(config, Mapping) else None
        if not isinstance(entries, list):
            raise DeployError("normalization_live_environment_invalid")
        names: set[str] = set()
        for entry in entries:
            if not isinstance(entry, str) or "\x00" in entry or "=" not in entry:
                raise DeployError("normalization_live_environment_invalid")
            name, _value = entry.split("=", 1)
            if ENV_NAME_RE.fullmatch(name) is None or name in names:
                raise DeployError("normalization_live_environment_invalid")
            names.add(name)
        return frozenset(names)

    def _prepare_fresh(self) -> dict[str, Any]:
        public_origin = self._fresh_public_origin()
        bundle_parent = self._private_fresh_bundle_parent()
        repository_before = self._clean_current_main()
        plan = self._read_plan()
        live_before = self._validate_live_split_baseline(
            plan=plan,
            repository=repository_before,
        )
        rollback_tag = self._require_rollback_tag_absent()
        runtime_before = self._capture_runtime_evidence(public_origin)
        render_live_before = self._validate_live_split_baseline(
            plan=plan,
            repository=repository_before,
            api_raw=runtime_before["api_raw"],
        )
        render_environment = self._live_bundle_render_environment(render_live_before)
        baseline_environment_names = self._live_bundle_environment_names(
            render_live_before
        )

        bundle = self._materialize_fresh_bundle(
            plan,
            bundle_parent,
            repository_before,
            render_environment,
            baseline_environment_names,
        )
        compose_before = self._render_bundle_compose(
            bundle,
            expected_image_reference=live_before["expected_image_reference"],
            expected_config_hash=live_before["config_hash"],
            reseal_bundle=self._reseal_bundle,
        )

        repository_after = self._clean_current_main()
        if repository_after != repository_before:
            raise DeployError("normalization_source_changed_during_preflight")
        bundle = self._reseal_bundle(bundle)
        self._require_fresh_bundle_parent(bundle)
        self._require_bundle_repository_binding(bundle, repository_after)
        compose_after = self._render_bundle_compose(
            bundle,
            expected_image_reference=live_before["expected_image_reference"],
            expected_config_hash=live_before["config_hash"],
            reseal_bundle=self._reseal_bundle,
        )
        if compose_after != compose_before:
            raise DeployError("normalization_compose_changed_during_preflight")
        runtime_after = self._capture_runtime_evidence(public_origin)
        live_after = self._validate_live_split_baseline(
            plan=plan,
            repository=repository_after,
            api_raw=runtime_after["api_raw"],
        )
        if {key: value for key, value in live_after.items() if key != "api_raw"} != {
            key: value for key, value in live_before.items() if key != "api_raw"
        }:
            raise DeployError("normalization_live_baseline_changed")
        if self._live_bundle_render_environment(live_after) != render_environment:
            raise DeployError("normalization_live_render_environment_changed")
        if (
            self._live_bundle_environment_names(live_after)
            != baseline_environment_names
        ):
            raise DeployError("normalization_live_environment_names_changed")
        runtime_comparison = self._compare_runtime_evidence(
            runtime_before, runtime_after
        )
        if self._require_rollback_tag_absent() != rollback_tag:
            raise DeployError("normalization_rollback_tag_identity_changed")
        return {
            "plan": plan,
            "repository": repository_after,
            "live": live_after,
            "bundle": bundle,
            "compose": compose_after,
            "runtime": runtime_after,
            "runtime_comparison": runtime_comparison,
            "public_origin": public_origin,
            "rollback_tag": rollback_tag,
        }

    @staticmethod
    def _prepared_mapping(prepared: Mapping[str, Any], name: str) -> Mapping[str, Any]:
        value = prepared.get(name)
        if not isinstance(value, Mapping):
            raise DeployError("normalization_prepared_evidence_invalid")
        return value

    def _require_canonical_journal(self, expected: Mapping[str, Any]) -> dict[str, Any]:
        current = self.journal.read()
        if current is None or current != dict(expected):
            raise DeployError("normalization_journal_not_owned")
        return current

    def _require_protected_image(
        self, rollback_tag: str, expected_image_id: str
    ) -> dict[str, Any]:
        inspection = self._inspect_image_optional(rollback_tag)
        tags = inspection.get("RepoTags") if inspection is not None else None
        if (
            inspection is None
            or str(inspection.get("Id") or "") != expected_image_id
            or not isinstance(tags, list)
            or any(not isinstance(item, str) for item in tags)
            or rollback_tag not in tags
        ):
            raise DeployError("normalization_protected_image_mismatch")
        return inspection

    def _revalidate_static_forward_inputs(
        self, prepared: Mapping[str, Any]
    ) -> dict[str, Any]:
        expected_repository = self._prepared_mapping(prepared, "repository")
        repository = self._clean_current_main()
        if repository != dict(expected_repository):
            raise DeployError("normalization_source_changed_during_transaction")
        expected_plan = self._prepared_mapping(prepared, "plan")
        plan = self._read_plan()
        if plan != dict(expected_plan):
            raise DeployError("normalization_plan_changed_during_transaction")
        expected_bundle = self._prepared_mapping(prepared, "bundle")
        bundle = self._reseal_bundle(expected_bundle)
        self._require_fresh_bundle_parent(bundle)
        self._require_bundle_repository_binding(bundle, repository)
        expected_live = self._prepared_mapping(prepared, "live")
        expected_compose = self._prepared_mapping(prepared, "compose")
        compose = self._render_bundle_compose(
            bundle,
            expected_image_reference=str(
                expected_live.get("expected_image_reference") or ""
            ),
            expected_config_hash=str(expected_live.get("config_hash") or ""),
            reseal_bundle=self._reseal_bundle,
        )
        if compose != dict(expected_compose):
            raise DeployError("normalization_compose_changed_during_transaction")
        return bundle

    def _revalidate_forward_baseline(
        self,
        prepared: Mapping[str, Any],
        *,
        protected_image_required: bool,
    ) -> dict[str, Any]:
        self._revalidate_static_forward_inputs(prepared)
        plan = self._prepared_mapping(prepared, "plan")
        repository = self._prepared_mapping(prepared, "repository")
        expected_live = self._prepared_mapping(prepared, "live")
        expected_runtime = self._prepared_mapping(prepared, "runtime")
        public_origin = str(prepared.get("public_origin") or "")
        observed_runtime = self._capture_runtime_evidence(public_origin)
        observed_live = self._validate_live_split_baseline(
            plan=plan,
            repository={str(key): str(value) for key, value in repository.items()},
            api_raw=observed_runtime["api_raw"],
        )
        if {key: value for key, value in observed_live.items() if key != "api_raw"} != {
            key: value for key, value in expected_live.items() if key != "api_raw"
        }:
            raise DeployError("normalization_live_baseline_changed")
        self._compare_runtime_evidence(expected_runtime, observed_runtime)
        rollback_tag = str(prepared.get("rollback_tag") or "")
        expected_image_id = str(expected_live.get("expected_image_id") or "")
        if protected_image_required:
            self._require_protected_image(rollback_tag, expected_image_id)
        elif self._inspect_image_optional(rollback_tag) is not None:
            raise DeployError("normalization_rollback_tag_already_exists")
        return observed_runtime

    def _new_forward_journal_payload(
        self, prepared: Mapping[str, Any]
    ) -> dict[str, Any]:
        bundle = self._prepared_mapping(prepared, "bundle")
        live = self._prepared_mapping(prepared, "live")
        runtime = self._prepared_mapping(prepared, "runtime")
        compose_files = [
            _normal_absolute_path(item, reason="normalization_bundle_compose_invalid")
            for item in list(bundle.get("compose_files") or [])
        ]
        environment_files = [
            _normal_absolute_path(item, reason="normalization_bundle_env_invalid")
            for item in list(bundle.get("environment_files") or [])
        ]
        runtime_environment_files = [
            _normal_absolute_path(
                item,
                reason="normalization_bundle_runtime_env_invalid",
            )
            for item in list(bundle.get("runtime_environment_files") or [])
        ]
        bundle_root = _normal_absolute_path(
            bundle.get("bundle_path"), reason="normalization_bundle_path_invalid"
        )
        expected_runtime_environment = [
            bundle_root / RUNTIME_DIRECTORY / RUNTIME_ENV_FILE,
            bundle_root / RUNTIME_DIRECTORY / RUNTIME_LOCAL_ENV_FILE,
        ]
        if (
            len(compose_files) != 3
            or len(environment_files) not in {1, 2}
            or runtime_environment_files != expected_runtime_environment
        ):
            raise DeployError("normalization_bundle_layout_invalid")
        return self.journal.new_payload(
            transaction_id=self.deployment_id,
            release_root=self.root,
            transaction_receipt_path=self.transaction_receipt_path,
            public_origin=str(prepared.get("public_origin") or ""),
            retained_bundle_path=bundle_root,
            retained_bundle_manifest_path=_normal_absolute_path(
                bundle.get("manifest_path"),
                reason="normalization_bundle_manifest_invalid",
            ),
            retained_bundle_manifest_sha256=str(bundle.get("manifest_sha256") or ""),
            retained_bundle_plan_sha256=str(bundle.get("plan_sha256") or ""),
            ordered_compose_files=compose_files,
            environment_file=environment_files[0],
            environment_local_file=(
                environment_files[1] if len(environment_files) == 2 else None
            ),
            source_revision=str(live.get("expected_revision") or ""),
            image_id=str(live.get("expected_image_id") or ""),
            image_reference=str(live.get("expected_image_reference") or ""),
            compose_config_hash=str(live.get("config_hash") or ""),
            docker_daemon_identity=str(runtime.get("docker_daemon_identity") or ""),
            api_identity=self._prepared_mapping(runtime, "api_identity"),
            cloudflared_identity=self._prepared_mapping(
                runtime, "cloudflared_identity"
            ),
            public_network_identity=self._prepared_mapping(
                runtime, "public_network_identity"
            ),
            public_edge_identity=self._prepared_mapping(
                runtime, "public_edge_identity"
            ),
            now=self.now(),
        )

    def _persist_phase(self, payload: Mapping[str, Any], phase: str) -> dict[str, Any]:
        replacement = self.journal.with_phase(payload, phase, now=self.now())
        self.journal.update(expected=payload, replacement=replacement)
        return replacement

    def _protect_previous_image(
        self, payload: Mapping[str, Any], prepared: Mapping[str, Any]
    ) -> dict[str, Any]:
        live = self._prepared_mapping(prepared, "live")
        rollback_tag = str(prepared.get("rollback_tag") or "")
        expected_image_id = str(live.get("expected_image_id") or "")
        with self._bounded_mutation_action():
            self._require_canonical_journal(payload)
            self._revalidate_forward_baseline(prepared, protected_image_required=False)
            self._remaining_mutation_action_seconds()
            payload = self._persist_phase(payload, "protect_previous_image_possible")
            if self._inspect_image_optional(rollback_tag) is not None:
                raise DeployError("normalization_rollback_tag_already_exists")
            self._remaining_mutation_action_seconds()
            self._run_sanitized(
                ["docker", "image", "tag", expected_image_id, rollback_tag]
            )
            protected = self._require_protected_image(rollback_tag, expected_image_id)
            replacement = self.journal.record_protected_image(
                payload,
                observed_image_id=str(protected.get("Id") or ""),
                observed_rollback_tag=rollback_tag,
                now=self.now(),
            )
            self.journal.update(expected=payload, replacement=replacement)
            return replacement

    def _sealed_api_recreate(self, bundle: Mapping[str, Any]) -> None:
        sealed = self._reseal_bundle(bundle)
        prefix = self._compose_prefix(sealed)
        try:
            self._run_sanitized(
                [
                    *prefix,
                    "up",
                    "-d",
                    "--no-build",
                    "--pull",
                    "never",
                    "--no-deps",
                    "--force-recreate",
                    API_SERVICE,
                ]
            )
        except BaseException as action_error:
            try:
                if self._reseal_bundle(sealed) != sealed:
                    raise DeployError("normalization_bundle_seal_changed")
            except BaseException as seal_error:
                raise action_error.with_traceback(
                    action_error.__traceback__
                ) from seal_error
            raise
        if self._reseal_bundle(sealed) != sealed:
            raise DeployError("normalization_bundle_seal_changed")

    def _wait_api_healthy(self) -> dict[str, Any]:
        deadline = self.monotonic() + self.wait_seconds
        last_reason = "normalization_api_not_ready"
        while True:
            try:
                inspection = self._inspect_container_raw(API_SERVICE)
                self._require_ready_container(
                    inspection, name=API_SERVICE, require_health=True
                )
                return inspection
            except DeployError as exc:
                last_reason = str(exc)
            if self.monotonic() >= deadline:
                raise DeployError(f"normalization_api_health_exhausted:{last_reason}")
            self.sleep(self.poll_seconds)

    def _validate_terminal_api(
        self,
        api_raw: Mapping[str, Any],
        *,
        prepared: Mapping[str, Any],
        bundle: Mapping[str, Any],
    ) -> None:
        live = self._prepared_mapping(prepared, "live")
        config = api_raw.get("Config")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        if not isinstance(config, Mapping) or not isinstance(labels, Mapping):
            raise DeployError("normalization_terminal_api_invalid")
        compose_files = [str(item) for item in list(bundle.get("compose_files") or [])]
        environment_files = [
            str(item) for item in list(bundle.get("environment_files") or [])
        ]
        expected_topology = {
            "com.docker.compose.project.working_dir": str(
                bundle.get("bundle_path") or ""
            ),
            "com.docker.compose.project.config_files": ",".join(compose_files),
            "com.docker.compose.project.environment_file": ",".join(environment_files),
        }
        expected_image_id = str(live.get("expected_image_id") or "")
        expected_image_reference = str(live.get("expected_image_reference") or "")
        if (
            labels.get("com.docker.compose.project") != PROJECT_NAME
            or labels.get("com.docker.compose.service") != API_SERVICE
            or any(labels.get(key) != value for key, value in expected_topology.items())
            or labels.get(CONFIG_HASH_LABEL) != live.get("config_hash")
            or str(config.get("Image") or "") != expected_image_reference
            or str(api_raw.get("Image") or "") != expected_image_id
            or self._container_environment_value(api_raw, "EA_SOURCE_REVISION")
            != live.get("expected_revision")
        ):
            raise DeployError("normalization_terminal_api_mismatch")
        image = self._inspect_image_optional(expected_image_reference)
        image_config = image.get("Config") if image is not None else None
        image_labels = (
            image_config.get("Labels") if isinstance(image_config, Mapping) else None
        )
        if (
            image is None
            or str(image.get("Id") or "") != expected_image_id
            or not isinstance(image_labels, Mapping)
            or image_labels.get(REVISION_LABEL) != live.get("expected_revision")
        ):
            raise DeployError("normalization_terminal_image_mismatch")

    def _capture_terminal_forward_evidence(
        self,
        *,
        prepared: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        bundle = self._revalidate_static_forward_inputs(prepared)
        self._wait_api_healthy()
        runtime = self._capture_runtime_evidence(
            str(prepared.get("public_origin") or "")
        )
        self._validate_terminal_api(
            runtime["api_raw"], prepared=prepared, bundle=bundle
        )
        baselines = self._prepared_mapping(payload, "baselines")
        target_topology = self._prepared_mapping(
            baselines, "target_api_topology_label_evidence"
        )
        comparison = self._compare_runtime_evidence(
            self._prepared_mapping(prepared, "runtime"),
            runtime,
            expected_api_topology=target_topology,
        )
        previous_image = self._prepared_mapping(payload, "previous_image")
        protected = self._require_protected_image(
            str(previous_image.get("rollback_tag") or ""),
            str(previous_image.get("image_id") or ""),
        )
        return {
            "runtime": runtime,
            "protected_image": protected,
            "comparison": comparison,
        }

    def _authorize_and_recreate_api(
        self, payload: Mapping[str, Any], prepared: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        bundle = self._prepared_mapping(prepared, "bundle")
        with self._bounded_mutation_action():
            self._require_canonical_journal(payload)
            self._revalidate_forward_baseline(prepared, protected_image_required=True)
            self._remaining_mutation_action_seconds()
            payload = self._persist_phase(payload, "api_mutation_possible")
            self._remaining_mutation_action_seconds()
            self._sealed_api_recreate(bundle)
        terminal = self._capture_terminal_forward_evidence(
            prepared=prepared, payload=payload
        )
        runtime = self._prepared_mapping(terminal, "runtime")
        replacement = self.journal.record_api_mutation(
            payload,
            observed_api_identity=self._prepared_mapping(runtime, "api_identity"),
            now=self.now(),
        )
        self.journal.update(expected=payload, replacement=replacement)
        return replacement, terminal

    def _durable_forward_commit(
        self,
        payload: Mapping[str, Any],
        terminal: Mapping[str, Any],
    ) -> dict[str, Any]:
        runtime = self._prepared_mapping(terminal, "runtime")
        protected = self._prepared_mapping(terminal, "protected_image")
        baselines = self._prepared_mapping(payload, "baselines")
        baseline_api = self._prepared_mapping(baselines, "api_identity")
        baseline_projection = self._prepared_mapping(baseline_api, "projection")
        observation = self.terminal_observation_builder(
            api_identity=self._prepared_mapping(runtime, "api_identity"),
            cloudflared_identity=self._prepared_mapping(
                runtime, "cloudflared_identity"
            ),
            public_network_identity=self._prepared_mapping(
                runtime, "public_network_identity"
            ),
            public_edge_identity=self._prepared_mapping(
                runtime, "public_edge_identity"
            ),
            docker_daemon_identity=str(runtime.get("docker_daemon_identity") or ""),
            observed_protected_image_id=str(protected.get("Id") or ""),
            expected_protected_image_id=str(
                self._prepared_mapping(payload, "previous_image").get("image_id") or ""
            ),
            compose_config_hash=str(baselines.get("compose_config_hash") or ""),
            public_origin=str(payload.get("public_origin") or ""),
            baseline_api_topology_label_evidence=self._prepared_mapping(
                baseline_projection, "topology_label_evidence"
            ),
            target_api_topology_label_evidence=self._prepared_mapping(
                baselines, "target_api_topology_label_evidence"
            ),
        )
        if observation.get("normalization_completed") is not True:
            raise DeployError("normalization_terminal_observation_incomplete")
        completed_at = self.now()
        receipt = self.terminal_receipt_builder(
            payload,
            kind="durable_commit",
            observation=observation,
            completed_at=completed_at,
        )
        receipt_path = self._journal_bound_terminal_receipt_path(
            payload.get("transaction_receipt_path"),
            transaction_id=payload.get("transaction_id"),
        )
        receipt_sha256 = self._write_terminal_receipt(
            receipt, receipt_path=receipt_path
        )
        replacement = self.journal.record_terminal_evidence(
            payload,
            kind="durable_commit",
            receipt_sha256=receipt_sha256,
            observed_api_identity=self._prepared_mapping(runtime, "api_identity"),
            observed_cloudflared_identity=self._prepared_mapping(
                runtime, "cloudflared_identity"
            ),
            observed_public_network_identity=self._prepared_mapping(
                runtime, "public_network_identity"
            ),
            observed_public_edge_identity=self._prepared_mapping(
                runtime, "public_edge_identity"
            ),
            observed_docker_daemon_identity=str(
                runtime.get("docker_daemon_identity") or ""
            ),
            observed_protected_image_id=str(protected.get("Id") or ""),
            now=completed_at,
        )
        self.journal.update(expected=payload, replacement=replacement)
        payload = replacement
        payload = self._persist_phase(payload, "commit_pending")
        try:
            self.journal.remove(expected=payload)
        except BaseException:
            active = self.journal.read()
            if active is not None:
                raise
            existing, raw, existing_sha256 = self._read_terminal_receipt(
                receipt_path=receipt_path
            )
            if (
                existing != receipt
                or raw != _private_json_bytes(receipt)
                or existing_sha256 != receipt_sha256
            ):
                raise DeployError(
                    "normalization_terminal_receipt_changed_after_cleanup"
                )
        return receipt

    def _mark_rollback_failed_if_allowed(self) -> None:
        current = self.journal.read()
        if current is None or current.get("phase") != "rollback_in_progress":
            return
        replacement = self.journal.with_phase(
            current, "rollback_failed", now=self.now()
        )
        self.journal.update(expected=current, replacement=replacement)

    def _recover_forward_failure(
        self,
        original: BaseException,
        *,
        transaction_id: str,
    ) -> dict[str, Any]:
        active = self.journal.read()
        if active is None or active.get("transaction_id") != transaction_id:
            raise original.with_traceback(original.__traceback__)
        try:
            return self._recover(active)
        except BaseException as recovery_error:
            try:
                self._mark_rollback_failed_if_allowed()
            except BaseException as mark_error:
                try:
                    recovery_error.add_note(
                        "rollback_failed journal marking also failed: "
                        f"{type(mark_error).__name__}"
                    )
                except AttributeError:
                    pass
            raise original.with_traceback(original.__traceback__) from recovery_error

    def _normalize(self, prepared: Mapping[str, Any]) -> dict[str, Any]:
        """Execute the forward transaction and durable commit."""
        payload = self._new_forward_journal_payload(prepared)
        transaction_id = str(payload.get("transaction_id") or "")
        journal_created = False
        try:
            try:
                self.journal.create(payload)
                journal_created = True
            except BaseException:
                active = self.journal.read()
                if active != payload:
                    raise
                journal_created = True
                raise
            payload = self._protect_previous_image(payload, prepared)
            payload, terminal = self._authorize_and_recreate_api(payload, prepared)
            return self._durable_forward_commit(payload, terminal)
        except BaseException as original:
            if not journal_created:
                raise
            return self._recover_forward_failure(
                original, transaction_id=transaction_id
            )

    def _load_recovery_bundle(
        self, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], Callable[[], dict[str, Any]]]:
        retained = self._prepared_mapping(payload, "retained_bundle")
        recovery_seal = self._prepared_mapping(retained, "recovery_seal")
        bundle_path = _normal_absolute_path(
            retained.get("path"), reason="normalization_recovery_bundle_invalid"
        )
        expected_compose = list(retained.get("ordered_compose_files") or [])
        expected_environment = [str(retained.get("environment_file") or "")]
        local_file = retained.get("environment_local_file")
        if local_file is not None:
            expected_environment.append(str(local_file))
        expected_runtime_environment = [
            str(bundle_path / RUNTIME_DIRECTORY / RUNTIME_ENV_FILE),
            str(bundle_path / RUNTIME_DIRECTORY / RUNTIME_LOCAL_ENV_FILE),
        ]

        def reseal() -> dict[str, Any]:
            try:
                current = self.recovery_bundle_validator(
                    bundle_path=bundle_path,
                    trusted_recovery_seal=dict(recovery_seal),
                )
            except BaselineBundleError as exc:
                raise DeployError("normalization_recovery_bundle_seal_invalid") from exc
            if (
                not isinstance(current, dict)
                or set(current)
                != {
                    "bundle_path",
                    "compose_files",
                    "contract_name",
                    "environment_files",
                    "manifest_path",
                    "manifest_sha256",
                    "origin_main_commit",
                    "plan_sha256",
                    "runtime_environment_files",
                    "source_revision",
                    "version",
                }
                or current.get("contract_name") != BUNDLE_CONTRACT
                or current.get("version") != BUNDLE_VERSION
                or current.get("bundle_path") != str(bundle_path)
                or current.get("manifest_path")
                != str(retained.get("manifest_path") or "")
                or current.get("manifest_sha256")
                != recovery_seal.get("manifest_sha256")
                or current.get("plan_sha256") != recovery_seal.get("plan_sha256")
                or current.get("source_revision") != payload.get("source_revision")
                or current.get("compose_files") != expected_compose
                or current.get("environment_files") != expected_environment
                or current.get("runtime_environment_files")
                != expected_runtime_environment
                or REVISION_RE.fullmatch(str(current.get("origin_main_commit") or ""))
                is None
            ):
                raise DeployError("normalization_recovery_bundle_binding_mismatch")
            return dict(current)

        bundle = reseal()
        return bundle, reseal

    def _run_recovery_bundle_command(
        self,
        bundle: Mapping[str, Any],
        reseal: Callable[[], dict[str, Any]],
        suffix: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        sealed_before = reseal()
        if sealed_before != dict(bundle):
            raise DeployError("normalization_recovery_bundle_changed")
        prefix = self._compose_prefix(sealed_before)
        try:
            completed = self._run_sanitized([*prefix, *suffix])
        except BaseException as action_error:
            try:
                sealed_after = reseal()
                if sealed_after != sealed_before:
                    raise DeployError("normalization_recovery_bundle_changed")
            except BaseException as seal_error:
                raise action_error.with_traceback(
                    action_error.__traceback__
                ) from seal_error
            raise
        sealed_after = reseal()
        if sealed_after != sealed_before:
            raise DeployError("normalization_recovery_bundle_changed")
        return completed

    def _render_recovery_bundle_compose(
        self,
        payload: Mapping[str, Any],
        bundle: Mapping[str, Any],
        reseal: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if (
            self._run_sanitized(
                ["docker", "compose", "version"], check=False
            ).returncode
            != 0
        ):
            raise DeployError("normalization_docker_compose_unavailable")
        previous_image = self._prepared_mapping(payload, "previous_image")
        baselines = self._prepared_mapping(payload, "baselines")
        rendered = self._completed_json(
            self._run_recovery_bundle_command(
                bundle,
                reseal,
                ["config", "--format", "json"],
            ),
            reason="normalization_recovery_compose_render_invalid",
        )
        services = rendered.get("services") if isinstance(rendered, Mapping) else None
        api = services.get(API_SERVICE) if isinstance(services, Mapping) else None
        if (
            not isinstance(rendered, Mapping)
            or rendered.get("name") not in {None, PROJECT_NAME}
            or not isinstance(api, Mapping)
            or api.get("image") != previous_image.get("image_reference")
            or api.get("pull_policy") != "never"
        ):
            raise DeployError("normalization_recovery_compose_contract_invalid")
        hash_output = (
            self._run_recovery_bundle_command(
                bundle,
                reseal,
                ["config", "--hash", API_SERVICE],
            )
            .stdout.strip()
            .split()
        )
        if len(hash_output) == 1:
            rendered_hash = hash_output[0]
        elif len(hash_output) == 2 and hash_output[0] == API_SERVICE:
            rendered_hash = hash_output[1]
        else:
            raise DeployError("normalization_recovery_compose_hash_invalid")
        if not SHA256_RE.fullmatch(rendered_hash) or rendered_hash != baselines.get(
            "compose_config_hash"
        ):
            raise DeployError("normalization_recovery_compose_hash_mismatch")
        return {
            "prefix": self._compose_prefix(bundle),
            "rendered_config_hash": rendered_hash,
            "rendered_service_image": str(api["image"]),
            "pull_policy": "never",
            "service_scope": [API_SERVICE],
        }

    def _recovery_bundle_api_up(
        self,
        bundle: Mapping[str, Any],
        reseal: Callable[[], dict[str, Any]],
    ) -> None:
        self._run_recovery_bundle_command(
            bundle,
            reseal,
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            ],
        )

    def _journal_projection(
        self, payload: Mapping[str, Any], name: str
    ) -> Mapping[str, Any]:
        baselines = self._prepared_mapping(payload, "baselines")
        wrapper = self._prepared_mapping(baselines, name)
        return self._prepared_mapping(wrapper, "projection")

    def _require_recovery_source_image(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        previous = self._prepared_mapping(payload, "previous_image")
        image_reference = str(previous.get("image_reference") or "")
        expected_image_id = str(previous.get("image_id") or "")
        inspection = self._inspect_image_optional(image_reference)
        config = inspection.get("Config") if inspection is not None else None
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        if (
            inspection is None
            or str(inspection.get("Id") or "") != expected_image_id
            or not isinstance(labels, Mapping)
            or labels.get(REVISION_LABEL) != payload.get("source_revision")
        ):
            raise DeployError("normalization_recovery_source_image_mismatch")
        return inspection

    def _inspect_container_optional(self, name: str) -> dict[str, Any] | None:
        completed = self._run_sanitized(
            ["docker", "container", "inspect", name], check=False
        )
        if completed.returncode != 0:
            normalized = f"{completed.stdout}\n{completed.stderr}".lower()
            if "no such container" in normalized or "no such object" in normalized:
                return None
            raise DeployError(f"normalization_container_inspect_failed:{name}")
        value = self._completed_json(
            completed, reason=f"normalization_container_inspect_invalid:{name}"
        )
        if (
            not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise DeployError(f"normalization_container_inspect_invalid:{name}")
        return dict(value[0])

    def _require_recovery_api_raw_binding(
        self, payload: Mapping[str, Any], api_raw: Mapping[str, Any]
    ) -> None:
        previous = self._prepared_mapping(payload, "previous_image")
        baselines = self._prepared_mapping(payload, "baselines")
        config = api_raw.get("Config")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        if (
            not isinstance(config, Mapping)
            or not isinstance(labels, Mapping)
            or labels.get("com.docker.compose.project") != PROJECT_NAME
            or labels.get("com.docker.compose.service") != API_SERVICE
            or labels.get(CONFIG_HASH_LABEL) != baselines.get("compose_config_hash")
            or config.get("Image") != previous.get("image_reference")
            or api_raw.get("Image") != previous.get("image_id")
            or self._container_environment_value(api_raw, "EA_SOURCE_REVISION")
            != payload.get("source_revision")
        ):
            raise DeployError("normalization_recovery_api_binding_mismatch")

    def _require_recovery_api_projection(
        self,
        payload: Mapping[str, Any],
        observed: Mapping[str, Any],
        *,
        allowed_topologies: Sequence[Mapping[str, Any]],
        allow_public_network_attachment_delta: bool = False,
    ) -> dict[str, object]:
        baseline = self._journal_projection(payload, "api_identity")
        try:
            report = self.comparison_report(baseline, observed)
        except RuntimeIdentityError as exc:
            raise DeployError("normalization_recovery_api_identity_invalid") from exc
        observed_topology = report.get("observed_topology_label_evidence")
        domain_match = report.get("match") is True
        if (
            not domain_match
            and allow_public_network_attachment_delta
            and report.get("mismatch_domains") == ["networks_and_aliases"]
        ):
            domain_match = self._network_domain_without_public_attachment(
                baseline
            ) == self._network_domain_without_public_attachment(observed)
        if not domain_match or not any(
            observed_topology == dict(expected) for expected in allowed_topologies
        ):
            raise DeployError("normalization_recovery_api_domain_drift")
        return report

    @staticmethod
    def _network_domain_without_public_attachment(
        projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        domain = projection.get("networks_and_aliases")
        if not isinstance(domain, Mapping):
            raise DeployError("normalization_recovery_api_network_invalid")
        networks = domain.get("networks")
        if not isinstance(networks, Mapping):
            raise DeployError("normalization_recovery_api_network_invalid")
        result = dict(domain)
        result["networks"] = {
            str(name): value
            for name, value in networks.items()
            if name != PUBLIC_NETWORK
        }
        return result

    @staticmethod
    def _network_without_api_member(
        projection: Mapping[str, Any], *, require_api_member: bool
    ) -> dict[str, Any]:
        members = projection.get("members")
        if not isinstance(members, list) or any(
            not isinstance(item, Mapping) for item in members
        ):
            raise DeployError("normalization_recovery_network_invalid")
        api_members = [item for item in members if item.get("name") == API_SERVICE]
        if len(api_members) > 1 or (require_api_member and len(api_members) != 1):
            raise DeployError("normalization_recovery_network_api_member_invalid")
        result = dict(projection)
        result["members"] = [
            dict(item) for item in members if item.get("name") != API_SERVICE
        ]
        return result

    def _require_recovery_runtime_match(
        self,
        payload: Mapping[str, Any],
        runtime: Mapping[str, Any],
        *,
        target_topology: bool,
    ) -> dict[str, object]:
        baselines = self._prepared_mapping(payload, "baselines")
        api_identity = self._prepared_mapping(runtime, "api_identity")
        expected_topology = (
            self._prepared_mapping(baselines, "target_api_topology_label_evidence")
            if target_topology
            else self._prepared_mapping(
                self._journal_projection(payload, "api_identity"),
                "topology_label_evidence",
            )
        )
        api_report = self._require_recovery_api_projection(
            payload,
            api_identity,
            allowed_topologies=[expected_topology],
        )
        cloudflared = self._prepared_mapping(runtime, "cloudflared_identity")
        network = self._prepared_mapping(runtime, "public_network_identity")
        public_edge = self._prepared_mapping(runtime, "public_edge_identity")
        daemon = str(runtime.get("docker_daemon_identity") or "")
        if (
            cloudflared != self._journal_projection(payload, "cloudflared_identity")
            or network != self._journal_projection(payload, "public_network_identity")
            or public_edge != self._journal_projection(payload, "public_edge_identity")
            or _sha256(daemon.encode("utf-8"))
            != baselines.get("docker_daemon_identity_sha256")
        ):
            raise DeployError("normalization_recovery_runtime_drift")
        return api_report

    def _capture_full_recovery_runtime(
        self,
        payload: Mapping[str, Any],
        *,
        target_topology: bool,
        protected_tag_state: str,
    ) -> dict[str, Any]:
        self._require_recovery_source_image(payload)
        runtime = self._capture_runtime_evidence(
            str(payload.get("public_origin") or "")
        )
        self._require_recovery_api_raw_binding(payload, runtime["api_raw"])
        comparison = self._require_recovery_runtime_match(
            payload, runtime, target_topology=target_topology
        )
        self._require_recovery_source_image(payload)
        previous = self._prepared_mapping(payload, "previous_image")
        rollback_tag = str(previous.get("rollback_tag") or "")
        expected_image_id = str(previous.get("image_id") or "")
        protected = self._inspect_image_optional(rollback_tag)
        if protected_tag_state == "absent":
            if protected is not None:
                raise DeployError("normalization_recovery_rollback_tag_present")
        elif protected_tag_state == "exact":
            protected = self._require_protected_image(rollback_tag, expected_image_id)
        elif protected_tag_state == "absent_or_exact":
            if protected is not None:
                protected = self._require_protected_image(
                    rollback_tag, expected_image_id
                )
        else:
            raise DeployError("normalization_recovery_tag_state_invalid")
        return {
            "runtime": runtime,
            "protected_image": protected,
            "comparison": comparison,
        }

    def _forward_recovery_precheck(self, payload: Mapping[str, Any]) -> None:
        self._require_recovery_source_image(payload)
        baselines = self._prepared_mapping(payload, "baselines")
        daemon = self._docker_daemon_identity()
        if _sha256(daemon.encode("utf-8")) != baselines.get(
            "docker_daemon_identity_sha256"
        ):
            raise DeployError("normalization_recovery_docker_daemon_drift")

        cloudflared_raw = self._inspect_container_raw(CLOUDFLARED_CONTAINER)
        self._require_ready_container(
            cloudflared_raw,
            name=CLOUDFLARED_CONTAINER,
            require_health=False,
        )
        try:
            cloudflared = self.cloudflared_projector(cloudflared_raw)
        except RuntimeIdentityError as exc:
            raise DeployError("normalization_recovery_cloudflared_invalid") from exc
        if cloudflared != self._journal_projection(payload, "cloudflared_identity"):
            raise DeployError("normalization_recovery_cloudflared_drift")

        network_raw = self._inspect_network_raw()
        try:
            network = self.network_projector(network_raw)
        except RuntimeIdentityError as exc:
            raise DeployError("normalization_recovery_network_invalid") from exc
        baseline_network = self._journal_projection(payload, "public_network_identity")
        if self._network_without_api_member(
            network, require_api_member=False
        ) != self._network_without_api_member(
            baseline_network, require_api_member=True
        ):
            raise DeployError("normalization_recovery_network_drift")

        api_raw = self._inspect_container_optional(API_SERVICE)
        if api_raw is not None:
            self._require_recovery_api_raw_binding(payload, api_raw)
            try:
                api_identity = self.api_projector(api_raw)
            except RuntimeIdentityError as exc:
                raise DeployError("normalization_recovery_api_invalid") from exc
            baseline_topology = self._prepared_mapping(
                self._journal_projection(payload, "api_identity"),
                "topology_label_evidence",
            )
            target_topology = self._prepared_mapping(
                baselines, "target_api_topology_label_evidence"
            )
            self._require_recovery_api_projection(
                payload,
                api_identity,
                allowed_topologies=[baseline_topology, target_topology],
                allow_public_network_attachment_delta=True,
            )
        self._require_recovery_source_image(payload)
        previous = self._prepared_mapping(payload, "previous_image")
        self._require_protected_image(
            str(previous.get("rollback_tag") or ""),
            str(previous.get("image_id") or ""),
        )

    def _enter_rollback_in_progress(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        phase = str(payload.get("phase") or "")
        if phase not in {
            "protect_previous_image_possible",
            "api_mutation_possible",
            "rollback_in_progress",
            "rollback_failed",
        }:
            raise DeployError("normalization_recovery_phase_invalid")
        replacement = self.journal.with_phase(
            payload, "rollback_in_progress", now=self.now()
        )
        self.journal.update(expected=payload, replacement=replacement)
        return replacement

    def _terminal_observation_from_capture(
        self,
        payload: Mapping[str, Any],
        capture: Mapping[str, Any],
    ) -> dict[str, Any]:
        runtime = self._prepared_mapping(capture, "runtime")
        protected = capture.get("protected_image")
        observed_protected_image_id = (
            str(protected.get("Id") or "") if isinstance(protected, Mapping) else None
        )
        baselines = self._prepared_mapping(payload, "baselines")
        baseline_api = self._journal_projection(payload, "api_identity")
        return self.terminal_observation_builder(
            api_identity=self._prepared_mapping(runtime, "api_identity"),
            cloudflared_identity=self._prepared_mapping(
                runtime, "cloudflared_identity"
            ),
            public_network_identity=self._prepared_mapping(
                runtime, "public_network_identity"
            ),
            public_edge_identity=self._prepared_mapping(
                runtime, "public_edge_identity"
            ),
            docker_daemon_identity=str(runtime.get("docker_daemon_identity") or ""),
            observed_protected_image_id=observed_protected_image_id,
            expected_protected_image_id=str(
                self._prepared_mapping(payload, "previous_image").get("image_id") or ""
            ),
            compose_config_hash=str(baselines.get("compose_config_hash") or ""),
            public_origin=str(payload.get("public_origin") or ""),
            baseline_api_topology_label_evidence=self._prepared_mapping(
                baseline_api, "topology_label_evidence"
            ),
            target_api_topology_label_evidence=self._prepared_mapping(
                baselines, "target_api_topology_label_evidence"
            ),
        )

    @staticmethod
    def _terminal_observation_from_record(
        terminal: Mapping[str, Any],
    ) -> dict[str, Any]:
        keys = {
            "verification_sha256",
            "api_domain_sha256",
            "cloudflared_domain_sha256",
            "public_network_identity_sha256",
            "public_edge_identity_sha256",
            "docker_daemon_identity_sha256",
            "protected_tag_state",
            "api_topology_label_evidence",
            "normalization_completed",
        }
        if not keys <= set(terminal):
            raise DeployError("normalization_recovery_terminal_evidence_invalid")
        return {key: terminal[key] for key in keys}

    def _optional_terminal_receipt(
        self, *, receipt_path: Path
    ) -> tuple[dict[str, Any], bytes, str] | None:
        try:
            return self._read_terminal_receipt(receipt_path=receipt_path)
        except DeployError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                return None
            raise

    def _require_exact_terminal_receipt(
        self,
        payload: Mapping[str, Any],
        *,
        kind: str,
        observation: Mapping[str, Any],
        completed_at: str,
        existing: tuple[dict[str, Any], bytes, str] | None = None,
    ) -> tuple[dict[str, Any], str, Path]:
        receipt_path = self._journal_bound_terminal_receipt_path(
            payload.get("transaction_receipt_path"),
            transaction_id=payload.get("transaction_id"),
        )
        current = existing or self._read_terminal_receipt(receipt_path=receipt_path)
        receipt, raw, digest = current
        expected = self.terminal_receipt_builder(
            payload,
            kind=kind,
            observation=observation,
            completed_at=completed_at,
        )
        if (
            receipt != expected
            or raw != _private_json_bytes(expected)
            or digest != _sha256(raw)
        ):
            raise DeployError("normalization_recovery_terminal_receipt_mismatch")
        return expected, digest, receipt_path

    def _record_recovery_operation_status(
        self, *, payload: Mapping[str, Any], kind: str
    ) -> None:
        self.receipt.update(
            {
                "status": "recovery_terminal_verified",
                "recovery_transaction_id": payload.get("transaction_id"),
                "recovery_terminal_kind": kind,
            }
        )
        self._write_receipt()

    def _remove_recovery_journal(
        self,
        payload: Mapping[str, Any],
        *,
        receipt: Mapping[str, Any],
        receipt_path: Path,
        receipt_sha256: str,
        kind: str,
    ) -> dict[str, Any]:
        self._record_recovery_operation_status(payload=payload, kind=kind)
        try:
            self.journal.remove(expected=payload)
        except BaseException:
            active = self.journal.read()
            if active is not None:
                raise
            existing, raw, digest = self._read_terminal_receipt(
                receipt_path=receipt_path
            )
            if (
                existing != dict(receipt)
                or raw != _private_json_bytes(receipt)
                or digest != receipt_sha256
            ):
                raise DeployError(
                    "normalization_recovery_terminal_changed_after_cleanup"
                )
        return dict(receipt)

    def _attach_recovery_terminal(
        self,
        payload: Mapping[str, Any],
        *,
        kind: str,
        capture: Mapping[str, Any],
    ) -> dict[str, Any]:
        observation = self._terminal_observation_from_capture(payload, capture)
        receipt_path = self._journal_bound_terminal_receipt_path(
            payload.get("transaction_receipt_path"),
            transaction_id=payload.get("transaction_id"),
        )
        existing = self._optional_terminal_receipt(receipt_path=receipt_path)
        if existing is None:
            completed_at = self.now()
            receipt = self.terminal_receipt_builder(
                payload,
                kind=kind,
                observation=observation,
                completed_at=completed_at,
            )
            receipt_sha256 = self._write_terminal_receipt(
                receipt, receipt_path=receipt_path
            )
        else:
            existing_receipt = existing[0]
            completed_at = str(existing_receipt.get("completed_at") or "")
            receipt, receipt_sha256, _path = self._require_exact_terminal_receipt(
                payload,
                kind=kind,
                observation=observation,
                completed_at=completed_at,
                existing=existing,
            )
        runtime = self._prepared_mapping(capture, "runtime")
        protected = capture.get("protected_image")
        replacement = self.journal.record_terminal_evidence(
            payload,
            kind=kind,
            receipt_sha256=receipt_sha256,
            observed_api_identity=self._prepared_mapping(runtime, "api_identity"),
            observed_cloudflared_identity=self._prepared_mapping(
                runtime, "cloudflared_identity"
            ),
            observed_public_network_identity=self._prepared_mapping(
                runtime, "public_network_identity"
            ),
            observed_public_edge_identity=self._prepared_mapping(
                runtime, "public_edge_identity"
            ),
            observed_docker_daemon_identity=str(
                runtime.get("docker_daemon_identity") or ""
            ),
            observed_protected_image_id=(
                str(protected.get("Id") or "")
                if isinstance(protected, Mapping)
                else None
            ),
            now=completed_at,
        )
        self.journal.update(expected=payload, replacement=replacement)
        return self._remove_recovery_journal(
            replacement,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_sha256=receipt_sha256,
            kind=kind,
        )

    def _finish_recorded_terminal(
        self,
        payload: Mapping[str, Any],
        *,
        current_capture: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        evidence = self._prepared_mapping(payload, "evidence")
        terminal = self._prepared_mapping(evidence, "terminal")
        recorded_observation = self._terminal_observation_from_record(terminal)
        observation = (
            recorded_observation
            if current_capture is None
            else self._terminal_observation_from_capture(payload, current_capture)
        )
        if observation != recorded_observation:
            raise DeployError("normalization_recovery_terminal_state_changed")
        kind = str(terminal.get("kind") or "")
        receipt, digest, receipt_path = self._require_exact_terminal_receipt(
            payload,
            kind=kind,
            observation=observation,
            completed_at=str(terminal.get("recorded_at") or ""),
        )
        if digest != terminal.get("receipt_sha256"):
            raise DeployError("normalization_recovery_terminal_receipt_mismatch")
        removal_payload = payload
        if kind == "durable_commit" and payload.get("phase") == "api_mutation_possible":
            removal_payload = self._persist_phase(payload, "commit_pending")
        return self._remove_recovery_journal(
            removal_payload,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_sha256=digest,
            kind=kind,
        )

    def _reuse_orphan_durable_commit(
        self,
        payload: Mapping[str, Any],
        *,
        reseal: Callable[[], dict[str, Any]],
    ) -> dict[str, Any] | None:
        receipt_path = self._journal_bound_terminal_receipt_path(
            payload.get("transaction_receipt_path"),
            transaction_id=payload.get("transaction_id"),
        )
        existing = self._optional_terminal_receipt(receipt_path=receipt_path)
        if existing is None:
            return None
        capture = self._capture_full_recovery_runtime(
            payload,
            target_topology=True,
            protected_tag_state="exact",
        )
        reseal()
        observation = self._terminal_observation_from_capture(payload, capture)
        completed_at = str(existing[0].get("completed_at") or "")
        receipt, receipt_sha256, _path = self._require_exact_terminal_receipt(
            payload,
            kind="durable_commit",
            observation=observation,
            completed_at=completed_at,
            existing=existing,
        )
        runtime = self._prepared_mapping(capture, "runtime")
        protected = self._prepared_mapping(capture, "protected_image")
        replacement = self.journal.record_terminal_evidence(
            payload,
            kind="durable_commit",
            receipt_sha256=receipt_sha256,
            observed_api_identity=self._prepared_mapping(runtime, "api_identity"),
            observed_cloudflared_identity=self._prepared_mapping(
                runtime, "cloudflared_identity"
            ),
            observed_public_network_identity=self._prepared_mapping(
                runtime, "public_network_identity"
            ),
            observed_public_edge_identity=self._prepared_mapping(
                runtime, "public_edge_identity"
            ),
            observed_docker_daemon_identity=str(
                runtime.get("docker_daemon_identity") or ""
            ),
            observed_protected_image_id=str(protected.get("Id") or ""),
            now=completed_at,
        )
        self.journal.update(expected=payload, replacement=replacement)
        committed = self._persist_phase(replacement, "commit_pending")
        return self._remove_recovery_journal(
            committed,
            receipt=receipt,
            receipt_path=receipt_path,
            receipt_sha256=receipt_sha256,
            kind="durable_commit",
        )

    def _recover_prepared(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        _bundle, reseal = self._load_recovery_bundle(payload)
        reseal()
        capture = self._capture_full_recovery_runtime(
            payload,
            target_topology=False,
            protected_tag_state="absent",
        )
        reseal()
        return self._attach_recovery_terminal(
            payload, kind="clean_abort", capture=capture
        )

    def _recover_old_baseline(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        recovering = self._enter_rollback_in_progress(payload)
        _bundle, reseal = self._load_recovery_bundle(recovering)
        reseal()
        before = self._capture_full_recovery_runtime(
            recovering,
            target_topology=False,
            protected_tag_state="absent_or_exact",
        )
        protected = before.get("protected_image")
        previous = self._prepared_mapping(recovering, "previous_image")
        rollback_tag = str(previous.get("rollback_tag") or "")
        if isinstance(protected, Mapping):
            self._require_canonical_journal(recovering)
            self._run_sanitized(["docker", "image", "rm", rollback_tag])
            if self._inspect_image_optional(rollback_tag) is not None:
                raise DeployError("normalization_recovery_tag_remove_failed")
        reseal()
        after = self._capture_full_recovery_runtime(
            recovering,
            target_topology=False,
            protected_tag_state="absent",
        )
        reseal()
        return self._attach_recovery_terminal(
            recovering, kind="verified_recovery", capture=after
        )

    def _recover_forward(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        recovering = self._enter_rollback_in_progress(payload)
        bundle, reseal = self._load_recovery_bundle(recovering)
        self._forward_recovery_precheck(recovering)
        self._render_recovery_bundle_compose(recovering, bundle, reseal)
        self._forward_recovery_precheck(recovering)
        self._require_canonical_journal(recovering)
        self._recovery_bundle_api_up(bundle, reseal)
        self._wait_api_healthy()
        capture = self._capture_full_recovery_runtime(
            recovering,
            target_topology=True,
            protected_tag_state="exact",
        )
        reseal()
        return self._attach_recovery_terminal(
            recovering,
            kind="verified_forward_recovery",
            capture=capture,
        )

    def _reuse_orphan_recovery_receipt(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        receipt_path = self._journal_bound_terminal_receipt_path(
            payload.get("transaction_receipt_path"),
            transaction_id=payload.get("transaction_id"),
        )
        if self._optional_terminal_receipt(receipt_path=receipt_path) is None:
            return None
        recovering = self._enter_rollback_in_progress(payload)
        _bundle, reseal = self._load_recovery_bundle(recovering)
        authorized = recovering.get("api_boundary_authorized") is True
        reseal()
        capture = self._capture_full_recovery_runtime(
            recovering,
            target_topology=authorized,
            protected_tag_state="exact" if authorized else "absent",
        )
        reseal()
        return self._attach_recovery_terminal(
            recovering,
            kind=("verified_forward_recovery" if authorized else "verified_recovery"),
            capture=capture,
        )

    def _recover_dispatch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        phase = str(payload.get("phase") or "")
        evidence = self._prepared_mapping(payload, "evidence")
        terminal = evidence.get("terminal")
        if terminal is not None:
            terminal_record = self._prepared_mapping(evidence, "terminal")
            kind = str(terminal_record.get("kind") or "")
            if phase == "cleanup_pending":
                return self._finish_recorded_terminal(payload)
            if kind not in {
                "clean_abort",
                "durable_commit",
                "verified_recovery",
                "verified_forward_recovery",
            }:
                raise DeployError("normalization_recovery_terminal_kind_invalid")
            target = kind in {"durable_commit", "verified_forward_recovery"}
            _bundle, reseal = self._load_recovery_bundle(payload)
            reseal()
            capture = self._capture_full_recovery_runtime(
                payload,
                target_topology=target,
                protected_tag_state="exact" if target else "absent",
            )
            reseal()
            return self._finish_recorded_terminal(payload, current_capture=capture)

        if phase == "cleanup_pending":
            raise DeployError("normalization_recovery_cleanup_terminal_missing")
        if phase == "commit_pending":
            raise DeployError("normalization_recovery_commit_terminal_missing")
        if phase == "prepared":
            return self._recover_prepared(payload)
        if phase == "protect_previous_image_possible":
            return self._recover_old_baseline(payload)
        if phase == "api_mutation_possible":
            _bundle, reseal = self._load_recovery_bundle(payload)
            reseal()
            orphan = self._reuse_orphan_durable_commit(payload, reseal=reseal)
            if orphan is not None:
                return orphan
            return self._recover_forward(payload)
        if phase in {"rollback_in_progress", "rollback_failed"}:
            orphan = self._reuse_orphan_recovery_receipt(payload)
            if orphan is not None:
                return orphan
            if payload.get("api_boundary_authorized") is True:
                return self._recover_forward(payload)
            return self._recover_old_baseline(payload)
        raise DeployError("normalization_recovery_phase_invalid")

    def _recover(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Converge one validated canonical recovery journal."""
        owned = self._require_canonical_journal(payload)
        self.receipt.update(
            {
                "status": "recovering",
                "recovery_transaction_id": owned.get("transaction_id"),
                "recovery_start_phase": owned.get("phase"),
            }
        )
        self._write_receipt()
        try:
            return self._recover_dispatch(owned)
        except BaseException as original:
            try:
                current = self.journal.read()
            except BaseException as read_error:
                raise original.with_traceback(original.__traceback__) from read_error
            terminal = (
                current.get("evidence", {}).get("terminal")
                if isinstance(current, Mapping)
                and isinstance(current.get("evidence"), Mapping)
                else None
            )
            if (
                current is not None
                and current.get("phase") == "rollback_in_progress"
                and terminal is None
            ):
                try:
                    replacement = self.journal.with_phase(
                        current, "rollback_failed", now=self.now()
                    )
                    self.journal.update(expected=current, replacement=replacement)
                except BaseException as mark_error:
                    raise original.with_traceback(
                        original.__traceback__
                    ) from mark_error
            raise

    def _preflight_receipt(self, prepared: Mapping[str, Any]) -> dict[str, Any]:
        bundle = prepared["bundle"]
        live = prepared["live"]
        repository = prepared["repository"]
        compose = prepared["compose"]
        comparison = prepared["runtime_comparison"]
        runtime = prepared["runtime"]
        if not all(
            isinstance(value, Mapping)
            for value in (bundle, live, repository, compose, comparison, runtime)
        ):
            raise DeployError("normalization_preflight_evidence_invalid")
        receipt: dict[str, Any] = {
            "contract_name": PREFLIGHT_RECEIPT_CONTRACT,
            "version": PREFLIGHT_RECEIPT_VERSION,
            "operation_id": self.deployment_id,
            "status": "pass",
            "preflight_only": True,
            "service_scope": [API_SERVICE],
            "ingress_mutation_scope": [],
            "promotion_authority": False,
            "candidate_authority": False,
            "mutation_authority": False,
            "normalization_completed": False,
            "source": {
                "branch": repository["branch"],
                "upstream": repository["upstream"],
                "revision": live["expected_revision"],
                "head_equals_origin_main": True,
            },
            "public_origin": prepared["public_origin"],
            "retained_bundle": {
                "contract_name": "ea.memorial_api_baseline_bundle_recovery_seal.v1",
                "manifest_sha256": bundle["manifest_sha256"],
                "plan_sha256": bundle["plan_sha256"],
            },
            "compose": {
                "project": PROJECT_NAME,
                "service_scope": [API_SERVICE],
                "image_reference": compose["rendered_service_image"],
                "pull_policy": compose["pull_policy"],
                "config_hash": compose["rendered_config_hash"],
            },
            "runtime_identity": dict(comparison),
            "public_edge_identity_sha256": _sha256(
                _canonical_bytes(runtime["public_edge_identity"])
            ),
            "execution": {
                "journal_created": False,
                "docker_mutations": 0,
                "compose_up_invocations": 0,
                "build_or_pull_invocations": 0,
                "ingress_mutations": 0,
            },
            "completed_at": self.now(),
        }
        self.receipt = receipt
        self._write_receipt()
        return receipt


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize only the live ea-api Compose topology labels from a "
            "sealed exact-Git baseline bundle."
        )
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--bundle-parent", required=True, type=Path)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = ApiBaselineNormalizationLane(
            plan_path=args.plan,
            bundle_parent=args.bundle_parent,
            public_origin=args.public_origin,
            preflight_only=args.preflight_only,
        ).execute()
    except (
        BaselineBundleError,
        DeployError,
        NormalizationJournalError,
        PlanError,
        RuntimeIdentityError,
        OSError,
    ) as exc:
        print(f"API baseline normalization failed: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
