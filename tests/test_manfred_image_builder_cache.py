from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from scripts import build_manfred_memorial_image as builder


IMAGE_ID = f"sha256:{'e' * 64}"


def _authority_evidence(*, phase: str, boundary: str) -> dict[str, object]:
    return {
        "status": "pass",
        "phase": phase,
        "boundary": boundary,
        "contract_name": "ea.vexp_manfred_candidate_mutation_permit.v2",
        "version": 2,
        "epoch_started_ms": 1784519901061,
        "qualified_at": "2026-07-27T03:58:21.061Z",
        "terminal_identity_sha256": "1" * 64,
        "qualification_certificate_schema": "ea.vexp_qualification_certificate.v2",
        "qualification_certificate_sha256": "2" * 64,
        "qualification_certificate_identity": f"sha256:{'3' * 64}",
        "qualification_certificate_event_hash": "4" * 64,
        "permit_sha256": "5" * 64,
        "permit_commit": {
            "contract_name": "ea.vexp_mutation_permit_commit.v1",
            "version": 1,
            "status": "committed",
            "sha256": "6" * 64,
        },
        "epoch_void_ledger": {
            "root": "/var/lib/vexp-qualification-epoch-voids",
            "entry": "/var/lib/vexp-qualification-epoch-voids/1784519901061.json",
            "entry_present": False,
            "root_trusted": True,
        },
        "permit_issued_at": "2026-07-27T04:00:00Z",
        "permit_expires_at": "2026-07-27T05:00:00Z",
        "current_predicate": {
            "contract_name": "ea.vexp_current_predicate.v1",
            "version": 1,
            "status": "positive",
            "epoch_started_ms": 1784519901061,
            "generation": 1,
            "record_sha256": "7" * 64,
            "boot_id": "12345678-1234-4234-9234-123456789abc",
            "monotonic_ns": 1_000_000_000,
            "sentinel_producer_sha256": "8" * 64,
            "root_predicate_producer_sha256": "9" * 64,
        },
    }


class _FakeCandidateVexpLease:
    def __init__(self, boundary: str) -> None:
        self.authority_evidence = _authority_evidence(
            phase="pre_mutation",
            boundary=boundary,
        )

    def command_timeout(self, requested_seconds: float) -> float:
        return requested_seconds


class _FakeCandidateVexpAuthority:
    def require_current(self) -> dict[str, object]:
        return _authority_evidence(phase="entry", boundary="candidate_entry")

    @contextmanager
    def mutation(self, boundary: str, *, minimum_validity_seconds: float):
        assert boundary == "before_candidate_image_build"
        assert minimum_validity_seconds > 0
        yield _FakeCandidateVexpLease(boundary)

    @contextmanager
    def finalization(self):
        yield _authority_evidence(
            phase="finalization",
            boundary="candidate_receipt_publication",
        )


@pytest.fixture(autouse=True)
def _candidate_vexp_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        builder,
        "candidate_vexp_authority",
        lambda **_kwargs: _FakeCandidateVexpAuthority(),
    )


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


def _record_fake_verification(
    image_id: str,
    *,
    authority: object,
    operations: list[dict[str, object]],
) -> str:
    name = builder._verification_container_name(image_id)
    for operation in (
        "verification_create",
        "verification_probe",
        "verification_cleanup",
    ):
        with authority.mutation(  # type: ignore[attr-defined]
            "before_candidate_image_build",
            minimum_validity_seconds=120,
        ) as lease:
            record = builder._record_authorized_operation(
                operations,
                operation=operation,
                argv=["fixture-verifier", operation, name],
                target=name,
                evidence=dict(lease.authority_evidence),
            )
            record["runner_acknowledged"] = True
    return name


def _verification_inspection(
    *,
    name: str,
    image_id: str,
    container_id: str,
) -> bytes:
    return json.dumps(
        [
            {
                "Id": container_id,
                "Name": f"/{name}",
                "Image": image_id,
                "Config": {
                    "Labels": {builder.VERIFICATION_CONTAINER_LABEL: image_id}
                },
                "HostConfig": {"NetworkMode": "none"},
            }
        ]
    ).encode("utf-8")


