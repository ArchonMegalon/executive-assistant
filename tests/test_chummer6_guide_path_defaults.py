from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chummer6_guide_canon_uses_local_design_mirror_without_host_fallback() -> None:
    source = (ROOT / "scripts" / "chummer6_guide_canon.py").read_text(encoding="utf-8")

    assert ".codex-design" in source
    assert "CHUMMER6_DESIGN_PRODUCT_ROOT" in source
    assert "/docker/chummercomplete" not in source
    assert "DEFAULT_DESIGN_ROOT" not in source


def test_chummer6_guide_workers_default_to_repo_local_paths() -> None:
    media = (ROOT / "scripts" / "chummer6_guide_media_worker.py").read_text(encoding="utf-8")
    worker = (ROOT / "scripts" / "chummer6_guide_worker.py").read_text(encoding="utf-8")

    assert ".codex-studio" in media
    assert "third_party" in media
    assert "chummer6_guide" in media
    assert "CHUMMER6_REPO_ROOT" in media
    assert "CHUMMER6_GUIDE_ROOT" in worker
    assert "chummer6_guide" in worker
    assert "/docker/chummercomplete" not in media
    assert "/docker/fleet" not in media
    assert "/docker/chummercomplete" not in worker
