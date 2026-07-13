from __future__ import annotations

import copy
import stat
from pathlib import Path

import pytest
import yaml

from scripts import build_manfred_memorial_image as image_builder
from scripts import prepare_manfred_memorial_candidate as candidate_prep
from scripts import run_manfred_memorial_candidate as candidate_runner
from scripts import verify_manfred_memorial_candidate as candidate_verify


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy/manfred-memorial/docker-compose.candidate.yml"
PROJECT = "ea-manfred-candidate-deployment-contract-a1b2c3d4"


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
    assert environment["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] == "0"
    assert environment["EA_TRUST_API_TOKEN_PRINCIPAL_HEADER"] == "0"
    assert environment["PYTHONPATH"] == "/app"

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

    candidate_prep._write_env(
        path=env_path,
        image="ea-runtime:manfred-abcdef123456",
        release_root=release_root,
        runtime_root=runtime_root,
        public_base_url="https://memorial.example.at",
        host_port=18090,
        project_name=PROJECT,
        rotate_secrets=True,
    )
    rotated = candidate_prep._parse_env(env_path)
    assert rotated["EA_API_TOKEN"] != second["EA_API_TOKEN"]
    assert rotated["EA_SIGNING_SECRET"] != second["EA_SIGNING_SECRET"]
    assert (
        rotated["EA_MANFRED_POSTGRES_PASSWORD"]
        != second["EA_MANFRED_POSTGRES_PASSWORD"]
    )


def test_runtime_runner_rejects_live_bind_or_external_network(tmp_path: Path) -> None:
    env_file = (tmp_path / "candidate.env").resolve()
    release_root = (tmp_path / "release").resolve()
    runtime_root = (tmp_path / "runtime").resolve()
    env = {
        "EA_MANFRED_COMPOSE_PROJECT": PROJECT,
        "EA_MANFRED_IMAGE": "ea-runtime:manfred-abcdef123456",
        "EA_MANFRED_HOST_PORT": "18090",
        "EA_MANFRED_RELEASE_ROOT": str(release_root),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root),
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
        {"type": "volume", "source": "artifacts", "target": "/data/artifacts"},
    ]
    declared_environment = {"EA_ROLE": "api"}
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
