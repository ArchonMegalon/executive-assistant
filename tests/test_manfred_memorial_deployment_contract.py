from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from scripts import build_manfred_memorial_image as image_builder
from scripts import deploy_ea_memorial as memorial_deploy
from scripts import prepare_manfred_memorial_candidate as candidate_prep
from scripts import run_manfred_memorial_candidate as candidate_runner
from scripts import verify_manfred_memorial_candidate as candidate_verify


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy/manfred-memorial/docker-compose.candidate.yml"
PROJECT = "ea-manfred-candidate-deployment-contract-a1b2c3d4"
COMMIT = "a" * 40


def test_production_memorial_compose_is_image_pure_and_numeric_nonroot() -> None:
    raw = (ROOT / "docker-compose.memorial.yml").read_text(encoding="utf-8")

    assert 'user: "10001:10001"' in raw
    assert "volumes: !override" in raw
    assert raw.count("${EA_MEMORIAL_DATA_HOST_PATH:?") == 1
    assert raw.count("${EA_MEMORIAL_RUNTIME_HOST_PATH:?") == 3
    assert "ea_artifacts:/data/artifacts" in raw
    for forbidden in (
        "/app/app",
        "/app/scripts",
        "/app/.codex",
        "/app/config",
        "/run/secrets",
        "./ea/",
        "./scripts/",
    ):
        assert forbidden not in raw


def test_projection_digest_matches_the_in_container_verifier(tmp_path: Path) -> None:
    root = tmp_path / "projection"
    nested = root / "public_memorials" / "manfred"
    nested.mkdir(parents=True)
    payload = nested / "memorial.json"
    payload.write_text('{"slug":"manfred"}\n', encoding="utf-8")
    payload.chmod(0o444)
    nested.chmod(0o550)
    nested.parent.chmod(0o550)
    root.chmod(0o550)

    projection_sha256, rows = candidate_prep._tree_digest(root)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            memorial_deploy.CONTAINER_PROJECTION_DIGEST_SCRIPT,
            str(root),
            str(len(rows)),
            str(sum(int(item["size_bytes"]) for item in rows)),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "projection_sha256": projection_sha256,
        "file_count": len(rows),
        "projection_bytes": sum(int(item["size_bytes"]) for item in rows),
    }


def test_projection_digest_rejects_multiply_linked_files(tmp_path: Path) -> None:
    root = tmp_path / "projection"
    root.mkdir()
    source = root / "source.json"
    source.write_text("{}\n", encoding="utf-8")
    alias = root / "alias.json"
    os.link(source, alias)
    source.chmod(0o444)
    root.chmod(0o550)

    with pytest.raises(
        ValueError,
        match="manfred_candidate_projection_file_links_invalid",
    ):
        candidate_prep._tree_digest(root)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            memorial_deploy.CONTAINER_PROJECTION_DIGEST_SCRIPT,
            str(root),
            "2",
            str(source.stat().st_size * 2),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 15


