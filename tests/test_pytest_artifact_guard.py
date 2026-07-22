from __future__ import annotations

import stat
from pathlib import Path

import pytest
from tests import conftest as suite_conftest


def test_mutable_repo_artifact_restore_recovers_bytes_mode_and_absence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tracked = tmp_path / "tracked.json"
    tracked.write_bytes(b'{"state":"baseline"}\n')
    tracked.chmod(0o640)
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(suite_conftest, "_ROOT", tmp_path)
    monkeypatch.setattr(
        suite_conftest,
        "_MUTABLE_REPO_ARTIFACT_PATHS",
        ("tracked.json", "absent.json"),
    )

    baseline = suite_conftest._capture_mutable_repo_artifact_baseline()
    tracked.write_bytes(b'{"state":"mutated"}\n')
    tracked.chmod(0o600)
    absent.mkdir()
    (absent / "leak.txt").write_text("leak", encoding="utf-8")

    suite_conftest._restore_mutable_repo_artifacts(baseline)

    assert tracked.read_bytes() == b'{"state":"baseline"}\n'
    assert stat.S_IMODE(tracked.stat().st_mode) == 0o640
    assert not absent.exists()


def test_mutable_repo_artifact_restore_replaces_symlink_without_touching_target(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tracked = tmp_path / "tracked.json"
    tracked.write_bytes(b"baseline\n")
    target = tmp_path / "outside.json"
    target.write_bytes(b"outside\n")
    monkeypatch.setattr(suite_conftest, "_ROOT", tmp_path)
    monkeypatch.setattr(
        suite_conftest,
        "_MUTABLE_REPO_ARTIFACT_PATHS",
        ("tracked.json",),
    )

    baseline = suite_conftest._capture_mutable_repo_artifact_baseline()
    tracked.unlink()
    tracked.symlink_to(target)

    suite_conftest._restore_mutable_repo_artifacts(baseline)

    assert tracked.is_file()
    assert not tracked.is_symlink()
    assert tracked.read_bytes() == b"baseline\n"
    assert target.read_bytes() == b"outside\n"


def test_mutable_repo_artifact_restore_keeps_existing_file_if_replace_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tracked = tmp_path / "tracked.json"
    tracked.write_bytes(b"baseline\n")
    monkeypatch.setattr(suite_conftest, "_ROOT", tmp_path)
    monkeypatch.setattr(
        suite_conftest,
        "_MUTABLE_REPO_ARTIFACT_PATHS",
        ("tracked.json",),
    )
    baseline = suite_conftest._capture_mutable_repo_artifact_baseline()
    tracked.write_bytes(b"mutated\n")

    def _fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(suite_conftest.os, "replace", _fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        suite_conftest._restore_mutable_repo_artifacts(baseline)

    assert tracked.read_bytes() == b"mutated\n"
    assert list(tmp_path.iterdir()) == [tracked]
