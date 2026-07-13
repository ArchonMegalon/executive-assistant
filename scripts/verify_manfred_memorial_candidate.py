#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_smoke.v1"
CONTRIBUTION_RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_contribution.v1"
PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
PRIVATE_AUDIO_RELPATH = "audio/hanusch-hospital-visit-enhanced.mp3"
BROWSER_ZERO_COUNT_FIELDS = (
    "automatic_provider_requests",
    "automatic_websockets",
    "external_requests",
    "failed_requests",
    "page_errors",
    "http_errors",
)
VERIFIER_REQUEST_HEADERS = {
    "User-Agent": "EA-Memorial-Launch-Verifier/1.0",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
}


def _http_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    hostname = str(parsed.hostname or "").casefold()
    if scheme not in {"http", "https"} or not hostname:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def _is_same_origin_http_error(
    *, base_url: str, response_url: str, status: int
) -> bool:
    return (
        int(status) >= 400
        and _http_origin(base_url) is not None
        and _http_origin(response_url) == _http_origin(base_url)
    )


def _has_exact_zero_counts(payload: dict[str, object]) -> bool:
    return all(
        type(payload.get(field)) is int and payload[field] == 0
        for field in BROWSER_ZERO_COUNT_FIELDS
    )


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    expected: set[int] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    data = None
    request_headers = dict(headers or {})
    # Cloudflare may reject urllib's default user agent. Keep this automation
    # identity explicit and stable; callers may add headers but cannot replace
    # the verifier identity or its bounded response preference.
    request_headers.update(VERIFIER_REQUEST_HEADERS)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = int(response.status)
            body = response.read(2 * 1024 * 1024 + 1)
            response_headers = {
                key.lower(): value for key, value in response.headers.items()
            }
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(2 * 1024 * 1024 + 1)
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
    allowed = expected or {200}
    if status not in allowed:
        raise RuntimeError(f"candidate_http_status_unexpected:{path}:{status}")
    if len(body) > 2 * 1024 * 1024:
        raise RuntimeError(f"candidate_http_response_too_large:{path}")
    return status, body, response_headers


def _json_body(body: bytes, *, path: str) -> dict[str, object]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"candidate_http_json_invalid:{path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"candidate_http_json_invalid:{path}")
    return payload


def _contains_forbidden_recipient_field(value: object) -> bool:
    forbidden = {
        "recipient",
        "recipient_id",
        "recipient_address",
        "phone_number",
        "email",
    }
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in forbidden
            or _contains_forbidden_recipient_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_recipient_field(item) for item in value)
    return False


