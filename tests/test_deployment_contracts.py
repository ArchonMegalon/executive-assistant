from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_base_compose_omits_host_docker_control_for_core_services() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    for service_name in ("ea-api", "ea-worker", "ea-scheduler", "ea-responses-proxy"):
        service = services.get(service_name) or {}
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        assert not any("/var/run/docker.sock" in item for item in volumes), service_name
        assert not any(item.startswith("/docker:") or ":/docker" in item for item in volumes), service_name


def test_base_compose_keeps_core_runtime_ports_loopback_only() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    expected = {
        "ea-api": "127.0.0.1:${EA_HOST_PORT:-8090}:8090",
        "ea-responses-proxy": "127.0.0.1:${EA_RESPONSES_PROXY_HOST_PORT:-8092}:8091",
    }
    for service_name, port_mapping in expected.items():
        service = services.get(service_name) or {}
        ports = [str(item) for item in list(service.get("ports") or [])]
        assert port_mapping in ports, service_name
        assert all(item.startswith("127.0.0.1:") for item in ports), service_name


def test_base_compose_trusts_token_authenticated_principal_header_on_loopback_api() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    service = services.get("ea-api") or {}
    environment = [str(item) for item in list(service.get("environment") or [])]

    assert "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER=${EA_TRUST_API_TOKEN_PRINCIPAL_HEADER:-1}" in environment
    assert "EA_ALLOW_LOOPBACK_NO_AUTH=${EA_ALLOW_LOOPBACK_NO_AUTH:-0}" in environment


def test_base_compose_applies_core_runtime_privilege_limits() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    for service_name in ("ea-api", "ea-worker", "ea-scheduler", "ea-responses-proxy"):
        service = services.get(service_name) or {}
        assert service.get("read_only") is True, service_name
        assert service.get("pids_limit") == 512, service_name
        assert set(str(item) for item in list(service.get("cap_drop") or [])) == {"ALL"}, service_name
        assert "no-new-privileges:true" in list(service.get("security_opt") or []), service_name
        assert set(str(item) for item in list(service.get("tmpfs") or [])) == {"/tmp", "/run"}, service_name


def test_base_compose_gives_pocket_sync_a_writable_durable_archive() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    expected_env = "EA_POCKET_AUDIO_ARCHIVE_ROOT=${EA_POCKET_AUDIO_ARCHIVE_ROOT:-/data/pocket-ai-audio}"
    expected_volume = "${EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT:-./data/pocket-ai-audio}:/data/pocket-ai-audio"

    for service_name in ("ea-api", "ea-worker", "ea-scheduler", "ea-responses-proxy", "ea-proactive-ooda"):
        service = services.get(service_name) or {}
        environment = [str(item) for item in list(service.get("environment") or [])]
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        assert expected_env in environment, service_name
        assert expected_volume in volumes, service_name


def test_base_compose_loads_optional_local_env_for_provider_runtime_only() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}

    for service_name in ("ea-api", "ea-worker", "ea-scheduler", "ea-responses-proxy"):
        service = services.get(service_name) or {}
        env_files = list(service.get("env_file") or [])
        assert ".env" in env_files, service_name
        assert {"path": ".env.local", "required": False} in env_files, service_name

    for service_name in ("ea-teable-relay", "ea-proactive-ooda", "ea-telegram-teable-sync", "ea-db"):
        service = services.get(service_name) or {}
        env_files = list(service.get("env_file") or [])
        assert {"path": ".env.local", "required": False} not in env_files, service_name


def test_base_compose_applies_auxiliary_runtime_privilege_limits() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    expected = {
        "ea-teable-relay": {"pids_limit": 256, "mem_limit": "512m", "mem_reservation": "128m"},
        "ea-proactive-ooda": {"pids_limit": 256, "mem_limit": "512m", "mem_reservation": "128m"},
        "ea-telegram-teable-sync": {"pids_limit": 256, "mem_limit": "512m", "mem_reservation": "128m"},
    }
    for service_name, expected_contract in expected.items():
        service = services.get(service_name) or {}
        assert service.get("read_only") is True, service_name
        assert service.get("pids_limit") == expected_contract["pids_limit"], service_name
        assert service.get("mem_limit") == expected_contract["mem_limit"], service_name
        assert service.get("mem_reservation") == expected_contract["mem_reservation"], service_name
        assert set(str(item) for item in list(service.get("cap_drop") or [])) == {"ALL"}, service_name
        assert "no-new-privileges:true" in list(service.get("security_opt") or []), service_name
        assert set(str(item) for item in list(service.get("tmpfs") or [])) == {"/tmp", "/run"}, service_name


def test_base_compose_applies_stateful_service_privilege_limits() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    expected = {
        "ea-db": {
            "image": "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229",
            "pids_limit": 512,
            "mem_limit": "2g",
            "mem_reservation": "512m",
        },
        "ea-redis": {
            "image": "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
            "pids_limit": 256,
            "mem_limit": "512m",
            "mem_reservation": "128m",
        },
    }
    for service_name, expected_contract in expected.items():
        service = services.get(service_name) or {}
        assert service.get("image") == expected_contract["image"], service_name
        assert service.get("pids_limit") == expected_contract["pids_limit"], service_name
        assert service.get("mem_limit") == expected_contract["mem_limit"], service_name
        assert service.get("mem_reservation") == expected_contract["mem_reservation"], service_name
        assert list(service.get("cap_drop") or []) == [], service_name
        assert "no-new-privileges:true" in list(service.get("security_opt") or []), service_name
        assert set(str(item) for item in list(service.get("tmpfs") or [])) == {"/tmp", "/run"}, service_name


def test_overlay_compose_pins_third_party_runtime_images_by_digest() -> None:
    host_tools = _load_yaml(ROOT / "docker-compose.host-tools.yml")
    fastestvpn = _load_yaml(ROOT / "docker-compose.fastestvpn.yml")
    cloudflared = _load_yaml(ROOT / "docker-compose.cloudflared.yml")

    assert (
        ((host_tools.get("services") or {}).get("ea-docker-socket-proxy") or {}).get("image")
        == "tecnativa/docker-socket-proxy:0.3.0@sha256:9e4b9e7517a6b660f2cc903a19b257b1852d5b3344794e3ea334ff00ae677ac2"
    )
    assert (
        ((fastestvpn.get("services") or {}).get("ea-docker-socket-proxy") or {}).get("image")
        == "tecnativa/docker-socket-proxy:0.3.0@sha256:9e4b9e7517a6b660f2cc903a19b257b1852d5b3344794e3ea334ff00ae677ac2"
    )
    assert (
        ((cloudflared.get("services") or {}).get("ea-cloudflared") or {}).get("image")
        == "cloudflare/cloudflared:latest@sha256:6d91c121b803126f7a5344005d17a9324788fc09d305b6e2560ec6040a7ae283"
    )
    cloudflared_service = ((cloudflared.get("services") or {}).get("ea-cloudflared") or {})
    assert cloudflared_service.get("mem_limit") == "256m"
    assert cloudflared_service.get("mem_reservation") == "64m"
    assert cloudflared_service.get("pids_limit") == 128
    assert set(str(item) for item in list(cloudflared_service.get("cap_drop") or [])) == {"ALL"}
    assert "no-new-privileges:true" in list(cloudflared_service.get("security_opt") or [])


