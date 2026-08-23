from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
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
TOUGH_TONGUE_BINDING_RECEIPT_SCHEMA = "ea.tough_tongue.read_only_binding_receipt.v1"
TOUGH_TONGUE_BINDING_CONTRACT_SCHEMA = "ea.tough_tongue.read_only_binding_contract.v1"
TOUGH_TONGUE_BINDING_CONTRACT_PATH_ENV = "EA_TOUGH_TONGUE_READ_ONLY_BINDING_CONTRACT_PATH"
TOUGH_TONGUE_BINDING_CONTRACT_DIGEST_ENV = "EA_TOUGH_TONGUE_READ_ONLY_BINDING_CONTRACT_DIGEST"
TOUGH_TONGUE_PREFERRED_ACCOUNT_REF_ENV_NAMES = (
    "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_PREFERRED_ACCOUNT_REF",
    "TOUGH_TONGUE_PREFERRED_ACCOUNT_REF",
)
TOUGH_TONGUE_CANDIDATE_ENV_NAMES = {
    "agent": "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_AGENT_ID",
    "voice": "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_VOICE_ID",
    "function": "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_FUNCTION_ID",
    "scenario": "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_SCENARIO_ID",
    "live_avatar": "CHUMMER_BUILD_GHOST_TOUGH_TONGUE_LIVE_AVATAR_ID",
}
TOUGH_TONGUE_BINDING_ROUTE_NAMES = ("account", "agent", "voice", "function", "scenario")
TOUGH_TONGUE_BINDING_REQUIRED_SELECTORS = {
    "account": ("account_ref", "organization_ref", "plan_name", "live_avatar_entitled"),
    "agent": ("resource_ref", "account_ref", "organization_ref"),
    "voice": ("resource_ref", "account_ref", "organization_ref"),
    "function": ("resource_ref", "account_ref", "organization_ref"),
    "scenario": (
        "resource_ref",
        "account_ref",
        "organization_ref",
        "live_avatar_ref",
        "live_avatar_provider",
        "voice_ref",
        "function_refs",
    ),
}
_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SELECTOR_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/{}/-]+$")


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _sha256(value: object) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _sha256_ref(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    if _SHA256_REF_RE.fullmatch(lowered):
        return lowered
    return f"sha256:{_sha256(normalized)}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _mapping_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float_value(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        raise TypeError("numeric_value_required")
    return float(value)


def _int_value(value: object) -> int:
    if not isinstance(value, (int, float, str)):
        raise TypeError("integer_value_required")
    return int(value)


def tough_tongue_binding_contract_digest(payload: Mapping[str, object]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"


def _receipt_with_digest(payload: Mapping[str, object]) -> dict[str, object]:
    receipt = dict(payload)
    receipt.pop("receipt_digest", None)
    receipt["receipt_digest"] = tough_tongue_binding_contract_digest(receipt)
    return receipt


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
            available_minutes = _float_value(available)
        except (TypeError, ValueError) as exc:
            raise ValueError("tough_tongue_balance_missing") from exc
        return {
            "available_minutes": max(available_minutes, 0.0),
            "last_updated": str(payload.get("last_updated") or "").strip(),
        }


@dataclass(frozen=True)
class ToughTongueBindingExpectations:
    preferred_account_ref: str
    agent_ref: str
    voice_ref: str
    function_ref: str
    scenario_ref: str
    live_avatar_ref: str

    @classmethod
    def from_env(cls) -> "ToughTongueBindingExpectations":
        preferred = next(
            (
                str(os.environ.get(name) or "").strip()
                for name in TOUGH_TONGUE_PREFERRED_ACCOUNT_REF_ENV_NAMES
                if str(os.environ.get(name) or "").strip()
            ),
            "",
        )
        return cls(
            preferred_account_ref=preferred,
            agent_ref=str(os.environ.get(TOUGH_TONGUE_CANDIDATE_ENV_NAMES["agent"]) or "").strip(),
            voice_ref=str(os.environ.get(TOUGH_TONGUE_CANDIDATE_ENV_NAMES["voice"]) or "").strip(),
            function_ref=str(os.environ.get(TOUGH_TONGUE_CANDIDATE_ENV_NAMES["function"]) or "").strip(),
            scenario_ref=str(os.environ.get(TOUGH_TONGUE_CANDIDATE_ENV_NAMES["scenario"]) or "").strip(),
            live_avatar_ref=str(os.environ.get(TOUGH_TONGUE_CANDIDATE_ENV_NAMES["live_avatar"]) or "").strip(),
        )

    @property
    def candidate_refs(self) -> dict[str, str]:
        return {
            "agent": self.agent_ref,
            "voice": self.voice_ref,
            "function": self.function_ref,
            "scenario": self.scenario_ref,
            "live_avatar": self.live_avatar_ref,
        }

    @property
    def missing_candidate_kinds(self) -> list[str]:
        return [kind for kind, value in self.candidate_refs.items() if not value]

    @property
    def digest(self) -> str:
        return tough_tongue_binding_contract_digest(
            {
                "preferred_account_ref": _sha256_ref(self.preferred_account_ref),
                "candidate_refs": {
                    kind: _sha256_ref(value)
                    for kind, value in sorted(self.candidate_refs.items())
                },
            }
        )


@dataclass(frozen=True)
class ToughTongueReadOnlyRoute:
    path: str
    selectors: Mapping[str, str]


@dataclass(frozen=True)
class ToughTongueReadOnlyBindingContract:
    base_url: str
    source_type: str
    source_ref_sha256: str
    verified_at: str
    routes: Mapping[str, ToughTongueReadOnlyRoute]
    premium_plan_values: tuple[str, ...]
    live_avatar_providers: tuple[str, ...]
    digest: str

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        *,
        expected_digest: str,
        configured_base_url: str,
    ) -> "ToughTongueReadOnlyBindingContract":
        digest = tough_tongue_binding_contract_digest(payload)
        if not _SHA256_REF_RE.fullmatch(str(expected_digest or "").strip().lower()):
            raise ValueError("tough_tongue_readback_contract_digest_missing")
        if digest != str(expected_digest).strip().lower():
            raise ValueError("tough_tongue_readback_contract_digest_mismatch")
        if str(payload.get("schema") or "").strip() != TOUGH_TONGUE_BINDING_CONTRACT_SCHEMA:
            raise ValueError("tough_tongue_readback_contract_schema_invalid")
        if str(payload.get("provider_key") or "").strip() != "tough_tongue":
            raise ValueError("tough_tongue_readback_contract_provider_invalid")
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        if base_url != str(configured_base_url or "").strip().rstrip("/"):
            raise ValueError("tough_tongue_readback_contract_base_url_mismatch")
        parsed_base = urllib.parse.urlsplit(base_url)
        if (
            parsed_base.scheme != "https"
            or not parsed_base.netloc
            or parsed_base.username
            or parsed_base.password
            or parsed_base.query
            or parsed_base.fragment
        ):
            raise ValueError("tough_tongue_readback_contract_base_url_invalid")
        source_type = str(payload.get("source_type") or "").strip()
        verified_at = str(payload.get("verified_at") or "").strip()
        raw_authority = payload.get("authority")
        authority = raw_authority if isinstance(raw_authority, Mapping) else {}
        source_ref_sha256 = str(authority.get("source_ref_sha256") or "").strip().lower()
        try:
            verified_datetime = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("tough_tongue_readback_contract_authority_unverified") from exc
        if (
            source_type not in {"provider_documentation", "captured_read_only_api"}
            or authority.get("operator_verified") is not True
            or not _SHA256_REF_RE.fullmatch(source_ref_sha256)
            or verified_datetime.tzinfo is None
        ):
            raise ValueError("tough_tongue_readback_contract_authority_unverified")
        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, Mapping):
            raise ValueError("tough_tongue_readback_contract_routes_missing")
        routes: dict[str, ToughTongueReadOnlyRoute] = {}
        for route_name in TOUGH_TONGUE_BINDING_ROUTE_NAMES:
            raw_route = raw_routes.get(route_name)
            if not isinstance(raw_route, Mapping):
                raise ValueError(f"tough_tongue_readback_contract_route_missing:{route_name}")
            if str(raw_route.get("method") or "").strip().upper() != "GET":
                raise ValueError(f"tough_tongue_readback_contract_method_not_get:{route_name}")
            path = str(raw_route.get("path") or "").strip()
            _validate_read_only_path(route_name, path)
            raw_selectors = raw_route.get("selectors")
            if not isinstance(raw_selectors, Mapping):
                raise ValueError(f"tough_tongue_readback_contract_selectors_missing:{route_name}")
            selectors: dict[str, str] = {}
            for selector_name in TOUGH_TONGUE_BINDING_REQUIRED_SELECTORS[route_name]:
                selector = str(raw_selectors.get(selector_name) or "").strip()
                if not _SELECTOR_RE.fullmatch(selector):
                    raise ValueError(
                        f"tough_tongue_readback_contract_selector_invalid:{route_name}:{selector_name}"
                    )
                selectors[selector_name] = selector
            routes[route_name] = ToughTongueReadOnlyRoute(path=path, selectors=selectors)
        raw_premium_values = payload.get("premium_plan_values")
        raw_avatar_providers = payload.get("live_avatar_providers")
        if not isinstance(raw_premium_values, list) or not isinstance(raw_avatar_providers, list):
            raise ValueError("tough_tongue_readback_contract_entitlement_values_missing")
        premium_values = tuple(
            sorted(
                {
                    str(value or "").strip().lower()
                    for value in raw_premium_values
                    if str(value or "").strip()
                }
            )
        )
        avatar_providers = tuple(
            sorted(
                {
                    str(value or "").strip().lower()
                    for value in raw_avatar_providers
                    if str(value or "").strip()
                }
            )
        )
        if not premium_values or not avatar_providers:
            raise ValueError("tough_tongue_readback_contract_entitlement_values_missing")
        return cls(
            base_url=base_url,
            source_type=source_type,
            source_ref_sha256=source_ref_sha256,
            verified_at=verified_at,
            routes=routes,
            premium_plan_values=premium_values,
            live_avatar_providers=avatar_providers,
            digest=digest,
        )

    @classmethod
    def from_env(
        cls,
        *,
        configured_base_url: str,
    ) -> "ToughTongueReadOnlyBindingContract":
        path_value = str(os.environ.get(TOUGH_TONGUE_BINDING_CONTRACT_PATH_ENV) or "").strip()
        expected_digest = str(os.environ.get(TOUGH_TONGUE_BINDING_CONTRACT_DIGEST_ENV) or "").strip()
        if not path_value:
            raise ValueError("tough_tongue_readback_contract_not_configured")
        path = Path(path_value).expanduser()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("tough_tongue_readback_contract_not_found") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("tough_tongue_readback_contract_invalid_json") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("tough_tongue_readback_contract_not_object")
        return cls.from_payload(
            payload,
            expected_digest=expected_digest,
            configured_base_url=configured_base_url,
        )