def test_candidate_build_uses_exact_scoped_buildx_and_prune_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "b" * 40
    image_tag = f"ea-runtime:manfred-{commit}"
    commands: list[list[str]] = []
    verified_filesystems: list[str] = []
    image_list_calls = 0

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(
        builder,
        "_root_free_bytes",
        lambda: builder.MINIMUM_ROOT_FREE_BYTES + 1024,
    )
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
    def verify_filesystem(
        image_reference: str,
        *,
        authority: object,
        operations: list[dict[str, object]],
    ) -> str:
        verified_filesystems.append(image_reference)
        return _record_fake_verification(
            image_reference,
            authority=authority,
            operations=operations,
        )

    monkeypatch.setattr(builder, "_verify_image_filesystem_authorized", verify_filesystem)

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

    assert receipt["schema"] == "ea.manfred_memorial_image_build.v3"
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
    assert verified_filesystems == [IMAGE_ID]


def test_durable_fresh_build_receipt_replays_without_mutation_and_rejects_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "repo"
    (source_root / ".git").mkdir(parents=True)
    commit = "7" * 40
    image_tag = f"ea-runtime:manfred-{commit}"
    producer_sha256 = "d" * 64
    receipt_path = tmp_path / "receipt.json"
    mutation_events: list[str] = []
    validation_events: list[str] = []
    root_free_calls = 0
    image_present = False
    current_image_id = IMAGE_ID
    image_created_at = ""

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(builder, "_producer_sha256", lambda: producer_sha256)

    def root_free_bytes() -> int:
        nonlocal root_free_calls
        root_free_calls += 1
        return builder.MINIMUM_ROOT_FREE_BYTES + 1024

    def materialize_context(
        *, source_root: Path, commit: str, destination: Path
    ) -> None:
        del source_root, commit
        mutation_events.append("context")
        dockerfile = destination / "ea" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")

    def ensure_builder(
        authority: object,
        operations: list[dict[str, object]],
    ) -> bool:
        mutation_events.append("builder")
        with authority.mutation(  # type: ignore[attr-defined]
            "before_candidate_image_build",
            minimum_validity_seconds=120,
        ) as lease:
            record = builder._record_authorized_operation(
                operations,
                operation="builder_create",
                argv=["fixture-builder", "create"],
                target=builder.BUILDX_BUILDER_NAME,
                evidence=dict(lease.authority_evidence),
            )
            record["runner_acknowledged"] = True
        return True

    def prune_cache(
        authority: object,
        operations: list[dict[str, object]],
    ) -> None:
        mutation_events.append("prune")
        with authority.mutation(  # type: ignore[attr-defined]
            "before_candidate_image_build",
            minimum_validity_seconds=300,
        ) as lease:
            record = builder._record_authorized_operation(
                operations,
                operation="builder_prune",
                argv=["fixture-builder", "prune"],
                target=builder.BUILDX_BUILDER_NAME,
                evidence=dict(lease.authority_evidence),
            )
            record["runner_acknowledged"] = True

    def run_build(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal image_present, image_created_at
        del cwd, stdout
        command = list(argv)
        if command[:3] != ["docker", "buildx", "build"]:
            raise AssertionError(f"unexpected mutating command: {command!r}")
        mutation_events.append("build")
        created_label = next(
            value
            for value in command
            if value.startswith("org.opencontainers.image.created=")
        )
        image_created_at = created_label.split("=", 1)[1]
        image_present = True
        return _completed(command)

    def listed_image_id(_tag: str) -> str | None:
        return current_image_id if image_present else None

    def inspect_image(
        _tag: str,
        *,
        expected_commit: str,
    ) -> tuple[str, dict[str, object]]:
        validation_events.append("inspect")
        assert expected_commit == commit
        return current_image_id, {
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": commit,
                    "org.opencontainers.image.created": image_created_at,
                },
                "Env": [f"EA_SOURCE_REVISION={commit}", "PATH=/usr/bin"],
            },
            "RootFS": {"Layers": ["sha256:layer-a", "sha256:layer-b"]},
        }

    def verify_filesystem(
        image_reference: str,
        *,
        authority: object,
        operations: list[dict[str, object]],
    ) -> str:
        validation_events.append(f"filesystem:{image_reference}")
        return _record_fake_verification(
            image_reference,
            authority=authority,
            operations=operations,
        )

    monkeypatch.setattr(builder, "_root_free_bytes", root_free_bytes)
    monkeypatch.setattr(builder, "_materialize_tracked_context", materialize_context)
    monkeypatch.setattr(builder, "_ensure_dedicated_builder", ensure_builder)
    monkeypatch.setattr(builder, "_prune_dedicated_builder_cache", prune_cache)
    monkeypatch.setattr(builder, "_run", run_build)
    monkeypatch.setattr(builder, "_listed_image_id", listed_image_id)
    monkeypatch.setattr(builder, "_image_inspection", inspect_image)
    monkeypatch.setattr(
        builder,
        "_verify_image_filesystem_authorized",
        verify_filesystem,
    )

    first = builder.build_image(
        source_root=source_root,
        ref="HEAD",
        tag=image_tag,
        receipt_path=receipt_path,
    )

    assert first["image_reused"] is False
    assert first["buildx_load_completed"] is True
    assert mutation_events == ["context", "builder", "build", "prune"]
    assert root_free_calls == 3
    assert validation_events == ["inspect", f"filesystem:{IMAGE_ID}"]
    original_bytes = receipt_path.read_bytes()
    original_inode = receipt_path.stat().st_ino
    assert original_bytes == builder._build_receipt_bytes(first)

    monkeypatch.setattr(
        builder,
        "_atomic_json",
        lambda *_args, **_kwargs: pytest.fail("replay must not publish a new receipt"),
    )
    mutation_events.clear()
    validation_events.clear()
    root_free_calls = 0
    replayed = builder.build_image(
        source_root=source_root,
        ref="HEAD",
        tag=image_tag,
        receipt_path=receipt_path,
    )

    assert replayed == first
    assert mutation_events == []
    assert validation_events == ["inspect"]
    assert root_free_calls == 0
    assert receipt_path.read_bytes() == original_bytes
    assert receipt_path.stat().st_ino == original_inode

    recovery_temporary = tmp_path / (
        f".{builder.RECEIPT_TEMP_BASENAME}.1234."
        "abcdef012345abcdef012345.tmp"
    )
    recovery_temporary.hardlink_to(receipt_path)
    assert receipt_path.stat().st_nlink == 2
    mutation_events.clear()
    validation_events.clear()
    root_free_calls = 0

    recovered = builder.build_image(
        source_root=source_root,
        ref="HEAD",
        tag=image_tag,
        receipt_path=receipt_path,
    )

    assert recovered == first
    assert not recovery_temporary.exists()
    assert receipt_path.read_bytes() == original_bytes
    assert receipt_path.stat().st_ino == original_inode
    assert receipt_path.stat().st_nlink == 1
    assert mutation_events == []
    assert validation_events == ["inspect"]
    assert root_free_calls == 0

    unrelated = tmp_path / "operator-backup.json"
    unrelated.hardlink_to(receipt_path)
    mutation_events.clear()
    validation_events.clear()
    root_free_calls = 0
    with pytest.raises(RuntimeError, match=builder.RECEIPT_PATH_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=image_tag,
            receipt_path=receipt_path,
        )
    assert unrelated.exists()
    assert receipt_path.stat().st_nlink == 2
    assert mutation_events == []
    assert validation_events == []
    assert root_free_calls == 0
    unrelated.unlink()

    second_temporary = tmp_path / (
        f".{builder.RECEIPT_TEMP_BASENAME}.5678."
        "012345abcdef012345abcdef.tmp"
    )
    recovery_temporary.hardlink_to(receipt_path)
    second_temporary.write_bytes(b"unrelated staged bytes\n")
    second_temporary.chmod(0o600)
    mutation_events.clear()
    validation_events.clear()
    root_free_calls = 0
    with pytest.raises(RuntimeError, match=builder.RECEIPT_PATH_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=image_tag,
            receipt_path=receipt_path,
        )
    assert recovery_temporary.exists()
    assert second_temporary.exists()
    assert receipt_path.stat().st_nlink == 2
    assert mutation_events == []
    assert validation_events == []
    assert root_free_calls == 0
    recovery_temporary.unlink()
    second_temporary.unlink()

    invalid_bytes = b'{"status":"pass"}\n'
    receipt_path.write_bytes(invalid_bytes)
    receipt_path.chmod(0o600)
    recovery_temporary.hardlink_to(receipt_path)
    mutation_events.clear()
    validation_events.clear()
    root_free_calls = 0
    with pytest.raises(RuntimeError, match=builder.RECEIPT_CONFLICT_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=image_tag,
            receipt_path=receipt_path,
        )
    assert not recovery_temporary.exists()
    assert receipt_path.read_bytes() == invalid_bytes
    assert receipt_path.stat().st_nlink == 1
    assert mutation_events == []
    assert validation_events == []
    assert root_free_calls == 0

    security_tamper = dict(first)
    security_tamper["runtime_secrets_baked_in"] = True
    legacy_schema_tamper = {
        **first,
        "schema": "ea.manfred_memorial_image_build.v2",
    }
    extra_field_tamper = {**first, "unexpected": True}
    failure_tamper = {**first, "status": "fail"}
    alternate_tag = f"ea-runtime:memorial-{commit}"
    cases = (
        (builder._build_receipt_bytes(security_tamper), IMAGE_ID, image_tag),
        (builder._build_receipt_bytes(legacy_schema_tamper), IMAGE_ID, image_tag),
        (builder._build_receipt_bytes(extra_field_tamper), IMAGE_ID, image_tag),
        (builder._build_receipt_bytes(failure_tamper), IMAGE_ID, image_tag),
        (original_bytes.rstrip(b"\n") + b" \n", IMAGE_ID, image_tag),
        (original_bytes, f"sha256:{'f' * 64}", image_tag),
        (original_bytes, IMAGE_ID, alternate_tag),
    )
    for encoded, replay_image_id, requested_tag in cases:
        receipt_path.write_bytes(encoded)
        receipt_path.chmod(0o600)
        current_image_id = replay_image_id
        mutation_events.clear()
        validation_events.clear()
        root_free_calls = 0

        with pytest.raises(RuntimeError, match=builder.RECEIPT_CONFLICT_ERROR):
            builder.build_image(
                source_root=source_root,
                ref="HEAD",
                tag=requested_tag,
                receipt_path=receipt_path,
            )

        assert mutation_events == []
        assert root_free_calls == 0
        assert receipt_path.read_bytes() == encoded

    class ChangedCurrentAuthority(_FakeCandidateVexpAuthority):
        def require_current(self) -> dict[str, object]:
            evidence = super().require_current()
            evidence["permit_sha256"] = "0" * 64
            return evidence

    receipt_path.write_bytes(original_bytes)
    receipt_path.chmod(0o600)
    mutation_events.clear()
    validation_events.clear()
    root_free_calls = 0
    with pytest.raises(RuntimeError, match=builder.RECEIPT_CONFLICT_ERROR):
        builder.build_image(
            source_root=source_root,
            ref="HEAD",
            tag=image_tag,
            receipt_path=receipt_path,
            vexp_authority=ChangedCurrentAuthority(),
        )
    assert mutation_events == []
    assert validation_events == []
    assert root_free_calls == 0


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

    operations: list[dict[str, object]] = []
    assert (
        builder._ensure_dedicated_builder(
            _FakeCandidateVexpAuthority(),
            operations,
        )
        is True
    )
    assert [row["operation"] for row in operations] == ["builder_create"]
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
        builder._ensure_dedicated_builder(_FakeCandidateVexpAuthority(), [])

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
        builder._ensure_dedicated_builder(_FakeCandidateVexpAuthority(), [])

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
        builder._ensure_dedicated_builder(_FakeCandidateVexpAuthority(), [])

    assert [command[:3] for command in commands] == [
        ["docker", "buildx", "ls"],
        ["docker", "buildx", "create"],
    ]


