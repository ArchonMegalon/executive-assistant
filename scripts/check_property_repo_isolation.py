#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

QUARANTINED_ARTIFACTS = (
    ".codex-design/",
    ".codex-studio/",
    "feedback/",
    "skills/",
    "scripts/bootstrap_chummer6_guide_skill.py",
)

RUNTIME_RELEASE_FILES = (
    "docker-compose.property.yml",
    "ea/Dockerfile.property",
    "scripts/property_release_gates.sh",
)

FORBIDDEN_RUNTIME_TOKENS = (
    ".codex-design",
    ".codex-studio",
    "/feedback",
    " feedback/",
    "skills/",
    "bootstrap_chummer6_guide_skill",
    "/docker/chummercomplete",
    "chummer-playwright",
    "ea-openvoice",
    "openvoice",
    "ea-responses-proxy",
    "ea-teable-relay",
    "/mnt/onedrive",
    "/mnt/pcloud",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _makefile_deploy_uses_property_compose(makefile: str) -> bool:
    match = re.search(r"^deploy:\n(?P<body>(?:\t.*\n)+)", makefile, flags=re.MULTILINE)
    if not match:
        return False
    return "docker-compose.property.yml" in match.group("body")


def main() -> int:
    failures: list[str] = []
    doc_path = ROOT / "docs" / "REPO_ISOLATION.md"
    if not doc_path.exists():
        failures.append("docs/REPO_ISOLATION.md must document inherited archive quarantine")
    else:
        doc_text = doc_path.read_text(encoding="utf-8")
        for artifact in QUARANTINED_ARTIFACTS:
            if artifact not in doc_text:
                failures.append(f"docs/REPO_ISOLATION.md must list quarantined artifact {artifact}")

    for path in RUNTIME_RELEASE_FILES:
        text = _read(path)
        lowered = text.lower()
        for token in FORBIDDEN_RUNTIME_TOKENS:
            if token.lower() in lowered:
                failures.append(f"{path} references inherited/non-property runtime token {token!r}")

    makefile = _read("Makefile")
    if not _makefile_deploy_uses_property_compose(makefile):
        failures.append("Makefile deploy target must use docker-compose.property.yml")
    if "PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh" not in makefile:
        failures.append("Makefile must keep legacy EA deploy behind PROPERTYQUARRY_USE_LEGACY_STACK=1")

    architecture = _read("docs/ARCHITECTURE.md")
    if "REPO_ISOLATION.md" not in architecture:
        failures.append("docs/ARCHITECTURE.md must point to docs/REPO_ISOLATION.md")

    if failures:
        print("property repo isolation check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: property repo isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