def test_property_compose_keeps_api_loopback_only_and_applies_runtime_limits() -> None:
    compose = _load_yaml(ROOT / "docker-compose.property.yml")
    services = compose.get("services") or {}

    api = services.get("propertyquarry-api") or {}
    scheduler = services.get("propertyquarry-scheduler") or {}
    db = services.get("propertyquarry-db") or {}

    api_ports = [str(item) for item in list(api.get("ports") or [])]
    assert api_ports == ["127.0.0.1:${EA_HOST_PORT:-8090}:8090"]

    assert api.get("mem_limit") == "2g"
    assert api.get("mem_reservation") == "512m"
    assert api.get("pids_limit") == 512
    assert api.get("read_only") is True
    assert set(str(item) for item in list(api.get("cap_drop") or [])) == {"ALL"}
    assert "no-new-privileges:true" in list(api.get("security_opt") or [])
    assert set(str(item) for item in list(api.get("tmpfs") or [])) == {"/tmp", "/run"}
    assert [str(item) for item in list(api.get("command") or [])] == [
        "nice",
        "-n",
        "19",
        "python",
        "-m",
        "app.runner",
    ]

    assert scheduler.get("mem_limit") == "1g"
    assert scheduler.get("mem_reservation") == "256m"
    scheduler_command = "\n".join(str(item) for item in list(scheduler.get("command") or []))
    assert "nice -n 19" in scheduler_command
    assert "ionice -c 3" in scheduler_command
    assert scheduler.get("pids_limit") == 512
    assert scheduler.get("read_only") is True
    assert set(str(item) for item in list(scheduler.get("cap_drop") or [])) == {"ALL"}
    assert "no-new-privileges:true" in list(scheduler.get("security_opt") or [])
    assert set(str(item) for item in list(scheduler.get("tmpfs") or [])) == {"/tmp", "/run"}

    assert db.get("image") == "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229"
    assert [str(item) for item in list(db.get("entrypoint") or [])] == [
        "nice",
        "-n",
        "19",
        "/usr/local/bin/docker-entrypoint.sh",
    ]
    assert [str(item) for item in list(db.get("command") or [])] == ["postgres"]
    assert db.get("mem_limit") == "2g"
    assert db.get("mem_reservation") == "512m"
    assert db.get("pids_limit") == 512
    assert set(str(item) for item in list(db.get("cap_drop") or [])) == {"ALL"}
    assert "no-new-privileges:true" in list(db.get("security_opt") or [])
    assert set(str(item) for item in list(db.get("tmpfs") or [])) == {"/tmp", "/run"}


def test_prod_compose_does_not_widen_core_runtime_port_exposure() -> None:
    compose = _load_yaml(ROOT / "docker-compose.prod.yml")
    services = compose.get("services") or {}
    for service_name in ("ea-api", "ea-responses-proxy", "ea-worker", "ea-scheduler"):
        service = services.get(service_name) or {}
        assert "ports" not in service, service_name


def test_compose_does_not_ship_openvoice_tts_sidecar() -> None:
    base = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").lower()
    prod = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8").lower()
    rendered = "\n".join((base, prod))

    for token in (
        "ea-openvoice",
        "dockerfile.openvoice",
        "requirements-openvoice.txt",
        "ea_role=openvoice",
        "openvoice_base_url",
    ):
        assert token not in rendered


def test_prod_compose_does_not_restore_memorial_runtime_contract() -> None:
    compose = _load_yaml(ROOT / "docker-compose.prod.yml")
    service = (compose.get("services") or {}).get("ea-api") or {}
    environment = [str(item) for item in list(service.get("environment") or [])]
    volumes = [str(item) for item in list(service.get("volumes") or [])]
    rendered = "\n".join(environment + volumes)
    assert service.get("environment", {}).get("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER") == "0"
    assert service.get("environment", {}).get("EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID") == "${EA_CODEXEA_AUTHENTICATED_PRINCIPAL_ID:-codexea-runtime}"
    assert service.get("environment", {}).get("EA_ENABLE_LEGACY_RUNTIME_SURFACES") == "${EA_ENABLE_LEGACY_RUNTIME_SURFACES:-0}"

    for token in (
        "EA_ENABLE_PUBLIC_MEMORIALS",
        "EA_HEALTHCHECK_MEMORIAL_SLUG",
        "EA_PUBLIC_MEMORIAL_RATE_BACKEND",
        "EA_PUBLIC_MEMORIAL_REDIS_URL",
        "EA_MEMORIAL_LIVE_TTS_PLUGIN",
    ):
        assert token not in rendered
    assert "EA_PUBLIC_MEMORIAL_DIR" in rendered
    assert "EA_PRIVATE_MEMORIAL_PROFILE_DIR" in rendered
    assert "/data/memorial_data" not in rendered


def test_base_compose_matches_ea_core_boundary() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    banned_tokens = (
        "EA_ENABLE_PUBLIC_MEMORIALS",
        "EA_PUBLIC_MEMORIAL_DIR",
        "EA_PRIVATE_MEMORIAL_PROFILE_DIR",
        "EA_MEMORIAL_LIVE_TTS_PLUGIN",
        "EA_HEALTHCHECK_MEMORIAL_SLUG",
        "EA_PUBLIC_MEMORIAL_REDIS_URL",
        "EA_CREZLO_PROPERTY_TOUR_WORKER",
        "EA_MOOTION_MOVIE_WORKER",
        "EA_AVOMAP_FLYOVER_WORKER",
        "EA_BOOKA_BOOK_WORKER",
        "EA_PUBLIC_RESULT_PUBLISHER",
        "EA_WILLHABEN_PROPERTY_TOUR_REQUIRE_360",
    )
    for service_name in ("ea-api", "ea-worker", "ea-scheduler"):
        service = services.get(service_name) or {}
        environment = [str(item) for item in list(service.get("environment") or [])]
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        rendered = "\n".join(environment + volumes)
        for token in banned_tokens:
            assert token not in rendered, f"{service_name} unexpectedly includes {token}"
        assert "/data/memorial_data" not in rendered, service_name


def test_host_tools_override_carries_explicit_host_docker_access() -> None:
    compose = _load_yaml(ROOT / "docker-compose.host-tools.yml")
    services = compose.get("services") or {}
    proxy = services.get("ea-docker-socket-proxy") or {}
    proxy_volumes = [str(item) for item in list(proxy.get("volumes") or [])]
    assert str(proxy.get("image", "")).startswith("tecnativa/docker-socket-proxy:0.3.0@sha256:")
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy_volumes
    assert proxy.get("read_only") is True
    assert proxy.get("mem_limit") == "256m"
    assert proxy.get("mem_reservation") == "64m"
    assert proxy.get("pids_limit") == 128
    assert set(str(item) for item in list(proxy.get("cap_drop") or [])) == {"ALL"}
    assert "no-new-privileges:true" in list(proxy.get("security_opt") or [])
    assert set(str(item) for item in list(proxy.get("tmpfs") or [])) == {"/run"}
    for service_name in ("ea-api", "ea-worker", "ea-scheduler"):
        service = services.get(service_name) or {}
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        environment = [str(item) for item in list(service.get("environment") or [])]
        build = service.get("build") or {}
        assert "/docker:/docker:ro" in volumes, service_name
        assert not any("/var/run/docker.sock" in item for item in volumes), service_name
        assert "DOCKER_HOST=tcp://ea-docker-socket-proxy:2375" in environment, service_name
        assert build.get("dockerfile") == "ea/Dockerfile.operator", service_name
        assert service.get("image") == "ea-runtime-operator:latest", service_name
        assert service.get("user") in (None, ""), service_name
        assert service.get("read_only") is True, service_name
        assert service.get("mem_limit") == "2g", service_name
        assert service.get("mem_reservation") == "512m", service_name
        assert service.get("pids_limit") == 512, service_name
        assert set(str(item) for item in list(service.get("cap_drop") or [])) == {"ALL"}, service_name
        assert "no-new-privileges:true" in list(service.get("security_opt") or []), service_name
        assert set(str(item) for item in list(service.get("tmpfs") or [])) == {"/tmp", "/run"}, service_name


def test_host_tools_override_leaves_responses_proxy_unprivileged() -> None:
    compose = _load_yaml(ROOT / "docker-compose.host-tools.yml")
    services = compose.get("services") or {}

    assert "ea-responses-proxy" not in services


def test_voicewave_override_does_not_restore_host_docker_access() -> None:
    compose = _load_yaml(ROOT / "docker-compose.voicewave-runtime.yml")
    service = (compose.get("services") or {}).get("ea-api") or {}
    volumes = [str(item) for item in list(service.get("volumes") or [])]
    environment = [str(item) for item in list(service.get("environment") or [])]

    assert not any("/var/run/docker.sock" in item for item in volumes)
    assert any(item.startswith("VOICEWAVE_RUNTIME_TMP_ROOT=") for item in environment)


