from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "sync_memorial_public_sources_to_teable.py"
    spec = importlib.util.spec_from_file_location("sync_memorial_public_sources_to_teable", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_configured_base_url_prefers_env(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("TEABLE_BASE_URL", "https://teable.example")
    assert module._configured_base_url() == "https://teable.example"


def test_default_memorial_paths_are_slug_or_explicit_env_driven(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setenv("MEMORIAL_PUBLIC_SLUG", "sample-person")

    assert module._default_memorial_path() == module.ROOT / "memorial_data" / "public_memorials" / "sample-person" / "memorial.json"
    assert (
        module._default_private_profile_path()
        == module.ROOT / "memorial_data" / "private_memorial_profiles" / "sample-person" / "llm_profile_notes.json"
    )

    explicit_memorial = tmp_path / "memorial.json"
    explicit_private = tmp_path / "profile.json"
    monkeypatch.setenv("EA_MEMORIAL_PUBLIC_SOURCE_JSON", str(explicit_memorial))
    monkeypatch.setenv("EA_MEMORIAL_PUBLIC_SOURCE_PRIVATE_PROFILE_JSON", str(explicit_private))

    assert module._default_memorial_path() == explicit_memorial
    assert module._default_private_profile_path() == explicit_private


def test_build_rows_uses_configured_default_slug_when_memorial_has_no_slug(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("EA_MEMORIAL_PUBLIC_SOURCE_SLUG", "portable-person")

    rows = module._build_rows(
        memorial={"source_grounded_profile": [{"trait": "voice", "evidence": "grounded", "confidence": "high"}]},
        private_profile={"public_source_notes": [{"label": "note", "note": "public source", "confidence": "medium"}]},
    )

    assert {row["memorial_slug"] for row in rows} == {"portable-person"}
    assert all(row["projection_key"].startswith("portable-person:") for row in rows)


def test_memorial_source_teable_sync_has_no_baked_table_id() -> None:
    source = (ROOT / "scripts" / "sync_memorial_public_sources_to_teable.py").read_text(encoding="utf-8")

    assert "tblnD8Ue8GDfsuus1Ym" not in source
    assert "teable_table_id_missing" in source
