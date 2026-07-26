from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import memorial_bind_source_guard as guard


def _rendered(
    source: Path,
    *,
    user: str = guard.EXPECTED_USER,
    group_add: list[str] | None = None,
    read_only: bool = True,
    target: str = "/app/app",
) -> dict[str, object]:
    return {
        "services": {
            "ea-api": {
                "user": user,
                "group_add": group_add if group_add is not None else [str(os.getgid())],
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(source),
                        "target": target,
                        "read_only": read_only,
                    }
                ],
            }
        }
    }


def _release_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    release = tmp_path / "release"
    source = release / "ea" / "app"
    source.mkdir(parents=True)
    runner = source / "runner.py"
    runner.write_text("from __future__ import annotations\n", encoding="utf-8")
    runner.chmod(0o440)
    source.chmod(0o550)
    source.parent.chmod(0o550)
    release.chmod(0o550)
    return release, source, runner


def _cartesia_credential(tmp_path: Path) -> tuple[Path, Path]:
    release, _source, _runner = _release_tree(tmp_path)
    credential_root = tmp_path / "runtime" / "provider-secrets"
    credential_root.mkdir(parents=True)
    credential = credential_root / "ea_memorial_cartesia.json"
    credential.write_text('{"api_key":"test-only"}\n', encoding="utf-8")
    credential.chmod(0o440)
    return release, credential


def test_group_readable_release_tree_passes_and_revalidates_exact_snapshot(
    tmp_path: Path,
) -> None:
    release, source, _runner = _release_tree(tmp_path)
    first = guard.validate_memorial_bind_sources(
        _rendered(source),
        service="ea-api",
        release_root=release,
    )

    assert first["status"] == "pass"
    assert first["user"] == "10001:10001"
    assert first["bind_mount_count"] == 1
    assert first["release_tree_mount_count"] == 1
    assert first["release_files_scanned"] == 1
    assert first["file_contents_read"] is False
    assert first["secrets_included"] is False
    assert "source" not in first["mounts"][0]

    second = guard.validate_memorial_bind_sources(
        _rendered(source),
        service="ea-api",
        release_root=release,
        expected_snapshot_sha256=str(first["snapshot_sha256"]),
    )
    assert second["snapshot_sha256"] == first["snapshot_sha256"]


def test_protected_cartesia_credential_file_passes_without_content_evidence(
    tmp_path: Path,
) -> None:
    release, credential = _cartesia_credential(tmp_path)

    receipt = guard.validate_memorial_bind_sources(
        _rendered(
            credential,
            target=guard.MEMORIAL_CARTESIA_CREDENTIAL_TARGET,
        ),
        service="ea-api",
        release_root=release,
    )

    assert receipt["status"] == "pass"
    assert receipt["bind_mount_count"] == 1
    assert receipt["root_inode_mount_count"] == 1
    assert receipt["file_contents_read"] is False
    assert receipt["secrets_included"] is False
    assert "source" not in receipt["mounts"][0]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("world_readable", "cartesia_credential_source_mode_invalid"),
        ("hard_linked", "cartesia_credential_source_link_count_invalid"),
        ("empty", "cartesia_credential_source_size_invalid"),
        ("writable", "cartesia_credential_source_must_be_read_only"),
        ("wrong_owner", "cartesia_credential_source_owner_invalid"),
        ("wrong_group", "cartesia_credential_source_group_invalid"),
        ("acl", "bind_source_posix_acl_unsupported"),
    ],
)
def test_cartesia_credential_file_posture_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason: str,
) -> None:
    release, credential = _cartesia_credential(tmp_path)
    read_only = True
    group_add: list[str] | None = None
    if mutation == "world_readable":
        credential.chmod(0o444)
    elif mutation == "hard_linked":
        os.link(credential, credential.with_name("linked-cartesia.json"))
    elif mutation == "empty":
        credential.chmod(0o600)
        credential.write_bytes(b"")
        credential.chmod(0o440)
    elif mutation == "writable":
        read_only = False
    elif mutation == "wrong_owner":
        current_uid = os.geteuid()
        monkeypatch.setattr(guard.os, "geteuid", lambda: current_uid + 1)
    elif mutation == "wrong_group":
        group_add = []
    elif mutation == "acl":
        monkeypatch.setattr(guard.os, "getxattr", lambda *_args: b"acl")

    with pytest.raises(guard.BindSourceGuardError, match=reason):
        guard.validate_memorial_bind_sources(
            _rendered(
                credential,
                group_add=group_add,
                read_only=read_only,
                target=guard.MEMORIAL_CARTESIA_CREDENTIAL_TARGET,
            ),
            service="ea-api",
            release_root=release,
        )


