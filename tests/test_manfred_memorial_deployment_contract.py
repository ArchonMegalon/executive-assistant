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
from starlette.websockets import WebSocket

from scripts import build_manfred_memorial_image as image_builder
from scripts import deploy_ea_memorial as memorial_deploy
from scripts import prepare_manfred_memorial_candidate as candidate_prep
from scripts import run_manfred_memorial_candidate as candidate_runner
from scripts import verify_manfred_memorial_candidate as candidate_verify


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy/manfred-memorial/docker-compose.candidate.yml"
PROJECT = "ea-manfred-candidate-deployment-contract-a1b2c3d4"
COMMIT = "a" * 40


@pytest.fixture(autouse=True)
def _exercise_existing_candidate_contracts_past_incident_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for module in (
        candidate_prep,
        candidate_runner,
        image_builder,
        memorial_deploy,
    ):
        monkeypatch.setattr(
            module,
            "_require_credential_exposure_remediation",
            lambda: None,
        )


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


def test_production_memorial_compose_uses_private_runtime_state_for_gemini_oauth() -> None:
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    overlay_raw = (ROOT / "docker-compose.memorial.yml").read_text(encoding="utf-8")

    class ComposeLoader(yaml.SafeLoader):
        pass

    ComposeLoader.add_constructor(
        "!override",
        lambda loader, node: loader.construct_sequence(node, deep=True),
    )
    overlay = yaml.load(overlay_raw, Loader=ComposeLoader)  # nosec B506

    def environment(entries: list[str]) -> dict[str, str]:
        return {
            name: value
            for name, value in (str(entry).split("=", 1) for entry in entries)
        }

    base_api = base["services"]["ea-api"]
    overlay_api = overlay["services"]["ea-api"]
    rendered_environment = {
        **environment(base_api["environment"]),
        **environment(overlay_api["environment"]),
    }
    rendered_volumes = overlay_api["volumes"]
    credential_target = (
        "/data/memorial-writable/state/gemini-oauth/oauth_creds.json"
    )

    assert rendered_environment["EA_MEMORIAL_GEMINI_OAUTH_CREDS_PATH"] == (
        credential_target
    )
    assert any(
        str(volume).endswith("/state:/data/memorial-writable/state")
        for volume in rendered_volumes
    )
    assert all("gemini" not in str(volume).casefold() for volume in rendered_volumes)
    assert "EA_MEMORIAL_GEMINI_OAUTH_CREDS_HOST_PATH" not in overlay_raw
    assert "/home/tibor/.gemini" not in overlay_raw


def test_production_memorial_compose_passes_sealed_conversation_decisions() -> None:
    raw = (ROOT / "docker-compose.memorial.yml").read_text(encoding="utf-8")

    assert (
        "EA_MEMORIAL_DEPLOYMENT_ID=${EA_MEMORIAL_DEPLOYMENT_ID:?"
        in raw
    )
    assert (
        "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH="
        "${EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH:?" in raw
    )
    assert (
        "EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION="
        "${EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION:?" in raw
    )
    assert (
        "EA_MEMORIAL_VOICE_PREVIEW_ENABLED="
        "${EA_MEMORIAL_VOICE_PREVIEW_ENABLED:?" in raw
    )
    assert (
        "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES="
        "${EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES:?" in raw
    )


def test_production_memorial_compose_is_memorial_only_without_public_tours() -> None:
    raw = (ROOT / "docker-compose.memorial.yml").read_text(encoding="utf-8")

    assert "EA_DEPLOY_PRIMARY_MODE=MEMORIAL" in raw
    assert "EA_DEPLOY_ENABLED_MODES=MEMORIAL" in raw
    assert "EA_DEPLOY_ENABLED_MODES=MEMORIAL,PROPERTY" not in raw
    assert "EA_ENABLE_PUBLIC_TOURS=0" in raw
    assert "PROPERTYQUARRY_ENABLE_PUBLIC_TOURS=0" in raw
    assert "EA_ENABLE_PUBLIC_TOURS=1" not in raw
    assert "PROPERTYQUARRY_ENABLE_PUBLIC_TOURS=1" not in raw


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_exact_memorial_only_runtime_redirects_public_root_to_conversation_e2e(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)

    @application.api_route("/", methods=["GET", "HEAD"])
    def generic_root() -> PlainTextResponse:
        return PlainTextResponse("generic")

    response = TestClient(application).request(
        method,
        "/?next=https%3A%2F%2Fevil.example%2Fcapture",
        headers={"Host": "myexternalbrain.com"},
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/memorials/manfred"
    assert response.headers["cache-control"] == "no-store"
    assert "evil.example" not in response.headers["location"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/memorial/manfred"),
        ("HEAD", "/memorial/manfred"),
        ("GET", "/memorials/manfred"),
        ("HEAD", "/memorials/manfred"),
        ("GET", "/memorials/manfred/app.webmanifest"),
        ("POST", "/memorials/manfred/chat"),
        ("POST", "/memorials/manfred/conversation-turn"),
        ("GET", "/memorials/manfred/icon.svg"),
        ("GET", "/memorials/manfred/icon-180.png"),
        ("GET", "/memorials/files/manfred/avatar.webp"),
        ("GET", "/memorials/manfred/personal-memory"),
        ("DELETE", "/memorials/manfred/personal-memory"),
        ("POST", "/memorials/manfred/playback-telemetry"),
        ("GET", "/memorials/manfred/readiness"),
        ("POST", "/memorials/manfred/realtime/webrtc"),
        ("GET", "/memorials/manfred/service-worker.js"),
        ("POST", "/memorials/manfred/speech-synthesize"),
        ("POST", "/memorials/manfred/speech-transcribe"),
        ("POST", "/memorials/manfred/voice-preview/session"),
        ("DELETE", "/memorials/manfred/voice-preview/session"),
        ("POST", "/memorials/manfred/warmup"),
        ("GET", "/memorials/manfred/warmup-status"),
    ],
)
def test_memorial_only_boundary_allows_exact_conversation_http_surface(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)
    application.add_api_route(
        path,
        lambda: PlainTextResponse("allowed"),
        methods=[method],
    )

    response = TestClient(application).request(
        method,
        path,
        headers={"Host": "myexternalbrain.com"},
    )

    assert response.status_code == 200


