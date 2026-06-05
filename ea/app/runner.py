from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import signal
import time
import urllib.error
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import uvicorn

from app.api.routes.channels import (
    _resolve_telegram_bot_config,
    _telegram_async_assistant_reply_worker,
)
from app.container import build_container
from app.logging_utils import configure_logging
from app.settings import get_settings

_IDLE_BACKOFF_START_SECONDS = 1.0
_IDLE_BACKOFF_MAX_SECONDS = 15.0
_ERROR_BACKOFF_SECONDS = 2.0
_SCHEDULER_SCAN_INTERVAL_SECONDS = 900.0
_SCHEDULER_ONEMIN_REFRESH_INTERVAL_SECONDS = 86400.0
_SCHEDULER_GOOGLE_SIGNAL_SYNC_INTERVAL_SECONDS = 900.0
_SCHEDULER_POCKET_SIGNAL_SYNC_INTERVAL_SECONDS = 900.0
_SCHEDULER_MORNING_MEMO_INTERVAL_SECONDS = 300.0
_SCHEDULER_TELEGRAM_ASYNC_RECOVERY_INTERVAL_SECONDS = 5.0
_SCHEDULER_TELEGRAM_ASYNC_RECOVERY_MIN_AGE_SECONDS = 0.0
_SCHEDULER_MORNING_MEMO_DELIVERY_WINDOW_MINUTES = 120
_SCHEDULER_MORNING_MEMO_RETRY_AFTER_MINUTES = 60
_SCHEDULER_GOOGLE_SIGNAL_SYNC_FORBIDDEN_COOLDOWNS: dict[str, float] = {}


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except Exception:
        value = default
    return max(0.0, value)


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except Exception:
        value = default
    return value


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


def _scheduler_property_alert_account_emails() -> tuple[str, ...]:
    raw = str(
        os.environ.get("EA_PROPERTY_ALERT_ACCOUNT_EMAILS")
        or os.environ.get("EA_GOOGLE_PROPERTY_ALERT_ACCOUNT_EMAILS")
        or ""
    ).strip()
    values = [part.strip().lower() for part in re.split(r"[\s,;]+", raw) if part.strip()]
    if values:
        return tuple(sorted(set(values)))
    source_raw = str(os.environ.get("EA_PROPERTY_SCOUT_URLS_JSON") or "").strip()
    if not source_raw:
        return ()
    try:
        parsed = json.loads(source_raw)
    except Exception:
        return ()
    if not isinstance(parsed, list):
        return ()
    for item in parsed:
        if isinstance(item, dict):
            account_email = str(item.get("account_email") or "").strip().lower()
            if account_email:
                values.append(account_email)
    return tuple(sorted(set(values)))


def _scheduler_google_signal_sync_enabled() -> bool:
    return _env_bool("EA_SCHEDULER_GOOGLE_SIGNAL_SYNC_ENABLED", True)


def _scheduler_google_signal_sync_forbidden_cooldown_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_GOOGLE_SIGNAL_SYNC_FORBIDDEN_COOLDOWN_SECONDS",
        21600.0,
    )


def _scheduler_pocket_signal_sync_interval_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_POCKET_SIGNAL_SYNC_INTERVAL_SECONDS",
        _SCHEDULER_POCKET_SIGNAL_SYNC_INTERVAL_SECONDS,
    )


def _scheduler_pocket_signal_sync_enabled() -> bool:
    return _env_bool("EA_SCHEDULER_POCKET_SIGNAL_SYNC_ENABLED", bool(str(os.environ.get("POCKET_API_KEY") or "").strip()))


def _scheduler_pocket_signal_sync_limit() -> int:
    return max(1, min(_env_int("EA_SCHEDULER_POCKET_SIGNAL_SYNC_LIMIT", 5), 100))


def _scheduler_morning_memo_interval_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_MORNING_MEMO_INTERVAL_SECONDS",
        _SCHEDULER_MORNING_MEMO_INTERVAL_SECONDS,
    )


def _scheduler_morning_memo_enabled() -> bool:
    return _env_bool("EA_SCHEDULER_MORNING_MEMO_ENABLED", True)


def _scheduler_telegram_async_recovery_interval_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_TELEGRAM_ASYNC_RECOVERY_INTERVAL_SECONDS",
        _SCHEDULER_TELEGRAM_ASYNC_RECOVERY_INTERVAL_SECONDS,
    )


def _scheduler_telegram_async_recovery_min_age_seconds() -> float:
    return _env_float(
        "EA_SCHEDULER_TELEGRAM_ASYNC_RECOVERY_MIN_AGE_SECONDS",
        _SCHEDULER_TELEGRAM_ASYNC_RECOVERY_MIN_AGE_SECONDS,
    )


def _scheduler_telegram_async_recovery_enabled() -> bool:
    return _env_bool("EA_SCHEDULER_TELEGRAM_ASYNC_RECOVERY_ENABLED", True)


