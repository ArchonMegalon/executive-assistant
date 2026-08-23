from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from app.services.provider_accounts import ProviderAccountSlot
from app.services.tough_tongue import MAX_RESPONSE_BYTES, ToughTongueConfig


CONTRACT_SCHEMA = "chummer.build_ghost.tough_tongue.read_only_binding_contract.v2"
RECEIPT_SCHEMA = "ea.tough_tongue.live_ops_binding_receipt.v2"
OFFICIAL_BASE_URL = "https://api.toughtongueai.com/api/public"
EXPECTED_SLOT_COUNT = 6
PREFLIGHT_STATES = {"ready", "disabled", "unavailable", "depleted", "malformed"}
DOCUMENTED_GET_ROUTES = {
    "balance": "balance",
    "subscriptions": "subscriptions",
    "organizations": "v2/organizations",
    "scenario": "scenarios/{resource_ref}",
}
NORMALIZATION = {
    "plan": "subscriptions.active.product_name",
    "remaining_minutes": "balance.available_minutes",
    "refresh_at": "balance.last_updated",
    "organization": "organizations.id",
    "resource_ownership": "organization_scoped_scenario_readback",
}
UNSUPPORTED_DIRECT_RESOURCES = ("agent", "voice", "function", "avatar")
_SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_POLICY_VALUE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: object) -> str:
    raw = value if isinstance(value, bytes) else str(value or "").strip().encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}" if raw else ""


def contract_digest(payload: Mapping[str, object]) -> str:
    return _digest(_canonical(payload))


