from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_CINEMATIC_DEFAULTS = {
    "EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS": "0",
    "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST": "1800",
}
CANARY_HMAC_KEY = "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY"
VOCALLAB_SAFE_DEFAULTS = {
    "VOCALLAB_API_KEY": "",
    "VOCALLAB_API_KEY_FILE": "config/vocallab_api_key",
    "EA_AUDIOBOOK_VOCALLAB_ENABLED": "0",
    "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER": "0",
    "EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_ROTATION_REQUIRED": "1",
    "EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_PRODUCTION_ELIGIBLE": "0",
    "EA_AUDIOBOOK_VOCALLAB_BASE_URL": "https://api.vocallab.ai",
    "EA_AUDIOBOOK_VOCALLAB_MODEL": "v-pro",
    "EA_AUDIOBOOK_VOCALLAB_EXPRESSIVE_MODEL": "v-studio",
    "EA_AUDIOBOOK_VOCALLAB_DRAFT_MODEL": "v-lite",
    "EA_AUDIOBOOK_VOCALLAB_MAX_CHARS_PER_REQUEST": "1800",
    "EA_AUDIOBOOK_VOCALLAB_REQUESTS_PER_MINUTE": "30",
    "EA_AUDIOBOOK_VOCALLAB_MAX_IN_FLIGHT": "1",
    "EA_AUDIOBOOK_VOCALLAB_MAX_SEGMENTS_PER_RUN": "10",
    "EA_AUDIOBOOK_VOCALLAB_TIMEOUT_SECONDS": "120",
    "EA_AUDIOBOOK_VOCALLAB_POLL_INTERVAL_SECONDS": "2",
    "EA_AUDIOBOOK_VOCALLAB_POLL_TIMEOUT_SECONDS": "180",
    "EA_AUDIOBOOK_VOCALLAB_OUTPUT_FORMAT": "WAV",
    "EA_AUDIOBOOK_VOCALLAB_SAMPLE_RATE": "44100",
    "EA_AUDIOBOOK_VOCALLAB_MAX_AUDIO_BYTES": "33554432",
    "EA_AUDIOBOOK_VOCALLAB_MIN_REMAINING_POINTS": "3000",
    "EA_AUDIOBOOK_VOCALLAB_MAX_POINTS_PER_JOB": "6000",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS": "0",
    "EA_AUDIOBOOK_VOCALLAB_ALLOWED_VOICE_CLASSES": "professional,consented_clone",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_COMMUNITY_VOICES": "0",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES": "0",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_PERSONA": "0",
    "EA_AUDIOBOOK_VOCALLAB_VOICE_CATALOG_FILE": (
        "config/vocallab_voice_catalog.local.json"
    ),
    "EA_AUDIOBOOK_TTS_PROVIDER_ORDER": "unmixr,vocallab,piper_local",
    "EA_AUDIOBOOK_TTS_ALLOW_CROSS_PROVIDER_FALLBACK": "0",
}
AUTHORIZED_VOCALLAB_SERVICES = frozenset(
    {"ea-api", "ea-worker", "ea-scheduler", "ea-whatsapp-web-action-processor"}
)
VOCALLAB_ENV_FILE_CONSUMERS = (
    "ea-teable-relay",
    "ea-api",
    "ea-responses-proxy",
    "ea-worker",
    "ea-scheduler",
    "ea-proactive-ooda",
    "ea-telegram-teable-sync",
    "ea-whatsapp-web-activator",
    "ea-whatsapp-web-action-processor",
    "ea-whatsapp-web-teable-sync",
)
SYNTHETIC_VOCALLAB_KEY = "synthetic-vocallab-compose-secret"
SYNTHETIC_VOCALLAB_KEY_FILE = "/private/synthetic-vocallab-key"
PRIVATE_VOCALLAB_CONFIG_FILENAMES = (
    "vocallab_api_key",
    "vocallab_api_key.bak",
    "vocallab_api_key~",
    "vocallab_credential_rotation_authority.local.json",
    "vocallab_credential_rotation_authority.local.json.tmp",
    "vocallab_verification_hmac_key",
    "vocallab_verification_hmac_key.swp",
    "vocallab_voice_catalog.local.json",
    "vocallab_voice_catalog.local.json.bak",
)
NON_VOCALLAB_CONFIG_ALLOWLIST = (
    "onemin_api_keys.example.json",
    "onemin_slot_owners.json",
    "places.yml",
    "tenants.yml",
)
UNAUTHORIZED_VOCALLAB_CONFIG_ROOTS = {
    "ea-proactive-ooda": ("/app/config",),
    "ea-telegram-teable-sync": ("/app/config",),
    "ea-responses-proxy": ("/config", "/app/config"),
    "ea-whatsapp-web-activator": ("/app/config",),
    "ea-whatsapp-web-teable-sync": ("/app/config",),
}
BROAD_REPO_UNAUTHORIZED_VOCALLAB_SERVICES = (
    "ea-proactive-ooda",
    "ea-telegram-teable-sync",
    "ea-whatsapp-web-activator",
    "ea-whatsapp-web-teable-sync",
)
SHARED_LEDGER_UNAUTHORIZED_VOCALLAB_SERVICES = (
    "ea-proactive-ooda",
    "ea-responses-proxy",
)
SHARED_LEDGER_AUTHORIZED_VOCALLAB_SERVICES = (
    "ea-api",
    "ea-worker",
    "ea-scheduler",
)
VOCALLAB_PRIVATE_LEDGER_ROOT = "/data/provider-ledger/vocallab"


