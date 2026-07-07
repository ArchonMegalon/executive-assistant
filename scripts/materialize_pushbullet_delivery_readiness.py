#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(EA_ROOT), str(ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

from app.services.pushbullet_delivery import (
    PUSHBULLET_ACCOUNT_SETTINGS_URL,
    PUSHBULLET_DOCS_URL,
    discover_pushbullet_clients,
    probe_pushbullet_client,
)

DEFAULT_OUTPUT = ROOT / ".codex-studio/published/ea_pushbullet_delivery_readiness.generated.json"
CONTRACT_NAME = "ea.pushbullet_delivery_readiness.v1"
DEFAULT_SECOND_CLIENT_KEY = "elisabeth"
DEFAULT_PRIMARY_CLIENT_KEY = "default"
DEFAULT_CLIENT_REF_ENV = "EA_PUSHBULLET_DEFAULT_CLIENT"
REQUIRED_CLIENTS_ENV = "EA_PUSHBULLET_REQUIRED_CLIENTS"
MULTI_CLIENT_REQUIRED_ENV = "EA_PUSHBULLET_MULTI_CLIENT_REQUIRED"
RELAY_ENABLED_ENV = "EA_PUSHBULLET_RELAY_ENABLED"
SCHEDULER_RELAY_ENABLED_ENV = "EA_SCHEDULER_PUSHBULLET_RELAY_ENABLED"
RELAY_PRIMARY_CLIENT_ENV = "EA_PUSHBULLET_RELAY_PRIMARY_CLIENT"
RELAY_SECONDARY_CLIENT_ENV = "EA_PUSHBULLET_RELAY_SECONDARY_CLIENT"
RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED_ENV = "EA_PUSHBULLET_RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED"
RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED_ENV = "EA_PUSHBULLET_RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED"
CLIENT_KEY_RE = re.compile(r"[^a-z0-9_]+")
RUNTIME_LEDGER_DIR_ENV = "EA_RESPONSES_PROVIDER_LEDGER_DIR"
RUNTIME_LEDGER_FILENAME = "pushbullet_readiness.generated.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_output_path(values: Mapping[str, str] | None = None) -> Path:
    env_values = values if values is not None else os.environ
    ledger_dir = str(env_values.get(RUNTIME_LEDGER_DIR_ENV) or "").strip()
    if ledger_dir:
        return Path(ledger_dir) / RUNTIME_LEDGER_FILENAME
    return DEFAULT_OUTPUT


def _load_env_file(path: Path | None) -> None:
    if path is None or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _client_row(client: object) -> dict[str, object]:
    return {
        "client_key": str(getattr(client, "client_key", "") or "").strip(),
        "email_sha256": str(getattr(client, "email_sha256", "") or "").strip(),
        "email_domain": str(getattr(client, "email_domain", "") or "").strip(),
        "email_present": bool(getattr(client, "email_present", False)),
        "token_env": str(getattr(client, "token_env", "") or "").strip(),
        "token_present": bool(getattr(client, "token_present", False)),
        "source": str(getattr(client, "source", "") or "").strip(),
        "raw_email_exposed": False,
        "raw_token_exposed": False,
    }


def _client_key(value: object) -> str:
    normalized = str(value or "").strip().lower()
    normalized = CLIENT_KEY_RE.sub("_", normalized).strip("_")
    return normalized or DEFAULT_PRIMARY_CLIENT_KEY


