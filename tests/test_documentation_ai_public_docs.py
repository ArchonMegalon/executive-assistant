from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


materializer = _load_script(
    ROOT / "scripts" / "materialize_documentation_ai_public_docs.py",
    "materialize_documentation_ai_public_docs",
)
verifier = _load_script(
    ROOT / "scripts" / "verify_documentation_ai_public_docs.py",
    "verify_documentation_ai_public_docs",
)


def _source_openapi(*, omit_first: bool = False) -> dict[str, object]:
    paths: dict[str, object] = {}
    endpoints = dict(materializer.PUBLIC_ENDPOINTS)
    if omit_first:
        first = next(iter(endpoints))
        endpoints.pop(first)
    for path, methods in endpoints.items():
        paths[path] = {method: {"responses": {"200": {"description": "ok"}}} for method in methods}
    return {"openapi": "3.0.3", "info": {"title": "source", "version": "test"}, "paths": paths}


def test_materializer_outputs_public_openapi_from_allowlist(tmp_path: Path) -> None:
    source_path = tmp_path / "source.openapi.json"
    source_path.write_text(json.dumps(_source_openapi()), encoding="utf-8")
    package_dir = tmp_path / "docs"

    manifest = materializer.materialize_public_docs(
        package_dir=package_dir,
        source_openapi_path=source_path,
        server_url="https://api.example.test",
        require_source=True,
    )

    public_openapi = json.loads((package_dir / "api-reference" / "openapi.public.json").read_text(encoding="utf-8"))
    assert public_openapi["servers"] == [{"url": "https://api.example.test"}]
    assert set(public_openapi["paths"]) == set(materializer.PUBLIC_ENDPOINTS)
    assert manifest["published_endpoint_count"] == sum(
        len(methods) for methods in materializer.PUBLIC_ENDPOINTS.values()
    )
    serialized = json.dumps(public_openapi).lower()
    assert "/v1/codex" not in serialized
    assert "/v1/responses" not in serialized
    assert "/v1/providers/onemin" not in serialized


def test_materializer_fails_when_public_allowlist_is_stale(tmp_path: Path) -> None:
    source_path = tmp_path / "source.openapi.json"
    source_path.write_text(json.dumps(_source_openapi(omit_first=True)), encoding="utf-8")

    with pytest.raises(ValueError, match="public endpoint allowlist is stale"):
        materializer.materialize_public_docs(
            package_dir=tmp_path / "docs",
            source_openapi_path=source_path,
            require_source=True,
        )


def test_repo_documentation_ai_public_package_verifies() -> None:
    failures = verifier.verify_public_docs(ROOT / "docs-public" / "executive-assistant")
    assert failures == []


def test_documentation_ai_public_docs_are_part_of_docs_verify_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "documentation-ai-public-openapi" in makefile.splitlines()[0]
    assert "verify-documentation-ai-public-docs" in makefile.splitlines()[0]
    assert "docs-verify: verify-release-assets verify-documentation-ai-public-docs" in makefile


def test_verifier_rejects_internal_route_exposure(tmp_path: Path) -> None:
    package_dir = tmp_path / "executive-assistant"
    shutil.copytree(ROOT / "docs-public" / "executive-assistant", package_dir)
    openapi_path = package_dir / "api-reference" / "openapi.public.json"
    public_openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    public_openapi["paths"]["/v1/codex/status"] = {
        "get": {
            "summary": "Must not publish",
            "responses": {"200": {"description": "ok"}},
        }
    }
    openapi_path.write_text(json.dumps(public_openapi, indent=2), encoding="utf-8")

    failures = verifier.verify_public_docs(package_dir)

    assert any("forbidden internal path exposed: /v1/codex/status" in failure for failure in failures)
