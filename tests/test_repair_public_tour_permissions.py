from __future__ import annotations

import os
import stat
from pathlib import Path

from scripts.repair_public_tour_permissions import repair_public_tour_permissions


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_repair_is_scoped_and_requires_explicit_apply(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    selected = root / "selected"
    selected_asset = selected / "generated" / "viewer.html"
    unselected = root / "unselected"
    unselected_manifest = unselected / "tour.json"
    selected_asset.parent.mkdir(parents=True)
    unselected.mkdir(parents=True)
    selected_asset.write_text("viewer", encoding="utf-8")
    unselected_manifest.write_text("{}", encoding="utf-8")
    selected.chmod(0o700)
    selected_asset.parent.chmod(0o700)
    selected_asset.chmod(0o600)
    unselected.chmod(0o700)
    unselected_manifest.chmod(0o600)

    audit = repair_public_tour_permissions(root=root, slugs=["selected"], apply=False)

    assert audit["status"] == "needs_repair"
    assert audit["changed_path_count"] == 0
    assert _mode(selected) == 0o700
    assert _mode(selected_asset) == 0o600

    repaired = repair_public_tour_permissions(root=root, slugs=["selected"], apply=True)

    assert repaired["status"] == "ready"
    assert repaired["reason"] == "permission_modes_repaired"
    assert repaired["changed_path_count"] == 3
    assert _mode(selected) == 0o755
    assert _mode(selected_asset.parent) == 0o755
    assert _mode(selected_asset) == 0o644
    assert _mode(unselected) == 0o700
    assert _mode(unselected_manifest) == 0o600


def test_repair_fails_closed_before_any_change_when_bundle_contains_symlink(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    bundle = root / "selected"
    bundle.mkdir(parents=True)
    manifest = bundle / "tour.json"
    manifest.write_text("{}", encoding="utf-8")
    manifest.chmod(0o600)
    (bundle / "escape").symlink_to(tmp_path, target_is_directory=True)

    result = repair_public_tour_permissions(root=root, slugs=["selected"], apply=True)

    assert result["status"] == "blocked"
    assert result["reason"] == "unsafe_or_missing_bundle_entry"
    assert result["changed_path_count"] == 0
    assert result["unsafe_entry_count"] == 1
    assert _mode(manifest) == 0o600


def test_repair_rejects_missing_and_traversal_bundle_names(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    root.mkdir()

    missing = repair_public_tour_permissions(root=root, slugs=["missing"], apply=True)
    assert missing["status"] == "blocked"
    assert missing["changed_path_count"] == 0

    try:
        repair_public_tour_permissions(root=root, slugs=["../escape"], apply=True)
    except ValueError as exc:
        assert str(exc).startswith("invalid_bundle_slug")
    else:
        raise AssertionError("traversal slug was accepted")
