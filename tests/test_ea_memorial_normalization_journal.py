from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deploy_ea_memorial_joint as joint_deploy
from scripts import ea_memorial_baseline_bundle as baseline_bundle
from scripts import ea_memorial_normalization_journal as journal
from scripts import ea_memorial_recovery_interlock as interlock
from scripts import ea_memorial_runtime_identity as runtime_identity


HEX = "a" * 64
REVISION = "2e5b40f9fe2ef4acb7946eb7e80537fcd01ab047"
DAEMON_IDENTITY = "docker-daemon-ea-production-01"


def _container_inspection(*, api: bool) -> dict[str, object]:
    labels = {
        runtime_identity.COMPOSE_CONFIG_HASH_LABEL: "d" * 64 if api else "9" * 64,
        runtime_identity.COMPOSE_PROJECT_LABEL: "ea",
        runtime_identity.COMPOSE_SERVICE_LABEL: ("ea-api" if api else "ea-cloudflared"),
    }
    if api:
        labels.update(
            {
                "com.docker.compose.project.working_dir": "/old/release",
                "com.docker.compose.project.config_files": "/old/docker-compose.yml",
                "com.docker.compose.project.environment_file": "/old/.env",
            }
        )
    return {
        "Name": "/ea-api" if api else "/externalbrain-cloudflared",
        "Image": "sha256:" + ("c" if api else "2") * 64,
        "Config": {
            "Image": (
                "ea-runtime:memorial-main-2e5b40f9-20260719"
                if api
                else "cloudflare/cloudflared:2026.7.0"
            ),
            "Env": ["APP_MODE=production", "PORT=8000"],
            "Cmd": ["python", "-m", "ea.app"] if api else ["tunnel", "run"],
            "Entrypoint": [],
            "WorkingDir": "/app" if api else "",
            "Healthcheck": None,
            "Labels": labels,
            "ExposedPorts": {},
            "User": "1000:1000" if api else "",
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "LogConfig": {"Type": "json-file", "Config": {}},
            "NetworkMode": "ea-public-ingress",
        },
        "NetworkSettings": {
            "Ports": {},
            "Networks": {
                "ea-public-ingress": {
                    "Aliases": ["ea-api" if api else "externalbrain-cloudflared"],
                    "IPAddress": "172.30.0.2" if api else "172.30.0.3",
                    "IPPrefixLen": 16,
                }
            },
        },
        "Mounts": [],
    }


def _api_projection() -> dict[str, object]:
    return runtime_identity.memorial_api_runtime_projection(
        _container_inspection(api=True)
    )


def _cloudflared_projection() -> dict[str, object]:
    return runtime_identity.cloudflared_runtime_projection(
        _container_inspection(api=False)
    )


def _network_projection() -> dict[str, object]:
    return runtime_identity.public_network_semantic_projection(
        {
            "Name": runtime_identity.PUBLIC_NETWORK_NAME,
            "Driver": "bridge",
            "Scope": "local",
            "Internal": False,
            "Attachable": True,
            "Ingress": False,
            "ConfigOnly": False,
            "ConfigFrom": {"Network": ""},
            "IPAM": {"Driver": "default", "Config": [], "Options": {}},
            "Containers": {
                "opaque-api-id": {
                    "Name": "ea-api",
                    "IPv4Address": "172.30.0.2/16",
                    "IPv6Address": "",
                    "MacAddress": "02:42:ac:1e:00:02",
                },
                "opaque-ingress-id": {
                    "Name": "externalbrain-cloudflared",
                    "IPv4Address": "172.30.0.3/16",
                    "IPv6Address": "",
                    "MacAddress": "02:42:ac:1e:00:03",
                },
            },
            "Options": {},
            "Labels": {},
        }
    )


def _edge_projection() -> dict[str, object]:
    probes = {}
    for index, (label, path) in enumerate(journal.PUBLIC_EDGE_PROBES):
        for method in ("GET", "HEAD"):
            probes[f"{label}_{method.lower()}"] = {
                "method": method,
                "path": path,
                "status": 200 if method == "GET" else 405,
                "body_sha256": (
                    f"{index + 1:x}" * 64
                    if method == "GET"
                    else journal.EMPTY_BODY_SHA256
                ),
                "headers_sha256": f"{index + 7:x}" * 64,
            }
    return {
        "schema": journal.PUBLIC_EDGE_IDENTITY_SCHEMA,
        "origin": "https://myexternalbrain.com",
        "probes": probes,
    }


def test_public_edge_probe_contract_matches_joint_deploy_lane() -> None:
    assert journal.PUBLIC_EDGE_PROBES == tuple(
        (probe.label, probe.path) for probe in joint_deploy.PUBLIC_PROBES
    )


@pytest.fixture
def store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> journal.NormalizationRecoveryJournal:
    home = tmp_path / "operator-home"
    anchor = tmp_path / "release-anchor"
    home.mkdir(mode=0o700)
    anchor.mkdir(mode=0o700)
    home.chmod(0o700)
    anchor.chmod(0o700)
    monkeypatch.setattr(
        interlock.pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_dir=str(home)),
    )
    return journal.NormalizationRecoveryJournal(operator_anchor=anchor)


