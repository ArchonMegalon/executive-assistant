#!/usr/bin/env python3
"""Materialize a non-authoritative plan for repairing split API baseline labels.

This module is intentionally incapable of executing the repair.  It does not
inspect Docker, invoke Compose or Git, read environment files, authorize a
mutation, or write the canonical recovery journal. Its only output is
a private plan that records the exact inputs a future independently reviewed
normalizer would have to prove.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


PLAN_CONTRACT = "ea.memorial_api_baseline_normalization_plan.v2"
PLAN_VERSION = 2
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REFERENCE_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*:"
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$"
)
PLAN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
UTC_MILLISECOND_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
BASELINE_LAYOUT_SPLIT = "split"
BASELINE_LAYOUT_COLOCATED_LEGACY_ENV = "colocated-legacy-env"
BASELINE_LAYOUTS = frozenset(
    {BASELINE_LAYOUT_SPLIT, BASELINE_LAYOUT_COLOCATED_LEGACY_ENV}
)
SPLIT_BASELINE_CONDITION = "exact_split_compose_label_baseline"
COLOCATED_LEGACY_ENV_CONDITION = (
    "exact_colocated_canonical_compose_legacy_environment_label_baseline"
)
COLOCATED_LEGACY_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.memorial.yml",
    "docker-compose.whatsapp-web-session.yml",
    "docker-compose.cloudflared.yml",
)

TOP_LEVEL_KEYS = frozenset(
    {
        "activation_condition",
        "authority",
        "contract_name",
        "execution",
        "generated_at",
        "identity_requirements",
        "ingress_mutation_scope",
        "mutation_authority",
        "mutation_performed",
        "normalization_completed",
        "plan_id",
        "promotion_authority",
        "prohibited_actions",
        "recovery_requirements",
        "secrecy",
        "service_scope",
        "source_requirements",
        "status",
        "version",
    }
)
ACTIVATION_KEYS = frozenset(
    {
        "condition",
        "external_config_root",
        "ordered_external_config_files",
        "recorded_environment_expectation",
        "recorded_working_dir",
        "trusted_environment_files",
        "trusted_environment_root",
        "verification_status",
    }
)
SOURCE_KEYS = frozenset(
    {
        "ancestry_ref",
        "expected_image_id",
        "expected_image_reference",
        "expected_revision",
        "materialization_source",
        "mutable_external_config_bytes_accepted",
        "required_equalities",
        "verification_status",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "allowed_differences",
        "required_equal_labels",
        "required_identity_domains",
        "verification_status",
    }
)
AUTHORITY_KEYS = frozenset(
    {
        "executor_implemented",
        "independent_review_required",
        "journal_contract_review_required",
    }
)
EXECUTION_KEYS = frozenset(
    {
        "available",
        "blocker",
        "compose_invocations",
        "docker_mutations",
        "git_mutations",
        "http_requests",
        "recovery_journal_written",
    }
)
SECRECY_KEYS = frozenset(
    {
        "environment_values_included",
        "external_file_contents_included",
        "private_output_required",
    }
)
RECOVERY_KEYS = frozenset(
    {
        "distinct_crash_journal_required",
        "normal_deploy_blocked_while_recovery_active",
        "retained_immutable_bundle_required",
        "verification_status",
    }
)
ENVIRONMENT_FILE_KEYS = frozenset(
    {"path", "requirement", "verification_status"}
)
REQUIRED_SOURCE_EQUALITIES = [
    "live_environment.EA_SOURCE_REVISION",
    "image_label.org.opencontainers.image.revision",
    "git_commit",
]
REQUIRED_IDENTITY_DOMAINS = [
    "image",
    "environment",
    "process",
    "healthcheck",
    "restart_policy",
    "user_and_groups",
    "capabilities_and_security_options",
    "privileged_and_read_only_posture",
    "resource_limits",
    "ports",
    "logging",
    "mounts",
    "networks_and_aliases",
    "public_ingress_network",
    "non_compose_labels",
    "cloudflared_container",
    "public_get_and_head_fingerprints",
]
ALLOWED_IDENTITY_DIFFERENCES = [
    "com.docker.compose.project.working_dir",
    "com.docker.compose.project.config_files",
    "com.docker.compose.project.environment_file",
]
REQUIRED_EQUAL_LABELS = ["com.docker.compose.config-hash"]
PROHIBITED_ACTIONS = [
    "build_or_pull_image",
    "copy_environment_values",
    "execute_external_compose_bytes",
    "invoke_docker_or_compose",
    "mutate_api_or_ingress",
    "write_canonical_recovery_journal",
]


class PlanError(ValueError):
    """The requested plan is malformed or could imply false authority."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _absolute_normal_path(raw: str, *, label: str) -> Path:
    if not raw or "\x00" in raw or raw.startswith("~"):
        raise PlanError(f"{label}_invalid")
    if not os.path.isabs(raw) or os.path.normpath(raw) != raw:
        raise PlanError(f"{label}_must_be_absolute_normalized")
    path = Path(raw)
    if path == Path("/") or ".." in path.parts:
        raise PlanError(f"{label}_invalid")
    return path


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _is_canonical_utc_millisecond_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not UTC_MILLISECOND_PATTERN.fullmatch(value):
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return (
        parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" == value
    )


