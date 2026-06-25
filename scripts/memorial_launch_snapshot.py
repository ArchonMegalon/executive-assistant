#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import scripts.memorial_demo_rehearsal as rehearsal
import scripts.memorial_flagship_preflight as preflight
import scripts.verify_memorial_video_call_avatar_ready as avatar_ready

_OPTIONAL_AVATAR_WARN_CODES = {
    "avatar_disabled_label_missing",
    "avatar_manifest_missing",
    "avatar_video_not_published",
}


def _extract_json_status(raw: str) -> tuple[str, dict[str, object]]:
    payload = json.loads(raw)
    findings = [dict(item) for item in list(payload.get("findings") or []) if isinstance(item, dict)]
    warn_codes = [str(item.get("code") or "") for item in findings if str(item.get("status") or "") == "warn"]
    return str(payload.get("status") or "fail"), {"finding_count": len(findings), "warn_codes": warn_codes}


def snapshot_status(commands: list[dict[str, object]]) -> str:
    has_warn = False
    for item in commands:
        if int(item.get("returncode") or 0) != 0:
            return "fail"
        semantic = str(item.get("semantic_status") or "pass")
        warn_codes = list(dict(item.get("semantic_detail") or {}).get("warn_codes") or [])
        if semantic == "fail":
            return "fail"
        if semantic == "warn":
            if not warn_codes or set(warn_codes) - _OPTIONAL_AVATAR_WARN_CODES:
                has_warn = True
    return "warn" if has_warn else "pass"


def build_snapshot(*, slug: str, base_url: str, questions: str) -> dict[str, object]:
    commands: list[dict[str, object]] = []
    preflight_report = preflight.Report(slug=slug)
    preflight.check_live(slug, preflight_report, base_url)
    commands.append(
        {
            "command": ["python3", "scripts/memorial_flagship_preflight.py", slug, "--base-url", base_url, "--json"],
            "returncode": 0 if preflight_report.status in {"pass", "warn"} else 1,
            "stdout": json.dumps(preflight_report.as_dict(), ensure_ascii=False),
            "semantic_status": preflight_report.status,
            "semantic_detail": {"warn_codes": [item.code for item in preflight_report.findings if item.status == "warn"]},
        }
    )
    avatar_report = avatar_ready.run_check(base_url=base_url, slug=slug)
    commands.append(
        {
            "command": ["python3", "scripts/verify_memorial_video_call_avatar_ready.py", "--base-url", base_url, "--slug", slug, "--json"],
            "returncode": 0 if avatar_report.status in {"pass", "warn"} else 1,
            "stdout": json.dumps(avatar_report.as_dict(), ensure_ascii=False),
            "semantic_status": avatar_report.status,
            "semantic_detail": {"warn_codes": [item.code for item in avatar_report.findings if item.status == "warn"]},
        }
    )
    rehearsal_report = rehearsal.run_rehearsal(slug=slug, base_url=base_url, questions_path=questions)
    commands.append(
        {
            "command": ["python3", "scripts/memorial_demo_rehearsal.py", slug, "--base-url", base_url, "--questions", questions, "--json"],
            "returncode": 0 if rehearsal_report.as_dict()["status"] in {"pass", "warn"} else 1,
            "stdout": json.dumps(rehearsal_report.as_dict(), ensure_ascii=False),
            "semantic_status": rehearsal_report.as_dict()["status"],
            "semantic_detail": {"warn_codes": [item.code for item in rehearsal_report.checks if item.status == "warn"]},
        }
    )
    return {
        "slug": slug,
        "base_url": base_url,
        "status": snapshot_status(commands),
        "commands": commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--questions", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = build_snapshot(slug=args.slug, base_url=args.base_url, questions=args.questions)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
