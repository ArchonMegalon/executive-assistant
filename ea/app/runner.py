from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import signal
import time

import uvicorn

from app.container import build_container
from app.logging_utils import configure_logging
from app.settings import get_settings

_IDLE_BACKOFF_START_SECONDS = 1.0
_IDLE_BACKOFF_MAX_SECONDS = 15.0
_ERROR_BACKOFF_SECONDS = 2.0
_SCHEDULER_SCAN_INTERVAL_SECONDS = 900.0
_SCHEDULER_ONEMIN_REFRESH_INTERVAL_SECONDS = 86400.0


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except Exception:
        value = default
    return max(0.0, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _scheduler_onemin_refresh_interval_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_ONEMIN_REFRESH_INTERVAL_SECONDS",
        _SCHEDULER_ONEMIN_REFRESH_INTERVAL_SECONDS,
    )


def _scheduler_onemin_global_provider_api_sweep_enabled() -> bool:
    return _env_bool("EA_SCHEDULER_ONEMIN_GLOBAL_PROVIDER_API_SWEEP", True)


def _run_scheduler_onemin_billing_refresh(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from app.api.routes import providers as providers_route

    refresh_allowed, throttle_seconds_remaining, throttle_reason = container.onemin_manager.begin_billing_refresh()
    if not refresh_allowed:
        return {
            "ran": False,
            "throttled": True,
            "throttle_seconds_remaining": max(float(throttle_seconds_remaining), 0.0),
            "throttle_reason": str(throttle_reason or ""),
            "browseract_attempted": 0,
            "browseract_refreshed": 0,
            "member_reconciled": 0,
            "api_attempted": 0,
            "api_rate_limited": False,
            "errors": 0,
        }

    browseract_attempted = 0
    browseract_refreshed = 0
    member_reconciled = 0
    api_attempted = 0
    api_rate_limited = False
    error_count = 0
    batch_size = max(1, int(providers_route._onemin_browseract_max_accounts_per_refresh()))
    batch_backoff_seconds = max(0.0, float(providers_route._onemin_direct_api_batch_backoff_seconds()))
    processed_in_batch = 0

    try:
        bindings = [
            binding
            for binding in container.tool_runtime.list_connector_bindings_for_connector("browseract", limit=1000)
            if str(binding.status or "").strip().lower() == "enabled"
        ]
        for binding in bindings:
            binding_metadata = dict(binding.auth_metadata_json or {})
            billing_run_url = providers_route._binding_run_url(
                binding_metadata,
                "onemin_billing_usage_run_url",
                "browseract_onemin_billing_usage_run_url",
                "run_url",
            )
            billing_workflow_id = providers_route._binding_workflow_id(
                binding_metadata,
                "onemin_billing_usage_workflow_id",
                "browseract_onemin_billing_usage_workflow_id",
                "workflow_id",
            )
            members_run_url = providers_route._binding_run_url(
                binding_metadata,
                "onemin_members_run_url",
                "browseract_onemin_members_run_url",
            )
            members_workflow_id = providers_route._binding_workflow_id(
                binding_metadata,
                "onemin_members_workflow_id",
                "browseract_onemin_members_workflow_id",
            )
            account_labels = providers_route._resolve_onemin_account_labels(binding)
            for account_label in account_labels:
                if processed_in_batch >= batch_size:
                    if batch_backoff_seconds > 0:
                        time.sleep(batch_backoff_seconds)
                    processed_in_batch = 0
                if not billing_run_url and not billing_workflow_id and not providers_route._browseract_onemin_login_ready(
                    account_label=account_label,
                    binding_metadata=binding_metadata,
                ):
                    continue
                browseract_attempted += 1
                processed_in_batch += 1
                try:
                    providers_route._invoke_browseract_tool(
                        container=container,
                        principal_id=str(binding.principal_id or "").strip(),
                        tool_name="browseract.onemin_billing_usage",
                        action_kind="billing.inspect",
                        payload_json={
                            "binding_id": binding.binding_id,
                            "account_label": account_label,
                            "capture_raw_text": False,
                            **({"run_url": billing_run_url} if billing_run_url else {}),
                            **({"workflow_id": billing_workflow_id} if billing_workflow_id else {}),
                            "timeout_seconds": 180,
                        },
                    )
                    browseract_refreshed += 1
                except providers_route.ToolExecutionError as exc:
                    error_count += 1
                    log.warning(
                        "scheduler onemin billing browseract refresh failed principal=%s binding=%s account=%s error=%s",
                        binding.principal_id,
                        binding.binding_id,
                        account_label,
                        exc,
                    )
                    continue
                if not members_run_url and not members_workflow_id and not providers_route._browseract_onemin_login_ready(
                    account_label=account_label,
                    binding_metadata=binding_metadata,
                ):
                    continue
                try:
                    providers_route._invoke_browseract_tool(
                        container=container,
                        principal_id=str(binding.principal_id or "").strip(),
                        tool_name="browseract.onemin_member_reconciliation",
                        action_kind="billing.reconcile_members",
                        payload_json={
                            "binding_id": binding.binding_id,
                            "account_label": account_label,
                            "capture_raw_text": False,
                            **({"run_url": members_run_url} if members_run_url else {}),
                            **({"workflow_id": members_workflow_id} if members_workflow_id else {}),
                            "timeout_seconds": 180,
                        },
                    )
                    member_reconciled += 1
                except providers_route.ToolExecutionError as exc:
                    error_count += 1
                    log.warning(
                        "scheduler onemin member reconciliation failed principal=%s binding=%s account=%s error=%s",
                        binding.principal_id,
                        binding.binding_id,
                        account_label,
                        exc,
                    )

        if _scheduler_onemin_global_provider_api_sweep_enabled():
            (
                _api_billing_results,
                _api_member_results,
                api_errors,
                api_attempted,
                _api_skipped,
                api_rate_limited,
            ) = providers_route._refresh_onemin_via_provider_api(
                include_members=True,
                timeout_seconds=180,
                all_accounts=True,
                continue_on_rate_limit=True,
            )
            error_count += len(api_errors)

        return {
            "ran": True,
            "throttled": False,
            "throttle_seconds_remaining": 0.0,
            "throttle_reason": "",
            "browseract_attempted": browseract_attempted,
            "browseract_refreshed": browseract_refreshed,
            "member_reconciled": member_reconciled,
            "api_attempted": api_attempted,
            "api_rate_limited": api_rate_limited,
            "errors": error_count,
        }
    finally:
        container.onemin_manager.finish_billing_refresh()


def _run_api() -> None:
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level=s.log_level.lower())


