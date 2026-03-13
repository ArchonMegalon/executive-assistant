from __future__ import annotations

from typing import Callable

from app.domain.models import OperatorProfile


class ExecutionOperatorProfileService:
    def __init__(
        self,
        *,
        upsert_profile: Callable[..., OperatorProfile],
        get_profile: Callable[[str], OperatorProfile | None],
        list_profiles_for_principal: Callable[..., list[OperatorProfile]],
    ) -> None:
        self._upsert_profile = upsert_profile
        self._get_profile = get_profile
        self._list_profiles_for_principal = list_profiles_for_principal

    def upsert_operator_profile(
        self,
        *,
        principal_id: str,
        operator_id: str | None = None,
        display_name: str,
        roles: tuple[str, ...] = (),
        skill_tags: tuple[str, ...] = (),
        trust_tier: str = "standard",
        status: str = "active",
        notes: str = "",
    ) -> OperatorProfile:
        return self._upsert_profile(
            principal_id=principal_id,
            operator_id=operator_id,
            display_name=display_name,
            roles=roles,
            skill_tags=skill_tags,
            trust_tier=trust_tier,
            status=status,
            notes=notes,
        )

    def fetch_operator_profile(self, operator_id: str, *, principal_id: str) -> OperatorProfile | None:
        row = self._get_profile(operator_id)
        if row is None or row.principal_id != str(principal_id or ""):
            return None
        return row

    def list_operator_profiles(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        rows = self._list_profiles_for_principal(
            principal_id=principal_id,
            status=status,
            limit=limit,
        )
        return sorted(rows, key=lambda row: str(row.operator_id or ""))
