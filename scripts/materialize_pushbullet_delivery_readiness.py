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
REQUIRED_CLIENTS_ENV = "EA_PUSHBULLET_REQUIRED_CLIENTS"
MULTI_CLIENT_REQUIRED_ENV = "EA_PUSHBULLET_MULTI_CLIENT_REQUIRED"
CLIENT_KEY_RE = re.compile(r"[^a-z0-9_]+")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _required_client_keys(
    *,
    rows: list[dict[str, object]],
    values: Mapping[str, str],
    required_clients: tuple[str, ...],
    multi_client_expected: bool,
) -> tuple[str, ...]:
    explicit = _unique(list(required_clients) + list(_env_required_clients(values)))
    configured = _unique([str(row.get("client_key") or "") for row in rows])
    if not multi_client_expected:
        return explicit or configured

    primary_candidates = [
        key
        for key in list(explicit) + list(configured)
        if key and key != DEFAULT_SECOND_CLIENT_KEY
    ]
    keys = list(_unique(primary_candidates)) or [DEFAULT_PRIMARY_CLIENT_KEY]
    if DEFAULT_SECOND_CLIENT_KEY not in keys:
        keys.append(DEFAULT_SECOND_CLIENT_KEY)
    for key in explicit:
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def _client_coverage(
    *,
    rows: list[dict[str, object]],
    required_keys: tuple[str, ...],
    multi_client_expected: bool,
) -> dict[str, object]:
    by_key = {str(row.get("client_key") or ""): row for row in rows}
    missing_client_keys = [key for key in required_keys if key not in by_key]
    missing_token_keys = [
        key
        for key in required_keys
        if key in by_key and not bool(by_key[key].get("token_present"))
    ]
    configured_required_count = len([key for key in required_keys if key in by_key])
    token_present_required_count = len(
        [
            key
            for key in required_keys
            if key in by_key and bool(by_key[key].get("token_present"))
        ]
    )
    multi_client_ready = (
        bool(multi_client_expected)
        and len(required_keys) >= 2
        and not missing_client_keys
        and not missing_token_keys
    )
    return {
        "multi_client_expected": bool(multi_client_expected),
        "expected_client_count": len(required_keys),
        "configured_client_count": len(rows),
        "configured_required_client_count": configured_required_count,
        "token_present_required_client_count": token_present_required_count,
        "missing_client_keys": missing_client_keys,
        "missing_token_keys": missing_token_keys,
        "multi_client_ready": multi_client_ready,
    }


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
    multi_client_expected = _env_bool(values, MULTI_CLIENT_REQUIRED_ENV, default=True)
    required_keys = _required_client_keys(
        rows=rows,
        values=values,
        required_clients=required_clients,
        multi_client_expected=multi_client_expected,
    )
    coverage = _client_coverage(
        rows=rows,
        required_keys=required_keys,
        multi_client_expected=multi_client_expected,
    )

    missing_setup: list[str] = []
    if not rows:
        missing_setup.append("pushbullet_client_config_missing")
    for key in required_keys:
        row = by_key.get(key)
        if row is None:
            missing_setup.append(f"pushbullet_client_missing:{key}")
        elif not bool(row.get("token_present")):
            missing_setup.append(f"pushbullet_token_missing:{key}")

    live_probes: list[dict[str, object]] = []
    if probe_live:
        for key in required_keys:
            if by_key.get(key) and bool(by_key[key].get("token_present")):
                probe = probe_pushbullet_client(key, env=values, timeout=timeout_seconds)
                live_probes.append(probe)
                if str(probe.get("status") or "").strip() != "pass":
                    missing_setup.append(f"pushbullet_live_probe_failed:{key}")

    if missing_setup:
        status = "blocked_setup_required"
    elif probe_live:
        status = "ready_live_verified"
    else:
        status = "ready_configured"

    setup_checklist = [
        {
            "key": "configure_pushbullet_clients",
            "label": "Configure every expected Pushbullet client",
            "how": (
                "Keep the original/default Pushbullet client configured and add the Elisabeth client. "
                "Use the listed token env vars so action-required delivery can target the right account."
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
        "client_coverage": coverage,
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
            "live_token_account_verified": status == "ready_live_verified",
            "irreversible_actions_consent_gated": True,
            "non_action_progress_push_allowed": False,
        },
        "operator_action": {
            "user_action_required": bool(missing_setup),
            "missing_setup": missing_setup,
            "required_client_keys": list(required_keys),
            "client_coverage": coverage,
            "delivery_policy": "action_required_only" if missing_setup else "queue_only",
            "telegram_push_allowed": bool(missing_setup),
            "interruption_budget": "action_required" if missing_setup else "none",
            "next_action": "create_missing_pushbullet_access_tokens" if missing_setup else "keep_pushbullet_clients_configured",
            "next_action_label": "Open Pushbullet account settings",
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
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--env-file", action="append", default=[str(ROOT / ".env"), str(EA_ROOT / ".env")])
    parser.add_argument("--required-client", action="append", default=[])
    parser.add_argument("--probe-live", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)

    for raw_path in args.env_file or []:
        _load_env_file(Path(raw_path))

    receipt = build_receipt(
        required_clients=tuple(args.required_client or ()),
        probe_live=bool(args.probe_live),
        timeout_seconds=float(args.timeout_seconds),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
