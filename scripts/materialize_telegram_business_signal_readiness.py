#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
DEFAULT_OUTPUT = ROOT / ".codex-studio/published/telegram_business_signal_readiness.generated.json"
CONTRACT_NAME = "ea.telegram_business_signal_readiness.v1"
ALLOWED_UPDATES = [
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
]


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _source_state() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _public_app_base_url() -> str:
    return _env("EA_PUBLIC_APP_BASE_URL").rstrip("/")


def _business_webhook_path(bot_key: str = "") -> str:
    normalized = str(bot_key or "").strip()
    if normalized and normalized != "default":
        return f"/v1/channels/telegram/business/ingest/{normalized}"
    return "/v1/channels/telegram/business/ingest"


def _business_webhook_url(bot_key: str = "") -> str:
    base = _public_app_base_url()
    return f"{base}{_business_webhook_path(bot_key)}" if base else ""


def _telegram_bot_registry() -> dict[str, dict[str, object]]:
    registry: dict[str, dict[str, object]] = {}
    raw = _env("EA_TELEGRAM_BOT_REGISTRY_JSON")
    if raw:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            for raw_key, value in parsed.items():
                if not isinstance(value, dict):
                    continue
                key = str(raw_key or "").strip()
                if not key:
                    continue
                registry[key] = {
                    "token_present": bool(str(value.get("token") or "").strip()),
                    "secret_present": bool(str(value.get("secret") or "").strip()),
                    "handle_present": bool(str(value.get("handle") or "").strip()),
                    "default_principal_present": bool(str(value.get("default_principal_id") or "").strip()),
                }
    if _env("EA_TELEGRAM_BOT_TOKEN"):
        registry.setdefault(
            "default",
            {
                "token_present": True,
                "secret_present": bool(_env("EA_TELEGRAM_INGEST_SECRET")),
                "handle_present": bool(_env("EA_TELEGRAM_BOT_HANDLE")),
                "default_principal_present": bool(_env("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or _env("EA_DEFAULT_PRINCIPAL_ID")),
            },
        )
    return registry


def _split_values(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("\n", ",").replace(";", ",").split(",") if item.strip()]


def _chat_allowlist() -> dict[str, object]:
    raw_ids = _split_values(_env("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS"))
    raw_hashes = _split_values(_env("EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES"))
    return {
        "configured": bool(raw_ids or raw_hashes),
        "raw_chat_ids_present": bool(raw_ids),
        "chat_hashes_present": bool(raw_hashes),
        "allowed_chat_id_count": len(raw_ids),
        "allowed_chat_hash_count": len(raw_hashes),
        "raw_chat_ids_exposed": False,
        "raw_chat_hashes_exposed": False,
    }


def _source_contains(path: Path, needles: list[str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return all(needle in text for needle in needles)


def _code_checks() -> dict[str, object]:
    endpoint_path = EA_ROOT / "app/api/routes/channels.py"
    normalizer_path = EA_ROOT / "app/services/telegram_business_signal_ingest.py"
    bootstrap_path = ROOT / "scripts/bootstrap_telegram_bot.py"
    verifier_path = ROOT / "scripts/verify_telegram_business_signal_readiness.py"
    return {
        "endpoint_present": _source_contains(endpoint_path, ["/telegram/business/ingest", "normalize_telegram_business_update"]),
        "normalizer_present": normalizer_path.is_file(),
        "normalizer_allowed_updates_present": _source_contains(normalizer_path, ALLOWED_UPDATES),
        "normalizer_read_only_guards_present": _source_contains(
            normalizer_path,
            ["memory_candidate_allowed", "reply_allowed", "raw_payload_exposed", "chat_not_allowlisted"],
        ),
        "bootstrap_business_mode_present": _source_contains(
            bootstrap_path,
            ["--business", "_business_webhook_url", "business_message", "deleted_business_messages"],
        ),
        "verifier_present": verifier_path.is_file(),
    }


def _optional_live_webhook_probe(*, bot_token: str, bot_key: str) -> dict[str, object]:
    if _env("EA_TELEGRAM_BUSINESS_LIVE_WEBHOOK_PROBE").lower() not in {"1", "true", "yes", "on"}:
        return {"status": "skipped", "reason": "live_probe_disabled"}
    if not bot_token:
        return {"status": "blocked", "reason": "bot_token_missing"}
    try:
        request = urllib.request.Request(f"https://api.telegram.org/bot{bot_token}/getWebhookInfo", method="GET")
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"status": "blocked", "reason": type(exc).__name__}
    result = payload.get("result") if isinstance(payload, dict) else {}
    result = result if isinstance(result, dict) else {}
    configured_url = str(result.get("url") or "").strip()
    expected_url = _business_webhook_url(bot_key)
    pending = int(result.get("pending_update_count") or 0)
    return {
        "status": "pass" if configured_url == expected_url and bool(expected_url) else "blocked",
        "expected_url_hash": _sha256(expected_url),
        "configured_url_hash": _sha256(configured_url),
        "url_matches_business_ingest": bool(expected_url and configured_url == expected_url),
        "pending_update_count": pending,
        "raw_webhook_url_exposed": False,
    }


def _sha256(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _setup_status(*, checks: dict[str, bool], allowlist: dict[str, object], code: dict[str, object], live_probe: dict[str, object]) -> dict[str, object]:
    code_missing = [key for key, value in code.items() if not bool(value)]
    return {
        "bot_credentials": {
            "status": "pass" if checks.get("bot_token_present") and checks.get("ingest_secret_present") else "missing",
            "required": ["bot token", "ingest secret"],
            "missing": [
                label
                for key, label in (
                    ("bot_token_present", "bot token"),
                    ("ingest_secret_present", "ingest secret"),
                )
                if not checks.get(key)
            ],
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
        },
        "public_webhook": {
            "status": "pass" if checks.get("public_app_base_url_present") else "missing",
            "required": ["EA_PUBLIC_APP_BASE_URL"],
            "missing": [] if checks.get("public_app_base_url_present") else ["public app base URL"],
            "raw_webhook_url_exposed": False,
        },
        "principal_binding": {
            "status": "pass" if checks.get("default_principal_present") else "missing",
            "required": ["EA_TELEGRAM_DEFAULT_PRINCIPAL_ID or EA_DEFAULT_PRINCIPAL_ID"],
            "missing": [] if checks.get("default_principal_present") else ["default principal binding"],
            "raw_principal_id_exposed": False,
        },
        "chat_allowlist": {
            "status": "pass" if checks.get("chat_allowlist_configured") else "missing",
            "required": ["EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES"],
            "missing": [] if checks.get("chat_allowlist_configured") else ["allowlisted Telegram Business chats"],
            "allowed_chat_id_count": int(allowlist.get("allowed_chat_id_count") or 0),
            "allowed_chat_hash_count": int(allowlist.get("allowed_chat_hash_count") or 0),
            "raw_chat_ids_exposed": False,
            "raw_chat_hashes_exposed": False,
        },
        "code_contract": {
            "status": "pass" if not code_missing else "missing",
            "missing": code_missing,
        },
        "live_webhook_probe": {
            "status": str(live_probe.get("status") or "skipped").strip(),
            "reason": str(live_probe.get("reason") or "").strip(),
            "raw_webhook_url_exposed": False,
        },
    }


def _setup_checklist(missing: list[str]) -> list[dict[str, str]]:
    checklist = {
        "bot_token_present": {
            "label": "Connect an EA Telegram bot token",
            "how": "Set EA_TELEGRAM_BOT_TOKEN or a token in EA_TELEGRAM_BOT_REGISTRY_JSON.",
        },
        "ingest_secret_present": {
            "label": "Configure the Telegram ingest secret",
            "how": "Set EA_TELEGRAM_INGEST_SECRET or a registry secret.",
        },
        "public_app_base_url_present": {
            "label": "Publish the EA webhook base URL",
            "how": "Set EA_PUBLIC_APP_BASE_URL to the public HTTPS EA app URL.",
        },
        "default_principal_present": {
            "label": "Bind Telegram signals to the workspace principal",
            "how": "Set EA_TELEGRAM_DEFAULT_PRINCIPAL_ID or EA_DEFAULT_PRINCIPAL_ID.",
        },
        "chat_allowlist_configured": {
            "label": "Choose Telegram Business chats EA may read",
            "how": "Set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES or EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS.",
        },
        "live_webhook_probe_pass": {
            "label": "Verify Telegram points at the Business ingest webhook",
            "how": "Run scripts/bootstrap_telegram_bot.py --business --set-webhook, then rerun the readiness materializer.",
        },
    }
    result: list[dict[str, str]] = []
    for item in missing:
        key = str(item or "").strip()
        entry = checklist.get(key)
        if entry:
            result.append({"key": key, **entry})
        elif key.startswith("code_"):
            result.append(
                {
                    "key": key,
                    "label": "Fix Telegram Business ingest code contract",
                    "how": f"Restore the missing readiness/code check: {key.removeprefix('code_')}.",
                }
            )
        elif key:
            result.append({"key": key, "label": "Complete Telegram Business setup", "how": f"Resolve setup check: {key}."})
    return result


def _telegram_action_message(*, missing: list[str], setup_checklist: list[dict[str, str]]) -> str:
    if not missing:
        return ""
    first_items = [str(item.get("label") or "").strip() for item in setup_checklist[:3] if str(item.get("label") or "").strip()]
    suffix = f" Missing: {', '.join(first_items)}." if first_items else ""
    return (
        "Action needed: Telegram Business/Secretary ingest is not live yet. "
        "Connect the EA bot, allowlist the selected chats, and run the Business webhook bootstrap."
        f"{suffix}"
    )


def build_receipt(*, bot_key: str = "", include_env_file: Path | None = None) -> dict[str, object]:
    if include_env_file is not None:
        _load_env_file(include_env_file)
    registry = _telegram_bot_registry()
    selected_key = str(bot_key or "default").strip() or "default"
    selected = dict(registry.get(selected_key) or next(iter(registry.values()), {}))
    allowlist = _chat_allowlist()
    code = _code_checks()
    public_base_present = bool(_public_app_base_url())
    secret_present = bool(selected.get("secret_present") or _env("EA_TELEGRAM_INGEST_SECRET"))
    token_present = bool(selected.get("token_present") or _env("EA_TELEGRAM_BOT_TOKEN"))
    principal_present = bool(
        selected.get("default_principal_present")
        or _env("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID")
        or _env("EA_DEFAULT_PRINCIPAL_ID")
    )
    live_probe = _optional_live_webhook_probe(bot_token=_env("EA_TELEGRAM_BOT_TOKEN") if token_present else "", bot_key=selected_key)
    checks = {
        "bot_token_present": token_present,
        "ingest_secret_present": secret_present,
        "public_app_base_url_present": public_base_present,
        "default_principal_present": principal_present,
        "chat_allowlist_configured": bool(allowlist.get("configured")),
        **{f"code_{key}": bool(value) for key, value in code.items()},
    }
    missing = [key for key, passed in checks.items() if not passed]
    live_status = str(live_probe.get("status") or "skipped").strip()
    if live_status == "blocked":
        missing.append("live_webhook_probe_pass")
    status = "pass" if not missing else "blocked_setup_required"
    setup_status = _setup_status(checks=checks, allowlist=allowlist, code=code, live_probe=live_probe)
    setup_checklist = _setup_checklist(missing)
    return {
        "contract_name": CONTRACT_NAME,
        "generated_at": _now_iso(),
        "generated_by": "scripts/materialize_telegram_business_signal_readiness.py",
        **_source_state(),
        "status": status,
        "business_mode": True,
        "webhook_path": _business_webhook_path(selected_key),
        "allowed_updates": list(ALLOWED_UPDATES),
        "bot_registry": {
            "configured_bot_count": len(registry),
            "selected_bot_key": selected_key,
            "selected_bot_present": bool(selected),
            "token_present": token_present,
            "ingest_secret_present": secret_present,
            "handle_present": bool(selected.get("handle_present") or _env("EA_TELEGRAM_BOT_HANDLE")),
            "default_principal_present": principal_present,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_principal_id_exposed": False,
        },
        "chat_allowlist": allowlist,
        "code": code,
        "live_webhook_probe": live_probe,
        "setup_status": setup_status,
        "privacy": {
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_webhook_url_exposed": False,
            "raw_payload_exposed": False,
        },
        "missing_setup": missing,
        "operator_action": {
            "user_action_required": bool(missing),
            "instruction": (
                "Connect the EA bot as Telegram Business/Secretary bot, allow only selected chats, "
                "configure the Business webhook, and set EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_IDS or "
                "EA_TELEGRAM_BUSINESS_ALLOWED_CHAT_HASHES."
            ),
            "next_action": "connect_telegram_business_secretary_bot_and_allowlist_chats",
            "next_action_href": "/integrations/telegram",
            "next_action_label": "Open Telegram setup",
            "next_action_method": "get",
            "missing_setup": missing,
            "setup_checklist": setup_checklist,
            "telegram_message": _telegram_action_message(missing=missing, setup_checklist=setup_checklist),
            "delivery_policy": "action_required_only" if missing else "queue_only",
            "telegram_push_allowed": bool(missing),
            "interruption_budget": "action_required" if missing else "none",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_private_context_exposed": False,
            "raw_chat_ids_exposed": False,
            "raw_token_exposed": False,
            "raw_secret_exposed": False,
        },
        "telegram_notification": {
            "should_send": bool(missing),
            "reason": "user_action_required" if missing else "no_operator_action_required",
            "delivery_policy": "action_required_only",
            "non_action_progress_push_allowed": False,
            "raw_private_context_exposed": False,
        },
        "setup_commands": [
            "python3 scripts/bootstrap_telegram_bot.py --business --show",
            "python3 scripts/bootstrap_telegram_bot.py --business --set-webhook",
            "python3 scripts/materialize_telegram_business_signal_readiness.py",
            "python3 scripts/verify_telegram_business_signal_readiness.py",
        ],
        "claim_boundary": "does_not_prove_telegram_business_signal_ingest_until_secretary_bot_is_connected_with_an_allowlisted_chat_and_business_webhook",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize Telegram Business/Secretary signal ingest readiness.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bot-key", default="", help="Optional bot registry key to inspect.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--no-env-file", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    receipt = build_receipt(bot_key=args.bot_key, include_env_file=None if args.no_env_file else args.env_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True) if args.pretty else output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
