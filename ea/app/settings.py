from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, replace


def _to_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def _env_truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CoreSettings:
    app_name: str
    app_version: str
    role: str
    host: str
    port: int
    log_level: str
    tenant_id: str


@dataclass(frozen=True)
class RuntimeSettings:
    mode: str


@dataclass(frozen=True)
class StorageSettings:
    backend: str
    database_url: str
    artifacts_dir: str


@dataclass(frozen=True)
class AuthSettings:
    api_token: str
    default_principal_id: str
    allow_loopback_no_auth: bool = False
    cf_access_team_domain: str = ""
    cf_access_audiences: tuple[str, ...] = ()
    cf_access_certs_url: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_token.strip()) or self.cf_access_enabled

    @property
    def cf_access_enabled(self) -> bool:
        return bool(self.cf_access_team_domain.strip()) and bool(self.cf_access_audiences)


@dataclass(frozen=True)
class PolicySettings:
    max_rewrite_chars: int
    approval_required_chars: int
    approval_ttl_minutes: int


@dataclass(frozen=True)
class ChannelSettings:
    default_list_limit: int


@dataclass(frozen=True)
class FeatureSettings:
    public_side_surfaces_enabled: bool = True


@dataclass(frozen=True)
class RuntimeProfile:
    mode: str
    storage_backend: str
    durability: str
    auth_mode: str
    principal_source: str
    database_required: bool
    database_configured: bool
    source_backend: str

    @property
    def caller_principal_header_allowed(self) -> bool:
        return self.principal_source in {
            "caller_header_or_default",
            "authenticated_header_or_default",
            "authenticated_header",
        }

    @property
    def caller_principal_header_requires_authentication(self) -> bool:
        return self.principal_source in {
            "authenticated_header_or_default",
            "authenticated_header",
        }

    @property
    def default_principal_fallback_allowed(self) -> bool:
        return self.principal_source in {
            "caller_header_or_default",
            "authenticated_header_or_default",
            "access_identity_or_default",
            "default_principal",
        }


@dataclass(frozen=True)
class Settings:
    core: CoreSettings
    runtime: RuntimeSettings
    storage: StorageSettings
    auth: AuthSettings
    policy: PolicySettings
    channels: ChannelSettings
    features: FeatureSettings

    @property
    def app_name(self) -> str:
        return self.core.app_name

    @property
    def app_version(self) -> str:
        return self.core.app_version

    @property
    def role(self) -> str:
        return self.core.role

    @property
    def host(self) -> str:
        return self.core.host

    @property
    def port(self) -> int:
        return self.core.port

    @property
    def log_level(self) -> str:
        return self.core.log_level

    @property
    def tenant_id(self) -> str:
        return self.core.tenant_id

    @property
    def runtime_mode(self) -> str:
        return self.runtime.mode

    @property
    def storage_backend(self) -> str:
        return self.storage.backend

    @property
    def database_url(self) -> str:
        return self.storage.database_url

    @property
    def ledger_backend(self) -> str:
        return self.storage.backend

    @property
    def storage_fallback_allowed(self) -> bool:
        return not is_prod_mode(self.runtime.mode)

    @property
    def public_side_surfaces_enabled(self) -> bool:
        return self.features.public_side_surfaces_enabled


def _runtime_mode(raw: str) -> str:
    mode = str(raw or "").strip().lower() or "dev"
    if mode not in {"dev", "test", "prod"}:
        return "dev"
    return mode


def is_prod_mode(raw: str | None) -> bool:
    return str(raw or "").strip().lower() == "prod"


def _database_url(settings: object) -> str:
    direct = getattr(settings, "database_url", None)
    if direct is not None:
        value = str(direct or "").strip()
        if value:
            return value
    storage = getattr(settings, "storage", None)
    if storage is None:
        return str(direct or "").strip()
    return str(getattr(storage, "database_url", "") or "").strip()


