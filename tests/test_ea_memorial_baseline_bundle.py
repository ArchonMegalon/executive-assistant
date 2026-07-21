from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from scripts import ea_memorial_baseline_bundle as bundle
from scripts import plan_ea_memorial_api_baseline_normalization as planner


REVISION = "2e5b40f9fe2ef4acb7946eb7e80537fcd01ab047"
BASE = b"""services:
  ea-api:
    environment:
      - EXPLICIT=fixed
"""
MEMORIAL = b"""services:
  ea-api:
    environment:
      - EA_SOURCE_REVISION=fixed
"""


def _object_id(raw: bytes) -> str:
    payload = f"blob {len(raw)}\0".encode("ascii") + raw
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


class FakeRunner:
    def __init__(self, *, ancestor: bool = True, base: bytes = BASE) -> None:
        self.ancestor = ancestor
        self.blobs = {
            "docker-compose.yml": base,
            "docker-compose.memorial.yml": MEMORIAL,
        }
        self.object_ids = {
            path: _object_id(raw) for path, raw in self.blobs.items()
        }
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        command = tuple(args)
        self.calls.append(command)
        assert command[0] == "/usr/bin/git"
        assert command[1] == "--no-replace-objects"
        assert check is False
        assert str(cwd).startswith("/proc/self/fd/")
        assert env["GIT_GRAFT_FILE"] == os.devnull
        assert env["GIT_OPTIONAL_LOCKS"] == "0"
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert env["GIT_NO_LAZY_FETCH"] == "1"
        assert env["PATH"] == "/usr/bin:/bin"
        git_args = command[2:]
        if git_args == (
            "rev-parse",
            "--verify",
            "--end-of-options",
            REVISION + "^{commit}",
        ):
            return self._result(command, REVISION.encode() + b"\n")
        if git_args == (
            "rev-parse",
            "--verify",
            "--end-of-options",
            "origin/main^{commit}",
        ):
            return self._result(command, REVISION.encode() + b"\n")
        if git_args == (
            "merge-base",
            "--is-ancestor",
            REVISION,
            REVISION,
        ):
            return self._result(command, b"", 0 if self.ancestor else 1)
        for path, object_id in self.object_ids.items():
            if git_args == (
                "rev-parse",
                "--verify",
                "--end-of-options",
                REVISION + ":" + path,
            ):
                return self._result(command, object_id.encode() + b"\n")
            if git_args == ("cat-file", "-t", object_id):
                return self._result(command, b"blob\n")
            if git_args == ("cat-file", "-s", object_id):
                return self._result(
                    command, str(len(self.blobs[path])).encode() + b"\n"
                )
            if git_args == ("cat-file", "blob", object_id):
                return self._result(command, self.blobs[path])
        raise AssertionError(f"unexpected command: {command!r}")

    @staticmethod
    def _result(
        args: Sequence[str], stdout: bytes, returncode: int = 0
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            list(args), returncode, stdout=stdout, stderr=b""
        )


def _private_dir(path: Path) -> Path:
    path.mkdir()
    path.chmod(0o700)
    return path


