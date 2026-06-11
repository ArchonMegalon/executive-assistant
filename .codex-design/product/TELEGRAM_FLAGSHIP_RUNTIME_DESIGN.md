# Telegram Flagship Runtime Design

This local mirror records the Telegram runtime surface that EA must keep green for the flagship assistant lane.

## Runtime Contract

* Webhook ingest accepts the configured Telegram secret header without requiring global API-token auth.
* Bot registry entries may provide per-bot token, handle, secret, default principal, and unknown-chat auto-bind policy.
* Unknown Telegram chats auto-bind only to an explicit default principal from the active bot configuration or environment.
* `/start` replies confirm the bot handle and connected EA workspace.
* Video and document messages receive a short acknowledgement that asks for the next instruction instead of silently dropping the media turn.
* Photo turns preserve the existing analysis acknowledgement path.

## Verification

The runtime contract is covered by:

* `tests/e2e/test_telegram_bot_workflows.py`
* `tests/e2e/test_telegram_bot_outbound_workflows.py`
* `tests/test_telegram_media_prompt.py`
* `tests/test_providers_api_contracts.py`
