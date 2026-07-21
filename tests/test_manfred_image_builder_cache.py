from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from scripts import build_manfred_memorial_image as builder


IMAGE_ID = f"sha256:{'e' * 64}"


def _completed(
    argv: list[str],
    *,
    stdout: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")


def _builder_listing(*, driver: str = builder.BUILDX_BUILDER_DRIVER) -> bytes:
    return (
        f"default\tdocker\n"
        f"default\tdefault\n"
        f"{builder.BUILDX_BUILDER_NAME}\t{driver}\n"
        f"{builder.BUILDX_BUILDER_NAME}0\tunix:///var/run/docker.sock\n"
    ).encode("utf-8")


def _builder_inspection(
    *,
    driver: str = builder.BUILDX_BUILDER_DRIVER,
    node_name: str = builder.BUILDX_BUILDER_NODE_NAME,
    endpoint: str = builder.BUILDX_BUILDER_ENDPOINT,
) -> bytes:
    return (
        f"Name:          {builder.BUILDX_BUILDER_NAME}\n"
        f"Driver:        {driver}\n"
        "Last Activity: 2026-07-13 12:00:00 +0000 UTC\n"
        "\n"
        "Nodes:\n"
        f"Name:           {node_name}\n"
        f"Endpoint:       {endpoint}\n"
        "Status:         stopped\n"
    ).encode("utf-8")


@contextmanager
def _acquired_lock() -> Iterator[None]:
    yield


def test_candidate_build_uses_exact_scoped_buildx_and_prune_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "b" * 40
    image_tag = f"ea-runtime:manfred-{commit}"
    commands: list[list[str]] = []
    image_list_calls = 0

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(
        builder,
        "_require_root_disk_capacity",
        lambda: None,
    )

    def materialize_context(
        *, source_root: Path, commit: str, destination: Path
    ) -> None:
        del source_root, commit
        dockerfile = destination / "ea" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    def record_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal image_list_calls
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "buildx", "ls"]:
            return _completed(command, stdout=_builder_listing())
        if command[:3] == ["docker", "buildx", "inspect"]:
            return _completed(command, stdout=_builder_inspection())
        if command[:3] == ["docker", "image", "ls"]:
            image_list_calls += 1
            image_id = b"" if image_list_calls == 1 else f"{IMAGE_ID}\n".encode()
            return _completed(command, stdout=image_id)
        return _completed(command)

    monkeypatch.setattr(builder, "_materialize_tracked_context", materialize_context)
    monkeypatch.setattr(builder, "_run", record_run)
    monkeypatch.setattr(
        builder,
        "_image_inspection",
        lambda _tag, *, expected_commit: (
            IMAGE_ID,
            {"RootFS": {"Layers": ["sha256:layer"]}},
        ),
    )
    monkeypatch.setattr(builder, "_verify_image_filesystem", lambda _tag: None)

    receipt_path = tmp_path / "receipt.json"
    receipt = builder.build_image(
        source_root=source_root,
        ref="HEAD",
        tag=image_tag,
        receipt_path=receipt_path,
    )

    build_command = next(
        command
        for command in commands
        if command[:3] == ["docker", "buildx", "build"]
    )
    context = Path(build_command[-1])
    assert build_command == [
        "docker",
        "buildx",
        "build",
        "--builder",
        builder.BUILDX_BUILDER_NAME,
        "--load",
        "--file",
        str(context / "ea" / "Dockerfile"),
        "--tag",
        image_tag,
        "--build-arg",
        f"EA_SOURCE_REVISION={commit}",
        "--label",
        f"org.opencontainers.image.revision={commit}",
        "--label",
        f"org.opencontainers.image.created={receipt['created_at']}",
        "--label",
        "org.opencontainers.image.title=EA Manfred Memorial candidate",
        "--label",
        "org.opencontainers.image.source=git:EA",
        str(context),
    ]
    prune_command = next(
        command
        for command in commands
        if command[:3] == ["docker", "buildx", "prune"]
    )
    assert prune_command == [
        "docker",
        "buildx",
        "prune",
        "--builder",
        builder.BUILDX_BUILDER_NAME,
        "-f",
        "--max-used-space",
        builder.BUILDX_CACHE_MAX_USED_SPACE,
        "--reserved-space",
        builder.BUILDX_CACHE_RESERVED_SPACE,
        "--min-free-space",
        builder.BUILDX_CACHE_MIN_FREE_SPACE,
    ]
    assert commands.index(build_command) < commands.index(prune_command)
    assert all("--use" not in command for command in commands)
    assert all(command[:3] != ["docker", "system", "prune"] for command in commands)
    assert all(command[:3] != ["docker", "builder", "prune"] for command in commands)
    assert all(command[:3] != ["docker", "image", "prune"] for command in commands)
    assert all(command[:3] != ["docker", "image", "rm"] for command in commands)

    assert receipt["schema"] == "ea.manfred_memorial_image_build.v2"
    assert receipt["buildx_builder_name"] == builder.BUILDX_BUILDER_NAME
    assert receipt["buildx_builder_driver"] == builder.BUILDX_BUILDER_DRIVER
    assert receipt["buildx_builder_created"] is False
    assert receipt["build_cache_scope"] == "dedicated_builder_only"
    assert receipt["build_cache_prune"] == {
        "status": "pass",
        "builder": builder.BUILDX_BUILDER_NAME,
        "max_used_space": builder.BUILDX_CACHE_MAX_USED_SPACE,
        "reserved_space": builder.BUILDX_CACHE_RESERVED_SPACE,
        "min_free_space": builder.BUILDX_CACHE_MIN_FREE_SPACE,
    }
    assert receipt["global_build_cache_pruned"] is False
    assert receipt["live_or_rollback_images_pruned"] is False
    assert receipt_path.is_file()


