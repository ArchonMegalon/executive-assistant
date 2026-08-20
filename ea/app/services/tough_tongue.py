from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import os
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from app.services.provider_accounts import (
    ProviderAccountRegistry,
    ProviderAccountSlot,
    sanitized_provider_account_slot,
)


DEFAULT_BASE_URL = "https://api.toughtongueai.com/api/public"
MAX_RESPONSE_BYTES = 256 * 1024
TOUGH_TONGUE_CREDENTIAL_ENV_NAMES = (
    "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_API_KEYS",
    "TOUGH_TONGUE_API_KEYS",
    "TOUGH_TONGUE_API_KEY",
)
TOUGH_TONGUE_ACCOUNT_REF_ENV_NAMES = (
    "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_ACCOUNT_REFS",
    "TOUGH_TONGUE_ACCOUNT_REFS",
)
TOUGH_TONGUE_ORGANIZATION_ENV_NAMES = (
    "TOUGH_TONGUE_ORGANIZATION_IDS",
    "TOUGH_TONGUE_ORGANIZATION_ID",
)
TOUGH_TONGUE_PLAN_ENV_NAMES = (
    "TOUGH_TONGUE_ACCOUNT_TIERS",
    "TOUGH_TONGUE_ACCOUNT_TIER",
)
TOUGH_TONGUE_INDEXED_CREDENTIAL_ENV_NAMES = tuple(
    f"TOUGH_TONGUE_TIER4_ACCOUNT_{index}_API_KEY" for index in range(1, 7)
)
TOUGH_TONGUE_INDEXED_ACCOUNT_REF_ENV_NAMES = tuple(
    f"TOUGH_TONGUE_TIER4_ACCOUNT_{index}_EMAIL" for index in range(1, 7)
)
TOUGH_TONGUE_INDEXED_ORGANIZATION_ENV_NAMES = (
    "",
    *(f"TOUGH_TONGUE_TIER4_ACCOUNT_{index}_ORGANIZATION_ID" for index in range(2, 7)),
)
TOUGH_TONGUE_INDEXED_PLAN_ENV_NAMES = tuple(
    f"TOUGH_TONGUE_TIER4_ACCOUNT_{index}_TIER" for index in range(1, 7)
)
AGGREGATE_BASES = {"independent_accounts_sum", "shared_team_pool", "unknown_no_sum"}


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _sha256(value: object) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ToughTongueConfig:
    api_key: str
    organization_id: str
    base_url: str
    login_email: str
    forwarding_email: str
    account_tier: str
    enabled: bool
    account_verified: bool
    provider_verified: bool
    auto_create_sessions: bool
    allow_outbound_calls: bool
    allow_meeting_bots: bool
    allow_purchases: bool
    allow_publication: bool
    min_remaining_minutes: float
    max_session_minutes: float
    account_slots: tuple[ProviderAccountSlot, ...] = ()
    aggregate_basis: str = "unknown_no_sum"

    @classmethod
    def from_env(cls) -> "ToughTongueConfig":
        def _float(name: str, default: float) -> float:
            try:
                return max(float(str(os.environ.get(name) or default).strip()), 0.0)
            except (TypeError, ValueError):
                return default

        pooled_registry = ProviderAccountRegistry.from_env(
            provider_key="tough_tongue",
            credential_env_names=TOUGH_TONGUE_CREDENTIAL_ENV_NAMES,
            account_ref_env_names=TOUGH_TONGUE_ACCOUNT_REF_ENV_NAMES,
            organization_ref_env_names=TOUGH_TONGUE_ORGANIZATION_ENV_NAMES,
            plan_env_names=TOUGH_TONGUE_PLAN_ENV_NAMES,
        )
        indexed_registry = ProviderAccountRegistry.from_indexed_env(
            provider_key="tough_tongue",
            credential_env_names=TOUGH_TONGUE_INDEXED_CREDENTIAL_ENV_NAMES,
            account_ref_env_names=TOUGH_TONGUE_INDEXED_ACCOUNT_REF_ENV_NAMES,
            organization_ref_env_names=TOUGH_TONGUE_INDEXED_ORGANIZATION_ENV_NAMES,
            plan_env_names=TOUGH_TONGUE_INDEXED_PLAN_ENV_NAMES,
        )
        slots = ProviderAccountRegistry(
            (*indexed_registry.configured_slots, *pooled_registry.configured_slots)
        ).distinct_slots()
        first_slot = slots[0] if slots else None
        configured_basis = str(os.environ.get("EA_TOUGH_TONGUE_AGGREGATE_BASIS") or "").strip()
        aggregate_basis = configured_basis if configured_basis in AGGREGATE_BASES else "unknown_no_sum"
        return cls(
            api_key=first_slot.credential if first_slot is not None else "",
            organization_id=first_slot.organization_ref if first_slot is not None else "",
            base_url=str(os.environ.get("TOUGH_TONGUE_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
            login_email=str(os.environ.get("TOUGH_TONGUE_LOGIN_EMAIL") or "").strip(),
            forwarding_email=str(os.environ.get("TOUGH_TONGUE_FORWARDING_EMAIL") or "").strip(),
            account_tier=(
                first_slot.plan_name
                if first_slot is not None
                else str(os.environ.get("TOUGH_TONGUE_ACCOUNT_TIER") or "").strip()
            ),
            enabled=_env_truthy("EA_TOUGH_TONGUE_ENABLED"),
            account_verified=_env_truthy("EA_TOUGH_TONGUE_ACCOUNT_VERIFIED"),
            provider_verified=_env_truthy("EA_TOUGH_TONGUE_PROVIDER_VERIFIED"),
            auto_create_sessions=_env_truthy("EA_TOUGH_TONGUE_AUTO_CREATE_SESSIONS"),
            allow_outbound_calls=_env_truthy("EA_TOUGH_TONGUE_ALLOW_OUTBOUND_CALLS"),
            allow_meeting_bots=_env_truthy("EA_TOUGH_TONGUE_ALLOW_MEETING_BOTS"),
            allow_purchases=_env_truthy("EA_TOUGH_TONGUE_ALLOW_PURCHASES"),
            allow_publication=_env_truthy("EA_TOUGH_TONGUE_ALLOW_PUBLICATION"),
            min_remaining_minutes=_float("EA_TOUGH_TONGUE_MIN_REMAINING_MINUTES", 30.0),
            max_session_minutes=_float("EA_TOUGH_TONGUE_MAX_SESSION_MINUTES", 15.0),
            account_slots=slots,
            aggregate_basis=aggregate_basis,
        )

    @property
    def execution_ready(self) -> bool:
        return bool(
            self.enabled
            and self.api_key
            and self.organization_id
            and self.account_verified
            and self.provider_verified
        )

    def posture(self) -> dict[str, object]:
        registry = _registry_for_config(self)
        return {
            "configured": bool(registry.configured_slots),
            "configured_account_count": len(registry.configured_slots),
            "distinct_account_count": len(registry.distinct_slots()),
            "organization_configured": bool(self.organization_id),
            "organization_id_sha256": _sha256(self.organization_id),
            "enabled": self.enabled,
            "account_verified": self.account_verified,
            "provider_verified": self.provider_verified,
            "execution_ready": self.execution_ready,
            "account_tier": self.account_tier,
            "login_email_sha256": _sha256(self.login_email),
            "forwarding_email_sha256": _sha256(self.forwarding_email),
            "auto_create_sessions": self.auto_create_sessions,
            "allow_outbound_calls": self.allow_outbound_calls,
            "allow_meeting_bots": self.allow_meeting_bots,
            "allow_purchases": self.allow_purchases,
            "allow_publication": self.allow_publication,
            "min_remaining_minutes": self.min_remaining_minutes,
            "max_session_minutes": self.max_session_minutes,
            "raw_credentials_exposed": False,
            "account_emails_exposed": False,
        }


class ToughTongueClient:
    """Read-only Tough Tongue account client.

    Runtime session creation, calls, meeting bots, purchases, and publication are
    deliberately absent. Those actions consume quota or affect external state and
    need separately approved adapters and receipts.
    """

    def __init__(
        self,
        config: ToughTongueConfig | None = None,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.config = config or ToughTongueConfig.from_env()
        self._opener = opener

    def _get_json(self, path: str, *, timeout_seconds: float) -> Mapping[str, object]:
        if not self.config.api_key:
            raise RuntimeError("tough_tongue_api_key_missing")
        url = f"{self.config.base_url}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": "EA-ToughTongue-ReadOnly-Probe/1.0",
        }
        if self.config.organization_id:
            headers["X-TT-ORG"] = self.config.organization_id
        request = urllib.request.Request(
            url,
            method="GET",
            headers=headers,
        )
        with self._opener(request, timeout=max(float(timeout_seconds), 1.0)) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("tough_tongue_response_too_large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("tough_tongue_response_not_object")
        return payload

    def balance(self, *, timeout_seconds: float = 15.0) -> dict[str, object]:
        payload = self._get_json("balance", timeout_seconds=timeout_seconds)
        available = payload.get("available_minutes")
        try:
            available_minutes = float(available)
        except (TypeError, ValueError) as exc:
            raise ValueError("tough_tongue_balance_missing") from exc
        return {
            "available_minutes": max(available_minutes, 0.0),
            "last_updated": str(payload.get("last_updated") or "").strip(),
        }


def probe_tough_tongue_balance(
    *,
    timeout_seconds: float = 15.0,
    config: ToughTongueConfig | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, object]:
    effective = config or ToughTongueConfig.from_env()
    observed_at = _now_iso()
    posture = effective.posture()
    registry = _registry_for_config(effective)
    configured_slots = registry.configured_slots
    distinct_slots = registry.distinct_slots()
    report: dict[str, object] = {
        "provider_key": "tough_tongue",
        "display_name": "Tough Tongue AI",
        "status": "blocked",
        "remaining": None,
        "unit": "available_minutes",
        "refresh_at": "",
        "observed_at": observed_at,
        "account_label": f"Tier {effective.account_tier}" if effective.account_tier else "",
        "source": "tough_tongue_public_api:GET /balance",
        "probe_ok": False,
        "ready": False,
        "reason": "tough_tongue_api_key_missing",
        "next_action": "create_tough_tongue_personal_access_token_after_operator_approval",
        "raw": posture,
        "accounts": [],
        "aggregate": {
            "configured_count": len(configured_slots),
            "distinct_count": len(distinct_slots),
            "probed_count": 0,
            "ready_count": 0,
            "unavailable_count": 0,
            "remaining_total": None,
            "spendable_capacity": None,
            "unit": "available_minutes",
            "aggregate_basis": "unknown_no_sum",
            "shared_pool": False,
            "degraded": False,
            "refresh_at_mixed": False,
        },
    }
    if not distinct_slots:
        return report

    rows = [
        _probe_account_slot(
            slot,
            effective,
            timeout_seconds=timeout_seconds,
            opener=opener,
        )
        for slot in distinct_slots
    ]
    aggregate = _aggregate_account_rows(rows, effective)
    report["accounts"] = rows
    report["aggregate"] = aggregate
    successful_rows = [row for row in rows if bool(row["probe_ok"])]
    if not successful_rows:
        first = rows[0]
        report.update(
            {
                "status": first["status"],
                "reason": first["reason"],
                "next_action": first["next_action"],
            }
        )
        if "http_status" in first:
            raw = dict(report["raw"])
            raw["http_status"] = first["http_status"]
            report["raw"] = raw
        return report

    spendable_capacity = float(aggregate["spendable_capacity"] or 0.0)
    ready = spendable_capacity >= effective.min_remaining_minutes
    degraded = bool(aggregate["degraded"])
    refresh_values = [str(row["refresh_at"]) for row in successful_rows if str(row["refresh_at"])]
    report.update(
        {
            "status": "ready" if ready else "quota_low",
            "remaining": spendable_capacity,
            "refresh_at": min(refresh_values) if refresh_values else "",
            "probe_ok": True,
            "ready": ready,
            "reason": (
                "tough_tongue_team_probe_degraded"
                if ready and degraded
                else "" if ready else "tough_tongue_minutes_below_reserve"
            ),
            "next_action": (
                "reprobe_unavailable_tough_tongue_team_slots"
                if ready and degraded
                else "" if ready else "review_tough_tongue_minute_budget"
            ),
            "account_label": f"{len(distinct_slots)} governed team slot(s)",
        }
    )
    return report


def _registry_for_config(config: ToughTongueConfig) -> ProviderAccountRegistry:
    if config.account_slots:
        return ProviderAccountRegistry(config.account_slots)
    slots: tuple[ProviderAccountSlot, ...] = ()
    if config.api_key:
        slots = (
            ProviderAccountSlot(
                provider_key="tough_tongue",
                slot_label="team-slot-1",
                credential=config.api_key,
                organization_ref=config.organization_id,
                plan_name=config.account_tier,
            ),
        )
    return ProviderAccountRegistry(slots)


def _probe_account_slot(
    slot: ProviderAccountSlot,
    config: ToughTongueConfig,
    *,
    timeout_seconds: float,
    opener: Callable[..., Any],
) -> dict[str, object]:
    row = sanitized_provider_account_slot(slot)
    row.update(
        {
            "status": "blocked",
            "probe_ok": False,
            "ready": False,
            "remaining": None,
            "unit": "available_minutes",
            "refresh_at": "",
            "source": "tough_tongue_public_api:GET /balance",
            "reason": "tough_tongue_api_key_missing",
            "next_action": "replace_or_reauthorize_tough_tongue_api_key",
        }
    )
    slot_config = replace(
        config,
        api_key=slot.credential,
        organization_id=slot.organization_ref,
        account_tier=slot.plan_name,
        login_email="",
        forwarding_email="",
        account_slots=(),
    )
    try:
        balance = ToughTongueClient(slot_config, opener=opener).balance(timeout_seconds=timeout_seconds)
    except urllib.error.HTTPError as exc:
        row["status"] = "auth_failed" if exc.code in {401, 403} else "provider_error"
        row["reason"] = "tough_tongue_auth_failed" if exc.code in {401, 403} else "tough_tongue_http_error"
        row["next_action"] = (
            "replace_or_reauthorize_tough_tongue_api_key"
            if exc.code in {401, 403}
            else "reprobe_tough_tongue_balance"
        )
        row["http_status"] = int(exc.code)
        return row
    except (urllib.error.URLError, TimeoutError):
        row["status"] = "unavailable"
        row["reason"] = "tough_tongue_unreachable"
        row["next_action"] = "reprobe_tough_tongue_balance"
        return row
    except (RuntimeError, ValueError, json.JSONDecodeError):
        row["status"] = "probe_failed"
        row["reason"] = "tough_tongue_invalid_response"
        row["next_action"] = "inspect_tough_tongue_api_contract"
        return row

    remaining = float(balance["available_minutes"])
    ready = remaining >= config.min_remaining_minutes
    row.update(
        {
            "status": "ready" if ready else "quota_low",
            "probe_ok": True,
            "ready": ready,
            "remaining": remaining,
            "refresh_at": str(balance.get("last_updated") or "").strip(),
            "reason": "" if ready else "tough_tongue_minutes_below_reserve",
            "next_action": "" if ready else "review_tough_tongue_minute_budget",
        }
    )
    return row


def _aggregate_account_rows(
    rows: list[dict[str, object]],
    config: ToughTongueConfig,
) -> dict[str, object]:
    successful = [row for row in rows if bool(row["probe_ok"])]
    organization_counts: dict[str, int] = {}
    for row in successful:
        organization_ref = str(row["organization_ref_sha256"] or "")
        if organization_ref:
            organization_counts[organization_ref] = organization_counts.get(organization_ref, 0) + 1
    repeated_organization = any(count > 1 for count in organization_counts.values())
    if len(successful) <= 1:
        aggregate_basis = "independent_accounts_sum"
    elif repeated_organization or config.aggregate_basis == "shared_team_pool":
        aggregate_basis = "shared_team_pool"
    elif config.aggregate_basis == "independent_accounts_sum":
        aggregate_basis = "independent_accounts_sum"
    else:
        aggregate_basis = "unknown_no_sum"

    remaining_values = [float(row["remaining"] or 0.0) for row in successful]
    remaining_total: float | None
    if aggregate_basis == "independent_accounts_sum":
        remaining_total = sum(remaining_values)
    elif aggregate_basis == "shared_team_pool":
        grouped: dict[str, list[float]] = {}
        for row in successful:
            organization_ref = str(row["organization_ref_sha256"] or "")
            group = organization_ref or "shared-team-pool"
            grouped.setdefault(group, []).append(float(row["remaining"] or 0.0))
        remaining_total = sum(min(values) for values in grouped.values())
    else:
        remaining_total = None

    spendable_capacity = (
        remaining_total
        if remaining_total is not None
        else max(remaining_values, default=0.0)
    )
    refresh_values = {str(row["refresh_at"]) for row in successful if str(row["refresh_at"])}
    return {
        "configured_count": int(config.posture()["configured_account_count"]),
        "distinct_count": len(rows),
        "probed_count": len(rows),
        "ready_count": sum(1 for row in successful if bool(row["ready"])),
        "unavailable_count": sum(1 for row in rows if not bool(row["probe_ok"])),
        "remaining_total": remaining_total,
        "spendable_capacity": spendable_capacity,
        "unit": "available_minutes",
        "aggregate_basis": aggregate_basis,
        "shared_pool": aggregate_basis == "shared_team_pool",
        "degraded": len(successful) != len(rows),
        "refresh_at_mixed": len(refresh_values) > 1,
    }