def _payload(store: journal.NormalizationRecoveryJournal) -> dict[str, object]:
    bundle = store.operator_anchor.parent / "retained-bundle"
    transaction_id = "normalize-transaction-001"
    return store.new_payload(
        transaction_id=transaction_id,
        release_root=store.operator_anchor,
        transaction_receipt_path=(
            store.operator_anchor / ".runtime" / f"{transaction_id}.json"
        ),
        public_origin="https://myexternalbrain.com",
        retained_bundle_path=bundle,
        retained_bundle_manifest_path=bundle / baseline_bundle.MANIFEST_NAME,
        retained_bundle_manifest_sha256=HEX,
        retained_bundle_plan_sha256="b" * 64,
        ordered_compose_files=[
            bundle / "docker-compose.yml",
            bundle / "docker-compose.memorial.yml",
            bundle / journal.NORMALIZATION_OVERRIDE_FILENAME,
        ],
        environment_file=bundle / ".env",
        environment_local_file=bundle / ".env.local",
        source_revision=REVISION,
        image_id="sha256:" + "c" * 64,
        image_reference="ea-runtime:memorial-main-2e5b40f9-20260719",
        compose_config_hash="d" * 64,
        docker_daemon_identity=DAEMON_IDENTITY,
        api_identity=_api_projection(),
        cloudflared_identity=_cloudflared_projection(),
        public_network_identity=_network_projection(),
        public_edge_identity=_edge_projection(),
        now="2026-07-21T12:00:00.000Z",
    )


def _publish_raw(store: journal.NormalizationRecoveryJournal, raw: bytes) -> None:
    store.path.parent.mkdir(mode=0o700)
    store.path.write_bytes(raw)
    store.path.chmod(0o600)


