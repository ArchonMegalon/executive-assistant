#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
EA_ROOT = SCRIPT_DIR.parent
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.memorial_archive_registry import public_registry_path, public_registry_payload
from app.services.memorial_archive_registry import load_json as load_registry_json

TOKEN_KEYS = {"write_token", "write_tokens", "admin_token", "management_token", "owner_token"}
PUBLIC_JSON_BLOCK_KEYS = TOKEN_KEYS | {
    "tts_plugin_voice_id",
    "voice_consent",
    "provider_secret",
    "private_profile",
    "llm_profile_notes",
}
BLOCKED_PUBLIC_ASSET_NAMES = {
    "tts_voice.json",
    "voice_ab.json",
    "ratings.json",
    "llm_profile_notes.json",
    "transcript_signal_report.json",
}
ALLOWED_PUBLIC_ASSET_SUFFIXES = {
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm",
    ".mp4", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".svg", ".pdf",
}
ALLOWED_AVATAR_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
ALLOWED_AVATAR_POSTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
REQUIRED_PUBLIC_CONSENT_SCOPES = {"synthesize", "conversation_turn", "realtime"}
REQUIRED_PUBLIC_PAGE_MARKERS = {
    "Gespräch beginnen",
    "Am Handy/Desktop installieren",
}
FORBIDDEN_PUBLIC_PAGE_MARKERS = {
    "Originalaufnahmen",
    "Belegte Erinnerungen",
    "Quellenbasiertes Profil",
    "Weitere gefundene Kandidaten",
    "Archiv lesen",
    "Stimmvergleich und Feedback",
    'id="memorial-voice-ab-wrap"',
    'id="memorial-voice-config-form"',
}
NON_BLOCKING_WARN_CODES = {
    "avatar_manifest_missing",
    "avatar_poster_not_declared",
    "avatar_verified_but_disabled",
    "avatar_not_live_yet",
    "no_public_assets_declared",
    "live_archive_json_unavailable",
}


@dataclass
class Finding:
    status: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    slug: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, status: str, code: str, message: str, **detail: Any) -> None:
        self.findings.append(Finding(status=status, code=code, message=message, detail=detail))

    @property
    def failed(self) -> bool:
        return any(item.status == "fail" for item in self.findings)

    @property
    def warned(self) -> bool:
        return any(item.status == "warn" and item.code not in NON_BLOCKING_WARN_CODES for item in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "status": "fail" if self.failed else ("warn" if self.warned else "pass"),
            "findings": [
                {"status": item.status, "code": item.code, "message": item.message, "detail": item.detail}
                for item in self.findings
            ],
        }

    def print_markdown(self) -> None:
        print(f"# Memorial Flagship Preflight: {self.slug}\n")
        print(f"Overall: **{self.as_dict()['status'].upper()}**\n")
        for finding in self.findings:
            icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(finding.status, "INFO")
            print(f"- `{icon}` `{finding.code}` {finding.message}")
            if finding.detail:
                print(f"  `{json.dumps(finding.detail, ensure_ascii=False, sort_keys=True)}`")


def _configured_or_existing_path(env_names: tuple[str, ...], candidates: tuple[str, ...]) -> Path:
    for env_name in env_names:
        value = str(os.getenv(env_name) or "").strip()
        if value:
            return Path(value).expanduser()
    for raw in candidates:
        path = Path(raw)
        if path.exists():
            return path
    return Path(candidates[0])