def _iso(value: object) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("tough_tongue_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("tough_tongue_timestamp_invalid")
    return parsed.astimezone(UTC)


def _provider_iso(value: object) -> datetime:
    """Parse a provider timestamp, treating its documented naive ISO form as UTC."""

    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("tough_tongue_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _now_text(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ToughTongueProbeAuthority:
    """Local ledger state which is checked before any provider request."""

    state: str
    observed_at: str
    evidence_digest: str


@dataclass(frozen=True)
class ToughTongueLiveOpsContract:
    base_url: str
    source_ref_sha256: str
    verified_at: str
    maximum_snapshot_age_seconds: int
    premium_plan_values: tuple[str, ...]
    live_avatar_providers: tuple[str, ...]
    digest: str

    @classmethod
    def from_env(cls, *, configured_base_url: str) -> "ToughTongueLiveOpsContract":
        path_text = str(os.environ.get("EA_TOUGH_TONGUE_READ_ONLY_BINDING_CONTRACT_PATH") or "").strip()
        expected_digest = str(os.environ.get("EA_TOUGH_TONGUE_READ_ONLY_BINDING_CONTRACT_DIGEST") or "").strip()
        if not path_text:
            raise ValueError("tough_tongue_contract_unavailable")
        path = Path(path_text)
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ValueError("tough_tongue_contract_unavailable") from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > MAX_RESPONSE_BYTES
        ):
            raise ValueError("tough_tongue_contract_file_invalid")
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("tough_tongue_contract_file_invalid") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("tough_tongue_contract_file_invalid")
        return cls.from_payload(
            parsed,
            expected_digest=expected_digest,
            configured_base_url=configured_base_url,
        )

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        *,
        expected_digest: str,
        configured_base_url: str,
    ) -> "ToughTongueLiveOpsContract":
        required = {
            "schema",
            "provider_key",
            "base_url",
            "source_type",
            "verified_at",
            "authority",
            "slot_cardinality",
            "maximum_snapshot_age_seconds",
            "premium_plan_values",
            "live_avatar_providers",
            "documented_get_allowlist",
            "normalization",
            "unsupported_direct_resources",
        }
        if set(payload) != required:
            raise ValueError("tough_tongue_contract_schema_invalid")
        digest = contract_digest(payload)
        if not _SHA256_REF.fullmatch(str(expected_digest or "").strip().lower()):
            raise ValueError("tough_tongue_contract_digest_missing")
        if digest != str(expected_digest).strip().lower():
            raise ValueError("tough_tongue_contract_digest_mismatch")
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        if (
            payload.get("schema") != CONTRACT_SCHEMA
            or payload.get("provider_key") != "tough_tongue"
            or payload.get("source_type") != "provider_documentation"
            or base_url != OFFICIAL_BASE_URL
            or base_url != str(configured_base_url or "").strip().rstrip("/")
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("tough_tongue_contract_schema_invalid")
        authority = payload.get("authority")
        if (
            not isinstance(authority, Mapping)
            or set(authority) != {"operator_verified", "source_ref_sha256"}
            or authority.get("operator_verified") is not True
            or not _SHA256_REF.fullmatch(str(authority.get("source_ref_sha256") or ""))
        ):
            raise ValueError("tough_tongue_contract_authority_invalid")
        _iso(payload.get("verified_at"))
        if payload.get("slot_cardinality") != EXPECTED_SLOT_COUNT:
            raise ValueError("tough_tongue_contract_cardinality_invalid")
        maximum_age = payload.get("maximum_snapshot_age_seconds")
        if not isinstance(maximum_age, int) or not 60 <= maximum_age <= 86400:
            raise ValueError("tough_tongue_contract_freshness_invalid")
        allowlist = payload.get("documented_get_allowlist")
        if not isinstance(allowlist, Mapping) or set(allowlist) != set(DOCUMENTED_GET_ROUTES):
            raise ValueError("tough_tongue_contract_allowlist_invalid")
        for name, path in DOCUMENTED_GET_ROUTES.items():
            row = allowlist.get(name)
            if not isinstance(row, Mapping) or set(row) != {"method", "path"}:
                raise ValueError(f"tough_tongue_contract_route_invalid:{name}")
            if row.get("method") != "GET" or row.get("path") != path:
                raise ValueError(f"tough_tongue_contract_route_invalid:{name}")
        if payload.get("normalization") != NORMALIZATION:
            raise ValueError("tough_tongue_contract_normalization_invalid")
        unsupported = payload.get("unsupported_direct_resources")
        if unsupported != list(UNSUPPORTED_DIRECT_RESOURCES):
            raise ValueError("tough_tongue_contract_unsupported_resources_invalid")

        def normalized_values(name: str) -> tuple[str, ...]:
            raw = payload.get(name)
            if not isinstance(raw, list):
                raise ValueError("tough_tongue_contract_policy_invalid")
            values = tuple(str(item or "").strip().lower() for item in raw)
            if (
                not values
                or any(_SAFE_POLICY_VALUE.fullmatch(item) is None for item in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("tough_tongue_contract_policy_invalid")
            return values

        return cls(
            base_url=base_url,
            source_ref_sha256=str(authority["source_ref_sha256"]),
            verified_at=str(payload["verified_at"]),
            maximum_snapshot_age_seconds=maximum_age,
            premium_plan_values=normalized_values("premium_plan_values"),
            live_avatar_providers=normalized_values("live_avatar_providers"),
            digest=digest,
        )


class ToughTongueDocumentedGetAdapter:
    """The complete mutation-free provider surface used by the v2 probe."""

    def __init__(
        self,
        *,
        config: ToughTongueConfig,
        slot: ProviderAccountSlot,
        contract: ToughTongueLiveOpsContract,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._config = replace(
            config,
            api_key=slot.credential,
            organization_id=slot.organization_ref,
            account_tier=slot.plan_name,
            account_slots=(),
            login_email="",
            forwarding_email="",
        )
        self._contract = contract
        self._opener = opener
        self.requests: list[str] = []

    def _get(self, route: str, *, resource_ref: str = "", timeout_seconds: float) -> Mapping[str, object]:
        if route not in DOCUMENTED_GET_ROUTES:
            raise ValueError("tough_tongue_route_not_allowlisted")
        path = DOCUMENTED_GET_ROUTES[route]
        if route == "scenario":
            if not resource_ref or any(character in resource_ref for character in "/?#\\"):
                raise ValueError("tough_tongue_scenario_ref_invalid")
            path = path.replace("{resource_ref}", urllib.parse.quote(resource_ref, safe=""))
        elif resource_ref:
            raise ValueError("tough_tongue_resource_ref_unexpected")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
            "User-Agent": "EA-ToughTongue-Documented-GET/2.0",
        }
        if self._config.organization_id:
            headers["X-TT-ORG"] = self._config.organization_id
        request = urllib.request.Request(
            f"{self._contract.base_url}/{path}", method="GET", headers=headers
        )
        self.requests.append(route)
        with self._opener(request, timeout=max(float(timeout_seconds), 1.0)) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("tough_tongue_response_too_large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("tough_tongue_response_not_object")
        return payload

    def balance(self, *, timeout_seconds: float) -> tuple[float, str]:
        payload = self._get("balance", timeout_seconds=timeout_seconds)
        value = payload.get("available_minutes")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("tough_tongue_balance_schema_invalid")
        remaining = float(value)
        refresh_at = str(payload.get("last_updated") or "").strip()
        if remaining < 0 or not refresh_at:
            raise ValueError("tough_tongue_balance_schema_invalid")
        normalized_refresh_at = _now_text(_provider_iso(refresh_at))
        return remaining, normalized_refresh_at

    def active_plan(self, *, timeout_seconds: float) -> str:
        payload = self._get("subscriptions", timeout_seconds=timeout_seconds)
        subscriptions = payload.get("subscriptions")
        if not isinstance(subscriptions, list):
            raise ValueError("tough_tongue_subscriptions_schema_invalid")
        plans = {
            str(row.get("product_name") or "").strip()
            for row in subscriptions
            if isinstance(row, Mapping) and str(row.get("status") or "").strip().lower() == "active"
        }
        plans.discard("")
        if len(plans) != 1:
            raise ValueError("tough_tongue_active_plan_cardinality_invalid")
        return plans.pop()

    def organization_member(self, organization_ref: str, *, timeout_seconds: float) -> bool:
        payload = self._get("organizations", timeout_seconds=timeout_seconds)
        organizations = payload.get("organizations")
        if not isinstance(organizations, list):
            raise ValueError("tough_tongue_organizations_schema_invalid")
        refs = {
            str(row.get("id") or "").strip()
            for row in organizations
            if isinstance(row, Mapping)
        }
        refs.discard("")
        if len(refs) != len(organizations):
            raise ValueError("tough_tongue_organizations_schema_invalid")
        return organization_ref in refs

    def scenario(self, resource_ref: str, *, timeout_seconds: float) -> tuple[str, str]:
        payload = self._get("scenario", resource_ref=resource_ref, timeout_seconds=timeout_seconds)
        observed_ref = str(payload.get("id") or "").strip()
        appearance = payload.get("appearance")
        if not observed_ref or not isinstance(appearance, Mapping):
            raise ValueError("tough_tongue_scenario_schema_invalid")
        voice = str(appearance.get("voice") or "").strip()
        if not voice:
            raise ValueError("tough_tongue_scenario_schema_invalid")
        return observed_ref, voice


def _slot_error(slots: tuple[ProviderAccountSlot, ...]) -> str:
    if len(slots) != EXPECTED_SLOT_COUNT:
        return "tough_tongue_slot_cardinality_invalid"
    expected_labels = [f"team-slot-{index}" for index in range(1, EXPECTED_SLOT_COUNT + 1)]
    if [slot.slot_label for slot in slots] != expected_labels:
        return "tough_tongue_slot_labels_invalid"
    credentials = [_digest(slot.credential) for slot in slots]
    accounts = [_digest(slot.account_ref) for slot in slots]
    if any(not value for value in credentials + accounts):
        return "tough_tongue_slot_fields_missing"
    if len(set(credentials)) != EXPECTED_SLOT_COUNT or len(set(accounts)) != EXPECTED_SLOT_COUNT:
        return "tough_tongue_slot_distinctness_invalid"
    return ""


def _receipt_digest(report: Mapping[str, object]) -> dict[str, object]:
    result = dict(report)
    result["evidence_digest"] = contract_digest(result)
    return result


def probe_tough_tongue_live_ops(
    *,
    config: ToughTongueConfig,
    contract: ToughTongueLiveOpsContract | None,
    authority: ToughTongueProbeAuthority | None,
    preferred_account_ref: str,
    candidate_refs: Mapping[str, str],
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout_seconds: float = 15.0,
    now: datetime | None = None,
) -> dict[str, object]:
    """Probe six slots only after a local state authority passes fail-closed guards."""

    clock = (now or _now()).astimezone(UTC)
    slots = tuple(config.account_slots)
    request_routes: list[str] = []
    account_hashes = [_digest(slot.account_ref) for slot in slots]
    org_hashes = [_digest(slot.organization_ref) for slot in slots]
    expected_hashes = {
        kind: _digest(candidate_refs.get(kind, ""))
        for kind in ("agent", "voice", "function", "scenario", "avatar")
    }
    report: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "generated_at": _now_text(clock),
        "provider_key": "tough_tongue",
        "status": "blocked",
        "ready": False,
        "reason": "tough_tongue_preflight_authority_missing",
        "source_types": ["local_preflight", "provider_documentation"],
        "contract_digest": contract.digest if contract else "",
        "preflight_authority": {
            "state": authority.state if authority else "",
            "observed_at": authority.observed_at if authority else "",
            "evidence_digest": authority.evidence_digest if authority else "",
        },
        "slot_cardinality": {
            "expected": EXPECTED_SLOT_COUNT,
            "configured": len(slots),
            "valid": False,
        },
        "accounts": [],
        "preferred_account_ref_sha256": _digest(preferred_account_ref),
        "candidate_ref_sha256": expected_hashes,
        "resource_ownership": {
            kind: {"configured": bool(candidate_refs.get(kind)), "verified": False}
            for kind in ("agent", "voice", "function", "scenario", "avatar")
        },
        "requests": {
            "attempted_count": 0,
            "methods": [],
            "allowlisted_routes": [],
            "mutation_request_count": 0,
            "response_bodies_persisted": False,
        },
        "runtime_gates_changed": False,
        "provider_resources_created_or_bound": False,
        "raw_credentials_persisted": False,
        "raw_identifiers_persisted": False,
    }

    def blocked(reason: str, status: str = "blocked") -> dict[str, object]:
        report["status"] = status
        report["reason"] = reason
        report["requests"] = {
            **dict(report["requests"]),  # type: ignore[arg-type]
            "attempted_count": len(request_routes),
            "methods": ["GET"] if request_routes else [],
            "allowlisted_routes": list(request_routes),
        }
        return _receipt_digest(report)

    if not config.enabled:
        return blocked("tough_tongue_disabled", "disabled")
    if not config.account_verified or not config.provider_verified:
        return blocked("tough_tongue_provider_unavailable", "unavailable")
    slot_error = _slot_error(slots)
    if slot_error:
        return blocked(slot_error, "malformed")
    report["slot_cardinality"] = {
        "expected": EXPECTED_SLOT_COUNT,
        "configured": len(slots),
        "valid": True,
    }
    if contract is None:
        return blocked("tough_tongue_contract_unavailable", "unavailable")
    if (
        authority is None
        or authority.state not in PREFLIGHT_STATES
        or _SHA256_REF.fullmatch(str(authority.evidence_digest or "").strip().lower()) is None
    ):
        return blocked("tough_tongue_preflight_authority_malformed", "malformed")
    try:
        authority_time = _iso(authority.observed_at)
    except ValueError:
        return blocked("tough_tongue_preflight_authority_malformed", "malformed")
    age_seconds = (clock - authority_time).total_seconds()
    if age_seconds < 0 or age_seconds > contract.maximum_snapshot_age_seconds:
        return blocked("tough_tongue_preflight_authority_stale", "stale")
    if authority.state != "ready":
        return blocked(f"tough_tongue_preflight_{authority.state}", authority.state)
    preferred_hash = _digest(preferred_account_ref)
    if not preferred_account_ref or account_hashes.count(preferred_hash) != 1:
        return blocked("tough_tongue_preferred_account_invalid", "malformed")
    if any(not candidate_refs.get(kind) for kind in ("agent", "voice", "function", "scenario", "avatar")):
        return blocked("tough_tongue_candidate_refs_incomplete", "malformed")

    rows: list[dict[str, object]] = []
    adapters: dict[str, ToughTongueDocumentedGetAdapter] = {}
    try:
        for index, slot in enumerate(slots, start=1):
            adapter = ToughTongueDocumentedGetAdapter(
                config=config, slot=slot, contract=contract, opener=opener
            )
            adapters[_digest(slot.account_ref)] = adapter
            try:
                remaining, refresh_at = adapter.balance(timeout_seconds=timeout_seconds)
                plan_name = adapter.active_plan(timeout_seconds=timeout_seconds)
                org_member = (
                    adapter.organization_member(slot.organization_ref, timeout_seconds=timeout_seconds)
                    if slot.organization_ref
                    else None
                )
            finally:
                request_routes.extend(adapter.requests)
                adapter.requests.clear()
            plan_normalized = (
                "premium" if plan_name.lower() in contract.premium_plan_values else "other"
            )
            rows.append(
                {
                    "slot": index,
                    "account_ref_sha256": account_hashes[index - 1],
                    "organization_ref_sha256": org_hashes[index - 1],
                    "organization_context_configured": bool(slot.organization_ref),
                    "organization_membership_verified": org_member,
                    "plan": plan_normalized,
                    "plan_ref_sha256": _digest(plan_name.lower()),
                    "remaining_minutes": remaining,
                    "refresh_at": refresh_at,
                    "depleted": remaining < config.min_remaining_minutes,
                }
            )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return blocked("tough_tongue_documented_get_unavailable", "unavailable")
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return blocked("tough_tongue_documented_get_malformed", "malformed")

    report["accounts"] = rows
    preferred_row = next(row for row in rows if row["account_ref_sha256"] == preferred_hash)
    if preferred_row["depleted"]:
        return blocked("tough_tongue_preferred_account_depleted", "depleted")
    if any(
        (clock - _iso(row["refresh_at"])).total_seconds() > contract.maximum_snapshot_age_seconds
        or (clock - _iso(row["refresh_at"])).total_seconds() < 0
        for row in rows
    ):
        return blocked("tough_tongue_balance_snapshot_stale", "stale")

    preferred_adapter = adapters[preferred_hash]
    try:
        try:
            scenario_ref, voice_ref = preferred_adapter.scenario(
                candidate_refs["scenario"], timeout_seconds=timeout_seconds
            )
        finally:
            request_routes.extend(preferred_adapter.requests)
            preferred_adapter.requests.clear()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return blocked("tough_tongue_scenario_readback_unavailable", "unavailable")
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return blocked("tough_tongue_scenario_readback_malformed", "malformed")

    scenario_match = _digest(scenario_ref) == expected_hashes["scenario"]
    voice_match = _digest(voice_ref) == expected_hashes["voice"]
    organization_verified = preferred_row["organization_membership_verified"] in {True, None}
    report["resource_ownership"] = {
        "scenario": {
            "configured": True,
            "verified": bool(scenario_match and organization_verified),
            "evidence": "organization_scoped_scenario_readback",
        },
        "agent": {
            "configured": True,
            "verified": _digest(candidate_refs["agent"]) == expected_hashes["scenario"] and scenario_match,
            "evidence": "documented_agent_is_scenario_alias",
        },
        "voice": {
            "configured": True,
            "verified": voice_match,
            "evidence": "documented_scenario_appearance_voice",
        },
        "function": {
            "configured": True,
            "verified": False,
            "evidence": "no_documented_direct_get_or_stable_identifier",
        },
        "avatar": {
            "configured": True,
            "verified": False,
            "evidence": "no_documented_direct_get_or_stable_identifier",
        },
    }
    return blocked("tough_tongue_direct_resource_ownership_not_documented", "unverified")
