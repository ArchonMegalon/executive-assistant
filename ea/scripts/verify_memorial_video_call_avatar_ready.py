#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html, */*",
    }
    if extra:
        headers.update(extra)
    return headers


def request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, method=method, data=body, headers=_headers(headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status), {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request_failed:{type(exc).__name__}:{exc}") from exc


@dataclass
class Finding:
    status: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AvatarReport:
    slug: str
    base_url: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, status: str, code: str, message: str, **detail: Any) -> None:
        self.findings.append(Finding(status=status, code=code, message=message, detail=detail))

    @property
    def failed(self) -> bool:
        return any(item.status == "fail" for item in self.findings)

    @property
    def warned(self) -> bool:
        return any(item.status == "warn" for item in self.findings)

    @property
    def status(self) -> str:
        if self.failed:
            return "fail"
        if self.warned:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "status": self.status,
            "findings": [
                {"status": item.status, "code": item.code, "message": item.message, "detail": item.detail}
                for item in self.findings
            ],
        }


def _load_public_json(*, base_url: str, slug: str) -> tuple[int, dict[str, Any]]:
    url = f"{base_url}/memorials/{urllib.parse.quote(slug)}.json"
    http_status, _, raw = request(url, timeout=20)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        payload = {}
    return http_status, payload if isinstance(payload, dict) else {}


def _load_page_html(*, base_url: str, slug: str) -> tuple[int, str]:
    url = f"{base_url}/memorials/{urllib.parse.quote(slug)}"
    http_status, _, raw = request(url, timeout=20)
    return http_status, raw.decode("utf-8", errors="replace")


def _check_remote_asset(url: str) -> tuple[int, int]:
    http_status, _, raw = request(url, timeout=20)
    return http_status, len(raw)


def run_check(*, base_url: str, slug: str) -> AvatarReport:
    report = AvatarReport(slug=slug, base_url=base_url)
    json_status, payload = _load_public_json(base_url=base_url, slug=slug)
    if json_status != 200:
        report.add("fail", "public_json_unavailable", "Public memorial JSON did not return 200.", http_status=json_status)
        return report
    report.add("pass", "public_json_available", "Public memorial JSON returned 200.")

    page_status, html = _load_page_html(base_url=base_url, slug=slug)
    if page_status != 200:
        report.add("fail", "landing_unavailable", "Public memorial page did not return 200.", http_status=page_status)
        return report
    report.add("pass", "landing_available", "Public memorial page returned 200.")

    avatar = dict(payload.get("video_call_avatar") or {})
    enabled = bool(avatar.get("enabled") is True)
    kind = str(avatar.get("kind") or "").strip()
    provider_label = str(avatar.get("provider_label") or "").strip()
    detail = str(avatar.get("detail") or "").strip()
    asset_url = str(avatar.get("asset_url") or "").strip()
    poster_url = str(avatar.get("poster_url") or "").strip()
    page_has_video_tag = 'id="memorial-video-call-avatar-video"' in html

    if enabled:
        if kind != "video":
            report.add("fail", "avatar_enabled_kind_mismatch", "Enabled avatar must report kind=video.", kind=kind)
        if not asset_url:
            report.add("fail", "avatar_asset_url_missing", "Enabled avatar is missing an asset URL.")
            return report
        if not page_has_video_tag:
            report.add("fail", "avatar_video_tag_missing", "Landing HTML does not render the avatar video element.")
        else:
            report.add("pass", "avatar_video_tag_present", "Landing HTML renders the avatar video element.")
        asset_status, asset_bytes = _check_remote_asset(f"{base_url}{asset_url}")
        if asset_status != 200 or asset_bytes <= 0:
            report.add("fail", "avatar_asset_unavailable", "Avatar video asset is not reachable from the public route.", http_status=asset_status, bytes=asset_bytes)
        else:
            report.add("pass", "avatar_asset_available", "Avatar video asset is reachable from the public route.", bytes=asset_bytes)
        if poster_url:
            poster_status, poster_bytes = _check_remote_asset(f"{base_url}{poster_url}")
            if poster_status != 200 or poster_bytes <= 0:
                report.add("fail", "avatar_poster_unavailable", "Avatar poster asset is not reachable from the public route.", http_status=poster_status, bytes=poster_bytes)
            else:
                report.add("pass", "avatar_poster_available", "Avatar poster asset is reachable from the public route.", bytes=poster_bytes)
        if provider_label and provider_label in html:
            report.add("pass", "avatar_provider_label_visible", "Avatar provider label is visible on the landing page.", provider_label=provider_label)
        else:
            report.add("warn", "avatar_provider_label_not_visible", "Avatar provider label is not visible on the landing page.", provider_label=provider_label)
        return report

    if kind != "portrait":
        report.add("fail", "avatar_disabled_kind_mismatch", "Disabled avatar must report kind=portrait.", kind=kind)
    if asset_url or poster_url:
        report.add("fail", "avatar_disabled_urls_present", "Disabled avatar must not expose asset URLs.", asset_url=asset_url, poster_url=poster_url)
    if page_has_video_tag:
        report.add("fail", "avatar_video_tag_present_while_disabled", "Landing HTML still renders a video avatar element while JSON says disabled.")
    else:
        report.add("pass", "avatar_portrait_fallback_present", "Landing HTML stays on portrait fallback while avatar is disabled.")
    if provider_label and provider_label in html:
        report.add("pass", "avatar_disabled_label_visible", "Landing page visibly explains the disabled avatar state.", provider_label=provider_label)
    else:
        report.add("warn", "avatar_disabled_label_missing", "Landing page does not visibly explain the disabled avatar state.", provider_label=provider_label)
    if "Portraitvorschau" in detail or "nicht freigegeben" in detail:
        report.add("warn", "avatar_video_not_published", "Avatar video is still not published; portrait fallback remains active.", detail=detail)
    else:
        report.add("warn", "avatar_disabled_detail_unclear", "Avatar is disabled but the public detail text is not explicit enough.", detail=detail)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the public memorial video-call avatar state.")
    parser.add_argument("--slug", default="manfred")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_check(base_url=str(args.base_url).rstrip("/"), slug=str(args.slug).strip())
    rendered = json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else json.dumps(report.as_dict(), ensure_ascii=False)
    print(rendered)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
