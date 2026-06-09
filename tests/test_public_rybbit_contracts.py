from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.public_rybbit import rybbit_head_snippet, rybbit_site_id_for_hostname


_MYEXTERNALBRAIN_SITE_ID = "rybbit-site-123"


def _client(
    *,
    principal_id: str = "exec-rybbit-contract",
    public_results_enabled: bool = False,
    public_tours_enabled: bool = False,
) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "1" if public_results_enabled else "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "1" if public_tours_enabled else "0"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "1" if (public_results_enabled or public_tours_enabled) else "0"
    os.environ["EA_ENABLE_RYBBIT"] = "1"
    os.environ["RYBBIT_MYEXTERNALBRAIN_SITE_ID"] = _MYEXTERNALBRAIN_SITE_ID
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_rybbit_site_id_for_hostname_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.setenv("RYBBIT_MYEXTERNALBRAIN_SITE_ID", "configured-site-id")
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)

    assert rybbit_site_id_for_hostname("myexternalbrain.com") == "configured-site-id"


def test_rybbit_site_id_for_hostname_falls_back_to_public_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.setenv("RYBBIT_MYEXTERNALBRAIN_SITE_ID", _MYEXTERNALBRAIN_SITE_ID)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")

    assert rybbit_site_id_for_hostname("internal-ea-host") == _MYEXTERNALBRAIN_SITE_ID


def test_rybbit_head_snippet_returns_empty_for_unknown_host_without_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.delenv("RYBBIT_MYEXTERNALBRAIN_SITE_ID", raising=False)
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)

    assert rybbit_head_snippet("example.com") == ""


def test_public_result_page_includes_rybbit_snippet_for_myexternalbrain_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_RESULTS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIDE_SURFACES", "1")
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.setenv("RYBBIT_MYEXTERNALBRAIN_SITE_ID", _MYEXTERNALBRAIN_SITE_ID)
    result_dir = tmp_path / "results"
    bundle_dir = result_dir / "movie-demo"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "asset.html").write_text("<html><body>movie</body></html>", encoding="utf-8")
    (bundle_dir / "result.json").write_text(
        json.dumps(
            {
                "slug": "movie-demo",
                "title": "Movie Demo",
                "service_key": "mootion_movie",
                "summary": "Demo movie",
                "body_text": "Demo movie",
                "mime_type": "text/html",
                "viewer_kind": "html",
                "asset_relpath": "asset.html",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_RESULT_DIR", str(result_dir))

    client = _client(public_results_enabled=True)
    response = client.get("/results/movie-demo", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert 'src="https://app.rybbit.io/api/script.js"' in response.text
    assert f'data-site-id="{_MYEXTERNALBRAIN_SITE_ID}"' in response.text


def test_public_tour_page_includes_rybbit_snippet_and_csp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIDE_SURFACES", "1")
    monkeypatch.setenv("EA_ENABLE_RYBBIT", "1")
    monkeypatch.setenv("RYBBIT_MYEXTERNALBRAIN_SITE_ID", _MYEXTERNALBRAIN_SITE_ID)
    slug = "rybbit-tour"
    bundle_dir = tmp_path / slug
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "scene-01.jpg").write_bytes(b"fake-jpeg-data")
    (bundle_dir / "tour.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Rybbit Tour",
                "display_title": "Rybbit Tour",
                "scene_count": 1,
                "scenes": [
                    {
                        "name": "Living room",
                        "role": "photo",
                        "image_url": "https://example.test/original.jpg",
                        "source_url": "https://example.test/original.jpg",
                        "asset_relpath": "scene-01.jpg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_TOUR_DIR", str(tmp_path))

    client = _client(public_tours_enabled=True)
    response = client.get(f"/tours/{slug}", headers={"host": "myexternalbrain.com"})

    assert response.status_code == 200
    assert 'src="https://app.rybbit.io/api/script.js"' in response.text
    assert f'data-site-id="{_MYEXTERNALBRAIN_SITE_ID}"' in response.text
    assert "https://app.rybbit.io" in response.headers["content-security-policy"]
