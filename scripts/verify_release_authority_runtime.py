#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / ".codex-studio" / "published" / "release_authority_status.generated.json"


def _default_base_url() -> str:
    host_port = str(os.environ.get("EA_HOST_PORT") or "").strip()
    if not host_port:
        env_path = ROOT / ".env"
        if env_path.is_file():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if str(key).strip() == "EA_HOST_PORT":
                    host_port = str(value).strip()
    host_port = host_port or "8090"
    return f"http://localhost:{host_port}"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _fetch_json(url: str) -> dict[str, Any]:
    try:
        with request.urlopen(url, timeout=10) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeError(f"fetch_failed:{url}:{exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"fetch_invalid_json:{url}:{exc}") from exc
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _release_authority_urls(base_url: str) -> tuple[str, ...]:
    normalized = base_url.rstrip("/")
    return (
        f"{normalized}/health/release-authority",
        f"{normalized}/app/health/release-authority",
    )


def verify_runtime_release_authority(
    *,
    artifact_path: Path = DEFAULT_ARTIFACT,
    base_url: str | None = None,
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_json,
    require_authoritative: bool = False,
) -> dict[str, Any]:
    artifact = _load_json(artifact_path)
    if str(artifact.get("contract_name") or "").strip() != "ea.release_authority_status.v1":
        return {
            "contract_name": "ea.release_authority_runtime.v1",
            "status": "fail",
            "issues": ["release_authority_status_missing_or_invalid"],
            "artifact_path": str(artifact_path),
            "base_url": (base_url or _default_base_url()).rstrip("/"),
        }

    resolved_base_url = (base_url or _default_base_url()).rstrip("/")
    version_url = f"{resolved_base_url}/version"
    release_urls = _release_authority_urls(resolved_base_url)
    issues: list[str] = []
    errors: dict[str, str] = {}

    try:
        version = fetch_json(version_url)
    except Exception as exc:
        version = {}
        issues.append("version_fetch_failed")
        errors["version"] = str(exc)

    release: dict[str, Any] = {}
    release_url_used = ""
    last_release_error = ""
    for candidate_url in release_urls:
        try:
            release = fetch_json(candidate_url)
            release_url_used = candidate_url
            break
        except Exception as exc:
            last_release_error = str(exc)
    if not release_url_used:
        issues.append("release_authority_endpoint_unavailable")
        if last_release_error:
            errors["release_authority"] = last_release_error

    runtime_release = dict(release.get("release_authority") or {})

    if not runtime_release:
        return {
            "contract_name": "ea.release_authority_runtime.v1",
            "status": "fail",
            "issues": issues,
            "artifact_path": str(artifact_path),
            "base_url": resolved_base_url,
            "version_url": version_url,
            "release_authority_urls": list(release_urls),
            "release_authority_url_used": release_url_used,
            "errors": errors,
            "release_authority_source": str(version.get("release_authority_source") or ""),
            "release_authority_state": str(version.get("release_authority_state") or ""),
            "release_authority_posture": str(version.get("release_authority_posture") or ""),
            "deployment_id": str(version.get("deployment_id") or artifact.get("deployment_id") or ""),
            "deployment_id_source": str(version.get("deployment_id_source") or artifact.get("deployment_id_source") or ""),
            "public_origin": str(version.get("public_origin") or artifact.get("public_origin") or ""),
            "public_origin_source": str(version.get("public_origin_source") or artifact.get("public_origin_source") or ""),
            "deploy_context_gate_status": "",
            "deploy_context_gate_issues": [],
            "require_authoritative": require_authoritative,
            "release_authority_gate_status": "",
            "release_authority_gate_issues": [],
        }

    if str(runtime_release.get("source") or "") != "published_status_artifact":
        issues.append("runtime_not_using_published_status_artifact")
    if str(version.get("release_authority_source") or "") != str(runtime_release.get("source") or ""):
        issues.append("version_release_authority_source_mismatch")
    if str(version.get("release_authority_state") or "") != str(runtime_release.get("state") or ""):
        issues.append("version_release_authority_state_mismatch")
    if str(version.get("release_authority_posture") or "") != str(runtime_release.get("authority_posture") or ""):
        issues.append("version_release_authority_posture_mismatch")

    field_pairs = (
        ("state", "release_authority_state"),
        ("authority_posture", "release_authority_posture"),
        ("deployment_id", "deployment_id"),
        ("deployment_id_source", "deployment_id_source"),
        ("public_origin", "public_origin"),
        ("public_origin_source", "public_origin_source"),
        ("branch", "branch"),
        ("tracking_branch", "tracking_branch"),
        ("commit_sha", "commit_sha"),
        ("source_remote_ref", "source_remote_ref"),
        ("source_remote_ref_commit_sha", "source_remote_ref_commit_sha"),
        ("source_remote_ref_evidence", "source_remote_ref_evidence"),
    )
    for artifact_key, version_key in field_pairs:
        if str(artifact.get(artifact_key) or "") != str(version.get(version_key) or ""):
            issues.append(f"version_mismatch:{artifact_key}")
        if str(artifact.get(artifact_key) or "") != str(runtime_release.get(artifact_key) or ""):
            issues.append(f"release_endpoint_mismatch:{artifact_key}")
    artifact_reachable = artifact.get("source_commit_reachable_from_remote_ref")
    if artifact_reachable is not version.get("source_commit_reachable_from_remote_ref"):
        issues.append("version_mismatch:source_commit_reachable_from_remote_ref")
    if artifact_reachable is not runtime_release.get(
        "source_commit_reachable_from_remote_ref"
    ):
        issues.append("release_endpoint_mismatch:source_commit_reachable_from_remote_ref")

    gate = dict(runtime_release.get("gate") or {})
    deploy_context_gate = dict(runtime_release.get("deploy_context_gate") or {})
    if dict(release.get("release_authority_gate") or {}) != gate:
        issues.append("release_authority_gate_not_inlined")
    if dict(artifact.get("gate") or {}) != gate:
        issues.append("release_authority_gate_mismatch")
    if dict(release.get("deploy_context_gate") or {}) != deploy_context_gate:
        issues.append("deploy_context_gate_not_inlined")
    if dict(artifact.get("deploy_context_gate") or {}) != deploy_context_gate:
        issues.append("deploy_context_gate_mismatch")
    if require_authoritative:
        if str(gate.get("status") or "") != "pass":
            issues.append("release_authority_gate_failed")
        if str(deploy_context_gate.get("status") or "") != "pass":
            issues.append("deploy_context_gate_failed")
        if str(runtime_release.get("state") or "") != "clear":
            issues.append("release_authority_state_not_clear")
        if str(runtime_release.get("authority_posture") or "") != "authoritative_runtime":
            issues.append("release_authority_posture_not_authoritative")
        source_remote_ref = str(runtime_release.get("source_remote_ref") or "")
        source_remote_ref_commit_sha = str(
            runtime_release.get("source_remote_ref_commit_sha") or ""
        )
        tracking_branch = str(runtime_release.get("tracking_branch") or "")
        commit_sha = str(runtime_release.get("commit_sha") or "")
        source_remote_binding_proven = all(
            (
                bool(tracking_branch),
                source_remote_ref == f"refs/remotes/{tracking_branch}",
                len(source_remote_ref_commit_sha) == 40,
                all(character in "0123456789abcdef" for character in source_remote_ref_commit_sha),
                runtime_release.get("source_remote_ref_evidence")
                == "local_remote_tracking_ref",
                runtime_release.get("source_commit_reachable_from_remote_ref") is True,
                gate.get("source_remote_ref") == source_remote_ref,
                gate.get("source_remote_ref_commit_sha") == source_remote_ref_commit_sha,
                gate.get("source_remote_ref_evidence") == "local_remote_tracking_ref",
                gate.get("source_commit_reachable_from_remote_ref") is True,
                gate.get("tracking_branch") == tracking_branch,
                gate.get("commit_sha") == commit_sha,
            )
        )
        if not source_remote_binding_proven:
            issues.append("source_remote_binding_not_proven")

    return {
        "contract_name": "ea.release_authority_runtime.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "artifact_path": str(artifact_path),
        "base_url": resolved_base_url,
        "version_url": version_url,
        "release_authority_urls": list(release_urls),
        "release_authority_url_used": release_url_used,
        "errors": errors,
        "release_authority_source": str(runtime_release.get("source") or ""),
        "release_authority_state": str(runtime_release.get("state") or ""),
        "release_authority_posture": str(runtime_release.get("authority_posture") or ""),
        "source_remote_ref": str(runtime_release.get("source_remote_ref") or ""),
        "source_remote_ref_commit_sha": str(
            runtime_release.get("source_remote_ref_commit_sha") or ""
        ),
        "source_remote_ref_evidence": str(
            runtime_release.get("source_remote_ref_evidence") or ""
        ),
        "source_commit_reachable_from_remote_ref": (
            runtime_release.get("source_commit_reachable_from_remote_ref") is True
        ),
        "deployment_id": str(runtime_release.get("deployment_id") or ""),
        "deployment_id_source": str(runtime_release.get("deployment_id_source") or ""),
        "public_origin": str(runtime_release.get("public_origin") or ""),
        "public_origin_source": str(runtime_release.get("public_origin_source") or ""),
        "deploy_context_gate_status": str(deploy_context_gate.get("status") or ""),
        "deploy_context_gate_issues": [
            str(item).strip()
            for item in list(deploy_context_gate.get("issues") or [])
            if str(item).strip()
        ],
        "require_authoritative": require_authoritative,
        "release_authority_gate_status": str(gate.get("status") or ""),
        "release_authority_gate_issues": [
            str(item).strip()
            for item in list(gate.get("issues") or [])
            if str(item).strip()
        ],
    }


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_release_authority_runtime.py [--base-url URL] [--artifact PATH] [--pretty] [--require-authoritative]\n\n"
            "Compare live /version and /health/release-authority responses against the published\n"
            "release-authority status artifact."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify that live runtime release-authority endpoints match the published release-authority status artifact.")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--require-authoritative", action="store_true")
    args = parser.parse_args()

    result = verify_runtime_release_authority(
        artifact_path=args.artifact,
        base_url=str(args.base_url or "").strip() or None,
        require_authoritative=bool(args.require_authoritative),
    )
    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
