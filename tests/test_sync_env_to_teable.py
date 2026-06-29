from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "sync_env_to_teable.py"
BOOTSTRAP_SCRIPT_PATH = ROOT / "scripts" / "bootstrap_from_teable.sh"


def _module():
    spec = importlib.util.spec_from_file_location("sync_env_to_teable", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_env_secret_rows_classifies_and_can_include_secret_values(tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TEABLE_API_KEY=teable-live-key",
                "UNMIXR_PASSWORD=voice-password",
                "EA_HOST_PORT=8010",
                "DATABASE_URL=postgresql://user:pass@db/app",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = module.build_env_secret_rows(env_files=(env_file,), include_values=True, host_profile="test-host")
    by_name = {row["env_name"]: row for row in rows}

    assert by_name["TEABLE_API_KEY"]["secret_kind"] == "api_key"
    assert by_name["TEABLE_API_KEY"]["provider_guess"] == "teable"
    assert by_name["TEABLE_API_KEY"]["env_value_secret"] == "teable-live-key"
    assert by_name["UNMIXR_PASSWORD"]["secret_kind"] == "password"
    assert by_name["DATABASE_URL"]["secret_kind"] == "database_url"
    assert by_name["EA_HOST_PORT"]["secret_kind"] == "config"
    assert by_name["TEABLE_API_KEY"]["projection_id"] == "test-host:ea_service:TEABLE_API_KEY"
    assert by_name["TEABLE_API_KEY"]["value_sha256"]


def test_build_env_secret_rows_can_omit_values_for_metadata_only_backup(tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("EMAILIT_API_KEY=emailit-key\nEA_RUNTIME_MODE=prod\n", encoding="utf-8")

    rows = module.build_env_secret_rows(env_files=(env_file,), include_values=False, host_profile="test-host")
    by_name = {row["env_name"]: row for row in rows}

    assert by_name["EMAILIT_API_KEY"]["env_value_secret"] == ""
    assert by_name["EMAILIT_API_KEY"]["value_present"] is False
    assert by_name["EMAILIT_API_KEY"]["value_sha256"] == ""
    assert by_name["EMAILIT_API_KEY"]["value_length"] == 0
    assert by_name["EMAILIT_API_KEY"]["notes"] == "metadata_only_secret_value_omitted"


def test_build_recovery_rows_includes_referenced_secret_files(tmp_path: Path) -> None:
    module = _module()
    secret_file = tmp_path / "onemin_api_keys.local.json"
    secret_file.write_text('{"keys":["one","two"]}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(f"ONEMIN_DIRECT_API_KEYS_JSON_FILE={secret_file}\n", encoding="utf-8")

    rows = module.build_recovery_rows(env_files=(env_file,), include_values=True, host_profile="test-host")
    file_rows = [row for row in rows if row["source_scope"] == "ea_file"]

    assert len(file_rows) == 1
    assert file_rows[0]["env_name"] == "ONEMIN_DIRECT_API_KEYS_JSON_FILE"
    assert file_rows[0]["secret_kind"] == "secret_file"
    assert file_rows[0]["env_value_secret"] == base64.b64encode(b'{"keys":["one","two"]}').decode("ascii")


def test_build_recovery_rows_includes_referenced_file_metadata_without_values(tmp_path: Path) -> None:
    module = _module()
    secret_file = tmp_path / "onemin_api_keys.local.json"
    secret_file.write_text('{"keys":["one","two"]}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(f"ONEMIN_DIRECT_API_KEYS_JSON_FILE={secret_file}\n", encoding="utf-8")

    rows = module.build_recovery_rows(env_files=(env_file,), include_values=False, host_profile="test-host")
    file_rows = [row for row in rows if row["source_scope"] == "ea_file"]

    assert len(file_rows) == 1
    assert file_rows[0]["env_name"] == "ONEMIN_DIRECT_API_KEYS_JSON_FILE"
    assert file_rows[0]["env_value_secret"] == ""
    assert file_rows[0]["value_present"] is False
    assert file_rows[0]["value_sha256"] == ""
    assert file_rows[0]["value_length"] == 0
    assert file_rows[0]["notes"] == "metadata_only_secret_file_value_omitted"


def test_build_recovery_rows_includes_config_file_references(tmp_path: Path) -> None:
    module = _module()
    config_file = tmp_path / "fastestvpn.ovpn"
    config_file.write_text("client\nremote vpn.example 1194\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(f"FASTESTVPN_CONFIG_FILE={config_file}\n", encoding="utf-8")

    rows = module.build_recovery_rows(env_files=(env_file,), include_values=True, host_profile="test-host")
    file_rows = [row for row in rows if row["source_scope"] == "ea_file"]

    assert len(file_rows) == 1
    assert file_rows[0]["env_name"] == "FASTESTVPN_CONFIG_FILE"
    assert file_rows[0]["secret_kind"] == "secret_file"
    assert file_rows[0]["env_value_secret"] == base64.b64encode(b"client\nremote vpn.example 1194\n").decode("ascii")


def test_build_recovery_rows_includes_default_local_secret_files(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cartesia_file = config_dir / "cartesia.local.json"
    gemini_file = config_dir / "gemini_cli_desktop_client_secret.json"
    unmixr_file = config_dir / "unmixr_api_keys.json"
    accounts_file = config_dir / "unmixr_accounts.json"
    slot_owner_file = config_dir / "onemin_slot_owners.json"
    example_file = config_dir / "onemin_api_keys.example.json"
    cartesia_file.write_text('{"api_key":"cartesia"}', encoding="utf-8")
    gemini_file.write_text('{"installed":{"client_id":"gemini"}}', encoding="utf-8")
    unmixr_file.write_text('{"keys":["unmixr"]}', encoding="utf-8")
    accounts_file.write_text('{"accounts":[{"label":"slot-1"}]}', encoding="utf-8")
    slot_owner_file.write_text('{"slots":[{"slot":"fallback_1","owner":"sample"}]}', encoding="utf-8")
    example_file.write_text('{"example":true}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))
    rows = module.build_recovery_rows(
        env_files=(env_file, service_env_file), include_values=True, host_profile="test-host"
    )
    file_rows = {row["source_path"]: row for row in rows if row["source_scope"] == "ea_file"}

    assert set(file_rows) == {
        str(cartesia_file),
        str(gemini_file),
        str(unmixr_file),
        str(accounts_file),
        str(slot_owner_file),
    }
    assert file_rows[str(cartesia_file)]["env_name"] == "LOCAL_SECRET_FILE:config/cartesia.local.json"
    assert file_rows[str(gemini_file)]["env_name"] == "LOCAL_SECRET_FILE:config/gemini_cli_desktop_client_secret.json"
    assert file_rows[str(unmixr_file)]["env_name"] == "LOCAL_SECRET_FILE:config/unmixr_api_keys.json"
    assert file_rows[str(accounts_file)]["env_name"] == "LOCAL_SECRET_FILE:config/unmixr_accounts.json"
    assert file_rows[str(slot_owner_file)]["env_name"] == "LOCAL_SECRET_FILE:config/onemin_slot_owners.json"
    assert file_rows[str(cartesia_file)]["env_value_secret"] == base64.b64encode(b'{"api_key":"cartesia"}').decode("ascii")
    assert str(example_file) not in file_rows


def test_build_recovery_rows_includes_default_audiobook_access_files(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    phone_whitelist = config_dir / "audiobook_instant_phone_whitelist"
    sender_whitelist = config_dir / "audiobook_instant_sender_whitelist"
    whatsapp_secret = config_dir / "whatsapp_audiobook_callback_secret"
    phone_whitelist.write_text("+15550101000\n", encoding="utf-8")
    sender_whitelist.write_text("telegram:123\n", encoding="utf-8")
    whatsapp_secret.write_text("callback-secret\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))
    rows = module.build_recovery_rows(
        env_files=(env_file, service_env_file), include_values=True, host_profile="test-host"
    )
    file_rows = {row["source_path"]: row for row in rows if row["source_scope"] == "ea_file"}

    assert set(file_rows) == {str(phone_whitelist), str(sender_whitelist), str(whatsapp_secret)}
    assert file_rows[str(phone_whitelist)]["env_name"] == "LOCAL_SECRET_FILE:config/audiobook_instant_phone_whitelist"
    assert file_rows[str(sender_whitelist)]["env_name"] == "LOCAL_SECRET_FILE:config/audiobook_instant_sender_whitelist"
    assert file_rows[str(whatsapp_secret)]["env_name"] == "LOCAL_SECRET_FILE:config/whatsapp_audiobook_callback_secret"
    assert file_rows[str(phone_whitelist)]["env_value_secret"] == base64.b64encode(b"+15550101000\n").decode("ascii")


def test_build_recovery_rows_ignores_generated_restore_backup_files(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    whatsapp_secret = config_dir / "whatsapp_audiobook_callback_secret"
    backup_secret = config_dir / "whatsapp_audiobook_callback_secret.20260629T130046Z.bak"
    whatsapp_secret.write_text("callback-secret\n", encoding="utf-8")
    backup_secret.write_text("older-callback-secret\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))
    rows = module.build_recovery_rows(
        env_files=(env_file, service_env_file), include_values=True, host_profile="test-host"
    )
    file_rows = {row["source_path"]: row for row in rows if row["source_scope"] == "ea_file"}

    assert set(file_rows) == {str(whatsapp_secret)}
    assert str(backup_secret) not in file_rows


def test_build_recovery_rows_deduplicates_env_referenced_default_local_secret_files(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    local_file = config_dir / "onemin_api_keys.local.json"
    local_file.write_text('{"keys":["one"]}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("ONEMIN_DIRECT_API_KEYS_JSON_FILE=config/onemin_api_keys.local.json\n", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))
    rows = module.build_recovery_rows(
        env_files=(env_file, service_env_file), include_values=True, host_profile="test-host"
    )
    file_rows = [row for row in rows if row["source_scope"] == "ea_file"]

    assert len(file_rows) == 1
    assert file_rows[0]["env_name"] == "ONEMIN_DIRECT_API_KEYS_JSON_FILE"
    assert file_rows[0]["source_path"] == str(local_file)


def test_audit_local_secret_file_coverage_fails_for_uncovered_likely_secret_file(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    covered_file = config_dir / "cartesia.local.json"
    uncovered_file = config_dir / "extra_credentials.json"
    covered_file.write_text('{"api_key":"cartesia"}', encoding="utf-8")
    uncovered_file.write_text('{"token":"extra"}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))

    result = module.audit_local_secret_file_coverage(env_files=(env_file, service_env_file), host_profile="test-host")

    assert result["status"] == "fail"
    assert result["candidate_count"] == 2
    assert result["covered_count"] == 1
    assert result["uncovered_count"] == 1
    assert result["uncovered_paths"] == [str(uncovered_file)]


def test_audit_local_secret_file_coverage_covers_default_audiobook_access_files(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "audiobook_instant_phone_whitelist").write_text("+15550101000\n", encoding="utf-8")
    (config_dir / "whatsapp_audiobook_callback_secret").write_text("callback-secret\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))

    result = module.audit_local_secret_file_coverage(env_files=(env_file, service_env_file), host_profile="test-host")

    assert result["status"] == "pass"
    assert result["candidate_count"] == 2
    assert result["covered_count"] == 2


def test_audit_local_secret_file_coverage_ignores_generated_restore_backup_files(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "whatsapp_audiobook_callback_secret").write_text("callback-secret\n", encoding="utf-8")
    (config_dir / "whatsapp_audiobook_callback_secret.20260629T130046Z.bak").write_text(
        "older-callback-secret\n", encoding="utf-8"
    )
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    service_env_file = tmp_path / "ea" / ".env"
    service_env_file.parent.mkdir()
    service_env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, service_env_file))

    result = module.audit_local_secret_file_coverage(env_files=(env_file, service_env_file), host_profile="test-host")

    assert result["status"] == "pass"
    assert result["candidate_count"] == 1
    assert result["covered_count"] == 1


def test_uses_default_env_files_accepts_standard_relative_paths(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root = tmp_path
    env_file = root / ".env"
    local_file = root / ".env.local"
    service_env_file = root / "ea" / ".env"
    service_env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("EA_API_TOKEN=test\n", encoding="utf-8")
    local_file.write_text("EA_API_TOKEN=test\n", encoding="utf-8")
    service_env_file.write_text("EA_API_TOKEN=test\n", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (env_file, local_file, service_env_file))

    assert module._uses_default_env_files((Path(".env"), Path(".env.local"), Path("ea/.env")))


def test_audit_local_secret_file_coverage_skips_custom_env_file(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "extra_credentials.json").write_text('{"token":"extra"}', encoding="utf-8")
    env_file = tmp_path / "custom.env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)

    result = module.audit_local_secret_file_coverage(env_files=(env_file,), host_profile="test-host")

    assert result["status"] == "skipped"
    assert result["uncovered_count"] == 0


def test_audit_default_env_files_fails_when_required_default_env_missing(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")

    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (root_env, local_env, service_env))
    monkeypatch.setattr(module, "REQUIRED_DEFAULT_ENV_FILES", (root_env, local_env))

    result = module.audit_default_env_files((root_env, local_env, service_env))

    assert result["status"] == "fail"
    assert result["missing_required_env_files"] == [str(local_env)]


def test_audit_compose_required_env_coverage_allows_defaults_and_home(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    service_env.parent.mkdir()
    root_env.write_text("DATABASE_URL=postgres://db\n", encoding="utf-8")
    local_env.write_text("", encoding="utf-8")
    service_env.write_text("", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  api:",
                "    environment:",
                "      - DATABASE_URL=${DATABASE_URL}",
                "      - HOME=${HOME}",
                "      - OPTIONAL=${OPTIONAL:-default}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (root_env, local_env, service_env))

    result = module.audit_compose_required_env_coverage(env_files=(root_env, local_env, service_env))

    assert result["status"] == "pass"
    assert result["missing_required_compose_env"] == []


def test_audit_compose_required_env_coverage_fails_missing_required_env(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    service_env.parent.mkdir()
    root_env.write_text("", encoding="utf-8")
    local_env.write_text("", encoding="utf-8")
    service_env.write_text("", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  api:\n    environment:\n      - EA_REQUIRED=${EA_REQUIRED}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (root_env, local_env, service_env))

    result = module.audit_compose_required_env_coverage(env_files=(root_env, local_env, service_env))

    assert result["status"] == "fail"
    assert result["missing_required_compose_env"] == ["EA_REQUIRED"]


def test_audit_compose_required_env_coverage_ignores_shell_local_variables(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    service_env.parent.mkdir()
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    local_env.write_text("EA_REQUIRED=done\n", encoding="utf-8")
    service_env.write_text("", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  api:\n    command: |\n      - code=0;\n      - if [ \"$${code}\" -ne 0 ]; then echo $${code}; fi\n      - port=8090;\n      - curl http://127.0.0.1:$${port}/health;\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (root_env, local_env, service_env))

    result = module.audit_compose_required_env_coverage(env_files=(root_env, local_env, service_env))

    assert result["status"] == "pass"
    assert result["missing_required_compose_env"] == []


def test_restore_env_file_writes_teable_values_without_leaking_other_scopes(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / ".env"
    output.write_text("OLD_SECRET=old\n", encoding="utf-8")

    def _fake_list_records(*, base_url: str, api_key: str, table_id: str):
        return [
            {
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EMAILIT_API_KEY",
                "env_value_secret": "emailit key with space",
            },
            {
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "VOICEWAVE_LOGIN_PASSWORD",
                "env_value_secret": "service-password",
            },
            {
                "source_scope": "ea_root",
                "restore_enabled": False,
                "env_name": "DISABLED_SECRET",
                "env_value_secret": "nope",
            },
        ]

    monkeypatch.setattr(module, "_list_records", _fake_list_records)
    result = module.restore_env_file(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        output_path=output,
        source_scope="ea_root",
    )

    text = output.read_text(encoding="utf-8")
    assert result["restored"] == 1
    assert result["hash_verified"] == 1
    assert result["hash_mismatch_keys"] == []
    backup_path = Path(result["backup_path"])
    assert backup_path.is_file()
    assert backup_path.read_text(encoding="utf-8") == "OLD_SECRET=old\n"
    assert 'EMAILIT_API_KEY="emailit key with space"' in text
    assert "VOICEWAVE_LOGIN_PASSWORD" not in text
    assert "DISABLED_SECRET" not in text
    assert output.stat().st_mode & 0o777 == 0o600


def test_restore_env_file_filters_other_host_profiles(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / ".env"

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-local:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "wrong-profile",
            },
            {
                "projection_id": "ea-prod:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "right-profile",
            },
        ],
    )

    result = module.restore_env_file(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        output_path=output,
        source_scope="ea_root",
        host_profile="ea-prod",
    )

    text = output.read_text(encoding="utf-8")
    assert result["restored"] == 1
    assert result["hash_verified"] == 1
    assert result["hash_mismatch_keys"] == []
    assert "EA_API_TOKEN=right-profile" in text
    assert "wrong-profile" not in text
    assert output.stat().st_mode & 0o777 == 0o600


def test_restore_env_file_treats_string_false_restore_enabled_as_disabled(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / ".env"

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:DISABLED_API_KEY",
                "source_scope": "ea_root",
                "restore_enabled": "false",
                "env_name": "DISABLED_API_KEY",
                "env_value_secret": "should-not-restore",
            }
        ],
    )

    result = module.restore_env_file(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        output_path=output,
        source_scope="ea_root",
        host_profile="ea-prod",
    )

    assert result["restored"] == 0
    assert "DISABLED_API_KEY" not in output.read_text(encoding="utf-8")


def test_restore_env_file_treats_omitted_disabled_stale_note_as_disabled(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / ".env"

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:DISABLED_STALE_API_KEY",
                "source_scope": "ea_root",
                "notes": "disabled_stale_not_in_current_env",
                "env_name": "DISABLED_STALE_API_KEY",
                "env_value_secret": "should-not-restore",
            }
        ],
    )

    result = module.restore_env_file(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        output_path=output,
        source_scope="ea_root",
        host_profile="ea-prod",
    )

    assert result["restored"] == 0
    assert "DISABLED_STALE_API_KEY" not in output.read_text(encoding="utf-8")


def test_restore_env_file_fails_before_write_when_required_secret_cell_is_blank(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / ".env"
    output.write_text("OLD_SECRET=old\n", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "value_present": True,
                "env_value_secret": "",
            }
        ],
    )

    try:
        module.restore_env_file(
            base_url="https://teable.example",
            api_key="teable-key",
            table_id="tbl_env",
            output_path=output,
            source_scope="ea_root",
            host_profile="ea-prod",
        )
    except SystemExit as exc:
        assert str(exc) == "teable_restore_missing_secret_values:ea_root:EA_API_TOKEN"
    else:
        raise AssertionError("expected restore to fail before writing blank required secret")

    assert output.read_text(encoding="utf-8") == "OLD_SECRET=old\n"
    assert not list(tmp_path.glob(".env.*.bak"))


def test_restore_referenced_secret_files_preserves_existing_file(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    secret_file = tmp_path / "config" / "onemin_api_keys.local.json"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text("old", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_path": str(secret_file),
                "env_value_secret": base64.b64encode(b"new-secret-file-content\n").decode("ascii"),
            }
        ],
    )

    result = module.restore_referenced_secret_files(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
    )

    assert result["restored_files"] == 1
    assert result["hash_verified"] == 1
    assert result["hash_mismatch_paths"] == []
    assert secret_file.read_text(encoding="utf-8") == "new-secret-file-content\n"
    assert result["restored_file_paths"] == [str(secret_file)]
    assert secret_file.stat().st_mode & 0o777 == 0o600
    backup_paths = result["file_backup_paths"]
    assert len(backup_paths) == 1
    assert Path(backup_paths[0]).read_text(encoding="utf-8") == "old"


def test_restore_referenced_secret_files_filters_other_host_profiles(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    wrong_file = tmp_path / "wrong.json"
    right_file = tmp_path / "right.json"

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-local:ea_file:ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_path": str(wrong_file),
                "env_value_secret": base64.b64encode(b"wrong").decode("ascii"),
            },
            {
                "projection_id": "ea-prod:ea_file:ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_path": str(right_file),
                "env_value_secret": base64.b64encode(b"right").decode("ascii"),
            },
        ],
    )

    result = module.restore_referenced_secret_files(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        host_profile="ea-prod",
    )

    assert result["restored_files"] == 1
    assert result["hash_verified"] == 1
    assert result["hash_mismatch_paths"] == []
    assert not wrong_file.exists()
    assert right_file.read_text(encoding="utf-8") == "right"
    assert result["restored_file_paths"] == [str(right_file)]
    assert right_file.stat().st_mode & 0o777 == 0o600


def test_restore_referenced_secret_files_fails_before_write_when_required_secret_cell_is_blank(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    secret_file = tmp_path / "config" / "onemin_api_keys.local.json"

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_file:ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "value_present": True,
                "source_path": str(secret_file),
                "env_value_secret": "",
            }
        ],
    )

    try:
        module.restore_referenced_secret_files(
            base_url="https://teable.example",
            api_key="teable-key",
            table_id="tbl_env",
            host_profile="ea-prod",
        )
    except SystemExit as exc:
        assert str(exc) == "teable_restore_missing_secret_values:ea_file:ONEMIN_DIRECT_API_KEYS_JSON_FILE"
    else:
        raise AssertionError("expected referenced file restore to fail before writing blank required secret")

    assert not secret_file.exists()


def test_restore_referenced_secret_files_can_map_paths_to_output_root(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    output_root = tmp_path / "drill"
    source_path = ROOT / "config" / "onemin_api_keys.local.json"

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_file:ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_path": str(source_path),
                "env_value_secret": base64.b64encode(b"drill-secret\n").decode("ascii"),
            }
        ],
    )

    result = module.restore_referenced_secret_files(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        host_profile="ea-prod",
        output_root=output_root,
    )

    assert result["restored_files"] == 1
    assert (output_root / "config" / "onemin_api_keys.local.json").read_text(encoding="utf-8") == "drill-secret\n"
    assert result["restored_file_paths"] == [str(output_root / "config" / "onemin_api_keys.local.json")]
    assert not result["file_backup_paths"]
    assert (output_root / "config" / "onemin_api_keys.local.json").stat().st_mode & 0o777 == 0o600


def test_bootstrap_env_files_restores_root_and_service_scopes(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_output = tmp_path / ".env"
    service_output = tmp_path / "ea" / ".env"
    root_output.write_text("OLD_ROOT=1\n", encoding="utf-8")
    service_output.parent.mkdir(parents=True, exist_ok=True)
    service_output.write_text("OLD_SERVICE=1\n", encoding="utf-8")

    def _fake_list_records(*, base_url: str, api_key: str, table_id: str):
        return [
            {
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "root-token",
            },
            {
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "VOICEWAVE_LOGIN_PASSWORD",
                "env_value_secret": "service-password",
            },
            {
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_path": str(tmp_path / "config" / "onemin_api_keys.local.json"),
                "env_value_secret": base64.b64encode(b"file-secret\n").decode("ascii"),
            },
        ]

    monkeypatch.setattr(module, "_list_records", _fake_list_records)

    result = module.bootstrap_env_files(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_output,
        service_env_path=service_output,
    )

    assert result["root_restored"] == 1
    assert result["root_hash_verified"] == 1
    assert result["root_hash_mismatch_keys"] == []
    assert result["service_restored"] == 1
    assert result["service_hash_verified"] == 1
    assert result["service_hash_mismatch_keys"] == []
    assert result["referenced_files_restored"] == 1
    assert result["referenced_file_hash_verified"] == 1
    assert result["referenced_file_hash_mismatch_paths"] == []
    assert result["referenced_file_paths"] == [str(tmp_path / "config" / "onemin_api_keys.local.json")]
    assert Path(result["root_backup_path"]).read_text(encoding="utf-8") == "OLD_ROOT=1\n"
    assert Path(result["service_backup_path"]).read_text(encoding="utf-8") == "OLD_SERVICE=1\n"
    assert "EA_API_TOKEN=root-token" in root_output.read_text(encoding="utf-8")
    assert "VOICEWAVE_LOGIN_PASSWORD=service-password" in service_output.read_text(encoding="utf-8")
    assert (tmp_path / "config" / "onemin_api_keys.local.json").read_text(encoding="utf-8") == "file-secret\n"


def test_drill_bootstrap_restore_materializes_into_drill_directory(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    drill_dir = tmp_path / "drill"
    drill_dir.mkdir(mode=0o755)

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "root-token",
            },
            {
                "projection_id": "ea-prod:ea_service:VOICEWAVE_LOGIN_PASSWORD",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "VOICEWAVE_LOGIN_PASSWORD",
                "env_value_secret": "service-password",
            },
            {
                "projection_id": "ea-prod:ea_file:/docker/EA/config/onemin_api_keys.local.json",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "ONEMIN_DIRECT_API_KEYS_JSON_FILE",
                "source_path": str(ROOT / "config" / "onemin_api_keys.local.json"),
                "env_value_secret": base64.b64encode(b"file-secret").decode("ascii"),
            },
        ],
    )

    result = module.drill_bootstrap_restore(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        host_profile="ea-prod",
        output_dir=drill_dir,
    )

    assert result["root_restored"] == 1
    assert result["root_hash_verified"] == 1
    assert result["service_restored"] == 1
    assert result["service_hash_verified"] == 1
    assert result["referenced_files_restored"] == 1
    assert result["referenced_file_hash_verified"] == 1
    assert result["drill_output_dir"] == str(drill_dir)
    assert result["contains_secret_material"] is True
    assert result["drill_verification"]["status"] == "pass"
    assert result["drill_verification"]["checked_file_count"] == 4
    assert result["drill_verification"]["hash_mismatches"] == []
    assert drill_dir.stat().st_mode & 0o777 == 0o700
    assert result["referenced_file_paths"] == [str(drill_dir / "config" / "onemin_api_keys.local.json")]
    assert "EA_API_TOKEN=root-token" in (drill_dir / ".env").read_text(encoding="utf-8")
    assert "VOICEWAVE_LOGIN_PASSWORD=service-password" in (drill_dir / "ea" / ".env").read_text(encoding="utf-8")
    assert (drill_dir / "config" / "onemin_api_keys.local.json").read_text(encoding="utf-8") == "file-secret"
    assert (drill_dir / ".env").stat().st_mode & 0o777 == 0o600
    assert (drill_dir / "ea" / ".env").stat().st_mode & 0o777 == 0o600
    assert (drill_dir / "config" / "onemin_api_keys.local.json").stat().st_mode & 0o777 == 0o600


def test_verify_drill_result_reports_wrong_file_modes(tmp_path: Path) -> None:
    module = _module()
    drill_dir = tmp_path / "drill"
    drill_dir.mkdir(mode=0o700)
    root_env = drill_dir / ".env"
    service_env = drill_dir / "ea" / ".env"
    secret_file = drill_dir / "config" / "onemin_api_keys.local.json"
    service_env.parent.mkdir()
    secret_file.parent.mkdir()
    for path in (root_env, service_env, secret_file):
        path.write_text("x", encoding="utf-8")
        path.chmod(0o600)
    secret_file.chmod(0o644)

    result = module.verify_drill_result(
        {
            "drill_output_dir": str(drill_dir),
            "root_env_path": str(root_env),
            "service_env_path": str(service_env),
            "root_restored": 1,
            "service_restored": 1,
            "referenced_files_restored": 1,
            "referenced_file_paths": [str(secret_file)],
        }
    )

    assert result["status"] == "fail"
    assert result["wrong_modes"] == [{"path": str(secret_file), "mode": "0o644"}]


def test_verify_drill_result_allows_zero_service_rows(tmp_path: Path) -> None:
    module = _module()
    drill_dir = tmp_path / "drill"
    drill_dir.mkdir(mode=0o700)
    root_env = drill_dir / ".env"
    service_env = drill_dir / "ea" / ".env"
    service_env.parent.mkdir()
    for path in (root_env, service_env):
        path.write_text("x", encoding="utf-8")
        path.chmod(0o600)

    result = module.verify_drill_result(
        {
            "drill_output_dir": str(drill_dir),
            "root_env_path": str(root_env),
            "service_env_path": str(service_env),
            "root_restored": 1,
            "root_hash_verified": 1,
            "service_restored": 0,
            "service_hash_verified": 0,
            "referenced_files_restored": 0,
            "referenced_file_hash_verified": 0,
            "referenced_file_paths": [],
        }
    )

    assert result["status"] == "pass"
    assert result["count_mismatch"] == []


def test_check_recovery_ready_passes_and_removes_default_drill_output(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    drill_dir = tmp_path / "drill"

    monkeypatch.setattr(module, "verify_recovery_table", lambda **_: {"status": "pass"})

    def _drill_bootstrap_restore(**_):
        drill_dir.mkdir()
        return {
            "drill_output_dir": str(drill_dir),
            "drill_verification": {"status": "pass"},
        }

    monkeypatch.setattr(module, "drill_bootstrap_restore", _drill_bootstrap_restore)

    result = module.check_recovery_ready(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
    )

    assert result["status"] == "pass"
    assert result["drill_output_removed"] is True
    assert not drill_dir.exists()


def test_check_recovery_ready_fails_when_table_or_drill_fails(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(module, "verify_recovery_table", lambda **_: {"status": "fail"})
    monkeypatch.setattr(
        module,
        "drill_bootstrap_restore",
        lambda **_: {"drill_output_dir": "", "drill_verification": {"status": "pass"}},
    )

    result = module.check_recovery_ready(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
    )

    assert result["status"] == "fail"


def test_verify_restored_outputs_from_table_uses_restored_files_not_default_env(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    restored_file = tmp_path / "config" / "cartesia.local.json"
    service_env.parent.mkdir()
    restored_file.parent.mkdir()
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    local_env.write_text("ONEMIN_AI_API_KEY=local-token\n", encoding="utf-8")
    service_env.write_text("VOICEWAVE_LOGIN_PASSWORD=service-password\n", encoding="utf-8")
    restored_file.write_text('{"api_key":"cartesia"}', encoding="utf-8")
    restored_file.chmod(0o600)

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "root-token",
            },
            {
                "projection_id": "ea-prod:ea_root_local:ONEMIN_AI_API_KEY",
                "source_scope": "ea_root_local",
                "restore_enabled": True,
                "env_name": "ONEMIN_AI_API_KEY",
                "env_value_secret": "local-token",
            },
            {
                "projection_id": "ea-prod:ea_service:VOICEWAVE_LOGIN_PASSWORD",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "VOICEWAVE_LOGIN_PASSWORD",
                "env_value_secret": "service-password",
            },
            {
                "projection_id": "ea-prod:ea_file:/docker/EA/config/cartesia.local.json",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "LOCAL_SECRET_FILE:config/cartesia.local.json",
                "source_path": "/docker/EA/config/cartesia.local.json",
                "env_value_secret": base64.b64encode(b'{"api_key":"cartesia"}').decode("ascii"),
            },
        ],
    )

    result = module.verify_restored_outputs_from_table(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        local_env_path=local_env,
        service_env_path=service_env,
        referenced_file_paths=[str(restored_file)],
        referenced_file_output_root=tmp_path,
        host_profile="ea-prod",
    )

    assert result["status"] == "pass"
    assert result["expected_rows"] == 4
    assert result["same_hash"] == 4
    assert result["root_restore_count"] == 1
    assert result["local_restore_count"] == 1
    assert result["service_restore_count"] == 1
    assert result["referenced_file_restore_count"] == 1


def test_verify_restored_outputs_from_table_requires_exact_mapped_file_path(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    expected_file = tmp_path / "config" / "cartesia.local.json"
    wrong_same_name = tmp_path / "other" / "cartesia.local.json"
    service_env.parent.mkdir()
    expected_file.parent.mkdir()
    wrong_same_name.parent.mkdir()
    root_env.write_text("", encoding="utf-8")
    local_env.write_text("", encoding="utf-8")
    service_env.write_text("", encoding="utf-8")
    expected_file.write_text('{"api_key":"right"}', encoding="utf-8")
    wrong_same_name.write_text('{"api_key":"right"}', encoding="utf-8")
    expected_file.chmod(0o600)
    wrong_same_name.chmod(0o600)

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_file:/docker/EA/config/cartesia.local.json",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "LOCAL_SECRET_FILE:config/cartesia.local.json",
                "source_path": "/docker/EA/config/cartesia.local.json",
                "env_value_secret": base64.b64encode(b'{"api_key":"right"}').decode("ascii"),
            }
        ],
    )

    result = module.verify_restored_outputs_from_table(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        local_env_path=local_env,
        service_env_path=service_env,
        referenced_file_paths=[str(wrong_same_name)],
        referenced_file_output_root=tmp_path,
        host_profile="ea-prod",
    )

    assert result["status"] == "fail"
    assert result["same_hash"] == 0
    assert result["different_hash_count"] == 1
    assert result["different_hash_keys"] == ["/docker/EA/config/cartesia.local.json"]


def test_local_recovery_status_detects_missing_referenced_secret_file(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    secret_file = tmp_path / "config" / "cartesia.local.json"
    service_env.parent.mkdir()
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    local_env.write_text("ONEMIN_AI_API_KEY=local-token\n", encoding="utf-8")
    root_env.chmod(0o600)
    local_env.chmod(0o600)

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "root-token",
            },
            {
                "projection_id": "ea-prod:ea_root_local:ONEMIN_AI_API_KEY",
                "source_scope": "ea_root_local",
                "restore_enabled": True,
                "env_name": "ONEMIN_AI_API_KEY",
                "env_value_secret": "local-token",
            },
            {
                "projection_id": f"ea-prod:ea_file:{secret_file}",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "LOCAL_SECRET_FILE:config/cartesia.local.json",
                "source_path": str(secret_file),
                "env_value_secret": base64.b64encode(b'{"api_key":"cartesia"}').decode("ascii"),
            },
        ],
    )

    result = module.local_recovery_status(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        local_env_path=local_env,
        service_env_path=service_env,
    )

    assert result["status"] == "fail"
    assert result["expected_rows"] == 3
    assert result["same_hash"] == 2
    assert result["missing_artifact_paths"] == [str(secret_file)]
    assert result["different_hash_keys"] == [str(secret_file)]


def test_local_recovery_status_passes_when_env_and_files_match_table(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    secret_file = tmp_path / "config" / "cartesia.local.json"
    service_env.parent.mkdir()
    secret_file.parent.mkdir()
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    local_env.write_text("ONEMIN_AI_API_KEY=local-token\n", encoding="utf-8")
    secret_file.write_text('{"api_key":"cartesia"}', encoding="utf-8")
    root_env.chmod(0o600)
    local_env.chmod(0o600)
    secret_file.chmod(0o600)

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_root:EA_API_TOKEN",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "root-token",
            },
            {
                "projection_id": "ea-prod:ea_root_local:ONEMIN_AI_API_KEY",
                "source_scope": "ea_root_local",
                "restore_enabled": True,
                "env_name": "ONEMIN_AI_API_KEY",
                "env_value_secret": "local-token",
            },
            {
                "projection_id": f"ea-prod:ea_file:{secret_file}",
                "source_scope": "ea_file",
                "restore_enabled": True,
                "env_name": "LOCAL_SECRET_FILE:config/cartesia.local.json",
                "source_path": str(secret_file),
                "env_value_secret": base64.b64encode(b'{"api_key":"cartesia"}').decode("ascii"),
            },
        ],
    )

    result = module.local_recovery_status(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        local_env_path=local_env,
        service_env_path=service_env,
    )

    assert result["status"] == "pass"
    assert result["expected_rows"] == 3
    assert result["same_hash"] == 3
    assert result["missing_artifact_count"] == 0


def test_ensure_local_recovery_repairs_modes_without_full_recover(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    root_env.chmod(0o664)
    calls = 0

    def _local_recovery_status(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "status": "fail",
                "missing_artifact_count": 0,
                "different_hash_count": 0,
                "wrong_mode_count": 1,
                "wrong_modes": [{"path": str(root_env), "mode": "0o664"}],
            }
        return {
            "status": "pass",
            "expected_rows": 1,
            "same_hash": 1,
            "missing_artifact_count": 0,
            "different_hash_count": 0,
            "wrong_mode_count": 0,
            "wrong_modes": [],
        }

    monkeypatch.setattr(module, "local_recovery_status", _local_recovery_status)

    def _recover_from_teable(**_):
        raise AssertionError("mode-only drift should not trigger full recovery")

    monkeypatch.setattr(module, "recover_from_teable", _recover_from_teable)

    result = module.ensure_local_recovery(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        local_env_path=local_env,
        service_env_path=service_env,
    )

    assert result["status"] == "ensured"
    assert result["recovered"] is False
    assert result["mode_repairs"] == 1
    assert (root_env.stat().st_mode & 0o777) == 0o600


def test_recover_from_teable_combines_bootstrap_and_verification(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    service_env = tmp_path / "ea" / ".env"
    observed: dict[str, object] = {}

    def _bootstrap_env_files(**kwargs):
        observed.update(kwargs)
        return {
            "root_env_path": str(root_env),
            "root_restored": 1,
            "root_hash_verified": 1,
            "root_hash_mismatch_keys": [],
            "service_env_path": str(service_env),
            "service_restored": 1,
            "service_hash_verified": 1,
            "service_hash_mismatch_keys": [],
            "referenced_files_restored": 0,
            "referenced_file_hash_verified": 0,
            "referenced_file_hash_mismatch_paths": [],
        }

    monkeypatch.setattr(module, "bootstrap_env_files", _bootstrap_env_files)
    monkeypatch.setattr(module, "verify_restored_outputs_from_table", lambda **_: {"status": "pass", "same_hash": 2})

    result = module.recover_from_teable(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        service_env_path=service_env,
        host_profile="ea-prod",
    )

    assert result["status"] == "recovered"
    assert result["bootstrap"]["root_restored"] == 1
    assert result["verification"]["status"] == "pass"
    assert observed["referenced_file_output_root"] == tmp_path


def test_recover_from_teable_returns_redacted_recovery_proof(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    secret_file = tmp_path / "config" / "onemin_api_keys.local.json"
    service_env.parent.mkdir()
    secret_file.parent.mkdir()
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    local_env.write_text("ONEMIN_AI_API_KEY=local-token\n", encoding="utf-8")
    service_env.write_text("VOICEWAVE_LOGIN_PASSWORD=service-password\n", encoding="utf-8")
    secret_file.write_text("super-secret-provider-key\n", encoding="utf-8")
    for path in (root_env, local_env, service_env, secret_file):
        path.chmod(0o600)

    monkeypatch.setattr(
        module,
        "bootstrap_env_files",
        lambda **_: {
            "root_env_path": str(root_env),
            "root_restored": 1,
            "root_hash_verified": 1,
            "root_hash_mismatch_keys": [],
            "root_backup_path": str(tmp_path / ".env.bak"),
            "local_env_path": str(local_env),
            "local_restored": 1,
            "local_hash_verified": 1,
            "local_hash_mismatch_keys": [],
            "local_backup_path": "",
            "service_env_path": str(service_env),
            "service_restored": 1,
            "service_hash_verified": 1,
            "service_hash_mismatch_keys": [],
            "service_backup_path": "",
            "referenced_files_restored": 1,
            "referenced_file_hash_verified": 1,
            "referenced_file_hash_mismatch_paths": [],
            "referenced_file_backup_count": 0,
            "referenced_file_paths": [str(secret_file)],
        },
    )
    monkeypatch.setattr(
        module,
        "verify_restored_outputs_from_table",
        lambda **_: {
            "status": "pass",
            "expected_rows": 4,
            "same_hash": 4,
            "missing_count": 0,
            "different_hash_count": 0,
            "missing_secret_value_count": 0,
            "extra_restorable_count": 0,
        },
    )

    result = module.recover_from_teable(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=root_env,
        local_env_path=local_env,
        service_env_path=service_env,
        host_profile="ea-prod",
    )

    proof = result["recovery_proof"]
    assert proof["contract_name"] == "ea.teable_env_recovery_proof.v1"
    assert proof["status"] == "recovered"
    assert proof["table_id"] == "tbl_env"
    assert proof["host_profile"] == "ea-prod"
    assert proof["secret_values_redacted"] is True
    assert proof["verification"] == {
        "status": "pass",
        "expected_rows": 4,
        "same_hash": 4,
        "missing_count": 0,
        "different_hash_count": 0,
        "missing_secret_value_count": 0,
        "extra_restorable_count": 0,
    }
    assert {item["scope"]: item["mode"] for item in proof["env_files"]} == {
        "ea_root": "0o600",
        "ea_root_local": "0o600",
        "ea_service": "0o600",
    }
    assert proof["env_files"][0]["backup_created"] is True
    assert proof["referenced_files"]["path_count"] == 1
    assert proof["referenced_files"]["paths"] == [str(secret_file)]
    assert proof["referenced_files"]["modes"] == [{"path": str(secret_file), "mode": "0o600"}]
    assert "root-token" not in json.dumps(proof)
    assert "local-token" not in json.dumps(proof)
    assert "service-password" not in json.dumps(proof)
    assert "super-secret-provider-key" not in json.dumps(proof)


def test_recover_from_teable_keeps_live_referenced_file_paths_for_default_recovery(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    def _bootstrap_env_files(**kwargs):
        observed.update(kwargs)
        return {
            "root_restored": 1,
            "root_hash_verified": 1,
            "root_hash_mismatch_keys": [],
            "service_restored": 1,
            "service_hash_verified": 1,
            "service_hash_mismatch_keys": [],
            "referenced_files_restored": 1,
            "referenced_file_hash_verified": 1,
            "referenced_file_hash_mismatch_paths": [],
        }

    monkeypatch.setattr(module, "bootstrap_env_files", _bootstrap_env_files)
    monkeypatch.setattr(module, "verify_recovery_table", lambda **_: {"status": "pass"})

    result = module.recover_from_teable(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=ROOT / ".env",
        service_env_path=ROOT / "ea" / ".env",
        host_profile="ea-prod",
    )

    assert result["status"] == "recovered"
    assert observed["referenced_file_output_root"] is None


def test_recover_from_teable_fails_when_post_restore_verification_fails(monkeypatch, tmp_path: Path) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "bootstrap_env_files",
        lambda **_: {
            "root_restored": 1,
            "root_hash_verified": 1,
            "root_hash_mismatch_keys": [],
            "service_restored": 1,
            "service_hash_verified": 1,
            "service_hash_mismatch_keys": [],
            "referenced_files_restored": 0,
            "referenced_file_hash_verified": 0,
            "referenced_file_hash_mismatch_paths": [],
        },
    )
    monkeypatch.setattr(module, "verify_restored_outputs_from_table", lambda **_: {"status": "fail", "missing_count": 1})

    result = module.recover_from_teable(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=tmp_path / ".env",
        service_env_path=tmp_path / "ea" / ".env",
        host_profile="ea-prod",
    )

    assert result["status"] == "failed"
    assert result["verification"]["missing_count"] == 1


def test_recover_from_teable_fails_when_post_write_hash_verification_fails(monkeypatch, tmp_path: Path) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "bootstrap_env_files",
        lambda **_: {
            "root_restored": 1,
            "root_hash_verified": 0,
            "root_hash_mismatch_keys": ["ea_root:EA_API_TOKEN"],
            "service_restored": 1,
            "service_hash_verified": 1,
            "service_hash_mismatch_keys": [],
            "referenced_files_restored": 0,
            "referenced_file_hash_verified": 0,
            "referenced_file_hash_mismatch_paths": [],
        },
    )
    monkeypatch.setattr(module, "verify_restored_outputs_from_table", lambda **_: {"status": "pass"})

    result = module.recover_from_teable(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        root_env_path=tmp_path / ".env",
        service_env_path=tmp_path / "ea" / ".env",
        host_profile="ea-prod",
    )

    assert result["status"] == "failed"
    assert result["bootstrap"]["root_hash_mismatch_keys"] == ["ea_root:EA_API_TOKEN"]


def test_sync_rows_upserts_existing_and_creates_missing(monkeypatch) -> None:
    module = _module()
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def _fake_existing_record_snapshots(*, base_url: str, api_key: str, table_id: str, key_field: str = "projection_id"):
        return {"host:ea_root:EXISTING_SECRET": {"record_id": "rec_existing", "value_sha256": "old"}}

    def _fake_teable_request(*, method: str, url: str, api_key: str, body=None):
        calls.append((method, url, body))
        if method == "POST":
            return {"records": [{"id": "rec_new"}]}
        return {}

    monkeypatch.setattr(module, "_existing_record_snapshots", _fake_existing_record_snapshots)
    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    result = module.sync_rows(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        rows=[
            {"projection_id": "host:ea_root:EXISTING_SECRET", "env_name": "EXISTING_SECRET", "value_sha256": "new"},
            {"projection_id": "host:ea_root:NEW_SECRET", "env_name": "NEW_SECRET", "value_sha256": "new"},
        ],
    )

    assert result == {"created": 1, "updated": 1, "skipped": 0, "total": 2}
    assert calls[0][0] == "PATCH"
    assert "/record/rec_existing" in calls[0][1]
    assert calls[1][0] == "POST"
    assert json.loads(json.dumps(calls[1][2]))["records"][0]["fields"]["env_name"] == "NEW_SECRET"


def test_sync_rows_skips_existing_secret_when_metadata_only(monkeypatch) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        module,
        "_existing_record_snapshots",
        lambda **_: {
            "host:ea_root:EMAILIT_API_KEY": {
                "record_id": "rec_existing",
                "value_sha256": "old",
                "stored_secret_hash": "old",
            }
        },
    )

    def _fake_teable_request(*, method: str, url: str, api_key: str, body=None):
        calls.append(dict(body or {}))
        return {}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    result = module.sync_rows(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        rows=[
            {
                "projection_id": "host:ea_root:EMAILIT_API_KEY",
                "env_name": "EMAILIT_API_KEY",
                "env_value_secret": "",
                "value_sha256": "new",
            }
        ],
        preserve_blank_secret_values=True,
    )

    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert calls == []


def test_verify_recovery_table_reports_hash_match_without_values(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    expected = module.build_env_secret_rows(env_files=(env_file,), include_values=True, host_profile="test-host")
    expected_hash = str(expected[0]["value_sha256"])

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "test-host:ea_service:EA_API_TOKEN",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "value_sha256": expected_hash,
                "env_value_secret": "root-token",
            },
            {
                "projection_id": "other-host:ea_root:OTHER_API_KEY",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "OTHER_API_KEY",
                "value_sha256": "other",
                "env_value_secret": "other-token",
            },
            {
                "projection_id": "test-host:ea_root:STALE_API_KEY",
                "source_scope": "ea_root",
                "restore_enabled": True,
                "env_name": "STALE_API_KEY",
                "value_sha256": "stale",
                "env_value_secret": "stale-token",
            },
            {
                "projection_id": "test-host:ea_root:DISABLED_STALE_API_KEY",
                "source_scope": "ea_root",
                "restore_enabled": "false",
                "env_name": "DISABLED_STALE_API_KEY",
                "value_sha256": "disabled-stale",
                "env_value_secret": "disabled-stale-token",
            }
        ],
    )

    result = module.verify_recovery_table(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        env_files=(env_file,),
        host_profile="test-host",
    )

    assert result["status"] == "fail"
    assert result["same_hash"] == 1
    assert result["missing_count"] == 0
    assert result["missing_secret_value_count"] == 0
    assert result["extra_restorable_count"] == 1
    assert result["extra_restorable_keys"] == ["ea_root:STALE_API_KEY"]
    assert result["root_restore_count"] == 1
    assert result["service_restore_count"] == 1
    assert "root-token" not in json.dumps(result)
    assert "other-token" not in json.dumps(result)
    assert "stale-token" not in json.dumps(result)


def test_verify_recovery_table_reports_missing_without_secret_values(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("EMAILIT_API_KEY=emailit-secret\n", encoding="utf-8")

    monkeypatch.setattr(module, "_list_records", lambda **_: [])

    result = module.verify_recovery_table(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        env_files=(env_file,),
        host_profile="test-host",
    )

    assert result["status"] == "fail"
    assert result["missing_count"] == 1
    assert result["missing_keys"] == ["ea_service:EMAILIT_API_KEY"]
    assert "emailit-secret" not in json.dumps(result)


def test_verify_recovery_table_fails_when_required_default_env_file_missing(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")

    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (root_env, local_env, service_env))
    monkeypatch.setattr(module, "REQUIRED_DEFAULT_ENV_FILES", (root_env, local_env))
    monkeypatch.setattr(module, "_list_records", lambda **_: [])

    result = module.verify_recovery_table(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        env_files=(root_env, local_env, service_env),
        host_profile="test-host",
    )

    assert result["status"] == "fail"
    assert result["missing_required_env_file_count"] == 1
    assert result["missing_required_env_files"] == [str(local_env)]


def test_verify_recovery_table_fails_when_secret_value_cell_is_blank(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("EMAILIT_API_KEY=emailit-secret\n", encoding="utf-8")
    expected = module.build_env_secret_rows(env_files=(env_file,), include_values=True, host_profile="test-host")

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "test-host:ea_service:EMAILIT_API_KEY",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "EMAILIT_API_KEY",
                "value_sha256": str(expected[0]["value_sha256"]),
                "env_value_secret": "",
            }
        ],
    )

    result = module.verify_recovery_table(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        env_files=(env_file,),
        host_profile="test-host",
    )

    assert result["status"] == "fail"
    assert result["missing_secret_value_count"] == 1
    assert result["missing_secret_value_keys"] == ["ea_service:EMAILIT_API_KEY"]
    assert "emailit-secret" not in json.dumps(result)


