#!/usr/bin/env python3
"""Private crash-recovery journal for API baseline normalization.

This module deliberately has no Docker, Git, HTTP, or deployment authority.  It
only validates and durably stores the secret-free facts a separate executor
needs to recover an interrupted ``ea-api`` label normalization transaction.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts.ea_memorial_recovery_interlock import (
        NORMALIZATION_RECOVERY_JOURNAL_FILENAME,
        NORMALIZATION_RECOVERY_STATE_DIRECTORY,
        default_normalization_recovery_journal_path,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from ea_memorial_recovery_interlock import (  # type: ignore[no-redef]
        NORMALIZATION_RECOVERY_JOURNAL_FILENAME,
        NORMALIZATION_RECOVERY_STATE_DIRECTORY,
        default_normalization_recovery_journal_path,
    )

try:
    from scripts import ea_memorial_runtime_identity as runtime_identity
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import ea_memorial_runtime_identity as runtime_identity  # type: ignore[no-redef]


CONTRACT_NAME = "ea.memorial_api_baseline_normalization_recovery.v1"
CONTRACT_VERSION = 1
MAX_JOURNAL_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 50_000
MAX_JSON_STRING_BYTES = 256 * 1024
NORMALIZATION_OVERRIDE_FILENAME = "docker-compose.api-baseline-normalization.yml"
SUPPORTED_RETAINED_COMPOSE_LAYOUTS = (
    (
        "docker-compose.yml",
        "docker-compose.memorial.yml",
        NORMALIZATION_OVERRIDE_FILENAME,
    ),
    (
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.memorial.yml",
        "docker-compose.cloudflared.yml",
        NORMALIZATION_OVERRIDE_FILENAME,
    ),
)
RETAINED_BUNDLE_MANIFEST_FILENAME = "baseline-bundle-manifest.json"
TERMINAL_RECEIPT_CONTRACT_NAME = "ea.memorial_api_baseline_normalization.v2"
TERMINAL_RECEIPT_VERSION = 2
BUNDLE_RECOVERY_SEAL_CONTRACT_NAME = "ea.memorial_api_baseline_bundle_recovery_seal.v1"
PUBLIC_EDGE_IDENTITY_SCHEMA = "ea.memorial_public_edge_identity.v1"
TERMINAL_RECEIPT_STATUS = {
    "clean_abort": "pre_mutation_aborted_verified",
    "durable_commit": "pass",
    "verified_recovery": "interrupted_transaction_recovered",
    "verified_forward_recovery": "interrupted_transaction_forward_recovered",
}
PUBLIC_EDGE_PROBES = (
    ("version", "/version"),
    ("memorial", "/memorials/manfred"),
    ("memorial_manifest", "/memorials/manfred.json"),
    (
        "spatial_landing",
        "/tours/360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6",
    ),
    (
        "spatial_manifest",
        "/tours/360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6.json",
    ),
    (
        "spatial_viewer",
        "/tours/viewer/360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6/"
        "generated-reconstruction/viewer.html",
    ),
)
EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
PHASES = frozenset(
    {
        "prepared",
        "protect_previous_image_possible",
        "api_mutation_possible",
        "commit_pending",
        "rollback_in_progress",
        "rollback_failed",
        "cleanup_pending",
    }
)
_TRANSITIONS = {
    "prepared": frozenset({"protect_previous_image_possible", "cleanup_pending"}),
    "protect_previous_image_possible": frozenset(
        {"api_mutation_possible", "rollback_in_progress"}
    ),
    "api_mutation_possible": frozenset({"commit_pending", "rollback_in_progress"}),
    "commit_pending": frozenset({"cleanup_pending"}),
    "rollback_in_progress": frozenset(
        {"rollback_in_progress", "rollback_failed", "cleanup_pending"}
    ),
    "rollback_failed": frozenset({"rollback_in_progress"}),
    "cleanup_pending": frozenset(),
}
_TRANSACTION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}")
_IMAGE_REPOSITORY_PATTERN = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
)
_IMAGE_TAG_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "password",
    "secret",
    "token",
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(?:authorization|credential|password|private[_-]?key|secret|token|"
    r"api[_-]?key)\s*(?:=|:)\s*[^\s,;]+"
)
_SECRET_OPTION_PATTERN = re.compile(
    r"(?i)--(?:authorization|credential|password|private-key|secret|token|"
    r"api-key)(?:=|\s+)\S+"
)
_AUTH_VALUE_PATTERN = re.compile(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]+")
_JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\."
    r"[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])"
)
_OPAQUE_SECRET_PATTERN = re.compile(r"[A-Za-z0-9_+/=-]{80,}")


class NormalizationJournalError(RuntimeError):
    """The journal cannot be proved valid, private, or durably updated."""


def _fail(reason: str) -> None:
    raise NormalizationJournalError(reason)


def _renameat2(
    source_fd: int,
    source: str,
    destination_fd: int,
    destination: str,
    flags: int,
) -> None:
    """Use Linux renameat2; no racy compatibility fallback is permitted."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise NormalizationJournalError(
            "normalization_journal_atomic_rename_unavailable"
        ) from exc
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = rename(
        source_fd,
        os.fsencode(source),
        destination_fd,
        os.fsencode(destination),
        flags,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(error, os.strerror(error), destination)
    if error == errno.ENOENT:
        raise FileNotFoundError(error, os.strerror(error), source)
    if error in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        _fail("normalization_journal_atomic_rename_unavailable")
    raise NormalizationJournalError(
        "normalization_journal_atomic_rename_failed"
    ) from OSError(error, os.strerror(error))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise NormalizationJournalError("normalization_journal_json_invalid") from exc


def _journal_bytes(value: Mapping[str, Any]) -> bytes:
    raw = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if not 0 < len(raw) <= MAX_JOURNAL_BYTES:
        _fail("normalization_journal_size_invalid")
    return raw


def _reject_constant(_value: str) -> object:
    _fail("normalization_journal_json_invalid")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("normalization_journal_json_duplicate_key")
        result[key] = value
    return result


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    if not 0 < len(raw) <= MAX_JOURNAL_BYTES:
        _fail("normalization_journal_size_invalid")
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except NormalizationJournalError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise NormalizationJournalError("normalization_journal_json_invalid") from exc
    if not isinstance(value, dict):
        _fail("normalization_journal_json_object_required")
    _validate_json_value(value)
    return value


def _validate_json_value(value: object, *, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        _fail("normalization_journal_json_depth_invalid")
    if value is None or type(value) in {bool, int, str}:
        if (
            isinstance(value, str)
            and len(value.encode("utf-8")) > MAX_JSON_STRING_BYTES
        ):
            _fail("normalization_journal_json_string_too_large")
        return 1
    if isinstance(value, list):
        count = 1
        for item in value:
            count += _validate_json_value(item, depth=depth + 1)
            if count > MAX_JSON_ITEMS:
                _fail("normalization_journal_json_items_invalid")
        return count
    if isinstance(value, dict):
        count = 1
        for key, item in value.items():
            if not isinstance(key, str) or not key or "\x00" in key:
                _fail("normalization_journal_json_key_invalid")
            count += _validate_json_value(key, depth=depth + 1)
            count += _validate_json_value(item, depth=depth + 1)
            if count > MAX_JSON_ITEMS:
                _fail("normalization_journal_json_items_invalid")
        return count
    _fail("normalization_journal_json_type_invalid")


def _normal_absolute_path(value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("normalization_journal_path_invalid")
    path = Path(value)
    if (
        not path.is_absolute()
        or value.startswith("~")
        or os.path.normpath(value) != value
        or ".." in path.parts
        or path == Path("/")
    ):
        _fail("normalization_journal_path_invalid")
    return path


def _is_hex(value: object, length: int = 64) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, str)
        or not 20 <= len(value) <= 40
        or not value.endswith("Z")
    ):
        _fail("normalization_journal_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise NormalizationJournalError(
            "normalization_journal_timestamp_invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("normalization_journal_timestamp_invalid")
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def deterministic_rollback_tag(transaction_id: str) -> str:
    if not isinstance(transaction_id, str) or not _TRANSACTION_PATTERN.fullmatch(
        transaction_id
    ):
        _fail("normalization_journal_transaction_id_invalid")
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", transaction_id.lower()).strip("-.")
    return f"ea-runtime:memorial-rollback-{(normalized[:96] or 'unknown')}"


def _validate_tagged_image(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        _fail("normalization_journal_image_reference_invalid")
    if any(character.isspace() or ord(character) < 32 for character in value):
        _fail("normalization_journal_image_reference_invalid")
    if "://" in value or "@" in value or value.startswith("sha256:"):
        _fail("normalization_journal_image_reference_invalid")
    try:
        repository, tag = value.rsplit(":", 1)
    except ValueError:
        _fail("normalization_journal_image_reference_invalid")
    if (
        not _IMAGE_REPOSITORY_PATTERN.fullmatch(repository)
        or not _IMAGE_TAG_PATTERN.fullmatch(tag)
        or ".." in repository
        or "//" in repository
    ):
        _fail("normalization_journal_image_reference_invalid")
    return value


def _exact_mapping(
    value: object,
    keys: set[str],
    *,
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(f"normalization_journal_{name}_invalid")
    return dict(value)


def _string_shape(value: object, *, name: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or "\x00" in value or (not allow_empty and not value):
        _fail(f"normalization_journal_{name}_invalid")
    return value


def _integer_shape(
    value: object,
    *,
    name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if (
        type(value) is not int
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
    ):
        _fail(f"normalization_journal_{name}_invalid")
    return value


def _boolean_shape(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"normalization_journal_{name}_invalid")
    return value


def _string_list_shape(value: object, *, name: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or "\x00" in item for item in value
    ):
        _fail(f"normalization_journal_{name}_invalid")
    return list(value)


def _mapping_identity_shape(value: object, *, name: str) -> None:
    item = _exact_mapping(value, {"entry_count", "sha256"}, name=name)
    _integer_shape(item["entry_count"], name=name, minimum=0, maximum=100_000)
    if not _is_hex(item["sha256"]):
        _fail(f"normalization_journal_{name}_invalid")


def _validate_container_projection(
    projection: Mapping[str, Any],
    *,
    name: str,
    api: bool,
    expected_config_hash: str | None,
) -> dict[str, str]:
    try:
        domain_sha256 = runtime_identity.runtime_identity_digests(projection)
    except runtime_identity.RuntimeIdentityError as exc:
        raise NormalizationJournalError(
            f"normalization_journal_{name}_invalid"
        ) from exc
    expected_kind = "memorial_api" if api else "cloudflared"
    labels = projection.get("labels")
    if (
        projection.get("schema") != runtime_identity.IDENTITY_SCHEMA
        or projection.get("projection_kind") != expected_kind
        or not isinstance(labels, Mapping)
        or (
            expected_config_hash is not None
            and labels.get("config_hash") != expected_config_hash
        )
    ):
        _fail(f"normalization_journal_{name}_invalid")
    return domain_sha256


def _validate_public_network_projection(
    projection: Mapping[str, Any], *, name: str
) -> None:
    try:
        validated = runtime_identity.validate_public_network_semantic_projection(
            projection
        )
    except runtime_identity.RuntimeIdentityError as exc:
        raise NormalizationJournalError(
            f"normalization_journal_{name}_invalid"
        ) from exc
    if validated != dict(projection):
        _fail(f"normalization_journal_{name}_invalid")


def _validate_public_edge_projection(
    projection: Mapping[str, Any], *, name: str, expected_origin: str
) -> None:
    edge = _exact_mapping(projection, {"schema", "origin", "probes"}, name=name)
    if (
        edge["schema"] != PUBLIC_EDGE_IDENTITY_SCHEMA
        or edge["origin"] != expected_origin
    ):
        _fail(f"normalization_journal_{name}_invalid")
    probes = edge["probes"]
    expected = {
        f"{label}_{method.lower()}": (method, path)
        for label, path in PUBLIC_EDGE_PROBES
        for method in ("GET", "HEAD")
    }
    if not isinstance(probes, Mapping) or set(probes) != set(expected):
        _fail(f"normalization_journal_{name}_invalid")
    for domain, raw_probe in probes.items():
        probe = _exact_mapping(
            raw_probe,
            {"method", "path", "status", "body_sha256", "headers_sha256"},
            name=name,
        )
        expected_method, expected_path = expected[str(domain)]
        if probe["method"] != expected_method or probe["path"] != expected_path:
            _fail(f"normalization_journal_{name}_invalid")
        path = _string_shape(probe["path"], name=name, allow_empty=False)
        if not path.startswith("/") or "?" in path or "#" in path:
            _fail(f"normalization_journal_{name}_invalid")
        _integer_shape(probe["status"], name=name, minimum=100, maximum=599)
        if not _is_hex(probe["body_sha256"]) or not _is_hex(probe["headers_sha256"]):
            _fail(f"normalization_journal_{name}_invalid")
        if probe["method"] == "HEAD" and probe["body_sha256"] != EMPTY_BODY_SHA256:
            _fail(f"normalization_journal_{name}_invalid")


def _identity_projection(
    value: object,
    *,
    name: str,
    expected_config_hash: str | None = None,
    expected_origin: str | None = None,
) -> dict[str, Any]:
    container = name in {"api_identity", "cloudflared_identity"}
    expected_wrapper = (
        {"projection", "sha256", "domain_sha256"}
        if container
        else {"projection", "sha256"}
    )
    if not isinstance(value, Mapping) or set(value) != expected_wrapper:
        _fail(f"normalization_journal_{name}_invalid")
    projection = value.get("projection")
    digest = value.get("sha256")
    if not isinstance(projection, Mapping) or not projection or not _is_hex(digest):
        _fail(f"normalization_journal_{name}_invalid")
    projection_copy = dict(projection)
    _validate_json_value(projection_copy)
    if _sha256(_canonical_json_bytes(projection_copy)) != digest:
        _fail(f"normalization_journal_{name}_digest_mismatch")
    if container:
        domain_sha256 = _validate_container_projection(
            projection_copy,
            name=name,
            api=name == "api_identity",
            expected_config_hash=expected_config_hash,
        )
        if value.get("domain_sha256") != domain_sha256:
            _fail(f"normalization_journal_{name}_domain_digest_mismatch")
    elif name == "public_network_identity":
        _validate_public_network_projection(projection_copy, name=name)
    elif name == "public_edge_identity":
        if expected_origin is None:
            _fail(f"normalization_journal_{name}_invalid")
        _validate_public_edge_projection(
            projection_copy, name=name, expected_origin=expected_origin
        )
    else:  # pragma: no cover - all callers use a fixed identity role
        _fail(f"normalization_journal_{name}_invalid")
    _reject_secret_projection(projection_copy, name=name)
    result: dict[str, Any] = {"projection": projection_copy, "sha256": str(digest)}
    if container:
        result["domain_sha256"] = dict(value["domain_sha256"])
    return result


def _secret_like_string(value: str) -> bool:
    if _is_hex(value) or (
        value.startswith("sha256:") and _is_hex(value.removeprefix("sha256:"))
    ):
        return False
    if (
        "-----BEGIN PRIVATE KEY-----" in value
        or "-----BEGIN OPENSSH PRIVATE KEY-----" in value
        or re.fullmatch(r"[0-9A-Fa-f]{80,}", value) is not None
        or _SECRET_ASSIGNMENT_PATTERN.search(value)
        or _SECRET_OPTION_PATTERN.search(value)
        or _AUTH_VALUE_PATTERN.search(value)
        or _JWT_PATTERN.search(value)
    ):
        return True
    if "://" in value:
        try:
            parsed = urllib.parse.urlsplit(value)
        except ValueError:
            return True
        if parsed.username or parsed.password:
            return True
        for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            if (
                any(fragment in key.lower() for fragment in _SECRET_KEY_FRAGMENTS)
                and item
            ):
                return True
    for candidate in _OPAQUE_SECRET_PATTERN.findall(value):
        if len(set(candidate)) >= 20:
            return True
    return False


def _reject_secret_projection(value: object, *, name: str, key: str = "") -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            lowered = str(raw_key).lower()
            if any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS) and not (
                item is False or item is None or item == "redacted"
            ):
                _fail(f"normalization_journal_{name}_secret_material_invalid")
            _reject_secret_projection(item, name=name, key=lowered)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if (
                isinstance(item, str)
                and item.lower()
                in {
                    "--authorization",
                    "--credential",
                    "--password",
                    "--private-key",
                    "--secret",
                    "--token",
                    "--api-key",
                }
                and index + 1 < len(value)
            ):
                _fail(f"normalization_journal_{name}_secret_material_invalid")
            _reject_secret_projection(item, name=name, key=key)
    elif isinstance(value, str):
        if key == "path" and value in {path for _, path in PUBLIC_EDGE_PROBES}:
            return
        if _secret_like_string(value):
            _fail(f"normalization_journal_{name}_secret_material_invalid")


def identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical projection/digest pair for a secret-free baseline."""
    projection = dict(value)
    _validate_json_value(projection)
    return {
        "projection": projection,
        "sha256": _sha256(_canonical_json_bytes(projection)),
    }


def container_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a container projection with its exact runtime-domain digest set."""
    record = identity(value)
    try:
        record["domain_sha256"] = runtime_identity.runtime_identity_digests(value)
    except runtime_identity.RuntimeIdentityError as exc:
        raise NormalizationJournalError(
            "normalization_journal_container_identity_invalid"
        ) from exc
    return record


def _docker_daemon_identity_sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_JSON_STRING_BYTES
        or _secret_like_string(value)
    ):
        _fail("normalization_journal_docker_daemon_identity_invalid")
    return _sha256(value.encode("utf-8"))


def _topology_label_value(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8")
    return {"value_bytes": len(encoded), "value_sha256": _sha256(encoded)}


def _target_api_topology_label_evidence(
    *,
    bundle_path: Path,
    ordered_compose_files: Sequence[Path],
    environment_file: Path,
    environment_local_file: Path | None,
    compose_config_hash: str,
) -> dict[str, dict[str, Any]]:
    environment_files = [environment_file]
    if environment_local_file is not None:
        environment_files.append(environment_local_file)
    values = {
        runtime_identity.COMPOSE_CONFIG_HASH_LABEL: compose_config_hash,
        "com.docker.compose.project.working_dir": str(bundle_path),
        "com.docker.compose.project.config_files": ",".join(
            str(path) for path in ordered_compose_files
        ),
        "com.docker.compose.project.environment_file": ",".join(
            str(path) for path in environment_files
        ),
    }
    if set(values) != runtime_identity.TOPOLOGY_LABELS:
        _fail("normalization_journal_target_topology_invalid")
    return {key: _topology_label_value(values[key]) for key in sorted(values)}


def _domain_digest_shape(
    value: object, *, expected: Mapping[str, str]
) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != set(expected)
        or any(not _is_hex(item) for item in value.values())
    ):
        _fail("normalization_journal_evidence_invalid")
    return {str(key): str(item) for key, item in value.items()}


def _topology_evidence_shape(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != runtime_identity.TOPOLOGY_LABELS:
        _fail(f"normalization_journal_{name}_invalid")
    result: dict[str, Any] = {}
    for label in sorted(value):
        item = _exact_mapping(value[label], {"value_bytes", "value_sha256"}, name=name)
        _integer_shape(item["value_bytes"], name=name, minimum=0)
        if not _is_hex(item["value_sha256"]):
            _fail(f"normalization_journal_{name}_invalid")
        result[str(label)] = item
    return result


def _evidence_sha256(kind: str, facts: Mapping[str, Any]) -> str:
    return _sha256(
        _canonical_json_bytes(
            {
                "evidence_kind": kind,
                "observed_facts": dict(facts),
            }
        )
    )


def _terminal_verification_sha256(
    *,
    api_domain_sha256: Mapping[str, str],
    cloudflared_domain_sha256: Mapping[str, str],
    public_network_identity_sha256: str,
    public_edge_identity_sha256: str,
    docker_daemon_identity_sha256: str,
    protected_tag_state: str,
    api_topology_label_evidence: Mapping[str, Any],
    normalization_completed: bool,
) -> str:
    topology = _topology_evidence_shape(
        api_topology_label_evidence, name="terminal_observation"
    )
    if (
        not isinstance(api_domain_sha256, Mapping)
        or not api_domain_sha256
        or any(
            not isinstance(key, str) or not _is_hex(value)
            for key, value in api_domain_sha256.items()
        )
        or not isinstance(cloudflared_domain_sha256, Mapping)
        or not cloudflared_domain_sha256
        or any(
            not isinstance(key, str) or not _is_hex(value)
            for key, value in cloudflared_domain_sha256.items()
        )
        or not _is_hex(public_network_identity_sha256)
        or not _is_hex(public_edge_identity_sha256)
        or not _is_hex(docker_daemon_identity_sha256)
        or protected_tag_state not in {"absent", "retained"}
        or type(normalization_completed) is not bool
    ):
        _fail("normalization_journal_terminal_observation_invalid")
    return _evidence_sha256(
        "terminal",
        {
            "api_domain_sha256": dict(api_domain_sha256),
            "cloudflared_domain_sha256": dict(cloudflared_domain_sha256),
            "public_network_identity_sha256": public_network_identity_sha256,
            "public_edge_identity_sha256": public_edge_identity_sha256,
            "docker_daemon_identity_sha256": docker_daemon_identity_sha256,
            "protected_tag_state": protected_tag_state,
            "api_topology_label_evidence": topology,
            "normalization_completed": normalization_completed,
        },
    )


def terminal_observation(
    *,
    api_identity: Mapping[str, Any],
    cloudflared_identity: Mapping[str, Any],
    public_network_identity: Mapping[str, Any],
    public_edge_identity: Mapping[str, Any],
    docker_daemon_identity: str,
    observed_protected_image_id: str | None,
    expected_protected_image_id: str,
    compose_config_hash: str,
    public_origin: str,
    baseline_api_topology_label_evidence: Mapping[str, Any],
    target_api_topology_label_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate raw terminal observations and derive their secret-free facts."""
    api = _identity_projection(
        container_identity(api_identity),
        name="api_identity",
        expected_config_hash=compose_config_hash,
    )
    cloudflared = _identity_projection(
        container_identity(cloudflared_identity),
        name="cloudflared_identity",
    )
    public_network = _identity_projection(
        identity(public_network_identity), name="public_network_identity"
    )
    public_edge = _identity_projection(
        identity(public_edge_identity),
        name="public_edge_identity",
        expected_origin=public_origin,
    )
    if observed_protected_image_id is None:
        protected_tag_state = "absent"
    elif observed_protected_image_id == expected_protected_image_id:
        protected_tag_state = "retained"
    else:
        _fail("normalization_journal_terminal_observation_invalid")
    observed_topology = _topology_evidence_shape(
        api["projection"]["topology_label_evidence"],
        name="terminal_observation",
    )
    baseline_topology = _topology_evidence_shape(
        baseline_api_topology_label_evidence,
        name="terminal_observation",
    )
    target_topology = _topology_evidence_shape(
        target_api_topology_label_evidence,
        name="terminal_observation",
    )
    if observed_topology == target_topology:
        normalization_completed = True
    elif observed_topology == baseline_topology:
        normalization_completed = False
    else:
        _fail("normalization_journal_terminal_observation_invalid")
    facts: dict[str, Any] = {
        "api_domain_sha256": api["domain_sha256"],
        "cloudflared_domain_sha256": cloudflared["domain_sha256"],
        "public_network_identity_sha256": public_network["sha256"],
        "public_edge_identity_sha256": public_edge["sha256"],
        "docker_daemon_identity_sha256": _docker_daemon_identity_sha256(
            docker_daemon_identity
        ),
        "protected_tag_state": protected_tag_state,
        "api_topology_label_evidence": observed_topology,
        "normalization_completed": normalization_completed,
    }
    facts["verification_sha256"] = _terminal_verification_sha256(**facts)
    return facts


def terminal_receipt_payload(
    payload: Mapping[str, Any],
    *,
    kind: str,
    observation: Mapping[str, Any],
    completed_at: str,
) -> dict[str, Any]:
    """Build the exact terminal receipt that authorizes journal erasure."""
    observation_keys = {
        "verification_sha256",
        "api_domain_sha256",
        "cloudflared_domain_sha256",
        "public_network_identity_sha256",
        "public_edge_identity_sha256",
        "docker_daemon_identity_sha256",
        "protected_tag_state",
        "api_topology_label_evidence",
        "normalization_completed",
    }
    if not isinstance(observation, Mapping) or set(observation) != observation_keys:
        _fail("normalization_journal_receipt_payload_invalid")
    terminal_facts = {
        key: observation[key] for key in observation_keys - {"verification_sha256"}
    }
    evidence = payload.get("evidence")
    if not isinstance(evidence, Mapping):
        _fail("normalization_journal_receipt_payload_invalid")
    if kind == "durable_commit":
        execution_record = {
            "mode": "forward",
            "api_recreation_observed": True,
            "protected_image_tag_mutation_recorded": True,
        }
    elif kind == "clean_abort":
        execution_record = {
            "mode": "clean_abort",
            "api_recreation_observed": False,
            "protected_image_tag_mutation_recorded": False,
        }
    else:
        execution_record = {
            "mode": "recovery",
            "api_recreation_observed": (
                kind == "verified_forward_recovery"
                or evidence.get("api_mutation") is not None
            ),
            "protected_image_tag_mutation_recorded": (
                evidence.get("protected_image") is not None
            ),
        }
    if (
        kind not in TERMINAL_RECEIPT_STATUS
        or observation["verification_sha256"]
        != _terminal_verification_sha256(**terminal_facts)
        or (
            kind in {"durable_commit", "verified_forward_recovery"}
            and observation["normalization_completed"] is not True
        )
        or (
            kind in {"clean_abort", "verified_recovery"}
            and observation["normalization_completed"] is not False
        )
        or (
            kind == "verified_forward_recovery"
            and execution_record["protected_image_tag_mutation_recorded"] is not True
        )
        or (
            kind in {"durable_commit", "verified_forward_recovery"}
            and payload.get("api_boundary_authorized") is not True
        )
        or (
            kind in {"clean_abort", "verified_recovery"}
            and payload.get("api_boundary_authorized") is not False
        )
        or (
            kind == "clean_abort"
            and (
                evidence.get("protected_image") is not None
                or evidence.get("api_mutation") is not None
            )
        )
        or (
            kind == "durable_commit"
            and (
                evidence.get("protected_image") is None
                or evidence.get("api_mutation") is None
            )
        )
        or (kind == "verified_recovery" and evidence.get("api_mutation") is not None)
    ):
        _fail("normalization_journal_receipt_payload_invalid")
    _timestamp(completed_at)
    retained_bundle = payload.get("retained_bundle")
    if not isinstance(retained_bundle, Mapping):
        _fail("normalization_journal_receipt_payload_invalid")
    recovery_seal = retained_bundle.get("recovery_seal")
    if not isinstance(recovery_seal, Mapping):
        _fail("normalization_journal_receipt_payload_invalid")
    return {
        "contract_name": TERMINAL_RECEIPT_CONTRACT_NAME,
        "version": TERMINAL_RECEIPT_VERSION,
        "transaction_id": payload.get("transaction_id"),
        "status": TERMINAL_RECEIPT_STATUS[kind],
        "journal_terminal_kind": kind,
        "journal_verification_sha256": observation["verification_sha256"],
        "terminal_observation": dict(observation),
        "source_revision": payload.get("source_revision"),
        "public_origin": payload.get("public_origin"),
        "service_scope": ["ea-api"],
        "ingress_mutation_scope": [],
        "promotion_authority": False,
        "candidate_authority": False,
        "normalization_completed": observation["normalization_completed"],
        "execution": execution_record,
        "retained_bundle": dict(recovery_seal),
        "completed_at": completed_at,
    }


def _validate_evidence(
    value: object,
    *,
    phase: str,
    api_boundary_authorized: bool,
    previous_image: Mapping[str, Any],
    baselines: Mapping[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    evidence = _exact_mapping(
        value,
        {"protected_image", "api_mutation", "terminal"},
        name="evidence",
    )
    protected = evidence["protected_image"]
    if protected is not None:
        protected = _exact_mapping(
            protected,
            {"recorded_at", "verification_sha256", "image_id", "rollback_tag"},
            name="evidence",
        )
        _timestamp(protected["recorded_at"])
        expected_verification = _evidence_sha256(
            "protected_image",
            {
                "image_id": protected["image_id"],
                "rollback_tag": protected["rollback_tag"],
            },
        )
        if (
            protected["verification_sha256"] != expected_verification
            or protected["image_id"] != previous_image["image_id"]
            or protected["rollback_tag"] != previous_image["rollback_tag"]
        ):
            _fail("normalization_journal_evidence_invalid")

    api_mutation = evidence["api_mutation"]
    expected_api_domains = baselines["api_identity"]["domain_sha256"]
    if api_mutation is not None:
        api_mutation = _exact_mapping(
            api_mutation,
            {"recorded_at", "verification_sha256", "api_domain_sha256"},
            name="evidence",
        )
        _timestamp(api_mutation["recorded_at"])
        if not _is_hex(api_mutation["verification_sha256"]):
            _fail("normalization_journal_evidence_invalid")
        observed_api = _domain_digest_shape(
            api_mutation["api_domain_sha256"], expected=expected_api_domains
        )
        expected_verification = _evidence_sha256(
            "api_mutation", {"api_domain_sha256": observed_api}
        )
        if (
            api_mutation["verification_sha256"] != expected_verification
            or observed_api != expected_api_domains
        ):
            _fail("normalization_journal_evidence_baseline_mismatch")

    terminal = evidence["terminal"]
    if terminal is not None:
        terminal = _exact_mapping(
            terminal,
            {
                "kind",
                "recorded_at",
                "verification_sha256",
                "receipt_path",
                "receipt_sha256",
                "api_domain_sha256",
                "cloudflared_domain_sha256",
                "public_network_identity_sha256",
                "public_edge_identity_sha256",
                "docker_daemon_identity_sha256",
                "protected_tag_state",
                "api_topology_label_evidence",
                "normalization_completed",
            },
            name="evidence",
        )
        kind = terminal["kind"]
        _timestamp(terminal["recorded_at"])
        observed_api = _domain_digest_shape(
            terminal["api_domain_sha256"], expected=expected_api_domains
        )
        expected_cloudflared = baselines["cloudflared_identity"]["domain_sha256"]
        observed_cloudflared = _domain_digest_shape(
            terminal["cloudflared_domain_sha256"], expected=expected_cloudflared
        )
        expected_verification = _terminal_verification_sha256(
            api_domain_sha256=observed_api,
            cloudflared_domain_sha256=observed_cloudflared,
            public_network_identity_sha256=terminal["public_network_identity_sha256"],
            public_edge_identity_sha256=terminal["public_edge_identity_sha256"],
            docker_daemon_identity_sha256=terminal["docker_daemon_identity_sha256"],
            protected_tag_state=terminal["protected_tag_state"],
            api_topology_label_evidence=terminal["api_topology_label_evidence"],
            normalization_completed=terminal["normalization_completed"],
        )
        expected_normalization = kind in {
            "durable_commit",
            "verified_forward_recovery",
        }
        expected_topology = (
            baselines["target_api_topology_label_evidence"]
            if expected_normalization
            else baselines["api_identity"]["projection"]["topology_label_evidence"]
        )
        if (
            kind
            not in {
                "clean_abort",
                "durable_commit",
                "verified_recovery",
                "verified_forward_recovery",
            }
            or terminal["verification_sha256"] != expected_verification
            or not _is_hex(terminal["receipt_sha256"])
            or _normal_absolute_path(terminal["receipt_path"]) != receipt_path
            or observed_api != expected_api_domains
            or observed_cloudflared != expected_cloudflared
            or terminal["public_network_identity_sha256"]
            != baselines["public_network_identity"]["sha256"]
            or terminal["public_edge_identity_sha256"]
            != baselines["public_edge_identity"]["sha256"]
            or terminal["docker_daemon_identity_sha256"]
            != baselines["docker_daemon_identity_sha256"]
            or terminal["protected_tag_state"]
            != (
                "retained"
                if kind in {"durable_commit", "verified_forward_recovery"}
                else "absent"
            )
            or terminal["normalization_completed"] is not expected_normalization
            or terminal["api_topology_label_evidence"] != expected_topology
            or (
                kind in {"durable_commit", "verified_forward_recovery"}
                and not api_boundary_authorized
            )
            or (
                kind in {"clean_abort", "verified_recovery"} and api_boundary_authorized
            )
        ):
            _fail("normalization_journal_evidence_baseline_mismatch")

    if phase == "prepared":
        if (
            protected is not None
            or api_mutation is not None
            or (terminal is not None and terminal["kind"] != "clean_abort")
        ):
            _fail("normalization_journal_evidence_phase_invalid")
    elif phase == "protect_previous_image_possible":
        if api_mutation is not None or terminal is not None:
            _fail("normalization_journal_evidence_phase_invalid")
    elif phase == "api_mutation_possible":
        if (
            protected is None
            or (terminal is not None and terminal["kind"] != "durable_commit")
            or (terminal is not None and api_mutation is None)
        ):
            _fail("normalization_journal_evidence_phase_invalid")
    elif phase == "commit_pending":
        if (
            protected is None
            or api_mutation is None
            or terminal is None
            or terminal["kind"] != "durable_commit"
        ):
            _fail("normalization_journal_evidence_phase_invalid")
    elif phase in {"rollback_in_progress", "rollback_failed"}:
        if terminal is not None and terminal["kind"] not in {
            "verified_recovery",
            "verified_forward_recovery",
        }:
            _fail("normalization_journal_evidence_phase_invalid")
        if phase == "rollback_failed" and terminal is not None:
            _fail("normalization_journal_evidence_phase_invalid")
    elif phase == "cleanup_pending":
        if terminal is None:
            _fail("normalization_journal_evidence_phase_invalid")
        if terminal["kind"] == "clean_abort" and (
            protected is not None or api_mutation is not None
        ):
            _fail("normalization_journal_evidence_phase_invalid")
        if terminal["kind"] == "durable_commit" and (
            protected is None or api_mutation is None
        ):
            _fail("normalization_journal_evidence_phase_invalid")
        if terminal["kind"] == "verified_recovery" and api_mutation is not None:
            _fail("normalization_journal_evidence_phase_invalid")
    else:  # pragma: no cover - PHASES constrains this before evidence validation
        _fail("normalization_journal_evidence_phase_invalid")
    return {
        "protected_image": protected,
        "api_mutation": api_mutation,
        "terminal": terminal,
    }


def validate_payload(
    payload: Mapping[str, Any],
    *,
    expected_path: Path,
    expected_operator_anchor: Path,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        _fail("normalization_journal_schema_invalid")
    journal = dict(payload)
    expected_keys = {
        "contract_name",
        "version",
        "material_classification",
        "contains_secret_material",
        "environment_values_included",
        "retention_policy",
        "transaction_id",
        "phase",
        "created_at",
        "updated_at",
        "recovery_attempts",
        "api_mutation_possible",
        "api_boundary_authorized",
        "operator_anchor",
        "recovery_journal_path",
        "release_root",
        "transaction_receipt_path",
        "public_origin",
        "retained_bundle",
        "source_revision",
        "previous_image",
        "baselines",
        "evidence",
    }
    transaction_id = journal.get("transaction_id")
    phase = journal.get("phase")
    created = _timestamp(journal.get("created_at"))
    updated = _timestamp(journal.get("updated_at"))
    if (
        set(journal) != expected_keys
        or journal.get("contract_name") != CONTRACT_NAME
        or type(journal.get("version")) is not int
        or journal.get("version") != CONTRACT_VERSION
        or journal.get("material_classification")
        != "private_secret_bearing_recovery_state"
        or journal.get("contains_secret_material") is not True
        or journal.get("environment_values_included") is not False
        or journal.get("retention_policy") != "until_verified_terminal_cleanup"
        or not isinstance(transaction_id, str)
        or not _TRANSACTION_PATTERN.fullmatch(transaction_id)
        or phase not in PHASES
        or created > updated
        or type(journal.get("recovery_attempts")) is not int
        or not 0 <= journal["recovery_attempts"] <= 1_000_000
        or type(journal.get("api_mutation_possible")) is not bool
        or type(journal.get("api_boundary_authorized")) is not bool
    ):
        _fail("normalization_journal_schema_invalid")
    expected_possible = phase in {
        "api_mutation_possible",
        "commit_pending",
        "rollback_in_progress",
        "rollback_failed",
    }
    if phase == "cleanup_pending":
        raw_evidence = journal.get("evidence")
        raw_terminal = (
            raw_evidence.get("terminal") if isinstance(raw_evidence, Mapping) else None
        )
        expected_possible = (
            isinstance(raw_terminal, Mapping)
            and raw_terminal.get("kind") != "clean_abort"
        )
    if journal["api_mutation_possible"] is not expected_possible:
        _fail("normalization_journal_phase_invalid")
    if (
        phase in {"prepared", "protect_previous_image_possible"}
        and journal["api_boundary_authorized"] is not False
    ) or (
        phase in {"api_mutation_possible", "commit_pending"}
        and journal["api_boundary_authorized"] is not True
    ):
        _fail("normalization_journal_phase_invalid")

    operator_anchor = _normal_absolute_path(journal["operator_anchor"])
    recovery_path = _normal_absolute_path(journal["recovery_journal_path"])
    release_root = _normal_absolute_path(journal["release_root"])
    receipt_path = _normal_absolute_path(journal["transaction_receipt_path"])
    if (
        operator_anchor != expected_operator_anchor
        or recovery_path != expected_path
        or receipt_path.name != f"{transaction_id}.json"
        or release_root != expected_operator_anchor
        or receipt_path.parent != release_root / ".runtime"
    ):
        _fail("normalization_journal_binding_invalid")

    try:
        parsed_origin = urllib.parse.urlsplit(str(journal.get("public_origin") or ""))
        parsed_port = parsed_origin.port
    except ValueError:
        _fail("normalization_journal_public_origin_invalid")
    if (
        parsed_origin.scheme != "https"
        or not parsed_origin.hostname
        or parsed_origin.username
        or parsed_origin.password
        or parsed_origin.query
        or parsed_origin.fragment
        or parsed_origin.path not in {"", "/"}
        or parsed_port not in {None, 443}
    ):
        _fail("normalization_journal_public_origin_invalid")

    bundle_raw = journal.get("retained_bundle")
    if not isinstance(bundle_raw, Mapping) or set(bundle_raw) != {
        "path",
        "manifest_path",
        "recovery_seal",
        "ordered_compose_files",
        "environment_file",
        "environment_local_file",
        "environment_local_present",
    }:
        _fail("normalization_journal_bundle_invalid")
    bundle = dict(bundle_raw)
    bundle_path = _normal_absolute_path(bundle["path"])
    manifest_path = _normal_absolute_path(bundle["manifest_path"])
    compose_files = bundle.get("ordered_compose_files")
    environment_file = _normal_absolute_path(bundle["environment_file"])
    local_present = bundle.get("environment_local_present")
    local_raw = bundle.get("environment_local_file")
    local_file = None if local_raw is None else _normal_absolute_path(local_raw)
    seal = bundle.get("recovery_seal")
    if (
        not isinstance(seal, Mapping)
        or set(seal) != {"contract_name", "manifest_sha256", "plan_sha256"}
        or seal.get("contract_name") != BUNDLE_RECOVERY_SEAL_CONTRACT_NAME
        or not _is_hex(seal.get("manifest_sha256"))
        or not _is_hex(seal.get("plan_sha256"))
        or not isinstance(compose_files, list)
        or len(compose_files) not in {3, 5}
        or not all(isinstance(item, str) for item in compose_files)
        or len(set(compose_files)) != len(compose_files)
        or type(local_present) is not bool
        or local_present is not (local_file is not None)
    ):
        _fail("normalization_journal_bundle_invalid")
    compose_paths = [_normal_absolute_path(item) for item in compose_files]
    bundle_children = [manifest_path, environment_file, *compose_paths]
    if local_file is not None:
        bundle_children.append(local_file)
    if any(path.parent != bundle_path for path in bundle_children):
        _fail("normalization_journal_bundle_binding_invalid")
    if (
        manifest_path.name != RETAINED_BUNDLE_MANIFEST_FILENAME
        or environment_file.name != ".env"
        or (local_file is not None and local_file.name != ".env.local")
        or tuple(path.name for path in compose_paths)
        not in SUPPORTED_RETAINED_COMPOSE_LAYOUTS
    ):
        _fail("normalization_journal_bundle_binding_invalid")

    if not _is_hex(journal.get("source_revision"), 40):
        _fail("normalization_journal_source_revision_invalid")
    image_raw = journal.get("previous_image")
    if not isinstance(image_raw, Mapping) or set(image_raw) != {
        "image_id",
        "image_reference",
        "rollback_tag",
    }:
        _fail("normalization_journal_image_invalid")
    image = dict(image_raw)
    image_id = image.get("image_id")
    if (
        not isinstance(image_id, str)
        or not image_id.startswith("sha256:")
        or not _is_hex(image_id[7:])
        or image.get("rollback_tag") != deterministic_rollback_tag(transaction_id)
    ):
        _fail("normalization_journal_image_invalid")
    _validate_tagged_image(image.get("image_reference"))
    _validate_tagged_image(image.get("rollback_tag"))

    baselines_raw = journal.get("baselines")
    if not isinstance(baselines_raw, Mapping) or set(baselines_raw) != {
        "compose_config_hash",
        "docker_daemon_identity_sha256",
        "api_identity",
        "cloudflared_identity",
        "public_network_identity",
        "public_edge_identity",
        "target_api_topology_label_evidence",
    }:
        _fail("normalization_journal_baselines_invalid")
    baselines = dict(baselines_raw)
    if not _is_hex(baselines.get("compose_config_hash")) or not _is_hex(
        baselines.get("docker_daemon_identity_sha256")
    ):
        _fail("normalization_journal_baselines_invalid")
    api_baseline = _identity_projection(
        baselines.get("api_identity"),
        name="api_identity",
    )
    target_topology = _topology_evidence_shape(
        baselines.get("target_api_topology_label_evidence"),
        name="target_topology",
    )
    expected_target_topology = _target_api_topology_label_evidence(
        bundle_path=bundle_path,
        ordered_compose_files=compose_paths,
        environment_file=environment_file,
        environment_local_file=local_file,
        compose_config_hash=str(baselines["compose_config_hash"]),
    )
    if (
        target_topology != expected_target_topology
        or target_topology == api_baseline["projection"]["topology_label_evidence"]
    ):
        _fail("normalization_journal_target_topology_invalid")
    _identity_projection(
        baselines.get("cloudflared_identity"), name="cloudflared_identity"
    )
    _identity_projection(
        baselines.get("public_network_identity"), name="public_network_identity"
    )
    _identity_projection(
        baselines.get("public_edge_identity"),
        name="public_edge_identity",
        expected_origin=str(journal["public_origin"]),
    )
    validated_evidence = _validate_evidence(
        journal.get("evidence"),
        phase=str(phase),
        api_boundary_authorized=bool(journal["api_boundary_authorized"]),
        previous_image=image,
        baselines=baselines,
        receipt_path=receipt_path,
    )
    for record in validated_evidence.values():
        if (
            record is not None
            and not created <= _timestamp(record["recorded_at"]) <= updated
        ):
            _fail("normalization_journal_evidence_timestamp_invalid")
    _validate_json_value(journal)
    if len(_journal_bytes(journal)) > MAX_JOURNAL_BYTES:
        _fail("normalization_journal_size_invalid")
    return journal


def _require_transition(old: Mapping[str, Any], new: Mapping[str, Any]) -> None:
    mutable = {
        "phase",
        "updated_at",
        "recovery_attempts",
        "api_mutation_possible",
        "api_boundary_authorized",
        "evidence",
    }
    old_evidence = old["evidence"]
    new_evidence = new["evidence"]
    evidence_monotonic = all(
        old_evidence[key] == new_evidence[key]
        or (old_evidence[key] is None and new_evidence[key] is not None)
        for key in old_evidence
    )
    evidence_additions = sum(
        old_evidence[key] is None and new_evidence[key] is not None
        for key in old_evidence
    )
    phase_changed = new["phase"] != old["phase"]
    recovery_retry = (
        not phase_changed
        and new["phase"] == "rollback_in_progress"
        and new_evidence == old_evidence
    )
    legal_phase = (
        new["phase"] in _TRANSITIONS[str(old["phase"])]
        if phase_changed
        else new_evidence != old_evidence or recovery_retry
    )
    expected_attempts = old["recovery_attempts"] + (
        1
        if new["phase"] == "rollback_in_progress" and (phase_changed or recovery_retry)
        else 0
    )
    if (
        {key: value for key, value in old.items() if key not in mutable}
        != {key: value for key, value in new.items() if key not in mutable}
        or not legal_phase
        or not evidence_monotonic
        or (phase_changed and evidence_additions != 0)
        or (not phase_changed and not recovery_retry and evidence_additions != 1)
        or (recovery_retry and evidence_additions != 0)
        or _timestamp(new["updated_at"]) < _timestamp(old["updated_at"])
        or new["recovery_attempts"] != expected_attempts
        or (old["api_boundary_authorized"] and not new["api_boundary_authorized"])
        or (
            not old["api_boundary_authorized"]
            and new["api_boundary_authorized"]
            and not (
                phase_changed
                and old["phase"] == "protect_previous_image_possible"
                and new["phase"] == "api_mutation_possible"
            )
        )
    ):
        _fail("normalization_journal_transition_invalid")


class NormalizationRecoveryJournal:
    """Descriptor-relative durable storage for one canonical journal.

    Every cooperating writer must also hold the Memorial global API deployment
    lock.  The 0700 state directory excludes other UIDs, and held descriptors
    plus atomic rename operations detect pathname substitution by a racing
    same-UID process.  POSIX has no portable conditional-rename-by-inode
    primitive, however, so a deliberately hostile process running as the same
    UID remains inside the trusted operator boundary and can always deny
    service.  Detected races preserve a valid canonical entry or a
    deterministic private leftover and fail closed.
    """

    def __init__(self, *, operator_anchor: Path) -> None:
        if not isinstance(operator_anchor, Path):
            _fail("normalization_journal_operator_anchor_invalid")
        self.operator_anchor = operator_anchor
        self.path = default_normalization_recovery_journal_path(
            operator_anchor=operator_anchor
        )
        if (
            self.path.name != NORMALIZATION_RECOVERY_JOURNAL_FILENAME
            or self.path.parent.name != NORMALIZATION_RECOVERY_STATE_DIRECTORY
        ):
            _fail("normalization_journal_canonical_path_invalid")
        self._home = self.path.parent.parent
        self._owner_uid = os.geteuid()

    def _open_directory(self, *, create: bool) -> tuple[int, int]:
        required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
        if any(not hasattr(os, item) for item in required):
            _fail("normalization_journal_nofollow_unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        home_fd = state_fd = -1
        try:
            home_before = self._home.lstat()
            home_fd = os.open(self._home, flags)
            home_open = os.fstat(home_fd)
            home_after = self._home.lstat()
            if (
                not stat.S_ISDIR(home_open.st_mode)
                or stat.S_ISLNK(home_before.st_mode)
                or home_open.st_uid != self._owner_uid
                or stat.S_IMODE(home_open.st_mode) & 0o022
                or (home_before.st_dev, home_before.st_ino)
                != (home_open.st_dev, home_open.st_ino)
                or (home_after.st_dev, home_after.st_ino)
                != (home_open.st_dev, home_open.st_ino)
            ):
                _fail("normalization_journal_account_home_invalid")
            if create:
                try:
                    os.mkdir(
                        NORMALIZATION_RECOVERY_STATE_DIRECTORY,
                        0o700,
                        dir_fd=home_fd,
                    )
                    os.fsync(home_fd)
                except FileExistsError:
                    pass
            path_metadata = os.stat(
                NORMALIZATION_RECOVERY_STATE_DIRECTORY,
                dir_fd=home_fd,
                follow_symlinks=False,
            )
            state_fd = os.open(
                NORMALIZATION_RECOVERY_STATE_DIRECTORY,
                flags,
                dir_fd=home_fd,
            )
            opened = os.fstat(state_fd)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != self._owner_uid
                or stat.S_IMODE(opened.st_mode) != 0o700
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (opened.st_dev, opened.st_ino)
            ):
                _fail("normalization_journal_directory_invalid")
            return home_fd, state_fd
        except FileNotFoundError:
            if not create:
                if state_fd >= 0:
                    os.close(state_fd)
                if home_fd >= 0:
                    os.close(home_fd)
                raise
            raise
        except NormalizationJournalError:
            if state_fd >= 0:
                os.close(state_fd)
            if home_fd >= 0:
                os.close(home_fd)
            raise
        except OSError as exc:
            if state_fd >= 0:
                os.close(state_fd)
            if home_fd >= 0:
                os.close(home_fd)
            raise NormalizationJournalError(
                "normalization_journal_directory_unavailable"
            ) from exc

    def _revalidate_directory(self, home_fd: int, state_fd: int) -> None:
        opened = os.fstat(state_fd)
        current = os.stat(
            NORMALIZATION_RECOVERY_STATE_DIRECTORY,
            dir_fd=home_fd,
            follow_symlinks=False,
        )
        home_open = os.fstat(home_fd)
        home_path = self._home.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != self._owner_uid
            or stat.S_IMODE(opened.st_mode) != 0o700
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            or (home_open.st_dev, home_open.st_ino)
            != (home_path.st_dev, home_path.st_ino)
        ):
            _fail("normalization_journal_directory_changed")

    def _read_open_held(
        self, home_fd: int, state_fd: int
    ) -> tuple[dict[str, Any], bytes, os.stat_result, int]:
        try:
            fd = os.open(
                self.path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=state_fd,
            )
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise NormalizationJournalError(
                "normalization_journal_unavailable"
            ) from exc
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != self._owner_uid
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= MAX_JOURNAL_BYTES
            ):
                _fail("normalization_journal_untrusted")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(fd)
            path_metadata = os.stat(
                self.path.name,
                dir_fd=state_fd,
                follow_symlinks=False,
            )
            if (
                remaining
                or len(raw) != before.st_size
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (before.st_dev, before.st_ino)
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                _fail("normalization_journal_changed_during_read")
            self._revalidate_directory(home_fd, state_fd)
            payload = _strict_json_object(raw)
            return (
                validate_payload(
                    payload,
                    expected_path=self.path,
                    expected_operator_anchor=self.operator_anchor,
                ),
                raw,
                before,
                fd,
            )
        except Exception:
            os.close(fd)
            raise

    def _read_open(
        self, home_fd: int, state_fd: int
    ) -> tuple[dict[str, Any], bytes, os.stat_result]:
        payload, raw, metadata, fd = self._read_open_held(home_fd, state_fd)
        os.close(fd)
        return payload, raw, metadata

    def _read_named_bytes(
        self,
        state_fd: int,
        name: str,
    ) -> tuple[bytes, os.stat_result]:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=state_fd,
            )
        except OSError as exc:
            raise NormalizationJournalError(
                "normalization_journal_leftover_unavailable"
            ) from exc
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != self._owner_uid
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= MAX_JOURNAL_BYTES
            ):
                _fail("normalization_journal_leftover_untrusted")
            raw = b""
            while len(raw) < before.st_size:
                chunk = os.read(fd, before.st_size - len(raw))
                if not chunk:
                    break
                raw += chunk
            after = os.fstat(fd)
            path_metadata = os.stat(name, dir_fd=state_fd, follow_symlinks=False)
            if (
                len(raw) != before.st_size
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (before.st_dev, before.st_ino)
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                _fail("normalization_journal_leftover_changed")
            return raw, before
        finally:
            os.close(fd)

    def _cleanup_update_leftover(
        self,
        home_fd: int,
        state_fd: int,
        *,
        current: Mapping[str, Any],
        current_raw: bytes,
    ) -> None:
        name = self._temporary_name("update", current_raw)
        try:
            raw, metadata = self._read_named_bytes(state_fd, name)
        except NormalizationJournalError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                return
            raise
        previous = validate_payload(
            _strict_json_object(raw),
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        if raw != _journal_bytes(previous):
            _fail("normalization_journal_leftover_not_canonical")
        _require_transition(previous, current)
        immediately_before = os.stat(name, dir_fd=state_fd, follow_symlinks=False)
        if (immediately_before.st_dev, immediately_before.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            _fail("normalization_journal_leftover_replaced")
        os.unlink(name, dir_fd=state_fd)
        os.fsync(state_fd)
        self._revalidate_directory(home_fd, state_fd)

    def read(self) -> dict[str, Any] | None:
        try:
            home_fd, state_fd = self._open_directory(create=False)
        except FileNotFoundError:
            return None
        try:
            try:
                current, raw, _ = self._read_open(home_fd, state_fd)
                self._cleanup_update_leftover(
                    home_fd,
                    state_fd,
                    current=current,
                    current_raw=raw,
                )
                return current
            except FileNotFoundError:
                self._revalidate_directory(home_fd, state_fd)
                return None
        finally:
            os.close(state_fd)
            os.close(home_fd)

    def _temporary_name(self, purpose: str, raw: bytes) -> str:
        return f".{self.path.name}.{purpose}.{_sha256(raw)}"

    def _write_temporary(
        self, state_fd: int, raw: bytes, *, name: str
    ) -> tuple[str, os.stat_result]:
        fd = -1
        try:
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=state_fd,
            )
            os.fchmod(fd, 0o600)
            created = os.fstat(fd)
            if (
                not stat.S_ISREG(created.st_mode)
                or created.st_nlink != 1
                or created.st_uid != self._owner_uid
                or stat.S_IMODE(created.st_mode) != 0o600
            ):
                _fail("normalization_journal_temporary_invalid")
            remaining = memoryview(raw)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    _fail("normalization_journal_write_failed")
                remaining = remaining[written:]
            os.fsync(fd)
            complete = os.fstat(fd)
            linked = os.stat(name, dir_fd=state_fd, follow_symlinks=False)
            if (
                complete.st_size != len(raw)
                or (complete.st_dev, complete.st_ino)
                != (created.st_dev, created.st_ino)
                or (linked.st_dev, linked.st_ino) != (created.st_dev, created.st_ino)
                or complete.st_nlink != 1
            ):
                _fail("normalization_journal_temporary_changed")
            return name, complete
        except FileExistsError:
            raise
        except NormalizationJournalError:
            try:
                os.unlink(name, dir_fd=state_fd)
            except OSError:
                pass
            raise
        except OSError as exc:
            try:
                os.unlink(name, dir_fd=state_fd)
            except OSError:
                pass
            raise NormalizationJournalError(
                "normalization_journal_write_unavailable"
            ) from exc
        finally:
            if fd >= 0:
                os.close(fd)

    def _prepare_temporary(
        self,
        state_fd: int,
        raw: bytes,
        *,
        purpose: str,
    ) -> tuple[str, os.stat_result]:
        name = self._temporary_name(purpose, raw)
        try:
            return self._write_temporary(state_fd, raw, name=name)
        except FileExistsError:
            existing, metadata = self._read_named_bytes(state_fd, name)
            if existing != raw:
                _fail("normalization_journal_leftover_not_owned")
            return name, metadata

    def create(self, payload: Mapping[str, Any]) -> str:
        validated = validate_payload(
            payload,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        if validated["phase"] != "prepared" or validated["evidence"] != {
            "protected_image": None,
            "api_mutation": None,
            "terminal": None,
        }:
            _fail("normalization_journal_initial_state_invalid")
        raw = _journal_bytes(validated)
        home_fd, state_fd = self._open_directory(create=True)
        temporary = ""
        try:
            temporary, created = self._prepare_temporary(
                state_fd, raw, purpose="create"
            )
            try:
                _renameat2(
                    state_fd,
                    temporary,
                    state_fd,
                    self.path.name,
                    _RENAME_NOREPLACE,
                )
            except FileExistsError as exc:
                try:
                    current, current_raw, _ = self._read_open(home_fd, state_fd)
                except (FileNotFoundError, NormalizationJournalError):
                    raise NormalizationJournalError(
                        "normalization_journal_already_exists"
                    ) from exc
                if current == validated and current_raw == raw:
                    return _sha256(raw)
                raise NormalizationJournalError(
                    "normalization_journal_already_exists"
                ) from exc
            temporary = ""
            os.fsync(state_fd)
            published = os.stat(self.path.name, dir_fd=state_fd, follow_symlinks=False)
            if (
                (published.st_dev, published.st_ino) != (created.st_dev, created.st_ino)
                or published.st_nlink != 1
                or stat.S_IMODE(published.st_mode) != 0o600
            ):
                _fail("normalization_journal_publish_invalid")
            self._revalidate_directory(home_fd, state_fd)
            read_payload, read_raw, _ = self._read_open(home_fd, state_fd)
            if read_raw != raw or read_payload != validated:
                _fail("normalization_journal_publish_invalid")
            return _sha256(raw)
        finally:
            if temporary:
                try:
                    os.unlink(temporary, dir_fd=state_fd)
                except OSError:
                    pass
            os.close(state_fd)
            os.close(home_fd)

    def update(
        self,
        *,
        expected: Mapping[str, Any],
        replacement: Mapping[str, Any],
    ) -> str:
        old = validate_payload(
            expected,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        new = validate_payload(
            replacement,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        _require_transition(old, new)
        old_raw = _journal_bytes(old)
        new_raw = _journal_bytes(new)
        home_fd, state_fd = self._open_directory(create=False)
        temporary = ""
        temporary_is_candidate = False
        current_fd = -1
        try:
            current, current_raw, current_metadata, current_fd = self._read_open_held(
                home_fd, state_fd
            )
            self._cleanup_update_leftover(
                home_fd,
                state_fd,
                current=current,
                current_raw=current_raw,
            )
            temporary = self._temporary_name("update", new_raw)
            if current == new and current_raw == new_raw:
                try:
                    leftover_raw, leftover_metadata = self._read_named_bytes(
                        state_fd, temporary
                    )
                except NormalizationJournalError as exc:
                    if isinstance(exc.__cause__, FileNotFoundError):
                        return _sha256(new_raw)
                    raise
                if leftover_raw != old_raw:
                    _fail("normalization_journal_leftover_not_owned")
                current_open = os.fstat(current_fd)
                linked = os.stat(temporary, dir_fd=state_fd, follow_symlinks=False)
                if (leftover_metadata.st_dev, leftover_metadata.st_ino) != (
                    linked.st_dev,
                    linked.st_ino,
                ) or (current_open.st_dev, current_open.st_ino) != (
                    current_metadata.st_dev,
                    current_metadata.st_ino,
                ):
                    _fail("normalization_journal_replaced")
                os.unlink(temporary, dir_fd=state_fd)
                os.fsync(state_fd)
                self._revalidate_directory(home_fd, state_fd)
                return _sha256(new_raw)
            if current != old or current_raw != old_raw:
                _fail("normalization_journal_not_owned")
            temporary, created = self._prepare_temporary(
                state_fd, new_raw, purpose="update"
            )
            temporary_is_candidate = True
            immediately_before = os.stat(
                self.path.name, dir_fd=state_fd, follow_symlinks=False
            )
            if (immediately_before.st_dev, immediately_before.st_ino) != (
                current_metadata.st_dev,
                current_metadata.st_ino,
            ):
                _fail("normalization_journal_replaced")
            _renameat2(
                state_fd,
                temporary,
                state_fd,
                self.path.name,
                _RENAME_EXCHANGE,
            )
            temporary_is_candidate = False
            os.fsync(state_fd)
            current_open = os.fstat(current_fd)
            old_at_leftover = os.stat(temporary, dir_fd=state_fd, follow_symlinks=False)
            new_at_canonical = os.stat(
                self.path.name, dir_fd=state_fd, follow_symlinks=False
            )
            if (
                (current_open.st_dev, current_open.st_ino)
                != (current_metadata.st_dev, current_metadata.st_ino)
                or (old_at_leftover.st_dev, old_at_leftover.st_ino)
                != (current_metadata.st_dev, current_metadata.st_ino)
                or (new_at_canonical.st_dev, new_at_canonical.st_ino)
                != (created.st_dev, created.st_ino)
            ):
                _fail("normalization_journal_exchange_invalid")
            self._revalidate_directory(home_fd, state_fd)
            updated, updated_raw, _ = self._read_open(home_fd, state_fd)
            if updated != new or updated_raw != new_raw:
                _fail("normalization_journal_update_invalid")
            os.unlink(temporary, dir_fd=state_fd)
            temporary = ""
            os.fsync(state_fd)
            return _sha256(new_raw)
        finally:
            if current_fd >= 0:
                os.close(current_fd)
            if temporary and temporary_is_candidate:
                try:
                    os.unlink(temporary, dir_fd=state_fd)
                except OSError:
                    pass
            os.close(state_fd)
            os.close(home_fd)

    def _verify_terminal_receipt(
        self,
        payload: Mapping[str, Any],
        terminal: Mapping[str, Any],
    ) -> None:
        required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
        if any(not hasattr(os, item) for item in required):
            _fail("normalization_journal_nofollow_unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        release_root = Path(str(payload["release_root"]))
        receipt_path = Path(str(terminal["receipt_path"]))
        root_fd = runtime_fd = receipt_fd = -1
        try:
            root_before = release_root.lstat()
            root_fd = os.open(release_root, flags)
            root_open = os.fstat(root_fd)
            root_after = release_root.lstat()
            if (
                not stat.S_ISDIR(root_open.st_mode)
                or stat.S_ISLNK(root_before.st_mode)
                or root_open.st_uid != self._owner_uid
                or stat.S_IMODE(root_open.st_mode) & 0o022
                or (root_before.st_dev, root_before.st_ino)
                != (root_open.st_dev, root_open.st_ino)
                or (root_after.st_dev, root_after.st_ino)
                != (root_open.st_dev, root_open.st_ino)
            ):
                _fail("normalization_journal_receipt_root_invalid")
            runtime_path_metadata = os.stat(
                ".runtime", dir_fd=root_fd, follow_symlinks=False
            )
            runtime_fd = os.open(".runtime", flags, dir_fd=root_fd)
            runtime_open = os.fstat(runtime_fd)
            if (
                not stat.S_ISDIR(runtime_open.st_mode)
                or runtime_open.st_uid != self._owner_uid
                or stat.S_IMODE(runtime_open.st_mode) != 0o700
                or (runtime_path_metadata.st_dev, runtime_path_metadata.st_ino)
                != (runtime_open.st_dev, runtime_open.st_ino)
            ):
                _fail("normalization_journal_receipt_directory_invalid")
            receipt_fd = os.open(
                receipt_path.name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=runtime_fd,
            )
            before = os.fstat(receipt_fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != self._owner_uid
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= MAX_JOURNAL_BYTES
            ):
                _fail("normalization_journal_receipt_untrusted")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(receipt_fd, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(receipt_fd)
            path_metadata = os.stat(
                receipt_path.name, dir_fd=runtime_fd, follow_symlinks=False
            )
            if (
                remaining
                or len(raw) != before.st_size
                or _sha256(raw) != terminal["receipt_sha256"]
                or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (before.st_dev, before.st_ino)
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                _fail("normalization_journal_receipt_changed")
            receipt = _strict_json_object(raw)
            expected_keys = {
                "contract_name",
                "version",
                "transaction_id",
                "status",
                "journal_terminal_kind",
                "journal_verification_sha256",
                "terminal_observation",
                "source_revision",
                "public_origin",
                "service_scope",
                "ingress_mutation_scope",
                "promotion_authority",
                "candidate_authority",
                "normalization_completed",
                "execution",
                "retained_bundle",
                "completed_at",
            }
            if set(receipt) != expected_keys:
                _fail("normalization_journal_receipt_binding_invalid")
            try:
                terminal_observation_record = {
                    "verification_sha256": terminal["verification_sha256"],
                    "api_domain_sha256": terminal["api_domain_sha256"],
                    "cloudflared_domain_sha256": terminal["cloudflared_domain_sha256"],
                    "public_network_identity_sha256": terminal[
                        "public_network_identity_sha256"
                    ],
                    "public_edge_identity_sha256": terminal[
                        "public_edge_identity_sha256"
                    ],
                    "docker_daemon_identity_sha256": terminal[
                        "docker_daemon_identity_sha256"
                    ],
                    "protected_tag_state": terminal["protected_tag_state"],
                    "api_topology_label_evidence": terminal[
                        "api_topology_label_evidence"
                    ],
                    "normalization_completed": terminal["normalization_completed"],
                }
                expected_receipt = terminal_receipt_payload(
                    payload,
                    kind=str(terminal["kind"]),
                    observation=terminal_observation_record,
                    completed_at=str(terminal["recorded_at"]),
                )
            except NormalizationJournalError as exc:
                raise NormalizationJournalError(
                    "normalization_journal_receipt_binding_invalid"
                ) from exc
            if receipt != expected_receipt:
                _fail("normalization_journal_receipt_binding_invalid")
            os.fsync(receipt_fd)
            os.fsync(runtime_fd)
            runtime_current = os.stat(".runtime", dir_fd=root_fd, follow_symlinks=False)
            root_current = release_root.lstat()
            if (runtime_current.st_dev, runtime_current.st_ino) != (
                runtime_open.st_dev,
                runtime_open.st_ino,
            ) or (root_current.st_dev, root_current.st_ino) != (
                root_open.st_dev,
                root_open.st_ino,
            ):
                _fail("normalization_journal_receipt_directory_changed")
        except NormalizationJournalError:
            raise
        except OSError as exc:
            raise NormalizationJournalError(
                "normalization_journal_receipt_unavailable"
            ) from exc
        finally:
            for fd in (receipt_fd, runtime_fd, root_fd):
                if fd >= 0:
                    os.close(fd)

    def remove(self, *, expected: Mapping[str, Any]) -> None:
        owned = validate_payload(
            expected,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        terminal = owned["evidence"]["terminal"]
        expected_terminal = {
            "prepared": {"clean_abort"},
            "commit_pending": {"durable_commit"},
            "rollback_in_progress": {
                "verified_recovery",
                "verified_forward_recovery",
            },
            "cleanup_pending": set(TERMINAL_RECEIPT_STATUS),
        }.get(str(owned["phase"]), set())
        if terminal is None or terminal["kind"] not in expected_terminal:
            _fail("normalization_journal_cleanup_phase_invalid")
        self._verify_terminal_receipt(owned, terminal)

        if owned["phase"] != "cleanup_pending":
            cleanup = dict(owned)
            cleanup["phase"] = "cleanup_pending"
            cleanup["api_mutation_possible"] = terminal["kind"] != "clean_abort"
            cleanup = validate_payload(
                cleanup,
                expected_path=self.path,
                expected_operator_anchor=self.operator_anchor,
            )
            _require_transition(owned, cleanup)
            self.update(expected=owned, replacement=cleanup)
            owned = cleanup

        expected_raw = _journal_bytes(owned)
        try:
            home_fd, state_fd = self._open_directory(create=False)
        except FileNotFoundError:
            return
        current_fd = -1
        try:
            try:
                current, current_raw, current_metadata, current_fd = (
                    self._read_open_held(home_fd, state_fd)
                )
            except FileNotFoundError:
                self._revalidate_directory(home_fd, state_fd)
                return
            self._cleanup_update_leftover(
                home_fd,
                state_fd,
                current=current,
                current_raw=current_raw,
            )
            if current != owned or current_raw != expected_raw:
                _fail("normalization_journal_not_owned")
            immediately_before = os.stat(
                self.path.name, dir_fd=state_fd, follow_symlinks=False
            )
            held = os.fstat(current_fd)
            if (immediately_before.st_dev, immediately_before.st_ino) != (
                current_metadata.st_dev,
                current_metadata.st_ino,
            ) or (held.st_dev, held.st_ino) != (
                current_metadata.st_dev,
                current_metadata.st_ino,
            ):
                _fail("normalization_journal_replaced")
            os.unlink(self.path.name, dir_fd=state_fd)
            os.fsync(state_fd)
            try:
                os.stat(self.path.name, dir_fd=state_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                _fail("normalization_journal_remove_failed")
            self._revalidate_directory(home_fd, state_fd)
        finally:
            if current_fd >= 0:
                os.close(current_fd)
            os.close(state_fd)
            os.close(home_fd)

    def new_payload(
        self,
        *,
        transaction_id: str,
        release_root: Path,
        transaction_receipt_path: Path,
        public_origin: str,
        retained_bundle_path: Path,
        retained_bundle_manifest_path: Path,
        retained_bundle_manifest_sha256: str,
        retained_bundle_plan_sha256: str,
        ordered_compose_files: Sequence[Path],
        environment_file: Path,
        environment_local_file: Path | None,
        source_revision: str,
        image_id: str,
        image_reference: str,
        compose_config_hash: str,
        docker_daemon_identity: str,
        api_identity: Mapping[str, Any],
        cloudflared_identity: Mapping[str, Any],
        public_network_identity: Mapping[str, Any],
        public_edge_identity: Mapping[str, Any],
        now: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now or _utc_now()
        payload: dict[str, Any] = {
            "contract_name": CONTRACT_NAME,
            "version": CONTRACT_VERSION,
            "material_classification": "private_secret_bearing_recovery_state",
            "contains_secret_material": True,
            "environment_values_included": False,
            "retention_policy": ("until_verified_terminal_cleanup"),
            "transaction_id": transaction_id,
            "phase": "prepared",
            "created_at": timestamp,
            "updated_at": timestamp,
            "recovery_attempts": 0,
            "api_mutation_possible": False,
            "api_boundary_authorized": False,
            "operator_anchor": str(self.operator_anchor),
            "recovery_journal_path": str(self.path),
            "release_root": str(release_root),
            "transaction_receipt_path": str(transaction_receipt_path),
            "public_origin": public_origin,
            "retained_bundle": {
                "path": str(retained_bundle_path),
                "manifest_path": str(retained_bundle_manifest_path),
                "recovery_seal": {
                    "contract_name": BUNDLE_RECOVERY_SEAL_CONTRACT_NAME,
                    "manifest_sha256": retained_bundle_manifest_sha256,
                    "plan_sha256": retained_bundle_plan_sha256,
                },
                "ordered_compose_files": [str(path) for path in ordered_compose_files],
                "environment_file": str(environment_file),
                "environment_local_file": (
                    str(environment_local_file)
                    if environment_local_file is not None
                    else None
                ),
                "environment_local_present": environment_local_file is not None,
            },
            "source_revision": source_revision,
            "previous_image": {
                "image_id": image_id,
                "image_reference": image_reference,
                "rollback_tag": deterministic_rollback_tag(transaction_id),
            },
            "baselines": {
                "compose_config_hash": compose_config_hash,
                "docker_daemon_identity_sha256": _docker_daemon_identity_sha256(
                    docker_daemon_identity
                ),
                "api_identity": container_identity(api_identity),
                "cloudflared_identity": container_identity(cloudflared_identity),
                "public_network_identity": identity(public_network_identity),
                "public_edge_identity": identity(public_edge_identity),
                "target_api_topology_label_evidence": (
                    _target_api_topology_label_evidence(
                        bundle_path=retained_bundle_path,
                        ordered_compose_files=ordered_compose_files,
                        environment_file=environment_file,
                        environment_local_file=environment_local_file,
                        compose_config_hash=compose_config_hash,
                    )
                ),
            },
            "evidence": {
                "protected_image": None,
                "api_mutation": None,
                "terminal": None,
            },
        }
        return validate_payload(
            payload,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )

    def with_phase(
        self,
        payload: Mapping[str, Any],
        phase: str,
        *,
        now: str | None = None,
        recovery_attempts: int | None = None,
    ) -> dict[str, Any]:
        current = validate_payload(
            payload,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        if phase not in _TRANSITIONS[str(current["phase"])]:
            _fail("normalization_journal_transition_invalid")
        updated = dict(current)
        updated["phase"] = phase
        updated["updated_at"] = now or _utc_now()
        expected_attempts = int(current["recovery_attempts"]) + (
            1 if phase == "rollback_in_progress" else 0
        )
        if recovery_attempts is not None and recovery_attempts != expected_attempts:
            _fail("normalization_journal_transition_invalid")
        updated["recovery_attempts"] = expected_attempts
        updated["api_mutation_possible"] = phase in {
            "api_mutation_possible",
            "commit_pending",
            "rollback_in_progress",
            "rollback_failed",
        }
        updated["api_boundary_authorized"] = bool(
            current["api_boundary_authorized"] or phase == "api_mutation_possible"
        )
        validate_payload(
            updated,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        return updated

    def record_protected_image(
        self,
        payload: Mapping[str, Any],
        *,
        observed_image_id: str,
        observed_rollback_tag: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        current = validate_payload(
            payload,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        if (
            current["phase"] != "protect_previous_image_possible"
            or current["evidence"]["protected_image"] is not None
        ):
            _fail("normalization_journal_evidence_transition_invalid")
        timestamp = now or _utc_now()
        verification_sha256 = _evidence_sha256(
            "protected_image",
            {
                "image_id": observed_image_id,
                "rollback_tag": observed_rollback_tag,
            },
        )
        updated = dict(current)
        updated["evidence"] = dict(current["evidence"])
        updated["evidence"]["protected_image"] = {
            "recorded_at": timestamp,
            "verification_sha256": verification_sha256,
            "image_id": observed_image_id,
            "rollback_tag": observed_rollback_tag,
        }
        updated["updated_at"] = timestamp
        return validate_payload(
            updated,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )

    def record_api_mutation(
        self,
        payload: Mapping[str, Any],
        *,
        observed_api_identity: Mapping[str, Any],
        now: str | None = None,
    ) -> dict[str, Any]:
        current = validate_payload(
            payload,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        if (
            current["phase"] != "api_mutation_possible"
            or current["evidence"]["protected_image"] is None
            or current["evidence"]["api_mutation"] is not None
        ):
            _fail("normalization_journal_evidence_transition_invalid")
        timestamp = now or _utc_now()
        observed = _identity_projection(
            container_identity(observed_api_identity),
            name="api_identity",
            expected_config_hash=str(current["baselines"]["compose_config_hash"]),
        )
        api_domain_sha256 = observed["domain_sha256"]
        verification_sha256 = _evidence_sha256(
            "api_mutation", {"api_domain_sha256": api_domain_sha256}
        )
        updated = dict(current)
        updated["evidence"] = dict(current["evidence"])
        updated["evidence"]["api_mutation"] = {
            "recorded_at": timestamp,
            "verification_sha256": verification_sha256,
            "api_domain_sha256": api_domain_sha256,
        }
        updated["updated_at"] = timestamp
        return validate_payload(
            updated,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )

    def record_terminal_evidence(
        self,
        payload: Mapping[str, Any],
        *,
        kind: str,
        receipt_sha256: str,
        observed_api_identity: Mapping[str, Any],
        observed_cloudflared_identity: Mapping[str, Any],
        observed_public_network_identity: Mapping[str, Any],
        observed_public_edge_identity: Mapping[str, Any],
        observed_docker_daemon_identity: str,
        observed_protected_image_id: str | None,
        now: str | None = None,
    ) -> dict[str, Any]:
        current = validate_payload(
            payload,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
        permitted = {
            "prepared": {"clean_abort"},
            "api_mutation_possible": {"durable_commit"},
            "rollback_in_progress": {
                "verified_recovery",
                "verified_forward_recovery",
            },
        }.get(str(current["phase"]), set())
        if (
            kind not in permitted
            or current["evidence"]["terminal"] is not None
            or not _is_hex(receipt_sha256)
            or (
                kind == "durable_commit" and current["evidence"]["api_mutation"] is None
            )
            or (
                kind == "verified_forward_recovery"
                and not current["api_boundary_authorized"]
            )
            or (kind == "verified_recovery" and current["api_boundary_authorized"])
        ):
            _fail("normalization_journal_evidence_transition_invalid")
        timestamp = now or _utc_now()
        observation = terminal_observation(
            api_identity=observed_api_identity,
            cloudflared_identity=observed_cloudflared_identity,
            public_network_identity=observed_public_network_identity,
            public_edge_identity=observed_public_edge_identity,
            docker_daemon_identity=observed_docker_daemon_identity,
            observed_protected_image_id=observed_protected_image_id,
            expected_protected_image_id=str(current["previous_image"]["image_id"]),
            compose_config_hash=str(current["baselines"]["compose_config_hash"]),
            public_origin=str(current["public_origin"]),
            baseline_api_topology_label_evidence=current["baselines"]["api_identity"][
                "projection"
            ]["topology_label_evidence"],
            target_api_topology_label_evidence=current["baselines"][
                "target_api_topology_label_evidence"
            ],
        )
        verification_sha256 = observation.pop("verification_sha256")
        updated = dict(current)
        updated["evidence"] = dict(current["evidence"])
        updated["evidence"]["terminal"] = {
            "kind": kind,
            "recorded_at": timestamp,
            "verification_sha256": verification_sha256,
            "receipt_path": current["transaction_receipt_path"],
            "receipt_sha256": receipt_sha256,
            **observation,
        }
        updated["updated_at"] = (
            timestamp
            if _timestamp(timestamp) >= _timestamp(current["updated_at"])
            else current["updated_at"]
        )
        return validate_payload(
            updated,
            expected_path=self.path,
            expected_operator_anchor=self.operator_anchor,
        )
