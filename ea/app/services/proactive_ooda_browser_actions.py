from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Mapping


BROWSER_ACTION_RECEIPT_SCHEMA = "proactive_ooda.browser_action_receipt.v1"

REVERSIBLE_BROWSER_OPERATIONS = (
    "authenticate",
    "search_site",
    "compare_options",
    "fill_cart",
    "remove_cart_item",
    "fill_unsent_form",
    "save_unsent_draft",
    "stage_booking_candidate",
    "collect_links",
    "capture_receipt",
)

IRREVERSIBLE_BROWSER_OPERATIONS = (
    "purchase",
    "pay",
    "book",
    "send_message",
    "send_external_message",
    "post",
    "cancel",
    "commit",
    "change_account_security",
)

HUMAN_HANDOFF_BLOCKERS = {
    "captcha_required",
    "cloudflare_not_cleared",
    "challenge_required",
    "turnstile_required",
    "mfa_code_required",
    "otp_required",
    "passkey_required",
    "human_verification_required",
    "interactive_login_required",
    "credentials_required",
    "session_expired",
}

_BLOCKER_ALIASES = {
    "captcha": "captcha_required",
    "recaptcha": "captcha_required",
    "cf_turnstile": "turnstile_required",
    "turnstile": "turnstile_required",
    "cloudflare": "cloudflare_not_cleared",
    "cloudflare_challenge": "cloudflare_not_cleared",
    "challenge": "challenge_required",
    "human_verification": "human_verification_required",
    "verify_human": "human_verification_required",
    "mfa": "mfa_code_required",
    "2fa": "mfa_code_required",
    "otp": "otp_required",
    "passkey": "passkey_required",
    "webauthn": "passkey_required",
    "login_required": "interactive_login_required",
    "interactive_login": "interactive_login_required",
    "missing_credentials": "credentials_required",
}

_CHALLENGE_MARKERS = (
    ("cloudflare_not_cleared", ("cloudflare", "just a moment", "checking your browser")),
    ("turnstile_required", ("turnstile", "cf-turnstile", "challenge-platform")),
    ("captcha_required", ("captcha", "recaptcha", "hcaptcha")),
    ("human_verification_required", ("verify you are human", "prove you are human", "human verification")),
    (
        "mfa_code_required",
        (
            "multi-factor",
            "two-factor",
            "2fa",
            "mfa",
            "verification code",
            "zwei-schritt-verifizierung",
            "bestätigungscode",
            "bestaetigungscode",
            "code eingeben",
        ),
    ),
    ("otp_required", ("one-time password", "otp code", "einmalpasswort")),
    ("passkey_required", ("passkey", "webauthn", "security key")),
)

_EMAIL_RE = re.compile(r"([A-Z0-9._%+\-]{1,64})@([A-Z0-9.\-]+\.[A-Z]{2,})", re.IGNORECASE)
_PHONE_ENDING_PATTERNS = (
    re.compile(r"auf\s+(\d{2,6})\s+endet", re.IGNORECASE),
    re.compile(r"ending(?:\s+in)?\s+(\d{2,6})", re.IGNORECASE),
    re.compile(r"ends(?:\s+in)?\s+(\d{2,6})", re.IGNORECASE),
    re.compile(r"phone(?:\s+number)?[^\d]{0,40}(\d{2,6})", re.IGNORECASE),
)


def browser_action_requested(
    *,
    stage_payload: Mapping[str, Any],
    input_contract: Mapping[str, Any] | None = None,
    work_type: str = "",
) -> bool:
    input_payload = dict(input_contract or {})
    browser_task = _browser_task(stage_payload=stage_payload, input_contract=input_payload)
    if browser_task:
        return True
    if _truthy(stage_payload.get("requires_browser_action")) or _truthy(input_payload.get("requires_browser_action")):
        return True
    if _truthy(stage_payload.get("requires_login")) or _truthy(input_payload.get("requires_login")):
        return True
    if _first_text(
        stage_payload.get("login_url"),
        input_payload.get("login_url"),
        stage_payload.get("browser_login_url"),
        input_payload.get("browser_login_url"),
    ):
        return True
    normalized_work = str(work_type or stage_payload.get("work_type") or input_payload.get("work_type") or "").strip()
    if normalized_work in {"prepare_cart_or_link", "prepare_booking_candidate"} and _first_text(
        stage_payload.get("site_url"),
        stage_payload.get("target_url"),
        stage_payload.get("target_site"),
        input_payload.get("site_url"),
        input_payload.get("target_url"),
        input_payload.get("target_site"),
    ):
        return True
    return False


