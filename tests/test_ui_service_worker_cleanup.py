from __future__ import annotations

from pathlib import Path

from scripts.ui_service_worker_cleanup import cleanup_ui_service_run_dir


def test_cleanup_ui_service_run_dir_preserves_final_asset_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "result.html").write_text("ok", encoding="utf-8")
    (run_dir / "preview.png").write_bytes(b"png")
    nested = run_dir / "trace"
    nested.mkdir()
    (nested / "01-step.png").write_bytes(b"trace")

    result = cleanup_ui_service_run_dir(run_dir=run_dir, asset_path=run_dir / "result.html")

    assert result["status"] == "cleaned"
    assert (run_dir / "result.html").exists()
    assert not (run_dir / "preview.png").exists()
    assert not (nested / "01-step.png").exists()
    assert result["preserved_paths"] == ["result.html"]


def test_cleanup_ui_service_run_dir_removes_all_files_when_no_asset_is_preserved(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "debug.json").write_text("{}", encoding="utf-8")

    result = cleanup_ui_service_run_dir(run_dir=run_dir)

    assert result["status"] == "cleaned"
    assert not any(run_dir.iterdir())
