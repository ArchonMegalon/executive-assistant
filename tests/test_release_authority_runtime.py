from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "verify_release_authority_runtime.py"
    spec = importlib.util.spec_from_file_location("verify_release_authority_runtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_authority_runtime_verifier_accepts_matching_runtime(tmp_path: Path) -> None:
    module = _load_script()
    artifact = tmp_path / "release_authority_status.generated.json"
    artifact.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_authority_status.v1",
                "state": "clear",
                "authority_posture": "authoritative_runtime",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source_remote_ref": "refs/remotes/origin/main",
                "source_remote_ref_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source_remote_ref_evidence": "local_remote_tracking_ref",
                "source_commit_reachable_from_remote_ref": True,
                "manifest_path": "/tmp/release_manifest.generated.json",
                "project_modes_path": "/tmp/PROJECT_MODES.generated.json",
                "deploy_context_gate": {
                    "contract_name": "ea.deploy_context_gate.v1",
                    "status": "pass",
                    "issues": [],
                },
                "gate": {
                    "contract_name": "ea.release_authority_gate.v1",
                    "status": "pass",
                    "issues": [],
                    "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "tracking_branch": "origin/main",
                    "source_remote_ref": "refs/remotes/origin/main",
                    "source_remote_ref_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "source_remote_ref_evidence": "local_remote_tracking_ref",
                    "source_commit_reachable_from_remote_ref": True,
                },
            }
        ),
        encoding="utf-8",
    )

    responses = {
        "http://runtime.test/version": {
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "published_status_artifact",
            "deployment_id": "deploy-123",
            "deployment_id_source": "explicit",
            "public_origin": "https://ea.example.test",
            "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
            "branch": "main",
            "tracking_branch": "origin/main",
            "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "source_remote_ref": "refs/remotes/origin/main",
            "source_remote_ref_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "source_remote_ref_evidence": "local_remote_tracking_ref",
            "source_commit_reachable_from_remote_ref": True,
        },
        "http://runtime.test/health/release-authority": {
            "release_authority": {
                "source": "published_status_artifact",
                "state": "clear",
                "authority_posture": "authoritative_runtime",
                "deployment_id": "deploy-123",
                "deployment_id_source": "explicit",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source_remote_ref": "refs/remotes/origin/main",
                "source_remote_ref_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source_remote_ref_evidence": "local_remote_tracking_ref",
                "source_commit_reachable_from_remote_ref": True,
                "deploy_context_gate": {
                    "contract_name": "ea.deploy_context_gate.v1",
                    "status": "pass",
                    "issues": [],
                },
                "gate": {
                    "contract_name": "ea.release_authority_gate.v1",
                    "status": "pass",
                    "issues": [],
                    "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "tracking_branch": "origin/main",
                    "source_remote_ref": "refs/remotes/origin/main",
                    "source_remote_ref_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "source_remote_ref_evidence": "local_remote_tracking_ref",
                    "source_commit_reachable_from_remote_ref": True,
                },
            },
            "deploy_context_gate": {
                "contract_name": "ea.deploy_context_gate.v1",
                "status": "pass",
                "issues": [],
            },
            "release_authority_gate": {
                "contract_name": "ea.release_authority_gate.v1",
                "status": "pass",
                "issues": [],
                "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "tracking_branch": "origin/main",
                "source_remote_ref": "refs/remotes/origin/main",
                "source_remote_ref_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source_remote_ref_evidence": "local_remote_tracking_ref",
                "source_commit_reachable_from_remote_ref": True,
            },
        },
    }

    result = module.verify_runtime_release_authority(
        artifact_path=artifact,
        base_url="http://runtime.test",
        fetch_json=lambda url: dict(responses[url]),
        require_authoritative=True,
    )

    assert result["contract_name"] == "ea.release_authority_runtime.v1"
    assert result["status"] == "pass"
    assert result["issues"] == []
    assert result["require_authoritative"] is True
    assert result["source_commit_reachable_from_remote_ref"] is True
    assert result["deploy_context_gate_status"] == "pass"
    assert result["deploy_context_gate_issues"] == []
    assert result["release_authority_gate_status"] == "pass"
    assert result["release_authority_gate_issues"] == []


