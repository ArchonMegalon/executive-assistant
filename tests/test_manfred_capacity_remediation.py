from __future__ import annotations

import ast
import builtins
import contextlib
import errno
import hashlib
import io
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import apply_manfred_memorial_capacity_handoff as root_applier
from scripts import reclaim_manfred_memorial_build_capacity as controller


def _builder(*, records: int, floor: int, digest: str) -> dict[str, object]:
    return {
        "name": controller.BUILDX_BUILDER_NAME,
        "driver": controller.BUILDX_BUILDER_DRIVER,
        "node": controller.BUILDX_BUILDER_NODE_NAME,
        "endpoint": controller.BUILDX_BUILDER_ENDPOINT,
        "container_name": f"buildx_buildkit_{controller.BUILDX_BUILDER_NODE_NAME}",
        "container_id": "a" * 64,
        "container_image_id": f"sha256:{'b' * 64}",
        "volume_name": f"buildx_buildkit_{controller.BUILDX_BUILDER_NODE_NAME}_state",
        "record_count": records,
        "records_sha256": digest,
        "reclaimable_floor_bytes": floor,
        "all_records_reclaimable": True,
        "global_cache_prune": False,
    }


def _complete_process_inventory() -> dict[str, object]:
    return {
        "status": "complete",
        "same_uid_process_count": 1,
        "unreadable_process_count": 0,
        "unbounded_process_count": 0,
        "process_enumeration_complete": True,
        "process_identities_included": False,
    }


def _scope_tree(path: str, *, allocated: int, uid: int) -> dict[str, object]:
    return {
        "path": path,
        "exists": True,
        "device": 1,
        "inode": int(hashlib.sha256(path.encode()).hexdigest()[:12], 16),
        "mode": 0o700,
        "uid": uid,
        "gid": os.getgid(),
        "file_count": 1,
        "apparent_bytes": 1,
        "allocated_bytes": allocated,
        "manifest_sha256": hashlib.sha256(path.encode()).hexdigest(),
        "nlink": 2,
        "entry_count": 2,
        "root_kind": "directory",
    }


def _absent_scope_tree(path: str) -> dict[str, object]:
    return {
        "path": path,
        "exists": False,
        "device": 0,
        "inode": 0,
        "mode": 0,
        "uid": 0,
        "gid": 0,
        "file_count": 0,
        "apparent_bytes": 0,
        "allocated_bytes": 0,
        "manifest_sha256": hashlib.sha256(b"absent\n").hexdigest(),
        "nlink": 0,
        "entry_count": 0,
        "root_kind": "directory",
    }


def _plan_scope() -> dict[str, object]:
    uid = max(1, os.getuid())
    runtime_uid = uid + 10_000
    operator_home = "/home/operator"
    projections = [
        {
            "path": f"/projection/{index:02d}",
            "candidate_root": f"/candidate/{index:02d}",
            "release_id": f"{index + 1:040x}",
            "tree": _scope_tree(
                f"/projection/{index:02d}", allocated=30, uid=runtime_uid
            ),
            "runtime_uid": runtime_uid,
            "release_authority_promotion_authority": False,
            "release_authority_runtime_clear": True,
            "process_references": None,
            "root_revalidation_required": True,
            "process_reference_check": "root_revalidation_required",
        }
        for index in range(controller.EXPECTED_PROJECTION_COUNT)
    ]
    cache_paths = {
        "nuget_http": Path(operator_home) / ".local/share/NuGet/http-cache",
        "nuget_global_packages": Path(operator_home) / ".nuget/packages",
        "npm_content_cache": Path(operator_home) / ".npm/_cacache",
        "pip_cache": Path(operator_home) / ".cache/pip",
    }
    caches = [
        {
            "name": name,
            "tree": _scope_tree(str(cache_paths[name]), allocated=10, uid=uid),
            "clear_argv": list(argv),
            "active_processes": [],
            "active_process_count": 0,
            "active_process_identities_redacted": True,
            "eligible": True,
            "user_eligible": True,
            "availability": "eligible",
            "eligible_reclaim_floor_bytes": 10,
            "root_candidate": False,
            "root_reclaim_floor_bytes": 0,
            "root_classification": "rebuildable_operator_cache",
            "process_inventory_status": "complete",
            "official_cache_contract": True,
        }
        for name, argv in (
            (
                "nuget_http",
                [controller.DOTNET_BINARY, "nuget", "locals", "http-cache", "--clear"],
            ),
            (
                "nuget_global_packages",
                [
                    controller.DOTNET_BINARY,
                    "nuget",
                    "locals",
                    "global-packages",
                    "--clear",
                ],
            ),
            (
                "npm_content_cache",
                [
                    controller.NODE_BINARY,
                    controller.NPM_CLI,
                    "cache",
                    "clean",
                    "--force",
                ],
            ),
            (
                "pip_cache",
                [controller.PYTHON_EXECUTABLE, "-I", "-m", "pip", "cache", "purge"],
            ),
        )
    ]
    root_free = controller.TARGET_ROOT_FREE_BYTES - 1000
    user_floor = 100 + 100 + 40 + 20
    root_floor = 30 * controller.EXPECTED_PROJECTION_COUNT
    eligible_floor = user_floor + root_floor
    required = controller.TARGET_ROOT_FREE_BYTES - root_free
    temp_inventory = [
        {
            "action_id": action_id,
            "kind": "rebuildable_temp_tree",
            "classification": "exact_rebuildable_temporary_output",
            "path": str(path),
            "tree": _absent_scope_tree(str(path)),
            "root_identity": None,
            "user_eligible": False,
            "root_candidate": False,
            "root_reclaim_floor_bytes": 0,
            "availability": "absent",
            "reported_observation_bytes": observation,
            "capacity_source": "live_tree_evidence",
            "parent_preserved": True,
            "protected_overlap": False,
            "selection_group": None,
            "selection_limit": None,
        }
        for action_id, path, observation in controller.ROOT_TEMP_CANDIDATE_SPECS
    ]
    plan = {
        "schema": controller.PLAN_SCHEMA,
        "producer_sha256": "1" * 64,
        "producer_path": "/release/scripts/controller.py",
        "producer": {
            "path": "/release/scripts/controller.py",
            "sha256": "1" * 64,
            "size_bytes": 100,
            "owner_uid": uid,
            "mode": 0o755,
        },
        "root_applier": {
            "path": "/release/scripts/root.py",
            "sha256": "3" * 64,
            "size_bytes": 100,
            "owner_uid": uid,
            "mode": 0o755,
            "stdlib_only": True,
            "repo_imports": False,
        },
        "root_installer": controller._root_installer_evidence(),
        "mutation_helpers": [
            {
                "path": str(path),
                "device": 1,
                "inode": index + 1,
                "mode": 0o644,
                "uid": uid,
                "gid": os.getgid(),
                "nlink": 1,
                "size_bytes": 100,
                "sha256": f"{index + 4:064x}",
            }
            for index, path in enumerate(controller.MUTATION_HELPER_PATHS)
        ],
        "operator_uid": uid,
        "operator_home": operator_home,
        "deploy_root": str(Path(operator_home) / controller.DEPLOY_ROOT_RELATIVE),
        "pinned_toolchain": [{"path": path} for path in controller.PINNED_TOOL_PATHS],
        "docker_host": controller.LOCAL_DOCKER_HOST,
        "docker_context_inherited": False,
        "target_root_free_bytes": controller.TARGET_ROOT_FREE_BYTES,
        "root_free_bytes_before": root_free,
        "required_reclaim_bytes": required,
        "user_eligible_reclaim_floor_bytes": user_floor,
        "root_revalidation_reclaim_floor_bytes": root_floor,
        "root_candidate_reclaim_floor_bytes": root_floor,
        "eligible_reclaim_floor_bytes": eligible_floor,
        "eligible_capacity_deficit_bytes": max(0, required - eligible_floor),
        "eligible_capacity_sufficient": eligible_floor >= required,
        "controller_process_inventory": _complete_process_inventory(),
        "unavailable_user_actions": {
            "cache_count": 0,
            "vscode_count": 0,
            "total_count": 0,
            "identities_included": False,
        },
        "builder": _builder(records=1, floor=100, digest="7" * 64),
        "caches": caches,
        "projections": projections,
        "temp_root_candidate_inventory": temp_inventory,
        "candidate": {
            "project": controller.EXPECTED_CANDIDATE_PROJECT,
            "revision": controller.EXPECTED_CANDIDATE_REVISION,
            "image_id": controller.EXPECTED_CANDIDATE_IMAGE_ID,
            "image_tag": controller.EXPECTED_CANDIDATE_IMAGE,
            "receipt_sha256": controller.EXPECTED_CANDIDATE_RECEIPT_SHA256,
            "image_unique_floor_bytes": 100,
        },
        "vscode": {
            "server_count": 2,
            "server_root": str(
                Path(operator_home) / ".vscode-server/cli/servers"
            ),
            "active_server": f"Stable-{'a' * 40}",
            "inactive_server": f"Stable-{'b' * 40}",
            "inactive_tree": _scope_tree(
                str(
                    Path(operator_home)
                    / ".vscode-server/cli/servers"
                    / f"Stable-{'b' * 40}"
                ),
                allocated=20,
                uid=uid,
            ),
            "journal_entry_count": 1,
            "journal_payload_bytes": 100,
            "journal_entries_sha256": "8" * 64,
            "process_references": [],
            "process_inventory_status": "complete",
            "eligible": True,
            "user_eligible": True,
            "availability": "eligible",
            "eligible_reclaim_floor_bytes": 20,
            "root_candidate": False,
            "root_candidate_trees": [],
            "root_reclaim_floor_bytes": 0,
            "root_selection_limit": 1,
            "root_classification": "rebuildable_inactive_vscode_server",
        },
        "global_docker_prune_allowed": False,
        "other_zero_container_images_mutable": False,
        "candidate_roots_removed": False,
        "runtime_or_receipts_removed": False,
    }
    plan["root_candidates"] = controller._finite_root_candidates(
        caches=caches,
        vscode=dict(plan["vscode"]),
        projections=projections,
        temp_candidates=temp_inventory,
    )
    plan["root_candidate_count"] = len(plan["root_candidates"])
    plan["unsafe_temp_candidate_exclusion_count"] = 0
    plan["root_candidate_scope"] = "finite_exact_paths_only"
    plan["root_attestation_required_before_user_mutation"] = True
    return plan


def _tree(root: Path, *, content: bytes = b"capacity\n") -> int:
    root.mkdir()
    target = root / "payload.txt"
    target.write_bytes(content)
    target.chmod(0o440)
    root.chmod(0o550)
    return os.getuid()


def test_mutation_allowlist_is_exact() -> None:
    allowed = {
        controller.BUILD_CACHE_PRUNE_ARGV,
        (controller.DOTNET_BINARY, "nuget", "locals", "http-cache", "--clear"),
        (controller.DOTNET_BINARY, "nuget", "locals", "global-packages", "--clear"),
        (controller.NODE_BINARY, controller.NPM_CLI, "cache", "clean", "--force"),
        (controller.PYTHON_EXECUTABLE, "-I", "-m", "pip", "cache", "purge"),
        (
            controller.DOCKER_BINARY,
            "--host",
            controller.LOCAL_DOCKER_HOST,
            "image",
            "rm",
            controller.EXPECTED_CANDIDATE_IMAGE_ID,
        ),
    }
    assert all(controller._mutation_command_allowed(command) for command in allowed)
    forbidden = {
        ("docker", "system", "prune", "--all", "--force"),
        ("docker", "builder", "prune", "--all", "--force"),
        ("docker", "image", "prune", "--all", "--force"),
        ("docker", "volume", "prune", "--force"),
        ("docker", "buildx", "prune", "--all", "--force"),
        ("docker", "image", "rm", "ea-runtime:unrelated"),
        ("rm", "-rf", "/tmp/example"),
    }
    assert not any(controller._mutation_command_allowed(command) for command in forbidden)


def test_forbidden_prune_is_rejected_before_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def unexpected(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(controller.subprocess, "run", unexpected)
    with pytest.raises(RuntimeError, match="mutation_command_forbidden"):
        controller._bounded_run(
            ["docker", "system", "prune", "--force"],
            home=Path.home(),
            mutation=True,
        )
    assert called is False


def test_builder_apply_uses_only_dedicated_exact_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _builder(records=2, floor=1234, digest="c" * 64)
    after = _builder(records=0, floor=0, digest="d" * 64)
    inspections = iter((before, after))
    commands: list[tuple[tuple[str, ...], bool]] = []

    @contextlib.contextmanager
    def lock():
        yield

    monkeypatch.setattr(controller, "_exclusive_build_lock", lock)
    monkeypatch.setattr(controller, "_builder_inspection", lambda _home: next(inspections))

    def run(argv: object, **kwargs: object) -> bytes:
        commands.append((tuple(argv), bool(kwargs.get("mutation"))))
        return b""

    monkeypatch.setattr(controller, "_bounded_run", run)
    result = controller._apply_builder({"builder": before}, home=Path.home())
    assert result["status"] == "pruned"
    assert commands == [(controller.BUILD_CACHE_PRUNE_ARGV, True)]
    assert result["global_cache_pruned"] is False


def test_builder_empty_resume_still_revalidates_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _builder(records=3, floor=100, digest="e" * 64)
    changed = _builder(records=0, floor=0, digest="f" * 64)
    changed["container_id"] = "9" * 64

    @contextlib.contextmanager
    def lock():
        yield

    monkeypatch.setattr(controller, "_exclusive_build_lock", lock)
    monkeypatch.setattr(controller, "_builder_inspection", lambda _home: changed)
    with pytest.raises(RuntimeError, match="builder_changed"):
        controller._apply_builder({"builder": expected}, home=Path.home())


def test_cache_resume_accepts_only_smaller_attested_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = controller.TreeEvidence(
        "/cache",
        True,
        1,
        2,
        0o700,
        os.getuid(),
        os.getgid(),
        10,
        1000,
        8192,
        "a" * 64,
    )
    observed = controller.TreeEvidence(
        "/cache",
        True,
        1,
        2,
        0o700,
        os.getuid(),
        os.getgid(),
        0,
        0,
        4096,
        "b" * 64,
    )
    monkeypatch.setattr(controller, "_tree_evidence", lambda *_args, **_kwargs: observed)
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_args, **_kwargs: pytest.fail("recovery must not mutate"),
    )
    result = controller._apply_caches(
        {
            "caches": [
                {
                    "name": "pip_cache",
                    "eligible": True,
                    "tree": expected.as_dict(),
                    "clear_argv": [sys.executable, "-m", "pip", "cache", "purge"],
                }
            ]
        },
        home=Path.home(),
        uid=os.getuid(),
    )
    assert result[0]["status"] == "recovered_cleared_postcondition"
    assert result[0]["mutation_command_count"] == 0


def test_plan_digest_and_frozen_scope_reject_substitution() -> None:
    plan = controller._with_plan_digest(_plan_scope())
    controller._validate_plan(plan, producer_sha256="1" * 64)
    substituted = dict(plan)
    substituted["candidate"] = {
        **dict(plan["candidate"]),
        "revision": "2" * 40,
    }
    substituted = controller._with_plan_digest(substituted)
    with pytest.raises(RuntimeError, match="(plan|root_candidate)_scope_invalid"):
        controller._validate_plan(substituted, producer_sha256="1" * 64)
    shortened = dict(plan)
    shortened["projections"] = list(plan["projections"])[:-1]
    shortened = controller._with_plan_digest(shortened)
    with pytest.raises(
        RuntimeError, match="(plan_(scope|capacity)|root_candidate_scope)_invalid"
    ):
        controller._validate_plan(shortened, producer_sha256="1" * 64)


def test_root_handoff_binds_sources_and_finite_attested_candidates(tmp_path: Path) -> None:
    intent_path = tmp_path / "intent.json"
    intent_path.write_text("{}\n", encoding="utf-8")
    plan = {
        **_plan_scope(),
        "plan_sha256": "4" * 64,
    }
    attestation_path = tmp_path / "root-attestation.json"
    attestation_path.write_text("{}\n", encoding="utf-8")
    attestation = {
        "authorized_root_action_ids": [
            dict(plan["root_candidates"])["action_id"]
            if isinstance(plan["root_candidates"], dict)
            else dict(list(plan["root_candidates"])[0])["action_id"]
        ]
    }
    handoff = controller._root_handoff_payload(
        intent_path=intent_path,
        intent_sha256="5" * 64,
        user_receipt_path=Path("/user.json"),
        root_handoff_path=Path("/handoff.json"),
        root_receipt_path=Path("/root.json"),
        plan=plan,
        root_attestation=attestation,
        root_attestation_path=attestation_path,
        root_attestation_sha256="6" * 64,
    )
    assert handoff["producer_path"] == plan["producer_path"]
    assert handoff["producer_sha256"] == plan["producer_sha256"]
    assert handoff["root_applier_sha256"] == "3" * 64
    assert handoff["projections"] == plan["projections"]
    assert handoff["projection_count"] == controller.EXPECTED_PROJECTION_COUNT
    assert handoff["root_candidates"] == plan["root_candidates"]
    assert handoff["delete_scope"] == "attested_finite_root_candidate_prefix_only"
    assert handoff["target_broadening_allowed"] is False
    assert handoff["candidate_roots_removed"] is False
    assert handoff["runtime_removed"] is False
    assert handoff["receipts_removed"] is False


