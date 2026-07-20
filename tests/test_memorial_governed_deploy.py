from __future__ import annotations

import _thread
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, Sequence

import pytest

from app.api.routes import public_tours
from app.services.public_tour_release_policy import (
    GENERATED_RECONSTRUCTION_PROVIDER,
    PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
)
from scripts import build_manfred_memorial_image as image_builder
from scripts import deploy_ea_memorial as deploy
from scripts import provision_memorial_gemini_oauth as oauth_provision


class TestVexpMemorialMutationAuthority(deploy.VexpMemorialMutationAuthority):
    __test__ = False

    def __init__(
        self,
        *,
        state_path: Path,
        certificate_root: Path,
        certificate_directory: Path,
        permit_path: Path,
        permit_commit_path: Path,
        lock_path: Path,
        epoch_void_ledger_root: Path,
        current_predicate_trusted_parent: Path,
        current_predicate_root: Path,
        current_predicate_producer_trusted_parent: Path,
        current_predicate_producer_path: Path,
        current_boot_id: str,
        monotonic_ns: Callable[[], int],
        utc_now: Callable[[], datetime],
    ) -> None:
        self._state_path = state_path
        self._certificate_root = certificate_root
        self._certificate_directory = certificate_directory
        self._permit_path = permit_path
        self._permit_commit_path = permit_commit_path
        self._lock_path = lock_path
        self._epoch_void_ledger_root = epoch_void_ledger_root
        self._current_predicate_trusted_parent = (
            current_predicate_trusted_parent
        )
        self._current_predicate_root = current_predicate_root
        self._current_predicate_producer_trusted_parent = (
            current_predicate_producer_trusted_parent
        )
        self._current_predicate_producer_path = current_predicate_producer_path
        self._current_boot_id = current_boot_id
        self._monotonic_ns = monotonic_ns
        self._utc_now = utc_now

    @property
    def sentinel_state_path(self) -> Path:
        return self._state_path

    @property
    def mutation_permit_path(self) -> Path:
        return self._permit_path

    @property
    def mutation_permit_commit_path(self) -> Path:
        return self._permit_commit_path

    @property
    def mutation_permit_commit_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def mutation_permit_commit_owner_gid(self) -> int:
        return os.getegid()

    @property
    def qualification_certificate_root(self) -> Path:
        return self._certificate_root

    @property
    def qualification_certificate_directory(self) -> Path:
        return self._certificate_directory

    @property
    def qualification_certificate_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def qualification_certificate_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_permit_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def mutation_permit_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_permit_lock_path(self) -> Path:
        return self._lock_path

    @property
    def mutation_permit_lock_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def mutation_permit_lock_owner_gid(self) -> int:
        return os.getegid()

    @property
    def mutation_authority_trusted_parent(self) -> Path:
        return self._permit_path.parent

    @property
    def mutation_authority_directory_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def mutation_authority_directory_owner_gid(self) -> int:
        return os.getegid()

    @property
    def epoch_void_ledger_root(self) -> Path:
        return self._epoch_void_ledger_root

    @property
    def epoch_void_ledger_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def epoch_void_ledger_owner_gid(self) -> int:
        return os.getegid()

    @property
    def current_predicate_trusted_parent(self) -> Path:
        return self._current_predicate_trusted_parent

    @property
    def current_predicate_root(self) -> Path:
        return self._current_predicate_root

    @property
    def current_predicate_records_directory(self) -> Path:
        return self._current_predicate_root / "records"

    @property
    def current_predicate_pointer_path(self) -> Path:
        return self._current_predicate_root / "current.json"

    @property
    def current_predicate_producer_manifest_path(self) -> Path:
        return self._current_predicate_root / "producer-manifest.json"

    @property
    def current_predicate_producer_path(self) -> Path:
        return self._current_predicate_producer_path

    @property
    def current_predicate_producer_trusted_parent(self) -> Path:
        return self._current_predicate_producer_trusted_parent

    @property
    def current_predicate_producer_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def current_predicate_producer_owner_gid(self) -> int:
        return os.getegid()

    @property
    def current_predicate_owner_uid(self) -> int:
        return os.geteuid()

    @property
    def current_predicate_owner_gid(self) -> int:
        return os.getegid()

    def current_boot_id(self) -> str:
        return self._current_boot_id

    def monotonic_ns(self) -> int:
        return self._monotonic_ns()

    def utc_now(self) -> datetime:
        return self._utc_now()


def _vexp_certificate(state: Mapping[str, object]) -> dict[str, object]:
    reset_hash = "a" * 64
    event_hash = "b" * 64
    tail_hash = "f" * 64
    reset_event = {
        "at": state["epoch_started_at"],
        "event": "qualification_reset",
        "sequence": 41,
        "previous_hash": "0" * 64,
        "hash": reset_hash,
    }
    event = {
        "at": state["qualified_at"],
        "event": "seven_day_qualification_achieved",
        "sequence": 42,
        "previous_hash": reset_hash,
        "hash": event_hash,
    }
    tail_event = {
        "at": "2026-07-20T09:44:56.206Z",
        "event": "resource_sample",
        "sequence": 43,
        "previous_hash": event_hash,
        "hash": tail_hash,
    }
    index = [reset_event, event, tail_event]
    certificate: dict[str, object] = {
        "schema": deploy.VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "sentinel_version": deploy.VEXP_SENTINEL_STATE_VERSION,
        "epoch_started_at": state["epoch_started_at"],
        "epoch_started_ms": state["epoch_started_ms"],
        "qualified_at": state["qualified_at"],
        "qualification_duration_ms": deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS,
        "qualification_monotonic_duration_ms": (
            deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS
        ),
        "qualification_boot_id": "12345678-1234-4234-9234-123456789abc",
        "qualification_monotonic_started_ns": 1_000_000_000,
        "qualification_monotonic_qualified_ns": (
            1_000_000_000
            + deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS * 1_000_000
        ),
        "active_chain": {
            "anchor": {**reset_event, "source": "sentinel"},
            "qualification_event": {**event, "source": "sentinel"},
            "tail_sequence": tail_event["sequence"],
            "tail_hash": tail_hash,
            "event_count": len(index),
            "index": index,
            "index_sha256": deploy._canonical_json_sha256(index),
        },
        "terminal_state": {
            "version": deploy.VEXP_SENTINEL_STATE_VERSION,
            "epoch_started_at": state["epoch_started_at"],
            "epoch_started_ms": state["epoch_started_ms"],
            "qualified_at": state["qualified_at"],
            "qualification_boot_id": "12345678-1234-4234-9234-123456789abc",
            "qualification_monotonic_started_ns": 1_000_000_000,
            "qualification_monotonic_qualified_ns": (
                1_000_000_000
                + deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS * 1_000_000
            ),
            "qualification_phase": "qualified",
            "certification_blockers": [],
            "certification_deferments": [],
            "predicate_contract": state["predicate_contract"],
            "predicate_contract_sha256": state["predicate_contract_sha256"],
            "last_event_hash": tail_hash,
        },
        "source_attestations": {
            "sentinel_state_sha256": "c" * 64,
            "event_generations": {"qualification": 1},
            "event_log_guard_sha256": "d" * 64,
            "event_log_guard": {"status": "pass"},
            "apparmor_audit_sha256": "e" * 64,
            "apparmor_audit": {"status": "pass"},
            "implementation_manifest_sha256": "0" * 64,
            "implementation": {
                "sentinel_executable": {"sha256": "1" * 64},
                "sentinel_systemd_unit": {"sha256": "2" * 64},
                "predicate_contract": {"value": "v6", "sha256": "3" * 64},
                "finalizer_executable": {"sha256": "4" * 64},
                "finalizer_checksum_manifest": {"sha256": "5" * 64},
                "finalizer_checksum_binding": {"sha256": "6" * 64},
                "finalizer_systemd_unit": {"sha256": "7" * 64},
                "systemd_runtime": {"sha256": "8" * 64},
                "apparmor_policy": {"sha256": "9" * 64},
            },
        },
        "seal": {
            "writer": "root_owned_systemd_oneshot",
            "write_policy": "create_exclusive_never_overwrite",
            "telegram_sent_by_finalizer": False,
            "docker_socket_used": False,
        },
    }
    certificate["identity"] = f"sha256:{deploy._canonical_json_sha256(certificate)}"
    return certificate


