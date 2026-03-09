from __future__ import annotations

import os
import warnings
from dataclasses import dataclass


def _to_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return default


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

    @property
    def enabled(self) -> bool:
        return bool(self.api_token.strip())


@dataclass(frozen=True)
class PolicySettings:
    max_rewrite_chars: int
    approval_required_chars: int
    approval_ttl_minutes: int


@dataclass(frozen=True)
class ChannelSettings:
    default_list_limit: int


@dataclass(frozen=True)
class Settings:
    core: CoreSettings
    runtime: RuntimeSettings
    storage: StorageSettings
    auth: AuthSettings
    policy: PolicySettings
    channels: ChannelSettings

    # Compatibility helpers for existing call sites.
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

    # Backward compatibility for prior naming.
    @property
    def ledger_backend(self) -> str:
        return self.storage.backend

    @property
    def storage_fallback_allowed(self) -> bool:
        return self.runtime.mode != "prod"


def _runtime_mode(raw: str) -> str:
    mode = str(raw or "").strip().lower() or "dev"
    if mode not in {"dev", "test", "prod"}:
        return "dev"
    return mode


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
    if settings.runtime.mode != "prod":
        return
    if str(settings.auth.api_token or "").strip():
        return
    raise RuntimeError("EA_RUNTIME_MODE=prod requires EA_API_TOKEN to be set")


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
    max_rewrite_chars = max(1, _to_int(os.environ.get("EA_MAX_REWRITE_CHARS") or "20000", 20000))
    approval_required_chars = max(1, _to_int(os.environ.get("EA_APPROVAL_THRESHOLD_CHARS") or "5000", 5000))
    approval_ttl_minutes = max(1, _to_int(os.environ.get("EA_APPROVAL_TTL_MINUTES") or "120", 120))
    default_list_limit = max(1, min(500, _to_int(os.environ.get("EA_CHANNEL_DEFAULT_LIMIT") or "50", 50)))

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
        auth=AuthSettings(api_token=api_token, default_principal_id=default_principal_id),
        policy=PolicySettings(
            max_rewrite_chars=max_rewrite_chars,
            approval_required_chars=approval_required_chars,
            approval_ttl_minutes=approval_ttl_minutes,
        ),
        channels=ChannelSettings(default_list_limit=default_list_limit),
    )
    ensure_prod_api_token_configured(settings)
    return settings