def test_memorial_only_boundary_allows_only_compose_healthcheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)
    application.add_api_route(
        "/healthz",
        lambda: PlainTextResponse("healthy"),
        methods=["GET"],
    )
    application.add_api_route(
        "/health/ready",
        lambda: PlainTextResponse("must-not-run"),
        methods=["GET"],
    )
    client = TestClient(application)

    healthz = client.get("/healthz", headers={"Host": "127.0.0.1:8090"})
    broader_health = client.get(
        "/health/ready",
        headers={"Host": "myexternalbrain.com"},
    )

    assert healthz.status_code == 200
    assert healthz.text == "healthy"
    assert broader_health.status_code == 404


@pytest.mark.parametrize(
    ("configured_origin", "request_host"),
    [
        ("https://example.com", "example.com"),
        ("https://propertyquarry.com", "propertyquarry.com"),
        ("https://jdownloader.girschele.com", "jdownloader.girschele.com"),
        ("https://myexternalbrain.com:443", "myexternalbrain.com:443"),
    ],
)
def test_memorial_only_boundary_rejects_every_noncanonical_configured_origin(
    monkeypatch: pytest.MonkeyPatch,
    configured_origin: str,
    request_host: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", configured_origin)
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)
    application.add_api_route(
        "/memorials/manfred",
        lambda: PlainTextResponse("must-not-run"),
        methods=["GET"],
    )
    application.add_api_route(
        "/healthz",
        lambda: PlainTextResponse("healthy"),
        methods=["GET"],
    )
    client = TestClient(application)

    root = client.get("/", headers={"Host": request_host}, follow_redirects=False)
    page = client.get("/memorials/manfred", headers={"Host": request_host})
    healthz = client.get("/healthz", headers={"Host": "127.0.0.1:8090"})

    assert root.status_code == 404
    assert "location" not in root.headers
    assert page.status_code == 404
    assert healthz.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/memorials%2Fmanfred",
        "/%6demorials/manfred",
        "/memorials/manfred%2Frealtime/webrtc",
        "/memorials/manfred/%2e%2e/admin",
        "/memorials/files/manfred/%2e%2e/private.json",
        "/memorials/files/manfred/avatar%2Fprivate.webp",
    ],
)
def test_memorial_only_boundary_rejects_noncanonical_raw_paths_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)
    handler_calls = 0

    @application.api_route("/{requested_path:path}", methods=["GET", "POST"])
    def catch_all(requested_path: str) -> PlainTextResponse:
        nonlocal handler_calls
        handler_calls += 1
        return PlainTextResponse(requested_path)

    response = TestClient(application).get(
        path,
        headers={"Host": "myexternalbrain.com"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}
    assert handler_calls == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/product"),
        ("GET", "/pricing"),
        ("GET", "/setup"),
        ("GET", "/admin"),
        ("GET", "/v1/providers/registry"),
        ("GET", "/app"),
        ("GET", "/archive-slug"),
        ("GET", "/memorials/manfred/archive"),
        ("GET", "/memorials/manfred/archive.json"),
        ("GET", "/memorials/manfred/memory-room"),
        ("GET", "/memorials/manfred/operator-status"),
        ("GET", "/memorials/manfred/video-meeting/status"),
        ("GET", "/memorials/manfred/voice-ab-admin"),
        ("GET", "/memorials/manfred/voice-ab"),
        ("POST", "/memorials/manfred/voice-ab/rate"),
        ("GET", "/memorials/manfred/voice-config"),
        ("GET", "/memorials/manfred/voice-profile"),
        ("POST", "/memorials/manfred/contributions"),
        ("POST", "/memorials/manfred/share-drafts"),
        ("POST", "/memorials/manfred/whatsapp-draft"),
        ("GET", "/memorials/other"),
        ("POST", "/memorials/other/conversation-turn"),
        ("GET", "/tours/manfred"),
        ("GET", "/app/research/candidate-1"),
        ("GET", "/memorials/manfred/speech-transcribe"),
        ("POST", "/memorials/manfred"),
    ],
)
def test_memorial_only_boundary_denies_every_non_conversation_http_surface_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)
    handler_calls = 0

    def forbidden_handler() -> PlainTextResponse:
        nonlocal handler_calls
        handler_calls += 1
        return PlainTextResponse("must-not-run")

    application.add_api_route(path, forbidden_handler, methods=[method])
    response = TestClient(application).request(
        method,
        path,
        headers={"Host": "myexternalbrain.com"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "not_found"}
    assert response.headers["cache-control"] == "no-store"
    assert handler_calls == 0


def test_memorial_only_boundary_is_fail_closed_for_websockets_before_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)
    forbidden_calls = 0

    @application.websocket("/memorials/manfred/realtime")
    async def allowed_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "ready"})

    @application.websocket("/internal/ws")
    async def forbidden_socket(websocket: WebSocket) -> None:
        nonlocal forbidden_calls
        forbidden_calls += 1
        await websocket.accept()

    client = TestClient(application)
    with client.websocket_connect(
        "wss://myexternalbrain.com/memorials/manfred/realtime",
        headers={"Origin": "https://myexternalbrain.com"},
    ) as websocket:
        assert websocket.receive_json() == {"type": "ready"}

    for url, headers, expected_code in (
        (
            "wss://myexternalbrain.com/internal/ws",
            {"Origin": "https://myexternalbrain.com"},
            4404,
        ),
        (
            "wss://myexternalbrain.com/memorials/other/realtime",
            {"Origin": "https://myexternalbrain.com"},
            4404,
        ),
        (
            "wss://myexternalbrain.com/memorials/manfred/realtime",
            {"Origin": "https://propertyquarry.com"},
            4403,
        ),
        (
            "wss://propertyquarry.com/memorials/manfred/realtime",
            {"Origin": "https://myexternalbrain.com"},
            4403,
        ),
        (
            "wss://myexternalbrain.com/memorials/manfred%2Frealtime",
            {"Origin": "https://myexternalbrain.com"},
            4404,
        ),
    ):
        with pytest.raises(WebSocketDisconnect) as blocked:
            with client.websocket_connect(url, headers=headers):
                pass
        assert blocked.value.code == expected_code
    assert forbidden_calls == 0