def test_in_container_projection_digest_rejects_declared_budget_overrun(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projection"
    root.mkdir()
    payload = root / "huge-sparse.bin"
    with payload.open("wb") as handle:
        handle.truncate(1024 * 1024 * 1024)
    payload.chmod(0o444)
    root.chmod(0o550)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            memorial_deploy.CONTAINER_PROJECTION_DIGEST_SCRIPT,
            str(root),
            "1",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 16


def test_projection_digest_rejects_content_changes_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "projection"
    root.mkdir()
    payload = root / "memorial.json"
    payload.write_bytes(b"a" * (2 * 1024 * 1024))
    payload.chmod(0o444)
    root.chmod(0o550)
    original_read = candidate_prep.os.read
    changed = False

    def mutate_then_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        if not changed:
            changed = True
            payload.chmod(0o644)
            with payload.open("ab") as handle:
                handle.write(b"changed")
            payload.chmod(0o444)
        return original_read(descriptor, size)

    monkeypatch.setattr(candidate_prep.os, "read", mutate_then_read)
    with pytest.raises(
        ValueError,
        match="manfred_candidate_projection_changed_during_digest",
    ):
        candidate_prep._tree_digest(root)


def test_candidate_compose_is_image_pure_isolated_and_provider_free() -> None:
    payload = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = payload["services"]
    api = services["api"]

    assert "build" not in api
    assert "container_name" not in api
    assert api["pull_policy"] == "never"
    assert api["user"] == "10001:10001"
    assert api["read_only"] is True
    assert api["cap_drop"] == ["ALL"]
    assert api["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in api
    assert api["networks"] == ["backend"]
    assert payload["networks"]["backend"]["internal"] is True
    assert payload["networks"]["ingress"] is None

    gateway = services["gateway"]
    assert gateway["image"] == api["image"]
    assert "env_file" not in gateway
    assert "environment" not in gateway
    assert gateway["networks"] == ["backend", "ingress"]
    assert gateway["ports"] == ["127.0.0.1:${EA_MANFRED_HOST_PORT:-18090}:18090"]

    environment = api["environment"]
    assert environment["EA_RUNTIME_MODE"] == "prod"
    assert environment["EA_SOURCE_REVISION"].startswith("${EA_MANFRED_COMMIT")
    assert environment["EA_RELEASE_AUTHORITY_STATUS_PATH"] == (
        "/data/release-authority/release_authority_status.generated.json"
    )
    assert environment["EA_RELEASE_MANIFEST_PATH"] == (
        "/data/release-authority/release_manifest.generated.json"
    )
    assert environment["EA_DEPLOY_CONTEXT_PATH"] == (
        "/data/release-authority/deploy_context.generated.json"
    )
    assert environment["EA_PROJECT_MODES_MANIFEST_PATH"] == (
        "/data/release-authority/PROJECT_MODES.generated.json"
    )
    assert environment["EA_DEPLOY_PRIMARY_MODE"] == "MEMORIAL"
    assert environment["EA_DEPLOY_ENABLED_MODES"] == "MEMORIAL,PROPERTY"
    assert environment["EA_DEPLOY_COMPOSE_FILES"] == (
        "deploy/manfred-memorial/docker-compose.candidate.yml"
    )
    assert environment["EA_STORAGE_BACKEND"] == "postgres"
    assert environment["EA_ENABLE_LEGACY_RUNTIME_SURFACES"] == "1"
    assert environment["PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES"] == "1"
    assert environment["EA_ENABLE_PUBLIC_TOURS"] == "1"
    assert environment["PROPERTYQUARRY_ENABLE_PUBLIC_TOURS"] == "1"
    assert environment["EA_ENABLE_PUBLIC_MEMORIALS"] == "1"
    assert environment["EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES"] == "0"
    assert environment["EA_PUBLIC_MEMORIAL_RATE_BACKEND"] == "redis"
    assert environment["EA_MEMORIAL_PAGE_PREWARM_ENABLED"] == "0"
    assert environment["EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED"] == "0"
    assert environment["EA_AUDIOBOOK_UNMIXR_AUTO_RENDER"] == "0"
    assert environment["EA_AUDIOBOOKSHELF_AUTO_IMPORT"] == "0"
    assert environment["EA_ALLOW_LOOPBACK_NO_AUTH"] == "0"
    assert environment["EA_TRUST_PROXY_HEADERS"] == "1"
    assert "EA_TRUSTED_PROXY_CIDRS" not in environment
    assert "PROPERTYQUARRY_TRUSTED_PROXY_CIDRS" not in environment
    assert environment["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] == "0"
    assert environment["EA_TRUST_API_TOKEN_PRINCIPAL_HEADER"] == "0"
    assert environment["PYTHONPATH"] == "/app"
    authority_mounts = [
        mount
        for mount in api["volumes"]
        if str(mount).endswith(":/data/release-authority:ro")
    ]
    assert len(authority_mounts) == 1

    assert (
        environment["EA_PUBLIC_MEMORIAL_DIR"]
        != environment["EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR"]
    )
    assert (
        environment["EA_PRIVATE_MEMORIAL_PROFILE_DIR"]
        != environment["EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR"]
    )
    rendered = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "/docker/EA" not in rendered
    assert "ea_default" not in rendered
    assert "docker.sock" not in rendered
    assert "/app/app/api/routes" not in rendered
    assert "/app/app/services" not in rendered
    assert services["postgres"]["image"].count("@sha256:") == 1
    assert services["redis"]["image"].count("@sha256:") == 1


def test_candidate_verifier_accepts_exact_unpublished_archive_gate() -> None:
    requests: list[tuple[str, str, set[int]]] = []

    def request(
        base_url: str,
        path: str,
        *,
        expected: set[int],
    ) -> tuple[int, bytes, dict[str, str]]:
        requests.append((base_url, path, expected))
        return (
            404,
            json.dumps(
                {
                    "detail": "memorial_not_found",
                    "archive_gate": {
                        "schema": "ea.memorial_archive_gate.v1",
                        "state": "intentionally_unpublished",
                        "slug": "manfred",
                        "registry_sha256": "a" * 64,
                    },
                }
            ).encode("utf-8"),
            {"content-type": "application/json"},
        )

    evidence = candidate_verify._verify_memorial_archive_gate(
        "https://memorial.example.test",
        request_fn=request,
    )

    assert requests == [
        (
            "https://memorial.example.test",
            "/memorials/manfred/archive.json",
            {404},
        )
    ]
    assert evidence == {
        "schema": "ea.memorial_archive_gate.v1",
        "state": "intentionally_unpublished",
        "slug": "manfred",
        "registry_sha256": "a" * 64,
        "http_status": 404,
        "publication_authority": False,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "ea.memorial_archive_gate.v0"),
        ("state", "published"),
        ("slug", "someone-else"),
        ("registry_sha256", "not-a-digest"),
    ],
)
def test_candidate_verifier_rejects_unattested_archive_gate(
    field: str,
    value: str,
) -> None:
    gate = {
        "schema": "ea.memorial_archive_gate.v1",
        "state": "intentionally_unpublished",
        "slug": "manfred",
        "registry_sha256": "b" * 64,
    }
    gate[field] = value

    def request(
        _base_url: str,
        _path: str,
        *,
        expected: set[int],
    ) -> tuple[int, bytes, dict[str, str]]:
        assert expected == {404}
        return (
            404,
            json.dumps({"detail": "memorial_not_found", "archive_gate": gate}).encode(
                "utf-8"
            ),
            {"content-type": "application/json"},
        )

    with pytest.raises(
        RuntimeError,
        match="candidate_memorial_archive_gate_invalid",
    ):
        candidate_verify._verify_memorial_archive_gate(
            "https://memorial.example.test",
            request_fn=request,
        )


def test_candidate_verifier_rejects_noncanonical_or_overexposed_archive_gate() -> None:
    canonical_gate = {
        "schema": "ea.memorial_archive_gate.v1",
        "state": "intentionally_unpublished",
        "slug": "manfred",
        "registry_sha256": "c" * 64,
    }
    canonical_payload = {
        "detail": "memorial_not_found",
        "archive_gate": canonical_gate,
    }
    cases = [
        (
            {**canonical_payload, "archive_sections": [{"private": "leak"}]},
            {"content-type": "application/json"},
        ),
        (
            {
                **canonical_payload,
                "archive_gate": {**canonical_gate, "unexpected": "field"},
            },
            {"content-type": "application/json"},
        ),
        (
            {
                **canonical_payload,
                "archive_gate": {
                    **canonical_gate,
                    "registry_sha256": "C" * 64,
                },
            },
            {"content-type": "application/json"},
        ),
        (canonical_payload, {"content-type": "text/html"}),
    ]

    for payload, headers in cases:

        def request(
            _base_url: str,
            _path: str,
            *,
            expected: set[int],
        ) -> tuple[int, bytes, dict[str, str]]:
            assert expected == {404}
            return 404, json.dumps(payload).encode("utf-8"), headers

        with pytest.raises(
            RuntimeError,
            match="candidate_memorial_archive_gate_invalid",
        ):
            candidate_verify._verify_memorial_archive_gate(
                "https://memorial.example.test",
                request_fn=request,
            )


def test_verify_candidate_wires_archive_publication_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    alias_calls: list[dict[str, object]] = []
    transport_calls: list[dict[str, object]] = []

    monkeypatch.setattr(candidate_verify, "_wait_for_health", lambda *_args: None)
    monkeypatch.setattr(
        candidate_verify,
        "_verify_memorial_transport_security",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        candidate_verify,
        "verify_conversation_only_page_html",
        lambda _body: {"status": "pass"},
    )

    def singular_alias(
        base_url: str,
        public_origin: str,
        *,
        request_fn: object,
    ) -> None:
        alias_calls.append(
            {
                "base_url": base_url,
                "public_origin": public_origin,
                "request_fn": request_fn,
            }
        )

    monkeypatch.setattr(
        candidate_verify, "_verify_singular_memorial_alias", singular_alias
    )

    def request(
        _base_url: str,
        path: str,
        **_kwargs: object,
    ) -> tuple[int, bytes, dict[str, str]]:
        if path == "/memorials/manfred.json":
            return (
                200,
                b'{"slug":"manfred"}',
                {"x-content-type-options": "nosniff"},
            )
        if path == "/memorials/manfred":
            return 200, b"<!doctype html><html></html>", {
                "x-content-type-options": "nosniff"
            }
        return 200, b"", {}

    def archive_gate(base_url: str) -> dict[str, object]:
        called.append(base_url)
        raise RuntimeError("archive_gate_wiring_reached")

    def transport_request(  # type: ignore[no-untyped-def]
        base_url,
        path,
        **kwargs,
    ):
        transport_calls.append({"base_url": base_url, "path": path, **kwargs})
        return 200, b"", {}

    monkeypatch.setattr(candidate_verify, "_request", request)
    monkeypatch.setattr(
        candidate_verify,
        "_verify_memorial_archive_gate",
        archive_gate,
    )

    with pytest.raises(RuntimeError, match="archive_gate_wiring_reached"):
        candidate_verify.verify_candidate(
            base_url="https://memorial.example.test",
            public_origin="https://memorial.example.test",
            wait_seconds=1,
            submit_receipt=None,
            withdraw_receipt=None,
            transport_request=transport_request,
        )

    assert called == ["https://memorial.example.test"]
    assert alias_calls == [
        {
            "base_url": "https://memorial.example.test",
            "public_origin": "https://memorial.example.test",
            "request_fn": transport_request,
        }
    ]
    assert transport_calls == [
        {
            "base_url": "https://memorial.example.test",
            "path": "/memorials/manfred",
            "method": "HEAD",
            "headers": {
                "Host": "memorial.example.test",
                "X-Forwarded-Host": "memorial.example.test",
                "X-Forwarded-Proto": "https",
            },
            "expected": {200},
            "follow_redirects": False,
        }
    ]


def test_candidate_keeps_governed_spatial_http_routes_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "EA_ENABLE_LEGACY_RUNTIME_SURFACES",
        "PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES",
        "EA_ENABLE_PUBLIC_TOURS",
        "PROPERTYQUARRY_ENABLE_PUBLIC_TOURS",
        "EA_ENABLE_PUBLIC_MEMORIALS",
        "PROPERTYQUARRY_ENABLE_PUBLIC_MEMORIALS",
    ):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("EA_RUNTIME_MODE", "dev")

    from app.api.app import create_app

    with pytest.warns(UserWarning, match="Duplicate Operation ID public_tour_page"):
        paths = create_app().openapi()["paths"]

    assert "/tours/viewer/{slug}/{asset_path}" in paths
    assert "/v1/internal/governed-spatial-render/compose" not in paths
    assert "/v1/internal/governed-spatial-render/build" not in paths


def test_public_memorial_singular_alias_is_permanent_safe_and_schema_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_origin = "https://memorial.example.test"
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", public_origin)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.public_memorial_surface import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, base_url=public_origin)

    for method in ("GET", "HEAD"):
        response = client.request(
            method,
            "/memorial/manfred?from=family",
            follow_redirects=False,
        )
        assert response.status_code == 308
        assert response.headers["location"] == "/memorials/manfred?from=family"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        if method == "HEAD":
            assert response.content == b""

    duplicate_query = client.get(
        "/memorial/manfred?tag=one&tag=two",
        follow_redirects=False,
    )
    assert duplicate_query.headers["location"] == ("/memorials/manfred?tag=one&tag=two")

    for unsafe_path in (
        "/memorial/a%3Fb",
        "/memorial/a%23b",
        "/memorial/a%2Fb",
        "/memorial/a%5Cb",
        "/memorial/a%0D%0ALocation%3Aevil",
    ):
        rejected = client.get(unsafe_path, follow_redirects=False)
        assert rejected.status_code == 404
        assert "location" not in rejected.headers

    assert "/memorial/manfred" not in app.openapi()["paths"]


