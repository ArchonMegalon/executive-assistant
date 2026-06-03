from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import os
from typing import Any

import requests


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class PropertyPlanSpec:
    plan_key: str
    display_name: str
    checkout_label: str
    amount_eur: str
    pass_days: int
    max_platforms: int
    max_results_per_source: int
    research_depth: str
    features: tuple[str, ...]


_FREE_PLAN = PropertyPlanSpec(
    plan_key="free",
    display_name="Free",
    checkout_label="Free",
    amount_eur="0.00",
    pass_days=0,
    max_platforms=1,
    max_results_per_source=2,
    research_depth="shallow",
    features=(
        "1 platform at a time",
        "up to 2 results per source",
        "light fit summary",
    ),
)

_PAID_PLANS = {
    "plus": PropertyPlanSpec(
        plan_key="plus",
        display_name="Plus",
        checkout_label="EUR 29 / 30 days",
        amount_eur="29.00",
        pass_days=30,
        max_platforms=3,
        max_results_per_source=5,
        research_depth="standard",
        features=(
            "up to 3 platforms per run",
            "up to 5 results per source",
            "richer hosted review packets",
        ),
    ),
    "agent": PropertyPlanSpec(
        plan_key="agent",
        display_name="Agent",
        checkout_label="EUR 99 / 30 days",
        amount_eur="99.00",
        pass_days=30,
        max_platforms=8,
        max_results_per_source=10,
        research_depth="deep",
        features=(
            "all major platforms in one run",
            "up to 10 results per source",
            "deep research and follow-up readiness",
        ),
    ),
}


def property_plan_catalog() -> tuple[PropertyPlanSpec, ...]:
    return (_FREE_PLAN, *_PAID_PLANS.values())


def property_plan_spec(plan_key: str) -> PropertyPlanSpec:
    normalized = str(plan_key or "").strip().lower()
    if normalized == "free":
        return _FREE_PLAN
    if normalized in _PAID_PLANS:
        return _PAID_PLANS[normalized]
    raise ValueError("unknown_property_plan")


def normalize_property_commercial(value: dict[str, object] | None) -> dict[str, object]:
    raw = dict(value or {})
    requested_plan_key = str(raw.get("active_plan_key") or raw.get("plan_key") or "free").strip().lower() or "free"
    if requested_plan_key not in {"free", *tuple(_PAID_PLANS.keys())}:
        requested_plan_key = "free"
    active_until = _parse_iso(raw.get("active_until"))
    expired = requested_plan_key != "free" and (active_until is None or active_until <= _now())
    effective_plan_key = "free" if expired else requested_plan_key
    status = str(raw.get("status") or ("expired" if expired else ("active" if effective_plan_key != "free" else "free"))).strip().lower()
    if effective_plan_key == "free" and status not in {"expired", "free"}:
        status = "free"
    if effective_plan_key != "free" and status not in {"active", "pending", "captured"}:
        status = "active"
    return {
        "active_plan_key": effective_plan_key,
        "status": status,
        "active_until": active_until.isoformat() if active_until is not None and effective_plan_key != "free" and not expired else "",
        "last_order_id": str(raw.get("last_order_id") or "").strip(),
        "last_capture_id": str(raw.get("last_capture_id") or "").strip(),
        "last_payment_status": str(raw.get("last_payment_status") or "").strip(),
        "last_payment_amount_eur": str(raw.get("last_payment_amount_eur") or "").strip(),
        "last_payer_email": str(raw.get("last_payer_email") or "").strip(),
        "captured_at": str(raw.get("captured_at") or "").strip(),
        "pending_order_id": str(raw.get("pending_order_id") or "").strip(),
        "pending_plan_key": str(raw.get("pending_plan_key") or "").strip().lower(),
        "pending_approval_url": str(raw.get("pending_approval_url") or "").strip(),
        "plan_source": str(raw.get("plan_source") or "").strip(),
    }


def property_commercial_snapshot(property_preferences: dict[str, object] | None) -> dict[str, object]:
    preferences = dict(property_preferences or {})
    commercial = normalize_property_commercial(dict(preferences.get("property_commercial") or {}))
    current_plan = property_plan_spec(str(commercial.get("active_plan_key") or "free"))
    pending_plan_key = str(commercial.get("pending_plan_key") or "").strip().lower()
    pending_plan = _PAID_PLANS.get(pending_plan_key)
    return {
        "current_plan_key": current_plan.plan_key,
        "current_plan_label": current_plan.display_name,
        "status": str(commercial.get("status") or "free"),
        "active_until": str(commercial.get("active_until") or ""),
        "is_paid": current_plan.plan_key != "free",
        "research_depth": current_plan.research_depth,
        "max_platforms": current_plan.max_platforms,
        "max_results_per_source": current_plan.max_results_per_source,
        "pending_plan_key": pending_plan.plan_key if pending_plan is not None else "",
        "pending_plan_label": pending_plan.display_name if pending_plan is not None else "",
        "pending_approval_url": str(commercial.get("pending_approval_url") or ""),
        "plan_catalog": [
            {
                "plan_key": spec.plan_key,
                "display_name": spec.display_name,
                "checkout_label": spec.checkout_label,
                "amount_eur": spec.amount_eur,
                "pass_days": spec.pass_days,
                "max_platforms": spec.max_platforms,
                "max_results_per_source": spec.max_results_per_source,
                "research_depth": spec.research_depth,
                "features": list(spec.features),
                "is_current": spec.plan_key == current_plan.plan_key,
            }
            for spec in property_plan_catalog()
        ],
        "property_commercial": commercial,
    }