def test_disable_extra_restorable_rows_turns_off_only_same_profile_stale_rows(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "projection_id": "ea-prod:ea_service:EA_API_TOKEN",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "root-token",
            },
            {
                "projection_id": "ea-prod:ea_service:STALE_API_KEY",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "STALE_API_KEY",
                "env_value_secret": "stale-token",
            },
            {
                "projection_id": "ea-local:ea_service:LOCAL_STALE_API_KEY",
                "source_scope": "ea_service",
                "restore_enabled": True,
                "env_name": "LOCAL_STALE_API_KEY",
                "env_value_secret": "local-stale-token",
            },
        ],
    )
    monkeypatch.setattr(
        module,
        "_existing_record_snapshots",
        lambda **_: {
            "ea-prod:ea_service:EA_API_TOKEN": {"record_id": "rec_current"},
            "ea-prod:ea_service:STALE_API_KEY": {"record_id": "rec_stale"},
            "ea-local:ea_service:LOCAL_STALE_API_KEY": {"record_id": "rec_local_stale"},
        },
    )

    def _teable_request(*, method: str, url: str, api_key: str, body=None):
        calls.append({"method": method, "url": url, "body": body})
        return {}

    monkeypatch.setattr(module, "_teable_request", _teable_request)

    result = module.disable_extra_restorable_rows(
        base_url="https://teable.example",
        api_key="teable-key",
        table_id="tbl_env",
        env_files=(env_file,),
        host_profile="ea-prod",
    )

    assert result["disabled_count"] == 1
    assert result["disabled_keys"] == ["ea_service:STALE_API_KEY"]
    assert len(calls) == 1
    assert "/record/rec_stale" in str(calls[0]["url"])
    fields = calls[0]["body"]["record"]["fields"]
    assert fields["restore_enabled"] is False
    assert fields["notes"] == "disabled_stale_not_in_current_env"