def _validate_read_only_path(route_name: str, path: str) -> None:
    parsed = urllib.parse.urlsplit(path)
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not _RELATIVE_PATH_RE.fullmatch(path)
        or any(segment == ".." for segment in path.split("/"))
    ):
        raise ValueError(f"tough_tongue_readback_contract_path_invalid:{route_name}")
    placeholder_count = path.count("{resource_ref}")
    if route_name == "account" and placeholder_count != 0:
        raise ValueError("tough_tongue_readback_contract_account_path_invalid")
    if route_name != "account" and placeholder_count != 1:
        raise ValueError(f"tough_tongue_readback_contract_resource_path_invalid:{route_name}")
    if path.replace("{resource_ref}", "").find("{") >= 0 or path.replace("{resource_ref}", "").find("}") >= 0:
        raise ValueError(f"tough_tongue_readback_contract_placeholder_invalid:{route_name}")


def _selected_value(payload: Mapping[str, object], selector: str) -> object:
    current: object = payload
    for segment in selector.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            raise ValueError("tough_tongue_readback_selector_missing")
        current = current[segment]
    return current


class ToughTongueReadOnlyBindingAdapter:
    """GET-only adapter materialized from a digest-bound verified contract.

    No create, update, delete, session, grant, or execution methods exist on this
    type. Provider response bodies stay in memory and are reduced to a bounded
    normalized projection before the receipt is built.
    """

    def __init__(
        self,
        *,
        config: ToughTongueConfig,
        slot: ProviderAccountSlot,
        contract: ToughTongueReadOnlyBindingContract,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._config = replace(
            config,
            api_key=slot.credential,
            organization_id=slot.organization_ref,
            account_tier=slot.plan_name,
            login_email="",
            forwarding_email="",
            account_slots=(),
        )
        self._contract = contract
        self._client = ToughTongueClient(self._config, opener=opener)
        self.request_count = 0

    def read(self, route_name: str, *, resource_ref: str = "", timeout_seconds: float) -> dict[str, object]:
        if route_name not in TOUGH_TONGUE_BINDING_ROUTE_NAMES:
            raise ValueError("tough_tongue_readback_route_unknown")
        route = self._contract.routes[route_name]
        path = route.path
        if route_name != "account":
            if not resource_ref:
                raise ValueError("tough_tongue_readback_resource_ref_missing")
            path = path.replace("{resource_ref}", urllib.parse.quote(resource_ref, safe=""))
        self.request_count += 1
        payload = self._client._get_json(path, timeout_seconds=timeout_seconds)
        return {
            selector_name: _selected_value(payload, selector)
            for selector_name, selector in route.selectors.items()
        }


def _finalize_tough_tongue_binding_receipt(report: Mapping[str, object]) -> dict[str, object]:
    payload = dict(report)
    evidence = {
        "contract": payload.get("contract"),
        "expectation_digest": payload.get("expectation_digest"),
        "accounts": payload.get("accounts"),
        "entitlements": payload.get("entitlements"),
        "bindings": payload.get("bindings"),
        "ownership": payload.get("ownership"),
        "requests": payload.get("requests"),
        "provider_activation": payload.get("provider_activation"),
    }
    payload["evidence_digest"] = tough_tongue_binding_contract_digest(evidence)
    return _receipt_with_digest(payload)


def probe_tough_tongue_bindings(
    *,
    timeout_seconds: float = 15.0,
    config: ToughTongueConfig | None = None,
    expectations: ToughTongueBindingExpectations | None = None,
    contract: ToughTongueReadOnlyBindingContract | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    observed_at: str | None = None,
) -> dict[str, object]:
    """Verify one preferred account and candidate bindings using GET only.

    Without a locally supplied, operator-verified contract whose canonical
    digest matches the configured digest, this function returns a redacted
    blocked receipt before opening a network connection.
    """

    effective = config or ToughTongueConfig.from_env()
    expected = expectations or ToughTongueBindingExpectations.from_env()
    registry = _registry_for_config(effective)
    distinct_slots = registry.distinct_slots()
    preferred_ref = str(expected.preferred_account_ref or "").strip().lower()
    account_refs = [_sha256_ref(slot.account_ref) for slot in distinct_slots]
    preferred_matches = [
        slot
        for slot in distinct_slots
        if preferred_ref and _sha256_ref(slot.account_ref) == preferred_ref
    ]
    candidate_ref_digests = {
        kind: _sha256_ref(value)
        for kind, value in sorted(expected.candidate_refs.items())
    }
    bindings = {
        kind: {
            "configured": bool(expected.candidate_refs[kind]),
            "ref_sha256": candidate_ref_digests[kind],
            "readback": False,
            "reference_match": False,
            "account_owner_match": False,
            "organization_owner_match": False,
        }
        for kind in ("agent", "voice", "function", "scenario")
    }
    report: dict[str, object] = {
        "schema": TOUGH_TONGUE_BINDING_RECEIPT_SCHEMA,
        "generated_at": str(observed_at or _now_iso()),
        "provider_key": "tough_tongue",
        "probe_mode": "strict_read_only_get",
        "status": "blocked",
        "ready": False,
        "probe_ok": False,
        "reason": "tough_tongue_readback_contract_not_configured",
        "blockers": [],
        "next_action": "supply_operator_verified_tough_tongue_readback_contract",
        "source": "local_fail_closed_preflight",
        "expectation_digest": expected.digest,
        "contract": {
            "schema": TOUGH_TONGUE_BINDING_CONTRACT_SCHEMA,
            "configured": False,
            "verified": False,
            "digest": "",
            "source_type": "",
            "source_ref_sha256": "",
            "verified_at": "",
            "methods": [],
        },
        "accounts": {
            "configured_count": len(registry.configured_slots),
            "distinct_count": len(distinct_slots),
            "opaque_account_refs": sorted(ref for ref in account_refs if ref),
            "preferred_account_ref": preferred_ref if _SHA256_REF_RE.fullmatch(preferred_ref) else "",
            "preferred_account_ref_configured": bool(preferred_ref),
            "preferred_account_ref_valid": bool(_SHA256_REF_RE.fullmatch(preferred_ref)),
            "preferred_match_count": len(preferred_matches),
            "preferred_ownership_verified": False,
        },
        "entitlements": {
            "plan_readback": False,
            "premium_verified": False,
            "live_avatar_verified": False,
            "observed_plan_ref_sha256": "",
        },
        "bindings": bindings,
        "ownership": {
            "account_verified": False,
            "organization_verified": False,
            "all_candidate_resources_verified": False,
        },
        "requests": {
            "attempted_count": 0,
            "methods": [],
            "mutation_request_count": 0,
            "response_bodies_persisted": False,
        },
        "provider_activation": {
            "sessions_created": False,
            "grants_created": False,
            "agents_mutated": False,
            "voices_mutated": False,
            "functions_mutated": False,
            "scenarios_mutated": False,
            "provider_resources_mutated": False,
        },
        "raw_credentials_exposed": False,
        "raw_account_identifiers_exposed": False,
        "raw_candidate_identifiers_exposed": False,
    }

    blockers: list[str] = []
    effective_contract = contract
    if effective_contract is None:
        try:
            effective_contract = ToughTongueReadOnlyBindingContract.from_env(
                configured_base_url=effective.base_url,
            )
        except ValueError as exc:
            reason = str(exc).strip()
            blockers.append(
                reason if reason.startswith("tough_tongue_") else "tough_tongue_readback_contract_invalid"
            )
    if effective_contract is not None:
        report["contract"] = {
            "schema": TOUGH_TONGUE_BINDING_CONTRACT_SCHEMA,
            "configured": True,
            "verified": True,
            "digest": effective_contract.digest,
            "source_type": effective_contract.source_type,
            "source_ref_sha256": effective_contract.source_ref_sha256,
            "verified_at": effective_contract.verified_at,
            "methods": ["GET"],
        }
    if not distinct_slots:
        blockers.append("tough_tongue_accounts_not_configured")
    if not preferred_ref:
        blockers.append("tough_tongue_preferred_account_ref_missing")
    elif not _SHA256_REF_RE.fullmatch(preferred_ref):
        blockers.append("tough_tongue_preferred_account_ref_invalid")
    elif len(preferred_matches) != 1:
        blockers.append(
            "tough_tongue_preferred_account_ref_not_found"
            if not preferred_matches
            else "tough_tongue_preferred_account_ref_ambiguous"
        )
    if expected.missing_candidate_kinds:
        blockers.extend(
            f"tough_tongue_candidate_{kind}_ref_missing"
            for kind in expected.missing_candidate_kinds
        )
    if blockers:
        report["blockers"] = blockers
        report["reason"] = blockers[0]
        return _finalize_tough_tongue_binding_receipt(report)

    assert effective_contract is not None
    selected_slot = preferred_matches[0]
    adapter = ToughTongueReadOnlyBindingAdapter(
        config=effective,
        slot=selected_slot,
        contract=effective_contract,
        opener=opener,
    )
    try:
        account = adapter.read("account", timeout_seconds=timeout_seconds)
        agent = adapter.read("agent", resource_ref=expected.agent_ref, timeout_seconds=timeout_seconds)
        voice = adapter.read("voice", resource_ref=expected.voice_ref, timeout_seconds=timeout_seconds)
        function = adapter.read(
            "function",
            resource_ref=expected.function_ref,
            timeout_seconds=timeout_seconds,
        )
        scenario = adapter.read(
            "scenario",
            resource_ref=expected.scenario_ref,
            timeout_seconds=timeout_seconds,
        )
    except urllib.error.HTTPError as exc:
        report["status"] = "auth_failed" if exc.code in {401, 403} else "provider_error"
        report["reason"] = (
            "tough_tongue_readback_auth_failed"
            if exc.code in {401, 403}
            else "tough_tongue_readback_http_error"
        )
        report["next_action"] = "verify_tough_tongue_read_only_credentials_and_contract"
        report["requests"] = {
            **_mapping_dict(report["requests"]),
            "attempted_count": adapter.request_count,
            "methods": ["GET"] if adapter.request_count else [],
        }
        return _finalize_tough_tongue_binding_receipt(report)
    except (urllib.error.URLError, TimeoutError):
        report["status"] = "unavailable"
        report["reason"] = "tough_tongue_readback_unreachable"
        report["next_action"] = "reprobe_tough_tongue_read_only_bindings"
        report["requests"] = {
            **_mapping_dict(report["requests"]),
            "attempted_count": adapter.request_count,
            "methods": ["GET"] if adapter.request_count else [],
        }
        return _finalize_tough_tongue_binding_receipt(report)
    except (RuntimeError, ValueError, json.JSONDecodeError):
        report["status"] = "probe_failed"
        report["reason"] = "tough_tongue_readback_invalid_response"
        report["next_action"] = "inspect_tough_tongue_read_only_contract_drift"
        report["requests"] = {
            **_mapping_dict(report["requests"]),
            "attempted_count": adapter.request_count,
            "methods": ["GET"] if adapter.request_count else [],
        }
        return _finalize_tough_tongue_binding_receipt(report)

    selected_account_ref = _sha256_ref(account.get("account_ref"))
    selected_organization_ref = _sha256_ref(selected_slot.organization_ref)
    observed_organization_ref = _sha256_ref(account.get("organization_ref"))
    account_match = selected_account_ref == preferred_ref
    organization_match = (
        observed_organization_ref == selected_organization_ref
        if selected_organization_ref
        else bool(observed_organization_ref)
    )
    plan_name = str(account.get("plan_name") or "").strip()
    premium_verified = plan_name.lower() in effective_contract.premium_plan_values
    live_avatar_verified = account.get("live_avatar_entitled") is True
    report["accounts"] = {
        **_mapping_dict(report["accounts"]),
        "preferred_ownership_verified": account_match,
    }
    report["entitlements"] = {
        "plan_readback": bool(plan_name),
        "premium_verified": premium_verified,
        "live_avatar_verified": live_avatar_verified,
        "observed_plan_ref_sha256": _sha256_ref(plan_name),
    }

    resource_payloads = {
        "agent": (agent, expected.agent_ref),
        "voice": (voice, expected.voice_ref),
        "function": (function, expected.function_ref),
        "scenario": (scenario, expected.scenario_ref),
    }
    all_resources_verified = True
    for kind, (payload, expected_ref) in resource_payloads.items():
        reference_match = str(payload.get("resource_ref") or "").strip() == expected_ref
        owner_match = _sha256_ref(payload.get("account_ref")) == preferred_ref
        resource_organization_ref = _sha256_ref(payload.get("organization_ref"))
        resource_organization_match = (
            resource_organization_ref == selected_organization_ref
            if selected_organization_ref
            else bool(resource_organization_ref)
        )
        row = dict(bindings[kind])
        row.update(
            {
                "readback": True,
                "reference_match": reference_match,
                "account_owner_match": owner_match,
                "organization_owner_match": resource_organization_match,
            }
        )
        bindings[kind] = row
        all_resources_verified = all_resources_verified and all(
            (reference_match, owner_match, resource_organization_match)
        )

    scenario_provider = str(scenario.get("live_avatar_provider") or "").strip().lower()
    scenario_live_avatar_match = (
        str(scenario.get("live_avatar_ref") or "").strip() == expected.live_avatar_ref
    )
    scenario_voice_match = str(scenario.get("voice_ref") or "").strip() == expected.voice_ref
    raw_function_refs = scenario.get("function_refs")
    scenario_function_match = bool(
        isinstance(raw_function_refs, list)
        and expected.function_ref in {str(value or "").strip() for value in raw_function_refs}
    )
    scenario_provider_allowed = scenario_provider in effective_contract.live_avatar_providers
    bindings["scenario"] = {
        **dict(bindings["scenario"]),
        "live_avatar_match": scenario_live_avatar_match,
        "live_avatar_provider_allowed": scenario_provider_allowed,
        "voice_match": scenario_voice_match,
        "function_match": scenario_function_match,
        "observed_live_avatar_provider_ref_sha256": _sha256_ref(scenario_provider),
    }
    all_resources_verified = all_resources_verified and all(
        (
            scenario_live_avatar_match,
            scenario_provider_allowed,
            scenario_voice_match,
            scenario_function_match,
        )
    )
    ownership_verified = account_match and organization_match and all_resources_verified
    ready = ownership_verified and premium_verified and live_avatar_verified
    report.update(
        {
            "status": "verified" if ready else "unverified",
            "ready": ready,
            "probe_ok": True,
            "reason": "" if ready else "tough_tongue_binding_evidence_mismatch",
            "blockers": [] if ready else ["tough_tongue_binding_evidence_mismatch"],
            "next_action": "" if ready else "review_tough_tongue_binding_readback_mismatch",
            "source": "tough_tongue_public_api:digest_bound_verified_get_contract",
            "bindings": bindings,
            "ownership": {
                "account_verified": account_match,
                "organization_verified": organization_match,
                "all_candidate_resources_verified": all_resources_verified,
            },
            "requests": {
                **_mapping_dict(report["requests"]),
                "attempted_count": adapter.request_count,
                "methods": ["GET"] if adapter.request_count else [],
            },
        }
    )
    return _finalize_tough_tongue_binding_receipt(report)


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
            raw = _mapping_dict(report["raw"])
            raw["http_status"] = first["http_status"]
            report["raw"] = raw
        return report

    spendable_capacity = _float_value(aggregate["spendable_capacity"] or 0.0)
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

    remaining = _float_value(balance["available_minutes"])
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

    remaining_values = [_float_value(row["remaining"] or 0.0) for row in successful]
    remaining_total: float | None
    if aggregate_basis == "independent_accounts_sum":
        remaining_total = sum(remaining_values)
    elif aggregate_basis == "shared_team_pool":
        grouped: dict[str, list[float]] = {}
        for row in successful:
            organization_ref = str(row["organization_ref_sha256"] or "")
            group = organization_ref or "shared-team-pool"
            grouped.setdefault(group, []).append(_float_value(row["remaining"] or 0.0))
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
        "configured_count": _int_value(config.posture()["configured_account_count"]),
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
