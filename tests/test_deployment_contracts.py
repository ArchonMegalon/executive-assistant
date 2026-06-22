from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
    assert proxy.get("image") == "tecnativa/docker-socket-proxy:0.3.0"
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy_volumes
    for service_name in ("ea-api", "ea-worker", "ea-scheduler"):
        service = services.get(service_name) or {}
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        environment = [str(item) for item in list(service.get("environment") or [])]
        build = service.get("build") or {}
        assert any(item.startswith("/docker:") or ":/docker" in item for item in volumes), service_name
        assert not any("/var/run/docker.sock" in item for item in volumes), service_name
        assert "DOCKER_HOST=tcp://ea-docker-socket-proxy:2375" in environment, service_name
        assert build.get("dockerfile") == "ea/Dockerfile.operator", service_name
        assert service.get("image") == "ea-runtime-operator:latest", service_name


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
    assert proxy.get("image") == "tecnativa/docker-socket-proxy:0.3.0"
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in proxy_volumes
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


def test_memorial_override_restores_memorial_runtime_contract() -> None:
    compose = _load_yaml(ROOT / "docker-compose.memorial.yml")
    service = (compose.get("services") or {}).get("ea-api") or {}
    environment = [str(item) for item in list(service.get("environment") or [])]
    volumes = [str(item) for item in list(service.get("volumes") or [])]

    assert any(item.startswith("EA_ENABLE_PUBLIC_MEMORIALS=") for item in environment)
    assert any(item.startswith("EA_PUBLIC_MEMORIAL_DIR=") for item in environment)
    assert any(item.startswith("EA_PRIVATE_MEMORIAL_PROFILE_DIR=") for item in environment)
    assert any("/data/memorial_data" in item for item in volumes)


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


def test_release_manifest_materializer_emits_authority_fields(tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"

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


def test_release_authority_verifier_rejects_missing_public_origin() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
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
    assert module._derive_authority_posture(issues) == "local_only_deploy_id"


def test_release_authority_verifier_accepts_authoritative_runtime_manifest() -> None:
    module = _load_script("verify_release_authority")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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


def test_deploy_script_materializes_release_manifest_after_health() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert 'RELEASE_MANIFEST_PATH="${RELEASE_MANIFEST_PATH:-${APP_ROOT}/.codex-studio/published/release_manifest.generated.json}"' in deploy
    assert 'DEPLOY_PRIMARY_MODE="${EA_DEPLOY_PRIMARY_MODE:-${EA_DEPLOY_PROJECT_MODE:-EA_CORE}}"' in deploy
    assert 'allow_dirty_worktree="${PROPERTYQUARRY_DEPLOY_ALLOW_DIRTY_WORKTREE:-${EA_DEPLOY_ALLOW_DIRTY_WORKTREE:-0}}"' in deploy
    assert "Refusing to deploy without a public runtime origin." in deploy
    assert "EA_PUBLIC_APP_BASE_URL=https://assistant.example.test" in deploy
    assert "PROPERTYQUARRY_PUBLIC_BASE_URL=https://property.example.test" in deploy
    assert "Refusing to deploy from a dirty git worktree." in deploy
    assert 'EA_DEPLOY_ALLOW_DIRTY_WORKTREE=1 bash scripts/deploy.sh' in deploy
    assert 'export EA_DEPLOYMENT_ID="deploy-$(date -u +%Y%m%dT%H%M%SZ)-${deploy_commit_fragment}"' in deploy
    assert 'EA_DEPLOY_COMPOSE_FILES="${compose_files_csv}" \\' in deploy
    assert 'EA_DEPLOY_COMPOSE_OVERRIDES="${compose_overrides_csv}" \\' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_release_manifest.py" --output "${RELEASE_MANIFEST_PATH}" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_project_mode_manifests.py" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_project_mode_manifests.py" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_runtime_mode.py" "${verify_mode_args[@]}" >/dev/null' in deploy
    assert '"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_artifact_plane.py" "${verify_artifact_args[@]}" >/dev/null' in deploy
    assert 'echo "Release manifest written to ${RELEASE_MANIFEST_PATH}"' in deploy


def test_deploy_script_extends_runtime_topology_for_whatsapp_overlay() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert 'if [[ "$(basename "${override}")" == "docker-compose.whatsapp-web-session.yml" ]]; then' in deploy
    assert 'RUNTIME_BUILD_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)' in deploy
    assert 'TOPOLOGY_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)' in deploy
    assert 'FAILURE_LOG_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)' in deploy
