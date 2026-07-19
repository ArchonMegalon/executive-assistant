from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess

import pytest

from scripts import verify_audiobook_runtime_production_stage as production
from scripts import vexp_schema_v6_authority as schema_v6


UTC = timezone.utc
REVISION = "a" * 40
MEMORIAL_REVISION = "9" * 40
IMAGE = "registry.example/ea/runtime@sha256:" + "b" * 64
IMAGE_ID = "sha256:" + "c" * 64
PROVENANCE_SHA256 = "e" * 64
SBOM_SHA256 = "f" * 64
MEMORIAL_RECEIPT_SHA256 = "7" * 64
NOW = datetime(2026, 7, 26, 3, 0, tzinfo=UTC)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _source_inventory(paths: tuple[Path, ...]) -> tuple[list[dict[str, str]], str]:
    entries = [
        {
            "path": path.as_posix(),
            "blob_sha256": f"{index + 1:x}" * 64,
            "working_sha256": f"{index + 1:x}" * 64,
        }
        for index, path in enumerate(paths)
    ]
    return entries, _canonical_sha256(entries)


def _qualification() -> schema_v6.QualificationEvidence:
    return schema_v6.QualificationEvidence(
        state_sha256="1" * 64,
        terminal_identity_sha256="2" * 64,
        qualified_at="2026-07-26T02:04:00Z",
        permit_contract_name=schema_v6.PERMIT_CONTRACT_NAME,
        permit_sha256="3" * 64,
        permit_expires_at="2026-07-26T03:30:00Z",
    )


def _baseline() -> dict[str, object]:
    services: dict[str, object] = {
        service: {"image": f"registry.example/ea/{service}@sha256:" + "8" * 64}
        for service in production.EXPECTED_SERVICE_NAMES
    }
    services["ea-api"] = {
        "image": "registry.example/ea/memorial@sha256:" + "9" * 64,
        "environment": {
            "PRIVATE_SENTINEL": "do-not-emit",
            "EA_SOURCE_REVISION": MEMORIAL_REVISION,
        },
        "labels": {"owner": "memorial"},
    }
    services["ea-worker"] = {
        "image": "ea-runtime:latest",
        "command": ["python", "-m", "app.runner"],
    }
    services["ea-scheduler"] = {
        "image": "ea-runtime:latest",
        "command": ["python", "-m", "app.runner"],
    }
    services["ea-whatsapp-web-action-processor"] = {
        "image": "ea-runtime:latest",
        "command": ["python", "unsafe.py"],
    }
    return {
        "name": "ea",
        "services": services,
        "networks": {"default": {"name": "ea_default"}},
        "volumes": {"ea_pgdata": {"name": "ea_pgdata"}},
    }


def _stage_service(service: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "image": IMAGE,
        "pull_policy": "never",
        "deploy": {"placement": {}, "replicas": 0, "resources": {}},
        "restart": "no",
        "environment": production._expected_environment(service, REVISION),
        "labels": production._expected_labels(REVISION),
        "command": list(production.IDLE_COMMAND),
        "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
        "working_dir": "/app",
        "user": "10001:10001",
        "cap_drop": ["ALL"],
        "read_only": True,
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp", "/run"],
        "healthcheck": {"disable": True},
        "networks": {"default": None},
        "container_name": service,
        **production.EXPECTED_STAGE_RESOURCES[service],
    }
    assert set(payload) == production.EXPECTED_STAGE_SERVICE_KEYS[service]
    return payload


def _staged() -> dict[str, object]:
    payload = copy.deepcopy(_baseline())
    payload["x-audiobook-production-stage"] = copy.deepcopy(
        production.EXPECTED_EXTENSION
    )
    payload["x-audiobook-production-stage-service"] = (
        production._expected_stage_anchor(REVISION, IMAGE)
    )
    services = payload["services"]
    assert isinstance(services, dict)
    for service in production.STAGE_MUTATION_SERVICES:
        services[service] = _stage_service(service)
    return payload


def _sbom() -> dict[str, object]:
    properties = [
        {"name": "ea:document-namespace", "value": "urn:ea:sbom:audiobook-runtime"},
        {"name": "ea:image-reference", "value": IMAGE},
        {"name": "ea:image-id", "value": IMAGE_ID},
        {"name": "ea:source-revision", "value": REVISION},
    ]
    return {
        "contract_name": production.SBOM_CONTRACT,
        "version": production.SBOM_VERSION,
        "status": "pass",
        "document_namespace": "urn:ea:sbom:audiobook-runtime",
        "serial_number": "urn:uuid:11111111-2222-3333-4444-555555555555",
        "subject_name": production.SBOM_SUBJECT_NAME,
        "subject_image_reference": IMAGE,
        "subject_image_id": IMAGE_ID,
        "subject_source_revision": REVISION,
        "bom": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "serialNumber": "urn:uuid:11111111-2222-3333-4444-555555555555",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "application",
                    "name": production.SBOM_SUBJECT_NAME,
                    "properties": properties,
                }
            },
            "components": [{"type": "library", "name": "runtime-dependency"}],
        },
    }