def test_candidate_alias_verifier_inspects_exact_get_and_head_first_hops() -> None:
    observed: list[dict[str, object]] = []

    def fake_request(  # type: ignore[no-untyped-def]
        base_url,
        path,
        *,
        method="GET",
        expected=None,
        follow_redirects=True,
        headers=None,
        **_kwargs,
    ):
        observed.append(
            {
                "base_url": base_url,
                "path": path,
                "method": method,
                "headers": dict(headers or {}),
                "follow_redirects": follow_redirects,
                "expected": set(expected or set()),
            }
        )
        return (
            308,
            b"" if method == "HEAD" else b"Permanent Redirect",
            {
                "location": "/memorials/manfred?from=ea-launch-verifier",
                "cache-control": "no-store",
                "referrer-policy": "no-referrer",
                "x-content-type-options": "nosniff",
                "x-robots-tag": "noindex, nofollow",
            },
        )

    candidate_verify._verify_singular_memorial_alias(
        "http://127.0.0.1:8090",
        "https://myexternalbrain.com",
        request_fn=fake_request,
    )

    assert observed == [
        {
            "base_url": "http://127.0.0.1:8090",
            "path": "/memorial/manfred?from=ea-launch-verifier",
            "method": "GET",
            "headers": {
                "Host": "myexternalbrain.com",
                "X-Forwarded-Host": "myexternalbrain.com",
                "X-Forwarded-Proto": "https",
            },
            "follow_redirects": False,
            "expected": {308},
        },
        {
            "base_url": "http://127.0.0.1:8090",
            "path": "/memorial/manfred?from=ea-launch-verifier",
            "method": "HEAD",
            "headers": {
                "Host": "myexternalbrain.com",
                "X-Forwarded-Host": "myexternalbrain.com",
                "X-Forwarded-Proto": "https",
            },
            "follow_redirects": False,
            "expected": {308},
        },
    ]


def test_candidate_transport_verifier_proves_gateway_cookie_hsts_and_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def fake_request(  # type: ignore[no-untyped-def]
        base_url,
        path,
        *,
        headers=None,
        expected=None,
        follow_redirects=True,
        **_kwargs,
    ):
        observed.append(
            {
                "base_url": base_url,
                "path": path,
                "headers": dict(headers or {}),
                "expected": set(expected or set()),
                "follow_redirects": follow_redirects,
            }
        )
        if (headers or {}).get("X-Forwarded-Proto") == "https":
            return (
                200,
                b"memorial",
                {
                    "set-cookie": (
                        "ea_memorial_guest=redacted; HttpOnly; Max-Age=31536000; "
                        "Path=/memorials/manfred; SameSite=Lax; Secure"
                    ),
                    "strict-transport-security": "max-age=31536000",
                },
            )
        return (
            308,
            b"Permanent Redirect",
            {
                "location": (
                    "https://myexternalbrain.com/memorials/manfred"
                    "?from=ea-transport-verifier"
                )
            },
        )

    monkeypatch.setattr(candidate_verify, "_request", fake_request)

    evidence = candidate_verify._verify_memorial_transport_security(
        "http://127.0.0.1:18095",
        "https://myexternalbrain.com",
    )

    assert evidence == {
        "status": "pass",
        "public_origin": "https://myexternalbrain.com",
        "proxy_scheme_headers_consistent": True,
        "cookie": {
            "name": "ea_memorial_guest",
            "secure": True,
            "http_only": True,
            "same_site": "Lax",
            "path": "/memorials/manfred",
            "max_age_seconds": 31_536_000,
        },
        "hsts": "max-age=31536000",
        "http_redirect_status": 308,
        "http_redirect_location": (
            "https://myexternalbrain.com/memorials/manfred?from=ea-transport-verifier"
        ),
    }
    assert observed == [
        {
            "base_url": "http://127.0.0.1:18095",
            "path": "/memorials/manfred",
            "headers": {
                "Host": "myexternalbrain.com",
                "X-Forwarded-Host": "myexternalbrain.com",
                "X-Forwarded-Proto": "https",
                "CF-Visitor": '{"scheme":"https"}',
            },
            "expected": {200},
            "follow_redirects": False,
        },
        {
            "base_url": "http://127.0.0.1:18095",
            "path": "/memorials/manfred?from=ea-transport-verifier",
            "headers": {"Host": "myexternalbrain.com"},
            "expected": {308},
            "follow_redirects": False,
        },
    ]


def test_candidate_transport_verifier_does_not_model_http_over_canonical_https() -> (
    None
):
    observed: list[dict[str, object]] = []

    def fake_request(  # type: ignore[no-untyped-def]
        base_url,
        path,
        *,
        headers=None,
        expected=None,
        follow_redirects=True,
        **_kwargs,
    ):
        observed.append(
            {
                "base_url": base_url,
                "path": path,
                "headers": dict(headers or {}),
                "expected": set(expected or set()),
                "follow_redirects": follow_redirects,
            }
        )
        return (
            200,
            b"memorial",
            {
                "set-cookie": (
                    "ea_memorial_guest=redacted; HttpOnly; Max-Age=31536000; "
                    "Path=/memorials/manfred; SameSite=Lax; Secure"
                ),
                "strict-transport-security": "max-age=31536000",
            },
        )

    evidence = candidate_verify._verify_memorial_transport_security(
        "https://myexternalbrain.com",
        "https://myexternalbrain.com",
        request_fn=fake_request,
    )

    assert evidence["status"] == "pass"
    assert evidence["http_redirect_probe"] == "not_applicable_to_https_base"
    assert "http_redirect_status" not in evidence
    assert observed == [
        {
            "base_url": "https://myexternalbrain.com",
            "path": "/memorials/manfred",
            "headers": {
                "Host": "myexternalbrain.com",
                "X-Forwarded-Host": "myexternalbrain.com",
                "X-Forwarded-Proto": "https",
                "CF-Visitor": '{"scheme":"https"}',
            },
            "expected": {200},
            "follow_redirects": False,
        }
    ]


def test_candidate_head_verifier_uses_exact_canonical_transport_headers() -> None:
    observed: list[dict[str, object]] = []

    def fake_request(  # type: ignore[no-untyped-def]
        base_url,
        path,
        **kwargs,
    ):
        observed.append({"base_url": base_url, "path": path, **kwargs})
        return 200, b"", {}

    candidate_verify._verify_memorial_head_surface(
        "http://127.0.0.1:8090",
        "https://myexternalbrain.com",
        request_fn=fake_request,
    )

    assert observed == [
        {
            "base_url": "http://127.0.0.1:8090",
            "path": "/memorials/manfred",
            "method": "HEAD",
            "headers": {
                "Host": "myexternalbrain.com",
                "X-Forwarded-Host": "myexternalbrain.com",
                "X-Forwarded-Proto": "https",
            },
            "expected": {200},
            "follow_redirects": False,
        }
    ]