def test_root_applier_has_fixed_shebang_and_only_stdlib_imports() -> None:
    source_path = Path(root_applier.__file__)
    content = source_path.read_text(encoding="utf-8")
    assert content.startswith("#!/usr/bin/python3.12\n")
    tree = ast.parse(content)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            imported.add(str(node.module).split(".")[0])
    assert imported <= sys.stdlib_module_names
    assert "scripts" not in imported


def test_root_source_digest_rejects_symlink_and_detects_tamper(tmp_path: Path) -> None:
    source = tmp_path / "root.py"
    source.write_text("print('safe')\n", encoding="utf-8")
    source.chmod(0o755)
    first = root_applier._source_digest(source, expected_uid=os.getuid())
    alias = tmp_path / "alias.py"
    alias.symlink_to(source)
    with pytest.raises(RuntimeError, match="root_path_invalid"):
        root_applier._source_digest(alias, expected_uid=os.getuid())
    source.write_text("print('changed')\n", encoding="utf-8")
    source.chmod(0o755)
    second = root_applier._source_digest(source, expected_uid=os.getuid())
    assert first != second


def test_root_json_reader_rejects_symlink_and_exposes_exact_digest(tmp_path: Path) -> None:
    receipt = tmp_path / "handoff.json"
    content = b'{"schema":"test"}\n'
    receipt.write_bytes(content)
    receipt.chmod(0o600)
    loaded, digest = root_applier._read_json(receipt, expected_uid=os.getuid())
    assert loaded == {"schema": "test"}
    assert digest == hashlib.sha256(content).hexdigest()
    alias = tmp_path / "handoff-link.json"
    alias.symlink_to(receipt)
    with pytest.raises(RuntimeError, match="root_path_invalid"):
        root_applier._read_json(alias, expected_uid=os.getuid())


def test_root_tree_manifest_detects_content_change(tmp_path: Path) -> None:
    target = tmp_path / "projection"
    uid = _tree(target)
    descriptor = os.open(
        target,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        first, _inodes, projection_sha, count, size, _journal = root_applier._tree_from_fd(
            descriptor, path=str(target), runtime_uid=uid
        )
    finally:
        os.close(descriptor)
    assert count == 1
    assert size == len(b"capacity\n")
    (target / "payload.txt").chmod(0o600)
    (target / "payload.txt").write_bytes(b"tampered\n")
    (target / "payload.txt").chmod(0o440)
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        second, _inodes, second_sha, _count, _size, _journal = root_applier._tree_from_fd(
            descriptor, path=str(target), runtime_uid=uid
        )
    finally:
        os.close(descriptor)
    assert first["manifest_sha256"] != second["manifest_sha256"]
    assert projection_sha != second_sha


def test_root_tree_and_unlink_reject_symlink_and_hardlink(tmp_path: Path) -> None:
    target = tmp_path / "projection"
    target.mkdir()
    payload = target / "payload.txt"
    payload.write_bytes(b"safe")
    payload.chmod(0o440)
    os.link(payload, target / "hardlink.txt")
    target.chmod(0o550)
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(RuntimeError, match="projection_identity_invalid"):
            root_applier._tree_from_fd(
                descriptor, path=str(target), runtime_uid=os.getuid()
            )
    finally:
        os.close(descriptor)

    symlink_tree = tmp_path / "symlink-projection"
    symlink_tree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    (symlink_tree / "escape").symlink_to(outside)
    symlink_tree.chmod(0o550)
    descriptor = os.open(symlink_tree, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(RuntimeError, match="projection_identity_invalid"):
            root_applier._unlink_contents(descriptor, runtime_uid=os.getuid())
    finally:
        os.close(descriptor)
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_root_projection_path_guard_rejects_candidate_root_target(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    descriptor = os.open(deploy, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(RuntimeError, match="projection_path_invalid"):
            root_applier._validate_projection(
                {
                    "candidate_root": str(deploy / "candidate-aaaaaaaa"),
                    "release_id": "a" * 40,
                    "path": str(deploy / "candidate-aaaaaaaa"),
                    "candidate_root_preserved": True,
                    "runtime_preserved": True,
                    "receipts_preserved": True,
                },
                deploy_descriptor=descriptor,
                deploy_root=deploy,
                operator_uid=os.getuid(),
                handoff_sha256="1" * 64,
                quarantine_descriptor=descriptor,
                quarantine_root=tmp_path / "quarantine",
            )
    finally:
        os.close(descriptor)


def test_root_docker_queries_use_fixed_binary_and_are_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(root_applier, "_validate_docker_binary", lambda: None)

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(stdout=b"", stderr=b"")

    monkeypatch.setattr(root_applier.subprocess, "run", run)
    root_applier._require_project_absent("ea-manfred-candidate-aaaaaaaa")
    assert len(calls) == 3
    assert all(call[:3] == ["/usr/bin/docker", "--host", root_applier.DOCKER_HOST] for call in calls)
    assert [call[3] for call in calls] == ["container", "network", "volume"]
    assert all("prune" not in call and "rm" not in call for call in calls)


def test_root_applier_exact_projection_count_is_frozen() -> None:
    assert root_applier.EXPECTED_PROJECTION_COUNT == 26
    assert controller.EXPECTED_PROJECTION_COUNT == 26
    assert root_applier.MAX_PROJECTIONS >= root_applier.EXPECTED_PROJECTION_COUNT


def test_live_api_discovery_uses_exact_service_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def lines(argv: list[str], *, home: Path) -> list[str]:
        calls.append(argv)
        return ["a" * 64]

    monkeypatch.setattr(controller, "_docker_filtered_lines", lines)
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_args, **_kwargs: json.dumps(
            [{"Image": f"sha256:{'b' * 64}"}]
        ).encode(),
    )
    protected = controller._protected_image_ids(home=Path("/tmp"), explicit=[])
    assert protected == {f"sha256:{'b' * 64}"}
    assert calls == [
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=ea",
            "--filter",
            "label=com.docker.compose.service=ea-api",
        ]
    ]


def test_active_tool_matching_is_exact_not_substring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = tmp_path / "12345"
    proc.mkdir()
    (proc / "cmdline").write_bytes(b"/usr/bin/npm\0start\0chapterr\0")
    entry = SimpleNamespace(name="12345", path=str(proc))
    real_scandir = controller.os.scandir
    monkeypatch.setattr(
        controller.os,
        "scandir",
        lambda path: [entry] if str(path) == "/proc" else real_scandir(path),
    )
    assert controller._active_tool_processes(os.getuid(), {"pip", "npx"}) == []
    (proc / "cmdline").write_bytes(b"/usr/bin/npx\0install\0")
    assert controller._active_tool_processes(os.getuid(), {"pip", "npx"}) == [12345]


def _vscode_layout(home: Path) -> tuple[Path, Path]:
    servers = home / ".vscode-server/cli/servers"
    servers.mkdir(parents=True)
    servers.parent.chmod(0o700)
    servers.chmod(0o775)
    (servers / "lru.json").write_text("{}\n", encoding="utf-8")
    (servers / "lru.json").chmod(0o644)
    active = servers / f"Stable-{'a' * 40}"
    inactive = servers / f"Stable-{'b' * 40}"
    active.mkdir()
    inactive.mkdir()
    return active, inactive


def test_vscode_lru_metadata_is_allowlisted_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, inactive = _vscode_layout(tmp_path)
    monkeypatch.setattr(
        controller,
        "_process_references",
        lambda path, **_kwargs: [{"pid": 1}] if path == active else [],
    )
    monkeypatch.setattr(
        controller,
        "_tree_evidence",
        lambda path, **_kwargs: controller.TreeEvidence(
            path=str(path),
            exists=True,
            device=inactive.stat().st_dev,
            inode=2,
            mode=0o700,
            uid=os.getuid(),
            gid=os.getgid(),
            file_count=1,
            apparent_bytes=1,
            allocated_bytes=4096,
            manifest_sha256="a" * 64,
        ),
    )
    result = controller._vscode_evidence(
        home=tmp_path,
        uid=os.getuid(),
        process_inventory=_complete_process_inventory(),
    )
    assert result["inactive_server"] == inactive.name
    assert result["preserved_metadata_entries"] == [
        {
            "name": "lru.json",
            "mode": 0o644,
            "uid": os.getuid(),
            "gid": os.getgid(),
            "nlink": 1,
            "size_bytes": 3,
            "content_in_receipt": False,
            "preserved": True,
        }
    ]


@pytest.mark.parametrize("variant", ["symlink", "mode", "extra"])
def test_vscode_metadata_allowlist_fails_closed(
    variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, _inactive = _vscode_layout(tmp_path)
    servers = active.parent
    lru = servers / "lru.json"
    if variant == "symlink":
        lru.unlink()
        outside = tmp_path / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        lru.symlink_to(outside)
    elif variant == "mode":
        lru.chmod(0o600)
    else:
        (servers / "unexpected.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    with pytest.raises(RuntimeError):
        controller._vscode_evidence(
            home=tmp_path,
            uid=os.getuid(),
            process_inventory=_complete_process_inventory(),
        )


def test_redacted_plan_probe_exposes_no_raw_paths_or_image_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {
        "plan_sha256": "1" * 64,
        "root_free_bytes_before": 1,
        "target_root_free_bytes": 2,
        "required_reclaim_bytes": 1,
        "user_eligible_reclaim_floor_bytes": 1,
        "root_revalidation_reclaim_floor_bytes": 1,
        "root_candidate_reclaim_floor_bytes": 1,
        "root_candidate_count": 1,
        "unsafe_temp_candidate_exclusion_count": 0,
        "root_attestation_required_before_user_mutation": True,
        "eligible_reclaim_floor_bytes": 2,
        "eligible_capacity_deficit_bytes": 0,
        "eligible_capacity_sufficient": True,
        "controller_process_inventory": {
            **_complete_process_inventory(),
            "status": "degraded",
            "unreadable_process_count": 2,
        },
        "unavailable_user_actions": {
            "cache_count": 4,
            "vscode_count": 1,
            "total_count": 5,
            "identities_included": False,
        },
        "projections": [{"path": "/secret/projection"}],
        "protected_image_ids": [f"sha256:{'a' * 64}"],
        "vscode": {
            "journal_entry_count": 2,
            "journal_payload_bytes": 300,
            "journal_entries_sha256": "b" * 64,
            "eligible": False,
        },
    }
    monkeypatch.setattr(controller, "discover_plan", lambda **_kwargs: plan)
    result = controller.redacted_plan_probe(
        source_root=Path("/secret/source"),
        deploy_root=Path("/secret/deploy"),
        registry_path=Path("/secret/registry"),
    )
    encoded = json.dumps(result)
    assert result["status"] == "pass"
    assert result["identities_redacted"] is True
    assert "/secret" not in encoded
    assert f"sha256:{'a' * 64}" not in encoded


def test_safe_environment_and_resolution_ignore_inherited_docker_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-production")
    monkeypatch.setenv("DOCKER_HOST", "tcp://host:2375")
    monkeypatch.setenv("PATH", "/untrusted")
    environment = controller._safe_environment(Path("/home/operator"))
    assert environment == {
        "HOME": "/home/operator",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "DOCKER_HOST": controller.LOCAL_DOCKER_HOST,
    }
    assert controller._resolved_command(("docker", "image", "ls"))[:3] == (
        controller.DOCKER_BINARY,
        "--host",
        controller.LOCAL_DOCKER_HOST,
    )


def test_plan_rejects_duplicate_projection_identities() -> None:
    plan = _plan_scope()
    plan["projections"] = [dict(row) for row in plan["projections"]]
    plan["projections"][1]["release_id"] = plan["projections"][0]["release_id"]
    with pytest.raises(RuntimeError, match="(plan|root_candidate)_scope_invalid"):
        controller._validate_plan(
            controller._with_plan_digest(plan), producer_sha256="1" * 64
        )


def test_cache_path_is_revalidated_immediately_before_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = controller.TreeEvidence(
        "/cache", True, 1, 2, 0o700, os.getuid(), os.getgid(), 1, 1, 4096, "a" * 64
    )
    monkeypatch.setattr(controller, "_tree_evidence", lambda *_a, **_k: expected)
    monkeypatch.setattr(controller, "_active_tool_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    monkeypatch.setattr(
        controller,
        "_official_cache_paths",
        lambda **_kwargs: {"pip_cache": Path("/different")},
    )
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_a, **_k: pytest.fail("clear must not execute after path drift"),
    )
    with pytest.raises(RuntimeError, match="cache_path_changed"):
        controller._apply_caches(
            {
                "caches": [
                    {
                        "name": "pip_cache",
                        "eligible": True,
                        "tree": expected.as_dict(),
                        "clear_argv": [
                                controller.PYTHON_EXECUTABLE,
                                "-I",
                                "-m",
                            "pip",
                            "cache",
                            "purge",
                        ],
                    }
                ]
            },
            home=Path("/home/operator"),
            uid=os.getuid(),
        )


def test_pip_discovery_and_clear_are_isolated_with_pinned_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path("/home/operator")
    commands: list[tuple[str, ...]] = []

    def run(argv: object, **_kwargs: object) -> bytes:
        command = tuple(str(value) for value in argv)
        commands.append(command)
        if command[:2] == ("dotnet", "nuget"):
            return (
                f"http-cache: {home}/.local/share/NuGet/http-cache\n"
                f"global-packages: {home}/.nuget/packages\n"
            ).encode()
        if command[:2] == ("npm", "config"):
            return f"{home}/.npm\n".encode()
        if "pip" in command:
            return f"{home}/.cache/pip\n".encode()
        raise AssertionError(command)

    monkeypatch.setattr(controller, "_bounded_run", run)
    controller._official_cache_paths(home=home)
    pip_commands = [command for command in commands if "pip" in command]
    assert pip_commands == [
        (
            controller.PYTHON_EXECUTABLE,
            "-I",
            "-m",
            "pip",
            "cache",
            "dir",
        )
    ]
    assert controller._mutation_command_allowed(
        (
            controller.PYTHON_EXECUTABLE,
            "-I",
            "-m",
            "pip",
            "cache",
            "purge",
        )
    )


def test_mutation_helper_drift_blocks_apply_before_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _user_apply_plan()
    intent = tmp_path / "intent.json"
    intent.write_text("{}\n", encoding="utf-8")
    intent.chmod(0o600)
    actions: list[str] = []
    _mock_user_apply(
        monkeypatch,
        plan=plan,
        home=tmp_path,
        free_values=(),
        action_counter=actions,
        validate_root=False,
    )
    changed = [dict(row) for row in list(plan["mutation_helpers"])]
    changed[0]["sha256"] = "f" * 64
    monkeypatch.setattr(controller, "_mutation_helper_evidence", lambda **_k: changed)
    user = tmp_path / "user.json"
    handoff = tmp_path / "handoff.json"
    with pytest.raises(RuntimeError, match="toolchain_changed"):
        controller.apply_user(
            intent_path=intent,
            user_receipt_path=user,
            root_handoff_path=handoff,
            root_receipt_path=tmp_path / "root.json",
        )
    assert actions == []
    assert not user.exists() and not handoff.exists()


def test_inline_installer_is_literal_hash_bound_and_sudo_uid_bound() -> None:
    code = controller.ROOT_INSTALLER_CODE
    evidence = controller._root_installer_evidence()
    assert evidence["code_sha256"] == hashlib.sha256(code.encode()).hexdigest()
    assert 'os.environ.get("SUDO_UID"' in code
    assert 'os.execve(\n    "/usr/bin/python3.12"' in code
    assert "O_NOFOLLOW" in code and "O_EXCL" in code
    assert "os.fsync(target_descriptor)" in code
    assert "os.fsync(stage_descriptor)" in code
    assert evidence["literal_argv_only"] is True
    assert evidence["unreviewed_command_string_authenticated"] is False


def test_root_installer_argv_uses_fixed_interpreter_and_no_shell() -> None:
    plan = _plan_scope()
    handoff = {"root_installer_sha256": controller.ROOT_INSTALLER_SHA256,
               "handoff_source_path": "/tmp/handoff.json",
               "user_receipt_path": "/tmp/user.json"}
    argv = controller._root_installer_argv(
        uid=max(1, os.getuid()),
        plan=plan,
        handoff=handoff,
        handoff_evidence={"path": "/tmp/handoff.json", "size_bytes": 10, "sha256": "4" * 64},
        user_receipt_evidence={"path": "/tmp/user.json", "size_bytes": 10, "sha256": "5" * 64},
        root_receipt_path=Path("/var/lib/ea/manfred-root-receipts/manfred-capacity-test.v2.json"),
    )
    assert argv[:4] == [controller.SUDO_BINARY, "--", controller.PYTHON_EXECUTABLE, "-I"]
    assert argv[4:6] == ["-c", controller.ROOT_INSTALLER_CODE]
    assert not any(value in argv for value in ("sh", "bash", "eval"))


def test_root_projection_prefix_stops_and_latches_at_target() -> None:
    rows = [
        {"path": f"/p/{index}", "tree": {"allocated_bytes": index + 1}}
        for index in range(4)
    ]
    removed: list[str] = []
    free = iter((0, root_applier.TARGET_ROOT_FREE_BYTES))
    actions = root_applier._bounded_projection_actions(
        rows,
        target=root_applier.TARGET_ROOT_FREE_BYTES,
        free_bytes=lambda: next(free),
        remove_projection=lambda row: removed.append(str(row["path"]))
        or {"path": row["path"], "status": "removed", "allocated_bytes": 1},
    )
    assert removed == ["/p/0"]
    assert [row["status"] for row in actions] == [
        "removed",
        "preserved_capacity_ready",
        "preserved_capacity_ready",
        "preserved_capacity_ready",
    ]


def test_root_projection_prefix_is_zero_delete_when_already_ready() -> None:
    rows = [{"path": "/p/0", "tree": {"allocated_bytes": 1}}]
    actions = root_applier._bounded_projection_actions(
        rows,
        target=root_applier.TARGET_ROOT_FREE_BYTES,
        free_bytes=lambda: root_applier.TARGET_ROOT_FREE_BYTES,
        remove_projection=lambda _row: pytest.fail("must not delete"),
    )
    assert actions[0]["status"] == "preserved_capacity_ready"
    with pytest.raises(RuntimeError, match="target_invalid"):
        root_applier._bounded_projection_actions(
            rows,
            target=root_applier.TARGET_ROOT_FREE_BYTES + 1,
            free_bytes=lambda: 0,
            remove_projection=lambda row: row,
        )


@pytest.mark.parametrize("relation", ["direct", "ancestor", "descendant"])
def test_global_container_mount_guard_rejects_path_overlap(
    relation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    if relation == "direct":
        source = target
    elif relation == "ancestor":
        source = tmp_path
    else:
        source = target / "nested"
        source.mkdir()
    identifier = "a" * 64
    queries: list[list[str]] = []

    def lines(argv: list[str]) -> list[str]:
        queries.append(argv)
        return [identifier]

    monkeypatch.setattr(root_applier, "_docker_lines", lines)
    monkeypatch.setattr(
        root_applier,
        "_docker_json",
        lambda _argv: [
            {"Id": identifier, "Mounts": [{"Type": "bind", "Source": str(source)}]}
        ],
    )
    with pytest.raises(RuntimeError, match="projection_container_mounted"):
        root_applier._require_no_container_mount_references(
            (str(target),), projection_inodes=set()
        )
    assert queries == [["container", "ls", "--all", "--quiet", "--no-trunc"]]


def test_global_container_mount_guard_rejects_symlink_and_inode_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    real_source = tmp_path / "source"
    real_source.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_source, target_is_directory=True)
    identifier = "b" * 64
    monkeypatch.setattr(root_applier, "_docker_lines", lambda _argv: [identifier])
    mounts = [{"Type": "bind", "Source": str(alias)}]
    monkeypatch.setattr(
        root_applier,
        "_docker_json",
        lambda _argv: [{"Id": identifier, "Mounts": mounts}],
    )
    with pytest.raises(RuntimeError, match="container_inventory_invalid"):
        root_applier._require_no_container_mount_references(
            (str(target),), projection_inodes=set()
        )
    mounts[:] = [{"Type": "bind", "Source": str(real_source)}]
    source_status = real_source.stat()
    with pytest.raises(RuntimeError, match="projection_container_mounted"):
        root_applier._require_no_container_mount_references(
            (str(target),),
            projection_inodes={(source_status.st_dev, source_status.st_ino)},
        )


def test_global_container_mount_inventory_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        root_applier,
        "_docker_lines",
        lambda _argv: [f"{index:064x}" for index in range(root_applier.MAX_CONTAINERS + 1)],
    )
    with pytest.raises(RuntimeError, match="container_inventory_invalid"):
        root_applier._require_no_container_mount_references(
            ("/safe/target",), projection_inodes=set()
        )


def test_host_mount_guard_rejects_nested_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"31 22 0:27 / /safe/target/nested rw - tmpfs tmpfs rw\n"
    real_open = builtins.open

    def fake_open(path: object, *args: object, **kwargs: object) -> object:
        if str(path) == "/proc/self/mountinfo":
            return io.BytesIO(content)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    with pytest.raises(RuntimeError, match="projection_nested_mount"):
        root_applier._require_no_nested_host_mounts(("/safe/target",))


def test_unlink_rejects_cross_device_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "projection"
    uid = _tree(target)
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    original_stat = root_applier.os.stat

    def changed_stat(path: object, *args: object, **kwargs: object) -> object:
        observed = original_stat(path, *args, **kwargs)
        if path == "payload.txt" and kwargs.get("dir_fd") == descriptor:
            return SimpleNamespace(st_dev=observed.st_dev + 1)
        return observed

    monkeypatch.setattr(root_applier.os, "stat", changed_stat)
    try:
        with pytest.raises(RuntimeError, match="projection_device_changed"):
            root_applier._unlink_contents(descriptor, runtime_uid=uid)
    finally:
        os.close(descriptor)


class _Scan:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.rows)

    def __enter__(self):  # type: ignore[no-untyped-def]
        return iter(self.rows)

    def __exit__(self, *_args: object) -> None:
        return None


@pytest.mark.parametrize("module", [controller, root_applier])
def test_process_fd_inventory_over_cap_fails_closed(
    module: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = tmp_path / "424242"
    (process / "fd").mkdir(parents=True)
    entry = SimpleNamespace(name="424242", path=str(process))
    descriptors = [SimpleNamespace(path=f"/missing/{index}") for index in range(4097)]
    original = module.os.scandir

    def fake_scandir(path: object) -> object:
        if str(path) == "/proc":
            return _Scan([entry])
        if str(path) == str(process / "fd"):
            return _Scan(descriptors)
        return original(path)

    monkeypatch.setattr(module.os, "scandir", fake_scandir)
    if module is controller:
        with pytest.raises(RuntimeError, match="fd_inventory_unbounded"):
            controller._process_references(Path("/target"), uid=os.getuid())
    else:
        with pytest.raises(RuntimeError, match="fd_inventory_unbounded"):
            root_applier._process_references(paths=("/target",), inodes=set())


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO, errno.EBADF])
def test_controller_process_inventory_rejects_nonvanished_errors(
    error_number: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = tmp_path / "515151"
    process.mkdir()
    entry = SimpleNamespace(name="515151", path=str(process))
    original_scandir = controller.os.scandir
    original_read = controller._bounded_process_read

    def fake_scandir(path: object) -> object:
        return _Scan([entry]) if str(path) == "/proc" else original_scandir(path)

    def unreadable(path: Path, *, maximum: int) -> bytes:
        if path == process / "cmdline":
            raise OSError(error_number, "injected process read failure")
        return original_read(path, maximum=maximum)

    monkeypatch.setattr(controller.os, "scandir", fake_scandir)
    monkeypatch.setattr(controller, "_bounded_process_read", unreadable)
    with pytest.raises(RuntimeError, match="process_inventory_invalid"):
        controller._process_references(Path("/target"), uid=os.getuid())
    with pytest.raises(RuntimeError, match="active_tool_inventory_invalid"):
        controller._active_tool_processes(os.getuid(), {"pip"})


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO, errno.EBADF])
def test_root_process_inventory_rejects_nonvanished_errors(
    error_number: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = tmp_path / "616161"
    (process / "fd").mkdir(parents=True)
    entry = SimpleNamespace(name="616161", path=str(process))
    original_scandir = root_applier.os.scandir
    real_open = builtins.open

    def fake_scandir(path: object) -> object:
        return _Scan([entry]) if str(path) == "/proc" else original_scandir(path)

    def unreadable(path: object, *args: object, **kwargs: object) -> object:
        if str(path) == str(process / "cmdline"):
            raise OSError(error_number, "injected process read failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(root_applier.os, "scandir", fake_scandir)
    monkeypatch.setattr(builtins, "open", unreadable)
    with pytest.raises(RuntimeError, match="root_process_inventory_invalid"):
        root_applier._process_references(paths=("/target",), inodes=set())


def test_unreadable_active_tool_inventory_blocks_cache_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = controller.TreeEvidence(
        "/cache", True, 1, 2, 0o700, os.getuid(), os.getgid(), 1, 1, 4096, "a" * 64
    )
    monkeypatch.setattr(controller, "_tree_evidence", lambda *_a, **_k: expected)
    monkeypatch.setattr(
        controller,
        "_active_tool_processes",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("manfred_capacity_active_tool_inventory_invalid")
        ),
    )
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_a, **_k: pytest.fail("cache mutation must remain blocked"),
    )
    with pytest.raises(RuntimeError, match="active_tool_inventory_invalid"):
        controller._apply_caches(
            {
                "caches": [
                    {
                        "name": "pip_cache",
                        "eligible": True,
                        "tree": expected.as_dict(),
                        "clear_argv": [
                            controller.PYTHON_EXECUTABLE,
                            "-I",
                            "-m",
                            "pip",
                            "cache",
                            "purge",
                        ],
                    }
                ]
            },
            home=Path("/home/operator"),
            uid=os.getuid(),
        )


