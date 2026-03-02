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

    payment_rails: dict = __import__("dataclasses").field(default_factory=lambda: {"default": "auth_workflow", "enabled": ["auth_workflow", "scan_to_pay", "manual_details"], "fallback_order": ["auth_workflow", "scan_to_pay", "manual_details"]})
    undetectable_api_key: str | None = None
    markupgo_template_master: str | None = None
    markupgo_template_coach: str | None = None
    onboarding_enabled: bool = False
    whatsapp_pairing_enabled: bool = False
    connector_agent_mode_enabled: bool = False
    self_host_connector_mode_enabled: bool = False
    operator_surface_enabled: bool = False
    evidence_vault_enabled: bool = False
    dead_letter_encryption_required: bool = False
    pointer_first_storage_required: bool = False
    regulated_copy_mode_disabled_by_default: bool = True
    actions_enabled: bool = False
    high_risk_actions_disabled_by_default: bool = True
    pre_exec_validation_required: bool = False
    personalization_enabled: bool = False
    sticky_dislikes_enabled: bool = False
    exploration_slot_percent: int = 10
    proactive_enabled: bool = False
    pre_llm_filter_required: bool = True
    planner_global_token_budget: int = 0

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
        magixx_api_key=os.environ.get("MAGIXX_API_KEY"),
        onboarding_enabled=_bool("ONBOARDING_ENABLED", False),
        whatsapp_pairing_enabled=_bool("WHATSAPP_PAIRING_ENABLED", False),
        connector_agent_mode_enabled=_bool("CONNECTOR_AGENT_MODE_ENABLED", False),
        self_host_connector_mode_enabled=_bool("SELF_HOST_CONNECTOR_MODE_ENABLED", False),
        operator_surface_enabled=_bool("OPERATOR_SURFACE_ENABLED", False),
        evidence_vault_enabled=_bool("EVIDENCE_VAULT_ENABLED", False),
        dead_letter_encryption_required=_bool("DEAD_LETTER_ENCRYPTION_REQUIRED", False),
        pointer_first_storage_required=_bool("POINTER_FIRST_STORAGE_REQUIRED", False),
        regulated_copy_mode_disabled_by_default=_bool("REGULATED_COPY_MODE_DISABLED_BY_DEFAULT", True),
        actions_enabled=_bool("ACTIONS_ENABLED", False),
        high_risk_actions_disabled_by_default=_bool("HIGH_RISK_ACTIONS_DISABLED_BY_DEFAULT", True),
        pre_exec_validation_required=_bool("PRE_EXEC_VALIDATION_REQUIRED", False),
        personalization_enabled=_bool("PERSONALIZATION_ENABLED", False),
        sticky_dislikes_enabled=_bool("STICKY_DISLIKES_ENABLED", False),
        exploration_slot_percent=int(os.environ.get("EXPLORATION_SLOT_PERCENT", "10")),
        proactive_enabled=_bool("PROACTIVE_ENABLED", False),
        pre_llm_filter_required=_bool("PRE_LLM_FILTER_REQUIRED", True),
        planner_global_token_budget=int(os.environ.get("PLANNER_GLOBAL_TOKEN_BUDGET", "0")),
    )

settings = load_settings()

TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
EA_ATTACHMENTS_DIR = settings.attachments_dir