def test_disable_extra_restorable_rows_refuses_when_required_default_env_file_missing(
    monkeypatch, tmp_path: Path
) -> None:
    module = _module()
    root_env = tmp_path / ".env"
    local_env = tmp_path / ".env.local"
    service_env = tmp_path / "ea" / ".env"
    root_env.write_text("EA_API_TOKEN=root-token\n", encoding="utf-8")
    disable_called = False

    monkeypatch.setattr(module, "DEFAULT_ENV_FILES", (root_env, local_env, service_env))
    monkeypatch.setattr(module, "REQUIRED_DEFAULT_ENV_FILES", (root_env, local_env))

    def _teable_request(**_):
        nonlocal disable_called
        disable_called = True
        return {}

    monkeypatch.setattr(module, "_teable_request", _teable_request)

    try:
        module.disable_extra_restorable_rows(
            base_url="https://teable.example",
            api_key="teable-key",
            table_id="tbl_env",
            env_files=(root_env, local_env, service_env),
            host_profile="ea-prod",
        )
    except SystemExit as exc:
        assert str(exc).startswith("teable_disable_extras_env_file_audit_failed:")
        assert str(local_env) in str(exc)
    else:
        raise AssertionError("expected disable-extras to refuse missing required env files")

    assert disable_called is False