def _rootish_status(observed: os.stat_result, *, nlink: int | None = None) -> object:
    return SimpleNamespace(
        st_mode=observed.st_mode,
        st_uid=0,
        st_gid=0,
        st_nlink=observed.st_nlink if nlink is None else nlink,
        st_size=observed.st_size,
        st_dev=observed.st_dev,
        st_ino=observed.st_ino,
        st_mtime_ns=observed.st_mtime_ns,
        st_ctime_ns=observed.st_ctime_ns,
    )


def test_root_stage_requires_exact_private_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = tmp_path / "ea-manfred-capacity.Abcd1234"
    stage.mkdir(mode=0o700)
    paths = {name: stage / name for name in ("applier.py", "controller.py", "handoff.json", "user-receipt.json")}
    for path in paths.values():
        path.write_bytes(b"x")
    paths["applier.py"].chmod(0o500)
    for name in ("controller.py", "handoff.json", "user-receipt.json"):
        paths[name].chmod(0o400)
    original_stat = Path.stat

    def fake_stat(path: Path, *args: object, **kwargs: object) -> object:
        observed = original_stat(path, *args, **kwargs)
        return _rootish_status(observed) if path == stage else observed

    monkeypatch.setattr(root_applier, "ROOT_STAGE_PARENT", tmp_path)
    monkeypatch.setattr(root_applier, "__file__", str(paths["applier.py"]))
    monkeypatch.setattr(Path, "stat", fake_stat)
    assert root_applier._validate_root_stage(
        stage_path=stage,
        applier_path=paths["applier.py"],
        controller_path=paths["controller.py"],
        handoff_path=paths["handoff.json"],
        user_receipt_path=paths["user-receipt.json"],
    ) == stage
    (stage / "extra").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="stage_invalid"):
        root_applier._validate_root_stage(
            stage_path=stage,
            applier_path=paths["applier.py"],
            controller_path=paths["controller.py"],
            handoff_path=paths["handoff.json"],
            user_receipt_path=paths["user-receipt.json"],
        )


def test_staged_evidence_rejects_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = tmp_path / "controller.py"
    staged.write_bytes(b"trusted")
    staged.chmod(0o400)
    original_fstat = root_applier.os.fstat
    monkeypatch.setattr(
        root_applier.os,
        "fstat",
        lambda fd: _rootish_status(original_fstat(fd)),
    )
    digest = hashlib.sha256(b"trusted").hexdigest()
    _content, evidence = root_applier._staged_evidence(
        staged, mode=0o400, expected_sha256=digest
    )
    assert evidence["sha256"] == digest
    with pytest.raises(RuntimeError, match="staged_digest_invalid"):
        root_applier._staged_evidence(
            staged, mode=0o400, expected_sha256="0" * 64
        )


def test_read_fd_detects_change_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"content")
    descriptor = os.open(path, os.O_RDONLY)
    observed = os.fstat(descriptor)
    sequence = iter(
        (
            observed,
            SimpleNamespace(
                st_dev=observed.st_dev,
                st_ino=observed.st_ino,
                st_size=observed.st_size,
                st_mtime_ns=observed.st_mtime_ns + 1,
            ),
        )
    )
    monkeypatch.setattr(root_applier.os, "fstat", lambda _fd: next(sequence))
    try:
        with pytest.raises(RuntimeError, match="file_changed"):
            root_applier._read_fd_all(descriptor, maximum=1024)
    finally:
        os.close(descriptor)


def _user_apply_plan() -> dict[str, object]:
    return {
        **_plan_scope(),
        "plan_sha256": "4" * 64,
        "eligible_capacity_sufficient": True,
        "builder": _builder(records=1, floor=100, digest="9" * 64),
        "caches": [],
        "vscode": {
            "eligible": True,
            "inactive_tree": {
                "path": "/home/operator/.vscode-server/cli/servers/Stable-test",
                "allocated_bytes": 4096,
            },
            "journal_entry_count": 1,
            "journal_payload_bytes": 100,
            "journal_entries_sha256": "8" * 64,
        },
    }


def _mock_user_apply(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: dict[str, object],
    home: Path,
    free_values: tuple[int, ...],
    action_counter: list[str],
    validate_root: bool,
) -> None:
    uid = max(1, os.getuid())

    @contextlib.contextmanager
    def capacity_lock(_uid: int):
        yield {"exclusive": True}

    monkeypatch.setattr(controller, "_operator_identity", lambda *_a, **_k: (uid, home))
    monkeypatch.setattr(controller, "_capacity_lock", capacity_lock)
    root_attestation_path = home / "root-attestation.v2.json"
    root_attestation_path.write_text("{}\n", encoding="utf-8")
    root_attestation = {
        "authorized_root_action_ids": [
            str(dict(row)["action_id"])
            for row in list(plan.get("root_candidates") or [])
        ]
    }
    monkeypatch.setattr(
        controller,
        "_load_intent",
        lambda _path, **_kwargs: (
            {
                "schema": controller.INTENT_SCHEMA,
                "root_attestation": root_attestation,
                "root_attestation_path": str(root_attestation_path),
                "root_attestation_sha256": "6" * 64,
            },
            "5" * 64,
            plan,
        ),
    )
    monkeypatch.setattr(controller, "_root_applier_evidence", lambda **_k: plan["root_applier"])
    monkeypatch.setattr(controller, "_controller_evidence", lambda **_k: plan["producer"])
    monkeypatch.setattr(
        controller,
        "_mutation_helper_evidence",
        lambda **_k: plan["mutation_helpers"],
    )
    monkeypatch.setattr(controller, "_pinned_toolchain_evidence", lambda: plan["pinned_toolchain"])
    values = iter(free_values)
    monkeypatch.setattr(controller, "_root_free_bytes", lambda: next(values))

    def action(name: str, value: object):
        def run(*_args: object, **_kwargs: object) -> object:
            action_counter.append(name)
            return value

        return run

    monkeypatch.setattr(controller, "_apply_builder", action("builder", {"status": "ok"}))
    monkeypatch.setattr(controller, "_apply_caches", action("caches", []))
    monkeypatch.setattr(controller, "_apply_vscode", action("vscode", {"status": "ok"}))
    monkeypatch.setattr(controller, "_apply_candidate", action("candidate", {"status": "ok"}))
    if validate_root:
        monkeypatch.setattr(
            controller,
            "_validate_root_receipt_destination",
            lambda path, **_kwargs: path.absolute(),
        )
    else:
        monkeypatch.setattr(
            controller,
            "_validate_root_receipt_destination",
            lambda *_a, **_k: pytest.fail("no-root terminal path must not validate root output"),
        )


