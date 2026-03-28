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
_SCHEDULER_GOOGLE_SIGNAL_SYNC_INTERVAL_SECONDS = 900.0


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


def _scheduler_google_signal_sync_interval_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_GOOGLE_SIGNAL_SYNC_INTERVAL_SECONDS",
        _SCHEDULER_GOOGLE_SIGNAL_SYNC_INTERVAL_SECONDS,
    )


def _scheduler_google_signal_sync_enabled() -> bool:
    return _env_bool("EA_SCHEDULER_GOOGLE_SIGNAL_SYNC_ENABLED", True)


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
    browseract_max_accounts = max(1, int(providers_route._onemin_browseract_max_accounts_per_refresh()))
    browseract_parallelism = max(1, int(providers_route._onemin_browseract_parallelism()))
    browseract_timeout_seconds = max(30, int(providers_route._onemin_browseract_timeout_seconds()))

    try:
        bindings = [
            binding
            for binding in container.tool_runtime.list_connector_bindings_for_connector("browseract", limit=1000)
            if str(binding.status or "").strip().lower() == "enabled"
        ]
        binding_jobs: list[dict[str, object]] = []
        principal_binding_rows: dict[str, list[object]] = {}
        principal_bound_account_label_order: dict[str, list[str]] = {}
        principal_seen_account_labels: dict[str, set[str]] = {}
        for binding in bindings:
            principal_id = str(binding.principal_id or "").strip()
            if not principal_id:
                continue
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
            principal_binding_rows.setdefault(principal_id, []).append(binding)
            principal_bound_account_label_order.setdefault(principal_id, [])
            principal_seen_account_labels.setdefault(principal_id, set())
            for account_label in account_labels:
                if account_label and account_label not in principal_seen_account_labels[principal_id]:
                    principal_seen_account_labels[principal_id].add(account_label)
                    principal_bound_account_label_order[principal_id].append(account_label)
            binding_jobs.append(
                {
                    "binding": binding,
                    "principal_id": principal_id,
                    "binding_metadata": binding_metadata,
                    "billing_run_url": billing_run_url,
                    "billing_workflow_id": billing_workflow_id,
                    "members_run_url": members_run_url,
                    "members_workflow_id": members_workflow_id,
                    "account_labels": tuple(account_labels),
                }
            )

        select_refresh_account_labels = getattr(container.onemin_manager, "select_billing_refresh_account_labels", None)
        principal_selected_browseract_labels: dict[str, set[str]] = {}
        for principal_id, account_labels in principal_bound_account_label_order.items():
            stale_labels, actual_labels = providers_route._partition_onemin_browseract_account_labels(
                container=container,
                principal_id=principal_id,
                binding_rows=principal_binding_rows.get(principal_id, []),
                account_labels=account_labels,
            )
            selected_browseract_labels: set[str] = set()
            if stale_labels:
                if callable(select_refresh_account_labels):
                    selected_browseract_labels.update(
                        select_refresh_account_labels(
                            stale_labels,
                            limit=min(browseract_max_accounts, len(stale_labels)),
                        )
                    )
                else:
                    selected_browseract_labels.update(list(stale_labels)[: min(browseract_max_accounts, len(stale_labels))])
            remaining_browseract_slots = max(browseract_max_accounts - len(selected_browseract_labels), 0)
            if remaining_browseract_slots > 0 and actual_labels:
                if callable(select_refresh_account_labels):
                    selected_browseract_labels.update(
                        select_refresh_account_labels(
                            actual_labels,
                            limit=min(remaining_browseract_slots, len(actual_labels)),
                        )
                    )
                else:
                    selected_browseract_labels.update(list(actual_labels)[: min(remaining_browseract_slots, len(actual_labels))])
            principal_selected_browseract_labels[principal_id] = selected_browseract_labels

        browseract_billing_jobs: list[dict[str, object]] = []
        for job in binding_jobs:
            binding = job["binding"]
            principal_id = str(job["principal_id"] or "")
            selected_browseract_labels = principal_selected_browseract_labels.get(principal_id, set())
            binding_metadata = dict(job["binding_metadata"] or {})
            billing_run_url = str(job["billing_run_url"] or "")
            billing_workflow_id = str(job["billing_workflow_id"] or "")
            members_run_url = str(job["members_run_url"] or "")
            members_workflow_id = str(job["members_workflow_id"] or "")
            account_labels = tuple(str(value or "").strip() for value in (job["account_labels"] or ()) if str(value or "").strip())
            for account_label in account_labels:
                if account_label not in selected_browseract_labels:
                    continue
                if not billing_run_url and not billing_workflow_id and not providers_route._browseract_onemin_login_ready(
                    account_label=account_label,
                    binding_metadata=binding_metadata,
                ):
                    continue
                browseract_billing_jobs.append(
                    {
                        "principal_id": str(binding.principal_id or "").strip(),
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                        "account_label": account_label,
                        "billing_run_url": billing_run_url,
                        "billing_workflow_id": billing_workflow_id,
                        "members_run_url": members_run_url,
                        "members_workflow_id": members_workflow_id,
                        "member_login_ready": providers_route._browseract_onemin_login_ready(
                            account_label=account_label,
                            binding_metadata=binding_metadata,
                        ),
                    }
                )

        browseract_attempted = len(browseract_billing_jobs)
        billing_results, billing_errors = providers_route._run_onemin_browseract_jobs(
            jobs=browseract_billing_jobs,
            max_workers=browseract_parallelism,
            tool_name="browseract.onemin_billing_usage",
            invoke_job=lambda job: providers_route._invoke_browseract_tool(
                container=container,
                principal_id=str(job.get("principal_id") or ""),
                tool_name="browseract.onemin_billing_usage",
                action_kind="billing.inspect",
                payload_json={
                    "binding_id": str(job.get("binding_id") or ""),
                    "account_label": str(job.get("account_label") or ""),
                    "capture_raw_text": False,
                    **({"run_url": str(job.get("billing_run_url") or "")} if str(job.get("billing_run_url") or "").strip() else {}),
                    **({"workflow_id": str(job.get("billing_workflow_id") or "")} if str(job.get("billing_workflow_id") or "").strip() else {}),
                    "timeout_seconds": browseract_timeout_seconds,
                },
            ),
        )
        browseract_refreshed = len(billing_results)
        error_count += len(billing_errors)
        for row in billing_errors:
            log.warning(
                "scheduler onemin billing browseract refresh failed principal=%s binding=%s account=%s error=%s",
                next((str(job.get("principal_id") or "") for job in browseract_billing_jobs if str(job.get("account_label") or "") == str(row.get("account_label") or "")), ""),
                row.get("binding_id"),
                row.get("account_label"),
                row.get("error"),
            )

        successful_labels = {
            str(row.get("account_label") or "").strip()
            for row in billing_results
            if str(row.get("account_label") or "").strip()
        }
        browseract_member_jobs = [
            dict(job)
            for job in browseract_billing_jobs
            if str(job.get("account_label") or "").strip() in successful_labels
            and (
                str(job.get("members_run_url") or "").strip()
                or str(job.get("members_workflow_id") or "").strip()
                or bool(job.get("member_login_ready"))
            )
        ]
        member_results, member_errors = providers_route._run_onemin_browseract_jobs(
            jobs=browseract_member_jobs,
            max_workers=browseract_parallelism,
            tool_name="browseract.onemin_member_reconciliation",
            invoke_job=lambda job: providers_route._invoke_browseract_tool(
                container=container,
                principal_id=str(job.get("principal_id") or ""),
                tool_name="browseract.onemin_member_reconciliation",
                action_kind="billing.reconcile_members",
                payload_json={
                    "binding_id": str(job.get("binding_id") or ""),
                    "account_label": str(job.get("account_label") or ""),
                    "capture_raw_text": False,
                    **({"run_url": str(job.get("members_run_url") or "")} if str(job.get("members_run_url") or "").strip() else {}),
                    **({"workflow_id": str(job.get("members_workflow_id") or "")} if str(job.get("members_workflow_id") or "").strip() else {}),
                    "timeout_seconds": browseract_timeout_seconds,
                },
            ),
        )
        member_reconciled = len(member_results)
        error_count += len(member_errors)
        for row in member_errors:
            log.warning(
                "scheduler onemin member reconciliation failed principal=%s binding=%s account=%s error=%s",
                next((str(job.get("principal_id") or "") for job in browseract_member_jobs if str(job.get("account_label") or "") == str(row.get("account_label") or "")), ""),
                row.get("binding_id"),
                row.get("account_label"),
                row.get("error"),
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


def _run_scheduler_google_signal_sync(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from app.product.service import build_product_service
    from app.services.google_oauth import GOOGLE_CONNECTOR_NAME

    service = build_product_service(container)
    bindings = [
        binding
        for binding in container.tool_runtime.list_connector_bindings_for_connector(GOOGLE_CONNECTOR_NAME, limit=1000)
        if str(binding.status or "").strip().lower() == "enabled" and str(binding.principal_id or "").strip()
    ]
    principal_ids = tuple(sorted({str(binding.principal_id or "").strip() for binding in bindings}))
    attempted = 0
    synced = 0
    error_count = 0
    for principal_id in principal_ids:
        attempted += 1
        try:
            summary = service.sync_google_workspace_signals(
                principal_id=principal_id,
                actor="scheduler",
                email_limit=5,
                calendar_limit=5,
            )
            if int(summary.get("total") or 0) >= 0:
                synced += 1
        except RuntimeError as exc:
            error_count += 1
            log.info(
                "scheduler google signal sync skipped principal=%s reason=%s",
                principal_id,
                str(exc or "unknown_error"),
            )
        except Exception:
            error_count += 1
            log.exception("scheduler google signal sync failed principal=%s", principal_id)
    return {
        "ran": True,
        "attempted": attempted,
        "synced": synced,
        "errors": error_count,
    }


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
    last_google_signal_sync_at = 0.0
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
            if _scheduler_google_signal_sync_enabled() and (
                now - last_google_signal_sync_at >= _scheduler_google_signal_sync_interval_seconds()
            ):
                try:
                    sync_summary = _run_scheduler_google_signal_sync(container, log)
                    last_google_signal_sync_at = now
                    log.info(
                        "role=%s scheduler google signal sync attempted=%s synced=%s errors=%s",
                        role,
                        sync_summary.get("attempted"),
                        sync_summary.get("synced"),
                        sync_summary.get("errors"),
                    )
                except Exception:
                    log.exception("role=%s scheduler google signal sync failed", role)
                    last_google_signal_sync_at = now
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