def _private_file(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


def _inputs(tmp_path: Path) -> dict[str, Any]:
    repository = _private_dir(tmp_path / "repository")
    trusted = _private_dir(tmp_path / "trusted")
    external = _private_dir(tmp_path / "external")
    recorded = _private_dir(tmp_path / "recorded")
    parent = _private_dir(tmp_path / "bundles")
    _private_file(
        trusted / ".env",
        b"EXPLICIT=must-not-enter-override\nENV_ONLY=super-secret-value\n",
    )
    _private_file(trusted / ".env.local", b"LOCAL_ONLY=another-secret\n")
    (repository / "docker-compose.yml").write_text(
        "POISONED_WORKTREE", encoding="utf-8"
    )
    (repository / "docker-compose.memorial.yml").write_text(
        "POISONED_WORKTREE", encoding="utf-8"
    )
    (external / "docker-compose.yml").write_text(
        "POISONED_EXTERNAL", encoding="utf-8"
    )
    (external / "docker-compose.memorial.yml").write_text(
        "POISONED_EXTERNAL", encoding="utf-8"
    )
    plan = planner.build_plan(
        plan_id="baseline-plan-001",
        recorded_working_dir=str(recorded),
        external_config_root=str(external),
        trusted_environment_root=str(trusted),
        expected_revision=REVISION,
        expected_image_reference="ea-runtime:memorial-main-2e5b40f9",
        expected_image_id="sha256:" + "a" * 64,
        generated_at="2026-07-21T12:00:00.000Z",
    )
    return {
        "bundle_parent": parent,
        "external": external,
        "plan": plan,
        "recorded": recorded,
        "repository_root": repository,
        "trusted": trusted,
    }


def _rebuild_plan(inputs: dict[str, Any], revision: str) -> None:
    inputs["plan"] = planner.build_plan(
        plan_id="baseline-plan-001",
        recorded_working_dir=str(inputs["recorded"]),
        external_config_root=str(inputs["external"]),
        trusted_environment_root=str(inputs["trusted"]),
        expected_revision=revision,
        expected_image_reference="ea-runtime:memorial-main-2e5b40f9",
        expected_image_id="sha256:" + "a" * 64,
        generated_at="2026-07-21T12:00:00.000Z",
    )


def _real_git(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "--no-replace-objects", *args],
        cwd=repository,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
        check=True,
        capture_output=True,
    )
    return result.stdout


def _real_repository(inputs: dict[str, Any]) -> str:
    repository = inputs["repository_root"]
    _real_git(repository, "init", "-q")
    _real_git(repository, "config", "user.name", "Baseline Test")
    _real_git(repository, "config", "user.email", "baseline@example.invalid")
    (repository / "docker-compose.yml").write_bytes(BASE)
    (repository / "docker-compose.memorial.yml").write_bytes(MEMORIAL)
    _real_git(repository, "add", "docker-compose.yml", "docker-compose.memorial.yml")
    _real_git(repository, "commit", "-q", "-m", "baseline")
    revision = _real_git(repository, "rev-parse", "HEAD").decode().strip()
    _real_git(repository, "update-ref", "refs/remotes/origin/main", revision)
    _rebuild_plan(inputs, revision)
    return revision


def _materialize(inputs: Mapping[str, Any], runner: FakeRunner) -> dict[str, Any]:
    return bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=inputs["repository_root"],
        bundle_parent=inputs["bundle_parent"],
        test_runner=runner,
        durable_root_check=lambda _path: None,
    )


def _seal(info: Mapping[str, Any]) -> dict[str, str]:
    return {
        "contract_name": bundle.RECOVERY_SEAL_CONTRACT,
        "manifest_sha256": str(info["manifest_sha256"]),
        "plan_sha256": str(info["plan_sha256"]),
    }


def _file_record(path: Path, relative_path: str) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "git_blob_id": None,
        "mode": "0600",
        "present": True,
        "relative_path": relative_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def test_materializes_exact_git_blobs_and_value_free_override(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()

    info = _materialize(inputs, runner)

    root = Path(info["bundle_path"])
    assert root.name == "api-baseline-baseline-plan-001"
    assert info["origin_main_commit"] == REVISION
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert Path(info["compose_files"][0]).read_bytes() == BASE
    assert Path(info["compose_files"][1]).read_bytes() == MEMORIAL
    assert Path(info["compose_files"][2]).name == (
        "docker-compose.api-baseline-normalization.yml"
    )
    override = Path(info["compose_files"][2]).read_text(encoding="utf-8")
    dollar = "$"
    assert "env_file: !reset []" in override
    assert "ENV_ONLY=" + dollar + "{ENV_ONLY}" in override
    assert "LOCAL_ONLY=" + dollar + "{LOCAL_ONLY}" in override
    assert "EXPLICIT=" + dollar + "{EXPLICIT}" not in override
    assert "super-secret-value" not in override
    assert "another-secret" not in override
    manifest = Path(info["manifest_path"]).read_text(encoding="utf-8")
    public = json.dumps(info, sort_keys=True)
    assert "ENV_ONLY" not in manifest
    assert "LOCAL_ONLY" not in manifest
    assert "super-secret-value" not in manifest + public
    assert all(path.stat().st_nlink == 1 for path in root.iterdir())
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in root.iterdir()
    )
    assert all(call[0] == "/usr/bin/git" for call in runner.calls)
    assert sum(call[2:4] == ("cat-file", "blob") for call in runner.calls) == 2
    assert bundle.require_baseline_bundle_seal(info) == info


