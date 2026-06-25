#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SBOM_PATH = ROOT / ".codex-studio" / "published" / "runtime_dependency_sbom.cdx.json"
AUDIT_PATH = ROOT / ".codex-studio" / "published" / "runtime_dependency_audit.generated.json"
REQUIRED_REQUIREMENTS_SOURCES = {
    "ea/requirements.txt",
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def verify() -> dict[str, Any]:
    issues: list[str] = []
    if not SBOM_PATH.is_file():
        issues.append("sbom_missing")
        sbom = {}
    else:
        sbom = _load(SBOM_PATH)
    if not AUDIT_PATH.is_file():
        issues.append("audit_receipt_missing")
        audit = {}
    else:
        audit = _load(AUDIT_PATH)

    if sbom:
        if sbom.get("bomFormat") != "CycloneDX":
            issues.append("sbom_format_invalid")
        if sbom.get("specVersion") != "1.6":
            issues.append("sbom_spec_version_invalid")
        components = list(sbom.get("components") or [])
        if not components:
            issues.append("sbom_components_empty")
        else:
            sbom_sources = {
                str(prop.get("value") or "")
                for component in components
                if isinstance(component, dict)
                for prop in list(component.get("properties") or [])
                if isinstance(prop, dict) and str(prop.get("name") or "") == "ea.requirements_source"
            }
            missing_sources = sorted(REQUIRED_REQUIREMENTS_SOURCES - sbom_sources)
            if missing_sources:
                issues.append("sbom_requirements_sources_missing")
    if audit:
        if audit.get("contract_name") != "ea.runtime_dependency_audit.v1":
            issues.append("audit_contract_invalid")
        if audit.get("status") != "pass":
            issues.append("audit_status_not_pass")
        if int(audit.get("vulnerable_dependency_count") or 0) != 0:
            issues.append("audit_vulnerabilities_present")
        if Path(str(audit.get("sbom_path") or "")) != SBOM_PATH.relative_to(ROOT):
            issues.append("audit_sbom_path_invalid")
        sources = list(audit.get("requirements_sources") or [])
        if not sources:
            issues.append("audit_requirements_sources_missing")
        else:
            seen_sources = {str(item.get("requirements_path") or "") for item in sources if isinstance(item, dict)}
            missing_sources = sorted(REQUIRED_REQUIREMENTS_SOURCES - seen_sources)
            if missing_sources:
                issues.append("audit_requirements_sources_incomplete")
            if any(not str(item.get("requirements_sha256") or "").strip() for item in sources if isinstance(item, dict)):
                issues.append("audit_requirements_sources_sha_missing")

    return {
        "contract_name": "ea.runtime_dependency_evidence_verify.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "checked": {
            "sbom_path": SBOM_PATH.relative_to(ROOT).as_posix(),
            "audit_path": AUDIT_PATH.relative_to(ROOT).as_posix(),
        },
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