def _run_execution_worker(role: str) -> None:
    stop = {"flag": False}

    def _handle_stop(signum, frame):  # type: ignore[no-untyped-def]
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log = logging.getLogger("ea.runner")
    container = build_container()
    idle_backoff_seconds = _IDLE_BACKOFF_START_SECONDS
    last_horizon_scan_at = 0.0
    last_onemin_refresh_at = 0.0
    log.info("role=%s started worker loop", role)
    while not stop["flag"]:
        if role == "scheduler":
            now = time.time()
            if now - last_horizon_scan_at >= _SCHEDULER_SCAN_INTERVAL_SECONDS:
                observed_at = datetime.now(timezone.utc)
                try:
                    candidates = container.proactive_horizon.scan(now=observed_at)
                    refreshed_principals = {
                        str(row.principal_id or "").strip()
                        for row in candidates
                        if str(row.principal_id or "").strip()
                    }
                    for principal_id in sorted(refreshed_principals):
                        container.cognitive_load.refresh_for_principal(
                            principal_id,
                            now=observed_at,
                        )
                    launched = container.proactive_horizon.run_once(now=observed_at)
                    if launched:
                        log.info("role=%s proactive horizon launched=%s", role, len(launched))
                    if refreshed_principals:
                        log.debug("role=%s cognitive-load refreshed principals=%s", role, len(refreshed_principals))
                except Exception:
                    log.exception("role=%s proactive horizon scan failed", role)
                last_horizon_scan_at = now
            if now - last_onemin_refresh_at >= _scheduler_onemin_refresh_interval_seconds():
                try:
                    refresh_summary = _run_scheduler_onemin_billing_refresh(container, log)
                    if bool(refresh_summary.get("ran")) and not bool(refresh_summary.get("throttled")):
                        last_onemin_refresh_at = now
                        log.info(
                            "role=%s scheduler onemin refresh browseract=%s/%s members=%s api_attempted=%s api_rate_limited=%s errors=%s",
                            role,
                            refresh_summary.get("browseract_refreshed"),
                            refresh_summary.get("browseract_attempted"),
                            refresh_summary.get("member_reconciled"),
                            refresh_summary.get("api_attempted"),
                            refresh_summary.get("api_rate_limited"),
                            refresh_summary.get("errors"),
                        )
                    elif bool(refresh_summary.get("throttled")):
                        throttle_seconds_remaining = max(
                            float(refresh_summary.get("throttle_seconds_remaining") or 0.0),
                            1.0,
                        )
                        last_onemin_refresh_at = now - _scheduler_onemin_refresh_interval_seconds() + throttle_seconds_remaining
                        log.info(
                            "role=%s scheduler onemin refresh throttled reason=%s retry_in=%.1fs",
                            role,
                            refresh_summary.get("throttle_reason"),
                            throttle_seconds_remaining,
                        )
                except Exception:
                    log.exception("role=%s scheduler onemin refresh failed", role)
        try:
            artifact = container.orchestrator.run_next_queue_item(lease_owner=role)
        except Exception:
            log.exception("role=%s queue execution failed; retrying in %.1fs", role, _ERROR_BACKOFF_SECONDS)
            time.sleep(_ERROR_BACKOFF_SECONDS)
            continue
        if artifact is None:
            log.debug("role=%s idle; sleeping %.1fs before next lease attempt", role, idle_backoff_seconds)
            time.sleep(idle_backoff_seconds)
            idle_backoff_seconds = min(idle_backoff_seconds * 2.0, _IDLE_BACKOFF_MAX_SECONDS)
            continue
        idle_backoff_seconds = _IDLE_BACKOFF_START_SECONDS
        log.info(
            "role=%s completed queued item session=%s artifact=%s; idle backoff reset",
            role,
            artifact.execution_session_id,
            artifact.artifact_id,
        )
    log.info("role=%s stopped worker loop", role)


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    if s.role == "api":
        _run_api()
        return
    _run_execution_worker(s.role)


if __name__ == "__main__":
    main()
