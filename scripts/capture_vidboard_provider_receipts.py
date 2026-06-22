#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_APP_ROOT = ROOT / "ea"
if EA_APP_ROOT.as_posix() not in sys.path:
    sys.path.insert(0, EA_APP_ROOT.as_posix())

from app.services.browseract_ui_template_catalog import browseract_ui_template_spec


DEFAULT_OUT_DIR = Path(os.environ.get("EA_AVATAR_PRESENTER_PROVIDER_OUT_DIR") or ROOT / "ea" / "_completion" / "avatar_presenter_provider")
DEFAULT_RECEIPT_DIR = DEFAULT_OUT_DIR / "receipts"
DEFAULT_CAPTURE_PATH = DEFAULT_OUT_DIR / "vidboard_workspace_capture.generated.json"
DEFAULT_HANDOFF_PATH = DEFAULT_OUT_DIR / "vidboard_operator_handoff.generated.json"
WORKER_SCRIPT = ROOT / "scripts" / "browseract_template_service_worker.py"
ENV_FILES = (ROOT / "ea" / ".env", ROOT / ".env")
RECEIPT_TYPES = (
    "login_capture",
    "commercial_use_terms_receipt",
    "watermark_export_receipt",
    "lip_sync_review_receipt",
    "viseme_quality_receipt",
    "privacy_terms_receipt",
    "source_data_boundary_receipt",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _env_value(name: str) -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue
        for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return ""


def _login_email(value: str) -> str:
    return value.strip() or _env_value("VIDBOARD_LOGIN_EMAIL")


def _login_password(value: str) -> str:
    return value.strip() or _env_value("VIDBOARD_LOGIN_PASSWORD")


def _run_worker(*, login_email: str, login_password: str, page_url: str, timeout_seconds: int) -> dict[str, object]:
    runtime_inputs = {
        "browseract_username": login_email,
        "browseract_password": login_password,
    }
    if page_url.strip():
        runtime_inputs["page_url"] = page_url.strip()
    packet = {
        "template_key": "vidboard_workspace_reader",
        "workflow_spec_json": browseract_ui_template_spec("vidboard_workspace_reader"),
        "browseract_username": login_email,
        "browseract_password": login_password,
        "page_url": page_url.strip(),
        "runtime_inputs_json": runtime_inputs,
        "timeout_seconds": timeout_seconds,
    }
    completed = subprocess.run(
        ["python3", str(WORKER_SCRIPT)],
        input=json.dumps(packet, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=max(240, timeout_seconds + 120),
        check=False,
    )
    raw = str(completed.stdout or "").strip()
    if not raw:
        detail = str(completed.stderr or "").strip()
        raise RuntimeError(f"vidboard_capture_worker_empty_output:{detail[:400]}")
    last_line = raw.splitlines()[-1].strip()
    try:
        payload = json.loads(last_line)
    except Exception as exc:
        raise RuntimeError(f"vidboard_capture_worker_non_json:{last_line[:400]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("vidboard_capture_worker_invalid_output")
    payload["_worker_exit_code"] = int(completed.returncode)
    return payload


def _capture_summary(result: dict[str, object]) -> dict[str, object]:
    render_status = str(result.get("render_status") or "").strip().lower()
    ui_failure_code = str(result.get("ui_failure_code") or "").strip().lower()
    structured = dict(result.get("structured_output_json") or {})
    body_text = str(result.get("body_text") or result.get("output_text") or result.get("raw_text") or "").strip()
    title = str(structured.get("page_title") or result.get("title") or result.get("result_title") or "").strip()
    source_url = str(structured.get("url") or result.get("url") or result.get("editor_url") or "").strip()
    warnings = list(structured.get("warnings") or result.get("warnings") or [])
    errors = list(structured.get("errors") or result.get("errors") or [])
    authenticated = render_status in {"completed", "completed_with_warnings"} and ui_failure_code == "" and bool(source_url or title or body_text)
    return {
        "captured_at": _utc_now(),
        "provider_key": "vidboard",
        "template_key": "vidboard_workspace_reader",
        "authenticated_workspace_detected": authenticated,
        "render_status": render_status,
        "ui_failure_code": ui_failure_code,
        "title": title,
        "url": source_url,
        "warnings": warnings,
        "errors": errors,
        "body_excerpt": body_text[:800],
        "asset_path": str(result.get("asset_path") or "").strip(),
        "screenshot_path": str(structured.get("screenshot_path") or "").strip(),
        "html_path": str(structured.get("html_path") or "").strip(),
        "auth_handoff": dict(structured.get("auth_handoff") or {}),
        "raw_result": result,
    }


def _failed_capture_summary(detail: str) -> dict[str, object]:
    normalized = str(detail or "").strip()
    failure_code = "capture_failed"
    if "captcha_required" in normalized:
        failure_code = "captcha_required"
    elif "invalid_credentials" in normalized:
        failure_code = "invalid_credentials"
    return {
        "captured_at": _utc_now(),
        "provider_key": "vidboard",
        "template_key": "vidboard_workspace_reader",
        "authenticated_workspace_detected": False,
        "render_status": "failed",
        "ui_failure_code": failure_code,
        "title": "",
        "url": "",
        "warnings": [],
        "errors": [normalized[:1200]],
        "body_excerpt": "",
        "asset_path": "",
        "screenshot_path": "",
        "html_path": "",
        "auth_handoff": {},
        "raw_result": {"error": normalized[:1200]},
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_payload(
    receipt_type: str,
    capture_summary: dict[str, object],
    *,
    capture_path: Path,
    capture_file_sha256: str,
) -> dict[str, object]:
    verified = bool(receipt_type == "login_capture" and capture_summary.get("authenticated_workspace_detected") is True)
    notes = {
        "login_capture": "Authenticated workspace snapshot captured via local BrowserAct template worker.",
        "commercial_use_terms_receipt": "Manual review required: confirm commercial-use terms from VidBoard plan/terms surface.",
        "watermark_export_receipt": "Manual review required: export a rendered clip and confirm watermark-free delivery.",
        "lip_sync_review_receipt": "Manual review required: inspect a talking-avatar clip for lip-sync quality.",
        "viseme_quality_receipt": "Manual review required: inspect mouth shapes and viseme quality on stressed phonemes.",
        "privacy_terms_receipt": "Manual review required: verify privacy, retention, and deletion posture.",
        "source_data_boundary_receipt": "Manual review required: confirm memorial-source-data allowance and boundaries.",
    }
    return {
        "provider_key": "vidboard",
        "receipt_type": receipt_type,
        "verified": verified,
        "captured_at": str(capture_summary.get("captured_at") or _utc_now()),
        "notes": notes[receipt_type],
        "source_capture_authenticated": bool(capture_summary.get("authenticated_workspace_detected") is True),
        "source_capture_render_status": str(capture_summary.get("render_status") or ""),
        "source_capture_url": str(capture_summary.get("url") or ""),
        "source_capture_title": str(capture_summary.get("title") or ""),
        "capture_path": capture_path.as_posix(),
        "capture_file_sha256": capture_file_sha256,
        "reviewed_by": "",
        "reviewed_at": "",
        "evidence_ref": "",
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _operator_handoff_payload(capture_summary: dict[str, object], *, capture_path: Path, receipt_dir: Path) -> dict[str, object]:
    failure_code = str(capture_summary.get("ui_failure_code") or "").strip()
    screenshot_path = str(capture_summary.get("screenshot_path") or "").strip()
    html_path = str(capture_summary.get("html_path") or "").strip()
    return {
        "generated_at": _utc_now(),
        "provider_key": "vidboard",
        "status": "operator_action_required",
        "failure_code": failure_code or "capture_failed",
        "recommended_action": (
            "Solve the captcha or complete the blocked login step in a supervised browser session, then rerun the capture command."
            if failure_code == "captcha_required"
            else "Inspect the capture artifacts, fix the blocked login path, then rerun the capture command."
        ),
        "resume_command": "python3 scripts/capture_vidboard_provider_receipts.py --login-email \"$VIDBOARD_LOGIN_EMAIL\" --login-password \"$VIDBOARD_LOGIN_PASSWORD\"",
        "capture_path": capture_path.as_posix(),
        "receipt_dir": receipt_dir.as_posix(),
        "preview_artifacts": {
            "screenshot_path": screenshot_path,
            "html_path": html_path,
        },
        "notes": list(capture_summary.get("errors") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a VidBoard workspace snapshot and materialize provider-proof receipt stubs.")
    parser.add_argument("--login-email", default="")
    parser.add_argument("--login-password", default="")
    parser.add_argument("--page-url", default="")
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--output", default=str(DEFAULT_CAPTURE_PATH))
    parser.add_argument("--receipt-dir", default=str(DEFAULT_RECEIPT_DIR))
    parser.add_argument("--handoff-output", default=str(DEFAULT_HANDOFF_PATH))
    args = parser.parse_args()

    login_email = _login_email(args.login_email)
    login_password = _login_password(args.login_password)
    if not login_email:
        raise SystemExit("vidboard_login_email_missing")
    if not login_password:
        raise SystemExit("vidboard_login_password_missing")

    exit_code = 0
    try:
        result = _run_worker(
            login_email=login_email,
            login_password=login_password,
            page_url=str(args.page_url).strip(),
            timeout_seconds=max(120, int(args.timeout_seconds)),
        )
        capture_summary = _capture_summary(result)
        if int(result.get("_worker_exit_code") or 0) != 0 or capture_summary["render_status"] == "failed":
            exit_code = 1
    except Exception as exc:
        capture_summary = _failed_capture_summary(str(exc))
        exit_code = 1
    output_path = Path(args.output)
    _write_json(output_path, capture_summary)
    capture_file_sha256 = _sha256_file(output_path)
    receipt_dir = Path(args.receipt_dir)
    handoff_path = Path(args.handoff_output)
    for receipt_type in RECEIPT_TYPES:
        _write_json(
            receipt_dir / f"vidboard_{receipt_type}.json",
            _receipt_payload(
                receipt_type,
                capture_summary,
                capture_path=output_path,
                capture_file_sha256=capture_file_sha256,
            ),
        )
    handoff_written = False
    if exit_code != 0:
        _write_json(
            handoff_path,
            _operator_handoff_payload(
                capture_summary,
                capture_path=output_path,
                receipt_dir=receipt_dir,
            ),
        )
        handoff_written = True
    print(
        json.dumps(
            {
                "status": "ok",
                "capture": output_path.as_posix(),
                "receipt_dir": receipt_dir.as_posix(),
                "handoff_path": handoff_path.as_posix() if handoff_written else "",
            },
            ensure_ascii=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
