from __future__ import annotations

CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS = ("binding_id", "channel", "recipient", "content")
CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS = ("metadata", "idempotency_key")
CONNECTOR_DISPATCH_ALLOWED_CHANNELS = ("email", "slack", "telegram")
CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY = "optional_passthrough"
CONNECTOR_CHANNEL_SCOPE_REQUIREMENTS = {
    "email": ("mail.send", "email.send", "send.mail"),
    "slack": ("chat.write", "chat.post", "slack.send", "slack.post"),
    "telegram": ("telegram.send", "telegram.post", "send.telegram"),
}


class ToolExecutionError(RuntimeError):
    pass