def test_fastestvpn_override_mounts_only_runtime_compose_inputs() -> None:
    compose = _load_yaml(ROOT / "docker-compose.fastestvpn.yml")
    services = compose.get("services") or {}
    proxy = services.get("ea-docker-socket-proxy") or {}
    proxy_volumes = [str(item) for item in list(proxy.get("volumes") or [])]
    assert str(proxy.get("image", "")).startswith("tecnativa/docker-socket-proxy:0.3.0@sha256:")
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy_volumes
    assert proxy.get("read_only") is True
    assert proxy.get("mem_limit") == "256m"
    assert proxy.get("mem_reservation") == "64m"
    assert proxy.get("pids_limit") == 128
    assert set(str(item) for item in list(proxy.get("cap_drop") or [])) == {"ALL"}
    assert "no-new-privileges:true" in list(proxy.get("security_opt") or [])
    assert set(str(item) for item in list(proxy.get("tmpfs") or [])) == {"/run"}
    expected_mounts = {
        "./docker-compose.yml:/app/docker-compose.yml:ro",
        "./docker-compose.fastestvpn.yml:/app/docker-compose.fastestvpn.yml:ro",
        "./vpn/fastestvpn:/app/vpn/fastestvpn:ro",
    }
    for service_name in ("ea-api", "ea-worker", "ea-scheduler"):
        service = services.get(service_name) or {}
        volumes = {str(item) for item in list(service.get("volumes") or [])}
        environment = {str(item) for item in list(service.get("environment") or [])}
        assert volumes == expected_mounts, service_name
        assert "DOCKER_HOST=tcp://ea-docker-socket-proxy:2375" in environment, service_name
        assert service.get("read_only") is True, service_name
        assert service.get("mem_limit") == "2g", service_name
        assert service.get("mem_reservation") == "512m", service_name
        assert service.get("pids_limit") == 512, service_name
        assert set(str(item) for item in list(service.get("cap_drop") or [])) == {"ALL"}, service_name
        assert "no-new-privileges:true" in list(service.get("security_opt") or []), service_name
        assert set(str(item) for item in list(service.get("tmpfs") or [])) == {"/tmp", "/run"}, service_name


def test_memorial_override_restores_memorial_runtime_contract() -> None:
    compose = _load_yaml(ROOT / "docker-compose.memorial.yml")
    service = (compose.get("services") or {}).get("ea-api") or {}
    environment = [str(item) for item in list(service.get("environment") or [])]
    volumes = [str(item) for item in list(service.get("volumes") or [])]

    assert any(item.startswith("EA_ENABLE_PUBLIC_MEMORIALS=") for item in environment)
    assert any(item.startswith("EA_PUBLIC_MEMORIAL_DIR=") for item in environment)
    assert any(item.startswith("EA_PRIVATE_MEMORIAL_PROFILE_DIR=") for item in environment)
    assert "${EA_MEMORIAL_DATA_HOST_PATH:-./memorial_data}:/data/memorial_data:ro" in volumes
    assert "ea_memorial_data" not in set(str(name) for name in (compose.get("volumes") or {}).keys())


def test_memorial_runtime_overlay_verifier_passes_for_mounted_runtime() -> None:
    module = _load_script("verify_memorial_runtime_overlay")

    result = module.verify_memorial_runtime_overlay(
        base_url="http://ea.test",
        fetch_json=lambda url: {
            "status": "live",
            "public_surface_flags": {"public_memorials_enabled": "true"},
            "memorial_runtime": {
                "state": "mounted",
                "configured_enabled": True,
                "route_mounted": True,
                "healthcheck_slug": "manfred",
                "route_path": "/memorials/{slug}",
                "next_action": "",
            },
        },
    )

    assert result["status"] == "pass"
    assert result["issues"] == []
    assert result["memorial_runtime"]["state"] == "mounted"
    assert result["memorial_runtime"]["healthcheck_slug"] == "manfred"


def test_memorial_runtime_overlay_verifier_fails_closed_for_disabled_base_stack() -> None:
    module = _load_script("verify_memorial_runtime_overlay")

    result = module.verify_memorial_runtime_overlay(
        base_url="http://ea.test",
        fetch_json=lambda url: {
            "status": "live",
            "public_surface_flags": {"public_memorials_enabled": "false"},
            "memorial_runtime": {
                "state": "disabled",
                "configured_enabled": False,
                "route_mounted": False,
                "healthcheck_slug": "",
                "route_path": "/memorials/{slug}",
                "next_action": "start_runtime_with_memorial_overlay",
            },
        },
    )

    assert result["status"] == "fail"
    assert "memorial_runtime_not_enabled" in result["issues"]
    assert "memorial_route_not_mounted" in result["issues"]
    assert "memorial_runtime_state_not_mounted:disabled" in result["issues"]
    assert result["next_action"] == "start_runtime_with_memorial_overlay"


def test_memorial_runtime_overlay_verifier_uses_container_loopback_fallback(monkeypatch) -> None:
    module = _load_script("verify_memorial_runtime_overlay")

    monkeypatch.setattr(
        module,
        "_fetch_container_health_live",
        lambda: {
            "status": "live",
            "public_surface_flags": {"public_memorials_enabled": "true"},
            "memorial_runtime": {
                "state": "mounted",
                "configured_enabled": True,
                "route_mounted": True,
                "healthcheck_slug": "manfred",
                "route_path": "/memorials/{slug}",
                "next_action": "",
            },
        },
    )

    result = module.verify_memorial_runtime_overlay(
        base_url="http://localhost:8090",
        fetch_json=lambda url: {"status": "live"},
    )

    assert result["status"] == "pass"
    assert result["source"] == "container_loopback_fallback"
    assert result["memorial_runtime"]["state"] == "mounted"


def test_provider_lab_override_restores_operator_media_lanes() -> None:
    compose = _load_yaml(ROOT / "docker-compose.provider-lab.yml")
    services = compose.get("services") or {}
    for service_name in ("ea-api", "ea-worker", "ea-scheduler"):
        service = services.get(service_name) or {}
        environment = [str(item) for item in list(service.get("environment") or [])]
        rendered = "\n".join(environment)
        for token in (
            "EA_CREZLO_PROPERTY_TOUR_WORKER",
            "EA_MOOTION_MOVIE_WORKER",
            "EA_AVOMAP_FLYOVER_WORKER",
            "EA_BOOKA_BOOK_WORKER",
            "EA_PUBLIC_RESULT_PUBLISHER",
        ):
            assert token in rendered, f"{service_name} missing {token}"


def test_release_manifest_materializer_emits_authority_fields(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "EA_CORE")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "EA_CORE")

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:40:00Z")

    assert manifest["contract_name"] == "ea.release_manifest.v1"
    assert manifest["repository"] == "EA"
    assert manifest["generated_at"] == "2026-06-22T18:40:00Z"
    assert set(
        (
            "branch",
            "tracking_branch",
            "commit_sha",
            "dirty_worktree",
            "source_worktree_dirty",
            "source_dirty_count",
            "source_dirty_files",
            "source_dirty_omitted_count",
            "source_dirty_status_sha256",
            "deploy_context_generated_at",
            "deploy_context_branch",
            "deploy_context_tracking_branch",
            "deploy_context_commit_sha",
            "deployment_id",
            "deployment_id_source",
            "public_origin",
            "public_origin_source",
            "git_remote_origin",
            "compose_files",
            "compose_overrides",
            "artifact_set",
            "release_label",
        )
    ) <= set(manifest)
    assert manifest["project_mode"] == "EA_CORE"
    assert manifest["enabled_project_modes"] == ["EA_CORE"]
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted == manifest
    assert str(manifest["deployment_id"]).strip()