def test_missing_builder_is_created_exactly_without_changing_current_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    list_calls = 0

    def record_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal list_calls
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "buildx", "ls"]:
            list_calls += 1
            listing = b"default\tdocker\ndefault\tdefault\n"
            if list_calls == 2:
                listing = _builder_listing()
            return _completed(command, stdout=listing)
        if command[:3] == ["docker", "buildx", "create"]:
            return _completed(
                command,
                stdout=f"{builder.BUILDX_BUILDER_NAME}\n".encode("utf-8"),
            )
        if command[:3] == ["docker", "buildx", "inspect"]:
            return _completed(command, stdout=_builder_inspection())
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(builder, "_run", record_run)

    assert builder._ensure_dedicated_builder() is True
    assert commands[1] == [
        "docker",
        "buildx",
        "create",
        "--name",
        builder.BUILDX_BUILDER_NAME,
        "--node",
        builder.BUILDX_BUILDER_NODE_NAME,
        "--driver",
        builder.BUILDX_BUILDER_DRIVER,
        builder.BUILDX_BUILDER_ENDPOINT,
    ]
    assert all("--use" not in command for command in commands)


def test_existing_builder_driver_mismatch_fails_closed_without_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def record_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        return _completed(command, stdout=_builder_listing(driver="docker"))

    monkeypatch.setattr(builder, "_run", record_run)

    with pytest.raises(RuntimeError, match=builder.BUILDX_BUILDER_MISMATCH_ERROR):
        builder._ensure_dedicated_builder()

    assert len(commands) == 1
    assert commands[0][:3] == ["docker", "buildx", "ls"]


@pytest.mark.parametrize(
    ("node_name", "endpoint"),
    [
        ("wrong-node", builder.BUILDX_BUILDER_ENDPOINT),
        (builder.BUILDX_BUILDER_NODE_NAME, "ssh://remote.example"),
    ],
)
def test_existing_builder_topology_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    node_name: str,
    endpoint: str,
) -> None:
    commands: list[list[str]] = []

    def record_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "buildx", "ls"]:
            return _completed(command, stdout=_builder_listing())
        if command[:3] == ["docker", "buildx", "inspect"]:
            return _completed(
                command,
                stdout=_builder_inspection(node_name=node_name, endpoint=endpoint),
            )
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(builder, "_run", record_run)

    with pytest.raises(RuntimeError, match=builder.BUILDX_BUILDER_MISMATCH_ERROR):
        builder._ensure_dedicated_builder()

    assert [command[:3] for command in commands] == [
        ["docker", "buildx", "ls"],
        ["docker", "buildx", "inspect"],
    ]