def resolve_runtime_profile(settings: Settings) -> RuntimeProfile:
    source_backend = str(settings.storage.backend or "auto").strip().lower() or "auto"
    database_url = _database_url(settings)
    auth_mode = "anonymous_dev"
    api_token = str(getattr(settings.auth, "api_token", "") or "").strip()
    cf_access_enabled = bool(getattr(settings.auth, "cf_access_enabled", False))
    if api_token and cf_access_enabled:
        auth_mode = "token_or_access"
    elif api_token:
        auth_mode = "token"
    elif cf_access_enabled:
        auth_mode = "access"
    if is_prod_mode(settings.runtime.mode):
        return RuntimeProfile(
            mode="prod",
            storage_backend="postgres",
            durability="durable",
            auth_mode=auth_mode,
            principal_source="authenticated_header" if auth_mode in {"token", "token_or_access"} else "access_identity",
            database_required=True,
            database_configured=bool(database_url),
            source_backend=source_backend,
        )
    storage_backend = "postgres" if source_backend in {"postgres"} else "memory"
    durability = "durable" if storage_backend == "postgres" else "ephemeral"
    if source_backend == "auto" and database_url:
        storage_backend = "postgres"
        durability = "durable"
    if auth_mode in {"token", "token_or_access"}:
        principal_source = "authenticated_header_or_default"
    elif auth_mode == "access":
        principal_source = "access_identity_or_default"
    else:
        principal_source = "caller_header_or_default"
    return RuntimeProfile(
        mode=settings.runtime.mode,
        storage_backend=storage_backend,
        durability=durability,
        auth_mode=auth_mode,
        principal_source=principal_source,
        database_required=storage_backend == "postgres",
        database_configured=bool(database_url),
        source_backend=source_backend,
    )


def settings_with_storage_backend(settings: Settings, backend: str) -> Settings:
    normalized = str(backend or "").strip().lower() or "memory"
    return replace(settings, storage=replace(settings.storage, backend=normalized))


def ensure_storage_fallback_allowed(
    settings: Settings,
    reason: str,
    exc: Exception | None = None,
) -> None:
    if settings.storage_fallback_allowed:
        return
    if exc is not None:
        message = str(exc)
        if message.startswith("EA_RUNTIME_MODE=prod forbids memory fallback"):
            raise exc
    message = f"EA_RUNTIME_MODE=prod forbids memory fallback({reason})"
    if exc is not None:
        raise RuntimeError(message) from exc
    raise RuntimeError(message)


def ensure_prod_api_token_configured(settings: Settings) -> None:
    if not is_prod_mode(settings.runtime.mode):
        return
    if str(settings.auth.api_token or "").strip():
        return
    if bool(getattr(settings.auth, "cf_access_enabled", False)):
        return
    raise RuntimeError("EA_RUNTIME_MODE=prod requires EA_API_TOKEN or Cloudflare Access auth to be set")


def validate_startup_settings(settings: Settings) -> RuntimeProfile:
    ensure_prod_api_token_configured(settings)
    profile = resolve_runtime_profile(settings)
    if is_prod_mode(settings.runtime.mode):
        if profile.storage_backend != "postgres":
            raise RuntimeError("EA_RUNTIME_MODE=prod requires a durable postgres runtime profile")
        if not _database_url(settings):
            raise RuntimeError("EA_RUNTIME_MODE=prod requires DATABASE_URL")
    return profile