def test_release_manifest_prefers_public_app_origin(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://ea.example.test/")

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:41:00Z")

    assert manifest["public_origin"] == "https://ea.example.test"
    assert manifest["public_origin_source"] == "EA_PUBLIC_APP_BASE_URL"


def test_release_manifest_reads_public_origin_from_repo_env_file(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)
    (tmp_path / ".env").write_text("EA_PUBLIC_APP_BASE_URL=https://from-env-file.example.test/\n", encoding="utf-8")

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:41:30Z")

    assert manifest["public_origin"] == "https://from-env-file.example.test"
    assert manifest["public_origin_source"] == "EA_PUBLIC_APP_BASE_URL"


def test_release_manifest_reads_explicit_deploy_id_from_deploy_context(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.setattr(module, "_DEPLOY_CONTEXT_CACHE", {})
    monkeypatch.delenv("EA_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "deployment_id": "deploy-ctx-123",
                "deployment_id_source": "explicit",
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:41:45Z")

    assert manifest["deployment_id"] == "deploy-ctx-123"
    assert manifest["deployment_id_source"] == "explicit"


def test_deploy_context_materializer_emits_authority_tuple(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_deploy_context")
    output_path = tmp_path / "deploy_context.generated.json"
    monkeypatch.setenv("EA_DEPLOYMENT_ID", "deploy-ctx-456")
    monkeypatch.setenv("EA_DEPLOY_REPOSITORY", "executive-assistant")
    monkeypatch.setenv("EA_DEPLOY_PUBLIC_ORIGIN", "https://ea.example.test")
    monkeypatch.setenv("EA_DEPLOY_PUBLIC_ORIGIN_SOURCE", "EA_PUBLIC_APP_BASE_URL")
    monkeypatch.setenv("EA_DEPLOY_BRANCH", "main")
    monkeypatch.setenv("EA_DEPLOY_TRACKING_BRANCH", "origin/main")
    monkeypatch.setenv("EA_DEPLOY_COMMIT_SHA", "deployctxcommit1234567890")
    monkeypatch.setenv("EA_RELEASE_LABEL", "weekly-2026-06-23")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "EA_CORE")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "EA_CORE,PROVIDER_LAB")
    monkeypatch.setenv("EA_DEPLOY_COMPOSE_FILES", "docker-compose.yml,docker-compose.prod.yml")
    monkeypatch.setenv("EA_DEPLOY_COMPOSE_OVERRIDES", "docker-compose.provider-lab.yml")

    payload = module.build_deploy_context(output_path=output_path, generated_at="2026-06-23T09:10:00Z")

    assert payload == json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["contract_name"] == "ea.deploy_context.v1"
    assert payload["generated_at"] == "2026-06-23T09:10:00Z"
    assert payload["repository"] == "executive-assistant"
    assert payload["deployment_id"] == "deploy-ctx-456"
    assert payload["deployment_id_source"] == "ea_deploy_id_env"
    assert payload["public_origin"] == "https://ea.example.test"
    assert payload["branch"] == "main"
    assert payload["tracking_branch"] == "origin/main"
    assert payload["commit_sha"] == "deployctxcommit1234567890"
    assert payload["release_label"] == "weekly-2026-06-23"
    assert payload["project_mode"] == "EA_CORE"
    assert payload["enabled_project_modes"] == ["EA_CORE", "PROVIDER_LAB"]
    assert payload["compose_files"] == ["docker-compose.yml", "docker-compose.prod.yml"]
    assert payload["compose_overrides"] == ["docker-compose.provider-lab.yml"]


def test_deploy_context_materializer_allows_explicit_deployment_source_override(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_deploy_context")
    output_path = tmp_path / "deploy_context.generated.json"
    monkeypatch.setenv("EA_DEPLOYMENT_ID", "local-ctx-456")
    monkeypatch.setenv("EA_DEPLOYMENT_ID_SOURCE", "local_fallback")
    monkeypatch.setenv("EA_DEPLOY_PUBLIC_ORIGIN", "https://ea.example.test")
    monkeypatch.setenv("EA_DEPLOY_PUBLIC_ORIGIN_SOURCE", "EA_PUBLIC_APP_BASE_URL")
    monkeypatch.setenv("EA_DEPLOY_BRANCH", "main")
    monkeypatch.setenv("EA_DEPLOY_TRACKING_BRANCH", "origin/main")
    monkeypatch.setenv("EA_DEPLOY_COMMIT_SHA", "deployctxcommit1234567890")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "EA_CORE")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "EA_CORE")
    monkeypatch.setenv("EA_DEPLOY_COMPOSE_FILES", "docker-compose.yml,docker-compose.prod.yml")

    payload = module.build_deploy_context(output_path=output_path, generated_at="2026-06-23T09:11:00Z")

    assert payload["deployment_id"] == "local-ctx-456"
    assert payload["deployment_id_source"] == "local_fallback"


def test_deploy_context_materializer_reads_platform_deployment_id(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_deploy_context")
    output_path = tmp_path / "deploy_context.generated.json"
    monkeypatch.delenv("EA_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("EA_DEPLOYMENT_ID_SOURCE", raising=False)
    monkeypatch.delenv("EA_RELEASE_LABEL", raising=False)
    monkeypatch.delenv("RELEASE_LABEL", raising=False)
    monkeypatch.setenv("DEPLOYMENT_ID", "platform-ctx-456")
    monkeypatch.setenv("EA_DEPLOY_PUBLIC_ORIGIN", "https://ea.example.test")
    monkeypatch.setenv("EA_DEPLOY_PUBLIC_ORIGIN_SOURCE", "EA_PUBLIC_APP_BASE_URL")
    monkeypatch.setenv("EA_DEPLOY_BRANCH", "main")
    monkeypatch.setenv("EA_DEPLOY_TRACKING_BRANCH", "origin/main")
    monkeypatch.setenv("EA_DEPLOY_COMMIT_SHA", "deployctxcommit1234567890")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "EA_CORE")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "EA_CORE")
    monkeypatch.setenv("EA_DEPLOY_COMPOSE_FILES", "docker-compose.yml,docker-compose.prod.yml")

    payload = module.build_deploy_context(output_path=output_path, generated_at="2026-06-23T09:11:30Z")

    assert payload["deployment_id"] == "platform-ctx-456"
    assert payload["deployment_id_source"] == "deploy_platform"
    assert payload["release_label"] == "platform-ctx-456"


def test_deploy_context_materializer_uses_repo_and_env_defaults(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_deploy_context")
    output_path = tmp_path / "deploy_context.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.delenv("EA_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("EA_DEPLOY_BRANCH", raising=False)
    monkeypatch.delenv("EA_DEPLOY_TRACKING_BRANCH", raising=False)
    monkeypatch.delenv("EA_DEPLOY_COMMIT_SHA", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PUBLIC_ORIGIN_SOURCE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)
    monkeypatch.delenv("EA_DEPLOY_COMPOSE_FILES", raising=False)
    monkeypatch.delenv("EA_DEPLOY_COMPOSE_OVERRIDES", raising=False)
    monkeypatch.delenv("EA_RELEASE_LABEL", raising=False)
    monkeypatch.delenv("RELEASE_LABEL", raising=False)
    (tmp_path / ".env").write_text(
        "EA_PUBLIC_APP_BASE_URL=https://ea.example.test/\n"
        "EA_DEPLOY_PRIMARY_MODE=MEMORIAL\n"
        "EA_DEPLOY_ENABLED_MODES=MEMORIAL,PROVIDER_LAB\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_git",
        lambda *args: {
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
            ("rev-parse", "HEAD"): "abcdef1234567890abcdef1234567890abcdef12",
        }.get(tuple(args), ""),
    )

    payload = module.build_deploy_context(output_path=output_path, generated_at="2026-06-23T09:12:00Z")

    assert payload["repository"] == tmp_path.name
    assert payload["branch"] == "main"
    assert payload["tracking_branch"] == "origin/main"
    assert payload["commit_sha"] == "abcdef1234567890abcdef1234567890abcdef12"
    assert payload["deployment_id"] == "local-20260623T091200Z-abcdef123456"
    assert payload["deployment_id_source"] == "local_fallback"
    assert payload["public_origin"] == "https://ea.example.test"
    assert payload["public_origin_source"] == "EA_PUBLIC_APP_BASE_URL"
    assert payload["project_mode"] == "MEMORIAL"
    assert payload["enabled_project_modes"] == ["MEMORIAL", "PROVIDER_LAB"]
    assert payload["compose_files"] == ["docker-compose.yml", "docker-compose.prod.yml"]
    assert payload["release_label"] == "local-20260623T091200Z-abcdef123456"


def test_deploy_context_verifier_accepts_complete_payload() -> None:
    module = _load_script("verify_deploy_context")
    payload = {
        "contract_name": "ea.deploy_context.v1",
        "repository": "executive-assistant",
        "deployment_id": "deploy-ctx-456",
        "deployment_id_source": "deploy_script_generated",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "deployctxcommit1234567890",
        "release_label": "weekly-2026-06-23",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE", "PROVIDER_LAB"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "compose_overrides": ["docker-compose.provider-lab.yml"],
    }

    result = module.verify(deploy_context=payload)

    assert result["contract_name"] == "ea.deploy_context_gate.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []


def test_deploy_context_verifier_rejects_incomplete_payload() -> None:
    module = _load_script("verify_deploy_context")
    payload = {
        "contract_name": "wrong.contract.v1",
        "repository": "",
        "deployment_id": "",
        "deployment_id_source": "",
        "public_origin": "",
        "public_origin_source": "",
        "branch": "",
        "tracking_branch": "",
        "commit_sha": "",
        "release_label": "",
        "project_mode": "EA_CORE",
        "enabled_project_modes": [],
        "compose_files": [],
    }

    result = module.verify(deploy_context=payload)

    assert result["status"] == "fail"
    assert "deploy_context_contract_invalid" in result["issues"]
    assert "missing_repository" in result["issues"]
    assert "missing_deployment_id" in result["issues"]
    assert "missing_release_label" in result["issues"]
    assert "enabled_project_modes_empty" in result["issues"]
    assert "compose_files_empty" in result["issues"]


def test_deploy_context_verifier_rejects_invalid_source_and_local_source_mismatch() -> None:
    module = _load_script("verify_deploy_context")
    payload = {
        "contract_name": "ea.deploy_context.v1",
        "repository": "executive-assistant",
        "deployment_id": "local-ctx-456",
        "deployment_id_source": "deploy_script_generated",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "deployctxcommit1234567890",
        "release_label": "weekly-2026-06-23",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
    }

    result = module.verify(deploy_context=payload)

    assert result["status"] == "fail"
    assert "deployment_id_source_mismatch" in result["issues"]

    payload["deployment_id_source"] = "unknown_source"
    result = module.verify(deploy_context=payload)
    assert "invalid_deployment_id_source" in result["issues"]
    assert result["status"] == "fail"


def test_deploy_context_verifier_rejects_local_fallback_deployment_id() -> None:
    module = _load_script("verify_deploy_context")
    payload = {
        "contract_name": "ea.deploy_context.v1",
        "repository": "executive-assistant",
        "deployment_id": "local-ctx-456",
        "deployment_id_source": "local_fallback",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "deployctxcommit1234567890",
        "release_label": "weekly-2026-06-23",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
    }

    result = module.verify(deploy_context=payload)

    assert result["status"] == "fail"
    assert "deployment_id_local_fallback" in result["issues"]


def test_release_manifest_reads_deploy_context_commit_binding(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.setattr(module, "_DEPLOY_CONTEXT_CACHE", {})
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "repository": "executive-assistant",
                "generated_at": "2026-06-22T18:42:00Z",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "deployctxcommit1234567890",
                "release_label": "weekly-2026-06-23",
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:42:30Z")

    assert manifest["deploy_context_generated_at"] == "2026-06-22T18:42:00Z"
    assert manifest["deploy_context_branch"] == "main"
    assert manifest["deploy_context_tracking_branch"] == "origin/main"
    assert manifest["deploy_context_commit_sha"] == "deployctxcommit1234567890"
    assert manifest["repository"] == "executive-assistant"
    assert manifest["release_label"] == "weekly-2026-06-23"


def test_release_manifest_regenerates_stale_local_fallback_deployment_id_from_old_deploy_context(
    monkeypatch: object, tmp_path: Path
) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.setattr(module, "_DEPLOY_CONTEXT_CACHE", {})
    monkeypatch.delenv("EA_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("EA_RELEASE_LABEL", raising=False)
    monkeypatch.delenv("RELEASE_LABEL", raising=False)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://ea.example.test")
    monkeypatch.setattr(
        module,
        "_git",
        lambda *args: {
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/main",
            ("rev-parse", "HEAD"): "newcommit1234567890abcdef1234567890abcdef",
            ("status", "--short"): " M .codex-studio/published/release_manifest.generated.json\n",
            ("remote", "get-url", "origin"): "https://github.com/ArchonMegalon/executive-assistant.git",
        }.get(tuple(args), ""),
    )
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "deployment_id": "local-20260629T015658001260Z-oldcommit1234",
                "deployment_id_source": "local_fallback",
                "release_label": "local-20260629T015658001260Z-oldcommit1234",
                "commit_sha": "oldcommit1234567890abcdef1234567890abcdef",
                "branch": "main",
                "tracking_branch": "origin/main",
                "generated_at": "2026-06-29T01:56:58.001260Z",
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-30T08:15:00Z")

    assert manifest["deployment_id"] == "local-20260630T081500Z-newcommit123"
    assert manifest["deployment_id_source"] == "local_fallback"
    assert manifest["release_label"] == "newcommit123"
    assert manifest["deploy_context_commit_sha"] == "oldcommit1234567890abcdef1234567890abcdef"


def test_release_manifest_ignores_invalid_deploy_context_contract(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", "https://from-env.example.test")
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "EA_CORE")
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "wrong.contract.v1",
                "deployment_id": "deploy-ctx-ignored",
                "public_origin": "https://from-deploy-context.example.test",
                "public_origin_source": "PROPERTYQUARRY_PUBLIC_BASE_URL",
                "project_mode": "MEMORIAL",
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-23T09:20:00Z")

    assert manifest["public_origin"] == "https://from-env.example.test"
    assert manifest["public_origin_source"] == "EA_PUBLIC_APP_BASE_URL"
    assert manifest["project_mode"] == "EA_CORE"
    assert manifest["deploy_context_generated_at"] == ""
    assert manifest["deploy_context_branch"] == ""
    assert manifest["deploy_context_tracking_branch"] == ""
    assert manifest["deploy_context_commit_sha"] == ""


def test_release_manifest_reads_modes_and_compose_topology_from_deploy_context(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.setattr(module, "_DEPLOY_CONTEXT_CACHE", {})
    monkeypatch.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_PROJECT_MODE", raising=False)
    monkeypatch.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)
    monkeypatch.delenv("EA_DEPLOY_ENABLED_PROJECT_MODES", raising=False)
    monkeypatch.delenv("EA_DEPLOY_COMPOSE_FILES", raising=False)
    monkeypatch.delenv("EA_DEPLOY_COMPOSE_OVERRIDES", raising=False)
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "deployment_id": "deploy-ctx-123",
                "deployment_id_source": "explicit",
                "project_mode": "MEMORIAL",
                "enabled_project_modes": ["MEMORIAL", "PROVIDER_LAB"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml", "docker-compose.memorial.yml"],
                "compose_overrides": ["docker-compose.memorial.yml"],
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:41:50Z")

    assert manifest["project_mode"] == "MEMORIAL"
    assert manifest["enabled_project_modes"] == ["MEMORIAL", "PROVIDER_LAB"]
    assert manifest["compose_files"] == [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.memorial.yml",
    ]
    assert manifest["compose_overrides"] == ["docker-compose.memorial.yml"]


def test_release_manifest_prefers_deploy_context_public_origin_over_repo_env_file(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_ENV_FILE_CACHE", {})
    monkeypatch.setattr(module, "_DEPLOY_CONTEXT_CACHE", {})
    monkeypatch.delenv("EA_PUBLIC_APP_BASE_URL", raising=False)
    monkeypatch.delenv("PROPERTYQUARRY_PUBLIC_BASE_URL", raising=False)
    (tmp_path / ".env").write_text("EA_PUBLIC_APP_BASE_URL=https://from-env-file.example.test/\n", encoding="utf-8")
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "deployment_id": "deploy-ctx-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://from-deploy-context.example.test",
                "public_origin_source": "PROPERTYQUARRY_PUBLIC_BASE_URL",
            }
        ),
        encoding="utf-8",
    )

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:41:55Z")

    assert manifest["public_origin"] == "https://from-deploy-context.example.test"
    assert manifest["public_origin_source"] == "PROPERTYQUARRY_PUBLIC_BASE_URL"


def test_release_authority_status_materializer_emits_gate_summary(tmp_path: Path) -> None:
    module = _load_script("materialize_release_authority_status")
    manifest_path = tmp_path / "release_manifest.generated.json"
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    output_path = tmp_path / "release_authority_status.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "deploy_context_generated_at": "2026-06-23T07:10:00Z",
                "deploy_context_branch": "main",
                "deploy_context_tracking_branch": "origin/main",
                "deploy_context_commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "dirty_worktree": False,
                "source_worktree_dirty": False,
                "source_dirty_count": 0,
                "source_dirty_files": [],
                "source_dirty_omitted_count": 0,
                "source_dirty_status_sha256": "",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "deploy-123",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            }
        ),
        encoding="utf-8",
    )
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "repository": "EA",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "release_label": "deploy-123",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")

    payload = module.build_status(
        release_manifest_path=manifest_path,
        deploy_context_path=deploy_context_path,
        project_modes_path=project_modes_path,
        generated_at="2026-06-23T07:20:00Z",
    )
    module._write_json_stable(output_path, payload)

    assert payload["contract_name"] == "ea.release_authority_status.v1"
    assert payload["generated_at"] == "2026-06-23T07:20:00Z"
    assert payload["state"] == "clear"
    assert payload["authority_posture"] == "authoritative_runtime"
    assert payload["next_action"] == "No action required."
    assert payload["authority_basis"] == "main@origin/main · 0123456789ab · EA_CORE · docker-compose.yml, docker-compose.prod.yml"
    assert payload["release_label"] == "deploy-123"
    assert payload["artifact_count"] == 1
    assert payload["deploy_context_path"].endswith("deploy_context.generated.json")
    assert payload["deploy_context_gate"]["contract_name"] == "ea.deploy_context_gate.v1"
    assert payload["deploy_context_gate"]["status"] == "pass"
    assert payload["gate"]["contract_name"] == "ea.release_authority_gate.v1"
    assert payload["gate"]["status"] == "pass"
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted == payload