def test_builder_create_failure_propagates_without_build_or_prune(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fail_create(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "buildx", "ls"]:
            return _completed(command, stdout=b"default\tdocker\ndefault\tdefault\n")
        if command[:3] == ["docker", "buildx", "create"]:
            raise subprocess.CalledProcessError(1, command, stderr=b"builder busy")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(builder, "_run", fail_create)

    with pytest.raises(subprocess.CalledProcessError):
        builder._ensure_dedicated_builder()

    assert [command[:3] for command in commands] == [
        ["docker", "buildx", "ls"],
        ["docker", "buildx", "create"],
    ]


def test_build_lock_busy_stops_before_builder_or_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @contextmanager
    def busy_lock() -> Iterator[None]:
        raise RuntimeError(builder.BUILD_BUSY_ERROR)
        yield  # pragma: no cover

    build_entered = False

    def forbidden_build(**_kwargs: object) -> dict[str, object]:
        nonlocal build_entered
        build_entered = True
        return {}

    monkeypatch.setattr(builder, "_exclusive_build_lock", busy_lock)
    monkeypatch.setattr(builder, "_build_image_locked", forbidden_build)

    with pytest.raises(RuntimeError, match=builder.BUILD_BUSY_ERROR):
        builder.build_image(
            source_root=tmp_path,
            ref="HEAD",
            tag="",
            receipt_path=tmp_path / "receipt.json",
        )

    assert build_entered is False


def test_valid_preexisting_full_revision_image_is_reused_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "a" * 40
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(
        builder,
        "_require_root_disk_capacity",
        lambda: pytest.fail("zero-build reuse reached the disk build gate"),
    )

    def image_only_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "image", "ls"]:
            return _completed(command, stdout=f"{IMAGE_ID}\n".encode("utf-8"))
        raise AssertionError(f"preexisting image must skip builder and build: {command!r}")

    monkeypatch.setattr(builder, "_run", image_only_run)
    monkeypatch.setattr(
        builder,
        "_image_inspection",
        lambda _tag, *, expected_commit: (
            IMAGE_ID,
            {"RootFS": {"Layers": ["sha256:layer"]}},
        ),
    )
    monkeypatch.setattr(builder, "_verify_image_filesystem", lambda _tag: None)

    receipt = builder.build_image(
        source_root=source_root,
        ref="HEAD",
        tag=f"ea-runtime:manfred-{commit}",
        receipt_path=tmp_path / "receipt.json",
    )

    assert receipt["image_reused"] is True
    assert receipt["preexisting_image_preserved"] is True
    assert receipt["buildx_load_completed"] is False
    assert receipt["buildx_builder_validated"] is False
    assert receipt["build_cache_prune"]["status"] == "not_run_existing_image_reused"
    assert [command[:3] for command in commands] == [
        ["docker", "image", "ls"],
        ["docker", "image", "ls"],
    ]


def test_mismatched_preexisting_tag_fails_without_overwrite_or_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "f" * 40
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(builder, "_require_root_disk_capacity", lambda: None)

    def image_only_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "image", "ls"]:
            return _completed(command, stdout=f"{IMAGE_ID}\n".encode("utf-8"))
        raise AssertionError(f"mismatched image must remain untouched: {command!r}")

    monkeypatch.setattr(builder, "_run", image_only_run)
    monkeypatch.setattr(
        builder,
        "_image_inspection",
        lambda _tag, *, expected_commit: (_ for _ in ()).throw(
            RuntimeError("manfred_image_revision_label_mismatch")
        ),
    )

    with pytest.raises(RuntimeError, match=builder.EXISTING_IMAGE_MISMATCH_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=f"ea-runtime:manfred-{commit}",
            receipt_path=tmp_path / "receipt.json",
        )

    assert [command[:3] for command in commands] == [["docker", "image", "ls"]]