def merge_property_commercial(
    property_preferences: dict[str, object] | None,
    *,
    updates: dict[str, object],
) -> dict[str, object]:
    merged = dict(property_preferences or {})
    current = normalize_property_commercial(dict(merged.get("property_commercial") or {}))
    current.update(dict(updates or {}))
    merged["property_commercial"] = normalize_property_commercial(current)
    return merged


def enforce_property_plan_limits(
    *,
    property_preferences: dict[str, object] | None,
    selected_platforms: tuple[str, ...],
    max_results_per_source: int | None,
) -> None:
    snapshot = property_commercial_snapshot(property_preferences)
    current_plan = property_plan_spec(str(snapshot.get("current_plan_key") or "free"))
    platform_count = len([value for value in selected_platforms if str(value or "").strip()])
    if platform_count > current_plan.max_platforms:
        target = "plus" if current_plan.plan_key == "free" else "agent"
        raise RuntimeError(f"property_plan_upgrade_required:{target}")
    if max_results_per_source is not None and int(max_results_per_source) > int(current_plan.max_results_per_source):
        target = "plus" if current_plan.plan_key == "free" else "agent"
        raise RuntimeError(f"property_plan_upgrade_required:{target}")


def paypal_configured() -> bool:
    return bool(str(os.getenv("PAYPAL_CLIENT_ID") or "").strip() and str(os.getenv("PAYPAL_SECRET") or "").strip())


def _paypal_api_base() -> str:
    return str(os.getenv("PAYPAL_API_BASE") or "https://api-m.paypal.com").strip().rstrip("/")


def _paypal_auth_header() -> str:
    client_id = str(os.getenv("PAYPAL_CLIENT_ID") or "").strip()
    secret = str(os.getenv("PAYPAL_SECRET") or "").strip()
    if not client_id or not secret:
        raise RuntimeError("paypal_not_configured")
    token = base64.b64encode(f"{client_id}:{secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _paypal_access_token() -> str:
    response = requests.post(
        f"{_paypal_api_base()}/v1/oauth2/token",
        headers={
            "Authorization": _paypal_auth_header(),
            "Accept": "application/json",
            "Accept-Language": "en_US",
        },
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"paypal_access_token_failed:{response.status_code}")
    payload = response.json()
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("paypal_access_token_missing")
    return token


def create_paypal_property_order(
    *,
    principal_id: str,
    plan_key: str,
    return_url: str,
    cancel_url: str,
) -> dict[str, object]:
    spec = property_plan_spec(plan_key)
    if spec.plan_key == "free":
        raise RuntimeError("property_plan_free_does_not_require_checkout")
    token = _paypal_access_token()
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": f"propertyquarry-{spec.plan_key}",
                "description": f"PropertyQuarry {spec.display_name} 30-day pass",
                "custom_id": f"{principal_id}:{spec.plan_key}",
                "amount": {
                    "currency_code": "EUR",
                    "value": spec.amount_eur,
                },
            }
        ],
        "application_context": {
            "brand_name": "PropertyQuarry",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    response = requests.post(
        f"{_paypal_api_base()}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"paypal_order_create_failed:{response.status_code}")
    body = response.json()
    approve_url = ""
    for link in list(body.get("links") or []):
        if str(link.get("rel") or "").strip().lower() == "approve":
            approve_url = str(link.get("href") or "").strip()
            break
    order_id = str(body.get("id") or "").strip()
    if not order_id or not approve_url:
        raise RuntimeError("paypal_order_create_invalid")
    return {
        "order_id": order_id,
        "approve_url": approve_url,
        "status": str(body.get("status") or "").strip().lower(),
        "plan_key": spec.plan_key,
        "amount_eur": spec.amount_eur,
    }


def capture_paypal_property_order(*, order_id: str) -> dict[str, object]:
    normalized_order_id = str(order_id or "").strip()
    if not normalized_order_id:
        raise RuntimeError("paypal_order_id_required")
    token = _paypal_access_token()
    response = requests.post(
        f"{_paypal_api_base()}/v2/checkout/orders/{normalized_order_id}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"paypal_order_capture_failed:{response.status_code}")
    body = response.json()
    captures = (
        body.get("purchase_units", [{}])[0].get("payments", {}).get("captures", [])
        if isinstance(body, dict)
        else []
    )
    capture_id = ""
    payment_status = str(body.get("status") or "").strip()
    amount_eur = ""
    if captures:
        first_capture = dict(captures[0] or {})
        capture_id = str(first_capture.get("id") or "").strip()
        payment_status = str(first_capture.get("status") or payment_status).strip()
        amount = dict(first_capture.get("amount") or {})
        amount_eur = str(amount.get("value") or "").strip()
    payer_email = str(dict(body.get("payer") or {}).get("email_address") or "").strip()
    return {
        "order_id": normalized_order_id,
        "capture_id": capture_id,
        "payment_status": payment_status.lower(),
        "payer_email": payer_email,
        "amount_eur": amount_eur,
        "raw": body,
    }


def paid_plan_expiry(*, plan_key: str, captured_at: datetime | None = None) -> str:
    spec = property_plan_spec(plan_key)
    if spec.plan_key == "free":
        return ""
    base = captured_at or _now()
    return (base + timedelta(days=spec.pass_days)).isoformat()
