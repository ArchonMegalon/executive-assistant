#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_OPTIONAL_AVATAR_WARN_CODES = {
    "avatar_disabled_label_missing",
    "avatar_manifest_missing",
    "avatar_video_not_published",
}


def public_memorial_root() -> Path:
    configured = str(os.getenv("EA_PUBLIC_MEMORIAL_DIR") or "").strip()
    return Path(configured) if configured else Path.cwd() / "public"


def private_profile_root() -> Path:
    configured = str(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or "").strip()
    return Path(configured) if configured else Path.cwd() / "private"


def public_registry_path(slug: str, generated: bool = False) -> Path:
    del generated
    return public_memorial_root() / slug / "archive_registry.json"


def load_registry_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Finding:
    status: str
    code: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class Report:
    slug: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, status: str, code: str, **detail: object) -> None:
        self.findings.append(Finding(status=status, code=code, detail=dict(detail)))

    @property
    def failed(self) -> bool:
        return any(item.status == "fail" for item in self.findings)

    @property
    def status(self) -> str:
        if self.failed:
            return "fail"
        warn_codes = {item.code for item in self.findings if item.status == "warn"}
        if warn_codes and warn_codes - _OPTIONAL_AVATAR_WARN_CODES:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, object]:
        return {"slug": self.slug, "status": self.status, "findings": [asdict(item) for item in self.findings]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_filesystem(slug: str, report: Report) -> None:
    bundle = public_memorial_root() / slug
    payload = json.loads((bundle / "memorial.json").read_text(encoding="utf-8"))
    if payload.get("write_token"):
        report.add("fail", "public_manifest_contains_tokens")
    voice_consent = dict(payload.get("voice_consent") or {})
    if voice_consent.get("status") == "approved" and voice_consent.get("revoked") is False:
        report.add("pass", "voice_consent_ok")
    registry = public_registry_path(slug)
    if registry.is_file():
        registry_payload = load_registry_json(registry)
        publications = {
            str(item.get("id") or ""): dict(item)
            for item in list(registry_payload.get("fliplink_publications") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        public_ids = {
            str(item_id)
            for section in list(registry_payload.get("archive_sections") or [])
            if isinstance(section, dict) and str(section.get("audience") or "") == "public"
            for item_id in list(section.get("items") or [])
            if str(item_id or "")
        }
        if public_ids and all(
            str(publications.get(item_id, {}).get("audience") or "") == "public"
            and str(publications.get(item_id, {}).get("review_status") or "") == "published"
            for item_id in public_ids
        ):
            report.add("pass", "archive_registry_public_only")
    avatar = dict(payload.get("video_call_avatar") or {})
    if not avatar:
        report.add("warn", "avatar_manifest_missing")
    elif avatar.get("public_ready") is True:
        asset = bundle / str(avatar.get("asset_relpath") or "")
        poster = bundle / str(avatar.get("poster_relpath") or "")
        if asset.is_file():
            report.add("pass", "avatar_video_asset_present")
        if asset.is_file() and str(avatar.get("asset_sha256") or "") == _sha256(asset):
            report.add("pass", "avatar_video_hash_ok")
        else:
            report.add("fail", "avatar_video_hash_mismatch")
        if avatar.get("provider_proof_verdict") == "VERIFIED_PROVIDER":
            report.add("pass", "avatar_manifest_verified")
        consent = dict(avatar.get("avatar_consent") or {})
        if consent.get("status") == "approved" and consent.get("revoked") is False:
            report.add("pass", "avatar_consent_ok")
    for document in list(payload.get("public_documents") or []):
        if not isinstance(document, dict) or str(document.get("provider") or "") != "joggai":
            continue
        relpath = str(document.get("asset_relpath") or "")
        receipt_relpath = str(document.get("receipt_relpath") or "")
        if not receipt_relpath or ".." in Path(receipt_relpath).parts:
            report.add("fail", "joggai_public_asset_missing_receipt_gate", missing=["receipt_relpath"], relpath=relpath)
            continue
        receipt_path = bundle / receipt_relpath
        if not receipt_path.is_file():
            report.add("fail", "joggai_public_asset_missing_receipt_gate", relpath=relpath)
            continue
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        asset_path = bundle / relpath
        if not asset_path.is_file():
            report.add("fail", "joggai_public_asset_hash_mismatch", relpath=relpath)
            continue
        if str(receipt.get("asset_sha256") or "") != _sha256(asset_path):
            detail: dict[str, object] = {"relpath": relpath}
            if receipt.get("poster_relpath"):
                detail["poster_relpath"] = str(receipt.get("poster_relpath"))
            report.add("fail", "joggai_public_asset_hash_mismatch", **detail)
            continue
        poster_relpath = str(receipt.get("poster_relpath") or "")
        if poster_relpath:
            poster_path = bundle / poster_relpath
            if not poster_path.is_file() or str(receipt.get("poster_sha256") or "") != _sha256(poster_path):
                report.add("fail", "joggai_public_asset_hash_mismatch", relpath=relpath, poster_relpath=poster_relpath)
                continue
        report.add("pass", "joggai_public_asset_gate_ok", relpath=relpath)


def http_request(url: str, *, method: str = "GET", body: bytes | None = None, headers=None) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
        with urllib.request.urlopen(req, timeout=20.0) as response:
            return int(getattr(response, "status", 200) or 200), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code or 0), exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def _public_json_has_raw_transcript(value: object) -> bool:
    if isinstance(value, dict):
        if "transcript" in value:
            return True
        return any(_public_json_has_raw_transcript(item) for item in value.values())
    if isinstance(value, list):
        return any(_public_json_has_raw_transcript(item) for item in value)
    return False


def check_live(slug: str, report: Report, base_url: str) -> None:
    routes = {
        "raw_manifest": f"{base_url}/memorials/files/{slug}/memorial.json",
        "public_json": f"{base_url}/memorials/{slug}.json",
        "public_page": f"{base_url}/memorials/{slug}",
        "voice_config": f"{base_url}/memorials/{slug}/voice-config",
        "archive_json": f"{base_url}/memorials/{slug}/archive.json",
    }
    payloads: dict[str, tuple[int, str]] = {}
    for name, url in routes.items():
        payloads[name] = http_request(url)
        if payloads[name][0] == 0:
            report.add("fail", "live_endpoint_request_failed", route=name, detail=payloads[name][1])
    speech_status, speech_body = http_request(
        f"{base_url}/memorials/{slug}/speech-synthesize",
        method="POST",
        body=json.dumps({"voice_name": "override"}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    if speech_status == 0:
        report.add("fail", "live_endpoint_request_failed", route="speech_synthesize_override_probe", detail=speech_body)
    if report.failed:
        return
    public_json = json.loads(payloads["public_json"][1])
    public_page = payloads["public_page"][1]
    public_memories = [item for item in list(public_json.get("memory_cards") or []) if isinstance(item, dict)]
    public_sources = [item for item in list(public_json.get("external_sources") or []) if isinstance(item, dict)]
    public_prompts = [item for item in list(public_json.get("suggested_prompts") or []) if isinstance(item, str) and item.strip()]
    source_first_page_ok = all(
        marker in public_page
        for marker in (
            '<main id="memorial-story" tabindex="-1">',
            'id="memorial-conversation-region" tabindex="-1"',
            'href="#memorial-conversation-region"',
            "Erinnerungen und belegte Quellen",
            "memorial-conversation",
            "memorial-retry-button",
        )
    )
    source_first_payload_ok = (
        bool(public_memories)
        and bool(public_sources)
        and bool(public_prompts)
        and all(str(item.get("body") or "").startswith("[stark redigiert]") for item in public_memories)
        and all(str(item.get("url") or "").startswith("https://") for item in public_sources)
        and not _public_json_has_raw_transcript(public_json)
    )
    if source_first_page_ok and source_first_payload_ok:
        report.add(
            "pass",
            "live_public_page_source_first",
            public_memory_count=len(public_memories),
            public_source_count=len(public_sources),
            public_prompt_count=len(public_prompts),
        )
    else:
        report.add(
            "fail",
            "live_public_page_source_first_failed",
            page_contract_ok=source_first_page_ok,
            payload_contract_ok=source_first_payload_ok,
            public_memory_count=len(public_memories),
            public_source_count=len(public_sources),
            public_prompt_count=len(public_prompts),
            raw_transcript_present=_public_json_has_raw_transcript(public_json),
        )
    if speech_status == 400 and "unsupported_public_tts_fields" in speech_body:
        report.add("pass", "live_public_tts_rejects_override")
    avatar = dict(public_json.get("video_call_avatar") or {})
    if avatar.get("enabled") is True and 'memorial-video-call-avatar-video' in public_page:
        report.add("pass", "live_avatar_video_present_on_page")
    elif avatar.get("enabled") is False and str(avatar.get("kind") or "") == "portrait":
        report.add("pass", "live_avatar_portrait_fallback_consistent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = Report(slug=args.slug)
    check_filesystem(args.slug, report)
    if args.base_url:
        check_live(args.slug, report, args.base_url.rstrip("/"))
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=None if args.json else 2))
    return 0 if report.status in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
