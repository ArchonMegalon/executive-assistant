#!/usr/bin/env python3
"""Verify the bounded EA Chummer lived-system observation receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from materialize_chummer_lived_system_observation import (
        ALLOWED_STATUSES,
        CHECK_KEYS,
        DEFAULT_OUTPUT,
        ROOT,
        required_input_keys,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by package-style test imports
    from scripts.materialize_chummer_lived_system_observation import (
        ALLOWED_STATUSES,
        CHECK_KEYS,
        DEFAULT_OUTPUT,
        ROOT,
        required_input_keys,
    )


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ZERO_ACTION_KEYS = ("network_actions", "provider_actions", "docker_actions", "source_mutations")


def _load_receipt(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, [f"receipt missing or invalid: {path} ({exc.__class__.__name__})"]
    if not isinstance(payload, dict):
        return {}, ["receipt root must be a JSON object"]
    return payload, []


def _status_values(value: Any, *, prefix: str = "$") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}"
            if key == "status":
                found.append((child, item))
            found.extend(_status_values(item, prefix=child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_status_values(item, prefix=f"{prefix}[{index}]"))
    return found


def _forbidden_authority_keys(value: Any, *, prefix: str = "$") -> list[str]:
    forbidden = {
        "blocker_decision",
        "blocker_status",
        "gold_claim_allowed",
        "promotion_authorized",
        "release_authorized",
    }
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}"
            if key in forbidden:
                found.append(child)
            found.extend(_forbidden_authority_keys(item, prefix=child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_forbidden_authority_keys(item, prefix=f"{prefix}[{index}]"))
    return found


def _expected_status(checks: list[dict[str, Any]]) -> str:
    values = [str(item.get("status") or "") for item in checks]
    if "invalid_inputs" in values:
        return "invalid_inputs"
    if "attention_required" in values:
        return "attention_required"
    return "consistent"


def verify(path: Path) -> list[str]:
    receipt, issues = _load_receipt(path)
    if issues:
        return issues

    if receipt.get("contract_name") != "ea.chummer_lived_system_observation":
        issues.append("contract_name must be ea.chummer_lived_system_observation")
    if receipt.get("contract_version") != "1.0.0":
        issues.append("contract_version must be 1.0.0")
    if receipt.get("authoritative") is not False:
        issues.append("authoritative must be false")
    if "release_decision" not in receipt or receipt.get("release_decision") is not None:
        issues.append("release_decision must be present and null")

    generated_at = receipt.get("generated_at_utc")
    if not isinstance(generated_at, str) or not generated_at:
        issues.append("generated_at_utc must be a non-empty string")
    else:
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            issues.append("generated_at_utc must be an ISO-8601 timestamp")

    for location, value in _status_values(receipt):
        if value not in ALLOWED_STATUSES:
            issues.append(f"{location} uses unsupported status {value!r}")

    forbidden_keys = _forbidden_authority_keys(receipt)
    if forbidden_keys:
        issues.append("authority-bearing fields are forbidden: " + ", ".join(forbidden_keys))

    scope = receipt.get("scope")
    if not isinstance(scope, dict):
        issues.append("scope must be an object")
    else:
        if scope.get("observation_only") is not True:
            issues.append("scope.observation_only must be true")
        if scope.get("does_not_clear_or_reopen_blockers") is not True:
            issues.append("scope must prohibit blocker clearance/reopening")
        if scope.get("does_not_publish_or_promote_releases") is not True:
            issues.append("scope must prohibit release publication/promotion")

    execution_policy = receipt.get("execution_policy")
    if not isinstance(execution_policy, dict):
        issues.append("execution_policy must be an object")
    else:
        if execution_policy.get("filesystem_input_mode") != "read_only":
            issues.append("filesystem_input_mode must be read_only")
        if execution_policy.get("output_write_mode") != "atomic_receipt_only":
            issues.append("output_write_mode must be atomic_receipt_only")
        for key in ZERO_ACTION_KEYS:
            if execution_policy.get(key) != 0:
                issues.append(f"execution_policy.{key} must be zero")

    boundaries = receipt.get("authority_boundaries")
    if not isinstance(boundaries, dict):
        issues.append("authority_boundaries must be an object")
    else:
        if boundaries.get("ea_is_release_authority") is not False:
            issues.append("EA must not be represented as release authority")
        if boundaries.get("ea_is_blocker_authority") is not False:
            issues.append("EA must not be represented as blocker authority")

    bindings_value = receipt.get("input_bindings")
    bindings = bindings_value if isinstance(bindings_value, list) else []
    if not isinstance(bindings_value, list):
        issues.append("input_bindings must be a list")
    binding_keys = [str(item.get("key") or "") for item in bindings if isinstance(item, dict)]
    if tuple(binding_keys) != required_input_keys():
        issues.append("input binding keys/order do not match the required owner-input contract")

    binding_errors = 0
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            issues.append(f"input_bindings[{index}] must be an object")
            continue
        key = str(binding.get("key") or f"index-{index}")
        owner = binding.get("owner")
        if not isinstance(owner, str) or not owner:
            issues.append(f"input binding {key} has no owner")
        path_value = binding.get("path")
        if not isinstance(path_value, str) or not path_value:
            issues.append(f"input binding {key} has no path")
            continue
        source_path = Path(path_value)
        if not source_path.is_absolute():
            issues.append(f"input binding {key} path must be absolute")

        error = binding.get("error")
        if error:
            binding_errors += 1
            if binding.get("sha256") is not None and not SHA256_PATTERN.fullmatch(str(binding.get("sha256"))):
                issues.append(f"input binding {key} has malformed SHA-256")
            continue

        expected_digest = binding.get("sha256")
        expected_size = binding.get("size_bytes")
        if not isinstance(expected_digest, str) or not SHA256_PATTERN.fullmatch(expected_digest):
            issues.append(f"input binding {key} has malformed SHA-256")
            continue
        if not isinstance(expected_size, int) or expected_size < 0:
            issues.append(f"input binding {key} has invalid size_bytes")
            continue
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            issues.append(f"hash-bound input {key} is unreadable ({exc.__class__.__name__})")
            continue
        actual_digest = hashlib.sha256(raw).hexdigest()
        if actual_digest != expected_digest:
            issues.append(f"hash-bound input {key} content changed")
        if len(raw) != expected_size:
            issues.append(f"hash-bound input {key} size changed")

    checks_value = receipt.get("checks")
    checks = checks_value if isinstance(checks_value, list) else []
    if not isinstance(checks_value, list):
        issues.append("checks must be a list")
    check_objects = [item for item in checks if isinstance(item, dict)]
    check_keys = tuple(str(item.get("key") or "") for item in check_objects)
    if check_keys != CHECK_KEYS:
        issues.append("check keys/order do not match the observation contract")
    if len(check_objects) != len(checks):
        issues.append("every check must be an object")

    expected_status = _expected_status(check_objects)
    if receipt.get("status") != expected_status:
        issues.append(
            f"overall status {receipt.get('status')!r} does not aggregate to {expected_status!r}"
        )
    if binding_errors and receipt.get("status") != "invalid_inputs":
        issues.append("input binding errors require invalid_inputs overall posture")

    summary = receipt.get("summary")
    if not isinstance(summary, dict):
        issues.append("summary must be an object")
    else:
        check_statuses = [str(item.get("status") or "") for item in check_objects]
        findings = receipt.get("findings")
        finding_count = len(findings) if isinstance(findings, list) else -1
        expected_summary = {
            "input_count": len(bindings),
            "check_count": len(checks),
            "consistent_check_count": check_statuses.count("consistent"),
            "attention_required_check_count": check_statuses.count("attention_required"),
            "invalid_input_check_count": check_statuses.count("invalid_inputs"),
            "finding_count": finding_count,
        }
        for key, value in expected_summary.items():
            if summary.get(key) != value:
                issues.append(f"summary.{key} must be {value}")

    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        pass
    else:
        if mode != 0o600:
            issues.append(f"receipt mode must be 0600, observed {mode:04o}")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the non-authoritative Chummer lived-system observation receipt."
    )
    parser.add_argument("--receipt", type=Path, default=ROOT / DEFAULT_OUTPUT)
    args = parser.parse_args()

    issues = verify(args.receipt.expanduser().resolve(strict=False))
    if issues:
        print(json.dumps({"status": "invalid_inputs", "issues": issues}, indent=2, sort_keys=True))
        return 1
    receipt, _ = _load_receipt(args.receipt)
    print(
        json.dumps(
            {
                "status": receipt.get("status"),
                "receipt": args.receipt.as_posix(),
                "contract_name": receipt.get("contract_name"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