def test_apply_user_terminal_path_creates_no_root_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _user_apply_plan()
    intent = tmp_path / "intent.json"
    intent.write_text("{}\n", encoding="utf-8")
    intent.chmod(0o600)
    actions: list[str] = []
    _mock_user_apply(
        monkeypatch,
        plan=plan,
        home=tmp_path,
        free_values=(0, controller.TARGET_ROOT_FREE_BYTES, controller.TARGET_ROOT_FREE_BYTES),
        action_counter=actions,
        validate_root=False,
    )
    user = tmp_path / "user.json"
    handoff = tmp_path / "handoff.json"
    result = controller.apply_user(
        intent_path=intent,
        user_receipt_path=user,
        root_handoff_path=handoff,
        root_receipt_path=Path("/invalid/no-root-receipt.json"),
    )
    assert result["status"] == "capacity_ready_no_root_actions"
    assert result["root_apply_argv"] == []
    assert result["projections_preserved_count"] == controller.EXPECTED_PROJECTION_COUNT
    assert not handoff.exists()
    persisted = json.loads(user.read_text(encoding="utf-8"))
    assert persisted["root_installer"] is None
    assert controller.ROOT_INSTALLER_CODE not in user.read_text(encoding="utf-8")


def test_user_action_latch_already_ready_performs_zero_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _user_apply_plan()
    plan["caches"] = [
        {
            "name": name,
            "tree": {"allocated_bytes": 100},
            "clear_argv": [],
            "eligible": True,
        }
        for name in ("first", "second")
    ]
    readings = iter(
        (controller.TARGET_ROOT_FREE_BYTES, controller.TARGET_ROOT_FREE_BYTES)
    )
    monkeypatch.setattr(controller, "_root_free_bytes", lambda: next(readings))
    for name in ("_apply_builder", "_apply_caches", "_apply_vscode", "_apply_candidate"):
        monkeypatch.setattr(
            controller,
            name,
            lambda *_a, _name=name, **_k: pytest.fail(f"{_name} must not mutate"),
        )
    builder, caches, vscode, candidate, before, after, preserved, unavailable = (
        controller._apply_user_actions(plan, home=Path("/home/operator"), uid=os.getuid())
    )
    assert before == after == controller.TARGET_ROOT_FREE_BYTES
    assert builder["status"] == "preserved_capacity_ready"
    assert [row["status"] for row in caches] == [
        "preserved_capacity_ready",
        "preserved_capacity_ready",
    ]
    assert vscode["status"] == candidate["status"] == "preserved_capacity_ready"
    assert preserved == [
        "builder",
        "cache:first",
        "cache:second",
        "vscode",
        "candidate",
    ]
    assert unavailable == []


def test_user_action_latch_executes_only_exact_early_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _user_apply_plan()
    plan["caches"] = [
        {
            "name": name,
            "tree": {"allocated_bytes": 100},
            "clear_argv": [],
            "eligible": True,
        }
        for name in ("first", "second", "third")
    ]
    readings = iter(
        (
            0,
            0,
            0,
            0,
            controller.TARGET_ROOT_FREE_BYTES,
            controller.TARGET_ROOT_FREE_BYTES,
        )
    )
    monkeypatch.setattr(controller, "_root_free_bytes", lambda: next(readings))
    executed: list[str] = []
    monkeypatch.setattr(
        controller,
        "_apply_builder",
        lambda *_a, **_k: executed.append("builder") or {"status": "pruned"},
    )

    def apply_cache(single: dict[str, object], **_kwargs: object) -> list[dict[str, object]]:
        name = str(dict(list(single["caches"])[0])["name"])
        executed.append(f"cache:{name}")
        return [{"name": name, "status": "cleared", "mutation_command_count": 1}]

    monkeypatch.setattr(controller, "_apply_caches", apply_cache)
    monkeypatch.setattr(
        controller,
        "_apply_vscode",
        lambda *_a, **_k: pytest.fail("vscode must be preserved"),
    )
    monkeypatch.setattr(
        controller,
        "_apply_candidate",
        lambda *_a, **_k: pytest.fail("candidate must be preserved"),
    )
    (
        _builder_result,
        caches,
        vscode,
        candidate,
        _before,
        after,
        preserved,
        unavailable,
    ) = (
        controller._apply_user_actions(plan, home=Path("/home/operator"), uid=os.getuid())
    )
    assert executed == ["builder", "cache:first"]
    assert [row["status"] for row in caches] == [
        "cleared",
        "preserved_capacity_ready",
        "preserved_capacity_ready",
    ]
    assert vscode["status"] == candidate["status"] == "preserved_capacity_ready"
    assert preserved == ["cache:second", "cache:third", "vscode", "candidate"]
    assert unavailable == []
    assert after == controller.TARGET_ROOT_FREE_BYTES


def test_capacity_preflight_latches_after_skipped_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _user_apply_plan()
    plan["caches"] = [
        {
            "name": "unavailable",
            "tree": {"allocated_bytes": 100},
            "clear_argv": [],
            "eligible": False,
            "availability": "process_inventory_unavailable",
        },
        {
            "name": "next",
            "tree": {"allocated_bytes": 100},
            "clear_argv": [],
            "eligible": True,
        },
    ]
    readings = iter(
        (
            0,
            0,
            0,
            controller.TARGET_ROOT_FREE_BYTES,
            controller.TARGET_ROOT_FREE_BYTES,
        )
    )
    monkeypatch.setattr(controller, "_root_free_bytes", lambda: next(readings))
    executed: list[str] = []
    monkeypatch.setattr(
        controller,
        "_apply_builder",
        lambda *_a, **_k: executed.append("builder") or {"status": "pruned"},
    )
    for name in ("_apply_caches", "_apply_vscode", "_apply_candidate"):
        monkeypatch.setattr(
            controller,
            name,
            lambda *_a, _name=name, **_k: pytest.fail(
                f"{_name} must be preserved after capacity preflight"
            ),
        )
    (
        _builder_result,
        caches,
        vscode,
        candidate,
        _before,
        after,
        preserved,
        unavailable,
    ) = controller._apply_user_actions(
        plan, home=Path("/home/operator"), uid=os.getuid()
    )
    assert executed == ["builder"]
    assert [row["status"] for row in caches] == [
        "preserved_process_inventory_unavailable",
        "preserved_capacity_ready",
    ]
    assert vscode["status"] == candidate["status"] == "preserved_capacity_ready"
    assert preserved == ["cache:next", "vscode", "candidate"]
    assert unavailable == ["cache:unavailable"]
    assert after == controller.TARGET_ROOT_FREE_BYTES


def test_capacity_preflight_latches_after_skipped_vscode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _user_apply_plan()
    plan["caches"] = []
    plan["vscode"] = {
        "eligible": False,
        "availability": "process_inventory_unavailable",
        "inactive_tree": None,
    }
    readings = iter(
        (
            0,
            0,
            0,
            controller.TARGET_ROOT_FREE_BYTES,
            controller.TARGET_ROOT_FREE_BYTES,
        )
    )
    monkeypatch.setattr(controller, "_root_free_bytes", lambda: next(readings))
    executed: list[str] = []
    monkeypatch.setattr(
        controller,
        "_apply_builder",
        lambda *_a, **_k: executed.append("builder") or {"status": "pruned"},
    )
    monkeypatch.setattr(
        controller,
        "_apply_candidate",
        lambda *_a, **_k: pytest.fail(
            "candidate must be preserved after skipped VSCode preflight"
        ),
    )
    (
        _builder_result,
        _caches,
        vscode,
        candidate,
        _before,
        after,
        preserved,
        unavailable,
    ) = controller._apply_user_actions(
        plan, home=Path("/home/operator"), uid=os.getuid()
    )
    assert executed == ["builder"]
    assert vscode["status"] == "preserved_process_inventory_unavailable"
    assert candidate["status"] == "preserved_capacity_ready"
    assert preserved == ["candidate"]
    assert unavailable == ["vscode"]
    assert after == controller.TARGET_ROOT_FREE_BYTES


def test_apply_user_drift_after_ready_writes_no_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _user_apply_plan()
    intent = tmp_path / "intent.json"
    intent.write_text("{}\n", encoding="utf-8")
    intent.chmod(0o600)
    actions: list[str] = []
    _mock_user_apply(
        monkeypatch,
        plan=plan,
        home=tmp_path,
        free_values=(
            controller.TARGET_ROOT_FREE_BYTES,
            controller.TARGET_ROOT_FREE_BYTES - 1,
        ),
        action_counter=actions,
        validate_root=False,
    )
    user = tmp_path / "user.json"
    handoff = tmp_path / "handoff.json"
    with pytest.raises(RuntimeError, match="drift_after_ready"):
        controller.apply_user(
            intent_path=intent,
            user_receipt_path=user,
            root_handoff_path=handoff,
            root_receipt_path=tmp_path / "unused-root.json",
        )
    assert actions == []
    assert not user.exists() and not handoff.exists()