def test_symlinked_cartesia_credential_file_is_rejected(tmp_path: Path) -> None:
    release, credential = _cartesia_credential(tmp_path)
    linked = credential.with_name("linked-cartesia.json")
    linked.symlink_to(credential)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_symlink_forbidden",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(
                linked,
                target=guard.MEMORIAL_CARTESIA_CREDENTIAL_TARGET,
            ),
            service="ea-api",
            release_root=release,
        )


def test_umask_077_release_directory_is_rejected_for_container_user(
    tmp_path: Path,
) -> None:
    release, source, runner = _release_tree(tmp_path)
    source.chmod(0o700)
    runner.chmod(0o600)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_directory_not_readable_searchable",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source), service="ea-api", release_root=release
        )


def test_umask_077_release_file_is_rejected_even_when_directories_are_searchable(
    tmp_path: Path,
) -> None:
    release, source, runner = _release_tree(tmp_path)
    runner.chmod(0o600)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_file_not_readable",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source), service="ea-api", release_root=release
        )


def test_second_validation_rejects_inode_metadata_change(tmp_path: Path) -> None:
    release, source, runner = _release_tree(tmp_path)
    first = guard.validate_memorial_bind_sources(
        _rendered(source), service="ea-api", release_root=release
    )
    runner.chmod(0o444)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_snapshot_changed",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source),
            service="ea-api",
            release_root=release,
            expected_snapshot_sha256=str(first["snapshot_sha256"]),
        )


def test_symlinked_bind_source_is_rejected(tmp_path: Path) -> None:
    release, source, _runner = _release_tree(tmp_path)
    link = release / "linked-app"
    release.chmod(0o750)
    link.symlink_to(source, target_is_directory=True)
    release.chmod(0o550)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_symlink_forbidden",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(link), service="ea-api", release_root=release
        )


def test_external_directory_is_bounded_to_root_inode(tmp_path: Path) -> None:
    release, _source, _runner = _release_tree(tmp_path)
    external = tmp_path / "external-data"
    external.mkdir(mode=0o770)
    external.chmod(0o770)
    inaccessible_child = external / "large-or-unavailable-subtree"
    inaccessible_child.mkdir(mode=0o000)

    receipt = guard.validate_memorial_bind_sources(
        _rendered(external, read_only=False, target="/data/external"),
        service="ea-api",
        release_root=release,
    )

    assert receipt["root_inode_mount_count"] == 1
    assert receipt["release_entries_scanned"] == 0
    assert receipt["mounts"][0]["scope"] == "root_inode"

    first_snapshot = str(receipt["snapshot_sha256"])
    (external / "concurrent-runtime-entry").write_text("mutable", encoding="utf-8")
    (external / "concurrent-runtime-directory").mkdir()
    repeated = guard.validate_memorial_bind_sources(
        _rendered(external, read_only=False, target="/data/external"),
        service="ea-api",
        release_root=release,
        expected_snapshot_sha256=first_snapshot,
    )
    assert repeated["snapshot_sha256"] == first_snapshot


def test_external_directory_child_creation_during_validation_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, _source, _runner = _release_tree(tmp_path)
    external = tmp_path / "external-data"
    external.mkdir(mode=0o770)
    external.chmod(0o770)
    original_require_access = guard._require_access
    mutated = False

    def require_access(*args: object, **kwargs: object) -> None:
        nonlocal mutated
        original_require_access(*args, **kwargs)
        if not mutated:
            mutated = True
            (external / "arrived-during-validation").mkdir()

    monkeypatch.setattr(guard, "_require_access", require_access)
    receipt = guard.validate_memorial_bind_sources(
        _rendered(external, read_only=False, target="/data/external"),
        service="ea-api",
        release_root=release,
    )

    assert receipt["status"] == "pass"
    assert receipt["mounts"][0]["scope"] == "root_inode"


def test_writable_external_directory_requires_container_write_permission(
    tmp_path: Path,
) -> None:
    release, _source, _runner = _release_tree(tmp_path)
    external = tmp_path / "external-data"
    external.mkdir(mode=0o550)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_directory_not_readable_searchable",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(external, read_only=False, target="/data/external"),
            service="ea-api",
            release_root=release,
        )


@pytest.mark.parametrize("user", ["", "ea", "10001", "0:0", "010001:10001"])
def test_noncanonical_or_non_numeric_runtime_user_is_rejected(
    tmp_path: Path, user: str
) -> None:
    release, source, _runner = _release_tree(tmp_path)

    with pytest.raises(guard.BindSourceGuardError):
        guard.validate_memorial_bind_sources(
            _rendered(source, user=user),
            service="ea-api",
            release_root=release,
        )


def test_release_mount_must_be_read_only(tmp_path: Path) -> None:
    release, source, _runner = _release_tree(tmp_path)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_release_mount_must_be_read_only",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source, read_only=False),
            service="ea-api",
            release_root=release,
        )