def _scheduler_public_base_url() -> str:
    return str(os.environ.get("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")


def _normalize_scheduler_time(value: str, *, default: str) -> tuple[int, int]:
    normalized = str(value or "").strip() or default
    hour, sep, minute = normalized.partition(":")
    try:
        hour_int = int(hour)
        minute_int = int(minute) if sep else 0
    except Exception:
        return _normalize_scheduler_time(default, default="08:00") if normalized != default else (8, 0)
    if 0 <= hour_int <= 23 and 0 <= minute_int <= 59:
        return hour_int, minute_int
    if normalized != default:
        return _normalize_scheduler_time(default, default="08:00")
    return 8, 0


def _schedule_timezone(name: str):
    normalized = str(name or "").strip()
    if not normalized:
        return timezone.utc
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _is_local_time_within_quiet_hours(
    local_now: datetime,
    *,
    quiet_start: tuple[int, int],
    quiet_end: tuple[int, int],
) -> bool:
    start_minutes = quiet_start[0] * 60 + quiet_start[1]
    end_minutes = quiet_end[0] * 60 + quiet_end[1]
    now_minutes = local_now.hour * 60 + local_now.minute
    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= now_minutes < end_minutes
    return now_minutes >= start_minutes or now_minutes < end_minutes


def _morning_memo_cadence_allows_now(cadence: str, *, local_now: datetime) -> bool:
    normalized = str(cadence or "daily_morning").strip().lower() or "daily_morning"
    if normalized in {"weekdays", "weekdays_morning"}:
        return local_now.weekday() < 5
    return True


def _parse_observation_created_at(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except Exception:
        return None


def _recent_morning_memo_failure_within_retry(
    channel_runtime,
    *,
    principal_id: str,
    schedule_key: str,
    local_day: str,
    observed_at: datetime,
    retry_after_minutes: int,
):
    for row in channel_runtime.list_recent_observations(limit=50, principal_id=principal_id):
        if str(getattr(row, "event_type", "") or "").strip() != "scheduled_morning_memo_delivery_failed":
            continue
        payload = dict(getattr(row, "payload", {}) or {})
        if str(payload.get("schedule_key") or "").strip() != schedule_key:
            continue
        if str(payload.get("local_day") or "").strip() != local_day:
            continue
        created_at = _parse_observation_created_at(str(getattr(row, "created_at", "") or ""))
        if created_at is None:
            continue
        if observed_at - created_at < timedelta(minutes=max(retry_after_minutes, 5)):
            return row
    return None


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
    api_recovered = 0
    browseract_failed = 0
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
        bound_account_label_order: list[str] = []
        seen_bound_account_labels: set[str] = set()
        all_account_login_credentials: dict[str, dict[str, str]] = {}
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
            for account_label in account_labels:
                if account_label and account_label not in seen_bound_account_labels:
                    seen_bound_account_labels.add(account_label)
                    bound_account_label_order.append(account_label)
                credentials = providers_route.upstream.onemin_account_login_credentials(
                    account_name=account_label,
                    binding_metadata=binding_metadata,
                )
                if credentials:
                    all_account_login_credentials[account_label] = credentials
            binding_jobs.append(
                {
                    "binding": binding,
                    "principal_id": principal_id,
                    "binding_id": binding.binding_id,
                    "external_account_ref": binding.external_account_ref,
                    "binding_metadata": binding_metadata,
                    "billing_run_url": billing_run_url,
                    "billing_workflow_id": billing_workflow_id,
                    "members_run_url": members_run_url,
                    "members_workflow_id": members_workflow_id,
                    "account_labels": tuple(account_labels),
                }
            )
        all_owner_account_rows = providers_route._normalized_onemin_owner_rows()
        for row in all_owner_account_rows:
            account_label = str(row.get("account_name") or "").strip()
            if not account_label or account_label in all_account_login_credentials:
                continue
            credentials = providers_route.upstream.onemin_account_login_credentials(
                account_name=account_label,
                binding_metadata={},
            )
            if credentials:
                all_account_login_credentials[account_label] = credentials

        if bound_account_label_order:
            browseract_target_label_order = list(bound_account_label_order)
        elif all_owner_account_rows and binding_jobs:
            browseract_target_label_order = [
                str(row.get("account_name") or "").strip()
                for row in all_owner_account_rows
                if str(row.get("account_name") or "").strip()
            ]
        else:
            browseract_target_label_order = []
        select_refresh_account_labels = getattr(container.onemin_manager, "select_billing_refresh_account_labels", None)
        stale_labels, actual_labels = providers_route._partition_onemin_browseract_account_labels(
            container=container,
            principal_id="",
            binding_rows=[],
            account_labels=browseract_target_label_order,
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

        browseract_billing_jobs: list[dict[str, object]] = []
        browseract_attempted_labels: set[str] = set()
        for account_label in browseract_target_label_order:
            if account_label not in selected_browseract_labels:
                continue
            selected_binding_job = providers_route._select_onemin_browseract_binding_job(
                binding_jobs=binding_jobs,
                account_label=account_label,
                require_members=False,
            )
            if selected_binding_job is None:
                continue
            binding_metadata = dict(selected_binding_job.get("binding_metadata") or {})
            browseract_billing_jobs.append(
                {
                    "principal_id": str(selected_binding_job.get("principal_id") or ""),
                    "binding_id": str(selected_binding_job.get("binding_id") or ""),
                    "external_account_ref": str(selected_binding_job.get("external_account_ref") or ""),
                    "account_label": account_label,
                    "billing_run_url": str(selected_binding_job.get("billing_run_url") or ""),
                    "billing_workflow_id": str(selected_binding_job.get("billing_workflow_id") or ""),
                    "members_run_url": str(selected_binding_job.get("members_run_url") or ""),
                    "members_workflow_id": str(selected_binding_job.get("members_workflow_id") or ""),
                    "member_login_ready": providers_route._browseract_onemin_login_ready(
                        account_label=account_label,
                        binding_metadata=binding_metadata,
                    ),
                }
            )

        browseract_attempted = len(browseract_billing_jobs)
        with providers_route._managed_fastestvpn_services(
            service_names=providers_route._browseract_fastestvpn_service_names(browseract_billing_jobs),
            reason="scheduler.onemin.browseract.refresh",
        ):
            effective_browseract_parallelism = 1 if all_owner_account_rows else max(
                1,
                min(
                    browseract_parallelism,
                    len(
                        {
                            str(job.get("binding_id") or "").strip()
                            for job in browseract_billing_jobs
                            if str(job.get("binding_id") or "").strip()
                        }
                    )
                    or 1,
                ),
            )
            billing_results, billing_errors = providers_route._run_onemin_browseract_jobs(
                jobs=browseract_billing_jobs,
                max_workers=effective_browseract_parallelism,
                tool_name="browseract.onemin_billing_usage",
                stop_on_failure_codes={
                    "auth_request_failed",
                    "challenge_required",
                    "session_expired",
                    "timeout",
                    "ui_worker_failed",
                    "lane_unavailable",
                },
                max_consecutive_stop_failures=providers_route._onemin_browseract_systemic_failure_threshold(),
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
                        **providers_route._browseract_proxy_payload(
                            binding_metadata=dict(job.get("binding_metadata") or {}),
                            account_label=str(job.get("account_label") or ""),
                        ),
                        "timeout_seconds": browseract_timeout_seconds,
                    },
                ),
            )
            browseract_attempted_labels = {
                str(row.get("account_label") or "").strip()
                for row in [*billing_results, *billing_errors]
                if str(row.get("account_label") or "").strip()
            }
            browseract_attempted = len(browseract_attempted_labels)
            browseract_refreshed = len(billing_results)

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
            effective_member_parallelism = 1 if all_owner_account_rows else max(
                1,
                min(
                    browseract_parallelism,
                    len(
                        {
                            str(job.get("binding_id") or "").strip()
                            for job in browseract_member_jobs
                            if str(job.get("binding_id") or "").strip()
                        }
                    )
                    or 1,
                ),
            )
            member_results, member_errors = providers_route._run_onemin_browseract_jobs(
                jobs=browseract_member_jobs,
                max_workers=effective_member_parallelism,
                tool_name="browseract.onemin_member_reconciliation",
                stop_on_failure_codes={
                    "auth_request_failed",
                    "challenge_required",
                    "session_expired",
                    "timeout",
                    "ui_worker_failed",
                    "lane_unavailable",
                },
                max_consecutive_stop_failures=providers_route._onemin_browseract_systemic_failure_threshold(),
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
                        **providers_route._browseract_proxy_payload(
                            binding_metadata=dict(job.get("binding_metadata") or {}),
                            account_label=str(job.get("account_label") or ""),
                        ),
                        "timeout_seconds": browseract_timeout_seconds,
                    },
                ),
            )
            member_reconciled = len(member_results)
        browseract_failed_labels = {
            str(row.get("account_label") or "").strip()
            for row in [*billing_errors, *member_errors]
            if str(row.get("account_label") or "").strip()
        }
        browseract_failed = len(browseract_failed_labels)
        recovered_browseract_labels: set[str] = set()
        fallback_api_errors: list[dict[str, object]] = []
        unattempted_browseract_labels = {
            label
            for label in browseract_target_label_order
            if label and label not in browseract_attempted_labels
        }
        if browseract_failed_labels:
            with providers_route._managed_fastestvpn_services(
                service_names=providers_route._onemin_direct_api_fastestvpn_service_names(
                    account_labels=browseract_failed_labels | unattempted_browseract_labels
                ),
                reason="scheduler.onemin.provider_api.recovery",
            ):
                (
                    api_billing_results,
                    api_member_results,
                    fallback_api_errors,
                    api_attempted,
                    _api_skipped,
                    api_rate_limited,
                ) = providers_route._refresh_onemin_via_provider_api(
                    include_members=True,
                    timeout_seconds=180,
                    all_accounts=False,
                    continue_on_rate_limit=False,
                    account_labels=browseract_failed_labels | unattempted_browseract_labels,
                    account_login_credentials={
                        account_label: credentials
                        for account_label, credentials in all_account_login_credentials.items()
                        if account_label in (browseract_failed_labels | unattempted_browseract_labels)
                    },
                )
            recovered_browseract_labels.update(
                str(row.get("account_label") or "").strip()
                for row in [*api_billing_results, *api_member_results]
                if str(row.get("account_label") or "").strip()
            )
            api_recovered = len(recovered_browseract_labels & browseract_failed_labels)
            member_reconciled = len(
                {
                    str(row.get("account_label") or "").strip()
                    for row in [*member_results, *api_member_results]
                    if str(row.get("account_label") or "").strip()
                }
            )
        elif _scheduler_onemin_global_provider_api_sweep_enabled():
            if unattempted_browseract_labels:
                with providers_route._managed_fastestvpn_services(
                    service_names=providers_route._onemin_direct_api_fastestvpn_service_names(
                        account_labels=unattempted_browseract_labels
                    ),
                    reason="scheduler.onemin.provider_api.gap_recovery",
                ):
                    (
                        _api_billing_results,
                        _api_member_results,
                        api_errors,
                        global_api_attempted,
                        _api_skipped,
                        global_api_rate_limited,
                    ) = providers_route._refresh_onemin_via_provider_api(
                        include_members=True,
                        timeout_seconds=180,
                        all_accounts=False,
                        continue_on_rate_limit=False,
                        account_labels=unattempted_browseract_labels,
                        account_login_credentials={
                            account_label: credentials
                            for account_label, credentials in all_account_login_credentials.items()
                            if account_label in unattempted_browseract_labels
                        },
                    )
                api_attempted += global_api_attempted
                api_rate_limited = api_rate_limited or global_api_rate_limited
                error_count += len(api_errors)
            elif not browseract_target_label_order:
                with providers_route._managed_fastestvpn_services(
                    service_names=providers_route._onemin_direct_api_fastestvpn_service_names(account_labels=None),
                    reason="scheduler.onemin.provider_api.global",
                ):
                    (
                        _api_billing_results,
                        _api_member_results,
                        api_errors,
                        global_api_attempted,
                        _api_skipped,
                        global_api_rate_limited,
                    ) = providers_route._refresh_onemin_via_provider_api(
                        include_members=True,
                        timeout_seconds=180,
                        all_accounts=True,
                        continue_on_rate_limit=False,
                    )
                api_attempted += global_api_attempted
                api_rate_limited = api_rate_limited or global_api_rate_limited
                error_count += len(api_errors)

        unrecovered_billing_errors = [
            row
            for row in billing_errors
            if str(row.get("account_label") or "").strip() not in recovered_browseract_labels
        ]
        unrecovered_member_errors = [
            row
            for row in member_errors
            if str(row.get("account_label") or "").strip() not in recovered_browseract_labels
        ]
        error_count += len(unrecovered_billing_errors)
        error_count += len(unrecovered_member_errors)
        error_count += len(fallback_api_errors)
        for row in unrecovered_billing_errors:
            log.warning(
                "scheduler onemin billing browseract refresh failed principal=%s binding=%s account=%s code=%s error=%s",
                next((str(job.get("principal_id") or "") for job in browseract_billing_jobs if str(job.get("account_label") or "") == str(row.get("account_label") or "")), ""),
                row.get("binding_id"),
                row.get("account_label"),
                row.get("failure_code"),
                row.get("error"),
            )
        for row in unrecovered_member_errors:
            log.warning(
                "scheduler onemin member reconciliation failed principal=%s binding=%s account=%s code=%s error=%s",
                next((str(job.get("principal_id") or "") for job in browseract_member_jobs if str(job.get("account_label") or "") == str(row.get("account_label") or "")), ""),
                row.get("binding_id"),
                row.get("account_label"),
                row.get("failure_code"),
                row.get("error"),
            )
        if recovered_browseract_labels:
            log.info(
                "scheduler onemin recovered browseract failures via provider api accounts=%s",
                ",".join(sorted(recovered_browseract_labels & browseract_failed_labels)),
            )
        for row in fallback_api_errors:
            log.warning(
                "scheduler onemin provider api fallback failed account=%s error=%s",
                row.get("account_label"),
                row.get("error"),
            )

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
            "api_recovered": api_recovered,
            "browseract_failed": browseract_failed,
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
    skipped = 0
    property_accounts = _scheduler_property_alert_account_emails()
    property_attempted = 0
    property_synced = 0
    forbidden_cooldown_seconds = _scheduler_google_signal_sync_forbidden_cooldown_seconds()
    now_epoch = time.time()
    for principal_id in principal_ids:
        blocked_until = float(_SCHEDULER_GOOGLE_SIGNAL_SYNC_FORBIDDEN_COOLDOWNS.get(principal_id) or 0.0)
        if blocked_until > now_epoch:
            skipped += 1
            log.info(
                "scheduler google signal sync skipped principal=%s reason=http_403_cooldown retry_in=%ss",
                principal_id,
                max(1, int(blocked_until - now_epoch)),
            )
            continue
        if blocked_until > 0.0:
            _SCHEDULER_GOOGLE_SIGNAL_SYNC_FORBIDDEN_COOLDOWNS.pop(principal_id, None)
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
            for account_email in property_accounts:
                property_attempted += 1
                property_summary = service.sync_google_willhaben_signals(
                    principal_id=principal_id,
                    actor="scheduler",
                    account_email=account_email,
                    email_limit=10,
                )
                property_synced += int(property_summary.get("synced_total") or 0)
        except RuntimeError as exc:
            error_count += 1
            log.info(
                "scheduler google signal sync skipped principal=%s reason=%s",
                principal_id,
                str(exc or "unknown_error"),
            )
        except urllib.error.HTTPError as exc:
            error_count += 1
            if exc.code in {401, 403} and forbidden_cooldown_seconds > 0.0:
                blocked_until = time.time() + forbidden_cooldown_seconds
                _SCHEDULER_GOOGLE_SIGNAL_SYNC_FORBIDDEN_COOLDOWNS[principal_id] = blocked_until
                log.warning(
                    "scheduler google signal sync auth blocked principal=%s status=%s cooldown_until=%s",
                    principal_id,
                    exc.code,
                    datetime.fromtimestamp(blocked_until, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                )
                continue
            log.exception("scheduler google signal sync failed principal=%s", principal_id)
        except Exception:
            error_count += 1
            log.exception("scheduler google signal sync failed principal=%s", principal_id)
    result = {
        "ran": True,
        "attempted": attempted,
        "synced": synced,
        "errors": error_count,
        "skipped": skipped,
    }
    if property_accounts:
        result.update(
            {
                "property_accounts": list(property_accounts),
                "property_attempted": property_attempted,
                "property_synced": property_synced,
            }
        )
    return result


def _scheduler_property_scout_enabled() -> bool:
    normalized = str(os.environ.get("EA_SCHEDULER_PROPERTY_SCOUT_ENABLED") or "").strip().lower()
    if not normalized:
        return True
    return normalized in {"1", "true", "yes", "on", "y"}


def _propertyquarry_scheduler_profile() -> str:
    return str(os.environ.get("PROPERTYQUARRY_SCHEDULER_PROFILE") or "").strip().lower()


def _scheduler_property_only_profile_enabled() -> bool:
    return _propertyquarry_scheduler_profile() in {"property_only", "property-only", "property"}


def _propertyquarry_worker_profile() -> str:
    return str(os.environ.get("PROPERTYQUARRY_WORKER_PROFILE") or "").strip().lower()


def _worker_property_only_profile_enabled() -> bool:
    return _propertyquarry_worker_profile() in {"property_only", "property-only", "property"}


def _scheduler_property_scout_interval_seconds() -> float:
    try:
        return max(300.0, float(os.environ.get("EA_SCHEDULER_PROPERTY_SCOUT_INTERVAL_SECONDS") or 1800.0))
    except Exception:
        return 1800.0


def _scheduler_property_results_finalize_interval_seconds() -> float:
    try:
        return max(15.0, float(os.environ.get("EA_SCHEDULER_PROPERTY_RESULTS_FINALIZE_INTERVAL_SECONDS") or 60.0))
    except Exception:
        return 60.0


def _scheduler_property_scout_principal_ids(container) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    raw = str(os.environ.get("EA_PROPERTY_SCOUT_PRINCIPAL_IDS") or "").strip()
    if raw:
        values = tuple(sorted({part.strip() for part in raw.split(",") if part.strip()}))
        if values:
            return values
    principal_candidates = {
        str(os.environ.get("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip(),
        str(getattr(getattr(container.settings, "auth", None), "default_principal_id", "") or "").strip(),
        str(os.environ.get("EA_DEFAULT_PRINCIPAL_ID") or "").strip(),
    }
    return tuple(sorted(value for value in principal_candidates if value))


def _run_scheduler_property_scout(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from app.product.service import build_product_service

    service = build_product_service(container)
    attempted = 0
    synced = 0
    errors = 0
    principals = _scheduler_property_scout_principal_ids(container)
    for principal_id in principals:
        attempted += 1
        try:
            summary = service.sync_direct_property_scout(
                principal_id=principal_id,
                actor="scheduler",
            )
            if str(summary.get("status") or "").strip() in {"processed", "noop"}:
                synced += max(
                    int(summary.get("review_created_total") or 0),
                    int(summary.get("notified_total") or 0),
                    int(summary.get("tour_created_total") or 0),
                )
        except Exception:
            errors += 1
            log.exception("scheduler property scout failed principal=%s", principal_id)
    return {
        "ran": True,
        "attempted": attempted,
        "synced": synced,
        "errors": errors,
        "principals": list(principals),
    }


def _run_scheduler_property_results_finalize(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from app.product.service import build_product_service

    service = build_product_service(container)
    try:
        summary = service.reconcile_property_search_results_delivery(limit=40)
    except Exception:
        log.exception("scheduler property results finalize failed")
        return {"ran": True, "attempted": 0, "finalized": 0, "emailed": 0, "pending": 0, "errors": 1}
    return {
        "ran": True,
        "attempted": int(summary.get("attempted") or 0),
        "finalized": int(summary.get("finalized") or 0),
        "emailed": int(summary.get("emailed") or 0),
        "pending": int(summary.get("pending") or 0),
        "errors": 0,
    }


def _run_scheduler_pocket_signal_sync(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from app.product.service import build_product_service

    if not str(os.environ.get("POCKET_API_KEY") or "").strip():
        return {"ran": False, "attempted": 0, "synced": 0, "errors": 0, "reason": "pocket_api_key_missing"}
    principal_id = str(getattr(getattr(container.settings, "auth", None), "default_principal_id", "") or "").strip() or "local-user"
    service = build_product_service(container)
    try:
        summary = service.sync_pocket_recordings(
            principal_id=principal_id,
            actor="scheduler",
            limit=_scheduler_pocket_signal_sync_limit(),
        )
        synced_total = max(int(summary.get("synced_total") or summary.get("total") or 0), 0)
        failed_total = max(int(summary.get("failed_total") or 0), 0)
        return {
            "ran": True,
            "attempted": 1,
            "synced": synced_total,
            "errors": failed_total,
            "principal_id": principal_id,
        }
    except RuntimeError as exc:
        log.info(
            "scheduler pocket signal sync skipped principal=%s reason=%s",
            principal_id,
            str(exc or "unknown_error"),
        )
        return {"ran": True, "attempted": 1, "synced": 0, "errors": 1, "principal_id": principal_id}
    except Exception:
        log.exception("scheduler pocket signal sync failed principal=%s", principal_id)
        return {"ran": True, "attempted": 1, "synced": 0, "errors": 1, "principal_id": principal_id}


def _run_scheduler_morning_memo_delivery(
    container,
    log: logging.Logger,
    *,
    now_utc: datetime | None = None,
) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from app.product.service import build_product_service
    from app.services.google_oauth import GOOGLE_CONNECTOR_NAME
    from app.services.registration_email import email_delivery_enabled
    from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR

    observed_at = now_utc or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    service = build_product_service(container)
    google_bindings = [
        binding
        for binding in container.tool_runtime.list_connector_bindings_for_connector(GOOGLE_CONNECTOR_NAME, limit=1000)
        if str(binding.status or "").strip().lower() == "enabled" and str(binding.principal_id or "").strip()
    ]
    telegram_bindings = [
        binding
        for binding in container.tool_runtime.list_connector_bindings_for_connector(TELEGRAM_IDENTITY_CONNECTOR, limit=1000)
        if str(binding.status or "").strip().lower() == "enabled" and str(binding.principal_id or "").strip()
    ]
    google_bindings_by_principal: dict[str, list[object]] = {}
    for binding in google_bindings:
        principal_id = str(binding.principal_id or "").strip()
        if principal_id:
            google_bindings_by_principal.setdefault(principal_id, []).append(binding)
    principals = {
        str(binding.principal_id or "").strip()
        for binding in [*google_bindings, *telegram_bindings]
        if str(binding.principal_id or "").strip()
    }

    configured = 0
    due = 0
    sent = 0
    blocked = 0
    failed = 0
    skipped = 0
    error_count = 0

    for principal_id in sorted(principals):
        try:
            principal_bindings = list(google_bindings_by_principal.get(principal_id, []))
            preferences = container.memory_runtime.list_delivery_preferences(
                principal_id=principal_id,
                limit=50,
                status="active",
            )
            preference = next(
                (
                    row
                    for row in preferences
                    if str(dict(row.format_json or {}).get("schedule_kind") or "").strip().lower() in {"morning_memo", "assistant_nudge"}
                ),
                None,
            )
            if preference is None:
                continue
            configured += 1
            quiet_hours = dict(preference.quiet_hours_json or {})
            format_json = dict(preference.format_json or {})
            local_now = observed_at.astimezone(_schedule_timezone(str(quiet_hours.get("timezone") or "UTC")))
            if not _morning_memo_cadence_allows_now(str(preference.cadence or "daily_morning"), local_now=local_now):
                skipped += 1
                continue
            delivery_time = _normalize_scheduler_time(
                str(quiet_hours.get("delivery_time_local") or ""),
                default="08:00",
            )
            delivery_start = local_now.replace(
                hour=delivery_time[0],
                minute=delivery_time[1],
                second=0,
                microsecond=0,
            )
            delivery_window_minutes = max(
                int(quiet_hours.get("delivery_window_minutes") or _SCHEDULER_MORNING_MEMO_DELIVERY_WINDOW_MINUTES),
                15,
            )
            delivery_end = delivery_start + timedelta(minutes=delivery_window_minutes)
            if local_now < delivery_start or local_now >= delivery_end:
                skipped += 1
                continue
            due += 1
            quiet_start = _normalize_scheduler_time(
                str(quiet_hours.get("quiet_hours_start") or ""),
                default="20:00",
            )
            quiet_end = _normalize_scheduler_time(
                str(quiet_hours.get("quiet_hours_end") or ""),
                default="07:00",
            )
            local_day = local_now.date().isoformat()
            schedule_key = str(preference.preference_id or f"morning-memo:{principal_id}").strip()
            sent_dedupe = f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|sent"
            if container.channel_runtime.find_observation_by_dedupe(sent_dedupe, principal_id=principal_id):
                skipped += 1
                continue
            if _is_local_time_within_quiet_hours(local_now, quiet_start=quiet_start, quiet_end=quiet_end):
                blocked += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_blocked",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "reason": "quiet_hours",
                        "delivery_time_local": f"{delivery_time[0]:02d}:{delivery_time[1]:02d}",
                    },
                    source_id=schedule_key,
                    dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|quiet-hours",
                )
                continue
            retry_after_minutes = max(
                int(format_json.get("retry_after_minutes") or _SCHEDULER_MORNING_MEMO_RETRY_AFTER_MINUTES),
                5,
            )
            recent_failure = _recent_morning_memo_failure_within_retry(
                container.channel_runtime,
                principal_id=principal_id,
                schedule_key=schedule_key,
                local_day=local_day,
                observed_at=observed_at,
                retry_after_minutes=retry_after_minutes,
            )
            if recent_failure is not None:
                blocked += 1
                continue
            delivery_channel = str(format_json.get("delivery_channel") or preference.channel or "email").strip().lower() or "email"
            if delivery_channel not in {"email", "telegram"}:
                blocked += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_blocked",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "reason": "unsupported_delivery_channel",
                        "delivery_channel": delivery_channel,
                    },
                    source_id=schedule_key,
                    dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|unsupported-channel",
                )
                continue
            explicit_email = str(format_json.get("recipient_email") or "").strip().lower()
            google_email = next(
                (
                    str(
                        dict(getattr(binding, "auth_metadata_json", {}) or {}).get("google_email")
                        or getattr(binding, "external_account_ref", "")
                        or ""
                    ).strip().lower()
                    for binding in principal_bindings
                    if str(
                        dict(getattr(binding, "auth_metadata_json", {}) or {}).get("google_email")
                        or getattr(binding, "external_account_ref", "")
                        or ""
                    ).strip()
                ),
                "",
            )
            recipient_email = explicit_email or google_email or principal_id
            if not recipient_email:
                blocked += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_blocked",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "reason": "recipient_missing",
                    },
                    source_id=schedule_key,
                    dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|recipient-missing",
                )
                continue
            digest_key = str(format_json.get("digest_key") or "memo").strip().lower() or "memo"
            digest = service.channel_digest_pack(
                principal_id=principal_id,
                digest_key=digest_key,
                operator_id="",
            )
            if digest is None or (digest_key == "assistant_nudge" and not list(digest.get("items") or [])):
                skipped += 1
                continue
            if delivery_channel == "email" and not email_delivery_enabled():
                blocked += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_blocked",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "reason": "email_delivery_not_configured",
                        "recipient_email": recipient_email,
                    },
                    source_id=schedule_key,
                    dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|email-not-configured",
                )
                continue
            payload = service.issue_channel_digest_delivery(
                principal_id=principal_id,
                digest_key=digest_key,
                recipient_email=recipient_email,
                role=str(format_json.get("role") or "principal").strip().lower() or "principal",
                display_name=str(format_json.get("display_name") or recipient_email or "Workspace Principal").strip(),
                operator_id="",
                delivery_channel=delivery_channel,
                expires_in_hours=72,
                base_url=_scheduler_public_base_url(),
            )
            if payload is None:
                failed += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_failed",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "reason": "digest_not_available",
                    },
                    source_id=schedule_key,
                    dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|digest-missing",
                )
                continue
            delivery_status = str(
                payload.get("telegram_delivery_status") if delivery_channel == "telegram" else payload.get("email_delivery_status") or ""
            ).strip().lower()
            if delivery_status == "sent":
                sent += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_sent",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "delivery_id": str(payload.get("delivery_id") or "").strip(),
                        "recipient_email": recipient_email,
                        "digest_key": str(payload.get("digest_key") or "memo").strip(),
                        "delivery_channel": delivery_channel,
                    },
                    source_id=str(payload.get("delivery_id") or schedule_key).strip() or schedule_key,
                    dedupe_key=sent_dedupe,
                )
                continue
            if delivery_status == "not_configured":
                blocked += 1
                container.channel_runtime.ingest_observation(
                    principal_id=principal_id,
                    channel="product",
                    event_type="scheduled_morning_memo_delivery_blocked",
                    payload={
                        "schedule_key": schedule_key,
                        "local_day": local_day,
                        "reason": f"{delivery_channel}_delivery_not_configured",
                        "recipient_email": recipient_email,
                    },
                    source_id=str(payload.get("delivery_id") or schedule_key).strip() or schedule_key,
                    dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|{delivery_channel}-not-configured",
                )
                continue
            failed += 1
            failure_bucket = int(observed_at.timestamp()) // max(retry_after_minutes * 60, 60)
            container.channel_runtime.ingest_observation(
                principal_id=principal_id,
                channel="product",
                event_type="scheduled_morning_memo_delivery_failed",
                payload={
                    "schedule_key": schedule_key,
                    "local_day": local_day,
                    "delivery_id": str(payload.get("delivery_id") or "").strip(),
                    "recipient_email": recipient_email,
                    "digest_key": str(payload.get("digest_key") or digest_key).strip(),
                    "delivery_channel": delivery_channel,
                    "email_delivery_status": str(payload.get("email_delivery_status") or "").strip(),
                    "email_delivery_error": str(payload.get("email_delivery_error") or "").strip(),
                    "telegram_delivery_status": str(payload.get("telegram_delivery_status") or "").strip(),
                    "telegram_delivery_error": str(payload.get("telegram_delivery_error") or "").strip(),
                },
                source_id=str(payload.get("delivery_id") or schedule_key).strip() or schedule_key,
                dedupe_key=f"{principal_id}|scheduled-morning-memo|{schedule_key}|{local_day}|failed|{failure_bucket}",
            )
        except Exception:
            error_count += 1
            log.exception("scheduler morning memo delivery failed principal=%s", principal_id)
    return {
        "ran": True,
        "configured": configured,
        "due": due,
        "sent": sent,
        "blocked": blocked,
        "failed": failed,
        "skipped": skipped,
        "errors": error_count,
    }