def _require_exact_keys(
    payload: Mapping[str, Any], expected: frozenset[str], *, label: str
) -> None:
    if set(payload) != expected:
        raise PlanError(f"{label}_schema_invalid")


def build_plan(
    *,
    plan_id: str,
    recorded_working_dir: str,
    external_config_root: str,
    trusted_environment_root: str,
    expected_revision: str,
    expected_image_reference: str,
    expected_image_id: str,
    baseline_layout: str = BASELINE_LAYOUT_SPLIT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a plan from explicit assertions without touching their targets."""
    if not PLAN_ID_PATTERN.fullmatch(plan_id):
        raise PlanError("plan_id_invalid")
    recorded_root = _absolute_normal_path(
        recorded_working_dir, label="recorded_working_dir"
    )
    external_root = _absolute_normal_path(
        external_config_root, label="external_config_root"
    )
    environment_root = _absolute_normal_path(
        trusted_environment_root, label="trusted_environment_root"
    )
    if baseline_layout not in BASELINE_LAYOUTS:
        raise PlanError("baseline_layout_invalid")
    colocated_legacy = baseline_layout == BASELINE_LAYOUT_COLOCATED_LEGACY_ENV
    if recorded_root == external_root and not colocated_legacy:
        raise PlanError("split_label_roots_must_differ")
    if recorded_root != external_root and colocated_legacy:
        raise PlanError("colocated_label_roots_must_match")
    if recorded_root == environment_root:
        raise PlanError("recorded_and_trusted_environment_roots_must_differ")
    external_files = [
        external_root / name
        for name in (
            COLOCATED_LEGACY_COMPOSE_FILES
            if colocated_legacy
            else ("docker-compose.yml", "docker-compose.memorial.yml")
        )
    ]
    environment_files = [environment_root / ".env", environment_root / ".env.local"]
    if (
        not colocated_legacy
        and any(_is_within(path, recorded_root) for path in external_files)
    ):
        raise PlanError("external_config_files_inside_recorded_root")
    if any(_is_within(path, recorded_root) for path in environment_files):
        raise PlanError("trusted_environment_files_inside_recorded_root")
    if not SOURCE_REVISION_PATTERN.fullmatch(expected_revision):
        raise PlanError("expected_revision_invalid")
    if not IMAGE_REFERENCE_PATTERN.fullmatch(expected_image_reference):
        raise PlanError("expected_image_reference_invalid")
    if not IMAGE_ID_PATTERN.fullmatch(expected_image_id):
        raise PlanError("expected_image_id_invalid")

    payload: dict[str, Any] = {
        "contract_name": PLAN_CONTRACT,
        "version": PLAN_VERSION,
        "status": "plan_only",
        "generated_at": generated_at or _utc_now(),
        "plan_id": plan_id,
        "promotion_authority": False,
        "mutation_authority": False,
        "mutation_performed": False,
        "normalization_completed": False,
        "service_scope": ["ea-api"],
        "ingress_mutation_scope": [],
        "activation_condition": {
            "condition": (
                COLOCATED_LEGACY_ENV_CONDITION
                if colocated_legacy
                else SPLIT_BASELINE_CONDITION
            ),
            "recorded_working_dir": str(recorded_root),
            "recorded_environment_expectation": (
                "legacy_private_file_present_unread"
                if colocated_legacy
                else "missing"
            ),
            "external_config_root": str(external_root),
            "ordered_external_config_files": [
                str(path) for path in external_files
            ],
            "trusted_environment_root": str(environment_root),
            "trusted_environment_files": [
                {
                    "path": str(environment_root / ".env"),
                    "requirement": "required_no_follow_private_copy",
                    "verification_status": "required_unverified",
                },
                {
                    "path": str(environment_root / ".env.local"),
                    "requirement": "optional_no_follow_private_copy",
                    "verification_status": "required_unverified_if_present",
                },
            ],
            "verification_status": "required_unverified",
        },
        "source_requirements": {
            "expected_revision": expected_revision,
            "expected_image_reference": expected_image_reference,
            "expected_image_id": expected_image_id,
            "required_equalities": list(REQUIRED_SOURCE_EQUALITIES),
            "ancestry_ref": "origin/main",
            "materialization_source": "immutable_git_objects_at_exact_revision",
            "mutable_external_config_bytes_accepted": False,
            "verification_status": "required_unverified",
        },
        "identity_requirements": {
            "required_identity_domains": list(REQUIRED_IDENTITY_DOMAINS),
            "allowed_differences": list(ALLOWED_IDENTITY_DIFFERENCES),
            "required_equal_labels": list(REQUIRED_EQUAL_LABELS),
            "verification_status": "required_unverified",
        },
        "authority": {
            "executor_implemented": False,
            "independent_review_required": True,
            "journal_contract_review_required": True,
        },
        "recovery_requirements": {
            "distinct_crash_journal_required": True,
            "normal_deploy_blocked_while_recovery_active": True,
            "retained_immutable_bundle_required": True,
            "verification_status": "required_unverified",
        },
        "execution": {
            "available": False,
            "blocker": "normalization_executor_and_recovery_journal_not_implemented",
            "docker_mutations": 0,
            "compose_invocations": 0,
            "git_mutations": 0,
            "http_requests": 0,
            "recovery_journal_written": False,
        },
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "secrecy": {
            "environment_values_included": False,
            "external_file_contents_included": False,
            "private_output_required": True,
        },
    }
    validate_plan_payload(payload)
    return payload


def validate_plan_payload(payload: Mapping[str, Any]) -> None:
    """Validate the exact non-authoritative v1 plan schema and invariants."""
    _require_exact_keys(payload, TOP_LEVEL_KEYS, label="plan")
    activation = payload.get("activation_condition")
    source = payload.get("source_requirements")
    identity = payload.get("identity_requirements")
    authority = payload.get("authority")
    execution = payload.get("execution")
    recovery = payload.get("recovery_requirements")
    secrecy = payload.get("secrecy")
    if not all(
        isinstance(item, Mapping)
        for item in (
            activation,
            source,
            identity,
            authority,
            execution,
            recovery,
            secrecy,
        )
    ):
        raise PlanError("plan_nested_schema_invalid")
    _require_exact_keys(activation, ACTIVATION_KEYS, label="activation")
    _require_exact_keys(source, SOURCE_KEYS, label="source")
    _require_exact_keys(identity, IDENTITY_KEYS, label="identity")
    _require_exact_keys(authority, AUTHORITY_KEYS, label="authority")
    _require_exact_keys(execution, EXECUTION_KEYS, label="execution")
    _require_exact_keys(recovery, RECOVERY_KEYS, label="recovery")
    _require_exact_keys(secrecy, SECRECY_KEYS, label="secrecy")
    environment_files = activation.get("trusted_environment_files")
    if (
        not isinstance(environment_files, list)
        or len(environment_files) != 2
        or any(not isinstance(item, Mapping) for item in environment_files)
    ):
        raise PlanError("trusted_environment_files_schema_invalid")
    for item in environment_files:
        _require_exact_keys(
            item, ENVIRONMENT_FILE_KEYS, label="trusted_environment_file"
        )
    try:
        recorded_root = _absolute_normal_path(
            str(activation.get("recorded_working_dir") or ""),
            label="recorded_working_dir",
        )
        external_root = _absolute_normal_path(
            str(activation.get("external_config_root") or ""),
            label="external_config_root",
        )
        environment_root = _absolute_normal_path(
            str(activation.get("trusted_environment_root") or ""),
            label="trusted_environment_root",
        )
    except (TypeError, ValueError) as exc:
        raise PlanError("plan_path_binding_invalid") from exc
    condition = activation.get("condition")
    colocated_legacy = condition == COLOCATED_LEGACY_ENV_CONDITION
    if condition not in {
        SPLIT_BASELINE_CONDITION,
        COLOCATED_LEGACY_ENV_CONDITION,
    }:
        raise PlanError("plan_authority_invariant_invalid")
    expected_external_files = [
        str(external_root / name)
        for name in (
            COLOCATED_LEGACY_COMPOSE_FILES
            if colocated_legacy
            else ("docker-compose.yml", "docker-compose.memorial.yml")
        )
    ]
    expected_environment_files = [
        {
            "path": str(environment_root / ".env"),
            "requirement": "required_no_follow_private_copy",
            "verification_status": "required_unverified",
        },
        {
            "path": str(environment_root / ".env.local"),
            "requirement": "optional_no_follow_private_copy",
            "verification_status": "required_unverified_if_present",
        },
    ]
    exact_zero_counters = (
        execution.get("docker_mutations"),
        execution.get("compose_invocations"),
        execution.get("git_mutations"),
        execution.get("http_requests"),
    )
    if (
        payload.get("contract_name") != PLAN_CONTRACT
        or type(payload.get("version")) is not int
        or payload.get("version") != PLAN_VERSION
        or payload.get("status") != "plan_only"
        or payload.get("promotion_authority") is not False
        or payload.get("mutation_authority") is not False
        or payload.get("mutation_performed") is not False
        or payload.get("normalization_completed") is not False
        or payload.get("service_scope") != ["ea-api"]
        or payload.get("ingress_mutation_scope") != []
        or not isinstance(payload.get("plan_id"), str)
        or not PLAN_ID_PATTERN.fullmatch(str(payload.get("plan_id")))
        or not _is_canonical_utc_millisecond_timestamp(
            payload.get("generated_at")
        )
        or activation.get("recorded_environment_expectation")
        != (
            "legacy_private_file_present_unread"
            if colocated_legacy
            else "missing"
        )
        or activation.get("verification_status") != "required_unverified"
        or (
            recorded_root != external_root
            if colocated_legacy
            else recorded_root == external_root
        )
        or recorded_root == environment_root
        or any(
            _is_within(path, recorded_root)
            for path in (
                environment_root / ".env",
                environment_root / ".env.local",
            )
        )
        or (
            not colocated_legacy
            and any(
                _is_within(external_root / name, recorded_root)
                for name in ("docker-compose.yml", "docker-compose.memorial.yml")
            )
        )
        or activation.get("ordered_external_config_files")
        != expected_external_files
        or environment_files != expected_environment_files
        or source.get("verification_status") != "required_unverified"
        or not SOURCE_REVISION_PATTERN.fullmatch(
            str(source.get("expected_revision") or "")
        )
        or not IMAGE_REFERENCE_PATTERN.fullmatch(
            str(source.get("expected_image_reference") or "")
        )
        or not IMAGE_ID_PATTERN.fullmatch(
            str(source.get("expected_image_id") or "")
        )
        or source.get("required_equalities") != REQUIRED_SOURCE_EQUALITIES
        or source.get("ancestry_ref") != "origin/main"
        or source.get("materialization_source")
        != "immutable_git_objects_at_exact_revision"
        or source.get("mutable_external_config_bytes_accepted") is not False
        or identity.get("required_identity_domains")
        != REQUIRED_IDENTITY_DOMAINS
        or identity.get("allowed_differences")
        != ALLOWED_IDENTITY_DIFFERENCES
        or identity.get("required_equal_labels") != REQUIRED_EQUAL_LABELS
        or identity.get("verification_status") != "required_unverified"
        or authority.get("executor_implemented") is not False
        or authority.get("independent_review_required") is not True
        or authority.get("journal_contract_review_required") is not True
        or recovery.get("distinct_crash_journal_required") is not True
        or recovery.get("normal_deploy_blocked_while_recovery_active")
        is not True
        or recovery.get("retained_immutable_bundle_required") is not True
        or recovery.get("verification_status") != "required_unverified"
        or execution.get("available") is not False
        or execution.get("blocker")
        != "normalization_executor_and_recovery_journal_not_implemented"
        or any(type(value) is not int or value != 0 for value in exact_zero_counters)
        or execution.get("recovery_journal_written") is not False
        or secrecy.get("environment_values_included") is not False
        or secrecy.get("external_file_contents_included") is not False
        or secrecy.get("private_output_required") is not True
        or payload.get("prohibited_actions") != PROHIBITED_ACTIONS
    ):
        raise PlanError("plan_authority_invariant_invalid")


def _write_private_plan(path: Path, payload: Mapping[str, Any]) -> None:
    raw_path = _absolute_normal_path(str(path), label="output")
    parent = raw_path.parent
    required_flag_names = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flag_names):
        raise PlanError("required_secure_open_primitive_missing")
    if os.open not in os.supports_dir_fd:
        raise PlanError("required_dir_fd_open_primitive_missing")
    parent_path_stat = os.lstat(parent)
    parent_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_fd = os.open(parent, parent_flags)
    output_fd: int | None = None
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    try:
        parent_fd_stat = os.fstat(parent_fd)
        parent_path_after_open = os.lstat(parent)
        parent_identity = (parent_fd_stat.st_dev, parent_fd_stat.st_ino)
        if (
            not stat.S_ISDIR(parent_fd_stat.st_mode)
            or stat.S_ISLNK(parent_path_stat.st_mode)
            or parent_fd_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_fd_stat.st_mode) != 0o700
            or (parent_path_stat.st_dev, parent_path_stat.st_ino)
            != parent_identity
            or (parent_path_after_open.st_dev, parent_path_after_open.st_ino)
            != parent_identity
        ):
            raise PlanError("output_parent_not_private")
        output_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        output_flags |= os.O_CLOEXEC | os.O_NOFOLLOW
        output_fd = os.open(
            raw_path.name,
            output_flags,
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(output_fd, 0o600)
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(output_fd, remaining)
            if written <= 0:  # pragma: no cover - kernel write invariant
                raise PlanError("output_write_failed")
            remaining = remaining[written:]
        os.fsync(output_fd)
        file_fd_stat = os.fstat(output_fd)
        file_path_stat = os.lstat(raw_path)
        if (
            not stat.S_ISREG(file_fd_stat.st_mode)
            or stat.S_ISLNK(file_path_stat.st_mode)
            or file_fd_stat.st_uid != os.geteuid()
            or file_fd_stat.st_nlink != 1
            or stat.S_IMODE(file_fd_stat.st_mode) != 0o600
            or (file_fd_stat.st_dev, file_fd_stat.st_ino)
            != (file_path_stat.st_dev, file_path_stat.st_ino)
        ):
            raise PlanError("output_identity_invalid")
        os.fsync(parent_fd)
    finally:
        if output_fd is not None:
            os.close(output_fd)
        os.close(parent_fd)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Write a private, plan-only ea-api baseline-normalization contract; "
            "this command cannot execute normalization."
        )
    )
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--recorded-working-dir", required=True)
    parser.add_argument("--external-config-root", required=True)
    parser.add_argument("--trusted-environment-root", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-image-reference", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument(
        "--baseline-layout",
        choices=sorted(BASELINE_LAYOUTS),
        default=BASELINE_LAYOUT_SPLIT,
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        plan = build_plan(
            plan_id=args.plan_id,
            recorded_working_dir=args.recorded_working_dir,
            external_config_root=args.external_config_root,
            trusted_environment_root=args.trusted_environment_root,
            expected_revision=args.expected_revision,
            expected_image_reference=args.expected_image_reference,
            expected_image_id=args.expected_image_id,
            baseline_layout=args.baseline_layout,
        )
        _write_private_plan(args.output, plan)
    except (OSError, PlanError) as exc:
        print(f"baseline-normalization planning failed: {exc}", file=os.sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "contract_name": PLAN_CONTRACT,
                "mutation_authority": False,
                "output": str(args.output),
                "status": "plan_only",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