@pytest.mark.parametrize(
    "set_cookie",
    [
        "ea_memorial_guest=redacted; HttpOnly; Path=/memorials/manfred; SameSite=Lax",
        "ea_memorial_guest=redacted; Max-Age=31536000; Path=/memorials/manfred; SameSite=Lax; Secure",
        "ea_memorial_guest=redacted; HttpOnly; Max-Age=31536000; Path=/; SameSite=Lax; Secure",
    ],
)
def test_candidate_transport_verifier_rejects_incomplete_cookie(
    monkeypatch: pytest.MonkeyPatch,
    set_cookie: str,
) -> None:
    monkeypatch.setattr(
        candidate_verify,
        "_request",
        lambda *_args, **_kwargs: (
            200,
            b"memorial",
            {
                "set-cookie": set_cookie,
                "strict-transport-security": "max-age=31536000",
            },
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="candidate_memorial_transport_cookie_invalid",
    ):
        candidate_verify._verify_memorial_transport_security(
            "http://127.0.0.1:18095",
            "https://myexternalbrain.com",
        )


def test_no_redirect_clients_observe_308_without_requesting_canonical_target() -> None:
    observed: list[tuple[str, str]] = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def _respond(self, *, include_body: bool) -> None:
            observed.append((self.command, self.path))
            if self.path.startswith("/memorials/"):
                self.send_response(418)
                self.end_headers()
                return
            self.send_response(308)
            self.send_header(
                "Location",
                "/memorials/manfred?from=ea-launch-verifier",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.end_headers()
            if include_body:
                self.wfile.write(b"Permanent Redirect")

        def do_GET(self) -> None:  # noqa: N802
            self._respond(include_body=True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._respond(include_body=False)

        def log_message(self, format_string: str, *args: object) -> None:
            del format_string, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        origin = f"http://{host}:{port}"
        candidate_verify._verify_singular_memorial_alias(
            origin,
            "https://myexternalbrain.com",
        )
        for method in ("GET", "HEAD"):
            response = memorial_deploy._default_http_no_redirect(
                f"{origin}/memorial/manfred?from=ea-launch-verifier",
                5,
                method,
            )
            assert response.status == 308
            assert response.headers is not None
            assert response.headers["Location"] == (
                "/memorials/manfred?from=ea-launch-verifier"
            )
            if method == "HEAD":
                assert response.body == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert observed == [
        ("GET", "/memorial/manfred?from=ea-launch-verifier"),
        ("HEAD", "/memorial/manfred?from=ea-launch-verifier"),
        ("GET", "/memorial/manfred?from=ea-launch-verifier"),
        ("HEAD", "/memorial/manfred?from=ea-launch-verifier"),
    ]


def test_docker_context_excludes_secret_and_memorial_material() -> None:
    lines = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    }
    assert {".env", ".env.*", "memorial_data/**", "memorial_archive/**"} <= lines


@pytest.mark.parametrize("tag", ["latest", "ea-runtime:latest", " Latest "])
def test_image_builder_rejects_mutable_tags(tag: str) -> None:
    with pytest.raises(ValueError, match="manfred_image_mutable_tag_forbidden"):
        image_builder._safe_tag(tag, commit="a" * 40)


def test_candidate_projection_rejects_unsafe_paths_and_classifies_private_audio() -> (
    None
):
    with pytest.raises(ValueError, match="manfred_candidate_asset_path_invalid"):
        candidate_prep._safe_relative("../private.wav", suffix_required=True)
    with pytest.raises(ValueError, match="manfred_candidate_asset_type_forbidden"):
        candidate_prep._safe_relative("audio/private.json", suffix_required=True)

    assets = candidate_prep._declared_assets(
        {"pwa_icon": {"src_192": "icons/manfred.png"}},
        {
            "audio_clips": [
                {
                    "asset_relpath": "audio/private.mp3",
                    "visibility": "private",
                }
            ]
        },
    )
    assert assets[Path("icons/manfred.png")] == 0o444
    assert assets[Path("audio/private.mp3")] == 0o400


def test_candidate_spatial_review_inputs_are_explicit_and_threaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_args = candidate_prep.build_parser().parse_args(
        [
            "--image",
            "ea-runtime:manfred-abcdef123456",
            "--public-base-url",
            "https://memorial.example.at",
            "--project-name",
            PROJECT,
            "--spatial-tour-bundle-dir",
            str(tmp_path / "bundle"),
            "--spatial-authority-receipt",
            str(tmp_path / "authority.json"),
            "--spatial-final-review-receipt",
            str(tmp_path / "final.json"),
            "--spatial-browser-review-receipt",
            str(tmp_path / "browser.json"),
        ]
    )
    assert parser_args.spatial_final_review_receipt == str(tmp_path / "final.json")
    assert parser_args.spatial_browser_review_receipt == str(tmp_path / "browser.json")

    monkeypatch.setattr(candidate_prep, "_commit", lambda *_args: COMMIT)
    monkeypatch.setattr(
        candidate_prep,
        "_image_revision",
        lambda _image: ("sha256:" + "1" * 64, COMMIT),
    )
    captured: dict[str, object] = {}

    def capture_spatial_inputs(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        raise RuntimeError("spatial_inputs_captured")

    monkeypatch.setattr(
        candidate_prep,
        "_validated_spatial_handoff_input",
        capture_spatial_inputs,
    )
    unlocked_prepare = candidate_prep.prepare_candidate.__wrapped__
    with pytest.raises(RuntimeError, match="spatial_inputs_captured"):
        unlocked_prepare(
            source_root=tmp_path,
            ref="HEAD",
            image="ea-runtime:manfred-abcdef123456",
            deploy_root=tmp_path / "deploy",
            public_base_url="https://memorial.example.at",
            host_port=18090,
            project_name=PROJECT,
            spatial_tour_bundle_dir=tmp_path / "bundle",
            spatial_authority_receipt=tmp_path / "authority.json",
            spatial_final_review_receipt=tmp_path / "review" / ".." / "final.json",
            spatial_browser_review_receipt=tmp_path / "browser.json",
        )

    assert captured == {
        "bundle_dir": tmp_path / "bundle",
        "authority_receipt_path": tmp_path / "authority.json",
        "final_review_receipt_path": tmp_path / "final.json",
        "browser_review_receipt_path": tmp_path / "browser.json",
        "target_origin": "https://memorial.example.at",
    }


@pytest.mark.parametrize(
    ("spatial_inputs", "expected_error"),
    [
        (
            {
                "spatial_tour_bundle_dir": Path("bundle"),
                "spatial_authority_receipt": Path("authority.json"),
            },
            "manfred_candidate_spatial_review_evidence_required",
        ),
        (
            {
                "spatial_tour_bundle_dir": Path("bundle"),
                "spatial_authority_receipt": Path("authority.json"),
                "spatial_final_review_receipt": Path("final.json"),
            },
            "manfred_candidate_spatial_review_input_pair_required",
        ),
        (
            {
                "spatial_final_review_receipt": Path("final.json"),
                "spatial_browser_review_receipt": Path("browser.json"),
            },
            "manfred_candidate_spatial_review_evidence_required",
        ),
    ],
)
def test_candidate_spatial_review_inputs_fail_closed_as_one_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spatial_inputs: dict[str, Path],
    expected_error: str,
) -> None:
    monkeypatch.setattr(candidate_prep, "_commit", lambda *_args: COMMIT)
    monkeypatch.setattr(
        candidate_prep,
        "_image_revision",
        lambda _image: ("sha256:" + "1" * 64, COMMIT),
    )

    with pytest.raises(ValueError, match=expected_error):
        candidate_prep.prepare_candidate.__wrapped__(
            source_root=tmp_path,
            ref="HEAD",
            image="ea-runtime:manfred-abcdef123456",
            deploy_root=tmp_path / "deploy",
            public_base_url="https://memorial.example.at",
            host_port=18090,
            project_name=PROJECT,
            **spatial_inputs,
        )


def test_candidate_env_is_allowlisted_private_and_idempotent(tmp_path: Path) -> None:
    env_path = tmp_path / "candidate.env"
    release_root = tmp_path / "release"
    runtime_root = tmp_path / "runtime"
    candidate_prep._write_env(
        path=env_path,
        image="ea-runtime:manfred-abcdef123456",
        release_root=release_root,
        runtime_root=runtime_root,
        public_base_url="https://memorial.example.at",
        host_port=18090,
        project_name=PROJECT,
        commit=COMMIT,
    )
    first = candidate_prep._parse_env(env_path)
    candidate_prep._write_env(
        path=env_path,
        image="ea-runtime:manfred-abcdef123456",
        release_root=release_root,
        runtime_root=runtime_root,
        public_base_url="https://memorial.example.at",
        host_port=18090,
        project_name=PROJECT,
        commit=COMMIT,
    )
    second = candidate_prep._parse_env(env_path)

    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert second["EA_API_TOKEN"] == first["EA_API_TOKEN"]
    assert second["EA_SIGNING_SECRET"] == first["EA_SIGNING_SECRET"]
    assert (
        second["EA_MANFRED_POSTGRES_PASSWORD"] == first["EA_MANFRED_POSTGRES_PASSWORD"]
    )
    assert second["DATABASE_URL"].startswith("postgresql://ea:")
    assert "+psycopg" not in second["DATABASE_URL"]
    assert (
        not {
            "UNMIXR_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "EA_PUBLIC_MEMORIAL_WRITE_TOKEN",
        }
        & second.keys()
    )
    assert set(second) == candidate_runner.ALLOWED_ENV_KEYS

    existing_bytes = env_path.read_bytes()
    with pytest.raises(ValueError, match="manfred_candidate_env_existing_conflict"):
        candidate_prep._write_env(
            path=env_path,
            image="ea-runtime:manfred-abcdef123456",
            release_root=release_root,
            runtime_root=runtime_root,
            public_base_url="https://memorial.example.at",
            host_port=18090,
            project_name=PROJECT,
            commit=COMMIT,
            rotate_secrets=True,
        )
    assert env_path.read_bytes() == existing_bytes

    rotated_path = tmp_path / "rotated-candidate.env"
    candidate_prep._write_env(
        path=rotated_path,
        image="ea-runtime:manfred-abcdef123456",
        release_root=release_root,
        runtime_root=runtime_root,
        public_base_url="https://memorial.example.at",
        host_port=18090,
        project_name=PROJECT,
        commit=COMMIT,
        rotate_secrets=True,
    )
    rotated = candidate_prep._parse_env(rotated_path)
    assert rotated["EA_API_TOKEN"] != second["EA_API_TOKEN"]
    assert rotated["EA_SIGNING_SECRET"] != second["EA_SIGNING_SECRET"]
    assert (
        rotated["EA_MANFRED_POSTGRES_PASSWORD"]
        != second["EA_MANFRED_POSTGRES_PASSWORD"]
    )


def test_candidate_release_authority_bundle_is_commit_bound_and_runtime_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = "sha256:" + "b" * 64
    authority_root = tmp_path / "release-authority"
    project_modes = {
        "contract_name": "ea.project_modes",
        "generated_at": "stale",
        "generated_by": "fixture",
        "source_git_head": "b" * 40,
        "head_semantics": "source_state",
        "modes": [
            {"key": "MEMORIAL", "status": "separate_risk_zone"},
            {"key": "PROPERTY", "status": "separate_product_plane"},
        ],
    }
    monkeypatch.setattr(
        candidate_prep,
        "_git_blob",
        lambda *_args, **_kwargs: candidate_prep._receipt_bytes(project_modes),
    )

    def fake_run(  # type: ignore[no-untyped-def]
        argv, *, cwd=None, input_bytes=None, timeout=None, environment=None
    ):
        del input_bytes, timeout, environment
        call = tuple(argv)
        if call == ("git", "status", "--short"):
            return b""
        if call[:3] == ("git", "rev-parse", "--verify"):
            return f"{COMMIT}\n".encode("ascii")
        if call[:3] == ("git", "merge-base", "--is-ancestor"):
            return b""
        if call == ("git", "remote", "get-url", "origin"):
            return (candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN + "\n").encode()
        if "ls-remote" in call:
            return f"{COMMIT}\trefs/heads/main\n".encode("ascii")
        raise AssertionError((call, cwd))

    monkeypatch.setattr(candidate_prep, "_run", fake_run)

    evidence = candidate_prep._materialize_candidate_release_authority(
        root=authority_root,
        source_root=tmp_path,
        commit=COMMIT,
        image_id=image_id,
        image_revision=COMMIT,
        project_name=PROJECT,
        public_origin="https://myexternalbrain.com",
        generated_at="2026-07-14T00:00:00Z",
        public_artifacts=["public_memorials/manfred/memorial.json"],
    )

    assert evidence["runtime_authority_state"] == "clear"
    assert evidence["runtime_authority_posture"] == "authoritative_runtime"
    assert evidence["promotion_authority"] is False
    paths = candidate_prep._candidate_release_authority_paths(authority_root)
    assert set(path.name for path in authority_root.iterdir()) == {
        path.name for path in paths.values()
    }
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o444 for path in paths.values())
    status = json.loads(paths["release_status"].read_text(encoding="utf-8"))
    assert status["commit_sha"] == COMMIT
    assert status["state"] == "clear"
    assert status["authority_posture"] == "authoritative_runtime"
    assert status["manifest_path"] == (
        "/data/release-authority/release_manifest.generated.json"
    )
    assert str(tmp_path) not in json.dumps(status)

    manifest = json.loads(paths["release_manifest"].read_text(encoding="utf-8"))
    manifest["commit_sha"] = "c" * 40
    paths["release_manifest"].chmod(0o644)
    paths["release_manifest"].write_bytes(candidate_prep._receipt_bytes(manifest))
    with pytest.raises(
        ValueError,
        match="manfred_candidate_release_authority_binding_invalid",
    ):
        candidate_prep._validate_candidate_release_authority_bundle(
            authority_root,
            expected_commit=COMMIT,
            expected_image_id=image_id,
            expected_project_name=PROJECT,
            expected_public_origin="https://myexternalbrain.com",
        )


def test_candidate_remote_main_evidence_queries_exact_official_live_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(  # type: ignore[no-untyped-def]
        argv, *, cwd=None, input_bytes=None, timeout=None, environment=None
    ):
        del input_bytes
        call = tuple(argv)
        calls.append(call)
        if call == ("git", "status", "--short"):
            return b""
        if call[:3] == ("git", "rev-parse", "--verify"):
            return f"{COMMIT}\n".encode("ascii")
        if call[:3] == ("git", "merge-base", "--is-ancestor"):
            return b""
        if call == ("git", "remote", "get-url", "origin"):
            return (candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN + "\n").encode()
        if call == (
            "git",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "ls-remote",
            "--exit-code",
            candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN,
            "refs/heads/main",
        ):
            assert timeout == 30
            assert cwd == Path("/")
            assert environment == {
                "GIT_ALLOW_PROTOCOL": "https",
                "GIT_ASKPASS": "/bin/false",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_PROTOCOL_FROM_USER": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "HOME": "/",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": os.environ.get("PATH") or os.defpath,
                "SSH_ASKPASS": "/bin/false",
            }
            return f"{COMMIT}\trefs/heads/main\n".encode("ascii")
        assert environment is None
        assert timeout is None
        raise AssertionError(call)

    monkeypatch.setattr(candidate_prep, "_run", fake_run)
    evidence = candidate_prep._candidate_remote_main_evidence(
        tmp_path,
        commit=COMMIT,
    )

    assert evidence["git_remote_origin"] == candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN
    assert evidence["source_head_commit_sha"] == COMMIT
    assert evidence["source_head_matches_candidate_commit"] is True
    assert evidence["live_remote_ref_commit_sha"] == COMMIT
    assert evidence["live_remote_ref_evidence"] == (
        "isolated_git_ls_remote_exact_https_ref"
    )
    assert (
        "git",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=",
        "ls-remote",
        "--exit-code",
        candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN,
        "refs/heads/main",
    ) in calls


@pytest.mark.parametrize(
    "configured_origin",
    [
        "https://github.com/example/executive-assistant.git",
        "https://token@github.com/ArchonMegalon/executive-assistant.git",
        "https://user:token@github.com/ArchonMegalon/executive-assistant.git",
    ],
)
def test_candidate_remote_main_evidence_rejects_wrong_or_credentialed_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_origin: str,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(  # type: ignore[no-untyped-def]
        argv, *, cwd=None, input_bytes=None, timeout=None, environment=None
    ):
        del cwd, input_bytes, environment
        call = tuple(argv)
        calls.append(call)
        if call == ("git", "status", "--short"):
            return b""
        if call[:3] == ("git", "rev-parse", "--verify"):
            return f"{COMMIT}\n".encode("ascii")
        if call[:3] == ("git", "merge-base", "--is-ancestor"):
            return b""
        if call == ("git", "remote", "get-url", "origin"):
            return f"{configured_origin}\n".encode()
        assert timeout is None
        raise AssertionError(call)

    monkeypatch.setattr(candidate_prep, "_run", fake_run)
    with pytest.raises(ValueError, match="remote_origin_invalid"):
        candidate_prep._candidate_remote_main_evidence(tmp_path, commit=COMMIT)
    assert not any("ls-remote" in call for call in calls)


def test_candidate_remote_main_evidence_rejects_stale_live_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(  # type: ignore[no-untyped-def]
        argv, *, cwd=None, input_bytes=None, timeout=None, environment=None
    ):
        del cwd, input_bytes, environment
        call = tuple(argv)
        if call == ("git", "status", "--short"):
            return b""
        if call[:3] == ("git", "rev-parse", "--verify"):
            return f"{COMMIT}\n".encode("ascii")
        if call[:3] == ("git", "merge-base", "--is-ancestor"):
            return b""
        if call == ("git", "remote", "get-url", "origin"):
            return (candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN + "\n").encode()
        if "ls-remote" in call:
            assert timeout == 30
            return f"{'c' * 40}\trefs/heads/main\n".encode("ascii")
        assert timeout is None
        raise AssertionError(call)

    monkeypatch.setattr(candidate_prep, "_run", fake_run)
    with pytest.raises(ValueError, match="live_main_mismatch"):
        candidate_prep._candidate_remote_main_evidence(tmp_path, commit=COMMIT)


def test_candidate_remote_main_evidence_requires_checked_out_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(  # type: ignore[no-untyped-def]
        argv, *, cwd=None, input_bytes=None, timeout=None, environment=None
    ):
        del cwd, input_bytes, timeout, environment
        call = tuple(argv)
        calls.append(call)
        if call == ("git", "status", "--short"):
            return b""
        if call == (
            "git",
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
        ):
            return f"{'b' * 40}\n".encode("ascii")
        raise AssertionError(call)

    monkeypatch.setattr(candidate_prep, "_run", fake_run)
    with pytest.raises(ValueError, match="release_head_mismatch"):
        candidate_prep._candidate_remote_main_evidence(tmp_path, commit=COMMIT)
    assert not any("remote" in call or "ls-remote" in call for call in calls)


def test_candidate_remote_main_evidence_normalizes_live_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(  # type: ignore[no-untyped-def]
        argv, *, cwd=None, input_bytes=None, timeout=None, environment=None
    ):
        del cwd, input_bytes, environment
        call = tuple(argv)
        if call == ("git", "status", "--short"):
            return b""
        if call[:3] == ("git", "rev-parse", "--verify"):
            return f"{COMMIT}\n".encode("ascii")
        if call == ("git", "remote", "get-url", "origin"):
            return (candidate_prep.OFFICIAL_EA_REMOTE_ORIGIN + "\n").encode()
        if call[:3] == ("git", "merge-base", "--is-ancestor"):
            return b""
        if "ls-remote" in call:
            raise subprocess.TimeoutExpired(call, timeout or 30)
        raise AssertionError(call)

    monkeypatch.setattr(candidate_prep, "_run", fake_run)
    with pytest.raises(ValueError, match="remote_main_unverifiable"):
        candidate_prep._candidate_remote_main_evidence(tmp_path, commit=COMMIT)


def test_runtime_runner_rejects_live_bind_or_external_network(tmp_path: Path) -> None:
    env_file = (tmp_path / "candidate.env").resolve()
    release_root = (tmp_path / "release").resolve()
    runtime_root = (tmp_path / "runtime").resolve()
    spatial_root = (release_root / "public_property_tours").resolve()
    authority_root = (
        release_root / candidate_prep.CANDIDATE_RELEASE_AUTHORITY_DIRNAME
    ).resolve()
    env = {
        "EA_MANFRED_COMPOSE_PROJECT": PROJECT,
        "EA_MANFRED_COMMIT": COMMIT,
        "EA_MANFRED_DEPLOYMENT_ID": f"{PROJECT}-{COMMIT[:12]}",
        "EA_MANFRED_IMAGE": "ea-runtime:manfred-abcdef123456",
        "EA_MANFRED_HOST_PORT": "18090",
        "EA_MANFRED_RELEASE_ROOT": str(release_root),
        "EA_MANFRED_RELEASE_AUTHORITY_ROOT": str(authority_root),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root),
        "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED": "0",
        "EA_MANFRED_SPATIAL_RELEASE_ROOT": str(spatial_root),
        "EA_MANFRED_SPATIAL_SHA256": candidate_prep._sha256(b"[]"),
        "EA_MANFRED_SPATIAL_SLUG": "",
        "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
    }
    mounts = [
        {
            "type": "bind",
            "source": str(release_root / "public_memorials"),
            "target": "/data/memorial/public",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(release_root / "private_memorial_profiles"),
            "target": "/data/memorial/private",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(release_root / "memorial_archive"),
            "target": "/data/memorial/archive",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(runtime_root / "public-contributions"),
            "target": "/data/memorial/public-contributions",
        },
        {
            "type": "bind",
            "source": str(runtime_root / "private-contributions"),
            "target": "/data/memorial/private-contributions",
        },
        {
            "type": "bind",
            "source": str(runtime_root / "state"),
            "target": "/data/memorial/state",
        },
        {
            "type": "bind",
            "source": str(spatial_root),
            "target": "/data/public_property_tours",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(authority_root),
            "target": "/data/release-authority",
            "read_only": True,
        },
        {"type": "volume", "source": "artifacts", "target": "/data/artifacts"},
    ]
    declared_environment = candidate_runner._expected_candidate_api_environment(env)
    base = {
        "name": PROJECT,
        "services": {
            "api": {
                "image": env["EA_MANFRED_IMAGE"],
                "pull_policy": "never",
                "read_only": True,
                "user": "10001:10001",
                "environment": {**env, **declared_environment},
                "volumes": mounts,
                "networks": {"backend": None},
            },
            "gateway": {
                "image": env["EA_MANFRED_IMAGE"],
                "pull_policy": "never",
                "read_only": True,
                "user": "10001:10001",
                "volumes": [],
                "networks": {"backend": None, "ingress": None},
                "ports": [
                    {"host_ip": "127.0.0.1", "published": "18090", "target": 18090}
                ],
            },
            "postgres": {"networks": {"backend": None}},
            "redis": {"networks": {"backend": None}},
        },
        "networks": {
            "backend": {"name": f"{PROJECT}_backend", "internal": True},
            "ingress": {"name": f"{PROJECT}_ingress"},
        },
        "volumes": {
            name: {"name": f"{PROJECT}_{name}"}
            for name in candidate_runner.EXPECTED_CANDIDATE_VOLUMES
        },
    }
    source = copy.deepcopy(base)
    source["services"]["api"]["environment"] = declared_environment
    source["services"]["api"]["env_file"] = [{"path": str(env_file)}]
    candidate_runner._assert_compose_isolation(
        base,
        source,
        env=env,
        env_file=env_file,
    )

    live_bind = copy.deepcopy(base)
    live_bind["services"]["redis"]["volumes"] = [
        {"type": "bind", "source": "/docker/EA/ea/app", "target": "/app/app"}
    ]
    with pytest.raises(
        RuntimeError, match="manfred_candidate_compose_live_bind_forbidden"
    ):
        candidate_runner._assert_compose_isolation(
            live_bind,
            source,
            env=env,
            env_file=env_file,
        )

    external_network = copy.deepcopy(base)
    external_network["networks"]["backend"]["external"] = True
    with pytest.raises(RuntimeError, match="compose_network_not_isolated"):
        candidate_runner._assert_compose_isolation(
            external_network,
            source,
            env=env,
            env_file=env_file,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://memorial.example.at",
        "https://localhost",
        "https://127.0.0.1",
        "https://example.invalid",
        "https://candidate.invalid",
    ],
)
def test_candidate_public_origin_must_be_nonplaceholder_https(url: str) -> None:
    with pytest.raises(ValueError, match="manfred_candidate_public_base_url_invalid"):
        candidate_prep._validate_public_base_url(url)