def _parse_runner_isoish_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _derive_telegram_async_message_id(dedupe_key: str, fallback_external_id: str) -> str:
    normalized = str(dedupe_key or "").strip()
    if normalized:
        parts = [part for part in normalized.split(":") if part]
        if len(parts) >= 3:
            return str(parts[-1]).strip()
    return str(fallback_external_id or "").strip()


def _run_scheduler_telegram_async_recovery(container, log: logging.Logger) -> dict[str, object]:  # type: ignore[no-untyped-def]
    drained = 0
    pending = 0
    skipped = 0
    errors = 0
    observed_at = datetime.now(timezone.utc)
    min_age_seconds = max(_scheduler_telegram_async_recovery_min_age_seconds(), 5.0)
    for row in container.channel_runtime.list_recent_observations(limit=400):
        if str(getattr(row, "channel", "") or "").strip() != "telegram":
            continue
        if str(getattr(row, "event_type", "") or "").strip() != "telegram.reply_async_started":
            continue
        principal_id = str(getattr(row, "principal_id", "") or "").strip()
        payload = dict(getattr(row, "payload", {}) or {})
        chat_id = str(payload.get("chat_id") or "").strip()
        prompt_text = str(payload.get("prompt_text") or "").strip()
        dedupe_key = str(payload.get("dedupe_key") or getattr(row, "external_id", "") or "").strip()
        current_message_id = _derive_telegram_async_message_id(
            dedupe_key,
            str(getattr(row, "external_id", "") or "").strip(),
        )
        created_at = _parse_runner_isoish_datetime(getattr(row, "created_at", "") or "")
        if not principal_id or not chat_id or not prompt_text or not current_message_id or not created_at:
            skipped += 1
            continue
        if max((observed_at - created_at).total_seconds(), 0.0) < min_age_seconds:
            pending += 1
            continue
        sent_dedupe = f"{current_message_id}:assistant_async_sent"
        failed_dedupe = f"{current_message_id}:assistant_async_failed"
        if container.channel_runtime.find_observation_by_dedupe(sent_dedupe, principal_id=principal_id) is not None:
            skipped += 1
            continue
        if container.channel_runtime.find_observation_by_dedupe(failed_dedupe, principal_id=principal_id) is not None:
            skipped += 1
            continue
        bot_key = str(payload.get("bot_key") or "").strip()
        bot_handle = str(payload.get("bot_handle") or "").strip()
        try:
            bot_config = _resolve_telegram_bot_config(bot_key=bot_key)
            if not bot_config and bot_handle:
                bot_config = _resolve_telegram_bot_config()
                if str(bot_config.get("handle") or "").strip() != bot_handle:
                    bot_config = {}
            if not bot_config:
                skipped += 1
                continue
            _telegram_async_assistant_reply_worker(
                container=container,
                principal_id=principal_id,
                bot_config=dict(bot_config),
                chat_id=chat_id,
                text=prompt_text,
                current_message_id=current_message_id,
            )
            drained += 1
        except Exception:
            errors += 1
            log.exception(
                "scheduler telegram async outbox drain failed principal=%s chat=%s message=%s",
                principal_id,
                chat_id,
                current_message_id,
            )
    return {
        "ran": True,
        "drained": drained,
        "pending": pending,
        "skipped": skipped,
        "errors": errors,
    }


