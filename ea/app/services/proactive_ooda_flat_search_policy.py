from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any


REAL_ESTATE_DIRECT_TOKENS = {
    "apartment",
    "apartments",
    "flat",
    "flats",
    "immo",
    "immobilie",
    "immobilien",
    "mietwohnung",
    "property_scout",
    "wohnung",
    "wohnungen",
    "wohnungstausch",
}
REAL_ESTATE_WEAK_OBJECT_TOKENS = {
    "haus",
    "house",
    "object",
    "objekt",
    "properties",
    "property",
}
REAL_ESTATE_ACTION_TOKENS = {
    "buy",
    "buying",
    "candidate",
    "candidates",
    "compare",
    "comparison",
    "kauf",
    "kaufe",
    "kaufen",
    "listing",
    "listings",
    "miete",
    "mieten",
    "mietwohnung",
    "portal",
    "rent",
    "rental",
    "scout",
    "search",
}
REAL_ESTATE_CONTEXT_PHRASES = (
    "apartment alert",
    "apartment candidate",
    "apartment candidates",
    "apartment search",
    "apartment tour",
    "flat search",
    "property alert",
    "property candidate",
    "property candidates",
    "property scout",
    "property search",
    "property tour",
    "real estate",
    "real-estate",
    "willhaben property",
)


def proactive_ooda_flat_search_enabled() -> bool:
    if _env_truthy(os.getenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH"), default=False):
        return False
    return _env_truthy(os.getenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED"), default=False)


def material_mentions_flat_property_search(*values: Any) -> bool:
    for value in values:
        if isinstance(value, str):
            if text_mentions_flat_property_search(value):
                return True
            continue
        try:
            material = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except Exception:
            material = str(value or "")
        if text_mentions_flat_property_search(material):
            return True
    return False


def text_mentions_flat_property_search(value: str) -> bool:
    normalized = f" {_ascii_fold_text(str(value or '').strip().lower())} "
    if not normalized.strip():
        return False
    if any(phrase in normalized for phrase in REAL_ESTATE_CONTEXT_PHRASES):
        return True
    tokens = set(re.findall(r"[a-z0-9_]+", normalized))
    if tokens & REAL_ESTATE_DIRECT_TOKENS:
        return True
    if any(token.startswith(("immobili", "wohnung")) for token in tokens):
        return True
    if "studio" in tokens and tokens & {"buy", "buying", "kauf", "kaufe", "kaufen", "miete", "mieten", "rent", "rental"}:
        return True
    if tokens & REAL_ESTATE_WEAK_OBJECT_TOKENS and tokens & REAL_ESTATE_ACTION_TOKENS:
        return True
    if "willhaben" in tokens and tokens & {"apartment", "immobilien", "listing", "property", "wohnung"}:
        return True
    return False


def _env_truthy(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled", "n"}:
        return False
    return default


def _ascii_fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()
