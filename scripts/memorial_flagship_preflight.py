#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

_OPTIONAL_AVATAR_WARN_CODES = {
    "avatar_disabled_label_missing",
    "avatar_manifest_missing",
    "avatar_video_not_published",
}
_REPO_ROOT = Path(__file__).resolve().parents[1]
_EA_APP_ROOT = _REPO_ROOT / "ea"
if str(_EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_EA_APP_ROOT))

from app.services.memorial_private_context import (  # noqa: E402
    PRIVATE_CONTEXT_DECLARATION,
    MemorialPrivateContextError,
    load_private_memorial_context,
)

_REQUIRED_VOICE_CONSENT_SCOPES = frozenset({"synthesize", "conversation_turn", "realtime"})


def public_memorial_root() -> Path:
    configured = str(os.getenv("EA_PUBLIC_MEMORIAL_DIR") or "").strip()
    return Path(configured) if configured else _REPO_ROOT / "memorial_data" / "public_memorials"


def private_profile_root() -> Path:
    configured = str(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR") or "").strip()
    return Path(configured) if configured else _REPO_ROOT / "memorial_data" / "private_memorial_profiles"


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


def _voice_consent(slug: str, public_payload: dict[str, object], report: Report) -> dict[str, object] | None:
    private_path = private_profile_root() / slug / "tts_voice.json"
    if private_path.exists():
        if not private_path.is_file():
            report.add("fail", "voice_consent_invalid")
            return None
        try:
            private_payload = json.loads(private_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            report.add("fail", "voice_consent_invalid")
            return None
        if not isinstance(private_payload, dict) or not isinstance(private_payload.get("voice_consent"), dict):
            report.add("fail", "voice_consent_invalid")
            return None
        return dict(private_payload["voice_consent"])

    legacy_consent = public_payload.get("voice_consent")
    if legacy_consent is None:
        report.add("fail", "voice_consent_missing")
        return None
    if not isinstance(legacy_consent, dict):
        report.add("fail", "voice_consent_invalid")
        return None
    return dict(legacy_consent)


def _check_voice_consent(slug: str, public_payload: dict[str, object], report: Report) -> None:
    consent = _voice_consent(slug, public_payload, report)
    if consent is None:
        return
    revoked = consent.get("revoked")
    if revoked is True:
        report.add("fail", "voice_consent_revoked")
        return
    if revoked is not False:
        report.add("fail", "voice_consent_invalid")
        return
    status = consent.get("status")
    if not isinstance(status, str) or not status.strip():
        report.add("fail", "voice_consent_invalid")
        return
    if status != "approved":
        report.add("fail", "voice_consent_not_approved")
        return
    raw_scope = consent.get("scope")
    if not isinstance(raw_scope, list) or any(not isinstance(item, str) or not item.strip() for item in raw_scope):
        report.add("fail", "voice_consent_invalid")
        return
    scope = {item.strip() for item in raw_scope}
    missing_scopes = sorted(_REQUIRED_VOICE_CONSENT_SCOPES - scope)
    if missing_scopes:
        report.add("fail", "voice_consent_scope_missing", missing_scopes=missing_scopes)
        return
    report.add("pass", "voice_consent_ok")


def _check_archive_registry(slug: str, report: Report) -> None:
    registry = public_registry_path(slug)
    if not registry.exists():
        report.add("fail", "archive_registry_missing")
        return
    if not registry.is_file():
        report.add("fail", "archive_registry_invalid")
        return
    try:
        registry_payload = load_registry_json(registry)
    except (OSError, TypeError, ValueError):
        report.add("fail", "archive_registry_invalid")
        return
    if not isinstance(registry_payload, dict):
        report.add("fail", "archive_registry_invalid")
        return
    raw_sections = registry_payload.get("archive_sections")
    raw_publications = registry_payload.get("fliplink_publications")
    if not isinstance(raw_sections, list) or not isinstance(raw_publications, list):
        report.add("fail", "archive_registry_invalid")
        return
    if any(not isinstance(item, dict) for item in raw_sections + raw_publications):
        report.add("fail", "archive_registry_invalid")
        return

    publications: dict[str, dict[str, object]] = {}
    for raw_publication in raw_publications:
        publication = dict(raw_publication)
        publication_id = publication.get("id")
        if not isinstance(publication_id, str) or not publication_id.strip() or publication_id in publications:
            report.add("fail", "archive_registry_invalid")
            return
        publications[publication_id] = publication

    public_ids: set[str] = set()
    for raw_section in raw_sections:
        section = dict(raw_section)
        if str(section.get("audience") or "") != "public":
            continue
        items = section.get("items")
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            report.add("fail", "archive_registry_invalid")
            return
        public_ids.update(item.strip() for item in items)

    registry_is_public = bool(public_ids) and all(
        item_id in publications
        and str(publications[item_id].get("audience") or "") == "public"
        and str(publications[item_id].get("review_status") or "") == "published"
        for item_id in public_ids
    )
    if not registry_is_public:
        report.add("fail", "archive_registry_not_public")
        return
    report.add("pass", "archive_registry_public_only")


def _check_private_context(
    slug: str,
    public_payload: dict[str, object],
    report: Report,
) -> None:
    declaration = public_payload.get("private_context")
    if declaration is None:
        return
    if not isinstance(declaration, dict) or declaration != PRIVATE_CONTEXT_DECLARATION:
        report.add("fail", "private_context_declaration_invalid")
        return
    try:
        load_private_memorial_context(
            private_root=private_profile_root(),
            slug=slug,
        )
    except FileNotFoundError:
        report.add("fail", "private_context_missing")
    except (OSError, MemorialPrivateContextError):
        report.add("fail", "private_context_invalid")
    else:
        report.add("pass", "private_context_valid")


def check_filesystem(slug: str, report: Report) -> None:
    bundle = public_memorial_root() / slug
    manifest_path = bundle / "memorial.json"
    if not manifest_path.is_file():
        report.add("fail", "public_manifest_missing")
        return
    try:
        raw_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        report.add("fail", "public_manifest_invalid")
        return
    if not isinstance(raw_payload, dict):
        report.add("fail", "public_manifest_invalid")
        return
    payload: dict[str, object] = raw_payload
    if payload.get("write_token"):
        report.add("fail", "public_manifest_contains_tokens")
    _check_private_context(slug, payload, report)
    _check_voice_consent(slug, payload, report)
    _check_archive_registry(slug, report)
    avatar = dict(payload.get("video_call_avatar") or {})
    if not avatar:
        report.add("warn", "avatar_manifest_missing")
    elif avatar.get("public_ready") is True:
        asset = bundle / str(avatar.get("asset_relpath") or "")
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


def _valid_public_evidence_url(value: object, *, slug: str) -> bool:
    raw = str(value or "").strip()
    if not raw or "\\" in raw or "%" in raw:
        return False
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError:
        return False
    if parsed.query or parsed.fragment or any(
        part in {"", ".", ".."} for part in parsed.path.split("/")[1:]
    ):
        return False
    internal_prefix = f"/memorials/{slug}/archive/"
    if not parsed.scheme and not parsed.netloc:
        publication_slug = parsed.path.removeprefix(internal_prefix)
        return (
            parsed.path.startswith(internal_prefix)
            and bool(publication_slug)
            and "/" not in publication_slug
        )
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


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

    raw_manifest_status = payloads["raw_manifest"][0]
    if raw_manifest_status in {401, 403, 404}:
        report.add(
            "pass",
            "live_raw_manifest_not_public",
            http_status=raw_manifest_status,
        )
    elif raw_manifest_status != 0:
        report.add(
            "fail",
            "live_raw_manifest_access_policy_failed",
            http_status=raw_manifest_status,
        )
    for route_name in ("public_json", "public_page", "voice_config", "archive_json"):
        route_status = payloads[route_name][0]
        if route_status not in {0, 200}:
            report.add(
                "fail",
                "live_endpoint_http_status_failed",
                route=route_name,
                http_status=route_status,
            )
    if speech_status != 0:
        if speech_status == 400 and "unsupported_public_tts_fields" in speech_body:
            report.add("pass", "live_public_tts_rejects_override")
        else:
            report.add(
                "fail",
                "live_public_tts_override_rejection_failed",
                http_status=speech_status,
            )
    if report.failed:
        return
    decoded_payloads: dict[str, dict[str, object]] = {}
    for route_name in ("public_json", "voice_config", "archive_json"):
        try:
            decoded = json.loads(payloads[route_name][1])
        except (TypeError, ValueError):
            report.add(
                "fail",
                "live_endpoint_json_invalid",
                route=route_name,
                http_status=payloads[route_name][0],
            )
            continue
        if not isinstance(decoded, dict):
            report.add(
                "fail",
                "live_endpoint_json_invalid",
                route=route_name,
                http_status=payloads[route_name][0],
            )
            continue
        decoded_payloads[route_name] = decoded
    if report.failed:
        return
    public_json = decoded_payloads["public_json"]
    public_page = payloads["public_page"][1]
    public_memories = [item for item in list(public_json.get("memory_cards") or []) if isinstance(item, dict)]
    public_sources = [item for item in list(public_json.get("external_sources") or []) if isinstance(item, dict)]
    public_profiles = [
        item
        for item in list(public_json.get("source_grounded_profile") or [])
        if isinstance(item, dict)
    ]
    public_prompts = [item for item in list(public_json.get("suggested_prompts") or []) if isinstance(item, str) and item.strip()]
    archive_json = decoded_payloads["archive_json"]
    approved_archive_publications = [
        item
        for item in list(archive_json.get("fliplink_publications") or [])
        if isinstance(item, dict)
        and str(item.get("audience") or "").strip().lower() == "public"
        and str(item.get("review_status") or "").strip().lower() in {"approved", "published"}
    ]
    approved_public_profiles = [
        item
        for item in public_profiles
        if item.get("approved") is True
        or str(item.get("curation_status") or "").strip() == "approved_public_profile"
    ]
    public_source_routes_ok = all(
        _valid_public_evidence_url(item.get("url"), slug=slug) for item in public_sources
    )
    archive_routes_ok = all(
        _valid_public_evidence_url(item.get("url"), slug=slug)
        for item in approved_archive_publications
    )
    public_source_evidence_ok = bool(
        public_sources or approved_archive_publications or approved_public_profiles
    )
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
        and public_source_evidence_ok
        and bool(public_prompts)
        and all(
            str(item.get("body") or "").startswith("[stark redigiert]")
            or str(item.get("curation_status") or "") == "approved_public_excerpt"
            for item in public_memories
        )
        and public_source_routes_ok
        and archive_routes_ok
        and not _public_json_has_raw_transcript(public_json)
    )
    if source_first_page_ok and source_first_payload_ok:
        report.add(
            "pass",
            "live_public_page_source_first",
            public_memory_count=len(public_memories),
            public_source_count=len(public_sources),
            public_archive_source_count=len(approved_archive_publications),
            public_profile_source_count=len(approved_public_profiles),
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
            public_archive_source_count=len(approved_archive_publications),
            public_profile_source_count=len(approved_public_profiles),
            public_prompt_count=len(public_prompts),
            public_source_routes_ok=public_source_routes_ok,
            archive_routes_ok=archive_routes_ok,
            raw_transcript_present=_public_json_has_raw_transcript(public_json),
        )
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