def test_release_authority_status_materializer_combines_local_deploy_and_dirty_worktree_guidance(tmp_path: Path) -> None:
    module = _load_script("materialize_release_authority_status")
    manifest_path = tmp_path / "release_manifest.generated.json"
    deploy_context_path = tmp_path / ".codex-studio" / "published" / "deploy_context.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "deploy_context_generated_at": "2026-06-23T07:10:00Z",
                "deploy_context_branch": "main",
                "deploy_context_tracking_branch": "origin/main",
                "deploy_context_commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "dirty_worktree": True,
                "source_worktree_dirty": True,
                "source_dirty_count": 2,
                "source_dirty_files": ["scripts/deploy.sh", "README.md"],
                "source_dirty_omitted_count": 0,
                "source_dirty_status_sha256": "abc123",
                "deployment_id": "local-20260623T071000Z-0123456789ab",
                "deployment_id_source": "local_fallback",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "local-20260623T071000Z-0123456789ab",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
            }
        ),
        encoding="utf-8",
    )
    deploy_context_path.parent.mkdir(parents=True, exist_ok=True)
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "repository": "EA",
                "deployment_id": "local-20260623T071000Z-0123456789ab",
                "deployment_id_source": "local_fallback",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "release_label": "local-20260623T071000Z-0123456789ab",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")

    payload = module.build_status(
        release_manifest_path=manifest_path,
        deploy_context_path=deploy_context_path,
        project_modes_path=project_modes_path,
        generated_at="2026-06-23T07:20:00Z",
    )

    assert payload["state"] == "watch"
    assert payload["authority_posture"] == "local_only_deploy_id"
    assert payload["issues"] == ["deployment_id_local_fallback", "dirty_worktree"]
    assert payload["next_action"] == "Deploy from a clean committed tree with an explicit deployment ID from the real deploy system, then rematerialize the release manifest."