def test_release_authority_runtime_verifier_rejects_endpoint_mismatch(tmp_path: Path) -> None:
    module = _load_script()
    artifact = tmp_path / "release_authority_status.generated.json"
    artifact.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_authority_status.v1",
                "state": "watch",
                "authority_posture": "missing_public_origin",
                "deployment_id": "deploy-999",
                "deployment_id_source": "explicit",
                "public_origin": "",
                "public_origin_source": "missing",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "manifest_path": "/tmp/release_manifest.generated.json",
                "project_modes_path": "/tmp/PROJECT_MODES.generated.json",
                "deploy_context_gate": {
                    "contract_name": "ea.deploy_context_gate.v1",
                    "status": "fail",
                    "issues": ["missing_deployment_id"],
                },
                "gate": {"contract_name": "ea.release_authority_gate.v1", "status": "fail", "issues": ["public_origin_missing"]},
            }
        ),
        encoding="utf-8",
    )

    responses = {
        "http://runtime.test/version": {
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "manifest_fallback",
            "deployment_id": "deploy-999",
            "deployment_id_source": "explicit",
            "public_origin": "",
            "public_origin_source": "missing",
            "branch": "main",
            "tracking_branch": "origin/main",
            "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
        "http://runtime.test/health/release-authority": {
            "release_authority": {
                "source": "manifest_fallback",
                "state": "clear",
                "authority_posture": "authoritative_runtime",
                "deployment_id": "deploy-999",
                "deployment_id_source": "explicit",
                "public_origin": "",
                "public_origin_source": "missing",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "deploy_context_gate": {
                    "contract_name": "ea.deploy_context_gate.v1",
                    "status": "fail",
                    "issues": ["missing_deployment_id"],
                },
                "gate": {"contract_name": "ea.release_authority_gate.v1", "status": "fail", "issues": ["public_origin_missing"]},
            },
            "deploy_context_gate": {
                "contract_name": "ea.deploy_context_gate.v1",
                "status": "pass",
                "issues": [],
            },
            "release_authority_gate": {"contract_name": "ea.release_authority_gate.v1", "status": "fail", "issues": ["public_origin_missing"]},
        },
    }

    result = module.verify_runtime_release_authority(
        artifact_path=artifact,
        base_url="http://runtime.test",
        fetch_json=lambda url: dict(responses[url]),
    )

    assert result["status"] == "fail"
    assert "runtime_not_using_published_status_artifact" in result["issues"]
    assert "version_mismatch:state" in result["issues"]
    assert "release_endpoint_mismatch:state" in result["issues"]
    assert "deploy_context_gate_not_inlined" in result["issues"]
    assert result["deploy_context_gate_status"] == "fail"
    assert result["deploy_context_gate_issues"] == ["missing_deployment_id"]
    assert result["release_authority_gate_status"] == "fail"
    assert result["release_authority_gate_issues"] == ["public_origin_missing"]


def test_release_authority_runtime_verifier_returns_structured_failure_when_release_endpoint_is_missing(tmp_path: Path) -> None:
    module = _load_script()
    artifact = tmp_path / "release_authority_status.generated.json"
    artifact.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_authority_status.v1",
                "state": "watch",
                "authority_posture": "local_only_deploy_id",
                "deployment_id": "local-deploy-123",
                "deployment_id_source": "local_fallback",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "cccccccccccccccccccccccccccccccccccccccc",
                "manifest_path": "/tmp/release_manifest.generated.json",
                "project_modes_path": "/tmp/PROJECT_MODES.generated.json",
            }
        ),
        encoding="utf-8",
    )

    def _fetch(url: str) -> dict[str, object]:
        if url == "http://runtime.test/version":
            return {
                "release_authority_state": "watch",
                "release_authority_posture": "local_only_deploy_id",
                "release_authority_source": "published_status_artifact",
                "deployment_id": "local-deploy-123",
                "public_origin": "https://ea.example.test",
            }
        raise RuntimeError(f"fetch_failed:{url}:HTTP Error 404: Not Found")

    result = module.verify_runtime_release_authority(
        artifact_path=artifact,
        base_url="http://runtime.test",
        fetch_json=_fetch,
    )

    assert result["status"] == "fail"
    assert "release_authority_endpoint_unavailable" in result["issues"]
    assert result["version_url"] == "http://runtime.test/version"
    assert result["release_authority_urls"] == [
        "http://runtime.test/health/release-authority",
        "http://runtime.test/app/health/release-authority",
    ]
    assert result["release_authority_url_used"] == ""
    assert "release_authority" in result["errors"]
    assert result["deployment_id_source"] == "local_fallback"
    assert result["public_origin_source"] == "EA_PUBLIC_APP_BASE_URL"
    assert result["deploy_context_gate_status"] == ""
    assert result["deploy_context_gate_issues"] == []


