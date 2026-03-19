from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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
    assert matrix["artifacts"][0]["platform"] == "windows"
    assert matrix["artifacts"][0]["kind"] == "archive"
    assert matrix["artifacts"][1]["platform"] == "macos"
    assert matrix["artifacts"][1]["arch"] == "arm64"
    assert matrix["artifacts"][1]["kind"] == "dmg"