def test_discover_table_id_finds_named_table_across_spaces(monkeypatch) -> None:
    module = _module()

    def _fake_teable_request(*, method: str, url: str, api_key: str, body=None):
        if url.endswith("/api/space"):
            return [{"id": "spc_1"}, {"id": "spc_2"}]
        if url.endswith("/api/space/spc_1/base"):
            return [{"id": "bse_1"}]
        if url.endswith("/api/space/spc_2/base"):
            return [{"id": "bse_2"}]
        if url.endswith("/api/base/bse_1/table"):
            return [{"id": "tbl_other", "name": "other"}]
        if url.endswith("/api/base/bse_2/table"):
            return [{"id": "tbl_env", "name": "ea_environment_secrets_recovery"}]
        return {}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    assert (
        module.discover_table_id(
            base_url="https://teable.example",
            api_key="teable-key",
            table_name="ea_environment_secrets_recovery",
        )
        == "tbl_env"
    )


def test_main_backup_requires_explicit_value_mode(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("TEABLE_API_KEY=key\n", encoding="utf-8")
    sync_called = False

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "backup",
                "base_url": "https://teable.example",
                "api_key": "teable-key",
                "base_id": "",
                "table_id": "tbl_env",
                "table_name": "ea_environment_secrets_recovery",
                "create_table": False,
                "include_values": False,
                "metadata_only": False,
                "secrets_only": False,
                "no_referenced_files": False,
                "no_history_backup": True,
                "host_profile": "ea-prod",
                "env_file": [str(env_file)],
                "require_seeded_api_key": False,
            },
        )(),
    )

    def _sync_rows(**_):
        nonlocal sync_called
        sync_called = True
        return {}

    monkeypatch.setattr(module, "sync_rows", _sync_rows)

    try:
        module.main()
    except SystemExit as exc:
        assert str(exc) == "teable_backup_requires_include_values_or_metadata_only"
    else:
        raise AssertionError("expected backup mode guard to fail")

    assert sync_called is False


