#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_smoke.v1"
CONTRIBUTION_RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_contribution.v1"
PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
PRIVATE_AUDIO_RELPATH = "audio/hanusch-hospital-visit-enhanced.mp3"


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
            response_headers = {key.lower(): value for key, value in response.headers.items()}
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
    forbidden = {"recipient", "recipient_id", "recipient_address", "phone_number", "email"}
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


def _atomic_private_json(path: Path, payload: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
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
    if not contribution_id or not manage_token or response.get("visibility") != "private":
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
    if response.get("status") != "withdrawn" or response.get("public_removed") is not True:
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
    if PRIVATE_AUDIO_RELPATH in serialized_share or _contains_forbidden_recipient_field(share_packet):
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

    return {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "base_url": base_url,
        "checks": checks,
        "provider_calls_performed": False,
        "page_get_performed": False,
        "operator_surface_used": False,
        "private_audio_served": False,
        "contribution": contribution,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run provider-free HTTP checks against an isolated Manfred candidate."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18090")
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--wait-seconds", type=int, default=180)
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
            submit_receipt=Path(args.submit_contribution_receipt) if args.submit_contribution_receipt else None,
            withdraw_receipt=Path(args.withdraw_contribution_receipt) if args.withdraw_contribution_receipt else None,
        )
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema": RECEIPT_SCHEMA, "status": "fail", "error": str(exc)[:200]}, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
