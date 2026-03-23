from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from app.domain.models import OneminAccount, OneminAllocationLease, OneminCredential, OneminRunwayForecast
from app.repositories.onemin_manager import OneminManagerRepository

_ACTIVE_ONEMIN_MANAGER: OneminManagerService | None = None
_ACTIVE_ONEMIN_MANAGER_LOCK = threading.Lock()


def register_onemin_manager(manager: OneminManagerService | None) -> None:
    global _ACTIVE_ONEMIN_MANAGER
    with _ACTIVE_ONEMIN_MANAGER_LOCK:
        _ACTIVE_ONEMIN_MANAGER = manager


def active_onemin_manager() -> OneminManagerService | None:
    with _ACTIVE_ONEMIN_MANAGER_LOCK:
        return _ACTIVE_ONEMIN_MANAGER


class OneminManagerService:
    def __init__(self, *, repo: OneminManagerRepository) -> None:
        self._repo = repo
        self._lock = threading.Lock()

    def _env_float(self, name: str, default: float) -> float:
        raw = str(os.environ.get(name) or "").strip()
        try:
            return float(raw) if raw else default
        except Exception:
            return default

    def _env_int(self, name: str, default: int) -> int:
        raw = str(os.environ.get(name) or "").strip()
        try:
            return int(float(raw)) if raw else default
        except Exception:
            return default

    def _lease_ttl_seconds(self) -> int:
        return max(30, self._env_int("EA_ONEMIN_LEASE_TTL_SECONDS", 300))

    def _core_floor_ratio(self) -> float:
        return min(0.95, max(0.0, self._env_float("EA_ONEMIN_CORE_FLOOR_RATIO", 0.50)))

    def _reserve_ratio(self) -> float:
        return min(0.95, max(0.0, self._env_float("EA_ONEMIN_RESERVE_RATIO", 0.20)))

    def _image_ratio(self) -> float:
        default = max(0.0, 1.0 - self._core_floor_ratio() - self._reserve_ratio())
        return min(0.95, max(0.0, self._env_float("EA_ONEMIN_IMAGE_SPENDABLE_RATIO", default)))

    def _max_inflight_core_per_account(self) -> int:
        return max(1, self._env_int("EA_ONEMIN_MAX_INFLIGHT_CORE_PER_ACCOUNT", 1))

    def _max_inflight_image_per_account(self) -> int:
        return max(1, self._env_int("EA_ONEMIN_MAX_INFLIGHT_IMAGE_PER_ACCOUNT", 1))

    def _max_inflight_total_per_account(self) -> int:
        return max(1, self._env_int("EA_ONEMIN_MAX_INFLIGHT_TOTAL_PER_ACCOUNT", 2))

    def _role_overrides(self) -> dict[str, str]:
        raw = str(os.environ.get("EA_ONEMIN_ROLE_TAGS_JSON") or "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, str] = {}
        for key, value in payload.items():
            normalized_key = str(key or "").strip()
            normalized_value = str(value or "").strip().lower()
            if normalized_key and normalized_value:
                result[normalized_key] = normalized_value
        return result

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat().replace("+00:00", "Z")

    def _epoch_to_iso(self, value: object) -> str | None:
        try:
            numeric = float(value or 0.0)
        except Exception:
            return None
        if numeric <= 0:
            return None
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _parse_float(self, value: object) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except Exception:
            return None

    def _parse_iso(self, value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        candidate = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _binding_account_labels(self, binding: object) -> tuple[str, ...]:
        metadata = dict(getattr(binding, "auth_metadata_json", {}) or {})
        labels: list[str] = []
        for key in ("onemin_account_name", "onemin_account_names", "account_name", "account_names", "slot_env_name", "slot_env_names"):
            raw = metadata.get(key)
            values = [raw] if isinstance(raw, str) else list(raw or []) if isinstance(raw, (list, tuple, set)) else []
            for value in values:
                normalized = str(value or "").strip()
                if normalized and normalized not in labels:
                    labels.append(normalized)
        external_account_ref = str(getattr(binding, "external_account_ref", "") or "").strip()
        if external_account_ref and external_account_ref not in labels:
            labels.append(external_account_ref)
        return tuple(labels)

    def _binding_map(self, binding_rows: list[object] | None) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for binding in binding_rows or []:
            binding_id = str(getattr(binding, "binding_id", "") or "").strip()
            if not binding_id:
                continue
            for label in self._binding_account_labels(binding):
                result.setdefault(label, [])
                if binding_id not in result[label]:
                    result[label].append(binding_id)
        return result

    def _task_class(self, *, lane: str, capability: str) -> str:
        normalized_lane = str(lane or "").strip().lower()
        normalized_capability = str(capability or "").strip().lower()
        if normalized_capability == "image_generate":
            return "image_generation"
        if normalized_capability == "media_transform":
            return "media_transform"
        if normalized_capability == "reasoned_patch_review" or normalized_lane in {"review", "audit", "review_light"}:
            return "core_review"
        return "core_code"

    def _slot_role(self, candidate: dict[str, object]) -> str:
        overrides = self._role_overrides()
        for key in (
            str(candidate.get("account_name") or "").strip(),
            str(candidate.get("secret_env_name") or "").strip(),
            str(candidate.get("slot_name") or "").strip(),
            str(candidate.get("credential_id") or "").strip(),
        ):
            override = str(overrides.get(key) or "").strip().lower()
            if override:
                return override
        slot_role = str(candidate.get("slot_role") or candidate.get("active_role") or "").strip().lower()
        if slot_role in {"core", "image", "mixed", "reserve"}:
            return slot_role
        return "mixed"

    def _candidate_remaining_credits(self, candidate: dict[str, object]) -> float:
        for key in ("billing_remaining_credits", "estimated_remaining_credits", "remaining_credits"):
            parsed = self._parse_float(candidate.get(key))
            if parsed is not None:
                return max(0.0, parsed)
        return 0.0

    def _slot_has_actual_billing(self, slot: dict[str, object]) -> bool:
        if slot.get("billing_remaining_credits") not in (None, ""):
            return True
        if slot.get("billing_max_credits") not in (None, ""):
            return True
        basis = str(slot.get("billing_basis") or "").strip().lower()
        if basis.startswith("actual_"):
            return True
        if str(slot.get("last_billing_snapshot_at") or "").strip():
            return True
        return False

    def _slot_credit_basis(self, slot: dict[str, object]) -> str:
        billing_basis = str(slot.get("billing_basis") or "").strip()
        if billing_basis:
            return billing_basis
        if self._slot_has_actual_billing(slot):
            return "actual_billing_snapshot"
        for key in ("estimated_credit_basis", "last_balance_source"):
            value = str(slot.get(key) or "").strip()
            if value:
                return value
        if slot.get("estimated_remaining_credits") not in (None, ""):
            return "estimated"
        return "unknown"

    def _account_credit_rollup(self, slots: list[dict[str, object]]) -> dict[str, object]:
        has_actual_billing = False
        actual_remaining = 0.0
        actual_max = 0.0
        estimated_remaining = 0.0
        estimated_seen = False
        actual_basis = ""
        estimated_basis = ""
        for slot in slots:
            if self._slot_has_actual_billing(slot):
                has_actual_billing = True
                if not actual_basis:
                    actual_basis = self._slot_credit_basis(slot)
                remaining_value = self._parse_float(slot.get("billing_remaining_credits"))
                if remaining_value is not None:
                    actual_remaining += max(0.0, remaining_value)
                max_value = self._parse_float(slot.get("billing_max_credits"))
                if max_value is not None:
                    actual_max += max(0.0, max_value)
            estimated_value = self._parse_float(slot.get("estimated_remaining_credits"))
            if estimated_value is not None:
                estimated_seen = True
                estimated_remaining += max(0.0, estimated_value)
                if not estimated_basis:
                    estimated_basis = str(slot.get("estimated_credit_basis") or slot.get("last_balance_source") or "estimated").strip()
        credit_basis = actual_basis if has_actual_billing else estimated_basis or "unknown"
        return {
            "has_actual_billing": has_actual_billing,
            "actual_remaining_credits": actual_remaining if has_actual_billing else None,
            "actual_max_credits": actual_max if has_actual_billing and actual_max > 0 else None,
            "estimated_remaining_credits": estimated_remaining if estimated_seen else None,
            "credit_basis": credit_basis,
        }

    def _account_burn_rollup(self, slots: list[dict[str, object]]) -> dict[str, object]:
        observed_usage_burn = 0.0
        observed_usage_slot_count = 0
        estimated_pool_burn: float | None = None
        for slot in slots:
            observed = self._parse_float(slot.get("billing_observed_usage_burn_credits_per_hour"))
            if observed is not None:
                observed_usage_burn += max(0.0, observed)
                observed_usage_slot_count += 1
            estimated = self._parse_float(slot.get("burn_credits_per_hour"))
            if estimated is not None and estimated_pool_burn is None:
                estimated_pool_burn = max(0.0, estimated)
        current_burn = observed_usage_burn if observed_usage_slot_count > 0 else estimated_pool_burn
        burn_basis = "observed_usage" if observed_usage_slot_count > 0 else "estimated_pool" if estimated_pool_burn is not None else "unknown"
        return {
            "observed_usage_burn_credits_per_hour": round(observed_usage_burn, 2) if observed_usage_slot_count > 0 else None,
            "slot_count_with_observed_usage_burn": observed_usage_slot_count,
            "estimated_pool_burn_credits_per_hour": round(estimated_pool_burn, 2) if estimated_pool_burn is not None else None,
            "current_burn_credits_per_hour": round(current_burn, 2) if current_burn is not None else None,
            "burn_basis": burn_basis,
        }

    def _floor_credits(self, remaining_credits: float) -> tuple[float, float, float]:
        core_floor = remaining_credits * self._core_floor_ratio()
        reserve = remaining_credits * self._reserve_ratio()
        image_spendable = max(0.0, remaining_credits * self._image_ratio())
        return core_floor, image_spendable, reserve

    def _active_leases(self) -> list[OneminAllocationLease]:
        now = self._now()
        rows: list[OneminAllocationLease] = []
        for lease in self._repo.list_leases(limit=5000, statuses=("reserved", "in_flight")):
            expires_at = self._parse_iso(lease.expires_at)
            if expires_at is not None and expires_at <= now:
                self._repo.upsert_lease(replace(lease, status="expired", finished_at=self._now_iso(), error=lease.error or "lease_expired"))
                continue
            rows.append(lease)
        return rows

    def _active_leases_for_account(self, account_id: str) -> list[OneminAllocationLease]:
        normalized = str(account_id or "").strip()
        return [lease for lease in self._active_leases() if lease.account_id == normalized]

    def _candidate_allowed(
        self,
        *,
        candidate: dict[str, object],
        task_class: str,
        estimated_credits: int | None,
        allow_reserve: bool,
    ) -> tuple[bool, str]:
        state = str(candidate.get("state") or "").strip().lower()
        if state not in {"ready", "unknown", "degraded"}:
            return False, "state_blocked"
        role = self._slot_role(candidate)
        if role == "reserve" and not allow_reserve:
            return False, "reserve_blocked"
        account_id = str(candidate.get("account_name") or candidate.get("account_id") or "").strip()
        leases = self._active_leases_for_account(account_id)
        total_inflight = len(leases)
        same_task_inflight = sum(1 for lease in leases if str((lease.metadata_json or {}).get("task_class") or "").strip() == task_class)
        core_inflight = any(str((lease.metadata_json or {}).get("task_class") or "").strip() in {"core_code", "core_review"} for lease in leases)
        image_inflight = any(str((lease.metadata_json or {}).get("task_class") or "").strip() in {"image_generation", "media_transform"} for lease in leases)
        if total_inflight >= self._max_inflight_total_per_account():
            return False, "account_concurrency_cap"
        if task_class in {"core_code", "core_review"}:
            if same_task_inflight >= self._max_inflight_core_per_account():
                return False, "core_concurrency_cap"
            if image_inflight:
                return False, "image_account_in_use"
        if task_class in {"image_generation", "media_transform"}:
            if same_task_inflight >= self._max_inflight_image_per_account():
                return False, "image_concurrency_cap"
            if core_inflight:
                return False, "core_account_in_use"
        remaining_credits = self._candidate_remaining_credits(candidate)
        _core_floor, _image_spendable, reserve_credits = self._floor_credits(remaining_credits)
        required = max(0, int(estimated_credits or 0))
        available = max(0.0, remaining_credits - reserve_credits)
        if required > 0 and available < required:
            return False, "insufficient_budget"
        return True, "eligible"

    def _candidate_score(
        self,
        *,
        candidate: dict[str, object],
        task_class: str,
        estimated_credits: int | None,
    ) -> float:
        remaining_credits = self._candidate_remaining_credits(candidate)
        core_floor, image_spendable, reserve_credits = self._floor_credits(remaining_credits)
        account_id = str(candidate.get("account_name") or candidate.get("account_id") or "").strip()
        leases = self._active_leases_for_account(account_id)
        role = self._slot_role(candidate)
        score = max(0.0, remaining_credits - reserve_credits)
        if task_class in {"core_code", "core_review"}:
            score += max(0.0, remaining_credits - core_floor)
        if task_class in {"image_generation", "media_transform"}:
            score += image_spendable
        score -= len(leases) * 5000.0
        score -= float(candidate.get("failure_count") or 0) * 2500.0
        last_success = self._parse_float(candidate.get("last_success_at")) or 0.0
        last_used = self._parse_float(candidate.get("last_used_at")) or 0.0
        score += min(last_success / 1000.0, 2500.0)
        score -= min(last_used / 1000.0, 2000.0)
        if task_class in {"core_code", "core_review"} and role == "core":
            score += 15000.0
        if task_class in {"image_generation", "media_transform"} and role == "image":
            score += 15000.0
        if role == "mixed":
            score += 5000.0
        if role == "reserve":
            score -= 15000.0
        next_topup = self._parse_iso(candidate.get("billing_next_topup_at"))
        if next_topup is not None and task_class in {"image_generation", "media_transform"}:
            hours_until_topup = max(0.0, (next_topup - self._now()).total_seconds() / 3600.0)
            score += max(0.0, 1000.0 - hours_until_topup * 10.0)
        if estimated_credits:
            score -= float(max(0, int(estimated_credits))) * 0.05
        return score

    def _state_from_provider_health(
        self,
        *,
        provider_health: dict[str, object],
        binding_rows: list[object] | None = None,
    ) -> tuple[list[OneminAccount], list[OneminCredential]]:
        _ = binding_rows
        onemin = dict(((provider_health.get("providers") or {}).get("onemin") or {}))
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in onemin.get("slots") or []:
            if not isinstance(row, dict):
                continue
            account_name = str(row.get("account_name") or row.get("slot_env_name") or row.get("slot") or "").strip()
            if not account_name:
                continue
            grouped.setdefault(account_name, []).append(dict(row))
        leases = self._active_leases()
        leases_by_account: dict[str, list[OneminAllocationLease]] = {}
        for lease in leases:
            leases_by_account.setdefault(lease.account_id, []).append(lease)
        accounts: list[OneminAccount] = []
        credentials: list[OneminCredential] = []
        for account_name, slots in grouped.items():
            owner_email = next((str(slot.get("owner_email") or "").strip() for slot in slots if str(slot.get("owner_email") or "").strip()), "")
            owner_name = next((str(slot.get("owner_name") or "").strip() for slot in slots if str(slot.get("owner_name") or "").strip()), "")
            last_billing_snapshot_at = max((str(slot.get("last_billing_snapshot_at") or "").strip() for slot in slots if str(slot.get("last_billing_snapshot_at") or "").strip()), default=None)
            last_member_reconciliation_at = max((str(slot.get("member_reconciliation_at") or "").strip() for slot in slots if str(slot.get("member_reconciliation_at") or "").strip()), default=None)
            credit_rollup = self._account_credit_rollup(slots)
            burn_rollup = self._account_burn_rollup(slots)
            billing_remaining = self._parse_float(credit_rollup.get("actual_remaining_credits"))
            estimated_remaining = self._parse_float(credit_rollup.get("estimated_remaining_credits")) or 0.0
            remaining_credits = billing_remaining if billing_remaining is not None else estimated_remaining
            max_credits = sum((self._parse_float(slot.get("billing_max_credits")) or self._parse_float(slot.get("max_credits")) or 0.0) for slot in slots)
            core_floor, image_spendable, reserve_credits = self._floor_credits(remaining_credits)
            states = {str(slot.get("state") or "").strip().lower() for slot in slots}
            status = "ready" if "ready" in states else "unknown" if "unknown" in states else sorted(states)[0] if states else "unknown"
            account_leases = leases_by_account.get(account_name, [])
            account = OneminAccount(
                account_id=account_name,
                account_label=account_name,
                owner_email=owner_email,
                owner_name=owner_name,
                browseract_binding_id="",
                status=status,
                remaining_credits=remaining_credits,
                max_credits=max_credits or None,
                core_floor_credits=core_floor,
                image_spendable_credits=image_spendable,
                reserve_credits=reserve_credits,
                slot_count=len(slots),
                ready_slot_count=sum(1 for slot in slots if str(slot.get("state") or "").strip().lower() == "ready"),
                last_billing_snapshot_at=last_billing_snapshot_at,
                last_member_reconciliation_at=last_member_reconciliation_at,
                details_json={
                    "credit_basis": str(credit_rollup.get("credit_basis") or "unknown"),
                    "has_actual_billing": bool(credit_rollup.get("has_actual_billing")),
                    "actual_remaining_credits": billing_remaining,
                    "actual_max_credits": self._parse_float(credit_rollup.get("actual_max_credits")),
                    "estimated_remaining_credits": estimated_remaining if estimated_remaining > 0 else 0.0,
                    "observed_usage_burn_credits_per_hour": self._parse_float(burn_rollup.get("observed_usage_burn_credits_per_hour")),
                    "slot_count_with_observed_usage_burn": int(burn_rollup.get("slot_count_with_observed_usage_burn") or 0),
                    "estimated_pool_burn_credits_per_hour": self._parse_float(burn_rollup.get("estimated_pool_burn_credits_per_hour")),
                    "current_burn_credits_per_hour": self._parse_float(burn_rollup.get("current_burn_credits_per_hour")),
                    "burn_basis": str(burn_rollup.get("burn_basis") or "unknown"),
                    "active_lease_count": len(account_leases),
                    "active_lease_task_classes": sorted(
                        {
                            str((lease.metadata_json or {}).get("task_class") or "").strip()
                            for lease in account_leases
                            if str((lease.metadata_json or {}).get("task_class") or "").strip()
                        }
                    ),
                },
            )
            accounts.append(account)
            for slot in slots:
                slot_name = str(slot.get("slot") or slot.get("slot_name") or account_name).strip()
                credential = OneminCredential(
                    credential_id=slot_name or account_name,
                    account_id=account_name,
                    slot_name=slot_name or account_name,
                    secret_env_name=str(slot.get("slot_env_name") or account_name),
                    owner_email=owner_email,
                    active_role=self._slot_role(slot),
                    state=str(slot.get("state") or "unknown"),
                    remaining_credits=self._parse_float(slot.get("billing_remaining_credits") or slot.get("estimated_remaining_credits")),
                    max_credits=self._parse_float(slot.get("billing_max_credits") or slot.get("max_credits")),
                    last_probe_at=self._epoch_to_iso(slot.get("last_probe_at")),
                    last_success_at=self._epoch_to_iso(slot.get("last_success_at")),
                    last_error=str(slot.get("last_error") or ""),
                    quarantine_until=self._epoch_to_iso(slot.get("quarantine_until")),
                    details_json=dict(slot),
                )
                credentials.append(credential)
        return accounts, credentials

    def _sync_state(self, *, provider_health: dict[str, object], binding_rows: list[object] | None = None) -> None:
        accounts, credentials = self._state_from_provider_health(provider_health=provider_health, binding_rows=binding_rows)
        self._repo.replace_state(accounts=accounts, credentials=credentials)

    def reserve_for_candidates(
        self,
        *,
        candidates: list[dict[str, object]],
        lane: str,
        capability: str,
        principal_id: str,
        request_id: str,
        estimated_credits: int | None,
        allow_reserve: bool,
    ) -> dict[str, object] | None:
        task_class = self._task_class(lane=lane, capability=capability)
        with self._lock:
            eligible: list[tuple[float, dict[str, object]]] = []
            for candidate in candidates:
                allowed, _ = self._candidate_allowed(candidate=candidate, task_class=task_class, estimated_credits=estimated_credits, allow_reserve=allow_reserve)
                if not allowed:
                    continue
                eligible.append((self._candidate_score(candidate=candidate, task_class=task_class, estimated_credits=estimated_credits), dict(candidate)))
            if not eligible:
                return None
            eligible.sort(key=lambda item: (-item[0], str(item[1].get("account_name") or ""), str(item[1].get("slot_name") or "")))
            chosen = eligible[0][1]
            account_id = str(chosen.get("account_name") or chosen.get("account_id") or "").strip()
            credential_id = str(chosen.get("credential_id") or chosen.get("slot_name") or account_id).strip()
            now = self._now()
            lease_id = "lease_" + uuid.uuid4().hex[:24]
            lease = OneminAllocationLease(
                lease_id=lease_id,
                request_id=request_id,
                principal_id=str(principal_id or "").strip(),
                lane=lane,
                capability=capability,
                account_id=account_id,
                credential_id=credential_id,
                estimated_credits=estimated_credits,
                status="in_flight",
                created_at=now.isoformat().replace("+00:00", "Z"),
                expires_at=(now + timedelta(seconds=self._lease_ttl_seconds())).isoformat().replace("+00:00", "Z"),
                metadata_json={
                    "task_class": task_class,
                    "slot_name": str(chosen.get("slot_name") or ""),
                    "slot_role": self._slot_role(chosen),
                    "secret_env_name": str(chosen.get("secret_env_name") or ""),
                    "account_name": account_id,
                },
            )
            self._repo.upsert_lease(lease)
            return {
                "lease_id": lease_id,
                "api_key": str(chosen.get("api_key") or ""),
                "account_name": account_id,
                "slot_name": str(chosen.get("slot_name") or ""),
                "credential_id": credential_id,
                "task_class": task_class,
            }

    def record_usage(self, *, lease_id: str, actual_credits_delta: int | None, status: str = "success") -> None:
        lease = self._repo.get_lease(lease_id)
        if lease is None:
            return
        self._repo.upsert_lease(replace(lease, actual_credits_delta=actual_credits_delta, status=status or lease.status))

    def release_lease(self, *, lease_id: str, status: str = "released", error: str = "") -> None:
        lease = self._repo.get_lease(lease_id)
        if lease is None:
            return
        self._repo.upsert_lease(replace(lease, status=status, finished_at=self._now_iso(), error=str(error or "").strip()))

    def _public_lease_metadata(self, lease: OneminAllocationLease) -> dict[str, object]:
        metadata = dict(lease.metadata_json or {})
        result: dict[str, object] = {}
        for key in ("task_class", "slot_name", "slot_role", "secret_env_name", "account_name"):
            value = metadata.get(key)
            normalized = str(value or "").strip()
            if normalized:
                result[key] = normalized
        return result

    def _leases_snapshot_rows(self, *, principal_id: str = "") -> list[OneminAllocationLease]:
        active_by_id = {lease.lease_id: lease for lease in self._active_leases()}
        normalized_principal = str(principal_id or "").strip()
        rows: list[OneminAllocationLease] = []
        for lease in self._repo.list_leases(limit=5000):
            current = active_by_id.get(lease.lease_id) or lease
            if normalized_principal and current.principal_id != normalized_principal:
                continue
            rows.append(current)
        return rows

    def leases_snapshot(self, *, principal_id: str = "") -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for lease in self._leases_snapshot_rows(principal_id=principal_id):
            rows.append(
                {
                    "lease_id": lease.lease_id,
                    "lane": lease.lane,
                    "capability": lease.capability,
                    "account_id": lease.account_id,
                    "credential_id": lease.credential_id,
                    "estimated_credits": lease.estimated_credits,
                    "actual_credits_delta": lease.actual_credits_delta,
                    "status": lease.status,
                    "created_at": lease.created_at,
                    "expires_at": lease.expires_at,
                    "finished_at": lease.finished_at,
                    "metadata_json": self._public_lease_metadata(lease),
                }
            )
        return rows

    def occupancy_snapshot(self, *, principal_id: str = "") -> dict[str, object]:
        normalized_principal = str(principal_id or "").strip()
        active = [
            lease
            for lease in self._active_leases()
            if lease.status in {"reserved", "in_flight"}
            and (not normalized_principal or lease.principal_id == normalized_principal)
        ]
        occupied_account_ids: set[str] = set()
        occupied_secret_env_names: set[str] = set()
        for lease in active:
            metadata = dict(lease.metadata_json or {})
            account_id = str(lease.account_id or metadata.get("account_name") or "").strip()
            if account_id:
                occupied_account_ids.add(account_id)
            secret_env_name = str(metadata.get("secret_env_name") or "").strip()
            if secret_env_name:
                occupied_secret_env_names.add(secret_env_name)
        return {
            "active_lease_count": len(active),
            "occupied_account_ids": sorted(occupied_account_ids),
            "occupied_secret_env_names": sorted(occupied_secret_env_names),
        }

    def accounts_snapshot(
        self,
        *,
        provider_health: dict[str, object],
        binding_rows: list[object] | None = None,
    ) -> list[dict[str, object]]:
        self._sync_state(provider_health=provider_health)
        binding_map = self._binding_map(binding_rows)
        credentials_by_account: dict[str, list[OneminCredential]] = {}
        for credential in self._repo.list_credentials():
            credentials_by_account.setdefault(credential.account_id, []).append(credential)
        leases_by_account: dict[str, list[OneminAllocationLease]] = {}
        for lease in self._active_leases():
            leases_by_account.setdefault(lease.account_id, []).append(lease)
        rows: list[dict[str, object]] = []
        for account in self._repo.list_accounts():
            account_credentials = credentials_by_account.get(account.account_id, [])
            account_leases = leases_by_account.get(account.account_id, [])
            details_json = dict(account.details_json or {})
            binding_ids = list(binding_map.get(account.account_id, binding_map.get(account.account_label, [])))
            rows.append(
                {
                    **asdict(account),
                    "browseract_binding_id": binding_ids[0] if binding_ids else "",
                    "browseract_binding_ids": binding_ids,
                    "credit_basis": str(details_json.get("credit_basis") or "unknown"),
                    "has_actual_billing": bool(details_json.get("has_actual_billing")),
                    "actual_remaining_credits": self._parse_float(details_json.get("actual_remaining_credits")),
                    "actual_max_credits": self._parse_float(details_json.get("actual_max_credits")),
                    "estimated_remaining_credits": self._parse_float(details_json.get("estimated_remaining_credits")),
                    "observed_usage_burn_credits_per_hour": self._parse_float(details_json.get("observed_usage_burn_credits_per_hour")),
                    "slot_count_with_observed_usage_burn": int(details_json.get("slot_count_with_observed_usage_burn") or 0),
                    "estimated_pool_burn_credits_per_hour": self._parse_float(details_json.get("estimated_pool_burn_credits_per_hour")),
                    "current_burn_credits_per_hour": self._parse_float(details_json.get("current_burn_credits_per_hour")),
                    "burn_basis": str(details_json.get("burn_basis") or "unknown"),
                    "active_lease_count": len(account_leases),
                    "active_lease_task_classes": sorted(
                        {
                            str((lease.metadata_json or {}).get("task_class") or "").strip()
                            for lease in account_leases
                            if str((lease.metadata_json or {}).get("task_class") or "").strip()
                        }
                    ),
                    "credentials": [asdict(item) for item in sorted(account_credentials, key=lambda row: (row.slot_name, row.credential_id))],
                }
            )
        return rows

    def aggregate_snapshot(
        self,
        *,
        provider_health: dict[str, object],
        binding_rows: list[object] | None = None,
        principal_id: str = "",
    ) -> dict[str, object]:
        accounts = self.accounts_snapshot(provider_health=provider_health, binding_rows=binding_rows)
        onemin = dict(((provider_health.get("providers") or {}).get("onemin") or {}))
        remaining_total = sum(float(item.get("remaining_credits") or 0.0) for item in accounts)
        max_total = sum(float(item.get("max_credits") or 0.0) for item in accounts)
        core_floor_total = sum(float(item.get("core_floor_credits") or 0.0) for item in accounts)
        image_spendable_total = sum(float(item.get("image_spendable_credits") or 0.0) for item in accounts)
        reserve_total = sum(float(item.get("reserve_credits") or 0.0) for item in accounts)
        ready_accounts = sum(1 for item in accounts if str(item.get("status") or "") == "ready")
        actual_accounts = [item for item in accounts if bool(item.get("has_actual_billing"))]
        estimated_accounts = [item for item in accounts if not bool(item.get("has_actual_billing"))]
        bound_accounts = [item for item in accounts if list(item.get("browseract_binding_ids") or [])]
        bound_actual_accounts = [item for item in bound_accounts if bool(item.get("has_actual_billing"))]
        actual_free_total = sum(float(item.get("actual_remaining_credits") or 0.0) for item in actual_accounts)
        estimated_free_total = sum(float(item.get("estimated_remaining_credits") or item.get("remaining_credits") or 0.0) for item in estimated_accounts)
        bound_actual_free_total = sum(float(item.get("actual_remaining_credits") or 0.0) for item in bound_actual_accounts)
        bound_estimated_free_total = sum(
            float(item.get("estimated_remaining_credits") or item.get("remaining_credits") or 0.0)
            for item in bound_accounts
            if not bool(item.get("has_actual_billing"))
        )
        observed_usage_burn_total = sum(float(item.get("observed_usage_burn_credits_per_hour") or 0.0) for item in accounts)
        observed_usage_burn_account_count = sum(1 for item in accounts if item.get("observed_usage_burn_credits_per_hour") not in (None, ""))
        estimated_pool_burn = self._parse_float(onemin.get("estimated_burn_credits_per_hour"))
        current_burn = round(observed_usage_burn_total, 2) if observed_usage_burn_account_count > 0 else estimated_pool_burn
        burn_basis = "observed_usage" if observed_usage_burn_account_count > 0 else "estimated_pool" if estimated_pool_burn is not None else "unknown"
        bound_observed_usage_burn_total = sum(float(item.get("observed_usage_burn_credits_per_hour") or 0.0) for item in bound_accounts)
        bound_observed_usage_burn_account_count = sum(
            1 for item in bound_accounts if item.get("observed_usage_burn_credits_per_hour") not in (None, "")
        )
        active_leases = [lease for lease in self.leases_snapshot() if str(lease.get("status") or "") in {"reserved", "in_flight"}]
        return {
            "provider_key": "onemin",
            "principal_id": principal_id,
            "account_count": len(accounts),
            "ready_account_count": ready_accounts,
            "slot_count": int(onemin.get("configured_slots") or sum(int(item.get("slot_count") or 0) for item in accounts)),
            "sum_free_credits": remaining_total,
            "sum_max_credits": max_total or None,
            "actual_free_credits_total": actual_free_total,
            "estimated_free_credits_total": estimated_free_total,
            "core_floor_credits_total": core_floor_total,
            "image_spendable_credits_total": image_spendable_total,
            "reserve_credits_total": reserve_total,
            "observed_usage_burn_credits_per_hour": round(observed_usage_burn_total, 2) if observed_usage_burn_account_count > 0 else None,
            "observed_usage_burn_account_count": observed_usage_burn_account_count,
            "estimated_pool_burn_credits_per_hour": estimated_pool_burn,
            "current_burn_credits_per_hour": current_burn,
            "burn_basis": burn_basis,
            "current_pace_burn_credits_per_hour": onemin.get("estimated_burn_credits_per_hour"),
            "hours_remaining_at_current_pace": onemin.get("estimated_hours_remaining_at_current_pace"),
            "days_remaining_at_7d_average": onemin.get("estimated_days_remaining_at_7d_average"),
            "active_lease_count": len(active_leases),
            "actual_billing_account_count": len(actual_accounts),
            "estimated_account_count": len(estimated_accounts),
            "bound_account_count": len(bound_accounts),
            "bound_actual_billing_account_count": len(bound_actual_accounts),
            "bound_actual_free_credits_total": bound_actual_free_total,
            "bound_estimated_free_credits_total": bound_estimated_free_total,
            "bound_observed_usage_burn_credits_per_hour": round(bound_observed_usage_burn_total, 2)
            if bound_observed_usage_burn_account_count > 0
            else None,
            "bound_observed_usage_burn_account_count": bound_observed_usage_burn_account_count,
            "member_reconciled_account_count": sum(1 for item in accounts if item.get("last_member_reconciliation_at")),
            "accounts": accounts,
        }

    def actual_credits_snapshot(
        self,
        *,
        provider_health: dict[str, object],
        binding_rows: list[object] | None = None,
        principal_id: str = "",
    ) -> dict[str, object]:
        accounts = self.accounts_snapshot(provider_health=provider_health, binding_rows=binding_rows)
        bound_accounts = [item for item in accounts if list(item.get("browseract_binding_ids") or [])]
        actual_accounts = [item for item in bound_accounts if bool(item.get("has_actual_billing"))]
        observed_usage_burn_total = sum(float(item.get("observed_usage_burn_credits_per_hour") or 0.0) for item in actual_accounts)
        observed_usage_burn_account_count = sum(
            1 for item in actual_accounts if item.get("observed_usage_burn_credits_per_hour") not in (None, "")
        )
        estimated_pool_burn = self._parse_float(dict(((provider_health.get("providers") or {}).get("onemin") or {})).get("estimated_burn_credits_per_hour"))
        return {
            "provider_key": "onemin",
            "principal_id": principal_id,
            "binding_account_count": len(bound_accounts),
            "actual_billing_account_count": len(actual_accounts),
            "actual_free_credits_total": sum(float(item.get("actual_remaining_credits") or 0.0) for item in actual_accounts),
            "actual_max_credits_total": sum(float(item.get("actual_max_credits") or item.get("max_credits") or 0.0) for item in actual_accounts),
            "observed_usage_burn_credits_per_hour": round(observed_usage_burn_total, 2) if observed_usage_burn_account_count > 0 else None,
            "observed_usage_burn_account_count": observed_usage_burn_account_count,
            "current_burn_credits_per_hour": round(observed_usage_burn_total, 2) if observed_usage_burn_account_count > 0 else None,
            "burn_basis": "observed_usage" if observed_usage_burn_account_count > 0 else "unknown",
            "global_estimated_pool_burn_credits_per_hour": estimated_pool_burn,
            "accounts_without_actual_billing_count": sum(1 for item in bound_accounts if not bool(item.get("has_actual_billing"))),
            "accounts": [
                {
                    "account_id": str(item.get("account_id") or ""),
                    "owner_email": str(item.get("owner_email") or ""),
                    "status": str(item.get("status") or ""),
                    "remaining_credits": self._parse_float(item.get("actual_remaining_credits")),
                    "max_credits": self._parse_float(item.get("actual_max_credits") or item.get("max_credits")),
                    "credit_basis": str(item.get("credit_basis") or "unknown"),
                    "observed_usage_burn_credits_per_hour": self._parse_float(item.get("observed_usage_burn_credits_per_hour")),
                    "current_burn_credits_per_hour": self._parse_float(item.get("current_burn_credits_per_hour")),
                    "burn_basis": str(item.get("burn_basis") or "unknown"),
                    "last_billing_snapshot_at": item.get("last_billing_snapshot_at"),
                    "last_member_reconciliation_at": item.get("last_member_reconciliation_at"),
                    "browseract_binding_ids": list(item.get("browseract_binding_ids") or []),
                }
                for item in actual_accounts
            ],
            "note": "no_enabled_browseract_bindings"
            if not bound_accounts
            else "no_actual_billing_snapshots"
            if not actual_accounts
            else "",
        }

    def runway_snapshot(
        self,
        *,
        provider_health: dict[str, object],
        binding_rows: list[object] | None = None,
    ) -> dict[str, object]:
        aggregate = self.aggregate_snapshot(provider_health=provider_health, binding_rows=binding_rows)
        onemin = dict(((provider_health.get("providers") or {}).get("onemin") or {}))
        return asdict(
            OneminRunwayForecast(
                remaining_credits=float(aggregate.get("sum_free_credits") or 0.0),
                core_floor_credits=float(aggregate.get("core_floor_credits_total") or 0.0),
                image_spendable_credits=float(aggregate.get("image_spendable_credits_total") or 0.0),
                reserve_credits=float(aggregate.get("reserve_credits_total") or 0.0),
                current_burn_per_hour=self._parse_float(aggregate.get("current_pace_burn_credits_per_hour")),
                hours_remaining_current_pace=self._parse_float(aggregate.get("hours_remaining_at_current_pace")),
                days_remaining_7d_avg=self._parse_float(aggregate.get("days_remaining_at_7d_average")),
                next_topup_at=str(onemin.get("billing_next_topup_at") or "") or None,
                topup_amount=self._parse_float(onemin.get("billing_topup_amount")),
            )
        )
