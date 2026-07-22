from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.services.public_tour_artifacts import (
    PUBLIC_TOUR_DIRECTORY_MODE,
    PUBLIC_TOUR_FILE_MODE,
    copy_public_tour_file,
    ensure_public_tour_directory,
    normalize_public_tour_bundle_modes,
    write_public_tour_bytes,
    write_public_tour_file,
    write_public_tour_json,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_public_tour_writes_override_private_umask_and_are_atomic(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    previous_umask = os.umask(0o077)
    try:
        manifest = root / "sample" / "tour.json"
        asset = root / "sample" / "panorama" / "front.jpg"
        write_public_tour_json(manifest, {"slug": "sample", "label": "Grüß Gott"}, root=root)
        write_public_tour_bytes(asset, b"image-bytes", root=root)
    finally:
        os.umask(previous_umask)

    assert json.loads(manifest.read_text(encoding="utf-8")) == {"slug": "sample", "label": "Grüß Gott"}
    assert asset.read_bytes() == b"image-bytes"
    assert _mode(root) == PUBLIC_TOUR_DIRECTORY_MODE
    assert _mode(root / "sample") == PUBLIC_TOUR_DIRECTORY_MODE
    assert _mode(root / "sample" / "panorama") == PUBLIC_TOUR_DIRECTORY_MODE
    assert _mode(manifest) == PUBLIC_TOUR_FILE_MODE
    assert _mode(asset) == PUBLIC_TOUR_FILE_MODE
    assert not tuple(manifest.parent.glob(f".{manifest.name}.*.tmp"))


def test_public_tour_write_replaces_private_regular_file_with_public_mode(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    target = root / "sample" / "tour.json"
    target.parent.mkdir(parents=True)
    target.write_text("private", encoding="utf-8")
    target.chmod(0o600)

    write_public_tour_json(target, {"slug": "sample"}, root=root)

    assert json.loads(target.read_text(encoding="utf-8")) == {"slug": "sample"}
    assert _mode(target) == PUBLIC_TOUR_FILE_MODE


def test_public_tour_copy_does_not_preserve_private_source_mode(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    source = tmp_path / "private-render.mp4"
    source.write_bytes(b"video")
    source.chmod(0o600)

    target = copy_public_tour_file(source, root / "sample" / "tour.mp4", root=root)

    assert target.read_bytes() == b"video"
    assert _mode(target) == PUBLIC_TOUR_FILE_MODE


def test_public_tour_operations_reject_escape_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    ensure_public_tour_directory(root / "sample", root=root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    linked_file = root / "sample" / "tour.json"
    outside_file = tmp_path / "outside.json"
    outside_file.write_text("outside", encoding="utf-8")
    linked_file.symlink_to(outside_file)

    with pytest.raises(RuntimeError, match="outside_root"):
        write_public_tour_bytes(tmp_path / "escape.json", b"no", root=root)
    with pytest.raises(RuntimeError, match="outside_root"):
        write_public_tour_bytes(root / "sample" / ".." / ".." / "escape.json", b"no", root=root)
    with pytest.raises(RuntimeError, match="directory_invalid"):
        write_public_tour_bytes(root / "linked" / "asset.jpg", b"no", root=root)
    with pytest.raises(RuntimeError, match="file_invalid"):
        write_public_tour_json(linked_file, {"slug": "sample"}, root=root)
    assert outside_file.read_text(encoding="utf-8") == "outside"


def test_public_tour_writer_failure_preserves_existing_file_and_cleans_temporary_file(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    target = root / "sample" / "tour.json"
    write_public_tour_bytes(target, b"original", root=root)

    def _fail(handle: object) -> None:
        handle.write(b"partial")  # type: ignore[attr-defined]
        raise RuntimeError("render_failed")

    with pytest.raises(RuntimeError, match="render_failed"):
        write_public_tour_file(target, _fail, root=root)

    assert target.read_bytes() == b"original"
    assert _mode(target) == PUBLIC_TOUR_FILE_MODE
    assert not tuple(target.parent.glob(f".{target.name}.*.tmp"))


def test_bundle_mode_normalization_is_recursive_and_rejects_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "public-tours"
    bundle = root / "sample"
    nested = bundle / "panorama"
    nested.mkdir(parents=True)
    asset = nested / "front.jpg"
    asset.write_bytes(b"image")
    bundle.chmod(0o700)
    nested.chmod(0o700)
    asset.chmod(0o600)

    normalize_public_tour_bundle_modes(bundle, root=root)

    assert _mode(bundle) == PUBLIC_TOUR_DIRECTORY_MODE
    assert _mode(nested) == PUBLIC_TOUR_DIRECTORY_MODE
    assert _mode(asset) == PUBLIC_TOUR_FILE_MODE

    (bundle / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink_forbidden"):
        normalize_public_tour_bundle_modes(bundle, root=root)