def get_settings() -> Settings:
    app_name = (os.environ.get("EA_APP_NAME") or "ea-rewrite").strip() or "ea-rewrite"
    app_version = (os.environ.get("EA_APP_VERSION") or "0.3.0").strip() or "0.3.0"
    role = (os.environ.get("EA_ROLE") or "api").strip().lower() or "api"
    host = (os.environ.get("EA_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    port = max(1, min(65535, _to_int(os.environ.get("EA_PORT") or "8090", 8090)))
    log_level = (os.environ.get("EA_LOG_LEVEL") or "INFO").strip().upper() or "INFO"
    tenant_id = (os.environ.get("EA_TENANT_ID") or "default").strip() or "default"
    runtime_mode = _runtime_mode(os.environ.get("EA_RUNTIME_MODE") or "dev")

    legacy_backend = (os.environ.get("EA_LEDGER_BACKEND") or "").strip().lower()
    configured_storage_backend = (os.environ.get("EA_STORAGE_BACKEND") or "").strip().lower()
    if legacy_backend and not configured_storage_backend:
        warnings.warn(
            "EA_LEDGER_BACKEND is deprecated; use EA_STORAGE_BACKEND instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    elif legacy_backend and configured_storage_backend:
        warnings.warn(
            "EA_LEDGER_BACKEND is deprecated and ignored when EA_STORAGE_BACKEND is set.",
            DeprecationWarning,
            stacklevel=2,
        )
    storage_backend = (configured_storage_backend or legacy_backend or "auto").strip().lower() or "auto"
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    artifacts_dir = (os.environ.get("EA_ARTIFACTS_DIR") or "/tmp/ea_artifacts").strip() or "/tmp/ea_artifacts"

    api_token = (os.environ.get("EA_API_TOKEN") or "").strip()
    default_principal_id = (os.environ.get("EA_DEFAULT_PRINCIPAL_ID") or "local-user").strip() or "local-user"
    allow_loopback_no_auth = _env_truthy(os.environ.get("EA_ALLOW_LOOPBACK_NO_AUTH"))
    cf_access_team_domain = (os.environ.get("EA_CF_ACCESS_TEAM_DOMAIN") or "").strip().lower().rstrip("/")
    raw_cf_access_aud = (os.environ.get("EA_CF_ACCESS_AUD") or "").strip()
    cf_access_audiences = tuple(
        value for value in {part.strip() for part in raw_cf_access_aud.split(",") if part.strip()}
    )
    cf_access_certs_url = (os.environ.get("EA_CF_ACCESS_CERTS_URL") or "").strip()
    if not cf_access_certs_url and cf_access_team_domain:
        cf_access_certs_url = f"https://{cf_access_team_domain}/cdn-cgi/access/certs"
    max_rewrite_chars = max(1, _to_int(os.environ.get("EA_MAX_REWRITE_CHARS") or "20000", 20000))
    approval_required_chars = max(1, _to_int(os.environ.get("EA_APPROVAL_THRESHOLD_CHARS") or "5000", 5000))
    approval_ttl_minutes = max(1, _to_int(os.environ.get("EA_APPROVAL_TTL_MINUTES") or "120", 120))
    default_list_limit = max(1, min(500, _to_int(os.environ.get("EA_CHANNEL_DEFAULT_LIMIT") or "50", 50)))
    raw_public_side_surfaces_enabled = os.environ.get("EA_ENABLE_PUBLIC_SIDE_SURFACES")
    public_side_surfaces_enabled = (
        True if raw_public_side_surfaces_enabled is None else _env_truthy(raw_public_side_surfaces_enabled)
    )

    settings = Settings(
        core=CoreSettings(
            app_name=app_name,
            app_version=app_version,
            role=role,
            host=host,
            port=port,
            log_level=log_level,
            tenant_id=tenant_id,
        ),
        runtime=RuntimeSettings(mode=runtime_mode),
        storage=StorageSettings(
            backend=storage_backend,
            database_url=database_url,
            artifacts_dir=artifacts_dir,
        ),
        auth=AuthSettings(
            api_token=api_token,
            default_principal_id=default_principal_id,
            allow_loopback_no_auth=allow_loopback_no_auth,
            cf_access_team_domain=cf_access_team_domain,
            cf_access_audiences=cf_access_audiences,
            cf_access_certs_url=cf_access_certs_url,
        ),
        policy=PolicySettings(
            max_rewrite_chars=max_rewrite_chars,
            approval_required_chars=approval_required_chars,
            approval_ttl_minutes=approval_ttl_minutes,
        ),
        channels=ChannelSettings(default_list_limit=default_list_limit),
        features=FeatureSettings(public_side_surfaces_enabled=public_side_surfaces_enabled),
    )
    ensure_prod_api_token_configured(settings)
    return settings