def test_main_backup_metadata_only_is_explicit_and_preserves_secret_values(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("TEABLE_API_KEY=key\n", encoding="utf-8")
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "backup",
                "base_url": "https://teable.example",
                "api_key": "teable-key",
                "base_id": "",
                "table_id": "tbl_env",
                "table_name": "ea_environment_secrets_recovery",
                "create_table": False,
                "include_values": False,
                "metadata_only": True,
                "secrets_only": False,
                "no_referenced_files": False,
                "no_history_backup": True,
                "host_profile": "ea-prod",
                "env_file": [str(env_file)],
                "require_seeded_api_key": False,
            },
        )(),
    )

    def _sync_rows(**kwargs):
        observed.update(kwargs)
        return {"created": 0, "updated": 0, "skipped": 1, "total": 1}

    monkeypatch.setattr(module, "sync_rows", _sync_rows)

    assert module.main() == 0
    assert observed["preserve_blank_secret_values"] is True
    row = observed["rows"][0]
    assert row["env_value_secret"] == ""


def test_main_backup_with_relative_env_paths_uses_normalized_repo_root_paths(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("TEABLE_API_KEY=key\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("EA_API_TOKEN=token\n", encoding="utf-8")
    (tmp_path / "ea").mkdir()
    (tmp_path / "ea" / ".env").write_text("EA_HOST_PORT=8000\n", encoding="utf-8")

    observed: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "backup",
                "base_url": "https://teable.example",
                "api_key": "teable-key",
                "base_id": "",
                "table_id": "tbl_env",
                "table_name": "ea_environment_secrets_recovery",
                "create_table": False,
                "include_values": False,
                "metadata_only": True,
                "secrets_only": False,
                "no_referenced_files": False,
                "no_history_backup": True,
                "host_profile": "ea-prod",
                "env_file": [".env", ".env.local", "ea/.env"],
                "require_seeded_api_key": False,
            },
        )(),
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)

    def _sync_rows(**kwargs):
        observed.update(kwargs)
        return {"created": 0, "updated": 0, "skipped": 1, "total": 1}

    monkeypatch.setattr(module, "sync_rows", _sync_rows)

    def _build_recovery_rows(**kwargs):
        observed["env_files"] = tuple(kwargs["env_files"])
        return [
            {
                "env_name": "EA_API_TOKEN",
                "env_value_secret": "",
                "projection_id": "ea-prod:ea_root_local:EA_API_TOKEN",
                "value_sha256": "",
                "value_length": 0,
                "source_scope": "ea_root_local",
            }
        ]

    monkeypatch.setattr(module, "build_recovery_rows", _build_recovery_rows)

    assert module.main() == 0
    expected_env_files = (
        tmp_path / ".env",
        tmp_path / ".env.local",
        tmp_path / "ea" / ".env",
    )
    assert observed["env_files"] == expected_env_files


