from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.prepare_ea_runtime_env import prepare_runtime_env


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "verify_audiobook_runtime_candidate.py"
SPEC = importlib.util.spec_from_file_location(
    "verify_audiobook_runtime_candidate", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

REVISION = "a" * 40
IMAGE_DIGEST = "sha256:" + ("b" * 64)
IMAGE_ID = "sha256:" + ("c" * 64)
IMAGE = f"registry.example.invalid/ea/runtime@{IMAGE_DIGEST}"
COMPOSE_VERSION = "2.38.2"
OVERLAY_SHA256 = "e" * 64


def _bind(source: Path, target: str, *, read_only: bool) -> dict[str, object]:
    return {
        "type": "bind",
        "source": str(source),
        "target": target,
        "read_only": read_only,
        "bind": {"create_host_path": False},
    }


def _fixture(tmp_path: Path, *, suffix: str = "one") -> tuple[dict[str, object], dict[str, str]]:
    fixture_root = tmp_path / suffix
    config = fixture_root / "config"
    durable = fixture_root / "audiobooks"
    jobs = durable / "jobs"
    shelf = durable / "audiobookshelf"
    onedrive = fixture_root / "onedrive"
    pocket_audio = fixture_root / "pocket-audio"
    gemini_config = fixture_root / "gemini-config"
    for directory in (config, jobs, shelf, onedrive, pocket_audio, gemini_config):
        directory.mkdir(parents=True, exist_ok=True)
    secret = fixture_root / "callback.secret"
    secret.write_text(f"callback-secret-{suffix}\n", encoding="utf-8")
    secret.chmod(0o600)

    sensitive_values = {
        "EA_AUDIOBOOKSHELF_API_BASE_URL": "https://abs.internal.invalid",
        "EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL": "https://listen.example.invalid",
        "EA_AUDIOBOOKSHELF_API_TOKEN": f"abs-api-token-that-must-not-leak-{suffix}",
        "EA_AUDIOBOOKSHELF_LIBRARY_ID": "library-id",
        "EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL": "https://player.example.invalid",
        "EA_AUDIOBOOK_ACCESS_SIGNING_SECRET": (
            f"access-signing-secret-that-must-not-leak-{suffix}"
        ),
        "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY": (
            f"canary-hmac-secret-that-must-not-leak-{suffix}"
        ),
    }
    environment = {
        **MODULE.SAFE_ENVIRONMENT,
        **sensitive_values,
        "EA_UNMIXR_PREFERRED_SLOTS": "UNMIXR_API_KEY_FALLBACK_1",
        "EA_UNMIXR_RESERVE_SLOTS": "UNMIXR_API_KEY",
        "EA_SOURCE_REVISION": REVISION,
        "EA_DEPLOY_COMMIT_SHA": REVISION,
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_REVISION": REVISION,
        "EA_AUDIOBOOK_RUNTIME_CANDIDATE_IMAGE_DIGEST": IMAGE_DIGEST,
        "EA_RELEASE_LABEL": f"audiobook-candidate-{REVISION}",
    }
    labels = {
        "org.opencontainers.image.revision": REVISION,
        "com.archonmegalon.ea.audiobook-runtime.contract": MODULE.OVERLAY_CONTRACT,
        "com.archonmegalon.ea.audiobook-runtime.source-revision": REVISION,
        "com.archonmegalon.ea.audiobook-runtime.image-digest": IMAGE_DIGEST,
        "com.archonmegalon.ea.audiobook-runtime.deployment-authority": "denied",
    }
    sources = {
        "/config": config,
        "/app/config": config,
        "/run/secrets/whatsapp_audiobook_callback_secret": secret,
        "/run/ea-gemini-cli-config": gemini_config,
        "/data/onedrive_attachments": onedrive,
        "/data/pocket-ai-audio": pocket_audio,
        "/data/audiobooks": durable,
        "/data/audiobooks/jobs": jobs,
        "/data/audiobooks/audiobookshelf": shelf,
    }
    services: dict[str, object] = {}
    for service in MODULE.ALL_SERVICES:
        services[service] = {
            "profiles": [MODULE.CANDIDATE_PROFILE],
            "deploy": {"replicas": 0},
            "restart": "no",
            "container_name": MODULE.CONTAINER_NAMES[service],
        }
    for service in MODULE.TARGET_SERVICES:
        volumes = [
            _bind(
                sources[target],
                target,
                read_only=bool(requirement["read_only"]),
            )
            for target, requirement in MODULE.SERVICE_REQUIRED_BIND_MOUNTS[service].items()
        ]
        volumes.extend(
            {
                "type": "volume",
                "source": source,
                "target": target,
                "volume": {},
            }
            for target, source in MODULE.SERVICE_REQUIRED_NAMED_VOLUMES[service].items()
        )
        service_labels = copy.deepcopy(labels)
        if service == "ea-api":
            service_labels[
                "com.archonmegalon.ea.audiobook-runtime.live-owner-handoff"
            ] = "required"
        payload = services[service]
        assert isinstance(payload, dict)
        service_environment = {
            **copy.deepcopy(environment),
            **MODULE.PRESERVED_SERVICE_ENVIRONMENT[service],
        }
        for key in MODULE.EXPECTED_ENVIRONMENT_KEYS[service]:
            service_environment.setdefault(key, f"fixture-value-{key.lower()}")
        payload.update(
            {
                "image": IMAGE,
                "pull_policy": "never",
                "environment": service_environment,
                "labels": service_labels,
                "volumes": volumes,
                "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
                "command": copy.deepcopy(MODULE.EXPECTED_COMMANDS[service]),
                "working_dir": "/app",
                "user": "10001:10001",
                "cap_drop": ["ALL"],
                "read_only": True,
                "security_opt": ["no-new-privileges:true"],
                "tmpfs": ["/tmp", "/run"],
                "networks": {name: None for name in MODULE.EXPECTED_NETWORKS[service]},
                "extra_hosts": copy.deepcopy(MODULE.EXPECTED_EXTRA_HOSTS),
                "depends_on": copy.deepcopy(MODULE.EXPECTED_DEPENDS_ON[service]),
                **copy.deepcopy(MODULE.EXPECTED_RESOURCE_LIMITS[service]),
            }
        )
        if service == "ea-whatsapp-web-action-processor":
            payload["healthcheck"] = copy.deepcopy(MODULE.EXPECTED_HEALTHCHECK)
    compose_payload = {
        "name": MODULE.CANDIDATE_PROJECT,
        "services": services,
        "volumes": copy.deepcopy(MODULE.EXPECTED_TOP_VOLUMES),
        "networks": copy.deepcopy(MODULE.EXPECTED_TOP_NETWORKS),
        "x-audiobook-inert-service": copy.deepcopy(MODULE.EXPECTED_INERT_EXTENSION),
        "x-audiobook-candidate-service": copy.deepcopy(
            MODULE.EXPECTED_CANDIDATE_EXTENSION
        ),
        "x-audiobook-runtime-environment": {
            key: environment[key]
            for key in MODULE.EXPECTED_SHARED_ENVIRONMENT_KEYS
        },
        "x-audiobook-runtime-labels": copy.deepcopy(labels),
    }
    return compose_payload, sensitive_values


def _image_inspection() -> dict[str, object]:
    return {
        "Id": IMAGE_ID,
        "RepoDigests": [IMAGE],
        "Config": {
            "Labels": {"org.opencontainers.image.revision": REVISION},
            "Env": [f"EA_SOURCE_REVISION={REVISION}", "PYTHONPATH=/app"],
        },
    }


def _supporting_provenance() -> dict[str, object]:
    return {
        "schema": MODULE.IMAGE_BUILD_RECEIPT_SCHEMA,
        "status": "pass",
        "commit": REVISION,
        "revision_label": REVISION,
        "runtime_source_revision": REVISION,
        "image_id": IMAGE_ID,
        "dirty_worktree_context_used": False,
        "runtime_secrets_baked_in": False,
        "customer_data_baked_in": False,
        "private_archive_baked_in": False,
        "global_build_cache_pruned": False,
        "live_or_rollback_images_pruned": False,
    }


def _verify(
    payload: dict[str, object],
    *,
    mode: str = "configuration",
    image_inspection: dict[str, object] | None = None,
    supporting_provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    return MODULE.verify_audiobook_runtime_candidate(
        payload,
        expected_revision=REVISION,
        expected_image=IMAGE,
        source_overlay_commit=REVISION,
        overlay_sha256=OVERLAY_SHA256,
        compose_version=COMPOSE_VERSION,
        mode=mode,
        image_inspection=image_inspection,
        supporting_provenance=supporting_provenance,
        supporting_provenance_sha256=(
            "sha256:" + ("d" * 64) if supporting_provenance is not None else ""
        ),
    )


def _require_docker_compose() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is unavailable")
    probe = subprocess.run(
        ["docker", "compose", "version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if probe.returncode != 0:
        pytest.skip("docker compose is unavailable")


def _prepare_real_compose(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    compose_root = tmp_path / "real-compose"
    compose_root.mkdir()
    shutil.copy2(ROOT / "docker-compose.yml", compose_root / "docker-compose.yml")
    shutil.copy2(
        ROOT / "docker-compose.whatsapp-web-session.yml",
        compose_root / "docker-compose.whatsapp-web-session.yml",
    )
    candidate_dir = compose_root / "deploy" / "audiobook-runtime-candidate"
    candidate_dir.mkdir(parents=True)
    shutil.copy2(
        ROOT / "deploy" / "audiobook-runtime-candidate" / "docker-compose.candidate.yml",
        candidate_dir / "docker-compose.candidate.yml",
    )
    source_env = compose_root / ".env"
    source_env.write_text(
        "# Empty environment file for static Compose rendering.\n", encoding="utf-8"
    )
    source_env.chmod(0o600)

    config = compose_root / "config"
    gemini = compose_root / "gemini"
    onedrive = compose_root / "onedrive"
    pocket_audio = compose_root / "pocket-audio"
    durable = compose_root / "audiobooks"
    jobs = durable / "jobs"
    shelf = durable / "audiobookshelf"
    for directory in (
        config,
        gemini,
        onedrive,
        pocket_audio,
        jobs,
        shelf,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    callback_secret = compose_root / "callback.secret"
    callback_secret.write_text("static-render-callback-secret\n", encoding="utf-8")
    callback_secret.chmod(0o600)
    environment = dict(os.environ)
    environment.update(
        {
            "POSTGRES_PASSWORD": "static-render-postgres-password",
            "EA_AUDIOBOOK_CANDIDATE_REVISION": REVISION,
            "EA_AUDIOBOOK_CANDIDATE_IMAGE_DIGEST": IMAGE_DIGEST,
            "EA_AUDIOBOOK_CANDIDATE_IMAGE": IMAGE,
            "EA_AUDIOBOOK_CONFIG_HOST_DIR": str(config),
            "EA_GEMINI_VORTEX_CONFIG_HOST_DIR": str(gemini),
            "EA_ONEDRIVE_ATTACHMENTS_HOST_PATH": str(onedrive),
            "EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT": str(pocket_audio),
            "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_RUNTIME_FILE": str(callback_secret),
            "EA_DURABLE_AUDIOBOOK_HOST_ROOT": str(durable),
            "EA_AUDIOBOOK_JOBS_HOST_ROOT": str(jobs),
            "EA_AUDIOBOOKSHELF_IMPORT_HOST_ROOT": str(shelf),
            "EA_AUDIOBOOKSHELF_API_BASE_URL": "https://abs.internal.invalid",
            "EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL": "https://listen.example.invalid",
            "EA_AUDIOBOOKSHELF_API_TOKEN": "static-render-abs-api-token",
            "EA_AUDIOBOOKSHELF_LIBRARY_ID": "static-render-library",
            "EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL": "https://player.example.invalid",
            "EA_AUDIOBOOK_ACCESS_SIGNING_SECRET": "static-render-access-signing-secret",
            "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY": "static-render-canary-hmac-secret",
            "EA_UNMIXR_PREFERRED_SLOTS": "UNMIXR_API_KEY_FALLBACK_1",
            "EA_UNMIXR_RESERVE_SLOTS": "UNMIXR_API_KEY",
            "EA_SOURCE_REVISION": REVISION,
        }
    )
    return compose_root, environment


def _render_real_compose(
    compose_root: Path,
    environment: dict[str, str],
    *compose_names: str,
) -> dict[str, object]:
    runtime_projection = prepare_runtime_env(compose_root)
    assert runtime_projection["status"] == "prepared"
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(compose_root),
        "--profile",
        MODULE.CANDIDATE_PROFILE,
    ]
    for name in compose_names:
        command.extend(("-f", str(compose_root / name)))
    command.extend(("config", "--format", "json"))
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _mounts_by_target(service: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(mount["target"]): mount
        for mount in service.get("volumes", [])
        if isinstance(mount, dict) and mount.get("target")
    }


def test_valid_candidate_is_configuration_only_and_receipt_is_sanitized(tmp_path: Path) -> None:
    payload, sensitive_values = _fixture(tmp_path)

    result = _verify(payload)

    assert result["status"] == "configuration_only"
    assert result["issues"] == []
    assert result["deploy_ready"] is False
    assert result["deployment_authority"] is False
    assert result["promotion_authority"] is False
    assert result["mutations_performed"] == 0
    assert result["live_owner"]["ea-api"] == "ea_core"
    assert result["services"]["ea-api"]["live_owner_handoff"] == "required"
    serialized = json.dumps(result, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "callback-secret-one" not in serialized
    for sensitive in sensitive_values.values():
        assert sensitive not in serialized


def test_rendered_contract_digest_binds_validated_host_bind_sources(tmp_path: Path) -> None:
    first, first_sensitive = _fixture(tmp_path, suffix="first")
    second, _ = _fixture(tmp_path, suffix="second")
    for key, value in first_sensitive.items():
        second["x-audiobook-runtime-environment"][key] = value
        for service in MODULE.TARGET_SERVICES:
            second["services"][service]["environment"][key] = value

    first_result = _verify(first)
    second_result = _verify(second)

    assert first_result["status"] == second_result["status"] == "configuration_only"
    assert first_result["rendered_contract_sha256"] != second_result["rendered_contract_sha256"]


def test_rendered_contract_digest_binds_secret_and_environment_values(tmp_path: Path) -> None:
    first, _ = _fixture(tmp_path, suffix="first")
    second, _ = _fixture(tmp_path, suffix="second")

    first_result = _verify(first)
    second_result = _verify(second)

    assert first_result["status"] == second_result["status"] == "configuration_only"
    assert first_result["rendered_contract_sha256"] != second_result["rendered_contract_sha256"]


def test_rendered_contract_digest_binds_allowed_noncritical_value_drift(tmp_path: Path) -> None:
    first, _ = _fixture(tmp_path)
    second = copy.deepcopy(first)
    second["services"]["ea-worker"]["environment"]["TZ"] = "UTC"

    first_result = _verify(first)
    second_result = _verify(second)

    assert first_result["status"] == second_result["status"] == "configuration_only"
    assert first_result["rendered_contract_sha256"] != second_result["rendered_contract_sha256"]


def test_rendered_contract_digest_binds_inert_inherited_service_drift(tmp_path: Path) -> None:
    first, _ = _fixture(tmp_path)
    second = copy.deepcopy(first)
    second["services"]["ea-db"]["command"] = ["inert-but-materially-different"]

    first_result = _verify(first)
    second_result = _verify(second)

    assert first_result["status"] == second_result["status"] == "configuration_only"
    assert first_result["rendered_contract_sha256"] != second_result["rendered_contract_sha256"]


def test_blocked_receipt_never_echoes_hostile_untrusted_values(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    hostile = str(tmp_path / "host-path-and-secret-token")
    worker = payload["services"]["ea-worker"]
    worker["command"] = [hostile]
    worker["entrypoint"] = [hostile]
    worker["extra_hosts"] = [hostile]
    worker["environment"]["PYTHONPATH"] = hostile
    worker["labels"]["org.opencontainers.image.revision"] = hostile
    worker["volumes"].append(
        {
            "type": "bind",
            "source": hostile,
            "target": hostile,
            "bind": {"create_host_path": False},
        }
    )
    payload["services"]["ea-db"]["restart"] = hostile
    payload["services"]["ea-db"]["deploy"][hostile] = hostile

    result = MODULE.verify_audiobook_runtime_candidate(
        payload,
        expected_revision=REVISION,
        expected_image=IMAGE,
        source_overlay_commit=REVISION,
        overlay_sha256=OVERLAY_SHA256,
        compose_version=hostile,
        mode=hostile,
    )

    assert result["status"] == "blocked"
    assert result["verification_mode"] == "invalid"
    assert result["compose_version"] == ""
    assert hostile not in json.dumps(result, sort_keys=True)


def test_extra_environment_or_label_key_blocks_exact_contract(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-worker"]["environment"]["ATTACKER_ENV"] = "hidden"
    payload["services"]["ea-worker"]["labels"]["attacker.label"] = "hidden"
    payload["x-audiobook-runtime-environment"]["ATTACKER_ENV"] = "hidden"
    payload["x-audiobook-runtime-labels"]["attacker.label"] = "hidden"

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-worker:environment:exact_keyset_mismatch" in result["issues"]
    assert "ea-worker:labels:exact_keyset_mismatch" in result["issues"]
    assert "compose:x_runtime_environment:exact_keyset_mismatch" in result["issues"]
    assert "compose:x_runtime_labels:exact_definition_mismatch" in result["issues"]
    assert result["rendered_contract_sha256"] == ""
    assert result["rendered_contract_digest_valid"] is False
    assert result["configuration_projection"]["status"] == "blocked"
    assert "hidden" not in json.dumps(result, sort_keys=True)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("env_file", ["/private/attacker.env"]),
        ("runtime", "attacker-runtime"),
        ("provider", {"type": "attacker"}),
        ("dns", ["203.0.113.53"]),
        ("logging", {"driver": "syslog", "options": {"address": "hidden"}}),
        ("hooks", [{"command": "hidden"}]),
        ("post_start", [{"command": "hidden"}]),
        ("pre_stop", [{"command": "hidden"}]),
    ),
)
def test_unallowlisted_execution_affecting_service_field_blocks(
    tmp_path: Path, field: str, value: object
) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-api"][field] = value

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-api:fields:exact_allowlist_mismatch" in result["issues"]
    assert result["rendered_contract_sha256"] == ""
    assert "hidden" not in json.dumps(result, sort_keys=True)


def test_resource_limit_drift_blocks_exact_contract(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-api"]["pids_limit"] = 0

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-api:resource_limits:exact_value_mismatch" in result["issues"]
    assert result["rendered_contract_sha256"] == ""


def test_top_level_volume_driver_options_and_network_drift_block(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["volumes"]["ea_artifacts"]["driver_opts"] = {
        "device": "/private/host-secret",
        "o": "bind",
        "type": "none",
    }
    payload["networks"]["default"]["driver_opts"] = {
        "com.example.hidden": "host-secret"
    }

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "compose:volumes:exact_definition_mismatch" in result["issues"]
    assert "compose:networks:exact_definition_mismatch" in result["issues"]
    assert result["rendered_contract_sha256"] == ""
    serialized = json.dumps(result, sort_keys=True)
    assert "/private/host-secret" not in serialized
    assert "com.example.hidden" not in serialized


def test_configuration_projection_is_explicitly_non_deployable(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)

    result = _verify(payload)
    projection = result["configuration_projection"]

    assert projection == {
        "contract_name": MODULE.OVERLAY_CONTRACT,
        "status": "pass",
        "configuration_only": True,
        "configuration_valid": True,
        "configuration_authority": False,
        "deploy_ready": False,
        "deployment_authority": False,
        "promotion_authority": False,
        "live_mutation_authority": False,
        "runtime_execution_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
        "target_services": list(MODULE.TARGET_SERVICES),
        "source_revision": REVISION,
        "candidate_image_reference": IMAGE,
        "overlay_sha256": OVERLAY_SHA256,
        "rendered_contract_sha256": result["rendered_contract_sha256"].removeprefix(
            "sha256:"
        ),
        "execution_scope": "isolated_candidate_configuration",
        "live_api_owner": "ea_core",
        "owner_handoff_required": True,
        "cross_product_runtime_compatible": False,
        "group_deploy_eligible": False,
        "silent_takeover_allowed": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    (
        ("entrypoint", ["/bin/sh"], "entrypoint:exact_value_mismatch"),
        ("command", ["python", "-c", "pass"], "command:exact_value_mismatch"),
        ("working_dir", "/tmp", "working_dir:exact_value_mismatch"),
        ("user", "0:0", "user:exact_value_mismatch"),
    ),
)
def test_execution_bypass_fails(
    tmp_path: Path, field: str, value: object, issue: str
) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-worker"][field] = value

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert f"ea-worker:{issue}" in result["issues"]


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    (
        ("privileged", True, "privileged:must_be_false"),
        ("cap_add", ["SYS_ADMIN"], "cap_add:must_be_empty"),
        ("cap_drop", [], "cap_drop:must_drop_all"),
        ("read_only", False, "read_only:must_be_true"),
        ("security_opt", [], "security_opt:exact_value_mismatch"),
        ("tmpfs", ["/tmp", "/run", "/app"], "tmpfs:exact_value_mismatch"),
    ),
)
def test_security_bypass_fails(
    tmp_path: Path, field: str, value: object, issue: str
) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-scheduler"][field] = value

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert f"ea-scheduler:{issue}" in result["issues"]


@pytest.mark.parametrize("field", ("pid", "ipc", "network_mode", "uts", "userns_mode"))
def test_host_isolation_namespace_bypass_fails(tmp_path: Path, field: str) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-api"][field] = "host"

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert f"ea-api:{field}:forbidden_isolation_override" in result["issues"]


@pytest.mark.parametrize("field", ("configs", "secrets", "devices", "volumes_from", "group_add"))
def test_unallowlisted_runtime_attachment_fails(tmp_path: Path, field: str) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-worker"][field] = ["unexpected"]

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert f"ea-worker:{field}:must_be_empty" in result["issues"]


@pytest.mark.parametrize("target", ("/app", "/"))
def test_unexpected_named_volume_and_executable_mount_fail(
    tmp_path: Path, target: str
) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-api"]["volumes"].append(
        {
            "type": "volume",
            "source": "attacker",
            "target": target,
            "volume": {},
        }
    )

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-api:volumes:mount_target_not_allowlisted" in result["issues"]
    assert "ea-api:volumes:mount_covers_executable_path" in result["issues"]


def test_required_mount_type_and_named_source_are_exact(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    volumes = payload["services"]["ea-scheduler"]["volumes"]
    config = next(mount for mount in volumes if mount["target"] == "/config")
    config["type"] = "volume"
    artifact = next(mount for mount in volumes if mount["target"] == "/data/artifacts")
    artifact["source"] = "other_volume"

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-scheduler:/config:mount_type_mismatch" in result["issues"]
    assert "ea-scheduler:/data/artifacts:named_volume_source_mismatch" in result["issues"]


def test_inert_profile_replica_and_candidate_name_are_mandatory(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-worker"]["profiles"] = ["default"]
    payload["services"]["ea-worker"]["deploy"]["replicas"] = 1
    payload["services"]["ea-worker"]["container_name"] = "ea-worker"

    result = _verify(payload)

    assert result["status"] == "blocked"
    issues = result["issues"]
    assert "ea-worker:profiles:candidate_profile_mismatch" in issues
    assert "ea-worker:deploy.replicas:must_be_zero" in issues
    assert "ea-worker:container_name:candidate_name_mismatch" in issues


def test_non_target_service_cannot_escape_inert_contract(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-db"]["restart"] = "always"
    payload["services"]["ea-db"]["deploy"]["mode"] = "global"

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-db:restart:must_be_no" in result["issues"]
    assert "ea-db:deploy:nonempty_option_forbidden" in result["issues"]


def test_new_or_missing_service_fails_exact_service_set(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["attacker"] = {}

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "compose:services:exact_set_mismatch" in result["issues"]


def _retired_memorial_owner_combination_is_explicitly_incompatible(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-api"]["environment"].update(
        {
            "EA_DEPLOY_PRIMARY_MODE": "MEMORIAL",
            "EA_MEMORIAL_DATA_ROOT": "/data/manfred",
        }
    )

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert "ea-api:memorial_lane:incompatible_owner_combination" in result["issues"]
    assert result["live_owner"]["candidate_posture"] == "owner_handoff_required"


def test_mutable_or_mismatched_image_build_and_pull_policy_fail(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    payload["services"]["ea-worker"]["image"] = "registry.example.invalid/ea/runtime:latest"
    payload["services"]["ea-worker"]["build"] = {"context": "."}
    payload["services"]["ea-worker"]["pull_policy"] = "always"

    result = _verify(payload)

    assert result["status"] == "blocked"
    issues = result["issues"]
    assert "ea-worker:image:does_not_match_candidate_image" in issues
    assert "ea-worker:build:must_be_absent" in issues
    assert "ea-worker:pull_policy:must_be_never" in issues


def test_insecure_secret_file_fails_without_disclosing_path(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    secret_mount = next(
        mount
        for mount in payload["services"]["ea-api"]["volumes"]
        if mount["target"] == "/run/secrets/whatsapp_audiobook_callback_secret"
    )
    Path(secret_mount["source"]).chmod(0o644)

    result = _verify(payload)

    assert result["status"] == "blocked"
    assert (
        "ea-api:/run/secrets/whatsapp_audiobook_callback_secret:source_permissions_not_private"
        in result["issues"]
    )
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)


def test_source_overlay_commit_and_compose_version_are_bound(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)

    old_compose = MODULE.verify_audiobook_runtime_candidate(
        payload,
        expected_revision=REVISION,
        expected_image=IMAGE,
        source_overlay_commit="e" * 40,
        overlay_sha256=OVERLAY_SHA256,
        compose_version="2.20.0",
    )

    assert old_compose["status"] == "blocked"
    assert "candidate:source_overlay_commit:revision_mismatch" in old_compose["issues"]
    assert "candidate:compose_version:too_old_for_override_contract" in old_compose["issues"]


def test_release_mode_validates_local_image_and_supporting_provenance_but_stays_blocked(
    tmp_path: Path,
) -> None:
    payload, _ = _fixture(tmp_path)

    result = _verify(
        payload,
        mode="release",
        image_inspection=_image_inspection(),
        supporting_provenance=_supporting_provenance(),
    )

    assert result["status"] == "blocked"
    assert result["evidence"]["local_image_inspection"]["validated"] is True
    assert result["evidence"]["supporting_build_provenance"]["validated"] is True
    assert (
        result["evidence"]["supporting_build_provenance"]["authority_eligible"]
        is False
    )
    assert "evidence:signed_immutable_candidate_authority:unavailable" in result["issues"]
    assert result["deploy_ready"] is False


def test_release_mode_fails_when_local_image_or_provenance_is_missing(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)

    result = _verify(payload, mode="release")

    assert result["status"] == "blocked"
    assert "evidence:local_image_inspection:missing" in result["issues"]
    assert "evidence:supporting_build_provenance:missing" in result["issues"]


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    (
        (
            lambda payload: payload.update({"RepoDigests": ["registry.invalid/x@sha256:" + "f" * 64]}),
            "evidence:local_image_inspection:repo_digest_mismatch",
        ),
        (
            lambda payload: payload["Config"]["Labels"].update(
                {"org.opencontainers.image.revision": "f" * 40}
            ),
            "evidence:local_image_inspection:oci_revision_mismatch",
        ),
        (
            lambda payload: payload["Config"].update(
                {"Env": ["EA_SOURCE_REVISION=" + "f" * 40]}
            ),
            "evidence:local_image_inspection:source_revision_mismatch",
        ),
    ),
)
def test_release_image_inspection_mismatch_fails(
    tmp_path: Path, mutator: object, expected_issue: str
) -> None:
    payload, _ = _fixture(tmp_path)
    inspection = _image_inspection()
    mutator(inspection)

    result = _verify(
        payload,
        mode="release",
        image_inspection=inspection,
        supporting_provenance=_supporting_provenance(),
    )

    assert result["status"] == "blocked"
    assert expected_issue in result["issues"]


def test_invalid_supporting_provenance_never_becomes_authority(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    provenance = _supporting_provenance()
    provenance["runtime_secrets_baked_in"] = True

    result = _verify(
        payload,
        mode="release",
        image_inspection=_image_inspection(),
        supporting_provenance=provenance,
    )

    assert (
        "evidence:supporting_build_provenance:runtime_secrets_baked_in_not_false"
        in result["issues"]
    )
    assert result["evidence"]["supporting_build_provenance"]["authority_eligible"] is False


def test_legacy_v2_supporting_provenance_is_rejected(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    provenance = _supporting_provenance()
    provenance["schema"] = "ea.audiobook_runtime_image_build.v0"

    result = _verify(
        payload,
        mode="release",
        image_inspection=_image_inspection(),
        supporting_provenance=provenance,
    )

    assert "evidence:supporting_build_provenance:schema_mismatch" in result["issues"]
    assert result["evidence"]["supporting_build_provenance"]["validated"] is False
    assert (
        result["evidence"]["supporting_build_provenance"]["schema"]
        == "unrecognized"
    )


def test_configuration_mode_does_not_ignore_supplied_bad_provenance(tmp_path: Path) -> None:
    payload, _ = _fixture(tmp_path)
    provenance = _supporting_provenance()
    provenance["commit"] = "f" * 40

    result = _verify(
        payload,
        image_inspection=_image_inspection(),
        supporting_provenance=provenance,
    )

    assert result["status"] == "blocked"
    assert "evidence:supporting_build_provenance:commit_mismatch" in result["issues"]


def test_read_only_evidence_helpers_never_issue_runtime_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["docker", "compose", "version"]:
            return subprocess.CompletedProcess(command, 0, stdout="2.38.2\n", stderr="")
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps([_image_inspection()]), stderr=""
            )
        if "diff" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout=REVISION + "\n", stderr="")

    monkeypatch.setattr(MODULE, "_run_read_only", fake_run)

    assert MODULE._read_compose_version() == "2.38.2"
    assert MODULE._inspect_local_image(IMAGE) == _image_inspection()
    assert MODULE._discover_overlay_commit() == REVISION
    assert calls == [
        ["docker", "compose", "version", "--short"],
        ["docker", "image", "inspect", "--", IMAGE],
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--quiet",
            "HEAD",
            "--",
            str(MODULE.OVERLAY_RELATIVE_PATH),
        ],
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    ]
    assert all("up" not in command and "run" not in command for command in calls)


def test_private_provenance_loader_rejects_open_permissions(tmp_path: Path) -> None:
    path = tmp_path / "provenance.json"
    path.write_text(json.dumps(_supporting_provenance()), encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(ValueError, match="permissions"):
        MODULE._load_private_json(path)


def test_private_provenance_loader_binds_exact_private_bytes(tmp_path: Path) -> None:
    path = tmp_path / "provenance.json"
    encoded = (json.dumps(_supporting_provenance(), sort_keys=True) + "\n").encode()
    path.write_bytes(encoded)
    path.chmod(0o600)

    payload, digest = MODULE._load_private_json(path)

    assert payload == _supporting_provenance()
    assert digest.startswith("sha256:") and len(digest) == 71


def test_real_compose_overlay_removes_source_mounts_and_is_inert(tmp_path: Path) -> None:
    _require_docker_compose()
    compose_root, environment = _prepare_real_compose(tmp_path)
    before = _render_real_compose(
        compose_root,
        environment,
        "docker-compose.yml",
        "docker-compose.whatsapp-web-session.yml",
    )
    after = _render_real_compose(
        compose_root,
        environment,
        "docker-compose.yml",
        "docker-compose.whatsapp-web-session.yml",
        "deploy/audiobook-runtime-candidate/docker-compose.candidate.yml",
    )

    assert any(
        target == "/app" or target.startswith("/app/")
        for service in MODULE.TARGET_SERVICES
        for target in _mounts_by_target(before["services"][service])
        if target != "/app/config"
    )
    for service in MODULE.TARGET_SERVICES:
        mounts = _mounts_by_target(after["services"][service])
        assert set(mounts) == (
            set(MODULE.SERVICE_REQUIRED_BIND_MOUNTS[service])
            | set(MODULE.SERVICE_REQUIRED_NAMED_VOLUMES[service])
        )
        assert not any(
            MODULE._mount_covers_path(target, executable)
            for target in mounts
            for executable in MODULE.EXECUTABLE_PATHS[service]
        )
    for service in MODULE.ALL_SERVICES:
        rendered = after["services"][service]
        assert rendered["profiles"] == [MODULE.CANDIDATE_PROFILE]
        assert rendered["deploy"]["replicas"] == 0
        assert rendered["container_name"] == MODULE.CONTAINER_NAMES[service]

    result = _verify(after)
    assert result["status"] == "configuration_only", result["issues"]
    assert result["issues"] == []


def _retired_real_memorial_overlay_cannot_be_combined_with_candidate(tmp_path: Path) -> None:
    _require_docker_compose()
    compose_root, environment = _prepare_real_compose(tmp_path)
    combined = _render_real_compose(
        compose_root,
        environment,
        "docker-compose.yml",
        "docker-compose.whatsapp-web-session.yml",
        "docker-compose.memorial.yml",
        "deploy/audiobook-runtime-candidate/docker-compose.candidate.yml",
    )

    result = _verify(combined)

    assert result["status"] == "blocked"
    assert any(
        issue.endswith("memorial_lane:incompatible_owner_combination")
        for issue in result["issues"]
    )
    assert result["deploy_ready"] is False


def test_cli_input_failure_emits_only_fail_closed_authority(tmp_path: Path) -> None:
    missing_compose = tmp_path / "missing-compose.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--compose-json",
            str(missing_compose),
            "--expected-revision",
            REVISION,
            "--expected-image",
            IMAGE,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["status"] == "blocked"
    assert result["issues"] == ["preflight_input:FileNotFoundError"]
    assert result["rendered_contract_sha256"] == ""
    assert result["rendered_contract_digest_valid"] is False
    for key in (
        "configuration_authority",
        "deploy_ready",
        "deployment_authority",
        "promotion_authority",
        "live_mutation_authority",
        "runtime_execution_authority",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "build_authority",
        "pull_authority",
    ):
        assert result[key] is False