SAFE_HTML = (
    "<!doctype html><html><body>Manfred – der Begleiter ist nicht Manfred "
    "und spricht nicht für ihn.</body></html>"
).encode("utf-8")
SAFE_MANIFEST = json.dumps(
    {
        "slug": "manfred",
        "intro": (
            "Der synthetische Gedenkbegleiter ist nicht Manfred und spricht nicht für ihn."
        ),
        "disclosure": "Neue Texte sind quellengebundene Einordnungen.",
    },
    ensure_ascii=False,
    separators=(",", ":"),
).encode("utf-8")
OAUTH_TEST_SECRET = "oauth-refresh-secret-sentinel"
OAUTH_TEST_CREDENTIAL_BYTES = (
    json.dumps(
        {
            "refresh_token": OAUTH_TEST_SECRET,
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "token_type": "Bearer",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n"
).encode("utf-8")
OAUTH_TEST_ALTERNATE_CREDENTIAL_BYTES = (
    json.dumps(
        {
            "refresh_token": "oauth-source-changed-sentinel",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "token_type": "Bearer",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n"
).encode("utf-8")
SAFE_TOUR = json.dumps(
    {"slug": "control-tour", "title": "Control tour"},
    separators=(",", ":"),
).encode("utf-8")
SPATIAL_VIEWER_RELPATH = "generated-reconstruction/viewer.html"
SPATIAL_PROOF_RELPATH = "generated-reconstruction/reconstruction.json"
SPATIAL_ASSET_PATHS = [
    SPATIAL_VIEWER_RELPATH,
    SPATIAL_PROOF_RELPATH,
    "generated-reconstruction/source-floorplan.png",
    "generated-reconstruction/vendor/three.module.js",
    ("generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"),
]
SPATIAL_ROUTE_LABELS = [f"Room {index}" for index in range(1, 10)]
SPATIAL_TEST_FILES = {
    "tour.json": json.dumps(
        {
            "slug": deploy.REQUIRED_CONTROL_TOUR_SLUG,
            "route_labels": SPATIAL_ROUTE_LABELS,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8"),
    SPATIAL_VIEWER_RELPATH: b"<!doctype html><title>Spatial test viewer</title>",
    SPATIAL_PROOF_RELPATH: b'{"schema":"test-reconstruction"}\n',
    "generated-reconstruction/source-floorplan.png": b"\x89PNG\r\n\x1a\nspatial-test",
    "generated-reconstruction/vendor/three.module.js": b"export const THREE = true;\n",
    (
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"
    ): b"export const OrbitControls = true;\n",
}
_SPATIAL_ASSET_ROLES = {
    SPATIAL_VIEWER_RELPATH: ("viewer_document", "text/html"),
    SPATIAL_PROOF_RELPATH: ("reconstruction_manifest", "application/json"),
    "generated-reconstruction/source-floorplan.png": (
        "floorplan_texture",
        "image/png",
    ),
    "generated-reconstruction/vendor/three.module.js": (
        "viewer_module",
        "text/javascript",
    ),
    (
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"
    ): ("viewer_module", "text/javascript"),
}
_SPATIAL_RAW_TOUR_PAYLOAD: dict[str, object] = {
    "slug": deploy.REQUIRED_CONTROL_TOUR_SLUG,
    "title": "Control tour",
    "tour_privacy_mode": "coarse_location",
    "route_labels": SPATIAL_ROUTE_LABELS,
    "generated_reconstruction": {
        "provider": GENERATED_RECONSTRUCTION_PROVIDER,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "viewer_version": "propertyquarry_3d_tour_viewer_v3",
        "viewer_relpath": SPATIAL_VIEWER_RELPATH,
        "manifest_relpath": SPATIAL_PROOF_RELPATH,
        "floorplan_relpath": (
            "generated-reconstruction/source-floorplan.png"
        ),
        "photo_relpaths": [],
        "photo_reference_panel_count": 0,
    },
    "generated_viewer_release": {
        "contract": PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
        "status": "ready",
        "provider": GENERATED_RECONSTRUCTION_PROVIDER,
        "viewer_relpath": SPATIAL_VIEWER_RELPATH,
        "asset_bindings": [
            {
                "path": relpath,
                "sha256": hashlib.sha256(SPATIAL_TEST_FILES[relpath]).hexdigest(),
                "size_bytes": len(SPATIAL_TEST_FILES[relpath]),
                "mime_type": mime_type,
                "role": role,
            }
            for relpath, (role, mime_type) in _SPATIAL_ASSET_ROLES.items()
        ],
        "browser_receipt_sha256": "1" * 64,
        "source_provenance_receipt_sha256": "2" * 64,
        "publication_authority_receipt_sha256": "3" * 64,
        "security_review_receipt_sha256": "4" * 64,
        "accessibility_review_receipt_sha256": "5" * 64,
        "browser_interaction_verified": True,
        "visual_quality_review_passed": True,
        "security_review_passed": True,
        "accessibility_review_passed": True,
        "source_provenance_verified": True,
        "publication_authority_verified": True,
        "release_revision": "test-release-v1",
        "disclosure": "Generated interactive reconstruction.",
    },
}
SPATIAL_TEST_FILES["tour.json"] = json.dumps(
    _SPATIAL_RAW_TOUR_PAYLOAD,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
PUBLIC_SPATIAL_TOUR_PAYLOAD = public_tours._redacted_public_tour_payload(
    json.loads(SPATIAL_TEST_FILES["tour.json"]),
    expose_asset_relpaths=False,
)
PUBLIC_SPATIAL_TOUR_JSON = json.dumps(
    PUBLIC_SPATIAL_TOUR_PAYLOAD,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")


def test_public_spatial_fixture_uses_the_real_redacted_route_projection() -> None:
    assert PUBLIC_SPATIAL_TOUR_JSON != SPATIAL_TEST_FILES["tour.json"]
    assert PUBLIC_SPATIAL_TOUR_PAYLOAD["slug"] == deploy.REQUIRED_CONTROL_TOUR_SLUG
    assert PUBLIC_SPATIAL_TOUR_PAYLOAD["tour_privacy_mode"] == "anonymous_public"
    assert isinstance(PUBLIC_SPATIAL_TOUR_PAYLOAD["facts"], dict)
    assert isinstance(PUBLIC_SPATIAL_TOUR_PAYLOAD["brief"], dict)
    assert isinstance(PUBLIC_SPATIAL_TOUR_PAYLOAD["scenes"], list)
    assert isinstance(PUBLIC_SPATIAL_TOUR_PAYLOAD["public_assets"], list)
    assert PUBLIC_SPATIAL_TOUR_PAYLOAD["generated_viewer"] == {
        "url": (
            f"/tours/viewer/{deploy.REQUIRED_CONTROL_TOUR_SLUG}/"
            f"{SPATIAL_VIEWER_RELPATH}"
        ),
        "release_revision": "test-release-v1",
        "disclosure": "Generated interactive reconstruction.",
        "synthetic": True,
        "verified_provider_capture": False,
    }


def _candidate_promotion_evidence() -> dict[str, object]:
    return {
        "provider_calls_performed": False,
        "memorial_surface": "conversation_only",
        "spatial_scope": "separate_propertyquarry_lane",
        "spatial_receipt_consumed": False,
        "separate_spatial_plane": {
            "status": "not_in_memorial_scope",
            "owner": "PropertyQuarry",
            "scope": "separate_propertyquarry_lane",
            "receipt_consumed": False,
            "routes_tested": False,
        },
    }


def _public_spatial_response(
    url: str,
    method: str,
    *,
    source_revision: str = "b" * 40,
    body_overrides: Mapping[str, bytes] | None = None,
    status_overrides: Mapping[str, int] | None = None,
) -> deploy.HttpResponse:
    path = urllib.parse.urlsplit(url).path
    slug = deploy.REQUIRED_CONTROL_TOUR_SLUG
    viewer_root = f"/tours/viewer/{slug}"
    response_specs: dict[str, tuple[int, str, bytes]] = {
        "/version": (
            200,
            "application/json",
            json.dumps(
                {"commit_sha": source_revision},
                separators=(",", ":"),
            ).encode("utf-8"),
        ),
        f"/tours/{slug}": (
            200,
            "text/html; charset=utf-8",
            (
                "<!doctype html><html><body><iframe src=\""
                f"{viewer_root}/{SPATIAL_VIEWER_RELPATH}\"></iframe></body></html>"
            ).encode("utf-8"),
        ),
        f"/tours/{slug}.json": (
            200,
            "application/json",
            PUBLIC_SPATIAL_TOUR_JSON,
        ),
        **{
            f"{viewer_root}/{relpath}": (
                404 if relpath == SPATIAL_PROOF_RELPATH else 200,
                (
                    "application/json"
                    if relpath == SPATIAL_PROOF_RELPATH
                    else "text/html; charset=utf-8"
                    if relpath == SPATIAL_VIEWER_RELPATH
                    else "image/png"
                    if relpath.endswith(".png")
                    else "text/javascript; charset=utf-8"
                ),
                (
                    b'{"error":{"code":"not_found"}}'
                    if relpath == SPATIAL_PROOF_RELPATH
                    else content
                ),
            )
            for relpath, content in SPATIAL_TEST_FILES.items()
            if relpath != "tour.json"
        },
    }
    if path not in response_specs:
        raise AssertionError(f"unexpected public spatial request: {path}")
    status, content_type, body = response_specs[path]
    if body_overrides and path in body_overrides:
        body = body_overrides[path]
    if status_overrides and path in status_overrides:
        status = status_overrides[path]
    return deploy.HttpResponse(
        status,
        content_type,
        b"" if method == "HEAD" else body,
        source_revision,
        headers={},
    )


def _singular_alias_response(method: str) -> deploy.HttpResponse:
    return deploy.HttpResponse(
        308,
        "text/plain; charset=utf-8",
        b"" if method == "HEAD" else b"Permanent Redirect",
        headers={
            "Location": "/memorials/manfred?from=ea-launch-verifier",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


def _completed(
    args: Sequence[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(args), returncode, stdout, stderr)


def _fake_secret_runner_docker(tmp_path: Path) -> Path:
    executable = tmp_path / "docker"
    executable.write_text(
        """#!/usr/bin/python3
import os
import sys
import time

if sys.argv[1:3] == ["container", "ls"]:
    if os.environ.get("FAKE_HELPER_PRESENT") == "1":
        print("helper-container-id")
    raise SystemExit(0)

mode = os.environ.get("FAKE_DOCKER_MODE")
if mode == "block":
    time.sleep(5)
elif mode == "bounded-output":
    sys.stdin.buffer.read()
    sys.stdout.buffer.write(b"x" * 10000)
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable


class _HashingBinarySink:
    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.size_bytes = 0

    def write(self, data: bytes | bytearray | memoryview) -> int:
        view = memoryview(data)
        self.digest.update(view)
        self.size_bytes += len(view)
        return len(view)


class FakeRunner:
    def __init__(
        self,
        root: Path,
        *,
        authority_status: str = "pass",
        readiness_status: str = "pass",
        baseline_files: tuple[str, ...] = ("docker-compose.yml",),
        include_working_dir_label: bool = True,
        baseline_root: Path | None = None,
        redis_present: bool = True,
        redis_running: bool = True,
        redis_health: str = "healthy",
        redis_project: str = "ea",
        redis_service: str = "ea-redis",
        prior_image_reference: str = "ea-runtime:latest",
        branch: str = "release/manfred",
        upstream: str = "origin/main",
        candidate_status: str = "pass",
        candidate_websockets: int = 0,
        candidate_http_errors: int = 0,
        candidate_archive_gate_check: bool = True,
        candidate_failure_origin: str = "",
        candidate_failure_error: str = "candidate_browser_runtime_unavailable",
        candidate_failure_secret: str = "",
    ) -> None:
        self.root = root
        self.baseline_root = baseline_root or root
        self.authority_status = authority_status
        self.readiness_status = readiness_status
        self.baseline_files = baseline_files
        self.include_working_dir_label = include_working_dir_label
        self.redis_present = redis_present
        self.redis_running = redis_running
        self.redis_health = redis_health
        self.redis_project = redis_project
        self.redis_service = redis_service
        self.calls: list[list[str]] = []
        self.call_envs: list[dict[str, str]] = []
        self.secret_stdin_observations: list[dict[str, object]] = []
        self.oauth_helper_returncode = 0
        self.oauth_helper_exit_unconfirmed = False
        self.oauth_helper_stdout_override: bytes | None = None
        self.oauth_helper_stderr = b""
        self.oauth_source_changed = False
        self.oauth_change_source_after_install = False
        self.oauth_snapshot_failure = False
        self.oauth_snapshot_count = 0
        self.oauth_helper_name_present = False
        self.oauth_helper_name_queries: list[str] = []
        self.old_image = "sha256:" + "a" * 64
        self.candidate_image = "sha256:" + "c" * 64
        self.candidate_reference = f"ea-runtime:memorial-{'b' * 40}"
        self.prior_image_reference = prior_image_reference
        self.branch = branch
        self.upstream = upstream
        self.candidate_status = candidate_status
        self.candidate_websockets = candidate_websockets
        self.candidate_http_errors = candidate_http_errors
        self.candidate_archive_gate_check = candidate_archive_gate_check
        self.candidate_failure_origin = candidate_failure_origin
        self.candidate_failure_error = candidate_failure_error
        self.candidate_failure_secret = candidate_failure_secret
        self.image_refs = {
            self.prior_image_reference: self.old_image,
            self.candidate_reference: self.candidate_image,
        }
        self.api_mode = "prior"
        self.api_running = True
        self.forward_files: list[str] = []
        self.forward_working_root = self.root
        self.forward_image_id = self.candidate_image
        self.forward_project = "ea"
        self.forward_service = "ea-api"
        self.forward_source_mounts = True
        self.forward_extra_mount = False
        self.rollback_mount_mismatch = False
        self.rollback_env_mismatch = False
        self.rollback_mode = False
        retirement_paths = [
            operation.split(" ", 1)[1]
            for operation in deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        ]
        self.prior_openapi_paths = [
            "/health",
            "/memorials/{slug}",
            "/tours/{slug}",
            *retirement_paths,
        ]
        self.forward_openapi_paths = [
            path for path in self.prior_openapi_paths if path not in retirement_paths
        ]
        self.rollback_openapi_paths: list[str] | None = None
        self.forward_openapi_changed_operation = False
        self.forward_version_compatible_evolution = False
        self.prior_openapi_schema_type = "object"
        self.forward_openapi_schema_type = "object"
        self.prior_openapi_property_types = {
            name: "string"
            for name in ("description", "title", "summary", "tags", "examples")
        }
        self.forward_openapi_property_types = dict(self.prior_openapi_property_types)
        self.prior_openapi_response_description = "safe response"
        self.forward_openapi_response_description = "safe response"
        self.prior_openapi_security_header = "X-EA-API-Token"
        self.forward_openapi_security_header = "X-EA-API-Token"
        self.prior_tour_json = SAFE_TOUR
        self.forward_tour_json = SAFE_TOUR
        self.rendered_candidate_reference = self.candidate_reference
        self.rendered_pull_policy = "never"
        self.rendered_memorial_data_source = str(self.root / "memorial_data")
        self.rendered_memorial_runtime_source = str(
            self.root / ".runtime" / "candidate-data"
        )
        self.rendered_memorial_data_read_only = True
        self.mounted_projection_sha256 = ""
        self.rollback_render_environment: dict[str, str] = {}
        self.materializer_seen = False
        self.materializer_call_count = 0
        self.materializer_mutated = False
        self.materializer_tracked_write: Path | None = None
        self.materializer_tracked_write_on_call = 1
        self.tracked_status = ""
        self.tracked_status_after_materialization: str | None = None
        self.head_revision = "b" * 40
        self.head_after_materialization: str | None = None
        self.head_tree = "d" * 40
        self.head_tree_after_materialization: str | None = None
        self.index_list = "H scripts/deploy_ea_memorial.py\0"
        self.authority_public_origin = "https://memorial.example.org"
        self.postdeploy_authority_public_origin: str | None = None
        self.authority_posture = "authoritative_runtime"
        self.postdeploy_authority_posture: str | None = None
        self.candidate_seal_returncode = 0
        self.candidate_seal_stderr = ""
        self.candidate_seal_stdout_override: str | None = None
        self.candidate_seal_overrides: dict[str, object] = {}
        self.candidate_seal_extra_fields: dict[str, object] = {}
        self.candidate_seal_epoch_started_ms = 0
        self.candidate_seal_certificate_sha256 = ""
        self.candidate_seal_image_build_permit_sha256 = "8" * 64

    def release_authority_payload(
        self, *, postdeploy: bool | None = None
    ) -> dict[str, object]:
        if postdeploy is None:
            postdeploy = self.materializer_call_count >= 8
        return {
            "contract_name": "ea.release_authority_gate.v1",
            "status": self.authority_status,
            "authority_posture": (
                self.postdeploy_authority_posture
                if postdeploy and self.postdeploy_authority_posture is not None
                else self.authority_posture
            ),
            "source_worktree_dirty": False,
            "deployment_id": "memorial-release-001",
            "commit_sha": "b" * 40,
            "project_mode": "MEMORIAL",
            "public_origin": (
                self.postdeploy_authority_public_origin
                if postdeploy and self.postdeploy_authority_public_origin is not None
                else self.authority_public_origin
            ),
        }

    def readiness_payload(self) -> dict[str, object]:
        return {
            "contract_name": "ea.memorial_deploy_readiness.v1",
            "status": self.readiness_status,
        }

    def verify_release_evidence_snapshots(
        self, snapshots: Mapping[str, bytes]
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        release_manifest = json.loads(snapshots["release_manifest"])
        postdeploy = int(release_manifest.get("materializer_call") or 0) >= 6
        return (
            self.release_authority_payload(postdeploy=postdeploy),
            self.readiness_payload(),
        )

    @staticmethod
    def _api_mounts(root: Path, *, memorial: bool) -> list[dict[str, object]]:
        if not memorial:
            return [
                {
                    "Type": "bind",
                    "Source": str(root / "ea" / "app"),
                    "Destination": "/app/app",
                    "RW": False,
                },
                {
                    "Type": "bind",
                    "Source": str(root / "scripts"),
                    "Destination": "/app/scripts",
                    "RW": False,
                },
            ]
        runtime_root = root / ".runtime" / "candidate-data"
        return [
            {
                "Type": "bind",
                "Source": str(root / "memorial_data"),
                "Destination": "/data/memorial_data",
                "RW": False,
            },
            *[
                {
                    "Type": "bind",
                    "Source": str(runtime_root / basename),
                    "Destination": destination,
                    "RW": True,
                }
                for destination, basename in (
                    (
                        "/data/memorial-writable/public-contributions",
                        "public-contributions",
                    ),
                    (
                        "/data/memorial-writable/private-contributions",
                        "private-contributions",
                    ),
                    ("/data/memorial-writable/state", "state"),
                )
            ],
            {
                "Type": "volume",
                "Name": "ea_ea_artifacts",
                "Destination": "/data/artifacts",
                "RW": True,
            },
        ]

    def _materialize_private_output(self, argv: list[str]) -> None:
        self.materializer_seen = True
        self.materializer_call_count += 1
        if (
            self.materializer_tracked_write is not None
            and self.materializer_call_count == self.materializer_tracked_write_on_call
        ):
            self.materializer_tracked_write.parent.mkdir(parents=True, exist_ok=True)
            self.materializer_tracked_write.write_text(
                "mutated by materializer\n", encoding="utf-8"
            )
            self.materializer_mutated = True
        if "--output" in argv:
            output = Path(argv[argv.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "materializer_call": self.materializer_call_count,
                        "status": "pass",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        self.calls.append(argv)
        self.call_envs.append(dict(env))
        stdout = ""
        stderr = ""
        returncode = 0
        if argv[:4] == [
            str(deploy.TRUSTED_VEXP_PERMIT_MANAGER_PYTHON),
            "-I",
            str(deploy.TRUSTED_VEXP_PERMIT_MANAGER),
            "candidate-seal-status",
        ]:
            candidate_permit_sha256 = argv[
                argv.index("--candidate-permit-sha256") + 1
            ]
            candidate_receipt_path = argv[argv.index("--candidate-receipt") + 1]
            candidate_receipt_sha256 = argv[
                argv.index("--candidate-receipt-sha256") + 1
            ]
            image_build_receipt_sha256 = argv[
                argv.index("--image-build-receipt-sha256") + 1
            ]
            seal: dict[str, object] = {
                "status": "valid",
                "contract_name": deploy.VEXP_CANDIDATE_FINALIZATION_CONTRACT_NAME,
                "version": deploy.VEXP_CANDIDATE_FINALIZATION_VERSION,
                "path": str(
                    deploy.VEXP_CANDIDATE_FINALIZATION_ROOT
                    / f"{candidate_permit_sha256}.json"
                ),
                "sha256": "0" * 64,
                "commit": {
                    "contract_name": (
                        deploy.VEXP_CANDIDATE_FINALIZATION_COMMIT_CONTRACT_NAME
                    ),
                    "version": deploy.VEXP_CANDIDATE_FINALIZATION_COMMIT_VERSION,
                    "status": "committed",
                    "sha256": "f" * 64,
                },
                "candidate_permit_sha256": candidate_permit_sha256,
                "candidate_receipt_path": candidate_receipt_path,
                "candidate_receipt_sha256": candidate_receipt_sha256,
                "image_build_receipt_sha256": image_build_receipt_sha256,
                "image_build_permit_sha256": (
                    self.candidate_seal_image_build_permit_sha256
                ),
                "epoch_started_ms": self.candidate_seal_epoch_started_ms,
                "qualification_certificate_sha256": (
                    self.candidate_seal_certificate_sha256
                ),
            }
            seal.update(self.candidate_seal_overrides)
            seal.update(self.candidate_seal_extra_fields)
            stdout = (
                self.candidate_seal_stdout_override
                if self.candidate_seal_stdout_override is not None
                else json.dumps(seal, sort_keys=True) + "\n"
            )
            stderr = self.candidate_seal_stderr
            returncode = self.candidate_seal_returncode
        elif argv[:3] == ["docker", "compose", "version"]:
            stdout = "Docker Compose version v2"
        elif argv[:2] == ["docker-compose", "version"]:
            returncode = 1
        elif argv[:4] == ["docker", "container", "ls", "--all"]:
            assert argv[-2:] == ["--format", "{{.Names}}"]
            exact_filter = argv[argv.index("--filter") + 1]
            assert exact_filter.startswith("name=^/")
            assert exact_filter.endswith("$")
            container_name = exact_filter[len("name=^/") : -1].replace(
                "\\", ""
            )
            self.oauth_helper_name_queries.append(container_name)
            if self.oauth_helper_name_present:
                stdout = container_name + "\n"
        elif argv == [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
        ]:
            if (
                self.materializer_mutated
                and self.tracked_status_after_materialization is not None
            ):
                stdout = self.tracked_status_after_materialization
            else:
                stdout = self.tracked_status
        elif argv == [
            "git",
            "-c",
            "core.fileMode=true",
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ]:
            if (
                self.materializer_mutated
                and self.tracked_status_after_materialization is not None
            ):
                stdout = self.tracked_status_after_materialization
            else:
                stdout = self.tracked_status
        elif argv[:4] == ["git", "symbolic-ref", "--quiet", "--short"]:
            if self.branch:
                stdout = self.branch + "\n"
            else:
                returncode = 1
        elif argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            if self.upstream:
                stdout = self.upstream + "\n"
            else:
                returncode = 1
        elif argv == ["git", "rev-parse", "HEAD"]:
            revision = (
                self.head_after_materialization
                if self.materializer_seen
                and self.head_after_materialization is not None
                else self.head_revision
            )
            stdout = revision + "\n"
        elif argv == ["git", "rev-parse", "HEAD^{tree}"]:
            tree = (
                self.head_tree_after_materialization
                if self.materializer_seen
                and self.head_tree_after_materialization is not None
                else self.head_tree
            )
            stdout = tree + "\n"
        elif argv == ["git", "write-tree"]:
            tree = (
                self.head_tree_after_materialization
                if self.materializer_seen
                and self.head_tree_after_materialization is not None
                else self.head_tree
            )
            stdout = tree + "\n"
        elif argv == ["git", "ls-files", "-v", "-z"]:
            stdout = self.index_list
        elif argv[:3] == ["docker", "image", "inspect"]:
            reference = argv[-1]
            image_id = self.image_refs.get(reference, self.candidate_image)
            stdout = json.dumps(
                [
                    {
                        "Id": image_id,
                        "Config": {
                            "Env": [],
                            "Cmd": ["uvicorn", "app.main:app"],
                            "Entrypoint": ["/usr/bin/tini", "--"],
                            "User": "10001:10001",
                        },
                    }
                ]
            )
        elif argv[:3] == ["docker", "image", "tag"]:
            source, destination = argv[-2:]
            self.image_refs[destination] = self.image_refs.get(source, source)
        elif argv[:3] == ["docker", "exec", "ea-api"] or argv[:6] == [
            "/usr/bin/timeout",
            "--signal=KILL",
            "30s",
            "docker",
            "exec",
            "ea-api",
        ]:
            projection_sha256, rows = deploy._candidate_projection_tree_digest(
                self.root / "memorial_data"
            )
            stdout = json.dumps(
                {
                    "projection_sha256": (
                        self.mounted_projection_sha256 or projection_sha256
                    ),
                    "file_count": len(rows),
                    "projection_bytes": sum(int(item["size_bytes"]) for item in rows),
                },
                sort_keys=True,
            )
        elif argv[:2] == ["docker", "inspect"]:
            name = argv[-1]
            if name == "ea-redis" and not self.redis_present:
                returncode = 1
                stderr = "Error: No such object: ea-redis"
                result = _completed(
                    argv, stdout=stdout, stderr=stderr, returncode=returncode
                )
                return result
            forward = name == "ea-api" and self.api_mode == "forward"
            working_root = self.forward_working_root if forward else self.baseline_root
            config_files = (
                self.forward_files
                if forward
                else [str(self.baseline_root / item) for item in self.baseline_files]
            )
            project = (
                self.forward_project
                if forward
                else self.redis_project
                if name == "ea-redis"
                else "ea"
            )
            service = (
                self.forward_service
                if forward
                else self.redis_service
                if name == "ea-redis"
                else name
            )
            labels = {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files": ",".join(config_files),
            }
            if self.include_working_dir_label:
                labels["com.docker.compose.project.working_dir"] = str(working_root)
            running = (
                self.redis_running
                if name == "ea-redis"
                else self.api_running
            )
            health = self.redis_health if name == "ea-redis" else "healthy"
            image_id = self.forward_image_id if forward else self.old_image
            image_reference = (
                self.candidate_reference if forward else self.prior_image_reference
            )
            mounts = (
                self._api_mounts(working_root, memorial=forward)
                if name == "ea-api"
                else []
            )
            if forward and not self.forward_source_mounts:
                mounts = []
            if forward and self.forward_extra_mount:
                mounts.append(
                    {
                        "Type": "bind",
                        "Source": str(working_root / "unexpected"),
                        "Destination": "/unexpected",
                        "RW": False,
                    }
                )
            if name == "ea-api" and self.rollback_mode and self.rollback_mount_mismatch:
                mounts.append(
                    {
                        "Type": "bind",
                        "Source": str(working_root / "unexpected"),
                        "Destination": "/unexpected",
                        "RW": False,
                    }
                )
            payload = {
                "Id": "container-" + name,
                "Created": "2026-07-13T00:00:00Z",
                "Image": image_id,
                "Config": {
                    "Image": image_reference,
                    "Labels": labels,
                    "Env": (
                        [f"EA_SOURCE_REVISION={'b' * 40}"]
                        if forward
                        else ["ROLLBACK_DRIFT=1"]
                        if self.rollback_mode and self.rollback_env_mismatch
                        else []
                    ),
                    "Cmd": ["uvicorn", "app.main:app"],
                    "Entrypoint": ["/usr/bin/tini", "--"],
                    "User": "10001:10001",
                },
                "State": {
                    "Running": running,
                    "Restarting": False,
                    "StartedAt": "2026-07-13T00:00:01Z",
                    "Health": {"Status": health},
                },
                "Mounts": mounts,
            }
            stdout = json.dumps([payload])
        elif argv[-2:] == ["config", "--services"]:
            stdout = "ea-db\nea-redis\nea-api\nea-worker\n"
        elif argv[-2:] == ["config", "--quiet"]:
            stdout = ""
        elif argv[-3:] == ["config", "--format", "json"]:
            memorial = (
                any(item.endswith("docker-compose.memorial.yml") for item in argv)
                and "EA_MEMORIAL_IMAGE" in env
            )
            if memorial:
                stdout = json.dumps(
                    {
                        "name": "ea",
                        "services": {
                            "ea-api": {
                                "image": self.rendered_candidate_reference,
                                "pull_policy": self.rendered_pull_policy,
                                "user": "10001:10001",
                                "volumes": [
                                    {
                                        "type": "bind",
                                        "source": self.rendered_memorial_data_source,
                                        "target": "/data/memorial_data",
                                        "read_only": self.rendered_memorial_data_read_only,
                                    },
                                    *[
                                        {
                                            "type": "bind",
                                            "source": str(
                                                Path(
                                                    self.rendered_memorial_runtime_source
                                                )
                                                / basename
                                            ),
                                            "target": destination,
                                            "read_only": False,
                                        }
                                        for destination, basename in (
                                            (
                                                "/data/memorial-writable/public-contributions",
                                                "public-contributions",
                                            ),
                                            (
                                                "/data/memorial-writable/private-contributions",
                                                "private-contributions",
                                            ),
                                            (
                                                "/data/memorial-writable/state",
                                                "state",
                                            ),
                                        )
                                    ],
                                    {
                                        "type": "volume",
                                        "source": "ea_artifacts",
                                        "target": "/data/artifacts",
                                        "read_only": False,
                                    },
                                ],
                            }
                        },
                    }
                )
            else:
                stdout = json.dumps(
                    {
                        "name": "ea",
                        "services": {
                            "ea-api": {
                                "image": self.prior_image_reference,
                                "environment": self.rollback_render_environment,
                                "volumes": [
                                    {
                                        "type": "bind",
                                        "source": str(
                                            self.baseline_root / "ea" / "app"
                                        ),
                                        "target": "/app/app",
                                        "read_only": True,
                                    },
                                    {
                                        "type": "bind",
                                        "source": str(self.baseline_root / "scripts"),
                                        "target": "/app/scripts",
                                        "read_only": True,
                                    },
                                ],
                            }
                        },
                    }
                )
        elif argv[:3] == ["docker", "start", "ea-redis"]:
            self.redis_present = True
            self.redis_running = True
            self.redis_health = "healthy"
        elif "up" in argv and argv[-1] == "ea-redis":
            self.redis_present = True
            self.redis_running = True
            self.redis_health = "healthy"
        elif "stop" in argv and argv[-1] == "ea-api":
            self.api_running = False
        elif "up" in argv and argv[-1] == "ea-api":
            memorial = any(
                item.endswith("docker-compose.memorial.yml") for item in argv
            )
            self.api_mode = "forward" if memorial else "prior"
            self.api_running = True
            self.rollback_mode = not memorial
            if memorial:
                self.forward_files = [
                    argv[index + 1]
                    for index, item in enumerate(argv[:-1])
                    if item == "-f"
                ]
        elif any(item.endswith("verify_release_authority.py") for item in argv):
            stdout = json.dumps(self.release_authority_payload())
        elif any(item.endswith("verify_memorial_deploy_readiness.py") for item in argv):
            stdout = json.dumps(self.readiness_payload())
        elif any(
            item.endswith("materialize_memorial_operator_status.py") for item in argv
        ):
            self._materialize_private_output(argv)
            stdout = json.dumps({"status": "blocked"})
        elif any(
            item.endswith("verify_manfred_memorial_candidate.py") for item in argv
        ):
            base_url = argv[argv.index("--base-url") + 1]
            origin = "public" if base_url.startswith("https://") else "local"
            if origin == self.candidate_failure_origin:
                returncode = 7
                stdout = json.dumps(
                    {
                        "schema": "ea.manfred_memorial_candidate_smoke.v1",
                        "status": "fail",
                        "error": (
                            f"{self.candidate_failure_error}:"
                            f"{self.candidate_failure_secret}"
                        ),
                    }
                )
                stderr = f"verifier stderr {self.candidate_failure_secret}"
            else:
                candidate_checks = [
                    "singular_memorial_alias",
                    "source_grounded_narrator_boundary",
                    "voice_provider_boundary_blocked",
                    "browser_provider_websocket_boundary",
                    "conversation_only_public_surface",
                ]
                if self.candidate_archive_gate_check:
                    candidate_checks.append("archive_publication_gate")
                stdout = json.dumps(
                    {
                        "schema": "ea.manfred_memorial_candidate_smoke.v1",
                        "status": self.candidate_status,
                        "checks": candidate_checks,
                        "provider_calls_performed": False,
                        "page_get_performed": True,
                        "memorial_surface": "conversation_only",
                        "spatial_scope": "separate_propertyquarry_lane",
                        "browser_audit": {
                            "status": "pass",
                            "automatic_provider_requests": 0,
                            "automatic_websockets": self.candidate_websockets,
                            "external_requests": 0,
                            "failed_requests": 0,
                            "page_errors": 0,
                            "http_errors": self.candidate_http_errors,
                        },
                    }
                )
        elif any("materialize_" in Path(item).name for item in argv):
            self._materialize_private_output(argv)
            stdout = json.dumps({"status": "pass"})
        result = _completed(argv, stdout=stdout, stderr=stderr, returncode=returncode)
        if check and returncode:
            raise deploy.DeployError(f"command_failed:{returncode}:{' '.join(argv)}")
        return result

    def run_secret_stdin(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        write_stdin: Callable[[BinaryIO], None],
        timeout_seconds: float,
        container_name: str,
        max_output_bytes: int,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd
        assert 0 < timeout_seconds <= deploy.GEMINI_OAUTH_PROVISION_TIMEOUT_SECONDS
        assert max_output_bytes == deploy.GEMINI_OAUTH_PROVISION_STDOUT_MAX_BYTES
        argv = [str(item) for item in args]
        assert argv[argv.index("--name") + 1] == container_name
        assert self.api_running is False
        assert self.oauth_helper_name_queries[-1] == container_name
        self.calls.append(argv)
        self.call_envs.append(dict(env))
        sink = _HashingBinarySink()
        write_stdin(sink)  # type: ignore[arg-type]
        digest = sink.digest.hexdigest()
        self.secret_stdin_observations.append(
            {"sha256": digest, "size_bytes": sink.size_bytes}
        )
        if self.oauth_helper_exit_unconfirmed:
            raise deploy.GeminiOAuthHelperExitUnconfirmed(
                "gemini_oauth_helper_exit_unconfirmed"
            )
        receipt = {
            "schema": deploy.GEMINI_OAUTH_PROVISION_CONTRACT,
            "status": "provisioned",
            "sha256": digest,
            "size_bytes": sink.size_bytes,
            "uid": deploy.GEMINI_OAUTH_TARGET_UID,
            "gid": deploy.GEMINI_OAUTH_TARGET_UID,
            "mode": "0600",
        }
        stdout = (
            self.oauth_helper_stdout_override
            if self.oauth_helper_stdout_override is not None
            else deploy._canonical_guard_json_bytes(receipt)
        )
        if self.oauth_change_source_after_install and self.oauth_helper_returncode == 0:
            self.oauth_source_changed = True
        return subprocess.CompletedProcess(
            argv,
            self.oauth_helper_returncode,
            stdout=stdout,
            stderr=self.oauth_helper_stderr,
        )


def _exact_spatial_browser_receipt(
    *,
    slug: str,
    source_revision: str,
    image_id: str,
    container_id: str,
    project: str,
    route_labels: list[str],
    local_files: list[dict[str, object]],
    package_sha256: str,
) -> dict[str, object]:
    candidate_origin = "http://127.0.0.1:18090"
    viewer_path = f"/tours/viewer/{slug}/{SPATIAL_VIEWER_RELPATH}"
    viewer_url = f"{candidate_origin}{viewer_path}"
    landing_url = f"{candidate_origin}/tours/{slug}"
    proof_path = f"/tours/viewer/{slug}/{SPATIAL_PROOF_RELPATH}"
    required_paths = {
        "floorplan": (
            f"/tours/viewer/{slug}/generated-reconstruction/source-floorplan.png"
        ),
        "orbit_controls": (
            f"/tours/viewer/{slug}/generated-reconstruction/vendor/"
            "examples/jsm/controls/OrbitControls.js"
        ),
        "three_module": (
            f"/tours/viewer/{slug}/generated-reconstruction/vendor/three.module.js"
        ),
    }
    required_relpaths = {
        "floorplan": "generated-reconstruction/source-floorplan.png",
        "orbit_controls": (
            "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"
        ),
        "three_module": "generated-reconstruction/vendor/three.module.js",
    }
    required_media_types = {
        "floorplan": "image/png",
        "orbit_controls": "text/javascript",
        "three_module": "text/javascript",
    }
    local_by_path = {str(row["path"]): row for row in local_files}

    def consumed_row(
        path: str,
        relpath: str,
        content_type: str,
    ) -> dict[str, object]:
        local = local_by_path[relpath]
        return {
            "url": f"{candidate_origin}{path}",
            "path": path,
            "status": 200,
            "content_type": content_type,
            "sha256": local["sha256"],
            "size_bytes": local["size_bytes"],
            "response_count": 1,
            "body_matches_local_package": True,
            "exact_candidate_url_verified": True,
        }

    def normal_surface(
        width: int,
        height: int,
        *,
        mobile: bool,
        reduced_motion: bool,
        collect_routes: bool,
    ) -> dict[str, object]:
        interactions = (
            [
                {
                    "index": index,
                    "label": label,
                    "active_state_verified": True,
                    "live_region_verified": True,
                    "playwright_actionability_verified": True,
                    "click_handler_state_change_verified": True,
                    "camera_canvas_screenshot_sha256": f"{index + 1:064x}",
                }
                for index, label in enumerate(route_labels)
            ]
            if collect_routes
            else []
        )
        return {
            "status": 200,
            "viewport": {"width": width, "height": height},
            "mobile": mobile,
            "prefers_reduced_motion": reduced_motion,
            "viewer_status": "ready",
            "canvas_ready": True,
            "route_stop_count": 9,
            "undersized_target_count": 0,
            "required_requests": {
                role: consumed_row(
                    path,
                    required_relpaths[role],
                    required_media_types[role],
                )
                for role, path in required_paths.items()
            },
            "viewer_response": consumed_row(
                viewer_path,
                SPATIAL_VIEWER_RELPATH,
                "text/html",
            ),
            "browser_response_count": 4,
            "browser_consumed_package_verified": True,
            "page_url": viewer_url,
            "response_url": viewer_url,
            "exact_candidate_url_verified": True,
            "route_interactions": interactions,
            "route_interaction_count": len(interactions),
            "camera_state_changes_verified": collect_routes,
            "horizontal_overflow_px": 0,
            "page_error_count": 0,
            "console_error_count": 0,
            "request_failure_count": 0,
            "viewer_subtree_non_2xx_count": 0,
        }

    def landing_surface(
        name: str,
        width: int,
        height: int,
        *,
        mobile: bool,
    ) -> dict[str, object]:
        return {
            "name": name,
            "path": f"/tours/{slug}",
            "status": 200,
            "viewport": {"width": width, "height": height},
            "mobile": mobile,
            "horizontal_overflow_px": 0,
            "iframe": {
                "src": viewer_path,
                "title_suffix": " interactive generated 3D reconstruction",
                "title_suffix_verified": True,
                "sandbox": "allow-scripts",
                "loading": "eager",
                "referrer_policy": "no-referrer",
                "aria_described_by": "generated-viewer-disclosure",
                "description_verified": True,
                "visible": True,
                "width": width - 32,
                "height": 620 if not mobile else 480,
            },
            "nested_viewer": {
                "url": viewer_url,
                "exact_candidate_url_verified": True,
                "viewer_status": "ready",
                "canvas_ready": True,
                "route_stop_count": 9,
                "route_labels": route_labels,
                "horizontal_overflow_px": 0,
                "undersized_target_count": 0,
            },
            "page_error_count": 0,
            "console_error_count": 0,
            "request_failure_count": 0,
            "non_2xx_response_count": 0,
            "external_request_count": 0,
            "page_url": landing_url,
            "response_url": landing_url,
            "exact_candidate_url_verified": True,
        }

    http_specs = (
        (SPATIAL_VIEWER_RELPATH, "viewer_document", "text/html"),
        (
            "generated-reconstruction/source-floorplan.png",
            "floorplan_texture",
            "image/png",
        ),
        (
            "generated-reconstruction/vendor/three.module.js",
            "viewer_module",
            "text/javascript",
        ),
        (
            "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
            "viewer_module",
            "text/javascript",
        ),
    )
    runtime_version = {
        "path": "/version",
        "status": 200,
        "commit_sha": source_revision,
        "body_commit_sha": source_revision,
        "source_revision_header": source_revision,
        "expected_commit_sha": source_revision,
        "oci_image_revision": source_revision,
        "repository": "EA",
        "role": "api",
        "release_authority_state": "clear",
        "release_authority_posture": "authoritative_runtime",
        "release_authority_source": "published_status_artifact",
        "commit_observed_over_http": True,
        "revision_agreement_verified": True,
    }
    public_tour_payload = dict(PUBLIC_SPATIAL_TOUR_PAYLOAD)
    assert public_tour_payload.get("slug") == slug
    public_tour_body = json.dumps(
        public_tour_payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema": "ea.manfred_spatial_candidate_browser.v5",
        "status": "pass",
        "slug": slug,
        "candidate_origin": candidate_origin,
        "candidate_commit": source_revision,
        "candidate_commit_source": (
            "GET /version body + X-EA-Source-Revision + expected commit + "
            "OCI image revision"
        ),
        "candidate_version": runtime_version,
        "candidate_oci_image": {
            "image_id": image_id,
            "oci_image_revision": source_revision,
            "revision_source": "docker_image_inspect_by_immutable_id",
            "immutable_image_id_verified": True,
        },
        "serving_container": {
            "container_id": container_id,
            "image_id": image_id,
            "compose_project": project,
            "compose_service": "gateway",
            "running": True,
            "container_port": 18090,
            "host_ip": "127.0.0.1",
            "host_port": 18090,
            "exact_loopback_publication_verified": True,
            "inspection_source": "docker_container_inspect_by_immutable_id",
        },
        "package_sha256": package_sha256,
        "package_binding": {
            "package_sha256": package_sha256,
            "local_file_count": 6,
            "local_files": local_files,
            "local_package_verified": True,
            "local_root_identity_bound": True,
            "tour_manifest_sha256": local_by_path["tour.json"]["sha256"],
            "release_revision": "test-release-v1",
            "http_asset_count": 4,
            "http_assets": [
                {
                    "path": f"/tours/viewer/{slug}/{relpath}",
                    "role": role,
                    "status": 200,
                    "sha256": local_by_path[relpath]["sha256"],
                    "size_bytes": local_by_path[relpath]["size_bytes"],
                    "content_type": content_type,
                    "asset_sha256_header_verified": True,
                    "viewer_revision_header_verified": True,
                    "body_matches_local_package": True,
                }
                for relpath, role, content_type in http_specs
            ],
            "http_assets_match_local_package": True,
            "proof_manifest": {
                "path": proof_path,
                "status": 404,
                "serveable": False,
                "local_sha256": local_by_path[SPATIAL_PROOF_RELPATH]["sha256"],
            },
            "public_tour_manifest": {
                "path": f"/tours/{slug}.json",
                "status": 200,
                "content_type": "application/json",
                "body_sha256": hashlib.sha256(public_tour_body).hexdigest(),
                "body_bytes": len(public_tour_body),
                "canonical_json_sha256": deploy._canonical_json_sha256(
                    public_tour_payload
                ),
                "source_revision": source_revision,
                "source_revision_verified": True,
                "slug": slug,
                "release_revision": "test-release-v1",
                "generated_viewer_url": viewer_path,
                "public_projection_verified": True,
            },
            "runtime_identity_revalidated_after_browser": True,
        },
        "landing": {
            "path": f"/tours/{slug}",
            "status": 200,
            "surface_count": 2,
            "surfaces": {
                "desktop": landing_surface(
                    "desktop",
                    1440,
                    1000,
                    mobile=False,
                ),
                "mobile": landing_surface(
                    "mobile",
                    390,
                    844,
                    mobile=True,
                ),
            },
            "responsive_iframe_verified": True,
            "nested_viewer_ready_verified": True,
            "page_error_count": 0,
            "console_error_count": 0,
            "request_failure_count": 0,
            "non_2xx_response_count": 0,
            "external_request_count": 0,
        },
        "proof_manifest": {
            "path": proof_path,
            "status": 404,
            "serveable": False,
        },
        "viewer_path": viewer_path,
        "surfaces": {
            "desktop": normal_surface(
                1440,
                1000,
                mobile=False,
                reduced_motion=False,
                collect_routes=True,
            ),
            "mobile": normal_surface(
                390,
                844,
                mobile=True,
                reduced_motion=False,
                collect_routes=True,
            ),
            "reduced_motion": normal_surface(
                1200,
                900,
                mobile=False,
                reduced_motion=True,
                collect_routes=True,
            ),
            "webgl_fallback": {
                "status": 200,
                "viewport": {"width": 1200, "height": 900},
                "viewer_status": "unavailable",
                "fallback_visible": True,
                "enabled_route_button_count": 0,
                "enabled_button_count": 0,
                "alert_role": "alert",
                "live_status_role": "status",
                "accessible_fallback_verified": True,
                "horizontal_overflow_px": 0,
                "page_error_count": 0,
                "console_error_count": 0,
                "required_requests": {
                    role: consumed_row(
                        path,
                        required_relpaths[role],
                        required_media_types[role],
                    )
                    for role, path in required_paths.items()
                },
                "viewer_response": consumed_row(
                    viewer_path,
                    SPATIAL_VIEWER_RELPATH,
                    "text/html",
                ),
                "browser_response_count": 4,
                "browser_consumed_package_verified": True,
                "page_url": viewer_url,
                "response_url": viewer_url,
                "exact_candidate_url_verified": True,
            },
        },
        "surface_count": 4,
        "route_stop_count": 9,
        "all_route_stops_interacted": True,
        "camera_state_changes_verified": True,
        "required_asset_requests_verified": True,
        "browser_consumed_package_verified": True,
        "responsive_overflow_verified": True,
        "page_error_count": 0,
        "console_error_count": 0,
        "request_failure_count": 0,
        "viewer_subtree_non_2xx_count": 0,
        "secret_material_recorded": False,
    }


@pytest.fixture()
def release_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    (root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    for filename in (
        "docker-compose.yml",
        "docker-compose.prod.yml",
        deploy.MEMORIAL_COMPOSE_FILE,
    ):
        (root / filename).write_text("services: {}\n", encoding="utf-8")
    project_modes = root / ".codex-design/product/PROJECT_MODES.generated.json"
    project_modes.parent.mkdir(parents=True)
    project_modes.write_text('{"modes":[{"key":"MEMORIAL"}]}\n', encoding="utf-8")
    project_modes.chmod(0o644)
    candidate_compose = root / "deploy/manfred-memorial/docker-compose.candidate.yml"
    candidate_compose.parent.mkdir(parents=True)
    candidate_compose.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        deploy,
        "PROPERTY_TOUR_SHA256",
        hashlib.sha256(SPATIAL_TEST_FILES["tour.json"]).hexdigest(),
    )
    return root


def _passing_bind_source_validator(
    _rendered: Mapping[str, object],
    **_kwargs: object,
) -> dict[str, object]:
    return {
        "schema": "ea.memorial_bind_source_access.v1",
        "status": "pass",
        "service": "ea-api",
        "user": "10001:10001",
        "uid": 10001,
        "primary_gid": 10001,
        "supplemental_gids": [10001],
        "bind_mount_count": 4,
        "release_tree_mount_count": 1,
        "root_inode_mount_count": 3,
        "release_entries_scanned": 1,
        "release_files_scanned": 1,
        "release_directories_scanned": 1,
        "release_bytes_accounted": 1,
        "snapshot_sha256": "5" * 64,
        "mounts": [],
        "file_contents_read": False,
        "secrets_included": False,
    }


def _lane(
    root: Path,
    runner: FakeRunner,
    *,
    http_get=None,  # type: ignore[no-untyped-def]
    http_no_redirect=None,  # type: ignore[no-untyped-def]
    deployment_id: str = "memorial-release-001",
    receipt_dir: Path | None = None,
    global_lock_path: Path | None = None,
    control_tour_slug: str = deploy.REQUIRED_CONTROL_TOUR_SLUG,
    bind_source_validator: Callable[..., dict[str, object]] = (
        _passing_bind_source_validator
    ),
) -> deploy.MemorialDeployLane:
    def safe_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/openapi.json"):
            forward = runner.api_mode == "forward"
            paths = (
                runner.rollback_openapi_paths
                if runner.rollback_mode and runner.rollback_openapi_paths is not None
                else runner.forward_openapi_paths
                if forward
                else runner.prior_openapi_paths
            )
            path_contract: dict[str, object] = {}
            retirement_paths = {
                operation.split(" ", 1)[1]
                for operation in deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
            }
            for path in paths:
                method = "post" if path in retirement_paths else "get"
                response_description = (
                    runner.forward_openapi_response_description
                    if forward
                    else runner.prior_openapi_response_description
                )
                response_status = (
                    "201"
                    if forward
                    and runner.forward_openapi_changed_operation
                    and path == "/health"
                    else "200"
                )
                response_schema: dict[str, object]
                if path == "/version":
                    additional_properties: dict[str, object] = {"type": "string"}
                    if forward and runner.forward_version_compatible_evolution:
                        additional_properties = {
                            "anyOf": [{"type": "string"}, {"type": "boolean"}]
                        }
                    response_schema = {
                        "type": "object",
                        "additionalProperties": additional_properties,
                    }
                else:
                    response_schema = {"$ref": "#/components/schemas/Control"}
                path_contract[path] = {
                    method: {
                        "responses": {
                            response_status: {
                                "description": response_description,
                                "content": {
                                    "application/json": {"schema": response_schema}
                                },
                            }
                        }
                    }
                }
            schema_type = (
                runner.forward_openapi_schema_type
                if forward
                else runner.prior_openapi_schema_type
            )
            property_types = (
                runner.forward_openapi_property_types
                if forward
                else runner.prior_openapi_property_types
            )
            security_header = (
                runner.forward_openapi_security_header
                if forward
                else runner.prior_openapi_security_header
            )
            body = json.dumps(
                {
                    "openapi": "3.1.0",
                    "security": [{"ApiToken": []}],
                    "paths": path_contract,
                    "components": {
                        "schemas": {
                            "Control": {
                                "type": schema_type,
                                "properties": {
                                    name: {"type": property_type}
                                    for name, property_type in property_types.items()
                                },
                            }
                        },
                        "securitySchemes": {
                            "ApiToken": {
                                "type": "apiKey",
                                "in": "header",
                                "name": security_header,
                            }
                        },
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return deploy.HttpResponse(200, "application/json", body, "b" * 40)
        if "/tours/" in url and url.endswith(".json"):
            body = (
                runner.forward_tour_json
                if runner.api_mode == "forward"
                else runner.prior_tour_json
            )
            return deploy.HttpResponse(200, "application/json", body, "b" * 40)
        if "/tours/" in url:
            return deploy.HttpResponse(
                200,
                "text/html; charset=utf-8",
                b"<!doctype html><html><body>Tour</body></html>",
                "b" * 40,
            )
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html; charset=utf-8", SAFE_HTML, "b" * 40)

    candidate_receipt = root / ".runtime" / "candidate-runtime-receipt.json"
    candidate_receipt.parent.mkdir(parents=True, exist_ok=True)
    projection_root = root / "memorial_data"
    projection_root.mkdir(exist_ok=True)
    projection_root.chmod(0o750)
    spatial_slug = deploy.REQUIRED_CONTROL_TOUR_SLUG
    # Keep the legacy spatial fixture available to tests that exercise the
    # separately governed PropertyQuarry lane, but never package it inside the
    # conversation-only Memorial projection.
    spatial_root = root / ".runtime" / "propertyquarry-test-projection"
    spatial_bundle_root = spatial_root / spatial_slug
    spatial_root.mkdir(exist_ok=True)
    spatial_root.chmod(0o750)
    spatial_bundle_root.mkdir(exist_ok=True)
    spatial_bundle_root.chmod(0o750)
    spatial_directories = {spatial_root, spatial_bundle_root}
    for relpath, content in SPATIAL_TEST_FILES.items():
        target = spatial_bundle_root / relpath
        parents_to_prepare: list[Path] = []
        parent = target.parent
        while True:
            parents_to_prepare.append(parent)
            if parent == spatial_bundle_root:
                break
            parent = parent.parent
        for directory in reversed(parents_to_prepare):
            directory.mkdir(exist_ok=True)
            directory.chmod(0o750)
        if target.exists():
            target.chmod(0o640)
        target.write_bytes(content)
        target.chmod(0o440)
        spatial_directories.update(
            parent
            for parent in target.parents
            if parent == spatial_bundle_root or spatial_bundle_root in parent.parents
        )
    for directory in spatial_directories:
        directory.chmod(0o550)
    projection_root.chmod(0o550)
    spatial_projection_sha256, spatial_projection_files = (
        deploy._candidate_projection_tree_digest(spatial_root)
    )
    spatial_projection_bytes = sum(
        int(row["size_bytes"]) for row in spatial_projection_files
    )
    spatial_snapshot = deploy._spatial_tree_snapshot(
        spatial_bundle_root,
        require_sanitized_modes=False,
    )
    spatial_local_files = [
        {
            "path": relpath,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for relpath, content in sorted(spatial_snapshot.items())
    ]
    spatial_package_sha256 = deploy._spatial_package_sha256(spatial_snapshot)
    projection_sha256, projection_files = deploy._candidate_projection_tree_digest(
        projection_root
    )
    projection_bytes = sum(int(row["size_bytes"]) for row in projection_files)
    source_revision = "b" * 40
    api_container_id = "1" * 64
    gateway_container_id = "2" * 64
    candidate_images = {
        "api": {
            "container_id": api_container_id,
            "image_id": runner.candidate_image,
        },
        "gateway": {
            "container_id": gateway_container_id,
            "image_id": runner.candidate_image,
        },
        "prepared_image_id": runner.candidate_image,
        "revision_label": source_revision,
        "all_match_prepared_image": True,
    }
    runtime_projection = {
        "schema": "ea.manfred_candidate_runtime_projection.v1",
        "projection_sha256": projection_sha256,
        "file_count": len(projection_files),
        "projection_bytes": projection_bytes,
        "mount_roots": [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/release-authority",
        ],
        "runtime_bytes_match_prepared_projection": True,
    }
    runtime_version = {
        "path": "/version",
        "status": 200,
        "commit_sha": source_revision,
        "body_commit_sha": source_revision,
        "source_revision_header": source_revision,
        "expected_commit_sha": source_revision,
        "oci_image_revision": source_revision,
        "repository": "EA",
        "role": "api",
        "release_authority_state": "clear",
        "release_authority_posture": "authoritative_runtime",
        "release_authority_source": "published_status_artifact",
        "commit_observed_over_http": True,
        "revision_agreement_verified": True,
    }
    compose_relative_path = "deploy/manfred-memorial/docker-compose.candidate.yml"
    compose_bytes = (root / compose_relative_path).read_bytes()
    git_blob_bytes = f"blob {len(compose_bytes)}\0".encode("ascii") + compose_bytes
    compose_attestation = {
        "canonical_relative_path": compose_relative_path,
        "canonical_source_path": str(
            (root.parent / "producer-checkout" / compose_relative_path).resolve()
        ),
        "candidate_commit": source_revision,
        "git_blob_oid": hashlib.sha1(  # noqa: S324 - Git object fixture
            git_blob_bytes,
            usedforsecurity=False,
        ).hexdigest(),
        "sha256": hashlib.sha256(compose_bytes).hexdigest(),
        "size_bytes": len(compose_bytes),
        "canonical_path_enforced": True,
        "tracked_blob_bytes_enforced": True,
    }
    candidate_env_keys = sorted(
        {
            "DATABASE_URL",
            "EA_API_TOKEN",
            "EA_MANFRED_COMPOSE_PROJECT",
            "EA_MANFRED_COMMIT",
            "EA_MANFRED_DEPLOYMENT_ID",
            "EA_MANFRED_ENV_FILE",
            "EA_MANFRED_HOST_PORT",
            "EA_MANFRED_IMAGE",
            "EA_MANFRED_MEMORIAL_SURFACE",
            "EA_MANFRED_POSTGRES_PASSWORD",
            "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
            "EA_MANFRED_RELEASE_ROOT",
            "EA_MANFRED_RUNTIME_ROOT",
            "EA_MANFRED_SPATIAL_SCOPE",
            "EA_PUBLIC_APP_BASE_URL",
            "EA_SIGNING_SECRET",
        }
    )
    execution_inputs = {
        "schema": "ea.manfred_candidate_execution_inputs.v1",
        "compose_sha256": compose_attestation["sha256"],
        "compose_size_bytes": compose_attestation["size_bytes"],
        "compose_git_blob_oid": compose_attestation["git_blob_oid"],
        "environment_sha256": "6" * 64,
        "environment_size_bytes": 8192,
        "environment_keys": candidate_env_keys,
        "compose_image_id": runner.candidate_image,
        "compose_image_reference_source": "prepared_image_id",
        "transport": "sealed_memfd",
        "required_seals": ["grow", "seal", "shrink", "write"],
        "all_compose_commands_use_sealed_inputs": True,
        "mutable_source_paths_consumed_by_compose": False,
        "mutable_image_locator_consumed_by_compose": False,
    }
    runtime_root = (root / ".runtime/candidate-data").resolve()
    runtime_mounts = [
        {
            "destination": destination,
            "identity": str(source.resolve()),
            "read_only": True,
            "type": "bind",
        }
        for destination, source in (
            (
                "/data/memorial/public",
                projection_root / "public_memorials",
            ),
            (
                "/data/memorial/private",
                projection_root / "private_memorial_profiles",
            ),
            (
                "/data/memorial/archive",
                projection_root / "memorial_archive",
            ),
            (
                "/data/release-authority",
                projection_root / "release-authority",
            ),
        )
    ]
    runtime_mounts.extend(
        {
            "destination": destination,
            "identity": str((runtime_root / basename).resolve()),
            "read_only": False,
            "type": "bind",
        }
        for destination, basename in (
            (
                "/data/memorial/public-contributions",
                "public-contributions",
            ),
            (
                "/data/memorial/private-contributions",
                "private-contributions",
            ),
            ("/data/memorial/state", "state"),
        )
    )
    runtime_mounts.append(
        {
            "destination": "/data/artifacts",
            "identity": "ea-manfred-candidate-test0001_artifacts",
            "read_only": False,
            "type": "volume",
        }
    )
    runtime_environment_keys = sorted(
        {
            *candidate_env_keys,
            "EA_ALLOW_LOOPBACK_NO_AUTH",
            "EA_DEPLOY_COMMIT_SHA",
            "EA_DEPLOY_PUBLIC_ORIGIN",
            "EA_ENABLE_PUBLIC_MEMORIALS",
            "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES",
            "EA_ENABLE_PUBLIC_TOURS",
            "EA_PUBLIC_MEMORIAL_RATE_BACKEND",
            "EA_PUBLIC_MEMORIAL_REDIS_URL",
            "EA_RELEASE_AUTHORITY_STATUS_PATH",
            "EA_SOURCE_REVISION",
            "EA_STORAGE_BACKEND",
            "EA_STORAGE_FALLBACK_ALLOWED",
            "EA_TRUST_PROXY_HEADERS",
        }
    )
    runtime_api_posture = {
        "schema": "ea.manfred_candidate_api_runtime_posture.v1",
        "api_container_id": api_container_id,
        "image_id": runner.candidate_image,
        "environment_sha256": "7" * 64,
        "execution_environment_sha256": execution_inputs["environment_sha256"],
        "environment_keys": runtime_environment_keys,
        "environment_exact": True,
        "provider_credentials_present": False,
        "mounts": runtime_mounts,
        "mounts_exact": True,
        "tmpfs_exact": True,
        "networks": ["ea-manfred-candidate-test0001_backend"],
        "network_exact": True,
        "ingress_attached": False,
        "read_only_rootfs": True,
        "all_capabilities_dropped": True,
        "no_new_privileges": True,
        "runtime_user": "10001:10001",
        "running_and_healthy": True,
    }
    spatial_viewer = SPATIAL_VIEWER_RELPATH
    spatial_proof = SPATIAL_PROOF_RELPATH
    route_labels = list(SPATIAL_ROUTE_LABELS)
    spatial_verifier = {"pass": True, "checks": {"binding_count": 5}}
    spatial_projection = {
        "included": True,
        "slug": spatial_slug,
        "release_root": str((projection_root / "public_property_tours").resolve()),
        "projection_sha256": spatial_projection_sha256,
        "file_count": len(spatial_projection_files),
        "projection_bytes": spatial_projection_bytes,
        "receipt_path": str((root / ".runtime/spatial.json").resolve()),
        "receipt_sha256": "a" * 64,
        "projection_tree_revalidated": True,
        "ea_public_activation_authority": False,
        "asset_paths": list(SPATIAL_ASSET_PATHS),
        "viewer_relpath": spatial_viewer,
        "proof_relpath": spatial_proof,
        "route_labels": route_labels,
        "upstream_publication_authority_sha256": deploy.PROPERTY_AUTHORITY_SHA256,
        "upstream_package_sha256": spatial_package_sha256,
        "upstream_tour_manifest_sha256": hashlib.sha256(
            spatial_snapshot["tour.json"]
        ).hexdigest(),
        "pre_authority_manifest_canonical_sha256": (
            deploy.PROPERTY_PRE_AUTHORITY_SHA256
        ),
        "upstream_public_activation_authority": True,
        "local_release_verifier": spatial_verifier,
    }
    quoted_slug = spatial_slug
    viewer_path = f"/tours/viewer/{quoted_slug}/{spatial_viewer}"
    proof_path = f"/tours/viewer/{quoted_slug}/{spatial_proof}"
    spatial_browser = _exact_spatial_browser_receipt(
        slug=spatial_slug,
        source_revision=source_revision,
        image_id=runner.candidate_image,
        container_id=gateway_container_id,
        project="ea-manfred-candidate-test0001",
        route_labels=route_labels,
        local_files=spatial_local_files,
        package_sha256=spatial_package_sha256,
    )
    spatial_routes = {}
    for label, path, status, content_type in (
        ("html", f"/tours/{quoted_slug}", 200, "text/html"),
        ("json", f"/tours/{quoted_slug}.json", 200, "application/json"),
        ("viewer", viewer_path, 200, "text/html"),
        ("proof_only", proof_path, 404, "application/json"),
    ):
        for method in ("get", "head"):
            spatial_routes[f"{label}_{method}"] = {
                "path": path,
                "status": status,
                "content_type": content_type,
            }
    spatial_runtime = {
        "included": True,
        "routes_required": True,
        "slug": spatial_slug,
        "routes": spatial_routes,
        "generated_viewer_release_verifier": spatial_verifier,
        "candidate_browser_gate": spatial_browser,
        "html_json_viewer_200": True,
        "proof_only_404": True,
        "ea_public_activation_authority": False,
        "upstream_public_activation_authority": True,
    }
    live_openapi_evidence = {
        "path_count": 3,
        "operation_count": 5,
        "schema_count": 2,
        "security_scheme_count": 1,
        "path_digest_sha256": "1" * 64,
        "contract_digest_sha256": "3" * 64,
        "snapshot_source": "live_api_container_app.openapi",
        "public_docs_config_retired": True,
        "container_id": "d" * 64,
        "image_id": runner.old_image,
        "started_at": "2026-07-13T00:00:01Z",
        "service": "ea-api",
        "container_name": "ea-api",
        "running": True,
        "health": "healthy",
    }
    candidate_receipt.write_text(
        json.dumps(
            {
                "schema": "ea.manfred_memorial_candidate_runtime.v4",
                "status": "pass",
                "image": runner.candidate_reference,
                "image_id": runner.candidate_image,
                "image_source_revision": source_revision,
                "image_locator_evidence": {
                    "locator": runner.candidate_reference,
                    "resolved_image_id": runner.candidate_image,
                    "revision_label": source_revision,
                    "used_for_attestation_only": True,
                    "consumed_by_compose": False,
                },
                "compose_uses_immutable_image_id": True,
                "candidate_container_images": candidate_images,
                "candidate_container_images_initial": candidate_images,
                "candidate_container_images_final": candidate_images,
                "candidate_container_image_identity_stable": True,
                "runtime_projection_initial": runtime_projection,
                "runtime_projection_final": runtime_projection,
                "runtime_projection_identity_stable": True,
                "runtime_version_identity": runtime_version,
                "runtime_source_revision": source_revision,
                "runtime_authority_commit": source_revision,
                "runtime_revision_matches_image": True,
                "projection_commit": source_revision,
                "prepared_image_locator": runner.candidate_reference,
                "prepared_image_id": runner.candidate_image,
                "projection_tree_revalidated": True,
                "release_id": (root / "memorial_data").name,
                "release_root": str((root / "memorial_data").resolve()),
                "projection_sha256": projection_sha256,
                "projection_files": projection_files,
                "projection_file_count": len(projection_files),
                "projection_bytes": projection_bytes,
                "spatial_handoff": spatial_projection,
                "compose_project": "ea-manfred-candidate-test0001",
                "compose_project_isolated": True,
                "compose_attestation": compose_attestation,
                "execution_inputs": execution_inputs,
                "compose_environment_bound_to_candidate_env": True,
                "candidate_named_resources": {
                    "containers": sorted(
                        [
                            f"ea-manfred-candidate-test0001-{service}-1"
                            for service in ("api", "gateway", "postgres", "redis")
                        ]
                        + [
                            f"ea-manfred-candidate-test0001_{service}_1"
                            for service in ("api", "gateway", "postgres", "redis")
                        ]
                    ),
                    "networks": [
                        "ea-manfred-candidate-test0001_backend",
                        "ea-manfred-candidate-test0001_ingress",
                    ],
                    "volumes": [
                        "ea-manfred-candidate-test0001_artifacts",
                        "ea-manfred-candidate-test0001_postgres_data",
                        "ea-manfred-candidate-test0001_redis_data",
                    ],
                },
                "candidate_preflight": {
                    "project": "ea-manfred-candidate-test0001",
                    "containers": 0,
                    "networks": 0,
                    "volumes": 0,
                    "named_container_collisions": [],
                    "named_network_collisions": [],
                    "named_volume_collisions": [],
                    "loopback_host": "127.0.0.1",
                    "loopback_port": 18090,
                    "loopback_port_free_before_start": True,
                },
                "locks": {
                    "project": {
                        "scope": "compose_project",
                        "project": "ea-manfred-candidate-test0001",
                        "held_through_candidate_proof": True,
                    },
                    "port": {
                        "scope": "host_loopback_port",
                        "port": 18090,
                        "held_through_candidate_proof": True,
                    },
                    "fleet": {
                        "scope": "manfred_candidate_fleet",
                        "lock_file": "ea-manfred-candidate-fleet.lock",
                        "exclusive": True,
                        "nonblocking": True,
                        "held_through_candidate_proof": True,
                    },
                },
                "project_lock": {
                    "scope": "compose_project",
                    "project": "ea-manfred-candidate-test0001",
                    "held_through_candidate_proof": True,
                },
                "port_lock": {
                    "scope": "host_loopback_port",
                    "port": 18090,
                    "held_through_candidate_proof": True,
                },
                "candidate_api_container_id": api_container_id,
                "runtime_api_posture": runtime_api_posture,
                "registry_recovery": {
                    "state_before_launch": "absent",
                    "crash_intent_reconciled": False,
                    "pending_contribution_reconciled": False,
                    "existing_receipt_resumed": False,
                    "interrupted_receipt_publication_completed": False,
                },
                "candidate_port": 18090,
                "api_network_internal": True,
                "gateway_has_runtime_secrets": False,
                "provider_credentials_present": False,
                "provider_calls_performed": False,
                "spatial_handoff_runtime": spatial_runtime,
                "openapi_contract": {
                    "live_before": dict(live_openapi_evidence),
                    "candidate": {
                        "path_count": 1,
                        "operation_count": 3,
                        "schema_count": 3,
                        "security_scheme_count": 1,
                        "path_digest_sha256": "2" * 64,
                        "contract_digest_sha256": "4" * 64,
                        "snapshot_source": "candidate_api_container_app.openapi",
                        "public_docs_config_retired": True,
                    },
                    "candidate_public_endpoint": {
                        "path": "/openapi.json",
                        "status": 404,
                        "error_code": "not_found",
                        "content_type": "application/json",
                        "media_type": "application/json",
                        "correlation_header_matches_body": True,
                        "security_headers": {
                            "content_security_policy": "frame-ancestors 'none'",
                            "x_content_type_options": "nosniff",
                            "x_frame_options": "DENY",
                        },
                        "public_endpoint_retired": True,
                    },
                    "live_after": dict(live_openapi_evidence),
                    "retirement_policy_id": deploy.OPENAPI_RETIREMENT_POLICY_ID,
                    "retirement_allowed_operations": list(
                        deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                    ),
                    "retired_operations": list(
                        deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                    ),
                    "retired_operation_count": len(
                        deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                    ),
                    "retirement_policy_exact_match": True,
                    "compatible_evolution_policy_id": (
                        "ea.openapi.compatible-evolution.version-remote-reachability.v1"
                    ),
                    "compatible_evolution_allowed_operations": ["GET /version"],
                    "compatible_evolved_operations": ["GET /version"],
                    "compatible_evolved_operation_count": 1,
                    "compatible_evolution_policy_exact_match": True,
                    "candidate_preserves_live_contract": True,
                    "missing_or_changed_operation_count": 0,
                    "missing_or_changed_schema_count": 0,
                    "missing_or_changed_security_scheme_count": 0,
                },
                "live_ea_api_unchanged": True,
                "live_ea_api": {
                    "name": "ea-api",
                    "service": "ea-api",
                    "running": True,
                    "health": "healthy",
                },
                "live_ea_project_before": {
                    "project": "ea",
                    "containers": [
                        {
                            "name": "ea-api",
                            "service": "ea-api",
                            "running": True,
                            "health": "healthy",
                        }
                    ],
                    "networks": [],
                    "volumes": [],
                },
                "live_ea_project_after": {
                    "project": "ea",
                    "containers": [
                        {
                            "name": "ea-api",
                            "service": "ea-api",
                            "running": True,
                            "health": "healthy",
                        }
                    ],
                    "networks": [],
                    "volumes": [],
                },
                "live_ea_project_unchanged": True,
                "candidate_left_running_for_soak": True,
                "promotion_authority": False,
                "first_smoke_checks": [
                    "archive_publication_gate",
                    "singular_memorial_alias",
                    "source_grounded_narrator_boundary",
                    "voice_provider_boundary_blocked",
                ],
                "second_smoke_checks": [
                    "archive_publication_gate",
                    "singular_memorial_alias",
                    "source_grounded_narrator_boundary",
                    "voice_provider_boundary_blocked",
                ],
                "browser_surface": {
                    "status": "pass",
                    "automatic_provider_requests": 0,
                    "automatic_websockets": 0,
                    "external_requests": 0,
                    "failed_requests": 0,
                    "page_errors": 0,
                    "http_errors": 0,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_receipt.chmod(0o600)

    env = {
        "EA_DEPLOYMENT_ID": deployment_id,
        "EA_MEMORIAL_IMAGE": runner.candidate_reference,
        "EA_MEMORIAL_CANDIDATE_RECEIPT": str(candidate_receipt),
        "EA_MEMORIAL_DATA_HOST_PATH": str((root / "memorial_data").resolve()),
        "EA_MEMORIAL_RUNTIME_HOST_PATH": str(runtime_root),
        "EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST": "memorial.example.org",
    }
    if control_tour_slug:
        env["EA_MEMORIAL_CONTROL_TOUR_SLUG"] = control_tour_slug

    vexp_authority_root = root.parent / "vexp-test-authority"
    vexp_authority_root.mkdir(parents=True, exist_ok=True)
    vexp_authority_root.chmod(0o755)
    vexp_state_path = vexp_authority_root / "state.json"
    vexp_permit_path = vexp_authority_root / "memorial-mutation-permit.json"
    vexp_permit_commit_path = (
        vexp_authority_root / "memorial-mutation-permit.commit.json"
    )
    vexp_lock_path = vexp_authority_root / "memorial-mutation-permit.lock"
    vexp_epoch_void_ledger_root = vexp_authority_root / "epoch-voids"
    vexp_epoch_void_ledger_root.mkdir(mode=0o750, exist_ok=True)
    vexp_epoch_void_ledger_root.chmod(0o750)
    vexp_certificate_root = vexp_authority_root / "qualification-certificate"
    vexp_certificate_root.mkdir(mode=0o750, exist_ok=True)
    vexp_certificate_root.chmod(0o750)
    vexp_certificate_directory = vexp_certificate_root / "certificates"
    vexp_certificate_directory.mkdir(mode=0o750, exist_ok=True)
    vexp_certificate_directory.chmod(0o750)
    vexp_state: dict[str, object] = {
        "version": deploy.VEXP_SENTINEL_STATE_VERSION,
        "epoch_started_at": "2026-07-13T09:43:56.206Z",
        "epoch_started_ms": 1783935836206,
        "qualification_phase": "qualified",
        "qualification_earliest_completion_at": "2026-07-20T09:43:56.206Z",
        "qualified_at": "2026-07-20T09:43:56.206Z",
        "updated_at": "2026-07-20T09:59:00.000Z",
        "current_resources_healthy": True,
        "certification_blockers": [],
        "certification_deferments": [],
        "predicate_contract": "v6",
        "predicate_contract_sha256": "3" * 64,
    }
    vexp_certificate = _vexp_certificate(vexp_state)
    vexp_certificate_raw = (
        json.dumps(
            vexp_certificate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    vexp_certificate_sha256 = hashlib.sha256(vexp_certificate_raw).hexdigest()
    runner.candidate_seal_epoch_started_ms = int(vexp_state["epoch_started_ms"])
    runner.candidate_seal_certificate_sha256 = vexp_certificate_sha256
    vexp_certificate_path = (
        vexp_certificate_directory / f"{vexp_state['epoch_started_ms']}.json"
    )
    vexp_certificate_path.write_bytes(vexp_certificate_raw)
    vexp_certificate_path.chmod(0o640)
    vexp_certificate_sidecar = vexp_certificate_path.with_suffix(".json.sha256")
    vexp_certificate_sidecar.write_bytes(
        f"sha256:{vexp_certificate_sha256}\n".encode("ascii")
    )
    vexp_certificate_sidecar.chmod(0o640)
    vexp_active_chain = vexp_certificate["active_chain"]
    assert isinstance(vexp_active_chain, dict)
    vexp_qualification_event = vexp_active_chain["qualification_event"]
    assert isinstance(vexp_qualification_event, dict)
    vexp_permit = {
        "contract_name": deploy.VEXP_MUTATION_PERMIT_CONTRACT_NAME,
        "version": deploy.VEXP_MUTATION_PERMIT_VERSION,
        "status": "allow",
        "epoch_started_at": vexp_state["epoch_started_at"],
        "epoch_started_ms": vexp_state["epoch_started_ms"],
        "qualification_earliest_completion_at": vexp_state[
            "qualification_earliest_completion_at"
        ],
        "qualified_at": vexp_state["qualified_at"],
        "terminal_identity_sha256": deploy._vexp_terminal_identity_sha256(
            vexp_state
        ),
        "qualification_certificate_schema": vexp_certificate["schema"],
        "qualification_certificate_sha256": vexp_certificate_sha256,
        "qualification_certificate_identity": vexp_certificate["identity"],
        "qualification_certificate_event_hash": vexp_qualification_event["hash"],
        "issued_at": "2026-07-20T09:45:00.000Z",
        "expires_at": "2026-07-20T10:30:00.000Z",
        "mutation_boundaries": list(deploy.VEXP_MUTATION_BOUNDARIES),
    }
    vexp_state_path.write_text(
        json.dumps(vexp_state, sort_keys=True) + "\n", encoding="utf-8"
    )
    vexp_state_path.chmod(0o600)
    vexp_permit_raw = (
        json.dumps(vexp_permit, sort_keys=True) + "\n"
    ).encode("utf-8")
    vexp_permit_path.write_bytes(vexp_permit_raw)
    vexp_permit_path.chmod(0o644)
    vexp_permit_commit = {
        "contract_name": deploy.VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME,
        "version": deploy.VEXP_MUTATION_PERMIT_COMMIT_VERSION,
        "status": "committed",
        "permit_sha256": hashlib.sha256(vexp_permit_raw).hexdigest(),
        "permit_contract_name": vexp_permit["contract_name"],
        "permit_version": vexp_permit["version"],
        "epoch_started_at": vexp_permit["epoch_started_at"],
        "epoch_started_ms": vexp_permit["epoch_started_ms"],
        "terminal_identity_sha256": vexp_permit["terminal_identity_sha256"],
        "qualification_certificate_sha256": vexp_permit[
            "qualification_certificate_sha256"
        ],
        "issued_at": vexp_permit["issued_at"],
        "expires_at": vexp_permit["expires_at"],
    }
    vexp_permit_commit_path.write_text(
        json.dumps(vexp_permit_commit, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    vexp_permit_commit_path.chmod(0o644)
    vexp_lock_path.touch()
    vexp_lock_path.chmod(0o644)

    current_predicate_root = (
        vexp_authority_root / "vexp-qualification-current-predicate"
    )
    current_predicate_root.mkdir(mode=0o750, exist_ok=True)
    current_predicate_root.chmod(0o750)
    current_predicate_records = current_predicate_root / "records"
    current_predicate_records.mkdir(mode=0o750, exist_ok=True)
    current_predicate_records.chmod(0o750)
    current_predicate_producer_parent = vexp_authority_root / "root-producers"
    current_predicate_producer_parent.mkdir(mode=0o755, exist_ok=True)
    current_predicate_producer_parent.chmod(0o755)
    current_predicate_producer_path = (
        current_predicate_producer_parent / "current-predicate-attestor"
    )
    producer_bytes = b"governed deploy test predicate attestor\n"
    if current_predicate_producer_path.exists():
        assert current_predicate_producer_path.read_bytes() == producer_bytes
    else:
        current_predicate_producer_path.write_bytes(producer_bytes)
    current_predicate_producer_path.chmod(0o555)
    current_predicate_producer_sha256 = hashlib.sha256(
        current_predicate_producer_path.read_bytes()
    ).hexdigest()
    current_predicate_manifest = {
        "contract_name": (
            deploy.VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_CONTRACT_NAME
        ),
        "version": deploy.VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_VERSION,
        "status": "reviewed",
        "producer_path": str(current_predicate_producer_path),
        "producer_sha256": current_predicate_producer_sha256,
    }
    current_predicate_manifest_path = (
        current_predicate_root / "producer-manifest.json"
    )
    current_predicate_manifest_path.write_bytes(
        deploy._canonical_guard_json_bytes(current_predicate_manifest)
    )
    current_predicate_manifest_path.chmod(0o640)
    current_predicate_boot_id = "12345678-1234-4234-9234-123456789abc"
    current_predicate_monotonic_ns = (
        1_000_000_000
        + deploy.MINIMUM_VEXP_QUALIFICATION_DURATION_MS * 1_000_000
        + 60_000_000_000
    )
    vexp_state_raw = vexp_state_path.read_bytes()
    current_predicate_record = {
        "contract_name": deploy.VEXP_CURRENT_PREDICATE_CONTRACT_NAME,
        "version": deploy.VEXP_CURRENT_PREDICATE_VERSION,
        "status": "positive",
        "epoch_started_ms": vexp_state["epoch_started_ms"],
        "generation": 1,
        "observed_at": "2026-07-20T09:59:00.000Z",
        "recorded_at": "2026-07-20T09:59:00.000Z",
        "boot_id": current_predicate_boot_id,
        "monotonic_ns": current_predicate_monotonic_ns,
        "sentinel_state_path": str(vexp_state_path),
        "sentinel_state_owner_uid": os.geteuid(),
        "sentinel_state_sha256": hashlib.sha256(vexp_state_raw).hexdigest(),
        "terminal_identity_sha256": deploy._vexp_terminal_identity_sha256(
            vexp_state
        ),
        "qualification_certificate_sha256": vexp_certificate_sha256,
        "predicate_contract_sha256": vexp_state["predicate_contract_sha256"],
        "current_resources_healthy": True,
        "certification_blockers": [],
        "certification_deferments": [],
        "sentinel_producer_sha256": "1" * 64,
        "root_predicate_producer_sha256": (
            current_predicate_producer_sha256
        ),
        "previous_record_sha256": "0" * 64,
    }
    current_predicate_record_path = (
        current_predicate_records
        / f"{vexp_state['epoch_started_ms']}-1.json"
    )
    current_predicate_record_raw = deploy._canonical_guard_json_bytes(
        current_predicate_record
    )
    current_predicate_record_path.write_bytes(current_predicate_record_raw)
    current_predicate_record_path.chmod(0o640)
    current_predicate_pointer = {
        "contract_name": deploy.VEXP_CURRENT_PREDICATE_POINTER_CONTRACT_NAME,
        "version": deploy.VEXP_CURRENT_PREDICATE_POINTER_VERSION,
        "status": "published",
        "epoch_started_ms": vexp_state["epoch_started_ms"],
        "generation": 1,
        "record_path": str(current_predicate_record_path),
        "record_sha256": hashlib.sha256(
            current_predicate_record_raw
        ).hexdigest(),
    }
    current_predicate_pointer_path = current_predicate_root / "current.json"
    current_predicate_pointer_path.write_bytes(
        deploy._canonical_guard_json_bytes(current_predicate_pointer)
    )
    current_predicate_pointer_path.chmod(0o640)

    candidate_authority_core = {
        "status": "pass",
        "contract_name": deploy.CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME,
        "version": deploy.CANDIDATE_VEXP_MUTATION_PERMIT_VERSION,
        "epoch_started_ms": vexp_state["epoch_started_ms"],
        "qualified_at": vexp_state["qualified_at"],
        "terminal_identity_sha256": deploy._vexp_terminal_identity_sha256(
            vexp_state
        ),
        "qualification_certificate_schema": vexp_certificate["schema"],
        "qualification_certificate_sha256": vexp_certificate_sha256,
        "qualification_certificate_identity": vexp_certificate["identity"],
        "qualification_certificate_event_hash": vexp_qualification_event["hash"],
        "permit_sha256": "8" * 64,
        "permit_commit": {
            "contract_name": deploy.VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME,
            "version": deploy.VEXP_MUTATION_PERMIT_COMMIT_VERSION,
            "status": "committed",
            "sha256": "9" * 64,
        },
        "epoch_void_ledger": {
            "root": str(vexp_epoch_void_ledger_root),
            "entry": str(
                vexp_epoch_void_ledger_root
                / f"{vexp_state['epoch_started_ms']}.json"
            ),
            "entry_present": False,
            "root_trusted": True,
        },
        "permit_issued_at": "2026-07-20T09:45:00.000Z",
        "permit_expires_at": "2026-07-20T10:30:00.000Z",
        "current_predicate": {
            "contract_name": deploy.VEXP_CURRENT_PREDICATE_CONTRACT_NAME,
            "version": deploy.VEXP_CURRENT_PREDICATE_VERSION,
            "status": "positive",
            "epoch_started_ms": vexp_state["epoch_started_ms"],
            "generation": 1,
            "record_sha256": hashlib.sha256(
                current_predicate_record_raw
            ).hexdigest(),
            "boot_id": current_predicate_boot_id,
            "monotonic_ns": current_predicate_monotonic_ns,
            "sentinel_producer_sha256": "1" * 64,
            "root_predicate_producer_sha256": (
                current_predicate_producer_sha256
            ),
        },
    }

    def candidate_authority_row(*, phase: str, boundary: str) -> dict[str, object]:
        return {**candidate_authority_core, "phase": phase, "boundary": boundary}

    candidate_payload = json.loads(candidate_receipt.read_text(encoding="utf-8"))
    candidate_payload["schema"] = "ea.manfred_memorial_candidate_runtime.v6"
    candidate_payload["memorial_surface"] = "conversation_only"
    candidate_payload["spatial_scope"] = "separate_propertyquarry_lane"
    candidate_payload["public_property_tours_packaged"] = False
    candidate_payload["public_property_tours_tested"] = False
    candidate_payload["memorial_spatial_receipt_generated"] = False
    candidate_payload.pop("spatial_handoff", None)
    candidate_payload.pop("spatial_handoff_runtime", None)
    candidate_payload["browser_surface"].update(
        {
            "memorial_surface": "conversation_only",
            "spatial_scope": "separate_propertyquarry_lane",
        }
    )
    for smoke_key in ("first_smoke_checks", "second_smoke_checks"):
        candidate_payload[smoke_key].append("conversation_only_public_surface")
    candidate_payload["observed_at"] = "2026-07-20T09:50:00Z"
    candidate_payload["openapi_contract"] = {
        "candidate": candidate_payload["openapi_contract"]["candidate"],
        "candidate_public_endpoint": candidate_payload["openapi_contract"][
            "candidate_public_endpoint"
        ],
        "live_comparison_status": "deferred_to_governed_promotion",
        "candidate_preserves_live_contract": False,
        "candidate_live_contract_claim_allowed": False,
    }
    candidate_payload["vexp_candidate_mutation_authority"] = {
        "entry": candidate_authority_row(
            phase="entry", boundary="candidate_entry"
        ),
        "mutations": [
            {
                "sequence": sequence,
                "operation": {
                    "before_candidate_up": "compose_up",
                    "before_candidate_exec": "redis_ping",
                    "before_candidate_interaction": "candidate_smoke",
                    "before_candidate_restart": "compose_restart_api",
                }[boundary],
                "resource": {
                    "argv": [
                        "fixture-runner",
                        {
                            "before_candidate_up": "compose_up",
                            "before_candidate_exec": "redis_ping",
                            "before_candidate_interaction": "candidate_smoke",
                            "before_candidate_restart": "compose_restart_api",
                        }[boundary],
                    ],
                    "target": f"fixture:{sequence}",
                },
                "runner_acknowledged": True,
                "authority": candidate_authority_row(
                    phase="pre_mutation",
                    boundary=boundary,
                ),
            }
            for sequence, boundary in enumerate(
                deploy.CANDIDATE_VEXP_MUTATION_SEQUENCE,
                start=1,
            )
        ],
        "finalization": candidate_authority_row(
            phase="finalization", boundary="candidate_receipt_publication"
        ),
        "cleanup_requires_positive_authority": True,
        "retention_timer_only_authority_free_cleanup": True,
    }
    image_build_receipt = root / ".runtime" / "candidate-image-build.v3.json"
    image_build_operations = []
    for sequence, (operation, resource) in enumerate(
        (
            ("image_build", runner.candidate_reference),
            ("builder_prune", image_builder.BUILDX_BUILDER_NAME),
            (
                "verification_create",
                image_builder._verification_container_name(runner.candidate_image),
            ),
            (
                "verification_probe",
                image_builder._verification_container_name(runner.candidate_image),
            ),
            (
                "verification_cleanup",
                image_builder._verification_container_name(runner.candidate_image),
            ),
        ),
        start=1,
    ):
        operation_argv = ["test-image-builder", operation, resource]
        image_build_operations.append(
            {
                "sequence": sequence,
                "operation": operation,
                "resource": {
                    "argv": operation_argv,
                    "target": resource,
                },
                "runner_acknowledged": True,
                "authority": candidate_authority_row(
                    phase="pre_mutation",
                    boundary="before_candidate_image_build",
                ),
            }
        )
    image_build_authority = {
        "entry": candidate_authority_row(
            phase="entry",
            boundary="candidate_entry",
        ),
        "operations": image_build_operations,
        "finalization": candidate_authority_row(
            phase="finalization",
            boundary="candidate_receipt_publication",
        ),
        "operation_count": len(image_build_operations),
        "operations_exact": True,
        "authority_basis": "new_image_build",
        "receipt_publication": "exclusive_hardlink_noreplace_v1",
        "receipt_publication_held_under_authority": True,
    }
    image_build_payload = image_builder._success_receipt(
        commit=source_revision,
        image_tag=runner.candidate_reference,
        image_id=runner.candidate_image,
        inspection={"RootFS": {"Layers": ["sha256:test-layer"]}},
        created_at="2026-07-20T09:49:00Z",
        builder_created=False,
        builder_validated=True,
        image_reused=False,
        cache_prune_status="pass",
        admission={
            "producer_sha256": "7" * 64,
            "soak_root_free_floor_bytes": (
                image_builder.SOAK_ROOT_FREE_FLOOR_BYTES
            ),
            "build_root_free_headroom_bytes": (
                image_builder.BUILD_ROOT_FREE_HEADROOM_BYTES
            ),
            "minimum_root_free_bytes": image_builder.MINIMUM_ROOT_FREE_BYTES,
            "root_free_bytes": {
                stage: image_builder.MINIMUM_ROOT_FREE_BYTES
                for stage in image_builder.ROOT_FREE_OBSERVATION_STAGES
            },
            "builder_created_before_build": False,
            "docker_mutations_before_build": 0,
            "docker_build_started": True,
        },
        producer_sha256="7" * 64,
        image_build_authority=image_build_authority,
    )
    image_build_raw = image_builder._build_receipt_bytes(image_build_payload)
    image_build_receipt.write_bytes(image_build_raw)
    image_build_receipt.chmod(0o600)
    candidate_payload["image_build_authority_binding"] = (
        image_builder.validated_build_receipt_binding(
            image_build_raw,
            receipt_path=image_build_receipt,
            commit=source_revision,
            image_tag=runner.candidate_reference,
            image_id=runner.candidate_image,
        )
    )
    candidate_receipt.write_text(
        json.dumps(candidate_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    candidate_receipt.chmod(0o600)

    def selected_http(
        url: str,
        timeout: float,
        public_authority: str = "",
    ) -> deploy.HttpResponse:
        del public_authority
        if url.endswith("/openapi.json") or "/tours/" in url:
            return safe_http(url, timeout)
        return (http_get or safe_http)(url, timeout)

    def safe_no_redirect(
        url: str,
        timeout: float,
        method: str,
    ) -> deploy.HttpResponse:
        del timeout
        if urllib.parse.urlsplit(url).path != "/memorial/manfred":
            return _public_spatial_response(url, method)
        return _singular_alias_response(method)

    def selected_no_redirect(
        url: str,
        timeout: float,
        method: str,
        public_authority: str = "",
    ) -> deploy.HttpResponse:
        del public_authority
        return (http_no_redirect or safe_no_redirect)(url, timeout, method)

    def internal_openapi_snapshot() -> dict[str, object]:
        response = safe_http("http://127.0.0.1:8090/openapi.json", 1)
        return {
            "docs_url": None,
            "document": json.loads(response.body),
            "openapi_url": None,
            "redoc_url": None,
        }

    def gemini_oauth_snapshot_factory() -> oauth_provision.CredentialSnapshot:
        runner.oauth_snapshot_count += 1
        if runner.oauth_snapshot_failure:
            raise oauth_provision.ProvisioningError("test_snapshot_failure")
        raw = (
            OAUTH_TEST_ALTERNATE_CREDENTIAL_BYTES
            if runner.oauth_source_changed
            else OAUTH_TEST_CREDENTIAL_BYTES
        )
        return oauth_provision.CredentialSnapshot(
            raw,
            oauth_provision.CredentialMetadata(
                schema=deploy.GEMINI_OAUTH_PROVISION_CONTRACT,
                status="snapshotted",
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                uid=os.geteuid(),
                gid=os.getegid(),
                mode="0600",
                device=101,
                inode=202 if not runner.oauth_source_changed else 303,
            ),
        )

    lane = deploy.MemorialDeployLane(
        root=root,
        env=env,
        runner=runner,
        http_get=selected_http,
        http_no_redirect=selected_no_redirect,
        internal_openapi_snapshot=internal_openapi_snapshot,
        sleep=lambda _: None,
        wait_seconds=0,
        receipt_dir=receipt_dir or root / ".runtime" / "test-receipts",
        global_lock_path=global_lock_path or root / ".runtime" / "test-global.lock",
        durable_root_check=lambda _root: None,
        bind_source_validator=bind_source_validator,
        release_evidence_verifier=runner.verify_release_evidence_snapshots,
        gemini_oauth_snapshot_factory=gemini_oauth_snapshot_factory,
    )
    lane._vexp_mutation_authority = TestVexpMemorialMutationAuthority(
        state_path=vexp_state_path,
        certificate_root=vexp_certificate_root,
        certificate_directory=vexp_certificate_directory,
        permit_path=vexp_permit_path,
        permit_commit_path=vexp_permit_commit_path,
        lock_path=vexp_lock_path,
        epoch_void_ledger_root=vexp_epoch_void_ledger_root,
        current_predicate_trusted_parent=vexp_authority_root,
        current_predicate_root=current_predicate_root,
        current_predicate_producer_trusted_parent=(
            current_predicate_producer_parent
        ),
        current_predicate_producer_path=current_predicate_producer_path,
        current_boot_id=current_predicate_boot_id,
        monotonic_ns=lambda: current_predicate_monotonic_ns,
        utc_now=lambda: datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
    )
    lane._require_reviewed_vexp_qualification_implementation_manifest = (  # type: ignore[method-assign]
        lambda _certificate: None
    )
    return lane


def _docker_mutation_calls(calls: Sequence[Sequence[str]]) -> list[list[str]]:
    return [
        list(call)
        for call in calls
        if list(call[:3])
        in (
            ["docker", "image", "tag"],
            ["docker", "start", "ea-redis"],
        )
        or list(call[:2]) == ["docker", "run"]
        or ("stop" in call and call[-1] == "ea-api")
        or ("up" in call and call[-1] in {"ea-api", "ea-redis"})
    ]


@pytest.mark.parametrize(
    "value",
    ["", "local-20260713", "../escape", "has space", "bad;command", "ab"],
)
def test_explicit_deployment_id_fails_closed(value: str, tmp_path: Path) -> None:
    with pytest.raises(deploy.DeployError):
        deploy.MemorialDeployLane(
            root=tmp_path,
            env={"EA_DEPLOYMENT_ID": value},
            receipt_dir=tmp_path / "receipts",
        )


def test_global_lock_serializes_distinct_ids_and_receipt_roots(
    release_root: Path,
) -> None:
    global_lock = release_root / ".runtime" / "host-global.lock"
    first = _lane(
        release_root,
        FakeRunner(release_root),
        deployment_id="memorial-release-001",
        receipt_dir=release_root / ".runtime" / "receipts-a",
        global_lock_path=global_lock,
    )
    second = _lane(
        release_root,
        FakeRunner(release_root),
        deployment_id="memorial-release-002",
        receipt_dir=release_root / ".runtime" / "receipts-b",
        global_lock_path=global_lock,
    )

    first._acquire_lock()
    try:
        with pytest.raises(
            deploy.DeployError, match="memorial_api_deployment_already_running"
        ):
            second._acquire_lock()
    finally:
        first._release_lock()


def test_default_global_lock_is_host_stable_across_receipt_roots(
    release_root: Path,
) -> None:
    lane = deploy.MemorialDeployLane(
        root=release_root,
        env={
            "EA_DEPLOYMENT_ID": "memorial-release-001",
            "EA_MEMORIAL_IMAGE": f"ea-runtime:memorial-{'b' * 40}",
        },
        receipt_dir=release_root / "custom-receipts",
        durable_root_check=lambda _root: None,
    )

    assert lane.global_lock_path == Path("/run/lock/ea-memorial-ea-api.lock")
    assert release_root not in lane.global_lock_path.parents


def test_secret_stdin_runner_timeout_covers_blocked_pipe_writer(
    tmp_path: Path,
) -> None:
    docker = _fake_secret_runner_docker(tmp_path)
    payload = bytearray(b"x" * (128 * 1024))

    def write_all(stream: BinaryIO) -> None:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = stream.write(view[offset:])
            assert isinstance(written, int) and written > 0
            offset += written

    started = time.monotonic()
    try:
        with pytest.raises(
            deploy.DeployError,
            match="^secret_stdin_command_timeout:docker$",
        ):
            deploy.SubprocessRunner().run_secret_stdin(
                [str(docker), "run"],
                cwd=tmp_path,
                env={"FAKE_DOCKER_MODE": "block"},
                write_stdin=write_all,
                timeout_seconds=0.05,
                container_name="ea-memorial-oauth-timeout-test",
                max_output_bytes=4096,
            )
    finally:
        for index in range(len(payload)):
            payload[index] = 0
        payload.clear()
    assert time.monotonic() - started < 2.0


def test_secret_stdin_runner_requires_positive_helper_container_absence(
    tmp_path: Path,
) -> None:
    docker = _fake_secret_runner_docker(tmp_path)

    with pytest.raises(
        deploy.GeminiOAuthHelperExitUnconfirmed,
        match="^gemini_oauth_helper_exit_unconfirmed$",
    ):
        deploy.SubprocessRunner().run_secret_stdin(
            [str(docker), "run"],
            cwd=tmp_path,
            env={
                "FAKE_DOCKER_MODE": "block",
                "FAKE_HELPER_PRESENT": "1",
            },
            write_stdin=lambda stream: stream.write(b"bounded-test-secret"),
            timeout_seconds=0.05,
            container_name="ea-memorial-oauth-present-test",
            max_output_bytes=4096,
        )


def test_secret_stdin_runner_interrupt_proves_helper_container_absence(
    tmp_path: Path,
) -> None:
    docker = _fake_secret_runner_docker(tmp_path)
    interrupt = threading.Timer(0.05, _thread.interrupt_main)
    interrupt.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            deploy.SubprocessRunner().run_secret_stdin(
                [str(docker), "run"],
                cwd=tmp_path,
                env={"FAKE_DOCKER_MODE": "block"},
                write_stdin=lambda stream: stream.write(b"bounded-test-secret"),
                timeout_seconds=2.0,
                container_name="ea-memorial-oauth-interrupt-test",
                max_output_bytes=4096,
            )
    finally:
        interrupt.cancel()


def test_secret_stdin_runner_bounds_attached_output(tmp_path: Path) -> None:
    docker = _fake_secret_runner_docker(tmp_path)

    completed = deploy.SubprocessRunner().run_secret_stdin(
        [str(docker), "run"],
        cwd=tmp_path,
        env={"FAKE_DOCKER_MODE": "bounded-output"},
        write_stdin=lambda stream: stream.write(b"bounded-test-secret"),
        timeout_seconds=2.0,
        container_name="ea-memorial-oauth-output-test",
        max_output_bytes=32,
    )

    assert completed.returncode == 0
    assert completed.stdout == b"x" * 33
    assert completed.stderr == b""


def test_preflight_does_not_require_a_propertyquarry_control_tour(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner, control_tour_slug="")

    context = lane.preflight()

    assert "EA_MEMORIAL_CONTROL_TOUR_SLUG" not in lane.env
    assert context["candidate_promotion"]["memorial_surface"] == "conversation_only"
    assert context["candidate_promotion"]["spatial_scope"] == (
        "separate_propertyquarry_lane"
    )


def test_candidate_projection_is_rehashed_before_promotion(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    candidate = {
        "reference": runner.candidate_reference,
        "image_id": runner.candidate_image,
    }

    evidence = lane._validate_candidate_promotion_receipt(
        candidate=candidate,
        source_revision="b" * 40,
    )
    assert evidence["projection"]["tree_revalidated"] is True
    assert evidence["projection"]["file_count"] == 0
    assert evidence["spatial_receipt_consumed"] is False
    assert evidence["separate_spatial_plane"] == {
        "status": "not_in_memorial_scope",
        "owner": "PropertyQuarry",
        "scope": "separate_propertyquarry_lane",
        "receipt_consumed": False,
        "routes_tested": False,
    }
    calls_after_validated_receipt = list(runner.calls)

    projection_root = release_root / "memorial_data"
    projection_root.chmod(0o750)
    changed = projection_root / "changed-after-candidate-proof.json"
    changed.write_text("{}\n", encoding="utf-8")
    changed.chmod(0o444)
    projection_root.chmod(0o550)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_projection_digest_mismatch",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate=candidate,
            source_revision="b" * 40,
        )
    assert runner.calls == calls_after_validated_receipt


def test_post_recreate_projection_mismatch_rolls_back(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    runner.mounted_projection_sha256 = "f" * 64
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match=("deployment_failed_rolled_back:deployed_api_projection_digest_mismatch"),
    ):
        lane.deploy()

    assert runner.api_mode == "prior"
    assert lane.receipt["status"] == "failed_rolled_back"
    assert any(
        call[:6]
        == [
            "/usr/bin/timeout",
            "--signal=KILL",
            "30s",
            "docker",
            "exec",
            "ea-api",
        ]
        for call in runner.calls
    )


def test_release_root_policy_rejects_temporary_paths_and_accepts_workspace(
    release_root: Path,
) -> None:
    with pytest.raises(deploy.DeployError, match="release_root_not_durable"):
        deploy._require_durable_release_root(release_root)
    deploy._require_durable_release_root(deploy.ROOT)


@pytest.mark.parametrize(
    ("branch", "upstream", "reason"),
    [
        ("", "origin/main", "release_branch_detached"),
        ("release/manfred", "", "release_branch_upstream_missing"),
    ],
)
def test_release_source_requires_attached_branch_and_upstream(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: str,
    upstream: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root, branch=branch, upstream=upstream)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("drift", "reason"),
    [
        ("detached_branch", "release_branch_detached"),
        ("authority_denied", "predeploy_release_authority_changed"),
        ("candidate_tag_retargeted", "predeploy_candidate_image_changed"),
        ("candidate_receipt_replaced", "memorial_candidate_vexp_authority_invalid"),
    ],
)
def test_predeploy_release_context_drift_denies_before_first_live_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_preflight = lane.preflight

    def preflight_then_drift() -> dict[str, object]:
        context = original_preflight()
        if drift == "detached_branch":
            runner.branch = ""
        elif drift == "authority_denied":
            runner.authority_status = "fail"
        elif drift == "candidate_tag_retargeted":
            runner.image_refs[runner.candidate_reference] = "sha256:" + "d" * 64
        elif drift == "candidate_receipt_replaced":
            candidate_receipt = Path(lane.candidate_receipt_value)
            candidate_receipt.write_text('{"status":"replaced"}\n', encoding="utf-8")
            candidate_receipt.chmod(0o600)
        else:  # pragma: no cover - guards the test table
            raise AssertionError(drift)
        return context

    monkeypatch.setattr(lane, "preflight", preflight_then_drift)

    with pytest.raises(deploy.DeployError, match=reason):
        lane.deploy()

    assert _docker_mutation_calls(runner.calls) == []
    assert lane.receipt["preparation"]["api_runtime_state"] == "unchanged"


def test_release_evidence_path_replacement_during_verification_is_denied(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    injected_verifier = lane.release_evidence_verifier
    assert injected_verifier is not None

    def replace_after_snapshot(
        snapshots: Mapping[str, bytes],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        release_manifest = (
            lane.receipt_dir
            / f"{lane.deployment_id}.evidence/predeploy/release-manifest.json"
        )
        assert hashlib.sha256(snapshots["release_manifest"]).hexdigest() == (
            hashlib.sha256(release_manifest.read_bytes()).hexdigest()
        )
        replacement = release_manifest.with_name("replacement-release-manifest.json")
        replacement.write_bytes(snapshots["release_manifest"])
        replacement.chmod(0o600)
        os.replace(replacement, release_manifest)
        return injected_verifier(snapshots)

    lane.release_evidence_verifier = replace_after_snapshot

    with pytest.raises(
        deploy.DeployError,
        match="release_evidence_file_rehashed_mismatch:release_manifest",
    ):
        lane.deploy(preflight_only=True)

    assert _docker_mutation_calls(runner.calls) == []


def test_release_context_drift_after_redis_create_denies_image_and_api_mutations(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root, redis_present=False)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_run = runner.run

    def run_then_drift(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = original_run(args, cwd=cwd, env=env, check=check)
        argv = [str(item) for item in args]
        if "up" in argv and argv[-1] == "ea-redis":
            runner.branch = ""
        return result

    runner.run = run_then_drift  # type: ignore[method-assign]

    with pytest.raises(deploy.DeployError, match="release_branch_detached"):
        lane.deploy()

    mutations = _docker_mutation_calls(runner.calls)
    assert len(mutations) == 1
    assert "up" in mutations[0] and mutations[0][-1] == "ea-redis"
    assert not any(call[:3] == ["docker", "image", "tag"] for call in mutations)
    assert not any("up" in call and call[-1] == "ea-api" for call in mutations)


def test_release_context_drift_after_image_tag_denies_api_recreation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_run = runner.run

    def run_then_drift(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = original_run(args, cwd=cwd, env=env, check=check)
        argv = [str(item) for item in args]
        if argv[:3] == ["docker", "image", "tag"]:
            runner.branch = ""
        return result

    runner.run = run_then_drift  # type: ignore[method-assign]

    with pytest.raises(deploy.DeployError, match="release_branch_detached"):
        lane.deploy()

    mutations = _docker_mutation_calls(runner.calls)
    assert len(mutations) == 1
    assert mutations[0][:3] == ["docker", "image", "tag"]
    assert not any("up" in call and call[-1] == "ea-api" for call in mutations)


def test_internal_docker_exec_is_a_live_read_only_non_mutating_probe(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    snapshot_factory = lane.internal_openapi_snapshot
    assert snapshot_factory is not None
    envelope = dict(snapshot_factory())
    lane.internal_openapi_snapshot = None
    monkeypatch.setattr(lane, "_vexp_mutation_lease", lambda _boundary: nullcontext())
    original_run = runner.run

    def openapi_exec(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        if argv[:6] == [
            "/usr/bin/timeout",
            "--signal=KILL",
            "30s",
            "docker",
            "exec",
            "ea-api",
        ]:
            runner.calls.append(argv)
            runner.call_envs.append(dict(env))
            return _completed(argv, stdout=json.dumps(envelope))
        return original_run(args, cwd=cwd, env=env, check=check)

    runner.run = openapi_exec  # type: ignore[method-assign]

    control = lane._capture_internal_openapi_control()

    probe = control["probe"]
    assert probe["transport"] == "docker_exec"
    assert probe["docker_exec_performed"] is True
    assert probe["live_action_performed"] is True
    assert probe["action_class"] == "read_only_non_mutating_probe"
    assert probe["live_mutation_performed"] is False
    assert _docker_mutation_calls(runner.calls) == []


@pytest.mark.parametrize(
    ("origin", "hosts", "reason"),
    [
        (
            "http://myexternalbrain.com",
            ["myexternalbrain.com"],
            "public_origin_invalid",
        ),
        (
            "https://unapproved.example.org",
            ["myexternalbrain.com"],
            "public_origin_host_not_approved",
        ),
        (
            "https://myexternalbrain.com:not-a-port",
            ["myexternalbrain.com"],
            "public_origin_invalid",
        ),
    ],
)
def test_public_origin_requires_https_and_approved_exact_host(
    origin: str, hosts: list[str], reason: str
) -> None:
    with pytest.raises(deploy.DeployError, match=reason):
        deploy._validate_public_origin(origin, allowed_hosts=hosts)

    assert (
        deploy._validate_public_origin(
            "https://www.myexternalbrain.com",
            allowed_hosts=deploy.DEFAULT_PUBLIC_HOSTS,
        )
        == "https://www.myexternalbrain.com"
    )


def test_local_public_authority_probe_sets_exact_headers_and_never_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []
    handlers: list[object] = []

    class RedirectingOpener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            del timeout
            requests.append(request)
            raise deploy.urllib.error.HTTPError(
                request.full_url,
                308,
                "Permanent Redirect",
                {"Location": "https://memorial.example.org/memorials/manfred"},
                None,
            )

    def fake_build_opener(*configured_handlers):  # type: ignore[no-untyped-def]
        handlers.extend(configured_handlers)
        return RedirectingOpener()

    monkeypatch.setattr(deploy.urllib.request, "build_opener", fake_build_opener)

    with pytest.raises(deploy.DeployError, match="http_status_invalid:.*:308"):
        deploy._default_http_get(
            "http://127.0.0.1:8090/memorials/manfred",
            1.0,
            "memorial.example.org",
        )

    assert len(requests) == 1
    request_headers = {
        str(name).casefold(): str(value)
        for name, value in requests[0].header_items()  # type: ignore[union-attr]
    }
    assert request_headers["host"] == "memorial.example.org"
    assert request_headers["x-forwarded-host"] == "memorial.example.org"
    assert request_headers["x-forwarded-proto"] == "https"
    assert any(isinstance(handler, deploy._NoRedirectHandler) for handler in handlers)


@pytest.mark.parametrize(
    ("image_reference", "reason"),
    [
        ("", "explicit_memorial_image_required"),
        ("ea-runtime:latest", "memorial_image_not_revision_bound"),
        ("https://registry.invalid/image:tag", "memorial_image_reference_invalid"),
    ],
)
def test_candidate_image_must_be_explicit_safe_and_revision_bound(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_reference: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    lane.memorial_image_reference = image_reference

    with pytest.raises(deploy.DeployError, match=reason):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        (
            "rendered_candidate_reference",
            "ea-runtime:wrong-candidate",
            "memorial_compose_candidate_image_mismatch",
        ),
        (
            "rendered_pull_policy",
            "missing",
            "memorial_compose_pull_policy_invalid",
        ),
    ],
)
def test_rendered_compose_requires_exact_candidate_and_never_pull(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    setattr(runner, attribute, value)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("rendered_memorial_data_source", "/wrong/memorial-data"),
        ("rendered_memorial_data_read_only", False),
    ],
)
def test_rendered_compose_requires_exact_read_only_memorial_data_mount(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: object,
) -> None:
    runner = FakeRunner(release_root)
    setattr(runner, attribute, value)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="memorial_compose_data_mount_mismatch"
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_rendered_process_config_matches_compose_dollar_escape_runtime() -> None:
    image_config = {
        "Cmd": ["python", "-c", "print('$$IMAGE_LITERAL')"],
        "Entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
        "User": "ea",
    }
    service = {
        "entrypoint": [
            "/bin/sh",
            "-ec",
            'umask 0007; exec /usr/local/bin/docker-entrypoint.sh "$$@"',
            "--",
        ]
    }

    rendered = deploy.MemorialDeployLane._rendered_process_config(service, image_config)

    assert rendered == {
        "Cmd": ["python", "-c", "print('$$IMAGE_LITERAL')"],
        "Entrypoint": [
            "/bin/sh",
            "-ec",
            'umask 0007; exec /usr/local/bin/docker-entrypoint.sh "$@"',
            "--",
        ],
        "User": "ea",
    }


def test_rendered_mount_identity_matches_named_volume_runtime_source(
    tmp_path: Path,
) -> None:
    runtime = deploy._mount_identities(
        {
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(tmp_path / "config"),
                    "Destination": "/app/config",
                    "RW": False,
                },
                {
                    "Type": "volume",
                    "Name": "ea_ea_artifacts",
                    "Source": "/var/lib/docker/volumes/ea_ea_artifacts/_data",
                    "Destination": "/data/artifacts",
                    "RW": True,
                },
            ]
        }
    )
    rendered = deploy.MemorialDeployLane._rendered_mount_identities(
        {"volumes": {"artifacts": {"name": "ea_ea_artifacts"}}},
        {
            "volumes": [
                {
                    "type": "bind",
                    "source": str(tmp_path / "config"),
                    "target": "/app/config",
                    "read_only": True,
                },
                {
                    "type": "volume",
                    "source": "artifacts",
                    "target": "/data/artifacts",
                },
            ]
        },
        root=tmp_path,
    )

    assert runtime == rendered


def test_memorial_rollback_environment_is_reconstructed_from_live_identity(
    tmp_path: Path,
) -> None:
    container_values = {
        "EA_SOURCE_REVISION": "a" * 40,
        "EA_ENABLE_PUBLIC_MEMORIALS": "1",
        "EA_HEALTHCHECK_MEMORIAL_SLUG": "manfred",
        "EA_PUBLIC_MEMORIAL_RATE_BACKEND": "redis",
        "EA_PUBLIC_MEMORIAL_REDIS_URL": "redis://ea-redis:6379/0",
        "EA_PUBLIC_MEMORIAL_DIR": "/data/memorial_data/public_memorials",
        "EA_PRIVATE_MEMORIAL_PROFILE_DIR": (
            "/data/memorial_data/private_memorial_profiles"
        ),
        "EA_MEMORIAL_LIVE_TTS_PLUGIN": "unmixr_clone",
        "EA_TRUSTED_PROXY_CIDRS": "172.22.0.12/32,172.22.0.1/32",
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES": "origin.myexternalbrain.com",
        "EA_ALLOWED_PUBLIC_HOSTS": "myexternalbrain.com,www.myexternalbrain.com",
        "SECRET_TOKEN": "must-not-be-copied",
    }
    data_root = (tmp_path / "release").resolve()
    runtime_root = (tmp_path / "runtime").resolve()
    mounts = [
        {
            "type": "bind",
            "source": str(data_root),
            "destination": "/data/memorial_data",
            "read_write": False,
        },
        *[
            {
                "type": "bind",
                "source": str(runtime_root / leaf),
                "destination": f"/data/memorial-writable/{leaf}",
                "read_write": True,
            }
            for leaf in ("public-contributions", "private-contributions", "state")
        ],
    ]

    environment = deploy._memorial_rollback_environment(
        config={
            "Env": [
                f"{name}={value}" for name, value in container_values.items()
            ]
        },
        mount_identities=mounts,
        image_reference="ea-runtime:manfred-prior",
    )

    assert set(environment) == deploy.ROLLBACK_MEMORIAL_RENDER_ENV_KEYS
    assert environment["EA_SOURCE_REVISION"] == "a" * 40
    assert environment["EA_MEMORIAL_DATA_HOST_PATH"] == str(data_root)
    assert environment["EA_MEMORIAL_RUNTIME_HOST_PATH"] == str(runtime_root)
    assert environment["EA_MEMORIAL_IMAGE"] == "ea-runtime:manfred-prior"
    assert "SECRET_TOKEN" not in environment


def test_rollback_render_environment_drift_fails_before_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_render_environment = {"DRIFTED_VALUE": "changed"}
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="rollback_render_environment_identity_mismatch",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_release_authority_failure_stops_before_compose_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, authority_status="fail")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="release_authority_not_pass"):
        lane.deploy(preflight_only=True)

    mutating = [
        call for call in runner.calls if "up" in call or "force-recreate" in call
    ]
    assert mutating == []


def test_memorial_readiness_failure_stops_before_compose_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, readiness_status="fail")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="memorial_deploy_readiness_not_pass"):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_dirty_source_fails_before_evidence_or_docker_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {
            "source_worktree_dirty": True,
            "source_dirty_files": ["ea/app/example.py"],
        },
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="source_worktree_dirty"):
        lane.deploy(preflight_only=True)

    assert not any("materialize_" in " ".join(call) for call in runner.calls)
    assert not any("up" in call for call in runner.calls)


def test_private_release_evidence_preserves_tracked_defaults_and_binds_phase(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracked_default = (
        release_root / ".codex-studio" / "published" / "deploy_context.generated.json"
    )
    tracked_default.parent.mkdir(parents=True)
    tracked_default.write_text('{"stale":"committed"}\n', encoding="utf-8")
    before = tracked_default.read_bytes()
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    lane.release_env["OPENAI_API_KEY"] = "provider-secret-sentinel"
    verified_snapshots: list[dict[str, bytes]] = []
    injected_verifier = lane.release_evidence_verifier
    assert injected_verifier is not None

    def capture_exact_snapshots(
        snapshots: Mapping[str, bytes],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        verified_snapshots.append(dict(snapshots))
        return injected_verifier(snapshots)

    lane.release_evidence_verifier = capture_exact_snapshots

    receipt = lane.deploy(preflight_only=True)

    assert tracked_default.read_bytes() == before
    assert set(receipt["release_evidence"]) == {"predeploy"}
    context_seal = receipt["predeploy_release_context_seal"]
    assert set(context_seal) == {"status", "sha256", "preimage"}
    assert context_seal["status"] == "sealed"
    assert context_seal["sha256"] == deploy._canonical_json_sha256(
        context_seal["preimage"]
    )
    assert "provider-secret-sentinel" not in json.dumps(context_seal, sort_keys=True)
    evidence = receipt["release_evidence"]["predeploy"]
    assert evidence["directory"] == ("memorial-release-001.evidence/predeploy")
    assert evidence["directory_mode"] == "0700"
    assert evidence["source_seal"]["head"] == "b" * 40
    assert evidence["source_seal"]["head_tree"] == "d" * 40
    assert set(evidence["files"]) == {
        "deploy_context",
        "release_manifest",
        "release_authority_status",
        "memorial_operator_status",
        "phase_manifest",
    }
    for detail in evidence["files"].values():
        path = lane.receipt_dir / detail["path"]
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
        assert detail["mode"] == "0600"
        assert len(detail["sha256"]) == 64
    phase_manifest_path = lane.receipt_dir / evidence["files"]["phase_manifest"]["path"]
    phase_manifest = json.loads(phase_manifest_path.read_text(encoding="utf-8"))
    assert phase_manifest["contract_name"] == ("ea.memorial_release_evidence_phase.v1")
    assert phase_manifest["phase"] == "predeploy"
    assert phase_manifest["deployment_id"] == lane.deployment_id
    assert phase_manifest["source_revision"] == "b" * 40
    assert phase_manifest["candidate_image"]["image_id"] == runner.candidate_image
    assert len(phase_manifest["projection_sha256"]) == 64
    assert {
        item["path"] for item in phase_manifest["deployment_input_seal"]["forward"]
    } == {
        str(release_root / ".env"),
        str(release_root / ".env.local"),
        str(release_root / "docker-compose.yml"),
        str(release_root / deploy.MEMORIAL_COMPOSE_FILE),
    }
    assert len(evidence["deployment_input_sha256"]) == 64
    assert len(verified_snapshots) == 1
    assert set(verified_snapshots[0]) == {
        "deploy_context",
        "release_manifest",
        "release_authority_status",
        "memorial_operator_status",
        "project_modes",
    }
    for name in (
        "deploy_context",
        "release_manifest",
        "release_authority_status",
        "memorial_operator_status",
    ):
        assert hashlib.sha256(verified_snapshots[0][name]).hexdigest() == (
            evidence["files"][name]["sha256"]
        )
    project_modes_binding = evidence["verifier_inputs"]["project_modes"]
    assert project_modes_binding["path"] == (
        ".codex-design/product/PROJECT_MODES.generated.json"
    )
    assert hashlib.sha256(verified_snapshots[0]["project_modes"]).hexdigest() == (
        project_modes_binding["sha256"]
    )
    assert phase_manifest["verifier_inputs"] == evidence["verifier_inputs"]

    materializer_calls = [
        call
        for call in runner.calls
        if any("materialize_" in Path(item).name for item in call)
    ]
    assert len(materializer_calls) == 4
    assert all("--output" in call for call in materializer_calls)
    assert all(
        str(lane.receipt_dir / "memorial-release-001.evidence" / "predeploy")
        in call[call.index("--output") + 1]
        for call in materializer_calls
    )
    evidence_call_indexes = [runner.calls.index(call) for call in materializer_calls]
    assert not any(
        any(
            item.endswith(
                ("verify_release_authority.py", "verify_memorial_deploy_readiness.py")
            )
            for item in call
        )
        for call in runner.calls
    )
    assert all(
        "OPENAI_API_KEY" not in runner.call_envs[index]
        for index in evidence_call_indexes
    )
    manifest_index = runner.calls.index(materializer_calls[1])
    assert runner.call_envs[manifest_index]["EA_DEPLOY_CONTEXT_PATH"].endswith(
        "/predeploy/deploy-context.json"
    )


def test_memorial_operator_help_is_side_effect_free() -> None:
    output = (
        deploy.ROOT
        / ".codex-design"
        / "product"
        / "MEMORIAL_OPERATOR_STATUS.generated.json"
    )
    existed = output.exists()
    before = output.read_bytes() if existed else b""

    completed = subprocess.run(  # nosec B603 - fixed local script
        [
            "python3",
            str(deploy.ROOT / "scripts/materialize_memorial_operator_status.py"),
            "--help",
        ],
        cwd=deploy.ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert "--release-authority-status" in completed.stdout
    assert output.exists() is existed
    assert (output.read_bytes() if output.exists() else b"") == before


def test_clear_release_authority_projects_as_operator_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import materialize_memorial_operator_status as operator_status

    authority = tmp_path / "release-authority.json"
    authority.write_text(
        json.dumps(
            {
                "contract_name": "ea.release_authority_status.v1",
                "state": "clear",
                "authority_posture": "authoritative_runtime",
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(operator_status, "RELEASE_AUTHORITY_STATUS", authority)

    projected = operator_status._release_authority_status()

    assert projected["status"] == "pass"
    assert projected["state"] == "clear"


def test_readiness_verifier_uses_explicit_private_artifacts(tmp_path: Path) -> None:
    from scripts import verify_memorial_deploy_readiness as readiness

    memorial_status = tmp_path / "memorial-operator.json"
    release_authority = tmp_path / "release-authority.json"
    memorial_status.write_text(
        json.dumps(
            {
                "public_runtime_mode_detail": {
                    "status": "pass",
                    "reason": "memorial_runtime_declared",
                    "next_action": "maintain_memorial_public_runtime",
                    "project_mode": "MEMORIAL",
                    "enabled_project_modes": ["MEMORIAL"],
                }
            }
        ),
        encoding="utf-8",
    )
    release_authority.write_text(
        json.dumps(
            {
                "state": "clear",
                "authority_posture": "authoritative_runtime",
                "issues": [],
                "gate": {"status": "pass", "issues": []},
            }
        ),
        encoding="utf-8",
    )

    payload = readiness.build_payload(
        memorial_status_path=memorial_status,
        release_authority_status_path=release_authority,
    )

    assert payload["status"] == "pass"
    assert payload["memorial_operator_status_path"] == str(memorial_status)
    assert payload["release_authority_status_path"] == str(release_authority)


def test_release_snapshot_verifier_uses_canonical_logic_without_path_reopen(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    lane.release_evidence_verifier = None
    original_load_json = deploy.readiness_verifier._load_json
    original_release_authority_payload = (
        deploy.readiness_verifier._release_authority_payload
    )
    commit = "b" * 40

    def encoded(payload: Mapping[str, object]) -> bytes:
        return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")

    authority, readiness = lane._verify_release_evidence_snapshots(
        {
            "deploy_context": encoded({"contract_name": "ea.deploy_context.v1"}),
            "release_manifest": encoded(
                {
                    "contract_name": "ea.release_manifest.v1",
                    "repository": "EA",
                    "branch": "release/manfred",
                    "tracking_branch": "origin/main",
                    "commit_sha": commit,
                    "source_remote_ref": "refs/remotes/origin/main",
                    "source_remote_ref_commit_sha": commit,
                    "source_remote_ref_evidence": "local_remote_tracking_ref",
                    "source_commit_reachable_from_remote_ref": True,
                    "deployment_id": "memorial-release-001",
                    "deployment_id_source": "ea_deploy_id_env",
                    "public_origin": "https://memorial.example.org",
                    "public_origin_source": "EA_PUBLIC_ORIGIN",
                    "release_label": "memorial-release-001",
                    "deploy_context_generated_at": "2026-07-20T10:00:00Z",
                    "deploy_context_branch": "release/manfred",
                    "deploy_context_tracking_branch": "origin/main",
                    "deploy_context_commit_sha": commit,
                    "project_mode": "MEMORIAL",
                    "enabled_project_modes": ["MEMORIAL"],
                    "compose_files": ["docker-compose.yml"],
                    "artifact_set": ["memorial"],
                    "dirty_worktree": False,
                    "source_worktree_dirty": False,
                }
            ),
            "release_authority_status": encoded(
                {
                    "state": "clear",
                    "authority_posture": "authoritative_runtime",
                    "issues": [],
                    "gate": {"status": "pass", "issues": []},
                }
            ),
            "memorial_operator_status": encoded(
                {
                    "public_runtime_mode_detail": {
                        "status": "pass",
                        "reason": "memorial_runtime_declared",
                        "next_action": "maintain_memorial_public_runtime",
                        "project_mode": "MEMORIAL",
                        "enabled_project_modes": ["MEMORIAL"],
                    }
                }
            ),
            "project_modes": encoded({"modes": [{"key": "MEMORIAL"}]}),
        }
    )

    assert authority["status"] == "pass"
    assert authority["authority_posture"] == "authoritative_runtime"
    assert authority["commit_sha"] == commit
    assert readiness["status"] == "pass"
    assert deploy.readiness_verifier._load_json is original_load_json
    assert (
        deploy.readiness_verifier._release_authority_payload
        is original_release_authority_payload
    )


def test_release_manifest_cache_is_scoped_to_explicit_context_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import materialize_release_manifest as release_manifest

    first = tmp_path / "first-context.json"
    second = tmp_path / "second-context.json"
    first.write_text(
        json.dumps({"contract_name": "ea.deploy_context.v1", "deployment_id": "first"}),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {"contract_name": "ea.deploy_context.v1", "deployment_id": "second"}
        ),
        encoding="utf-8",
    )
    release_manifest._DEPLOY_CONTEXT_CACHE.clear()

    monkeypatch.setenv("EA_DEPLOY_CONTEXT_PATH", str(first))
    first_payload = release_manifest._deploy_context()
    monkeypatch.setenv("EA_DEPLOY_CONTEXT_PATH", str(second))
    second_payload = release_manifest._deploy_context()

    assert first_payload["deployment_id"] == "first"
    assert second_payload["deployment_id"] == "second"
    assert len(release_manifest._DEPLOY_CONTEXT_CACHE) == 2


def test_materializer_tracked_write_stops_evidence_before_next_script(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.materializer_tracked_write = (
        release_root / ".codex-studio" / "published" / "deploy_context.generated.json"
    )
    runner.tracked_status_after_materialization = (
        "1 .M N... 100644 100644 100644 deadbeef deadbeef "
        ".codex-studio/published/deploy_context.generated.json\0"
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    with pytest.raises(
        deploy.DeployError,
        match="^release_evidence_mutated_tracked_worktree$",
    ):
        lane.deploy(preflight_only=True)

    assert runner.materializer_call_count == 1
    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


def test_materializer_ignored_env_write_stops_before_next_script(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.materializer_tracked_write = release_root / ".env"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="^deployment_input_seal_changed:forward$",
    ):
        lane.deploy(preflight_only=True)

    assert runner.materializer_call_count == 1
    assert not any("up" in call for call in runner.calls)


def test_materializer_optional_env_creation_stops_before_next_script(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.materializer_tracked_write = release_root / ".env.local"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="^deployment_input_seal_changed:forward$",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert runner.materializer_call_count == 1
    assert not any("up" in call for call in runner.calls)


def test_nondefault_git_index_flags_fail_before_evidence(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.index_list = "S scripts/deploy_ea_memorial.py\0"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="^release_evidence_nondefault_index_flags$",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert runner.materializer_call_count == 0
    assert not any("up" in call for call in runner.calls)


def test_clean_head_switch_during_evidence_is_rejected(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.head_after_materialization = "e" * 40
    runner.head_tree_after_materialization = "f" * 40
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="^release_evidence_mutated_tracked_worktree$",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert runner.materializer_call_count == 1
    assert not any("up" in call for call in runner.calls)


def test_postdeploy_evidence_mutation_denies_unsealed_rollback_mutations(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.materializer_tracked_write = (
        release_root / ".codex-studio" / "published" / "deploy_context.generated.json"
    )
    runner.materializer_tracked_write_on_call = 5
    runner.tracked_status_after_materialization = (
        "1 .M N... 100644 100644 100644 deadbeef deadbeef "
        ".codex-studio/published/deploy_context.generated.json\0"
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match=(
            "deployment_and_rollback_failed:"
            "release_evidence_mutated_tracked_worktree:"
            "release_evidence_mutated_tracked_worktree"
        ),
    ):
        lane.deploy()

    assert runner.materializer_call_count == 5
    assert runner.api_mode == "forward"
    assert lane.receipt["status"] == "rollback_failed"
    assert len(_docker_mutation_calls(runner.calls)) == 4


def test_postdeploy_optional_env_creation_denies_unsealed_rollback_mutations(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    (prior_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(release_root, baseline_root=prior_root)
    runner.materializer_tracked_write = release_root / ".env.local"
    runner.materializer_tracked_write_on_call = 5
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match=(
            "deployment_and_rollback_failed:"
            "deployment_input_seal_changed:forward:"
            "deployment_input_seal_changed:forward"
        ),
    ):
        lane.deploy()

    assert runner.api_mode == "forward"
    assert lane.receipt["status"] == "rollback_failed"
    assert len(_docker_mutation_calls(runner.calls)) == 4
    assert not (prior_root / ".env.local").exists()


def test_postdeploy_authority_origin_drift_triggers_automatic_rollback(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.postdeploy_authority_public_origin = "https://other.example.org"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    lane.allowed_public_hosts = ("memorial.example.org", "other.example.org")

    with pytest.raises(
        deploy.DeployError,
        match=(
            "deployment_failed_rolled_back:release_authority_public_origin_mismatch"
        ),
    ):
        lane.deploy()

    assert runner.api_mode == "prior"
    assert lane.receipt["status"] == "failed_rolled_back"


def test_happy_path_mutates_only_redis_and_api(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert [
        check["boundary"]
        for check in receipt["checks"]
        if check.get("name") == "predeploy_release_context_revalidation"
    ] == [
        "before_protect_previous_image_tag",
        "before_stop_api_for_gemini_oauth",
        "before_gemini_oauth_install",
        "before_recreate_api_up",
    ]
    stop_calls = [
        call
        for call in runner.calls
        if "stop" in call and call[-1] == "ea-api"
    ]
    assert len(stop_calls) == 1
    assert "docker-compose.memorial.yml" not in " ".join(stop_calls[0])
    assert stop_calls[0][-4:] == ["stop", "--timeout", "30", "ea-api"]
    oauth_calls = [call for call in runner.calls if call[:2] == ["docker", "run"]]
    helper_container_name = oauth_calls[0][oauth_calls[0].index("--name") + 1]
    assert oauth_calls == [
        lane._expected_gemini_oauth_install_command(
            candidate_image_id=runner.candidate_image,
            runtime_root=(release_root / ".runtime" / "candidate-data"),
            container_name=helper_container_name,
        )
    ]
    assert len(helper_container_name) <= deploy.GEMINI_OAUTH_HELPER_NAME_MAX_CHARS
    assert re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", helper_container_name)
    assert "--interactive" in oauth_calls[0]
    assert oauth_calls[0][oauth_calls[0].index("--log-driver") + 1] == "none"
    assert oauth_calls[0][oauth_calls[0].index("--sig-proxy") + 1] == "true"
    assert oauth_calls[0][oauth_calls[0].index("--mount") + 1].endswith(
        "dst=/runtime"
    )
    oauth_call_index = runner.calls.index(oauth_calls[0])
    assert runner.calls.index(stop_calls[0]) < oauth_call_index
    assert set(runner.call_envs[oauth_call_index]) <= set(
        deploy.GEMINI_OAUTH_DOCKER_ENV_ALLOWLIST
    )
    assert runner.secret_stdin_observations == [
        {
            "sha256": hashlib.sha256(OAUTH_TEST_CREDENTIAL_BYTES).hexdigest(),
            "size_bytes": len(OAUTH_TEST_CREDENTIAL_BYTES),
        }
    ]
    oauth_binding = receipt["gemini_oauth_source_binding"]
    assert oauth_binding["source"]["sha256"] == hashlib.sha256(
        OAUTH_TEST_CREDENTIAL_BYTES
    ).hexdigest()
    assert oauth_binding["source"]["size_bytes"] == len(
        OAUTH_TEST_CREDENTIAL_BYTES
    )
    assert oauth_binding["runtime"]["api_target"] == deploy.GEMINI_OAUTH_API_TARGET
    assert receipt["predeploy_release_context_seal"]["preimage"][
        "gemini_oauth"
    ] == oauth_binding
    provisioning = receipt["gemini_oauth_provisioning"]
    assert provisioning["installed"] == {
        "schema": deploy.GEMINI_OAUTH_PROVISION_CONTRACT,
        "status": "provisioned",
        "sha256": hashlib.sha256(OAUTH_TEST_CREDENTIAL_BYTES).hexdigest(),
        "size_bytes": len(OAUTH_TEST_CREDENTIAL_BYTES),
        "uid": deploy.GEMINI_OAUTH_TARGET_UID,
        "gid": deploy.GEMINI_OAUTH_TARGET_UID,
        "mode": "0600",
    }
    assert provisioning["secret_transport"] == {
        "transport": "anonymous_stdin_pipe",
        "argv_contains_secret": False,
        "environment_contains_secret": False,
        "temporary_file_created": False,
    }
    runtime_exclusion = receipt["gemini_oauth_runtime_lock_exclusion"]
    assert runtime_exclusion["status"] == "initial_point_check_pass"
    assert runtime_exclusion["initial_api_stopped"] == {
        "status": "pass",
        "boundary": "after_api_stop_confirmation",
        "checked_at": runtime_exclusion["initial_api_stopped"]["checked_at"],
        "container_id": "container-ea-api",
        "image_id": runner.old_image,
        "running": False,
        "restarting": False,
    }
    assert runtime_exclusion["initial_api_stopped"]["checked_at"]
    assert runtime_exclusion["helper_invocation_state_at_initial_check"] == (
        "not_started"
    )
    assert runtime_exclusion["lock_protocol_compatibility_assumed"] is False
    assert runtime_exclusion["rollback_requires_confirmed_helper_exit"] is True
    assert runtime_exclusion["future_helper_requires_api_stop"] is True
    assert runtime_exclusion["continuous_absence_claimed"] is False
    assert "parallel_runtime_access_during_helper" not in runtime_exclusion
    point_checks = receipt["gemini_oauth_pre_run_point_checks"]
    assert point_checks["status"] == "pass"
    assert point_checks["release_context_guard_boundary"] == (
        "before_gemini_oauth_install"
    )
    assert point_checks["api_stopped"]["boundary"] == (
        "after_release_guard_before_helper_run"
    )
    assert point_checks["api_stopped"]["checked_at"]
    assert point_checks["helper_name_absence"]["boundary"] == (
        "after_release_guard_before_helper_run"
    )
    assert point_checks["helper_name_absence"]["checked_at"]
    assert point_checks["helper_invocation_state"] == "completed"
    assert point_checks["continuous_absence_claimed"] is False
    assert [
        evidence["boundary"]
        for evidence in receipt["gemini_oauth_helper_name_checks"]
    ] == ["before_api_stop", "after_release_guard_before_helper_run"]
    assert all(
        evidence["status"] == "pass"
        and evidence["exact_name_absent"] is True
        and evidence["checked_at"]
        for evidence in receipt["gemini_oauth_helper_name_checks"]
    )
    serialized_oauth_evidence = json.dumps(
        {
            "calls": runner.calls,
            "call_envs": runner.call_envs,
            "receipt": receipt,
        },
        sort_keys=True,
    )
    assert OAUTH_TEST_SECRET not in serialized_oauth_evidence
    assert str(deploy.GEMINI_OAUTH_SOURCE_PATH) not in serialized_oauth_evidence
    up_calls = [call for call in runner.calls if "up" in call]
    assert len(up_calls) == 1
    assert up_calls[0][-1] == "ea-api"
    assert "--no-deps" in up_calls[0]
    assert "--force-recreate" in up_calls[0]
    assert "docker-compose.memorial.yml" in " ".join(up_calls[0])
    assert "docker-compose.prod.yml" not in " ".join(up_calls[0])
    assert receipt["target_compose_files"] == [
        "docker-compose.yml",
        "docker-compose.memorial.yml",
    ]
    assert receipt["source_revision"] == "b" * 40
    assert receipt["candidate_image"] == {
        "reference": runner.candidate_reference,
        "image_id": runner.candidate_image,
    }
    memorial_probes = [
        probe for probe in receipt["probes"] if "/memorials/manfred" in probe["url"]
    ]
    assert len(memorial_probes) == 4
    assert {probe["source_revision"] for probe in memorial_probes} == {"b" * 40}
    config_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[-2:] == ["config", "--quiet"]
    )
    assert runner.call_envs[config_index]["EA_SOURCE_REVISION"] == "b" * 40
    assert (
        runner.call_envs[config_index]["EA_MEMORIAL_IMAGE"]
        == runner.candidate_reference
    )
    rendered_config_calls = [
        call
        for call in runner.calls
        if call[-3:] == ["config", "--format", "json"]
        and "docker-compose.memorial.yml" in " ".join(call)
    ]
    assert len(rendered_config_calls) == 3
    assert receipt["bind_source_access"]["snapshot_sha256"] == "5" * 64
    assert [
        check.get("boundary")
        for check in receipt["checks"]
        if check.get("name") == "memorial_bind_source_revalidation"
    ] == ["before_gemini_oauth_install", "before_recreate_api"]
    assert any(
        call[:2] == ["docker", "inspect"] and call[-1] == "ea-redis"
        for call in runner.calls
    )
    assert not any("build" in call for call in runner.calls)
    forbidden = {
        "ea-worker",
        "ea-scheduler",
        "ea-teable-relay",
        "ea-db",
        "ea-cloudflared",
    }
    assert not any(forbidden.intersection(call[-1:]) for call in up_calls)
    candidate_calls = [
        call
        for call in runner.calls
        if any(item.endswith("verify_manfred_memorial_candidate.py") for item in call)
    ]
    assert len(candidate_calls) == 2
    assert all("--browser-audit" in call for call in candidate_calls)
    assert "http://127.0.0.1:8090" in candidate_calls[0]
    assert "https://memorial.example.org" in candidate_calls[1]
    assert {item["origin"] for item in receipt["candidate_verifier"]} == {
        "local",
        "public",
    }
    assert all("base_url" not in item for item in receipt["candidate_verifier"])
    previous = receipt["previous_api"]
    assert "mount_identities" not in previous
    assert "mounts" not in previous
    assert len(previous["mount_identity_sha256"]) == 64
    rollback_render = receipt["rollback_render_preflight"]
    assert rollback_render["status"] == "pass"
    assert rollback_render["environment_sha256"] == previous["environment_sha256"]
    assert rollback_render["process_config_sha256"] == previous["process_config_sha256"]
    prior_render_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[-3:] == ["config", "--format", "json"]
        and "docker-compose.memorial.yml" not in " ".join(call)
    )
    assert not deploy.FORWARD_ONLY_ENV_KEYS.intersection(
        runner.call_envs[prior_render_index]
    )
    promotion = receipt["candidate_promotion_evidence"]
    assert promotion["path"] == lane.candidate_receipt_value
    assert len(promotion["sha256"]) == 64
    assert promotion["schema"] == "ea.manfred_memorial_candidate_runtime.v6"
    assert promotion["memorial_surface"] == "conversation_only"
    assert promotion["spatial_scope"] == "separate_propertyquarry_lane"
    assert promotion["spatial_receipt_consumed"] is False
    assert len(promotion["projection"]["projection_sha256"]) == 64
    assert len(promotion["live_ea"]["snapshot_sha256"]) == 64
    assert promotion["openapi"]["candidate_preserves_live_contract"] is False
    assert promotion["openapi"]["candidate_live_contract_claim_allowed"] is False
    assert (
        promotion["openapi"]["live_comparison_status"]
        == "deferred_to_governed_promotion"
    )
    assert promotion["openapi"]["candidate_public_openapi_retired"] is True
    assert promotion["openapi"]["compatibility_enforced_by"] == (
        "governed_postdeploy_internal_snapshot_with_rollback"
    )
    assert promotion["vexp_candidate_mutation_authority"][
        "mutation_sequence_exact"
    ] is True
    assert promotion["vexp_candidate_mutation_authority"][
        "mutation_count"
    ] == len(deploy.CANDIDATE_VEXP_MUTATION_SEQUENCE)
    assert promotion["browser"]["http_errors"] == 0
    assert promotion["runtime_identity"]["revision_agreement_verified"] is True
    assert promotion["execution_inputs"]["sealed"] is True
    assert promotion["runtime_posture"]["hardened"] is True
    assert promotion["registry_recovery"]["safe"] is True
    assert promotion["separate_spatial_plane"] == {
        "status": "not_in_memorial_scope",
        "owner": "PropertyQuarry",
        "scope": "separate_propertyquarry_lane",
        "receipt_consumed": False,
        "routes_tested": False,
    }
    public_spatial = receipt["public_spatial_tour"]
    assert public_spatial == {
        "status": "not_in_memorial_scope",
        "owner": "PropertyQuarry",
        "scope": "separate_propertyquarry_lane",
        "receipt_consumed": False,
        "requests_performed": 0,
    }
    assert "first_smoke_checks" not in promotion
    assert "second_smoke_checks" not in promotion
    assert "browser_surface" not in promotion
    assert "candidate_api_container_id" not in promotion
    assert "live_ea_project_before" not in promotion
    assert "live_ea_project_after" not in promotion
    predeploy_openapi = receipt["predeploy_non_memorial_controls"]["openapi"]
    postdeploy_openapi = receipt["postdeploy_non_memorial_controls"]["openapi"]
    assert predeploy_openapi["paths"] == sorted(runner.prior_openapi_paths)
    assert postdeploy_openapi["path_count"] == predeploy_openapi["path_count"] - 2
    assert postdeploy_openapi["added_path_count"] == 0
    assert postdeploy_openapi["retired_operations"] == list(
        deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
    )
    assert postdeploy_openapi["retired_operation_count"] == 2
    assert postdeploy_openapi["retirement_policy_exact_match"] is True
    assert postdeploy_openapi["changed_operation_count"] == 0
    assert postdeploy_openapi["missing_or_changed_schema_count"] == 0
    assert postdeploy_openapi["missing_or_changed_security_scheme_count"] == 0
    assert "_contract" not in predeploy_openapi
    assert "_contract" not in postdeploy_openapi


def test_gemini_oauth_helper_names_digest_full_long_deployment_identity(
    release_root: Path,
) -> None:
    lane = object.__new__(deploy.MemorialDeployLane)
    lane.root = release_root.resolve()
    context = {
        "authority": {"status": "pass", "identity": "authority-a"},
        "candidate": {"image_id": "sha256:" + "c" * 64},
        "predeploy_release_context_seal": {"sha256": "d" * 64},
    }
    deployment_ids = ["a" * 96 + "-one", "a" * 96 + "-two"]
    names: list[str] = []

    for deployment_id in deployment_ids:
        lane.deployment_id = deployment_id
        identity_sha256 = deploy._canonical_json_sha256(
            {
                "schema": deploy.GEMINI_OAUTH_HELPER_IDENTITY_SCHEMA,
                "deployment_id": deployment_id,
                "release_root": str(lane.root),
                "deployment_context": context,
            }
        )
        name = lane._gemini_oauth_helper_container_name(context)
        names.append(name)
        assert name == (
            "ea-memorial-oauth-"
            + deployment_id[: deploy.GEMINI_OAUTH_HELPER_NAME_READABLE_MAX_CHARS]
            + "-"
            + identity_sha256
        )
        assert len(name) == (
            len("ea-memorial-oauth-")
            + deploy.GEMINI_OAUTH_HELPER_NAME_READABLE_MAX_CHARS
            + 1
            + 64
        )
        assert len(name) <= deploy.GEMINI_OAUTH_HELPER_NAME_MAX_CHARS
        assert re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", name)

    assert deployment_ids[0][:96] == deployment_ids[1][:96]
    assert names[0][:-64] == names[1][:-64]
    assert names[0] != names[1]


def test_gemini_oauth_pre_stop_name_collision_never_stops_api(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.oauth_helper_name_present = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.GeminiOAuthHelperNameCollision,
        match="^gemini_oauth_helper_name_collision$",
    ):
        lane.deploy()

    assert len(runner.oauth_helper_name_queries) == 1
    assert runner.secret_stdin_observations == []
    assert runner.api_running is True
    assert not any(
        "stop" in call and call[-1] == "ea-api" for call in runner.calls
    )
    assert not any(call[:2] == ["docker", "run"] for call in runner.calls)
    assert not any(
        "up" in call and call[-1] == "ea-api" for call in runner.calls
    )
    assert lane.receipt["failure"]["type"] == (
        "GeminiOAuthHelperNameCollision"
    )
    assert lane.receipt["gemini_oauth_helper_name_checks"] == [
        {
            "status": "collision",
            "boundary": "before_api_stop",
            "checked_at": lane.receipt["gemini_oauth_helper_name_checks"][0][
                "checked_at"
            ],
            "container_name": runner.oauth_helper_name_queries[0],
            "exact_name_absent": False,
            "helper_invocation_state": "not_started",
        }
    ]


def test_gemini_oauth_post_guard_name_collision_never_runs_and_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_context_check = lane._require_predeploy_release_context_current

    def collide_after_helper_release_guard(
        expected: Mapping[str, object],
        *,
        boundary: str,
        deployment_input_seal: Mapping[
            str, Sequence[Mapping[str, object]]
        ],
    ) -> None:
        original_context_check(
            expected,
            boundary=boundary,
            deployment_input_seal=deployment_input_seal,
        )
        if boundary == "before_gemini_oauth_install":
            runner.oauth_helper_name_present = True

    monkeypatch.setattr(
        lane,
        "_require_predeploy_release_context_current",
        collide_after_helper_release_guard,
    )

    with pytest.raises(
        deploy.DeployError,
        match=(
            "^deployment_failed_rolled_back:"
            "gemini_oauth_helper_name_collision$"
        ),
    ):
        lane.deploy()

    assert len(runner.oauth_helper_name_queries) == 2
    assert runner.oauth_helper_name_queries[0] == runner.oauth_helper_name_queries[1]
    assert runner.secret_stdin_observations == []
    assert not any(call[:2] == ["docker", "run"] for call in runner.calls)
    assert len(
        [
            call
            for call in runner.calls
            if "stop" in call and call[-1] == "ea-api"
        ]
    ) == 1
    rollback_up_calls = [
        call for call in runner.calls if "up" in call and call[-1] == "ea-api"
    ]
    assert len(rollback_up_calls) == 1
    assert "docker-compose.memorial.yml" not in " ".join(rollback_up_calls[0])
    assert runner.api_running is True
    assert lane.receipt["failure"]["type"] == (
        "GeminiOAuthHelperNameCollision"
    )
    assert lane.receipt["status"] == "failed_rolled_back"
    assert lane.receipt["rollback"]["status"] == "pass"
    point_checks = lane.receipt["gemini_oauth_pre_run_point_checks"]
    assert point_checks["status"] == "fail"
    assert point_checks["api_stopped"]["status"] == "pass"
    assert point_checks["helper_name_absence"]["status"] == "collision"
    assert point_checks["helper_invocation_state"] == "not_started"
    assert point_checks["continuous_absence_claimed"] is False


@pytest.mark.parametrize(
    ("mutation", "missing_flag", "remove_count"),
    [
        ("wrong_image", "", 0),
        ("wrong_helper_arguments", "", 0),
        ("missing_flag", "--rm", 1),
        ("missing_flag", "--interactive", 1),
        ("missing_flag", "--name", 2),
        ("missing_flag", "--network", 2),
        ("missing_flag", "--user", 2),
        ("missing_flag", "--read-only", 1),
        ("missing_flag", "--pull", 2),
        ("missing_flag", "--log-driver", 2),
        ("missing_flag", "--cap-drop", 2),
        ("missing_flag", "--security-opt", 2),
        ("missing_flag", "--pids-limit", 2),
        ("missing_flag", "--sig-proxy", 2),
        ("missing_flag", "--mount", 2),
        ("missing_flag", "--entrypoint", 2),
    ],
)
def test_gemini_oauth_command_contract_denies_tampering_before_helper_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    missing_flag: str,
    remove_count: int,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_command = lane._gemini_oauth_install_command

    def tampered_command(
        *,
        candidate_image_id: str,
        runtime_root: Path,
        container_name: str,
    ) -> list[str]:
        command = original_command(
            candidate_image_id=candidate_image_id,
            runtime_root=runtime_root,
            container_name=container_name,
        )
        if mutation == "wrong_image":
            command[command.index(candidate_image_id)] = runner.old_image
        elif mutation == "wrong_helper_arguments":
            command[command.index("install")] = "inspect"
        else:
            index = command.index(missing_flag)
            del command[index : index + remove_count]
        return command

    monkeypatch.setattr(lane, "_gemini_oauth_install_command", tampered_command)

    with pytest.raises(
        deploy.DeployError,
        match="^gemini_oauth_provision_command_invalid$",
    ):
        lane.deploy()

    assert runner.secret_stdin_observations == []
    assert not any(call[:2] == ["docker", "run"] for call in runner.calls)
    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)
    assert _docker_mutation_calls(runner.calls) == [
        [
            "docker",
            "image",
            "tag",
            runner.old_image,
            deploy._safe_rollback_tag(lane.deployment_id),
        ]
    ]


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("sha256", "f" * 64),
        ("size_bytes", len(OAUTH_TEST_CREDENTIAL_BYTES) + 1),
        ("uid", deploy.GEMINI_OAUTH_TARGET_UID + 1),
        ("gid", deploy.GEMINI_OAUTH_TARGET_UID + 1),
        ("mode", "0640"),
        ("extra", True),
    ],
)
def test_gemini_oauth_helper_stdout_must_exactly_match_snapshot_and_target(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    wrong_value: object,
) -> None:
    runner = FakeRunner(release_root)
    receipt: dict[str, object] = {
        "schema": deploy.GEMINI_OAUTH_PROVISION_CONTRACT,
        "status": "provisioned",
        "sha256": hashlib.sha256(OAUTH_TEST_CREDENTIAL_BYTES).hexdigest(),
        "size_bytes": len(OAUTH_TEST_CREDENTIAL_BYTES),
        "uid": deploy.GEMINI_OAUTH_TARGET_UID,
        "gid": deploy.GEMINI_OAUTH_TARGET_UID,
        "mode": "0600",
    }
    receipt[field] = wrong_value
    runner.oauth_helper_stdout_override = deploy._canonical_guard_json_bytes(receipt)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match=(
            "^deployment_failed_rolled_back:"
            "gemini_oauth_provision_receipt_invalid$"
        ),
    ) as raised:
        lane.deploy()

    assert OAUTH_TEST_SECRET not in str(raised.value)
    assert len(runner.secret_stdin_observations) == 1
    api_up_calls = [
        call for call in runner.calls if "up" in call and call[-1] == "ea-api"
    ]
    assert len(api_up_calls) == 1
    assert "docker-compose.memorial.yml" not in " ".join(api_up_calls[0])
    serialized = lane.receipt_path.read_text(encoding="utf-8")
    assert OAUTH_TEST_SECRET not in serialized
    assert str(deploy.GEMINI_OAUTH_SOURCE_PATH) not in serialized


def test_gemini_oauth_helper_failure_redacts_child_output_and_aborts_api(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.oauth_helper_returncode = 2
    runner.oauth_helper_stdout_override = OAUTH_TEST_SECRET.encode("utf-8")
    runner.oauth_helper_stderr = f"helper-error:{OAUTH_TEST_SECRET}".encode("utf-8")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="^deployment_failed_rolled_back:gemini_oauth_provision_failed$",
    ) as raised:
        lane.deploy()

    assert str(raised.value) == (
        "deployment_failed_rolled_back:gemini_oauth_provision_failed"
    )
    assert OAUTH_TEST_SECRET not in str(raised.value)
    assert len(runner.secret_stdin_observations) == 1
    api_up_calls = [
        call for call in runner.calls if "up" in call and call[-1] == "ea-api"
    ]
    assert len(api_up_calls) == 1
    assert "docker-compose.memorial.yml" not in " ".join(api_up_calls[0])
    stop_index = next(
        index
        for index, call in enumerate(runner.calls)
        if "stop" in call and call[-1] == "ea-api"
    )
    helper_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[:2] == ["docker", "run"]
    )
    rollback_index = runner.calls.index(api_up_calls[0])
    assert stop_index < helper_index < rollback_index
    persisted = lane.receipt_path.read_text(encoding="utf-8")
    assert OAUTH_TEST_SECRET not in persisted
    assert "helper-error" not in persisted
    assert lane.receipt["preparation"]["api_mutation_started"] is True
    assert lane.receipt["rollback"]["status"] == "pass"
    assert runner.api_running is True


def test_gemini_oauth_api_restart_during_guard_never_runs_and_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_context_check = lane._require_predeploy_release_context_current

    def restart_during_helper_release_guard(
        expected: Mapping[str, object],
        *,
        boundary: str,
        deployment_input_seal: Mapping[
            str, Sequence[Mapping[str, object]]
        ],
    ) -> None:
        original_context_check(
            expected,
            boundary=boundary,
            deployment_input_seal=deployment_input_seal,
        )
        if boundary == "before_gemini_oauth_install":
            runner.api_running = True

    monkeypatch.setattr(
        lane,
        "_require_predeploy_release_context_current",
        restart_during_helper_release_guard,
    )

    with pytest.raises(
        deploy.DeployError,
        match=(
            "^deployment_failed_rolled_back:"
            "gemini_oauth_api_stop_not_confirmed$"
        ),
    ):
        lane.deploy()

    assert runner.secret_stdin_observations == []
    assert not any(call[:2] == ["docker", "run"] for call in runner.calls)
    assert len(runner.oauth_helper_name_queries) == 1
    assert any(
        check.get("name") == "predeploy_release_context_revalidation"
        and check.get("boundary") == "before_gemini_oauth_install"
        for check in lane.receipt["checks"]
    )
    point_checks = lane.receipt["gemini_oauth_pre_run_point_checks"]
    assert point_checks["status"] == "fail"
    assert point_checks["api_stopped"]["status"] == "fail"
    assert point_checks["api_stopped"]["running"] is True
    assert point_checks["helper_name_absence"] == {
        "status": "not_checked",
        "boundary": "after_release_guard_before_helper_run",
        "checked_at": None,
        "container_name": runner.oauth_helper_name_queries[0],
        "exact_name_absent": None,
        "helper_invocation_state": "not_started",
        "reason": "api_stopped_recheck_failed",
    }
    assert point_checks["helper_invocation_state"] == "not_started"
    assert point_checks["continuous_absence_claimed"] is False
    assert lane.receipt["status"] == "failed_rolled_back"
    assert lane.receipt["rollback"]["status"] == "pass"
    assert runner.api_running is True


def test_gemini_oauth_unconfirmed_helper_exit_forbids_api_rollback(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.oauth_helper_exit_unconfirmed = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_secret_run = runner.run_secret_stdin
    permit_path = lane._vexp_mutation_authority.mutation_permit_path

    def unconfirmed_and_revoke(*args: object, **kwargs: object) -> object:
        try:
            return original_secret_run(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            permit_path.unlink()

    runner.run_secret_stdin = unconfirmed_and_revoke  # type: ignore[method-assign]

    with pytest.raises(
        deploy.GeminiOAuthHelperExitUnconfirmed,
        match="^gemini_oauth_helper_exit_unconfirmed$",
    ):
        lane.deploy()

    assert len(runner.secret_stdin_observations) == 1
    assert runner.api_running is False
    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)
    assert lane.receipt["status"] == "rollback_denied_helper_exit_unconfirmed"
    assert lane.receipt["rollback"] == {
        "status": "denied",
        "reason": "gemini_oauth_helper_exit_unconfirmed",
    }
    assert lane.receipt["preparation"]["rollback_performed"] is False
    persisted = lane.receipt_path.read_text(encoding="utf-8")
    assert OAUTH_TEST_SECRET not in persisted


def test_gemini_oauth_source_change_after_install_denies_api_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.oauth_change_source_after_install = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match=(
            "^deployment_and_rollback_failed:gemini_oauth_source_changed:"
            "gemini_oauth_source_changed$"
        ),
    ):
        lane.deploy()

    assert len(runner.secret_stdin_observations) == 1
    assert any(call[:2] == ["docker", "run"] for call in runner.calls)
    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)
    assert lane.receipt["preparation"]["api_mutation_started"] is True
    assert lane.receipt["rollback"]["status"] == "fail"
    assert runner.api_running is False
    assert [
        check["boundary"]
        for check in lane.receipt["checks"]
        if check.get("name") == "predeploy_release_context_revalidation"
    ] == [
        "before_protect_previous_image_tag",
        "before_stop_api_for_gemini_oauth",
        "before_gemini_oauth_install",
    ]


def test_gemini_oauth_snapshot_failure_after_preflight_denies_first_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    original_preflight = lane.preflight

    def preflight_then_fail_snapshot() -> dict[str, object]:
        context = original_preflight()
        runner.oauth_snapshot_failure = True
        return context

    monkeypatch.setattr(lane, "preflight", preflight_then_fail_snapshot)

    with pytest.raises(
        deploy.DeployError,
        match="^gemini_oauth_source_snapshot_failed$",
    ):
        lane.deploy()

    assert _docker_mutation_calls(runner.calls) == []
    assert runner.secret_stdin_observations == []


def test_gemini_oauth_and_api_mutations_each_follow_exact_release_revalidation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    events: list[str] = []
    original_context_check = lane._require_predeploy_release_context_current
    original_command = lane._gemini_oauth_install_command
    original_provision = lane._provision_gemini_oauth
    original_api_stopped_evidence = lane._gemini_oauth_api_stopped_evidence
    original_helper_name_evidence = (
        lane._gemini_oauth_helper_name_absence_evidence
    )
    original_secret_run = runner.run_secret_stdin
    original_run = runner.run

    def tracked_command(
        *,
        candidate_image_id: str,
        runtime_root: Path,
        container_name: str,
    ) -> list[str]:
        command = original_command(
            candidate_image_id=candidate_image_id,
            runtime_root=runtime_root,
            container_name=container_name,
        )
        events.append("helper_argv_precomputed")
        return command

    def tracked_provision(
        *,
        candidate: Mapping[str, object],
        previous: Mapping[str, object],
        expected_binding: Mapping[str, object],
        command: Sequence[str],
        helper_container_name: str,
        runtime_root: Path,
        before_mutation: Callable[[str], None],
    ) -> None:
        assert list(command) == lane._expected_gemini_oauth_install_command(
            candidate_image_id=str(candidate["image_id"]),
            runtime_root=runtime_root,
            container_name=helper_container_name,
        )
        events.append("precomputed_argv_supplied")
        original_provision(
            candidate=candidate,
            previous=previous,
            expected_binding=expected_binding,
            command=command,
            helper_container_name=helper_container_name,
            runtime_root=runtime_root,
            before_mutation=before_mutation,
        )

    def tracked_api_stopped_evidence(
        previous: Mapping[str, object],
        *,
        boundary: str,
    ) -> dict[str, object]:
        evidence = original_api_stopped_evidence(previous, boundary=boundary)
        if boundary == "after_release_guard_before_helper_run":
            events.append("exact_old_api_stopped_recheck")
        return evidence

    def tracked_helper_name_evidence(
        container_name: str,
        *,
        boundary: str,
    ) -> dict[str, object]:
        evidence = original_helper_name_evidence(
            container_name,
            boundary=boundary,
        )
        events.append(f"exact_helper_name_absence:{boundary}")
        return evidence

    def tracked_context_check(
        expected: Mapping[str, object],
        *,
        boundary: str,
        deployment_input_seal: Mapping[
            str, Sequence[Mapping[str, object]]
        ],
    ) -> None:
        original_context_check(
            expected,
            boundary=boundary,
            deployment_input_seal=deployment_input_seal,
        )
        events.append(f"release_context:{boundary}")

    def tracked_secret_run(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        write_stdin: Callable[[BinaryIO], None],
        timeout_seconds: float,
        container_name: str,
        max_output_bytes: int,
    ) -> subprocess.CompletedProcess[bytes]:
        events.append("oauth_mutation")
        return original_secret_run(
            args,
            cwd=cwd,
            env=env,
            write_stdin=write_stdin,
            timeout_seconds=timeout_seconds,
            container_name=container_name,
            max_output_bytes=max_output_bytes,
        )

    def tracked_run(
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        if "stop" in argv and argv[-1] == "ea-api":
            events.append("api_stop_mutation")
        elif "up" in argv and argv[-1] == "ea-api":
            events.append("api_mutation")
        return original_run(args, cwd=cwd, env=env, check=check)

    monkeypatch.setattr(
        lane,
        "_require_predeploy_release_context_current",
        tracked_context_check,
    )
    monkeypatch.setattr(lane, "_gemini_oauth_install_command", tracked_command)
    monkeypatch.setattr(lane, "_provision_gemini_oauth", tracked_provision)
    monkeypatch.setattr(
        lane,
        "_gemini_oauth_api_stopped_evidence",
        tracked_api_stopped_evidence,
    )
    monkeypatch.setattr(
        lane,
        "_gemini_oauth_helper_name_absence_evidence",
        tracked_helper_name_evidence,
    )
    runner.run_secret_stdin = tracked_secret_run  # type: ignore[method-assign]
    runner.run = tracked_run  # type: ignore[method-assign]

    receipt = lane.deploy()

    assert events.index("helper_argv_precomputed") < events.index(
        "exact_helper_name_absence:before_api_stop"
    )
    assert events.index("exact_helper_name_absence:before_api_stop") < (
        events.index("api_stop_mutation")
    )
    pre_run_index = events.index("precomputed_argv_supplied")
    assert events[pre_run_index : pre_run_index + 5] == [
        "precomputed_argv_supplied",
        "release_context:before_gemini_oauth_install",
        "exact_old_api_stopped_recheck",
        "exact_helper_name_absence:after_release_guard_before_helper_run",
        "oauth_mutation",
    ]

    assert [
        event
        for event in events
        if event
        in {
            "release_context:before_stop_api_for_gemini_oauth",
            "api_stop_mutation",
            "release_context:before_gemini_oauth_install",
            "oauth_mutation",
            "release_context:before_recreate_api_up",
            "api_mutation",
        }
    ] == [
        "release_context:before_stop_api_for_gemini_oauth",
        "api_stop_mutation",
        "release_context:before_gemini_oauth_install",
        "oauth_mutation",
        "release_context:before_recreate_api_up",
        "api_mutation",
    ]
    point_checks = receipt["gemini_oauth_pre_run_point_checks"]
    assert point_checks["status"] == "pass"
    assert point_checks["api_stopped"]["status"] == "pass"
    assert point_checks["api_stopped"]["checked_at"]
    assert point_checks["helper_name_absence"]["status"] == "pass"
    assert point_checks["helper_name_absence"]["checked_at"]
    assert point_checks["helper_invocation_state"] == "completed"
    assert point_checks["continuous_absence_claimed"] is False
    assert "parallel_runtime_access_during_helper" not in json.dumps(
        receipt,
        sort_keys=True,
    )


def test_candidate_promotion_receipt_is_explicit_private_and_non_symlink(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    missing = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-missing-candidate",
    )
    missing.candidate_receipt_value = ""
    with pytest.raises(
        deploy.DeployError, match="explicit_memorial_candidate_receipt_required"
    ):
        missing.deploy(preflight_only=True)

    insecure = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-insecure-candidate",
    )
    Path(insecure.candidate_receipt_value).chmod(0o644)
    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_receipt_permissions_invalid",
    ):
        insecure.deploy(preflight_only=True)

    symlinked = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-symlink-candidate",
    )
    target = Path(symlinked.candidate_receipt_value)
    link = target.with_name("candidate-runtime-link.json")
    link.symlink_to(target)
    symlinked.candidate_receipt_value = str(link)
    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_receipt_path_invalid"
    ):
        symlinked.deploy(preflight_only=True)

    hardlinked = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-hardlink-candidate",
    )
    original = Path(hardlinked.candidate_receipt_value)
    hardlink = original.with_name("candidate-runtime-hardlink.json")
    hardlink.hardlink_to(original)
    hardlinked.candidate_receipt_value = str(hardlink)
    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_receipt_permissions_invalid",
    ):
        hardlinked.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"status":"pass","status":"pass"}\n',
        b'{"status":NaN}\n',
        b'{"status":Infinity}\n',
    ],
)
def test_candidate_promotion_receipt_rejects_ambiguous_json(
    release_root: Path,
    raw: bytes,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    path.write_bytes(raw)
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_receipt_json_invalid",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image_id", "sha256:" + "d" * 64),
        ("schema", "ea.manfred_memorial_candidate_runtime.v3"),
        ("runtime_source_revision", "a" * 40),
        ("compose_uses_immutable_image_id", False),
        ("image_locator_evidence", {}),
        ("image_locator_evidence.consumed_by_compose", True),
        ("projection_commit", "a" * 40),
        ("prepared_image_id", "sha256:" + "d" * 64),
        ("projection_sha256", "not-a-digest"),
        ("projection_file_count", 1),
        ("compose_project_isolated", False),
        ("candidate_preflight.containers", 1),
        ("projection_tree_revalidated", False),
        ("locks", {}),
        ("locks.fleet.exclusive", False),
        ("project_lock", {}),
        ("port_lock", {}),
        ("candidate_container_images", {}),
        (
            "candidate_container_images_initial.api.image_id",
            "sha256:" + "d" * 64,
        ),
        (
            "candidate_container_images_final.gateway.container_id",
            "3" * 64,
        ),
        ("candidate_container_image_identity_stable", False),
        ("runtime_projection_initial.projection_sha256", "e" * 64),
        ("runtime_projection_final.file_count", 1),
        ("runtime_projection_identity_stable", False),
        ("runtime_version_identity.body_commit_sha", "a" * 40),
        (
            "runtime_version_identity.release_authority_posture",
            "advisory_only",
        ),
        ("runtime_authority_commit", "a" * 40),
        ("compose_attestation.canonical_source_path", "relative/compose.yml"),
        ("compose_attestation.git_blob_oid", "4" * 40),
        ("compose_attestation.sha256", "f" * 64),
        ("compose_attestation.candidate_commit", "a" * 40),
        (
            "execution_inputs.schema",
            "ea.manfred_candidate_execution_inputs.v0",
        ),
        ("execution_inputs.environment_sha256", "not-a-digest"),
        ("execution_inputs.compose_image_id", "sha256:" + "d" * 64),
        ("execution_inputs.mutable_image_locator_consumed_by_compose", True),
        ("runtime_api_posture.image_id", "sha256:" + "d" * 64),
        ("runtime_api_posture.mounts_exact", False),
        ("runtime_api_posture.read_only_rootfs", False),
        ("runtime_api_posture.ingress_attached", True),
        ("registry_recovery.state_before_launch", "registered_receipt"),
        ("registry_recovery.existing_receipt_resumed", True),
        ("memorial_surface", "conversation_plus_spatial"),
        ("spatial_scope", "embedded_memorial_tour"),
        ("public_property_tours_packaged", True),
        ("public_property_tours_tested", True),
        ("memorial_spatial_receipt_generated", True),
        ("spatial_handoff", {}),
        ("spatial_handoff_runtime", {}),
        ("candidate_api_container_id", "different-container"),
        ("openapi_contract.retirement_policy_id", "mutable-policy"),
        ("openapi_contract.retirement_allowed_operations", []),
        ("openapi_contract.retired_operations", []),
        ("openapi_contract.retired_operation_count", 1),
        ("openapi_contract.retirement_policy_exact_match", False),
        (
            "openapi_contract.compatible_evolution_policy_id",
            "mutable-policy",
        ),
        ("openapi_contract.compatible_evolution_allowed_operations", []),
        ("openapi_contract.compatible_evolved_operation_count", 2),
        ("openapi_contract.compatible_evolution_policy_exact_match", False),
        ("openapi_contract.candidate_preserves_live_contract", True),
        ("openapi_contract.candidate_live_contract_claim_allowed", True),
        ("openapi_contract.live_comparison_status", "claimed_locally"),
        (
            "openapi_contract.candidate.snapshot_source",
            "public_http_openapi",
        ),
        ("openapi_contract.candidate_public_endpoint.status", 200),
        (
            "openapi_contract.candidate_public_endpoint."
            "security_headers.x_frame_options",
            "SAMEORIGIN",
        ),
        ("live_ea_project_after", {}),
        ("live_ea_api_unchanged", False),
        ("provider_calls_performed", True),
        ("release_root", "/different/memorial-data"),
        (
            "first_smoke_checks",
            [
                "singular_memorial_alias",
                "source_grounded_narrator_boundary",
                "voice_provider_boundary_blocked",
            ],
        ),
        (
            "second_smoke_checks",
            [
                "singular_memorial_alias",
                "source_grounded_narrator_boundary",
                "voice_provider_boundary_blocked",
            ],
        ),
        ("browser_surface.http_errors", 1),
        ("browser_surface.failed_requests", None),
    ],
)
def test_candidate_promotion_receipt_contract_mismatch_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    path_parts = field.split(".")
    target = payload
    for part in path_parts[:-1]:
        target = target[part]
    if value is None:
        target.pop(path_parts[-1])
    else:
        target[path_parts[-1]] = value
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_receipt_contract_invalid"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", "2026-07-20T10:30:00Z"),
        ("vexp_candidate_mutation_authority", None),
        (
            "vexp_candidate_mutation_authority.cleanup_requires_positive_authority",
            False,
        ),
        ("vexp_candidate_mutation_authority.entry.phase", "pre_mutation"),
        ("vexp_candidate_mutation_authority.entry.boundary", "candidate_entry_alt"),
        ("vexp_candidate_mutation_authority.entry.permit_sha256", "a" * 64),
        (
            "vexp_candidate_mutation_authority.finalization.boundary",
            "candidate_entry",
        ),
    ],
)
def test_candidate_vexp_authority_envelope_is_required_before_promotion(
    release_root: Path,
    field: str,
    value: object,
) -> None:
    lane = _lane(release_root, FakeRunner(release_root))
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    target = payload
    parts = field.split(".")
    for part in parts[:-1]:
        target = target[part]
    if value is None:
        target.pop(parts[-1])
    else:
        target[parts[-1]] = value
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_vexp_authority_invalid"
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": lane.memorial_image_reference,
                "image_id": "sha256:" + "c" * 64,
            },
            source_revision="b" * 40,
        )


def test_candidate_vexp_mutation_sequence_cannot_be_reordered(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutations = payload["vexp_candidate_mutation_authority"]["mutations"]
    mutations[0], mutations[7] = mutations[7], mutations[0]
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_vexp_authority_invalid"
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


def test_candidate_vexp_authority_must_bind_current_terminal_certificate(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    authority = payload["vexp_candidate_mutation_authority"]
    rows = [authority["entry"], *authority["mutations"], authority["finalization"]]
    for row in rows:
        row["qualification_certificate_sha256"] = "a" * 64
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_vexp_authority_invalid"
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


def test_candidate_finalization_status_requires_exact_committed_record(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    state, _state_sha256 = lane._read_trusted_vexp_sentinel_state()
    receipt_path = Path(lane.candidate_receipt_value).resolve()
    candidate_receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    candidate_authority = {
        "historical_candidate_permit_sha256": "7" * 64,
        "epoch_started_ms": state["epoch_started_ms"],
        "qualification_certificate_sha256": (
            runner.candidate_seal_certificate_sha256
        ),
        "terminal_identity_sha256": deploy._vexp_terminal_identity_sha256(state),
    }
    image_authority = {
        "receipt_sha256": "6" * 64,
        "historical_image_build_permit_sha256": (
            runner.candidate_seal_image_build_permit_sha256
        ),
    }

    seal = lane._validate_candidate_finalization_seal(
        candidate_receipt_path=receipt_path,
        candidate_receipt_sha256=candidate_receipt_sha256,
        candidate_vexp_authority=candidate_authority,
        candidate_image_build_authority=image_authority,
    )
    assert seal["commit"] == {
        "contract_name": deploy.VEXP_CANDIDATE_FINALIZATION_COMMIT_CONTRACT_NAME,
        "version": deploy.VEXP_CANDIDATE_FINALIZATION_COMMIT_VERSION,
        "status": "committed",
        "sha256": "f" * 64,
    }

    forged = dict(seal)
    forged["commit"] = dict(seal["commit"])
    forged["commit"]["status"] = "provisional"
    runner.candidate_seal_stdout_override = json.dumps(forged, sort_keys=True) + "\n"
    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_finalization_seal_invalid",
    ):
        lane._validate_candidate_finalization_seal(
            candidate_receipt_path=receipt_path,
            candidate_receipt_sha256=candidate_receipt_sha256,
            candidate_vexp_authority=candidate_authority,
            candidate_image_build_authority=image_authority,
        )


def test_candidate_finalization_seal_uses_fixed_manager_and_exact_bindings(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    receipt_path = Path(lane.candidate_receipt_value).resolve()
    receipt_raw = receipt_path.read_bytes()
    receipt_payload = json.loads(receipt_raw)

    evidence = lane._validate_candidate_promotion_receipt(
        candidate={
            "reference": runner.candidate_reference,
            "image_id": runner.candidate_image,
        },
        source_revision="b" * 40,
    )

    binding = receipt_payload["image_build_authority_binding"]
    expected_call = [
        str(deploy.TRUSTED_VEXP_PERMIT_MANAGER_PYTHON),
        "-I",
        str(deploy.TRUSTED_VEXP_PERMIT_MANAGER),
        "candidate-seal-status",
        "--candidate-permit-sha256",
        "8" * 64,
        "--candidate-receipt",
        str(receipt_path),
        "--candidate-receipt-sha256",
        hashlib.sha256(receipt_raw).hexdigest(),
        "--image-build-receipt-sha256",
        binding["receipt_sha256"],
    ]
    call_index = runner.calls.index(expected_call)
    assert runner.call_envs[call_index] == {}
    seal = evidence["candidate_finalization_seal"]
    assert set(seal) == deploy.VEXP_CANDIDATE_FINALIZATION_STATUS_KEYS
    assert seal["status"] == "valid"
    assert seal["candidate_receipt_path"] == str(receipt_path)
    assert seal["candidate_receipt_sha256"] == hashlib.sha256(
        receipt_raw
    ).hexdigest()
    assert seal["image_build_receipt_sha256"] == binding["receipt_sha256"]
    assert seal["image_build_permit_sha256"] == "8" * 64
    assert lane._candidate_finalization_authority_identity == (
        runner.candidate_seal_epoch_started_ms,
        runner.candidate_seal_certificate_sha256,
    )


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (2, "permit_error:vexp_candidate_finalization_record_unavailable\n"),
        (2, "/usr/bin/python3: can't open file 'manager'\n"),
    ],
    ids=["seal-missing", "manager-missing"],
)
def test_candidate_finalization_seal_or_manager_missing_fails_closed(
    release_root: Path,
    returncode: int,
    stderr: str,
) -> None:
    runner = FakeRunner(release_root)
    runner.candidate_seal_returncode = returncode
    runner.candidate_seal_stderr = stderr
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_finalization_seal_invalid",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


@pytest.mark.parametrize(
    "malformed",
    [
        "not-json\n",
        "{}\ntrailing-output\n",
        '{"status":"valid","status":"valid"}\n',
        '{"status":NaN}\n',
    ],
)
def test_candidate_finalization_seal_malformed_output_fails_closed(
    release_root: Path,
    malformed: str,
) -> None:
    runner = FakeRunner(release_root)
    runner.candidate_seal_stdout_override = malformed
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_finalization_seal_invalid",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "sealed"),
        ("contract_name", "ea.vexp_candidate_finalization.v0"),
        ("version", True),
        ("path", "/var/lib/vexp-manfred-candidate-authority/wrong.json"),
        ("sha256", "not-a-digest"),
        ("sha256", int("1" * 64)),
        ("candidate_permit_sha256", "1" * 64),
        ("candidate_receipt_path", "/tmp/forged-candidate.json"),
        ("candidate_receipt_sha256", "2" * 64),
        ("image_build_receipt_sha256", "3" * 64),
        ("image_build_permit_sha256", "4" * 64),
        ("epoch_started_ms", 1),
        ("qualification_certificate_sha256", "5" * 64),
    ],
)
def test_candidate_finalization_seal_forged_binding_fails_closed(
    release_root: Path,
    field: str,
    value: object,
) -> None:
    runner = FakeRunner(release_root)
    runner.candidate_seal_overrides[field] = value
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_finalization_seal_invalid",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


def test_candidate_finalization_seal_rejects_extra_output_fields(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    runner.candidate_seal_extra_fields["untrusted"] = "forged"
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_finalization_seal_invalid",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )


def test_invalid_candidate_never_invokes_root_seal_manager(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema"] = "ea.manfred_memorial_candidate_runtime.v4"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_receipt_contract_invalid",
    ):
        lane._validate_candidate_promotion_receipt(
            candidate={
                "reference": runner.candidate_reference,
                "image_id": runner.candidate_image,
            },
            source_revision="b" * 40,
        )
    assert not any(
        call[:4]
        == [
            str(deploy.TRUSTED_VEXP_PERMIT_MANAGER_PYTHON),
            "-I",
            str(deploy.TRUSTED_VEXP_PERMIT_MANAGER),
            "candidate-seal-status",
        ]
        for call in runner.calls
    )


def test_api_authority_must_stay_bound_to_candidate_finalization_epoch(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner)
    lane._validate_candidate_promotion_receipt(
        candidate={
            "reference": runner.candidate_reference,
            "image_id": runner.candidate_image,
        },
        source_revision="b" * 40,
    )
    lane._candidate_finalization_authority_identity = (1, "f" * 64)

    with pytest.raises(
        deploy.DeployError,
        match="vexp_candidate_finalization_authority_changed",
    ):
        lane._require_vexp_mutation_permitted("before_ensure_redis")


def test_candidate_openapi_evidence_rejects_extra_unbounded_fields(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["openapi_contract"]["candidate"]["raw_contract"] = {
        "unexpected": "content"
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_receipt_contract_invalid"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_postdeploy_openapi_uses_retired_internal_container_snapshot(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _lane(release_root, FakeRunner(release_root))
    assert lane.internal_openapi_snapshot is not None
    envelope = dict(lane.internal_openapi_snapshot())
    observed: list[list[str]] = []

    def fake_run(args, **_kwargs):  # type: ignore[no-untyped-def]
        observed.append(list(args))
        return _completed(args, stdout=json.dumps(envelope))

    lane.internal_openapi_snapshot = None
    monkeypatch.setattr(lane, "_run", fake_run)

    control = lane._capture_internal_openapi_control()

    assert observed == [
        [
            "/usr/bin/timeout",
            "--signal=KILL",
            "30s",
            "docker",
            "exec",
            "ea-api",
            "python3",
            "-c",
            deploy.CONTAINER_OPENAPI_SNAPSHOT_SCRIPT,
        ]
    ]
    assert control["operation_count"] > 0
    assert control["probe"]["source"] == "deployed_api_container_app.openapi"
    assert control["probe"]["public_docs_config_retired"] is True


def test_postdeploy_internal_openapi_rejects_exposed_docs(release_root: Path) -> None:
    lane = _lane(release_root, FakeRunner(release_root))
    assert lane.internal_openapi_snapshot is not None
    envelope = dict(lane.internal_openapi_snapshot())
    envelope["docs_url"] = "/docs"
    lane.internal_openapi_snapshot = lambda: envelope

    with pytest.raises(
        deploy.DeployError,
        match="deployed_api_internal_openapi_snapshot_invalid",
    ):
        lane._capture_internal_openapi_control()


def test_deploy_openapi_canonicalizer_matches_candidate_producer() -> None:
    from scripts import run_manfred_memorial_candidate as candidate

    presentation_named_properties = (
        "description",
        "title",
        "summary",
        "tags",
        "examples",
    )
    document: dict[str, object] = {
        "openapi": "3.1.0",
        "security": [{"ApiToken": []}],
        "paths": {
            "/control/{control_id}": {
                "parameters": [
                    {
                        "name": "control_id",
                        "in": "path",
                        "required": True,
                        "description": "stable path parameter",
                        "schema": {"type": "string"},
                    }
                ],
                "get": {
                    "summary": "presentation field outside the contract projection",
                    "tags": ["control"],
                    "parameters": [
                        {
                            "name": "mode",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "examples": ["safe"],
                            },
                        }
                    ],
                    "requestBody": {
                        "description": "stable request description",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Control"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "stable response description",
                            "headers": {
                                "X-Control": {
                                    "description": "stable response header",
                                    "schema": {"type": "string"},
                                }
                            },
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Control"}
                                }
                            },
                        }
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "Control": {
                    "type": "object",
                    "title": "Control schema",
                    "properties": {
                        name: {"type": "string", "title": f"{name} field"}
                        for name in presentation_named_properties
                    },
                }
            },
            "securitySchemes": {
                "ApiToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-EA-API-Token",
                    "description": "stable security description",
                }
            },
        },
    }

    deploy_contract = deploy._canonical_openapi_contract(document)
    candidate_contract = candidate._canonical_openapi_contract(document)

    assert deploy_contract == candidate_contract
    operation = deploy_contract["operations"]["GET /control/{control_id}"]
    assert set(operation) == {"security", "parameters", "requestBody", "responses"}
    assert operation["responses"]["200"]["description"] == (
        "stable response description"
    )
    assert set(deploy_contract["schemas"]["Control"]["properties"]) == set(
        presentation_named_properties
    )


def test_openapi_operation_outside_exact_retirement_rolls_back(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_paths = ["/health", "/memorials/{slug}"]
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert (
        "postdeploy_openapi_operation_retirement_mismatch"
        in receipt["failure"]["reason"]
    )
    assert receipt["rollback"]["status"] == "pass"


def test_openapi_partial_safety_retirement_rolls_back(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    retained_retirement_path = deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS[0].split(
        " ", 1
    )[1]
    runner.forward_openapi_paths.append(retained_retirement_path)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert (
        "postdeploy_openapi_operation_retirement_mismatch"
        in receipt["failure"]["reason"]
    )
    assert receipt["rollback"]["status"] == "pass"


def test_predeploy_requires_both_safety_retirement_operations(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    missing_path = deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS[0].split(" ", 1)[1]
    runner.prior_openapi_paths.remove(missing_path)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="predeploy_openapi_retirement_operations_missing",
    ):
        lane.deploy()

    assert not any("up" in call for call in runner.calls)


def test_openapi_retirement_is_idempotent_for_governed_update(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.prior_openapi_paths = list(runner.forward_openapi_paths)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy()

    assert receipt["status"] == "pass"
    predeploy = receipt["predeploy_non_memorial_controls"]["openapi"]
    postdeploy = receipt["postdeploy_non_memorial_controls"]["openapi"]
    assert predeploy["retirement_state"] == "applied"
    assert postdeploy["retired_operations"] == []
    assert postdeploy["retired_operation_count"] == 0
    assert postdeploy["retirement_policy_exact_match"] is True


def test_openapi_changed_retained_operation_has_no_waiver(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_changed_operation = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_openapi_operation_changed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_openapi_exact_version_boolean_evolution_is_compatible(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.prior_openapi_paths.append("/version")
    runner.forward_openapi_paths.append("/version")
    runner.forward_version_compatible_evolution = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy()

    openapi = receipt["postdeploy_non_memorial_controls"]["openapi"]
    assert openapi["compatible_evolution_policy_id"] == (
        deploy.OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
    )
    assert openapi["compatible_evolved_operations"] == ["GET /version"]
    assert openapi["compatible_evolved_operation_count"] == 1
    assert openapi["compatible_evolution_policy_exact_match"] is True


def test_openapi_schema_change_has_no_waiver(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_schema_type = "string"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_openapi_schema_regression" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


@pytest.mark.parametrize(
    "property_name",
    ["description", "title", "summary", "tags", "examples"],
)
def test_openapi_presentation_named_schema_property_change_has_no_waiver(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    property_name: str,
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_property_types[property_name] = "integer"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_openapi_schema_regression" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_openapi_response_description_change_has_no_waiver(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_response_description = "changed response description"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_openapi_operation_changed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_openapi_security_change_has_no_waiver(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_security_header = "X-Changed-Token"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_openapi_security_regression" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_propertyquarry_control_tour_is_not_captured_by_scoped_memorial_lane(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_tour_json = (
        b'{\n  "title": "Control tour",\n  "slug": "control-tour"\n}\n'
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(
        release_root,
        runner,
        control_tour_slug=deploy.REQUIRED_CONTROL_TOUR_SLUG,
    ).deploy()

    assert "tour" not in receipt["predeploy_non_memorial_controls"]
    assert "tour" not in receipt["postdeploy_non_memorial_controls"]
    assert receipt["public_spatial_tour"] == {
        "status": "not_in_memorial_scope",
        "owner": "PropertyQuarry",
        "scope": "separate_propertyquarry_lane",
        "receipt_consumed": False,
        "requests_performed": 0,
    }


def test_propertyquarry_tour_json_drift_does_not_block_scoped_memorial(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_tour_json = b'{"slug":"control-tour","title":"changed"}'
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(
        release_root,
        runner,
        control_tour_slug=deploy.REQUIRED_CONTROL_TOUR_SLUG,
    )

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert "tour" not in receipt["predeploy_non_memorial_controls"]
    assert "tour" not in receipt["postdeploy_non_memorial_controls"]


def test_propertyquarry_viewer_evolution_has_no_scoped_memorial_policy(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    payload = json.loads(SAFE_TOUR)
    slug = deploy.REQUIRED_CONTROL_TOUR_SLUG
    payload["generated_viewer"] = {
        "disclosure": deploy.CONTROL_TOUR_GENERATED_VIEWER_DISCLOSURE,
        "release_revision": f"property-3d-{deploy.PROPERTY_ARTIFACT_COMMIT[:12]}",
        "synthetic": True,
        "url": (f"/tours/viewer/{slug}/generated-reconstruction/viewer.html"),
        "verified_provider_capture": False,
    }
    runner.forward_tour_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(
        release_root,
        runner,
        control_tour_slug=slug,
    ).deploy()

    assert receipt["status"] == "pass"
    assert "tour" not in receipt["postdeploy_non_memorial_controls"]
    assert receipt["candidate_promotion_evidence"]["separate_spatial_plane"] == {
        "status": "not_in_memorial_scope",
        "owner": "PropertyQuarry",
        "scope": "separate_propertyquarry_lane",
        "receipt_consumed": False,
        "routes_tested": False,
    }


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("forward_image_id", "sha256:" + "d" * 64, "deployed_api_image_mismatch"),
        ("forward_project", "other", "deployed_api_project_mismatch"),
        ("forward_service", "other-api", "deployed_api_service_mismatch"),
        ("forward_source_mounts", False, "deployed_api_source_mounts_mismatch"),
        ("forward_extra_mount", True, "deployed_api_source_mounts_mismatch"),
    ],
)
def test_forward_api_identity_mismatch_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: object,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    setattr(runner, attribute, value)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert reason in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_missing_redis_is_created_without_touching_other_dependencies(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, redis_present=False)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy()

    up_calls = [call for call in runner.calls if "up" in call]
    assert [call[-1] for call in up_calls] == ["ea-redis", "ea-api"]
    assert receipt["status"] == "pass"
    assert [
        check["boundary"]
        for check in receipt["checks"]
        if check.get("name") == "predeploy_release_context_revalidation"
    ] == [
        "before_redis_create",
        "before_protect_previous_image_tag",
        "before_stop_api_for_gemini_oauth",
        "before_gemini_oauth_install",
        "before_recreate_api_up",
    ]


def test_stopped_redis_is_started_without_compose_reconfiguration(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, redis_running=False, redis_health="unhealthy")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    _lane(release_root, runner).deploy()

    assert ["docker", "start", "ea-redis"] in runner.calls
    assert not any("up" in call and call[-1] == "ea-redis" for call in runner.calls)


def test_running_unhealthy_redis_is_never_reconfigured(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, redis_health="unhealthy")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match="container_not_ready:ea-redis"):
        _lane(release_root, runner).deploy()

    assert not any("up" in call for call in runner.calls)
    assert ["docker", "start", "ea-redis"] not in runner.calls


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"redis_project": "other"}, "redis_project_mismatch"),
        ({"redis_service": "other-redis"}, "redis_service_mismatch"),
    ],
)
def test_existing_redis_requires_exact_compose_identity_before_trust_or_start(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    reason: str,
) -> None:
    runner = FakeRunner(release_root, **kwargs)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy()

    assert not any("up" in call for call in runner.calls)
    assert ["docker", "start", "ea-redis"] not in runner.calls


def test_unrestorable_baseline_fails_before_redis_or_api_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, baseline_files=())
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError, match="prior_api_compose_config_files_missing"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_missing_baseline_working_dir_fails_before_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, include_working_dir_label=False)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError, match="prior_api_compose_working_dir_missing"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_forward_topology_rebases_ordered_baseline_layers_into_release_root(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        (prior_root / filename).write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=("docker-compose.yml", "docker-compose.prod.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    assert receipt["target_compose_files"] == [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.memorial.yml",
    ]
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    assert str(release_root / "docker-compose.yml") in config_call
    assert str(release_root / "docker-compose.prod.yml") in config_call
    assert str(prior_root / "docker-compose.yml") not in config_call
    assert receipt["rollback_compose_files"] == [
        str(prior_root / "docker-compose.yml"),
        str(prior_root / "docker-compose.prod.yml"),
    ]


def test_existing_memorial_baseline_is_replaced_for_governed_update(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    for filename in ("docker-compose.yml", "docker-compose.memorial.yml"):
        (prior_root / filename).write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=("docker-compose.yml", "docker-compose.memorial.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    monkeypatch.setattr(
        deploy,
        "_memorial_rollback_environment",
        lambda **_kwargs: {},
    )

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    assert receipt["target_compose_files"] == [
        "docker-compose.yml",
        "docker-compose.memorial.yml",
    ]
    assert receipt["forward_topology_source"]["prior_memorial_layer_replaced"] is True
    assert receipt["rollback_compose_files"] == [
        str(prior_root / "docker-compose.yml"),
        str(prior_root / "docker-compose.memorial.yml"),
    ]
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    assert config_call.count(str(release_root / "docker-compose.memorial.yml")) == 1
    assert str(prior_root / "docker-compose.memorial.yml") not in config_call
    assert not any("up" in call for call in runner.calls)


def test_baseline_layer_outside_prior_working_dir_is_rejected(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    external_file = tmp_path / "external-compose.yml"
    external_file.write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=(str(external_file),),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="forward_baseline_compose_file_unmappable"
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    "reference",
    ["sha256:" + "a" * 64, "registry.example.org/ea@sha256:" + "a" * 64],
)
def test_unrestorable_prior_image_reference_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
) -> None:
    runner = FakeRunner(release_root, prior_image_reference=reference)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="prior_api_image_reference_unrestorable"
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_public_failure_rolls_back_once_with_base_and_prod_only(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        release_root,
        baseline_files=("docker-compose.yml", "docker-compose.prod.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    api_up_calls = [
        call for call in runner.calls if "up" in call and call[-1] == "ea-api"
    ]
    assert len(api_up_calls) == 2
    forward, rollback = api_up_calls
    assert "docker-compose.memorial.yml" in " ".join(forward)
    assert "docker-compose.memorial.yml" not in " ".join(rollback)
    assert "docker-compose.yml" in " ".join(rollback)
    assert "docker-compose.prod.yml" in " ".join(rollback)
    payload = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed_rolled_back"
    assert payload["rollback"]["status"] == "pass"
    rollback_openapi = payload["rollback"]["openapi"]
    assert rollback_openapi["matches_predeploy_contract"] is True
    assert rollback_openapi["restored_retirement_operations"] == list(
        deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
    )
    assert (
        rollback_openapi["contract_sha256"]
        == payload["predeploy_non_memorial_controls"]["openapi"]["contract_sha256"]
    )
    assert "_contract" not in rollback_openapi
    assert "paths" not in rollback_openapi
    rollback_index = runner.calls.index(rollback)
    assert not deploy.FORWARD_ONLY_ENV_KEYS.intersection(
        runner.call_envs[rollback_index]
    )
    assert [
        "docker",
        "image",
        "tag",
        runner.old_image,
        runner.prior_image_reference,
    ] in runner.calls
    assert payload["failure"]["reason"].startswith("http_probe_exhausted:")
    assert [
        check["boundary"]
        for check in payload["checks"]
        if check.get("name") == "predeploy_release_context_revalidation"
    ] == [
        "before_protect_previous_image_tag",
        "before_stop_api_for_gemini_oauth",
        "before_gemini_oauth_install",
        "before_recreate_api_up",
        "before_rollback_image_tag",
        "before_rollback_api_up",
    ]


@pytest.mark.parametrize("rollback_contract", ["candidate", "partial"])
def test_rollback_fails_when_healthy_runtime_does_not_restore_openapi_contract(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    rollback_contract: str,
) -> None:
    runner = FakeRunner(release_root)
    if rollback_contract == "candidate":
        runner.rollback_openapi_paths = list(runner.forward_openapi_paths)
    else:
        missing_operation_path = deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS[0].split(
            " ", 1
        )[1]
        runner.rollback_openapi_paths = [
            path
            for path in runner.prior_openapi_paths
            if path != missing_operation_path
        ]
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    requested_urls: list[str] = []

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        requested_urls.append(url)
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rollback_failed"
    assert receipt["failure"]["reason"].startswith("http_probe_exhausted:")
    assert receipt["rollback"]["reason"] == "rollback_openapi_contract_mismatch"
    assert runner.api_mode == "prior"
    assert sum(url.endswith("/health") for url in requested_urls) >= 2


def test_rollback_mount_mismatch_preserves_primary_and_rollback_failures(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_mount_mismatch = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rollback_failed"
    assert receipt["failure"]["reason"].startswith("http_probe_exhausted:")
    assert receipt["rollback"]["reason"] == "rollback_mount_identity_mismatch"


def test_rollback_environment_drift_preserves_primary_and_rollback_failures(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_env_mismatch = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith("/openapi.json"):
            return deploy.HttpResponse(
                200,
                "application/json",
                b'{"paths":{"/health":{}}}',
            )
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["failure"]["reason"].startswith("http_probe_exhausted:")
    assert receipt["rollback"]["reason"] == "rollback_environment_identity_mismatch"


def test_rollback_replays_exact_captured_baseline_compose_files(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, baseline_files=("docker-compose.yml",))
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)
    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    rollback = [
        call
        for call in runner.calls
        if "up" in call
        and call[-1] == "ea-api"
        and "docker-compose.memorial.yml" not in " ".join(call)
    ][0]
    assert str(release_root / "docker-compose.yml") in rollback
    assert str(release_root / "docker-compose.prod.yml") not in rollback
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["rollback"]["compose_config_files"] == [
        str(release_root / "docker-compose.yml")
    ]


def test_memorial_surface_requires_transparent_narrator_markers(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)

    def unsafe_http(url: str, timeout: float) -> deploy.HttpResponse:
        return deploy.HttpResponse(200, "text/html", b"<html>Ich bin Manfred</html>")

    lane = _lane(release_root, runner, http_get=unsafe_http)

    with pytest.raises(deploy.DeployError, match="http_probe_exhausted"):
        lane._wait_http("https://memorial.example.org/memorials/manfred", kind="html")


def test_public_manifest_must_match_local_manifest(release_root: Path) -> None:
    runner = FakeRunner(release_root)

    def divergent_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        if url.endswith(".json"):
            body = SAFE_MANIFEST
            if url.startswith("https://"):
                body = SAFE_MANIFEST + b" "
            return deploy.HttpResponse(200, "application/json", body, "b" * 40)
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=divergent_http)

    with pytest.raises(
        deploy.DeployError, match="public_memorial_manifest_differs_from_local"
    ):
        lane._verify_deployed_surface(
            "https://memorial.example.org",
            source_revision="b" * 40,
            candidate_promotion_evidence=_candidate_promotion_evidence(),
        )


def test_deployed_surface_probes_canonical_and_singular_alias_origins(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    observed_requests: list[tuple[str, str]] = []
    observed_alias_requests: list[tuple[str, str, str]] = []
    observed_spatial_requests: list[str] = []

    def recording_http(
        url: str,
        timeout: float,
        public_authority: str = "",
    ) -> deploy.HttpResponse:
        del timeout
        observed_requests.append((url, public_authority))
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        if url.endswith(".json"):
            return deploy.HttpResponse(
                200,
                "application/json",
                SAFE_MANIFEST,
                "b" * 40,
            )
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    def recording_no_redirect(
        url: str,
        timeout: float,
        method: str,
        public_authority: str = "",
    ) -> deploy.HttpResponse:
        del timeout
        if urllib.parse.urlsplit(url).path != "/memorial/manfred":
            observed_spatial_requests.append(url)
            raise AssertionError("scoped Memorial verifier requested a spatial route")
        observed_alias_requests.append((method, url, public_authority))
        return _singular_alias_response(method)

    lane = _lane(release_root, runner)
    lane.http_get = recording_http
    lane.http_no_redirect = recording_no_redirect
    lane._verify_deployed_surface(
        "https://memorial.example.org",
        source_revision="b" * 40,
        candidate_promotion_evidence=_candidate_promotion_evidence(),
    )

    assert (
        "http://127.0.0.1:8090/memorials/manfred",
        "memorial.example.org",
    ) in observed_requests
    assert (
        "http://127.0.0.1:8090/memorials/manfred.json",
        "memorial.example.org",
    ) in observed_requests
    assert (
        "https://memorial.example.org/memorials/manfred",
        "",
    ) in observed_requests
    assert (
        "https://memorial.example.org/memorials/manfred.json",
        "",
    ) in observed_requests
    assert observed_alias_requests == [
        (
            "GET",
            "http://127.0.0.1:8090/memorial/manfred?from=ea-launch-verifier",
            "memorial.example.org",
        ),
        (
            "HEAD",
            "http://127.0.0.1:8090/memorial/manfred?from=ea-launch-verifier",
            "memorial.example.org",
        ),
        (
            "GET",
            "https://memorial.example.org/memorial/manfred?from=ea-launch-verifier",
            "",
        ),
        (
            "HEAD",
            "https://memorial.example.org/memorial/manfred?from=ea-launch-verifier",
            "",
        ),
    ]
    assert lane.receipt["alias_probes"][0]["query_preserved"] is True
    assert lane.receipt["alias_probes"][1]["query_preserved"] is True
    assert observed_spatial_requests == []
    spatial = lane.receipt["public_spatial_tour"]
    assert spatial == {
        "status": "not_in_memorial_scope",
        "owner": "PropertyQuarry",
        "scope": "separate_propertyquarry_lane",
        "receipt_consumed": False,
        "requests_performed": 0,
    }


@pytest.mark.parametrize("failure_mode", ["digest", "public_json", "missing", "revision"])
def test_public_spatial_edge_failures_are_not_requested_by_scoped_memorial(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    observed_spatial_requests: list[tuple[str, str]] = []

    def forbidden_public_spatial_edge(
        url: str,
        timeout: float,
        method: str,
    ) -> deploy.HttpResponse:
        del timeout
        if urllib.parse.urlsplit(url).path == "/memorial/manfred":
            return _singular_alias_response(method)
        observed_spatial_requests.append((failure_mode, url))
        raise AssertionError("scoped Memorial lane requested PropertyQuarry")

    lane = _lane(
        release_root,
        runner,
        http_no_redirect=forbidden_public_spatial_edge,
    )
    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    assert observed_spatial_requests == []
    assert receipt["public_spatial_tour"]["requests_performed"] == 0


def test_deployed_surface_revalidates_public_authority_before_http(
    release_root: Path,
) -> None:
    lane = _lane(release_root, FakeRunner(release_root))
    observed: list[str] = []

    def unexpected_http(
        url: str,
        timeout: float,
        public_authority: str = "",
    ) -> deploy.HttpResponse:
        del timeout, public_authority
        observed.append(url)
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane.http_get = unexpected_http

    with pytest.raises(deploy.DeployError, match="public_origin_host_not_approved"):
        lane._verify_deployed_surface(
            "https://attacker.example",
            source_revision="b" * 40,
            candidate_promotion_evidence=_candidate_promotion_evidence(),
        )

    assert observed == []


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (
            deploy.HttpResponse(200, "text/html", SAFE_HTML),
            "memorial_alias_status_invalid",
        ),
        (
            deploy.HttpResponse(301, "text/plain", b""),
            "memorial_alias_status_invalid",
        ),
        (
            deploy.HttpResponse(302, "text/plain", b""),
            "memorial_alias_status_invalid",
        ),
        (
            deploy.HttpResponse(
                307,
                "text/plain",
                b"",
                headers={"Location": "/memorials/manfred?from=ea-launch-verifier"},
            ),
            "memorial_alias_status_invalid",
        ),
        (
            deploy.HttpResponse(
                308,
                "text/plain",
                b"",
                headers={
                    "Location": "https://attacker.invalid/",
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            ),
            "memorial_alias_location_invalid",
        ),
        (
            deploy.HttpResponse(
                308,
                "text/plain",
                b"",
                headers={
                    "Location": "/memorials/manfred?from=ea-launch-verifier",
                    "Cache-Control": "public, max-age=3600",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            ),
            "memorial_alias_headers_invalid",
        ),
        (
            deploy.HttpResponse(
                308,
                "text/plain",
                b"unexpected-head-body",
                headers={
                    "Location": "/memorials/manfred?from=ea-launch-verifier",
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            ),
            "memorial_alias_head_body_invalid",
        ),
    ],
)
def test_singular_alias_probe_rejects_followed_or_malformed_first_hop(
    release_root: Path,
    response: deploy.HttpResponse,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(
        release_root,
        runner,
        http_no_redirect=lambda _url, _timeout, _method: response,
    )

    with pytest.raises(deploy.DeployError, match=reason):
        lane._verify_singular_memorial_alias("https://memorial.example.org")


def test_memorial_probe_rejects_stale_runtime_source_revision(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)

    def stale_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "a" * 40)
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "a" * 40)

    lane = _lane(release_root, runner, http_get=stale_http)

    with pytest.raises(deploy.DeployError, match="source_revision_mismatch"):
        lane._verify_deployed_surface(
            "https://memorial.example.org",
            source_revision="b" * 40,
            candidate_promotion_evidence=_candidate_promotion_evidence(),
        )


@pytest.mark.parametrize(
    "runner_kwargs",
    [
        {"candidate_websockets": 1},
        {"candidate_http_errors": 1},
        {"candidate_archive_gate_check": False},
    ],
)
def test_candidate_browser_or_provider_boundary_failure_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_kwargs: dict[str, object],
) -> None:
    runner = FakeRunner(release_root, **runner_kwargs)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    candidate_calls = [
        call
        for call in runner.calls
        if any(item.endswith("verify_manfred_memorial_candidate.py") for item in call)
    ]
    assert candidate_calls
    assert all("--browser-audit" in call for call in candidate_calls)
    assert all("--submit-contribution-receipt" not in call for call in candidate_calls)
    assert all(
        "--withdraw-contribution-receipt" not in call for call in candidate_calls
    )
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "candidate_verifier_contract_failed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_nonzero_candidate_verifier_records_safe_origin_after_local_evidence(
    release_root: Path,
) -> None:
    secret = "provider-secret-must-not-enter-receipt"
    runner = FakeRunner(
        release_root,
        candidate_failure_origin="public",
        candidate_failure_error="candidate_http_status_unexpected",
        candidate_failure_secret=f"/healthz:403:{secret}",
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match=(
            "fixed_json_script_failed:manfred_candidate_verifier:public:"
            "candidate_http_status_unexpected:7"
        ),
    ) as raised:
        lane._verify_candidate_origins("https://memorial.example.org")

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["candidate_verifier"] == [
        {
            "origin": "local",
            "status": "pass",
            "checks": [
                "archive_publication_gate",
                "browser_provider_websocket_boundary",
                "conversation_only_public_surface",
                "singular_memorial_alias",
                "source_grounded_narrator_boundary",
                "voice_provider_boundary_blocked",
            ],
            "provider_calls_performed": False,
            "browser": {
                "automatic_provider_requests": 0,
                "automatic_websockets": 0,
                "external_requests": 0,
                "failed_requests": 0,
                "page_errors": 0,
                "http_errors": 0,
            },
        }
    ]
    failure = next(
        check for check in receipt["checks"] if check["name"] == "fixed_json_script"
    )
    assert failure == {
        "name": "fixed_json_script",
        "status": "fail",
        "script": "manfred_candidate_verifier",
        "origin": "public",
        "return_code": 7,
        "error_code": "candidate_http_status_unexpected",
        "stdout_bytes": failure["stdout_bytes"],
        "stdout_size_capped": False,
    }
    serialized = json.dumps(receipt, sort_keys=True)
    assert secret not in serialized
    assert secret not in str(raised.value)
    assert "stderr" not in failure


def test_candidate_http_status_failure_records_only_allowlisted_safe_evidence() -> None:
    completed = _completed(
        ["python", "scripts/verify_manfred_memorial_candidate.py"],
        stdout=json.dumps(
            {
                "schema": "ea.manfred_memorial_candidate_smoke.v1",
                "status": "fail",
                "error": "candidate_http_status_unexpected:/memorials/manfred:421",
            }
        ),
        returncode=1,
    )

    evidence = deploy._fixed_json_script_failure_evidence(
        script="scripts/verify_manfred_memorial_candidate.py",
        origin="local",
        completed=completed,
    )

    assert evidence["error_code"] == "candidate_http_status_unexpected"
    assert evidence["error_path"] == "/memorials/manfred"
    assert evidence["http_status"] == 421


@pytest.mark.parametrize(
    "unsafe_error",
    [
        "candidate_http_status_unexpected:/healthz:421",
        "candidate_http_status_unexpected:/memorials/manfred:099",
        "candidate_http_status_unexpected:/memorials/manfred:600",
        "candidate_http_status_unexpected:/memorials/manfred:421:secret",
        "candidate_http_status_unexpected:/memorials/manfred%0a:421",
    ],
)
def test_candidate_http_status_failure_redacts_unallowlisted_details(
    unsafe_error: str,
) -> None:
    completed = _completed(
        ["python", "scripts/verify_manfred_memorial_candidate.py"],
        stdout=json.dumps(
            {
                "schema": "ea.manfred_memorial_candidate_smoke.v1",
                "status": "fail",
                "error": unsafe_error,
            }
        ),
        returncode=1,
    )

    evidence = deploy._fixed_json_script_failure_evidence(
        script="scripts/verify_manfred_memorial_candidate.py",
        origin="local",
        completed=completed,
    )

    assert evidence["error_code"] == "candidate_http_status_unexpected"
    assert "error_path" not in evidence
    assert "http_status" not in evidence
    assert unsafe_error not in json.dumps(evidence, sort_keys=True)


def test_candidate_verifier_browser_flag_is_explicit() -> None:
    from scripts import verify_manfred_memorial_candidate as candidate

    args = candidate.build_parser().parse_args(
        [
            "--base-url",
            "https://myexternalbrain.com",
            "--public-origin",
            "https://myexternalbrain.com",
            "--browser-audit",
        ]
    )

    assert args.browser_audit is True


def test_subprocess_failure_never_exposes_output_or_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "super-secret-token"

    def failed_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _completed(
            ["docker", "compose", "config"],
            stdout=f"stdout:{secret}",
            stderr=f"stderr:{secret}",
            returncode=9,
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(deploy.DeployError) as raised:
        deploy.SubprocessRunner().run(
            ["docker", "compose", "config"],
            cwd=tmp_path,
            env={"TOKEN": secret},
        )

    message = str(raised.value)
    assert message == "command_failed:9:docker"
    assert secret not in message
    assert "stdout" not in message
    assert "stderr" not in message


def test_receipt_is_private_and_deployment_id_cannot_be_reused(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    lane.deploy(preflight_only=True)

    assert lane.receipt_path.stat().st_mode & 0o777 == 0o600
    duplicate = _lane(release_root, FakeRunner(release_root))
    with pytest.raises(deploy.DeployError, match="deployment_receipt_already_exists"):
        duplicate.deploy(preflight_only=True)


def test_make_target_uses_scoped_conversation_lane_and_keeps_joint_explicit() -> None:
    makefile = (deploy.ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("deploy-ea-memorial:", 1)[1].split("\n\n", 1)[0]
    joint = makefile.split("deploy-ea-memorial-joint:\n", 1)[1].split("\n\n", 1)[0]
    scoped = makefile.split("deploy-ea-memorial-scoped:\n", 1)[1].split("\n\n", 1)[0]

    assert "deploy-ea-memorial-scoped" in target
    assert "EA_DEPLOY_PRIMARY_MODE=MEMORIAL" in target
    assert "EA_DEPLOY_ENABLED_MODES=MEMORIAL" in target
    assert "deploy-ea-memorial-joint" not in target
    assert "scripts/deploy_ea_memorial_joint.py" in joint
    assert "EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT" in joint
    assert "scripts/deploy_ea_memorial.py" in scoped
    assert "EA_MEMORIAL_IMAGE" in scoped
    assert "EA_MEMORIAL_CANDIDATE_RECEIPT" in scoped
    assert "verify-memorial-deploy-readiness" not in target
    assert "scripts/deploy.sh" not in target + joint + scoped


def test_memorial_compose_override_is_api_only() -> None:
    raw = (deploy.ROOT / "docker-compose.memorial.yml").read_text(encoding="utf-8")
    assert raw.startswith("services:\n  ea-api:\n")
    assert "image: ${EA_MEMORIAL_IMAGE:?" in raw
    assert "pull_policy: never" in raw
    assert 'user: "10001:10001"' in raw
    assert "volumes: !override" in raw
    assert "EA_SOURCE_REVISION=${EA_SOURCE_REVISION:?" in raw
    assert "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER=0" in raw
    assert "EA_TRUST_PROXY_HEADERS=1" in raw
    assert "EA_TRUSTED_PROXY_CIDRS=${EA_MEMORIAL_TRUSTED_PROXY_CIDRS:?" in raw
    assert (
        "EA_TRUSTED_PUBLIC_ORIGIN_ALIASES="
        "${EA_MEMORIAL_TRUSTED_PUBLIC_ORIGIN_ALIASES:-origin.myexternalbrain.com}"
        in raw
    )
    assert "EA_ALLOWED_PUBLIC_HOSTS=${EA_MEMORIAL_ALLOWED_PUBLIC_HOSTS:-" in raw
    assert (
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR=/data/memorial-writable/public-contributions"
        in raw
    )
    assert (
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR=/data/memorial-writable/private-contributions"
        in raw
    )
    assert "EA_MEMORIAL_STATE_DIR=/data/memorial-writable/state" in raw
    assert "EA_PUBLIC_TOUR_DIR=/data/memorial_data/public_property_tours" in raw
    assert "/data/memorial_data:ro" in raw
    assert "/data/artifacts" in raw
    assert "/app/app" not in raw
    assert "/app/scripts" not in raw
    assert "/app/.codex" not in raw
    assert "/app/config" not in raw
    assert "/run/secrets" not in raw
    assert raw.count("${EA_MEMORIAL_RUNTIME_HOST_PATH:?") == 3
    assert "\n  ea-worker:" not in raw
    assert "\n  ea-scheduler:" not in raw


def test_bind_source_denial_fails_preflight_before_any_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def deny(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise deploy.BindSourceGuardError("bind_source_file_not_readable")

    lane = _lane(
        release_root,
        runner,
        bind_source_validator=deny,
    )
    with pytest.raises(
        deploy.DeployError,
        match=(
            "memorial_bind_source_access_denied:"
            "bind_source_file_not_readable"
        ),
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


def test_bind_source_snapshot_drift_stops_before_api_recreation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def drift(
        _rendered: Mapping[str, object],
        *,
        expected_snapshot_sha256: str = "",
        **_kwargs: object,
    ) -> dict[str, object]:
        if expected_snapshot_sha256:
            raise deploy.BindSourceGuardError("bind_source_snapshot_changed")
        return _passing_bind_source_validator({})

    lane = _lane(
        release_root,
        runner,
        bind_source_validator=drift,
    )
    with pytest.raises(
        deploy.DeployError,
        match=(
            "memorial_bind_source_access_denied:"
            "bind_source_snapshot_changed"
        ),
    ):
        lane.deploy()

    api_up_calls = [
        call for call in runner.calls if "up" in call and call[-1] == "ea-api"
    ]
    assert len(api_up_calls) == 1
    assert "docker-compose.memorial.yml" not in " ".join(api_up_calls[0])
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["preparation"]["api_mutation_started"] is True
    assert receipt["rollback"]["status"] == "pass"