def _run_api() -> None:
    s = get_settings()
    uvicorn.run(
        "app.main:app",
        host=s.host,
        port=s.port,
        log_level=s.log_level.lower(),
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )


def _run_openvoice() -> None:
    host = str(os.environ.get("OPENVOICE_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    raw_port = str(os.environ.get("OPENVOICE_PORT") or "8093").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 8093
    log_level = str(os.environ.get("OPENVOICE_LOG_LEVEL") or get_settings().log_level).strip().lower() or "info"
    uvicorn.run(
        "app.openvoice_app:app",
        host=host,
        port=port,
        log_level=log_level,
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )


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
    last_property_scout_at = 0.0
    last_property_results_finalize_at = 0.0
    last_pocket_signal_sync_at = 0.0
    last_morning_memo_at = 0.0
    last_telegram_async_recovery_at = 0.0
    property_only_scheduler = role == "scheduler" and _scheduler_property_only_profile_enabled()
    property_only_worker = role == "worker" and _worker_property_only_profile_enabled()
    log.info("role=%s started worker loop", role)
    while not stop["flag"]:
        if role == "scheduler":
            now = time.time()
            if not property_only_scheduler and now - last_horizon_scan_at >= _SCHEDULER_SCAN_INTERVAL_SECONDS:
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
            if not property_only_scheduler and now - last_onemin_refresh_at >= _scheduler_onemin_refresh_interval_seconds():
                try:
                    refresh_summary = _run_scheduler_onemin_billing_refresh(container, log)
                    if bool(refresh_summary.get("ran")) and not bool(refresh_summary.get("throttled")):
                        last_onemin_refresh_at = now
                        log.info(
                            "role=%s scheduler onemin refresh browseract=%s/%s browseract_failed=%s members=%s api_attempted=%s api_recovered=%s api_rate_limited=%s errors=%s",
                            role,
                            refresh_summary.get("browseract_refreshed"),
                            refresh_summary.get("browseract_attempted"),
                            refresh_summary.get("browseract_failed"),
                            refresh_summary.get("member_reconciled"),
                            refresh_summary.get("api_attempted"),
                            refresh_summary.get("api_recovered"),
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
            if not property_only_scheduler and _scheduler_google_signal_sync_enabled() and (
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
            if _scheduler_property_scout_enabled() and (
                now - last_property_scout_at >= _scheduler_property_scout_interval_seconds()
            ):
                try:
                    scout_summary = _run_scheduler_property_scout(container, log)
                    last_property_scout_at = now
                    log.info(
                        "role=%s scheduler property scout attempted=%s synced=%s errors=%s principals=%s",
                        role,
                        scout_summary.get("attempted"),
                        scout_summary.get("synced"),
                        scout_summary.get("errors"),
                        ",".join(list(scout_summary.get("principals") or [])),
                    )
                except Exception:
                    log.exception("role=%s scheduler property scout failed", role)
                    last_property_scout_at = now
            if now - last_property_results_finalize_at >= _scheduler_property_results_finalize_interval_seconds():
                try:
                    finalize_summary = _run_scheduler_property_results_finalize(container, log)
                    last_property_results_finalize_at = now
                    if (
                        int(finalize_summary.get("attempted") or 0) > 0
                        or int(finalize_summary.get("emailed") or 0) > 0
                        or int(finalize_summary.get("pending") or 0) > 0
                    ):
                        log.info(
                            "role=%s scheduler property results finalize attempted=%s finalized=%s emailed=%s pending=%s errors=%s",
                            role,
                            finalize_summary.get("attempted"),
                            finalize_summary.get("finalized"),
                            finalize_summary.get("emailed"),
                            finalize_summary.get("pending"),
                            finalize_summary.get("errors"),
                        )
                except Exception:
                    log.exception("role=%s scheduler property results finalize failed", role)
                    last_property_results_finalize_at = now
            if not property_only_scheduler and _scheduler_pocket_signal_sync_enabled() and (
                now - last_pocket_signal_sync_at >= _scheduler_pocket_signal_sync_interval_seconds()
            ):
                try:
                    sync_summary = _run_scheduler_pocket_signal_sync(container, log)
                    last_pocket_signal_sync_at = now
                    log.info(
                        "role=%s scheduler pocket signal sync attempted=%s synced=%s errors=%s principal=%s",
                        role,
                        sync_summary.get("attempted"),
                        sync_summary.get("synced"),
                        sync_summary.get("errors"),
                        sync_summary.get("principal_id", ""),
                    )
                except Exception:
                    log.exception("role=%s scheduler pocket signal sync failed", role)
                    last_pocket_signal_sync_at = now
            if not property_only_scheduler and _scheduler_morning_memo_enabled() and (
                now - last_morning_memo_at >= _scheduler_morning_memo_interval_seconds()
            ):
                try:
                    memo_summary = _run_scheduler_morning_memo_delivery(container, log)
                    last_morning_memo_at = now
                    log.info(
                        "role=%s scheduler morning memo configured=%s due=%s sent=%s blocked=%s failed=%s skipped=%s errors=%s",
                        role,
                        memo_summary.get("configured"),
                        memo_summary.get("due"),
                        memo_summary.get("sent"),
                        memo_summary.get("blocked"),
                        memo_summary.get("failed"),
                        memo_summary.get("skipped"),
                        memo_summary.get("errors"),
                    )
                except Exception:
                    log.exception("role=%s scheduler morning memo delivery failed", role)
                    last_morning_memo_at = now
            if not property_only_scheduler and _scheduler_telegram_async_recovery_enabled() and (
                now - last_telegram_async_recovery_at >= _scheduler_telegram_async_recovery_interval_seconds()
            ):
                try:
                    recovery_summary = _run_scheduler_telegram_async_recovery(container, log)
                    last_telegram_async_recovery_at = now
                    log.info(
                        "role=%s scheduler telegram async outbox drained=%s pending=%s skipped=%s errors=%s",
                        role,
                        recovery_summary.get("drained"),
                        recovery_summary.get("pending"),
                        recovery_summary.get("skipped"),
                        recovery_summary.get("errors"),
                    )
                except Exception:
                    log.exception("role=%s scheduler telegram async outbox failed", role)
                    last_telegram_async_recovery_at = now
            if property_only_scheduler:
                log.debug("role=%s property-only scheduler idle; sleeping %.1fs", role, idle_backoff_seconds)
                time.sleep(idle_backoff_seconds)
                idle_backoff_seconds = min(idle_backoff_seconds * 2.0, _IDLE_BACKOFF_MAX_SECONDS)
                continue
        if property_only_worker:
            log.debug("role=%s property-only worker skips inherited generic queue; sleeping %.1fs", role, idle_backoff_seconds)
            time.sleep(idle_backoff_seconds)
            idle_backoff_seconds = min(idle_backoff_seconds * 2.0, _IDLE_BACKOFF_MAX_SECONDS)
            continue
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
    if s.role == "openvoice":
        _run_openvoice()
        return
    _run_execution_worker(s.role)


if __name__ == "__main__":
    main()
