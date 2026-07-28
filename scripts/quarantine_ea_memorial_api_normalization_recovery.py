#!/usr/bin/env python3
"""Quarantine one irrecoverable memorial API normalization journal.

This is deliberately not a success path for baseline normalization.  It is an
operator-confirmed incident path for a healthy API that exactly matches its
sealed target bundle while the pre-mutation environment values are no longer
available.  The lane proves the bounded drift, writes a non-gold intent
receipt, and atomically moves (never deletes) the active journal to a private
quarantine name before writing a completion receipt.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts.deploy_ea_memorial import API_SERVICE, DeployError
    from scripts.ea_memorial_normalization_journal import (
        _RENAME_NOREPLACE,
        _renameat2,
    )
    from scripts.execute_ea_memorial_api_baseline_normalization import (
        ApiBaselineNormalizationLane,
        _canonical_bytes,
        _private_json_bytes,
        _sha256,
        _strict_json,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from deploy_ea_memorial import API_SERVICE, DeployError  # type: ignore[no-redef]
    from ea_memorial_normalization_journal import (  # type: ignore[no-redef]
        _RENAME_NOREPLACE,
        _renameat2,
    )
    from execute_ea_memorial_api_baseline_normalization import (  # type: ignore[no-redef]
        ApiBaselineNormalizationLane,
        _canonical_bytes,
        _private_json_bytes,
        _sha256,
        _strict_json,
    )


ROOT = Path(__file__).resolve().parents[1]
INTENT_CONTRACT = "ea.memorial_api_normalization_degraded_adoption_intent.v1"
COMPLETION_CONTRACT = (
    "ea.memorial_api_normalization_degraded_adoption_completion.v1"
)
ALLOWED_BASELINE_MISMATCH_DOMAINS = {
    "environment",
    "networks_and_aliases",
}


def _environment(entries: object, *, reason: str) -> dict[str, str]:
    if not isinstance(entries, list):
        raise DeployError(reason)
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, str) or "=" not in entry:
            raise DeployError(reason)
        name, value = entry.split("=", 1)
        if not name or name in result:
            raise DeployError(reason)
        result[name] = value
    return result


def _rendered_environment(
    rendered_api: Mapping[str, Any],
    image_inspection: Mapping[str, Any],
) -> dict[str, str]:
    image_config = image_inspection.get("Config")
    image_entries = (
        image_config.get("Env") if isinstance(image_config, Mapping) else None
    )
    result = _environment(
        list(image_entries or []),
        reason="degraded_adoption_image_environment_invalid",
    )
    service_environment = rendered_api.get("environment")
    if not isinstance(service_environment, Mapping):
        raise DeployError("degraded_adoption_rendered_environment_invalid")
    for name, value in service_environment.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
        ):
            raise DeployError("degraded_adoption_rendered_environment_invalid")
        result[name] = value
    return result


def _without_network_macs(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    networks = result.get("networks")
    if not isinstance(networks, Mapping):
        raise DeployError("degraded_adoption_network_identity_invalid")
    normalized: dict[str, Any] = {}
    for name, raw in networks.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            raise DeployError("degraded_adoption_network_identity_invalid")
        item = dict(raw)
        item.pop("mac_address", None)
        normalized[name] = item
    result["networks"] = normalized
    return result


def _without_dynamic_memorial_get_body(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    probes = result.get("probes")
    if not isinstance(probes, Mapping):
        raise DeployError("degraded_adoption_public_edge_identity_invalid")
    normalized = dict(probes)
    memorial_get = normalized.get("memorial_get")
    if not isinstance(memorial_get, Mapping):
        raise DeployError("degraded_adoption_public_edge_identity_invalid")
    memorial_get_without_body = dict(memorial_get)
    memorial_get_without_body.pop("body_sha256", None)
    normalized["memorial_get"] = memorial_get_without_body
    result["probes"] = normalized
    return result


def _environment_sha256(environment: Mapping[str, str]) -> str:
    canonical = [
        f"{name}={environment[name]}" for name in sorted(environment)
    ]
    return _sha256(_canonical_bytes(canonical))


def _receipt_paths(root: Path, transaction_id: str) -> tuple[Path, Path]:
    runtime = (root / ".runtime").resolve()
    return (
        runtime / f"{transaction_id}.degraded-adoption.intent.json",
        runtime / f"{transaction_id}.degraded-adoption.completed.json",
    )


def _quarantine_path(journal_path: Path, transaction_id: str, digest: str) -> Path:
    return journal_path.with_name(
        "api-baseline-normalization-quarantined-"
        f"{transaction_id}-{digest[:16]}.json"
    )


def _validate_degraded_target(
    lane: ApiBaselineNormalizationLane,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        payload.get("phase") != "rollback_failed"
        or payload.get("api_boundary_authorized") is not True
        or payload.get("api_mutation_possible") is not True
        or not isinstance(payload.get("evidence"), Mapping)
        or payload["evidence"].get("terminal") is not None
    ):
        raise DeployError("degraded_adoption_journal_state_invalid")

    repository = lane._clean_current_main()
    bundle, reseal = lane._load_recovery_bundle(payload)
    reseal()
    rendered_contract = lane._render_recovery_bundle_compose(
        payload,
        bundle,
        reseal,
    )
    rendered = lane._completed_json(
        lane._run_recovery_bundle_command(
            bundle,
            reseal,
            ["config", "--format", "json"],
        ),
        reason="degraded_adoption_compose_render_invalid",
    )
    services = rendered.get("services") if isinstance(rendered, Mapping) else None
    rendered_api = (
        services.get(API_SERVICE) if isinstance(services, Mapping) else None
    )
    if not isinstance(rendered_api, Mapping):
        raise DeployError("degraded_adoption_compose_render_invalid")

    runtime = lane._capture_runtime_evidence(str(payload.get("public_origin") or ""))
    api_raw = runtime.get("api_raw")
    if not isinstance(api_raw, Mapping):
        raise DeployError("degraded_adoption_api_runtime_invalid")
    lane._require_recovery_api_raw_binding(payload, api_raw)
    lane._require_recovery_source_image(payload)

    baselines = lane._prepared_mapping(payload, "baselines")
    baseline_api = lane._journal_projection(payload, "api_identity")
    observed_api = lane._prepared_mapping(runtime, "api_identity")
    comparison = lane.comparison_report(baseline_api, observed_api)
    mismatch_domains = set(comparison.get("mismatch_domains") or [])
    if mismatch_domains != ALLOWED_BASELINE_MISMATCH_DOMAINS:
        raise DeployError("degraded_adoption_api_mismatch_scope_invalid")
    if comparison.get("observed_topology_label_evidence") != lane._prepared_mapping(
        baselines,
        "target_api_topology_label_evidence",
    ):
        raise DeployError("degraded_adoption_target_topology_mismatch")

    baseline_network = baseline_api.get("networks_and_aliases")
    observed_network = observed_api.get("networks_and_aliases")
    if (
        not isinstance(baseline_network, Mapping)
        or not isinstance(observed_network, Mapping)
        or _without_network_macs(baseline_network)
        != _without_network_macs(observed_network)
    ):
        raise DeployError("degraded_adoption_network_delta_not_ephemeral")

    previous_image = lane._prepared_mapping(payload, "previous_image")
    image = lane._inspect_image_optional(
        str(previous_image.get("image_reference") or "")
    )
    if image is None:
        raise DeployError("degraded_adoption_image_missing")
    expected_environment = _rendered_environment(rendered_api, image)
    config = api_raw.get("Config")
    live_entries = config.get("Env") if isinstance(config, Mapping) else None
    live_environment = _environment(
        live_entries,
        reason="degraded_adoption_live_environment_invalid",
    )
    baseline_environment = baseline_api.get("environment")
    baseline_count = (
        baseline_environment.get("environment_count")
        if isinstance(baseline_environment, Mapping)
        else None
    )
    if (
        expected_environment != live_environment
        or baseline_count != len(live_environment)
    ):
        raise DeployError("degraded_adoption_target_environment_mismatch")

    cloudflared = lane._prepared_mapping(runtime, "cloudflared_identity")
    if cloudflared != lane._journal_projection(payload, "cloudflared_identity"):
        raise DeployError("degraded_adoption_cloudflared_drift")
    public_network = lane._prepared_mapping(runtime, "public_network_identity")
    baseline_public_network = lane._journal_projection(
        payload,
        "public_network_identity",
    )
    if lane._network_without_api_member(
        public_network,
        require_api_member=True,
    ) != lane._network_without_api_member(
        baseline_public_network,
        require_api_member=True,
    ):
        raise DeployError("degraded_adoption_public_network_drift")
    public_edge = lane._prepared_mapping(runtime, "public_edge_identity")
    baseline_public_edge = lane._journal_projection(
        payload,
        "public_edge_identity",
    )
    if _without_dynamic_memorial_get_body(
        public_edge
    ) != _without_dynamic_memorial_get_body(baseline_public_edge):
        raise DeployError("degraded_adoption_public_edge_drift")
    daemon = str(runtime.get("docker_daemon_identity") or "")
    if _sha256(daemon.encode("utf-8")) != baselines.get(
        "docker_daemon_identity_sha256"
    ):
        raise DeployError("degraded_adoption_docker_daemon_drift")

    protected = lane._require_protected_image(
        str(previous_image.get("rollback_tag") or ""),
        str(previous_image.get("image_id") or ""),
    )
    reseal()
    return {
        "repository_head": repository.get("head"),
        "repository_remote_main": repository.get("origin_main"),
        "journal_source_revision": payload.get("source_revision"),
        "live_image_id": api_raw.get("Image"),
        "live_image_reference": (
            config.get("Image") if isinstance(config, Mapping) else None
        ),
        "target_config_hash": rendered_contract.get("rendered_config_hash"),
        "baseline_mismatch_domains": sorted(mismatch_domains),
        "baseline_environment_sha256": baseline_environment.get(
            "environment_sha256"
        ),
        "target_environment_sha256": _environment_sha256(
            expected_environment
        ),
        "environment_count": len(expected_environment),
        "environment_count_matches_baseline": True,
        "target_environment_exact": True,
        "network_delta_ephemeral_mac_only": True,
        "target_topology_exact": True,
        "cloudflared_identity_sha256": _sha256(_canonical_bytes(cloudflared)),
        "public_network_identity_sha256": _sha256(
            _canonical_bytes(public_network)
        ),
        "public_edge_identity_sha256": _sha256(_canonical_bytes(public_edge)),
        "public_edge_delta": "memorial_get_body_sha256_only",
        "docker_daemon_identity_sha256": _sha256(daemon.encode("utf-8")),
        "protected_image_id": protected.get("Id"),
        "public_origin": payload.get("public_origin"),
    }


def _publish_receipt(
    lane: ApiBaselineNormalizationLane,
    path: Path,
    payload: Mapping[str, Any],
) -> str:
    digest, _identity = lane._publish_private_noreplace(
        path,
        _private_json_bytes(dict(payload)),
        reason="degraded_adoption_receipt",
        idempotent=True,
    )
    return digest


def _read_receipt(
    lane: ApiBaselineNormalizationLane,
    path: Path,
) -> dict[str, Any]:
    raw = lane._read_private_file(path, reason="degraded_adoption_receipt")
    return _strict_json(raw, reason="degraded_adoption_receipt_json_invalid")


def _quarantine_journal(
    lane: ApiBaselineNormalizationLane,
    *,
    journal_path: Path,
    quarantine_path: Path,
    expected_raw: bytes,
) -> None:
    state_fd, state_identity = lane._open_absolute_directory(
        journal_path.parent,
        require_private=True,
        reason="degraded_adoption_state_directory_untrusted",
    )
    try:
        observed_raw, before_identity = lane._read_private_entry_at(
            state_fd,
            journal_path.name,
            reason="degraded_adoption_active_journal",
        )
        if observed_raw != expected_raw:
            raise DeployError("degraded_adoption_active_journal_changed")
        _renameat2(
            state_fd,
            journal_path.name,
            state_fd,
            quarantine_path.name,
            _RENAME_NOREPLACE,
        )
        os.fsync(state_fd)
        archived_raw, archived_identity = lane._read_private_entry_at(
            state_fd,
            quarantine_path.name,
            reason="degraded_adoption_quarantined_journal",
        )
        if archived_raw != expected_raw or archived_identity != before_identity:
            raise DeployError("degraded_adoption_quarantine_identity_changed")
        try:
            os.stat(
                journal_path.name,
                dir_fd=state_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise DeployError("degraded_adoption_active_journal_still_present")
        os.fsync(state_fd)
        lane._revalidate_absolute_directory(
            journal_path.parent,
            state_identity,
            require_private=True,
            reason="degraded_adoption_state_directory_changed",
        )
    except DeployError:
        raise
    except OSError as exc:
        raise DeployError("degraded_adoption_quarantine_failed") from exc
    finally:
        os.close(state_fd)


def _complete_existing_quarantine(
    lane: ApiBaselineNormalizationLane,
    *,
    transaction_id: str,
    intent_path: Path,
    completion_path: Path,
) -> dict[str, Any]:
    intent = _read_receipt(lane, intent_path)
    quarantine_path = Path(str(intent.get("quarantine_path") or ""))
    journal_sha256 = str(intent.get("journal_sha256") or "")
    if (
        intent.get("contract_name") != INTENT_CONTRACT
        or intent.get("transaction_id") != transaction_id
        or not quarantine_path.is_absolute()
        or quarantine_path.parent
        != lane.journal.path.resolve().parent
        or not quarantine_path.name.startswith(
            f"api-baseline-normalization-quarantined-{transaction_id}-"
        )
    ):
        raise DeployError("degraded_adoption_intent_invalid")
    archived_raw = lane._read_private_file(
        quarantine_path,
        reason="degraded_adoption_quarantined_journal",
    )
    if _sha256(archived_raw) != journal_sha256:
        raise DeployError("degraded_adoption_quarantined_journal_changed")
    completion = {
        "contract_name": COMPLETION_CONTRACT,
        "version": 1,
        "transaction_id": transaction_id,
        "status": "degraded_target_adopted_journal_quarantined",
        "gold_claim_allowed": False,
        "normalization_pass_claim_allowed": False,
        "intent_receipt_sha256": _sha256(
            lane._read_private_file(
                intent_path,
                reason="degraded_adoption_receipt",
            )
        ),
        "journal_sha256": journal_sha256,
        "quarantine_path": str(quarantine_path),
        "completed_at": lane.now(),
    }
    if completion_path.exists():
        existing = _read_receipt(lane, completion_path)
        if (
            existing.get("contract_name") != COMPLETION_CONTRACT
            or existing.get("transaction_id") != transaction_id
            or existing.get("journal_sha256") != journal_sha256
            or existing.get("quarantine_path") != str(quarantine_path)
            or existing.get("gold_claim_allowed") is not False
        ):
            raise DeployError("degraded_adoption_completion_invalid")
        return existing
    _publish_receipt(lane, completion_path, completion)
    return completion


def execute(
    *,
    root: Path,
    operation_id: str,
    transaction_id: str,
    apply: bool,
) -> dict[str, Any]:
    lane = ApiBaselineNormalizationLane(
        plan_path=Path("/recovery-inputs-not-consulted/plan.json"),
        bundle_parent=Path("/recovery-inputs-not-consulted/bundles"),
        public_origin="https://recovery-inputs-not-consulted.invalid",
        root=root,
        env={"EA_DEPLOYMENT_ID": operation_id},
    )
    intent_path, completion_path = _receipt_paths(root, transaction_id)
    with lane._global_lock():
        lane._require_joint_recovery_absent()
        payload = lane.journal.read()
        if payload is None:
            if not intent_path.exists():
                raise DeployError("degraded_adoption_active_journal_missing")
            if not apply:
                intent = _read_receipt(lane, intent_path)
                return {
                    "status": "already_quarantined",
                    "transaction_id": transaction_id,
                    "gold_claim_allowed": False,
                    "quarantine_path": intent.get("quarantine_path"),
                }
            return _complete_existing_quarantine(
                lane,
                transaction_id=transaction_id,
                intent_path=intent_path,
                completion_path=completion_path,
            )
        if payload.get("transaction_id") != transaction_id:
            raise DeployError("degraded_adoption_transaction_id_mismatch")
        journal_path = Path(str(payload.get("recovery_journal_path") or ""))
        if journal_path.resolve() != lane.journal.path.resolve():
            raise DeployError("degraded_adoption_journal_path_mismatch")
        journal_raw = lane._read_private_file(
            journal_path,
            reason="degraded_adoption_active_journal",
        )
        journal_sha256 = _sha256(journal_raw)
        quarantine_path = _quarantine_path(
            journal_path,
            transaction_id,
            journal_sha256,
        )
        evidence_before = _validate_degraded_target(lane, payload)
        if not apply:
            return {
                "status": "validated_dry_run",
                "transaction_id": transaction_id,
                "gold_claim_allowed": False,
                "normalization_pass_claim_allowed": False,
                "quarantine_path": str(quarantine_path),
                "evidence": evidence_before,
            }
        intent = {
            "contract_name": INTENT_CONTRACT,
            "version": 1,
            "transaction_id": transaction_id,
            "status": "degraded_target_quarantine_authorized",
            "reason": "pre_mutation_environment_values_no_longer_recoverable",
            "gold_claim_allowed": False,
            "normalization_pass_claim_allowed": False,
            "service_scope": [API_SERVICE],
            "docker_mutations": 0,
            "journal_sha256": journal_sha256,
            "active_journal_path": str(journal_path),
            "quarantine_path": str(quarantine_path),
            "evidence": evidence_before,
            "source_journal_updated_at": payload.get("updated_at"),
        }
        if intent_path.exists():
            existing_intent = _read_receipt(lane, intent_path)
            if existing_intent != intent:
                raise DeployError("degraded_adoption_intent_changed")
        else:
            _publish_receipt(lane, intent_path, intent)
        evidence_after = _validate_degraded_target(lane, payload)
        if evidence_after != evidence_before:
            raise DeployError("degraded_adoption_runtime_changed")
        current_raw = lane._read_private_file(
            journal_path,
            reason="degraded_adoption_active_journal",
        )
        if current_raw != journal_raw:
            raise DeployError("degraded_adoption_active_journal_changed")
        _quarantine_journal(
            lane,
            journal_path=journal_path,
            quarantine_path=quarantine_path,
            expected_raw=journal_raw,
        )
        return _complete_existing_quarantine(
            lane,
            transaction_id=transaction_id,
            intent_path=intent_path,
            completion_path=completion_path,
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and quarantine an irrecoverable memorial API "
            "normalization journal without claiming normalization pass."
        )
    )
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--confirm-transaction-id", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = execute(
            root=ROOT,
            operation_id=args.operation_id,
            transaction_id=args.confirm_transaction_id,
            apply=args.apply,
        )
    except (DeployError, OSError, ValueError) as exc:
        print(f"Degraded adoption failed: {exc}", file=os.sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
