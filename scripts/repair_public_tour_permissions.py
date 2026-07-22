#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PUBLIC_DIRECTORY_MODE = 0o755
PUBLIC_FILE_MODE = 0o644
CONTRACT = "ea.public-tour-permission-repair.v1"


@dataclass(frozen=True)
class BundleScan:
    slug: str
    directory_count: int
    file_count: int
    mode_violation_count: int
    unsafe_entries: tuple[str, ...]


def _safe_bundle_path(root: Path, slug: str) -> Path:
    normalized = str(slug or "").strip()
    if not normalized or normalized in {".", ".."} or Path(normalized).name != normalized:
        raise ValueError(f"invalid_bundle_slug:{normalized}")
    return root / normalized


def _scan_bundle(root: Path, slug: str) -> tuple[BundleScan, tuple[tuple[Path, int], ...]]:
    bundle = _safe_bundle_path(root, slug)
    if not os.path.lexists(bundle):
        return BundleScan(slug, 0, 0, 0, ("bundle_missing",)), ()
    bundle_stat = os.lstat(bundle)
    if stat.S_ISLNK(bundle_stat.st_mode) or not stat.S_ISDIR(bundle_stat.st_mode):
        return BundleScan(slug, 0, 0, 0, ("bundle_not_regular_directory",)), ()

    planned: list[tuple[Path, int]] = []
    unsafe: list[str] = []
    directory_count = 0
    file_count = 0

    def _visit(directory: Path) -> None:
        nonlocal directory_count, file_count
        directory_count += 1
        directory_stat = os.lstat(directory)
        if stat.S_IMODE(directory_stat.st_mode) != PUBLIC_DIRECTORY_MODE:
            planned.append((directory, PUBLIC_DIRECTORY_MODE))
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative_path = str(path.relative_to(bundle))
                entry_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    unsafe.append(f"symlink:{relative_path}")
                    continue
                if stat.S_ISDIR(entry_stat.st_mode):
                    _visit(path)
                    continue
                if not stat.S_ISREG(entry_stat.st_mode):
                    unsafe.append(f"special:{relative_path}")
                    continue
                file_count += 1
                if stat.S_IMODE(entry_stat.st_mode) != PUBLIC_FILE_MODE:
                    planned.append((path, PUBLIC_FILE_MODE))

    _visit(bundle)
    return (
        BundleScan(
            slug=slug,
            directory_count=directory_count,
            file_count=file_count,
            mode_violation_count=len(planned),
            unsafe_entries=tuple(sorted(unsafe)),
        ),
        tuple(planned),
    )


def repair_public_tour_permissions(*, root: Path, slugs: list[str], apply: bool) -> dict[str, object]:
    root_path = Path(os.path.abspath(root.expanduser()))
    if not os.path.lexists(root_path):
        return {
            "contract": CONTRACT,
            "status": "blocked",
            "reason": "public_tour_root_missing",
            "apply_requested": bool(apply),
            "root": str(root_path),
            "bundles": [],
            "changed_path_count": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    root_stat = os.lstat(root_path)
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        return {
            "contract": CONTRACT,
            "status": "blocked",
            "reason": "public_tour_root_invalid",
            "apply_requested": bool(apply),
            "root": str(root_path),
            "bundles": [],
            "changed_path_count": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    normalized_slugs = list(dict.fromkeys(str(slug or "").strip() for slug in slugs if str(slug or "").strip()))
    if not normalized_slugs:
        raise ValueError("at_least_one_bundle_required")
    scans: list[BundleScan] = []
    plans: list[tuple[Path, int]] = []
    for slug in normalized_slugs:
        scan, bundle_plan = _scan_bundle(root_path, slug)
        scans.append(scan)
        plans.extend(bundle_plan)

    unsafe_count = sum(len(scan.unsafe_entries) for scan in scans)
    if unsafe_count:
        status = "blocked"
        reason = "unsafe_or_missing_bundle_entry"
        changed_path_count = 0
    elif not plans:
        status = "ready"
        reason = "permissions_already_ready"
        changed_path_count = 0
    elif not apply:
        status = "needs_repair"
        reason = "permission_modes_not_public"
        changed_path_count = 0
    else:
        for path, mode in plans:
            os.chmod(path, mode, follow_symlinks=False)
        changed_path_count = len(plans)
        remaining_violations = 0
        for slug in normalized_slugs:
            rescan, _ = _scan_bundle(root_path, slug)
            remaining_violations += rescan.mode_violation_count + len(rescan.unsafe_entries)
        if remaining_violations:
            status = "blocked"
            reason = "permission_repair_incomplete"
        else:
            status = "ready"
            reason = "permission_modes_repaired"

    return {
        "contract": CONTRACT,
        "status": status,
        "reason": reason,
        "apply_requested": bool(apply),
        "root": str(root_path),
        "bundle_count": len(scans),
        "directory_count": sum(scan.directory_count for scan in scans),
        "file_count": sum(scan.file_count for scan in scans),
        "mode_violation_count": sum(scan.mode_violation_count for scan in scans),
        "unsafe_entry_count": unsafe_count,
        "changed_path_count": changed_path_count,
        "bundles": [
            {
                "slug": scan.slug,
                "directory_count": scan.directory_count,
                "file_count": scan.file_count,
                "mode_violation_count": scan.mode_violation_count,
                "unsafe_entries": list(scan.unsafe_entries),
            }
            for scan in scans
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_receipt(path: Path, payload: dict[str, object]) -> None:
    target = path.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit or repair modes for selected public 3D-tour bundles.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(str(os.getenv("EA_PUBLIC_TOUR_DIR") or "/data/public_property_tours")),
    )
    parser.add_argument("--bundle", action="append", default=[], help="Exact public bundle slug; repeat as needed.")
    parser.add_argument("--apply", action="store_true", help="Apply 0755 directory and 0644 file modes.")
    parser.add_argument("--receipt", type=Path, help="Optional JSON receipt path.")
    args = parser.parse_args(argv)
    try:
        payload = repair_public_tour_permissions(root=args.root, slugs=args.bundle, apply=bool(args.apply))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.receipt:
        _write_receipt(args.receipt, payload)
    return 0 if payload.get("status") == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