def test_pre_journal_reuse_rejects_changed_trusted_environment(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    _materialize(inputs, runner)
    env_path = inputs["trusted"] / ".env"
    env_path.unlink()
    env_path.symlink_to(inputs["trusted"] / ".env.local")

    with pytest.raises(bundle.BaselineBundleError):
        _materialize(inputs, runner)


def test_recovery_reuse_requires_external_manifest_and_plan_seal(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    first = _materialize(inputs, runner)
    (inputs["trusted"] / ".env").unlink()

    with pytest.raises(bundle.BaselineBundleError):
        _materialize(inputs, runner)

    second = bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=inputs["repository_root"],
        bundle_parent=inputs["bundle_parent"],
        test_runner=runner,
        trusted_recovery_seal=_seal(first),
        durable_root_check=lambda _path: None,
    )
    assert second == first


def test_sealed_recovery_uses_no_repository_or_trusted_environment(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    first = _materialize(inputs, runner)
    call_count = len(runner.calls)
    inputs["repository_root"].rename(tmp_path / "repository-unavailable")
    inputs["trusted"].rename(tmp_path / "trusted-unavailable")

    recovered = bundle.require_recovery_baseline_bundle(
        bundle_path=Path(first["bundle_path"]),
        trusted_recovery_seal=_seal(first),
    )
    delegated = bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=inputs["repository_root"],
        bundle_parent=inputs["bundle_parent"],
        test_runner=runner,
        trusted_recovery_seal=_seal(first),
        durable_root_check=lambda _path: None,
    )

    assert recovered == first
    assert delegated == first
    assert len(runner.calls) == call_count


def test_sealed_recovery_missing_bundle_blocks_before_repository_access(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    first = _materialize(inputs, runner)
    call_count = len(runner.calls)
    Path(first["bundle_path"]).rename(
        inputs["bundle_parent"] / "retained-but-not-canonical"
    )
    inputs["repository_root"].rename(tmp_path / "repository-unavailable")

    with pytest.raises(
        bundle.BaselineBundleError, match="trusted_recovery_bundle_missing"
    ):
        bundle.require_recovery_baseline_bundle(
            bundle_path=Path(first["bundle_path"]),
            trusted_recovery_seal=_seal(first),
        )
    assert len(runner.calls) == call_count


def test_occupied_bundle_cannot_self_sign_different_override_semantics(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    first = _materialize(inputs, runner)
    root = Path(first["bundle_path"])
    manifest_path = Path(first["manifest_path"])
    manifest = json.loads(manifest_path.read_bytes())
    override = root / bundle.NORMALIZATION_OVERRIDE
    override.write_bytes(
        b"services:\n  ea-api:\n    env_file: !reset []\n"
        b"    environment:\n      - FORGED=${FORGED}\n"
    )
    manifest["ordered_compose_files"][2] = _file_record(
        override, bundle.NORMALIZATION_OVERRIDE
    )
    manifest["environment_key_count"] = 1
    manifest["environment_key_set_sha256"] = hashlib.sha256(
        b'["FORGED"]'
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        bundle.BaselineBundleError, match="existing_bundle_semantics_mismatch"
    ):
        _materialize(inputs, runner)
    with pytest.raises(
        bundle.BaselineBundleError, match="trusted_recovery_seal_mismatch"
    ):
        bundle._materialize_baseline_bundle_for_test(
            plan=inputs["plan"],
            repository_root=inputs["repository_root"],
            bundle_parent=inputs["bundle_parent"],
            test_runner=runner,
            trusted_recovery_seal=_seal(first),
            durable_root_check=lambda _path: None,
        )


def test_pre_journal_reuse_requires_exact_retained_environment_bytes(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    first = _materialize(inputs, runner)
    retained = Path(first["bundle_path"]) / ".env"
    retained.write_bytes(b"EXPLICIT=fixed\nFORGED=secret\n")
    manifest_path = Path(first["manifest_path"])
    manifest = json.loads(manifest_path.read_bytes())
    manifest["environment_files"][0] = _file_record(retained, ".env")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        bundle.BaselineBundleError,
        match="existing_bundle_trusted_environment_mismatch",
    ):
        _materialize(inputs, runner)


@pytest.mark.parametrize(
    "seal_change",
    [
        {"plan_sha256": "0" * 64},
        {"manifest_sha256": "0" * 64},
        {"contract_name": "wrong.contract"},
        {"extra": "not-allowed"},
    ],
)
def test_recovery_seal_is_exact_and_externally_bound(
    tmp_path: Path, seal_change: Mapping[str, str]
) -> None:
    inputs = _inputs(tmp_path)
    runner = FakeRunner()
    first = _materialize(inputs, runner)
    candidate = _seal(first)
    candidate.update(seal_change)

    with pytest.raises(bundle.BaselineBundleError):
        bundle._materialize_baseline_bundle_for_test(
            plan=inputs["plan"],
            repository_root=inputs["repository_root"],
            bundle_parent=inputs["bundle_parent"],
            test_runner=runner,
            trusted_recovery_seal=candidate,
            durable_root_check=lambda _path: None,
        )


def test_seal_rejects_mode_and_content_drift(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    info = _materialize(inputs, FakeRunner())
    override = Path(info["compose_files"][2])
    override.chmod(0o644)

    with pytest.raises(bundle.BaselineBundleError):
        bundle.require_baseline_bundle_seal(info)


@pytest.mark.parametrize("attack", ["mode", "symlink", "hardlink", "fifo"])
def test_rejects_untrusted_required_environment_file(
    tmp_path: Path, attack: str
) -> None:
    inputs = _inputs(tmp_path)
    target = inputs["trusted"] / ".env"
    if attack == "mode":
        target.chmod(0o644)
    elif attack == "symlink":
        target.unlink()
        target.symlink_to(inputs["trusted"] / ".env.local")
    elif attack == "hardlink":
        os.link(target, inputs["trusted"] / "second-link")
    else:
        target.unlink()
        os.mkfifo(target, mode=0o600)

    with pytest.raises(bundle.BaselineBundleError):
        _materialize(inputs, FakeRunner())


@pytest.mark.parametrize("mode", [0o750, 0o701, 0o770])
def test_trusted_environment_root_must_be_exactly_private(
    tmp_path: Path, mode: int
) -> None:
    inputs = _inputs(tmp_path)
    inputs["trusted"].chmod(mode)

    with pytest.raises(bundle.BaselineBundleError, match="directory_mode_invalid"):
        _materialize(inputs, FakeRunner())


@pytest.mark.parametrize("attack", ["mode", "symlink", "hardlink", "fifo"])
def test_rejects_untrusted_optional_environment_file(
    tmp_path: Path, attack: str
) -> None:
    inputs = _inputs(tmp_path)
    target = inputs["trusted"] / ".env.local"
    if attack == "mode":
        target.chmod(0o640)
    elif attack == "symlink":
        target.unlink()
        target.symlink_to(inputs["trusted"] / ".env")
    elif attack == "hardlink":
        os.link(target, inputs["trusted"] / "local-second-link")
    else:
        target.unlink()
        os.mkfifo(target, mode=0o600)

    with pytest.raises(bundle.BaselineBundleError):
        _materialize(inputs, FakeRunner())


def test_optional_environment_absence_is_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    (inputs["trusted"] / ".env.local").unlink()
    original = bundle._read_at

    def racing_read(
        directory_fd: int, name: str, **kwargs: Any
    ) -> tuple[bytes | None, dict[str, object]]:
        result = original(directory_fd, name, **kwargs)
        if name == ".env.local" and result[0] is None:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            os.write(descriptor, b"RACED=value\n")
            os.close(descriptor)
        return result

    monkeypatch.setattr(bundle, "_read_at", racing_read)
    with pytest.raises(
        bundle.BaselineBundleError, match="trusted_env_local_presence_changed"
    ):
        _materialize(inputs, FakeRunner())


def test_trusted_environment_root_identity_is_held_across_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    trusted = inputs["trusted"]
    original = bundle._read_at
    swapped = False

    def swapping_read(
        directory_fd: int, name: str, **kwargs: Any
    ) -> tuple[bytes | None, dict[str, object]]:
        nonlocal swapped
        result = original(directory_fd, name, **kwargs)
        if name == ".env" and not swapped:
            swapped = True
            old = trusted.with_name("trusted-held-old")
            trusted.rename(old)
            _private_dir(trusted)
            _private_file(trusted / ".env", b"FORGED=value\n")
            _private_file(trusted / ".env.local", b"FORGED_LOCAL=value\n")
        return result

    monkeypatch.setattr(bundle, "_read_at", swapping_read)
    with pytest.raises(
        bundle.BaselineBundleError, match="trusted_environment_root_changed"
    ):
        _materialize(inputs, FakeRunner())


def test_rejects_non_ancestor_and_occupied_bundle_path(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(
        bundle.BaselineBundleError,
        match="source_commit_not_origin_main_ancestor",
    ):
        _materialize(inputs, FakeRunner(ancestor=False))

    occupied = (
        inputs["bundle_parent"] / "api-baseline-baseline-plan-001"
    )
    occupied.symlink_to(inputs["trusted"], target_is_directory=True)
    with pytest.raises(bundle.BaselineBundleError, match="bundle_path_occupied"):
        _materialize(inputs, FakeRunner())


def test_duplicate_historical_environment_key_fails_closed(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    poisoned = b"""services:
  ea-api:
    environment:
      - DUPLICATE=one
      - DUPLICATE=two
"""
    with pytest.raises(
        bundle.BaselineBundleError, match="compose_environment_duplicate"
    ):
        _materialize(inputs, FakeRunner(base=poisoned))


@pytest.mark.parametrize(
    "poisoned",
    [
        b"""x-api: &api
  environment:
    - MERGED=value
services:
  ea-api:
    <<: *api
""",
        b"""services:
  ea-api:
    extends:
      service: inherited
    environment: []
""",
        b"""include:
  - external.yml
services:
  ea-api:
    environment: []
""",
        b"""services:
  ea-api: !unsupported
    environment: []
""",
        b"""services:
  ea-api:
    command: !unsupported []
    environment: []
""",
        b"""services:
  ea-api:
    environment: []
---
services:
  ea-api:
    environment: []
""",
    ],
)
def test_rejects_compose_features_that_hide_environment_semantics(
    tmp_path: Path, poisoned: bytes
) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(bundle.BaselineBundleError):
        _materialize(inputs, FakeRunner(base=poisoned))


@pytest.mark.parametrize(
    "poisoned",
    [
        b'A="first\nB=second"\n',
        b"A='first\nB=second'\n",
        b'A=prefix"quoted"\n',
        b"A=value\\\nB=second\n",
        b'A="bad\\q"\n',
        b"A='closed' trailing\n",
    ],
)
def test_dotenv_parser_rejects_multiline_and_unsupported_quoting(
    tmp_path: Path, poisoned: bytes
) -> None:
    inputs = _inputs(tmp_path)
    _private_file(inputs["trusted"] / ".env", poisoned)

    with pytest.raises(bundle.BaselineBundleError):
        _materialize(inputs, FakeRunner())


def test_dotenv_parser_accepts_only_bounded_single_line_quotes(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    _private_file(
        inputs["trusted"] / ".env",
        b"EXPLICIT='fixed'\nENV_ONLY=\"one\\nline\"\nPLAIN=value # note\n",
    )

    info = _materialize(inputs, FakeRunner())

    override = Path(info["compose_files"][2]).read_text(encoding="utf-8")
    assert "ENV_ONLY=${ENV_ONLY}" in override
    assert "PLAIN=${PLAIN}" in override


def test_real_git_replace_ref_cannot_change_exact_historical_blobs(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    revision = _real_repository(inputs)
    repository = inputs["repository_root"]
    (repository / "docker-compose.yml").write_bytes(
        b"services:\n  ea-api:\n    environment:\n      - POISON=replaced\n"
    )
    _real_git(repository, "add", "docker-compose.yml")
    replacement_tree = _real_git(repository, "write-tree").decode().strip()
    replacement_commit = _real_git(
        repository, "commit-tree", replacement_tree, "-m", "replacement"
    ).decode().strip()
    _real_git(repository, "reset", "-q", "--hard", revision)
    _real_git(repository, "replace", revision, replacement_commit)
    replaced = subprocess.run(
        ["/usr/bin/git", "show", revision + ":docker-compose.yml"],
        cwd=repository,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
        check=True,
        capture_output=True,
    ).stdout
    assert b"POISON=replaced" in replaced

    info = bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=repository,
        bundle_parent=inputs["bundle_parent"],
        test_runner=None,
        durable_root_check=lambda _path: None,
    )

    assert Path(info["compose_files"][0]).read_bytes() == BASE
    assert info["origin_main_commit"] == revision


def test_real_git_graft_cannot_forge_origin_main_ancestry(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    revision = _real_repository(inputs)
    repository = inputs["repository_root"]
    tree = _real_git(repository, "write-tree").decode().strip()
    unrelated = _real_git(
        repository, "commit-tree", tree, "-m", "unrelated-origin"
    ).decode().strip()
    _real_git(repository, "update-ref", "refs/remotes/origin/main", unrelated)
    graft = repository / ".git" / "info" / "grafts"
    graft.write_text(f"{unrelated} {revision}\n", encoding="ascii")
    forged = subprocess.run(
        ["/usr/bin/git", "merge-base", "--is-ancestor", revision, unrelated],
        cwd=repository,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        },
        check=False,
        capture_output=True,
    )
    assert forged.returncode == 0

    with pytest.raises(
        bundle.BaselineBundleError,
        match="source_commit_not_origin_main_ancestor",
    ):
        bundle._materialize_baseline_bundle_for_test(
            plan=inputs["plan"],
            repository_root=repository,
            bundle_parent=inputs["bundle_parent"],
            test_runner=None,
            durable_root_check=lambda _path: None,
        )


def test_descriptor_bound_git_reads_linked_worktree(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    revision = _real_repository(inputs)
    repository = inputs["repository_root"]
    linked = tmp_path / "linked-worktree"
    _real_git(
        repository,
        "worktree",
        "add",
        "-q",
        "--detach",
        str(linked),
        revision,
    )
    linked_fd = bundle._open_dir(linked, private=False, owner=True)
    try:
        descriptor_cwd = bundle._repository_descriptor_cwd(linked_fd)
        top_level = bundle._git_line(
            bundle.SubprocessRunner(),
            descriptor_cwd,
            ["rev-parse", "--show-toplevel"],
            "linked_worktree_top_level_unavailable",
        )
        assert Path(top_level).samefile(linked)
    finally:
        os.close(linked_fd)

    info = bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=linked,
        bundle_parent=inputs["bundle_parent"],
        test_runner=None,
        durable_root_check=lambda _path: None,
    )

    assert info["source_revision"] == revision
    assert Path(info["compose_files"][0]).read_bytes() == BASE


def test_sealed_recovery_ignores_current_origin_fast_forward_and_rewrite(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    revision = _real_repository(inputs)
    repository = inputs["repository_root"]
    first = bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=repository,
        bundle_parent=inputs["bundle_parent"],
        test_runner=None,
        durable_root_check=lambda _path: None,
    )
    tree = _real_git(repository, "write-tree").decode().strip()
    fast_forward = _real_git(
        repository,
        "commit-tree",
        tree,
        "-p",
        revision,
        "-m",
        "advanced-origin",
    ).decode().strip()
    _real_git(
        repository, "update-ref", "refs/remotes/origin/main", fast_forward
    )
    advanced_recovery = bundle.require_recovery_baseline_bundle(
        bundle_path=Path(first["bundle_path"]),
        trusted_recovery_seal=_seal(first),
    )
    assert advanced_recovery == first

    rewritten = _real_git(
        repository, "commit-tree", tree, "-m", "rewritten-origin"
    ).decode().strip()
    assert rewritten != revision
    _real_git(repository, "update-ref", "refs/remotes/origin/main", rewritten)

    recovered = bundle.require_recovery_baseline_bundle(
        bundle_path=Path(first["bundle_path"]),
        trusted_recovery_seal=_seal(first),
    )

    assert recovered == first


def test_production_git_ignores_hostile_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    revision = _real_repository(inputs)
    hostile = _private_dir(tmp_path / "hostile-bin")
    fake_git = hostile / "git"
    fake_git.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(hostile))

    info = bundle._materialize_baseline_bundle_for_test(
        plan=inputs["plan"],
        repository_root=inputs["repository_root"],
        bundle_parent=inputs["bundle_parent"],
        test_runner=None,
        durable_root_check=lambda _path: None,
    )

    assert info["source_revision"] == revision


def test_repository_path_identity_is_revalidated_around_git_reads(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    repository = inputs["repository_root"]

    class SwappingRunner(FakeRunner):
        def run(
            self,
            args: Sequence[str],
            *,
            cwd: Path,
            env: Mapping[str, str],
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            result = super().run(args, cwd=cwd, env=env, check=check)
            if len(self.calls) == 1:
                repository.rename(repository.with_name("repository-held-old"))
                _private_dir(repository)
            return result

    with pytest.raises(
        bundle.BaselineBundleError, match="repository_root_changed"
    ):
        _materialize(inputs, SwappingRunner())


def test_repository_ancestor_swap_is_detected_with_descriptor_bound_git(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    ancestor = _private_dir(tmp_path / "repository-ancestor")
    repository = _private_dir(ancestor / "repository")
    inputs["repository_root"] = repository

    class AncestorSwappingRunner(FakeRunner):
        def run(
            self,
            args: Sequence[str],
            *,
            cwd: Path,
            env: Mapping[str, str],
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            result = super().run(args, cwd=cwd, env=env, check=check)
            if len(self.calls) == 1:
                ancestor.rename(tmp_path / "repository-ancestor-held-old")
                replacement = _private_dir(tmp_path / "repository-ancestor")
                _private_dir(replacement / "repository")
            return result

    with pytest.raises(
        bundle.BaselineBundleError, match="repository_root_changed"
    ):
        _materialize(inputs, AncestorSwappingRunner())


def test_manifest_json_rejects_duplicate_keys_and_nonfinite_numbers(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    info = _materialize(inputs, FakeRunner())
    manifest_path = Path(info["manifest_path"])
    original = manifest_path.read_text(encoding="utf-8")
    duplicate = original.rstrip()[:-1] + ', "version": 1}\n'
    manifest_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(
        bundle.BaselineBundleError,
        match="bundle_manifest_json_duplicate_key",
    ):
        bundle.require_baseline_bundle_seal(info)

    manifest_path.write_text(original, encoding="utf-8")
    nonfinite = original.replace(
        '"environment_key_count": 2',
        '"environment_key_count": NaN',
    )
    assert nonfinite != original
    manifest_path.write_text(nonfinite, encoding="utf-8")
    with pytest.raises(
        bundle.BaselineBundleError, match="bundle_manifest_json_nonfinite"
    ):
        bundle.require_baseline_bundle_seal(info)


def test_final_bundle_rejects_any_unsealed_entry(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    info = _materialize(inputs, FakeRunner())
    extra = Path(info["bundle_path"]) / "unexpected"
    _private_file(extra, b"not sealed\n")

    with pytest.raises(bundle.BaselineBundleError, match="bundle_unsealed_entry"):
        bundle.require_baseline_bundle_seal(info)


def test_public_entry_point_has_no_injectable_test_or_durability_hooks(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(TypeError, match="test_runner"):
        bundle.materialize_baseline_bundle(
            plan=inputs["plan"],
            repository_root=inputs["repository_root"],
            bundle_parent=inputs["bundle_parent"],
            test_runner=FakeRunner(),
        )
    with pytest.raises(TypeError, match="durable_root_check"):
        bundle.materialize_baseline_bundle(
            plan=inputs["plan"],
            repository_root=inputs["repository_root"],
            bundle_parent=inputs["bundle_parent"],
            durable_root_check=lambda _path: None,
        )


def test_crash_staging_leftover_is_never_reused_or_deleted(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    leftover = inputs["bundle_parent"] / (
        ".api-baseline-baseline-plan-001.staging-dead"
    )
    _private_dir(leftover)
    _private_file(leftover / "attacker", b"occupied\n")

    info = _materialize(inputs, FakeRunner())

    assert leftover.is_dir()
    assert (leftover / "attacker").read_bytes() == b"occupied\n"
    assert Path(info["bundle_path"]).is_dir()


def test_publish_race_never_overwrites_and_leaves_private_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    original = bundle._rename_noreplace

    def racing_publish(parent_fd: int, source: str, destination: str) -> None:
        os.mkdir(destination, 0o700, dir_fd=parent_fd)
        destination_fd = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        try:
            marker_fd = os.open(
                "owner-marker",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_fd,
            )
            os.write(marker_fd, b"do-not-overwrite\n")
            os.close(marker_fd)
        finally:
            os.close(destination_fd)
        original(parent_fd, source, destination)

    monkeypatch.setattr(bundle, "_rename_noreplace", racing_publish)
    with pytest.raises(bundle.BaselineBundleError, match="bundle_creation_race"):
        _materialize(inputs, FakeRunner())

    destination = (
        inputs["bundle_parent"] / "api-baseline-baseline-plan-001"
    )
    assert (destination / "owner-marker").read_bytes() == b"do-not-overwrite\n"
    staging = [
        entry
        for entry in inputs["bundle_parent"].iterdir()
        if entry.name.startswith(".api-baseline-staging-")
    ]
    assert len(staging) == 1
    assert stat.S_IMODE(staging[0].stat().st_mode) == 0o700


def test_published_directory_is_revalidated_after_atomic_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    original = bundle._rename_noreplace

    def poison_after_publish(
        parent_fd: int, source: str, destination: str
    ) -> None:
        original(parent_fd, source, destination)
        destination_fd = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        try:
            poison_fd = os.open(
                "post-rename-poison",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_fd,
            )
            os.close(poison_fd)
        finally:
            os.close(destination_fd)

    monkeypatch.setattr(bundle, "_rename_noreplace", poison_after_publish)
    with pytest.raises(bundle.BaselineBundleError, match="bundle_unsealed_entry"):
        _materialize(inputs, FakeRunner())