def test_release_authority_status_materializer_pretty_flag_outputs_indented_json(tmp_path: Path) -> None:
    output_path = tmp_path / "release_authority_status.generated.json"
    manifest_path = tmp_path / "release_manifest.generated.json"
    deploy_context_path = tmp_path / "deploy_context.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"

    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "deploy_context_generated_at": "2026-06-23T07:10:00Z",
                "deploy_context_branch": "main",
                "deploy_context_tracking_branch": "origin/main",
                "deploy_context_commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "dirty_worktree": False,
                "source_worktree_dirty": False,
                "source_dirty_count": 0,
                "source_dirty_files": [],
                "source_dirty_omitted_count": 0,
                "source_dirty_status_sha256": "",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
                "release_label": "deploy-123",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [],
            }
        ),
        encoding="utf-8",
    )
    deploy_context_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.deploy_context.v1",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "materialize_release_authority_status.py"),
            "--output",
            str(output_path),
            "--release-manifest",
            str(manifest_path),
            "--deploy-context",
            str(deploy_context_path),
            "--project-modes",
            str(project_modes_path),
            "--pretty",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.startswith("{\n  ")


def test_release_manifest_carries_primary_and_enabled_project_modes(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "memorial")
    monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "memorial,provider_lab")

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:42:00Z")

    assert manifest["project_mode"] == "MEMORIAL"
    assert manifest["enabled_project_modes"] == ["MEMORIAL", "PROVIDER_LAB"]


def test_release_manifest_carries_compose_files_and_overrides(monkeypatch: object, tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"
    monkeypatch.setenv("EA_DEPLOY_COMPOSE_FILES", "docker-compose.yml,docker-compose.prod.yml,docker-compose.memorial.yml")
    monkeypatch.setenv("EA_DEPLOY_COMPOSE_OVERRIDES", "docker-compose.memorial.yml")

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:43:00Z")

    assert manifest["compose_files"] == [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.memorial.yml",
    ]
    assert manifest["compose_overrides"] == ["docker-compose.memorial.yml"]


def test_release_manifest_defaults_compose_files_when_not_exported(tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:43:30Z")

    assert manifest["compose_files"] == ["docker-compose.yml", "docker-compose.prod.yml"]


def test_release_manifest_runtime_mode_verifier_rejects_mixed_ea_core_plane() -> None:
    module = _load_script("verify_release_manifest_runtime_mode")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE", "PROVIDER_LAB"],
    }
    project_modes = {"modes": [{"key": "EA_CORE"}, {"key": "PROVIDER_LAB"}]}

    issues = module.validate_release_contract(
        release_manifest=release_manifest,
        project_modes=project_modes,
        requested_mode="EA_CORE",
        enabled_modes=["EA_CORE", "PROVIDER_LAB"],
        compose_overrides=["docker-compose.provider-lab.yml"],
    )

    assert "ea_core_must_not_mix_planes" in issues
    assert "ea_core_override_leak" in issues


def test_release_manifest_runtime_mode_verifier_accepts_memorial_plane_with_override() -> None:
    module = _load_script("verify_release_manifest_runtime_mode")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
    }
    project_modes = {"modes": [{"key": "EA_CORE"}, {"key": "MEMORIAL"}]}

    issues = module.validate_release_contract(
        release_manifest=release_manifest,
        project_modes=project_modes,
        requested_mode="MEMORIAL",
        enabled_modes=["MEMORIAL"],
        compose_overrides=["docker-compose.memorial.yml"],
    )

    assert issues == []