def test_page_render_prewarm_can_be_disabled_without_changing_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.routes import public_memorials

    calls: list[str] = []
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda slug: calls.append(slug),
    )
    monkeypatch.delenv("EA_MEMORIAL_PAGE_PREWARM_ENABLED", raising=False)
    public_memorials._prime_memorial_live_warmup_on_page_render("manfred")
    assert calls == ["manfred"]

    monkeypatch.setenv("EA_MEMORIAL_PAGE_PREWARM_ENABLED", "0")
    public_memorials._prime_memorial_live_warmup_on_page_render("manfred")
    assert calls == ["manfred"]


def test_manfred_public_page_uses_scoped_talk_only_minimal_theme() -> None:
    from app.api.routes import public_memorials

    common = {
        "person_name": "Manfred Hoza",
        "page_title": "Erinnerungen an Manfred Hoza",
        "subtitle": "Eine ruhige Seite für Erinnerungen.",
        "memorial_avatar_url": "/memorials/manfred/icon-180.png",
        "pwa_short_name": "Manfred",
        "clickrank_html": "",
        "story_html": "<section>Story</section>",
    }
    manfred_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        **common,
    )
    conversation_only_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        conversation_only=True,
        **common,
    )
    other_html = public_memorials._minimal_public_memorial_html(
        slug="another-memorial",
        **common,
    )

    assert (
        '<body class="memorial-theme-minimal" '
        'data-memorial-theme="editorial-minimal-v2" '
        'data-public-memorial-surface="legacy">'
    ) in manfred_html
    assert (
        '<body class="memorial-theme-minimal" '
        'data-memorial-theme="editorial-minimal-v2" '
        'data-public-memorial-surface="conversation-only">'
    ) in conversation_only_html
    assert "<section>Story</section>" in manfred_html
    assert "<section>Story</section>" not in conversation_only_html
    assert conversation_only_html.count("<main ") == 1
    assert 'id="memorial-story"' not in conversation_only_html
    assert 'id="memorial-contribution"' not in conversation_only_html
    assert 'id="memorial-install-hint"' not in conversation_only_html
    assert conversation_only_html.count('<details class="conversation-settings">') == 1
    assert "<summary>Datenschutz und Gespräch</summary>" in conversation_only_html
    assert (
        '<input type="checkbox" id="memorial-personal-memory-optin" '
        'disabled aria-disabled="true">'
        in conversation_only_html
    )
    assert 'id="memorial-conversation"' in conversation_only_html
    assert 'id="memorial-text-turn-form"' in conversation_only_html
    assert '<html lang="de-AT">' in conversation_only_html
    assert 'placeholder="Was möchtest du fragen?"' in conversation_only_html
    assert 'id="memorial-speech-note" hidden' in conversation_only_html
    assert 'id="memorial-retry-button"' in conversation_only_html
    assert 'id="memorial-speech-transcript" role="log"' in conversation_only_html
    rendered_contract = candidate_verify.verify_conversation_only_page_html(
        conversation_only_html.encode("utf-8")
    )
    assert rendered_contract == {
        "status": "pass",
        "public_surface": "conversation-only",
        "main_count": 1,
        "nav_count": 0,
        "aside_count": 0,
        "iframe_count": 0,
        "video_count": 0,
        "article_count": 0,
        "form_count": 1,
        "details_count": 1,
        "section_count": 2,
        "conversation_settings_count": 1,
        "personal_memory_optin_count": 1,
        "personal_memory_optin_default_checked": False,
        "personal_memory_optin_default_disabled": True,
        "personal_memory_forget_count": 1,
        "memory_room_link_count": 0,
        "tour_link_count": 0,
        "voice_release": "available",
        "voice_access": "public-release",
        "operator_preview": "",
        "missing_required_ids": [],
        "duplicate_ids": [],
        "present_forbidden_ids": [],
        "forbidden_dom_semantics": [],
    }
    assert ".memorial-theme-minimal::before" in manfred_html
    assert ".memorial-theme-minimal .story-card" in manfred_html
    assert ".memorial-theme-minimal .skip-link:focus-visible" in manfred_html
    assert '<body class="memorial-theme-minimal"' not in other_html
    assert "data-memorial-theme=" not in other_html