def _wait_for_health(base_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "candidate_health_timeout"
    while time.monotonic() < deadline:
        try:
            _request(base_url, "/healthz")
            return
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            last_error = str(exc)[:160]
            time.sleep(2)
    raise RuntimeError(last_error)


def _chromium_launch_executable(browser_type: object) -> str:
    configured = str(os.environ.get("EA_PLAYWRIGHT_CHROMIUM_EXECUTABLE") or "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError("candidate_browser_executable_invalid")
        return str(path)

    bundled = Path(str(getattr(browser_type, "executable_path", "") or "")).expanduser()
    if bundled.is_file():
        return str(bundled.resolve())
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise RuntimeError("candidate_browser_executable_unavailable")


def audit_browser_surface(base_url: str) -> dict[str, object]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("candidate_browser_runtime_unavailable") from exc

    original_tmpdir = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = "/tmp"
    requested_urls: list[str] = []
    failed_requests: list[str] = []
    page_errors: list[str] = []
    http_errors: list[str] = []
    websocket_urls: list[str] = []
    browser = None
    try:
        with sync_playwright() as playwright:
            executable_path = _chromium_launch_executable(playwright.chromium)
            launch_options: dict[str, object] = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-proxy-server",
                ],
            }
            launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(
                **launch_options,
            )
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.on("request", lambda request: requested_urls.append(request.url))
            page.on(
                "requestfailed", lambda request: failed_requests.append(request.url)
            )
            page.on(
                "response",
                lambda response: (
                    http_errors.append(response.url)
                    if _is_same_origin_http_error(
                        base_url=base_url,
                        response_url=response.url,
                        status=response.status,
                    )
                    else None
                ),
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)[:200]))
            page.on("websocket", lambda websocket: websocket_urls.append(websocket.url))
            response = page.goto(
                f"{base_url.rstrip('/')}/memorials/manfred",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            if response is None or response.status != 200:
                raise RuntimeError("candidate_browser_page_unavailable")
            page.wait_for_timeout(900)
            page.evaluate(
                """() => document.getElementById("memorial-conversation")?.click()"""
            )
            page.wait_for_timeout(150)

            provider_work_paths = {
                "/memorials/manfred/warmup",
                "/memorials/manfred/warmup-status",
                "/memorials/manfred/speech-transcribe",
                "/memorials/manfred/speech-synthesize",
                "/memorials/manfred/conversation-turn",
                "/memorials/manfred/realtime",
            }
            automatic_provider_requests = sorted(
                {
                    urlparse(url).path
                    for url in requested_urls
                    if urlparse(url).path in provider_work_paths
                }
            )
            if automatic_provider_requests:
                raise RuntimeError("candidate_browser_automatic_provider_work_detected")
            if websocket_urls:
                raise RuntimeError("candidate_browser_automatic_websocket_detected")
            external_requests = sorted(
                {
                    url
                    for url in requested_urls
                    if _http_origin(url) != _http_origin(base_url)
                }
            )
            if external_requests:
                raise RuntimeError("candidate_browser_external_request_detected")
            if http_errors:
                raise RuntimeError("candidate_browser_same_origin_http_error")
            if failed_requests or page_errors:
                raise RuntimeError("candidate_browser_runtime_error")

            accessibility = page.evaluate(
                """() => {
                  const visible = (element) => {
                    const style = getComputedStyle(element);
                    return !element.hidden && style.display !== "none" && style.visibility !== "hidden";
                  };
                  const controls = Array.from(document.querySelectorAll("input, textarea, button"))
                    .filter((element) => visible(element) && String(element.type || "") !== "hidden");
                  const unlabeled = controls.filter((element) => {
                    if (element.tagName === "BUTTON") {
                      return !String(element.innerText || element.getAttribute("aria-label") || element.title || "").trim();
                    }
                    return !(element.labels && element.labels.length) && !String(element.getAttribute("aria-label") || "").trim();
                  }).map((element) => element.id || element.name || element.tagName);
                  const story = document.getElementById("memorial-story");
                  const conversation = document.getElementById("memorial-conversation-region");
                  const storyRect = story?.getBoundingClientRect();
                  const conversationRect = conversation?.getBoundingClientRect();
                  const conversationPosition = conversation ? getComputedStyle(conversation).position : "missing";
                  return {
                    lang: document.documentElement.lang,
                    main_count: document.querySelectorAll("main").length,
                    h1_count: document.querySelectorAll("h1").length,
                    skip_link_count: document.querySelectorAll("a.skip-link").length,
                    unlabeled_controls: unlabeled,
                    consent_checked: Boolean(document.getElementById("memorial-contribution-consent")?.checked),
                    personal_memory_checked: Boolean(document.getElementById("memorial-personal-memory-optin")?.checked),
                    conversation_enabled: !Boolean(document.getElementById("memorial-conversation")?.disabled),
                    conversation_label: String(document.getElementById("memorial-conversation")?.textContent || "").trim(),
                    voice_release: String(document.getElementById("memorial-conversation-region")?.dataset.voiceRelease || ""),
                    guidance: String(document.querySelector("#memorial-conversation-region .hero-guidance")?.textContent || "").trim(),
                    text_form_visible: visible(document.getElementById("memorial-text-turn-form")),
                    text_input_focused: document.activeElement === document.getElementById("memorial-text-turn-input"),
                    text_placeholder: String(document.getElementById("memorial-text-turn-input")?.getAttribute("placeholder") || ""),
                    voice_autostart_hidden: !visible(document.getElementById("memorial-autostart-optin")?.closest(".conversation-toggle")),
                    old_impersonation_copy_visible: document.body.innerText.includes("Was möchtest du Manfred fragen?") || document.body.innerText.includes("synthetischen Manfred-Stimme"),
                    reduced_motion: matchMedia("(prefers-reduced-motion: reduce)").matches,
                    horizontal_overflow: Math.max(0, document.documentElement.scrollWidth - innerWidth),
                    conversation_position: conversationPosition,
                    conversation_after_story: Boolean(
                      storyRect && conversationRect && conversationRect.top >= storyRect.bottom - 1
                    ),
                    conversation_overlap: Math.max(
                      0,
                      Math.round((storyRect?.bottom || 0) - (conversationRect?.top || 0)),
                    ),
                  };
                }"""
            )
            if (
                not str(accessibility.get("lang") or "").lower().startswith("de")
                or accessibility.get("main_count") != 1
                or accessibility.get("h1_count") != 1
                or int(accessibility.get("skip_link_count") or 0) < 2
                or accessibility.get("unlabeled_controls")
                or accessibility.get("consent_checked") is True
                or accessibility.get("personal_memory_checked") is True
                or accessibility.get("conversation_enabled") is not True
                or accessibility.get("conversation_label")
                != "Schriftliche Frage stellen"
                or accessibility.get("voice_release") != "blocked"
                or "ist nicht Manfred" not in str(accessibility.get("guidance") or "")
                or "spricht nicht für ihn"
                not in str(accessibility.get("guidance") or "")
                or accessibility.get("text_form_visible") is not True
                or accessibility.get("text_input_focused") is not True
                or accessibility.get("text_placeholder")
                != "Welche belegte Erinnerung möchtest du einordnen?"
                or accessibility.get("voice_autostart_hidden") is not True
                or accessibility.get("old_impersonation_copy_visible") is True
                or accessibility.get("reduced_motion") is not True
                or int(accessibility.get("horizontal_overflow") or 0) > 1
                or accessibility.get("conversation_position")
                in {"fixed", "sticky", "missing"}
                or accessibility.get("conversation_after_story") is not True
                or int(accessibility.get("conversation_overlap") or 0) > 1
            ):
                raise RuntimeError("candidate_browser_accessibility_contract_failed")

            navigation = page.evaluate(
                """() => {
                  const entry = performance.getEntriesByType("navigation")[0];
                  return entry ? {
                    dom_content_loaded_ms: Math.round(entry.domContentLoadedEventEnd),
                    load_event_ms: Math.round(entry.loadEventEnd),
                    transfer_bytes: Number(entry.transferSize || 0),
                  } : {};
                }"""
            )
            dom_loaded_ms = int(navigation.get("dom_content_loaded_ms") or 0)
            load_event_ms = int(navigation.get("load_event_ms") or 0)
            if dom_loaded_ms <= 0 or dom_loaded_ms > 5000 or load_event_ms > 7000:
                raise RuntimeError("candidate_browser_performance_contract_failed")

            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(100)
            desktop_layout = page.evaluate(
                """() => {
                  const story = document.getElementById("memorial-story");
                  const conversation = document.getElementById("memorial-conversation-region");
                  const storyRect = story?.getBoundingClientRect();
                  const conversationRect = conversation?.getBoundingClientRect();
                  return {
                    overflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
                    conversation_position: conversation ? getComputedStyle(conversation).position : "missing",
                    conversation_after_story: Boolean(
                      storyRect && conversationRect && conversationRect.top >= storyRect.bottom - 1
                    ),
                    conversation_overlap: Math.max(
                      0,
                      Math.round((storyRect?.bottom || 0) - (conversationRect?.top || 0)),
                    ),
                  };
                }"""
            )
            desktop_overflow = int(desktop_layout.get("overflow") or 0)
            if (
                desktop_overflow > 1
                or desktop_layout.get("conversation_position")
                in {"fixed", "sticky", "missing"}
                or desktop_layout.get("conversation_after_story") is not True
                or int(desktop_layout.get("conversation_overlap") or 0) > 1
            ):
                raise RuntimeError("candidate_browser_desktop_layout_contract_failed")
            context.close()
            browser.close()
            browser = None
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                browser.close()
        if original_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = original_tmpdir
    return {
        "status": "pass",
        "mobile_viewport": "390x844",
        "desktop_viewport": "1440x900",
        "reduced_motion": True,
        "horizontal_overflow_px": 0,
        "conversation_in_document_flow": True,
        "conversation_overlap_px": 0,
        "unlabeled_controls": 0,
        "automatic_provider_requests": 0,
        "automatic_websockets": 0,
        "external_requests": 0,
        "failed_requests": 0,
        "page_errors": 0,
        "http_errors": 0,
        "dom_content_loaded_ms": dom_loaded_ms,
        "load_event_ms": load_event_ms,
        "transfer_bytes": int(navigation.get("transfer_bytes") or 0),
    }


def _atomic_private_json(path: Path, payload: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _submit_contribution(base_url: str, receipt_path: Path) -> dict[str, object]:
    marker = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    status, body, _headers = _request(
        base_url,
        "/memorials/manfred/contributions",
        method="POST",
        payload={
            "title": f"Candidate restart proof {marker}",
            "body": "Synthetic candidate-only durability proof; never publish.",
            "source_label": "Automated isolated candidate check",
            "publication_consent": False,
        },
        expected={201},
    )
    response = _json_body(body, path="/memorials/manfred/contributions")
    contribution_id = str(response.get("contribution_id") or "").strip()
    manage_token = str(response.get("manage_token") or "").strip()
    if (
        not contribution_id
        or not manage_token
        or response.get("visibility") != "private"
    ):
        raise RuntimeError("candidate_contribution_receipt_invalid")
    _atomic_private_json(
        receipt_path,
        {
            "schema": CONTRIBUTION_RECEIPT_SCHEMA,
            "contribution_id": contribution_id,
            "manage_token": manage_token,
            "submitted_at": response.get("submitted_at"),
            "status": "pending_restart_withdrawal",
        },
    )
    return {
        "submitted": True,
        "withdrawn": False,
        "http_status": status,
        "private_by_default": True,
        "publication_consent": False,
    }


def _withdraw_contribution(base_url: str, receipt_path: Path) -> dict[str, object]:
    if not receipt_path.is_file() or os.path.islink(receipt_path):
        raise RuntimeError("candidate_contribution_receipt_missing")
    if (receipt_path.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("candidate_contribution_receipt_permissions_invalid")
    payload = _json_body(receipt_path.read_bytes(), path="contribution_receipt")
    if payload.get("schema") != CONTRIBUTION_RECEIPT_SCHEMA:
        raise RuntimeError("candidate_contribution_receipt_invalid")
    contribution_id = str(payload.get("contribution_id") or "").strip()
    manage_token = str(payload.get("manage_token") or "").strip()
    status, body, _headers = _request(
        base_url,
        f"/memorials/manfred/contributions/{contribution_id}/withdraw",
        method="POST",
        payload={"reason": "Candidate restart durability proof completed"},
        headers={"x-memorial-contribution-token": manage_token},
    )
    response = _json_body(body, path="contribution_withdraw")
    if (
        response.get("status") != "withdrawn"
        or response.get("public_removed") is not True
    ):
        raise RuntimeError("candidate_contribution_withdrawal_invalid")
    receipt_path.unlink()
    return {
        "submitted": True,
        "withdrawn": True,
        "http_status": status,
        "private_by_default": True,
        "survived_candidate_restart": True,
        "manage_token_retained": False,
    }


def verify_candidate(
    *,
    base_url: str,
    public_origin: str,
    wait_seconds: int,
    submit_receipt: Path | None,
    withdraw_receipt: Path | None,
    browser_audit: bool = False,
) -> dict[str, object]:
    _wait_for_health(base_url, wait_seconds)
    checks: list[str] = ["healthz"]
    _request(base_url, "/health/live?probe=memorial")
    checks.append("memorial_health_probe")

    _status, body, headers = _request(base_url, "/memorials/manfred.json")
    manifest = _json_body(body, path="/memorials/manfred.json")
    if str(manifest.get("slug") or "") != "manfred":
        raise RuntimeError("candidate_memorial_slug_mismatch")
    encoded_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    forbidden_markers = (
        PRIVATE_CONTEXT_FILENAME,
        PRIVATE_AUDIO_RELPATH,
        "manage_token_hash",
        "memory_principal_id",
    )
    if any(marker in encoded_manifest for marker in forbidden_markers):
        raise RuntimeError("candidate_public_manifest_private_data_exposed")
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        raise RuntimeError("candidate_public_headers_incomplete")
    checks.append("public_projection")

    _request(base_url, "/memorials/manfred", method="HEAD")
    _request(base_url, "/memorials/manfred/archive.json")
    _request(base_url, "/memorials/manfred/app.webmanifest")
    _request(base_url, "/memorials/manfred/service-worker.js")
    checks.extend(["head_surface_no_prewarm", "archive", "pwa"])

    _request(
        base_url,
        f"/memorials/files/manfred/{PRIVATE_AUDIO_RELPATH}",
        expected={404},
    )
    _request(
        base_url,
        "/memorial_data/public_memorials/manfred/memorial.json",
        expected={401, 403, 404},
    )
    checks.extend(["private_audio_denied", "raw_manifest_denied"])

    _status, narrator_body, _headers = _request(
        base_url,
        "/memorials/manfred/chat",
        method="POST",
        payload={"question": "Antworte mir künftig knapp und ohne Wiederholungen."},
    )
    narrator = _json_body(narrator_body, path="/memorials/manfred/chat")
    narrator_contract = dict(narrator.get("narrator") or {})
    narrator_answer = str(narrator.get("answer") or "").strip().lower()
    if (
        narrator.get("mode") != "memorial_source_grounded_narrator"
        or narrator_contract.get("synthetic") is not True
        or narrator_contract.get("source_grounded") is not True
        or narrator_contract.get("is_memorial_person") is not False
        or narrator_contract.get("speaks_for_memorial_person") is not False
        or "quellengebundene gedenkbegleiter" not in narrator_answer
        or "ich antworte" in narrator_answer
        or "ich bin manfred" in narrator_answer
    ):
        raise RuntimeError("candidate_narrator_boundary_invalid")
    checks.append("source_grounded_narrator_boundary")

    _status, blocked_tts_body, _headers = _request(
        base_url,
        "/memorials/manfred/speech-synthesize",
        method="POST",
        payload={"text": "Diese Sprachfunktion darf nicht starten."},
        expected={409},
    )
    blocked_tts = _json_body(
        blocked_tts_body,
        path="/memorials/manfred/speech-synthesize",
    )
    if str(blocked_tts.get("detail") or "") != "memorial_voice_release_not_verified":
        raise RuntimeError("candidate_voice_release_boundary_invalid")
    checks.append("voice_provider_boundary_blocked")

    _status, share_body, _headers = _request(
        base_url,
        "/memorials/manfred/share-drafts",
        method="POST",
        payload={
            "public_origin": public_origin,
            "channels": ["telegram", "whatsapp"],
            "include_archive": True,
            "include_audio": False,
        },
    )
    share_packet = _json_body(share_body, path="share-drafts")
    serialized_share = json.dumps(share_packet, ensure_ascii=False, sort_keys=True)
    if PRIVATE_AUDIO_RELPATH in serialized_share or _contains_forbidden_recipient_field(
        share_packet
    ):
        raise RuntimeError("candidate_share_packet_private_data_exposed")
    checks.append("unsent_public_share_drafts")

    contribution = {
        "submitted": False,
        "withdrawn": False,
        "survived_candidate_restart": False,
    }
    if submit_receipt is not None and withdraw_receipt is not None:
        raise ValueError("candidate_contribution_mode_conflict")
    if submit_receipt is not None:
        contribution = _submit_contribution(base_url, submit_receipt)
        checks.append("private_contribution_submitted")
    elif withdraw_receipt is not None:
        contribution = _withdraw_contribution(base_url, withdraw_receipt)
        checks.append("private_contribution_withdrawn_after_restart")

    browser_evidence: dict[str, object] = {"status": "not_run"}
    if browser_audit:
        browser_evidence = audit_browser_surface(base_url)
        if browser_evidence.get("status") != "pass" or not _has_exact_zero_counts(
            browser_evidence
        ):
            raise RuntimeError("candidate_browser_provider_boundary_invalid")
        checks.append("browser_provider_websocket_boundary")

    return {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "checked_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "base_url": base_url,
        "checks": checks,
        "provider_calls_performed": False,
        "page_get_performed": browser_audit,
        "operator_surface_used": False,
        "private_audio_served": False,
        "contribution": contribution,
        "browser_audit": browser_evidence,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run provider-free HTTP checks against an isolated Manfred candidate."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18090")
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument(
        "--browser-audit",
        action="store_true",
        help="Exercise the rendered surface and fail on provider requests or WebSockets.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--submit-contribution-receipt", default="")
    modes.add_argument("--withdraw-contribution-receipt", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = verify_candidate(
            base_url=str(args.base_url).rstrip("/"),
            public_origin=str(args.public_origin).rstrip("/"),
            wait_seconds=max(1, min(600, int(args.wait_seconds))),
            submit_receipt=Path(args.submit_contribution_receipt)
            if args.submit_contribution_receipt
            else None,
            withdraw_receipt=Path(args.withdraw_contribution_receipt)
            if args.withdraw_contribution_receipt
            else None,
            browser_audit=bool(args.browser_audit),
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        urllib.error.URLError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {"schema": RECEIPT_SCHEMA, "status": "fail", "error": str(exc)[:200]},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
