from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pytest

from app.api.routes import public_tours
from app.services.public_tour_release_policy import (
    GENERATED_RECONSTRUCTION_PROVIDER,
    PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
)
from scripts import deploy_ea_memorial as deploy


class TestVexpMemorialMutationAuthority(deploy.VexpMemorialMutationAuthority):
    __test__ = False

    def __init__(
        self,
        *,
        state_path: Path,
        certificate_root: Path,
        certificate_directory: Path,
        permit_path: Path,
        lock_path: Path,
        utc_now: Callable[[], datetime],
    ) -> None:
        self._state_path = state_path
        self._certificate_root = certificate_root
        self._certificate_directory = certificate_directory
        self._permit_path = permit_path
        self._lock_path = lock_path
        self._utc_now = utc_now

    @property
    def sentinel_state_path(self) -> Path:
        return self._state_path

    @property
    def mutation_permit_path(self) -> Path:
        return self._permit_path

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
    def mutation_permit_lock_path(self) -> Path:
        return self._lock_path

    @property
    def mutation_permit_lock_owner_uid(self) -> int:
        return os.geteuid()

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
    allowed_files = {
        relpath: {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for relpath, content in sorted(SPATIAL_TEST_FILES.items())
    }
    return {
        "provider_calls_performed": False,
        "spatial_handoff": {
            "slug": deploy.REQUIRED_CONTROL_TOUR_SLUG,
            "route_count": 8,
            "html_json_viewer_200": True,
            "proof_only_404": True,
            "release_verifier_pass": True,
            "browser_schema": "ea.manfred_spatial_candidate_browser.v5",
            "browser_pass": True,
            "identity_bound": True,
            "package_sha256": deploy._spatial_package_sha256(SPATIAL_TEST_FILES),
            "allowed_files": allowed_files,
            "viewer_relpath": SPATIAL_VIEWER_RELPATH,
            "proof_relpath": SPATIAL_PROOF_RELPATH,
            "tour_manifest_canonical_sha256": deploy._canonical_json_sha256(
                PUBLIC_SPATIAL_TOUR_PAYLOAD
            ),
            "property_artifact_commit": deploy.PROPERTY_ARTIFACT_COMMIT,
            "upstream_publication_authority_sha256": (
                deploy.PROPERTY_AUTHORITY_SHA256
            ),
            "upstream_tour_manifest_sha256": hashlib.sha256(
                SPATIAL_TEST_FILES["tour.json"]
            ).hexdigest(),
            "pre_authority_manifest_canonical_sha256": (
                deploy.PROPERTY_PRE_AUTHORITY_SHA256
            ),
            "upstream_public_activation_authority": True,
            "ea_public_activation_authority": False,
            "provider_calls_performed": False,
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
            output.write_text('{"status":"pass"}\n', encoding="utf-8")

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
        if argv[:3] == ["docker", "compose", "version"]:
            stdout = "Docker Compose version v2"
        elif argv[:2] == ["docker-compose", "version"]:
            returncode = 1
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
            running = self.redis_running if name == "ea-redis" else True
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
        elif "up" in argv and argv[-1] == "ea-api":
            memorial = any(
                item.endswith("docker-compose.memorial.yml") for item in argv
            )
            self.api_mode = "forward" if memorial else "prior"
            self.rollback_mode = not memorial
            if memorial:
                self.forward_files = [
                    argv[index + 1]
                    for index, item in enumerate(argv[:-1])
                    if item == "-f"
                ]
        elif any(item.endswith("verify_release_authority.py") for item in argv):
            stdout = json.dumps(
                {
                    "contract_name": "ea.release_authority_gate.v1",
                    "status": self.authority_status,
                    "authority_posture": (
                        self.postdeploy_authority_posture
                        if self.materializer_call_count >= 8
                        and self.postdeploy_authority_posture is not None
                        else self.authority_posture
                    ),
                    "source_worktree_dirty": False,
                    "deployment_id": "memorial-release-001",
                    "commit_sha": "b" * 40,
                    "project_mode": "MEMORIAL",
                    "public_origin": (
                        self.postdeploy_authority_public_origin
                        if self.materializer_call_count >= 8
                        and self.postdeploy_authority_public_origin is not None
                        else self.authority_public_origin
                    ),
                }
            )
        elif any(item.endswith("verify_memorial_deploy_readiness.py") for item in argv):
            stdout = json.dumps(
                {
                    "contract_name": "ea.memorial_deploy_readiness.v1",
                    "status": self.readiness_status,
                }
            )
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
    spatial_root = projection_root / "public_property_tours"
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
            "/data/public_property_tours",
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
            "EA_MANFRED_POSTGRES_PASSWORD",
            "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
            "EA_MANFRED_RELEASE_ROOT",
            "EA_MANFRED_RUNTIME_ROOT",
            "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED",
            "EA_MANFRED_SPATIAL_RELEASE_ROOT",
            "EA_MANFRED_SPATIAL_SHA256",
            "EA_MANFRED_SPATIAL_SLUG",
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
                "/data/public_property_tours",
                projection_root / "public_property_tours",
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
    vexp_state_path = vexp_authority_root / "state.json"
    vexp_permit_path = vexp_authority_root / "memorial-mutation-permit.json"
    vexp_lock_path = vexp_authority_root / "memorial-mutation-permit.lock"
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
    vexp_permit_path.write_text(
        json.dumps(vexp_permit, sort_keys=True) + "\n", encoding="utf-8"
    )
    vexp_permit_path.chmod(0o644)
    vexp_lock_path.touch()
    vexp_lock_path.chmod(0o644)

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
    )
    lane._vexp_mutation_authority = TestVexpMemorialMutationAuthority(
        state_path=vexp_state_path,
        certificate_root=vexp_certificate_root,
        certificate_directory=vexp_certificate_directory,
        permit_path=vexp_permit_path,
        lock_path=vexp_lock_path,
        utc_now=lambda: datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
    )
    return lane


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


def test_preflight_requires_the_flagship_control_tour(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)
    lane = _lane(release_root, runner, control_tour_slug="")

    with pytest.raises(
        deploy.DeployError,
        match="memorial_control_tour_slug_required",
    ):
        lane.preflight()

    assert runner.calls == []


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
    assert evidence["projection"]["file_count"] == len(SPATIAL_TEST_FILES)

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
    assert runner.calls == []


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

    receipt = lane.deploy(preflight_only=True)

    assert tracked_default.read_bytes() == before
    assert set(receipt["release_evidence"]) == {"predeploy"}
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
    authority_call = next(
        call
        for call in runner.calls
        if any(item.endswith("verify_release_authority.py") for item in call)
    )
    readiness_call = next(
        call
        for call in runner.calls
        if any(item.endswith("verify_memorial_deploy_readiness.py") for item in call)
    )
    assert "--release-manifest" in authority_call
    assert "--memorial-status" in readiness_call
    assert "--release-authority-status" in readiness_call
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


def test_postdeploy_evidence_mutation_triggers_automatic_rollback(
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
            "deployment_failed_rolled_back:release_evidence_mutated_tracked_worktree"
        ),
    ):
        lane.deploy()

    assert runner.materializer_call_count == 5
    assert runner.api_mode == "prior"
    assert lane.receipt["status"] == "failed_rolled_back"


def test_postdeploy_optional_env_creation_uses_sealed_prior_root_for_rollback(
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
        match=("deployment_failed_rolled_back:deployment_input_seal_changed:forward"),
    ):
        lane.deploy()

    assert runner.api_mode == "prior"
    assert lane.receipt["status"] == "failed_rolled_back"
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
    assert len(rendered_config_calls) == 2
    assert receipt["bind_source_access"]["snapshot_sha256"] == "5" * 64
    assert any(
        check.get("name") == "memorial_bind_source_revalidation"
        and check.get("boundary") == "before_recreate_api"
        for check in receipt["checks"]
    )
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
    assert promotion["schema"] == "ea.manfred_memorial_candidate_runtime.v4"
    assert len(promotion["projection"]["projection_sha256"]) == 64
    assert len(promotion["live_ea"]["snapshot_sha256"]) == 64
    assert promotion["openapi"]["candidate_preserves_live_contract"] is True
    assert (
        promotion["openapi"]["retirement_policy_id"]
        == deploy.OPENAPI_RETIREMENT_POLICY_ID
    )
    assert promotion["openapi"]["retired_operations"] == list(
        deploy.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
    )
    assert promotion["openapi"]["retired_operation_count"] == 2
    assert promotion["openapi"]["candidate_public_openapi_retired"] is True
    assert promotion["openapi"]["compatible_evolution_policy_exact_match"] is True
    assert promotion["openapi"]["compatible_evolved_operations"] == ["GET /version"]
    assert promotion["browser"]["http_errors"] == 0
    assert promotion["runtime_identity"]["revision_agreement_verified"] is True
    assert promotion["execution_inputs"]["sealed"] is True
    assert promotion["runtime_posture"]["hardened"] is True
    assert promotion["registry_recovery"]["safe"] is True
    spatial_handoff = promotion["spatial_handoff"]
    assert spatial_handoff["identity_bound"] is True
    assert set(spatial_handoff["allowed_files"]) == set(SPATIAL_TEST_FILES)
    assert all(
        set(file_evidence) == {"sha256", "size_bytes"}
        for file_evidence in spatial_handoff["allowed_files"].values()
    )
    assert all(
        not relpath.startswith("/") and "://" not in relpath
        for relpath in spatial_handoff["allowed_files"]
    )
    assert spatial_handoff["property_artifact_commit"] == (
        deploy.PROPERTY_ARTIFACT_COMMIT
    )
    assert spatial_handoff["upstream_public_activation_authority"] is True
    assert spatial_handoff["ea_public_activation_authority"] is False
    assert spatial_handoff["provider_calls_performed"] is False
    public_spatial = receipt["public_spatial_tour"]
    assert public_spatial["request_count"] == 16
    assert public_spatial["proof_only_404"] is True
    assert public_spatial["redirect_count"] == 0
    assert public_spatial["external_request_count"] == 0
    assert public_spatial["provider_calls_performed"] is False
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
        ("spatial_handoff.included", False),
        ("spatial_handoff.projection_sha256", "e" * 64),
        ("spatial_handoff.upstream_publication_authority_sha256", "e" * 64),
        ("spatial_handoff.upstream_package_sha256", "e" * 64),
        ("spatial_handoff.upstream_tour_manifest_sha256", "e" * 64),
        ("spatial_handoff.pre_authority_manifest_canonical_sha256", "e" * 64),
        ("spatial_handoff.local_release_verifier.pass", False),
        ("spatial_handoff_runtime.included", False),
        ("spatial_handoff_runtime.routes.html_get.status", 404),
        ("spatial_handoff_runtime.routes.proof_only_head.status", 200),
        (
            "spatial_handoff_runtime.generated_viewer_release_verifier.pass",
            False,
        ),
        ("spatial_handoff_runtime.candidate_browser_gate.status", "fail"),
        (
            "spatial_handoff_runtime.candidate_browser_gate.landing.status",
            500,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate.viewer_path",
            "/tours/viewer/wrong/viewer.html",
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate.proof_manifest.path",
            "/tours/viewer/wrong/reconstruction.json",
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate."
            "package_binding.local_file_count",
            5,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate."
            "package_binding.http_asset_count",
            3,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate.surfaces.desktop.status",
            500,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate.candidate_commit",
            "a" * 40,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate."
            "candidate_oci_image.image_id",
            "sha256:" + "d" * 64,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate."
            "serving_container.container_id",
            "3" * 64,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate.package_sha256",
            "e" * 64,
        ),
        (
            "spatial_handoff_runtime.candidate_browser_gate.secret_material_recorded",
            True,
        ),
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
        ("openapi_contract.candidate_preserves_live_contract", False),
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
    payload["openapi_contract"]["live_before"]["raw_contract"] = {
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
        lane.deploy(preflight_only=True)

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


def test_required_tour_control_survives_unchanged(
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

    before = receipt["predeploy_non_memorial_controls"]["tour"]
    after = receipt["postdeploy_non_memorial_controls"]["tour"]
    assert before["slug"] == deploy.REQUIRED_CONTROL_TOUR_SLUG
    assert before["json"]["body_sha256"] != after["json"]["body_sha256"]
    assert (
        before["json"]["canonical_json_sha256"]
        == after["json"]["canonical_json_sha256"]
    )
    assert "_json_payload" not in before
    assert "_json_payload" not in after
    assert before["html"]["status_code"] == after["html"]["status_code"] == 200


def test_required_tour_json_drift_rolls_back(
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

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_control_tour_json_changed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_exact_generated_viewer_tour_evolution_is_compatible(
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

    tour = receipt["postdeploy_non_memorial_controls"]["tour"]
    assert tour["compatible_evolution_policy_id"] == (
        deploy.CONTROL_TOUR_COMPATIBLE_EVOLUTION_POLICY_ID
    )
    assert tour["compatible_evolution_applied"] is True
    assert tour["compatible_evolution_policy_exact_match"] is True


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
            assert public_authority == ""
            return _public_spatial_response(url, method)
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
    spatial = lane.receipt["public_spatial_tour"]
    assert set(spatial) == {
        "status",
        "origin",
        "slug",
        "source_revision",
        "request_count",
        "get_count",
        "head_count",
        "routes",
        "exact_byte_file_count",
        "canonical_json_file_count",
        "proof_only_404",
        "redirect_count",
        "external_request_count",
        "provider_calls_performed",
        "property_authority",
    }
    assert spatial["status"] == "pass"
    assert spatial["request_count"] == 16
    assert spatial["get_count"] == spatial["head_count"] == 8
    assert spatial["provider_calls_performed"] is False
    assert spatial["external_request_count"] == 0
    assert set(spatial["routes"]) == {
        f"{label}_{method}"
        for label in (
            "version",
            "landing",
            "tour_json",
            "viewer",
            "floorplan",
            "three_module",
            "orbit_controls",
            "proof_only",
        )
        for method in ("get", "head")
    }
    base_route_fields = {
        "path",
        "method",
        "status",
        "content_type",
        "source_revision",
        "body_bytes",
        "body_sha256",
    }
    assert set(spatial["routes"]["version_get"]) == {
        *base_route_fields,
        "commit_sha",
    }
    assert set(spatial["routes"]["tour_json_get"]) == {
        *base_route_fields,
        "canonical_json_sha256",
    }
    for label in ("viewer", "floorplan", "three_module", "orbit_controls"):
        assert set(spatial["routes"][f"{label}_get"]) == {
            *base_route_fields,
            "candidate_file_identity_verified",
        }
    assert set(spatial["routes"]["proof_only_get"]) == {
        *base_route_fields,
        "candidate_file_not_disclosed",
    }
    assert set(spatial["routes"]["landing_get"]) == base_route_fields
    assert all(
        set(spatial["routes"][f"{label}_head"]) == base_route_fields
        for label in (
            "version",
            "landing",
            "tour_json",
            "viewer",
            "floorplan",
            "three_module",
            "orbit_controls",
            "proof_only",
        )
    )
    assert spatial["property_authority"]["owner"] == "PropertyQuarry"
    assert spatial["property_authority"]["ea_public_activation_authority"] is False


@pytest.mark.parametrize(
    ("failure_mode", "failure_reason"),
    [
        ("digest", "public_spatial_asset_digest_mismatch"),
        ("public_json", "public_spatial_tour_json_digest_mismatch"),
        ("missing", "public_spatial_status_invalid"),
        ("revision", "public_spatial_source_revision_mismatch"),
    ],
)
def test_public_spatial_edge_failure_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    failure_reason: str,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    slug = deploy.REQUIRED_CONTROL_TOUR_SLUG
    viewer_path = f"/tours/viewer/{slug}/{SPATIAL_VIEWER_RELPATH}"
    tour_json_path = f"/tours/{slug}.json"
    floorplan_path = (
        f"/tours/viewer/{slug}/generated-reconstruction/source-floorplan.png"
    )

    def failing_public_edge(
        url: str,
        timeout: float,
        method: str,
    ) -> deploy.HttpResponse:
        del timeout
        if urllib.parse.urlsplit(url).path == "/memorial/manfred":
            return _singular_alias_response(method)
        if failure_mode == "digest":
            return _public_spatial_response(
                url,
                method,
                body_overrides={viewer_path: b"tampered-viewer"},
            )
        if failure_mode == "public_json":
            return _public_spatial_response(
                url,
                method,
                body_overrides={tour_json_path: b'{"slug":"tampered"}'},
            )
        if failure_mode == "missing":
            return _public_spatial_response(
                url,
                method,
                status_overrides={floorplan_path: 404},
            )
        return _public_spatial_response(
            url,
            method,
            source_revision="a" * 40,
        )

    lane = _lane(
        release_root,
        runner,
        http_no_redirect=failing_public_edge,
    )
    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert failure_reason in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"
    assert receipt["preparation"]["api_runtime_state"] == "restored_by_rollback"


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


def test_make_target_uses_joint_lane_not_generic_deployer() -> None:
    makefile = (deploy.ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("deploy-ea-memorial:", 1)[1].split("\n\n", 1)[0]
    joint = makefile.split("deploy-ea-memorial-joint:\n", 1)[1].split("\n\n", 1)[0]
    scoped = makefile.split("deploy-ea-memorial-scoped:\n", 1)[1].split("\n\n", 1)[0]

    assert "deploy-ea-memorial-joint" in target
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

    assert not any(
        "up" in call and call[-1] == "ea-api" for call in runner.calls
    )
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["preparation"]["api_mutation_started"] is False