def test_release_authority_runtime_verifier_can_require_authoritative_runtime(tmp_path: Path) -> None:
    module = _load_script()
    artifact = tmp_path / "release_authority_status.generated.json"
    artifact.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_authority_status.v1",
                "state": "watch",
                "authority_posture": "local_only_deploy_id",
                "deployment_id": "local-deploy-123",
                "deployment_id_source": "local_fallback",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "cccccccccccccccccccccccccccccccccccccccc",
                "manifest_path": "/tmp/release_manifest.generated.json",
                "project_modes_path": "/tmp/PROJECT_MODES.generated.json",
                "deploy_context_gate": {
                    "contract_name": "ea.deploy_context_gate.v1",
                    "status": "fail",
                    "issues": ["deployment_id_local_fallback"],
                },
                "gate": {
                    "contract_name": "ea.release_authority_gate.v1",
                    "status": "fail",
                    "issues": ["deployment_id_local_fallback", "dirty_worktree"],
                },
            }
        ),
        encoding="utf-8",
    )

    responses = {
        "http://runtime.test/version": {
            "release_authority_state": "watch",
            "release_authority_posture": "local_only_deploy_id",
            "release_authority_source": "published_status_artifact",
            "deployment_id": "local-deploy-123",
            "deployment_id_source": "local_fallback",
            "public_origin": "https://ea.example.test",
            "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
            "branch": "main",
            "tracking_branch": "origin/main",
            "commit_sha": "cccccccccccccccccccccccccccccccccccccccc",
        },
        "http://runtime.test/health/release-authority": {
            "release_authority": {
                "source": "published_status_artifact",
                "state": "watch",
                "authority_posture": "local_only_deploy_id",
                "deployment_id": "local-deploy-123",
                "deployment_id_source": "local_fallback",
                "public_origin": "https://ea.example.test",
                "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
                "branch": "main",
                "tracking_branch": "origin/main",
                "commit_sha": "cccccccccccccccccccccccccccccccccccccccc",
                "deploy_context_gate": {
                    "contract_name": "ea.deploy_context_gate.v1",
                    "status": "fail",
                    "issues": ["deployment_id_local_fallback"],
                },
                "gate": {
                    "contract_name": "ea.release_authority_gate.v1",
                    "status": "fail",
                    "issues": ["deployment_id_local_fallback", "dirty_worktree"],
                },
            },
            "deploy_context_gate": {
                "contract_name": "ea.deploy_context_gate.v1",
                "status": "fail",
                "issues": ["deployment_id_local_fallback"],
            },
            "release_authority_gate": {
                "contract_name": "ea.release_authority_gate.v1",
                "status": "fail",
                "issues": ["deployment_id_local_fallback", "dirty_worktree"],
            },
        },
    }

    result = module.verify_runtime_release_authority(
        artifact_path=artifact,
        base_url="http://runtime.test",
        fetch_json=lambda url: dict(responses[url]),
        require_authoritative=True,
    )

    assert result["status"] == "fail"
    assert result["require_authoritative"] is True
    assert "release_authority_gate_failed" in result["issues"]
    assert "deploy_context_gate_failed" in result["issues"]
    assert "release_authority_state_not_clear" in result["issues"]
    assert "release_authority_posture_not_authoritative" in result["issues"]