def _write_terminal_receipt(
    store: journal.NormalizationRecoveryJournal,
    payload: dict[str, object],
    *,
    kind: str,
    observations: dict[str, object],
    completed_at: str,
) -> str:
    receipt_path = Path(str(payload["transaction_receipt_path"]))
    receipt_path.parent.mkdir(mode=0o700, exist_ok=True)
    receipt_path.parent.chmod(0o700)
    observation = _terminal_observation(payload, observations)
    raw = (
        json.dumps(
            journal.terminal_receipt_payload(
                payload,
                kind=kind,
                observation=observation,
                completed_at=completed_at,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    receipt_path.write_bytes(raw)
    receipt_path.chmod(0o600)
    return journal._sha256(raw)


def _record_protected(
    store: journal.NormalizationRecoveryJournal,
    payload: dict[str, object],
    *,
    now: str,
) -> dict[str, object]:
    return store.record_protected_image(
        payload,
        observed_image_id=payload["previous_image"]["image_id"],
        observed_rollback_tag=payload["previous_image"]["rollback_tag"],
        now=now,
    )


def _terminal_observations(
    payload: dict[str, object], *, kind: str
) -> dict[str, object]:
    baselines = payload["baselines"]
    api_identity = copy.deepcopy(baselines["api_identity"]["projection"])
    if kind in {"durable_commit", "verified_forward_recovery"}:
        api_identity["topology_label_evidence"] = copy.deepcopy(
            baselines["target_api_topology_label_evidence"]
        )
    return {
        "observed_api_identity": api_identity,
        "observed_cloudflared_identity": copy.deepcopy(
            baselines["cloudflared_identity"]["projection"]
        ),
        "observed_public_network_identity": copy.deepcopy(
            baselines["public_network_identity"]["projection"]
        ),
        "observed_public_edge_identity": copy.deepcopy(
            baselines["public_edge_identity"]["projection"]
        ),
        "observed_docker_daemon_identity": DAEMON_IDENTITY,
        "observed_protected_image_id": (
            payload["previous_image"]["image_id"]
            if kind in {"durable_commit", "verified_forward_recovery"}
            else None
        ),
    }


def _terminal_observation(
    payload: dict[str, object], observations: dict[str, object]
) -> dict[str, object]:
    return journal.terminal_observation(
        api_identity=observations["observed_api_identity"],
        cloudflared_identity=observations["observed_cloudflared_identity"],
        public_network_identity=observations["observed_public_network_identity"],
        public_edge_identity=observations["observed_public_edge_identity"],
        docker_daemon_identity=observations["observed_docker_daemon_identity"],
        observed_protected_image_id=observations["observed_protected_image_id"],
        expected_protected_image_id=payload["previous_image"]["image_id"],
        compose_config_hash=payload["baselines"]["compose_config_hash"],
        public_origin=payload["public_origin"],
        baseline_api_topology_label_evidence=payload["baselines"]["api_identity"][
            "projection"
        ]["topology_label_evidence"],
        target_api_topology_label_evidence=payload["baselines"][
            "target_api_topology_label_evidence"
        ],
    )


def test_create_read_is_private_durable_and_canonical(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)

    digest = store.create(payload)

    assert digest == journal._sha256(journal._journal_bytes(payload))
    assert store.read() == payload
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    metadata = store.path.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert stat.S_ISREG(metadata.st_mode)
    assert metadata.st_nlink == 1
    assert store.path == (
        store.operator_anchor.parent
        / "operator-home"
        / interlock.NORMALIZATION_RECOVERY_STATE_DIRECTORY
        / interlock.NORMALIZATION_RECOVERY_JOURNAL_FILENAME
    )


def test_absent_state_is_not_created_by_read(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    assert store.read() is None
    assert not store.path.parent.exists()


def test_create_is_no_replace(store: journal.NormalizationRecoveryJournal) -> None:
    _publish_raw(store, b"do-not-replace")

    with pytest.raises(journal.NormalizationJournalError, match="already_exists"):
        store.create(_payload(store))

    assert store.path.read_bytes() == b"do-not-replace"


def test_create_only_accepts_initial_prepared_state(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    protected = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )

    with pytest.raises(journal.NormalizationJournalError, match="initial_state"):
        store.create(protected)


def test_create_crash_after_atomic_publish_never_leaves_two_links(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    real_rename = journal._renameat2
    real_fsync = journal.os.fsync
    published = False

    def rename_then_mark(*args: object) -> None:
        nonlocal published
        real_rename(*args)
        published = True

    def crash_after_publish(fd: int) -> None:
        if published:
            raise OSError("simulated process loss after publish")
        real_fsync(fd)

    monkeypatch.setattr(journal, "_renameat2", rename_then_mark)
    monkeypatch.setattr(journal.os, "fsync", crash_after_publish)

    with pytest.raises(OSError, match="simulated process loss"):
        store.create(payload)

    monkeypatch.setattr(journal, "_renameat2", real_rename)
    monkeypatch.setattr(journal.os, "fsync", real_fsync)
    assert store.read() == payload
    assert store.path.stat().st_nlink == 1


@pytest.mark.parametrize("entry_kind", ["symlink", "hardlink", "fifo"])
def test_read_rejects_non_private_or_special_entry(
    store: journal.NormalizationRecoveryJournal,
    tmp_path: Path,
    entry_kind: str,
) -> None:
    store.path.parent.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_bytes(journal._journal_bytes(_payload(store)))
    target.chmod(0o600)
    if entry_kind == "symlink":
        store.path.symlink_to(target)
    elif entry_kind == "hardlink":
        os.link(target, store.path)
    else:
        os.mkfifo(store.path, 0o600)

    with pytest.raises(journal.NormalizationJournalError):
        store.read()


def test_read_rejects_duplicate_keys(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    _publish_raw(store, b'{"contract_name":"a","contract_name":"b"}\n')

    with pytest.raises(journal.NormalizationJournalError, match="duplicate_key"):
        store.read()


def test_read_rejects_oversized_file_without_parsing(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    _publish_raw(store, b"x" * (journal.MAX_JOURNAL_BYTES + 1))

    with pytest.raises(journal.NormalizationJournalError, match="untrusted"):
        store.read()


def test_update_requires_exact_owned_bytes_and_legal_transition(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    store.create(payload)
    protected = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )

    store.update(expected=payload, replacement=protected)

    assert store.read() == protected
    stale = copy.deepcopy(payload)
    stale["source_revision"] = "9" * 40
    stale_replacement = copy.deepcopy(protected)
    stale_replacement["source_revision"] = "9" * 40
    with pytest.raises(journal.NormalizationJournalError, match="not_owned"):
        store.update(expected=stale, replacement=stale_replacement)
    with pytest.raises(journal.NormalizationJournalError, match="transition_invalid"):
        store.with_phase(protected, "commit_pending")


def test_fresh_read_recovers_update_crash_leftover_without_replaying_update(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    store.create(payload)
    protected = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    real_rename = journal._renameat2
    real_fsync = journal.os.fsync
    exchanged = False

    def exchange_then_mark(*args: object) -> None:
        nonlocal exchanged
        real_rename(*args)
        if args[-1] == journal._RENAME_EXCHANGE:
            exchanged = True

    def crash_after_exchange(fd: int) -> None:
        if exchanged:
            raise OSError("simulated process loss after exchange")
        real_fsync(fd)

    monkeypatch.setattr(journal, "_renameat2", exchange_then_mark)
    monkeypatch.setattr(journal.os, "fsync", crash_after_exchange)
    with pytest.raises(OSError, match="simulated process loss"):
        store.update(expected=payload, replacement=protected)

    monkeypatch.setattr(journal, "_renameat2", real_rename)
    monkeypatch.setattr(journal.os, "fsync", real_fsync)
    leftover = store.path.parent / store._temporary_name(
        "update", journal._journal_bytes(protected)
    )
    assert leftover.exists()
    fresh = journal.NormalizationRecoveryJournal(operator_anchor=store.operator_anchor)
    assert fresh.read() == protected
    assert not leftover.exists()


def test_update_detects_same_uid_path_substitution_and_keeps_canonical_valid(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    store.create(payload)
    protected = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    attacker_entry = store.operator_anchor.parent / "attacker-journal"
    attacker_entry.write_bytes(journal._journal_bytes(payload))
    attacker_entry.chmod(0o600)
    real_rename = journal._renameat2

    def substitute_then_exchange(*args: object) -> None:
        if args[-1] == journal._RENAME_EXCHANGE:
            os.replace(attacker_entry, store.path)
        real_rename(*args)

    monkeypatch.setattr(journal, "_renameat2", substitute_then_exchange)
    with pytest.raises(journal.NormalizationJournalError, match="exchange_invalid"):
        store.update(expected=payload, replacement=protected)

    assert store.read() == protected


def test_phase_flags_and_recovery_retry_are_strict(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    current = _payload(store)
    current = store.with_phase(
        current,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    current = _record_protected(
        store,
        current,
        now="2026-07-21T12:01:30.000Z",
    )
    current = store.with_phase(
        current,
        "api_mutation_possible",
        now="2026-07-21T12:02:00.000Z",
    )
    for phase in (
        "rollback_in_progress",
        "rollback_failed",
        "rollback_in_progress",
    ):
        current = store.with_phase(
            current,
            phase,
            now="2026-07-21T12:03:00.000Z",
            recovery_attempts=(
                int(current["recovery_attempts"]) + 1
                if phase == "rollback_in_progress"
                else int(current["recovery_attempts"])
            ),
        )
    assert current["api_mutation_possible"] is True
    assert current["recovery_attempts"] == 2


def test_recovery_retry_is_persistable_through_update(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    prepared = _payload(store)
    store.create(prepared)
    protected_possible = store.with_phase(
        prepared,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=prepared, replacement=protected_possible)
    recovering = store.with_phase(
        protected_possible,
        "rollback_in_progress",
        now="2026-07-21T12:02:00.000Z",
    )
    store.update(expected=protected_possible, replacement=recovering)
    retry = store.with_phase(
        recovering,
        "rollback_in_progress",
        now="2026-07-21T12:03:00.000Z",
    )

    store.update(expected=recovering, replacement=retry)

    assert store.read() == retry
    assert retry["recovery_attempts"] == 2


def test_retry_can_bind_an_older_orphan_terminal_receipt_without_time_regression(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    prepared = _payload(store)
    store.create(prepared)
    protected_possible = store.with_phase(
        prepared,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=prepared, replacement=protected_possible)
    recovering = store.with_phase(
        protected_possible,
        "rollback_in_progress",
        now="2026-07-21T12:02:00.000Z",
    )
    store.update(expected=protected_possible, replacement=recovering)
    failed = store.with_phase(
        recovering,
        "rollback_failed",
        now="2026-07-21T12:04:00.000Z",
    )
    store.update(expected=recovering, replacement=failed)
    retry = store.with_phase(
        failed,
        "rollback_in_progress",
        now="2026-07-21T12:05:00.000Z",
    )
    store.update(expected=failed, replacement=retry)
    observations = _terminal_observations(retry, kind="verified_recovery")
    receipt_sha256 = _write_terminal_receipt(
        store,
        retry,
        kind="verified_recovery",
        observations=observations,
        completed_at="2026-07-21T12:03:00.000Z",
    )

    evidenced = store.record_terminal_evidence(
        retry,
        kind="verified_recovery",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:03:00.000Z",
    )
    store.update(expected=retry, replacement=evidenced)

    assert evidenced["updated_at"] == "2026-07-21T12:05:00.000Z"
    assert evidenced["evidence"]["terminal"]["recorded_at"] == (
        "2026-07-21T12:03:00.000Z"
    )
    store.remove(expected=evidenced)
    assert store.read() is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_revision", "short", "source_revision_invalid"),
        ("recovery_journal_path", "/tmp/wrong.json", "binding_invalid"),
        ("public_origin", "http://myexternalbrain.com", "public_origin_invalid"),
    ],
)
def test_schema_rejects_unbound_or_malformed_top_level_values(
    store: journal.NormalizationRecoveryJournal,
    field: str,
    value: object,
    reason: str,
) -> None:
    payload = copy.deepcopy(_payload(store))
    payload[field] = value

    with pytest.raises(journal.NormalizationJournalError, match=reason):
        journal.validate_payload(
            payload,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


def test_schema_rejects_unknown_fields_and_bundle_escape(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = copy.deepcopy(_payload(store))
    payload["unexpected"] = True
    with pytest.raises(journal.NormalizationJournalError, match="schema_invalid"):
        journal.validate_payload(
            payload,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )

    escaped = copy.deepcopy(_payload(store))
    escaped["retained_bundle"]["ordered_compose_files"][2] = str(
        store.operator_anchor / journal.NORMALIZATION_OVERRIDE_FILENAME
    )
    with pytest.raises(journal.NormalizationJournalError, match="bundle_binding"):
        journal.validate_payload(
            escaped,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


def test_bundle_recovery_seal_is_exact_and_plan_bound(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    assert (
        journal.BUNDLE_RECOVERY_SEAL_CONTRACT_NAME
        == baseline_bundle.RECOVERY_SEAL_CONTRACT
    )
    assert (
        Path(payload["retained_bundle"]["manifest_path"]).name
        == baseline_bundle.MANIFEST_NAME
        == journal.RETAINED_BUNDLE_MANIFEST_FILENAME
    )
    seal = payload["retained_bundle"]["recovery_seal"]
    assert seal == {
        "contract_name": journal.BUNDLE_RECOVERY_SEAL_CONTRACT_NAME,
        "manifest_sha256": HEX,
        "plan_sha256": "b" * 64,
    }
    assert "tree_sha256" not in payload["retained_bundle"]

    tampered = copy.deepcopy(payload)
    tampered["retained_bundle"]["recovery_seal"]["plan_sha256"] = "short"
    with pytest.raises(journal.NormalizationJournalError, match="bundle_invalid"):
        journal.validate_payload(
            tampered,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


def test_projection_digest_tamper_and_secret_values_are_rejected(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = copy.deepcopy(_payload(store))
    payload["baselines"]["api_identity"]["projection"]["healthy"] = False
    with pytest.raises(journal.NormalizationJournalError, match="digest_mismatch"):
        journal.validate_payload(
            payload,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


def test_identity_roles_and_exact_domain_sets_are_not_interchangeable(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    swapped = copy.deepcopy(_payload(store))
    (
        swapped["baselines"]["api_identity"],
        swapped["baselines"]["cloudflared_identity"],
    ) = (
        swapped["baselines"]["cloudflared_identity"],
        swapped["baselines"]["api_identity"],
    )
    with pytest.raises(journal.NormalizationJournalError, match="api_identity_invalid"):
        journal.validate_payload(
            swapped,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )

    missing_domain = copy.deepcopy(_payload(store))
    wrapper = missing_domain["baselines"]["api_identity"]
    del wrapper["projection"]["mounts"]
    wrapper["sha256"] = journal._sha256(
        journal._canonical_json_bytes(wrapper["projection"])
    )
    with pytest.raises(journal.NormalizationJournalError, match="api_identity_invalid"):
        journal.validate_payload(
            missing_domain,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )

    arbitrary_network = copy.deepcopy(_payload(store))
    arbitrary_network["baselines"]["public_network_identity"] = journal.identity(
        {"schema": runtime_identity.PUBLIC_NETWORK_SCHEMA, "members": []}
    )
    with pytest.raises(
        journal.NormalizationJournalError, match="public_network_identity_invalid"
    ):
        journal.validate_payload(
            arbitrary_network,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


@pytest.mark.parametrize("mutation", ["name", "config_from", "ipam_config"])
def test_public_network_identity_requires_exact_nested_schema(
    store: journal.NormalizationRecoveryJournal,
    mutation: str,
) -> None:
    payload = copy.deepcopy(_payload(store))
    projection = payload["baselines"]["public_network_identity"]["projection"]
    if mutation == "name":
        projection["name"] = "arbitrary-public-network"
    elif mutation == "config_from":
        projection["config_from"] = {"network": "", "extra": "accepted-before"}
    else:
        projection["ipam"]["config"] = [{"arbitrary": "accepted-before"}]
    payload["baselines"]["public_network_identity"] = journal.identity(projection)

    with pytest.raises(
        journal.NormalizationJournalError, match="public_network_identity_invalid"
    ):
        journal.validate_payload(
            payload,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


@pytest.mark.parametrize("mutation", ["missing", "wrong_method", "head_body"])
def test_public_edge_identity_requires_all_exact_get_and_head_records(
    store: journal.NormalizationRecoveryJournal,
    mutation: str,
) -> None:
    payload = copy.deepcopy(_payload(store))
    projection = payload["baselines"]["public_edge_identity"]["projection"]
    if mutation == "missing":
        del projection["probes"]["version_get"]
    elif mutation == "wrong_method":
        projection["probes"]["version_get"]["method"] = "HEAD"
    else:
        projection["probes"]["version_head"]["body_sha256"] = "a" * 64
    payload["baselines"]["public_edge_identity"] = journal.identity(projection)

    with pytest.raises(
        journal.NormalizationJournalError, match="public_edge_identity_invalid"
    ):
        journal.validate_payload(
            payload,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


def test_observed_evidence_cannot_be_replaced_with_baseline_assertions(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    protected_possible = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    with pytest.raises(journal.NormalizationJournalError, match="evidence_invalid"):
        store.record_protected_image(
            protected_possible,
            observed_image_id="sha256:" + "0" * 64,
            observed_rollback_tag=protected_possible["previous_image"]["rollback_tag"],
            now="2026-07-21T12:01:30.000Z",
        )

    protected = _record_protected(
        store,
        protected_possible,
        now="2026-07-21T12:01:30.000Z",
    )
    mutable = store.with_phase(
        protected,
        "api_mutation_possible",
        now="2026-07-21T12:02:00.000Z",
    )
    wrong_api = copy.deepcopy(mutable["baselines"]["api_identity"]["projection"])
    wrong_api["image"]["id"] = "sha256:" + "0" * 64
    with pytest.raises(
        journal.NormalizationJournalError, match="evidence_baseline_mismatch"
    ):
        store.record_api_mutation(
            mutable,
            observed_api_identity=wrong_api,
            now="2026-07-21T12:02:30.000Z",
        )

    observations = _terminal_observations(payload, kind="clean_abort")
    observations["observed_public_edge_identity"]["probes"]["version_get"][
        "body_sha256"
    ] = "0" * 64
    with pytest.raises(
        journal.NormalizationJournalError, match="evidence_baseline_mismatch"
    ):
        store.record_terminal_evidence(
            payload,
            kind="clean_abort",
            receipt_sha256="8" * 64,
            **observations,
            now="2026-07-21T12:01:30.000Z",
        )


@pytest.mark.parametrize(
    "secret_value",
    [
        "https://example.invalid/path?token=must-never-be-recorded",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJtYW5mcmVkLW1lbW9yaWFsIn0."
        "signature-material-that-must-not-be-recorded",
        "opaque_" + "AbCDefghijklmnopqrstuvwxyz0123456789" * 3,
    ],
)
def test_secret_like_values_under_innocuous_keys_are_rejected(
    store: journal.NormalizationRecoveryJournal,
    secret_value: str,
) -> None:
    payload = copy.deepcopy(_payload(store))
    projection = copy.deepcopy(payload["baselines"]["api_identity"]["projection"])
    projection["image"]["reference"] = secret_value
    payload["baselines"]["api_identity"] = journal.container_identity(projection)

    with pytest.raises(journal.NormalizationJournalError, match="secret_material"):
        journal.validate_payload(
            payload,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )

    secret = copy.deepcopy(_payload(store))
    projection = copy.deepcopy(secret["baselines"]["api_identity"]["projection"])
    projection["image"]["reference"] = "Bearer must-never-be-recorded"
    secret["baselines"]["api_identity"] = journal.container_identity(projection)
    with pytest.raises(journal.NormalizationJournalError, match="secret_material"):
        journal.validate_payload(
            secret,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )


def test_remove_only_accepts_exact_owned_terminal_evidence(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    store.create(payload)
    protected_possible = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=protected_possible)
    protected = _record_protected(
        store,
        protected_possible,
        now="2026-07-21T12:01:30.000Z",
    )
    store.update(expected=protected_possible, replacement=protected)
    mutable = store.with_phase(
        protected,
        "api_mutation_possible",
        now="2026-07-21T12:02:00.000Z",
    )
    store.update(expected=protected, replacement=mutable)
    api_verified = store.record_api_mutation(
        mutable,
        observed_api_identity=mutable["baselines"]["api_identity"]["projection"],
        now="2026-07-21T12:03:00.000Z",
    )
    store.update(expected=mutable, replacement=api_verified)
    observations = _terminal_observations(api_verified, kind="durable_commit")
    receipt_sha256 = _write_terminal_receipt(
        store,
        api_verified,
        kind="durable_commit",
        observations=observations,
        completed_at="2026-07-21T12:04:00.000Z",
    )
    evidenced = store.record_terminal_evidence(
        api_verified,
        kind="durable_commit",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:04:00.000Z",
    )
    store.update(expected=api_verified, replacement=evidenced)
    committed = store.with_phase(
        evidenced,
        "commit_pending",
        now="2026-07-21T12:05:00.000Z",
    )
    store.update(expected=evidenced, replacement=committed)

    store.remove(expected=committed)
    assert store.read() is None


def test_clean_abort_requires_bound_receipt_and_no_mutation_evidence(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    receipt_sha256 = _write_terminal_receipt(
        store,
        payload,
        kind="clean_abort",
        observations=observations,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=evidenced)

    receipt_path = Path(str(evidenced["transaction_receipt_path"]))
    receipt_path.write_text("tampered\n")
    receipt_path.chmod(0o600)
    with pytest.raises(journal.NormalizationJournalError, match="receipt_changed"):
        store.remove(expected=evidenced)
    assert store.read() == evidenced

    _write_terminal_receipt(
        store,
        payload,
        kind="clean_abort",
        observations=observations,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    store.remove(expected=evidenced)
    assert store.read() is None


def test_clean_abort_cannot_be_attached_after_a_mutation_boundary(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    protected_possible = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )

    with pytest.raises(
        journal.NormalizationJournalError, match="evidence_transition_invalid"
    ):
        store.record_terminal_evidence(
            protected_possible,
            kind="clean_abort",
            receipt_sha256="8" * 64,
            **_terminal_observations(protected_possible, kind="clean_abort"),
            now="2026-07-21T12:02:00.000Z",
        )


def test_cleanup_pending_clean_abort_rejects_injected_mutation_evidence(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    prepared = _payload(store)
    protected_possible = store.with_phase(
        prepared,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    protected = _record_protected(
        store,
        protected_possible,
        now="2026-07-21T12:01:30.000Z",
    )
    mutable = store.with_phase(
        protected,
        "api_mutation_possible",
        now="2026-07-21T12:02:00.000Z",
    )
    mutated = store.record_api_mutation(
        mutable,
        observed_api_identity=mutable["baselines"]["api_identity"]["projection"],
        now="2026-07-21T12:02:30.000Z",
    )
    clean = store.record_terminal_evidence(
        prepared,
        kind="clean_abort",
        receipt_sha256="8" * 64,
        **_terminal_observations(prepared, kind="clean_abort"),
        now="2026-07-21T12:03:00.000Z",
    )
    attacked = copy.deepcopy(clean)
    attacked["phase"] = "cleanup_pending"
    attacked["evidence"]["protected_image"] = mutated["evidence"]["protected_image"]
    attacked["evidence"]["api_mutation"] = mutated["evidence"]["api_mutation"]

    with pytest.raises(
        journal.NormalizationJournalError, match="evidence_phase_invalid"
    ):
        journal.validate_payload(
            attacked,
            expected_path=store.path,
            expected_operator_anchor=store.operator_anchor,
        )
    with pytest.raises(
        journal.NormalizationJournalError, match="receipt_payload_invalid"
    ):
        journal.terminal_receipt_payload(
            attacked,
            kind="clean_abort",
            observation=_terminal_observation(
                prepared, _terminal_observations(prepared, kind="clean_abort")
            ),
            completed_at="2026-07-21T12:03:00.000Z",
        )


def test_verified_recovery_receipt_authorizes_terminal_erasure(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    store.create(payload)
    protected_possible = store.with_phase(
        payload,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=protected_possible)
    recovering = store.with_phase(
        protected_possible,
        "rollback_in_progress",
        now="2026-07-21T12:02:00.000Z",
    )
    store.update(expected=protected_possible, replacement=recovering)
    observations = _terminal_observations(recovering, kind="verified_recovery")
    receipt_sha256 = _write_terminal_receipt(
        store,
        recovering,
        kind="verified_recovery",
        observations=observations,
        completed_at="2026-07-21T12:03:00.000Z",
    )
    receipt = json.loads(Path(str(recovering["transaction_receipt_path"])).read_text())
    assert receipt["terminal_observation"]["protected_tag_state"] == "absent"
    assert receipt["execution"]["protected_image_tag_mutation_recorded"] is False
    recovered = store.record_terminal_evidence(
        recovering,
        kind="verified_recovery",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:03:00.000Z",
    )
    store.update(expected=recovering, replacement=recovered)

    store.remove(expected=recovered)
    assert store.read() is None


def test_verified_forward_recovery_requires_persisted_api_boundary_and_target_topology(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    prepared = _payload(store)
    store.create(prepared)
    protected_possible = store.with_phase(
        prepared,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=prepared, replacement=protected_possible)
    protected = _record_protected(
        store,
        protected_possible,
        now="2026-07-21T12:01:30.000Z",
    )
    store.update(expected=protected_possible, replacement=protected)
    mutable = store.with_phase(
        protected,
        "api_mutation_possible",
        now="2026-07-21T12:02:00.000Z",
    )
    store.update(expected=protected, replacement=mutable)
    mutated = store.record_api_mutation(
        mutable,
        observed_api_identity=mutable["baselines"]["api_identity"]["projection"],
        now="2026-07-21T12:02:30.000Z",
    )
    store.update(expected=mutable, replacement=mutated)
    recovering = store.with_phase(
        mutated,
        "rollback_in_progress",
        now="2026-07-21T12:03:00.000Z",
    )
    store.update(expected=mutated, replacement=recovering)
    with pytest.raises(
        journal.NormalizationJournalError, match="evidence_transition_invalid"
    ):
        store.record_terminal_evidence(
            recovering,
            kind="verified_recovery",
            receipt_sha256="8" * 64,
            **_terminal_observations(recovering, kind="verified_recovery"),
            now="2026-07-21T12:03:30.000Z",
        )
    observations = _terminal_observations(recovering, kind="verified_forward_recovery")
    receipt_sha256 = _write_terminal_receipt(
        store,
        recovering,
        kind="verified_forward_recovery",
        observations=observations,
        completed_at="2026-07-21T12:04:00.000Z",
    )
    recovered = store.record_terminal_evidence(
        recovering,
        kind="verified_forward_recovery",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:04:00.000Z",
    )
    store.update(expected=recovering, replacement=recovered)

    assert recovered["api_boundary_authorized"] is True
    assert recovered["evidence"]["terminal"]["normalization_completed"] is True
    assert recovered["evidence"]["terminal"]["protected_tag_state"] == "retained"
    receipt = json.loads(Path(str(recovered["transaction_receipt_path"])).read_text())
    assert receipt["contract_name"] == "ea.memorial_api_baseline_normalization.v2"
    assert receipt["version"] == 2
    assert receipt["status"] == "interrupted_transaction_forward_recovered"
    assert receipt["execution"] == {
        "mode": "recovery",
        "api_recreation_observed": True,
        "protected_image_tag_mutation_recorded": True,
    }
    store.remove(expected=recovered)
    assert store.read() is None


def test_protect_only_recovery_cannot_claim_forward_normalization(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    prepared = _payload(store)
    protected_possible = store.with_phase(
        prepared,
        "protect_previous_image_possible",
        now="2026-07-21T12:01:00.000Z",
    )
    protected = _record_protected(
        store,
        protected_possible,
        now="2026-07-21T12:01:30.000Z",
    )
    recovering = store.with_phase(
        protected,
        "rollback_in_progress",
        now="2026-07-21T12:02:00.000Z",
    )
    observations = _terminal_observations(recovering, kind="verified_forward_recovery")

    with pytest.raises(
        journal.NormalizationJournalError, match="evidence_transition_invalid"
    ):
        store.record_terminal_evidence(
            recovering,
            kind="verified_forward_recovery",
            receipt_sha256="8" * 64,
            **observations,
            now="2026-07-21T12:03:00.000Z",
        )


def test_terminal_receipt_content_is_transaction_bound(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    observation = _terminal_observation(payload, observations)
    receipt_path = Path(str(payload["transaction_receipt_path"]))
    receipt_path.parent.mkdir(mode=0o700)
    receipt_path.parent.chmod(0o700)
    receipt = journal.terminal_receipt_payload(
        payload,
        kind="clean_abort",
        observation=observation,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    receipt["transaction_id"] = "different-transaction-999"
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt_path.write_bytes(raw)
    receipt_path.chmod(0o600)
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=journal._sha256(raw),
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=evidenced)

    with pytest.raises(journal.NormalizationJournalError, match="receipt_binding"):
        store.remove(expected=evidenced)
    assert store.read() == evidenced


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "legacy_contract",
        "status",
        "observation",
        "execution",
        "bundle",
        "completed_at",
    ],
)
def test_terminal_receipt_rejects_self_consistent_schema_and_governance_attacks(
    store: journal.NormalizationRecoveryJournal,
    mutation: str,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    observation = _terminal_observation(payload, observations)
    receipt = journal.terminal_receipt_payload(
        payload,
        kind="clean_abort",
        observation=observation,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    if mutation == "extra":
        receipt["extra"] = "self-consistent-but-unauthorized"
    elif mutation == "legacy_contract":
        receipt["contract_name"] = "ea.memorial_api_baseline_normalization.v1"
        receipt["version"] = 1
    elif mutation == "status":
        receipt["status"] = "pass"
    elif mutation == "observation":
        receipt["terminal_observation"]["protected_tag_state"] = "retained"
    elif mutation == "execution":
        receipt["execution"]["protected_image_tag_mutation_recorded"] = True
    elif mutation == "bundle":
        receipt["retained_bundle"]["plan_sha256"] = "0" * 64
    else:
        receipt["completed_at"] = "2026-07-21T12:01:01.000Z"
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt_path = Path(str(payload["transaction_receipt_path"]))
    receipt_path.parent.mkdir(mode=0o700)
    receipt_path.parent.chmod(0o700)
    receipt_path.write_bytes(raw)
    receipt_path.chmod(0o600)
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=journal._sha256(raw),
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=evidenced)

    with pytest.raises(journal.NormalizationJournalError, match="receipt_binding"):
        store.remove(expected=evidenced)
    assert store.read() == evidenced


def test_remove_crash_after_cleanup_publish_is_recovered_from_disk_only(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    receipt_sha256 = _write_terminal_receipt(
        store,
        payload,
        kind="clean_abort",
        observations=observations,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=evidenced)
    real_rename = journal._renameat2
    real_fsync = journal.os.fsync
    detached = False

    def detach_then_mark(*args: object) -> None:
        nonlocal detached
        real_rename(*args)
        if args[-1] == journal._RENAME_EXCHANGE:
            detached = True

    def crash_after_detach(fd: int) -> None:
        if detached:
            raise OSError("simulated process loss after detach")
        real_fsync(fd)

    monkeypatch.setattr(journal, "_renameat2", detach_then_mark)
    monkeypatch.setattr(journal.os, "fsync", crash_after_detach)
    with pytest.raises(OSError, match="simulated process loss"):
        store.remove(expected=evidenced)

    monkeypatch.setattr(journal, "_renameat2", real_rename)
    monkeypatch.setattr(journal.os, "fsync", real_fsync)
    assert store.path.exists()
    fresh = journal.NormalizationRecoveryJournal(operator_anchor=store.operator_anchor)
    cleanup = fresh.read()
    assert cleanup is not None
    assert cleanup["phase"] == "cleanup_pending"
    assert cleanup["evidence"] == evidenced["evidence"]
    fresh.remove(expected=cleanup)
    assert fresh.read() is None


def test_remove_crash_after_cleanup_unlink_is_terminal_from_disk_only(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    receipt_sha256 = _write_terminal_receipt(
        store,
        payload,
        kind="clean_abort",
        observations=observations,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=evidenced)
    cleanup = store.with_phase(
        evidenced,
        "cleanup_pending",
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=evidenced, replacement=cleanup)
    real_unlink = journal.os.unlink
    real_fsync = journal.os.fsync
    unlinked = False

    def unlink_then_mark(path: object, *args: object, **kwargs: object) -> None:
        nonlocal unlinked
        real_unlink(path, *args, **kwargs)
        if path == store.path.name:
            unlinked = True

    def crash_after_unlink(fd: int) -> None:
        if unlinked:
            raise OSError("simulated process loss after cleanup unlink")
        real_fsync(fd)

    monkeypatch.setattr(journal.os, "unlink", unlink_then_mark)
    monkeypatch.setattr(journal.os, "fsync", crash_after_unlink)
    with pytest.raises(OSError, match="cleanup unlink"):
        store.remove(expected=cleanup)

    monkeypatch.setattr(journal.os, "unlink", real_unlink)
    monkeypatch.setattr(journal.os, "fsync", real_fsync)
    fresh = journal.NormalizationRecoveryJournal(operator_anchor=store.operator_anchor)
    assert fresh.read() is None


def test_terminal_remove_cleans_unreplayed_update_leftover(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    receipt_sha256 = _write_terminal_receipt(
        store,
        payload,
        kind="clean_abort",
        observations=observations,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    real_rename = journal._renameat2
    real_fsync = journal.os.fsync
    exchanged = False

    def exchange_then_mark(*args: object) -> None:
        nonlocal exchanged
        real_rename(*args)
        if args[-1] == journal._RENAME_EXCHANGE:
            exchanged = True

    def crash_after_exchange(fd: int) -> None:
        if exchanged:
            raise OSError("simulated process loss after update exchange")
        real_fsync(fd)

    monkeypatch.setattr(journal, "_renameat2", exchange_then_mark)
    monkeypatch.setattr(journal.os, "fsync", crash_after_exchange)
    with pytest.raises(OSError, match="update exchange"):
        store.update(expected=payload, replacement=evidenced)
    monkeypatch.setattr(journal, "_renameat2", real_rename)
    monkeypatch.setattr(journal.os, "fsync", real_fsync)
    leftover = store.path.parent / store._temporary_name(
        "update", journal._journal_bytes(evidenced)
    )
    assert leftover.exists()

    fresh = journal.NormalizationRecoveryJournal(operator_anchor=store.operator_anchor)
    fresh.remove(expected=evidenced)
    assert not leftover.exists()
    assert fresh.read() is None


def test_remove_path_substitution_leaves_readable_cleanup_pending_state(
    store: journal.NormalizationRecoveryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(store)
    store.create(payload)
    observations = _terminal_observations(payload, kind="clean_abort")
    receipt_sha256 = _write_terminal_receipt(
        store,
        payload,
        kind="clean_abort",
        observations=observations,
        completed_at="2026-07-21T12:01:00.000Z",
    )
    evidenced = store.record_terminal_evidence(
        payload,
        kind="clean_abort",
        receipt_sha256=receipt_sha256,
        **observations,
        now="2026-07-21T12:01:00.000Z",
    )
    store.update(expected=payload, replacement=evidenced)
    attacker_entry = store.operator_anchor.parent / "attacker-terminal-journal"
    attacker_entry.write_bytes(journal._journal_bytes(evidenced))
    attacker_entry.chmod(0o600)
    real_rename = journal._renameat2

    def substitute_then_exchange(*args: object) -> None:
        if args[-1] == journal._RENAME_EXCHANGE:
            os.replace(attacker_entry, store.path)
        real_rename(*args)

    monkeypatch.setattr(journal, "_renameat2", substitute_then_exchange)
    with pytest.raises(journal.NormalizationJournalError, match="exchange_invalid"):
        store.remove(expected=evidenced)

    monkeypatch.setattr(journal, "_renameat2", real_rename)
    assert store.path.exists()
    fresh = journal.NormalizationRecoveryJournal(operator_anchor=store.operator_anchor)
    cleanup = fresh.read()
    assert cleanup is not None
    assert cleanup["phase"] == "cleanup_pending"
    fresh.remove(expected=cleanup)
    assert fresh.read() is None


def test_directory_permissions_are_fail_closed(
    store: journal.NormalizationRecoveryJournal,
) -> None:
    store.path.parent.mkdir(mode=0o700)
    store.path.parent.chmod(0o755)

    with pytest.raises(journal.NormalizationJournalError, match="directory_invalid"):
        store.create(_payload(store))