def test_release_manifest_artifact_plane_verifier_rejects_memorial_artifact_for_ea_core() -> None:
    module = _load_script("verify_release_manifest_artifact_plane")
    release_manifest = {
        "artifact_set": [
            ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
            ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        ]
    }

    issues = module.validate_artifact_plane(release_manifest=release_manifest, enabled_modes=["EA_CORE"])

    assert issues == [
        "artifact_outside_enabled_modes:.codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json:MEMORIAL"
    ]


def test_release_manifest_artifact_plane_verifier_allows_core_and_memorial_mix_for_memorial_mode() -> None:
    module = _load_script("verify_release_manifest_artifact_plane")
    release_manifest = {
        "artifact_set": [
            ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
            ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        ]
    }

    issues = module.validate_artifact_plane(release_manifest=release_manifest, enabled_modes=["MEMORIAL"])

    assert issues == []


def test_release_manifest_artifact_plane_verifier_allows_proactive_ooda_operator_status_for_ea_core() -> None:
    module = _load_script("verify_release_manifest_artifact_plane")
    release_manifest = {
        "artifact_set": [
            ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
            ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
        ]
    }

    issues = module.validate_artifact_plane(release_manifest=release_manifest, enabled_modes=["EA_CORE"])

    assert issues == []


def test_release_manifest_artifact_plane_verifier_allows_proactive_ooda_gold_acceptance_for_ea_core() -> None:
    module = _load_script("verify_release_manifest_artifact_plane")
    release_manifest = {
        "artifact_set": [
            ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
            ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
        ]
    }

    issues = module.validate_artifact_plane(release_manifest=release_manifest, enabled_modes=["EA_CORE"])

    assert issues == []


def test_release_authority_verifier_rejects_missing_public_origin() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "deploy_context_generated_at": "2026-06-23T07:12:00Z",
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "deployment_id": "deploy-123",
        "deployment_id_source": "explicit",
        "public_origin": "",
        "public_origin_source": "missing",
        "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
        "release_label": "deploy-123",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
    }
    project_modes = {"modes": [{"key": "EA_CORE"}]}

    issues = module.validate_release_authority(release_manifest=release_manifest, project_modes=project_modes)

    assert "public_origin_missing" in issues
    assert "public_origin_source_missing" in issues
    assert "public_origin_not_runtime_origin" in issues
    assert module._derive_authority_posture(issues) == "missing_public_origin"


def test_release_authority_verifier_rejects_local_deployment_and_dirty_worktree() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "89abcdef0123456789abcdef0123456789abcdef",
        "deployment_id": "local-20260622T000000Z-89abcdef0123",
        "deployment_id_source": "local_fallback",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
        "release_label": "deploy-123",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
        "dirty_worktree": True,
    }
    project_modes = {"modes": [{"key": "EA_CORE"}]}

    issues = module.validate_release_authority(release_manifest=release_manifest, project_modes=project_modes)

    assert "deployment_id_local_fallback" in issues
    assert "dirty_worktree" in issues
    assert "deploy_context_commit_mismatch" not in issues


def test_release_authority_verifier_does_not_report_stale_deploy_context_for_local_fallback_deployment() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "deploy_context_generated_at": "2026-06-22T18:42:00Z",
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "deployment_id": "local-20260622T000000Z-aaaaaaaaaaaa",
        "deployment_id_source": "local_fallback",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
        "release_label": "local-20260622T000000Z-aaaaaaaaaaaa",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
        "dirty_worktree": False,
    }
    project_modes = {"modes": [{"key": "EA_CORE"}]}

    issues = module.validate_release_authority(release_manifest=release_manifest, project_modes=project_modes)

    assert "deployment_id_local_fallback" in issues
    assert "deploy_context_commit_mismatch" not in issues
    assert module._derive_authority_posture(issues) == "local_only_deploy_id"


def test_release_authority_verifier_allows_generated_only_dirty_worktree() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "deploy_context_generated_at": "2026-06-23T07:13:00Z",
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "deployment_id": "deploy-123",
        "deployment_id_source": "explicit",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
        "release_label": "deploy-123",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
        "dirty_worktree": True,
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
        "source_dirty_status_sha256": "",
    }
    project_modes = {"modes": [{"key": "EA_CORE"}]}

    issues = module.validate_release_authority(release_manifest=release_manifest, project_modes=project_modes)

    assert "dirty_worktree" not in issues
    assert module._derive_authority_posture(issues) == "authoritative_runtime"


def test_release_authority_verifier_rejects_stale_deploy_context_commit() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "deploy_context_generated_at": "2026-06-22T18:42:00Z",
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "deployment_id": "deploy-123",
        "deployment_id_source": "explicit",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
        "release_label": "deploy-123",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
        "dirty_worktree": False,
    }
    project_modes = {"modes": [{"key": "EA_CORE"}]}

    issues = module.validate_release_authority(release_manifest=release_manifest, project_modes=project_modes)

    assert "deploy_context_commit_mismatch" in issues
    assert module._derive_authority_posture(issues) == "stale_deploy_context"


def test_release_authority_verifier_accepts_authoritative_runtime_manifest() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "deploy_context_generated_at": "2026-06-23T07:14:00Z",
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "deployment_id": "deploy-123",
        "deployment_id_source": "explicit",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "git_remote_origin": "https://github.com/ArchonMegalon/executive-assistant.git",
        "release_label": "deploy-123",
        "project_mode": "EA_CORE",
        "enabled_project_modes": ["EA_CORE"],
        "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
        "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
        "dirty_worktree": False,
    }
    project_modes = {"modes": [{"key": "EA_CORE"}]}

    issues = module.validate_release_authority(release_manifest=release_manifest, project_modes=project_modes)

    assert issues == []
    assert module._derive_authority_posture(issues) == "authoritative_runtime"


