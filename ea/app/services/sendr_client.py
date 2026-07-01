from __future__ import annotations

import os
from dataclasses import dataclass


class SendrDisabled(RuntimeError):
    """Raised when code tries to use Sendr while the lane is disabled."""


@dataclass(frozen=True)
class SendrClient:
    api_token: str
    workspace_id: str = ""
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "SendrClient":
        return cls(
            api_token=os.getenv("SENDR_API_TOKEN", ""),
            workspace_id=os.getenv("SENDR_WORKSPACE_ID", ""),
            enabled=os.getenv("EA_SENDR_API_ENABLED", "0") == "1",
        )

    def require_enabled(self) -> None:
        if not self.enabled:
            raise SendrDisabled("sendr_api_disabled")
        if not self.api_token:
            raise SendrDisabled("sendr_api_token_missing")

    def create_campaign_preview(self, packet: dict[str, object]) -> dict[str, object]:
        self.require_enabled()
        raise NotImplementedError("sendr_live_api_adapter_not_implemented")