def test_failed_buildx_build_prunes_scoped_cache_and_writes_failure_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "c" * 40
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(builder, "_require_root_disk_capacity", lambda: None)

    def materialize_context(
        *, source_root: Path, commit: str, destination: Path
    ) -> None:
        del source_root, commit
        dockerfile = destination / "ea" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    def fail_build(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "image", "ls"]:
            return _completed(command)
        if command[:3] == ["docker", "buildx", "ls"]:
            return _completed(command, stdout=_builder_listing())
        if command[:3] == ["docker", "buildx", "inspect"]:
            return _completed(command, stdout=_builder_inspection())
        if command[:3] == ["docker", "buildx", "build"]:
            raise subprocess.CalledProcessError(1, command, stderr=b"builder busy")
        if command[:3] == ["docker", "buildx", "prune"]:
            return _completed(command)
        raise AssertionError(f"unexpected command after failed build: {command!r}")

    monkeypatch.setattr(builder, "_materialize_tracked_context", materialize_context)
    monkeypatch.setattr(builder, "_run", fail_build)
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(RuntimeError, match=builder.BUILDX_BUILD_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=f"ea-runtime:manfred-{commit}",
            receipt_path=receipt_path,
        )

    assert any(command[:3] == ["docker", "buildx", "build"] for command in commands)
    assert any(command[:3] == ["docker", "buildx", "prune"] for command in commands)
    failure_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert failure_receipt["status"] == "fail"
    assert failure_receipt["error"] == builder.BUILDX_BUILD_ERROR
    assert failure_receipt["build_cache_prune"]["status"] == "pass"
    assert failure_receipt["new_image_cleanup_status"] == "already_absent"


def test_post_build_verification_failure_prunes_cache_and_removes_only_new_tag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "9" * 40
    image_tag = f"ea-runtime:manfred-{commit}"
    commands: list[list[str]] = []
    image_present = False

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(builder, "_require_root_disk_capacity", lambda: None)

    def materialize_context(
        *, source_root: Path, commit: str, destination: Path
    ) -> None:
        del source_root, commit
        dockerfile = destination / "ea" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    def record_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal image_present
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "image", "ls"]:
            rendered = f"{IMAGE_ID}\n".encode("utf-8") if image_present else b""
            return _completed(command, stdout=rendered)
        if command[:3] == ["docker", "buildx", "ls"]:
            return _completed(command, stdout=_builder_listing())
        if command[:3] == ["docker", "buildx", "inspect"]:
            return _completed(command, stdout=_builder_inspection())
        if command[:3] == ["docker", "buildx", "build"]:
            image_present = True
            return _completed(command)
        if command[:3] == ["docker", "buildx", "prune"]:
            return _completed(command)
        if command[:3] == ["docker", "image", "rm"]:
            assert command == ["docker", "image", "rm", image_tag]
            image_present = False
            return _completed(command, stdout=f"Untagged: {image_tag}\n".encode("utf-8"))
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(builder, "_materialize_tracked_context", materialize_context)
    monkeypatch.setattr(builder, "_run", record_run)
    monkeypatch.setattr(
        builder,
        "_image_inspection",
        lambda _tag, *, expected_commit: (
            IMAGE_ID,
            {"RootFS": {"Layers": ["sha256:layer"]}},
        ),
    )
    monkeypatch.setattr(
        builder,
        "_verify_image_filesystem",
        lambda _tag: (_ for _ in ()).throw(RuntimeError("filesystem mismatch")),
    )
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(RuntimeError, match=builder.POST_BUILD_VERIFY_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=image_tag,
            receipt_path=receipt_path,
        )

    prune_command = next(
        command
        for command in commands
        if command[:3] == ["docker", "buildx", "prune"]
    )
    remove_command = next(
        command
        for command in commands
        if command[:3] == ["docker", "image", "rm"]
    )
    assert commands.index(prune_command) < commands.index(remove_command)
    assert "--force" not in remove_command
    assert "-f" not in remove_command
    assert image_present is False

    failure_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert failure_receipt["schema"] == "ea.manfred_memorial_image_build.v2"
    assert failure_receipt["status"] == "fail"
    assert failure_receipt["error"] == builder.POST_BUILD_VERIFY_ERROR
    assert failure_receipt["new_image_cleanup_status"] == "removed"
    assert failure_receipt["build_cache_prune"]["status"] == "pass"
    assert failure_receipt["preexisting_image"] is False


def test_candidate_tag_is_full_revision_and_rejects_short_collision_locator() -> None:
    commit = "d" * 40
    exact = f"ea-runtime:manfred-{commit}"

    assert builder._safe_tag("", commit=commit) == exact
    assert builder._safe_tag(exact, commit=commit) == exact
    with pytest.raises(ValueError, match="manfred_image_tag_revision_mismatch"):
        builder._safe_tag(f"ea-runtime:manfred-{commit[:12]}", commit=commit)
    with pytest.raises(ValueError, match="manfred_image_mutable_tag_forbidden"):
        builder._safe_tag("ea-runtime:latest", commit=commit)