def _provenance() -> dict[str, object]:
    return {
        "contract_name": production.PROVENANCE_CONTRACT,
        "version": production.PROVENANCE_VERSION,
        "status": "pass",
        "source_revision": REVISION,
        "image_reference": IMAGE,
        "image_id": IMAGE_ID,
        "sbom_sha256": SBOM_SHA256,
    }


def _memorial_receipt(
    baseline: dict[str, object] | None = None,
) -> dict[str, object]:
    selected_baseline = baseline or _baseline()
    inventory, inventory_sha256 = _source_inventory(
        production.BASE_COMPOSE_SOURCE_PATHS
    )
    services = selected_baseline["services"]
    assert isinstance(services, dict)
    return {
        "contract_name": production.MEMORIAL_BASELINE_CONTRACT,
        "version": production.MEMORIAL_BASELINE_VERSION,
        "status": "pass",
        "issuer": production.MEMORIAL_BASELINE_ISSUER,
        "source_revision": MEMORIAL_REVISION,
        "compose_source_inventory": inventory,
        "compose_source_inventory_sha256": inventory_sha256,
        "rendered_compose_sha256": _canonical_sha256(selected_baseline),
        "ea_api_sha256": _canonical_sha256(services["ea-api"]),
        "issued_at": "2026-07-26T02:50:00Z",
        "expires_at": "2026-07-26T03:20:00Z",
    }


def _verify(
    *,
    baseline: dict[str, object] | None = None,
    staged: dict[str, object] | None = None,
    qualification: schema_v6.QualificationEvidence | None = None,
    memorial_receipt: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
    sbom: dict[str, object] | None = None,
    source_inventory: list[dict[str, str]] | None = None,
    source_inventory_sha256: str | None = None,
    expected_revision: str = REVISION,
    expected_image: str = IMAGE,
    expected_image_id: str = IMAGE_ID,
    source_commit: str | None = None,
    memorial_receipt_sha256: str = MEMORIAL_RECEIPT_SHA256,
    provenance_sha256: str = PROVENANCE_SHA256,
    sbom_sha256: str = SBOM_SHA256,
) -> dict[str, object]:
    selected_baseline = baseline or _baseline()
    selected_inventory, selected_inventory_sha256 = _source_inventory(
        production.COMPOSE_SOURCE_PATHS
    )
    if source_inventory is not None:
        selected_inventory = source_inventory
    if source_inventory_sha256 is not None:
        selected_inventory_sha256 = source_inventory_sha256
    return production.verify_audiobook_runtime_production_stage(
        selected_baseline,
        staged or _staged(),
        expected_revision=expected_revision,
        expected_image=expected_image,
        expected_image_id=expected_image_id,
        source_commit=source_commit if source_commit is not None else expected_revision,
        compose_source_inventory=selected_inventory,
        compose_source_inventory_sha256=selected_inventory_sha256,
        compose_version="2.27.1",
        memorial_baseline_receipt=(
            memorial_receipt
            if memorial_receipt is not None
            else _memorial_receipt(selected_baseline)
        ),
        memorial_baseline_receipt_sha256=memorial_receipt_sha256,
        provenance=provenance if provenance is not None else _provenance(),
        provenance_sha256=provenance_sha256,
        sbom=sbom if sbom is not None else _sbom(),
        sbom_sha256=sbom_sha256,
        qualification=qualification if qualification is not None else _qualification(),
        now=NOW,
    )


def test_prepared_projection_never_grants_authority() -> None:
    result = _verify()
    assert result["status"] == "prepared"
    assert result["issues"] == []
    assert result["preparation_valid"] is True
    assert result["non_transferable"] is True
    projection = result["production_projection"]
    assert isinstance(projection, dict)
    assert projection["status"] == "prepared"
    assert projection["configuration_only"] is True
    assert projection["stage_projection_sha256"]
    assert projection["required_owner_permit_contract"] == (
        production.REQUIRED_OWNER_PERMIT_CONTRACT
    )
    for payload in (result, projection):
        for field in (
            "deploy_ready",
            "stage_deploy_eligible",
            "stage_mutation_authority",
            "deployment_authority",
            "group_deploy_eligible",
            "runtime_activation_authority",
            "queue_mutation_authority",
            "provider_work_authority",
            "outbound_send_authority",
            "build_authority",
            "pull_authority",
        ):
            assert payload[field] is False


