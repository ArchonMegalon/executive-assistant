import os
from dataclasses import dataclass

def _bool(name: str, default: bool=False) -> bool:
    v = os.environ.get(name)
    if v is None: return default
    return str(v).strip().lower() in ("1","true","yes","on")

@dataclass(frozen=True)
class Settings:
    role: str
    tz: str
    tenants_yaml: str
    places_yaml: str
    attachments_dir: str
    docker_sock: str
    tg_outbox_enabled: bool
    telegram_bot_token: str
    gemini_api_key: str | None
    litellm_base_url: str | None
    litellm_api_key: str | None
    intent_engine: str
    llm_chain: str
    llm_model: str
    apixdrive_shared_secret: str | None
    ea_ingest_token: str | None
    ea_operator_token: str | None
    markupgo_base_url: str
    markupgo_api_key: str | None
    magixx_base_url: str | None
    magixx_api_key: str | None
    one_min_ai_api_key: str | None
    gog_keyring_password: str | None
    calendar_ics_secret: str | None
    calendar_default_duration_min: int
    calendar_loop_interval_s: int
    calendar_remind_soon_min: int
    calendar_leave_buffer_min: int
    calendar_lookahead_hours: int
    location_poll_interval_s: int
    default_location_cooldown_min: int

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
    avomap_enabled: bool = False
    avomap_browseract_workflow: str = "avomap.render_trip_video"
    avomap_recent_place_days: int = 30
    avomap_max_per_person_per_day: int = 1
    avomap_daily_render_budget: int = 3
    avomap_default_orientation: str = "portrait"
    avomap_duration_target_sec: int = 20
    avomap_late_attach_window_sec: int = 900
    avomap_min_novelty_distance_km: int = 100

def load_settings() -> Settings:
    return Settings(
        role=(os.environ.get("EA_ROLE") or "monolith").lower(),
        tz=os.environ.get("TZ", "Europe/Vienna"),
        tenants_yaml=os.environ.get("EA_TENANTS_YAML", "/app/app/tenants.yml"),
        places_yaml=os.environ.get("EA_PLACES_YAML", "/config/places.yml"),
        attachments_dir=os.environ.get("EA_ATTACHMENTS_DIR", "/attachments"),
        docker_sock=os.environ.get("DOCKER_SOCK", "/var/run/docker.sock"),
        tg_outbox_enabled=_bool("EA_TG_OUTBOX", True),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        litellm_base_url=os.environ.get("LITELLM_BASE_URL"),
        litellm_api_key=os.environ.get("LITELLM_API_KEY"),
        intent_engine=os.environ.get("EA_INTENT_ENGINE", "rules_llm_strict_json"),
        llm_chain=os.environ.get("EA_LLM_CHAIN", "magixx:o3-mini"),
        llm_model=os.environ.get("EA_LLM_MODEL", "gpt-4o-mini"),
        apixdrive_shared_secret=os.environ.get("APIXDRIVE_SHARED_SECRET"),
        ea_ingest_token=os.environ.get("EA_INGEST_TOKEN"),
        ea_operator_token=os.environ.get("EA_OPERATOR_TOKEN"),
        markupgo_base_url=os.environ.get("MARKUPGO_BASE_URL", "https://api.markupgo.com/api/v1"),
        markupgo_api_key=os.environ.get("MARKUPGO_API_KEY"),
        magixx_base_url=os.environ.get("MAGIXX_BASE_URL"),
        magixx_api_key=os.environ.get("MAGIXX_API_KEY"),
        one_min_ai_api_key=os.environ.get("ONE_MIN_AI_API_KEY"),
        gog_keyring_password=os.environ.get("GOG_KEYRING_PASSWORD") or os.environ.get("EA_GOG_KEYRING_PASSWORD"),
        calendar_ics_secret=os.environ.get("EA_CALENDAR_ICS_SECRET"),
        calendar_default_duration_min=int(os.environ.get("EA_CALENDAR_DEFAULT_DURATION_MIN", "30")),
        calendar_loop_interval_s=int(os.environ.get("EA_CALENDAR_LOOP_INTERVAL_S", "30")),
        calendar_remind_soon_min=int(os.environ.get("EA_CALENDAR_REMIND_SOON_MIN", "60")),
        calendar_leave_buffer_min=int(os.environ.get("EA_CALENDAR_LEAVE_BUFFER_MIN", "15")),
        calendar_lookahead_hours=int(os.environ.get("EA_CALENDAR_LOOKAHEAD_HOURS", "24")),
        location_poll_interval_s=int(os.environ.get("EA_LOCATION_POLL_INTERVAL_S", "20")),
        default_location_cooldown_min=int(os.environ.get("EA_DEFAULT_LOCATION_COOLDOWN_MIN", "30")),
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
        avomap_enabled=_bool("AVOMAP_ENABLED", False),
        avomap_browseract_workflow=os.environ.get("AVOMAP_BROWSERACT_WORKFLOW", "avomap.render_trip_video"),
        avomap_recent_place_days=int(os.environ.get("AVOMAP_RECENT_PLACE_DAYS", "30")),
        avomap_max_per_person_per_day=int(os.environ.get("AVOMAP_MAX_PER_PERSON_PER_DAY", "1")),
        avomap_daily_render_budget=int(os.environ.get("AVOMAP_DAILY_RENDER_BUDGET", "3")),
        avomap_default_orientation=os.environ.get("AVOMAP_DEFAULT_ORIENTATION", "portrait"),
        avomap_duration_target_sec=int(os.environ.get("AVOMAP_DURATION_TARGET_SEC", "20")),
        avomap_late_attach_window_sec=int(os.environ.get("AVOMAP_LATE_ATTACH_WINDOW_SEC", "900")),
        avomap_min_novelty_distance_km=int(os.environ.get("AVOMAP_MIN_NOVELTY_DISTANCE_KM", "100")),
    )

settings = load_settings()

TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
EA_ATTACHMENTS_DIR = settings.attachments_dir
