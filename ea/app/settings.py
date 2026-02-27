import os
from dataclasses import dataclass

def _bool(name: str, default: bool=False) -> bool:
    v = os.environ.get(name)
    if v is None: return default
    return str(v).strip().lower() in ("1","true","yes","on")

@dataclass(frozen=True)
class Settings:
    role: str
    tenants_yaml: str
    places_yaml: str
    attachments_dir: str
    tg_outbox_enabled: bool
    telegram_bot_token: str
    gemini_api_key: str | None
    litellm_base_url: str | None
    litellm_api_key: str | None
    intent_engine: str
    llm_chain: str
    markupgo_base_url: str
    markupgo_api_key: str | None
    magixx_base_url: str | None
    magixx_api_key: str | None

def load_settings() -> Settings:
    return Settings(
        role=(os.environ.get("EA_ROLE") or "monolith").lower(),
        tenants_yaml=os.environ.get("EA_TENANTS_YAML", "/app/app/tenants.yml"),
        places_yaml=os.environ.get("EA_PLACES_YAML", "/config/places.yml"),
        attachments_dir=os.environ.get("EA_ATTACHMENTS_DIR", "/attachments"),
        tg_outbox_enabled=_bool("EA_TG_OUTBOX", True),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        litellm_base_url=os.environ.get("LITELLM_BASE_URL"),
        litellm_api_key=os.environ.get("LITELLM_API_KEY"),
        intent_engine=os.environ.get("EA_INTENT_ENGINE", "rules_llm_strict_json"),
        llm_chain=os.environ.get("EA_LLM_CHAIN", "magixx:o3-mini"),
        markupgo_base_url=os.environ.get("MARKUPGO_BASE_URL", "https://api.markupgo.com/api/v1"),
        markupgo_api_key=os.environ.get("MARKUPGO_API_KEY"),
        magixx_base_url=os.environ.get("MAGIXX_BASE_URL"),
        magixx_api_key=os.environ.get("MAGIXX_API_KEY")
    )

settings = load_settings()

TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
EA_ATTACHMENTS_DIR = settings.attachments_dir
