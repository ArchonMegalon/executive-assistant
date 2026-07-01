#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

CHECK_SCRIPT = ROOT / "scripts" / "check_whatsapp_web_action_processor_readiness.py"
DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "whatsapp_web_action_processor_readiness.generated.json"
CONTRACT_NAME = "ea.whatsapp_web_action_processor_readiness.v1"
READINESS_PATH_ENV = "EA_WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_PATH"
PROVIDER_LEDGER_DIR_ENV = "EA_RESPONSES_PROVIDER_LEDGER_DIR"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def _docker_container_checks_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _runtime_output_path() -> Path:
    ledger_dir = str(os.getenv(PROVIDER_LEDGER_DIR_ENV) or "/data/provider-ledger").strip() or "/data/provider-ledger"
    return Path(ledger_dir) / "provider-health-cache" / DEFAULT_OUTPUT.name


def _path_parent_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / f".{path.name}.write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def resolve_whatsapp_web_action_processor_readiness_output_path(output_path: Path) -> Path:
    requested = Path(output_path)
    if requested != DEFAULT_OUTPUT:
        return requested
    configured = str(os.getenv(READINESS_PATH_ENV) or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(DEFAULT_OUTPUT)
    runtime_output = _runtime_output_path()
    if runtime_output not in candidates:
        candidates.append(runtime_output)
    for candidate in candidates:
        if _path_parent_writable(candidate):
            return candidate
    return candidates[0]


def _load_check_module():
    spec = importlib.util.spec_from_file_location("check_whatsapp_web_action_processor_readiness_materializer", CHECK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("whatsapp_web_action_processor_readiness_check_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _default_args(module, *, output: Path) -> argparse.Namespace:
    docker_available = _docker_container_checks_available()
    return argparse.Namespace(
        output=output,
        env_file=module._env("EA_WHATSAPP_WEB_ACTION_ENV_FILE", str(module.DEFAULT_ENV_FILE)),
        compose_file=module._env("EA_WHATSAPP_WEB_ACTION_COMPOSE_FILE", str(module.DEFAULT_COMPOSE_FILE)),
        session_api_base_url=module._env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", module.DEFAULT_SESSION_API_BASE_URL),
        session_ref=module._env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", module.DEFAULT_SESSION_REF),
        session_api_token=module._env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"),
        auth_header_name=module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"),
        auth_header_prefix=module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "),
        timeout_seconds=float(module._env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "15") or "15"),
        state_file=module._env("EA_WHATSAPP_WEB_ACTION_STATE_FILE", module.DEFAULT_ACTION_STATE_FILE),
        state_stale_seconds=module._int_value(module._env("EA_WHATSAPP_WEB_ACTION_STATE_STALE_SECONDS", "600"), 600),
        probe_sidecar=True,
        check_containers=docker_available,
        api_container=module._env("EA_API_CONTAINER", "ea-api"),
        processor_container=module._env("EA_WHATSAPP_WEB_ACTION_PROCESSOR_CONTAINER", "ea-whatsapp-web-action-processor"),
    )


def _next_action(report: dict[str, Any]) -> str:
    if bool(report.get("ready")):
        return "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow"

    reasons = [str(item).strip() for item in list(report.get("reasons") or []) if str(item).strip()]
    if "callback_secret_missing" in reasons:
        return "seed_whatsapp_callback_secret_and_rerun_readiness"
    if any(code in reasons for code in ("state_file_container_probe_unavailable", "processor_container_disabled_or_not_running")):
        return "start_or_repair_whatsapp_action_processor_container"
    if any(
        code in reasons
        for code in (
            "state_file_parent_not_writable",
            "state_file_missing",
            "state_file_unreadable",
            "state_file_not_object",
            "state_updated_at_invalid",
            "state_file_stale",
            "state_session_ref_mismatch",
        )
    ):
        return "repair_whatsapp_action_processor_state_runtime"
    if any(code in reasons for code in ("processor_service_declared", "processor_script_mounted", "processor_state_volume_declared")):
        return "repair_whatsapp_action_processor_compose_contract"
    if any(code in reasons for code in ("api_container_callback_secret_missing", "processor_container_callback_secret_missing")):
        return "sync_callback_secret_into_runtime_containers"
    if "sidecar_not_ready" in reasons or "sidecar_message_text_storage_disabled" in reasons:
        return "restore_whatsapp_web_session_sidecar_readiness"
    return "fix_whatsapp_web_action_processor_readiness"


def build_whatsapp_web_action_processor_readiness(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
    args: argparse.Namespace | None = None,
    request_json: Callable[..., dict[str, Any]] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    module = _load_check_module()
    effective_args = args or _default_args(module, output=output_path)
    report = module.build_report(
        effective_args,
        request_json=request_json or module._request_json,
        run=run,
    )
    ready = bool(report.get("ready"))
    resolved_output_path = resolve_whatsapp_web_action_processor_readiness_output_path(output_path)
    receipt = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_whatsapp_web_action_processor_readiness.py",
        "source_git_head": _git_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": _source_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": resolved_output_path.as_posix(),
        "canonical_output_path": DEFAULT_OUTPUT.as_posix(),
        "status": "ready" if ready else "blocked",
        "claim": (
            "This receipt proves only that the WhatsApp Web action processor runtime is ready to receive and process "
            "live audiobook actions, including degraded voice-selection text commands when button transport falls back. "
            "It does not prove a live EPUB arrived or that a share link was delivered."
        ),
        "next_action": _next_action(report),
        "runtime_ready_claim_allowed": ready,
        "live_delivery_claim_allowed": False,
        "goal_completion_claim_allowed": False,
        "rules": [
            "A ready runtime receipt does not prove a live audiobook delivery happened.",
            "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice selection when the upstream transport preserves those messages.",
            "A blocked runtime receipt means the WhatsApp action processor cannot be trusted for fresh live EPUB evidence yet.",
            "Live delivery still requires a fresh WhatsApp job receipt plus public-share delivery and playback evidence.",
        ],
        **report,
    }
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args() -> argparse.Namespace:
    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/materialize_whatsapp_web_action_processor_readiness.py [options]\n\n"
            "Materialize the WhatsApp Web action processor readiness receipt."
        )
        raise SystemExit(0)
    module = _load_check_module()
    parser = argparse.ArgumentParser(description="Materialize the WhatsApp Web action processor readiness receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--env-file", default=module._env("EA_WHATSAPP_WEB_ACTION_ENV_FILE", str(module.DEFAULT_ENV_FILE)))
    parser.add_argument("--compose-file", default=module._env("EA_WHATSAPP_WEB_ACTION_COMPOSE_FILE", str(module.DEFAULT_COMPOSE_FILE)))
    parser.add_argument(
        "--session-api-base-url",
        default=module._env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", module.DEFAULT_SESSION_API_BASE_URL),
    )
    parser.add_argument("--session-ref", default=module._env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", module.DEFAULT_SESSION_REF))
    parser.add_argument("--session-api-token", default=module._env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"))
    parser.add_argument(
        "--auth-header-prefix",
        default=module._env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(module._env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "15") or "15"),
    )
    parser.add_argument("--state-file", default=module._env("EA_WHATSAPP_WEB_ACTION_STATE_FILE", module.DEFAULT_ACTION_STATE_FILE))
    parser.add_argument(
        "--state-stale-seconds",
        type=int,
        default=module._int_value(module._env("EA_WHATSAPP_WEB_ACTION_STATE_STALE_SECONDS", "600"), 600),
    )
    parser.add_argument("--probe-sidecar", dest="probe_sidecar", action="store_true", default=True)
    parser.add_argument("--no-probe-sidecar", dest="probe_sidecar", action="store_false")
    parser.add_argument(
        "--check-containers",
        dest="check_containers",
        action="store_true",
        default=_docker_container_checks_available(),
    )
    parser.add_argument("--no-check-containers", dest="check_containers", action="store_false")
    parser.add_argument("--api-container", default=module._env("EA_API_CONTAINER", "ea-api"))
    parser.add_argument(
        "--processor-container",
        default=module._env("EA_WHATSAPP_WEB_ACTION_PROCESSOR_CONTAINER", "ea-whatsapp-web-action-processor"),
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_whatsapp_web_action_processor_readiness(
        output_path=args.output,
        generated_at=args.generated_at or None,
        args=args,
    )
    print(json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True))
    if args.require_ready and not bool(receipt.get("ready")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
