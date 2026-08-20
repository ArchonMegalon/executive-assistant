from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from typing import Iterable, Mapping, Sequence


def _sha256(value: object) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def split_provider_account_values(value: object) -> tuple[str, ...]:
    """Split a governed multi-slot value without ever serializing its contents."""

    normalized = str(value or "").replace("\r", "\n")
    values: list[str] = []
    for line in normalized.split("\n"):
        values.extend(part.strip() for part in line.split(";") if part.strip())
    return tuple(values)


@dataclass(frozen=True)
class ProviderAccountSlot:
    provider_key: str
    slot_label: str
    credential: str
    account_ref: str = ""
    organization_ref: str = ""
    plan_name: str = ""

    @property
    def credential_sha256(self) -> str:
        return _sha256(self.credential)

    @property
    def account_ref_sha256(self) -> str:
        return _sha256(self.account_ref)

    @property
    def organization_ref_sha256(self) -> str:
        return _sha256(self.organization_ref)


class ProviderAccountRegistry:
    """Generic in-memory registry for governed provider credential slots.

    Raw credentials and account identifiers stay in memory and are deliberately
    absent from the sanitized projections returned to callers.
    """

    def __init__(self, slots: Iterable[ProviderAccountSlot]) -> None:
        self._slots = tuple(slots)

    @property
    def configured_slots(self) -> tuple[ProviderAccountSlot, ...]:
        return self._slots

    def distinct_slots(self) -> tuple[ProviderAccountSlot, ...]:
        distinct: list[ProviderAccountSlot] = []
        seen_credentials: set[str] = set()
        seen_accounts: set[str] = set()
        for slot in self._slots:
            credential_ref = slot.credential_sha256
            account_ref = slot.account_ref_sha256
            if not credential_ref or credential_ref in seen_credentials:
                continue
            if account_ref and account_ref in seen_accounts:
                continue
            seen_credentials.add(credential_ref)
            if account_ref:
                seen_accounts.add(account_ref)
            distinct.append(slot)
        return tuple(distinct)

    @classmethod
    def from_env(
        cls,
        *,
        provider_key: str,
        credential_env_names: Sequence[str],
        account_ref_env_names: Sequence[str] = (),
        organization_ref_env_names: Sequence[str] = (),
        plan_env_names: Sequence[str] = (),
        environ: Mapping[str, str] | None = None,
    ) -> "ProviderAccountRegistry":
        source = environ if environ is not None else os.environ
        credentials = _first_configured_values(source, credential_env_names)
        account_refs = _first_configured_values(source, account_ref_env_names)
        organization_refs = _first_configured_values(source, organization_ref_env_names)
        plan_names = _first_configured_values(source, plan_env_names)
        slots = tuple(
            ProviderAccountSlot(
                provider_key=provider_key,
                slot_label=f"team-slot-{index + 1}",
                credential=credential,
                account_ref=_aligned(account_refs, index),
                organization_ref=_aligned(organization_refs, index, repeat_single=True),
                plan_name=_aligned(plan_names, index, repeat_single=True),
            )
            for index, credential in enumerate(credentials)
        )
        return cls(slots)

    @classmethod
    def from_indexed_env(
        cls,
        *,
        provider_key: str,
        credential_env_names: Sequence[str],
        account_ref_env_names: Sequence[str] = (),
        organization_ref_env_names: Sequence[str] = (),
        plan_env_names: Sequence[str] = (),
        environ: Mapping[str, str] | None = None,
    ) -> "ProviderAccountRegistry":
        """Load one governed account per named credential slot.

        Unlike ``from_env``, which accepts a delimited pool, this preserves the
        original slot index and aligns each credential with its independently
        named account, organization, and plan references.
        """

        source = environ if environ is not None else os.environ
        slots = tuple(
            ProviderAccountSlot(
                provider_key=provider_key,
                slot_label=f"team-slot-{index + 1}",
                credential=credential,
                account_ref=_indexed_env_value(source, account_ref_env_names, index),
                organization_ref=_indexed_env_value(source, organization_ref_env_names, index),
                plan_name=_indexed_env_value(source, plan_env_names, index),
            )
            for index, credential_env_name in enumerate(credential_env_names)
            if (credential := str(source.get(credential_env_name, "") or "").strip())
        )
        return cls(slots)


def sanitized_provider_account_slot(slot: ProviderAccountSlot) -> dict[str, object]:
    return {
        "slot_label": slot.slot_label,
        "account_ref_sha256": slot.account_ref_sha256,
        "organization_ref_sha256": slot.organization_ref_sha256,
        "plan_name": slot.plan_name,
        "raw_credentials_exposed": False,
        "account_emails_exposed": False,
    }


def _first_configured_values(
    environ: Mapping[str, str],
    names: Sequence[str],
) -> tuple[str, ...]:
    for name in names:
        values = split_provider_account_values(environ.get(name, ""))
        if values:
            return values
    return ()


def _aligned(values: Sequence[str], index: int, *, repeat_single: bool = False) -> str:
    if index < len(values):
        return str(values[index]).strip()
    if repeat_single and len(values) == 1:
        return str(values[0]).strip()
    return ""


def _indexed_env_value(
    environ: Mapping[str, str],
    names: Sequence[str],
    index: int,
) -> str:
    if index >= len(names):
        return ""
    return str(environ.get(names[index], "") or "").strip()
