#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Finding:
    status: str
    code: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass
class AvatarReadinessReport:
    slug: str
    base_url: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(item.status == "fail" for item in self.findings):
            return "fail"
        if any(item.status == "warn" for item in self.findings):
            return "warn"
        return "pass"

    def add(self, status: str, code: str, **detail: object) -> None:
        self.findings.append(Finding(status=status, code=code, detail=dict(detail)))

    def as_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "base_url": self.base_url,
            "status": self.status,
            "findings": [asdict(item) for item in self.findings],
        }


def _absolute(base_url: str, value: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"{base_url.rstrip('/')}/{value.lstrip('/')}"


def _load_public_json(*, base_url: str, slug: str) -> tuple[int, dict[str, object]]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/memorials/{slug}.json", timeout=15.0) as response:
        return int(getattr(response, "status", 200) or 200), json.loads(response.read().decode("utf-8"))


def _load_page_html(*, base_url: str, slug: str) -> tuple[int, str]:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/memorials/{slug}", timeout=15.0) as response:
        return int(getattr(response, "status", 200) or 200), response.read().decode("utf-8", errors="replace")


def _check_remote_asset(url: str) -> tuple[int, int]:
    with urllib.request.urlopen(url, timeout=20.0) as response:
        payload = response.read()
        return int(getattr(response, "status", 200) or 200), len(payload)


def run_check(*, base_url: str, slug: str) -> AvatarReadinessReport:
    report = AvatarReadinessReport(slug=slug, base_url=base_url)
    status_json, payload = _load_public_json(base_url=base_url, slug=slug)
    status_html, html = _load_page_html(base_url=base_url, slug=slug)
    if status_json != 200 or not isinstance(payload, dict):
        report.add("fail", "avatar_public_json_unavailable", status=status_json)
        return report
    if status_html != 200:
        report.add("fail", "avatar_public_page_unavailable", status=status_html)
        return report
    avatar = dict(payload.get("video_call_avatar") or {})
    if avatar.get("enabled") is not True:
        provider_label = str(avatar.get("provider_label") or "").strip()
        if provider_label and provider_label in html:
            report.add("warn", "avatar_video_not_published", provider_label=provider_label)
        else:
            report.add("warn", "avatar_disabled_label_missing")
            report.add("warn", "avatar_video_not_published")
        return report
    asset_url = str(avatar.get("asset_url") or "").strip()
    poster_url = str(avatar.get("poster_url") or "").strip()
    if not re.search(r'id="memorial-video-call-avatar-video"', html):
        report.add("fail", "avatar_video_tag_missing")
        return report
    asset_status, asset_size = _check_remote_asset(_absolute(base_url, asset_url))
    if asset_status != 200 or asset_size <= 0:
        report.add("fail", "avatar_asset_unavailable", status=asset_status, size=asset_size)
        return report
    report.add("pass", "avatar_asset_available", size=asset_size)
    if poster_url:
        poster_status, poster_size = _check_remote_asset(_absolute(base_url, poster_url))
        if poster_status == 200 and poster_size > 0:
            report.add("pass", "avatar_poster_available", size=poster_size)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_check(base_url=args.base_url, slug=args.slug)
    payload = report.as_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.status in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
