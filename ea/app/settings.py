from __future__ import annotations

import os
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
class StorageSettings:
    backend: str
    database_url: str
    artifacts_dir: str


@dataclass(frozen=True)
class AuthSettings:
    api_token: str

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
    def storage_backend(self) -> str:
        return self.storage.backend

    @property
    def database_url(self) -> str:
        return self.storage.database_url

    # Backward compatibility for prior naming.
    @property
    def ledger_backend(self) -> str:
        return self.storage.backend


def get_settings() -> Settings:
    app_name = (os.environ.get("EA_APP_NAME") or "ea-rewrite").strip() or "ea-rewrite"
    app_version = (os.environ.get("EA_APP_VERSION") or "0.3.0").strip() or "0.3.0"
    role = (os.environ.get("EA_ROLE") or "api").strip().lower() or "api"
    host = (os.environ.get("EA_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    port = max(1, min(65535, _to_int(os.environ.get("EA_PORT") or "8090", 8090)))
    log_level = (os.environ.get("EA_LOG_LEVEL") or "INFO").strip().upper() or "INFO"
    tenant_id = (os.environ.get("EA_TENANT_ID") or "default").strip() or "default"

    legacy_backend = (os.environ.get("EA_LEDGER_BACKEND") or "").strip().lower()
    storage_backend = (os.environ.get("EA_STORAGE_BACKEND") or legacy_backend or "auto").strip().lower() or "auto"
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    artifacts_dir = (os.environ.get("EA_ARTIFACTS_DIR") or "/tmp/ea_artifacts").strip() or "/tmp/ea_artifacts"

    api_token = (os.environ.get("EA_API_TOKEN") or "").strip()
    max_rewrite_chars = max(1, _to_int(os.environ.get("EA_MAX_REWRITE_CHARS") or "20000", 20000))
    approval_required_chars = max(1, _to_int(os.environ.get("EA_APPROVAL_THRESHOLD_CHARS") or "5000", 5000))
    approval_ttl_minutes = max(1, _to_int(os.environ.get("EA_APPROVAL_TTL_MINUTES") or "120", 120))
    default_list_limit = max(1, min(500, _to_int(os.environ.get("EA_CHANNEL_DEFAULT_LIMIT") or "50", 50)))

    return Settings(
        core=CoreSettings(
            app_name=app_name,
            app_version=app_version,
            role=role,
            host=host,
            port=port,
            log_level=log_level,
            tenant_id=tenant_id,
        ),
        storage=StorageSettings(
            backend=storage_backend,
            database_url=database_url,
            artifacts_dir=artifacts_dir,
        ),
        auth=AuthSettings(api_token=api_token),
        policy=PolicySettings(
            max_rewrite_chars=max_rewrite_chars,
            approval_required_chars=approval_required_chars,
            approval_ttl_minutes=approval_ttl_minutes,
        ),
        channels=ChannelSettings(default_list_limit=default_list_limit),
    )