def test_projection_contract_keysets_are_exact() -> None:
    result = _verify()
    assert set(result) == {
        "contract_name",
        "version",
        "status",
        "verification_mode",
        "verified_at",
        "mutations_performed",
        "preparation_valid",
        "non_transferable",
        "deploy_ready",
        "deployment_scope",
        "stage_deploy_eligible",
        "stage_mutation_authority",
        "deployment_authority",
        "group_deploy_eligible",
        "runtime_activation_authority",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "build_authority",
        "pull_authority",
        "issues",
        "production_projection",
        "next_action",
    }
    projection = result["production_projection"]
    assert isinstance(projection, dict)
    assert set(projection) == {
        "contract_name",
        "version",
        "status",
        "configuration_only",
        "configuration_valid",
        "preparation_valid",
        "non_transferable",
        "deploy_ready",
        "deployment_scope",
        "stage_deploy_eligible",
        "stage_mutation_authority",
        "deployment_authority",
        "group_deploy_eligible",
        "runtime_activation_authority",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "build_authority",
        "pull_authority",
        "target_services",
        "stage_mutation_services",
        "preserved_services",
        "source_revision",
        "candidate_image_reference",
        "candidate_image_id",
        "compose_source_inventory",
        "compose_source_inventory_sha256",
        "overlay_path",
        "overlay_blob_sha256",
        "overlay_working_sha256",
        "rendered_compose_sha256",
        "memorial_baseline",
        "stage_projection_sha256",
        "provenance",
        "sbom",
        "live_api_owner",
        "live_api_mutation_authority",
        "owner_handoff_required",
        "owner_handoff_performed",
        "owner_preservation_permit_required",
        "required_owner_permit_contract",
        "silent_takeover_allowed",
        "memorial_compatible",
        "schema_v6_qualification",
        "side_effect_posture",
    }
    assert set(projection["memorial_baseline"]) == {
        "contract_name",
        "receipt_sha256",
        "source_revision",
        "compose_inventory_sha256",
        "rendered_compose_sha256",
        "ea_api_sha256",
    }
    assert set(projection["provenance"]) == {
        "contract_name",
        "sha256",
        "source_revision",
        "image_reference",
        "image_id",
    }
    assert set(projection["sbom"]) == {
        "contract_name",
        "sha256",
        "document_namespace",
        "serial_number",
        "subject_name",
        "subject_image_reference",
        "subject_image_id",
        "subject_source_revision",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network_mode", "host"),
        ("pid", "host"),
        ("ipc", "host"),
        ("userns_mode", "host"),
        ("post_start", [{"command": ["/bin/sh", "-ec", "echo unexpected"]}]),
        ("runtime", "runc"),
        ("logging", {"driver": "syslog"}),
        ("ports", ["127.0.0.1:9999:9999"]),
        ("volumes", ["/:/host:ro"]),
    ],
)
def test_unknown_or_host_control_stage_fields_fail_closed(
    field: str, value: object
) -> None:
    staged = _staged()
    staged["services"]["ea-worker"][field] = value
    result = _verify(staged=staged)
    assert result["status"] == "blocked"
    assert "compose:ea-worker:field_set_invalid" in result["issues"]
    assert result["stage_mutation_authority"] is False


def test_command_substring_injection_fails_closed() -> None:
    staged = _staged()
    staged["services"]["ea-worker"]["command"] = [
        "/bin/sh",
        "-ec",
        "echo side_effect; echo paused_stage_idle; while :; do sleep 3600; done",
    ]
    result = _verify(staged=staged)
    assert result["status"] == "blocked"
    assert "compose:ea-worker:idle_command_invalid" in result["issues"]


def test_document_and_service_inventories_are_exact_and_content_free() -> None:
    baseline = _baseline()
    staged = _staged()
    private_name = "/home/operator/private/bearer-token"
    baseline["services"][private_name] = {"image": "safe"}
    staged["services"][private_name] = {"image": "drifted"}
    staged["private-extension"] = {"secret": "do-not-emit"}
    receipt = _memorial_receipt(baseline)
    result = _verify(
        baseline=baseline,
        staged=staged,
        memorial_receipt=receipt,
    )
    serialized = json.dumps(result, sort_keys=True)
    assert result["status"] == "blocked"
    assert "compose:service_inventory_invalid" in result["issues"]
    assert "compose:staged_document_field_set_invalid" in result["issues"]
    assert private_name not in serialized
    assert "do-not-emit" not in serialized


