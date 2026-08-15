from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://api.toughtongueai.com/api/public"
MAX_RESPONSE_BYTES = 256 * 1024


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

    @classmethod
    def from_env(cls) -> "ToughTongueConfig":
        def _float(name: str, default: float) -> float:
            try:
                return max(float(str(os.environ.get(name) or default).strip()), 0.0)
            except (TypeError, ValueError):
                return default

        return cls(
            api_key=str(os.environ.get("TOUGH_TONGUE_API_KEY") or "").strip(),
            base_url=str(os.environ.get("TOUGH_TONGUE_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
            login_email=str(os.environ.get("TOUGH_TONGUE_LOGIN_EMAIL") or "").strip(),
            forwarding_email=str(os.environ.get("TOUGH_TONGUE_FORWARDING_EMAIL") or "").strip(),
            account_tier=str(os.environ.get("TOUGH_TONGUE_ACCOUNT_TIER") or "").strip(),
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
        )

    @property
    def execution_ready(self) -> bool:
        return bool(
            self.enabled
            and self.api_key
            and self.account_verified
            and self.provider_verified
        )

    def posture(self) -> dict[str, object]:
        return {
            "configured": bool(self.api_key),
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
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "User-Agent": "EA-ToughTongue-ReadOnly-Probe/1.0",
            },
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
    }
    if not effective.api_key:
        return report

    try:
        balance = ToughTongueClient(effective, opener=opener).balance(timeout_seconds=timeout_seconds)
    except urllib.error.HTTPError as exc:
        report["status"] = "auth_failed" if exc.code in {401, 403} else "provider_error"
        report["reason"] = "tough_tongue_auth_failed" if exc.code in {401, 403} else "tough_tongue_http_error"
        report["next_action"] = (
            "replace_or_reauthorize_tough_tongue_api_key"
            if exc.code in {401, 403}
            else "reprobe_tough_tongue_balance"
        )
        raw = dict(report["raw"])
        raw["http_status"] = int(exc.code)
        report["raw"] = raw
        return report
    except (urllib.error.URLError, TimeoutError):
        report["status"] = "unavailable"
        report["reason"] = "tough_tongue_unreachable"
        report["next_action"] = "reprobe_tough_tongue_balance"
        return report
    except (RuntimeError, ValueError, json.JSONDecodeError):
        report["status"] = "probe_failed"
        report["reason"] = "tough_tongue_invalid_response"
        report["next_action"] = "inspect_tough_tongue_api_contract"
        return report

    available_minutes = float(balance["available_minutes"])
    report.update(
        {
            "status": "ready" if available_minutes >= effective.min_remaining_minutes else "quota_low",
            "remaining": available_minutes,
            "refresh_at": str(balance.get("last_updated") or "").strip(),
            "probe_ok": True,
            "ready": available_minutes >= effective.min_remaining_minutes,
            "reason": "" if available_minutes >= effective.min_remaining_minutes else "tough_tongue_minutes_below_reserve",
            "next_action": "" if available_minutes >= effective.min_remaining_minutes else "review_tough_tongue_minute_budget",
        }
    )
    return report