def public_memorial_root() -> Path:
    return _configured_or_existing_path(
        ("EA_PUBLIC_MEMORIAL_ROOT", "EA_PUBLIC_MEMORIAL_DIR"),
        ("/docker/EA/memorial_data/public_memorials", "/data/memorial_data/public_memorials"),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_provider(item: dict[str, Any]) -> str:
    return str(item.get("provider") or item.get("provider_key") or "").strip().lower()


def _check_joggai_public_document(
    *,
    item: dict[str, Any],
    candidate: Path,
    bundle: Path,
    section: str,
    relpath: str,
    report: Report,
) -> None:
    if _manifest_provider(item) != "joggai":
        return
    review_status = str(item.get("review_status") or "").strip().lower()
    visibility = str(item.get("visibility") or "").strip().lower() or "public"
    public_flag = bool(item.get("public") is True)
    sha256 = str(item.get("sha256") or item.get("asset_sha256") or "").strip().lower()
    receipt_relpath = _relpath(str(item.get("receipt_relpath") or item.get("receipt_path") or ""))
    if public_flag or visibility == "public":
        missing: list[str] = []
        if review_status != "approved":
            missing.append("review_status=approved")
        if not sha256:
            missing.append("sha256")
        if not receipt_relpath:
            missing.append("receipt_relpath")
        if missing:
            report.add(
                "fail",
                "joggai_public_asset_missing_receipt_gate",
                "Public JoggAI asset is missing review/hash/receipt gates.",
                section=section,
                relpath=relpath,
                missing=missing,
            )
            return
        receipt_path = bundle / receipt_relpath
        if not receipt_path.is_file():
            report.add(
                "fail",
                "joggai_public_asset_missing_receipt_gate",
                "Public JoggAI asset receipt is not present in the memorial bundle.",
                section=section,
                relpath=relpath,
                receipt_relpath=receipt_relpath,
            )
            return
        try:
            receipt = load_json(receipt_path)
        except Exception as exc:
            report.add(
                "fail",
                "joggai_public_asset_missing_receipt_gate",
                "Public JoggAI asset receipt could not be parsed.",
                section=section,
                relpath=relpath,
                receipt_relpath=receipt_relpath,
                error=str(exc),
            )
            return
        receipt_contract = str(receipt.get("contract_name") or "").strip()
        receipt_provider = str(receipt.get("provider") or receipt.get("provider_key") or "").strip().lower()
        receipt_asset_relpath = _relpath(str(receipt.get("asset_relpath") or ""))
        receipt_asset_hash = str(receipt.get("asset_sha256") or "").strip().lower()
        receipt_public_ready = bool(receipt.get("public_ready") is True)
        receipt_review_status = str(receipt.get("review_status") or "").strip().lower()
        receipt_missing: list[str] = []
        if receipt_contract != "executive_assistant.memorial_joggai_render.v1":
            receipt_missing.append("contract_name")
        if receipt_provider != "joggai":
            receipt_missing.append("provider=joggai")
        if receipt_asset_relpath != relpath:
            receipt_missing.append("asset_relpath")
        if receipt_asset_hash != sha256:
            receipt_missing.append("asset_sha256")
        if receipt_review_status != "approved":
            receipt_missing.append("receipt.review_status=approved")
        if receipt_public_ready is not True:
            receipt_missing.append("receipt.public_ready=true")
        if receipt_missing:
            report.add(
                "fail",
                "joggai_public_asset_missing_receipt_gate",
                "Public JoggAI asset receipt does not match the manifest gate.",
                section=section,
                relpath=relpath,
                receipt_relpath=receipt_relpath,
                missing=receipt_missing,
            )
            return
        if candidate.is_file() and sha256_file(candidate) != sha256:
            report.add(
                "fail",
                "joggai_public_asset_hash_mismatch",
                "Public JoggAI asset hash does not match manifest.",
                section=section,
                relpath=relpath,
            )
            return
        report.add(
            "pass",
            "joggai_public_asset_gate_ok",
            "Public JoggAI asset is approved, receipt-linked, and hash-pinned.",
            section=section,
            relpath=relpath,
        )


def private_profile_root() -> Path:
    return _configured_or_existing_path(
        ("EA_PRIVATE_MEMORIAL_PROFILE_DIR",),
        ("/docker/EA/memorial_data/private_memorial_profiles", "/mnt/pcloud/EA/private_memorial_profiles"),
    )


def safe_slug(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or "/" in normalized or ".." in normalized:
        raise SystemExit("invalid memorial slug")
    return normalized


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid_json_object:{path}")
    return payload


def _relpath(value: str) -> str:
    return PurePosixPath(str(value or "").strip()).as_posix().lstrip("/")


def _voice_consent_from(slug: str, memorial: dict[str, Any]) -> tuple[dict[str, Any], str]:
    explicit = memorial.get("voice_consent")
    if isinstance(explicit, dict) and explicit:
        return dict(explicit), "public memorial.json"
    voice_path = private_profile_root() / safe_slug(slug) / "tts_voice.json"
    if not voice_path.is_file():
        return {}, ""
    try:
        payload = load_json(voice_path)
    except Exception:
        return {}, ""
    explicit = payload.get("voice_consent")
    if isinstance(explicit, dict) and explicit:
        return dict(explicit), str(voice_path)
    return {}, ""


def _public_registry_for(slug: str) -> tuple[dict[str, Any], Path]:
    path = public_registry_path(slug, generated=False)
    if not path.is_file():
        return {}, path
    raw = load_registry_json(path)
    return public_registry_payload(raw), path


def _check_avatar_bundle(memorial: dict[str, Any], *, bundle: Path, report: Report) -> None:
    raw = memorial.get("video_call_avatar")
    if not isinstance(raw, dict) or not raw:
        report.add("warn", "avatar_manifest_missing", "Public memorial manifest does not declare a video-call avatar block.")
        return
    avatar = dict(raw)
    enabled = bool(avatar.get("public_ready") is True)
    asset_relpath = _relpath(str(avatar.get("asset_relpath") or ""))
    poster_relpath = _relpath(str(avatar.get("poster_relpath") or ""))
    provider_key = str(avatar.get("provider_key") or "").strip().lower()
    proof_verdict = str(avatar.get("provider_proof_verdict") or "").strip().upper()
    asset_sha256 = str(avatar.get("asset_sha256") or "").strip().lower()
    poster_sha256 = str(avatar.get("poster_sha256") or "").strip().lower()
    consent = avatar.get("avatar_consent") if isinstance(avatar.get("avatar_consent"), dict) else {}
    if enabled:
        missing = []
        if not provider_key:
            missing.append("provider_key")
        if proof_verdict != "VERIFIED_PROVIDER":
            missing.append("provider_proof_verdict")
        if not asset_relpath:
            missing.append("asset_relpath")
        if not asset_sha256:
            missing.append("asset_sha256")
        if not consent:
            missing.append("avatar_consent")
        if missing:
            report.add("fail", "avatar_manifest_incomplete", "Enabled avatar manifest is missing required fields.", fields=missing)
            return
        consent_status = str(consent.get("status") or "").strip().lower()
        consent_revoked = bool(consent.get("revoked") is True)
        consent_scope = {str(item or "").strip() for item in list(consent.get("scope") or [])}
        if consent_status != "approved" or consent_revoked or not {"public_video_call", "avatar_playback"} <= consent_scope:
            report.add(
                "fail",
                "avatar_consent_invalid",
                "Enabled avatar is missing approved public likeness consent.",
                status=consent_status,
                revoked=consent_revoked,
                scope=sorted(consent_scope),
            )
            return
        report.add("pass", "avatar_consent_ok", "Enabled avatar has explicit public likeness consent.")
        asset_path = bundle / asset_relpath
        asset_suffix = asset_path.suffix.lower()
        if asset_suffix not in ALLOWED_AVATAR_VIDEO_SUFFIXES:
            report.add("fail", "avatar_video_suffix_invalid", "Enabled avatar video uses an unsupported suffix.", relpath=asset_relpath, suffix=asset_suffix)
        elif not asset_path.is_file():
            report.add("fail", "avatar_video_asset_missing", "Enabled avatar video asset is missing from disk.", relpath=asset_relpath)
        else:
            report.add("pass", "avatar_video_asset_present", "Enabled avatar video asset exists on disk.", relpath=asset_relpath)
            if asset_sha256 and sha256_file(asset_path) != asset_sha256:
                report.add("fail", "avatar_video_hash_mismatch", "Enabled avatar video hash no longer matches the published manifest.", relpath=asset_relpath)
            else:
                report.add("pass", "avatar_video_hash_ok", "Enabled avatar video hash matches the published manifest.", relpath=asset_relpath)
        if poster_relpath:
            poster_path = bundle / poster_relpath
            poster_suffix = poster_path.suffix.lower()
            if poster_suffix not in ALLOWED_AVATAR_POSTER_SUFFIXES:
                report.add("fail", "avatar_poster_suffix_invalid", "Enabled avatar poster uses an unsupported suffix.", relpath=poster_relpath, suffix=poster_suffix)
            elif not poster_path.is_file():
                report.add("fail", "avatar_poster_missing", "Enabled avatar poster asset is missing from disk.", relpath=poster_relpath)
            else:
                report.add("pass", "avatar_poster_present", "Enabled avatar poster asset exists on disk.", relpath=poster_relpath)
                if poster_sha256:
                    if sha256_file(poster_path) != poster_sha256:
                        report.add("fail", "avatar_poster_hash_mismatch", "Enabled avatar poster hash no longer matches the published manifest.", relpath=poster_relpath)
                    else:
                        report.add("pass", "avatar_poster_hash_ok", "Enabled avatar poster hash matches the published manifest.", relpath=poster_relpath)
        else:
            report.add("warn", "avatar_poster_not_declared", "Enabled avatar has no poster asset declared.")
        report.add("pass", "avatar_manifest_verified", "Enabled avatar manifest is tied to a verified provider verdict.", provider_key=provider_key)
        return
    if asset_relpath and proof_verdict == "VERIFIED_PROVIDER":
        report.add("warn", "avatar_verified_but_disabled", "Avatar proof is verified but public_ready is still false; portrait fallback remains active.", relpath=asset_relpath)
    else:
        report.add("warn", "avatar_not_live_yet", "Avatar video is not live yet; portrait fallback remains active.", provider_key=provider_key or "unknown")


def check_filesystem(slug: str, report: Report, *, require_clone_consent: bool = False) -> None:
    bundle = public_memorial_root() / safe_slug(slug)
    manifest_path = bundle / "memorial.json"
    if not bundle.is_dir():
        report.add("fail", "bundle_missing", "Public memorial bundle is missing.", path=str(bundle))
        return
    report.add("pass", "bundle_exists", "Public memorial bundle exists.", path=str(bundle))

    if not manifest_path.is_file():
        report.add("fail", "manifest_missing", "Public memorial manifest is missing.", path=str(manifest_path))
        return

    try:
        memorial = load_json(manifest_path)
    except Exception as exc:
        report.add("fail", "manifest_invalid_json", "Public memorial manifest is invalid JSON.", error=str(exc))
        return

    leaked_tokens = sorted(key for key in TOKEN_KEYS if memorial.get(key))
    if leaked_tokens:
        report.add("fail", "public_manifest_contains_tokens", "Public memorial manifest still contains write/admin tokens.", keys=leaked_tokens)
    else:
        report.add("pass", "public_manifest_has_no_tokens", "Public memorial manifest does not contain write/admin tokens.")

    consent, source = _voice_consent_from(slug, memorial)
    required_scopes = set(REQUIRED_PUBLIC_CONSENT_SCOPES)
    if require_clone_consent:
        required_scopes.update({"clone", "profile_build"})
    if consent.get("status") != "approved" or bool(consent.get("revoked")):
        report.add("fail", "voice_consent_not_approved", "Explicit voice consent is missing, revoked, or not approved.", source=source or "none")
    else:
        scopes = {str(item).strip() for item in list(consent.get("scope") or []) if str(item).strip()}
        missing = sorted(required_scopes - scopes)
        if missing:
            report.add("fail", "voice_consent_scope_missing", "Voice consent is approved but missing required public scopes.", missing=missing, source=source)
        else:
            report.add("pass", "voice_consent_ok", "Voice consent is explicit and covers public memorial speech.", scopes=sorted(scopes), source=source)

    allowed_assets = 0
    for section in ("audio_clips", "public_documents"):
        for item in list(memorial.get(section) or []):
            if not isinstance(item, dict):
                continue
            relpath = _relpath(str(item.get("asset_relpath") or ""))
            if not relpath:
                continue
            candidate = bundle / relpath
            suffix = candidate.suffix.lower()
            allowed_assets += 1
            if candidate.name.lower() in BLOCKED_PUBLIC_ASSET_NAMES:
                report.add("fail", "blocked_asset_listed", "A blocked config file is listed as public asset.", section=section, relpath=relpath)
            elif suffix not in ALLOWED_PUBLIC_ASSET_SUFFIXES:
                report.add("fail", "asset_suffix_not_allowed", "A public asset uses a non-public suffix.", section=section, relpath=relpath, suffix=suffix)
            elif not candidate.is_file():
                report.add("fail", "listed_asset_missing", "A listed public asset is missing from disk.", section=section, relpath=relpath)
            else:
                _check_joggai_public_document(
                    item=item,
                    candidate=candidate,
                    bundle=bundle,
                    section=section,
                    relpath=relpath,
                    report=report,
                )
    if allowed_assets:
        report.add("pass", "public_assets_manifest_driven", "Public assets are declared through manifest fields.", count=allowed_assets)
    else:
        report.add("warn", "no_public_assets_declared", "No audio/public document assets are declared in the public memorial manifest.")

    blocked_present = sorted(
        name for name in BLOCKED_PUBLIC_ASSET_NAMES if (bundle / name).is_file()
    )
    if blocked_present:
        report.add("fail", "blocked_files_present_in_public_bundle", "Private memorial config files are present in the public bundle.", filenames=blocked_present)
    else:
        report.add("pass", "blocked_files_absent_from_public_bundle", "Private memorial config files are absent from the public bundle.")

    _check_avatar_bundle(memorial, bundle=bundle, report=report)

    try:
        registry, registry_path = _public_registry_for(slug)
    except Exception as exc:
        report.add("fail", "archive_registry_invalid", "Public archive registry exists but could not be parsed.", error=str(exc))
        return
    if not registry:
        report.add("warn", "archive_registry_missing", "Public archive registry is missing or empty.", path=str(public_registry_path(slug, generated=False)))
        return
    non_public_audiences = sorted(
        {
            str(item.get("audience") or "")
            for item in list(registry.get("fliplink_publications") or [])
            if isinstance(item, dict) and str(item.get("audience") or "public").strip().lower() != "public"
        }
    )
    if non_public_audiences:
        report.add("fail", "archive_registry_exposes_non_public_audience", "Public archive registry still exposes non-public audiences.", audiences=non_public_audiences)
    else:
        report.add("pass", "archive_registry_public_only", "Public archive registry resolves to public publications only.", path=str(registry_path))


def http_request(url: str, *, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, str]:
    merged_headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, */*",
    }
    if headers:
        merged_headers.update(headers)
    request = urllib.request.Request(url, method=method, data=body, headers=merged_headers)
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def check_live(slug: str, report: Report, base_url: str) -> None:
    base = base_url.rstrip("/")
    public_json_payload: dict[str, Any] = {}

    status, _ = http_request(f"{base}/memorials/files/{slug}/memorial.json")
    if status == 404:
        report.add("pass", "live_raw_manifest_blocked", "Live raw memorial.json is blocked from the public asset route.")
    else:
        report.add("fail", "live_raw_manifest_exposed", "Live raw memorial.json is still publicly retrievable.", http_status=status)

    status, body = http_request(f"{base}/memorials/{slug}.json")
    if status != 200:
        report.add("fail", "live_public_json_unavailable", "Live public memorial JSON is unavailable.", http_status=status)
    else:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        public_json_payload = payload if isinstance(payload, dict) else {}
        leaked = sorted(key for key in PUBLIC_JSON_BLOCK_KEYS if payload.get(key))
        if leaked:
            report.add("fail", "live_public_json_leaks_sensitive_fields", "Live public memorial JSON leaks sensitive fields.", keys=leaked)
        else:
            report.add("pass", "live_public_json_sanitized", "Live public memorial JSON is sanitized.")

    status, body = http_request(f"{base}/memorials/{slug}")
    if status != 200:
        report.add("fail", "live_public_page_unavailable", "Live public memorial page is unavailable.", http_status=status)
    else:
        missing_markers = sorted(marker for marker in REQUIRED_PUBLIC_PAGE_MARKERS if marker not in body)
        if missing_markers:
            report.add(
                "fail",
                "live_public_page_missing_required_copy",
                "Live public memorial page is missing required minimal landing copy.",
                markers=missing_markers,
            )
        else:
            report.add("pass", "live_public_page_has_required_copy", "Live public memorial page exposes the current minimal landing copy.")
        present_forbidden = sorted(marker for marker in FORBIDDEN_PUBLIC_PAGE_MARKERS if marker in body)
        if present_forbidden:
            report.add("fail", "live_public_page_not_minimal", "Live public memorial page still exposes removed public sections.", markers=present_forbidden)
        else:
            report.add("pass", "live_public_page_minimal", "Live public memorial page stays on the minimal conversation-only surface.")
        avatar_payload = dict(public_json_payload.get("video_call_avatar") or {}) if isinstance(public_json_payload, dict) else {}
        avatar_enabled = bool(avatar_payload.get("enabled") is True)
        page_has_avatar_video = 'id="memorial-video-call-avatar-video"' in body
        if avatar_enabled and not page_has_avatar_video:
            report.add("fail", "live_avatar_video_missing_from_page", "Live page does not render avatar video even though public JSON says enabled.")
        elif avatar_enabled and page_has_avatar_video:
            report.add("pass", "live_avatar_video_present_on_page", "Live page renders avatar video when public JSON says enabled.")
        elif (not avatar_enabled) and page_has_avatar_video:
            report.add("fail", "live_avatar_video_present_while_disabled", "Live page still renders avatar video even though public JSON says disabled.")
        else:
            report.add("pass", "live_avatar_portrait_fallback_consistent", "Live page portrait fallback matches the public JSON avatar-disabled state.")

    status, body = http_request(f"{base}/memorials/{slug}/voice-config")
    if status != 200:
        report.add("fail", "live_voice_config_unavailable", "Live voice-config route is unavailable.", http_status=status)
    else:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        leaked = sorted(key for key in {"tts_plugin_voice_id", "provider_secret"} if key in payload)
        if leaked:
            report.add("fail", "live_voice_config_leaks_provider_data", "Live voice-config route leaks provider voice identifiers or secrets.", keys=leaked)
        else:
            report.add("pass", "live_voice_config_sanitized", "Live voice-config route does not expose raw provider identifiers.")

    status, body = http_request(f"{base}/memorials/{slug}/archive.json")
    if status == 200:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        non_public = sorted(
            {
                str(item.get("audience") or "")
                for item in list(payload.get("fliplink_publications") or [])
                if isinstance(item, dict) and str(item.get("audience") or "public").strip().lower() != "public"
            }
        )
        if non_public:
            report.add("fail", "live_archive_json_exposes_non_public_audience", "Live archive JSON still exposes non-public audiences.", audiences=non_public)
        else:
            report.add("pass", "live_archive_json_public_only", "Live archive JSON exposes public publications only.")
    else:
        report.add("warn", "live_archive_json_unavailable", "Live archive JSON endpoint is unavailable.", http_status=status)

    bad_tts_payload = json.dumps({"text": "Test", "tts_plugin_voice_id": "should-not-pass"}).encode("utf-8")
    status, _ = http_request(
        f"{base}/memorials/{slug}/speech-synthesize",
        method="POST",
        body=bad_tts_payload,
        headers={"Content-Type": "application/json"},
    )
    if status in {400, 403}:
        report.add("pass", "live_public_tts_rejects_override", "Live public TTS rejects client-supplied voice overrides.", http_status=status)
    else:
        report.add("fail", "live_public_tts_override_not_rejected", "Live public TTS accepted or ignored a forbidden voice override payload.", http_status=status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight checks for the current Manfred memorial flagship.")
    parser.add_argument("slug", help="memorial slug, e.g. manfred")
    parser.add_argument("--base-url", default="", help="Optional live base URL, e.g. https://myexternalbrain.com")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown")
    parser.add_argument("--require-clone-consent", action="store_true", help="Require clone/profile_build scopes in voice consent")
    args = parser.parse_args(argv)

    slug = safe_slug(args.slug)
    report = Report(slug=slug)
    check_filesystem(slug, report, require_clone_consent=args.require_clone_consent)
    if args.base_url:
        check_live(slug, report, args.base_url)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        report.print_markdown()
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