def test_invalid_authority_and_evidence_fields_are_content_free() -> None:
    private_values = [
        f"/home/operator/private/bearer-token-{index}" for index in range(32)
    ]
    baseline = _baseline()
    staged = _staged()
    source_inventory, _ = _source_inventory(production.COMPOSE_SOURCE_PATHS)
    source_inventory[0] = {
        "path": private_values[0],
        "blob_sha256": private_values[1],
        "working_sha256": private_values[2],
    }
    memorial = _memorial_receipt(baseline)
    memorial.update(
        {
            "contract_name": private_values[3],
            "status": private_values[4],
            "issuer": private_values[5],
            "source_revision": private_values[6],
            "compose_source_inventory_sha256": private_values[7],
            "rendered_compose_sha256": private_values[8],
            "ea_api_sha256": private_values[9],
            "issued_at": private_values[10],
            "expires_at": private_values[11],
        }
    )
    memorial["compose_source_inventory"][0] = {
        "path": private_values[12],
        "blob_sha256": private_values[13],
        "working_sha256": private_values[14],
    }
    provenance = _provenance()
    provenance.update(
        {
            "contract_name": private_values[15],
            "status": private_values[16],
            "source_revision": private_values[17],
            "image_reference": private_values[18],
            "image_id": private_values[19],
            "sbom_sha256": private_values[20],
        }
    )
    sbom = _sbom()
    sbom.update(
        {
            "contract_name": private_values[21],
            "status": private_values[22],
            "document_namespace": private_values[23],
            "serial_number": private_values[24],
            "subject_name": private_values[25],
            "subject_image_reference": private_values[26],
            "subject_image_id": private_values[27],
            "subject_source_revision": private_values[28],
        }
    )
    sbom["bom"]["metadata"]["component"]["name"] = private_values[29]
    sbom["bom"]["components"][0]["name"] = private_values[30]
    invalid_qualification = schema_v6.QualificationEvidence(
        state_sha256=private_values[31],
        terminal_identity_sha256=private_values[31],
        qualified_at=private_values[31],
        permit_contract_name=private_values[31],
        permit_sha256=private_values[31],
        permit_expires_at=private_values[31],
    )
    result = _verify(
        baseline=baseline,
        staged=staged,
        qualification=invalid_qualification,
        memorial_receipt=memorial,
        provenance=provenance,
        sbom=sbom,
        source_inventory=source_inventory,
        source_inventory_sha256=private_values[1],
        expected_revision=private_values[2],
        expected_image=private_values[3],
        expected_image_id=private_values[4],
        source_commit=private_values[5],
        memorial_receipt_sha256=private_values[6],
        provenance_sha256=private_values[7],
        sbom_sha256=private_values[8],
    )
    serialized = json.dumps(result, sort_keys=True)
    assert result["status"] == "blocked"
    for private_value in private_values:
        assert private_value not in serialized


def test_memorial_api_must_match_root_baseline_digest() -> None:
    staged = _staged()
    staged["services"]["ea-api"]["image"] = IMAGE
    result = _verify(staged=staged)
    assert result["status"] == "blocked"
    assert (
        "compose:ea-api:not_canonical_byte_equivalent_to_memorial_baseline"
        in result["issues"]
    )


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        (
            "rendered_compose_sha256",
            "0" * 64,
            "authority:memorial_baseline:render_digest_mismatch",
        ),
        (
            "ea_api_sha256",
            "0" * 64,
            "authority:memorial_baseline:ea_api_digest_mismatch",
        ),
        (
            "expires_at",
            "2026-07-26T02:59:59Z",
            "authority:memorial_baseline:not_current",
        ),
    ],
)
def test_memorial_baseline_receipt_is_exact_and_current(
    field: str, value: object, issue: str
) -> None:
    receipt = _memorial_receipt()
    receipt[field] = value
    result = _verify(memorial_receipt=receipt)
    assert result["status"] == "blocked"
    assert issue in result["issues"]


def test_memorial_baseline_inventory_is_exact() -> None:
    receipt = _memorial_receipt()
    receipt["compose_source_inventory"][1]["path"] = "docker-compose.prod.yml"
    receipt["compose_source_inventory_sha256"] = _canonical_sha256(
        receipt["compose_source_inventory"]
    )
    result = _verify(memorial_receipt=receipt)
    assert result["status"] == "blocked"
    assert "authority:memorial_baseline:entry_1_path_invalid" in result["issues"]


def test_provenance_requires_exact_image_and_sbom_linkage() -> None:
    provenance = _provenance()
    del provenance["image_reference"]
    provenance["sbom_sha256"] = "0" * 64
    result = _verify(provenance=provenance)
    assert result["status"] == "blocked"
    assert "evidence:provenance:schema_invalid" in result["issues"]
    assert "evidence:provenance:image_reference_mismatch" in result["issues"]
    assert "evidence:provenance:sbom_digest_mismatch" in result["issues"]


def test_sbom_requires_exact_subject_and_embedded_linkage() -> None:
    sbom = _sbom()
    sbom["subject_name"] = "unrelated-artifact"
    sbom["bom"]["metadata"]["component"]["properties"][1]["value"] = (
        "registry.example/unrelated@sha256:" + "0" * 64
    )
    result = _verify(sbom=sbom)
    assert result["status"] == "blocked"
    assert "evidence:sbom:subject_name_mismatch" in result["issues"]
    assert "evidence:sbom:subject_linkage_invalid" in result["issues"]


def test_duplicate_sbom_linkage_property_is_rejected() -> None:
    sbom = _sbom()
    properties = sbom["bom"]["metadata"]["component"]["properties"]
    properties.append(copy.deepcopy(properties[0]))
    result = _verify(sbom=sbom)
    assert result["status"] == "blocked"
    assert "evidence:sbom:subject_properties_invalid" in result["issues"]