def test_build_history_rows_preserves_source_fields_json_secret() -> None:
    module = _module()

    rows = module.build_history_rows(
        records=[
            {
                "id": "rec_1",
                "fields": {
                    "projection_id": "ea-prod:ea_root:TEABLE_API_KEY",
                    "env_name": "TEABLE_API_KEY",
                    "env_value_secret": "secret-value",
                    "value_sha256": "a" * 64,
                    "custom_future_field": "kept",
                },
            }
        ],
        source_table_id="tbl_env",
        source_table_name="ea_environment_secrets_recovery",
        history_reason="unit_snapshot",
        host_profile="ea-prod",
        recorded_at="2026-06-29T12:00:00Z",
        batch_id="batch-1",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["history_id"].startswith("batch-1:")
    assert row["history_source_record_id"] == "rec_1"
    assert row["history_reason"] == "unit_snapshot"
    assert row["env_value_secret"] == "secret-value"
    assert "secret-value" not in str(row["history_id"])
    source_fields = json.loads(str(row["source_fields_json_secret"]))
    assert source_fields["env_value_secret"] == "secret-value"
    assert source_fields["custom_future_field"] == "kept"


def test_ensure_history_table_id_creates_missing_history_table(monkeypatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    monkeypatch.setattr(module, "discover_table_id", lambda **_: "")

    def _create_history_table(**kwargs):
        observed.update(kwargs)
        return "tbl_history"

    monkeypatch.setattr(module, "create_history_table", _create_history_table)

    assert (
        module.ensure_history_table_id(
            base_url="https://teable.example",
            api_key="teable-key",
            base_id="bse_env",
            history_table_id="",
            history_table_name="ea_environment_secrets_recovery_history",
        )
        == "tbl_history"
    )
    assert observed["base_id"] == "bse_env"
    assert observed["table_name"] == "ea_environment_secrets_recovery_history"


def test_main_backup_writes_pre_and_post_history_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("TEABLE_API_KEY=key\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "backup",
                "base_url": "https://teable.example",
                "api_key": "teable-key",
                "base_id": "bse_env",
                "table_id": "tbl_env",
                "table_name": "ea_environment_secrets_recovery",
                "history_table_id": "",
                "history_table_name": "ea_environment_secrets_recovery_history",
                "create_table": False,
                "create_history_table": True,
                "include_values": True,
                "metadata_only": False,
                "secrets_only": False,
                "no_referenced_files": False,
                "no_history_backup": False,
                "history_reason": "",
                "host_profile": "ea-prod",
                "env_file": [str(env_file)],
                "require_seeded_api_key": False,
            },
        )(),
    )
    monkeypatch.setattr(module, "ensure_history_table_id", lambda **_: "tbl_history")

    def _write_history_backup(**kwargs):
        calls.append(f"history:{kwargs['history_reason']}")
        return {
            "created": 1,
            "total": 1,
            "history_reason": kwargs["history_reason"],
        }

    def _sync_rows(**kwargs):
        calls.append("sync")
        return {"created": 1, "updated": 0, "skipped": 0, "total": len(kwargs["rows"])}

    monkeypatch.setattr(module, "write_history_backup", _write_history_backup)
    monkeypatch.setattr(module, "sync_rows", _sync_rows)

    assert module.main() == 0
    assert calls == ["history:pre_backup_snapshot", "sync", "history:post_backup_snapshot"]
    output = json.loads(capsys.readouterr().out)
    assert output["history_backup"]["enabled"] is True
    assert output["history_backup"]["history_table_id"] == "tbl_history"
    assert output["history_backup"]["pre_snapshot"]["total"] == 1
    assert output["history_backup"]["post_snapshot"]["total"] == 1
    assert output["history_backup"]["secret_values_redacted"] is True


