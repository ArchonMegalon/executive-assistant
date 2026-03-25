from __future__ import annotations

from app.services.google_oauth import build_google_oauth_start


class GoogleOAuthService:
    def __init__(self) -> None:
        pass

    def build_start(self, principal_id: str, scope_bundle: str, redirect_uri_override: str | None = None):
        return build_google_oauth_start(
            principal_id=principal_id,
            scope_bundle=scope_bundle,
            redirect_uri_override=redirect_uri_override,
        )
