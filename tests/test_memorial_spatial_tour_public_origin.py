from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import materialize_memorial_spatial_tour_public_origin as materializer
from scripts import memorial_spatial_public_origin_contract as contract
from scripts.prepare_manfred_memorial_candidate import _spatial_package_sha256
from tests.test_manfred_spatial_candidate_browser import _valid_receipt


ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
FINGERPRINT = "b" * 64
ORIGIN = "https://myexternalbrain.com"


@pytest.mark.parametrize(
    "script_name",
    (
        "materialize_memorial_spatial_tour_public_origin.py",
        "verify_memorial_spatial_tour_public_origin.py",
    ),
)
def test_spatial_entrypoints_support_external_direct_execution(
    script_name: str,
    tmp_path: Path,
) -> None:
    external_python = tmp_path / "external-venv" / "bin" / "python"
    external_python.parent.mkdir(parents=True)
    external_python.symlink_to(Path(sys.executable).resolve())
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "ea")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [
            str(external_python),
            str(ROOT / "scripts" / script_name),
            "--help",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def _encoded(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


def _write_private(path: Path, payload: object) -> bytes:
    content = _encoded(payload)
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def _cleanup_state_directory_identity(path: Path) -> dict[str, object]:
    metadata = path.stat()
    return {
        "path": str(path),
        "dev": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "mode": int(stat.S_IMODE(metadata.st_mode)),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }


def _public_spatial(
    browser: dict[str, object],
    *,
    authority_sha256: str,
) -> dict[str, object]:
    binding = dict(browser["package_binding"])
    file_rows = {
        str(row["path"]): dict(row)
        for row in list(binding["local_files"])
        if isinstance(row, dict)
    }
    slug = contract.PROPERTY_TOUR_SLUG
    viewer_root = f"/tours/viewer/{slug}"
    specs = {
        "version": ("/version", 200, "application/json", None),
        "landing": (f"/tours/{slug}", 200, "text/html", None),
        "tour_json": (
            f"/tours/{slug}.json",
            200,
            "application/json",
            "tour.json",
        ),
        "viewer": (
            f"{viewer_root}/{contract.VIEWER_RELPATH}",
            200,
            "text/html",
            contract.VIEWER_RELPATH,
        ),
        "floorplan": (
            f"{viewer_root}/{contract.FLOORPLAN_RELPATH}",
            200,
            "image/png",
            contract.FLOORPLAN_RELPATH,
        ),
        "three_module": (
            f"{viewer_root}/{contract.THREE_RELPATH}",
            200,
            "text/javascript",
            contract.THREE_RELPATH,
        ),
        "orbit_controls": (
            f"{viewer_root}/{contract.ORBIT_RELPATH}",
            200,
            "text/javascript",
            contract.ORBIT_RELPATH,
        ),
        "proof_only": (
            f"{viewer_root}/{contract.PROOF_RELPATH}",
            404,
            "application/json",
            contract.PROOF_RELPATH,
        ),
    }
    routes: dict[str, dict[str, object]] = {}
    empty_sha = hashlib.sha256(b"").hexdigest()
    for label in materializer.ROUTE_LABELS:
        name, method_lower = label.rsplit("_", 1)
        method = method_lower.upper()
        path, status, content_type, relpath = specs[name]
        if method == "HEAD":
            body_bytes = 0
            body_sha256 = empty_sha
        elif relpath and name not in {"proof_only", "tour_json"}:
            body_bytes = int(file_rows[relpath]["size_bytes"])
            body_sha256 = str(file_rows[relpath]["sha256"])
        else:
            body_bytes = 48
            body_sha256 = "e" * 64
        row: dict[str, object] = {
            "path": path,
            "method": method,
            "status": status,
            "content_type": content_type,
            "source_revision": HEAD,
            "body_bytes": body_bytes,
            "body_sha256": body_sha256,
        }
        if label == "version_get":
            row["commit_sha"] = HEAD
        elif label == "tour_json_get":
            public_tour = dict(binding["public_tour_manifest"])
            row["canonical_json_sha256"] = public_tour[
                "canonical_json_sha256"
            ]
        elif label in {
            "viewer_get",
            "floorplan_get",
            "three_module_get",
            "orbit_controls_get",
        }:
            row["candidate_file_identity_verified"] = True
        elif label == "proof_only_get":
            row["candidate_file_not_disclosed"] = True
        routes[label] = row
    return {
        "status": "pass",
        "origin": ORIGIN,
        "slug": slug,
        "source_revision": HEAD,
        "request_count": 16,
        "get_count": 8,
        "head_count": 8,
        "routes": routes,
        "exact_byte_file_count": 4,
        "canonical_json_file_count": 1,
        "proof_only_404": True,
        "redirect_count": 0,
        "external_request_count": 0,
        "provider_calls_performed": False,
        "property_authority": {
            "owner": contract.PROPERTY_AUTHORITY_OWNER,
            "artifact_commit": contract.PROPERTY_ARTIFACT_COMMIT,
            "publication_authority_sha256": authority_sha256,
            "package_sha256": browser["package_sha256"],
            "upstream_public_activation_authority": True,
            "ea_public_activation_authority": False,
        },
    }


def _valid_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    joint_deploy: bool = True,
) -> tuple[Path, Path, materializer.SourceState]:
    browser = copy.deepcopy(_valid_receipt())
    browser["slug"] = contract.PROPERTY_TOUR_SLUG
    browser["candidate_commit"] = HEAD
    version = dict(browser["candidate_version"])
    for key in (
        "commit_sha",
        "body_commit_sha",
        "source_revision_header",
        "expected_commit_sha",
        "oci_image_revision",
    ):
        version[key] = HEAD
    browser["candidate_version"] = version
    image = dict(browser["candidate_oci_image"])
    image["oci_image_revision"] = HEAD
    browser["candidate_oci_image"] = image
    binding = dict(browser["package_binding"])
    local_files = [dict(row) for row in list(binding["local_files"])]
    binding["local_files"] = local_files
    viewer_path = (
        f"/tours/viewer/{contract.PROPERTY_TOUR_SLUG}/"
        f"{contract.VIEWER_RELPATH}"
    )
    public_tour_payload = {
        "slug": contract.PROPERTY_TOUR_SLUG,
        "tour_privacy_mode": "coarse_location",
        "facts": {},
        "brief": {},
        "scenes": [],
        "public_assets": [],
        "generated_viewer": {
            "url": viewer_path,
            "release_revision": binding["release_revision"],
            "disclosure": "Generated interactive reconstruction.",
            "synthetic": True,
            "verified_provider_capture": False,
        },
    }
    public_tour_body = json.dumps(
        public_tour_payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    binding["public_tour_manifest"] = {
        "path": f"/tours/{contract.PROPERTY_TOUR_SLUG}.json",
        "status": 200,
        "content_type": "application/json",
        "body_sha256": hashlib.sha256(public_tour_body).hexdigest(),
        "body_bytes": len(public_tour_body),
        "canonical_json_sha256": contract.canonical_json_sha256(
            public_tour_payload
        ),
        "source_revision": HEAD,
        "source_revision_verified": True,
        "slug": contract.PROPERTY_TOUR_SLUG,
        "release_revision": binding["release_revision"],
        "generated_viewer_url": viewer_path,
        "public_projection_verified": True,
    }
    browser["package_binding"] = binding
    tour_sha = str(next(row for row in local_files if row["path"] == "tour.json")["sha256"])
    monkeypatch.setattr(contract, "PROPERTY_TOUR_SHA256", tour_sha)

    authority = {
        "schema": contract.PROPERTY_AUTHORITY_SCHEMA,
        "status": "authorized",
        "owner": contract.PROPERTY_AUTHORITY_OWNER,
        "repository": contract.PROPERTY_REPOSITORY,
        "slug": contract.PROPERTY_TOUR_SLUG,
        "public_activation_authority": True,
        "publication_authority_verified": True,
        "source": {
            "artifact_commit": contract.PROPERTY_ARTIFACT_COMMIT,
            "packager_commit": contract.PROPERTY_PACKAGER_COMMIT,
            "worktree_clean": True,
        },
        "review_receipts": {
            "flagship_final": {
                "sha256": contract.PROPERTY_FINAL_REVIEW_SHA256,
            },
            "exact_viewer_browser": {
                "sha256": contract.PROPERTY_BROWSER_REVIEW_SHA256,
            },
        },
    }
    authority_sha = hashlib.sha256(
        json.dumps(
            authority,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    ).hexdigest()
    monkeypatch.setattr(contract, "PROPERTY_AUTHORITY_SHA256", authority_sha)

    spatial = {
        "schema": materializer.SPATIAL_PROJECTION_SCHEMA,
        "status": "pass",
        "slug": contract.PROPERTY_TOUR_SLUG,
        "public_activation_authority": False,
        "upstream_public_activation_authority": True,
        "upstream_publication_authority": authority,
        "upstream_publication_authority_sha256": authority_sha,
        "upstream_package_sha256": browser["package_sha256"],
        "upstream_tour_manifest_sha256": tour_sha,
        "pre_authority_manifest_canonical_sha256": (
            contract.PROPERTY_PRE_AUTHORITY_SHA256
        ),
        "route_labels": [f"Stop {index}" for index in range(1, 10)],
    }
    spatial_path = tmp_path / "spatial.private.json"
    spatial_bytes = _write_private(spatial_path, spatial)

    candidate = {
        "schema": materializer.CANDIDATE_RUNTIME_SCHEMA,
        "status": "pass",
        "projection_commit": HEAD,
        "image_source_revision": HEAD,
        "runtime_source_revision": HEAD,
        "runtime_authority_commit": HEAD,
        "runtime_revision_matches_image": True,
        "provider_calls_performed": False,
        "promotion_authority": False,
        "spatial_handoff": {
            "receipt_path": str(spatial_path),
            "receipt_sha256": hashlib.sha256(spatial_bytes).hexdigest(),
        },
        "spatial_handoff_runtime": {"candidate_browser_gate": browser},
    }
    candidate_path = tmp_path / "candidate.private.json"
    candidate_bytes = _write_private(candidate_path, candidate)
    browser_path = tmp_path / "browser.private.json"
    browser_bytes = _write_private(browser_path, browser)
    public_spatial = _public_spatial(browser, authority_sha256=authority_sha)
    deploy = {
        "contract_name": contract.DEPLOY_RECEIPT_CONTRACT,
        "deployment_id": "manfred-20260717-release",
        "status": "pass",
        "source_revision": HEAD,
        "public_origin": ORIGIN,
        "completed_at": "2026-07-17T12:00:00Z",
        "source_worktree": {"source_worktree_dirty": False},
        "candidate_promotion_evidence": {
            "path": str(candidate_path),
            "sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "status": "pass",
            "source_revision": HEAD,
        },
        "public_spatial_tour": public_spatial,
    }
    deploy_path = tmp_path / "deploy.private.json"
    if joint_deploy:
        cleanup_state_directory = tmp_path / "joint-cleanup-state"
        cleanup_state_directory.mkdir(mode=0o700)
        cleanup_journal_path = (
            cleanup_state_directory
            / materializer.JOINT_RECOVERY_JOURNAL_FILENAME
        )
        candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
        browser_sha256 = hashlib.sha256(browser_bytes).hexdigest()
        browser_binding = {
            "status": "pass",
            "candidate_runtime_receipt_path": str(candidate_path),
            "candidate_runtime_receipt_sha256": candidate_sha256,
            "candidate_runtime_schema": materializer.CANDIDATE_RUNTIME_SCHEMA,
            "browser_receipt_path": str(browser_path),
            "browser_receipt_sha256": browser_sha256,
            "browser_schema": contract.CANDIDATE_BROWSER_SCHEMA,
            "secret_material_recorded": False,
            "exact_embedded_binding": True,
        }
        deploy.update(
            {
                "contract_name": materializer.JOINT_DEPLOY_RECEIPT_CONTRACT,
                "coordination_contract_name": (
                    materializer.JOINT_DEPLOY_RECEIPT_CONTRACT
                ),
                "component_contracts": {
                    "memorial_deploy": contract.DEPLOY_RECEIPT_CONTRACT,
                },
                "service_scope": list(materializer.JOINT_SERVICE_SCOPE),
                "api_mutation_scope": ["ea-api"],
                "ingress_mutation_scope": ["ea-cloudflared"],
                "joint_atomicity": dict(materializer.JOINT_ATOMICITY),
                "joint_public_edge": {
                    "status": "pass",
                    "request_count": 12,
                    "source_revision": HEAD,
                },
                "recovery_journal_cleanup": {
                    "status": "removed",
                    "path": str(cleanup_journal_path),
                    "contains_secret_material": True,
                    "state_directory": _cleanup_state_directory_identity(
                        cleanup_state_directory
                    ),
                },
                "spatial_browser_binding": browser_binding,
                "spatial_materializer_handoff": {
                    "deploy_receipt": {
                        "environment": materializer.DEPLOY_RECEIPT_ENV,
                        "path": str(deploy_path),
                        "contract_name": (
                            materializer.JOINT_DEPLOY_RECEIPT_CONTRACT
                        ),
                    },
                    "candidate_runtime_receipt": {
                        "path": str(candidate_path),
                        "sha256": candidate_sha256,
                        "schema": materializer.CANDIDATE_RUNTIME_SCHEMA,
                    },
                    "candidate_browser_receipt": {
                        "environment": (
                            materializer.CANDIDATE_BROWSER_RECEIPT_ENV
                        ),
                        "path": str(browser_path),
                        "sha256": browser_sha256,
                        "schema": contract.CANDIDATE_BROWSER_SCHEMA,
                        "exact_binding": (
                            "candidate_runtime.spatial_handoff_runtime."
                            "candidate_browser_gate"
                        ),
                    },
                },
            }
        )
    _write_private(deploy_path, deploy)
    return (
        deploy_path,
        browser_path,
        materializer.SourceState(HEAD, FINGERPRINT, False),
    )


def test_no_arg_invocation_writes_deterministic_private_blocked_receipt(
    tmp_path: Path,
) -> None:
    output = tmp_path / "blocked.json"
    assert materializer.main(["--output", str(output)]) == 0
    first = output.read_bytes()
    assert materializer.main(["--output", str(output)]) == 0
    assert output.read_bytes() == first
    payload = json.loads(first)
    assert payload["status"] == "blocked"
    assert payload["gold_claim_allowed"] is False
    assert payload["provider_calls_performed"] is False
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_materializer_emits_strict_sanitized_pass_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        expected_public_origin=ORIGIN,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )
    assert receipt["status"] == "pass", receipt
    assert contract.validate_memorial_spatial_public_origin_receipt(
        receipt,
        current_head=HEAD,
        current_fingerprint=FINGERPRINT,
    ) == []
    encoded = json.dumps(receipt, sort_keys=True)
    assert str(tmp_path) not in encoded
    assert "provider_calls_performed" in receipt
    assert receipt["external_requests"] == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "identity_tamper",
        "journal_present",
        "state_directory_swap",
        "state_directory_symlink",
        "wrong_mode",
    ),
)
def test_materializer_revalidates_bound_cleanup_state_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    deploy = json.loads(deploy_path.read_bytes())
    cleanup = deploy["recovery_journal_cleanup"]
    state_directory = Path(cleanup["state_directory"]["path"])
    if mutation == "identity_tamper":
        cleanup["state_directory"]["inode"] += 1
        _write_private(deploy_path, deploy)
    elif mutation == "journal_present":
        journal = Path(cleanup["path"])
        journal.write_bytes(b"{}\n")
        journal.chmod(0o600)
    elif mutation == "wrong_mode":
        state_directory.chmod(0o755)
    else:
        moved = state_directory.with_name(f"{mutation}-original")
        state_directory.rename(moved)
        if mutation == "state_directory_swap":
            state_directory.mkdir(mode=0o700)
        else:
            state_directory.symlink_to(moved, target_is_directory=True)

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )

    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["failed_codes"] == [
        "joint_recovery_journal_cleanup_state_invalid"
    ]


