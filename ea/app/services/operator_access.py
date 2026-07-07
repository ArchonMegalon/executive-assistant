from __future__ import annotations

from collections.abc import Iterable
from typing import Any


OPERATOR_ACCESS_ROLES = frozenset({"operator", "admin", "reviewer", "cloudflare_access"})


def normalized_operator_roles(row: Any) -> frozenset[str]:
    raw_roles = getattr(row, "roles", ()) if row is not None else ()
    if not isinstance(raw_roles, (list, tuple, set, frozenset)):
        raw_roles = ()
    return frozenset(
        str(role or "").strip().lower()
        for role in raw_roles
        if str(role or "").strip()
    )


def operator_access_profile(row: Any) -> bool:
    if row is None:
        return False
    status = str(getattr(row, "status", "active") or "active").strip().lower() or "active"
    if status != "active":
        return False
    return bool(normalized_operator_roles(row).intersection(OPERATOR_ACCESS_ROLES))


def operator_access_profiles(rows: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(row for row in rows if operator_access_profile(row))


def operator_access_profile_count(rows: Iterable[Any]) -> int:
    return sum(1 for row in rows if operator_access_profile(row))


def first_operator_access_profile(rows: Iterable[Any]) -> Any | None:
    for row in rows:
        if operator_access_profile(row):
            return row
    return None
