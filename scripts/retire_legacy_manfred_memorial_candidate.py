#!/usr/bin/env python3
"""Read-only audit for the unbound legacy Manfred candidate.

The historical ``ea-manfred-candidate`` project is outside the managed v4
candidate namespace.  This controller can identify that exact project and bind
two stable Docker observations, but it has no Docker mutation primitive and
never grants retirement authority.  ``--apply`` is retained only as an explicit
fail-closed compatibility boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cleanup_manfred_memorial_candidates import (  # noqa: E402
    FLEET_LOCK_PATH,
    LIVE_COMPOSE_PROJECT,
    _container_inventory,
)
from scripts.manfred_candidate_fleet_lock import (  # noqa: E402
    hold_candidate_fleet_lock,
)
from scripts.manfred_candidate_registry import (  # noqa: E402
    _read_private_json,
    _validated_registry,
    default_registry_path,
)


RECEIPT_SCHEMA = "ea.manfred_memorial_legacy_candidate_retirement.v2"
LEGACY_PROJECT = "ea-manfred-candidate"
LEGACY_PORT = 18090
EXPECTED_SERVICES = frozenset({"api", "gateway", "postgres", "redis"})
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
MAX_RECEIPT_BYTES = 1024 * 1024


def _utc_now() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_error(exc: BaseException) -> str:
    code = str(exc)
    if code.startswith("manfred_legacy_candidate_audit_"):
        return code
    if code.startswith("manfred_candidate_"):
        return code
    return "manfred_legacy_candidate_audit_failed"


def _receipt_bytes(payload: dict[str, object]) -> bytes:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if not 1 <= len(encoded) <= MAX_RECEIPT_BYTES:
        raise RuntimeError("manfred_legacy_candidate_audit_receipt_size_invalid")
    return encoded


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    """Publish one private receipt without replacing any existing path."""

    destination = Path(path).expanduser()
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    try:
        parent = destination.parent.resolve(strict=True)
        parent_status = parent.stat()
    except OSError as exc:
        raise RuntimeError(
            "manfred_legacy_candidate_audit_receipt_parent_invalid"
        ) from exc
    if (
        not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or stat.S_IMODE(parent_status.st_mode) & 0o022
        or destination.parent != parent
        or os.path.lexists(destination)
    ):
        raise RuntimeError("manfred_legacy_candidate_audit_receipt_path_invalid")

    encoded = _receipt_bytes(payload)
    descriptor = -1
    temporary = ""
    published = False
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=parent,
        )
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise RuntimeError(
                    "manfred_legacy_candidate_audit_receipt_write_failed"
                )
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, destination, follow_symlinks=False)
        published = True
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError as exc:
        raise RuntimeError(
            "manfred_legacy_candidate_audit_receipt_path_invalid"
        ) from exc
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(
            "manfred_legacy_candidate_audit_receipt_write_failed"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        if not published and os.path.lexists(destination):
            # The exclusive link is the commit point.  A failure after that
            # point keeps the complete, fsynced receipt rather than deleting
            # evidence whose publication may already have been observed.
            pass


def _project_rows(
    inventory: tuple[dict[str, object], ...], project: str
) -> tuple[dict[str, object], ...]:
    return tuple(row for row in inventory if row.get("project") == project)


def _live_identity(
    inventory: tuple[dict[str, object], ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                row.get("id"),
                row.get("service"),
                row.get("image_id"),
                row.get("running"),
                row.get("health"),
            )
            for row in _project_rows(inventory, LIVE_COMPOSE_PROJECT)
        )
    )


def _legacy_snapshot(
    inventory: tuple[dict[str, object], ...],
    *,
    expected_image_id: str,
) -> dict[str, object]:
    rows = _project_rows(inventory, LEGACY_PROJECT)
    if not rows:
        return {
            "present": False,
            "services": [],
            "container_ids": [],
            "api_gateway_image_id": "",
            "running_and_healthy": False,
        }
    services = [str(row.get("service") or "") for row in rows]
    if len(rows) != len(EXPECTED_SERVICES) or set(services) != EXPECTED_SERVICES:
        raise RuntimeError("manfred_legacy_candidate_audit_service_inventory_invalid")
    if len(services) != len(set(services)):
        raise RuntimeError("manfred_legacy_candidate_audit_service_inventory_invalid")
    if any(
        HEX_64.fullmatch(str(row.get("id") or "")) is None
        or row.get("running") is not True
        or row.get("health") != "healthy"
        for row in rows
    ):
        raise RuntimeError("manfred_legacy_candidate_audit_health_invalid")
    by_service = {str(row["service"]): row for row in rows}
    if any(
        by_service[service].get("image_id") != expected_image_id
        for service in ("api", "gateway")
    ):
        raise RuntimeError("manfred_legacy_candidate_audit_image_identity_invalid")
    return {
        "present": True,
        "services": sorted(services),
        "container_ids": sorted(str(row["id"]) for row in rows),
        "api_gateway_image_id": expected_image_id,
        "running_and_healthy": True,
    }


def _registry_projection(
    entries: list[dict[str, object]],
    *,
    expected_image_id: str,
) -> dict[str, object]:
    if len(entries) > 128 or any(not isinstance(row, dict) for row in entries):
        raise RuntimeError("manfred_legacy_candidate_audit_registry_invalid")
    legacy_rows = [
        row for row in entries if str(row.get("project") or "") == LEGACY_PROJECT
    ]
    conflicting = sorted(
        {
            str(row.get("project") or "")
            for row in entries
            if str(row.get("project") or "") != LEGACY_PROJECT
            and row.get("image_id") == expected_image_id
        }
    )
    if any(not project for project in conflicting):
        raise RuntimeError("manfred_legacy_candidate_audit_registry_invalid")
    return {
        "legacy_receipt_count": len(legacy_rows),
        "expected_image_referenced_by_managed_projects": conflicting,
        "expected_image_exclusively_legacy": not conflicting,
    }


def _registered_candidate_entries(registry_path: Path) -> list[dict[str, object]]:
    """Read registry protection metadata without reopening historical receipts."""

    loaded = _read_private_json(registry_path, missing_ok=True)
    if loaded is None:
        return []
    entries, _pending = _validated_registry(loaded[0])
    return [dict(entry) for entry in entries]


def _base_report(*, apply: bool, expected_image_id: str) -> dict[str, object]:
    return {
        "schema": RECEIPT_SCHEMA,
        "observed_at": _utc_now(),
        "status": "blocked" if apply else "pass",
        "mode": "apply_requested" if apply else "dry_run",
        "controller_posture": "observation_only",
        "project": LEGACY_PROJECT,
        "expected_image_id": expected_image_id,
        "docker_access": "read_only",
        "destructive_apply_supported": False,
        "automatic_retirement_authorized": False,
        "retirement_authorized": False,
        "mutation_performed": False,
        "mutations_performed": 0,
        "live_compose_project": LIVE_COMPOSE_PROJECT,
        "live_compose_project_protected": True,
        "secrets_included": False,
    }


def _evaluate_locked(
    *,
    expected_image_id: str,
    registry_entries: list[dict[str, object]],
    apply: bool,
    sample_spacing_seconds: float,
    sleep: Callable[[float], None],
    lock_evidence: dict[str, object],
) -> dict[str, object]:
    report = _base_report(apply=apply, expected_image_id=expected_image_id)
    report["lock"] = dict(lock_evidence)
    registry = _registry_projection(
        registry_entries,
        expected_image_id=expected_image_id,
    )
    initial_inventory = _container_inventory()
    initial_live = _live_identity(initial_inventory)
    try:
        initial = _legacy_snapshot(
            initial_inventory,
            expected_image_id=expected_image_id,
        )
    except RuntimeError as exc:
        initial = {
            "present": bool(_project_rows(initial_inventory, LEGACY_PROJECT)),
            "qualified": False,
            "error": _safe_error(exc),
        }
    sleep(sample_spacing_seconds)
    final_inventory = _container_inventory()
    final_live = _live_identity(final_inventory)
    if final_live != initial_live:
        raise RuntimeError("manfred_legacy_candidate_audit_live_identity_changed")
    try:
        final = _legacy_snapshot(
            final_inventory,
            expected_image_id=expected_image_id,
        )
    except RuntimeError as exc:
        final = {
            "present": bool(_project_rows(final_inventory, LEGACY_PROJECT)),
            "qualified": False,
            "error": _safe_error(exc),
        }

    stable = initial == final and "error" not in initial
    present = bool(final.get("present"))
    if not stable:
        candidate_state = "quarantined_identity_unstable"
    elif present:
        candidate_state = "observed_identity_stable"
    else:
        candidate_state = "absent"
    report.update(
        {
            "candidate_state": candidate_state,
            "candidate_present": present,
            "candidate_identity_stable": stable,
            "sample_count": 2,
            "sample_spacing_seconds": sample_spacing_seconds,
            "legacy_candidate": final,
            "registry": registry,
            "live_identity_unchanged": True,
            "retirement_observation_complete": stable,
        }
    )
    if apply:
        report["apply_block_reason"] = (
            "manfred_legacy_candidate_audit_destructive_apply_unavailable"
        )
    return report


def audit_legacy_candidate(
    *,
    project: str,
    expected_image_id: str,
    registry_path: Path | None = None,
    lock_path: Path | None = None,
    output_receipt: Path | None = None,
    apply: bool = False,
    skip_if_busy: bool = False,
    sample_spacing_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if project != LEGACY_PROJECT:
        raise RuntimeError("manfred_legacy_candidate_audit_project_invalid")
    if IMAGE_ID.fullmatch(expected_image_id) is None:
        raise RuntimeError("manfred_legacy_candidate_audit_image_id_invalid")
    if (
        type(sample_spacing_seconds) not in {int, float}
        or not 1 <= float(sample_spacing_seconds) <= 300
    ):
        raise RuntimeError("manfred_legacy_candidate_audit_sample_spacing_invalid")
    registry = Path(registry_path or default_registry_path())
    fleet_lock = Path(lock_path or FLEET_LOCK_PATH)
    with hold_candidate_fleet_lock(
        skip_if_busy=skip_if_busy,
        lock_path=fleet_lock,
    ) as lock_evidence:
        if lock_evidence is None:
            report = _base_report(
                apply=apply,
                expected_image_id=expected_image_id,
            )
            report.update(
                {
                    "status": "skipped",
                    "skip_reason": "manfred_candidate_fleet_lock_held",
                    "candidate_state": "not_observed",
                    "candidate_present": False,
                    "candidate_identity_stable": False,
                    "sample_count": 0,
                    "mutation_performed": False,
                }
            )
        else:
            entries = _registered_candidate_entries(registry)
            report = _evaluate_locked(
                expected_image_id=expected_image_id,
                registry_entries=entries,
                apply=apply,
                sample_spacing_seconds=float(sample_spacing_seconds),
                sleep=sleep,
                lock_evidence=dict(lock_evidence),
            )
    if output_receipt is not None:
        _atomic_receipt(Path(output_receipt), report)
    return report


# Preserve the old callable name for callers while changing its authority to a
# read-only audit.  Legacy destructive-only keyword arguments are intentionally
# not accepted.
retire_legacy_candidate = audit_legacy_candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the exact unbound ea-manfred-candidate legacy stack. "
            "Docker mutation is unavailable."
        )
    )
    parser.add_argument(
        "--project",
        required=True,
        choices=[LEGACY_PROJECT],
    )
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("--lock-path", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--sample-spacing-seconds",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Request apply; the audit reports blocked and performs no mutation.",
    )
    parser.add_argument("--skip-if-busy", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_legacy_candidate(
            project=args.project,
            expected_image_id=args.expected_image_id,
            registry_path=args.registry,
            lock_path=args.lock_path,
            output_receipt=args.receipt,
            apply=bool(args.apply),
            skip_if_busy=bool(args.skip_if_busy),
            sample_spacing_seconds=args.sample_spacing_seconds,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "error",
                    "error": _safe_error(exc),
                    "mutation_performed": False,
                    "secrets_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
