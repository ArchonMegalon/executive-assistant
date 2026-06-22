from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from app.settings import AuthSettings


@dataclass(frozen=True)
class CloudflareAccessIdentity:
    principal_id: str
    email: str
    subject: str
    display_name: str
    issuer: str
    idp_name: str
    audiences: tuple[str, ...]
    claims: dict[str, object]


def resolve_access_identity(*, headers: Mapping[str, str], settings: AuthSettings) -> CloudflareAccessIdentity | None:
    return None


def build_operator_id(identity: CloudflareAccessIdentity) -> str:
    return identity.principal_id


def build_operator_notes(identity: CloudflareAccessIdentity) -> str:
    return json.dumps(
        {
            "source": "cloudflare_access",
            "email": identity.email,
            "subject": identity.subject,
            "issuer": identity.issuer,
            "idp": identity.idp_name,
            "audiences": list(identity.audiences),
        },
        sort_keys=True,
    )