def test_cache_prune_and_image_removal_hold_explicit_candidate_leases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_depth = 0
    lease_events: list[tuple[str, str, float]] = []
    commands: list[list[str]] = []
    image_present = True

    class RecordingAuthority:
        @contextmanager
        def mutation(self, boundary: str, *, minimum_validity_seconds: float):
            nonlocal lease_depth
            lease_events.append(("enter", boundary, minimum_validity_seconds))
            lease_depth += 1
            try:
                yield _FakeCandidateVexpLease(boundary)
            finally:
                lease_depth -= 1
                lease_events.append(("exit", boundary, minimum_validity_seconds))

    def guarded_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        stdout: object | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal image_present
        del cwd, stdout
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "buildx", "prune"]:
            assert lease_depth == 1
            return _completed(command)
        if command[:3] == ["docker", "image", "ls"]:
            rendered = f"{IMAGE_ID}\n".encode("utf-8") if image_present else b""
            return _completed(command, stdout=rendered)
        if command[:3] == ["docker", "image", "rm"]:
            assert lease_depth == 1
            image_present = False
            return _completed(command)
        raise AssertionError(f"unexpected command: {command!r}")

    authority = RecordingAuthority()
    monkeypatch.setattr(builder, "_run", guarded_run)

    operations: list[dict[str, object]] = []
    builder._prune_dedicated_builder_cache(authority, operations)
    cleanup_status = builder._cleanup_new_image(
        "ea-runtime:manfred-test",
        expected_image_id=IMAGE_ID,
        authority=authority,
        operations=operations,
    )

    assert cleanup_status == "removed"
    assert [event[0] for event in lease_events] == [
        "enter",
        "exit",
        "enter",
        "exit",
    ]
    assert {event[1] for event in lease_events} == {
        "before_candidate_image_build"
    }
    assert commands[0][:3] == ["docker", "buildx", "prune"]
    assert [command[:3] for command in commands].count(
        ["docker", "image", "rm"]
    ) == 1
    assert [row["operation"] for row in operations] == [
        "builder_prune",
        "image_cleanup",
    ]