def test_compose_source_inventory_is_exact() -> None:
    inventory, _ = _source_inventory(production.COMPOSE_SOURCE_PATHS)
    inventory[-1]["working_sha256"] = "0" * 64
    digest = _canonical_sha256(inventory)
    result = _verify(
        source_inventory=inventory,
        source_inventory_sha256=digest,
    )
    assert result["status"] == "blocked"
    assert "preflight:compose_source:entry_3_digest_invalid" in result["issues"]


def test_projection_digest_binds_exact_valid_source_inventory() -> None:
    first = _verify()
    inventory, _ = _source_inventory(production.COMPOSE_SOURCE_PATHS)
    inventory[-1]["blob_sha256"] = "a" * 64
    inventory[-1]["working_sha256"] = "a" * 64
    second = _verify(
        source_inventory=inventory,
        source_inventory_sha256=_canonical_sha256(inventory),
    )
    assert first["status"] == second["status"] == "prepared"
    assert (
        first["production_projection"]["stage_projection_sha256"]
        != second["production_projection"]["stage_projection_sha256"]
    )


def test_repository_snapshot_rejects_working_blob_drift(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    binding = object()
    monkeypatch.setattr(production, "_discover_repository_binding", lambda: binding)
    monkeypatch.setattr(
        production,
        "_require_clean_source_revision",
        lambda _rev, *, binding: None,
    )
    monkeypatch.setattr(production, "_committed_blob", lambda *_args: b"same")
    reads = iter([b"same"] * 6 + [b"drift", b"same"])
    monkeypatch.setattr(production, "_read_repository_file", lambda _path: next(reads))
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_changed_during_snapshot",
    ):
        production._discover_compose_source_inventory(REVISION)


def test_repository_snapshot_rejects_commit_working_mismatch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    binding = object()
    monkeypatch.setattr(production, "_discover_repository_binding", lambda: binding)
    monkeypatch.setattr(
        production,
        "_require_clean_source_revision",
        lambda _rev, *, binding: None,
    )
    monkeypatch.setattr(production, "_committed_blob", lambda *_args: b"committed")
    monkeypatch.setattr(production, "_read_repository_file", lambda _path: b"working")
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_working_blob_mismatch",
    ):
        production._discover_compose_source_inventory(REVISION)


def test_root_authority_anchor_requires_uid0_directory_and_safe_mode() -> None:
    def metadata(*, mode: int, uid: int = 0, dev: int = 1, ino: int = 2):  # type: ignore[no-untyped-def]
        return os.stat_result((mode, ino, dev, 1, uid, uid, 0, 0, 0, 0))

    trusted = metadata(mode=stat.S_IFDIR | 0o755)
    assert schema_v6._root_authority_anchor_is_trusted(trusted, trusted) is True
    adversarial = (
        metadata(mode=stat.S_IFLNK | 0o755),
        metadata(mode=stat.S_IFDIR | 0o755, uid=1000),
        metadata(mode=stat.S_IFDIR | 0o777),
        metadata(mode=stat.S_IFDIR | 0o755, dev=9),
        metadata(mode=stat.S_IFDIR | 0o755, ino=9),
    )
    for candidate in adversarial:
        assert (
            schema_v6._root_authority_anchor_is_trusted(trusted, candidate)
            is False
        )


def test_root_authority_traversal_checks_initial_root_anchor(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        schema_v6,
        "_root_authority_anchor_is_trusted",
        lambda _opened, _current: False,
    )
    with pytest.raises(
        schema_v6.SchemaV6AuthorityError,
        match="authority_root_anchor_untrusted",
    ):
        schema_v6._open_absolute_nofollow(
            Path("/etc/hosts"),
            flags=os.O_RDONLY,
            reason="authority",
            require_root_parents=True,
        )