def test_candidate_conversation_surface_rejects_disguised_or_duplicate_dom() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    hostile_fragments = (
        '<section id="memorial-story">Unzulässige Story</section>',
        '<section id="renamed-history" class="story-section">Verdeckte Story</section>',
        '<article id="renamed-biography">Verdeckte Biografie</article>',
        '<form id="renamed-private-upload" class="contribution-form"></form>',
        '<button id="renamed-offline-cta" data-install-surface="pwa">Installieren</button>',
        '<div id="renamed-visual" data-region="video-call">Video</div>',
        '<div id="neutral-region-one" role="region" aria-label="Story">Inhalt</div>',
        '<button id="neutral-action-one" aria-label="Install application">Öffnen</button>',
        '<div id="neutral-region-two" role="region" aria-label="Archive">Inhalt</div>',
        '<div id="neutral-region-three" role="img" aria-label="Video call">Bild</div>',
        '<span id="neutral-label-one">Story</span>'
        '<div id="neutral-region-four" role="region" '
        'aria-labelledby="neutral-label-one">Inhalt</div>',
        '<div id="neutral-region-five" title="Archive">Inhalt</div>',
        '<button id="neutral-action-two" name="offline-action" '
        'value="install">Öffnen</button>',
        '<a id="neutral-link-one" href="/memorials/manfred" '
        'download="archive.zip">Weiter</a>',
        '<div id="memorial-chat-status">Doppelte ID</div>',
    )
    for fragment in hostile_fragments:
        hostile_html = page_html.replace("</body>", f"{fragment}</body>")
        with pytest.raises(
            RuntimeError,
            match="candidate_conversation_surface_invalid",
        ) as caught:
            candidate_verify.verify_conversation_only_page_html(
                hostile_html.encode("utf-8")
            )
        if 'id="memorial-chat-status"' in fragment:
            assert '"duplicate_ids":["memorial-chat-status"]' in str(caught.value)
        else:
            assert '"forbidden_dom_semantics":[' in str(caught.value)

    dead_markup = page_html.replace(
        "</body>",
        "<style>.story-card::after { content: "
        "'<a href=\"/memory%252Droom\" aria-label=\"Archive\">'; }</style>"
        "<script>const deadMarkup = "
        "'<article class=\"story-card\" aria-label=\"Video call\"></article>';"
        "</script></body>",
    )
    assert (
        candidate_verify.verify_conversation_only_page_html(
            dead_markup.encode("utf-8")
        )["status"]
        == "pass"
    )


