from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mootion_movie_worker.py"


def _load_module():
    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("mootion_movie_worker", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_mootion_run_dir_keeps_final_webm(tmp_path: Path) -> None:
    module = _load_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in ("storyboard-01.jpg", "storyboard-02.jpg", "storyboard-subtitles.srt", "preview.png", "movie.mp4", "movie.webm"):
        (run_dir / name).write_bytes(b"x" * 8)

    result = module.cleanup_mootion_run_dir(run_dir=run_dir, asset_path=run_dir / "movie.webm")

    assert result["status"] == "cleaned"
    assert not (run_dir / "storyboard-01.jpg").exists()
    assert not (run_dir / "storyboard-02.jpg").exists()
    assert not (run_dir / "storyboard-subtitles.srt").exists()
    assert not (run_dir / "preview.png").exists()
    assert not (run_dir / "movie.mp4").exists()
    assert (run_dir / "movie.webm").exists()