def test_git_environment_discards_inherited_controls(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    hostile = {
        "GIT_DIR": "/private/hostile-git-dir",
        "GIT_WORK_TREE": "/private/hostile-work-tree",
        "GIT_COMMON_DIR": "/private/hostile-common-dir",
        "GIT_INDEX_FILE": "/private/hostile-index",
        "GIT_OBJECT_DIRECTORY": "/private/hostile-objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/private/hostile-alternates",
        "GIT_REPLACE_REF_BASE": "refs/private/replace",
        "GIT_CONFIG_PARAMETERS": "'core.worktree'='/private/hostile'",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": "/private/hostile",
        "GIT_CONFIG_GLOBAL": "/private/hostile-global-config",
    }
    for key, value in hostile.items():
        monkeypatch.setenv(key, value)
    selected = production._git_environment()
    assert selected["GIT_CONFIG_COUNT"] == "0"
    assert selected["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert selected["GIT_NO_LAZY_FETCH"] == "1"
    assert selected["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert selected["GIT_ALLOW_PROTOCOL"] == ""
    assert selected["GIT_PROTOCOL_FROM_USER"] == "0"
    assert selected["GIT_ASKPASS"] == "/bin/false"
    assert selected["SSH_ASKPASS"] == "/bin/false"
    assert selected["GIT_SSH_COMMAND"] == "/bin/false"
    for key, value in hostile.items():
        assert selected.get(key) != value


def test_repository_binding_ignores_hostile_git_environment(
    monkeypatch, tmp_path: Path  # type: ignore[no-untyped-def]
) -> None:
    hostile_config = tmp_path / "hostile.gitconfig"
    hostile_config.write_text(
        "[core]\n\tworktree = /private/hostile-work-tree\n",
        encoding="utf-8",
    )
    hostile = {
        "GIT_DIR": "/private/hostile-git-dir",
        "GIT_WORK_TREE": "/private/hostile-work-tree",
        "GIT_OBJECT_DIRECTORY": "/private/hostile-objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/private/hostile-alternates",
        "GIT_CONFIG_GLOBAL": str(hostile_config),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": "/private/hostile-work-tree",
    }
    for key, value in hostile.items():
        monkeypatch.setenv(key, value)
    binding = production._discover_repository_binding()
    assert binding.work_tree == production.ROOT
    assert binding.head_commit == production._binding_value(
        ["rev-parse", "--verify", "HEAD^{commit}"],
        reason="test_head_unavailable",
        binding=binding,
    )


def test_missing_promisor_blob_never_fetches_or_invokes_helper(
    monkeypatch, tmp_path: Path  # type: ignore[no-untyped-def]
) -> None:
    git = str(production._trusted_git_executable())
    work_tree = tmp_path / "work"
    remote = tmp_path / "remote.git"
    helper_marker = tmp_path / "upload-pack-invoked"
    upload_pack = tmp_path / "upload-pack-sentinel"
    setup_environment = {
        "PATH": production.GIT_SAFE_PATH,
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "file",
    }

    def run_git(*arguments: str, cwd: Path | None = None) -> str:
        completed = subprocess.run(  # nosec B603 - fixed trusted Git test setup
            [git, *arguments],
            cwd=cwd,
            env=setup_environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.stdout.strip()

    run_git("init", "--quiet", str(work_tree))
    run_git("config", "user.name", "authority-test", cwd=work_tree)
    run_git("config", "user.email", "authority-test@example.invalid", cwd=work_tree)
    source_path = work_tree / "production-stage.yml"
    source_path.write_text("services: {}\n", encoding="utf-8")
    run_git("add", source_path.name, cwd=work_tree)
    run_git("commit", "--quiet", "-m", "sealed source", cwd=work_tree)
    revision = run_git("rev-parse", "HEAD", cwd=work_tree)
    blob_id = run_git("rev-parse", f"HEAD:{source_path.name}", cwd=work_tree)

    run_git("init", "--bare", "--quiet", str(remote))
    run_git("remote", "add", "origin", remote.as_uri(), cwd=work_tree)
    run_git("push", "--quiet", "origin", "HEAD:refs/heads/main", cwd=work_tree)
    upload_pack.write_text(
        "#!/bin/sh\n"
        f"printf invoked > {shlex.quote(str(helper_marker))}\n"
        "exit 97\n",
        encoding="utf-8",
    )
    upload_pack.chmod(0o700)
    run_git("config", "extensions.partialClone", "origin", cwd=work_tree)
    run_git("config", "remote.origin.promisor", "true", cwd=work_tree)
    run_git(
        "config",
        "remote.origin.partialCloneFilter",
        "blob:none",
        cwd=work_tree,
    )
    run_git(
        "config",
        "remote.origin.uploadpack",
        str(upload_pack),
        cwd=work_tree,
    )

    missing_blob = work_tree / ".git" / "objects" / blob_id[:2] / blob_id[2:]
    assert missing_blob.is_file()
    missing_blob.unlink()
    monkeypatch.setattr(production, "ROOT", work_tree.resolve())
    monkeypatch.setattr(
        production,
        "COMPOSE_SOURCE_PATHS",
        (Path(source_path.name),),
    )

    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_blob_unavailable",
    ):
        production._discover_compose_source_inventory(revision)
    assert not helper_marker.exists()
    assert not missing_blob.exists()


def _fake_git_binding(path: Path) -> production.GitRepositoryBinding:
    identity = (1, 2, stat.S_IFDIR | 0o700, os.getuid(), os.getgid())
    return production.GitRepositoryBinding(
        work_tree=path,
        git_dir=path,
        common_dir=path,
        head_commit=REVISION,
        work_tree_identity=identity,
        git_dir_identity=identity,
        common_dir_identity=identity,
    )


def test_replacement_refs_are_rejected(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    binding = _fake_git_binding(tmp_path)
    monkeypatch.setattr(
        production,
        "_git_output",
        lambda *_args, **_kwargs: b"refs/replace/private\n",
    )
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_replace_refs_present",
    ):
        production._require_no_repository_overrides(binding)


def test_repository_object_alternates_are_rejected(
    monkeypatch, tmp_path: Path  # type: ignore[no-untyped-def]
) -> None:
    binding = _fake_git_binding(tmp_path)
    alternates = tmp_path / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True)
    alternates.write_text("/private/hostile-objects\n", encoding="utf-8")
    monkeypatch.setattr(production, "_git_output", lambda *_args, **_kwargs: b"")
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_alternates_present",
    ):
        production._require_no_repository_overrides(binding)


def test_repository_snapshot_revalidates_final_committed_blobs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    binding = object()
    monkeypatch.setattr(production, "_discover_repository_binding", lambda: binding)
    monkeypatch.setattr(
        production,
        "_require_clean_source_revision",
        lambda _rev, *, binding: None,
    )
    blobs = iter([b"same"] * 4 + [b"same", b"drift", b"same", b"same"])
    monkeypatch.setattr(
        production,
        "_committed_blob",
        lambda *_args: next(blobs),
    )
    monkeypatch.setattr(production, "_read_repository_file", lambda _path: b"same")
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_changed_during_snapshot",
    ):
        production._discover_compose_source_inventory(REVISION)