def test_candidate_conversation_surface_rejects_generic_visible_features() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    hostile_fragments = (
        "<div><h2>Geschichte</h2><p>Eine vollständige Biografie.</p></div>",
        '<div id="neutral-panel"><h2>Archiv</h2><p>Alle Erinnerungen.</p></div>',
        '<div id="neutral-copy">Eine weitere Geschichte über Manfred.</div>',
        '<div id="neutral-split-copy">Sto<span>ry</span></div>',
        '<label>Ar<span>chiv</span></label>',
        '<input id="neutral-control" type="button" value="Installieren">',
        '<label for="neutral-control">Archiv öffnen</label>'
        '<input id="neutral-control" type="button" value="Öffnen">',
        '<input id="neutral-control" type="image" alt="Video" src="/safe.png">',
    )
    for fragment in hostile_fragments:
        hostile_html = page_html.replace("</body>", f"{fragment}</body>")
        with pytest.raises(
            RuntimeError,
            match="candidate_conversation_surface_invalid",
        ) as caught:
            candidate_verify.verify_conversation_only_page_html(
                hostile_html.encode("utf-8")
            )
        assert '"forbidden_dom_semantics":[' in str(caught.value)


def test_candidate_conversation_surface_rejects_duplicate_attributes() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    hostile_fragments = (
        '<a href="/memory%2Droom" href="/">Weiter</a>',
        '<a HREF="/archive" href="/">Weiter</a>',
        '<svg><a xlink:href="/archive" XLINK:HREF="/">Weiter</a></svg>',
        '<div title="Archive" TITLE="Neutral">Inhalt</div>',
    )
    for fragment in hostile_fragments:
        hostile_html = page_html.replace("</body>", f"{fragment}</body>")
        with pytest.raises(
            RuntimeError,
            match="candidate_conversation_surface_invalid",
        ) as caught:
            candidate_verify.verify_conversation_only_page_html(
                hostile_html.encode("utf-8")
            )
        assert "duplicate-attribute" in str(caught.value)


def test_candidate_conversation_surface_rejects_active_navigation_bypasses() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    assert 'action="/memorials/manfred/chat"' in page_html
    hostile_documents = (
        page_html.replace(
            "</body>",
            '<svg><a xlink:href="/memory%2Droom">Weiter</a></svg></body>',
        ),
        page_html.replace(
            "</body>",
            '<svg><use href="/story"></use></svg></body>',
        ),
        page_html.replace(
            "</body>",
            '<button onclick="location.href=\'/memory-room\'">Weiter</button></body>',
        ),
        page_html.replace(
            "</body>",
            '<button onpointerdown="window.open(\'/archive\')">Weiter</button></body>',
        ),
        page_html.replace("</head>", '<base href="/memory-room/"></head>'),
        page_html.replace(
            "</head>",
            '<meta http-equiv="refresh" content="0;url=/memory-room"></head>',
        ),
        page_html.replace(
            'action="/memorials/manfred/chat"',
            'action="/memory-room"',
            1,
        ),
        page_html.replace(
            "</body>",
            '<button formaction="/archive">Weiter</button></body>',
        ),
        page_html.replace(
            "</body>",
            '<a href="https://archive.example/">Weiter</a></body>',
        ),
        page_html.replace(
            "</body>",
            '<a href="https://%61rchive.example/">Weiter</a></body>',
        ),
        page_html.replace(
            "</body>",
            '<a href="javascript:location.href=\'/memory-room\'">Weiter</a></body>',
        ),
        page_html.replace("</body>", '<a href="/install">Weiter</a></body>'),
        page_html.replace("</body>", '<a href="/video">Weiter</a></body>'),
    )
    for hostile_html in hostile_documents:
        with pytest.raises(
            RuntimeError,
            match="candidate_conversation_surface_invalid",
        ):
            candidate_verify.verify_conversation_only_page_html(
                hostile_html.encode("utf-8")
            )


def test_candidate_conversation_surface_accepts_benign_semantics_and_navigation() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    benign_fragment = (
        "<div><h2>Gesprächshinweis</h2>"
        "<p>Text und Stimme bleiben verfügbar.</p></div>"
        '<label for="neutral-control">Antwortmodus</label>'
        '<input id="neutral-control" type="button" value="Öffnen">'
        '<svg aria-hidden="true"><use href="#safe-icon"></use></svg>'
        '<a href="https://example.com/help" title="Weitere Hilfe">Hilfe</a>'
    )
    benign_html = page_html.replace("</body>", f"{benign_fragment}</body>")

    assert (
        candidate_verify.verify_conversation_only_page_html(
            benign_html.encode("utf-8")
        )["status"]
        == "pass"
    )


def test_candidate_conversation_surface_rejects_public_operator_preview() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    page_html = page_html.replace(
        '<body class="memorial-theme-minimal" '
        'data-memorial-theme="editorial-minimal-v2" '
        'data-public-memorial-surface="conversation-only">',
        '<body class="memorial-theme-minimal" '
        'data-memorial-theme="editorial-minimal-v2" '
        'data-public-memorial-surface="conversation-only" '
        'data-operator-voice-preview="allowed">',
        1,
    )
    assert 'data-operator-voice-preview="allowed"' in page_html

    with pytest.raises(RuntimeError, match="candidate_conversation_surface_invalid"):
        candidate_verify.verify_conversation_only_page_html(page_html.encode("utf-8"))


def test_candidate_conversation_surface_rejects_inconsistent_voice_access() -> None:
    from app.api.routes import public_memorials

    page_html = public_memorials._minimal_public_memorial_html(
        slug="manfred",
        person_name="Manfred Hoza",
        page_title="Erinnerungen an Manfred Hoza",
        subtitle="Ein ruhiger Ort für ein Gespräch über Manfred.",
        memorial_avatar_url="/memorials/manfred/icon-180.png",
        pwa_short_name="Manfred",
        clickrank_html="",
        story_html="",
        conversation_only=True,
    )
    assert 'data-voice-access="public-release"' in page_html
    page_html = page_html.replace(
        'data-voice-access="public-release"',
        'data-voice-access="text-only"',
        1,
    )

    with pytest.raises(RuntimeError, match="candidate_conversation_surface_invalid"):
        candidate_verify.verify_conversation_only_page_html(page_html.encode("utf-8"))