def test_exact_memorial_only_runtime_blocks_property_and_tour_surfaces_e2e(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)

    @application.get("/app/research/{candidate_ref}")
    def property_surface(candidate_ref: str) -> PlainTextResponse:
        return PlainTextResponse(candidate_ref)

    @application.get("/tours/{slug}")
    def tour_surface(slug: str) -> PlainTextResponse:
        return PlainTextResponse(slug)

    client = TestClient(application)
    for path in ("/app/research/candidate-1", "/tours/manfred"):
        response = client.get(path, headers={"Host": "propertyquarry.com"})
        assert response.status_code == 404
        assert response.json() == {"detail": "not_found"}
        assert response.headers["cache-control"] == "no-store"


def test_create_app_enforces_memorial_only_public_topology_e2e(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_RUNTIME_MODE", "test")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    # Even contradictory feature flags cannot expose these planes while the
    # effective deploy topology is exactly MEMORIAL-only.
    monkeypatch.setenv("EA_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("PROPERTYQUARRY_ENABLE_PUBLIC_TOURS", "1")
    monkeypatch.setenv("EA_ENABLE_LEGACY_RUNTIME_SURFACES", "0")

    client = TestClient(app_module.create_app())
    request_headers = {"Host": "myexternalbrain.com"}

    root = client.get(
        "/?next=https%3A%2F%2Fevil.example%2Fcapture",
        headers=request_headers,
        follow_redirects=False,
    )
    root_head = client.head("/", headers=request_headers, follow_redirects=False)
    tour = client.get("/tours/manfred", headers=request_headers)
    property_research = client.get(
        "/app/research/candidate-1",
        headers={"Host": "propertyquarry.com"},
    )
    wrong_origin_roots = [
        client.get(
            "/",
            headers={"Host": hostname},
            follow_redirects=False,
        )
        for hostname in ("propertyquarry.com", "jdownloader.girschele.com")
    ]
    healthz = client.get("/healthz", headers={"Host": "127.0.0.1:8090"})
    denied_surfaces = [
        client.request(method, path, headers=request_headers)
        for method, path in (
            ("GET", "/product"),
            ("GET", "/pricing"),
            ("GET", "/setup"),
            ("GET", "/admin"),
            ("GET", "/v1/providers/registry"),
            ("GET", "/app"),
            ("GET", "/archive-slug"),
            ("GET", "/memorials/manfred/archive"),
            ("GET", "/memorials/manfred/memory-room"),
            ("GET", "/memorials/other"),
        )
    ]

    assert root.status_code == 307
    assert root.headers["location"] == "/memorials/manfred"
    assert root_head.status_code == 307
    assert root_head.headers["location"] == "/memorials/manfred"
    assert tour.status_code == 404
    assert tour.json() == {"detail": "not_found"}
    assert property_research.status_code == 404
    assert property_research.json() == {"detail": "not_found"}
    assert all(response.status_code == 404 for response in wrong_origin_roots)
    assert all("location" not in response.headers for response in wrong_origin_roots)
    assert healthz.status_code == 200
    assert all(response.status_code == 404 for response in denied_surfaces)

    duplicate_host = client.get(
        "/",
        headers=[
            ("Host", "myexternalbrain.com"),
            ("Host", "jdownloader.girschele.com"),
        ],
        follow_redirects=False,
    )
    explicit_default_port = client.get(
        "/",
        headers={"Host": "myexternalbrain.com:443"},
        follow_redirects=False,
    )
    assert duplicate_host.status_code in {400, 404}
    assert "location" not in duplicate_host.headers
    assert explicit_default_port.status_code == 307
    assert explicit_default_port.headers["location"] == "/memorials/manfred"


@pytest.mark.parametrize(
    ("primary_mode", "enabled_modes"),
    [("EA_CORE", "EA_CORE"), ("MEMORIAL", "MEMORIAL,PROPERTY"), ("", "")],
)
def test_memorial_root_dispatch_leaves_every_other_mode_unchanged_e2e(
    monkeypatch: pytest.MonkeyPatch,
    primary_mode: str,
    enabled_modes: str,
) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    from app.api import app as app_module

    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", primary_mode)
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", enabled_modes)
    application = FastAPI()
    app_module.install_memorial_only_surface_boundary(application)

    @application.get("/")
    def generic_root() -> PlainTextResponse:
        return PlainTextResponse("generic")

    @application.get("/tours/{slug}")
    def tour_surface(slug: str) -> PlainTextResponse:
        return PlainTextResponse(slug)

    client = TestClient(application)
    root = client.get("/", follow_redirects=False)
    tour = client.get("/tours/example")

    assert root.status_code == 200
    assert root.text == "generic"
    assert tour.status_code == 200
    assert tour.text == "example"


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


@pytest.mark.parametrize("bundle_included", [False, True])
def test_candidate_runtime_projection_includes_exact_conversation_bundle(
    tmp_path: Path,
    bundle_included: bool,
) -> None:
    projection = tmp_path / "projection"
    roots = {
        container_path: projection / projected_path
        for container_path, projected_path in candidate_runner.RUNTIME_PROJECTION_ROOTS
    }
    fixture_files = {
        roots["/data/memorial/public"] / "manfred" / "memorial.json": (
            b'{"slug":"manfred"}\n',
            0o444,
        ),
        roots["/data/memorial/private"] / "manfred" / "tts_voice.json": (
            b'{"voice":"private"}\n',
            0o440,
        ),
        roots["/data/memorial/archive"] / "manfred" / "public" / "index.json": (
            b"{}\n",
            0o444,
        ),
        roots["/data/release-authority"] / "release_manifest.generated.json": (
            b"{}\n",
            0o444,
        ),
    }
    if bundle_included:
        fixture_files[
            roots["/data/memorial_data/conversation-release"]
            / candidate_prep.CONVERSATION_PREREQUISITES_FILENAME
        ] = (b'{"status":"pass"}\n', 0o440)
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    for path, (content, mode) in fixture_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
    for directory in sorted(projection.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.chmod(0o550)
    projection.chmod(0o550)

    script = candidate_runner.RUNTIME_PROJECTION_SNAPSHOT_SCRIPT
    for container_path, fixture_path in sorted(
        roots.items(), key=lambda item: len(item[0]), reverse=True
    ):
        script = script.replace(container_path, str(fixture_path))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_projection = json.loads(completed.stdout)
    projection_sha256, projection_rows = candidate_prep._tree_digest(projection)

    assert runtime_projection == {
        "projection_sha256": projection_sha256,
        "rows": projection_rows,
        "schema": candidate_runner.RUNTIME_PROJECTION_SCHEMA,
    }
    conversation_rows = [
        row
        for row in projection_rows
        if str(row["path"]).startswith(
            f"{candidate_prep.CONVERSATION_RELEASE_DIRNAME}/"
        )
    ]
    assert len(conversation_rows) == (1 if bundle_included else 0)


def test_candidate_runtime_projection_roots_are_exactly_conversation_only() -> None:
    assert candidate_runner.RUNTIME_PROJECTION_ROOTS == (
        ("/data/memorial/public", "public_memorials"),
        ("/data/memorial/private", "private_memorial_profiles"),
        ("/data/memorial/archive", "memorial_archive"),
        (
            "/data/memorial_data/conversation-release",
            candidate_prep.CONVERSATION_RELEASE_DIRNAME,
        ),
        ("/data/release-authority", "release-authority"),
    )
    assert "public_property_tours" not in (
        candidate_runner.RUNTIME_PROJECTION_SNAPSHOT_SCRIPT
    )
    assert "propertyquarry" not in (
        candidate_runner.RUNTIME_PROJECTION_SNAPSHOT_SCRIPT.casefold()
    )


@pytest.mark.parametrize(
    "missing_container_root",
    [container_path for container_path, _ in candidate_runner.RUNTIME_PROJECTION_ROOTS],
)
def test_candidate_runtime_projection_blocks_when_required_root_is_missing(
    tmp_path: Path,
    missing_container_root: str,
) -> None:
    projection = tmp_path / "projection"
    roots = {
        container_path: projection / projected_path
        for container_path, projected_path in candidate_runner.RUNTIME_PROJECTION_ROOTS
    }
    for container_path, root in roots.items():
        if container_path == missing_container_root:
            continue
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o550)
    projection.chmod(0o550)

    script = candidate_runner.RUNTIME_PROJECTION_SNAPSHOT_SCRIPT
    for container_path, fixture_path in sorted(
        roots.items(), key=lambda item: len(item[0]), reverse=True
    ):
        script = script.replace(container_path, str(fixture_path))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "FileNotFoundError" in completed.stderr


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
    assert environment["EA_DEPLOY_ENABLED_MODES"] == "MEMORIAL"
    assert environment["EA_DEPLOY_COMPOSE_FILES"] == (
        "deploy/manfred-memorial/docker-compose.candidate.yml"
    )
    assert environment["EA_STORAGE_BACKEND"] == "postgres"
    assert environment["EA_ENABLE_LEGACY_RUNTIME_SURFACES"] == "1"
    assert environment["PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES"] == "1"
    assert environment["EA_ENABLE_PUBLIC_TOURS"] == "0"
    assert environment["PROPERTYQUARRY_ENABLE_PUBLIC_TOURS"] == "0"
    assert environment["EA_ENABLE_PUBLIC_MEMORIALS"] == "1"
    assert environment["EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES"] == "0"
    assert environment["EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION"] == "0"
    assert environment["EA_MEMORIAL_VOICE_PREVIEW_ENABLED"] == "0"
    assert environment["EA_MEMORIAL_DEPLOYMENT_ID"].startswith(
        "${EA_MEMORIAL_DEPLOYMENT_ID"
    )
    assert environment["EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH"] == (
        candidate_prep.CONVERSATION_PREREQUISITES_CONTAINER_PATH
    )
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
        "${EA_MANFRED_RELEASE_ROOT:?prepared release root is required}/"
        "conversation-release:/data/memorial_data/conversation-release:ro"
        in api["volumes"]
    )

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


def test_tracked_memorial_candidate_runtime_mode_is_memorial_only() -> None:
    project_modes = {
        "modes": [
            {"key": "MEMORIAL"},
            {"key": "PROPERTY"},
        ]
    }

    def validate(enabled_modes: list[str]) -> list[str]:
        return candidate_prep.validate_release_runtime_mode(
            release_manifest={
                "contract_name": "ea.release_manifest.v1",
                "project_mode": "MEMORIAL",
                "enabled_project_modes": enabled_modes,
                "compose_files": [
                    "deploy/manfred-memorial/docker-compose.candidate.yml"
                ],
                "compose_overrides": [],
            },
            project_modes=project_modes,
            requested_mode="MEMORIAL",
            enabled_modes=enabled_modes,
            compose_overrides=[],
            manfred_composite_candidate_observed=True,
        )

    assert validate(["MEMORIAL"]) == []
    assert "memorial_mode_missing_override" in validate(
        ["MEMORIAL", "PROPERTY"]
    )


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


def test_candidate_keeps_spatial_scaffold_unregistered(
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


def test_public_memorial_singular_alias_is_permanent_safe_and_schema_hidden() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.public_memorial_surface import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

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


def test_candidate_spatial_review_inputs_are_rejected_from_memorial_lane(
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
            "--image-build-receipt",
            str(tmp_path / "image-build.json"),
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
    monkeypatch.setattr(candidate_prep, "_commit", lambda *_args: COMMIT)
    monkeypatch.setattr(
        candidate_prep,
        "_image_revision",
        lambda _image: ("sha256:" + "1" * 64, COMMIT),
    )
    unlocked_prepare = candidate_prep.prepare_candidate.__wrapped__
    with pytest.raises(
        ValueError,
        match="manfred_candidate_spatial_inputs_forbidden_in_conversation_only",
    ):
        unlocked_prepare(
            source_root=tmp_path,
            ref="HEAD",
            image="ea-runtime:manfred-abcdef123456",
            deploy_root=tmp_path / "deploy",
            public_base_url="https://memorial.example.at",
            host_port=18090,
            project_name=PROJECT,
            image_build_receipt=tmp_path / "image-build.json",
            spatial_tour_bundle_dir=tmp_path / "bundle",
            spatial_authority_receipt=tmp_path / "authority.json",
            spatial_final_review_receipt=tmp_path / "review" / ".." / "final.json",
            spatial_browser_review_receipt=tmp_path / "browser.json",
        )


@pytest.mark.parametrize(
    "spatial_inputs",
    [
        {
            "spatial_tour_bundle_dir": Path("bundle"),
            "spatial_authority_receipt": Path("authority.json"),
        },
        {
            "spatial_tour_bundle_dir": Path("bundle"),
            "spatial_authority_receipt": Path("authority.json"),
            "spatial_final_review_receipt": Path("final.json"),
        },
        {
            "spatial_final_review_receipt": Path("final.json"),
            "spatial_browser_review_receipt": Path("browser.json"),
        },
    ],
)
def test_candidate_spatial_review_inputs_fail_closed_as_out_of_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spatial_inputs: dict[str, Path],
) -> None:
    monkeypatch.setattr(candidate_prep, "_commit", lambda *_args: COMMIT)
    monkeypatch.setattr(
        candidate_prep,
        "_image_revision",
        lambda _image: ("sha256:" + "1" * 64, COMMIT),
    )

    with pytest.raises(
        ValueError,
        match="manfred_candidate_spatial_inputs_forbidden_in_conversation_only",
    ):
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


@pytest.mark.parametrize(
    ("receipt_present", "evidence_present"),
    [(True, False), (False, True)],
)
def test_candidate_conversation_prerequisite_inputs_must_be_paired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_present: bool,
    evidence_present: bool,
) -> None:
    monkeypatch.setattr(candidate_prep, "_commit", lambda *_args: COMMIT)
    monkeypatch.setattr(
        candidate_prep,
        "_image_revision",
        lambda _image: ("sha256:" + "1" * 64, COMMIT),
    )

    with pytest.raises(
        ValueError,
        match="manfred_candidate_conversation_prerequisites_inputs_incomplete",
    ):
        candidate_prep.prepare_candidate.__wrapped__(
            source_root=tmp_path,
            ref="HEAD",
            image="ea-runtime:manfred-abcdef123456",
            deploy_root=tmp_path / "deploy",
            public_base_url="https://memorial.example.at",
            host_port=18090,
            project_name=PROJECT,
            conversation_prerequisites_receipt=(
                tmp_path / "prerequisites.json" if receipt_present else None
            ),
            conversation_evidence_root=(
                tmp_path / "evidence" if evidence_present else None
            ),
        )


def _write_private_json(path: Path, payload: dict[str, object]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    encoded = candidate_prep._receipt_bytes(payload)
    path.write_bytes(encoded)
    path.chmod(0o600)
    return encoded


def test_candidate_stages_exact_conversation_prerequisites_privately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = "f" * 64
    receipt_path = tmp_path / "operator" / "prerequisites.json"
    packet_bytes = _write_private_json(
        receipt_path,
        {
            "status": "pass",
            "conversation_prerequisites_pass": True,
            "source_git_head": COMMIT,
            "source_state_fingerprint": fingerprint,
            "effective_expires_at": "2026-07-21T00:00:00Z",
        },
    )
    evidence_root = tmp_path / "evidence"
    readiness_bytes = _write_private_json(
        evidence_root / candidate_prep.CONVERSATION_READINESS_FILENAME,
        {"kind": "readiness"},
    )
    source_bytes: dict[str, bytes] = {
        candidate_prep.CONVERSATION_READINESS_FILENAME: readiness_bytes,
    }
    for key, filename in candidate_prep.CONVERSATION_EVIDENCE_FILENAMES.items():
        source_bytes[filename] = _write_private_json(
            evidence_root / filename,
            {"kind": key},
        )
    source_tts = tmp_path / "source" / "tts_voice.json"
    staged_tts = tmp_path / "staging" / "private" / "tts_voice.json"
    _write_private_json(source_tts, {"voice": "source"})
    _write_private_json(staged_tts, {"voice": "source"})
    staged_tts.chmod(0o400)
    authority_root = tmp_path / "staging" / "release-authority"
    for path in candidate_prep._candidate_release_authority_paths(
        authority_root
    ).values():
        _write_private_json(path, {"authority": path.name})
    authority_before = {
        path.name: path.read_bytes()
        for path in authority_root.iterdir()
    }
    destination = tmp_path / "staging" / candidate_prep.CONVERSATION_RELEASE_DIRNAME
    calls: list[dict[str, object]] = []

    def verify(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        supplied_receipt = Path(str(kwargs["receipt_path"]))
        supplied_root = Path(str(kwargs["readiness_evidence_root"]))
        assert kwargs["expected_source_git_head"] == COMMIT
        assert kwargs["expected_source_state_fingerprint"] == fingerprint
        if len(calls) == 1:
            assert supplied_receipt == receipt_path.resolve()
            assert supplied_root == evidence_root.resolve()
        else:
            assert supplied_receipt == (
                destination
                / candidate_prep.CONVERSATION_PREREQUISITES_FILENAME
            )
            assert supplied_root == destination
            assert supplied_receipt.read_bytes() == packet_bytes
            for filename, expected in source_bytes.items():
                assert (destination / filename).read_bytes() == expected
        return {
            "contract_name": candidate_prep.CONVERSATION_VERIFY_CONTRACT,
            "status": "pass",
            "issues": [],
        }

    monkeypatch.setattr(
        candidate_prep,
        "_canonical_conversation_prerequisites_verification",
        verify,
    )
    evidence = candidate_prep._stage_conversation_prerequisites(
        receipt_path=receipt_path,
        evidence_root=evidence_root,
        destination_root=destination,
        source_tts_voice_path=source_tts,
        staged_tts_voice_path=staged_tts,
        authority_root=authority_root,
        expected_source_git_head=COMMIT,
        expected_source_state_fingerprint=fingerprint,
    )

    assert len(calls) == 2
    assert evidence["packet_sha256"] == candidate_prep._sha256(packet_bytes)
    assert evidence["readiness_receipt_sha256"] == candidate_prep._sha256(
        readiness_bytes
    )
    assert evidence["room_audio_receipt_sha256"] == candidate_prep._sha256(
        source_bytes[candidate_prep.CONVERSATION_ROOM_FILENAME]
    )
    assert len(evidence["evidence_sha256"]) == 8
    assert len(evidence["files"]) == 10
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o400
        for path in destination.iterdir()
    )
    candidate_prep._set_modes(tmp_path / "staging")
    _digest, projected = candidate_prep._tree_digest(tmp_path / "staging")
    conversation_rows = [
        row
        for row in projected
        if str(row["path"]).startswith(
            f"{candidate_prep.CONVERSATION_RELEASE_DIRNAME}/"
        )
    ]
    assert len(conversation_rows) == 10
    assert {row["mode"] for row in conversation_rows} == {"440"}
    assert authority_before == {
        path.name: path.read_bytes()
        for path in authority_root.iterdir()
    }


def test_candidate_initial_and_final_conversation_projections_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    private_source = (
        source_root
        / "memorial_data"
        / "private_memorial_profiles"
        / "manfred"
    )
    private_source.mkdir(parents=True)
    image_id = "sha256:" + "1" * 64
    fingerprint = "f" * 64
    authority_artifact_sets: list[list[str]] = []

    monkeypatch.setattr(candidate_prep, "_commit", lambda *_args: COMMIT)
    monkeypatch.setattr(
        candidate_prep,
        "_image_revision",
        lambda _image: (image_id, COMMIT),
    )
    monkeypatch.setattr(
        candidate_prep,
        "_image_build_authority_binding",
        lambda *_args, **_kwargs: {"status": "pass"},
    )
    monkeypatch.setattr(
        candidate_prep,
        "_commit_generated_at",
        lambda *_args: "2026-07-20T00:00:00Z",
    )

    def git_blob(_root: Path, _commit: str, path: str) -> bytes:
        if path.endswith("/memorial.json"):
            return b'{"slug":"manfred"}\n'
        return b"{}\n"

    monkeypatch.setattr(candidate_prep, "_git_blob", git_blob)
    monkeypatch.setattr(
        candidate_prep,
        "_load_private_context",
        lambda *_args: ({}, b'{"slug":"manfred"}\n'),
    )

    def copy_archive(**kwargs: object) -> list[dict[str, object]]:
        Path(str(kwargs["destination"])).mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr(candidate_prep, "_copy_archive", copy_archive)

    def materialize_authority(**kwargs: object) -> dict[str, object]:
        root = Path(str(kwargs["root"]))
        artifacts = list(kwargs["public_artifacts"])
        authority_artifact_sets.append(artifacts)
        for name, path in candidate_prep._candidate_release_authority_paths(
            root
        ).items():
            candidate_prep._write_bytes(
                path,
                candidate_prep._receipt_bytes(
                    {
                        "document": name,
                        "artifact_set": artifacts,
                        "commit": COMMIT,
                    }
                ),
                mode=0o444,
            )
        return {"status": "pass"}

    monkeypatch.setattr(
        candidate_prep,
        "_materialize_candidate_release_authority",
        materialize_authority,
    )
    monkeypatch.setattr(
        candidate_prep,
        "_validate_candidate_release_authority_bundle",
        lambda *_args, **_kwargs: {"status": "pass"},
    )
    monkeypatch.setattr(candidate_prep, "_chown_for_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        candidate_prep,
        "resolve_source_worktree_fingerprint",
        lambda _root: fingerprint,
    )

    bundle_contents = {
        candidate_prep.CONVERSATION_PREREQUISITES_FILENAME: b"packet\n",
        candidate_prep.CONVERSATION_READINESS_FILENAME: b"readiness\n",
        **{
            filename: f"{key}\n".encode("ascii")
            for key, filename in candidate_prep.CONVERSATION_EVIDENCE_FILENAMES.items()
        },
    }

    def stage_bundle(**kwargs: object) -> dict[str, object]:
        destination = Path(str(kwargs["destination_root"]))
        files: list[dict[str, object]] = []
        for filename, content in sorted(bundle_contents.items()):
            info = candidate_prep._write_bytes(
                destination / filename,
                content,
                mode=0o400,
            )
            files.append(
                {
                    "path": (
                        f"{candidate_prep.CONVERSATION_RELEASE_DIRNAME}/"
                        f"{filename}"
                    ),
                    **info,
                }
            )
        return {
            "effective_expires_at": "2026-07-21T00:00:00Z",
            "packet_sha256": candidate_prep._sha256(
                bundle_contents[
                    candidate_prep.CONVERSATION_PREREQUISITES_FILENAME
                ]
            ),
            "readiness_receipt_sha256": candidate_prep._sha256(
                bundle_contents[candidate_prep.CONVERSATION_READINESS_FILENAME]
            ),
            "room_audio_receipt_sha256": candidate_prep._sha256(
                bundle_contents[candidate_prep.CONVERSATION_ROOM_FILENAME]
            ),
            "evidence_sha256": {
                key: candidate_prep._sha256(bundle_contents[filename])
                for key, filename in candidate_prep.CONVERSATION_EVIDENCE_FILENAMES.items()
            },
            "source_state_fingerprint": fingerprint,
            "files": files,
        }

    monkeypatch.setattr(
        candidate_prep,
        "_stage_conversation_prerequisites",
        stage_bundle,
    )
    common = {
        "source_root": source_root,
        "ref": "HEAD",
        "image": "ea-runtime:manfred-abcdef123456",
        "public_base_url": "https://myexternalbrain.com",
        "host_port": 18090,
        "project_name": PROJECT,
        "image_build_receipt": tmp_path / "image-build.json",
    }
    initial = candidate_prep.prepare_candidate.__wrapped__(
        deploy_root=tmp_path / "initial",
        **common,
    )
    final = candidate_prep.prepare_candidate.__wrapped__(
        deploy_root=tmp_path / "final",
        conversation_prerequisites_receipt=tmp_path / "packet.json",
        conversation_evidence_root=tmp_path / "evidence",
        **common,
    )

    assert initial["conversation_prerequisites_included"] is False
    assert initial["public_voice_activation_intended"] is False
    assert initial["conversation_release_files"] == []
    assert initial["conversation_prerequisites_sha256"] == ""
    assert final["conversation_prerequisites_included"] is True
    assert final["public_voice_activation_intended"] is True
    assert final["conversation_prerequisites_effective_expires_at"] == (
        "2026-07-21T00:00:00Z"
    )
    assert len(final["conversation_release_files"]) == 10
    assert {row["mode"] for row in final["conversation_release_files"]} == {
        "440"
    }
    assert authority_artifact_sets[0] == authority_artifact_sets[1]
    assert all(
        not path.startswith(f"{candidate_prep.CONVERSATION_RELEASE_DIRNAME}/")
        for path in authority_artifact_sets[0]
    )
    initial_authority = (
        Path(str(initial["release_root"]))
        / candidate_prep.CANDIDATE_RELEASE_AUTHORITY_DIRNAME
    )
    final_authority = (
        Path(str(final["release_root"]))
        / candidate_prep.CANDIDATE_RELEASE_AUTHORITY_DIRNAME
    )
    assert {
        path.name: path.read_bytes() for path in initial_authority.iterdir()
    } == {path.name: path.read_bytes() for path in final_authority.iterdir()}


@pytest.mark.parametrize(
    "issue",
    [
        "release_receipt_content_mismatch",
        "readiness_expired",
        "voice_manfred_identity_mismatch",
        "release_authority_status_not_exact_pass",
        "readiness_source_binding_mismatch",
    ],
)
def test_candidate_canonical_conversation_verifier_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    issue: str,
) -> None:
    from ea.scripts import manfred_realtime_conversation_release as release

    monkeypatch.setattr(
        release,
        "verify_manfred_realtime_conversation_release",
        lambda **_kwargs: {
            "contract_name": candidate_prep.CONVERSATION_VERIFY_CONTRACT,
            "status": "fail",
            "issues": [issue],
        },
    )
    with pytest.raises(
        ValueError,
        match="manfred_candidate_conversation_prerequisites_not_pass",
    ):
        candidate_prep._canonical_conversation_prerequisites_verification(
            receipt_path=tmp_path / "packet.json",
            readiness_receipt_path=tmp_path / "readiness.json",
            readiness_evidence_root=tmp_path,
            room_receipt_path=tmp_path / "room.json",
            tts_voice_path=tmp_path / "tts_voice.json",
            release_manifest_path=tmp_path / "manifest.json",
            release_authority_status_path=tmp_path / "status.json",
            project_modes_path=tmp_path / "modes.json",
            expected_source_git_head=COMMIT,
            expected_source_state_fingerprint="f" * 64,
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
    assert second["EA_MEMORIAL_DEPLOYMENT_ID"] == second[
        "EA_MANFRED_DEPLOYMENT_ID"
    ]
    assert second["EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH"] == (
        candidate_prep.CONVERSATION_PREREQUISITES_CONTAINER_PATH
    )
    assert second["EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION"] == "0"
    assert second["EA_MEMORIAL_VOICE_PREVIEW_ENABLED"] == "1"
    assert second["EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES"] == "1"

    bundled_path = tmp_path / "bundled-candidate.env"
    candidate_prep._write_env(
        path=bundled_path,
        image="ea-runtime:manfred-abcdef123456",
        release_root=release_root,
        runtime_root=runtime_root,
        public_base_url="https://memorial.example.at",
        host_port=18090,
        project_name=PROJECT,
        commit=COMMIT,
        conversation_prerequisites_included=True,
    )
    bundled = candidate_prep._parse_env(bundled_path)
    assert bundled["EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION"] == "1"
    assert bundled["EA_MEMORIAL_VOICE_PREVIEW_ENABLED"] == "0"
    assert bundled["EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES"] == "0"
    for candidate_env in (second, bundled):
        runtime_environment = candidate_runner._expected_candidate_api_environment(
            candidate_env
        )
        assert runtime_environment["EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION"] == "0"
        assert runtime_environment["EA_MEMORIAL_VOICE_PREVIEW_ENABLED"] == "0"
        assert runtime_environment[
            "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES"
        ] == "0"
        assert runtime_environment["EA_MEMORIAL_DEPLOYMENT_ID"] == (
            candidate_env["EA_MEMORIAL_DEPLOYMENT_ID"]
        )
        assert runtime_environment[
            "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH"
        ] == candidate_prep.CONVERSATION_PREREQUISITES_CONTAINER_PATH

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
    assert evidence["project_mode"] == "MEMORIAL"
    assert evidence["enabled_project_modes"] == ["MEMORIAL"]
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
    deploy_context = json.loads(
        paths["deploy_context"].read_text(encoding="utf-8")
    )
    authority_receipt = json.loads(
        paths["receipt"].read_text(encoding="utf-8")
    )
    for payload in (manifest, deploy_context, authority_receipt):
        assert payload["project_mode"] == "MEMORIAL"
        assert payload["enabled_project_modes"] == ["MEMORIAL"]

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
        "EA_MANFRED_MEMORIAL_SURFACE": candidate_prep.MEMORIAL_SURFACE,
        "EA_MANFRED_SPATIAL_SCOPE": candidate_prep.SPATIAL_SCOPE,
        "EA_MEMORIAL_DEPLOYMENT_ID": f"{PROJECT}-{COMMIT[:12]}",
        "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH": (
            candidate_prep.CONVERSATION_PREREQUISITES_CONTAINER_PATH
        ),
        "EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION": "0",
        "EA_MEMORIAL_VOICE_PREVIEW_ENABLED": "1",
        "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES": "1",
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
            "source": str(release_root / "conversation-release"),
            "target": "/data/memorial_data/conversation-release",
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


def test_manfred_public_page_selects_conversation_only_surface_explicitly() -> None:
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
    assert '<details class="conversation-settings">' not in conversation_only_html
    assert 'id="memorial-conversation"' in conversation_only_html
    assert 'id="memorial-text-turn-form"' in conversation_only_html
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
        "conversation_settings_count": 0,
        "memory_room_link_count": 0,
        "tour_link_count": 0,
        "missing_required_ids": [],
        "present_forbidden_ids": [],
    }
    assert ".memorial-theme-minimal::before" in manfred_html
    assert ".memorial-theme-minimal .story-card" in manfred_html
    assert ".memorial-theme-minimal .skip-link:focus-visible" in manfred_html
    assert '<body class="memorial-theme-minimal"' not in other_html
    assert "data-memorial-theme=" not in other_html


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