def test_cleanup_mutations_fail_closed_when_candidate_lease_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    class DeniedAuthority:
        @contextmanager
        def mutation(self, boundary: str, *, minimum_validity_seconds: float):
            assert boundary == "before_candidate_image_build"
            assert minimum_validity_seconds > 0
            raise RuntimeError("candidate-cleanup-authority-denied")
            yield  # pragma: no cover

    def read_only_image_lookup(
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
        raise AssertionError(f"mutation escaped denied authority: {command!r}")

    authority = DeniedAuthority()
    monkeypatch.setattr(builder, "_run", read_only_image_lookup)

    with pytest.raises(RuntimeError, match="candidate-cleanup-authority-denied"):
        builder._prune_dedicated_builder_cache(authority, [])
    cleanup_status = builder._cleanup_new_image(
        "ea-runtime:manfred-test",
        expected_image_id=IMAGE_ID,
        authority=authority,
        operations=[],
    )

    assert cleanup_status == "remove_failed"
    assert [command[:3] for command in commands] == [["docker", "image", "ls"]]


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
    verified_filesystems: list[str] = []

    monkeypatch.setattr(builder, "_exclusive_build_lock", lambda: _acquired_lock())
    monkeypatch.setattr(builder, "_commit_for_ref", lambda _root, _ref: commit)
    monkeypatch.setattr(
        builder,
        "_root_free_bytes",
        lambda: builder.MINIMUM_ROOT_FREE_BYTES + 1024,
    )
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
    def verify_filesystem(
        image_reference: str,
        *,
        authority: object,
        operations: list[dict[str, object]],
    ) -> str:
        verified_filesystems.append(image_reference)
        return _record_fake_verification(
            image_reference,
            authority=authority,
            operations=operations,
        )

    monkeypatch.setattr(
        builder,
        "_verify_image_filesystem_authorized",
        verify_filesystem,
    )

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
    assert verified_filesystems == [IMAGE_ID]


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
    monkeypatch.setattr(
        builder,
        "_root_free_bytes",
        lambda: builder.MINIMUM_ROOT_FREE_BYTES + 1024,
    )
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
    monkeypatch.setattr(
        builder,
        "_root_free_bytes",
        lambda: builder.MINIMUM_ROOT_FREE_BYTES + 1024,
    )
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
    monkeypatch.setattr(
        builder,
        "_root_free_bytes",
        lambda: builder.MINIMUM_ROOT_FREE_BYTES + 1024,
    )
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

    def fail_filesystem_verification(
        image_reference: str,
        *,
        authority: object,
        operations: list[dict[str, object]],
    ) -> None:
        del authority, operations
        assert image_reference == IMAGE_ID
        raise RuntimeError("filesystem mismatch")

    monkeypatch.setattr(
        builder,
        "_verify_image_filesystem_authorized",
        fail_filesystem_verification,
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
    assert failure_receipt["schema"] == "ea.manfred_memorial_image_build.v3"
    assert failure_receipt["status"] == "fail"
    assert failure_receipt["error"] == builder.POST_BUILD_VERIFY_ERROR
    assert failure_receipt["new_image_cleanup_status"] == "removed"
    assert failure_receipt["build_cache_prune"]["status"] == "pass"
    assert failure_receipt["preexisting_image"] is False


def test_verifier_reclaims_exact_stale_identity_and_leaves_no_orphan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _FakeCandidateVexpAuthority()
    operations: list[dict[str, object]] = []
    commands: list[list[str]] = []
    container_id = "1" * 64
    name = builder._verification_container_name(IMAGE_ID)
    present = True

    def lifecycle_run(
        argv: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal present
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "container", "inspect"]:
            if not present:
                raise subprocess.CalledProcessError(
                    1,
                    command,
                    stderr=b"Error: No such container",
                )
            return _completed(
                command,
                stdout=_verification_inspection(
                    name=name,
                    image_id=IMAGE_ID,
                    container_id=container_id,
                ),
            )
        if command[:3] == ["docker", "container", "rm"]:
            assert command == [
                "docker",
                "container",
                "rm",
                "--force",
                container_id,
            ]
            present = False
            return _completed(command)
        if command[:3] == ["docker", "container", "create"]:
            assert present is False
            assert command[3:7] == [
                "--name",
                name,
                "--label",
                f"{builder.VERIFICATION_CONTAINER_LABEL}={IMAGE_ID}",
            ]
            present = True
            return _completed(command, stdout=f"{container_id}\n".encode("ascii"))
        if command[:3] == ["docker", "container", "start"]:
            assert command == [
                "docker",
                "container",
                "start",
                "--attach",
                container_id,
            ]
            return _completed(command)
        raise AssertionError(f"unexpected verification command: {command!r}")

    monkeypatch.setattr(builder, "_run", lifecycle_run)

    assert (
        builder._verify_image_filesystem(
            IMAGE_ID,
            authority=authority,
            operations=operations,
        )
        == name
    )

    assert present is False
    assert [row["operation"] for row in operations] == [
        "verification_stale_cleanup",
        "verification_create",
        "verification_probe",
        "verification_cleanup",
    ]
    assert all(command[:2] != ["docker", "run"] for command in commands)
    assert [command[:3] for command in commands].count(
        ["docker", "container", "rm"]
    ) == 2


def test_verifier_create_failure_rechecks_exact_name_and_cleans_created_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _FakeCandidateVexpAuthority()
    operations: list[dict[str, object]] = []
    commands: list[list[str]] = []
    container_id = "2" * 64
    name = builder._verification_container_name(IMAGE_ID)
    present = False

    def create_then_fail(
        argv: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal present
        command = list(argv)
        commands.append(command)
        if command[:3] == ["docker", "container", "inspect"]:
            if not present:
                raise subprocess.CalledProcessError(
                    1,
                    command,
                    stderr=b"Error: No such object",
                )
            return _completed(
                command,
                stdout=_verification_inspection(
                    name=name,
                    image_id=IMAGE_ID,
                    container_id=container_id,
                ),
            )
        if command[:3] == ["docker", "container", "create"]:
            present = True
            raise subprocess.CalledProcessError(
                125,
                command,
                stderr=b"client transport failed after create",
            )
        if command[:3] == ["docker", "container", "rm"]:
            present = False
            return _completed(command)
        raise AssertionError(f"unexpected verification command: {command!r}")

    monkeypatch.setattr(builder, "_run", create_then_fail)

    with pytest.raises(subprocess.CalledProcessError):
        builder._verify_image_filesystem(
            IMAGE_ID,
            authority=authority,
            operations=operations,
        )

    assert present is False
    assert [row["operation"] for row in operations] == [
        "verification_create",
        "verification_cleanup",
    ]
    assert [command[:3] for command in commands].count(
        ["docker", "container", "rm"]
    ) == 1


def test_verifier_never_removes_foreign_exact_name_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[dict[str, object]] = []
    commands: list[list[str]] = []
    name = builder._verification_container_name(IMAGE_ID)

    def foreign_inspection(
        argv: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        command = list(argv)
        commands.append(command)
        assert command == ["docker", "container", "inspect", name]
        return _completed(
            command,
            stdout=_verification_inspection(
                name=name,
                image_id=f"sha256:{'f' * 64}",
                container_id="3" * 64,
            ),
        )

    monkeypatch.setattr(builder, "_run", foreign_inspection)

    with pytest.raises(
        RuntimeError,
        match="manfred_image_verification_container_identity_mismatch",
    ):
        builder._verify_image_filesystem(
            IMAGE_ID,
            authority=_FakeCandidateVexpAuthority(),
            operations=operations,
        )

    assert operations == []
    assert commands == [["docker", "container", "inspect", name]]


def test_candidate_tag_is_full_revision_and_rejects_short_collision_locator() -> None:
    commit = "d" * 40
    exact = f"ea-runtime:manfred-{commit}"

    assert builder._safe_tag("", commit=commit) == exact
    assert builder._safe_tag(exact, commit=commit) == exact
    with pytest.raises(ValueError, match="manfred_image_tag_revision_mismatch"):
        builder._safe_tag(f"ea-runtime:manfred-{commit[:12]}", commit=commit)
    with pytest.raises(ValueError, match="manfred_image_mutable_tag_forbidden"):
        builder._safe_tag("ea-runtime:latest", commit=commit)


def test_candidate_authority_denial_stops_before_lock_or_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class DeniedAuthority:
        def require_current(self) -> dict[str, object]:
            raise RuntimeError("candidate-authority-denied")

    lock_entered = False

    @contextmanager
    def forbidden_lock() -> Iterator[None]:
        nonlocal lock_entered
        lock_entered = True
        yield

    monkeypatch.setattr(builder, "_producer_sha256", lambda: "a" * 64)
    monkeypatch.setattr(builder, "_exclusive_build_lock", forbidden_lock)
    monkeypatch.setattr(
        builder,
        "_run",
        lambda *_args, **_kwargs: pytest.fail(
            "Docker and Git must not run after candidate authority denial"
        ),
    )

    with pytest.raises(RuntimeError, match="candidate-authority-denied"):
        builder.build_image(
            source_root=tmp_path,
            ref="HEAD",
            tag="",
            receipt_path=tmp_path / "receipt.json",
            vexp_authority=DeniedAuthority(),
        )

    assert lock_entered is False
