from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import site
import subprocess
import sys
from typing import Any

import pytest

import scripts.materialize_ea_browser_workflow_proof as materializer


SEED = Path(".codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json")
REVISION = "a" * 40
TREE = "b" * 40
RUN_ID = "c" * 32
PYTHON_IDENTITY = {
    "executable": "/usr/bin/python3",
    "sha256": "d" * 64,
    "version": "3.12.0",
    "dependency_root": "/opt/ea-dependencies",
    "dependency_versions": {
        "playwright": "1.0",
        "pytest": "9.0",
        "uvicorn": "1.0",
    },
}
BROWSER_IDENTITY = {"executable": "/opt/chromium/chrome", "sha256": "e" * 64}


def _write_seed(root: Path, text: str | None = None) -> None:
    path = root / SEED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        text
        if text is not None
        else json.dumps(
            {
                "release_claim": {"summary": "current proof"},
                "browser_workflow_proof": {
                    "expected_browser_signals": ["/register", "/app/today"]
                },
            }
        ),
        encoding="utf-8",
    )


def _state(
    revision: str = REVISION, tree: str = TREE, dirty: bool = False
) -> dict[str, object]:
    return {"revision": revision, "tree": tree, "dirty": dirty}


def _constant_source_state(
    root: Path, *, excluded_output: Path | None = None
) -> dict[str, object]:
    assert root.exists()
    del excluded_output
    return _state()


def _junit_xml(cases: list[str], *, disposition: str = "pass") -> str:
    rows: list[str] = []
    for index, case in enumerate(cases):
        child = ""
        if index == 0 and disposition == "xfail":
            child = '<skipped type="pytest.xfail" message="xfail reason" />'
        elif index == 0 and disposition == "xpass":
            child = '<failure message="[XPASS(strict)] unexpectedly passed" />'
        rows.append(f'<testcase classname="proof" name="{case}">{child}</testcase>')
    skipped = 1 if cases and disposition == "xfail" else 0
    failures = 1 if cases and disposition == "xpass" else 0
    return (
        "<testsuites><testsuite "
        f'tests="{len(cases)}" failures="{failures}" errors="0" skipped="{skipped}">'
        f"{''.join(rows)}</testsuite></testsuites>"
    )


def _passing_lane(
    test_file: str,
    cases: list[str],
    *,
    real_browser: bool,
    run_id: str = RUN_ID,
    revision: str = REVISION,
    tree: str = TREE,
) -> dict[str, Any]:
    xml_text = _junit_xml(cases)
    return {
        "status": "pass",
        "run_id": run_id,
        "trust_model": materializer.TRUST_MODEL,
        "source_revision": revision,
        "source_tree": tree,
        "test_file": test_file,
        "cases": list(cases),
        "selection_mode": "exact_node_ids",
        "node_ids": [f"{test_file}::{case}" for case in cases],
        "runner_root_kind": materializer.RUNNER_ROOT_KIND,
        "snapshot_read_only": True,
        "environment_policy": materializer._environment_policy(real_browser),
        "argv_template": materializer._normalized_argv_template(test_file, cases),
        "python_identity": dict(PYTHON_IDENTITY),
        "browser_identity": dict(BROWSER_IDENTITY) if real_browser else None,
        "exit_code": 0,
        "duration_seconds": 0.1,
        "output_excerpt": [f"{len(cases)} passed in 0.01s"],
        "terminal_summary": f"{len(cases)} passed in 0.01s",
        "report_format": "junit_xml_embedded",
        "junit_xml": xml_text,
        "junit_xml_sha256": hashlib.sha256(xml_text.encode()).hexdigest(),
        "limitations": [],
        "blocking_reasons": [],
        "executed_count": len(cases),
        "passed_count": len(cases),
        "failed_count": 0,
        "error_count": 0,
        "skipped_count": 0,
        "xfail_count": 0,
        "xpass_count": 0,
        "executed_cases": list(cases),
        "passed_cases": list(cases),
        "junit_declared_tests_count": len(cases),
        "junit_declared_failure_count": 0,
        "junit_declared_error_count": 0,
        "junit_declared_skipped_count": 0,
        "junit_totals_consistent": True,
        "terminal_passed_count": len(cases),
        "terminal_xfail_count": 0,
        "terminal_xpass_count": 0,
    }


