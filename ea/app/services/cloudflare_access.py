from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

try:
    import jwt
except ModuleNotFoundError:  # pragma: no cover - exercised in dependency-light test envs
    jwt = None  # type: ignore[assignment]

from app.settings import AuthSettings

CF_ACCESS_JWT_HEADER = "cf-access-jwt-assertion"
CF_ACCESS_EMAIL_HEADER = "cf-access-authenticated-user-email"


@dataclass(frozen=True)
class CloudflareAccessConfig:
    team_domain: str
    issuer: str
    certs_url: str
    audiences: tuple[str, ...]


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


def access_config_from_settings(settings: AuthSettings | object) -> CloudflareAccessConfig | None:
    team_domain = str(getattr(settings, "cf_access_team_domain", "") or "").strip().lower().rstrip("/")
    certs_url = str(getattr(settings, "cf_access_certs_url", "") or "").strip()
    raw_audiences = tuple(getattr(settings, "cf_access_audiences", ()) or ())
    audiences = tuple(str(value or "").strip() for value in raw_audiences if str(value or "").strip())
    if not team_domain or not certs_url or not audiences:
        return None
    return CloudflareAccessConfig(
        team_domain=team_domain,
        issuer=f"https://{team_domain}",
        certs_url=certs_url,
        audiences=audiences,
    )


def resolve_access_identity(
    *,
    headers: Mapping[str, str],
    settings: AuthSettings,
) -> CloudflareAccessIdentity | None:
    config = access_config_from_settings(settings)
    if config is None:
        return None
    token = str(headers.get(CF_ACCESS_JWT_HEADER) or headers.get(CF_ACCESS_JWT_HEADER.title()) or "").strip()
    if not token:
        return None
    claims = _decode_access_jwt(token=token, config=config)
    email = str(claims.get("email") or headers.get(CF_ACCESS_EMAIL_HEADER) or headers.get(CF_ACCESS_EMAIL_HEADER.title()) or "").strip().lower()
    subject = str(claims.get("sub") or "").strip()
    if not email or not subject:
        raise RuntimeError("cloudflare_access_identity_incomplete")
    display_name = str(claims.get("name") or email).strip() or email
    idp = claims.get("idp")
    idp_name = ""
    if isinstance(idp, dict):
        idp_name = str(idp.get("type") or idp.get("id") or "").strip()
    return CloudflareAccessIdentity(
        principal_id=_principal_id_for_email(email),
        email=email,
        subject=subject,
        display_name=display_name,
        issuer=str(claims.get("iss") or config.issuer).strip() or config.issuer,
        idp_name=idp_name,
        audiences=tuple(_audience_values(claims.get("aud"))),
        claims={str(k): v for k, v in dict(claims).items()},
    )


def build_operator_id(identity: CloudflareAccessIdentity) -> str:
    digest = hashlib.sha256(identity.subject.encode("utf-8")).hexdigest()[:24]
    return f"cf-access:{digest}"


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


def _principal_id_for_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    candidate = f"cf-email:{normalized}"
    if len(candidate) <= 200:
        return candidate
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"cf-email:{digest}"


def _audience_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        values = [str(item).strip() for item in value if str(item).strip()]
        return tuple(values)
    return ()


def _require_jwt_support() -> Any:
    if jwt is None:
        raise RuntimeError("cloudflare_access_jwt_support_missing")
    return jwt


@lru_cache(maxsize=16)
def _jwks_client(certs_url: str) -> Any:
    jwt_module = _require_jwt_support()
    return jwt_module.PyJWKClient(certs_url)


def _decode_access_jwt(*, token: str, config: CloudflareAccessConfig) -> dict[str, object]:
    jwt_module = _require_jwt_support()
    signing_key = _jwks_client(config.certs_url).get_signing_key_from_jwt(token)
    claims = jwt_module.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=list(config.audiences),
        issuer=config.issuer,
        options={"require": ["exp", "iat", "sub", "aud", "iss"]},
    )
    return {str(k): v for k, v in dict(claims).items()}