def test_materializer_rejects_unbound_legacy_joint_cleanup_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    deploy = json.loads(deploy_path.read_bytes())
    deploy["recovery_journal_cleanup"].pop("state_directory")
    _write_private(deploy_path, deploy)

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )

    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["failed_codes"] == [
        "joint_recovery_journal_cleanup_invalid"
    ]


def test_materializer_rejects_symlinked_private_deploy_input(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    _write_private(target, {"status": "pass"})
    link = tmp_path / "deploy.json"
    link.symlink_to(target)
    browser = tmp_path / "browser.json"
    _write_private(browser, {"status": "pass"})
    receipt = materializer.materialize(
        deploy_receipt_path=link,
        candidate_browser_receipt_path=browser,
        source_state=materializer.SourceState(HEAD, FINGERPRINT, False),
    )
    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    assert "deploy_receipt_invalid" in receipt["failed_codes"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_calls_performed", True),
        ("external_request_count", 1),
        ("redirect_count", 1),
    ],
)
def test_materializer_blocks_non_first_party_public_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    deploy = json.loads(deploy_path.read_bytes())
    deploy["public_spatial_tour"][field] = value
    _write_private(deploy_path, deploy)
    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )
    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False


def test_materializer_blocks_boolean_only_candidate_browser_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    deploy = json.loads(deploy_path.read_bytes())
    candidate_path = Path(deploy["candidate_promotion_evidence"]["path"])
    candidate = json.loads(candidate_path.read_bytes())
    partial = {"schema": contract.CANDIDATE_BROWSER_SCHEMA, "status": "pass"}
    candidate["spatial_handoff_runtime"]["candidate_browser_gate"] = partial
    candidate_bytes = _write_private(candidate_path, candidate)
    deploy["candidate_promotion_evidence"]["sha256"] = hashlib.sha256(
        candidate_bytes
    ).hexdigest()
    _write_private(deploy_path, deploy)
    _write_private(browser_path, partial)
    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )
    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False