def test_repository_snapshot_rejects_transient_binding_change(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bindings = iter((object(), object()))
    monkeypatch.setattr(
        production,
        "_discover_repository_binding",
        lambda: next(bindings),
    )
    monkeypatch.setattr(
        production,
        "_require_clean_source_revision",
        lambda _rev, *, binding: None,
    )
    monkeypatch.setattr(production, "_committed_blob", lambda *_args: b"same")
    monkeypatch.setattr(production, "_read_repository_file", lambda _path: b"same")
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_repository_binding_changed",
    ):
        production._discover_compose_source_inventory(REVISION)


def test_pre_receipt_revalidation_rechecks_exact_blobs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    inventory, inventory_sha256 = _source_inventory(production.COMPOSE_SOURCE_PATHS)
    binding = object()
    monkeypatch.setattr(production, "_discover_repository_binding", lambda: binding)
    monkeypatch.setattr(
        production,
        "_require_clean_source_revision",
        lambda _rev, *, binding: None,
    )
    monkeypatch.setattr(
        production,
        "_committed_blob",
        lambda *_args: b"transient-drift",
    )
    monkeypatch.setattr(
        production,
        "_read_repository_file",
        lambda _path: b"transient-drift",
    )
    with pytest.raises(
        production.ProductionStageError,
        match="compose_source_inventory_revalidation_failed",
    ):
        production._revalidate_compose_source_inventory(
            REVISION,
            inventory,
            inventory_sha256,
        )


def test_authority_uid_is_not_caller_selectable() -> None:
    signature = inspect.signature(schema_v6.load_schema_v6_qualification)
    assert "permit_owner_uid" not in signature.parameters
    assert schema_v6.ROOT_AUTHORITY_UID == 0
    assert production.ROOT_AUTHORITY_UID == 0


def test_non_root_authority_file_is_rejected(tmp_path: Path) -> None:
    if os.getuid() == 0:
        pytest.skip("requires a non-root test process")
    authority = tmp_path / "self-issued.json"
    authority.write_text('{"status":"allow"}', encoding="utf-8")
    authority.chmod(0o644)
    with pytest.raises(
        schema_v6.SchemaV6AuthorityError,
        match="authority_(?:parent_)?untrusted",
    ):
        schema_v6.read_trusted_json(
            authority,
            expected_uid=production.ROOT_AUTHORITY_UID,
            expected_mode=0o644,
            max_bytes=1024,
            reason="authority",
        )


def _schema_state(*, phase: str = "qualified") -> dict[str, object]:
    qualified_at: str | None = "2026-07-26T02:04:00Z" if phase == "qualified" else None
    return {
        "version": 6,
        "qualification_phase": phase,
        "epoch_started_at": "2026-07-19T02:03:22.235Z",
        "epoch_started_ms": 1784426602235,
        "qualification_earliest_completion_at": "2026-07-26T02:03:22.235Z",
        "qualified_at": qualified_at,
        "updated_at": "2026-07-26T02:59:00Z",
        "current_resources_healthy": True,
        "certification_blockers": [],
    }


def _schema_permit(state: dict[str, object]) -> dict[str, object]:
    identity = schema_v6.terminal_identity(state)
    return {
        "contract_name": schema_v6.PERMIT_CONTRACT_NAME,
        "version": schema_v6.PERMIT_VERSION,
        "status": "allow",
        **identity,
        "terminal_identity_sha256": schema_v6.terminal_identity_sha256(state),
        "issued_at": "2026-07-26T02:05:00Z",
        "expires_at": "2026-07-26T03:05:00Z",
        "mutation_boundaries": list(schema_v6.PERMIT_BOUNDARIES),
    }


