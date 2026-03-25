from __future__ import annotations

from app.repositories.onboarding_state import OnboardingStateRepository
from app.services.google_oauth_service import GoogleOAuthService
from app.services.provider_registry import ProviderRegistryService
from app.services.telegram_onboarding_service import TelegramBotOnboardingService, TelegramIdentityService
from app.services.tool_runtime import ToolRuntimeService
from app.services.whatsapp_onboarding_service import (
    ChatExportIngestionService,
    WhatsAppEmbeddedSignupService,
    WhatsAppHistoryImportService,
)
from app.settings import Settings


class AssistantOnboardingService:
    def __init__(
        self,
        *,
        onboarding_repo: OnboardingStateRepository,
        provider_registry: ProviderRegistryService,
        tool_runtime: ToolRuntimeService,
        settings: Settings,
    ) -> None:
        self._repo = onboarding_repo
        self._provider_registry = provider_registry
        self._tool_runtime = tool_runtime
        self._settings = settings
        self._google_oauth = GoogleOAuthService()
        self._telegram_identity = TelegramIdentityService(tool_runtime=tool_runtime)
        self._telegram_bot = TelegramBotOnboardingService(tool_runtime=tool_runtime)
        self._whatsapp_business = WhatsAppEmbeddedSignupService(tool_runtime=tool_runtime)
        self._whatsapp_import = WhatsAppHistoryImportService(tool_runtime=tool_runtime)
        self._chat_export_ingest = ChatExportIngestionService(tool_runtime=tool_runtime)
