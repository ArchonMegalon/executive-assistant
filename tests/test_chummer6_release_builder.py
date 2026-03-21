from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "chummer6_release_builder.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("chummer6_release_builder", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_release_matrix_normalizes_platform_arch_and_kind(tmp_path: Path) -> None:
    builder = _load_module()
    manifest = tmp_path / "releases.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "v-test",
                "channel": "preview",
                "publishedAt": "2026-03-19T18:00:00Z",
                "downloads": [
                    {
                        "id": "avalonia-osx-arm64",
                        "platform": "Chummer 6 Avalonia macOS ARM64",
                        "url": "/downloads/files/chummer-osx-arm64.dmg",
                        "sha256": "abc",
                        "sizeBytes": 42,
                    },
                    {
                        "id": "avalonia-win-x64",
                        "platform": "Chummer 6 Avalonia Windows x64",
                        "url": "/downloads/files/chummer-win-x64.zip",
                        "sha256": "def",
                        "sizeBytes": 84,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    matrix = builder.build_release_matrix(manifest_path=manifest, base_url="https://chummer.run")

    assert matrix["version"] == "v-test"
    assert len(matrix["artifacts"]) == 2
    assert matrix["archiveOnly"] is False
    assert matrix["primaryArtifactKind"] == "dmg"
    assert matrix["frontDoorDownloadPosture"] == "preview_artifacts_available"
    assert matrix["primaryArtifactConsumerReady"] is True
    assert matrix["frontDoorPrimaryCtaEligible"] is True
    assert matrix["artifacts"][0]["platform"] == "windows"
    assert matrix["artifacts"][0]["kind"] == "archive"
    assert matrix["artifacts"][1]["platform"] == "macos"
    assert matrix["artifacts"][1]["arch"] == "arm64"
    assert matrix["artifacts"][1]["kind"] == "dmg"


def test_build_release_matrix_demotes_archive_only_shelves(tmp_path: Path) -> None:
    builder = _load_module()
    manifest = tmp_path / "releases.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "v-archive",
                "channel": "preview",
                "publishedAt": "2026-03-21T02:00:00Z",
                "downloads": [
                    {
                        "id": "avalonia-win-x64",
                        "platform": "Chummer 6 Avalonia Windows x64",
                        "url": "/downloads/files/chummer-win-x64.zip",
                        "sha256": "def",
                        "sizeBytes": 84,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    matrix = builder.build_release_matrix(manifest_path=manifest, base_url="https://chummer.run")

    assert matrix["archiveOnly"] is True
    assert matrix["primaryArtifactKind"] == "archive"
    assert matrix["primaryArtifactConsumerReady"] is False
    assert matrix["frontDoorDownloadPosture"] == "advanced_manual_preview_only"
    assert matrix["frontDoorPrimaryCtaEligible"] is False


def test_default_manifest_path_honors_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    builder = _load_module()
    custom_manifest = tmp_path / "custom-releases.json"
    monkeypatch.setenv("CHUMMER6_RELEASE_MANIFEST_PATH", str(custom_manifest))

    assert builder.default_manifest_path() == custom_manifest


def test_default_manifest_path_prefers_first_existing_candidate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    builder = _load_module()
    first = tmp_path / "preferred.json"
    second = tmp_path / "fallback.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("CHUMMER6_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.setattr(builder, "DEFAULT_MANIFEST_CANDIDATES", (first, second))

    assert builder.default_manifest_path() == first
