#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    ".jpg", ".jpeg", ".png", ".webp", ".svg", ".pdf",
}
REQUIRED_PUBLIC_CONSENT_SCOPES = {"synthesize", "conversation_turn", "realtime"}
EXPECTED_INTERACTION_HINT = "Tippen, sprechen, kurz warten, einfach weiterreden."
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
        return any(item.status == "warn" for item in self.findings)

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
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def check_live(slug: str, report: Report, base_url: str) -> None:
    base = base_url.rstrip("/")

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
        leaked = sorted(key for key in PUBLIC_JSON_BLOCK_KEYS if payload.get(key))
        if leaked:
            report.add("fail", "live_public_json_leaks_sensitive_fields", "Live public memorial JSON leaks sensitive fields.", keys=leaked)
        else:
            report.add("pass", "live_public_json_sanitized", "Live public memorial JSON is sanitized.")

    status, body = http_request(f"{base}/memorials/{slug}")
    if status != 200:
        report.add("fail", "live_public_page_unavailable", "Live public memorial page is unavailable.", http_status=status)
    else:
        if EXPECTED_INTERACTION_HINT not in body:
            report.add("fail", "live_public_page_missing_interaction_hint", "Live public memorial page is missing the minimal conversation hint.")
        else:
            report.add("pass", "live_public_page_has_interaction_hint", "Live public memorial page exposes the minimal conversation hint.")
        present_forbidden = sorted(marker for marker in FORBIDDEN_PUBLIC_PAGE_MARKERS if marker in body)
        if present_forbidden:
            report.add("fail", "live_public_page_not_minimal", "Live public memorial page still exposes removed public sections.", markers=present_forbidden)
        else:
            report.add("pass", "live_public_page_minimal", "Live public memorial page stays on the minimal conversation-only surface.")

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