def test_main_history_backup_command_snapshots_current_table(monkeypatch, capsys) -> None:
    module = _module()
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "history-backup",
                "base_url": "https://teable.example",
                "api_key": "teable-key",
                "base_id": "bse_env",
                "table_id": "tbl_env",
                "table_name": "ea_environment_secrets_recovery",
                "history_table_id": "tbl_history",
                "history_table_name": "ea_environment_secrets_recovery_history",
                "create_table": False,
                "create_history_table": True,
                "include_values": False,
                "metadata_only": False,
                "secrets_only": False,
                "no_referenced_files": False,
                "no_history_backup": False,
                "history_reason": "",
                "host_profile": "ea-prod",
                "env_file": [],
                "require_seeded_api_key": False,
            },
        )(),
    )
    monkeypatch.setattr(module, "ensure_history_table_id", lambda **_: "tbl_history")

    def _write_history_backup(**kwargs):
        observed.update(kwargs)
        return {
            "status": "history_snapshot_written",
            "created": 2,
            "total": 2,
            "history_table_id": kwargs["history_table_id"],
            "history_reason": kwargs["history_reason"],
            "secret_values_redacted": True,
        }

    monkeypatch.setattr(module, "write_history_backup", _write_history_backup)

    assert module.main() == 0
    assert observed["source_table_id"] == "tbl_env"
    assert observed["history_table_id"] == "tbl_history"
    assert observed["history_reason"] == "manual_history_snapshot"
    output = json.loads(capsys.readouterr().out)
    assert output["created"] == 2
    assert output["secret_values_redacted"] is True


def test_main_recover_discovers_table_without_seeded_table_id(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_output = tmp_path / ".env"
    service_output = tmp_path / "ea" / ".env"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "recover",
                "base_url": "https://teable.example",
                "api_key": "teable-key",
                "base_id": "",
                "table_id": "",
                "table_name": "ea_environment_secrets_recovery",
                "create_table": False,
                "include_values": False,
                "metadata_only": False,
                "secrets_only": False,
                "no_referenced_files": False,
                "host_profile": "ea-prod",
                "env_file": [],
                "root_output_path": str(root_output),
                "local_output_path": str(tmp_path / ".env.local"),
                "service_output_path": str(service_output),
                "no_backup_existing": True,
                "drill_output_dir": "",
                "output_path": str(root_output),
                "source_scope": "ea_root",
                "require_seeded_api_key": False,
            },
        )(),
    )
    monkeypatch.setattr(
        module,
        "discover_table_id",
        lambda *, base_url, api_key, table_name: "tbl_discovered",
    )

    def _recover_from_teable(**kwargs):
        observed.update(kwargs)
        return {"status": "recovered", "bootstrap": {}, "verification": {"status": "pass"}}

    monkeypatch.setattr(module, "recover_from_teable", _recover_from_teable)

    assert module.main() == 0
    assert observed["table_id"] == "tbl_discovered"
    assert observed["api_key"] == "teable-key"
    assert observed["root_env_path"] == root_output
    assert observed["local_env_path"] == tmp_path / ".env.local"
    assert observed["service_env_path"] == service_output