def test_existing_memorial_permit_is_qualification_only() -> None:
    state = _schema_state()
    evidence = schema_v6.validate_schema_v6_qualification(
        state,
        _schema_permit(state),
        state_sha256="5" * 64,
        permit_sha256="6" * 64,
        now=NOW,
    )
    assert evidence.mutation_authority_transferred is False
    assert evidence.projection()["evidence_scope"] == (
        "schema_v6_terminal_qualification_only"
    )


def test_active_enforced_soak_cannot_be_prepared() -> None:
    state = _schema_state(phase="enforced_soak")
    with pytest.raises(
        schema_v6.SchemaV6AuthorityError,
        match="schema_v6_state_not_terminal",
    ):
        schema_v6.validate_schema_v6_qualification(
            state,
            _schema_permit(state),
            state_sha256="5" * 64,
            permit_sha256="6" * 64,
            now=NOW,
        )


def test_expired_injected_schema_evidence_cannot_prepare() -> None:
    expired = schema_v6.QualificationEvidence(
        state_sha256="1" * 64,
        terminal_identity_sha256="2" * 64,
        qualified_at="2026-07-26T02:04:00Z",
        permit_contract_name=schema_v6.PERMIT_CONTRACT_NAME,
        permit_sha256="3" * 64,
        permit_expires_at="2026-07-26T02:59:59Z",
    )
    result = _verify(qualification=expired)
    assert result["status"] == "blocked"
    assert "authority:schema_v6_qualification_missing" in result["issues"]


def test_trusted_reader_rejects_duplicate_authority_keys(tmp_path: Path) -> None:
    authority = tmp_path / "authority.json"
    authority.write_text('{"status":"allow","status":"deny"}', encoding="utf-8")
    authority.chmod(0o600)
    with pytest.raises(schema_v6.SchemaV6AuthorityError, match="authority_json_invalid"):
        schema_v6.read_trusted_json(
            authority,
            expected_uid=os.getuid(),
            expected_mode=0o600,
            max_bytes=1024,
            reason="authority",
        )


def test_private_reader_rejects_duplicate_keys_and_symlinks(tmp_path: Path) -> None:
    payload = tmp_path / "private.json"
    payload.write_text('{"status":"pass","status":"blocked"}', encoding="utf-8")
    payload.chmod(0o600)
    with pytest.raises(production.ProductionStageError, match="private_json_invalid"):
        production._read_private_json(payload, max_bytes=1024, reason="private")
    payload.write_text('{"status":"pass"}', encoding="utf-8")
    link = tmp_path / "private-link.json"
    link.symlink_to(payload)
    with pytest.raises(production.ProductionStageError, match="private_unavailable"):
        production._read_private_json(link, max_bytes=1024, reason="private")

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    nested = real_parent / "nested.json"
    nested.write_text('{"status":"pass"}', encoding="utf-8")
    nested.chmod(0o600)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(production.ProductionStageError, match="private_unavailable"):
        production._read_private_json(
            linked_parent / "nested.json",
            max_bytes=1024,
            reason="private",
        )


def test_receipt_writer_requires_private_non_symlink_parent(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    receipt = tmp_path / "receipt.json"
    production._write_receipt(receipt, {"status": "prepared"})
    assert stat_mode(receipt) == 0o600
    assert json.loads(receipt.read_text(encoding="utf-8")) == {"status": "prepared"}

    real_parent = tmp_path / "real-output"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-output"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(
        production.ProductionStageError,
        match="receipt_parent_unavailable",
    ):
        production._write_receipt(
            linked_parent / "receipt.json",
            {"status": "prepared"},
        )


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_shared_schema_contract_matches_memorial_deployer() -> None:
    from scripts import deploy_ea_memorial as memorial

    assert schema_v6.STATE_VERSION == memorial.VEXP_SENTINEL_STATE_VERSION
    assert schema_v6.PERMIT_CONTRACT_NAME == memorial.VEXP_MUTATION_PERMIT_CONTRACT_NAME
    assert schema_v6.PERMIT_VERSION == memorial.VEXP_MUTATION_PERMIT_VERSION
    assert schema_v6.PERMIT_BOUNDARIES == memorial.VEXP_MUTATION_BOUNDARIES
    assert schema_v6.PERMIT_KEYS == memorial.VEXP_MUTATION_PERMIT_KEYS


def test_checked_in_overlay_is_api_free_and_idle() -> None:
    raw = (production.ROOT / production.OVERLAY_RELATIVE_PATH).read_text(
        encoding="utf-8"
    )
    assert "\n  ea-api:" not in raw
    assert "replicas: 0" in raw
    assert "runtime_activation_authority: denied" in raw
    assert "provider_work_authority: denied" in raw


def test_producer_has_no_authorize_or_owner_permit_cli() -> None:
    source = Path(production.__file__).read_text(encoding="utf-8")
    assert 'choices=("prepare", "authorize")' not in source
    assert 'parser.add_argument("--owner-permit"' not in source
    assert "--owner-permit-owner-uid" not in source
    assert "--schema-v6-permit-owner-uid" not in source