def _fake_snapshot_builder(root: Path, destination: Path, *, revision: str) -> Path:
    assert revision == REVISION
    destination.mkdir(parents=True)
    source = root / "tracked.txt"
    (destination / "tracked.txt").write_text(
        source.read_text(encoding="utf-8") if source.exists() else "committed",
        encoding="utf-8",
    )
    materializer._make_tree_read_only(destination)
    return destination


def _fake_runtime_resolver(python_bin: str) -> tuple[dict[str, Any], Path]:
    assert Path(python_bin).is_absolute()
    return dict(PYTHON_IDENTITY), Path(PYTHON_IDENTITY["dependency_root"])


def test_load_json_rejects_duplicate_keys_and_nonobject_root(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"status":"pass","status":"blocked"}', encoding="utf-8")
    nonobject = tmp_path / "list.json"
    nonobject.write_text("[]", encoding="utf-8")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"duration_seconds":NaN}', encoding="utf-8")

    with pytest.raises(materializer._DuplicateJSONKey):
        materializer._load_json(duplicate)
    with pytest.raises(ValueError, match="root must be an object"):
        materializer._load_json(nonobject)
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        materializer._load_json(nonfinite)


def test_runtime_context_probes_the_canonical_operator_user_site(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python_bin = tmp_path / "python3"
    python_bin.write_bytes(b"python")
    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()
    dependency_root = operator_home / ".local/lib/python3.12/site-packages"
    observed: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["args"] = args
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "version": "3.12.3",
                    "dependency_root": dependency_root.as_posix(),
                    "dependencies": {
                        "playwright": "1.60.0",
                        "pytest": "9.0.2",
                        "uvicorn": "0.49.0",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(materializer, "_operator_home", lambda: operator_home)
    monkeypatch.setattr(materializer, "_sha256_file", lambda path: "f" * 64)
    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    identity, resolved_dependency_root = materializer._runtime_context(
        python_bin.as_posix()
    )

    assert observed["args"][1:3] == ["-I", "-c"]  # type: ignore[index]
    assert "sys.path.insert(0,site.getusersitepackages())" in observed["args"][3]  # type: ignore[index,operator]
    assert observed["env"]["HOME"] == operator_home.as_posix()  # type: ignore[index]
    assert resolved_dependency_root == dependency_root
    assert identity["dependency_versions"]["pytest"] == "9.0.2"


def test_resolve_python_bin_preserves_a_venv_launcher_symlink(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    launcher = root / ".venv" / "bin" / "python"
    launcher.parent.mkdir(parents=True)
    target = tmp_path / "system-python"
    target.write_bytes(b"python")
    launcher.symlink_to(target)

    assert materializer._resolve_python_bin(root) == launcher.as_posix()


def test_runtime_context_rejects_an_unresolved_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python_bin = tmp_path / "python3"
    python_bin.write_bytes(b"python")
    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "version": "3.12.3",
                    "dependency_root": "/missing",
                    "dependencies": {
                        "playwright": None,
                        "pytest": "9.0.2",
                        "uvicorn": "0.49.0",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(materializer, "_operator_home", lambda: operator_home)
    monkeypatch.setattr(materializer, "_sha256_file", lambda path: "f" * 64)
    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="dependency identity is incomplete"):
        materializer._runtime_context(python_bin.as_posix())


def test_lane_identity_redaction_fails_closed_for_malformed_shapes() -> None:
    malformed_python = {
        **PYTHON_IDENTITY,
        "operator_home": "/home/tibor/private",
    }
    lane = {
        "status": "blocked",
        "python_identity": malformed_python,
        "browser_identity": "/home/tibor/.cache/chromium",
    }

    published = materializer._redact_lane_identity_paths(lane)

    sentinel = {"status": materializer.INVALID_IDENTITY_REDACTED}
    assert published["python_identity"] == sentinel
    assert published["browser_identity"] == sentinel
    assert "/home/tibor" not in json.dumps(published)


def test_python_identity_rejects_path_shaped_version_labels() -> None:
    identity = {
        **PYTHON_IDENTITY,
        "version": "/home/tibor/python",
    }

    assert materializer._python_identity_is_complete(identity) is False
    published = materializer._redact_lane_identity_paths(
        {"python_identity": identity}
    )
    assert published["python_identity"] == {
        "status": materializer.INVALID_IDENTITY_REDACTED
    }
    assert "/home/tibor" not in json.dumps(published)


def test_build_receipt_uses_one_immutable_snapshot_for_both_lanes(
    tmp_path: Path,
) -> None:
    _write_seed(tmp_path)
    (tmp_path / "tracked.txt").write_text("committed", encoding="utf-8")
    roots: list[Path] = []
    contents: list[str] = []

    def runner(root: Path, **kwargs: Any) -> dict[str, Any]:
        roots.append(root)
        contents.append((root / "tracked.txt").read_text(encoding="utf-8"))
        assert materializer._snapshot_is_read_only(root)
        return _passing_lane(
            kwargs["test_file"],
            kwargs["cases"],
            real_browser=kwargs["real_browser"],
            run_id=kwargs["run_id"],
            revision=kwargs["source_revision"],
            tree=kwargs["source_tree"],
        )

    receipt = materializer.build_receipt(
        tmp_path,
        seed_path=SEED,
        run_id=RUN_ID,
        runner=runner,
        source_state=_constant_source_state,
        snapshot_builder=_fake_snapshot_builder,
        runtime_resolver=_fake_runtime_resolver,
        operator_env={},
    )

    assert receipt["version"] == 3
    assert receipt["status"] == "pass"
    assert receipt["source_revision"] == REVISION
    assert receipt["source_tree"] == TREE
    assert receipt["source_worktree_dirty"] is False
    assert all(row["dirty"] is False for row in receipt["source_state_samples"])
    assert roots[0] == roots[1]
    assert contents == ["committed", "committed"]
    assert [
        row["stage"] for row in receipt["source_state_samples"]
    ] == materializer.SOURCE_STATE_STAGES
    snapshot = receipt["snapshot"]
    assert snapshot["archive_format"] == "git_archive_tar"
    assert snapshot["read_only"] is True
    assert snapshot["read_only_enforcement"] == (
        materializer.SNAPSHOT_READ_ONLY_ENFORCEMENT
    )
    assert snapshot["source_revision"] == REVISION
    assert snapshot["source_tree"] == TREE
    assert snapshot["seal_algorithm"] == materializer.SNAPSHOT_SEAL_ALGORITHM
    assert [row["stage"] for row in snapshot["seal_samples"]] == (
        materializer.SNAPSHOT_SEAL_STAGES
    )
    assert len({row["sha256"] for row in snapshot["seal_samples"]}) == 1
    assert snapshot["mutation_watch"] == {
        "algorithm": materializer.SNAPSHOT_MUTATION_WATCH_ALGORITHM,
        "samples": [
            {"stage": stage, "event_count": 0, "overflow": False}
            for stage in materializer.SNAPSHOT_MUTATION_WATCH_STAGES
        ],
    }
    source_python = receipt["source_backed_journey_proof"]["python_identity"]
    browser_python = receipt["real_browser_e2e_proof"]["python_identity"]
    browser_identity = receipt["real_browser_e2e_proof"]["browser_identity"]
    for identity in (source_python, browser_python):
        assert identity["executable"] == materializer.REDACTED_PYTHON_EXECUTABLE
        assert identity["dependency_root"] == (
            materializer.REDACTED_PYTHON_DEPENDENCY_ROOT
        )
        assert identity["sha256"] == PYTHON_IDENTITY["sha256"]
        assert identity["version"] == PYTHON_IDENTITY["version"]
        assert identity["dependency_versions"] == PYTHON_IDENTITY[
            "dependency_versions"
        ]
    assert browser_identity == {
        "executable": materializer.REDACTED_BROWSER_EXECUTABLE,
        "sha256": BROWSER_IDENTITY["sha256"],
    }
    assert PYTHON_IDENTITY["executable"] == "/usr/bin/python3"
    assert BROWSER_IDENTITY["executable"] == "/opt/chromium/chrome"


def test_transient_snapshot_chmod_write_restore_is_detected(tmp_path: Path) -> None:
    _write_seed(tmp_path)
    (tmp_path / "tracked.txt").write_text("committed", encoding="utf-8")
    calls = 0

    def runner(root: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        if calls == 0:
            target = root / "tracked.txt"
            original = target.stat()
            target.chmod(0o644)
            target.write_text("transient attacker content", encoding="utf-8")
            target.write_text("committed", encoding="utf-8")
            target.chmod(0o444)
            # Restore the visible content, mode, and mtime; inotify must still
            # record the transient write even on coarse-timestamp filesystems.
            os.utime(
                target,
                ns=(original.st_atime_ns, original.st_mtime_ns),
            )
            assert target.read_text(encoding="utf-8") == "committed"
            assert target.stat().st_mode & 0o222 == 0
            assert target.stat().st_mtime_ns == original.st_mtime_ns
        calls += 1
        return _passing_lane(
            kwargs["test_file"],
            kwargs["cases"],
            real_browser=kwargs["real_browser"],
            run_id=kwargs["run_id"],
            revision=kwargs["source_revision"],
            tree=kwargs["source_tree"],
        )

    receipt = materializer.build_receipt(
        tmp_path,
        seed_path=SEED,
        run_id=RUN_ID,
        runner=runner,
        source_state=_constant_source_state,
        snapshot_builder=_fake_snapshot_builder,
        runtime_resolver=_fake_runtime_resolver,
        operator_env={},
    )

    assert receipt["status"] == "blocked"
    assert (
        "committed snapshot changed during proof execution"
        in receipt["blocking_reasons"]
    )
    assert any(
        row["event_count"] > 0
        for row in receipt["snapshot"]["mutation_watch"]["samples"]
    )


def test_original_mutation_cannot_change_shared_snapshot_runner_root(
    tmp_path: Path,
) -> None:
    _write_seed(tmp_path)
    original = tmp_path / "tracked.txt"
    original.write_text("committed", encoding="utf-8")
    calls = 0
    observed: list[str] = []

    def source_state(
        root: Path, *, excluded_output: Path | None = None
    ) -> dict[str, object]:
        nonlocal calls
        del excluded_output
        calls += 1
        if calls == 2:
            (root / "tracked.txt").write_text("transient mutation", encoding="utf-8")
        return _state()

    def runner(root: Path, **kwargs: Any) -> dict[str, Any]:
        observed.append((root / "tracked.txt").read_text(encoding="utf-8"))
        return _passing_lane(
            kwargs["test_file"], kwargs["cases"], real_browser=kwargs["real_browser"]
        )

    receipt = materializer.build_receipt(
        tmp_path,
        seed_path=SEED,
        run_id=RUN_ID,
        runner=runner,
        source_state=source_state,
        snapshot_builder=_fake_snapshot_builder,
        runtime_resolver=_fake_runtime_resolver,
        operator_env={},
    )

    assert observed == ["committed", "committed"]
    assert original.read_text(encoding="utf-8") == "transient mutation"
    assert receipt["status"] == "pass"


@pytest.mark.parametrize(
    "final_state",
    [
        _state(tree="f" * 40),
        _state(revision="f" * 40),
        _state(dirty=True),
    ],
)
def test_final_source_state_change_blocks_current_receipt(
    tmp_path: Path,
    final_state: dict[str, object],
) -> None:
    _write_seed(tmp_path)
    states = iter([_state(), _state(), _state(), final_state])

    def changing_state(
        root: Path, *, excluded_output: Path | None = None
    ) -> dict[str, object]:
        del root, excluded_output
        return next(states)

    def runner(root: Path, **kwargs: Any) -> dict[str, Any]:
        del root
        return _passing_lane(
            kwargs["test_file"], kwargs["cases"], real_browser=kwargs["real_browser"]
        )

    receipt = materializer.build_receipt(
        tmp_path,
        seed_path=SEED,
        run_id=RUN_ID,
        runner=runner,
        source_state=changing_state,
        snapshot_builder=_fake_snapshot_builder,
        runtime_resolver=_fake_runtime_resolver,
        operator_env={},
    )

    assert receipt["status"] == "blocked"
    assert (
        "original source revision, tree, or cleanliness changed during proof"
        in receipt["blocking_reasons"]
    )


def test_child_environment_is_allowlisted_and_drops_poisoned_operator_state(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    private = tmp_path / "private"
    poison = {
        "CI": "true",
        "HTTP_PROXY": "http://attacker",
        "DATABASE_URL": "postgres://attacker",
        "OPENAI_API_KEY": "secret",
        "GIT_CONFIG_GLOBAL": "/tmp/evil",
        "PLAYWRIGHT_BROWSERS_PATH": "/opt/playwright-browsers",
    }

    environment, policy = materializer._child_environment(
        snapshot,
        private,
        dependency_root=Path("/opt/ea-dependencies"),
        real_browser=True,
        operator_env=poison,
    )

    assert sorted(environment) == policy["allowed_keys"]
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/playwright-browsers"
    for forbidden in (
        "CI",
        "HTTP_PROXY",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "GIT_CONFIG_GLOBAL",
    ):
        assert forbidden not in environment
    assert policy["explicit_plugins"] == []


def test_pytest_runner_uses_normalized_argv_and_embeds_bounded_junit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "test_proof.py").write_text("def test_one(): pass\n", encoding="utf-8")
    materializer._make_tree_read_only(snapshot)
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update({"command": command, **kwargs})
        junit = Path(
            next(
                item.split("=", 1)[1]
                for item in command
                if item.startswith("--junitxml=")
            )
        )
        junit.write_text(_junit_xml(["test_one"]), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "1 passed in 0.01s", "")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)
    try:
        lane = materializer._run_pytest_cases(
            snapshot,
            python_bin="/usr/bin/python3",
            python_identity=dict(PYTHON_IDENTITY),
            dependency_root=Path("/opt/ea-dependencies"),
            private_root=tmp_path / "private",
            operator_env={"CI": "true", "HTTP_PROXY": "http://attacker"},
            test_file="test_proof.py",
            cases=["test_one"],
            real_browser=False,
            run_id=RUN_ID,
            source_revision=REVISION,
            source_tree=TREE,
        )
    finally:
        materializer._make_tree_owner_writable(snapshot)

    assert lane["status"] == "pass"
    assert (
        lane["junit_xml_sha256"]
        == hashlib.sha256(lane["junit_xml"].encode()).hexdigest()
    )
    assert lane["argv_template"] == materializer._normalized_argv_template(
        "test_proof.py", ["test_one"]
    )
    assert "-p" in captured["command"] and "no:cacheprovider" in captured["command"]
    assert "--confcutdir" in captured["command"]
    assert "CI" not in captured["env"] and "HTTP_PROXY" not in captured["env"]


def test_real_non_strict_xpass_is_blocked_by_terminal_evidence(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "test_xpass.py").write_text(
        "import pytest\n@pytest.mark.xfail(strict=False)\ndef test_xpass():\n    assert True\n",
        encoding="utf-8",
    )
    materializer._make_tree_read_only(snapshot)
    try:
        lane = materializer._run_pytest_cases(
            snapshot,
            python_bin=sys.executable,
            python_identity=dict(PYTHON_IDENTITY),
            dependency_root=Path(site.getusersitepackages()).resolve(strict=False),
            private_root=tmp_path / "private",
            operator_env={},
            test_file="test_xpass.py",
            cases=["test_xpass"],
            real_browser=False,
            run_id=RUN_ID,
            source_revision=REVISION,
            source_tree=TREE,
        )
    finally:
        materializer._make_tree_owner_writable(snapshot)

    assert lane["exit_code"] == 0, lane["output_excerpt"]
    assert lane["passed_count"] == 1
    assert lane["terminal_xpass_count"] == 1
    assert lane["xpass_count"] >= 1
    assert lane["status"] == "blocked"


@pytest.mark.parametrize(
    ("summary", "passed"),
    [
        ("2 passed in 0.01s", 2),
        ("1 passed, 1 warning in 1.00s", 1),
        ("2 passed, 2 warnings in 64.73s (0:01:04)", 2),
        ("one passed in 0.01s", -1),
        ("2 passed, 1 passed in 0.01s", -1),
        ("2 passed, 1 failed in 0.01s", -1),
        ("2 passed, 1 skipped in 0.01s", -1),
        ("2 passed, 1 skipped, 2 warnings in 64.73s (0:01:04)", -1),
    ],
)
def test_terminal_summary_parser_fails_closed(summary: str, passed: int) -> None:
    assert (
        materializer._parse_terminal_summary(summary)["terminal_passed_count"] == passed
    )


def test_junit_declared_totals_mismatch_fails_closed() -> None:
    xml_text = _junit_xml(["one"]).replace('tests="1"', 'tests="2"')
    evidence = materializer._parse_junit_xml(xml_text)
    assert evidence["junit_declared_tests_count"] == 2
    assert evidence["junit_totals_consistent"] is False


def test_current_failure_replaces_prior_pass_and_no_ci_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    output = tmp_path / "published" / "proof.json"
    materializer._atomic_write_json(output, {"status": "pass", "version": 2})
    monkeypatch.setenv("CI", "true")
    writes: list[str] = []
    original_writer = materializer._atomic_write_json

    def recording_writer(path: Path, payload: dict[str, Any]) -> None:
        writes.append(str(payload.get("phase") or payload.get("status")))
        original_writer(path, payload)

    def failing_builder(root: Path, **kwargs: Any) -> dict[str, Any]:
        del root, kwargs
        raise RuntimeError("current failure")

    monkeypatch.setattr(materializer, "_atomic_write_json", recording_writer)
    receipt = materializer.materialize_and_publish(
        repo,
        output_path=output,
        builder=failing_builder,
    )

    published = json.loads(output.read_text(encoding="utf-8"))
    assert writes == ["materializing", "error"]
    assert receipt["status"] == "blocked"
    assert published == receipt
    assert published["version"] == 3


def test_custom_in_repository_output_cannot_overwrite_source(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "tracked.py"
    source.write_text("original source\n", encoding="utf-8")
    builder_called = False

    def builder(root: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal builder_called
        del root, kwargs
        builder_called = True
        return {"status": "pass"}

    with pytest.raises(ValueError, match="custom proof outputs must be outside"):
        materializer.materialize_and_publish(
            repo,
            output_path=source,
            builder=builder,
        )

    assert builder_called is False
    assert source.read_text(encoding="utf-8") == "original source\n"


def test_initial_sentinel_failure_removes_prior_green_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    output = tmp_path / "published" / "proof.json"
    materializer._atomic_write_json(output, {"status": "pass", "version": 3})
    builder_called = False

    def failing_writer(path: Path, payload: dict[str, Any]) -> None:
        del path, payload
        raise OSError("sentinel write failed")

    def builder(root: Path, **kwargs: Any) -> dict[str, Any]:
        nonlocal builder_called
        del root, kwargs
        builder_called = True
        return {"status": "pass"}

    monkeypatch.setattr(materializer, "_atomic_write_json", failing_writer)
    with pytest.raises(OSError, match="sentinel write failed"):
        materializer.materialize_and_publish(
            repo,
            output_path=output,
            builder=builder,
        )

    assert builder_called is False
    assert not output.exists()


def test_invalidation_truncates_prior_green_when_directory_denies_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "published"
    output = directory / "proof.json"
    materializer._atomic_write_json(output, {"status": "pass", "version": 3})
    original_unlink = Path.unlink

    def permission_denied(path: Path, missing_ok: bool = False) -> None:
        if path == output:
            raise PermissionError("directory denies unlink")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", permission_denied)
    directory.chmod(0o555)
    try:
        materializer._invalidate_current_receipt(output)
    finally:
        directory.chmod(0o755)

    assert output.exists()
    assert output.read_bytes() == b""
    assert output.stat().st_mode & 0o777 == 0o600


def test_in_place_invalidation_checks_inode_before_truncating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "proof.json"
    displaced = tmp_path / "displaced.json"
    replacement = tmp_path / "replacement.json"
    output.write_text('{"status":"pass"}\n', encoding="utf-8")
    replacement.write_text("unrelated file\n", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swapping_open(path: str | bytes | Path, flags: int, mode: int = 0o777) -> int:
        nonlocal swapped
        if not swapped and Path(path) == output:
            output.rename(displaced)
            replacement.rename(output)
            swapped = True
        return original_open(path, flags, mode)

    monkeypatch.setattr(materializer.os, "open", swapping_open)
    with pytest.raises(RuntimeError, match="changed during invalidation"):
        materializer._truncate_receipt_in_place(output)

    assert swapped is True
    assert output.read_text(encoding="utf-8") == "unrelated file\n"
    assert displaced.read_text(encoding="utf-8") == '{"status":"pass"}\n'


def test_atomic_writer_replaces_complete_json_in_same_directory(tmp_path: Path) -> None:
    output = tmp_path / "proof.json"
    materializer._atomic_write_json(output, {"status": "old"})
    materializer._atomic_write_json(output, {"status": "current", "value": 3})

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "status": "current",
        "value": 3,
    }
    assert not [path for path in tmp_path.iterdir() if path.name.endswith(".tmp")]
    assert (
        materializer._output_lock_path(output, tmp_path).is_relative_to(tmp_path)
        is False
    )

    with pytest.raises(ValueError, match="Out of range float values"):
        materializer._atomic_write_json(output, {"duration_seconds": float("nan")})
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "current"


def test_git_environment_is_absolute_and_ignores_inherited_git_configuration() -> None:
    environment = materializer._git_environment()
    assert materializer.GIT_BIN == Path("/usr/bin/git")
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert "GIT_DIR" not in environment
    assert "GIT_WORK_TREE" not in environment


def test_git_source_state_ignores_generated_evidence_but_not_source_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*arguments: str) -> str:
        result = subprocess.run(
            [materializer.GIT_BIN.as_posix(), *arguments],
            cwd=repo,
            env=materializer._git_environment(),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "EA Test")
    git("config", "user.email", "ea-test@example.invalid")
    (repo / "app.py").write_text("SOURCE = 1\n", encoding="utf-8")
    design_receipt = (
        repo / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"
    )
    browser_receipt = (
        repo / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
    )
    design_receipt.parent.mkdir(parents=True)
    browser_receipt.parent.mkdir(parents=True)
    design_receipt.write_text('{"status":"blocked"}\n', encoding="utf-8")
    browser_receipt.write_text('{"status":"blocked"}\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "source")
    source_revision = git("rev-parse", "HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")

    design_receipt.write_text('{"status":"pass"}\n', encoding="utf-8")
    browser_receipt.write_text('{"status":"pass"}\n', encoding="utf-8")
    generated_dirty = materializer._git_source_state(
        repo,
        excluded_output=browser_receipt,
    )
    assert generated_dirty == {
        "revision": source_revision,
        "tree": source_tree,
        "dirty": False,
    }

    generated_looking_source = repo / "outside.generated.json"
    generated_looking_source.write_text('{"source":true}\n', encoding="utf-8")
    assert materializer._git_source_state(
        repo,
        excluded_output=browser_receipt,
    )["dirty"] is True
    generated_looking_source.unlink()

    git("add", ".")
    git("commit", "-q", "-m", "generated evidence")
    generated_commit = git("rev-parse", "HEAD")
    assert generated_commit != source_revision
    generated_committed = materializer._git_source_state(
        repo,
        excluded_output=browser_receipt,
    )
    assert generated_committed == {
        "revision": source_revision,
        "tree": source_tree,
        "dirty": False,
    }

    (repo / "app.py").write_text("SOURCE = 2\n", encoding="utf-8")
    source_dirty = materializer._git_source_state(
        repo,
        excluded_output=browser_receipt,
    )
    assert source_dirty["revision"] == source_revision
    assert source_dirty["tree"] == source_tree
    assert source_dirty["dirty"] is True

    git("add", "app.py")
    git("commit", "-q", "-m", "source change")
    source_committed = materializer._git_source_state(
        repo,
        excluded_output=browser_receipt,
    )
    assert source_committed["revision"] != source_revision
    assert source_committed["tree"] != source_tree
    assert source_committed["dirty"] is False


def test_hardened_git_readers_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        materializer,
        "_run_git",
        lambda root, arguments: subprocess.CompletedProcess(
            [materializer.GIT_BIN.as_posix(), *arguments],
            1,
            "",
            "git failed",
        ),
    )

    with pytest.raises(RuntimeError, match="canonical Git source state"):
        materializer._hardened_git_stdout(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="canonical Git worktree state"):
        materializer._hardened_git_stdout_raw(tmp_path, "status", "--porcelain=v1")


def test_git_source_state_rejects_inconsistent_worktree_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        materializer,
        "resolve_source_state_head",
        lambda root, **kwargs: REVISION,
    )
    monkeypatch.setattr(
        materializer,
        "_run_git",
        lambda root, arguments: subprocess.CompletedProcess(
            [materializer.GIT_BIN.as_posix(), *arguments],
            0,
            TREE + "\n",
            "",
        ),
    )
    monkeypatch.setattr(
        materializer,
        "source_worktree_metadata",
        lambda root, **kwargs: {
            "source_worktree_dirty": False,
            "source_dirty_count": 1,
        },
    )

    with pytest.raises(RuntimeError, match="invalid or inconsistent"):
        materializer._git_source_state(tmp_path)