def test_manfred_story_progressively_discloses_secondary_memories() -> None:
    from app.api.routes import public_memorials

    payload = {
        "memory_cards": [
            {
                "visibility": "public",
                "public": True,
                "title": f"Erinnerung {index}",
                "body": f"Freigegebene Kurzfassung {index}.",
            }
            for index in range(1, 7)
        ]
    }
    story_html = public_memorials._public_memorial_story_html(
        payload,
        slug="manfred",
    )
    other_story_html = public_memorials._public_memorial_story_html(
        payload,
        slug="another-memorial",
    )

    assert story_html.count('article class="story-card memory-card"') == 6
    assert '<details class="story-more">' in story_html
    assert "Weitere belegte Spuren (3)" in story_html
    assert story_html.index("Erinnerung 3") < story_html.index(
        '<details class="story-more">'
    )
    assert story_html.index('<details class="story-more">') < story_html.index(
        "Erinnerung 4"
    )
    assert '<details class="story-more">' not in other_story_html
    assert other_story_html.count('article class="story-card memory-card"') == 6


def test_share_verifier_rejects_real_recipient_fields_not_safety_receipts() -> None:
    assert candidate_verify._contains_forbidden_recipient_field(
        {"draft": {"recipient_address": "+430000000"}}
    )
    assert not candidate_verify._contains_forbidden_recipient_field(
        {"recipient_free": True, "sent": False}
    )


def test_candidate_browser_uses_system_chromium_when_playwright_bundle_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrowserType:
        executable_path = "/missing/playwright/chromium"

    monkeypatch.delenv("EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE", raising=False)
    monkeypatch.setattr(
        candidate_verify.shutil,
        "which",
        lambda name: "/usr/bin/chromium" if name == "chromium" else None,
    )

    assert (
        candidate_verify._chromium_launch_executable(BrowserType())
        == "/usr/bin/chromium"
    )


def test_candidate_browser_passes_existing_playwright_executable_explicitly(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "chromium"
    executable.write_bytes(b"binary-placeholder")

    class BrowserType:
        executable_path = str(executable)

    assert candidate_verify._chromium_launch_executable(BrowserType()) == str(
        executable.resolve()
    )


def test_candidate_browser_rejects_missing_configured_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrowserType:
        executable_path = "/missing/playwright/chromium"

    monkeypatch.setenv(
        "EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE",
        "/missing/operator/chromium",
    )
    with pytest.raises(RuntimeError, match="candidate_browser_executable_invalid"):
        candidate_verify._chromium_launch_executable(BrowserType())


def test_candidate_browser_classifies_same_origin_http_errors_exactly() -> None:
    base_url = "https://memorial.example.at"

    assert candidate_verify._is_same_origin_http_error(
        base_url=base_url,
        response_url="https://memorial.example.at/missing.css",
        status=404,
    )
    assert candidate_verify._is_same_origin_http_error(
        base_url="https://memorial.example.at:443",
        response_url="https://memorial.example.at/broken.png",
        status=500,
    )
    assert not candidate_verify._is_same_origin_http_error(
        base_url=base_url,
        response_url="https://cdn.example.at/missing.css",
        status=404,
    )
    assert not candidate_verify._is_same_origin_http_error(
        base_url=base_url,
        response_url="https://memorial.example.at/app.css",
        status=399,
    )


def test_candidate_browser_uses_forwarded_https_authority_only_for_local_origin() -> (
    None
):
    assert candidate_verify._browser_proxy_headers(
        "http://127.0.0.1:8090",
        "https://myexternalbrain.com",
    ) == {
        "X-Forwarded-Host": "myexternalbrain.com",
        "X-Forwarded-Proto": "https",
    }
    assert (
        candidate_verify._browser_proxy_headers(
            "https://myexternalbrain.com",
            "https://myexternalbrain.com",
        )
        == {}
    )


def test_candidate_http_uses_fixed_verifier_identity_and_bounded_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class Response:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return False

        def read(self, _limit: int) -> bytes:
            return b"{}"

    def fake_urlopen(request, *, timeout: int):  # type: ignore[no-untyped-def]
        assert timeout == 20
        captured.update({name.lower(): value for name, value in request.header_items()})
        return Response()

    monkeypatch.setattr(candidate_verify.urllib.request, "urlopen", fake_urlopen)

    candidate_verify._request(
        "https://myexternalbrain.com",
        "/healthz",
        headers={
            "User-Agent": "Mozilla/5.0 should-not-win",
            "Accept": "text/plain should-not-win",
            "X-EA-Test": "retained",
        },
    )

    assert captured["user-agent"] == "EA-Memorial-Launch-Verifier/1.0"
    assert captured["accept"] == candidate_verify.VERIFIER_REQUEST_HEADERS["Accept"]
    assert len(captured["accept"]) <= 64
    assert captured["x-ea-test"] == "retained"
    assert "mozilla" not in captured["user-agent"].casefold()


def test_public_tour_json_route_supports_get_and_head() -> None:
    from app.api.routes import public_tours

    methods = {
        method
        for route in public_tours.router.routes
        if route.path == "/tours/{slug}.json"
        for method in (route.methods or set())
    }

    assert methods == {"GET", "HEAD"}


def test_projection_source_reader_is_stable_nofollow_and_mode_bounded(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "projection" / "source.bin"
    source.write_bytes(b"governed-source")
    source.chmod(0o664)

    evidence = candidate_prep._copy_regular(
        source,
        destination,
        maximum=1024,
        mode=0o444,
    )
    assert destination.read_bytes() == b"governed-source"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o444
    assert evidence["sha256"] == candidate_prep._sha256(b"governed-source")

    linked = tmp_path / "linked.bin"
    os.link(source, linked)
    with pytest.raises(ValueError, match="source_asset_invalid"):
        candidate_prep._read_regular_source(source, maximum=1024)
    linked.unlink()

    source.unlink()
    target = tmp_path / "target.bin"
    target.write_bytes(b"hostile")
    source.symlink_to(target)
    with pytest.raises(ValueError, match="source_asset_invalid"):
        candidate_prep._read_regular_source(source, maximum=1024)


def test_spatial_materializer_sanitizes_private_operator_source_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    slug = candidate_prep.PROPERTY_AUTHORIZED_SLUG
    source = tmp_path / "operator-private" / slug
    source.mkdir(parents=True, mode=0o700)
    nested = source / "generated-reconstruction"
    nested.mkdir(mode=0o700)
    for index, relative in enumerate(
        (
            "tour.json",
            "generated-reconstruction/reconstruction.json",
            "generated-reconstruction/source-floorplan.png",
            "generated-reconstruction/viewer.html",
            "generated-reconstruction/three.module.js",
            "generated-reconstruction/OrbitControls.js",
        )
    ):
        path = source / relative
        path.write_bytes(f"source-{index}".encode("ascii"))
        path.chmod(0o600 if index % 2 == 0 else 0o664)

    authority = tmp_path / "evidence" / "authority.json"
    final_review = tmp_path / "evidence" / "final.json"
    browser_review = tmp_path / "evidence" / "browser.json"
    authority.parent.mkdir()
    for path in (authority, final_review, browser_review):
        path.write_bytes(b"{}\n")
        path.chmod(0o600)

    monkeypatch.setattr(
        candidate_prep,
        "_validated_property_publication",
        lambda **_kwargs: {
            "slug": slug,
            "asset_paths": [],
            "upstream_publication_authority_sha256": "a" * 64,
            "upstream_public_activation_authority": True,
            "upstream_package_sha256": "b" * 64,
            "upstream_tour_manifest_sha256": "c" * 64,
            "review_evidence": {},
        },
    )
    monkeypatch.setattr(
        candidate_prep,
        "_verify_spatial_bundle_before_copy",
        lambda *_args, **_kwargs: {"pass": True},
    )
    handoff_bundle = tmp_path / "handoff" / slug
    handoff_receipt = tmp_path / "receipts" / "handoff.json"

    receipt = candidate_prep.materialize_spatial_handoff(
        source_bundle_dir=source,
        upstream_authority_receipt_path=authority,
        final_review_receipt_path=final_review,
        browser_review_receipt_path=browser_review,
        handoff_bundle_dir=handoff_bundle,
        handoff_receipt_path=handoff_receipt,
        target_origin="https://myexternalbrain.com",
    )

    assert receipt["status"] == "pass"
    assert stat.S_IMODE(handoff_bundle.stat().st_mode) == 0o755
    assert stat.S_IMODE(handoff_receipt.stat().st_mode) == 0o600
    for path in handoff_bundle.rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)