def test_release_authority_pretty_payload_includes_context_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "release_manifest.generated.json"
    project_modes_path = tmp_path / "PROJECT_MODES.generated.json"
    manifest_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_manifest.v1",
                "repository": "EA",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "deploy_context_generated_at": "2026-06-23T07:15:00Z",
                "deploy_context_branch": "main",
                "deploy_context_tracking_branch": "origin/main",
                "deploy_context_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "release_label": "deploy-123",
                "project_mode": "EA_CORE",
                "enabled_project_modes": ["EA_CORE"],
                "compose_files": ["docker-compose.yml", "docker-compose.prod.yml"],
                "compose_overrides": [],
                "artifact_set": [".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"],
                "dirty_worktree": True,
                "source_worktree_dirty": True,
                "source_dirty_count": 2,
                "source_dirty_files": ["ea/app/product/service.py", "scripts/deploy.sh"],
                "source_dirty_omitted_count": 1,
                "source_dirty_status_sha256": "abc123",
            }
        ),
        encoding="utf-8",
    )
    project_modes_path.write_text(json.dumps({"modes": [{"key": "EA_CORE"}]}), encoding="utf-8")

    import subprocess

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "verify_release_authority.py"),
            "--release-manifest",
            str(manifest_path),
            "--project-modes",
            str(project_modes_path),
            "--pretty",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["authority_posture"] == "dirty_worktree"
    assert payload["deployment_id"] == "deploy-123"
    assert payload["public_origin"] == "https://ea.example.test"
    assert payload["compose_files"] == ["docker-compose.yml", "docker-compose.prod.yml"]
    assert payload["deploy_context_commit_sha"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert payload["source_worktree_dirty"] is True
    assert payload["source_dirty_count"] == 2
    assert payload["source_dirty_files"] == ["ea/app/product/service.py", "scripts/deploy.sh"]
    assert payload["source_dirty_omitted_count"] == 1


def test_deploy_script_materializes_release_manifest_after_health() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert 'RELEASE_MANIFEST_PATH="${RELEASE_MANIFEST_PATH:-${APP_ROOT}/.codex-studio/published/release_manifest.generated.json}"' in deploy
    assert 'RELEASE_AUTHORITY_STATUS_PATH="${RELEASE_AUTHORITY_STATUS_PATH:-${APP_ROOT}/.codex-studio/published/release_authority_status.generated.json}"' in deploy
    assert 'DEPLOY_PRIMARY_MODE="${EA_DEPLOY_PRIMARY_MODE:-${EA_DEPLOY_PROJECT_MODE:-EA_CORE}}"' in deploy
    assert 'allow_dirty_worktree="${PROPERTYQUARRY_DEPLOY_ALLOW_DIRTY_WORKTREE:-${EA_DEPLOY_ALLOW_DIRTY_WORKTREE:-0}}"' in deploy
    assert "Refusing to deploy without a public runtime origin." in deploy
    assert "EA_PUBLIC_APP_BASE_URL=https://assistant.example.test" in deploy
    assert "PROPERTYQUARRY_PUBLIC_BASE_URL=https://property.example.test" in deploy
    assert "Refusing to deploy with placeholder workspace access token binding origin/issuer." in deploy
    assert "Do not deploy with example.test or localhost token-binding origins." in deploy
    assert 'api_token_value="$(normalize_origin_like "$(effective_value EA_API_TOKEN)")"' in deploy
    assert 'cf_access_team_domain="$(normalize_origin_like "$(effective_value EA_CF_ACCESS_TEAM_DOMAIN)")"' in deploy
    assert 'cf_access_aud="$(normalize_origin_like "$(effective_value EA_CF_ACCESS_AUD)")"' in deploy
    assert 'signing_secret_value="$(normalize_origin_like "$(effective_value EA_SIGNING_SECRET)")"' in deploy
    assert 'require_valid_prod_auth() {' in deploy
    assert 'require_valid_prod_auth "${api_token_value}" "${cf_access_team_domain}" "${cf_access_aud}"' in deploy
    assert 'require_non_placeholder_secret() {' in deploy
    assert 'require_non_placeholder_secret "EA_SIGNING_SECRET" "${signing_secret_value}"' in deploy
    assert 'ensure_runtime_readable_file_projection() {' in deploy
    assert 'ensure_runtime_readable_file_projection "ONEMIN_DIRECT_API_KEYS_JSON_FILE"' in deploy
    assert 'ensure_runtime_writable_dir_projection() {' in deploy
    assert 'ensure_runtime_writable_dir_projection "EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT" "./data/pocket-ai-audio"' in deploy
    assert 'mode="$(stat -c \'%a\' "${resolved_path}" 2>/dev/null || true)"' in deploy
    assert 'if [[ "${mode}" == "1777" ]]; then' in deploy
    assert 'scripts/materialize_whatsapp_callback_secret_runtime_projection.py" >/dev/null' in deploy
    assert 'setfacl -m u:10001:r "${resolved_path}"' in deploy
    assert 'chmod a+r,go-w "${resolved_path}"' in deploy
    assert "Refusing to deploy without production auth." in deploy
    assert "EA_API_TOKEN=<real-token>" in deploy
    assert "EA_CF_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com" in deploy
    assert "EA_CF_ACCESS_AUD=<audience>" in deploy
    assert "Refusing to deploy with placeholder EA_CF_ACCESS_TEAM_DOMAIN." in deploy
    assert "Refusing to deploy with placeholder EA_CF_ACCESS_AUD." in deploy
    assert "Refusing to deploy without ${key}." in deploy
    assert "Refusing to deploy with placeholder ${key}." in deploy
    assert "Set a real production value in .env before deploy." in deploy
    assert "Refusing to deploy without complete workspace access token binding metadata." in deploy
    assert "EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE=workspace-access" in deploy
    assert "EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION=v1" in deploy
    assert "Refusing to deploy with placeholder workspace access token binding metadata." in deploy
    assert "Do not deploy with placeholder token audience or key-version values." in deploy
    assert 'public_origin_value="$(normalize_origin_like "$(effective_value EA_PUBLIC_APP_BASE_URL)")"' in deploy
    assert 'workspace_issuer="$(normalize_origin_like "$(effective_value EA_WORKSPACE_ACCESS_TOKEN_ISSUER)")"' in deploy
    assert 'workspace_audience="$(normalize_origin_like "$(effective_value EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE)")"' in deploy
    assert 'workspace_key_version="$(normalize_origin_like "$(effective_value EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION)")"' in deploy
    assert "Refusing to deploy from a dirty git worktree." in deploy
    assert 'EA_DEPLOY_ALLOW_DIRTY_WORKTREE=1 bash scripts/deploy.sh' in deploy
    assert 'export EA_DEPLOYMENT_ID="deploy-$(date -u +%Y%m%dT%H%M%SZ)-${deploy_commit_fragment}"' in deploy
    assert 'EA_DEPLOY_COMPOSE_FILES="${compose_files_csv}" \\' in deploy
    assert 'EA_DEPLOY_COMPOSE_OVERRIDES="${compose_overrides_csv}" \\' in deploy
    assert 'export EA_DEPLOY_BRANCH="${deploy_branch}"' in deploy
    assert 'export EA_DEPLOY_TRACKING_BRANCH="${deploy_tracking_branch}"' in deploy
    assert 'export EA_DEPLOY_COMMIT_SHA="${deploy_commit_sha}"' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_deploy_context.py" --output "${DEPLOY_CONTEXT_PATH}" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_release_manifest.py" --output "${RELEASE_MANIFEST_PATH}" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_release_authority_status.py" \\' in deploy
    assert '--output "${RELEASE_AUTHORITY_STATUS_PATH}" \\' in deploy
    assert '--release-manifest "${RELEASE_MANIFEST_PATH}" >/dev/null' in deploy
    assert 'if ! "${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_authority.py" \\' in deploy
    assert '--release-manifest "${RELEASE_MANIFEST_PATH}" >/dev/null; then' in deploy
    assert "Refusing to publish a runtime without authoritative release evidence." in deploy
    assert "Fix the reported release-authority issues and rerun deploy." in deploy
    assert "verify_release_authority_manifest" in deploy
    assert "materialize_release_authority_status" in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_project_mode_manifests.py" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_project_mode_manifests.py" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_runtime_mode.py" "${verify_mode_args[@]}" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_artifact_plane.py" "${verify_artifact_args[@]}" >/dev/null' in deploy
    assert 'public_smoke_base_url="${public_origin_value:-https://example.test}"' in deploy
    assert '${public_smoke_base_url}/health' in deploy
    assert 'for _public in $(seq 1 60); do' in deploy
    assert 'echo "Release manifest written to ${RELEASE_MANIFEST_PATH}"' in deploy
    assert 'echo "Release authority status written to ${RELEASE_AUTHORITY_STATUS_PATH}"' in deploy


def test_deploy_script_extends_runtime_topology_for_whatsapp_overlay() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert 'if [[ "$(basename "${override}")" == "docker-compose.whatsapp-web-session.yml" ]]; then' in deploy
    assert "RUNTIME_RECREATE_ONLY_SERVICES=(ea-proactive-ooda ea-telegram-teable-sync)" in deploy
    assert "recreate_services_without_build() {" in deploy
    assert 'compose up -d --no-build --no-deps --force-recreate "${service}"' in deploy
    assert 'echo "Service failed to become ready during no-build deploy: ${service}" >&2' in deploy
    assert 'TOPOLOGY_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-proactive-ooda ea-telegram-teable-sync ea-db)' in deploy
    assert 'FAILURE_LOG_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-proactive-ooda ea-telegram-teable-sync ea-db)' in deploy
    assert 'recreate_services_without_build "${RUNTIME_RECREATE_ONLY_SERVICES[@]}"' in deploy
    assert 'RUNTIME_BUILD_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)' in deploy
    assert 'TOPOLOGY_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)' in deploy
    assert 'FAILURE_LOG_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)' in deploy
