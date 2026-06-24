#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_documentation_ai_public_docs import verify_public_docs  # noqa: E402


DEFAULT_PACKAGE_DIR = ROOT / "docs-public" / "executive-assistant"
DEFAULT_OUTPUT_PATH = ROOT / ".codex-studio" / "published" / "documentation_ai_deployment_readiness.generated.json"
EXPECTED_ORG = "Executive Assistant"
READY_DOMAIN_STATES = {"verified", "active", "ready", "connected"}
READY_SSL_STATES = {"active", "issued", "ready", "valid"}
READY_PUBLISH_STATES = {"published", "success", "deployed", "ready"}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _env_value(env: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        value = str(env.get(key) or "").strip()
        if value:
            return value
    return ""


def _split_repos(value: str) -> list[str]:
    normalized = value.replace("\n", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ("<", ">", "example", "yourcompany", "localhost", "127.0.0.1"))


def _context_repo_failures(repos: list[str]) -> list[str]:
    failures: list[str] = []
    if not repos:
        return ["context_repositories_not_configured"]
    if len(repos) > 2:
        failures.append("context_repository_limit_exceeded")
    joined = " ".join(repos).lower()
    if "archonmegalon/executive-assistant" in joined or "tiborgirschele/executive-assistant" in joined:
        failures.append("private_runtime_repository_connected")
    if not any(("docs" in repo.lower() or "documentation" in repo.lower()) for repo in repos):
        failures.append("public_docs_repository_not_configured")
    return failures


def build_deployment_readiness(
    *,
    env: Mapping[str, str] | None = None,
    package_dir: Path = DEFAULT_PACKAGE_DIR,
    git_head: str | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    current_head = git_head if git_head is not None else _git_head()
    public_doc_failures = verify_public_docs(package_dir)
    site_url = _env_value(env, "DOCUMENTATION_AI_EA_SITE_URL", "EA_DOCS_PUBLIC_URL")
    org = _env_value(env, "DOCUMENTATION_AI_EA_ORG")
    context_repos = _split_repos(_env_value(env, "DOCUMENTATION_AI_EA_CONTEXT_REPOS"))
    custom_domain_status = _env_value(env, "DOCUMENTATION_AI_EA_CUSTOM_DOMAIN_STATUS").lower()
    ssl_status = _env_value(env, "DOCUMENTATION_AI_EA_SSL_STATUS").lower()
    publish_status = _env_value(env, "DOCUMENTATION_AI_EA_PUBLISH_STATUS").lower()
    published_git_head = _env_value(env, "DOCUMENTATION_AI_EA_PUBLISHED_GIT_HEAD")
    provider_writeback = _env_value(env, "DOCUMENTATION_AI_EA_PROVIDER_WRITEBACK").lower()

    blockers: list[str] = []
    if public_doc_failures:
        blockers.append("public_docs_package_failed")
    if org != EXPECTED_ORG:
        blockers.append("documentation_ai_org_not_configured")
    if not site_url:
        blockers.append("site_url_not_configured")
    elif not site_url.startswith("https://") or _is_placeholder(site_url):
        blockers.append("site_url_not_public_https")
    blockers.extend(_context_repo_failures(context_repos))
    if custom_domain_status not in READY_DOMAIN_STATES:
        blockers.append("custom_domain_not_verified")
    if ssl_status not in READY_SSL_STATES:
        blockers.append("ssl_not_active")
    if publish_status not in READY_PUBLISH_STATES:
        blockers.append("site_not_published")
    if not current_head:
        blockers.append("source_git_head_unavailable")
    if not published_git_head:
        blockers.append("published_git_head_not_recorded")
    elif current_head and published_git_head != current_head:
        blockers.append("published_git_head_mismatch")
    if provider_writeback in {"1", "true", "yes", "enabled"}:
        blockers.append("provider_writeback_enabled")

    return {
        "contract": "ea.documentation_ai_deployment_readiness.v1",
        "generated_at": _utc_timestamp(),
        "status": "deployed" if not blockers else "blocked",
        "git_publication_ready": not public_doc_failures,
        "external_deployment_ready": not blockers,
        "blocking_reasons": blockers,
        "public_docs_failures": public_doc_failures,
        "documentation_ai": {
            "expected_org": EXPECTED_ORG,
            "configured_org": org,
            "site_url": site_url,
            "context_repositories": context_repos,
            "custom_domain_status": custom_domain_status,
            "ssl_status": ssl_status,
            "publish_status": publish_status,
            "provider_writeback_enabled": provider_writeback in {"1", "true", "yes", "enabled"},
        },
        "git": {
            "source_head": current_head,
            "published_head": published_git_head,
            "published_head_matches_source": bool(current_head and published_git_head == current_head),
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or enforce the EA Documentation.AI deployment readiness receipt.")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    parser.add_argument("--write", type=Path, default=None, help="Optional JSON receipt output path.")
    parser.add_argument("--require-deployed", action="store_true", help="Return non-zero unless external deployment is ready.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    receipt = build_deployment_readiness(package_dir=args.package_dir)
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        print(text, end="")
    if args.require_deployed and receipt["status"] != "deployed":
        print("Documentation.AI deployment readiness failed:", file=sys.stderr)
        for blocker in receipt["blocking_reasons"]:
            print(f"- {blocker}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