def _env_example() -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        entries[key] = value
    return entries


def _compose_environment(path: Path, service_name: str) -> dict[str, str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    services = payload.get("services")
    assert isinstance(services, dict)
    service = services.get(service_name)
    assert isinstance(service, dict)
    raw_environment = service.get("environment")
    assert isinstance(raw_environment, list)

    entries: dict[str, str] = {}
    for raw_entry in raw_environment:
        assert isinstance(raw_entry, str)
        key, separator, value = raw_entry.partition("=")
        assert separator == "="
        entries[key] = value
    return entries


def _render_effective_compose(
    tmp_path: Path,
    *,
    compose_paths_before_injection: tuple[Path, ...],
    compose_paths_after_injection: tuple[Path, ...] = (),
) -> dict[str, object]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose is unavailable")
    tmp_path.mkdir(parents=True, exist_ok=True)
    cartesia_credential = tmp_path.parent / "cartesia-credential.json"
    cartesia_credential.write_text("{}\n", encoding="utf-8")
    cartesia_credential.chmod(0o600)
    synthetic_env = tmp_path / "vocallab-synthetic.env"
    synthetic_env.write_text(
        "\n".join(
            (
                f"VOCALLAB_API_KEY={SYNTHETIC_VOCALLAB_KEY}",
                f"VOCALLAB_API_KEY_FILE={SYNTHETIC_VOCALLAB_KEY_FILE}",
                "POSTGRES_PASSWORD=synthetic-postgres-password",
                "EA_AUDIOBOOK_PRODUCTION_IMAGE=registry.example/ea/runtime@sha256:"
                + "1" * 64,
                "EA_AUDIOBOOK_PRODUCTION_REVISION=" + "2" * 40,
                "EA_MEMORIAL_IMAGE=registry.example/ea/memorial@sha256:" + "3" * 64,
                "EA_SOURCE_REVISION=" + "4" * 40,
                "EA_MEMORIAL_TRUSTED_PROXY_CIDRS=172.31.254.2/32",
                "EA_MEMORIAL_DATA_HOST_PATH=/tmp/ea-memorial-data",
                "EA_MEMORIAL_RUNTIME_HOST_PATH=/tmp/ea-memorial-runtime",
                "EA_MEMORIAL_CARTESIA_CREDENTIAL_HOST_FILE="
                + str(cartesia_credential),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    synthetic_env.chmod(0o600)
    env_override = tmp_path / "vocallab-env-file-override.yml"
    override_lines = ["services:"]
    for service in VOCALLAB_ENV_FILE_CONSUMERS:
        override_lines.extend(
            (
                f"  {service}:",
                "    env_file: !override",
                f"      - {synthetic_env}",
            )
        )
    env_override.write_text("\n".join(override_lines) + "\n", encoding="utf-8")

    command = [docker, "compose", "--env-file", str(synthetic_env)]
    for path in compose_paths_before_injection:
        command.extend(("-f", str(path)))
    command.extend(("-f", str(env_override)))
    for path in compose_paths_after_injection:
        command.extend(("-f", str(path)))
    command.extend(("config", "--format", "json"))
    process_environment = dict(os.environ)
    process_environment.pop("VOCALLAB_API_KEY", None)
    process_environment.pop("VOCALLAB_API_KEY_FILE", None)
    rendered = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=process_environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if rendered.returncode != 0:
        pytest.fail("effective Compose render failed")
    try:
        payload = json.loads(rendered.stdout)
    except json.JSONDecodeError:
        pytest.fail("effective Compose render returned invalid JSON")
    assert isinstance(payload, dict)
    return payload


def _effective_service_environment(
    payload: dict[str, object],
    service_name: str,
) -> dict[str, str]:
    services = payload.get("services")
    if not isinstance(services, dict):
        pytest.fail("effective Compose services are invalid")
    service = services.get(service_name)
    if not isinstance(service, dict):
        pytest.fail("effective Compose service is invalid")
    environment = service.get("environment")
    if environment is None:
        return {}
    if not isinstance(environment, dict):
        pytest.fail("effective Compose environment is invalid")
    return {str(key): str(value) for key, value in environment.items()}


def _effective_service_mounts(
    payload: dict[str, object],
    service_name: str,
) -> tuple[dict[str, object], ...]:
    services = payload.get("services")
    if not isinstance(services, dict):
        pytest.fail("effective Compose services are invalid")
    service = services.get(service_name)
    if not isinstance(service, dict):
        pytest.fail("effective Compose service is invalid")
    volumes = service.get("volumes")
    if not isinstance(volumes, list):
        pytest.fail("effective Compose volumes are invalid")
    if not all(isinstance(volume, dict) for volume in volumes):
        pytest.fail("effective Compose volume is invalid")
    return tuple(volumes)  # type: ignore[return-value]


def _mount_reaching_container_path(
    mounts: tuple[dict[str, object], ...],
    container_path: str,
) -> dict[str, object]:
    normalized_path = "/" + str(container_path).strip("/")
    candidates: list[dict[str, object]] = []
    for mount in mounts:
        target = "/" + str(mount.get("target") or "").strip("/")
        if normalized_path == target or normalized_path.startswith(target + "/"):
            candidates.append(mount)
    if not candidates:
        pytest.fail(f"no effective mount reaches {normalized_path}")
    return max(candidates, key=lambda mount: len(str(mount.get("target") or "")))


def test_env_example_declares_safe_audiobook_runtime_defaults() -> None:
    environment = _env_example()

    assert {key: environment[key] for key in SAFE_CINEMATIC_DEFAULTS} == SAFE_CINEMATIC_DEFAULTS
    assert CANARY_HMAC_KEY in environment
    assert environment[CANARY_HMAC_KEY] == ""
    assert {key: environment[key] for key in VOCALLAB_SAFE_DEFAULTS} == (
        VOCALLAB_SAFE_DEFAULTS
    )


@pytest.mark.parametrize("service_name", ("ea-api", "ea-worker", "ea-scheduler"))
def test_main_compose_audiobook_services_share_safe_runtime_contract(service_name: str) -> None:
    environment = _compose_environment(REPO_ROOT / "docker-compose.yml", service_name)

    for key, default in SAFE_CINEMATIC_DEFAULTS.items():
        assert environment[key] == f"${{{key}:-{default}}}"
    assert environment[CANARY_HMAC_KEY] == f"${{{CANARY_HMAC_KEY}:-}}"
    for key, default in VOCALLAB_SAFE_DEFAULTS.items():
        assert environment[key] == f"${{{key}:-{default}}}"


def test_whatsapp_action_processor_shares_safe_audiobook_runtime_contract() -> None:
    environment = _compose_environment(
        REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        "ea-whatsapp-web-action-processor",
    )

    for key, default in SAFE_CINEMATIC_DEFAULTS.items():
        assert environment[key] == f"${{{key}:-{default}}}"
    assert environment[CANARY_HMAC_KEY] == f"${{{CANARY_HMAC_KEY}:-}}"
    for key, default in VOCALLAB_SAFE_DEFAULTS.items():
        assert environment[key] == f"${{{key}:-{default}}}"


def test_effective_compose_projects_vocallab_secret_only_to_authorized_services(
    tmp_path: Path,
) -> None:
    rendered = _render_effective_compose(
        tmp_path,
        compose_paths_before_injection=(
            REPO_ROOT / "docker-compose.yml",
            REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        ),
    )
    services = rendered.get("services")
    assert isinstance(services, dict)
    recipients: set[str] = set()
    key_file_recipients: set[str] = set()
    unauthorized_key_recipients: set[str] = set()
    unauthorized_key_file_recipients: set[str] = set()
    for service_name in services:
        environment = _effective_service_environment(rendered, str(service_name))
        key = environment.get("VOCALLAB_API_KEY")
        key_file = environment.get("VOCALLAB_API_KEY_FILE")
        if key == SYNTHETIC_VOCALLAB_KEY:
            recipients.add(str(service_name))
        if key_file == SYNTHETIC_VOCALLAB_KEY_FILE:
            key_file_recipients.add(str(service_name))
        if str(service_name) not in AUTHORIZED_VOCALLAB_SERVICES:
            if key not in (None, ""):
                unauthorized_key_recipients.add(str(service_name))
            if key_file not in (None, ""):
                unauthorized_key_file_recipients.add(str(service_name))
    assert recipients == AUTHORIZED_VOCALLAB_SERVICES
    assert key_file_recipients == AUTHORIZED_VOCALLAB_SERVICES
    assert unauthorized_key_recipients == set()
    assert unauthorized_key_file_recipients == set()


def test_unauthorized_services_mask_private_vocallab_files_from_broad_mounts(
    tmp_path: Path,
) -> None:
    rendered = _render_effective_compose(
        tmp_path,
        compose_paths_before_injection=(
            REPO_ROOT / "docker-compose.yml",
            REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        ),
    )

    for service_name, config_roots in UNAUTHORIZED_VOCALLAB_CONFIG_ROOTS.items():
        mounts = _effective_service_mounts(rendered, service_name)
        for config_root in config_roots:
            for filename in PRIVATE_VOCALLAB_CONFIG_FILENAMES:
                private_target = f"{config_root}/{filename}"
                winner = _mount_reaching_container_path(mounts, private_target)
                assert winner.get("type") == "tmpfs"
                assert winner.get("target") == config_root
                tmpfs = winner.get("tmpfs")
                assert isinstance(tmpfs, dict)
                assert tmpfs.get("mode") == 0o555
                assert int(str(tmpfs.get("size") or "0")) == 65536

        for filename in PRIVATE_VOCALLAB_CONFIG_FILENAMES:
            private_source = (REPO_ROOT / "config" / filename).resolve()
            for mount in mounts:
                if mount.get("type") != "bind":
                    continue
                source = mount.get("source")
                target = mount.get("target")
                if not isinstance(source, str) or not isinstance(target, str):
                    pytest.fail("effective Compose bind mount is invalid")
                try:
                    relative_private_path = private_source.relative_to(
                        Path(source).resolve()
                    )
                except ValueError:
                    continue
                projected_target = (
                    Path(target) / relative_private_path
                ).as_posix()
                winner = _mount_reaching_container_path(mounts, projected_target)
                assert winner.get("type") == "tmpfs"
                assert winner.get("target") in config_roots


def test_unauthorized_services_keep_only_explicit_non_vocallab_config_files(
    tmp_path: Path,
) -> None:
    rendered = _render_effective_compose(
        tmp_path,
        compose_paths_before_injection=(
            REPO_ROOT / "docker-compose.yml",
            REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        ),
    )

    for service_name, config_roots in UNAUTHORIZED_VOCALLAB_CONFIG_ROOTS.items():
        mounts = _effective_service_mounts(rendered, service_name)
        for config_root in config_roots:
            for filename in NON_VOCALLAB_CONFIG_ALLOWLIST:
                allowed_target = f"{config_root}/{filename}"
                winner = _mount_reaching_container_path(mounts, allowed_target)
                assert winner.get("type") == "bind"
                assert winner.get("target") == allowed_target
                assert winner.get("read_only") is True
                source = winner.get("source")
                assert isinstance(source, str)
                assert Path(source).resolve() == (
                    REPO_ROOT / "config" / filename
                ).resolve()


def test_unauthorized_broad_repo_mounts_mask_runtime_env_file(
    tmp_path: Path,
) -> None:
    rendered = _render_effective_compose(
        tmp_path,
        compose_paths_before_injection=(
            REPO_ROOT / "docker-compose.yml",
            REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        ),
    )

    for service_name in BROAD_REPO_UNAUTHORIZED_VOCALLAB_SERVICES:
        mounts = _effective_service_mounts(rendered, service_name)
        winner = _mount_reaching_container_path(mounts, "/app/.env")
        assert winner.get("type") == "bind"
        assert winner.get("source") == "/dev/null"
        assert winner.get("target") == "/app/.env"
        assert winner.get("read_only") is True

        repo_mount = next(
            mount
            for mount in mounts
            if mount.get("type") == "bind"
            and Path(str(mount.get("source") or "")).resolve() == REPO_ROOT
            and mount.get("target") == "/app"
        )
        projected_env = (
            Path(str(repo_mount["target"]))
            / (REPO_ROOT / ".env").resolve().relative_to(
                Path(str(repo_mount["source"])).resolve()
            )
        ).as_posix()
        assert _mount_reaching_container_path(mounts, projected_env) == winner


def test_unauthorized_shared_provider_ledger_mounts_mask_vocallab_ledger(
    tmp_path: Path,
) -> None:
    rendered = _render_effective_compose(
        tmp_path,
        compose_paths_before_injection=(
            REPO_ROOT / "docker-compose.yml",
            REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        ),
    )

    for service_name in SHARED_LEDGER_UNAUTHORIZED_VOCALLAB_SERVICES:
        mounts = _effective_service_mounts(rendered, service_name)
        winner = _mount_reaching_container_path(
            mounts,
            VOCALLAB_PRIVATE_LEDGER_ROOT,
        )
        assert winner.get("type") == "tmpfs"
        assert winner.get("target") == VOCALLAB_PRIVATE_LEDGER_ROOT
        tmpfs = winner.get("tmpfs")
        assert isinstance(tmpfs, dict)
        assert tmpfs.get("mode") == 0o555
        assert int(str(tmpfs.get("size") or "0")) == 65536

    for service_name in SHARED_LEDGER_AUTHORIZED_VOCALLAB_SERVICES:
        mounts = _effective_service_mounts(rendered, service_name)
        winner = _mount_reaching_container_path(
            mounts,
            VOCALLAB_PRIVATE_LEDGER_ROOT,
        )
        assert winner.get("type") == "volume"
        assert winner.get("target") == "/data/provider-ledger"


def test_full_paused_stage_removes_vocallab_secret_and_preserves_ea_api(
    tmp_path: Path,
) -> None:
    compose_before_stage = (
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
    )
    baseline = _render_effective_compose(
        tmp_path / "baseline",
        compose_paths_before_injection=compose_before_stage,
    )
    staged = _render_effective_compose(
        tmp_path / "staged",
        compose_paths_before_injection=compose_before_stage,
        compose_paths_after_injection=(
            REPO_ROOT
            / "deploy/audiobook-runtime-production/docker-compose.production-stage.yml",
        ),
    )
    baseline_services = baseline.get("services")
    staged_services = staged.get("services")
    assert isinstance(baseline_services, dict)
    assert isinstance(staged_services, dict)
    assert staged_services["ea-api"] == baseline_services["ea-api"]
    api_environment = _effective_service_environment(staged, "ea-api")
    baseline_api_environment = _effective_service_environment(baseline, "ea-api")
    assert api_environment == baseline_api_environment
    assert api_environment.get("VOCALLAB_API_KEY") == SYNTHETIC_VOCALLAB_KEY
    assert api_environment.get("VOCALLAB_API_KEY_FILE") == SYNTHETIC_VOCALLAB_KEY_FILE
    for key in (
        "EA_AUDIOBOOK_VOCALLAB_ENABLED",
        "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER",
        "EA_AUDIOBOOK_VOCALLAB_ALLOW_PERSONA",
        "EA_AUDIOBOOK_TTS_ALLOW_CROSS_PROVIDER_FALLBACK",
    ):
        assert api_environment.get(key) == "0"

    authority_flags = (
        "EA_AUDIOBOOK_RUNTIME_ACTIVATION_AUTHORITY",
        "EA_AUDIOBOOK_RUNTIME_QUEUE_MUTATION_AUTHORITY",
        "EA_AUDIOBOOK_RUNTIME_PROVIDER_WORK_AUTHORITY",
        "EA_AUDIOBOOK_RUNTIME_OUTBOUND_SEND_AUTHORITY",
    )
    safe_flags = (
        "EA_AUDIOBOOK_VOCALLAB_ENABLED",
        "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER",
        "EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS",
        "EA_AUDIOBOOK_VOCALLAB_ALLOW_COMMUNITY_VOICES",
        "EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES",
        "EA_AUDIOBOOK_VOCALLAB_ALLOW_PERSONA",
        "EA_AUDIOBOOK_TTS_ALLOW_CROSS_PROVIDER_FALLBACK",
        "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED",
        "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER",
        "EA_AUDIOBOOK_CINEMATIC_NARRATION",
        "EA_AUDIOBOOKSHELF_AUTO_IMPORT",
        "EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED",
    )
    service_specific_safe_flags = {
        "ea-worker": (
            "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED",
            "EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS",
        ),
        "ea-scheduler": (
            "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED",
            "EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS",
        ),
        "ea-whatsapp-web-action-processor": (
            "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED",
            "EA_WHATSAPP_AUDIOBOOK_RESUME_DUE",
            "EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED",
            "EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED",
        ),
    }
    for service_name in (
        "ea-worker",
        "ea-scheduler",
        "ea-whatsapp-web-action-processor",
    ):
        service = staged_services[service_name]
        assert isinstance(service, dict)
        deploy = service.get("deploy")
        assert isinstance(deploy, dict)
        assert deploy.get("replicas") == 0
        environment = _effective_service_environment(staged, service_name)
        service_key_present = bool(environment.get("VOCALLAB_API_KEY"))
        assert service_key_present is False
        for key in (
            *authority_flags,
            *safe_flags,
            *service_specific_safe_flags[service_name],
        ):
            assert environment.get(key) == "0"

    leaking_services: set[str] = set()
    for service_name in staged_services:
        environment = _effective_service_environment(staged, str(service_name))
        if environment.get("VOCALLAB_API_KEY") not in (None, ""):
            leaking_services.add(str(service_name))
    # The overlay leaves the existing live API byte-for-byte unchanged. Only
    # the three newly staged, paused services must have provider credentials
    # stripped from their effective configuration.
    assert leaking_services == {"ea-api"}