def test_materializer_blocks_browser_and_public_route_canonical_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    deploy = json.loads(deploy_path.read_bytes())
    deploy["public_spatial_tour"]["routes"]["tour_json_get"][
        "canonical_json_sha256"
    ] = "0" * 64
    _write_private(deploy_path, deploy)

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )

    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["failed_codes"] == ["browser_public_tour_digest_mismatch"]


def test_materializer_normalizes_browser_validator_runtime_error_to_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)

    def reject_browser(_payload: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("private browser diagnostic")

    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=reject_browser,
    )
    assert receipt["status"] == "blocked"
    assert receipt["failed_codes"] == ["spatial_public_origin_evidence_invalid"]
    assert "private browser diagnostic" not in json.dumps(receipt)


def test_package_digest_matches_deploy_spatial_package_semantics() -> None:
    snapshot = {
        "tour.json": b'{"slug":"tour"}\n',
        contract.VIEWER_RELPATH: b"<!doctype html>",
        contract.PROOF_RELPATH: b'{"schema":"proof"}\n',
        contract.FLOORPLAN_RELPATH: b"png-bytes",
        contract.THREE_RELPATH: b"three-module",
        contract.ORBIT_RELPATH: b"orbit-controls",
    }
    rows = [
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for path, content in sorted(snapshot.items())
    ]
    assert contract.canonical_json_sha256(rows) == _spatial_package_sha256(snapshot)


def test_strict_validator_rejects_public_asset_digest_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy_path, browser_path, source_state = _valid_inputs(tmp_path, monkeypatch)
    receipt = materializer.materialize(
        deploy_receipt_path=deploy_path,
        candidate_browser_receipt_path=browser_path,
        source_state=source_state,
        browser_validator=lambda payload, **_kwargs: payload,
    )
    assert receipt["status"] == "pass"
    mutated = copy.deepcopy(receipt)
    mutated["public_spatial_tour"]["routes"]["viewer_get"]["body_sha256"] = "0" * 64
    issues = contract.validate_memorial_spatial_public_origin_receipt(
        mutated,
        current_head=HEAD,
        current_fingerprint=FINGERPRINT,
    )
    assert "public_spatial_tour_byte_binding_invalid:viewer_get" in issues
