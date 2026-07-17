#!/usr/bin/env python3
"""Atomically deploy the Manfred API and its public Cloudflare ingress.

The standalone memorial lane cannot repair a broken public edge because it
verifies that edge immediately after changing ea-api. The standalone ingress
lane is intentionally read-only. This coordinator owns the one transaction
that may compose them: capture both baselines, change and prove the API locally,
change and prove ingress, then prove every public surface.

Rollback is recovery, not a new promotion. Once a forward mutation may have
started, rollback never waits for a fresh permit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pwd
import signal
import stat
import subprocess
import sys
import time
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
        VEXP_MUTATION_BOUNDARIES,
        DeployError,
        HttpResponse,
        MemorialDeployLane,
        Runner,
        _NoRedirectHandler,
        _default_http_get,
        _default_http_no_redirect,
        _safe_rollback_tag,
        _safe_tagged_image_reference,
        _utc_now,
        _validate_public_origin,
    )
    from scripts.reconcile_ea_public_ingress import (
        CLOUDFLARED_CONTAINER,
        CLOUDFLARED_SERVICE,
        PINNED_CLOUDFLARED_IMAGE,
        PROPERTY_NETWORK,
        PUBLIC_INGRESS_CLOUDFLARED_IPV4,
        PUBLIC_INGRESS_GATEWAY,
        PUBLIC_INGRESS_NETWORK,
        PUBLIC_INGRESS_SUBNET,
        PUBLIC_PROBES,
        TARGET_COMPOSE_FILES,
        PublicIngressReconciliationLane,
        _trusted_file_seal,
        _trusted_optional_private_file_seal,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from deploy_ea_memorial import (  # type: ignore[no-redef]
        API_SERVICE,
        MAX_HTTP_BODY_BYTES,
        VEXP_MUTATION_BOUNDARIES,
        DeployError,
        HttpResponse,
        MemorialDeployLane,
        Runner,
        _NoRedirectHandler,
        _default_http_get,
        _default_http_no_redirect,
        _safe_rollback_tag,
        _safe_tagged_image_reference,
        _utc_now,
        _validate_public_origin,
    )
    from reconcile_ea_public_ingress import (  # type: ignore[no-redef]
        CLOUDFLARED_CONTAINER,
        CLOUDFLARED_SERVICE,
        PINNED_CLOUDFLARED_IMAGE,
        PROPERTY_NETWORK,
        PUBLIC_INGRESS_CLOUDFLARED_IPV4,
        PUBLIC_INGRESS_GATEWAY,
        PUBLIC_INGRESS_NETWORK,
        PUBLIC_INGRESS_SUBNET,
        PUBLIC_PROBES,
        TARGET_COMPOSE_FILES,
        PublicIngressReconciliationLane,
        _trusted_file_seal,
        _trusted_optional_private_file_seal,
    )


ROOT = Path(__file__).resolve().parents[1]
JOINT_COORDINATION_CONTRACT_NAME = "ea.memorial_joint_api_ingress_deploy.v1"
MEMORIAL_COMPONENT_CONTRACT_NAME = "ea.memorial_scoped_deploy_receipt.v1"
JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME = "ea.vexp_memorial_joint_mutation_permit.v1"
JOINT_VEXP_MUTATION_PERMIT_VERSION = 1
INGRESS_MUTATION_BOUNDARY = "before_recreate_cloudflared"
SPATIAL_DEPLOY_RECEIPT_ENV = "EA_MEMORIAL_SPATIAL_DEPLOY_RECEIPT"
SPATIAL_BROWSER_RECEIPT_ENV = "EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT"
CANDIDATE_RUNTIME_SCHEMA = "ea.manfred_memorial_candidate_runtime.v4"
CANDIDATE_BROWSER_SCHEMA = "ea.manfred_spatial_candidate_browser.v5"
MAX_SPATIAL_RECEIPT_BYTES = 8 * 1024 * 1024
JOINT_RECOVERY_JOURNAL_CONTRACT_NAME = "ea.memorial_joint_recovery_journal.v1"
JOINT_RECOVERY_JOURNAL_VERSION = 1
JOINT_RECOVERY_JOURNAL_FILENAME = "joint-active-recovery.json"
JOINT_RECOVERY_STATE_DIRECTORY = ".ea-memorial-deploy-state"
JOINT_DEPLOY_OPERATOR_ANCHOR = Path("/docker/EA")
INGRESS_ROLLBACK_ENV_KEYS = frozenset(
    {
        "EA_CF_TUNNEL_TOKEN",
        "EA_PUBLIC_INGRESS_CLOUDFLARED_IPV4",
        "EA_PUBLIC_INGRESS_GATEWAY",
        "EA_PUBLIC_INGRESS_NETWORK_NAME",
        "EA_PUBLIC_INGRESS_SUBNET",
    }
)
DOCKER_TRANSPORT_ENV_KEYS = frozenset(
    {
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "SSH_AUTH_SOCK",
    }
)
MAX_JOINT_RECOVERY_JOURNAL_BYTES = 8 * 1024 * 1024
JOINT_RECOVERY_PHASES = frozenset(
    {
        "prepared",
        "api_mutation_possible",
        "ingress_mutation_possible",
        "commit_pending",
        "rollback_in_progress",
        "rollback_failed",
    }
)
DEFAULT_JOINT_ROLLBACK_DEADLINE_SECONDS = 180.0
MIN_JOINT_ROLLBACK_DEADLINE_SECONDS = 30.0
MAX_JOINT_ROLLBACK_DEADLINE_SECONDS = 900.0
JOINT_VEXP_MUTATION_BOUNDARIES = (
    *VEXP_MUTATION_BOUNDARIES,
    INGRESS_MUTATION_BOUNDARY,
)


PublicSnapshot = Callable[[str, float, str], HttpResponse]


class JointDeploySignalInterruption(DeployError):
    """A catchable process signal that enters the normal rollback domain."""


class JointCommittedCleanupIncident(DeployError):
    """The transaction committed, but cleanup state or evidence is incomplete."""


class _DeploymentSignalController:
    """Turn process signals into one interruption, or defer them during recovery."""

    def __init__(self) -> None:
        self.deferral_depth = 0
        self.interruption_raised = False
        self.deferred_signal_counts: dict[int, int] = {}

    def handle(self, signum: int, _frame: Any) -> None:
        if self.deferral_depth:
            self.deferred_signal_counts[signum] = min(
                self.deferred_signal_counts.get(signum, 0) + 1,
                1_000_000,
            )
            return
        if self.interruption_raised:
            return
        self.interruption_raised = True
        raise JointDeploySignalInterruption(f"joint_deployment_signal:{signum}")

    @contextmanager
    def defer(self) -> Iterator[None]:
        self.deferral_depth += 1
        try:
            yield
        finally:
            self.deferral_depth -= 1

    def deferred_receipt(self) -> dict[str, int]:
        return {
            signal.Signals(signum).name: count
            for signum, count in sorted(self.deferred_signal_counts.items())
        }


_ACTIVE_SIGNAL_CONTROLLER: _DeploymentSignalController | None = None


@contextmanager
def _defer_deployment_signals() -> Iterator[_DeploymentSignalController | None]:
    controller = _ACTIVE_SIGNAL_CONTROLLER
    if controller is None:
        yield None
        return
    with controller.defer():
        yield controller


def _public_snapshot_no_redirect(
    url: str,
    timeout_seconds: float,
    method: str,
) -> HttpResponse:
    """Return a bounded fingerprint even when the current edge is broken."""
    if method not in {"GET", "HEAD"}:
        raise DeployError("joint_public_snapshot_method_invalid")
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            "User-Agent": "EA-Memorial-Joint-Deploy/1.0",
        },
    )
    response: Any
    try:
        response = urllib.request.build_opener(_NoRedirectHandler()).open(
            request,
            timeout=timeout_seconds,
        )
    except urllib.error.HTTPError as exc:
        status = int(exc.code or 0)
        if not 100 <= status <= 599:
            raise DeployError("joint_public_snapshot_status_invalid") from exc
        response = exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(f"joint_public_snapshot_failed:{type(exc).__name__}") from exc
    try:
        body = response.read(MAX_HTTP_BODY_BYTES + 1)
        if len(body) > MAX_HTTP_BODY_BYTES:
            raise DeployError("joint_public_snapshot_body_too_large")
        return HttpResponse(
            status=int(getattr(response, "status", 0) or response.getcode() or 0),
            content_type=str(response.headers.get("Content-Type") or ""),
            body=body,
            source_revision=str(
                response.headers.get("X-EA-Source-Revision") or ""
            ).strip(),
            headers={
                "location": str(response.headers.get("Location") or "").strip(),
            },
        )
    finally:
        response.close()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _completed_json(
    completed: subprocess.CompletedProcess[str],
    *,
    reason: str,
) -> object:
    try:
        return json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise DeployError(reason) from exc


def _strict_json_object(raw: bytes, *, reason: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite number")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise DeployError(reason) from exc
    if not isinstance(payload, dict):
        raise DeployError(reason)
    return payload


class JointMemorialIngressDeployLane(MemorialDeployLane):
    """One rollback domain for ea-api and ea-cloudflared."""

    vexp_mutation_permit_contract_name = JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME
    vexp_mutation_permit_version = JOINT_VEXP_MUTATION_PERMIT_VERSION
    vexp_mutation_boundaries = JOINT_VEXP_MUTATION_BOUNDARIES

    def __init__(
        self,
        *,
        root: Path = ROOT,
        env: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        http_get: Callable[[str, float, str], HttpResponse] = _default_http_get,
        http_no_redirect: Callable[
            [str, float, str, str], HttpResponse
        ] = _default_http_no_redirect,
        public_snapshot: PublicSnapshot = _public_snapshot_no_redirect,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 90.0,
        poll_seconds: float = 2.0,
        request_timeout_seconds: float = 10.0,
        internal_openapi_snapshot: Callable[[], Mapping[str, Any]] | None = None,
        receipt_dir: Path | None = None,
        ingress_receipt_dir: Path | None = None,
        global_lock_path: Path | None = None,
        recovery_journal_path: Path | None = None,
        durable_root_check: Callable[[Path], None] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "root": root,
            "env": env,
            "runner": runner,
            "http_get": http_get,
            "http_no_redirect": http_no_redirect,
            "sleep": sleep,
            "monotonic": monotonic,
            "wait_seconds": wait_seconds,
            "poll_seconds": poll_seconds,
            "request_timeout_seconds": request_timeout_seconds,
            "internal_openapi_snapshot": internal_openapi_snapshot,
            "receipt_dir": receipt_dir,
            "global_lock_path": global_lock_path,
        }
        if durable_root_check is not None:
            kwargs["durable_root_check"] = durable_root_check
        super().__init__(**kwargs)
        self.public_snapshot = public_snapshot
        raw_rollback_deadline = str(
            self.env.get("EA_MEMORIAL_JOINT_ROLLBACK_DEADLINE_SECONDS")
            or DEFAULT_JOINT_ROLLBACK_DEADLINE_SECONDS
        ).strip()
        try:
            rollback_deadline_seconds = float(raw_rollback_deadline)
        except ValueError as exc:
            raise DeployError("joint_rollback_deadline_invalid") from exc
        if (
            not math.isfinite(rollback_deadline_seconds)
            or not MIN_JOINT_ROLLBACK_DEADLINE_SECONDS
            <= rollback_deadline_seconds
            <= MAX_JOINT_ROLLBACK_DEADLINE_SECONDS
        ):
            raise DeployError("joint_rollback_deadline_invalid")
        self.rollback_deadline_seconds = rollback_deadline_seconds
        self._joint_rollback_deadline: float | None = None
        self._recovery_local_origin: str | None = None
        self.ingress_receipt_dir = (
            ingress_receipt_dir.resolve()
            if ingress_receipt_dir is not None
            else self.receipt_dir / "ingress"
        )
        self._default_recovery_state_home: Path | None = None
        self._recovery_state_owner_uid = os.geteuid()
        if recovery_journal_path is None:
            try:
                operator_anchor = JOINT_DEPLOY_OPERATOR_ANCHOR.lstat()
                operator_uid = int(operator_anchor.st_uid)
                account_home = Path(pwd.getpwuid(operator_uid).pw_dir)
            except (KeyError, OSError) as exc:
                raise DeployError("joint_recovery_account_home_unavailable") from exc
            if (
                not stat.S_ISDIR(operator_anchor.st_mode)
                or stat.S_ISLNK(operator_anchor.st_mode)
            ):
                raise DeployError("joint_recovery_operator_anchor_invalid")
            if os.geteuid() != operator_uid:
                raise DeployError("joint_recovery_deployment_operator_mismatch")
            if not account_home.is_absolute() or ".." in account_home.parts:
                raise DeployError("joint_recovery_account_home_invalid")
            self._default_recovery_state_home = account_home
            self._recovery_state_owner_uid = operator_uid
            self.recovery_journal_path = (
                account_home
                / JOINT_RECOVERY_STATE_DIRECTORY
                / JOINT_RECOVERY_JOURNAL_FILENAME
            )
        else:
            selected_journal_path = recovery_journal_path.expanduser()
            if (
                not selected_journal_path.is_absolute()
                or ".." in selected_journal_path.parts
                or selected_journal_path.name != JOINT_RECOVERY_JOURNAL_FILENAME
            ):
                raise DeployError("joint_recovery_journal_path_invalid")
            self.recovery_journal_path = selected_journal_path
        self.receipt.update(
            {
                "contract_name": JOINT_COORDINATION_CONTRACT_NAME,
                "coordination_contract_name": JOINT_COORDINATION_CONTRACT_NAME,
                "component_contracts": {
                    "memorial_deploy": MEMORIAL_COMPONENT_CONTRACT_NAME,
                },
                "service_scope": [
                    API_SERVICE,
                    "ea-redis",
                    CLOUDFLARED_SERVICE,
                ],
                "api_mutation_scope": [API_SERVICE],
                "ingress_mutation_scope": [CLOUDFLARED_SERVICE],
                "joint_atomicity": {
                    "api_rollback_baseline_verified": False,
                    "ingress_rollback_baseline_verified": False,
                    "network_rollback_baseline_captured": False,
                    "public_edge_rollback_baseline_captured": False,
                    "rollback_executed": False,
                    "rollback_execution_status": "not_executed",
                },
                "permit_contract": {
                    "contract_name": self.vexp_mutation_permit_contract_name,
                    "version": self.vexp_mutation_permit_version,
                    "mutation_boundaries": list(self.vexp_mutation_boundaries),
                },
            }
        )

    def _remaining_vexp_mutation_seconds(self) -> float | None:
        permit_remaining = super()._remaining_vexp_mutation_seconds()
        deadline = self._joint_rollback_deadline
        if deadline is None:
            return permit_remaining
        rollback_remaining = deadline - self._vexp_monotonic_now()
        if not math.isfinite(rollback_remaining) or rollback_remaining <= 0:
            raise DeployError("joint_rollback_deadline_exceeded")
        if permit_remaining is None:
            return rollback_remaining
        return min(permit_remaining, rollback_remaining)

    def _local_origin(self) -> str:
        if self._recovery_local_origin is not None:
            return self._recovery_local_origin
        return super()._local_origin()

    @contextmanager
    def _rollback_deadline_scope(self) -> Iterator[None]:
        if self._joint_rollback_deadline is not None:
            raise DeployError("joint_rollback_deadline_nested")
        started = self._vexp_monotonic_now()
        deadline = started + self.rollback_deadline_seconds
        if not math.isfinite(deadline) or deadline <= started:
            raise DeployError("joint_rollback_deadline_invalid")
        self._joint_rollback_deadline = deadline
        try:
            yield
            self._remaining_vexp_mutation_seconds()
        finally:
            self._joint_rollback_deadline = None

    @contextmanager
    def _ensure_rollback_deadline_scope(self) -> Iterator[None]:
        if self._joint_rollback_deadline is not None:
            yield
            return
        with self._rollback_deadline_scope():
            yield

    @contextmanager
    def _bounded_rollback_waits(self) -> Iterator[None]:
        if self._joint_rollback_deadline is None:
            yield
            return
        remaining = self._remaining_vexp_mutation_seconds()
        if remaining is None:  # pragma: no cover - deadline invariant
            raise DeployError("joint_rollback_deadline_missing")
        original_wait_seconds = self.wait_seconds
        original_poll_seconds = self.poll_seconds
        original_request_timeout_seconds = self.request_timeout_seconds
        original_http_get = self.http_get
        original_sleep = self.sleep

        def bounded_http_get(
            url: str,
            timeout_seconds: float,
            public_authority: str = "",
        ) -> HttpResponse:
            current = self._remaining_vexp_mutation_seconds()
            if current is None:  # pragma: no cover - deadline invariant
                raise DeployError("joint_rollback_deadline_missing")
            return original_http_get(
                url,
                min(timeout_seconds, current),
                public_authority,
            )

        def bounded_sleep(seconds: float) -> None:
            current = self._remaining_vexp_mutation_seconds()
            if current is None:  # pragma: no cover - deadline invariant
                raise DeployError("joint_rollback_deadline_missing")
            original_sleep(min(max(seconds, 0.0), current))

        self.wait_seconds = min(self.wait_seconds, remaining)
        self.poll_seconds = min(self.poll_seconds, remaining)
        self.request_timeout_seconds = min(
            self.request_timeout_seconds,
            remaining,
        )
        self.http_get = bounded_http_get
        self.sleep = bounded_sleep
        try:
            yield
        finally:
            self.wait_seconds = original_wait_seconds
            self.poll_seconds = original_poll_seconds
            self.request_timeout_seconds = original_request_timeout_seconds
            self.http_get = original_http_get
            self.sleep = original_sleep

    def _wait_container(
        self,
        name: str,
        *,
        require_health: bool,
    ) -> dict[str, str]:
        with self._bounded_rollback_waits():
            return super()._wait_container(name, require_health=require_health)

    def _wait_http(
        self,
        url: str,
        *,
        kind: str,
        expected_source_revision: str = "",
        public_authority: str = "",
    ) -> dict[str, Any]:
        with self._bounded_rollback_waits():
            return super()._wait_http(
                url,
                kind=kind,
                expected_source_revision=expected_source_revision,
                public_authority=public_authority,
            )

    def _wait_json_control(
        self,
        url: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._bounded_rollback_waits():
            return super()._wait_json_control(url)

    @staticmethod
    def _recovery_journal_bytes(payload: Mapping[str, Any]) -> bytes:
        return (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")

    def _open_recovery_journal_directory(self, *, create: bool) -> int:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise DeployError("joint_recovery_journal_nofollow_unavailable")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        expected_uid = self._recovery_state_owner_uid
        if self._default_recovery_state_home is not None:
            home_descriptor = -1
            try:
                home_path_metadata = self._default_recovery_state_home.lstat()
                home_descriptor = os.open(
                    self._default_recovery_state_home,
                    directory_flags,
                )
                home_metadata = os.fstat(home_descriptor)
                if (
                    not stat.S_ISDIR(home_metadata.st_mode)
                    or stat.S_ISLNK(home_path_metadata.st_mode)
                    or home_metadata.st_uid != expected_uid
                    or stat.S_IMODE(home_metadata.st_mode) & 0o022
                    or (home_metadata.st_dev, home_metadata.st_ino)
                    != (home_path_metadata.st_dev, home_path_metadata.st_ino)
                ):
                    raise DeployError("joint_recovery_account_home_invalid")
                if create:
                    try:
                        os.mkdir(
                            JOINT_RECOVERY_STATE_DIRECTORY,
                            0o700,
                            dir_fd=home_descriptor,
                        )
                    except FileExistsError:
                        pass
                directory_descriptor = os.open(
                    JOINT_RECOVERY_STATE_DIRECTORY,
                    directory_flags,
                    dir_fd=home_descriptor,
                )
                directory_metadata = os.fstat(directory_descriptor)
                path_metadata = os.stat(
                    JOINT_RECOVERY_STATE_DIRECTORY,
                    dir_fd=home_descriptor,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISDIR(directory_metadata.st_mode)
                    or directory_metadata.st_uid != expected_uid
                    or stat.S_IMODE(directory_metadata.st_mode) != 0o700
                    or (directory_metadata.st_dev, directory_metadata.st_ino)
                    != (path_metadata.st_dev, path_metadata.st_ino)
                ):
                    os.close(directory_descriptor)
                    raise DeployError("joint_recovery_journal_directory_invalid")
                return directory_descriptor
            except FileNotFoundError:
                raise
            except DeployError:
                raise
            except OSError as exc:
                raise DeployError(
                    "joint_recovery_journal_directory_unavailable"
                ) from exc
            finally:
                if home_descriptor >= 0:
                    os.close(home_descriptor)

        directory = self.recovery_journal_path.parent
        if create:
            try:
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError as exc:
                raise DeployError(
                    "joint_recovery_journal_directory_unavailable"
                ) from exc
        try:
            path_metadata = directory.lstat()
            if stat.S_ISLNK(path_metadata.st_mode):
                raise DeployError("joint_recovery_journal_directory_invalid")
            directory_descriptor = os.open(directory, directory_flags)
            directory_metadata = os.fstat(directory_descriptor)
            final_path_metadata = directory.lstat()
        except FileNotFoundError:
            raise
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError("joint_recovery_journal_directory_unavailable") from exc
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != expected_uid
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
            or (directory_metadata.st_dev, directory_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
            or (directory_metadata.st_dev, directory_metadata.st_ino)
            != (final_path_metadata.st_dev, final_path_metadata.st_ino)
        ):
            os.close(directory_descriptor)
            raise DeployError("joint_recovery_journal_directory_invalid")
        return directory_descriptor

    def _require_recovery_directory_identity(self, descriptor: int) -> None:
        try:
            descriptor_metadata = os.fstat(descriptor)
            path_metadata = self.recovery_journal_path.parent.lstat()
        except OSError as exc:
            raise DeployError("joint_recovery_journal_directory_changed") from exc
        if (
            stat.S_ISLNK(path_metadata.st_mode)
            or descriptor_metadata.st_uid != self._recovery_state_owner_uid
            or stat.S_IMODE(descriptor_metadata.st_mode) != 0o700
            or (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise DeployError("joint_recovery_journal_directory_changed")

    def _recovery_state_directory_identity(
        self,
        descriptor: int,
    ) -> dict[str, object]:
        self._require_recovery_directory_identity(descriptor)
        metadata = os.fstat(descriptor)
        directory = self.recovery_journal_path.parent
        if not directory.is_absolute() or ".." in directory.parts:
            raise DeployError("joint_recovery_journal_directory_invalid")
        return {
            "path": str(directory),
            "dev": int(metadata.st_dev),
            "inode": int(metadata.st_ino),
            "uid": int(metadata.st_uid),
            "gid": int(metadata.st_gid),
            "mode": int(stat.S_IMODE(metadata.st_mode)),
            "mtime_ns": int(metadata.st_mtime_ns),
            "ctime_ns": int(metadata.st_ctime_ns),
        }

    def _write_recovery_journal(self, payload: Mapping[str, Any]) -> str:
        encoded = self._recovery_journal_bytes(payload)
        if not 0 < len(encoded) <= MAX_JOINT_RECOVERY_JOURNAL_BYTES:
            raise DeployError("joint_recovery_journal_size_invalid")

        temporary_name = (
            f".{self.recovery_journal_path.name}.tmp.{os.getpid()}."
            f"{os.urandom(12).hex()}"
        )
        file_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | os.O_NOFOLLOW
        )
        directory_descriptor = -1
        descriptor = -1
        temporary_created = False
        try:
            directory_descriptor = self._open_recovery_journal_directory(create=True)
            directory_metadata = os.fstat(directory_descriptor)
            descriptor = os.open(
                temporary_name,
                file_flags,
                0o600,
                dir_fd=directory_descriptor,
            )
            temporary_created = True
            os.fchmod(descriptor, 0o600)
            created = os.fstat(descriptor)
            if (
                not stat.S_ISREG(created.st_mode)
                or created.st_nlink != 1
                or created.st_uid != self._recovery_state_owner_uid
                or stat.S_IMODE(created.st_mode) != 0o600
            ):
                raise DeployError("joint_recovery_journal_temporary_invalid")
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise DeployError("joint_recovery_journal_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            completed = os.fstat(descriptor)
            path_metadata = os.stat(
                temporary_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                completed.st_size != len(encoded)
                or completed.st_nlink != 1
                or completed.st_uid != self._recovery_state_owner_uid
                or stat.S_IMODE(completed.st_mode) != 0o600
                or (completed.st_dev, completed.st_ino)
                != (created.st_dev, created.st_ino)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (created.st_dev, created.st_ino)
            ):
                raise DeployError("joint_recovery_journal_temporary_changed")
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary_name,
                self.recovery_journal_path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            temporary_created = False
            published = os.stat(
                self.recovery_journal_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(published.st_mode)
                or published.st_nlink != 1
                or published.st_uid != self._recovery_state_owner_uid
                or stat.S_IMODE(published.st_mode) != 0o600
                or published.st_size != len(encoded)
                or (published.st_dev, published.st_ino)
                != (created.st_dev, created.st_ino)
            ):
                raise DeployError("joint_recovery_journal_publish_invalid")
            os.fsync(directory_descriptor)
            self._require_recovery_directory_identity(directory_descriptor)
            if (directory_metadata.st_dev, directory_metadata.st_ino) != (
                os.fstat(directory_descriptor).st_dev,
                os.fstat(directory_descriptor).st_ino,
            ):
                raise DeployError("joint_recovery_journal_directory_changed")
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError("joint_recovery_journal_write_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_created and directory_descriptor >= 0:
                try:
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
                except OSError:
                    pass
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
        return _sha256(encoded)

    def _read_recovery_journal(self) -> tuple[dict[str, Any], bytes] | None:
        directory_descriptor = -1
        descriptor = -1
        try:
            directory_descriptor = self._open_recovery_journal_directory(create=False)
        except FileNotFoundError:
            return None
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
            raise DeployError("joint_recovery_journal_nofollow_unavailable")
        try:
            descriptor = os.open(
                self.recovery_journal_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            os.close(directory_descriptor)
            return None
        except OSError as exc:
            os.close(directory_descriptor)
            raise DeployError("joint_recovery_journal_unavailable") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != self._recovery_state_owner_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not 0 < metadata.st_size <= MAX_JOINT_RECOVERY_JOURNAL_BYTES
            ):
                raise DeployError("joint_recovery_journal_untrusted")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            final_metadata = os.fstat(descriptor)
            path_metadata = os.stat(
                self.recovery_journal_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                len(raw) != metadata.st_size
                or remaining != 0
                or (final_metadata.st_dev, final_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
                or final_metadata.st_size != metadata.st_size
                or final_metadata.st_mtime_ns != metadata.st_mtime_ns
                or final_metadata.st_ctime_ns != metadata.st_ctime_ns
            ):
                raise DeployError("joint_recovery_journal_changed_during_read")
            self._require_recovery_directory_identity(directory_descriptor)
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError("joint_recovery_journal_unreadable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
        return (
            _strict_json_object(raw, reason="joint_recovery_journal_json_invalid"),
            raw,
        )

    def _require_canonical_recovery_journal_absent(
        self,
        *,
        expected_directory_identity: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        directory_descriptor = -1
        try:
            directory_descriptor = self._open_recovery_journal_directory(
                create=False
            )
        except FileNotFoundError as exc:
            raise DeployError(
                "joint_committed_cleanup_state_directory_missing"
            ) from exc
        try:
            directory_identity = self._recovery_state_directory_identity(
                directory_descriptor
            )
            if (
                expected_directory_identity is not None
                and directory_identity != dict(expected_directory_identity)
            ):
                raise DeployError(
                    "joint_committed_cleanup_state_directory_changed"
                )
            try:
                os.stat(
                    self.recovery_journal_path.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                final_identity = self._recovery_state_directory_identity(
                    directory_descriptor
                )
                if final_identity != directory_identity:
                    raise DeployError(
                        "joint_committed_cleanup_state_directory_changed"
                    )
                return final_identity
            except OSError as exc:
                raise DeployError(
                    "joint_committed_cleanup_journal_absence_unprovable"
                ) from exc
            raise DeployError("joint_committed_cleanup_journal_still_present")
        finally:
            if directory_descriptor >= 0:
                os.close(directory_descriptor)

    def _remove_recovery_journal(self) -> dict[str, object] | None:
        directory_descriptor = -1
        descriptor = -1
        try:
            directory_descriptor = self._open_recovery_journal_directory(create=False)
        except FileNotFoundError:
            return None
        try:
            descriptor = os.open(
                self.recovery_journal_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            os.close(directory_descriptor)
            directory_descriptor = -1
            return self._require_canonical_recovery_journal_absent()
        except OSError as exc:
            os.close(directory_descriptor)
            raise DeployError("joint_recovery_journal_remove_failed") from exc
        try:
            metadata = os.fstat(descriptor)
            current = os.stat(
                self.recovery_journal_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != self._recovery_state_owner_uid
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or (current.st_dev, current.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise DeployError("joint_recovery_journal_changed")
            os.unlink(self.recovery_journal_path.name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
            return self._recovery_state_directory_identity(directory_descriptor)
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError("joint_recovery_journal_remove_failed") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if directory_descriptor >= 0:
                os.close(directory_descriptor)

    def _remove_owned_recovery_journal(
        self,
        journal: Mapping[str, Any],
        *,
        transaction_id: str | None = None,
    ) -> dict[str, object]:
        expected_transaction_id = transaction_id or self.deployment_id
        if journal.get("transaction_id") != expected_transaction_id:
            raise DeployError("joint_recovery_journal_not_owned")
        current = self._read_recovery_journal()
        if current is None or current[1] != self._recovery_journal_bytes(journal):
            raise DeployError("joint_recovery_journal_not_owned")
        directory_identity = self._remove_recovery_journal()
        if directory_identity is None:
            raise DeployError("joint_recovery_journal_remove_failed")
        return directory_identity

    def _remove_owned_recovery_journal_best_effort(
        self,
        journal: Mapping[str, Any] | None,
    ) -> dict[str, object]:
        if journal is None:
            return {"status": "not_applicable"}
        try:
            directory_identity = self._remove_owned_recovery_journal(journal)
        except BaseException as exc:
            return {
                "status": "retained_cleanup_failed",
                "reason": str(exc) or type(exc).__name__,
                "path": str(self.recovery_journal_path),
                "contains_secret_material": True,
            }
        return {
            "status": "removed",
            "path": str(self.recovery_journal_path),
            "contains_secret_material": True,
            "state_directory": directory_identity,
        }

    def _new_recovery_journal(
        self,
        *,
        context: Mapping[str, Any],
        rollback_tag: str,
    ) -> dict[str, Any]:
        ingress_context = dict(context.get("ingress") or {})
        ingress = ingress_context.get("lane")
        if not isinstance(ingress, PublicIngressReconciliationLane):
            raise DeployError("joint_recovery_ingress_lane_invalid")
        now = _utc_now()
        return {
            "contract_name": JOINT_RECOVERY_JOURNAL_CONTRACT_NAME,
            "version": JOINT_RECOVERY_JOURNAL_VERSION,
            "material_classification": "private_secret_bearing_recovery_state",
            "contains_secret_material": True,
            "retention_policy": "until_commit_or_verified_rollback_cleanup",
            "transaction_id": self.deployment_id,
            "phase": "prepared",
            "created_at": now,
            "updated_at": now,
            "recovery_attempts": 0,
            "api_mutation_possible": False,
            "ingress_mutation_possible": False,
            "root": str(self.root),
            "receipt_dir": str(self.receipt_dir),
            "ingress_receipt_dir": str(self.ingress_receipt_dir),
            "recovery_journal_path": str(self.recovery_journal_path),
            "transaction_receipt_path": str(self.receipt_path),
            "source_revision": str(context.get("source_revision") or ""),
            "public_origin": str(context.get("public_origin") or ""),
            "api_local_origin": str(context.get("api_local_origin") or ""),
            "docker_daemon_identity": dict(
                context.get("docker_daemon_identity") or {}
            ),
            "rollback_tag": rollback_tag,
            "rollback_context": {
                "previous": dict(context.get("previous") or {}),
                "non_memorial_controls": {
                    "openapi": dict(
                        dict(context.get("non_memorial_controls") or {}).get(
                            "openapi"
                        )
                        or {}
                    )
                },
                "deployment_input_seal": dict(
                    context.get("deployment_input_seal") or {}
                ),
                "ingress": {
                    "cloudflared_baseline": dict(
                        ingress_context.get("cloudflared_baseline") or {}
                    ),
                    "network_baseline": dict(
                        ingress_context.get("network_baseline") or {}
                    ),
                    "public_edge_baseline": dict(
                        ingress_context.get("public_edge_baseline") or {}
                    ),
                    "rollback_input_seals": [
                        dict(item)
                        for item in list(
                            ingress_context.get("rollback_input_seals") or []
                        )
                        if isinstance(item, Mapping)
                    ],
                    "rollback_interpolation_environment": dict(
                        ingress_context.get("rollback_interpolation_environment")
                        or {}
                    ),
                    "rollback_render_projection": dict(
                        ingress_context.get("rollback_render_projection") or {}
                    ),
                    "rollback_render_sha256": str(
                        ingress_context.get("rollback_render_sha256") or ""
                    ),
                },
            },
        }

    def _set_recovery_phase(
        self,
        journal: dict[str, Any],
        phase: str,
        *,
        api_mutation_possible: bool,
        ingress_mutation_possible: bool,
    ) -> None:
        if phase not in JOINT_RECOVERY_PHASES:
            raise DeployError("joint_recovery_phase_invalid")
        journal.update(
            {
                "phase": phase,
                "updated_at": _utc_now(),
                "api_mutation_possible": api_mutation_possible,
                "ingress_mutation_possible": ingress_mutation_possible,
            }
        )
        self._write_recovery_journal(journal)

    @staticmethod
    def _recovery_hex(value: object, *, lengths: tuple[int, ...] = (64,)) -> bool:
        text = str(value or "")
        return len(text) in lengths and all(
            character in "0123456789abcdef" for character in text
        )

    @staticmethod
    def _recovery_timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not 10 <= len(value) <= 64:
            raise DeployError("joint_recovery_journal_timestamp_invalid")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DeployError("joint_recovery_journal_timestamp_invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DeployError("joint_recovery_journal_timestamp_invalid")
        return parsed.astimezone(UTC)

    def _validate_recovery_ingress_baseline_schema(
        self,
        ingress_payload: Mapping[str, Any],
    ) -> None:
        cloudflared = dict(ingress_payload["cloudflared_baseline"])
        if set(cloudflared) != {
            "contract_name",
            "captured_at",
            "container",
            "contains_environment_values",
            "contains_tunnel_token",
            "restoration",
        }:
            raise DeployError("joint_recovery_cloudflared_baseline_invalid")
        container = cloudflared.get("container")
        restoration = cloudflared.get("restoration")
        if (
            cloudflared.get("contract_name")
            != "ea.public_ingress_cloudflared_baseline.v1"
            or cloudflared.get("contains_environment_values") is not False
            or cloudflared.get("contains_tunnel_token") is not False
            or not isinstance(container, Mapping)
            or not isinstance(restoration, Mapping)
            or dict(restoration)
            != {
                "status": "coordinator_required",
                "reason": "standalone_mutation_has_no_authorized_permit_boundary",
                "compose_no_deps_required": True,
                "network_removal_allowed": False,
            }
        ):
            raise DeployError("joint_recovery_cloudflared_baseline_invalid")
        self._recovery_timestamp(cloudflared.get("captured_at"))
        container = dict(container)
        expected_container_keys = {
            "id",
            "created_at",
            "image_id",
            "image_reference",
            "compose_working_dir",
            "compose_config_files",
            "compose_input_seals",
            "environment_identity",
            "command",
            "entrypoint",
            "user",
            "process_config_sha256",
            "security",
            "mounts",
            "networks",
        }
        environment_identity = container.get("environment_identity")
        security = container.get("security")
        networks = container.get("networks")
        if (
            set(container) != expected_container_keys
            or not isinstance(container.get("id"), str)
            or not container["id"]
            or not isinstance(container.get("created_at"), str)
            or not container["created_at"]
            or not str(container.get("image_id") or "").startswith("sha256:")
            or not self._recovery_hex(str(container.get("image_id"))[7:])
            or not isinstance(container.get("image_reference"), str)
            or ":" not in str(container["image_reference"])
            or not isinstance(container.get("compose_working_dir"), str)
            or not Path(container["compose_working_dir"]).is_absolute()
            or not isinstance(container.get("compose_config_files"), list)
            or not container["compose_config_files"]
            or not all(
                isinstance(item, str) and Path(item).is_absolute()
                for item in container["compose_config_files"]
            )
            or container.get("compose_input_seals")
            != ingress_payload["rollback_input_seals"]
            or not isinstance(environment_identity, Mapping)
            or set(environment_identity)
            != {"environment_sha256", "environment_count"}
            or not self._recovery_hex(
                dict(environment_identity).get("environment_sha256")
            )
            or type(dict(environment_identity).get("environment_count")) is not int
            or not isinstance(container.get("command"), list)
            or not all(isinstance(item, str) for item in container["command"])
            or not isinstance(container.get("entrypoint"), list)
            or not all(isinstance(item, str) for item in container["entrypoint"])
            or not isinstance(container.get("user"), str)
            or not self._recovery_hex(container.get("process_config_sha256"))
            or not isinstance(security, Mapping)
            or set(security)
            != {
                "cap_drop",
                "memory",
                "memory_reservation",
                "pids_limit",
                "privileged",
                "read_only",
                "restart",
                "security_opt",
            }
            or container.get("mounts") != []
            or not isinstance(networks, list)
            or not networks
            or not all(
                isinstance(item, Mapping)
                and set(item)
                == {
                    "name",
                    "network_id",
                    "driver",
                    "ipam_driver",
                    "ipam_config",
                    "internal",
                    "attachable",
                    "ipv4_address",
                    "aliases",
                }
                for item in networks
            )
        ):
            raise DeployError("joint_recovery_cloudflared_baseline_invalid")

        network = dict(ingress_payload["network_baseline"])
        if network.get("present") is False:
            if network != {"present": False}:
                raise DeployError("joint_recovery_network_baseline_invalid")
        elif (
            network.get("present") is not True
            or set(network)
            != {
                "present",
                "id",
                "name",
                "driver",
                "ipam_driver",
                "ipam_config",
                "internal",
                "attachable",
                "containers",
            }
            or not isinstance(network.get("containers"), list)
            or not all(
                isinstance(item, Mapping)
                and set(item)
                == {"container_id", "name", "ipv4_address", "ipv6_address"}
                for item in network["containers"]
            )
        ):
            raise DeployError("joint_recovery_network_baseline_invalid")

        edge = dict(ingress_payload["public_edge_baseline"])
        expected_edge_keys = {
            f"{probe.label}_{method.lower()}"
            for probe in PUBLIC_PROBES
            for method in ("GET", "HEAD")
        }
        if set(edge) != expected_edge_keys:
            raise DeployError("joint_recovery_public_edge_baseline_invalid")
        probes_by_label = {probe.label: probe for probe in PUBLIC_PROBES}
        for key, raw_row in edge.items():
            if not isinstance(raw_row, Mapping):
                raise DeployError("joint_recovery_public_edge_baseline_invalid")
            row = dict(raw_row)
            label, method_suffix = key.rsplit("_", 1)
            method = method_suffix.upper()
            probe = probes_by_label.get(label)
            if (
                probe is None
                or set(row)
                != {
                    "method",
                    "path",
                    "status",
                    "content_type",
                    "source_revision",
                    "location",
                    "body_bytes",
                    "body_sha256",
                }
                or row.get("method") != method
                or row.get("path") != probe.path
                or type(row.get("status")) is not int
                or not 100 <= int(row["status"]) <= 599
                or not isinstance(row.get("content_type"), str)
                or not isinstance(row.get("source_revision"), str)
                or not isinstance(row.get("location"), str)
                or type(row.get("body_bytes")) is not int
                or int(row["body_bytes"]) < 0
                or not self._recovery_hex(row.get("body_sha256"))
                or (method == "HEAD" and row["body_bytes"] != 0)
            ):
                raise DeployError("joint_recovery_public_edge_baseline_invalid")

    def _validate_recovery_journal(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        expected_keys = {
            "contract_name",
            "version",
            "material_classification",
            "contains_secret_material",
            "retention_policy",
            "transaction_id",
            "phase",
            "created_at",
            "updated_at",
            "recovery_attempts",
            "api_mutation_possible",
            "ingress_mutation_possible",
            "root",
            "receipt_dir",
            "ingress_receipt_dir",
            "recovery_journal_path",
            "transaction_receipt_path",
            "source_revision",
            "public_origin",
            "api_local_origin",
            "docker_daemon_identity",
            "rollback_tag",
            "rollback_context",
        }
        journal = dict(payload)
        transaction_id = str(journal.get("transaction_id") or "")
        phase = str(journal.get("phase") or "")
        api_possible = journal.get("api_mutation_possible")
        ingress_possible = journal.get("ingress_mutation_possible")
        try:
            created_at = self._recovery_timestamp(journal.get("created_at"))
            updated_at = self._recovery_timestamp(journal.get("updated_at"))
            timestamps_valid = created_at <= updated_at
        except DeployError:
            timestamps_valid = False
        phase_flags_valid = (
            (phase == "prepared" and api_possible is False and ingress_possible is False)
            or (
                phase == "api_mutation_possible"
                and api_possible is True
                and ingress_possible is False
            )
            or (
                phase in {"ingress_mutation_possible", "commit_pending"}
                and api_possible is True
                and ingress_possible is True
            )
            or (
                phase in {"rollback_in_progress", "rollback_failed"}
                and api_possible is True
                and type(ingress_possible) is bool
            )
        )
        recorded_root = Path(str(journal.get("root") or "")).expanduser()
        recorded_receipt_dir = Path(
            str(journal.get("receipt_dir") or "")
        ).expanduser()
        recorded_ingress_receipt_dir = Path(
            str(journal.get("ingress_receipt_dir") or "")
        ).expanduser()
        expected_receipt_path = recorded_receipt_dir / f"{transaction_id}.json"
        docker_daemon_identity = journal.get("docker_daemon_identity")
        if (
            set(journal) != expected_keys
            or journal.get("contract_name")
            != JOINT_RECOVERY_JOURNAL_CONTRACT_NAME
            or type(journal.get("version")) is not int
            or journal.get("version") != JOINT_RECOVERY_JOURNAL_VERSION
            or journal.get("material_classification")
            != "private_secret_bearing_recovery_state"
            or journal.get("contains_secret_material") is not True
            or journal.get("retention_policy")
            != "until_commit_or_verified_rollback_cleanup"
            or not transaction_id
            or len(transaction_id) > 128
            or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for character in transaction_id
            )
            or phase not in JOINT_RECOVERY_PHASES
            or not phase_flags_valid
            or not timestamps_valid
            or type(journal.get("recovery_attempts")) is not int
            or int(journal["recovery_attempts"]) < 0
            or not recorded_root.is_absolute()
            or ".." in recorded_root.parts
            or not recorded_receipt_dir.is_absolute()
            or ".." in recorded_receipt_dir.parts
            or not recorded_ingress_receipt_dir.is_absolute()
            or ".." in recorded_ingress_receipt_dir.parts
            or journal.get("recovery_journal_path")
            != str(self.recovery_journal_path)
            or journal.get("transaction_receipt_path")
            != str(expected_receipt_path)
            or not isinstance(docker_daemon_identity, Mapping)
            or set(docker_daemon_identity)
            != {"identity_source", "daemon_id_sha256"}
            or dict(docker_daemon_identity).get("identity_source")
            != "docker_info_engine_id"
            or not self._recovery_hex(
                dict(docker_daemon_identity).get("daemon_id_sha256")
            )
            or not self._recovery_hex(
                journal.get("source_revision"), lengths=(40, 64)
            )
        ):
            raise DeployError("joint_recovery_journal_schema_invalid")
        self.durable_root_check(recorded_root)

        for private_directory in (
            recorded_receipt_dir,
            recorded_ingress_receipt_dir,
        ):
            try:
                directory_metadata = private_directory.lstat()
            except OSError as exc:
                raise DeployError(
                    "joint_recovery_recorded_receipt_directory_invalid"
                ) from exc
            if (
                not stat.S_ISDIR(directory_metadata.st_mode)
                or stat.S_ISLNK(directory_metadata.st_mode)
                or directory_metadata.st_uid != self._recovery_state_owner_uid
                or stat.S_IMODE(directory_metadata.st_mode) != 0o700
            ):
                raise DeployError(
                    "joint_recovery_recorded_receipt_directory_invalid"
                )

        public_origin = str(journal.get("public_origin") or "")
        parsed_origin = urllib.parse.urlsplit(public_origin)
        if (
            parsed_origin.scheme != "https"
            or not parsed_origin.hostname
            or parsed_origin.username
            or parsed_origin.password
            or parsed_origin.query
            or parsed_origin.fragment
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.port not in {None, 443}
            or parsed_origin.hostname.lower().rstrip(".")
            not in set(self.allowed_public_hosts)
        ):
            raise DeployError("joint_recovery_public_origin_invalid")

        api_local_origin = str(journal.get("api_local_origin") or "")
        parsed_local_origin = urllib.parse.urlsplit(api_local_origin)
        if (
            parsed_local_origin.scheme != "http"
            or parsed_local_origin.hostname != "127.0.0.1"
            or parsed_local_origin.port is None
            or parsed_local_origin.path not in {"", "/"}
            or parsed_local_origin.query
            or parsed_local_origin.fragment
            or parsed_local_origin.username
            or parsed_local_origin.password
        ):
            raise DeployError("joint_recovery_api_local_origin_invalid")

        rollback_tag = str(journal.get("rollback_tag") or "")
        rollback_context = journal.get("rollback_context")
        if (
            rollback_tag != _safe_rollback_tag(transaction_id)
            or not isinstance(rollback_context, Mapping)
            or set(rollback_context)
            != {
                "previous",
                "non_memorial_controls",
                "deployment_input_seal",
                "ingress",
            }
        ):
            raise DeployError("joint_recovery_rollback_context_invalid")
        rollback_context = dict(rollback_context)
        previous = rollback_context.get("previous")
        non_memorial_controls = rollback_context.get("non_memorial_controls")
        deployment_input_seal = rollback_context.get("deployment_input_seal")
        ingress_payload = rollback_context.get("ingress")
        if not all(
            isinstance(item, Mapping)
            for item in (
                previous,
                non_memorial_controls,
                deployment_input_seal,
                ingress_payload,
            )
        ):
            raise DeployError("joint_recovery_rollback_context_invalid")
        previous = dict(previous)
        non_memorial_controls = dict(non_memorial_controls)
        deployment_input_seal = dict(deployment_input_seal)
        ingress_payload = dict(ingress_payload)
        working_dir = Path(str(previous.get("working_dir") or "")).expanduser()
        compose_files = list(previous.get("compose_config_files") or [])
        expected_previous = {
            "container_id",
            "created_at",
            "working_dir",
            "compose_config_files",
            "image_id",
            "image_reference",
            "rollback_environment",
            "mount_identities",
            "mount_identity_sha256",
            "mount_identity_count",
            "environment_sha256",
            "environment_count",
            "process_config_sha256",
            "state",
        }
        mount_identities = previous.get("mount_identities")
        state = previous.get("state")
        rollback_environment = previous.get("rollback_environment")
        if (
            set(previous) != expected_previous
            or not isinstance(previous.get("container_id"), str)
            or not 1 <= len(str(previous["container_id"])) <= 128
            or not isinstance(previous.get("created_at"), str)
            or not 1 <= len(str(previous["created_at"])) <= 128
            or not working_dir.is_absolute()
            or ".." in working_dir.parts
            or not compose_files
            or not all(isinstance(item, str) for item in compose_files)
            or len(set(compose_files)) != len(compose_files)
            or any(
                not Path(str(item)).is_absolute() or ".." in Path(str(item)).parts
                for item in compose_files
            )
            or not str(previous.get("image_id") or "").startswith("sha256:")
            or not self._recovery_hex(str(previous.get("image_id"))[7:])
            or not isinstance(rollback_environment, Mapping)
            or not all(
                isinstance(key, str)
                and key
                and isinstance(value, str)
                and "\x00" not in value
                and "\n" not in value
                and "\r" not in value
                for key, value in dict(rollback_environment).items()
            )
            or not isinstance(mount_identities, list)
            or not all(
                isinstance(item, Mapping)
                and set(item) == {"type", "source", "destination", "read_write"}
                and isinstance(dict(item).get("type"), str)
                and isinstance(dict(item).get("source"), str)
                and isinstance(dict(item).get("destination"), str)
                and type(dict(item).get("read_write")) is bool
                for item in mount_identities
            )
            or not self._recovery_hex(previous.get("mount_identity_sha256"))
            or type(previous.get("mount_identity_count")) is not int
            or previous.get("mount_identity_count") != len(mount_identities)
            or not self._recovery_hex(previous.get("environment_sha256"))
            or type(previous.get("environment_count")) is not int
            or int(previous["environment_count"]) < 0
            or not self._recovery_hex(previous.get("process_config_sha256"))
            or not isinstance(state, Mapping)
            or set(state) != {"running", "restarting", "started_at", "health"}
            or dict(state).get("running") is not True
            or dict(state).get("restarting") is not False
            or not isinstance(dict(state).get("started_at"), str)
            or dict(state).get("health") != "healthy"
        ):
            raise DeployError("joint_recovery_previous_api_invalid")
        try:
            _safe_tagged_image_reference(
                str(previous["image_reference"]),
                reason="joint_recovery_previous_api_invalid",
            )
        except DeployError as exc:
            raise DeployError("joint_recovery_previous_api_invalid") from exc
        openapi = non_memorial_controls.get("openapi")
        contract = dict(openapi).get("_contract") if isinstance(openapi, Mapping) else None
        if (
            set(non_memorial_controls) != {"openapi"}
            or not isinstance(openapi, Mapping)
            or set(openapi)
            != {
                "path_count",
                "operation_count",
                "schema_count",
                "security_scheme_count",
                "path_set_sha256",
                "contract_sha256",
                "probe",
                "_contract",
            }
            or not isinstance(contract, Mapping)
            or set(contract) != {"operations", "schemas", "security_schemes"}
            or not isinstance(dict(contract).get("operations"), Mapping)
            or not dict(dict(contract).get("operations") or {})
            or not isinstance(dict(contract).get("schemas"), Mapping)
            or not isinstance(dict(contract).get("security_schemes"), Mapping)
            or type(dict(openapi).get("path_count")) is not int
            or type(dict(openapi).get("operation_count")) is not int
            or type(dict(openapi).get("schema_count")) is not int
            or type(dict(openapi).get("security_scheme_count")) is not int
            or not self._recovery_hex(dict(openapi).get("path_set_sha256"))
            or not self._recovery_hex(dict(openapi).get("contract_sha256"))
            or not isinstance(dict(openapi).get("probe"), Mapping)
        ):
            raise DeployError("joint_recovery_non_memorial_baseline_invalid")
        if (
            set(deployment_input_seal) != {"forward", "rollback"}
            or not all(
                isinstance(deployment_input_seal.get(scope), list)
                and deployment_input_seal[scope]
                for scope in ("forward", "rollback")
            )
        ):
            raise DeployError("joint_recovery_deployment_seal_invalid")
        expected_ingress_keys = {
            "cloudflared_baseline",
            "network_baseline",
            "public_edge_baseline",
            "rollback_input_seals",
            "rollback_interpolation_environment",
            "rollback_render_projection",
            "rollback_render_sha256",
        }
        rollback_interpolation_environment = ingress_payload.get(
            "rollback_interpolation_environment"
        )
        rollback_render_projection = ingress_payload.get(
            "rollback_render_projection"
        )
        if (
            set(ingress_payload) != expected_ingress_keys
            or not isinstance(ingress_payload.get("cloudflared_baseline"), Mapping)
            or not isinstance(ingress_payload.get("network_baseline"), Mapping)
            or not isinstance(ingress_payload.get("public_edge_baseline"), Mapping)
            or not dict(ingress_payload["public_edge_baseline"])
            or not isinstance(ingress_payload.get("rollback_input_seals"), list)
            or not ingress_payload["rollback_input_seals"]
            or not isinstance(rollback_interpolation_environment, Mapping)
            or set(rollback_interpolation_environment) != INGRESS_ROLLBACK_ENV_KEYS
            or not all(
                isinstance(value, str)
                and value
                and "\x00" not in value
                and "\n" not in value
                and "\r" not in value
                for value in dict(rollback_interpolation_environment).values()
            )
            or not isinstance(rollback_render_projection, Mapping)
            or not self._recovery_hex(ingress_payload.get("rollback_render_sha256"))
            or _canonical_json_sha256(rollback_render_projection)
            != ingress_payload.get("rollback_render_sha256")
        ):
            raise DeployError("joint_recovery_ingress_baseline_invalid")
        if self._ingress_rollback_environment(
            dict(rollback_render_projection)
        ) != dict(rollback_interpolation_environment):
            raise DeployError("joint_recovery_ingress_environment_invalid")
        self._validate_recovery_ingress_baseline_schema(ingress_payload)
        cloudflared_container = dict(
            dict(ingress_payload["cloudflared_baseline"]).get("container") or {}
        )
        if not cloudflared_container:
            raise DeployError("joint_recovery_cloudflared_baseline_invalid")

        ingress_lane = self._build_ingress_lane(
            {
                "source_revision": journal["source_revision"],
                "public_origin": public_origin,
            },
            deployment_id=transaction_id,
            root=recorded_root,
            receipt_dir=recorded_ingress_receipt_dir,
            rollback_interpolation_environment={
                str(key): str(value)
                for key, value in dict(
                    rollback_interpolation_environment
                ).items()
            },
        )
        context = {
            "previous": previous,
            "non_memorial_controls": non_memorial_controls,
            "deployment_input_seal": deployment_input_seal,
            "source_revision": str(journal["source_revision"]),
            "public_origin": public_origin,
            "api_local_origin": api_local_origin,
            "docker_daemon_identity": dict(docker_daemon_identity),
            "recorded_root": recorded_root,
            "recorded_receipt_dir": recorded_receipt_dir,
            "recorded_ingress_receipt_dir": recorded_ingress_receipt_dir,
            "ingress": {
                "lane": ingress_lane,
                "cloudflared_baseline": dict(
                    ingress_payload["cloudflared_baseline"]
                ),
                "network_baseline": dict(ingress_payload["network_baseline"]),
                "public_edge_baseline": dict(
                    ingress_payload["public_edge_baseline"]
                ),
                "rollback_input_seals": [
                    dict(item)
                    for item in ingress_payload["rollback_input_seals"]
                    if isinstance(item, Mapping)
                ],
                "rollback_interpolation_environment": dict(
                    rollback_interpolation_environment
                ),
                "rollback_render_projection": dict(
                    rollback_render_projection
                ),
                "rollback_render_sha256": str(
                    ingress_payload["rollback_render_sha256"]
                ),
            },
        }
        if len(context["ingress"]["rollback_input_seals"]) != len(
            ingress_payload["rollback_input_seals"]
        ):
            raise DeployError("joint_recovery_ingress_seals_invalid")
        return journal, context

    @staticmethod
    def _transaction_receipt_payload_is_committed(
        payload: Mapping[str, Any],
        transaction_id: str,
        *,
        source_revision: str,
        public_origin: str,
    ) -> bool:
        atomicity = payload.get("joint_atomicity")
        preparation = payload.get("preparation")
        return bool(
            payload.get("contract_name") == JOINT_COORDINATION_CONTRACT_NAME
            and payload.get("deployment_id") == transaction_id
            and payload.get("source_revision") == source_revision
            and payload.get("public_origin") == public_origin
            and payload.get("status") in {"pass", "committed_cleanup_incident"}
            and isinstance(atomicity, Mapping)
            and dict(atomicity).get("transaction_status") == "committed"
            and dict(atomicity).get("rollback_executed") is False
            and dict(atomicity).get("rollback_execution_status") == "not_required"
            and isinstance(preparation, Mapping)
            and dict(preparation).get("status") == "complete"
            and dict(preparation).get("api_runtime_state") == "changed_verified"
            and dict(preparation).get("ingress_runtime_state") == "changed_verified"
        )

    def _read_trusted_transaction_receipt(self, path: Path) -> dict[str, Any]:
        raw = self._read_trusted_guard_file(
            path,
            expected_mode=0o600,
            expected_uid=os.geteuid(),
            max_bytes=MAX_SPATIAL_RECEIPT_BYTES,
            reason_prefix="joint_final_receipt",
        )
        return _strict_json_object(
            raw,
            reason="joint_final_receipt_json_invalid",
        )

    def _trusted_transaction_receipt_is_committed(
        self,
        path: Path,
        transaction_id: str,
        *,
        source_revision: str,
        public_origin: str,
    ) -> bool:
        with _defer_deployment_signals():
            try:
                payload = self._read_trusted_transaction_receipt(path)
            except JointDeploySignalInterruption:
                raise
            except DeployError:
                return False
        return self._transaction_receipt_payload_is_committed(
            payload,
            transaction_id,
            source_revision=source_revision,
            public_origin=public_origin,
        )

    @staticmethod
    def _require_private_receipt_directory(path: Path) -> None:
        if (
            not path.is_absolute()
            or ".." in path.parts
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
        ):
            raise DeployError("joint_cleanup_receipt_directory_invalid")
        descriptor = -1
        try:
            path_metadata = path.lstat()
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            descriptor_metadata = os.fstat(descriptor)
        except OSError as exc:
            raise DeployError("joint_cleanup_receipt_directory_invalid") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (
            stat.S_ISLNK(path_metadata.st_mode)
            or not stat.S_ISDIR(descriptor_metadata.st_mode)
            or descriptor_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(descriptor_metadata.st_mode) != 0o700
            or (descriptor_metadata.st_dev, descriptor_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise DeployError("joint_cleanup_receipt_directory_invalid")

    def _write_transaction_receipt_payload(
        self,
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        self._require_private_receipt_directory(path.parent)
        original_receipt_dir = self.receipt_dir
        original_receipt_path = self.receipt_path
        original_receipt = self.receipt
        try:
            self.receipt_dir = path.parent
            self.receipt_path = path
            self.receipt = dict(payload)
            self._write_receipt()
        finally:
            self.receipt_dir = original_receipt_dir
            self.receipt_path = original_receipt_path
            self.receipt = original_receipt

    def _require_committed_cleanup_receipt_identity(
        self,
        payload: Mapping[str, Any],
        transaction_id: str,
        *,
        source_revision: str,
        public_origin: str,
    ) -> None:
        if (
            type(source_revision) is not str
            or len(source_revision) != 40
            or any(
                character not in "0123456789abcdef"
                for character in source_revision
            )
        ):
            raise DeployError("joint_committed_cleanup_source_revision_invalid")
        try:
            validated_origin = _validate_public_origin(
                public_origin,
                allowed_hosts=self.allowed_public_hosts,
            )
            parsed_origin = urllib.parse.urlsplit(validated_origin)
            canonical_origin = (
                f"https://{str(parsed_origin.hostname or '').rstrip('.').lower()}"
            )
        except (TypeError, ValueError, DeployError) as exc:
            raise DeployError(
                "joint_committed_cleanup_public_origin_invalid"
            ) from exc
        if validated_origin != canonical_origin:
            raise DeployError("joint_committed_cleanup_public_origin_invalid")
        public_edge = payload.get("joint_public_edge")
        promotion = payload.get("candidate_promotion_evidence")
        if (
            not isinstance(public_edge, Mapping)
            or dict(public_edge).get("status") != "pass"
            or dict(public_edge).get("source_revision") != source_revision
            or type(dict(public_edge).get("request_count")) is not int
            or dict(public_edge).get("request_count") != 12
            or not isinstance(promotion, Mapping)
            or dict(promotion).get("source_revision") != source_revision
        ):
            raise DeployError("joint_committed_cleanup_source_binding_invalid")
        if not self._transaction_receipt_payload_is_committed(
            payload,
            transaction_id,
            source_revision=source_revision,
            public_origin=public_origin,
        ):
            raise DeployError("joint_committed_cleanup_receipt_invalid")

    def _normalize_committed_cleanup_pending_receipt(
        self,
        path: Path,
        transaction_id: str,
        *,
        source_revision: str,
        public_origin: str,
        journal: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected_path = path.parent / f"{transaction_id}.json"
        current_journal = self._read_recovery_journal()
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path != expected_path
            or current_journal is None
            or current_journal[1] != self._recovery_journal_bytes(journal)
            or journal.get("transaction_id") != transaction_id
        ):
            raise DeployError("joint_committed_cleanup_normalization_unsafe")
        self._require_private_receipt_directory(path.parent)
        payload = self._read_trusted_transaction_receipt(path)
        self._require_committed_cleanup_receipt_identity(
            payload,
            transaction_id,
            source_revision=source_revision,
            public_origin=public_origin,
        )
        cleanup = payload.get("recovery_journal_cleanup")
        if not isinstance(cleanup, Mapping):
            raise DeployError("joint_committed_cleanup_receipt_invalid")
        cleanup = dict(cleanup)
        status_cleanup_pair = (payload.get("status"), cleanup.get("status"))
        exact_pending = {
            "status": "pending_after_commit",
            "path": str(self.recovery_journal_path),
            "contains_secret_material": True,
        }
        retained_keys = {"contains_secret_material", "path", "reason", "status"}
        retained_valid = bool(
            status_cleanup_pair
            == ("committed_cleanup_incident", "retained_cleanup_failed")
            and payload.get("operator_action_required") is True
            and set(cleanup) == retained_keys
            and cleanup.get("path") == str(self.recovery_journal_path)
            and cleanup.get("contains_secret_material") is True
            and isinstance(cleanup.get("reason"), str)
            and bool(str(cleanup["reason"]).strip())
        )
        pending_valid = bool(
            status_cleanup_pair == ("pass", "pending_after_commit")
            and "operator_action_required" not in payload
            and cleanup == exact_pending
        )
        if not (retained_valid or pending_valid):
            raise DeployError("joint_committed_cleanup_receipt_invalid")
        normalized = dict(payload)
        normalized["status"] = "pass"
        normalized.pop("operator_action_required", None)
        normalized["recovery_journal_cleanup"] = exact_pending
        if normalized != payload:
            self._write_transaction_receipt_payload(path, normalized)
        verified = self._read_trusted_transaction_receipt(path)
        current_after = self._read_recovery_journal()
        if (
            verified != normalized
            or current_after is None
            or current_after[1] != self._recovery_journal_bytes(journal)
        ):
            raise DeployError("joint_committed_cleanup_normalization_failed")
        return normalized

    def _finalize_committed_cleanup_receipt(
        self,
        path: Path,
        transaction_id: str,
        *,
        source_revision: str,
        public_origin: str,
        expected_state_directory_identity: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        expected_path = path.parent / f"{transaction_id}.json"
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path != expected_path
        ):
            raise DeployError("joint_committed_cleanup_finalization_unsafe")
        state_directory_identity = (
            self._require_canonical_recovery_journal_absent(
                expected_directory_identity=expected_state_directory_identity
            )
        )
        self._require_private_receipt_directory(path.parent)
        payload = self._read_trusted_transaction_receipt(path)
        self._require_committed_cleanup_receipt_identity(
            payload,
            transaction_id,
            source_revision=source_revision,
            public_origin=public_origin,
        )
        cleanup = payload.get("recovery_journal_cleanup")
        if not isinstance(cleanup, Mapping):
            raise DeployError("joint_committed_cleanup_receipt_invalid")
        cleanup = dict(cleanup)
        exact_pending = {
            "status": "pending_after_commit",
            "path": str(self.recovery_journal_path),
            "contains_secret_material": True,
        }
        exact_removed = {
            **exact_pending,
            "status": "removed",
            "state_directory": state_directory_identity,
        }
        if (
            payload.get("status") != "pass"
            or "operator_action_required" in payload
            or cleanup not in (exact_pending, exact_removed)
        ):
            raise DeployError("joint_committed_cleanup_receipt_invalid")
        finalized = dict(payload)
        finalized["recovery_journal_cleanup"] = exact_removed
        try:
            with _defer_deployment_signals():
                if finalized != payload:
                    self._write_transaction_receipt_payload(path, finalized)
                verified = self._read_trusted_transaction_receipt(path)
                if (
                    verified != finalized
                    or not self._transaction_receipt_payload_is_committed(
                        verified,
                        transaction_id,
                        source_revision=source_revision,
                        public_origin=public_origin,
                    )
                ):
                    raise DeployError(
                        "joint_committed_cleanup_finalization_failed"
                    )
                self._require_canonical_recovery_journal_absent(
                    expected_directory_identity=state_directory_identity
                )
        except BaseException as exc:
            if finalized != payload:
                restoration_error: BaseException | None = None
                try:
                    with _defer_deployment_signals():
                        self._write_transaction_receipt_payload(path, payload)
                except BaseException as restore_exc:
                    restoration_error = restore_exc
                try:
                    restored = self._read_trusted_transaction_receipt(path)
                except BaseException as read_exc:
                    restored = {}
                    restoration_error = restoration_error or read_exc
                if restored != payload:
                    raise DeployError(
                        "joint_committed_cleanup_finalization_restore_failed"
                    ) from (restoration_error or exc)
            raise
        return finalized

    def _acquire_cleanup_finalizer_lock(self) -> None:
        self._global_lock_handle = self._open_lock(
            self.global_lock_path,
            busy_reason="memorial_api_deployment_already_running",
        )
        try:
            self._lock_handle = self._open_lock(
                self.lock_path,
                busy_reason="deployment_already_running",
            )
        except BaseException:
            self._release_lock()
            raise

    def finalize_committed_cleanup(self) -> dict[str, Any]:
        """Repair only cleanup metadata after securely proving the journal absent."""
        self._acquire_cleanup_finalizer_lock()
        try:
            self._require_private_receipt_directory(self.receipt_dir)
            payload = self._read_trusted_transaction_receipt(self.receipt_path)
            source_revision = str(payload.get("source_revision") or "")
            public_origin = str(payload.get("public_origin") or "")
            finalized = self._finalize_committed_cleanup_receipt(
                self.receipt_path,
                self.deployment_id,
                source_revision=source_revision,
                public_origin=public_origin,
            )
            self.receipt = finalized
            return self.receipt
        finally:
            self._release_lock()

    def _prevalidate_recovery_context(
        self,
        context: Mapping[str, Any],
        rollback_tag: str,
    ) -> None:
        deployment_input_seal = dict(context["deployment_input_seal"])
        self._require_docker_daemon_identity(
            dict(context["docker_daemon_identity"])
        )
        self._require_deployment_input_seal(
            deployment_input_seal,
            scope="rollback",
        )
        ingress_context = dict(context["ingress"])
        rollback_input_seals = list(ingress_context["rollback_input_seals"])
        self._revalidate_ingress_input_seals(rollback_input_seals)
        ingress_lane = ingress_context["lane"]
        if not isinstance(ingress_lane, PublicIngressReconciliationLane):
            raise DeployError("joint_recovery_ingress_lane_invalid")
        baseline = dict(ingress_context["cloudflared_baseline"])
        container = dict(baseline.get("container") or {})
        prior_root = Path(
            str(container.get("compose_working_dir") or "")
        ).expanduser()
        prior_files = [
            str(item)
            for item in list(container.get("compose_config_files") or [])
            if str(item)
        ]
        if not prior_root.is_absolute() or ".." in prior_root.parts or not prior_files:
            raise DeployError("joint_recovery_ingress_topology_invalid")
        rendered, rendered_seals = ingress_lane._render_compose(
            root=prior_root,
            files=prior_files,
            expected_input_seals=rollback_input_seals,
        )
        if (
            rendered_seals != rollback_input_seals
            or self._ingress_rollback_projection(rendered)
            != ingress_context["rollback_render_projection"]
            or _canonical_json_sha256(
                self._ingress_rollback_projection(rendered)
            )
            != ingress_context["rollback_render_sha256"]
        ):
            raise DeployError("joint_recovery_ingress_render_changed")
        previous = dict(context["previous"])
        self._rollback_environment(previous)
        self._verify_rollback_renderability(previous)
        protected = self._inspect_image(rollback_tag)
        if protected.get("image_id") != previous.get("image_id"):
            raise DeployError("joint_recovery_protected_image_mismatch")
        self._require_deployment_input_seal(
            deployment_input_seal,
            scope="rollback",
        )
        self._revalidate_ingress_input_seals(rollback_input_seals)

    def _recover_interrupted_transaction(self, *, preflight_only: bool) -> None:
        journal_record = self._read_recovery_journal()
        if journal_record is None:
            return
        payload, raw = journal_record
        try:
            journal, context = self._validate_recovery_journal(payload)
        except DeployError as exc:
            self.receipt["status"] = "recovery_journal_invalid"
            self.receipt["recovery"] = {
                "status": "blocked_invalid_journal",
                "journal_sha256": _sha256(raw),
                "reason": str(exc),
                "mutation_attempted": False,
                "permit_requested": False,
            }
            self._write_receipt()
            raise
        transaction_id = str(journal["transaction_id"])
        transaction_receipt_path = Path(str(journal["transaction_receipt_path"]))
        journal_sha256 = _sha256(raw)
        if self._trusted_transaction_receipt_is_committed(
            transaction_receipt_path,
            transaction_id,
            source_revision=str(journal["source_revision"]),
            public_origin=str(journal["public_origin"]),
        ):
            self._normalize_committed_cleanup_pending_receipt(
                transaction_receipt_path,
                transaction_id,
                source_revision=str(journal["source_revision"]),
                public_origin=str(journal["public_origin"]),
                journal=journal,
            )
            removed_state_directory_identity = self._remove_owned_recovery_journal(
                journal,
                transaction_id=transaction_id,
            )
            finalized_receipt = self._finalize_committed_cleanup_receipt(
                transaction_receipt_path,
                transaction_id,
                source_revision=str(journal["source_revision"]),
                public_origin=str(journal["public_origin"]),
                expected_state_directory_identity=(
                    removed_state_directory_identity
                ),
            )
            self.receipt["recovery"] = {
                "status": "committed_transaction_confirmed",
                "transaction_id": transaction_id,
                "journal_sha256": journal_sha256,
                "transaction_receipt_path": str(transaction_receipt_path),
                "transaction_receipt_cleanup": dict(
                    finalized_receipt["recovery_journal_cleanup"]
                ),
                "mutation_attempted": False,
                "permit_requested": False,
            }
            return
        api_possible = bool(journal["api_mutation_possible"])
        ingress_possible = bool(journal["ingress_mutation_possible"])
        if not api_possible and not ingress_possible:
            self._remove_recovery_journal()
            self.receipt["recovery"] = {
                "status": "prepared_transaction_abandoned",
                "transaction_id": transaction_id,
                "journal_sha256": journal_sha256,
                "mutation_attempted": False,
                "permit_requested": False,
            }
            return
        if preflight_only:
            self.receipt["status"] = "recovery_required"
            self.receipt["recovery"] = {
                "status": "blocked_preflight_only",
                "transaction_id": transaction_id,
                "journal_sha256": journal_sha256,
                "mutation_attempted": False,
                "permit_requested": False,
            }
            self._write_receipt()
            raise DeployError("joint_recovery_required")

        self.receipt["status"] = "recovering_interrupted_transaction"
        self.receipt["recovery"] = {
            "status": "in_progress",
            "transaction_id": transaction_id,
            "journal_sha256": journal_sha256,
            "api_mutation_possible": api_possible,
            "ingress_mutation_possible": ingress_possible,
            "permit_requested": False,
        }
        self._write_receipt()
        ingress_lane = dict(context["ingress"])["lane"]
        if not isinstance(ingress_lane, PublicIngressReconciliationLane):
            raise DeployError("joint_recovery_ingress_lane_invalid")
        previous_timeout_provider = ingress_lane.command_timeout_provider
        with (
            _defer_deployment_signals() as controller,
            self._ensure_rollback_deadline_scope(),
        ):
            ingress_lane.command_timeout_provider = (
                self._remaining_vexp_mutation_seconds
            )
            try:
                self._prevalidate_recovery_context(
                    context,
                    str(journal["rollback_tag"]),
                )
                journal["recovery_attempts"] = int(journal["recovery_attempts"]) + 1
                self._set_recovery_phase(
                    journal,
                    "rollback_in_progress",
                    api_mutation_possible=api_possible,
                    ingress_mutation_possible=ingress_possible,
                )
                rollback = self._perform_joint_rollback(
                    context=context,
                    api_mutation_started=api_possible,
                    ingress_mutation_started=ingress_possible,
                    rollback_tag=str(journal["rollback_tag"]),
                )
                if controller is not None and controller.deferred_signal_counts:
                    rollback["deferred_signals"] = controller.deferred_receipt()
                self.receipt["status"] = "interrupted_transaction_recovered"
                self.receipt["rollback"] = rollback
                self.receipt["recovery"] = {
                    "status": "pass",
                    "transaction_id": transaction_id,
                    "journal_sha256": journal_sha256,
                    "api_mutation_possible": api_possible,
                    "ingress_mutation_possible": ingress_possible,
                    "permit_requested": False,
                    "completed_at": _utc_now(),
                }
                self._write_receipt()
                self._remove_recovery_journal()
            except BaseException as exc:
                try:
                    self._set_recovery_phase(
                        journal,
                        "rollback_failed",
                        api_mutation_possible=api_possible,
                        ingress_mutation_possible=ingress_possible,
                    )
                except BaseException as journal_exc:
                    self.receipt["recovery_journal_update_failure"] = str(
                        journal_exc
                    ) or type(journal_exc).__name__
                self.receipt["status"] = "interrupted_transaction_recovery_failed"
                self.receipt["recovery"] = {
                    "status": "fail",
                    "transaction_id": transaction_id,
                    "journal_sha256": journal_sha256,
                    "reason": str(exc) or type(exc).__name__,
                    "api_mutation_possible": api_possible,
                    "ingress_mutation_possible": ingress_possible,
                    "permit_requested": False,
                }
                self._write_receipt()
                raise DeployError(
                    "joint_interrupted_transaction_recovery_failed:"
                    f"{str(exc) or type(exc).__name__}"
                ) from exc
            finally:
                ingress_lane.command_timeout_provider = previous_timeout_provider

    def _build_ingress_lane(
        self,
        context: Mapping[str, Any],
        *,
        deployment_id: str | None = None,
        root: Path | None = None,
        receipt_dir: Path | None = None,
        rollback_interpolation_environment: Mapping[str, str] | None = None,
    ) -> PublicIngressReconciliationLane:
        if rollback_interpolation_environment is None:
            ingress_env = dict(self.env)
        else:
            if set(rollback_interpolation_environment) != INGRESS_ROLLBACK_ENV_KEYS:
                raise DeployError("joint_recovery_ingress_environment_invalid")
            ingress_env = {
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                **{
                    key: str(self.env[key])
                    for key in DOCKER_TRANSPORT_ENV_KEYS
                    if key in self.env and str(self.env[key])
                },
                **{
                    key: str(value)
                    for key, value in rollback_interpolation_environment.items()
                },
            }
        ingress_env.update(
            {
                "EA_DEPLOYMENT_ID": deployment_id or self.deployment_id,
                "EA_SOURCE_REVISION": str(context["source_revision"]),
                "EA_PUBLIC_ORIGIN": str(context["public_origin"]),
            }
        )
        return PublicIngressReconciliationLane(
            root=(root or self.root),
            env=ingress_env,
            runner=self.runner,
            http_no_redirect=self.http_no_redirect,
            receipt_dir=(receipt_dir or self.ingress_receipt_dir),
            global_lock_path=self.global_lock_path,
            request_timeout_seconds=self.request_timeout_seconds,
        )

    def _capture_docker_daemon_identity(self) -> dict[str, str]:
        completed = self._run(
            ["docker", "info", "--format", "{{json .ID}}"],
            check=False,
        )
        if completed.returncode != 0:
            raise DeployError("joint_docker_daemon_identity_unavailable")
        try:
            daemon_id = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise DeployError("joint_docker_daemon_identity_invalid") from exc
        if (
            not isinstance(daemon_id, str)
            or not 1 <= len(daemon_id) <= 256
            or any(ord(character) < 32 for character in daemon_id)
        ):
            raise DeployError("joint_docker_daemon_identity_invalid")
        return {
            "identity_source": "docker_info_engine_id",
            "daemon_id_sha256": _sha256(daemon_id.encode("utf-8")),
        }

    def _require_docker_daemon_identity(
        self,
        expected: Mapping[str, str],
    ) -> None:
        if dict(expected) != self._capture_docker_daemon_identity():
            raise DeployError("joint_recovery_docker_daemon_changed")

    @staticmethod
    def _ingress_rollback_projection(rendered: Mapping[str, Any]) -> dict[str, Any]:
        services = rendered.get("services")
        networks = rendered.get("networks")
        if not isinstance(services, Mapping) or not isinstance(networks, Mapping):
            raise DeployError("joint_ingress_rollback_projection_invalid")
        service = dict(services).get(CLOUDFLARED_SERVICE)
        if not isinstance(service, Mapping):
            raise DeployError("joint_ingress_rollback_projection_invalid")
        service_networks = dict(service).get("networks")
        if isinstance(service_networks, Mapping):
            network_names = set(service_networks)
        elif isinstance(service_networks, list) and all(
            isinstance(item, str) for item in service_networks
        ):
            network_names = set(service_networks)
        else:
            raise DeployError("joint_ingress_rollback_projection_invalid")
        if network_names != {"public_ingress", "property_default"}:
            raise DeployError("joint_ingress_rollback_projection_invalid")
        selected_networks = {
            name: dict(networks)[name]
            for name in sorted(network_names)
            if name in networks
        }
        if set(selected_networks) != network_names:
            raise DeployError("joint_ingress_rollback_projection_invalid")
        return {
            "service": dict(service),
            "networks": selected_networks,
        }

    @staticmethod
    def _ingress_rollback_environment(
        projection: Mapping[str, Any],
    ) -> dict[str, str]:
        service = projection.get("service")
        networks = projection.get("networks")
        if not isinstance(service, Mapping) or not isinstance(networks, Mapping):
            raise DeployError("joint_ingress_rollback_environment_invalid")
        environment = dict(service).get("environment")
        if not isinstance(environment, Mapping):
            raise DeployError("joint_ingress_rollback_environment_invalid")
        service_networks = dict(service).get("networks")
        if not isinstance(service_networks, Mapping):
            raise DeployError("joint_ingress_rollback_environment_invalid")
        public_endpoint = dict(service_networks).get("public_ingress")
        public_network = dict(networks).get("public_ingress")
        if not isinstance(public_endpoint, Mapping) or not isinstance(
            public_network, Mapping
        ):
            raise DeployError("joint_ingress_rollback_environment_invalid")
        ipam = dict(public_network).get("ipam")
        configs = dict(ipam).get("config") if isinstance(ipam, Mapping) else None
        if (
            not isinstance(configs, list)
            or len(configs) != 1
            or not isinstance(configs[0], Mapping)
        ):
            raise DeployError("joint_ingress_rollback_environment_invalid")
        values = {
            "EA_CF_TUNNEL_TOKEN": str(dict(environment).get("TUNNEL_TOKEN") or ""),
            "EA_PUBLIC_INGRESS_CLOUDFLARED_IPV4": str(
                dict(public_endpoint).get("ipv4_address") or ""
            ),
            "EA_PUBLIC_INGRESS_NETWORK_NAME": str(
                dict(public_network).get("name") or ""
            ),
            "EA_PUBLIC_INGRESS_SUBNET": str(dict(configs[0]).get("subnet") or ""),
            "EA_PUBLIC_INGRESS_GATEWAY": str(dict(configs[0]).get("gateway") or ""),
        }
        if set(values) != INGRESS_ROLLBACK_ENV_KEYS or any(
            not value or "\x00" in value or "\n" in value or "\r" in value
            for value in values.values()
        ):
            raise DeployError("joint_ingress_rollback_environment_invalid")
        return values

    @staticmethod
    def _check_detail(receipt: Mapping[str, Any], name: str) -> dict[str, Any]:
        matches = [
            dict(item)
            for item in list(receipt.get("checks") or [])
            if isinstance(item, dict)
            and item.get("name") == name
            and item.get("status") == "pass"
        ]
        if len(matches) != 1:
            raise DeployError(f"joint_ingress_check_missing:{name}")
        return matches[0]

    @staticmethod
    def _revalidate_ingress_input_seals(
        seals: Sequence[Mapping[str, object]],
    ) -> None:
        if not seals:
            raise DeployError("joint_ingress_input_seals_missing")
        file_seal_keys = {
            "path",
            "sha256",
            "size_bytes",
            "mode",
            "device",
            "inode",
            "uid",
            "gid",
            "link_count",
            "mtime_ns",
            "ctime_ns",
        }
        for raw_expected in seals:
            expected = dict(raw_expected)
            path = Path(str(expected.get("path") or ""))
            if not path.is_absolute() or ".." in path.parts:
                raise DeployError("joint_ingress_input_seal_invalid")
            optional_absent = (
                set(expected) == {"path", "present"}
                and expected.get("present") is False
            )
            optional_present = (
                set(expected) == {"present", *file_seal_keys}
                and expected.get("present") is True
            )
            if optional_absent or optional_present:
                if (
                    path.name != ".env.local"
                ):
                    raise DeployError("joint_ingress_input_seal_invalid")
                current_optional = _trusted_optional_private_file_seal(path)
                if current_optional != expected:
                    raise DeployError(f"joint_ingress_input_changed:{path.name}")
                continue
            if set(expected) != file_seal_keys:
                raise DeployError("joint_ingress_input_seal_invalid")
            current = _trusted_file_seal(
                path,
                private=str(expected["mode"]) == "0600",
                expected_uid=int(expected["uid"]),
            )
            if current != expected:
                raise DeployError(f"joint_ingress_input_changed:{path.name}")

    @staticmethod
    def _network_payload(
        completed: subprocess.CompletedProcess[str],
    ) -> dict[str, Any]:
        payload = _completed_json(
            completed, reason="joint_public_ingress_network_inspect_invalid"
        )
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError("joint_public_ingress_network_inspect_invalid")
        return dict(payload[0])

    def _capture_public_network(
        self, ingress: PublicIngressReconciliationLane
    ) -> dict[str, Any]:
        completed = ingress._run(
            ["docker", "network", "inspect", PUBLIC_INGRESS_NETWORK],
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").casefold()
            if "not found" in detail or "no such network" in detail:
                return {"present": False}
            raise DeployError("joint_public_ingress_network_inspect_failed")
        network = self._network_payload(completed)
        containers: list[dict[str, str]] = []
        for container_id, raw_membership in sorted(
            dict(network.get("Containers") or {}).items()
        ):
            membership = (
                dict(raw_membership) if isinstance(raw_membership, dict) else {}
            )
            containers.append(
                {
                    "container_id": str(container_id),
                    "name": str(membership.get("Name") or ""),
                    "ipv4_address": str(membership.get("IPv4Address") or ""),
                    "ipv6_address": str(membership.get("IPv6Address") or ""),
                }
            )
        ipam = dict(network.get("IPAM") or {})
        return {
            "present": True,
            "id": str(network.get("Id") or ""),
            "name": str(network.get("Name") or ""),
            "driver": str(network.get("Driver") or ""),
            "ipam_driver": str(ipam.get("Driver") or ""),
            "ipam_config": list(ipam.get("Config") or []),
            "internal": bool(network.get("Internal")),
            "attachable": bool(network.get("Attachable")),
            "containers": containers,
        }

    def _capture_public_edge(self, public_origin: str) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        for probe in PUBLIC_PROBES:
            url = f"{public_origin}{probe.path}"
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise DeployError("joint_public_snapshot_url_invalid")
            for method in ("GET", "HEAD"):
                remaining = self._remaining_vexp_mutation_seconds()
                timeout_seconds = self.request_timeout_seconds
                if remaining is not None:
                    timeout_seconds = min(timeout_seconds, remaining)
                response = self.public_snapshot(
                    url, timeout_seconds, method
                )
                if not 100 <= response.status <= 599:
                    raise DeployError("joint_public_snapshot_status_invalid")
                if method == "HEAD" and response.body:
                    raise DeployError("joint_public_snapshot_head_body_invalid")
                headers = {
                    str(key).casefold(): str(value)
                    for key, value in dict(response.headers or {}).items()
                }
                source_revision = str(response.source_revision or "")
                if len(source_revision) > 128 or any(
                    ord(character) < 32 for character in source_revision
                ):
                    raise DeployError("joint_public_snapshot_revision_invalid")
                evidence[f"{probe.label}_{method.lower()}"] = {
                    "method": method,
                    "path": probe.path,
                    "status": response.status,
                    "content_type": response.content_type,
                    "source_revision": source_revision,
                    "location": headers.get("location", ""),
                    "body_bytes": len(response.body),
                    "body_sha256": _sha256(response.body),
                }
        return evidence

    def _capture_stable_public_edge(self, public_origin: str) -> dict[str, Any]:
        first = self._capture_public_edge(public_origin)
        if self._capture_public_edge(public_origin) != first:
            raise DeployError("joint_public_snapshot_unstable")
        return first

    @staticmethod
    def _cloudflared_identity(
        baseline: Mapping[str, Any],
    ) -> dict[str, Any]:
        container = dict(baseline.get("container") or {})
        return {
            key: container.get(key)
            for key in (
                "image_id",
                "image_reference",
                "compose_working_dir",
                "compose_config_files",
                "environment_identity",
                "command",
                "entrypoint",
                "user",
                "process_config_sha256",
                "security",
                "mounts",
                "networks",
            )
        }

    @staticmethod
    def _network_rollback_identity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Compare stable network topology while tolerating recreated container IDs."""
        if not snapshot.get("present"):
            return {"present": False}
        containers = [
            {
                "name": str(row.get("name") or ""),
                "ipv4_address": str(row.get("ipv4_address") or ""),
                "ipv6_address": str(row.get("ipv6_address") or ""),
            }
            for row in list(snapshot.get("containers") or [])
            if isinstance(row, Mapping)
        ]
        containers.sort(
            key=lambda row: (
                row["name"],
                row["ipv4_address"],
                row["ipv6_address"],
            )
        )
        return {
            key: snapshot.get(key)
            for key in (
                "present",
                "id",
                "name",
                "driver",
                "ipam_driver",
                "ipam_config",
                "internal",
                "attachable",
            )
        } | {"containers": containers}

    def _preflight_ingress(
        self,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        ingress = self._build_ingress_lane(context)
        ingress._write_receipt()
        ingress._git_source_preflight()
        ingress._detect_compose()
        target_input_seals = ingress._capture_compose_input_seals(
            root=self.root,
            files=ingress.target_compose_files,
        )
        network_baseline = self._capture_public_network(ingress)
        cloudflared_baseline = ingress._capture_cloudflared_baseline()
        target_rendered = ingress._validate_target_compose(
            expected_input_seals=target_input_seals,
        )
        target_check = self._check_detail(ingress.receipt, "target_compose")
        target_seals = [
            dict(item)
            for item in list(target_check.get("compose_input_seals") or [])
            if isinstance(item, dict)
        ]
        if target_seals != [dict(item) for item in target_input_seals]:
            raise DeployError("joint_ingress_target_input_seals_changed")
        rollback_seals = [
            dict(item)
            for item in list(
                dict(cloudflared_baseline.get("container") or {}).get(
                    "compose_input_seals"
                )
                or []
            )
            if isinstance(item, dict)
        ]
        baseline_container = dict(cloudflared_baseline.get("container") or {})
        rollback_root = Path(
            str(baseline_container.get("compose_working_dir") or "")
        )
        rollback_files = [
            str(item)
            for item in list(baseline_container.get("compose_config_files") or [])
            if str(item)
        ]
        rollback_rendered, rollback_render_seals = ingress._render_compose(
            root=rollback_root,
            files=rollback_files,
            expected_input_seals=rollback_seals,
        )
        if rollback_render_seals != rollback_seals:
            raise DeployError("joint_ingress_rollback_render_seals_changed")
        rollback_projection = self._ingress_rollback_projection(rollback_rendered)
        rollback_render_sha256 = _canonical_json_sha256(rollback_projection)
        rollback_interpolation_environment = self._ingress_rollback_environment(
            rollback_projection
        )
        self._revalidate_ingress_input_seals([*target_seals, *rollback_seals])
        public_origin = str(context["public_origin"])
        public_edge_baseline = self._capture_stable_public_edge(public_origin)
        ingress.receipt.update(
            {
                "status": "joint_preflight_pass",
                "coordinator": {
                    "status": "delegated",
                    "contract_name": JOINT_COORDINATION_CONTRACT_NAME,
                    "joint_rollback_baselines_captured": True,
                    "mutation_executed": False,
                },
                "permit_contract": {
                    "contract_name": self.vexp_mutation_permit_contract_name,
                    "version": self.vexp_mutation_permit_version,
                    "authorized_boundaries": list(self.vexp_mutation_boundaries),
                    "ingress_boundary_authorized": True,
                },
                "completed_at": _utc_now(),
            }
        )
        ingress._write_receipt()
        self.receipt["ingress_preflight"] = {
            "receipt_path": str(ingress.receipt_path),
            "receipt_sha256": _sha256(ingress.receipt_path.read_bytes()),
            "baseline_path": str(ingress.baseline_path),
            "baseline_sha256": _sha256(ingress.baseline_path.read_bytes()),
            "target_compose_files": list(TARGET_COMPOSE_FILES),
            "public_network_preexisting": bool(network_baseline.get("present")),
            "public_edge_stability_sample_count": 2,
            "public_edge_request_count_per_sample": len(public_edge_baseline),
            "public_edge_request_count": len(public_edge_baseline) * 2,
        }
        self._record_check(
            "joint_ingress_preflight",
            "pass",
            ingress_receipt_path=str(ingress.receipt_path),
            ingress_receipt_sha256=_sha256(ingress.receipt_path.read_bytes()),
            target_compose_files=list(TARGET_COMPOSE_FILES),
            public_network_preexisting=bool(network_baseline.get("present")),
            public_edge_stability_sample_count=2,
            public_edge_request_count_per_sample=len(public_edge_baseline),
            public_edge_request_count=len(public_edge_baseline) * 2,
        )
        return {
            "lane": ingress,
            "cloudflared_baseline": cloudflared_baseline,
            "network_baseline": network_baseline,
            "public_edge_baseline": public_edge_baseline,
            "rollback_input_seals": rollback_seals,
            "rollback_interpolation_environment": (
                rollback_interpolation_environment
            ),
            "rollback_render_projection": rollback_projection,
            "rollback_render_sha256": rollback_render_sha256,
            "target_input_seals": target_seals,
            "target_rendered": target_rendered,
        }

    def preflight(self) -> dict[str, Any]:
        context = super().preflight()
        spatial_browser_binding = self._load_spatial_browser_binding(
            dict(context["candidate_promotion"])
        )
        self.receipt["spatial_browser_binding"] = dict(spatial_browser_binding)
        self._record_check(
            "spatial_browser_binding",
            "pass",
            browser_receipt_path=spatial_browser_binding["browser_receipt_path"],
            browser_receipt_sha256=spatial_browser_binding[
                "browser_receipt_sha256"
            ],
            candidate_runtime_receipt_sha256=spatial_browser_binding[
                "candidate_runtime_receipt_sha256"
            ],
            exact_embedded_binding=True,
        )
        ingress = self._preflight_ingress(context)
        docker_daemon_identity = self._capture_docker_daemon_identity()
        self.receipt["joint_atomicity"] = {
            "api_rollback_baseline_verified": True,
            "ingress_rollback_baseline_verified": True,
            "network_rollback_baseline_captured": True,
            "public_edge_rollback_baseline_captured": True,
            "rollback_executed": False,
            "rollback_execution_status": "not_executed",
            "baseline_semantics": (
                "prechange-inputs-captured-and-rollback-renderability-validated"
            ),
        }
        self.receipt["status"] = "joint_preflight_pass"
        self._write_receipt()
        return {
            **context,
            "api_local_origin": self._local_origin(),
            "docker_daemon_identity": docker_daemon_identity,
            "ingress": ingress,
            "spatial_browser_binding": spatial_browser_binding,
        }

    def _read_spatial_private_json(
        self,
        path: Path,
        *,
        reason_prefix: str,
    ) -> tuple[dict[str, Any], bytes]:
        if not path.is_absolute() or ".." in path.parts:
            raise DeployError(f"{reason_prefix}_path_invalid")
        raw = self._read_trusted_guard_file(
            path,
            expected_mode=0o600,
            expected_uid=os.geteuid(),
            max_bytes=MAX_SPATIAL_RECEIPT_BYTES,
            reason_prefix=reason_prefix,
        )
        return _strict_json_object(raw, reason=f"{reason_prefix}_json_invalid"), raw

    def _load_spatial_browser_binding(
        self,
        candidate_promotion_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence = dict(candidate_promotion_evidence)
        configured_browser_path = str(
            self.env.get(SPATIAL_BROWSER_RECEIPT_ENV) or ""
        ).strip()
        if not configured_browser_path:
            raise DeployError("joint_spatial_browser_receipt_required")
        browser_path = Path(configured_browser_path).expanduser()
        candidate_path = Path(str(evidence.get("path") or "")).expanduser()
        candidate, candidate_raw = self._read_spatial_private_json(
            candidate_path,
            reason_prefix="joint_spatial_candidate_runtime_receipt",
        )
        browser, browser_raw = self._read_spatial_private_json(
            browser_path,
            reason_prefix="joint_spatial_browser_receipt",
        )
        candidate_sha256 = _sha256(candidate_raw)
        browser_sha256 = _sha256(browser_raw)
        runtime = candidate.get("spatial_handoff_runtime")
        embedded = (
            dict(runtime).get("candidate_browser_gate")
            if isinstance(runtime, Mapping)
            else None
        )
        evidence_spatial = evidence.get("spatial_handoff")
        if (
            candidate_sha256 != evidence.get("sha256")
            or evidence.get("schema") != CANDIDATE_RUNTIME_SCHEMA
            or evidence.get("status") != "pass"
            or candidate.get("schema") != CANDIDATE_RUNTIME_SCHEMA
            or candidate.get("status") != "pass"
            or browser.get("schema") != CANDIDATE_BROWSER_SCHEMA
            or browser.get("status") != "pass"
            or browser.get("secret_material_recorded") is not False
            or not isinstance(embedded, Mapping)
            or dict(embedded) != browser
            or not isinstance(evidence_spatial, Mapping)
            or dict(evidence_spatial).get("browser_schema")
            != CANDIDATE_BROWSER_SCHEMA
            or dict(evidence_spatial).get("browser_pass") is not True
            or dict(evidence_spatial).get("identity_bound") is not True
        ):
            raise DeployError("joint_spatial_browser_binding_invalid")
        return {
            "status": "pass",
            "candidate_runtime_receipt_path": str(candidate_path),
            "candidate_runtime_receipt_sha256": candidate_sha256,
            "candidate_runtime_schema": CANDIDATE_RUNTIME_SCHEMA,
            "browser_receipt_path": str(browser_path),
            "browser_receipt_sha256": browser_sha256,
            "browser_schema": CANDIDATE_BROWSER_SCHEMA,
            "secret_material_recorded": False,
            "exact_embedded_binding": True,
        }

    def _require_spatial_browser_binding(
        self,
        context: Mapping[str, Any],
    ) -> None:
        expected = dict(context.get("spatial_browser_binding") or {})
        current = self._load_spatial_browser_binding(
            dict(context["candidate_promotion"])
        )
        if not expected or current != expected:
            raise DeployError("joint_spatial_browser_binding_changed")

    def _spatial_materializer_handoff(
        self,
        candidate_promotion_evidence: Mapping[str, Any],
        spatial_browser_binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence = dict(candidate_promotion_evidence)
        candidate_path = Path(str(evidence.get("path") or ""))
        candidate_sha256 = str(evidence.get("sha256") or "")
        spatial = dict(evidence.get("spatial_handoff") or {})
        browser_binding = dict(spatial_browser_binding)
        if (
            not candidate_path.is_absolute()
            or ".." in candidate_path.parts
            or evidence.get("schema") != CANDIDATE_RUNTIME_SCHEMA
            or evidence.get("status") != "pass"
            or len(candidate_sha256) != 64
            or any(character not in "0123456789abcdef" for character in candidate_sha256)
            or spatial.get("browser_schema") != CANDIDATE_BROWSER_SCHEMA
            or spatial.get("browser_pass") is not True
            or spatial.get("identity_bound") is not True
            or browser_binding.get("status") != "pass"
            or browser_binding.get("candidate_runtime_receipt_path")
            != str(candidate_path)
            or browser_binding.get("candidate_runtime_receipt_sha256")
            != candidate_sha256
            or browser_binding.get("browser_schema") != CANDIDATE_BROWSER_SCHEMA
            or browser_binding.get("secret_material_recorded") is not False
            or browser_binding.get("exact_embedded_binding") is not True
        ):
            raise DeployError("joint_spatial_materializer_handoff_invalid")
        return {
            "deploy_receipt": {
                "environment": SPATIAL_DEPLOY_RECEIPT_ENV,
                "path": str(self.receipt_path),
                "contract_name": str(self.receipt["contract_name"]),
            },
            "candidate_runtime_receipt": {
                "path": str(candidate_path),
                "sha256": candidate_sha256,
                "schema": CANDIDATE_RUNTIME_SCHEMA,
            },
            "candidate_browser_receipt": {
                "environment": SPATIAL_BROWSER_RECEIPT_ENV,
                "path": str(browser_binding["browser_receipt_path"]),
                "sha256": str(browser_binding["browser_receipt_sha256"]),
                "schema": CANDIDATE_BROWSER_SCHEMA,
                "exact_binding": (
                    "candidate_runtime.spatial_handoff_runtime."
                    "candidate_browser_gate"
                ),
            },
        }

    def _recreate_cloudflared(self, ingress: PublicIngressReconciliationLane) -> None:
        args = ingress._compose_args(root=self.root, files=ingress.target_compose_files)
        self._run(
            [
                *args,
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                CLOUDFLARED_SERVICE,
            ],
            env=ingress.release_env,
        )

    def _verify_forward_cloudflared(
        self,
        ingress_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        ingress = ingress_context["lane"]
        if not isinstance(ingress, PublicIngressReconciliationLane):
            raise DeployError("joint_ingress_lane_invalid")
        self._wait_container(CLOUDFLARED_CONTAINER, require_health=False)
        original_path = ingress.baseline_path
        forward_path = ingress.receipt_dir / (f"{self.deployment_id}.forward.json")
        ingress.baseline_path = forward_path
        try:
            forward = ingress._capture_cloudflared_baseline()
        finally:
            ingress.baseline_path = original_path
        container = dict(forward.get("container") or {})
        expected_files = [
            str((self.root / name).resolve()) for name in TARGET_COMPOSE_FILES
        ]
        networks = {
            str(item.get("name") or ""): dict(item)
            for item in list(container.get("networks") or [])
            if isinstance(item, dict)
        }
        public_network = networks.get(PUBLIC_INGRESS_NETWORK, {})
        if (
            container.get("image_reference") != PINNED_CLOUDFLARED_IMAGE
            or container.get("compose_working_dir") != str(self.root)
            or container.get("compose_config_files") != expected_files
            or set(networks)
            != {
                PUBLIC_INGRESS_NETWORK,
                PROPERTY_NETWORK,
            }
            or public_network.get("ipv4_address") != PUBLIC_INGRESS_CLOUDFLARED_IPV4
        ):
            raise DeployError("joint_forward_cloudflared_identity_mismatch")
        ingress._validate_api_runtime_posture(forward)
        self.receipt["forward_cloudflared"] = {
            "receipt_path": str(forward_path),
            "receipt_sha256": _sha256(forward_path.read_bytes()),
            "image_id": container.get("image_id"),
            "image_reference": container.get("image_reference"),
            "network_names": sorted(networks),
            "public_ingress_ipv4": public_network.get("ipv4_address"),
        }
        self._record_check(
            "forward_cloudflared",
            "pass",
            image_id=container.get("image_id"),
            image_reference=container.get("image_reference"),
            network_names=sorted(networks),
            public_ingress_ipv4=public_network.get("ipv4_address"),
        )
        return forward

    @staticmethod
    def _rollback_ingress_environment(
        source: Mapping[str, str],
    ) -> dict[str, str]:
        environment = {str(key): str(value) for key, value in source.items()}
        environment["COMPOSE_PROJECT_NAME"] = "ea"
        return environment

    def _rollback_cloudflared(
        self,
        ingress_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        ingress = ingress_context["lane"]
        if not isinstance(ingress, PublicIngressReconciliationLane):
            raise DeployError("joint_ingress_lane_invalid")
        self._revalidate_ingress_input_seals(
            list(ingress_context["rollback_input_seals"])
        )
        baseline = dict(ingress_context["cloudflared_baseline"])
        container = dict(baseline.get("container") or {})
        prior_root = Path(
            str(container.get("compose_working_dir") or "")
        ).expanduser()
        if not prior_root.is_absolute() or ".." in prior_root.parts:
            raise DeployError("joint_ingress_rollback_working_dir_invalid")
        prior_files = [
            str(item)
            for item in list(container.get("compose_config_files") or [])
            if str(item)
        ]
        if not prior_files:
            raise DeployError("joint_ingress_rollback_topology_missing")
        rollback_rendered, rollback_render_seals = ingress._render_compose(
            root=prior_root,
            files=prior_files,
            expected_input_seals=list(ingress_context["rollback_input_seals"]),
        )
        if (
            rollback_render_seals
            != list(ingress_context["rollback_input_seals"])
            or self._ingress_rollback_projection(rollback_rendered)
            != ingress_context["rollback_render_projection"]
            or _canonical_json_sha256(
                self._ingress_rollback_projection(rollback_rendered)
            )
            != ingress_context["rollback_render_sha256"]
        ):
            raise DeployError("joint_ingress_rollback_render_changed")
        args = ingress._compose_args(root=prior_root, files=prior_files)
        self._run(
            [
                *args,
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                CLOUDFLARED_SERVICE,
            ],
            cwd=prior_root,
            env=self._rollback_ingress_environment(ingress.release_env),
        )
        self._revalidate_ingress_input_seals(
            list(ingress_context["rollback_input_seals"])
        )
        self._wait_container(CLOUDFLARED_CONTAINER, require_health=False)
        restore_path = ingress.receipt_dir / (f"{self.deployment_id}.restored.json")
        original_path = ingress.baseline_path
        ingress.baseline_path = restore_path
        try:
            restored = ingress._capture_cloudflared_baseline()
        finally:
            ingress.baseline_path = original_path
        if self._cloudflared_identity(restored) != self._cloudflared_identity(baseline):
            raise DeployError("joint_ingress_rollback_identity_mismatch")
        return {
            "status": "pass",
            "completed_at": _utc_now(),
            "receipt_path": str(restore_path),
            "receipt_sha256": _sha256(restore_path.read_bytes()),
            "identity_restored": True,
        }

    def _restore_public_network(
        self,
        ingress_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        ingress = ingress_context["lane"]
        if not isinstance(ingress, PublicIngressReconciliationLane):
            raise DeployError("joint_ingress_lane_invalid")
        baseline = dict(ingress_context["network_baseline"])
        current = self._capture_public_network(ingress)
        if baseline.get("present"):
            if self._network_rollback_identity(
                current
            ) != self._network_rollback_identity(baseline):
                raise DeployError("joint_public_network_rollback_mismatch")
            return {"status": "pass", "preexisting": True, "removed": False}
        if not current.get("present"):
            return {"status": "pass", "preexisting": False, "removed": False}
        if (
            current.get("name") != PUBLIC_INGRESS_NETWORK
            or current.get("driver") != "bridge"
            or current.get("ipam_driver") != "default"
            or current.get("containers") != []
            or current.get("ipam_config")
            != [
                {
                    "Subnet": PUBLIC_INGRESS_SUBNET,
                    "Gateway": PUBLIC_INGRESS_GATEWAY,
                }
            ]
        ):
            raise DeployError("joint_public_network_cleanup_unsafe")
        self._run(["docker", "network", "rm", PUBLIC_INGRESS_NETWORK])
        final = self._capture_public_network(ingress)
        if final.get("present"):
            raise DeployError("joint_public_network_cleanup_failed")
        return {"status": "pass", "preexisting": False, "removed": True}

    def _perform_joint_rollback(
        self,
        *,
        context: Mapping[str, Any],
        api_mutation_started: bool,
        ingress_mutation_started: bool,
        rollback_tag: str,
    ) -> dict[str, Any]:
        original_wait_seconds = self.wait_seconds
        original_request_timeout_seconds = self.request_timeout_seconds
        ingress_context = dict(context.get("ingress") or {})
        ingress_lane = ingress_context.get("lane")
        if not isinstance(ingress_lane, PublicIngressReconciliationLane):
            raise DeployError("joint_ingress_lane_invalid")
        original_ingress_timeout_provider = ingress_lane.command_timeout_provider
        original_recovery_local_origin = self._recovery_local_origin
        recovery_local_origin = str(context.get("api_local_origin") or "")
        if recovery_local_origin:
            self._recovery_local_origin = recovery_local_origin
        with (
            _defer_deployment_signals() as controller,
            self._ensure_rollback_deadline_scope(),
        ):
            remaining = self._remaining_vexp_mutation_seconds()
            if remaining is None:  # pragma: no cover - deadline scope invariant
                raise DeployError("joint_rollback_deadline_missing")
            self.wait_seconds = min(self.wait_seconds, remaining)
            self.request_timeout_seconds = min(
                self.request_timeout_seconds,
                remaining,
            )
            ingress_lane.command_timeout_provider = (
                self._remaining_vexp_mutation_seconds
            )
            try:
                result = self._perform_joint_rollback_components(
                    context=context,
                    api_mutation_started=api_mutation_started,
                    ingress_mutation_started=ingress_mutation_started,
                    rollback_tag=rollback_tag,
                )
                if controller is not None and controller.deferred_signal_counts:
                    result["deferred_signals"] = controller.deferred_receipt()
                return result
            finally:
                self.wait_seconds = original_wait_seconds
                self.request_timeout_seconds = original_request_timeout_seconds
                ingress_lane.command_timeout_provider = (
                    original_ingress_timeout_provider
                )
                self._recovery_local_origin = original_recovery_local_origin

    def _perform_joint_rollback_components(
        self,
        *,
        context: Mapping[str, Any],
        api_mutation_started: bool,
        ingress_mutation_started: bool,
        rollback_tag: str,
    ) -> dict[str, Any]:
        failures: list[str] = []
        result: dict[str, Any] = {
            "status": "in_progress",
            "api": {"status": "not_required"},
            "ingress": {"status": "not_required"},
            "network": {"status": "not_required"},
            "public_edge": {"status": "not_checked"},
        }
        atomicity = dict(self.receipt.get("joint_atomicity") or {})
        atomicity.update(
            {
                "rollback_executed": True,
                "rollback_execution_status": "in_progress",
            }
        )
        self.receipt["joint_atomicity"] = atomicity
        ingress_context = dict(context["ingress"])
        if ingress_mutation_started:
            try:
                self._remaining_vexp_mutation_seconds()
                result["ingress"] = self._rollback_cloudflared(ingress_context)
                self._remaining_vexp_mutation_seconds()
            except BaseException as exc:  # rollback must survive a second interrupt
                failures.append(f"ingress:{str(exc) or type(exc).__name__}")
                result["ingress"] = {
                    "status": "fail",
                    "reason": str(exc) or type(exc).__name__,
                }
        self._rollback_boundary_checkpoint("after_ingress")
        if api_mutation_started:
            try:
                self._remaining_vexp_mutation_seconds()
                result["api"] = self._rollback(
                    dict(context["previous"]),
                    rollback_tag,
                    dict(context["non_memorial_controls"]),
                    context["deployment_input_seal"],
                )
                self._remaining_vexp_mutation_seconds()
            except BaseException as exc:  # rollback must survive a second interrupt
                failures.append(f"api:{str(exc) or type(exc).__name__}")
                result["api"] = {
                    "status": "fail",
                    "reason": str(exc) or type(exc).__name__,
                }
        self._rollback_boundary_checkpoint("after_api")
        if api_mutation_started or ingress_mutation_started:
            try:
                self._remaining_vexp_mutation_seconds()
                result["network"] = self._restore_public_network(ingress_context)
                self._remaining_vexp_mutation_seconds()
            except BaseException as exc:
                failures.append(f"network:{str(exc) or type(exc).__name__}")
                result["network"] = {
                    "status": "fail",
                    "reason": str(exc) or type(exc).__name__,
                }
        self._rollback_boundary_checkpoint("after_network")
        if not failures:
            try:
                self._remaining_vexp_mutation_seconds()
                restored_edge = self._capture_public_edge(str(context["public_origin"]))
                if restored_edge != ingress_context["public_edge_baseline"]:
                    raise DeployError("joint_public_edge_rollback_mismatch")
                result["public_edge"] = {
                    "status": "pass",
                    "request_count": len(restored_edge),
                    "matches_predeploy": True,
                }
                self._remaining_vexp_mutation_seconds()
            except BaseException as exc:
                failures.append(f"public_edge:{str(exc) or type(exc).__name__}")
                result["public_edge"] = {
                    "status": "fail",
                    "reason": str(exc) or type(exc).__name__,
                }
        result["completed_at"] = _utc_now()
        if failures:
            result["status"] = "fail"
            result["failures"] = failures
            atomicity.update(
                {
                    "rollback_execution_status": "fail",
                    "rollback_components": {
                        component: dict(result[component])["status"]
                        for component in ("api", "ingress", "network", "public_edge")
                    },
                }
            )
            self.receipt["joint_atomicity"] = atomicity
            self.receipt["rollback"] = result
            self._write_receipt()
            raise DeployError("joint_rollback_failed:" + "|".join(failures))
        result["status"] = "pass"
        atomicity.update(
            {
                "rollback_execution_status": "pass",
                "rollback_components": {
                    component: dict(result[component])["status"]
                    for component in ("api", "ingress", "network", "public_edge")
                },
            }
        )
        self.receipt["joint_atomicity"] = atomicity
        return result

    def _rollback_boundary_checkpoint(self, _boundary: str) -> None:
        """A no-op scheduling point kept inside whole-rollback signal deferral."""

    def _final_receipt_is_irrevocably_committed(self) -> bool:
        return self._trusted_transaction_receipt_is_committed(
            self.receipt_path,
            self.deployment_id,
            source_revision=str(self.receipt.get("source_revision") or ""),
            public_origin=str(self.receipt.get("public_origin") or ""),
        )

    def deploy(self, *, preflight_only: bool = False) -> dict[str, Any]:
        context: dict[str, Any] = {}
        rollback_tag = ""
        api_mutation_started = False
        ingress_mutation_started = False
        postdeploy_evidence_completed = False
        preparation_attempted: list[str] = []
        preparation_completed: list[str] = []
        pending_action: str | None = None
        active_action: str | None = None
        transaction_committed = False
        recovery_journal: dict[str, Any] | None = None

        def persist_preparation(
            status: str,
            *,
            api_runtime_state: str = "unchanged",
            ingress_runtime_state: str = "unchanged",
        ) -> None:
            self.receipt["preparation"] = {
                "status": status,
                "attempted_actions": list(preparation_attempted),
                "completed_actions": list(preparation_completed),
                "pending_action": pending_action,
                "active_action": active_action,
                "preparation_side_effects_possible": bool(preparation_attempted),
                "api_mutation_started": api_mutation_started,
                "ingress_mutation_started": ingress_mutation_started,
                "api_runtime_state": api_runtime_state,
                "ingress_runtime_state": ingress_runtime_state,
            }
            self._write_receipt()

        self._acquire_lock()
        try:
            self._recover_interrupted_transaction(preflight_only=preflight_only)
            context = self.preflight()
            self.receipt["source_revision"] = str(
                context.get("source_revision") or ""
            )
            self.receipt["public_origin"] = str(context.get("public_origin") or "")
            if preflight_only:
                self.receipt["status"] = "preflight_only_pass"
                self.receipt["completed_at"] = _utc_now()
                self._write_receipt()
                return self.receipt

            ingress_context = dict(context["ingress"])
            ingress = ingress_context["lane"]
            if not isinstance(ingress, PublicIngressReconciliationLane):
                raise DeployError("joint_ingress_lane_invalid")

            self._require_spatial_browser_binding(context)
            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._revalidate_ingress_input_seals(
                [
                    *ingress_context["target_input_seals"],
                    *ingress_context["rollback_input_seals"],
                ]
            )
            pending_action = "ensure_redis"
            persist_preparation("authorization_pending")
            with self._vexp_mutation_lease("before_ensure_redis"):
                pending_action = None
                active_action = "ensure_redis"
                preparation_attempted.append("ensure_redis")
                persist_preparation("in_progress")
                self._ensure_redis()
            preparation_completed.append("ensure_redis")
            active_action = None
            persist_preparation("in_progress")

            self._require_spatial_browser_binding(context)
            pending_action = "protect_previous_image"
            persist_preparation("authorization_pending")
            with self._vexp_mutation_lease("before_protect_previous_image"):
                pending_action = None
                active_action = "protect_previous_image"
                preparation_attempted.append("protect_previous_image")
                persist_preparation("in_progress")
                rollback_tag = self._protect_previous_image(dict(context["previous"]))
            preparation_completed.append("protect_previous_image")
            active_action = None
            self.receipt["rollback"] = {
                "status": "available",
                "api_image_tag": rollback_tag,
                "api_working_dir": dict(context["previous"])["working_dir"],
                "ingress_baseline_path": str(ingress.baseline_path),
            }
            recovery_journal = self._new_recovery_journal(
                context=context,
                rollback_tag=rollback_tag,
            )
            recovery_journal_sha256 = self._write_recovery_journal(recovery_journal)
            self.receipt["recovery_journal"] = {
                "contract_name": JOINT_RECOVERY_JOURNAL_CONTRACT_NAME,
                "path": str(self.recovery_journal_path),
                "sha256": recovery_journal_sha256,
                "phase": "prepared",
                "durable_before_mutation": True,
            }
            persist_preparation("api_authorization_pending")

            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._require_spatial_browser_binding(context)
            self._revalidate_ingress_input_seals(ingress_context["target_input_seals"])
            self.receipt["status"] = "changing_api"
            pending_action = "recreate_api"
            persist_preparation("api_authorization_pending")
            with self._vexp_mutation_lease("before_recreate_api"):
                pending_action = None
                active_action = "recreate_api"
                preparation_attempted.append("recreate_api")
                if recovery_journal is None:  # pragma: no cover - ordering invariant
                    raise DeployError("joint_recovery_journal_missing")
                self._set_recovery_phase(
                    recovery_journal,
                    "api_mutation_possible",
                    api_mutation_possible=True,
                    ingress_mutation_possible=False,
                )
                api_mutation_started = True
                persist_preparation(
                    "api_mutation_in_progress",
                    api_runtime_state="mutation_possible",
                )
                self._recreate_api()
            preparation_completed.append("recreate_api")
            active_action = None
            persist_preparation(
                "api_changed_pending_verification",
                api_runtime_state="changed_pending_verification",
            )
            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._revalidate_ingress_input_seals(
                [
                    *ingress_context["target_input_seals"],
                    *ingress_context["rollback_input_seals"],
                ]
            )

            api_detail = self._wait_container(API_SERVICE, require_health=True)
            api_identity = self._verify_forward_api(
                candidate=dict(context["candidate"]),
                source_revision=str(context["source_revision"]),
                expected_mounts=list(context["target_mounts"]),
                expected_projection=dict(
                    dict(context["candidate_promotion"]).get("projection") or {}
                ),
            )
            self._record_check(
                "api_container",
                "pass",
                **api_detail,
                identity=api_identity,
            )
            local_origin = self._local_origin()
            local_probes = [
                self._wait_http(f"{local_origin}/health", kind="health"),
                self._wait_http(
                    f"{local_origin}/memorials/manfred",
                    kind="html",
                    expected_source_revision=str(context["source_revision"]),
                ),
                self._wait_http(
                    f"{local_origin}/memorials/manfred.json",
                    kind="json",
                    expected_source_revision=str(context["source_revision"]),
                ),
            ]
            self._verify_non_memorial_controls(
                dict(context["non_memorial_controls"]),
                internal_openapi=True,
            )
            local_candidate = self._verify_candidate_origin(
                label="local",
                base_url=local_origin,
                public_origin=str(context["public_origin"]),
            )
            self.receipt["joint_local_api_proof"] = {
                "probes": local_probes,
                "candidate_verifier": local_candidate,
            }
            self._record_check("joint_local_api_proof", "pass")

            # Prove the reserved address is free or belongs to the old tunnel.
            ingress._validate_api_runtime_posture(
                ingress_context["cloudflared_baseline"]
            )
            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._require_spatial_browser_binding(context)
            self._revalidate_ingress_input_seals(
                [
                    *ingress_context["target_input_seals"],
                    *ingress_context["rollback_input_seals"],
                ]
            )
            self.receipt["status"] = "changing_ingress"
            pending_action = "recreate_cloudflared"
            persist_preparation(
                "ingress_authorization_pending",
                api_runtime_state="changed_verified_locally",
            )
            with self._vexp_mutation_lease(INGRESS_MUTATION_BOUNDARY):
                pending_action = None
                active_action = "recreate_cloudflared"
                preparation_attempted.append("recreate_cloudflared")
                if recovery_journal is None:  # pragma: no cover - ordering invariant
                    raise DeployError("joint_recovery_journal_missing")
                self._set_recovery_phase(
                    recovery_journal,
                    "ingress_mutation_possible",
                    api_mutation_possible=True,
                    ingress_mutation_possible=True,
                )
                ingress_mutation_started = True
                persist_preparation(
                    "ingress_mutation_in_progress",
                    api_runtime_state="changed_verified_locally",
                    ingress_runtime_state="mutation_possible",
                )
                self._recreate_cloudflared(ingress)
            preparation_completed.append("recreate_cloudflared")
            active_action = None
            persist_preparation(
                "joint_changed_pending_verification",
                api_runtime_state="changed_verified_locally",
                ingress_runtime_state="changed_pending_verification",
            )
            self._require_deployment_input_seal(context["deployment_input_seal"])
            self._revalidate_ingress_input_seals(
                [
                    *ingress_context["target_input_seals"],
                    *ingress_context["rollback_input_seals"],
                ]
            )

            self._verify_forward_cloudflared(ingress_context)
            self._verify_deployed_surface(
                str(context["public_origin"]),
                source_revision=str(context["source_revision"]),
                candidate_promotion_evidence=dict(context["candidate_promotion"]),
            )
            public_candidate = self._verify_candidate_origin(
                label="public",
                base_url=str(context["public_origin"]),
                public_origin=str(context["public_origin"]),
            )
            self.receipt["candidate_verifier"] = [
                local_candidate,
                public_candidate,
            ]
            self._record_check("candidate_verifier_origin", "pass", origin="public")
            self._record_check("local_and_public_candidate_verifier", "pass")
            public_edge = ingress._verify_public_origin()
            self.receipt["joint_public_edge"] = {
                "status": "pass",
                "request_count": len(public_edge),
                "source_revision": context["source_revision"],
            }
            self._require_spatial_browser_binding(context)
            spatial_materializer_handoff = self._spatial_materializer_handoff(
                dict(context["candidate_promotion"]),
                dict(context["spatial_browser_binding"]),
            )
            self._materialize_and_verify_release_evidence(
                phase="postdeploy",
                deployment_input_seal=context["deployment_input_seal"],
                expected_public_origin=str(context["public_origin"]),
                expected_authority_posture=str(
                    dict(context["authority"]).get("authority_posture") or ""
                ),
            )
            postdeploy_evidence_completed = True

            self._require_spatial_browser_binding(context)
            self.receipt["spatial_materializer_handoff"] = spatial_materializer_handoff

            with _defer_deployment_signals() as commit_signal_controller:
                if recovery_journal is None:  # pragma: no cover - ordering invariant
                    raise DeployError("joint_recovery_journal_missing")
                self._set_recovery_phase(
                    recovery_journal,
                    "commit_pending",
                    api_mutation_possible=True,
                    ingress_mutation_possible=True,
                )
                self.receipt["status"] = "pass"
                self.receipt["completed_at"] = _utc_now()
                self.receipt["joint_atomicity"] = {
                    "api_rollback_baseline_verified": True,
                    "ingress_rollback_baseline_verified": True,
                    "network_rollback_baseline_captured": True,
                    "public_edge_rollback_baseline_captured": True,
                    "rollback_executed": False,
                    "rollback_execution_status": "not_required",
                    "transaction_status": "committed",
                    "baseline_semantics": (
                        "prechange-inputs-captured-and-rollback-renderability-validated"
                    ),
                }
                self.receipt["preparation"] = {
                    "status": "complete",
                    "attempted_actions": list(preparation_attempted),
                    "completed_actions": list(preparation_completed),
                    "pending_action": pending_action,
                    "active_action": active_action,
                    "preparation_side_effects_possible": bool(preparation_attempted),
                    "api_mutation_started": api_mutation_started,
                    "ingress_mutation_started": ingress_mutation_started,
                    "api_runtime_state": "changed_verified",
                    "ingress_runtime_state": "changed_verified",
                }
                self.receipt["recovery_journal_cleanup"] = {
                    "status": "pending_after_commit",
                    "path": str(self.recovery_journal_path),
                    "contains_secret_material": True,
                }
                # This is the one durable, irrevocable transaction commit point.
                self._write_receipt()
                transaction_committed = True
                self.receipt["recovery_journal_cleanup"] = (
                    self._remove_owned_recovery_journal_best_effort(recovery_journal)
                )
                cleanup_failed = (
                    self.receipt["recovery_journal_cleanup"].get("status")
                    == "retained_cleanup_failed"
                )
                if cleanup_failed:
                    self.receipt["status"] = "committed_cleanup_incident"
                    self.receipt["operator_action_required"] = True
                # Post-commit metadata only; transaction truth was durable above.
                if (
                    commit_signal_controller is not None
                    and commit_signal_controller.deferred_signal_counts
                ):
                    self.receipt["postcommit_deferred_signals"] = (
                        commit_signal_controller.deferred_receipt()
                    )
                self._write_receipt()
                if cleanup_failed:
                    raise JointCommittedCleanupIncident(
                        "joint_committed_recovery_journal_cleanup_failed"
                    )
                removed_cleanup = dict(
                    self.receipt["recovery_journal_cleanup"]
                )
                state_directory = removed_cleanup.get("state_directory")
                if (
                    set(removed_cleanup)
                    != {
                        "contains_secret_material",
                        "path",
                        "state_directory",
                        "status",
                    }
                    or not isinstance(state_directory, Mapping)
                ):
                    raise JointCommittedCleanupIncident(
                        "joint_committed_cleanup_evidence_invalid"
                    )
                self._require_canonical_recovery_journal_absent(
                    expected_directory_identity=dict(state_directory)
                )
            return self.receipt
        except (Exception, KeyboardInterrupt) as exc:
            if transaction_committed or self._final_receipt_is_irrevocably_committed():
                transaction_committed = True
                if isinstance(exc, JointCommittedCleanupIncident):
                    raise
                cleanup = self.receipt.get("recovery_journal_cleanup")
                if not isinstance(cleanup, Mapping) or dict(cleanup).get(
                    "status"
                ) != "removed":
                    self.receipt["recovery_journal_cleanup"] = (
                        self._remove_owned_recovery_journal_best_effort(
                            recovery_journal
                        )
                    )
                cleanup_retained = (
                    self.receipt["recovery_journal_cleanup"].get("status")
                    != "removed"
                )
                try:
                    journal_still_present = self._read_recovery_journal() is not None
                except BaseException:
                    # A committed transaction must never report success when the
                    # secret-bearing journal cannot be proven absent.
                    journal_still_present = True
                if cleanup_retained or journal_still_present:
                    self.receipt["status"] = "committed_cleanup_incident"
                    self.receipt["operator_action_required"] = True
                    raise JointCommittedCleanupIncident(
                        "joint_committed_recovery_journal_cleanup_failed"
                    ) from exc
                self.receipt["status"] = "pass"
                self.receipt.pop("operator_action_required", None)
                publication_error: BaseException | None = None
                with _defer_deployment_signals():
                    try:
                        self._write_receipt()
                    except BaseException as write_exc:
                        publication_error = write_exc
                    try:
                        durable_payload = self._read_trusted_transaction_receipt(
                            self.receipt_path
                        )
                        cleanup_is_durable = bool(
                            durable_payload == self.receipt
                            and self._transaction_receipt_payload_is_committed(
                                durable_payload,
                                self.deployment_id,
                                source_revision=str(
                                    self.receipt.get("source_revision") or ""
                                ),
                                public_origin=str(
                                    self.receipt.get("public_origin") or ""
                                ),
                            )
                        )
                        durable_cleanup = dict(
                            durable_payload.get("recovery_journal_cleanup") or {}
                        )
                        durable_state_directory = durable_cleanup.get(
                            "state_directory"
                        )
                        cleanup_is_durable = bool(
                            cleanup_is_durable
                            and set(durable_cleanup)
                            == {
                                "contains_secret_material",
                                "path",
                                "state_directory",
                                "status",
                            }
                            and durable_cleanup.get("status") == "removed"
                            and durable_cleanup.get("path")
                            == str(self.recovery_journal_path)
                            and durable_cleanup.get("contains_secret_material")
                            is True
                            and isinstance(durable_state_directory, Mapping)
                        )
                        if cleanup_is_durable:
                            self._require_canonical_recovery_journal_absent(
                                expected_directory_identity=dict(
                                    durable_state_directory
                                )
                            )
                    except BaseException:
                        cleanup_is_durable = False
                if not cleanup_is_durable:
                    self.receipt["status"] = "committed_cleanup_incident"
                    self.receipt["operator_action_required"] = True
                    raise JointCommittedCleanupIncident(
                        "joint_committed_cleanup_evidence_publication_failed"
                    ) from (publication_error or exc)
                return self.receipt
            original_error = str(exc) or type(exc).__name__
            self.receipt["failure"] = {
                "at": _utc_now(),
                "reason": original_error,
                "type": type(exc).__name__,
                "api_mutation_started": api_mutation_started,
                "ingress_mutation_started": ingress_mutation_started,
            }
            if postdeploy_evidence_completed:
                self.receipt["postdeploy_evidence_disposition"] = {
                    "status": "superseded",
                    "reason": "joint_transaction_did_not_commit",
                    "superseded_at": _utc_now(),
                }
            if context and (api_mutation_started or ingress_mutation_started):
                with _defer_deployment_signals() as signal_controller:
                    try:
                        if recovery_journal is not None:
                            try:
                                self._set_recovery_phase(
                                    recovery_journal,
                                    "rollback_in_progress",
                                    api_mutation_possible=api_mutation_started,
                                    ingress_mutation_possible=ingress_mutation_started,
                                )
                            except BaseException as journal_exc:
                                self.receipt["recovery_journal_update_failure"] = (
                                    str(journal_exc) or type(journal_exc).__name__
                                )
                        rollback = self._perform_joint_rollback(
                            context=context,
                            api_mutation_started=api_mutation_started,
                            ingress_mutation_started=ingress_mutation_started,
                            rollback_tag=rollback_tag,
                        )
                        if (
                            signal_controller is not None
                            and signal_controller.deferred_signal_counts
                        ):
                            rollback["deferred_signals"] = (
                                signal_controller.deferred_receipt()
                            )
                        self.receipt["status"] = "failed_rolled_back"
                        self.receipt["rollback"] = rollback
                        persist_preparation(
                            "joint_mutation_failed_rolled_back",
                            api_runtime_state="restored_by_rollback",
                            ingress_runtime_state=(
                                "restored_by_rollback"
                                if ingress_mutation_started
                                else "unchanged"
                            ),
                        )
                        self.receipt["completed_at"] = _utc_now()
                        self.receipt["recovery_journal_cleanup"] = {
                            "status": "pending_after_verified_rollback",
                            "path": str(self.recovery_journal_path),
                            "contains_secret_material": True,
                        }
                        self._write_receipt()
                        self.receipt["recovery_journal_cleanup"] = (
                            self._remove_owned_recovery_journal_best_effort(
                                recovery_journal
                            )
                        )
                        self._write_receipt()
                        raise DeployError(
                            f"joint_deployment_failed_rolled_back:{original_error}"
                        ) from exc
                    except DeployError as rollback_exc:
                        if str(rollback_exc).startswith(
                            "joint_deployment_failed_rolled_back:"
                        ):
                            raise
                        self.receipt["status"] = "rollback_failed"
                        rollback_detail = dict(self.receipt.get("rollback") or {})
                        rollback_detail.update(
                            {
                                "status": "fail",
                                "reason": str(rollback_exc),
                                "primary_failure": original_error,
                            }
                        )
                        if (
                            signal_controller is not None
                            and signal_controller.deferred_signal_counts
                        ):
                            rollback_detail["deferred_signals"] = (
                                signal_controller.deferred_receipt()
                            )
                        self.receipt["rollback"] = rollback_detail
                        if recovery_journal is not None:
                            try:
                                self._set_recovery_phase(
                                    recovery_journal,
                                    "rollback_failed",
                                    api_mutation_possible=api_mutation_started,
                                    ingress_mutation_possible=ingress_mutation_started,
                                )
                            except BaseException as journal_exc:
                                self.receipt["recovery_journal_update_failure"] = (
                                    str(journal_exc) or type(journal_exc).__name__
                                )
                        persist_preparation(
                            "joint_mutation_rollback_failed",
                            api_runtime_state="unknown_after_failed_rollback",
                            ingress_runtime_state="unknown_after_failed_rollback",
                        )
                        self.receipt["completed_at"] = _utc_now()
                        self._write_receipt()
                        raise DeployError(
                            "joint_deployment_and_rollback_failed:"
                            f"{original_error}:{rollback_exc}"
                        ) from rollback_exc
            if preparation_attempted:
                failed_during_action = active_action is not None
                self.receipt["status"] = (
                    "failed_during_preparation"
                    if failed_during_action
                    else "failed_after_preparation"
                )
                persist_preparation(
                    (
                        "failed_during_action"
                        if failed_during_action
                        else "failed_before_api_mutation"
                    )
                )
                self.receipt["rollback"] = {
                    "status": "not_required",
                    "reason": "api_and_ingress_unchanged",
                    **(
                        {"protected_api_image_tag": rollback_tag}
                        if rollback_tag
                        else {}
                    ),
                }
            elif pending_action is not None:
                if self.receipt.get("status") != "blocked_vexp_soak":
                    self.receipt["status"] = "authorization_failed"
                self.receipt["preparation"] = {
                    "status": "authorization_failed",
                    "attempted_actions": [],
                    "completed_actions": [],
                    "pending_action": pending_action,
                    "active_action": None,
                    "preparation_side_effects_possible": False,
                    "api_mutation_started": False,
                    "ingress_mutation_started": False,
                    "api_runtime_state": "unchanged",
                    "ingress_runtime_state": "unchanged",
                }
                self.receipt["rollback"] = {
                    "status": "not_required",
                    "reason": "no_mutation_attempted",
                }
            elif self.receipt.get("status") not in {
                "blocked_vexp_soak",
                "recovery_journal_invalid",
                "recovery_required",
                "interrupted_transaction_recovery_failed",
            }:
                self.receipt["status"] = "preflight_failed"
            self.receipt["completed_at"] = _utc_now()
            self._write_receipt()
            if (
                recovery_journal is not None
                and not api_mutation_started
                and not ingress_mutation_started
            ):
                self.receipt["recovery_journal_cleanup"] = (
                    self._remove_owned_recovery_journal_best_effort(recovery_journal)
                )
                self._write_receipt()
            if isinstance(exc, (DeployError, KeyboardInterrupt)):
                raise
            raise DeployError(original_error) from exc
        finally:
            self._release_lock()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Atomically deploy governed Manfred ea-api plus public ingress.")
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Capture and validate API, ingress, network, and public-edge "
            "rollback baselines without mutation."
        ),
    )
    mode.add_argument(
        "--finalize-committed-cleanup",
        action="store_true",
        help=(
            "Atomically finalize a trusted committed receipt after securely "
            "proving the canonical recovery journal absent; performs no runtime "
            "mutation."
        ),
    )
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--receipt-dir", type=Path, default=None)
    return parser.parse_args(argv)


@contextmanager
def _deployment_signal_handlers() -> Iterator[_DeploymentSignalController]:
    global _ACTIVE_SIGNAL_CONTROLLER
    handled = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        handled.append(signal.SIGHUP)
    previous: dict[signal.Signals, Any] = {}
    previous_controller = _ACTIVE_SIGNAL_CONTROLLER
    controller = _DeploymentSignalController()

    try:
        for signum in handled:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, controller.handle)
        _ACTIVE_SIGNAL_CONTROLLER = controller
        yield controller
    finally:
        _ACTIVE_SIGNAL_CONTROLLER = previous_controller
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        lane = JointMemorialIngressDeployLane(
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            receipt_dir=args.receipt_dir,
        )
        with _deployment_signal_handlers():
            if args.finalize_committed_cleanup:
                receipt = lane.finalize_committed_cleanup()
            else:
                receipt = lane.deploy(preflight_only=bool(args.preflight_only))
    except KeyboardInterrupt:
        print("joint memorial deploy interrupted", file=sys.stderr)
        return 130
    except DeployError as exc:
        print(f"joint memorial deploy failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