@pytest.mark.parametrize("read_only", [None, 0, 1, "false", "true"])
def test_bind_read_only_must_be_a_boolean(
    tmp_path: Path, read_only: object
) -> None:
    release, source, _runner = _release_tree(tmp_path)
    rendered = _rendered(source)
    rendered["services"]["ea-api"]["volumes"][0]["read_only"] = read_only

    with pytest.raises(
        guard.BindSourceGuardError,
        match="memorial_api_bind_read_only_invalid",
    ):
        guard.validate_memorial_bind_sources(
            rendered,
            service="ea-api",
            release_root=release,
        )


def test_compose_omitted_read_only_is_writable_default(tmp_path: Path) -> None:
    release, _source, _runner = _release_tree(tmp_path)
    external = tmp_path / "external-data"
    external.mkdir(mode=0o770)
    external.chmod(0o770)
    rendered = _rendered(external, read_only=False, target="/data/external")
    del rendered["services"]["ea-api"]["volumes"][0]["read_only"]

    receipt = guard.validate_memorial_bind_sources(
        rendered,
        service="ea-api",
        release_root=release,
    )

    assert receipt["status"] == "pass"
    assert receipt["mounts"][0]["read_only"] is False


def test_compose_omitted_read_only_rejects_release_mount(tmp_path: Path) -> None:
    release, source, _runner = _release_tree(tmp_path)
    rendered = _rendered(source)
    del rendered["services"]["ea-api"]["volumes"][0]["read_only"]

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_release_mount_must_be_read_only",
    ):
        guard.validate_memorial_bind_sources(
            rendered,
            service="ea-api",
            release_root=release,
        )


def test_private_external_directory_uses_inode_bound_opath_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, _release_source, _runner = _release_tree(tmp_path)
    source = tmp_path / "private-runtime"
    source.mkdir(mode=0o770)
    source.chmod(0o770)
    real_open = guard.os.open
    fallback_used = False

    def restricted_open(
        path: str | bytes | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal fallback_used
        if path == source.name and flags & os.O_DIRECTORY and not flags & os.O_PATH:
            raise PermissionError(13, "runtime uid owns private directory")
        if path == source.name and flags & os.O_PATH:
            fallback_used = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(guard.os, "open", restricted_open)
    receipt = guard.validate_memorial_bind_sources(
        _rendered(source, read_only=False, target="/data/private-runtime"),
        service="ea-api",
        release_root=release,
    )

    assert fallback_used is True
    assert receipt["status"] == "pass"
    assert receipt["mounts"][0]["scope"] == "root_inode"


@pytest.mark.parametrize(
    "target",
    [
        "/",
        "app/app",
        "/app/../app",
        "/app/./app",
        "/app//app",
        "//app/app",
        "/app/app/",
    ],
)
def test_bind_target_must_be_canonical(tmp_path: Path, target: str) -> None:
    release, source, _runner = _release_tree(tmp_path)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="memorial_api_bind_mount_invalid",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source, target=target),
            service="ea-api",
            release_root=release,
        )


def test_release_scan_budget_is_fail_closed(tmp_path: Path) -> None:
    release, source, _runner = _release_tree(tmp_path)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_scan_budget_exceeded",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source),
            service="ea-api",
            release_root=release,
            maximum_release_entries=1,
        )


def test_release_scan_depth_is_fail_closed(tmp_path: Path) -> None:
    release, source, _runner = _release_tree(tmp_path)
    nested = source / "one" / "two"
    source.chmod(0o750)
    nested.mkdir(parents=True)
    nested.chmod(0o550)
    nested.parent.chmod(0o550)
    source.chmod(0o550)

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_scan_depth_exceeded",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(source),
            service="ea-api",
            release_root=release,
            maximum_release_depth=1,
        )


def test_concurrent_disappearance_is_normalized_without_raw_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, source, _runner = _release_tree(tmp_path)
    monkeypatch.setattr(
        guard.os,
        "scandir",
        lambda _descriptor: (_ for _ in ()).throw(
            FileNotFoundError(2, "disappeared", "sensitive-release-name")
        ),
    )

    with pytest.raises(guard.BindSourceGuardError) as captured:
        guard.validate_memorial_bind_sources(
            _rendered(source),
            service="ea-api",
            release_root=release,
        )

    assert str(captured.value) == "bind_source_filesystem_race"
    assert "sensitive-release-name" not in str(captured.value)


def test_noncanonical_source_path_is_rejected(tmp_path: Path) -> None:
    release, source, _runner = _release_tree(tmp_path)
    noncanonical = source / ".." / "app"

    with pytest.raises(
        guard.BindSourceGuardError,
        match="bind_source_not_absolute",
    ):
        guard.validate_memorial_bind_sources(
            _rendered(noncanonical), service="ea-api", release_root=release
        )