def test_main_fresh_host_recover_requires_shell_seeded_teable_key(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    root_output = tmp_path / ".env"
    service_output = tmp_path / "ea" / ".env"

    monkeypatch.delenv("TEABLE_API_KEY", raising=False)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "command": "recover",
                "base_url": "https://teable.example",
                "api_key": "teable-key-from-dotenv",
                "base_id": "",
                "table_id": "",
                "table_name": "ea_environment_secrets_recovery",
                "create_table": False,
                "include_values": False,
                "metadata_only": False,
                "secrets_only": False,
                "no_referenced_files": False,
                "host_profile": "ea-prod",
                "env_file": [],
                "root_output_path": str(root_output),
                "local_output_path": str(tmp_path / ".env.local"),
                "service_output_path": str(service_output),
                "no_backup_existing": True,
                "drill_output_dir": "",
                "output_path": str(root_output),
                "source_scope": "ea_root",
                "require_seeded_api_key": True,
            },
        )(),
    )

    try:
        module.main()
    except SystemExit as exc:
        assert str(exc) == "teable_seeded_api_key_required"
    else:
        raise AssertionError("expected seeded API key guard to fail")


def test_parse_args_fresh_host_uses_seeded_teable_key_and_defaults(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_dotenv_value",
        lambda name: str(os.environ.get(name) or "").strip(),
    )
    monkeypatch.setenv("TEABLE_API_KEY", "seeded-teable-key")
    monkeypatch.delenv("EA_ENV_TEABLE_TABLE_ID", raising=False)
    monkeypatch.delenv("EA_ENV_TEABLE_TABLE_NAME", raising=False)
    monkeypatch.delenv("EA_ENV_TEABLE_HOST_PROFILE", raising=False)
    monkeypatch.setattr("sys.argv", ["sync_env_to_teable.py", "recover"])

    args = module.parse_args()

    assert args.api_key == "seeded-teable-key"
    assert args.table_id == ""
    assert args.table_name == module.DEFAULT_TABLE_NAME
    assert args.host_profile == "ea-prod"
    assert args.base_url == module.DEFAULT_BASE_URL
    assert args.require_seeded_api_key is False


def test_bootstrap_script_is_directly_executable_for_fresh_host_recovery() -> None:
    assert SCRIPT_PATH.is_file()
    assert os.access(SCRIPT_PATH, os.X_OK)
    assert BOOTSTRAP_SCRIPT_PATH.is_file()
    assert os.access(BOOTSTRAP_SCRIPT_PATH, os.X_OK)
    result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert "scripts/bootstrap_from_teable.sh --check" in result.stdout
    assert "scripts/bootstrap_from_teable.sh --drill" in result.stdout
    assert "scripts/bootstrap_from_teable.sh --ensure-local" in result.stdout
    assert "scripts/bootstrap_from_teable.sh --fresh-host" in result.stdout
    assert "scripts/bootstrap_from_teable.sh --probe" in result.stdout
    bad_result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--not-a-real-mode"],
        check=False,
        env={**os.environ, "TEABLE_API_KEY": "dummy"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert bad_result.returncode == 2
    assert "Unknown argument" in bad_result.stderr


def test_bootstrap_script_fresh_host_requires_shell_seeded_teable_key(tmp_path: Path) -> None:
    recorder = tmp_path / "python-recorder.sh"
    log_path = tmp_path / "argv.json"
    recorder.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "python3 - \"$@\" <<'PY'",
                "import json, sys",
                f"open({str(log_path)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))",
                "print('{\"status\":\"recovered\"}')",
                "PY",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorder.chmod(0o755)

    missing_seed = subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--fresh-host"],
        check=False,
        env={key: value for key, value in os.environ.items() if key != "TEABLE_API_KEY"} | {"PYTHON_BIN": str(recorder)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert missing_seed.returncode == 2
    assert "TEABLE_API_KEY must be seeded" in missing_seed.stderr

    result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--fresh-host"],
        check=True,
        env={**os.environ, "TEABLE_API_KEY": "dummy", "PYTHON_BIN": str(recorder)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    argv = json.loads(log_path.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert argv[1] == "recover"
    assert "--require-seeded-api-key" in argv
    assert argv[argv.index("--table-id") + 1] == ""


def test_deploy_help_describes_teable_env_config_recovery() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts" / "deploy.sh"), "--help"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "Verify and recover EA env/config artifacts from Teable before deploy." in result.stdout


def test_bootstrap_script_probe_recovers_to_throwaway_dir(tmp_path: Path) -> None:
    recorder = tmp_path / "python-recorder.sh"
    log_path = tmp_path / "argv.json"
    recorder.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "python3 - \"$@\" <<'PY'",
                "import json, sys",
                f"open({str(log_path)!r}, 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))",
                "print('{\"status\":\"recovered\"}')",
                "PY",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorder.chmod(0o755)

    result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--probe"],
        check=True,
        env={**os.environ, "TEABLE_API_KEY": "dummy", "PYTHON_BIN": str(recorder)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    argv = json.loads(log_path.read_text(encoding="utf-8"))
    root_index = argv.index("--root-output-path") + 1
    local_index = argv.index("--local-output-path") + 1
    service_index = argv.index("--service-output-path") + 1
    root_output = Path(argv[root_index])
    local_output = Path(argv[local_index])
    service_output = Path(argv[service_index])
    assert argv[1] == "recover"
    assert "--require-seeded-api-key" in argv
    assert argv[argv.index("--table-id") + 1] == ""
    assert "--no-backup-existing" in argv
    assert root_output.name == ".env"
    assert local_output == root_output.parent / ".env.local"
    assert service_output == root_output.parent / "ea" / ".env"
    assert not root_output.parent.exists()
    assert '"status":"recovered"' in result.stdout


def test_bootstrap_script_probe_requires_shell_seeded_teable_key(tmp_path: Path) -> None:
    recorder = tmp_path / "python-recorder.sh"
    recorder.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    recorder.chmod(0o755)

    result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--probe"],
        check=False,
        env={key: value for key, value in os.environ.items() if key != "TEABLE_API_KEY"} | {"PYTHON_BIN": str(recorder)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 2
    assert "TEABLE_API_KEY must be seeded" in result.stderr


def test_bootstrap_script_ensure_local_checks_before_recovering(tmp_path: Path) -> None:
    recorder = tmp_path / "python-recorder.sh"
    log_path = tmp_path / "argv.jsonl"
    recorder.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "printf '%s\\n' \"$*\" >> " + repr(str(log_path)),
                "printenv TEABLE_API_KEY >/dev/null",
                "printf '{\"status\":\"ensured\"}\\n'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorder.chmod(0o755)

    subprocess.run(
        [str(BOOTSTRAP_SCRIPT_PATH), "--ensure-local"],
        check=True,
        env={**os.environ, "TEABLE_API_KEY": "dummy", "PYTHON_BIN": str(recorder)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1
    assert " ensure-local" in calls[0]


def test_makefile_exposes_teable_probe_operator_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "env-probe-teable" in makefile
    assert "env-ensure-local-teable:\n\t@scripts/bootstrap_from_teable.sh --ensure-local" in makefile
    assert "env-fresh-host-teable:\n\t@scripts/bootstrap_from_teable.sh --fresh-host" in makefile
    assert "env-local-status-teable:\n\t$(PYTHON_BIN) scripts/sync_env_to_teable.py local-status" in makefile
    assert "env-probe-teable:\n\t@scripts/bootstrap_from_teable.sh --probe" in makefile
    assert "env-recover-teable:\n\t@scripts/bootstrap_from_teable.sh" in makefile
    assert "env-restore-teable-local:\n\t$(PYTHON_BIN) scripts/sync_env_to_teable.py restore --output-path .env.local --source-scope ea_root_local" in makefile
    assert "scripts/bootstrap_from_teable.sh scripts/sync_env_to_teable.py" in makefile


def test_deploy_paths_recover_missing_env_from_teable_before_template_fallback() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert '[[ -n "${TEABLE_API_KEY:-}" ]]' in deploy
    assert 'bash "${APP_ROOT}/scripts/bootstrap_from_teable.sh" --ensure-local >/dev/null' in deploy
    assert deploy.index('bash "${APP_ROOT}/scripts/bootstrap_from_teable.sh" --ensure-local >/dev/null') < deploy.index(
        'cp "${APP_ROOT}/.env.example" "${APP_ROOT}/.env"'
    )
    assert '[ -n "$${TEABLE_API_KEY:-}" ]' in makefile
    assert "scripts/bootstrap_from_teable.sh --ensure-local >/dev/null" in makefile
    assert makefile.index("scripts/bootstrap_from_teable.sh --ensure-local >/dev/null") < makefile.index(
        "cp .env.example .env"
    )


def test_gitignore_covers_teable_recovery_secret_backups() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".env.*" in gitignore
    assert "config/*.local.json.*.bak" in gitignore
    assert "config/*api_keys*.json.*.bak" in gitignore
    assert "config/*accounts*.json.*.bak" in gitignore
    assert "config/*slot_owners*.json.*.bak" in gitignore
    assert "config/*client_secret*.json.*.bak" in gitignore
    assert "config/*oauth*secret*.json.*.bak" in gitignore
    assert "config/audiobook_*.*.bak" in gitignore
    assert "config/whatsapp_audiobook_*.*.bak" in gitignore
    assert "config/*credential*.json.*.bak" in gitignore
    assert "config/*secret*.json.*.bak" in gitignore
