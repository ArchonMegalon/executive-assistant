from __future__ import annotations

from pathlib import Path

from app.product import service as product_service


def test_repo_script_path_prefers_repo_root_layout(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "scripts").mkdir(parents=True)
    target = repo_root / "scripts" / "materialize_release_authority_status.py"
    target.write_text("# test\n", encoding="utf-8")

    monkeypatch.setattr(product_service, "_repo_root", lambda: repo_root)

    assert product_service._repo_script_path("scripts/materialize_release_authority_status.py") == target.resolve()


def test_repo_script_path_falls_back_to_parent_of_app_root(monkeypatch, tmp_path: Path) -> None:
    host_root = tmp_path / "host"
    app_root = host_root / "ea"
    app_root.mkdir(parents=True)
    (host_root / "scripts").mkdir(parents=True)
    target = host_root / "scripts" / "materialize_release_authority_status.py"
    target.write_text("# test\n", encoding="utf-8")

    monkeypatch.setattr(product_service, "_repo_root", lambda: app_root)

    assert product_service._repo_script_path("scripts/materialize_release_authority_status.py") == target.resolve()


def test_product_design_and_public_manifest_defaults_are_repo_local(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".codex-design" / "product").mkdir(parents=True)
    monkeypatch.setattr(product_service, "_repo_root", lambda: repo_root)
    monkeypatch.delenv("CHUMMER6_DESIGN_PRODUCT_ROOT", raising=False)
    monkeypatch.delenv("EA_DESIGN_PRODUCT_ROOT", raising=False)
    monkeypatch.delenv("EA_PUBLIC_GUIDE_MANIFEST_PATH", raising=False)

    assert product_service._design_product_root() == repo_root / ".codex-design" / "product"
    assert product_service._default_public_guide_manifest_path() == repo_root / ".codex-studio/published/public_guide_manifest.generated.json"


def test_pocket_audio_archive_default_is_repo_local(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    monkeypatch.setattr(product_service, "_repo_root", lambda: repo_root)
    monkeypatch.delenv("EA_POCKET_AUDIO_ARCHIVE_ROOT", raising=False)

    archive_root = product_service._pocket_audio_archive_root()

    assert archive_root == repo_root / ".runtime" / "pocket-ai-audio"
    assert "/mnt/" + "pcloud" not in archive_root.as_posix()