def _optional_client_key(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return CLIENT_KEY_RE.sub("_", normalized).strip("_")


def _unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    keys: list[str] = []
    for value in values:
        key = _client_key(value)
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return tuple(keys)


def _env_bool(values: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = str(values.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def _env_required_clients(values: Mapping[str, str]) -> tuple[str, ...]:
    raw = str(values.get(REQUIRED_CLIENTS_ENV) or "").strip()
    if not raw:
        return ()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            return _unique([str(item) for item in parsed])
    return _unique([item for item in re.split(r"[,;\s]+", raw) if item.strip()])


def _declared_required_client_keys(
    *,
    values: Mapping[str, str],
    required_clients: tuple[str, ...],
) -> tuple[str, ...]:
    return _unique(list(required_clients) + list(_env_required_clients(values)))


def _default_client_ref(values: Mapping[str, str]) -> str:
    return _optional_client_key(values.get(DEFAULT_CLIENT_REF_ENV))


def _required_client_keys(
    *,
    values: Mapping[str, str],
    declared_required_keys: tuple[str, ...],
    multi_client_expected: bool,
) -> tuple[str, ...]:
    keys: list[str] = []
    if multi_client_expected:
        keys.extend([DEFAULT_PRIMARY_CLIENT_KEY, DEFAULT_SECOND_CLIENT_KEY])
    if _relay_enabled(values):
        keys.append(_relay_client_key(values, RELAY_PRIMARY_CLIENT_ENV, default=DEFAULT_PRIMARY_CLIENT_KEY))
        keys.append(_relay_client_key(values, RELAY_SECONDARY_CLIENT_ENV, default=DEFAULT_SECOND_CLIENT_KEY))
    for key in declared_required_keys:
        if key not in keys:
            keys.append(key)
    return _unique(keys) or declared_required_keys or (DEFAULT_PRIMARY_CLIENT_KEY,)


def _token_required_client_keys(
    *,
    values: Mapping[str, str],
    required_keys: tuple[str, ...],
    declared_required_keys: tuple[str, ...],
    multi_client_expected: bool,
) -> tuple[str, ...]:
    keys: list[str] = []
    if DEFAULT_PRIMARY_CLIENT_KEY in required_keys:
        keys.append(DEFAULT_PRIMARY_CLIENT_KEY)
    if multi_client_expected and DEFAULT_SECOND_CLIENT_KEY in required_keys:
        keys.append(DEFAULT_SECOND_CLIENT_KEY)
    if _relay_enabled(values):
        if _env_bool(values, RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED_ENV, default=True):
            keys.append(_relay_client_key(values, RELAY_PRIMARY_CLIENT_ENV, default=DEFAULT_PRIMARY_CLIENT_KEY))
        if _env_bool(values, RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED_ENV, default=True):
            keys.append(_relay_client_key(values, RELAY_SECONDARY_CLIENT_ENV, default=DEFAULT_SECOND_CLIENT_KEY))
    for key in declared_required_keys:
        if key not in keys:
            keys.append(key)
    return _unique(keys)


def _client_coverage(
    *,
    rows: list[dict[str, object]],
    required_keys: tuple[str, ...],
    token_required_keys: tuple[str, ...],
    multi_client_expected: bool,
    default_client_ref: str,
) -> dict[str, object]:
    by_key = {str(row.get("client_key") or ""): row for row in rows}
    default_alias_row = by_key.get(default_client_ref) if default_client_ref else None
    default_client_ref_present = bool(default_client_ref)
    default_client_ref_resolves = default_alias_row is not None
    missing_client_keys: list[str] = []
    missing_token_keys: list[str] = []
    configured_required_count = 0
    token_present_required_count = 0
    for key in required_keys:
        row = by_key.get(key)
        if row is None and key == DEFAULT_PRIMARY_CLIENT_KEY and default_alias_row is not None:
            row = default_alias_row
        if row is None:
            missing_client_keys.append(key)
            continue
        configured_required_count += 1
    for key in token_required_keys:
        row = by_key.get(key)
        if row is None and key == DEFAULT_PRIMARY_CLIENT_KEY and default_alias_row is not None:
            row = default_alias_row
        if row is None:
            continue
        if bool(row.get("token_present")):
            token_present_required_count += 1
            continue
        if key == DEFAULT_PRIMARY_CLIENT_KEY and str(row.get("client_key") or "") != DEFAULT_PRIMARY_CLIENT_KEY:
            continue
        missing_token_keys.append(key)
    multi_client_ready = (
        bool(multi_client_expected)
        and len(required_keys) >= 2
        and not missing_client_keys
        and not missing_token_keys
    )
    return {
        "multi_client_expected": bool(multi_client_expected),
        "expected_client_count": len(required_keys),
        "token_required_client_count": len(token_required_keys),
        "configured_client_count": len(rows),
        "configured_required_client_count": configured_required_count,
        "token_present_required_client_count": token_present_required_count,
        "missing_client_keys": missing_client_keys,
        "missing_token_keys": missing_token_keys,
        "multi_client_ready": multi_client_ready,
        "default_client_ref_present": default_client_ref_present,
        "default_client_ref_resolves": default_client_ref_resolves,
    }


def _resolved_required_row(
    required_key: str,
    *,
    by_key: Mapping[str, dict[str, object]],
    default_client_ref: str,
) -> dict[str, object] | None:
    row = dict(by_key.get(required_key) or {}) if isinstance(by_key.get(required_key), dict) else None
    if row is not None:
        return row
    if required_key == DEFAULT_PRIMARY_CLIENT_KEY and default_client_ref:
        alias = by_key.get(default_client_ref)
        return dict(alias) if isinstance(alias, dict) else None
    return None


def _relay_enabled(values: Mapping[str, str]) -> bool:
    return _env_bool(values, RELAY_ENABLED_ENV, default=False) or _env_bool(values, SCHEDULER_RELAY_ENABLED_ENV, default=False)


def _relay_client_key(values: Mapping[str, str], env_name: str, *, default: str) -> str:
    return _client_key(values.get(env_name) or default)


def _relay_status(
    *,
    values: Mapping[str, str],
    by_key: Mapping[str, dict[str, object]],
    default_client_ref: str,
    probe_live: bool,
) -> dict[str, object]:
    enabled = _relay_enabled(values)
    primary_client_key = _relay_client_key(values, RELAY_PRIMARY_CLIENT_ENV, default=DEFAULT_PRIMARY_CLIENT_KEY)
    secondary_client_key = _relay_client_key(values, RELAY_SECONDARY_CLIENT_ENV, default=DEFAULT_SECOND_CLIENT_KEY)
    primary_row = _resolved_required_row(primary_client_key, by_key=by_key, default_client_ref=default_client_ref)
    secondary_row = _resolved_required_row(secondary_client_key, by_key=by_key, default_client_ref=default_client_ref)
    resolved_primary_client_key = str((primary_row or {}).get("client_key") or "").strip()
    resolved_secondary_client_key = str((secondary_row or {}).get("client_key") or "").strip()
    primary_email_sha256 = str((primary_row or {}).get("email_sha256") or "").strip()
    secondary_email_sha256 = str((secondary_row or {}).get("email_sha256") or "").strip()
    distinct_client_keys_ready = bool(
        resolved_primary_client_key
        and resolved_secondary_client_key
        and resolved_primary_client_key != resolved_secondary_client_key
    )
    distinct_account_hashes_ready = bool(
        primary_email_sha256
        and secondary_email_sha256
        and primary_email_sha256 != secondary_email_sha256
    )
    missing_setup: list[str] = []
    if enabled:
        if not primary_row:
            missing_setup.append(f"pushbullet_relay_client_missing:{primary_client_key}")
        if not secondary_row:
            missing_setup.append(f"pushbullet_relay_client_missing:{secondary_client_key}")
        if primary_row and secondary_row and not distinct_client_keys_ready:
            missing_setup.append("pushbullet_relay_distinct_clients_required")
        if primary_row and secondary_row and distinct_client_keys_ready and not distinct_account_hashes_ready:
            missing_setup.append("pushbullet_relay_distinct_accounts_required")
    return {
        "enabled": enabled,
        "primary_client_key": primary_client_key,
        "secondary_client_key": secondary_client_key,
        "resolved_primary_client_key": resolved_primary_client_key,
        "resolved_secondary_client_key": resolved_secondary_client_key,
        "primary_uses_default_alias": bool(
            primary_client_key == DEFAULT_PRIMARY_CLIENT_KEY
            and default_client_ref
            and resolved_primary_client_key
            and resolved_primary_client_key != DEFAULT_PRIMARY_CLIENT_KEY
        ),
        "secondary_uses_default_alias": bool(
            secondary_client_key == DEFAULT_PRIMARY_CLIENT_KEY
            and default_client_ref
            and resolved_secondary_client_key
            and resolved_secondary_client_key != DEFAULT_PRIMARY_CLIENT_KEY
        ),
        "distinct_client_keys_ready": distinct_client_keys_ready,
        "distinct_account_hashes_ready": distinct_account_hashes_ready,
        "live_verified": bool(probe_live and enabled and distinct_client_keys_ready and distinct_account_hashes_ready),
        "missing_setup": missing_setup,
        "raw_email_exposed": False,
    }


def _account_label(
    *,
    by_key: Mapping[str, dict[str, object]],
    required_keys: tuple[str, ...],
    default_client_ref: str,
) -> tuple[str, str]:
    if DEFAULT_PRIMARY_CLIENT_KEY in required_keys:
        if DEFAULT_PRIMARY_CLIENT_KEY in by_key:
            return DEFAULT_PRIMARY_CLIENT_KEY, "literal_default_client"
        if default_client_ref:
            if default_client_ref in by_key:
                return f"{DEFAULT_PRIMARY_CLIENT_KEY}->{default_client_ref}", "default_client_ref"
            return f"{DEFAULT_PRIMARY_CLIENT_KEY}->{default_client_ref}(missing)", "default_client_ref_missing"
        return f"{DEFAULT_PRIMARY_CLIENT_KEY}(missing)", "default_client_missing"

    for key in required_keys:
        if key in by_key:
            return key, "required_client"
    if required_keys:
        return f"{required_keys[0]}(missing)", "required_client_missing"
    if by_key:
        first_key = next(iter(sorted(by_key)))
        return first_key, "configured_client"
    return "", "missing"


def build_receipt(
    *,
    env: Mapping[str, str] | None = None,
    required_clients: tuple[str, ...] = (),
    probe_live: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    values = env if env is not None else os.environ
    clients = list(discover_pushbullet_clients(values))
    rows = [_client_row(client) for client in clients]
    by_key = {str(row.get("client_key") or ""): row for row in rows}
    default_client_ref = _default_client_ref(values)
    multi_client_expected = _env_bool(values, MULTI_CLIENT_REQUIRED_ENV, default=True)
    declared_required_keys = _declared_required_client_keys(values=values, required_clients=required_clients)
    required_keys = _required_client_keys(
        values=values,
        declared_required_keys=declared_required_keys,
        multi_client_expected=multi_client_expected,
    )
    token_required_keys = _token_required_client_keys(
        values=values,
        required_keys=required_keys,
        declared_required_keys=declared_required_keys,
        multi_client_expected=multi_client_expected,
    )
    coverage = _client_coverage(
        rows=rows,
        required_keys=required_keys,
        token_required_keys=token_required_keys,
        multi_client_expected=multi_client_expected,
        default_client_ref=default_client_ref,
    )
    default_alias_row = by_key.get(default_client_ref) if default_client_ref else None
    relay = _relay_status(
        values=values,
        by_key=by_key,
        default_client_ref=default_client_ref,
        probe_live=probe_live,
    )
    if bool(relay.get("enabled")) and bool(relay.get("missing_setup")):
        coverage["multi_client_ready"] = False
    account_label, account_label_basis = _account_label(
        by_key=by_key,
        required_keys=required_keys,
        default_client_ref=default_client_ref,
    )

    missing_setup: list[str] = []
    if not rows:
        missing_setup.append("pushbullet_client_config_missing")
    for key in required_keys:
        row = by_key.get(key)
        if row is None and key == DEFAULT_PRIMARY_CLIENT_KEY and default_alias_row is not None:
            row = default_alias_row
        if row is None:
            missing_setup.append(f"pushbullet_client_missing:{key}")
    for key in token_required_keys:
        row = _resolved_required_row(key, by_key=by_key, default_client_ref=default_client_ref)
        if row is None:
            continue
        if not bool(row.get("token_present")) and not (
            key == DEFAULT_PRIMARY_CLIENT_KEY and str(row.get("client_key") or "") != DEFAULT_PRIMARY_CLIENT_KEY
        ): 
            missing_setup.append(f"pushbullet_token_missing:{key}")

    live_probes: list[dict[str, object]] = []
    probed_client_keys: set[str] = set()
    if probe_live:
        for key in token_required_keys:
            row = _resolved_required_row(key, by_key=by_key, default_client_ref=default_client_ref)
            actual_client_key = str((row or {}).get("client_key") or "").strip()
            if (
                row
                and bool(row.get("token_present"))
                and actual_client_key
                and actual_client_key not in probed_client_keys
            ):
                probe = probe_pushbullet_client(actual_client_key, env=values, timeout=timeout_seconds)
                live_probes.append(probe)
                if str(probe.get("status") or "").strip() != "pass":
                    missing_setup.append(f"pushbullet_live_probe_failed:{actual_client_key}")
                probed_client_keys.add(actual_client_key)
    missing_setup.extend(str(item) for item in list(relay.get("missing_setup") or []) if str(item or "").strip())
    missing_setup = list(dict.fromkeys(missing_setup))
    relay["live_verified"] = bool(
        probe_live
        and relay.get("enabled")
        and relay.get("distinct_client_keys_ready")
        and relay.get("distinct_account_hashes_ready")
        and not any(str(reason).startswith("pushbullet_live_probe_failed:") for reason in missing_setup)
    )

    if missing_setup:
        status = "blocked_setup_required"
    elif probe_live:
        status = "ready_live_verified"
    else:
        status = "ready_configured"

    live_probe_failures = [
        reason.removeprefix("pushbullet_live_probe_failed:").strip()
        for reason in missing_setup
        if str(reason).startswith("pushbullet_live_probe_failed:")
    ]

    setup_checklist = [
        {
            "key": "configure_pushbullet_clients",
            "label": "Configure every expected Pushbullet client",
            "how": (
                "Configure each expected Pushbullet client. If you do not keep a literal default client, set "
                "EA_PUSHBULLET_DEFAULT_CLIENT to an existing named client key so default-route delivery stays explicit."
            ),
        },
        {
            "key": "create_pushbullet_access_token",
            "label": "Create a Pushbullet access token for each missing token",
            "how": (
                "Open Pushbullet Account Settings, sign in as the intended account, create an access token, "
                "store it in the listed token env var, then rerun this readiness receipt."
            ),
        },
        {
            "key": "verify_pushbullet_account_match",
            "label": "Verify the token belongs to the expected account",
            "how": "Rerun this materializer with --probe-live so /v2/users/me can be compared against the configured account hash.",
        },
    ] if missing_setup else []
    if live_probe_failures:
        affected_clients = ", ".join(sorted({item for item in live_probe_failures if item}))
        setup_checklist.insert(
            0,
            {
                "key": "replace_mismatched_pushbullet_access_token",
                "label": "Replace the mismatched Pushbullet token",
                "how": (
                    "The configured Pushbullet token authenticated as the wrong account"
                    + (f" for {affected_clients}." if affected_clients else ".")
                    + " Sign in as the intended Pushbullet account, create a fresh access token, replace the existing "
                    "PB_TOKEN_* value, then rerun this readiness receipt with --probe-live."
                ),
            },
        )
    if relay.get("enabled") and any(
        reason in {"pushbullet_relay_distinct_clients_required", "pushbullet_relay_distinct_accounts_required"}
        or str(reason).startswith("pushbullet_relay_client_missing:")
        for reason in missing_setup
    ):
        setup_checklist.insert(
            0,
            {
                "key": "configure_pushbullet_relay_clients",
                "label": "Configure distinct Pushbullet accounts for relay",
                "how": (
                    "The Pushbullet relay needs two different configured accounts: one for the primary route "
                    f"({relay.get('primary_client_key')}) and one for the secondary route ({relay.get('secondary_client_key')}). "
                    "Do not point both relay sides at the same named/default client."
                ),
            },
        )
    if DEFAULT_PRIMARY_CLIENT_KEY in required_keys and DEFAULT_PRIMARY_CLIENT_KEY not in by_key and not coverage.get("default_client_ref_resolves"):
        setup_checklist.insert(
            0,
            {
                "key": "configure_pushbullet_default_client_ref",
                "label": "Choose the default Pushbullet delivery client",
                "how": (
                    "Either configure a literal default Pushbullet client with PUSHBULLET_EMAIL/PB_TOKEN, or set "
                    "EA_PUSHBULLET_DEFAULT_CLIENT to one of the existing named client keys."
                ),
            },
        )

    next_action = "keep_pushbullet_clients_configured"
    next_action_label = "Open Pushbullet account settings"
    if live_probe_failures:
        next_action = "replace_mismatched_pushbullet_access_token"
        next_action_label = "Replace the mismatched Pushbullet token"
    elif missing_setup:
        next_action = "create_missing_pushbullet_access_tokens"

    return {
        "contract_name": CONTRACT_NAME,
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_pushbullet_delivery_readiness.py",
        **_source_state(),
        "status": status,
        "provider": "pushbullet",
        "multi_client_expected": bool(multi_client_expected),
        "client_count": len(rows),
        "clients": rows,
        "required_client_keys": list(required_keys),
        "token_required_client_keys": list(token_required_keys),
        "account_label": account_label,
        "account_label_basis": account_label_basis,
        "default_client_ref_env": DEFAULT_CLIENT_REF_ENV,
        "default_client_ref": default_client_ref,
        "default_client_ref_present": bool(default_client_ref),
        "default_client_ref_resolves": bool(coverage.get("default_client_ref_resolves")),
        "client_coverage": coverage,
        "relay": relay,
        "missing_setup": missing_setup,
        "probe_live": bool(probe_live),
        "live_probes": live_probes,
        "api_base_url": "https://api.pushbullet.com",
        "account_settings_url": PUSHBULLET_ACCOUNT_SETTINGS_URL,
        "docs_url": PUSHBULLET_DOCS_URL,
        "privacy": {
            "raw_email_exposed": False,
            "raw_token_exposed": False,
            "raw_push_body_exposed": False,
            "raw_push_ids_exposed": False,
        },
        "delivery_claim": {
            "pushbullet_note_delivery_ready": status in {"ready_configured", "ready_live_verified"},
            "multi_client_delivery_ready": (
                status in {"ready_configured", "ready_live_verified"} and bool(coverage.get("multi_client_ready"))
            ),
            "pushbullet_relay_ready": status in {"ready_configured", "ready_live_verified"} and not bool(relay.get("missing_setup")),
            "pushbullet_relay_live_verified": (
                status == "ready_live_verified" and not bool(relay.get("missing_setup")) and bool(relay.get("enabled"))
            ),
            "live_token_account_verified": status == "ready_live_verified",
            "irreversible_actions_consent_gated": True,
            "non_action_progress_push_allowed": False,
        },
        "operator_action": {
            "user_action_required": bool(missing_setup),
            "missing_setup": missing_setup,
            "required_client_keys": list(required_keys),
            "token_required_client_keys": list(token_required_keys),
            "default_client_ref": default_client_ref,
            "default_client_ref_present": bool(default_client_ref),
            "default_client_ref_resolves": bool(coverage.get("default_client_ref_resolves")),
            "client_coverage": coverage,
            "delivery_policy": "action_required_only" if missing_setup else "queue_only",
            "telegram_push_allowed": bool(missing_setup),
            "interruption_budget": "action_required" if missing_setup else "none",
            "next_action": next_action,
            "next_action_label": next_action_label,
            "next_action_href": PUSHBULLET_ACCOUNT_SETTINGS_URL,
            "next_action_method": "get",
            "setup_checklist": setup_checklist,
            "raw_email_exposed": False,
            "raw_token_exposed": False,
            "raw_private_context_exposed": False,
        },
        "claim_boundary": (
            "A configured token can support Pushbullet note delivery, but live account ownership is proven only when "
            "--probe-live passes against /v2/users/me. This receipt does not send a push."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize EA Pushbullet multi-client delivery readiness.")
    parser.add_argument("--output", default="")
    parser.add_argument("--env-file", action="append", default=[str(ROOT / ".env"), str(EA_ROOT / ".env")])
    parser.add_argument("--required-client", action="append", default=[])
    parser.add_argument("--probe-live", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    for raw_path in args.env_file or []:
        _load_env_file(Path(raw_path))

    receipt = build_receipt(
        required_clients=tuple(args.required_client or ()),
        probe_live=bool(args.probe_live),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = Path(str(args.output).strip()) if str(args.output).strip() else _default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True) if args.pretty else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