def test_apply_user_handoff_and_receipt_resumes_are_hash_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _user_apply_plan()
    intent = tmp_path / "intent.json"
    intent.write_text("{}\n", encoding="utf-8")
    intent.chmod(0o600)
    user = tmp_path / "user.json"
    handoff = tmp_path / "handoff.json"
    root_receipt = tmp_path / "root-receipt.json"
    actions: list[str] = []
    _mock_user_apply(
        monkeypatch,
        plan=plan,
        home=tmp_path,
        free_values=(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        action_counter=actions,
        validate_root=True,
    )
    first = controller.apply_user(
        intent_path=intent,
        user_receipt_path=user,
        root_handoff_path=handoff,
        root_receipt_path=root_receipt,
    )
    first_handoff_sha = first["root_handoff_sha256"]
    persisted_text = user.read_text(encoding="utf-8")
    assert json.loads(persisted_text)["root_apply_argv"] is None
    assert controller.ROOT_INSTALLER_CODE not in persisted_text
    assert controller.ROOT_INSTALLER_CODE not in handoff.read_text(encoding="utf-8")
    assert first["root_apply_argv"][:4] == [
        controller.SUDO_BINARY,
        "--",
        controller.PYTHON_EXECUTABLE,
        "-I",
    ]

    # Simulate a crash after handoff creation but before user-receipt durability.
    user.unlink()
    second = controller.apply_user(
        intent_path=intent,
        user_receipt_path=user,
        root_handoff_path=handoff,
        root_receipt_path=root_receipt,
    )
    assert second["root_handoff_sha256"] == first_handoff_sha
    count_after_recovery = len(actions)
    resumed = controller.apply_user(
        intent_path=intent,
        user_receipt_path=user,
        root_handoff_path=handoff,
        root_receipt_path=root_receipt,
    )
    assert resumed["resumed"] is True
    assert resumed["root_handoff_sha256"] == first_handoff_sha
    assert len(actions) == count_after_recovery


def _write_private(path: Path, payload: dict[str, object]) -> str:
    content = controller._json_bytes(payload)
    path.write_bytes(content)
    path.chmod(0o600)
    return hashlib.sha256(content).hexdigest()


def test_finalize_no_root_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = max(1, os.getuid())
    paths = [f"/projection/{index:02d}" for index in range(controller.EXPECTED_PROJECTION_COUNT)]
    root_candidates = [
        {"action_id": f"projection:{index:040x}", "path": path}
        for index, path in enumerate(paths)
    ]
    attestation_path = tmp_path / "root-attestation.v2.json"
    attestation_path.write_text("{}\n", encoding="utf-8")
    attestation = {"authorized_root_action_ids": []}
    intent_payload = {
        "schema": controller.INTENT_SCHEMA,
        "producer_sha256": "1" * 64,
        "plan_sha256": "2" * 64,
        "target_root_free_bytes": controller.TARGET_ROOT_FREE_BYTES,
        "plan": {
            "projections": [{"path": path} for path in paths],
            "root_candidates": root_candidates,
        },
        "root_attestation_path": str(attestation_path),
        "root_attestation_sha256": "9" * 64,
        "root_attestation": attestation,
        "root_attestation_required_before_user_mutation": True,
    }
    intent = tmp_path / "intent.json"
    intent_sha = _write_private(intent, intent_payload)
    user_payload = {
        "schema": controller.USER_RECEIPT_SCHEMA,
        "status": "capacity_ready_no_root_actions",
        "producer_sha256": "1" * 64,
        "intent_sha256": intent_sha,
        "plan_sha256": "2" * 64,
        "root_actions_performed": False,
        "target_broadened": False,
        "root_handoff_required": False,
        "root_handoff_path": None,
        "root_handoff_sha256": None,
        "root_receipt_path": None,
        "root_apply_argv": [],
        "root_apply_argv_persisted": True,
        "root_installer": None,
        "root_installer_sha256": None,
        "projection_deletion_authorized": False,
        "root_candidate_deletion_authorized": False,
        "projection_deletion_performed": False,
        "root_candidate_deletion_performed": False,
        "root_attestation_path": str(attestation_path),
        "root_attestation_sha256": "9" * 64,
        "projections_preserved_count": len(paths),
        "root_free_bytes_after": controller.TARGET_ROOT_FREE_BYTES,
    }
    user = tmp_path / "user.json"
    _write_private(user, user_payload)
    monkeypatch.setattr(controller, "_operator_identity", lambda: (uid, tmp_path))
    monkeypatch.setattr(
        controller, "_root_free_bytes", lambda: controller.TARGET_ROOT_FREE_BYTES
    )
    result = controller.finalize(
        intent_path=intent,
        user_receipt_path=user,
        root_receipt_path=None,
        completion_receipt_path=tmp_path / "completion.json",
    )
    assert result["status"] == "pass"
    assert result["root_stage"] == "not_required"
    assert result["projection_deletion_performed"] is False


def test_finalize_root_chain_rejects_action_reordering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = max(1, os.getuid())
    intended = [f"/projection/{index:02d}" for index in range(controller.EXPECTED_PROJECTION_COUNT)]
    root_candidates = [
        {"action_id": f"projection:{index:040x}", "path": path}
        for index, path in enumerate(intended)
    ]
    authorized_ids = [str(row["action_id"]) for row in root_candidates]
    attestation_path = tmp_path / "root-attestation.v2.json"
    attestation_path.write_text("{}\n", encoding="utf-8")
    attestation = {"authorized_root_action_ids": authorized_ids}
    plan = {
        "projections": [{"path": path} for path in intended],
        "root_candidates": root_candidates,
        "root_applier": {"sha256": "3" * 64},
        "root_installer": controller._root_installer_evidence(),
    }
    intent_payload = {
        "schema": controller.INTENT_SCHEMA,
        "producer_sha256": "1" * 64,
        "plan_sha256": "2" * 64,
        "target_root_free_bytes": controller.TARGET_ROOT_FREE_BYTES,
        "plan": plan,
        "root_attestation_path": str(attestation_path),
        "root_attestation_sha256": "9" * 64,
        "root_attestation": attestation,
        "root_attestation_required_before_user_mutation": True,
    }
    intent = tmp_path / "intent.json"
    intent_sha = _write_private(intent, intent_payload)
    handoff_sha = "4" * 64
    root_receipt_path = tmp_path / "root.json"
    root_receipt_path.write_text("placeholder", encoding="utf-8")
    user_payload = {
        "schema": controller.USER_RECEIPT_SCHEMA,
        "status": "root_handoff_required",
        "producer_sha256": "1" * 64,
        "intent_sha256": intent_sha,
        "plan_sha256": "2" * 64,
        "root_actions_performed": False,
        "target_broadened": False,
        "root_handoff_required": True,
        "root_handoff_path": "/tmp/handoff.json",
        "root_handoff_sha256": handoff_sha,
        "root_receipt_path": str(root_receipt_path),
        "root_apply_argv": None,
        "root_apply_argv_persisted": False,
        "root_installer": controller._root_installer_evidence(),
        "root_installer_sha256": controller.ROOT_INSTALLER_SHA256,
        "projection_deletion_authorized": True,
        "root_candidate_deletion_authorized": True,
        "projection_deletion_performed": False,
        "root_candidate_deletion_performed": False,
        "root_attestation_path": str(attestation_path),
        "root_attestation_sha256": "9" * 64,
    }
    user = tmp_path / "user.json"
    user_sha = _write_private(user, user_payload)
    stage = Path("/root/ea-manfred-capacity.Abcd1234")
    actions = [
        {
            "action_id": root_candidates[index]["action_id"],
            "kind": "candidate_release_projection",
            "path": path,
            "status": (
                "recovered_removed"
                if index == 0
                else "preserved_capacity_ready"
            ),
        }
        for index, path in enumerate(intended)
    ]
    root = {
        "schema": controller.ROOT_RECEIPT_SCHEMA,
        "status": "capacity_ready",
        "intent_sha256": intent_sha,
        "user_receipt_sha256": user_sha,
        "handoff_sha256": handoff_sha,
        "producer_sha256": "1" * 64,
        "root_applier_sha256": "3" * 64,
        "root_installer": controller._root_installer_evidence(),
        "root_installer_sha256": controller.ROOT_INSTALLER_SHA256,
        "user_writable_root_interpreted_file": False,
        "inline_installer_execution_trust_boundary": True,
        "handoff_path": "/tmp/handoff.json",
        "user_receipt_path": str(user),
        "root_stage_path": str(stage),
        "root_stage_mode": 0o700,
        "root_stage_nlink": 2,
        "staged_root_applier": {
            "path": str(stage / "applier.py"), "sha256": "3" * 64, "mode": 0o500, "owner_uid": 0
        },
        "staged_controller": {
            "path": str(stage / "controller.py"), "sha256": "1" * 64, "mode": 0o400, "owner_uid": 0
        },
        "staged_handoff": {
            "path": str(stage / "handoff.json"), "sha256": handoff_sha, "mode": 0o400, "owner_uid": 0
        },
        "staged_user_receipt": {
            "path": str(stage / "user-receipt.json"), "sha256": user_sha, "mode": 0o400, "owner_uid": 0
        },
        "projection_count": len(actions),
        "root_candidate_count": len(actions),
        "authorized_root_action_ids": authorized_ids,
        "root_attestation_path": str(attestation_path),
        "root_attestation_sha256": "9" * 64,
        "root_candidate_set_sha256": controller._root_candidate_set_sha256(plan),
        "global_preflight_complete_before_mutation": True,
        "actions": actions,
        "projection_deletion_performed": True,
        "root_candidate_deletion_performed": True,
        "projections_preserved_count": len(actions) - 1,
        "target_broadened": False,
        "docker_mutations_performed": False,
        "candidate_roots_removed": False,
        "runtime_removed": False,
        "receipts_removed": False,
    }
    monkeypatch.setattr(controller, "_operator_identity", lambda: (uid, tmp_path))
    monkeypatch.setattr(
        controller, "_root_free_bytes", lambda: controller.TARGET_ROOT_FREE_BYTES
    )
    monkeypatch.setattr(
        controller, "_read_root_receipt", lambda *_a, **_k: (root, "6" * 64)
    )
    passed = controller.finalize(
        intent_path=intent,
        user_receipt_path=user,
        root_receipt_path=root_receipt_path,
        completion_receipt_path=tmp_path / "completion.json",
    )
    assert passed["root_stage"] == "receipt_verified"
    root["actions"] = list(reversed(actions))
    with pytest.raises(RuntimeError, match="receipt_chain_invalid"):
        controller.finalize(
            intent_path=intent,
            user_receipt_path=user,
            root_receipt_path=root_receipt_path,
            completion_receipt_path=tmp_path / "completion-reordered.json",
        )


def _vscode_replay_plan(root: Path) -> tuple[dict[str, object], Path, Path]:
    cli = root / ".vscode-server/cli"
    servers = cli / "servers"
    target = servers / f"Stable-{'c' * 40}"
    target.mkdir(parents=True)
    cli.chmod(0o700)
    servers.chmod(0o775)
    for index in range(2):
        path = target / f"payload-{index}.txt"
        path.write_bytes(f"payload-{index}\n".encode())
        path.chmod(0o644)
    evidence = controller._tree_evidence(
        target,
        allowed_owners={os.getuid()},
        hash_content=True,
        missing_ok=False,
    )
    entries = controller._vscode_journal_entries(target, uid=os.getuid())
    quarantine = servers / f".ea-capacity-{evidence.manifest_sha256[:16]}.retired"
    sample_journal = {
        "schema": controller.VSCODE_JOURNAL_SCHEMA,
        "created_at": controller._utc_now(),
        "operator_uid": os.getuid(),
        "target_path": str(target),
        "quarantine_path": str(quarantine),
        "manifest_sha256": evidence.manifest_sha256,
        "entries": entries,
        "entry_count": len(entries),
        "target_broadened": False,
    }
    plan = {
        "vscode": {
            "eligible": True,
            "inactive_tree": evidence.as_dict(),
            "journal_entry_count": len(entries),
            "journal_entries_sha256": controller._sha256(
                controller._json_bytes(entries)
            ),
            "journal_payload_bytes": len(controller._json_bytes(sample_journal)),
        }
    }
    return plan, target, quarantine


@pytest.mark.parametrize("crash_point", ["after_rename", "partial_unlink", "after_rmdir"])
def test_vscode_quarantine_journal_replays_crash_boundaries(
    crash_point: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, target, quarantine = _vscode_replay_plan(tmp_path)
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    original_unlink = controller._unlink_vscode_journaled
    original_atomic = controller._atomic_new_json
    tripped = False
    if crash_point == "after_rename":
        monkeypatch.setattr(
            controller,
            "_unlink_vscode_journaled",
            lambda *_a, **_k: (_ for _ in ()).throw(
                RuntimeError("test_vscode_crash_after_rename")
            ),
        )
    elif crash_point == "partial_unlink":
        def partial(path: Path, **_kwargs: object) -> None:
            first = sorted(os.scandir(path), key=lambda row: row.name)[0]
            Path(first.path).unlink()
            raise RuntimeError("test_vscode_crash_partial_unlink")

        monkeypatch.setattr(controller, "_unlink_vscode_journaled", partial)
    else:
        def crash_complete(path: Path, payload: dict[str, object], *, owner: int) -> str:
            nonlocal tripped
            if not tripped and path.name.endswith(".complete.v2.json"):
                tripped = True
                raise RuntimeError("test_vscode_crash_after_rmdir")
            return original_atomic(path, payload, owner=owner)

        monkeypatch.setattr(controller, "_atomic_new_json", crash_complete)
    with pytest.raises(RuntimeError, match="test_vscode_crash"):
        controller._apply_vscode(plan, uid=os.getuid())
    monkeypatch.setattr(controller, "_unlink_vscode_journaled", original_unlink)
    monkeypatch.setattr(controller, "_atomic_new_json", original_atomic)
    recovered = controller._apply_vscode(plan, uid=os.getuid())
    assert recovered["status"] in {"recovered_removed", "already_removed_verified"}
    assert not target.exists() and not quarantine.exists()
    journal_files = list((target.parent.parent).glob("*.journal.v2.json"))
    complete_files = list((target.parent.parent).glob("*.complete.v2.json"))
    assert len(journal_files) == len(complete_files) == 1


def test_vscode_replay_rejects_unexpected_quarantine_addition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, target, quarantine = _vscode_replay_plan(tmp_path)
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    original_unlink = controller._unlink_vscode_journaled
    monkeypatch.setattr(
        controller,
        "_unlink_vscode_journaled",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("test_stop_after_rename")),
    )
    with pytest.raises(RuntimeError, match="test_stop_after_rename"):
        controller._apply_vscode(plan, uid=os.getuid())
    assert not target.exists() and quarantine.exists()
    unexpected = quarantine / "unexpected.txt"
    unexpected.write_text("do not delete", encoding="utf-8")
    monkeypatch.setattr(
        controller,
        "_unlink_vscode_journaled",
        original_unlink,
    )
    with pytest.raises(RuntimeError, match="remaining_set_invalid"):
        controller._apply_vscode(plan, uid=os.getuid())
    assert unexpected.read_text(encoding="utf-8") == "do not delete"


def test_vscode_journal_oversize_fails_during_read_only_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, _inactive = _vscode_layout(tmp_path)
    monkeypatch.setattr(
        controller,
        "_process_references",
        lambda path, **_kwargs: [{"pid": 1}] if path == active else [],
    )
    monkeypatch.setattr(controller, "MAX_JSON_BYTES", 256)
    with pytest.raises(RuntimeError, match="receipt_size_invalid"):
        controller._vscode_evidence(
            home=tmp_path,
            uid=os.getuid(),
            process_inventory=_complete_process_inventory(),
        )


def test_vscode_journal_contract_change_fails_before_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, target, quarantine = _vscode_replay_plan(tmp_path)
    vscode = plan["vscode"]
    assert isinstance(vscode, dict)
    payload_bytes = vscode["journal_payload_bytes"]
    assert isinstance(payload_bytes, int)
    vscode["journal_payload_bytes"] = payload_bytes + 1
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    rename_calls: list[tuple[object, ...]] = []

    def forbid_rename(*args: object, **_kwargs: object) -> None:
        rename_calls.append(args)
        raise AssertionError("rename must not run for a changed journal contract")

    monkeypatch.setattr(controller.os, "rename", forbid_rename)
    with pytest.raises(RuntimeError, match="journal_contract_changed"):
        controller._apply_vscode(plan, uid=os.getuid())
    assert rename_calls == []
    assert target.exists()
    assert not quarantine.exists()
    assert list((target.parent.parent).glob("*.journal.v2.json")) == []


def _projection_replay_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object]]:
    uid = os.getuid()
    deploy = tmp_path / "deploy"
    candidate = deploy / "candidate-aaaaaaaa"
    releases = candidate / "releases"
    receipts = candidate / "receipts"
    release_id = "a" * 40
    target = releases / release_id
    target.mkdir(parents=True)
    receipts.mkdir()
    candidate.chmod(0o700)
    releases.chmod(0o700)
    receipts.chmod(0o700)
    for index in range(2):
        payload = target / f"payload-{index}.txt"
        payload.write_bytes(f"payload-{index}\n".encode())
        payload.chmod(0o440)
    nested = target / "nested-empty"
    nested.mkdir()
    nested.chmod(0o550)
    target.chmod(0o550)
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        tree, _inodes, projection_sha, count, size, _entries = root_applier._tree_from_fd(
            descriptor, path=str(target), runtime_uid=uid
        )
    finally:
        os.close(descriptor)
    spatial_payload = {"schema": "test.spatial.v1"}
    spatial_path = receipts / f"{release_id}.spatial.json"
    spatial_sha = _write_private(spatial_path, spatial_payload)
    project = "ea-manfred-candidate-aaaaaaaa"
    receipt_payload = {
        "schema": root_applier.PROJECTION_SCHEMA,
        "status": "pass",
        "release_id": release_id,
        "release_root": str(target),
        "compose_project": project,
        "projection_sha256": projection_sha,
        "spatial_receipt_sha256": spatial_sha,
        "runtime_uid": uid,
        "release_authority_promotion_authority": False,
        "release_authority_runtime_clear": True,
        "file_count": count,
        "projection_bytes": size,
    }
    receipt_path = receipts / f"{release_id}.json"
    receipt_sha = _write_private(receipt_path, receipt_payload)
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir(mode=0o700)
    raw = {
        "candidate_root": str(candidate),
        "release_id": release_id,
        "path": str(target),
        "project": project,
        "tree": tree,
        "projection_sha256": projection_sha,
        "receipt_sha256": receipt_sha,
        "spatial_receipt_sha256": spatial_sha,
        "runtime_uid": uid,
        "release_authority_promotion_authority": False,
        "release_authority_runtime_clear": True,
        "candidate_root_preserved": True,
        "runtime_preserved": True,
        "receipts_preserved": True,
        "root_revalidation_required": True,
        "process_reference_check": "root_revalidation_required",
        "process_references": None,
    }
    original_open_dir = root_applier._open_dir_at
    original_read_at = root_applier._read_json_at
    monkeypatch.setattr(
        root_applier,
        "_open_dir_at",
        lambda parent, name, **kwargs: original_open_dir(
            parent,
            name,
            expected_uid=uid,
            exact_mode=kwargs.get("exact_mode"),
        ),
    )
    monkeypatch.setattr(
        root_applier,
        "_read_json_at",
        lambda parent, name, **_kwargs: original_read_at(
            parent, name, expected_uid=uid
        ),
    )
    monkeypatch.setattr(root_applier, "_require_project_absent", lambda _project: None)
    monkeypatch.setattr(
        root_applier,
        "_require_no_container_mount_references",
        lambda *_a, **_k: {"all_containers_inspected": True},
    )
    monkeypatch.setattr(
        root_applier,
        "_require_no_nested_host_mounts",
        lambda *_a, **_k: {"nested_mounts_absent": True},
    )
    monkeypatch.setattr(root_applier, "_process_references", lambda **_kwargs: [])
    # Root may rename an attested 0550 directory across parents; the unprivileged
    # test process cannot update its ``..`` entry.  Simulate only that privilege
    # boundary while restoring the exact attested mode before revalidation.
    original_rename = os.rename

    def privileged_rename(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        os.chmod(source, 0o750, dir_fd=src_dir_fd)
        original_rename(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        os.chmod(destination, 0o550, dir_fd=dst_dir_fd)

    monkeypatch.setattr(root_applier.os, "rename", privileged_rename)
    production_unlink = root_applier._unlink_contents

    def rootlike_unlink(descriptor: int, **kwargs: object) -> None:
        os.fchmod(descriptor, 0o750)
        try:
            production_unlink(descriptor, **kwargs)
        finally:
            os.fchmod(descriptor, 0o550)

    monkeypatch.setattr(root_applier, "_unlink_contents", rootlike_unlink)

    def read_optional(path: Path):  # type: ignore[no-untyped-def]
        return (
            root_applier._read_json(path, expected_uid=uid)
            if os.path.lexists(path)
            else None
        )

    def write_journal(path: Path, payload: dict[str, object]) -> str:
        if os.path.lexists(path):
            raise RuntimeError("test_journal_exists")
        return _write_private(path, payload)

    monkeypatch.setattr(root_applier, "_read_optional_root_json", read_optional)
    monkeypatch.setattr(root_applier, "_atomic_private_root_json", write_journal)
    state = {
        "deploy": deploy,
        "target": target,
        "candidate": candidate,
        "receipts": receipts,
        "quarantine": quarantine,
        "operator_uid": uid + 1,
        "handoff_sha256": "7" * 64,
        "write_journal": write_journal,
    }
    return raw, state


@pytest.mark.parametrize(
    "crash_point",
    [
        "after_rename",
        "partial_unlink",
        "nested_child_rmdir",
        "empty_tree",
        "after_rmdir",
    ],
)
def test_projection_deletion_journal_replays_each_crash_boundary(
    crash_point: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, state = _projection_replay_fixture(tmp_path, monkeypatch)
    deploy_descriptor = os.open(
        state["deploy"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    quarantine_descriptor = os.open(
        state["quarantine"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    original_unlink = root_applier._unlink_contents
    safe_writer = state["write_journal"]
    tripped = False

    if crash_point == "after_rename":
        production_rename = root_applier.os.rename

        def rename_then_crash(*args: object, **kwargs: object) -> None:
            nonlocal tripped
            production_rename(*args, **kwargs)
            if not tripped:
                tripped = True
                raise RuntimeError("test_crash_after_rename")

        monkeypatch.setattr(root_applier.os, "rename", rename_then_crash)
    elif crash_point == "after_rmdir":
        def crashing_writer(path: Path, payload: dict[str, object]) -> str:
            nonlocal tripped
            suffix = ".complete.v2.json"
            if not tripped and path.name.endswith(suffix):
                tripped = True
                raise RuntimeError(f"test_crash_{crash_point}")
            return safe_writer(path, payload)

        monkeypatch.setattr(root_applier, "_atomic_private_root_json", crashing_writer)
    elif crash_point == "partial_unlink":
        def partial(descriptor: int, **_kwargs: object) -> None:
            os.fchmod(descriptor, 0o750)
            try:
                name = next(
                    name
                    for name in sorted(os.listdir(descriptor))
                    if stat.S_ISREG(
                        os.stat(
                            name,
                            dir_fd=descriptor,
                            follow_symlinks=False,
                        ).st_mode
                    )
                )
                os.unlink(name, dir_fd=descriptor)
            finally:
                os.fchmod(descriptor, 0o550)
            raise RuntimeError("test_crash_partial_unlink")

        monkeypatch.setattr(root_applier, "_unlink_contents", partial)
    elif crash_point == "nested_child_rmdir":
        production_rmdir = root_applier.os.rmdir

        def child_rmdir_then_crash(*args: object, **kwargs: object) -> None:
            nonlocal tripped
            production_rmdir(*args, **kwargs)
            if not tripped and args[0] == "nested-empty":
                tripped = True
                raise RuntimeError("test_crash_nested_child_rmdir")

        monkeypatch.setattr(root_applier.os, "rmdir", child_rmdir_then_crash)
    else:
        def empty_then_crash(descriptor: int, **kwargs: object) -> None:
            original_unlink(descriptor, **kwargs)
            raise RuntimeError("test_crash_empty_tree")

        monkeypatch.setattr(root_applier, "_unlink_contents", empty_then_crash)

    arguments = {
        "deploy_descriptor": deploy_descriptor,
        "deploy_root": state["deploy"],
        "operator_uid": state["operator_uid"],
        "handoff_sha256": state["handoff_sha256"],
        "quarantine_descriptor": quarantine_descriptor,
        "quarantine_root": state["quarantine"],
    }
    try:
        with pytest.raises(RuntimeError, match="test_crash"):
            root_applier._validate_projection(raw, **arguments)
        monkeypatch.setattr(root_applier, "_atomic_private_root_json", safe_writer)
        monkeypatch.setattr(root_applier, "_unlink_contents", original_unlink)
        recovered = root_applier._validate_projection(raw, **arguments)
    finally:
        os.close(quarantine_descriptor)
        os.close(deploy_descriptor)
    assert recovered["status"] == "recovered_removed"
    assert not Path(state["target"]).exists()
    assert Path(state["candidate"]).exists()
    assert Path(state["receipts"]).exists()
    journal_files = list(Path(state["quarantine"]).glob("*.journal.v2.json"))
    complete_files = list(Path(state["quarantine"]).glob("*.complete.v2.json"))
    assert len(journal_files) == len(complete_files) == 1


@pytest.mark.parametrize(
    "inventory_error",
    [
        "manfred_capacity_root_process_inventory_invalid",
        "manfred_capacity_root_process_fd_inventory_unbounded",
    ],
)
def test_projection_inventory_failure_precedes_rename_and_unlink(
    inventory_error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, state = _projection_replay_fixture(tmp_path, monkeypatch)
    deploy_descriptor = os.open(
        state["deploy"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    quarantine_descriptor = os.open(
        state["quarantine"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    mutation_calls: list[str] = []

    def fail_inventory(**_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError(inventory_error)

    def forbid_rename(*_args: object, **_kwargs: object) -> None:
        mutation_calls.append("rename")
        raise AssertionError("rename must not run after inventory failure")

    def forbid_unlink(*_args: object, **_kwargs: object) -> None:
        mutation_calls.append("unlink")
        raise AssertionError("unlink must not run after inventory failure")

    monkeypatch.setattr(root_applier, "_process_references", fail_inventory)
    monkeypatch.setattr(root_applier.os, "rename", forbid_rename)
    monkeypatch.setattr(root_applier, "_unlink_contents", forbid_unlink)
    try:
        with pytest.raises(RuntimeError, match=inventory_error):
            root_applier._validate_projection(
                raw,
                deploy_descriptor=deploy_descriptor,
                deploy_root=state["deploy"],
                operator_uid=state["operator_uid"],
                handoff_sha256=state["handoff_sha256"],
                quarantine_descriptor=quarantine_descriptor,
                quarantine_root=state["quarantine"],
            )
    finally:
        os.close(quarantine_descriptor)
        os.close(deploy_descriptor)
    assert mutation_calls == []
    assert Path(state["target"]).exists()
    assert list(Path(state["quarantine"]).iterdir()) == []


def test_projection_plan_defers_process_proof_to_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy"
    candidate = deploy / "candidate-aaaaaaaa"
    release_id = "a" * 40
    release = candidate / "releases" / release_id
    receipts = candidate / "receipts"
    release.mkdir(parents=True)
    receipts.mkdir()
    deploy.chmod(0o700)
    candidate.chmod(0o700)
    spatial = receipts / f"{release_id}.spatial.json"
    receipt = {
        "schema": controller.PROJECTION_SCHEMA,
        "status": "pass",
        "release_id": release_id,
        "release_root": str(release),
        "runtime_root": str(candidate / "runtime"),
        "compose_project": "ea-manfred-candidate-aaaaaaaa",
        "commit": "b" * 40,
        "runtime_uid": max(1, os.getuid() + 1),
        "release_authority_promotion_authority": False,
        "release_authority_runtime_clear": True,
        "spatial_receipt_path": str(spatial),
        "spatial_receipt_sha256": "c" * 64,
        "projection_sha256": "d" * 64,
        "file_count": 1,
        "projection_bytes": 10,
    }

    def receipt_reader(path: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        if path == spatial:
            return {"schema": "test.spatial.v1"}, "c" * 64
        return receipt, "e" * 64

    monkeypatch.setattr(controller, "EXPECTED_PROJECTION_COUNT", 1)
    monkeypatch.setattr(controller, "_projection_receipt", receipt_reader)
    monkeypatch.setattr(
        controller,
        "_projection_tree_digest",
        lambda _path: ("d" * 64, [{"size_bytes": 10}]),
    )
    monkeypatch.setattr(
        controller,
        "_tree_evidence",
        lambda path, **_kwargs: controller.TreeEvidence(
            str(path), True, 1, 2, 0o550, max(1, os.getuid() + 1), os.getgid(), 1, 10, 4096, "f" * 64
        ),
    )
    monkeypatch.setattr(controller, "_bounded_run", lambda *_a, **_k: b"")
    monkeypatch.setattr(
        controller,
        "_require_project_absent",
        lambda *_a, **_k: {"all_resources_absent": True},
    )
    monkeypatch.setattr(
        controller,
        "_process_references",
        lambda *_a, **_k: pytest.fail("operator proc proof must be deferred"),
    )
    rows, exclusions = controller._projection_evidence(
        source_root=tmp_path,
        deploy_root=deploy,
        home=tmp_path,
        uid=os.getuid(),
    )
    assert exclusions == []
    assert rows[0]["root_revalidation_required"] is True
    assert rows[0]["process_reference_check"] == "root_revalidation_required"
    assert rows[0]["process_references"] is None


def test_degraded_inventory_freezes_cache_and_vscode_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active, _inactive = _vscode_layout(tmp_path)
    cache_paths = {
        "nuget_http": tmp_path / "nuget-http",
        "nuget_global_packages": tmp_path / "nuget-global",
        "npm_content_cache": tmp_path / "npm",
        "pip_cache": tmp_path / "pip",
    }
    inventory = {
        **_complete_process_inventory(),
        "status": "degraded",
        "unreadable_process_count": 1,
    }
    monkeypatch.setattr(controller, "_official_cache_paths", lambda **_k: cache_paths)
    monkeypatch.setattr(
        controller,
        "_tree_evidence",
        lambda path, **_kwargs: controller.TreeEvidence(
            str(path), True, 1, 2, 0o700, os.getuid(), os.getgid(), 1, 10, 4096, "a" * 64
        ),
    )
    monkeypatch.setattr(
        controller,
        "_active_tool_processes",
        lambda *_a, **_k: pytest.fail("degraded cache inventory must not be rescanned"),
    )
    monkeypatch.setattr(
        controller,
        "_process_references",
        lambda *_a, **_k: pytest.fail("degraded targets must not be selected"),
    )
    caches = controller._cache_evidence(
        home=tmp_path,
        uid=os.getuid(),
        process_inventory=inventory,
    )
    assert len(caches) == 4
    assert all(row["eligible"] is False for row in caches)
    assert all(row["eligible_reclaim_floor_bytes"] == 0 for row in caches)
    vscode = controller._vscode_evidence(
        home=tmp_path,
        uid=os.getuid(),
        process_inventory=inventory,
    )
    assert active.parent == Path(vscode["server_root"])
    assert vscode["eligible"] is False
    assert vscode["inactive_tree"] is None
    assert vscode["journal_entry_count"] == 0


def test_ineligible_user_actions_skip_before_any_target_touch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = {
        "name": "pip_cache",
        "eligible": False,
        "availability": "process_inventory_unavailable",
        "tree": {"path": "/unreadable/cache", "allocated_bytes": 4096},
    }
    vscode = {
        "eligible": False,
        "availability": "process_inventory_unavailable",
        "inactive_tree": None,
    }
    monkeypatch.setattr(
        controller,
        "_tree_evidence",
        lambda *_a, **_k: pytest.fail("ineligible cache target must not be touched"),
    )
    monkeypatch.setattr(
        controller,
        "_secure_remove_tree",
        lambda *_a, **_k: pytest.fail("ineligible VSCode target must not be touched"),
    )
    cache_result = controller._apply_caches(
        {"caches": [cache]}, home=Path("/home/operator"), uid=os.getuid()
    )
    vscode_result = controller._apply_vscode(
        {"vscode": vscode}, uid=os.getuid()
    )
    assert cache_result[0]["status"] == "preserved_process_inventory_unavailable"
    assert cache_result[0]["mutation_command_count"] == 0
    assert vscode_result["status"] == "preserved_process_inventory_unavailable"
    assert vscode_result["mutation_command_count"] == 0


def test_capacity_contract_moves_unreadable_user_actions_to_exact_root_candidates() -> None:
    plan = json.loads(json.dumps(_plan_scope()))
    for cache in plan["caches"]:
        cache["eligible"] = False
        cache["user_eligible"] = False
        cache["availability"] = "process_inventory_unavailable"
        cache["eligible_reclaim_floor_bytes"] = 0
        cache["root_candidate"] = True
        cache["root_reclaim_floor_bytes"] = int(cache["tree"]["allocated_bytes"])
        cache["process_inventory_status"] = "degraded"
    vscode_root = Path(plan["vscode"]["server_root"])
    vscode_trees = [
        _scope_tree(
            str(vscode_root / f"Stable-{'a' * 40}"), allocated=15, uid=plan["operator_uid"]
        ),
        _scope_tree(
            str(vscode_root / f"Stable-{'b' * 40}"), allocated=20, uid=plan["operator_uid"]
        ),
    ]
    vscode_trees.sort(
        key=lambda row: (-int(row["allocated_bytes"]), str(row["path"]))
    )
    plan["vscode"] = {
        **plan["vscode"],
        "active_server": None,
        "inactive_server": None,
        "inactive_tree": None,
        "journal_entry_count": 0,
        "journal_payload_bytes": 0,
        "journal_entries_sha256": None,
        "process_references": None,
        "process_inventory_status": "degraded",
        "eligible": False,
        "user_eligible": False,
        "availability": "process_inventory_unavailable",
        "eligible_reclaim_floor_bytes": 0,
        "root_candidate": True,
        "root_candidate_trees": vscode_trees,
        "root_reclaim_floor_bytes": 20,
    }
    plan["controller_process_inventory"] = {
        **plan["controller_process_inventory"],
        "status": "degraded",
        "unreadable_process_count": 1,
    }
    plan["unavailable_user_actions"] = {
        "cache_count": 4,
        "vscode_count": 1,
        "total_count": 5,
        "identities_included": False,
    }
    plan["root_candidates"] = controller._finite_root_candidates(
        caches=[dict(row) for row in plan["caches"]],
        vscode=dict(plan["vscode"]),
        projections=[dict(row) for row in plan["projections"]],
        temp_candidates=[dict(row) for row in plan["temp_root_candidate_inventory"]],
    )
    plan["root_candidate_count"] = len(plan["root_candidates"])
    capacity = controller._recomputed_plan_capacity(plan)
    assert capacity["user_eligible_reclaim_floor_bytes"] == 200
    assert capacity["root_candidate_reclaim_floor_bytes"] == 840
    assert capacity["eligible_capacity_deficit_bytes"] == 0
    assert capacity["eligible_capacity_sufficient"] is True


def test_root_revalidation_flag_is_required_before_projection_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, state = _projection_replay_fixture(tmp_path, monkeypatch)
    raw["root_revalidation_required"] = False
    mutation_calls: list[str] = []
    monkeypatch.setattr(
        root_applier.os,
        "rename",
        lambda *_a, **_k: mutation_calls.append("rename"),
    )
    monkeypatch.setattr(
        root_applier,
        "_unlink_contents",
        lambda *_a, **_k: mutation_calls.append("unlink"),
    )
    deploy_descriptor = os.open(
        state["deploy"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    quarantine_descriptor = os.open(
        state["quarantine"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    try:
        with pytest.raises(RuntimeError, match="projection_path_invalid"):
            root_applier._validate_projection(
                raw,
                deploy_descriptor=deploy_descriptor,
                deploy_root=state["deploy"],
                operator_uid=state["operator_uid"],
                handoff_sha256=state["handoff_sha256"],
                quarantine_descriptor=quarantine_descriptor,
                quarantine_root=state["quarantine"],
            )
    finally:
        os.close(quarantine_descriptor)
        os.close(deploy_descriptor)
    assert mutation_calls == []
    assert Path(state["target"]).exists()


@pytest.mark.parametrize("relationship", ["direct", "ancestor", "descendant"])
def test_mount_confinement_rejects_related_mount_boundaries(
    relationship: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    if relationship == "direct":
        boundary = target
    elif relationship == "ancestor":
        boundary = target.parent
    else:
        boundary = target / "nested"
    root_status = os.lstat("/")
    entries = (
        controller.MountInfoEntry(
            1,
            0,
            os.major(root_status.st_dev),
            os.minor(root_status.st_dev),
            Path("/"),
            "overlay",
        ),
        controller.MountInfoEntry(
            2,
            1,
            os.major(root_status.st_dev),
            os.minor(root_status.st_dev),
            boundary,
            "fuse.test" if relationship == "descendant" else "ext4",
        ),
    )
    monkeypatch.setattr(controller, "_mountinfo_entries", lambda: entries)
    with pytest.raises(RuntimeError, match="mount_boundary_invalid"):
        controller._assert_mount_confinement(target)


def test_mountinfo_parser_fails_closed_on_malformed_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        controller,
        "_bounded_process_read",
        lambda *_a, **_k: b"not mountinfo\n",
    )
    with pytest.raises(RuntimeError, match="mount_inventory_invalid"):
        controller._mountinfo_entries()


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO, errno.EBADF])
def test_mountinfo_parser_fails_closed_on_read_errors(
    error_number: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        controller,
        "_bounded_process_read",
        lambda *_a, **_k: (_ for _ in ()).throw(
            OSError(error_number, "injected mountinfo failure")
        ),
    )
    with pytest.raises(RuntimeError, match="mount_inventory_invalid"):
        controller._mountinfo_entries()


def test_tree_planning_rejects_same_device_intermediate_symlink(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    pip_cache = outside / "pip"
    home.mkdir()
    pip_cache.mkdir(parents=True)
    (home / ".cache").symlink_to(outside, target_is_directory=True)
    lexical = home / ".cache/pip"
    assert os.lstat(lexical).st_dev == os.lstat(home).st_dev
    with pytest.raises(RuntimeError, match="path_symlink_invalid"):
        controller._tree_evidence(
            lexical,
            allowed_owners={os.getuid()},
            hash_content=False,
        )


def test_allow_missing_guard_rejects_symlinked_parent_chain(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    (home / ".cache").symlink_to(outside, target_is_directory=True)
    missing = home / ".cache/not-created/quarantine"
    assert not os.path.lexists(missing)
    with pytest.raises(RuntimeError, match="path_symlink_invalid"):
        controller._assert_mount_confinement(missing, allow_missing=True)


def test_cache_immediate_guard_rejects_intermediate_symlink_before_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    actual = outside / "pip"
    home.mkdir()
    actual.mkdir(parents=True)
    (actual / "payload").write_text("cache\n", encoding="utf-8")
    (home / ".cache").symlink_to(outside, target_is_directory=True)
    lexical = home / ".cache/pip"
    status = os.lstat(actual)
    expected = controller.TreeEvidence(
        str(lexical),
        True,
        status.st_dev,
        status.st_ino,
        stat.S_IMODE(status.st_mode),
        status.st_uid,
        status.st_gid,
        1,
        6,
        4096,
        "a" * 64,
    )
    monkeypatch.setattr(controller, "_tree_evidence", lambda *_a, **_k: expected)
    monkeypatch.setattr(controller, "_active_tool_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    monkeypatch.setattr(
        controller,
        "_official_cache_paths",
        lambda **_k: {"pip_cache": lexical},
    )
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_a, **_k: pytest.fail("cache tool must not follow parent symlink"),
    )
    with pytest.raises(RuntimeError, match="path_symlink_invalid"):
        controller._apply_caches(
            {
                "caches": [
                    {
                        "name": "pip_cache",
                        "eligible": True,
                        "tree": expected.as_dict(),
                        "clear_argv": list(
                            dict(controller.CACHE_MUTATION_COMMANDS)["pip_cache"]
                        ),
                    }
                ]
            },
            home=home,
            uid=os.getuid(),
        )


def test_vscode_apply_rejects_intermediate_servers_symlink_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = tmp_path / ".vscode-server/cli"
    outside_servers = tmp_path / "outside-servers"
    target_name = f"Stable-{'c' * 40}"
    actual_target = outside_servers / target_name
    cli.mkdir(parents=True)
    cli.chmod(0o700)
    actual_target.mkdir(parents=True)
    outside_servers.chmod(0o775)
    (actual_target / "payload").write_text("payload\n", encoding="utf-8")
    (cli / "servers").symlink_to(outside_servers, target_is_directory=True)
    lexical_target = cli / "servers" / target_name
    status = os.lstat(actual_target)
    expected = {
        "path": str(lexical_target),
        "exists": True,
        "device": status.st_dev,
        "inode": status.st_ino,
        "mode": stat.S_IMODE(status.st_mode),
        "uid": status.st_uid,
        "gid": status.st_gid,
        "file_count": 1,
        "apparent_bytes": 8,
        "allocated_bytes": 4096,
        "manifest_sha256": "a" * 64,
    }
    for name in ("_atomic_new_json", "_unlink_vscode_journaled"):
        monkeypatch.setattr(
            controller,
            name,
            lambda *_a, _name=name, **_k: pytest.fail(
                f"{_name} must not run through servers symlink"
            ),
        )
    monkeypatch.setattr(
        controller.os,
        "rename",
        lambda *_a, **_k: pytest.fail("quarantine rename must not follow symlink"),
    )
    with pytest.raises(RuntimeError, match="path_symlink_invalid"):
        controller._apply_vscode(
            {
                "vscode": {
                    "eligible": True,
                    "inactive_tree": expected,
                    "journal_entry_count": 1,
                    "journal_payload_bytes": 1,
                    "journal_entries_sha256": "b" * 64,
                }
            },
            uid=os.getuid(),
        )


def test_vscode_rename_guard_rejects_symlinked_journal_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    real_journal = tmp_path / "real-journal"
    real_journal.write_text("{}\n", encoding="utf-8")
    journal = tmp_path / "journal"
    journal.symlink_to(real_journal)
    complete = tmp_path / "complete"
    with pytest.raises(RuntimeError, match="path_symlink_invalid"):
        controller._assert_vscode_rename_confinement(
            source,
            destination,
            expected_device=os.lstat(source).st_dev,
            journal_path=journal,
            complete_path=complete,
        )


def test_schema_v2_cut_rejects_v1_plan() -> None:
    schemas = (
        controller.PLAN_SCHEMA,
        controller.PLAN_PROBE_SCHEMA,
        controller.ROOT_ATTEST_REQUEST_SCHEMA,
        controller.ROOT_ATTESTATION_SCHEMA,
        controller.INTENT_SCHEMA,
        controller.USER_RECEIPT_SCHEMA,
        controller.ROOT_HANDOFF_SCHEMA,
        controller.ROOT_RECEIPT_SCHEMA,
        controller.COMPLETION_SCHEMA,
        controller.VSCODE_JOURNAL_SCHEMA,
        controller.VSCODE_COMPLETE_SCHEMA,
        root_applier.ROOT_ATTEST_REQUEST_SCHEMA,
        root_applier.ROOT_ATTESTATION_SCHEMA,
        root_applier.HANDOFF_SCHEMA,
        root_applier.USER_RECEIPT_SCHEMA,
        root_applier.ROOT_RECEIPT_SCHEMA,
        root_applier.DELETION_JOURNAL_SCHEMA,
        root_applier.DELETION_COMPLETE_SCHEMA,
    )
    assert all(value.endswith(".v2") for value in schemas)
    plan = _plan_scope()
    plan["schema"] = "ea.manfred_memorial_build_capacity.plan.v1"
    with pytest.raises(RuntimeError, match="plan_invalid"):
        controller._validate_plan(
            controller._with_plan_digest(plan), producer_sha256="1" * 64
        )


def test_temp_candidate_observations_never_drive_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {
        path: reported + index + 1
        for index, (_action, path, reported) in enumerate(
            controller.ROOT_TEMP_CANDIDATE_SPECS
        )
    }

    def evidence(path: Path, **_kwargs: object) -> controller.TreeEvidence:
        allocated = observed[path]
        return controller.TreeEvidence(
            path=str(path),
            exists=True,
            device=1,
            inode=allocated,
            mode=0o700,
            uid=os.getuid(),
            gid=os.getgid(),
            file_count=1,
            apparent_bytes=1,
            allocated_bytes=allocated,
            manifest_sha256=hashlib.sha256(str(path).encode()).hexdigest(),
            nlink=2,
            entry_count=2,
        )

    monkeypatch.setattr(controller, "_tree_evidence", evidence)
    rows = controller._temp_root_candidate_evidence(uid=os.getuid())
    assert [row["root_reclaim_floor_bytes"] for row in rows] == [
        observed[path] for _action, path, _reported in controller.ROOT_TEMP_CANDIDATE_SPECS
    ]
    assert [row["reported_observation_bytes"] for row in rows] == [
        reported for _action, _path, reported in controller.ROOT_TEMP_CANDIDATE_SPECS
    ]
    assert all(row["capacity_source"] == "live_tree_evidence" for row in rows)


def test_root_attestation_tamper_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = controller._with_plan_digest(_plan_scope())
    action_ids = [str(dict(row)["action_id"]) for row in plan["root_candidates"]]
    eligible_floor = sum(
        int(dict(row)["root_reclaim_floor_bytes"])
        for row in plan["root_candidates"]
    )
    receipt = {
        "schema": controller.ROOT_ATTESTATION_SCHEMA,
        "status": "root_candidates_sufficient",
        "operator_uid": plan["operator_uid"],
        "plan_sha256": plan["plan_sha256"],
        "producer_sha256": plan["producer_sha256"],
        "root_applier_sha256": plan["root_applier"]["sha256"],
        "root_installer": plan["root_installer"],
        "root_installer_sha256": controller.ROOT_INSTALLER_SHA256,
        "root_candidate_set_sha256": controller._root_candidate_set_sha256(plan),
        "root_candidate_count": len(action_ids),
        "eligible_root_action_ids": action_ids,
        "authorized_root_action_ids": [],
        "eligible_root_reclaim_floor_bytes": eligible_floor,
        "authorized_root_reclaim_floor_bytes": 0,
        "root_free_bytes_at_attestation": controller.TARGET_ROOT_FREE_BYTES,
        "target_root_free_bytes": controller.TARGET_ROOT_FREE_BYTES,
        "global_preflight_complete": True,
        "two_sample_stable": True,
        "all_process_fields_readable": True,
        "all_host_mounts_inventoried": True,
        "all_docker_mounts_inventoried": True,
        "guaranteed_user_reclaim_floor_bytes": 0,
        "root_authorization_basis": "all_finite_eligible_candidates",
        "mutation_performed": False,
        "target_broadened": False,
        "secrets_included": False,
    }
    monkeypatch.setattr(
        controller,
        "_read_root_receipt",
        lambda *_a, **_k: (dict(receipt), "a" * 64),
    )
    validated, _digest = controller._validated_root_attestation(
        path=Path("/unused.v2.json"),
        plan=plan,
        operator_uid=int(plan["operator_uid"]),
    )
    assert validated == receipt
    receipt["root_candidate_set_sha256"] = "f" * 64
    with pytest.raises(RuntimeError, match="root_attestation_invalid"):
        controller._validated_root_attestation(
            path=Path("/unused.v2.json"),
            plan=plan,
            operator_uid=int(plan["operator_uid"]),
        )


def test_root_authorization_covers_partial_user_reclaim_and_is_group_limited() -> None:
    rows = [
        {
            "action_id": "a",
            "root_reclaim_floor_bytes": 40,
            "selection_group": None,
            "selection_limit": None,
        },
        {
            "action_id": "vs-a",
            "root_reclaim_floor_bytes": 30,
            "selection_group": "vscode_inactive_one",
            "selection_limit": 1,
        },
        {
            "action_id": "vs-b",
            "root_reclaim_floor_bytes": 50,
            "selection_group": "vscode_inactive_one",
            "selection_limit": 1,
        },
        {
            "action_id": "b",
            "root_reclaim_floor_bytes": 40,
            "selection_group": None,
            "selection_limit": None,
        },
    ]
    target = root_applier.TARGET_ROOT_FREE_BYTES
    eligible, authorized, eligible_floor, authorized_floor = (
        root_applier._eligible_root_prefix(
            rows,
            referenced_action_ids=["vs-a"],
            root_free_bytes=target - 70,
            user_reclaim_floor_bytes=70,
            target=target,
        )
    )
    assert eligible == ["a", "vs-b", "b"]
    assert authorized == ["a", "vs-b", "b"]
    assert eligible_floor == 130
    assert authorized_floor == 130
    with pytest.raises(RuntimeError, match="root_candidates_insufficient"):
        root_applier._eligible_root_prefix(
            rows,
            referenced_action_ids=["a", "vs-a", "vs-b", "b"],
            root_free_bytes=target - 1,
            user_reclaim_floor_bytes=0,
            target=target,
        )


def test_two_sample_root_preflight_rejects_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def sample(_rows: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "snapshots": [],
            "candidates": [{"action_id": "a", "identity": calls}],
            "processes": {
                "referenced_action_ids": [],
                "process_inventory_sha256": str(calls),
            },
            "host_mounts": {"mountpoint_set_sha256": "h"},
            "docker_mounts": {
                "container_set_sha256": "d",
                "bind_or_volume_mount_count": 0,
            },
        }

    monkeypatch.setattr(root_applier, "_root_union_sample", sample)
    with pytest.raises(RuntimeError, match="root_preflight_drift"):
        root_applier._two_sample_root_preflight([{"action_id": "a"}])
    assert calls == 2


def test_strict_root_process_inventory_reads_every_required_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Scan(list[SimpleNamespace]):
        def __enter__(self) -> "Scan":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    process_entry = SimpleNamespace(name="123", path="/proc/123")
    monkeypatch.setattr(
        root_applier.os,
        "scandir",
        lambda path: Scan([process_entry]) if str(path) == "/proc" else Scan(),
    )
    monkeypatch.setattr(
        Path,
        "stat",
        lambda self: SimpleNamespace(st_dev=1, st_ino=123, st_uid=0),
    )
    monkeypatch.setattr(
        root_applier.os,
        "readlink",
        lambda path: "/safe" if str(path).startswith("/proc/123/") else "",
    )
    reads: list[str] = []

    def bounded(path: Path, *, maximum: int) -> bytes:
        assert maximum > 0
        reads.append(path.name)
        return b""

    monkeypatch.setattr(root_applier, "_bounded_proc_read", bounded)
    result = root_applier._strict_process_inventory(
        [
            {
                "action_id": "candidate",
                "path": "/candidate",
                "reference_paths": ["/candidate"],
                "inodes": set(),
            }
        ]
    )
    assert reads == ["cmdline", "maps", "environ", "mountinfo"]
    assert result["all_process_fields_readable"] is True
    assert result["referenced_action_ids"] == []

    def unreadable(path: Path, *, maximum: int) -> bytes:
        if path.name == "environ":
            raise PermissionError(errno.EACCES, "denied")
        assert maximum > 0
        return b""

    monkeypatch.setattr(root_applier, "_bounded_proc_read", unreadable)
    with pytest.raises(RuntimeError, match="process_inventory_invalid"):
        root_applier._strict_process_inventory(
            [
                {
                    "action_id": "candidate",
                    "path": "/candidate",
                    "reference_paths": ["/candidate"],
                    "inodes": set(),
                }
            ]
        )


@pytest.mark.parametrize("variant", ["hardlink", "symlink", "special"])
def test_general_root_candidate_tree_rejects_unsafe_entries(
    variant: str, tmp_path: Path
) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    payload = root / "payload"
    payload.write_bytes(b"safe")
    if variant == "hardlink":
        os.link(payload, root / "alias")
    elif variant == "symlink":
        (root / "alias").symlink_to(payload)
    else:
        os.mkfifo(root / "fifo")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(RuntimeError, match="candidate_identity_invalid"):
            root_applier._general_tree_from_fd(descriptor, path=str(root))
    finally:
        os.close(descriptor)


def test_generic_root_candidate_journal_is_durable_before_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "payload").write_bytes(b"safe")
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        tree, _inodes, _entries, _identity = root_applier._general_tree_from_fd(
            descriptor, path=str(target)
        )
    finally:
        os.close(descriptor)
    row = {
        "action_id": "temp:test",
        "kind": "rebuildable_temp_tree",
        "path": str(target),
        "tree": tree,
        "root_reclaim_floor_bytes": tree["allocated_bytes"],
    }
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir(mode=0o700)

    def read_optional(path: Path):  # type: ignore[no-untyped-def]
        return (
            root_applier._read_json(path, expected_uid=os.getuid())
            if os.path.lexists(path)
            else None
        )

    monkeypatch.setattr(root_applier, "_read_optional_root_json", read_optional)
    monkeypatch.setattr(
        root_applier,
        "_atomic_private_root_json",
        lambda path, payload: _write_private(path, payload),
    )

    def crash_before_rename(*_args: object, **_kwargs: object) -> None:
        assert len(list(quarantine.glob("*.journal.v2.json"))) == 1
        raise RuntimeError("test_crash_before_rename")

    monkeypatch.setattr(root_applier.os, "rename", crash_before_rename)
    quarantine_descriptor = os.open(
        quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    try:
        with pytest.raises(RuntimeError, match="test_crash_before_rename"):
            root_applier._remove_generic_candidate(
                row,
                handoff_sha256="7" * 64,
                quarantine_descriptor=quarantine_descriptor,
                quarantine_root=quarantine,
                pre_mutation=lambda: None,
            )
    finally:
        os.close(quarantine_descriptor)
    assert target.exists()
    assert len(list(quarantine.glob("*.journal.v2.json"))) == 1
    assert list(quarantine.glob("*.complete.v2.json")) == []


def _generic_replay_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], Path, Path, object]:
    target = tmp_path / "generic-target"
    target.mkdir()
    for index in range(3):
        (target / f"payload-{index}.txt").write_bytes(
            f"payload-{index}\n".encode()
        )
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        tree, _inodes, _entries, _identity = root_applier._general_tree_from_fd(
            descriptor, path=str(target)
        )
    finally:
        os.close(descriptor)
    row = {
        "action_id": "temp:generic-replay",
        "kind": "rebuildable_temp_tree",
        "path": str(target),
        "tree": tree,
        "root_reclaim_floor_bytes": tree["allocated_bytes"],
    }
    quarantine = tmp_path / ("7" * 64)
    quarantine.mkdir(mode=0o700)

    def read_optional(path: Path):  # type: ignore[no-untyped-def]
        return (
            root_applier._read_json(path, expected_uid=os.getuid())
            if os.path.lexists(path)
            else None
        )

    def write_journal(path: Path, payload: dict[str, object]) -> str:
        if os.path.lexists(path):
            raise RuntimeError("test_journal_exists")
        return _write_private(path, payload)

    monkeypatch.setattr(root_applier, "_read_optional_root_json", read_optional)
    monkeypatch.setattr(root_applier, "_atomic_private_root_json", write_journal)
    monkeypatch.setattr(
        root_applier,
        "_require_no_nested_host_mounts",
        lambda *_a, **_k: {"nested_mounts_absent": True},
    )
    monkeypatch.setattr(
        root_applier,
        "_require_no_container_mount_references",
        lambda *_a, **_k: {"all_containers_inspected": True},
    )
    monkeypatch.setattr(
        root_applier,
        "_strict_process_inventory",
        lambda _rows: {
            "referenced_action_ids": [],
            "process_inventory_sha256": "0" * 64,
        },
    )
    return row, target, quarantine, write_journal


@pytest.mark.parametrize(
    "crash_point",
    ["after_rename", "partial_unlink", "empty_tree", "after_rmdir"],
)
def test_generic_root_candidate_replays_every_journaled_crash_boundary(
    crash_point: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row, target, quarantine, safe_writer = _generic_replay_fixture(
        tmp_path, monkeypatch
    )
    original_unlink = root_applier._unlink_general_contents
    tripped = False
    if crash_point == "after_rename":
        production_rename = root_applier.os.rename

        def rename_then_crash(*args: object, **kwargs: object) -> None:
            nonlocal tripped
            production_rename(*args, **kwargs)
            if not tripped:
                tripped = True
                raise RuntimeError("test_generic_crash_after_rename")

        monkeypatch.setattr(root_applier.os, "rename", rename_then_crash)
    elif crash_point == "partial_unlink":

        def partial(descriptor: int, **_kwargs: object) -> None:
            name = sorted(os.listdir(descriptor))[0]
            os.unlink(name, dir_fd=descriptor)
            raise RuntimeError("test_generic_crash_partial_unlink")

        monkeypatch.setattr(root_applier, "_unlink_general_contents", partial)
    elif crash_point == "empty_tree":

        def empty_then_crash(descriptor: int, **kwargs: object) -> None:
            original_unlink(descriptor, **kwargs)
            raise RuntimeError("test_generic_crash_empty_tree")

        monkeypatch.setattr(
            root_applier, "_unlink_general_contents", empty_then_crash
        )
    else:

        def crash_complete(path: Path, payload: dict[str, object]) -> str:
            nonlocal tripped
            if not tripped and path.name.endswith(".complete.v2.json"):
                tripped = True
                raise RuntimeError("test_generic_crash_after_rmdir")
            return safe_writer(path, payload)  # type: ignore[misc]

        monkeypatch.setattr(
            root_applier, "_atomic_private_root_json", crash_complete
        )

    quarantine_descriptor = os.open(
        quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    arguments = {
        "handoff_sha256": "7" * 64,
        "quarantine_descriptor": quarantine_descriptor,
        "quarantine_root": quarantine,
        "pre_mutation": lambda: None,
    }
    try:
        with pytest.raises(RuntimeError, match="test_generic_crash"):
            root_applier._remove_generic_candidate(row, **arguments)
        recovered_preflight = root_applier._two_sample_root_preflight(
            [row], recovery_root=quarantine
        )
        assert recovered_preflight["candidates"][0]["tree"] == row["tree"]
        monkeypatch.setattr(root_applier, "_unlink_general_contents", original_unlink)
        monkeypatch.setattr(
            root_applier, "_atomic_private_root_json", safe_writer
        )
        recovered = root_applier._remove_generic_candidate(row, **arguments)
        verified = root_applier._remove_generic_candidate(row, **arguments)
    finally:
        os.close(quarantine_descriptor)
    assert recovered["status"] == "recovered_removed"
    assert verified["status"] == "already_removed_verified"
    assert not target.exists()
    assert len(list(quarantine.glob("*.journal.v2.json"))) == 1
    assert len(list(quarantine.glob("*.complete.v2.json"))) == 1


def test_tree_evidence_rejects_cross_device_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tree"
    target.mkdir()
    child = target / "payload"
    child.write_text("payload\n", encoding="utf-8")
    root_device = os.lstat(target).st_dev
    original_lstat = controller.os.lstat

    def changed_device(path: object) -> object:
        observed = original_lstat(path)
        if Path(path) != child:
            return observed
        return SimpleNamespace(
            st_mode=observed.st_mode,
            st_uid=observed.st_uid,
            st_gid=observed.st_gid,
            st_nlink=observed.st_nlink,
            st_dev=observed.st_dev + 1,
            st_ino=observed.st_ino,
            st_size=observed.st_size,
            st_blocks=observed.st_blocks,
            st_mtime_ns=observed.st_mtime_ns,
        )

    monkeypatch.setattr(controller.os, "lstat", changed_device)
    monkeypatch.setattr(
        controller,
        "_assert_mount_confinement",
        lambda *_a, **_k: root_device,
    )
    with pytest.raises(RuntimeError, match="tree_device_changed"):
        controller._tree_evidence(
            target,
            allowed_owners={os.getuid()},
            hash_content=False,
        )


def test_vscode_journal_rejects_cross_device_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "tree"
    target.mkdir()
    child = target / "payload"
    child.write_text("payload\n", encoding="utf-8")
    root_device = os.lstat(target).st_dev
    original_lstat = controller.os.lstat

    def changed_device(path: object) -> object:
        observed = original_lstat(path)
        if Path(path) != child:
            return observed
        return SimpleNamespace(
            st_mode=observed.st_mode,
            st_uid=observed.st_uid,
            st_gid=observed.st_gid,
            st_nlink=observed.st_nlink,
            st_dev=observed.st_dev + 1,
            st_ino=observed.st_ino,
            st_size=observed.st_size,
            st_blocks=observed.st_blocks,
            st_mtime_ns=observed.st_mtime_ns,
            st_ctime_ns=observed.st_ctime_ns,
        )

    monkeypatch.setattr(controller.os, "lstat", changed_device)
    monkeypatch.setattr(
        controller,
        "_assert_mount_confinement",
        lambda *_a, **_k: root_device,
    )
    with pytest.raises(RuntimeError, match="vscode_tree_changed"):
        controller._vscode_journal_entries(target, uid=os.getuid())


def test_cache_mount_recheck_precedes_exact_tool_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = controller.TreeEvidence(
        "/cache",
        True,
        11,
        12,
        0o700,
        os.getuid(),
        os.getgid(),
        1,
        10,
        4096,
        "a" * 64,
    )
    monkeypatch.setattr(controller, "_tree_evidence", lambda *_a, **_k: expected)
    monkeypatch.setattr(controller, "_active_tool_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    monkeypatch.setattr(
        controller,
        "_official_cache_paths",
        lambda **_k: {"pip_cache": Path("/cache")},
    )
    monkeypatch.setattr(
        controller,
        "_assert_mount_confinement",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("manfred_capacity_mount_boundary_invalid")
        ),
    )
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_a, **_k: pytest.fail("cache tool must not run after mount drift"),
    )
    with pytest.raises(RuntimeError, match="mount_boundary_invalid"):
        controller._apply_caches(
            {
                "caches": [
                    {
                        "name": "pip_cache",
                        "eligible": True,
                        "tree": expected.as_dict(),
                        "clear_argv": list(dict(controller.CACHE_MUTATION_COMMANDS)["pip_cache"]),
                    }
                ]
            },
            home=Path("/home/operator"),
            uid=os.getuid(),
        )


def test_cache_name_rejects_swapped_allowlisted_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = controller.TreeEvidence(
        "/cache",
        True,
        11,
        12,
        0o700,
        os.getuid(),
        os.getgid(),
        1,
        10,
        4096,
        "a" * 64,
    )
    monkeypatch.setattr(controller, "_tree_evidence", lambda *_a, **_k: expected)
    monkeypatch.setattr(controller, "_active_tool_processes", lambda *_a, **_k: [])
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    monkeypatch.setattr(
        controller,
        "_bounded_run",
        lambda *_a, **_k: pytest.fail("swapped command must never execute"),
    )
    with pytest.raises(RuntimeError, match="cache_command_invalid"):
        controller._apply_caches(
            {
                "caches": [
                    {
                        "name": "nuget_http",
                        "eligible": True,
                        "tree": expected.as_dict(),
                        "clear_argv": list(
                            dict(controller.CACHE_MUTATION_COMMANDS)[
                                "nuget_global_packages"
                            ]
                        ),
                    }
                ]
            },
            home=Path("/home/operator"),
            uid=os.getuid(),
        )


def test_plan_rejects_cache_command_valid_for_different_name() -> None:
    plan = _plan_scope()
    caches = [dict(row) for row in plan["caches"]]
    caches[0]["clear_argv"] = list(caches[1]["clear_argv"])
    plan["caches"] = caches
    with pytest.raises(RuntimeError, match="plan_scope_invalid"):
        controller._validate_plan(
            controller._with_plan_digest(plan),
            producer_sha256="1" * 64,
        )


def test_vscode_mount_recheck_precedes_quarantine_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, target, quarantine = _vscode_replay_plan(tmp_path)
    monkeypatch.setattr(controller, "_process_references", lambda *_a, **_k: [])
    rename_calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        controller,
        "_assert_vscode_rename_confinement",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("manfred_capacity_mount_boundary_invalid")
        ),
    )
    monkeypatch.setattr(
        controller.os,
        "rename",
        lambda *args, **_kwargs: rename_calls.append(args),
    )
    with pytest.raises(RuntimeError, match="mount_boundary_invalid"):
        controller._apply_vscode(plan, uid=os.getuid())
    assert rename_calls == []
    assert target.exists()
    assert not quarantine.exists()


def test_vscode_mount_recheck_precedes_journaled_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    payload = target / "payload.txt"
    payload.write_text("payload\n", encoding="utf-8")
    entries = controller._vscode_journal_entries(target, uid=os.getuid())
    expected_device = os.lstat(target).st_dev
    guard_calls = 0
    unlink_calls: list[object] = []

    def fail_before_unlink(
        _path: Path, *, expected_device: int | None = None, allow_missing: bool = False
    ) -> int:
        nonlocal guard_calls
        assert allow_missing is False
        guard_calls += 1
        if guard_calls == 2:
            raise RuntimeError("manfred_capacity_mount_boundary_invalid")
        assert expected_device is not None
        return expected_device

    monkeypatch.setattr(controller, "_assert_mount_confinement", fail_before_unlink)
    monkeypatch.setattr(
        controller.os,
        "unlink",
        lambda path: unlink_calls.append(path),
    )
    with pytest.raises(RuntimeError, match="mount_boundary_invalid"):
        controller._unlink_vscode_journaled(
            target,
            confinement_root=target,
            expected_device=expected_device,
            relative=Path("."),
            expected_by_path={str(row["path"]): row for row in entries},
            uid=os.getuid(),
        )
    assert unlink_calls == []
    assert payload.exists()


def test_projection_runtime_uid_is_distinct_and_exactly_bound() -> None:
    plan = controller._with_plan_digest(_plan_scope())
    operator_uid = int(plan["operator_uid"])
    assert all(
        int(dict(row)["runtime_uid"]) != operator_uid
        and dict(dict(row)["tree"])["uid"] == dict(row)["runtime_uid"]
        for row in plan["projections"]
    )
    controller._validate_plan(plan, producer_sha256="1" * 64)


def test_root_candidate_scope_binds_exact_authorized_operator_uid() -> None:
    operator_uid = max(1, os.getuid())
    runtime_uid = operator_uid + 10_000
    operator_home = Path("/home/operator")
    deploy_root = operator_home / root_applier.DEPLOY_ROOT_RELATIVE
    projections = []
    for index in range(root_applier.EXPECTED_PROJECTION_COUNT):
        candidate_root = deploy_root / f"candidate-{index:08x}"
        release_id = f"{index + 1:040x}"
        path = candidate_root / "releases" / release_id
        projections.append(
            {
                "path": str(path),
                "candidate_root": str(candidate_root),
                "release_id": release_id,
                "tree": _scope_tree(str(path), allocated=30, uid=runtime_uid),
                "runtime_uid": runtime_uid,
                "release_authority_promotion_authority": False,
                "release_authority_runtime_clear": True,
                "candidate_root_preserved": True,
                "runtime_preserved": True,
                "receipts_preserved": True,
            }
        )
    rows = [root_applier._projection_candidate_row(row) for row in projections]
    cache_path = operator_home / ".cache/pip"
    cache_tree = _scope_tree(str(cache_path), allocated=10, uid=operator_uid)
    rows.append(
        {
            "action_id": "cache:pip_cache",
            "kind": "operator_cache_tree",
            "classification": "rebuildable_operator_cache",
            "path": str(cache_path),
            "tree": cache_tree,
            "user_eligible": False,
            "root_candidate": True,
            "root_reclaim_floor_bytes": 10,
            "reported_observation_bytes": None,
            "capacity_source": "live_tree_evidence",
            "parent_preserved": True,
            "protected_overlap": False,
            "selection_group": None,
            "selection_limit": None,
        }
    )

    assert root_applier._validate_root_candidate_scope(
        rows,
        operator_uid=operator_uid,
        operator_home=operator_home,
        deploy_root=deploy_root,
        projections=projections,
    ) == rows

    with pytest.raises(RuntimeError, match="root_candidate_scope_invalid"):
        root_applier._validate_root_candidate_scope(
            rows,
            operator_uid=runtime_uid,
            operator_home=operator_home,
            deploy_root=deploy_root,
            projections=projections,
        )


def test_projection_candidate_cannot_substitute_top_level_plan_scope() -> None:
    plan = _plan_scope()
    original_candidates = list(plan["root_candidates"])
    projections = [dict(row) for row in plan["projections"]]
    projections[0] = {
        **projections[0],
        "commit": "f" * 40,
    }
    plan["projections"] = projections
    plan["root_candidates"] = original_candidates
    with pytest.raises(RuntimeError, match="root_candidate_scope_invalid"):
        controller._validate_plan(
            controller._with_plan_digest(plan), producer_sha256="1" * 64
        )


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("release_authority_promotion_authority", True),
        ("release_authority_runtime_clear", False),
    ],
)
def test_projection_authority_flags_fail_closed_even_when_scope_is_recomputed(
    field: str, unsafe: bool
) -> None:
    plan = _plan_scope()
    projections = [dict(row) for row in plan["projections"]]
    projections[0] = {**projections[0], field: unsafe}
    plan["projections"] = projections
    plan["root_candidates"] = controller._finite_root_candidates(
        caches=[dict(row) for row in plan["caches"]],
        vscode=dict(plan["vscode"]),
        projections=projections,
        temp_candidates=[
            dict(row) for row in plan["temp_root_candidate_inventory"]
        ],
    )
    plan["root_candidate_count"] = len(plan["root_candidates"])
    with pytest.raises(RuntimeError, match="root_candidate_scope_invalid"):
        controller._recomputed_plan_capacity(plan)


def test_controller_tree_entry_bomb_is_bounded_before_descent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "entry-bomb"
    target.mkdir()
    for index in range(3):
        (target / f"directory-{index}").mkdir()
    monkeypatch.setattr(controller, "MAX_TREE_ENTRIES", 2)
    monkeypatch.setattr(
        controller,
        "_assert_mount_confinement",
        lambda *_a, **_k: os.lstat(target).st_dev,
    )
    with pytest.raises(RuntimeError, match="tree_too_large"):
        controller._tree_evidence(
            target, allowed_owners={os.getuid()}, hash_content=False
        )


def test_root_tree_entry_bomb_is_bounded_before_descent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "root-entry-bomb"
    target.mkdir()
    for index in range(3):
        (target / f"directory-{index}").mkdir()
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    monkeypatch.setattr(root_applier, "MAX_TREE_ENTRIES", 2)
    try:
        with pytest.raises(RuntimeError, match="candidate_too_large"):
            root_applier._general_tree_from_fd(descriptor, path=str(target))
    finally:
        os.close(descriptor)


def test_controller_oversized_file_is_rejected_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "oversized-controller"
    target.mkdir()
    (target / "payload").write_bytes(b"12345")
    monkeypatch.setattr(controller, "MAX_TREE_BYTES", 4)
    monkeypatch.setattr(
        controller,
        "_assert_mount_confinement",
        lambda *_a, **_k: os.lstat(target).st_dev,
    )
    monkeypatch.setattr(
        controller.os,
        "open",
        lambda *_a, **_k: pytest.fail("oversized payload must not be opened"),
    )
    with pytest.raises(RuntimeError, match="tree_too_large"):
        controller._tree_evidence(
            target, allowed_owners={os.getuid()}, hash_content=True
        )


def test_root_oversized_file_is_rejected_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "oversized-root"
    target.mkdir()
    (target / "payload").write_bytes(b"12345")
    descriptor = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    monkeypatch.setattr(root_applier, "MAX_TREE_BYTES", 4)
    monkeypatch.setattr(
        root_applier.os,
        "open",
        lambda *_a, **_k: pytest.fail("oversized payload must not be opened"),
    )
    try:
        with pytest.raises(RuntimeError, match="candidate_too_large"):
            root_applier._general_tree_from_fd(descriptor, path=str(target))
    finally:
        os.close(descriptor)


def test_vscode_root_selection_matches_plan_and_root_order() -> None:
    plan = _plan_scope()
    operator_home = Path(str(plan["operator_home"]))
    trees = [
        _scope_tree(
            str(operator_home / ".vscode-server/cli/servers" / f"Stable-{'a' * 40}"),
            allocated=15,
            uid=int(plan["operator_uid"]),
        ),
        _scope_tree(
            str(operator_home / ".vscode-server/cli/servers" / f"Stable-{'b' * 40}"),
            allocated=20,
            uid=int(plan["operator_uid"]),
        ),
    ]
    vscode = {
        **dict(plan["vscode"]),
        "eligible": False,
        "user_eligible": False,
        "root_candidate": True,
        "root_candidate_trees": trees,
    }
    rows = controller._finite_root_candidates(
        caches=[], vscode=vscode, projections=[], temp_candidates=[]
    )
    assert [int(dict(row["tree"])["allocated_bytes"]) for row in rows] == [20, 15]
    assert [row["selection_order"] for row in rows] == [0, 1]
    target = root_applier.TARGET_ROOT_FREE_BYTES
    eligible, authorized, eligible_floor, authorized_floor = (
        root_applier._eligible_root_prefix(
            rows,
            referenced_action_ids=[],
            root_free_bytes=target - 1,
            user_reclaim_floor_bytes=0,
            target=target,
        )
    )
    assert eligible == authorized == [rows[0]["action_id"]]
    assert eligible_floor == authorized_floor == 20
