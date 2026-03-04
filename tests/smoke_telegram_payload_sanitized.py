from __future__ import annotations

BANNED_CHAT_SUBSTRINGS = [
    "MarkupGo API HTTP 400",
    "statusCode",
    "FST_ERR_VALIDATION",
    "OODA Diagnostic",
    "Traceback",
    "\"code\":",
]


def assert_telegram_payload_sanitized(rendered_message: str) -> None:
    for token in BANNED_CHAT_SUBSTRINGS:
        assert token not in rendered_message, f"Leaked debug/error token: {token}"


if __name__ == "__main__":
    # Self-check for script plumbing.
    assert_telegram_payload_sanitized("Delivered in simplified mode today.")
    print("PASS: telegram payload sanitization smoke")