def build_browser_action_receipt(
    packet: Mapping[str, Any],
    *,
    generated_at: str | None = None,
    execution_output: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    order = packet.get("safe_work_order") if isinstance(packet.get("safe_work_order"), Mapping) else {}
    input_contract = order.get("input_contract") if isinstance(order.get("input_contract"), Mapping) else {}
    stage = packet.get("stage") if isinstance(packet.get("stage"), Mapping) else {}
    stage_payload = stage.get("payload") if isinstance(stage.get("payload"), Mapping) else {}
    work_type = str(order.get("work_type") or stage_payload.get("work_type") or "").strip()
    if not browser_action_requested(stage_payload=stage_payload, input_contract=input_contract, work_type=work_type):
        return {}

    browser_task = _browser_task(stage_payload=stage_payload, input_contract=input_contract)
    execution = _mapping_value(
        execution_output
        or browser_task.get("execution")
        or stage_payload.get("browser_execution")
        or input_contract.get("browser_execution")
    )
    requested_operations = _requested_operations(
        browser_task=browser_task,
        stage_payload=stage_payload,
        input_contract=input_contract,
        work_type=work_type,
    )
    attempted_operations = _operation_list(
        execution.get("attempted_operations"),
        execution.get("operations_attempted"),
        stage_payload.get("browser_operations_attempted"),
    )
    if not attempted_operations and execution:
        attempted_operations = tuple(operation for operation in requested_operations if operation in REVERSIBLE_BROWSER_OPERATIONS)
    irreversible_attempts = tuple(
        operation
        for operation in (*attempted_operations, *_operation_list(execution.get("irreversible_actions_attempted")))
        if operation in IRREVERSIBLE_BROWSER_OPERATIONS
    )
    blocker_code = _normalize_blocker_code(
        _first_text(
            execution.get("blocker_code"),
            execution.get("error_code"),
            execution.get("challenge_code"),
            browser_task.get("blocker_code"),
            stage_payload.get("browser_blocker"),
            input_contract.get("browser_blocker"),
        )
    ) or _detect_blocker_from_text(execution, browser_task, stage_payload)
    artifact_kind = _artifact_kind(work_type=work_type, stage_payload=stage_payload, browser_task=browser_task)
    staged_artifact_present = _truthy(execution.get("staged_artifact_present")) or bool(
        _first_text(
            stage_payload.get("cart_url"),
            stage_payload.get("approval_url"),
            stage_payload.get("draft_text"),
            stage_payload.get("draft"),
            browser_task.get("staged_artifact_url"),
        )
    )
    status = _status(
        blocker_code=blocker_code,
        irreversible_attempts=irreversible_attempts,
        staged_artifact_present=staged_artifact_present,
        execution=execution,
    )
    challenge = _challenge_handoff_detail(
        blocker_code=blocker_code,
        execution=execution,
        browser_task=browser_task,
        stage_payload=stage_payload,
        input_contract=input_contract,
    )
    user_action_required = status in {
        "blocked_human_handoff_required",
        "blocked_credentials_required",
        "blocked_policy_violation",
    }
    credential_ref = _first_text(
        browser_task.get("credential_ref"),
        stage_payload.get("credential_ref"),
        input_contract.get("credential_ref"),
        stage_payload.get("credential_id"),
        input_contract.get("credential_id"),
    )
    username = _first_text(
        browser_task.get("login_email"),
        browser_task.get("username"),
        stage_payload.get("login_email"),
        stage_payload.get("browseract_username"),
        input_contract.get("login_email"),
        input_contract.get("browseract_username"),
    )
    target_url = _first_text(
        browser_task.get("target_url"),
        browser_task.get("site_url"),
        stage_payload.get("target_url"),
        stage_payload.get("site_url"),
        stage_payload.get("target_site"),
        input_contract.get("target_url"),
        input_contract.get("site_url"),
        input_contract.get("target_site"),
    )
    login_url = _first_text(
        browser_task.get("login_url"),
        stage_payload.get("login_url"),
        stage_payload.get("browser_login_url"),
        input_contract.get("login_url"),
        input_contract.get("browser_login_url"),
    )
    observed_account = _first_text(
        execution.get("observed_account"),
        execution.get("account_label"),
        execution.get("account_email"),
        browser_task.get("observed_account"),
    )
    expected_account = _first_text(
        browser_task.get("expected_account"),
        browser_task.get("expected_account_email"),
        stage_payload.get("expected_account"),
        stage_payload.get("expected_account_email"),
        input_contract.get("expected_account"),
        input_contract.get("expected_account_email"),
    )
    receipt_ref_material = "|".join(
        (
            str(packet.get("packet_ref") or packet.get("packet_id") or ""),
            target_url,
            login_url,
            status,
            blocker_code,
            str(generated_at or ""),
        )
    )
    receipt_id = f"browser-action-{_hash_value(receipt_ref_material)[:20]}"
    return {
        "schema": BROWSER_ACTION_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "receipt_ref": f"browser_action_receipt:{receipt_id}",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_packet_ref_hash": _hash_value(str(packet.get("packet_ref") or packet.get("packet_id") or "")),
        "status": status,
        "user_action_required": user_action_required,
        "work_type": work_type or "browser_action",
        "artifact_kind": artifact_kind,
        "target": {
            "site_host": _host(target_url or login_url),
            "target_url": target_url,
            "target_url_sha256": _hash_value(target_url),
            "login_url": login_url,
            "login_url_sha256": _hash_value(login_url),
        },
        "requested_operations": list(requested_operations),
        "attempted_operations": list(attempted_operations),
        "staged_artifact_present": staged_artifact_present,
        "handoff": {
            "required": user_action_required and blocker_code in HUMAN_HANDOFF_BLOCKERS,
            "blocker_code": blocker_code,
            "reason": _handoff_reason(blocker_code),
            "next_action": _next_action(blocker_code),
            "resume_instruction": _resume_instruction(blocker_code),
            "challenge": challenge,
            "keep_session_alive_requested": _truthy(
                browser_task.get("keep_session_alive"),
                default=True,
            ),
        },
        "account_context": {
            "verification_required": _truthy(
                browser_task.get("verify_account_context"),
                stage_payload.get("verify_account_context"),
                input_contract.get("verify_account_context"),
                default=True,
            ),
            "expected_account_sha256": _hash_value(expected_account),
            "observed_account_sha256": _hash_value(observed_account),
            "account_context_verified": bool(expected_account and observed_account and expected_account == observed_account)
            if expected_account or observed_account
            else False,
            "raw_account_values_stored": False,
        },
        "security": {
            "credential_ref_sha256": _hash_value(credential_ref),
            "username_sha256": _hash_value(username),
            "credential_ref_present": bool(credential_ref),
            "username_present": bool(username),
            "password_input_present": bool(
                _first_text(
                    browser_task.get("login_password"),
                    browser_task.get("login_password_present"),
                    browser_task.get("password"),
                    browser_task.get("password_present"),
                    stage_payload.get("login_password"),
                    stage_payload.get("login_password_present"),
                    stage_payload.get("browseract_password"),
                    stage_payload.get("browseract_password_present"),
                    input_contract.get("login_password"),
                    input_contract.get("login_password_present"),
                    input_contract.get("browseract_password"),
                    input_contract.get("browseract_password_present"),
                )
            ),
            "raw_credentials_stored": False,
            "secret_values_stored": False,
        },
        "policy": {
            "allowed_before_approval": list(REVERSIBLE_BROWSER_OPERATIONS),
            "forbidden_without_explicit_approval": list(IRREVERSIBLE_BROWSER_OPERATIONS),
            "irreversible_actions_require_explicit_approval": True,
            "irreversible_actions_attempted": list(irreversible_attempts),
        },
        "privacy": {
            "raw_credentials_stored": False,
            "raw_account_values_stored": False,
            "raw_cookie_or_session_stored": False,
        },
    }


def browser_action_user_prompt(receipt: Mapping[str, Any]) -> str:
    if not receipt:
        return ""
    handoff = receipt.get("handoff") if isinstance(receipt.get("handoff"), Mapping) else {}
    if bool(handoff.get("required")):
        reason = str(handoff.get("reason") or "The website needs a human step before EA can continue.").strip()
        challenge = handoff.get("challenge") if isinstance(handoff.get("challenge"), Mapping) else {}
        instruction = str(challenge.get("operator_instruction") or "").strip()
        detail = f" {instruction}" if instruction else ""
        return f"{reason}{detail} Complete the website step, then approve whether EA should resume the reversible browser task. No purchase, booking, send, post, cancel, payment, or commitment will happen without explicit approval."
    if str(receipt.get("status") or "") == "blocked_policy_violation":
        return "EA stopped because the browser task attempted an irreversible action boundary. Approve a revised reversible-only plan before resuming."
    return ""


def browser_action_handoff_required(receipt: Mapping[str, Any]) -> bool:
    return bool(receipt and receipt.get("user_action_required"))


def _browser_task(*, stage_payload: Mapping[str, Any], input_contract: Mapping[str, Any]) -> dict[str, Any]:
    for value in (stage_payload.get("browser_task"), input_contract.get("browser_task"), stage_payload.get("browser_action")):
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _mapping_value(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _truthy(*values: object, default: bool = False) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if not text:
            continue
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _operation_list(*values: object) -> tuple[str, ...]:
    operations: list[str] = []
    for value in values:
        for item in _string_list(value):
            normalized = item.strip().lower().replace("-", "_").replace(" ", "_")
            if normalized:
                operations.append(normalized)
    return tuple(dict.fromkeys(operations))


def _requested_operations(
    *,
    browser_task: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    input_contract: Mapping[str, Any],
    work_type: str,
) -> tuple[str, ...]:
    explicit = _operation_list(
        browser_task.get("operations"),
        browser_task.get("requested_operations"),
        stage_payload.get("browser_operations"),
        input_contract.get("browser_operations"),
    )
    if explicit:
        return explicit
    normalized = str(work_type or stage_payload.get("work_type") or "").strip()
    if normalized == "prepare_cart_or_link":
        return ("authenticate", "search_site", "compare_options", "fill_cart", "capture_receipt")
    if normalized == "prepare_booking_candidate":
        return ("authenticate", "search_site", "compare_options", "stage_booking_candidate", "capture_receipt")
    if normalized == "draft":
        return ("authenticate", "fill_unsent_form", "save_unsent_draft", "capture_receipt")
    return ("authenticate", "search_site", "compare_options", "capture_receipt")


def _normalize_blocker_code(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return ""
    return _BLOCKER_ALIASES.get(normalized, normalized)


def _detect_blocker_from_text(*values: object) -> str:
    fragments = " ".join(_collect_text(value) for value in values).lower()
    if not fragments:
        return ""
    for code, markers in _CHALLENGE_MARKERS:
        if any(marker in fragments for marker in markers):
            return code
    return ""


def _collect_text(value: object, *, limit: int = 128) -> str:
    parts: list[str] = []

    def visit(node: object) -> None:
        if len(parts) >= limit or node is None:
            return
        if isinstance(node, Mapping):
            for key, nested in node.items():
                if len(parts) >= limit:
                    break
                parts.append(str(key or "")[:120])
                visit(nested)
            return
        if isinstance(node, (list, tuple, set)):
            for nested in node:
                visit(nested)
            return
        text = str(node or "").strip()
        if text:
            parts.append(text[:500])

    visit(value)
    return " ".join(parts)


def _artifact_kind(*, work_type: str, stage_payload: Mapping[str, Any], browser_task: Mapping[str, Any]) -> str:
    explicit = _first_text(browser_task.get("artifact_kind"), stage_payload.get("artifact_kind"))
    if explicit:
        return explicit
    if work_type == "prepare_cart_or_link":
        return "cart"
    if work_type == "prepare_booking_candidate":
        return "booking_candidate"
    if work_type == "draft":
        return "unsent_draft"
    return "browser_result"


def _status(
    *,
    blocker_code: str,
    irreversible_attempts: tuple[str, ...],
    staged_artifact_present: bool,
    execution: Mapping[str, Any],
) -> str:
    explicit = str(execution.get("status") or "").strip().lower()
    if irreversible_attempts:
        return "blocked_policy_violation"
    if blocker_code in {"credentials_required"}:
        return "blocked_credentials_required"
    if blocker_code in HUMAN_HANDOFF_BLOCKERS:
        return "blocked_human_handoff_required"
    if explicit in {"staged_for_user_decision", "completed_reversible", "blocked_human_handoff_required"}:
        return explicit
    if staged_artifact_present:
        return "staged_for_user_decision"
    if execution:
        return "attempted_no_staged_artifact"
    return "planned"


def _handoff_reason(blocker_code: str) -> str:
    if blocker_code == "cloudflare_not_cleared":
        return "The website is holding EA at a Cloudflare or browser security check."
    if blocker_code in {"captcha_required", "turnstile_required", "human_verification_required", "challenge_required"}:
        return "The website requires a human verification step."
    if blocker_code in {"mfa_code_required", "otp_required", "passkey_required"}:
        return "The website requires a one-time login or device verification step."
    if blocker_code == "credentials_required":
        return "EA needs scoped credentials before it can continue this website task."
    if blocker_code == "session_expired":
        return "The authenticated browser session expired before EA could finish the reversible task."
    return "The website needs a human browser handoff before EA can continue."


def _next_action(blocker_code: str) -> str:
    if blocker_code in HUMAN_HANDOFF_BLOCKERS:
        return "complete_browser_handoff_then_resume_ooda_task"
    return ""


def _resume_instruction(blocker_code: str) -> str:
    if blocker_code in {"mfa_code_required", "otp_required", "passkey_required"}:
        return "Complete the verification in the live browser session, then let EA resume from the current page."
    if blocker_code in {"cloudflare_not_cleared", "captcha_required", "turnstile_required", "human_verification_required", "challenge_required"}:
        return "Complete the human check in the live browser session, then let EA resume from the current page."
    if blocker_code == "credentials_required":
        return "Provide or approve a scoped credential reference, then rerun the browser task."
    return "Resume only after the operator confirms the browser state is ready."


def _challenge_handoff_detail(
    *,
    blocker_code: str,
    execution: Mapping[str, Any],
    browser_task: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    input_contract: Mapping[str, Any],
) -> dict[str, Any]:
    if blocker_code not in {"mfa_code_required", "otp_required", "passkey_required"}:
        return {}
    fragments = _challenge_text_fragments(
        execution=execution,
        browser_task=browser_task,
        stage_payload=stage_payload,
        input_contract=input_contract,
    )
    available_channels = _challenge_channels(
        fragments=fragments,
        explicit_values=(
            execution.get("challenge_channel"),
            execution.get("challenge_channels"),
            execution.get("verification_channel"),
            execution.get("verification_channels"),
            browser_task.get("challenge_channel"),
            browser_task.get("challenge_channels"),
            stage_payload.get("challenge_channel"),
            input_contract.get("challenge_channel"),
        ),
        blocker_code=blocker_code,
    )
    destination_hint = _sanitize_destination_hint(
        _first_text(
            execution.get("destination_hint"),
            execution.get("challenge_destination_hint"),
            browser_task.get("destination_hint"),
            browser_task.get("challenge_destination_hint"),
            stage_payload.get("destination_hint"),
            input_contract.get("destination_hint"),
        ),
        fragments=fragments,
    )
    primary_channel = _primary_challenge_channel(
        explicit_value=_first_text(
            execution.get("challenge_channel"),
            execution.get("verification_channel"),
            browser_task.get("challenge_channel"),
            stage_payload.get("challenge_channel"),
            input_contract.get("challenge_channel"),
        ),
        available_channels=available_channels,
        blocker_code=blocker_code,
        destination_hint=destination_hint,
    )
    operator_instruction = _challenge_operator_instruction(
        blocker_code=blocker_code,
        primary_channel=primary_channel,
        available_channels=available_channels,
        destination_hint=destination_hint,
    )
    return {
        "primary_channel": primary_channel,
        "available_channels": list(available_channels),
        "destination_hint": destination_hint,
        "operator_instruction": operator_instruction,
        "raw_destination_stored": False,
    }


def _challenge_text_fragments(
    *,
    execution: Mapping[str, Any],
    browser_task: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    input_contract: Mapping[str, Any],
) -> str:
    sources = (
        _collect_text(execution, limit=256),
        _first_text(
            browser_task.get("challenge_text"),
            browser_task.get("challenge_page_text"),
            stage_payload.get("challenge_text"),
            input_contract.get("challenge_text"),
            stage_payload.get("browser_challenge_text"),
            input_contract.get("browser_challenge_text"),
        ),
        _first_text(
            browser_task.get("destination_hint"),
            browser_task.get("challenge_destination_hint"),
            stage_payload.get("destination_hint"),
            input_contract.get("destination_hint"),
        ),
        _first_text(
            browser_task.get("challenge_channel"),
            browser_task.get("challenge_channels"),
            stage_payload.get("challenge_channel"),
            input_contract.get("challenge_channel"),
        ),
    )
    return " ".join(part for part in sources if part)


def _challenge_channels(
    *,
    fragments: str,
    explicit_values: tuple[object, ...],
    blocker_code: str,
) -> tuple[str, ...]:
    channels: list[str] = []
    for value in explicit_values:
        channels.extend(_normalized_challenge_channels(value))
    lowered = fragments.lower()
    keyword_map = (
        ("whatsapp", ("whatsapp",)),
        ("email", ("e-mail", "email")),
        ("phone", ("telefonnummer", "phone number", "text message", "sms", "code sent to a phone")),
        ("authenticator_app", ("authenticator app", "authenticator", "otp app", "code generator")),
        ("passkey", ("passkey", "webauthn", "security key")),
    )
    for channel, markers in keyword_map:
        if any(marker in lowered for marker in markers):
            channels.append(channel)
    if blocker_code == "passkey_required":
        channels.append("passkey")
    if blocker_code in {"mfa_code_required", "otp_required"} and destination_hint_like_phone(lowered):
        channels.append("phone")
    return tuple(dict.fromkeys(channel for channel in channels if channel))


def _normalized_challenge_channels(value: object) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        raw = [segment.strip() for segment in re.split(r"[,\n;/]+", value) if segment.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(item or "").strip() for item in value if str(item or "").strip()]
    else:
        raw = []
    for item in raw:
        normalized = item.lower().replace("-", "_").replace(" ", "_")
        if normalized in {"sms", "text_message", "phone", "phone_code", "phone_number"}:
            values.append("phone")
        elif normalized in {"email", "e_mail", "mail"}:
            values.append("email")
        elif normalized in {"whatsapp", "wa"}:
            values.append("whatsapp")
        elif normalized in {"authenticator", "authenticator_app", "otp_app", "totp"}:
            values.append("authenticator_app")
        elif normalized in {"passkey", "webauthn", "security_key"}:
            values.append("passkey")
    return values


def destination_hint_like_phone(value: str) -> bool:
    return any(pattern.search(value) for pattern in _PHONE_ENDING_PATTERNS)


def _sanitize_destination_hint(explicit_value: str, *, fragments: str) -> str:
    explicit = str(explicit_value or "").strip()
    if explicit:
        masked = _masked_destination_from_text(explicit)
        if masked:
            return masked
    return _masked_destination_from_text(fragments)


def _masked_destination_from_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in _PHONE_ENDING_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"phone ending {match.group(1)}"
    email_match = _EMAIL_RE.search(text)
    if email_match:
        local = email_match.group(1)
        domain = email_match.group(2).lower()
        prefix = (local[:1] or "*").lower()
        return f"email {prefix}***@{domain}"
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 7:
        return f"phone ending {digits[-4:]}"
    return ""


def _primary_challenge_channel(
    *,
    explicit_value: str,
    available_channels: tuple[str, ...],
    blocker_code: str,
    destination_hint: str,
) -> str:
    explicit = _normalized_challenge_channels(explicit_value)
    if explicit:
        return explicit[0]
    if blocker_code == "passkey_required":
        return "passkey"
    if destination_hint.startswith("phone ending"):
        return "phone"
    if destination_hint.startswith("email "):
        return "email"
    if available_channels:
        return available_channels[0]
    if blocker_code in {"mfa_code_required", "otp_required"}:
        return "verification_code"
    return ""


def _challenge_operator_instruction(
    *,
    blocker_code: str,
    primary_channel: str,
    available_channels: tuple[str, ...],
    destination_hint: str,
) -> str:
    if blocker_code == "passkey_required" or primary_channel == "passkey":
        return "Complete the passkey or device approval step in the live browser session."
    if primary_channel == "authenticator_app":
        instruction = "Provide the verification code from the authenticator app."
    elif primary_channel == "email":
        instruction = (
            f"Provide the verification code sent to {destination_hint}."
            if destination_hint
            else "Provide the verification code sent by email."
        )
    elif primary_channel == "phone":
        instruction = (
            f"Provide the verification code sent to the {destination_hint}."
            if destination_hint
            else "Provide the verification code sent to the linked phone."
        )
    else:
        instruction = "Provide the one-time verification code from the website challenge."
    if "whatsapp" in available_channels and primary_channel != "whatsapp":
        instruction += " The page also offers WhatsApp code delivery."
    return instruction


def _host(value: str) -> str:
    try:
        return urllib.parse.urlparse(value).netloc.lower()
    except Exception:
        return ""


def _hash_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
