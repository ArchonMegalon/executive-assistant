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
DEFAULT_CAPTURE_PATH = DEFAULT_OUT_DIR / "nonverbia_custom_project_analysis.generated.json"
WORKER_SCRIPT = ROOT / "scripts" / "browseract_template_service_worker.py"
ENV_FILES = (ROOT / "ea" / ".env", ROOT / ".env")


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
    return value.strip() or _env_value("NONVERBIA_LOGIN_EMAIL")


def _login_password(value: str) -> str:
    return value.strip() or _env_value("NONVERBIA_LOGIN_PASSWORD")


def _run_worker(*, login_email: str, login_password: str, page_url: str, timeout_seconds: int) -> dict[str, object]:
    runtime_inputs = {
        "browseract_username": login_email,
        "browseract_password": login_password,
    }
    if page_url.strip():
        runtime_inputs["page_url"] = page_url.strip()
    packet = {
        "template_key": "nonverbia_workspace_reader",
        "workflow_spec_json": browseract_ui_template_spec("nonverbia_workspace_reader"),
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
        raise RuntimeError(f"nonverbia_analysis_worker_empty_output:{detail[:400]}")
    last_line = raw.splitlines()[-1].strip()
    try:
        payload = json.loads(last_line)
    except Exception as exc:
        raise RuntimeError(f"nonverbia_analysis_worker_non_json:{last_line[:400]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("nonverbia_analysis_worker_invalid_output")
    payload["_worker_exit_code"] = int(completed.returncode)
    return payload


def _worker_summary(result: dict[str, object]) -> dict[str, object]:
    structured = dict(result.get("structured_output_json") or {})
    render_status = str(result.get("render_status") or "").strip().lower()
    ui_failure_code = str(result.get("ui_failure_code") or "").strip().lower()
    body_text = str(result.get("body_text") or result.get("raw_text") or "").strip()
    title = str(structured.get("page_title") or result.get("result_title") or "").strip()
    url = str(structured.get("url") or result.get("editor_url") or "").strip()
    warnings = list(structured.get("warnings") or result.get("warnings") or [])
    errors = list(structured.get("errors") or result.get("errors") or [])
    authenticated = render_status in {"completed", "completed_with_warnings"} and ui_failure_code == "" and bool(title or body_text or url)
    return {
        "captured_at": _utc_now(),
        "provider_key": "nonverbia",
        "template_key": "nonverbia_workspace_reader",
        "authenticated_workspace_detected": authenticated,
        "render_status": render_status,
        "ui_failure_code": ui_failure_code,
        "title": title,
        "url": url,
        "warnings": warnings,
        "errors": errors,
        "body_excerpt": body_text[:1200],
        "asset_path": str(result.get("asset_path") or "").strip(),
        "screenshot_path": str(structured.get("screenshot_path") or "").strip(),
        "html_path": str(structured.get("html_path") or "").strip(),
        "raw_result": result,
    }


def _failed_summary(detail: str) -> dict[str, object]:
    normalized = str(detail or "").strip()
    failure_code = "analysis_failed"
    if "invalid_credentials" in normalized:
        failure_code = "invalid_credentials"
    elif "challenge_required" in normalized:
        failure_code = "challenge_required"
    return {
        "captured_at": _utc_now(),
        "provider_key": "nonverbia",
        "template_key": "nonverbia_workspace_reader",
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
        "raw_result": {"error": normalized[:1200]},
    }


def _tokenize(text: object) -> list[str]:
    parts = []
    current = []
    for char in str(text or "").lower():
        if char.isalnum():
            current.append(char)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return parts


def _analysis(summary: dict[str, object], *, project_name: str, fit_keywords: list[str]) -> dict[str, object]:
    title = str(summary.get("title") or "")
    url = str(summary.get("url") or "")
    body = str(summary.get("body_excerpt") or "")
    haystack = " ".join([title, url, body]).lower()
    project_tokens = [token for token in _tokenize(project_name) if len(token) >= 3]
    matched_project_tokens = [token for token in project_tokens if token in haystack]
    normalized_keywords = [token.lower().strip() for token in fit_keywords if token.strip()]
    matched_keywords = [token for token in normalized_keywords if token in haystack]
    avatar_markers = [token for token in ("avatar", "video", "presenter", "camera", "talking", "speaker") if token in haystack]
    project_found = bool(not project_tokens or matched_project_tokens)
    score = 0
    if summary.get("authenticated_workspace_detected") is True:
        score += 2
    if project_found:
        score += 2
    if matched_keywords:
        score += 1
    if avatar_markers:
        score += 1
    fit = "blocked"
    if summary.get("render_status") in {"completed", "completed_with_warnings"}:
        if score >= 5:
            fit = "strong_fit"
        elif score >= 3:
            fit = "possible_fit"
        else:
            fit = "weak_fit"
    return {
        "project_name": project_name,
        "project_tokens": project_tokens,
        "matched_project_tokens": matched_project_tokens,
        "fit_keywords": normalized_keywords,
        "matched_fit_keywords": matched_keywords,
        "avatar_markers": avatar_markers,
        "project_found": project_found,
        "fit_score": score,
        "fit_verdict": fit,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a Nonverbia custom project surface for avatar-presenter fit.")
    parser.add_argument("--login-email", default="")
    parser.add_argument("--login-password", default="")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--project-url", default="")
    parser.add_argument("--fit-keyword", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--output", default=str(DEFAULT_CAPTURE_PATH))
    args = parser.parse_args()

    login_email = _login_email(args.login_email)
    login_password = _login_password(args.login_password)
    if not login_email:
        raise SystemExit("nonverbia_login_email_missing")
    if not login_password:
        raise SystemExit("nonverbia_login_password_missing")

    exit_code = 0
    try:
        result = _run_worker(
            login_email=login_email,
            login_password=login_password,
            page_url=str(args.project_url).strip(),
            timeout_seconds=max(120, int(args.timeout_seconds)),
        )
        summary = _worker_summary(result)
        if int(result.get("_worker_exit_code") or 0) != 0 or summary["render_status"] == "failed":
            exit_code = 1
    except Exception as exc:
        summary = _failed_summary(str(exc))
        exit_code = 1

    analysis = _analysis(summary, project_name=str(args.project_name).strip(), fit_keywords=list(args.fit_keyword or []))
    payload = dict(summary)
    payload["analysis"] = analysis
    output_path = Path(args.output)
    _write_json(output_path, payload)
    payload["capture_file_sha256"] = _sha256_file(output_path)
    _write_json(output_path, payload)
    print(json.dumps({"status": "ok", "output": output_path.as_posix(), "fit_verdict": analysis["fit_verdict"]}, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
