from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import urllib.parse
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pytest

from app.api.routes import public_tours
from app.services.public_tour_release_policy import (
    GENERATED_RECONSTRUCTION_PROVIDER,
    PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
)
from scripts import deploy_ea_memorial as deploy

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
    ("generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"): (
        "viewer_module",
        "text/javascript",
    ),
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
        "floorplan_relpath": ("generated-reconstruction/source-floorplan.png"),
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
            "upstream_publication_authority_sha256": (deploy.PROPERTY_AUTHORITY_SHA256),
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
                {
                    "app_name": "ea-rewrite",
                    "version": "0.3.0",
                    "role": "api",
                    "storage_backend": "postgres",
                    "release_authority_state": "clear",
                    "release_authority_posture": "authoritative_runtime",
                    "release_authority_source": "published_status_artifact",
                    "release_manifest_generated_at": "2026-07-16T16:11:22Z",
                },
                separators=(",", ":"),
            ).encode("utf-8"),
        ),
        f"/tours/{slug}": (
            200,
            "text/html; charset=utf-8",
            (
                '<!doctype html><html><body><iframe src="'
                f'{viewer_root}/{SPATIAL_VIEWER_RELPATH}"></iframe></body></html>'
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


def _local_https_redirect_response(
    url: str,
    method: str,
    *,
    public_origin: str = "https://memorial.example.org",
) -> deploy.HttpResponse:
    parsed = urllib.parse.urlsplit(url)
    location = f"{public_origin}{parsed.path}"
    if parsed.query:
        location = f"{location}?{parsed.query}"
    return deploy.HttpResponse(
        308,
        "text/plain; charset=utf-8",
        b"" if method == "HEAD" else b"Permanent Redirect",
        headers={"Location": location},
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
        baseline_config_root: Path | None = None,
        baseline_environment_files: tuple[str, ...] | None = None,
        trusted_baseline_root: bool = True,
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
        self.baseline_config_root = baseline_config_root or self.baseline_root
        self.baseline_environment_files = baseline_environment_files
        self.trusted_baseline_root = trusted_baseline_root
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
        self.prior_container_id = "container-ea-api"
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
        self.api_present = True
        self.forward_files: list[str] = []
        self.forward_environment_files: list[str] = []
        self.forward_working_root = self.root
        self.forward_image_id = self.candidate_image
        self.forward_project = "ea"
        self.forward_service = "ea-api"
        self.forward_source_mounts = True
        self.forward_extra_mount = False
        self.rollback_mount_mismatch = False
        self.rollback_env_mismatch = False
        self.rollback_mode = False
        self.rollback_capsule_file = ""
        self.prior_extra_environment: list[str] = []
        self.prior_config_overrides: dict[str, object] = {}
        self.prior_host_config: dict[str, object] = {}
        self.rollback_host_config_overrides: dict[str, object] = {}
        self.prior_networks: dict[str, object] = {}
        self.prior_network_settings_overrides: dict[str, object] = {}
        self.network_resource_id_overrides: dict[str, str] = {}
        self.network_resource_id_after_first_inspect: dict[str, str] = {}
        self.network_resource_inspect_counts: dict[str, int] = {}
        self.volume_resource_driver_overrides: dict[str, str] = {}
        self.prior_mounts_override: list[dict[str, object]] | None = None
        self.prior_noncompose_labels: dict[str, str] = {}
        self.tamper_capsule_on_forward = False
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
        self.prior_source_revision = "a" * 40
        self.prior_source_revision_env = [
            f"EA_SOURCE_REVISION={self.prior_source_revision}"
        ]
        self.public_openapi_methods: list[str] = []
        self.public_openapi_overrides: dict[str, dict[str, object]] = {}
        self.rollback_render_environment: dict[str, str] = {
            "EA_SOURCE_REVISION": self.prior_source_revision
        }
        self.rollback_capsule_render_environment_override: dict[str, str] | None = None
        self.rollback_capsule_render_mutator: (
            Callable[[dict[str, object]], None] | None
        ) = None
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
        self.head_blob_overrides: dict[str, str] = {}
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
                    "Mode": "ro",
                    "RW": False,
                    "Propagation": "rprivate",
                },
                {
                    "Type": "bind",
                    "Source": str(root / "scripts"),
                    "Destination": "/app/scripts",
                    "Mode": "ro",
                    "RW": False,
                    "Propagation": "rprivate",
                },
            ]
        runtime_root = root / ".runtime" / "candidate-data"
        return [
            {
                "Type": "bind",
                "Source": str(root / "memorial_data"),
                "Destination": "/data/memorial_data",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate",
            },
            *[
                {
                    "Type": "bind",
                    "Source": str(runtime_root / basename),
                    "Destination": destination,
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate",
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
                "Driver": "local",
                "Destination": "/data/artifacts",
                "Mode": "rw",
                "RW": True,
                "Propagation": "",
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

    def _normalized_capsule_render(
        self, capsule_document: Mapping[str, object]
    ) -> dict[str, object]:
        rendered = json.loads(json.dumps(capsule_document))
        service = rendered["services"]["ea-api"]
        extra_hosts = service.get("extra_hosts")
        if isinstance(extra_hosts, list):
            normalized_hosts = []
            for item in extra_hosts:
                host, separator, address = str(item).partition(":")
                normalized_hosts.append(f"{host}={address}" if separator else str(item))
            service["extra_hosts"] = normalized_hosts
        ports = service.get("ports")
        if isinstance(ports, list):
            for port in ports:
                if (
                    isinstance(port, dict)
                    and str(port.get("published") or "").isdigit()
                ):
                    port["published"] = int(str(port["published"]))
                    port.setdefault("mode", "ingress")
        volumes = service.get("volumes")
        if isinstance(volumes, list):
            for mount in volumes:
                if not isinstance(mount, dict):
                    continue
                if mount.get("type") == "bind":
                    bind = dict(mount.get("bind") or {})
                    bind.setdefault("create_host_path", True)
                    mount["bind"] = bind
                elif mount.get("type") == "volume":
                    volume = dict(mount.get("volume") or {})
                    volume.setdefault("nocopy", False)
                    mount["volume"] = volume
        if self.rollback_capsule_render_mutator is not None:
            self.rollback_capsule_render_mutator(rendered)
        return rendered

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
        elif argv[:2] == ["git", "-C"] and argv[3:] == ["rev-parse", "--show-toplevel"]:
            if self.trusted_baseline_root:
                stdout = str(self.baseline_root) + "\n"
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
        elif argv[:4] == ["git", "hash-object", "--no-filters", "--"]:
            relative = argv[4]
            content = (self.root / relative).read_bytes()
            stdout = (
                hashlib.sha1(
                    f"blob {len(content)}\0".encode("ascii") + content
                ).hexdigest()
                + "\n"
            )
        elif argv[:2] == ["git", "rev-parse"] and len(argv) == 3 and ":" in argv[2]:
            _revision, relative = argv[2].split(":", 1)
            content = (self.root / relative).read_bytes()
            stdout = (
                self.head_blob_overrides.get(
                    relative,
                    hashlib.sha1(
                        f"blob {len(content)}\0".encode("ascii") + content
                    ).hexdigest(),
                )
                + "\n"
            )
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
                            "Labels": (
                                dict(self.prior_noncompose_labels)
                                if image_id == self.old_image
                                else {}
                            ),
                        },
                    }
                ]
            )
        elif argv[:3] == ["docker", "image", "tag"]:
            source, destination = argv[-2:]
            self.image_refs[destination] = self.image_refs.get(source, source)
        elif argv[:3] == ["docker", "network", "inspect"]:
            name = argv[-1]
            self.network_resource_inspect_counts[name] = (
                self.network_resource_inspect_counts.get(name, 0) + 1
            )
            endpoint = self.prior_networks.get(name)
            if not isinstance(endpoint, dict):
                returncode = 1
                stderr = f"Error: No such network: {name}"
            else:
                stdout = json.dumps(
                    [
                        {
                            "Name": name,
                            "Id": (
                                self.network_resource_id_after_first_inspect[name]
                                if self.network_resource_inspect_counts[name] > 1
                                and name in self.network_resource_id_after_first_inspect
                                else self.network_resource_id_overrides.get(
                                    name, str(endpoint.get("NetworkID") or "")
                                )
                            ),
                        }
                    ]
                )
        elif argv[:3] == ["docker", "volume", "inspect"]:
            name = argv[-1]
            known_volumes = {
                str(item.get("Name") or ""): str(item.get("Driver") or "local")
                for item in (
                    self.prior_mounts_override
                    or self._api_mounts(self.baseline_root, memorial=False)
                )
                if item.get("Type") == "volume"
            }
            if name not in known_volumes:
                returncode = 1
                stderr = f"Error: No such volume: {name}"
            else:
                stdout = json.dumps(
                    [
                        {
                            "Name": name,
                            "Driver": self.volume_resource_driver_overrides.get(
                                name, known_volumes[name]
                            ),
                        }
                    ]
                )
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
            if name == "ea-api" and not self.api_present:
                returncode = 1
                stderr = "Error: No such object: ea-api"
                return _completed(
                    argv, stdout=stdout, stderr=stderr, returncode=returncode
                )
            if name == "ea-redis" and not self.redis_present:
                returncode = 1
                stderr = "Error: No such object: ea-redis"
                result = _completed(
                    argv, stdout=stdout, stderr=stderr, returncode=returncode
                )
                return result
            forward = name == "ea-api" and self.api_mode == "forward"
            working_root = (
                self.forward_working_root
                if forward
                else Path(self.rollback_capsule_file).parent
                if self.rollback_mode and self.rollback_capsule_file
                else self.baseline_root
            )
            config_files = (
                self.forward_files
                if forward
                else [self.rollback_capsule_file]
                if self.rollback_mode and self.rollback_capsule_file
                else [
                    str(self.baseline_config_root / item)
                    for item in self.baseline_files
                ]
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
            environment_files = (
                self.forward_environment_files
                if forward
                else list(self.baseline_environment_files or ())
            )
            if environment_files:
                labels["com.docker.compose.project.environment_file"] = ",".join(
                    environment_files
                )
            if name == "ea-api":
                labels.update(self.prior_noncompose_labels)
            if self.include_working_dir_label:
                labels["com.docker.compose.project.working_dir"] = str(working_root)
            running = self.redis_running if name == "ea-redis" else True
            health = self.redis_health if name == "ea-redis" else "healthy"
            image_id = self.forward_image_id if forward else self.old_image
            image_reference = (
                self.candidate_reference if forward else self.prior_image_reference
            )
            if name == "ea-api":
                labels.update(
                    {
                        "com.docker.compose.container-number": "1",
                        "com.docker.compose.image": image_id,
                        "com.docker.compose.oneoff": "False",
                    }
                )
            mount_root = self.baseline_root if self.rollback_mode else working_root
            mounts = (
                self._api_mounts(mount_root, memorial=forward)
                if name == "ea-api"
                else []
            )
            if (
                name == "ea-api"
                and not forward
                and self.prior_mounts_override is not None
            ):
                mounts = [dict(item) for item in self.prior_mounts_override]
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
            for mount in mounts:
                read_write = bool(mount.get("RW"))
                mount.setdefault("Mode", "rw" if read_write else "ro")
                mount.setdefault(
                    "Propagation",
                    "rprivate" if mount.get("Type") == "bind" else "",
                )
                if mount.get("Type") == "volume":
                    mount.setdefault("Driver", "local")
            payload = {
                "Id": (
                    self.prior_container_id
                    if name == "ea-api" and not forward
                    else "container-" + name
                ),
                "Created": "2026-07-13T00:00:00Z",
                "Image": image_id,
                "Path": "/usr/bin/tini" if name == "ea-api" else "",
                "Args": (["--", "uvicorn", "app.main:app"] if name == "ea-api" else []),
                "Config": {
                    "Image": image_reference,
                    "Labels": labels,
                    "Env": (
                        [f"EA_SOURCE_REVISION={'b' * 40}"]
                        if forward
                        else [
                            *self.prior_source_revision_env,
                            *self.prior_extra_environment,
                            "ROLLBACK_DRIFT=1",
                        ]
                        if self.rollback_mode and self.rollback_env_mismatch
                        else [
                            *self.prior_source_revision_env,
                            *self.prior_extra_environment,
                        ]
                    ),
                    "Cmd": ["uvicorn", "app.main:app"],
                    "Entrypoint": ["/usr/bin/tini", "--"],
                    "User": "10001:10001",
                    **(
                        dict(self.prior_config_overrides)
                        if name == "ea-api" and not forward
                        else {}
                    ),
                },
                "HostConfig": (
                    {
                        **deploy.ROLLBACK_CAPSULE_ENGINE_SECURITY_DEFAULTS,
                        **self.prior_host_config,
                        **(
                            self.rollback_host_config_overrides
                            if self.rollback_mode
                            else {}
                        ),
                    }
                    if name == "ea-api" and not forward
                    else {}
                ),
                "NetworkSettings": {
                    "Networks": (
                        dict(self.prior_networks)
                        if name == "ea-api" and not forward
                        else {}
                    ),
                    **(
                        dict(self.prior_network_settings_overrides)
                        if name == "ea-api" and not forward
                        else {}
                    ),
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
            capsule_files = [
                Path(argv[index + 1])
                for index, item in enumerate(argv[:-1])
                if item == "-f"
                and argv[index + 1].endswith(".rollback-capsule.compose.json")
            ]
            memorial = (
                any(item.endswith("docker-compose.memorial.yml") for item in argv)
                and "EA_MEMORIAL_IMAGE" in env
            )
            if capsule_files:
                self.rollback_capsule_file = str(capsule_files[-1])
                capsule_document = json.loads(
                    capsule_files[-1].read_text(encoding="utf-8")
                )
                if self.rollback_capsule_render_environment_override is not None:
                    capsule_document["services"]["ea-api"]["environment"] = dict(
                        self.rollback_capsule_render_environment_override
                    )
                stdout = json.dumps(self._normalized_capsule_render(capsule_document))
            elif memorial:
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
            capsule_files = [
                argv[index + 1]
                for index, item in enumerate(argv[:-1])
                if item == "-f"
                and argv[index + 1].endswith(".rollback-capsule.compose.json")
            ]
            self.api_mode = "forward" if memorial else "prior"
            self.api_present = True
            self.rollback_mode = not memorial
            if capsule_files:
                self.rollback_capsule_file = capsule_files[-1]
            if memorial:
                self.forward_files = [
                    argv[index + 1]
                    for index, item in enumerate(argv[:-1])
                    if item == "-f"
                ]
                self.forward_environment_files = [
                    argv[index + 1]
                    for index, item in enumerate(argv[:-1])
                    if item == "--env-file"
                ]
                if self.tamper_capsule_on_forward:
                    capsule_path = Path(self.rollback_capsule_file)
                    capsule_path.write_text("{}\n", encoding="utf-8")
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
    environment = root / ".env"
    environment.write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    environment.chmod(0o600)
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


def test_prepares_sanitized_runtime_environment_before_compose(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release"
    root.mkdir()
    primary = root / ".env"
    local = root / ".env.local"
    primary.write_bytes(
        b"EA_HOST_PORT=8090\nPROPERTYQUARRY_PRIVATE_KEY=propertyquarry-sentinel\n"
    )
    local.write_bytes(b"EA_RUNTIME_SAFE=retained\nEMAILIT_API_KEY=email-sentinel\n")
    primary.chmod(0o600)
    local.chmod(0o600)

    receipt = deploy._prepare_ea_runtime_environment(root)

    runtime_root = root / deploy.EA_RUNTIME_ENV_DIRECTORY
    runtime_primary = runtime_root / deploy.EA_RUNTIME_ENV_FILE
    runtime_local = runtime_root / deploy.EA_RUNTIME_LOCAL_ENV_FILE
    assert receipt["status"] == "prepared"
    assert receipt["output_count"] == 2
    assert receipt["removed_key_count"] == 2
    assert runtime_primary.read_bytes() == b"EA_HOST_PORT=8090\n"
    assert runtime_local.read_bytes() == b"EA_RUNTIME_SAFE=retained\n"
    assert stat.S_IMODE(runtime_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime_primary.stat().st_mode) == 0o600
    assert stat.S_IMODE(runtime_local.stat().st_mode) == 0o600
    assert "propertyquarry-sentinel" not in json.dumps(receipt, sort_keys=True)
    assert "email-sentinel" not in json.dumps(receipt, sort_keys=True)


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
            source_revision = (
                "b" * 40
                if runner.api_mode == "forward"
                else runner.prior_source_revision
            )
            return deploy.HttpResponse(
                200,
                "application/json",
                b'{"status":"ok"}',
                source_revision,
            )
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
                "schema": "ea.manfred_memorial_candidate_runtime.v5",
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
                "candidate_left_running": True,
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
        parsed_url = urllib.parse.urlsplit(url)
        path = parsed_url.path
        if parsed_url.hostname == "127.0.0.1":
            return _local_https_redirect_response(url, method)
        if path == "/openapi.json":
            runner.public_openapi_methods.append(method)
            phase = (
                "rollback"
                if runner.rollback_mode
                else "forward"
                if runner.api_mode == "forward"
                else "prior"
            )
            expected_revision = (
                "b" * 40 if phase == "forward" else runner.prior_source_revision
            )
            override = dict(runner.public_openapi_overrides.get(phase) or {})
            return deploy.HttpResponse(
                int(override.get("status", 404)),
                str(override.get("content_type", "application/json; charset=utf-8")),
                bytes(
                    override.get(
                        "body",
                        b'{"error":{"code":"not_found"}}',
                    )
                ),
                str(override.get("source_revision", expected_revision)),
                headers=dict(override.get("headers") or {}),
            )
        if path != "/memorial/manfred":
            return _public_spatial_response(url, method)
        return _singular_alias_response(method)

    def selected_no_redirect(
        url: str,
        timeout: float,
        method: str,
        public_authority: str = "",
    ) -> deploy.HttpResponse:
        del public_authority
        if urllib.parse.urlsplit(url).path == "/openapi.json":
            return safe_no_redirect(url, timeout, method)
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
    recovery_root = root.parent / ".ea-memorial-deploy-state"
    recovery_root.mkdir(exist_ok=True, mode=0o700)
    recovery_root.chmod(0o700)
    lane.normalization_recovery_journal_path = (
        recovery_root / "api-baseline-normalization-active-recovery.json"
    )
    lane.joint_recovery_journal_path = recovery_root / "joint-active-recovery.json"
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


def test_constructor_loads_release_env_file_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "release"
    root.mkdir()
    parsed_paths: list[Path] = []

    def parse_release_env(path: Path) -> dict[str, str]:
        parsed_paths.append(path)
        return {"EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST": "from-release-env.example"}

    monkeypatch.setattr(deploy, "_parse_env_file", parse_release_env)

    lane = deploy.MemorialDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "memorial-release-env-default"},
        receipt_dir=root / "receipts",
        global_lock_path=root / "memorial.lock",
        durable_root_check=lambda _root: None,
    )

    assert parsed_paths == [root / ".env"]
    assert lane.env_file_values == {
        "EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST": "from-release-env.example"
    }
    assert lane.allowed_public_hosts == ("from-release-env.example",)


def test_constructor_can_skip_release_env_file_without_touching_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "release"
    root.mkdir()
    assert not (root / ".env").exists()

    def reject_release_env_access(_path: Path) -> dict[str, str]:
        raise AssertionError("release .env must not be inspected")

    monkeypatch.setattr(deploy, "_parse_env_file", reject_release_env_access)

    lane = deploy.MemorialDeployLane(
        root=root,
        env={"EA_DEPLOYMENT_ID": "memorial-release-env-optout"},
        load_release_env_file=False,
        receipt_dir=root / "receipts",
        global_lock_path=root / "memorial.lock",
        durable_root_check=lambda _root: None,
    )

    assert lane.env_file_values == {}
    assert lane.allowed_public_hosts == deploy.DEFAULT_PUBLIC_HOSTS


def test_constructor_rejects_non_boolean_release_env_optout(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="load_release_env_file_must_be_bool"):
        deploy.MemorialDeployLane(
            root=tmp_path,
            env={"EA_DEPLOYMENT_ID": "memorial-release-env-invalid"},
            load_release_env_file=1,  # type: ignore[arg-type]
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
    assert "x-forwarded-host" not in request_headers
    assert "x-forwarded-proto" not in request_headers
    assert any(isinstance(handler, deploy._NoRedirectHandler) for handler in handlers)


def test_local_no_redirect_helper_sends_host_without_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []

    class Response:
        status = 308
        headers = {"Location": "https://memorial.example.org/memorials/manfred"}

        @staticmethod
        def read(_limit: int) -> bytes:
            return b""

        @staticmethod
        def getcode() -> int:
            return 308

        @staticmethod
        def close() -> None:
            return None

    class Opener:
        def open(self, request, timeout):  # type: ignore[no-untyped-def]
            del timeout
            requests.append(request)
            return Response()

    monkeypatch.setattr(
        deploy.urllib.request,
        "build_opener",
        lambda *_handlers: Opener(),
    )

    response = deploy._default_http_no_redirect(
        "http://127.0.0.1:8090/memorials/manfred",
        1.0,
        "GET",
        "memorial.example.org",
    )

    assert response.status == 308
    request_headers = {
        str(name).casefold(): str(value)
        for name, value in requests[0].header_items()  # type: ignore[union-attr]
    }
    assert request_headers["host"] == "memorial.example.org"
    assert "x-forwarded-host" not in request_headers
    assert "x-forwarded-proto" not in request_headers


@pytest.mark.parametrize(
    ("status", "location", "reason"),
    [
        (200, "https://memorial.example.org/memorials/manfred", "status_invalid"),
        (308, "/memorials/manfred", "location_invalid"),
        (308, "https://attacker.example/memorials/manfred", "location_invalid"),
    ],
)
def test_local_https_redirect_proof_rejects_noncanonical_first_hop(
    release_root: Path,
    status: int,
    location: str,
    reason: str,
) -> None:
    lane = _lane(release_root, FakeRunner(release_root))
    lane.http_no_redirect = lambda *_args: deploy.HttpResponse(  # type: ignore[method-assign]
        status,
        "text/plain",
        b"",
        headers={"Location": location},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        lane._verify_local_https_redirects(
            "http://127.0.0.1:8090",
            "https://memorial.example.org",
        )


def test_local_https_redirect_proof_rejects_head_body(
    release_root: Path,
) -> None:
    lane = _lane(release_root, FakeRunner(release_root))

    def redirect(url: str, _timeout: float, method: str, _authority: str = ""):
        response = _local_https_redirect_response(url, method)
        if method == "HEAD":
            return deploy.HttpResponse(
                response.status,
                response.content_type,
                b"unexpected",
                response.source_revision,
                response.headers,
            )
        return response

    lane.http_no_redirect = redirect  # type: ignore[method-assign]
    with pytest.raises(deploy.DeployError, match="head_body_invalid"):
        lane._verify_local_https_redirects(
            "http://127.0.0.1:8090",
            "https://memorial.example.org",
        )


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
        config={"Env": [f"{name}={value}" for name, value in container_values.items()]},
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
    runner.rollback_capsule_render_environment_override = {"DRIFTED_VALUE": "changed"}
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="rollback_capsule_render_functional_identity_mismatch:environment",
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
        str(
            release_root / deploy.EA_RUNTIME_ENV_DIRECTORY / deploy.EA_RUNTIME_ENV_FILE
        ),
        str(
            release_root
            / deploy.EA_RUNTIME_ENV_DIRECTORY
            / deploy.EA_RUNTIME_LOCAL_ENV_FILE
        ),
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
    assert receipt["rollback_capsule"]["status"] == "retired_after_pass"
    assert receipt["rollback_recovery"]["status"] == "retired_after_pass"
    assert not lane.rollback_capsule_path.exists()
    assert not lane.joint_recovery_journal_path.exists()
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
    assert len(memorial_probes) == 2
    assert receipt["local_https_redirects"]["route_count"] == 6
    assert receipt["local_https_redirects"]["trusted_proxy_headers_sent"] is False
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
    assert len(candidate_calls) == 1
    assert "--browser-audit" in candidate_calls[0]
    assert "http://127.0.0.1:8090" not in candidate_calls[0]
    assert "https://memorial.example.org" in candidate_calls[0]
    assert {item["origin"] for item in receipt["candidate_verifier"]} == {"public"}
    assert all("base_url" not in item for item in receipt["candidate_verifier"])
    previous = receipt["previous_api"]
    assert "mount_identities" not in previous
    assert "mounts" not in previous
    assert previous["source_revision"] == runner.prior_source_revision
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
    assert promotion["schema"] == "ea.manfred_memorial_candidate_runtime.v5"
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
    bounded_public_endpoint_fields = {
        "path",
        "method",
        "status_code",
        "redirect_count",
        "content_type",
        "media_type",
        "error_code",
        "source_revision",
        "body_bytes",
        "body_sha256",
        "canonical_json_sha256",
    }
    predeploy_public_endpoint = predeploy_openapi["public_endpoint"]
    postdeploy_public_endpoint = postdeploy_openapi["public_endpoint"]
    assert set(predeploy_public_endpoint) == bounded_public_endpoint_fields
    assert set(postdeploy_public_endpoint) == bounded_public_endpoint_fields
    assert predeploy_public_endpoint["source_revision"] == (
        runner.prior_source_revision
    )
    assert postdeploy_public_endpoint["source_revision"] == "b" * 40
    assert predeploy_public_endpoint["method"] == "GET"
    assert postdeploy_public_endpoint["method"] == "GET"
    assert predeploy_public_endpoint["status_code"] == 404
    assert postdeploy_public_endpoint["status_code"] == 404
    assert predeploy_public_endpoint["redirect_count"] == 0
    assert postdeploy_public_endpoint["redirect_count"] == 0
    assert predeploy_openapi["probe"]["source"] == (
        "deployed_api_container_app.openapi"
    )
    assert postdeploy_openapi["probe"]["source"] == (
        "deployed_api_container_app.openapi"
    )
    assert runner.public_openapi_methods == ["GET", "GET"]
    assert "_contract" not in predeploy_openapi
    assert "_contract" not in postdeploy_openapi


def test_runtime_local_tamper_during_bind_revalidation_stops_before_api_up(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_source = release_root / ".env.local"
    local_source.write_bytes(b"EA_LOCAL_SAFE=sealed\n")
    local_source.chmod(0o600)
    runner = FakeRunner(release_root)

    def tampering_validator(
        rendered: Mapping[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        if kwargs.get("expected_snapshot_sha256"):
            runtime_local = (
                release_root
                / deploy.EA_RUNTIME_ENV_DIRECTORY
                / deploy.EA_RUNTIME_LOCAL_ENV_FILE
            )
            runtime_local.write_bytes(b"EA_LOCAL_SAFE=tampered\n")
            runtime_local.chmod(0o600)
        return _passing_bind_source_validator(rendered, **kwargs)

    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="^deployment_input_seal_changed:forward$",
    ):
        _lane(
            release_root,
            runner,
            bind_source_validator=tampering_validator,
        ).deploy()

    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)


def test_out_of_band_api_replacement_stops_before_api_up(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)

    def replacing_validator(
        rendered: Mapping[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        if kwargs.get("expected_snapshot_sha256"):
            runner.prior_container_id = "container-ea-api-replaced"
        return _passing_bind_source_validator(rendered, **kwargs)

    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="^prior_api_changed_before_mutation$",
    ):
        _lane(
            release_root,
            runner,
            bind_source_validator=replacing_validator,
        ).deploy()

    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)


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


@pytest.mark.parametrize(
    ("source_revision_env", "reason"),
    [
        ([], "prior_api_source_revision_missing_or_ambiguous"),
        (
            [
                f"EA_SOURCE_REVISION={'a' * 40}",
                f"EA_SOURCE_REVISION={'b' * 40}",
            ],
            "prior_api_source_revision_missing_or_ambiguous",
        ),
        (["EA_SOURCE_REVISION=not-a-revision"], "prior_api_source_revision_invalid"),
    ],
)
def test_prior_api_source_revision_fails_closed_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_revision_env: list[str],
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    runner.prior_source_revision_env = source_revision_env
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match=reason):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert runner.public_openapi_methods == []
    assert lane.receipt["status"] == "preflight_failed"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"status": 200}, "public_openapi_retirement_status_invalid"),
        (
            {"headers": {"Location": "/docs"}},
            "public_openapi_retirement_redirect_invalid",
        ),
        (
            {"content_type": "text/html"},
            "public_openapi_retirement_content_type_invalid",
        ),
        (
            {"content_type": "application/json; charset=utf-8\nX-Leak: value"},
            "public_openapi_retirement_content_type_invalid",
        ),
        (
            {"body": b'{"error":{"code":"still_public"}}'},
            "public_openapi_retirement_error_code_invalid",
        ),
        (
            {"body": b"not-json"},
            "public_openapi_retirement_json_invalid",
        ),
        (
            {"source_revision": "c" * 40},
            "public_openapi_retirement_revision_mismatch",
        ),
        (
            {"body": b"x" * (deploy.MAX_HTTP_BODY_BYTES + 1)},
            "public_openapi_retirement_body_size_invalid",
        ),
    ],
)
def test_public_openapi_retirement_fails_preflight_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, object],
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    runner.public_openapi_overrides["prior"] = override
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match=reason):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert runner.public_openapi_methods == ["GET"]
    assert lane.receipt["status"] == "preflight_failed"


def test_postdeploy_public_openapi_exposure_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.public_openapi_overrides["forward"] = {"status": 200}
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "public_openapi_retirement_status_invalid" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"
    assert receipt["rollback"]["openapi"]["public_endpoint"]["status_code"] == 404
    assert runner.public_openapi_methods == ["GET", "GET", "GET"]


def test_rollback_fails_closed_when_public_openapi_retirement_is_not_restored(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_changed_operation = True
    runner.public_openapi_overrides["rollback"] = {"source_revision": "c" * 40}
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rollback_failed"
    assert "postdeploy_openapi_operation_changed" in receipt["failure"]["reason"]
    assert (
        "public_openapi_retirement_revision_mismatch" in receipt["rollback"]["reason"]
    )
    assert runner.public_openapi_methods == ["GET", "GET", "GET"]


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
        "memorial-release-001.rollback-capsule.compose.json"
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
        "memorial-release-001.rollback-capsule.compose.json"
    ]
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    assert config_call.count(str(release_root / "docker-compose.memorial.yml")) == 1
    assert str(prior_root / "docker-compose.memorial.yml") not in config_call
    assert not any("up" in call for call in runner.calls)


def test_normalized_api_baseline_drops_normalization_only_forward_layer(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-normalized-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    prior_files = (
        "docker-compose.yml",
        "docker-compose.memorial.yml",
        deploy.API_BASELINE_NORMALIZATION_COMPOSE_FILE,
    )
    for filename in prior_files:
        (prior_root / filename).write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=prior_files,
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    monkeypatch.setattr(deploy, "_memorial_rollback_environment", lambda **_kwargs: {})

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    assert receipt["status"] == "preflight_only_pass"
    assert receipt["target_compose_files"] == [
        "docker-compose.yml",
        "docker-compose.memorial.yml",
    ]
    assert receipt["forward_topology_source"]["compose_config_files"] == [
        str(prior_root / filename) for filename in prior_files
    ]
    assert receipt["forward_topology_source"]["prior_memorial_layer_replaced"] is True
    assert (
        receipt["forward_topology_source"]["prior_normalization_layer_dropped"] is True
    )
    assert receipt["rollback_compose_files"] == [
        "memorial-release-001.rollback-capsule.compose.json"
    ]
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    assert str(release_root / "docker-compose.yml") in config_call
    assert config_call.count(str(release_root / "docker-compose.memorial.yml")) == 1
    assert (
        str(prior_root / deploy.API_BASELINE_NORMALIZATION_COMPOSE_FILE)
        not in config_call
    )
    assert (
        str(release_root / deploy.API_BASELINE_NORMALIZATION_COMPOSE_FILE)
        not in config_call
    )
    assert not any("up" in call for call in runner.calls)


def test_normalization_only_forward_layer_rejects_nested_path(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-normalized-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=(f"nested/{deploy.API_BASELINE_NORMALIZATION_COMPOSE_FILE}",),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="forward_baseline_normalization_path_invalid",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

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
            return deploy.HttpResponse(
                200,
                "application/json",
                b'{"status":"ok"}',
                "b" * 40,
            )
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
    assert "rollback-capsule.compose.json" in " ".join(rollback)
    assert "docker-compose.yml" not in " ".join(rollback)
    assert "docker-compose.prod.yml" not in " ".join(rollback)
    payload = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed_rolled_back"
    assert payload["rollback_capsule"]["status"] == ("retired_after_verified_rollback")
    assert payload["rollback_recovery"]["status"] == ("retired_after_verified_rollback")
    assert not lane.rollback_capsule_path.exists()
    assert not lane.joint_recovery_journal_path.exists()
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
    assert rollback_openapi["probe"]["source"] == ("deployed_api_container_app.openapi")
    assert rollback_openapi["public_endpoint"]["source_revision"] == (
        runner.prior_source_revision
    )
    assert rollback_openapi["public_endpoint"]["method"] == "GET"
    assert rollback_openapi["public_endpoint"]["status_code"] == 404
    assert rollback_openapi["public_endpoint"]["redirect_count"] == 0
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


def test_rollback_replays_only_the_sealed_capsule(
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
    assert str(release_root / "docker-compose.yml") not in rollback
    assert str(release_root / "docker-compose.prod.yml") not in rollback
    assert any(item.endswith(".rollback-capsule.compose.json") for item in rollback)
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["rollback"]["compose_config_files"] == [
        str(lane.rollback_capsule_path)
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


def test_deployed_surface_requires_revision_bearing_local_health(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)

    def missing_revision_http(url: str, timeout: float) -> deploy.HttpResponse:
        del timeout
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        raise AssertionError("local health failure must stop later probes")

    lane = _lane(release_root, runner, http_get=missing_revision_http)

    with pytest.raises(deploy.DeployError, match="source_revision_mismatch"):
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
            return deploy.HttpResponse(
                200,
                "application/json",
                b'{"status":"ok"}',
                "b" * 40,
            )
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
        if urllib.parse.urlsplit(url).hostname == "127.0.0.1":
            return _local_https_redirect_response(url, method)
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

    assert ("http://127.0.0.1:8090/health", "") in observed_requests
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
    local_transport = lane.receipt["local_https_redirects"]
    assert local_transport["status"] == "pass"
    assert local_transport["trusted_proxy_headers_sent"] is False
    assert local_transport["route_count"] == 6
    assert set(local_transport["routes"]) == {
        f"{label}_{method}"
        for label in ("canonical_html", "canonical_json", "singular_alias")
        for method in ("get", "head")
    }
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
        "source_revision_header_verified",
    }
    assert spatial["routes"]["version_get"]["source_revision_header_verified"] is True
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
        if urllib.parse.urlsplit(url).hostname == "127.0.0.1":
            return _local_https_redirect_response(url, method)
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
    assert len(candidate_calls) == 1
    candidate_call = candidate_calls[0]
    assert "--browser-audit" in candidate_call
    assert "--submit-contribution-receipt" not in candidate_call
    assert "--withdraw-contribution-receipt" not in candidate_call
    assert candidate_call[candidate_call.index("--base-url") + 1] == (
        "https://memorial.example.org"
    )
    assert candidate_call[candidate_call.index("--public-origin") + 1] == (
        "https://memorial.example.org"
    )
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "candidate_verifier_contract_failed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_nonzero_public_candidate_verifier_records_no_fake_local_evidence(
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
    assert "candidate_verifier" not in receipt
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
        origin="public",
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
        origin="public",
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
    assert "group_add: !reset []" in raw
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


def test_memorial_compose_override_resets_base_supplemental_groups() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI unavailable")
    version = subprocess.run(  # nosec B603 - read-only fixed Docker command
        ["docker", "compose", "version"],
        cwd=deploy.ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if version.returncode != 0:
        pytest.skip("Docker Compose plugin unavailable")

    completed = subprocess.run(  # nosec B603 - config-only; no daemon mutation
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            deploy.MEMORIAL_COMPOSE_FILE,
            "config",
            "--no-interpolate",
            "--format",
            "json",
        ],
        cwd=deploy.ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Docker Compose memorial config-only probe failed:{completed.returncode}"
        )
    rendered = json.loads(completed.stdout)
    service = dict(rendered["services"])["ea-api"]

    assert service["user"] == "10001:10001"
    assert "group_add" not in service
    assert not any(
        token in completed.args for token in ("up", "start", "create", "run")
    )


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
        match=("memorial_bind_source_access_denied:bind_source_file_not_readable"),
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
        match=("memorial_bind_source_access_denied:bind_source_snapshot_changed"),
    ):
        lane.deploy()

    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["preparation"]["api_mutation_started"] is False


def _configure_observed_live_rollback_posture(runner: FakeRunner, root: Path) -> None:
    mounts = FakeRunner._api_mounts(root, memorial=True)
    runner.prior_mounts_override = mounts
    runner.prior_extra_environment = [
        "CAPSULE_SECRET=private$value\nsecond-line",
        "EMPTY_VALUE=",
    ]
    runner.prior_noncompose_labels = {
        "org.opencontainers.image.revision": "a" * 40,
        "org.opencontainers.image.source": "EA",
        "org.opencontainers.image.title": "EA Runtime",
    }
    runner.prior_config_overrides = {
        "ExposedPorts": {"8090/tcp": {}},
        "Healthcheck": {
            "Test": ["CMD-SHELL", "curl -fsS http://127.0.0.1:8090/health"],
            "Interval": 120_000_000_000,
            "Timeout": 10_000_000_000,
            "Retries": 5,
        },
        "Hostname": "bfa3c4263428",
        "WorkingDir": "/app",
    }
    binds = [
        (
            f"{mount.get('Name') if mount.get('Type') == 'volume' else mount['Source']}:"
            f"{mount['Destination']}:{'rw' if mount['RW'] else 'ro'}"
        )
        for mount in mounts
    ]
    runner.prior_host_config = {
        "Binds": binds,
        "CapDrop": ["ALL"],
        "CgroupnsMode": "private",
        "CpuShares": 512,
        "ExtraHosts": ["host.docker.internal:host-gateway"],
        "GroupAdd": ["1000"],
        "IpcMode": "private",
        "LogConfig": {
            "Type": "json-file",
            "Config": {"max-file": "3", "max-size": "10m"},
        },
        "MaskedPaths": list(
            deploy.ROLLBACK_CAPSULE_ENGINE_SECURITY_DEFAULTS["MaskedPaths"]
        ),
        "Memory": 4 * 1024**3,
        "MemoryReservation": 1024**3,
        "MemorySwap": 8 * 1024**3,
        "NanoCpus": 2_000_000_000,
        "NetworkMode": "ea_default",
        "PidsLimit": 512,
        "PortBindings": {"8090/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8090"}]},
        "ReadonlyPaths": list(
            deploy.ROLLBACK_CAPSULE_ENGINE_SECURITY_DEFAULTS["ReadonlyPaths"]
        ),
        "ReadonlyRootfs": True,
        "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
        "Runtime": "runc",
        "SecurityOpt": ["no-new-privileges:true"],
        "ShmSize": 64 * 1024**2,
        "Tmpfs": {"/run": "", "/tmp": ""},
    }
    runner.prior_networks = {
        "ea_default": {
            "Aliases": ["ea-api", "ea-api"],
            "DNSNames": ["ea-api", "container-ea-api"],
            "EndpointID": "3" * 64,
            "Gateway": "172.20.0.1",
            "IPAddress": "172.20.0.2",
            "IPPrefixLen": 16,
            "MacAddress": "02:42:ac:14:00:02",
            "NetworkID": "1" * 64,
        },
        "ea_public_ingress": {
            "Aliases": ["ea-api", "ea-api"],
            "DNSNames": ["ea-api", "container-ea-api"],
            "EndpointID": "4" * 64,
            "Gateway": "172.21.0.1",
            "IPAddress": "172.21.0.2",
            "IPPrefixLen": 16,
            "MacAddress": "02:42:ac:15:00:02",
            "NetworkID": "2" * 64,
        },
    }


def _captured_five_layer_live_runner(
    release_root: Path,
    tmp_path: Path,
) -> tuple[FakeRunner, Path, Path]:
    layer_names = deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER
    for index, filename in enumerate(layer_names):
        (release_root / filename).write_text(
            f"services: {{}}\n# trusted-layer-{index}\n",
            encoding="utf-8",
        )
    release_local = release_root / ".env.local"
    release_local.write_bytes(b"EA_PRIOR_LOCAL=retained\nEMAILIT_API_KEY=blocked\n")
    release_local.chmod(0o600)

    prior_root = tmp_path / "trusted-prior-repo"
    prior_root.mkdir()
    prior_primary = prior_root / ".env"
    prior_local = prior_root / ".env.local"
    prior_primary.write_bytes(
        b"EA_HOST_PORT=8090\nPROPERTYQUARRY_PRIVATE_KEY=blocked\n"
    )
    prior_local.write_bytes(b"EA_PRIOR_LOCAL=retained\nEMAILIT_API_KEY=blocked\n")
    prior_primary.chmod(0o600)
    prior_local.chmod(0o600)
    prior_runtime_root = prior_root / deploy.EA_RUNTIME_ENV_DIRECTORY
    prior_runtime_root.mkdir(mode=0o700)
    prior_runtime_root.chmod(0o700)
    for source, filename in (
        (prior_primary, deploy.EA_RUNTIME_ENV_FILE),
        (prior_local, deploy.EA_RUNTIME_LOCAL_ENV_FILE),
    ):
        destination = prior_runtime_root / filename
        destination.write_bytes(deploy.sanitize_env_bytes(source.read_bytes())[0])
        destination.chmod(0o600)

    external_root = tmp_path / "captured-live-compose"
    external_root.mkdir(mode=0o700)
    external_root.chmod(0o700)
    for filename in layer_names:
        destination = external_root / filename
        destination.write_bytes((release_root / filename).read_bytes())
        destination.chmod(0o600)
    environment_files = tuple(
        str(prior_runtime_root / filename)
        for filename in (
            deploy.EA_RUNTIME_ENV_FILE,
            deploy.EA_RUNTIME_LOCAL_ENV_FILE,
        )
    )
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_config_root=external_root,
        baseline_files=layer_names,
        baseline_environment_files=environment_files,
    )
    return runner, prior_root, external_root


def _recovered_capsule_live_runner(
    release_root: Path,
) -> tuple[FakeRunner, Path, Path]:
    for index, filename in enumerate(deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER):
        (release_root / filename).write_text(
            f"services: {{}}\n# recovery-bridge-layer-{index}\n",
            encoding="utf-8",
        )
    release_local = release_root / ".env.local"
    release_local.write_bytes(b"EA_RECOVERY_BRIDGE_LOCAL=retained\n")
    release_local.chmod(0o600)

    receipt_root = release_root / ".runtime" / "deployments" / "memorial"
    receipt_root.mkdir(parents=True, mode=0o700)
    receipt_root.chmod(0o700)
    historical_deployment_id = "manfred-recovery-source-001"
    capsule_path = receipt_root / (
        f"{historical_deployment_id}{deploy.ROLLBACK_CAPSULE_FILE_SUFFIX}"
    )
    runner = FakeRunner(
        release_root,
        baseline_root=receipt_root,
        baseline_config_root=receipt_root,
        baseline_files=(capsule_path.name,),
    )
    _configure_observed_live_rollback_posture(runner, release_root)
    builder = _lane(
        release_root,
        runner,
        deployment_id=historical_deployment_id,
        receipt_dir=receipt_root,
    )
    inspection = json.loads(
        runner.run(
            ["docker", "inspect", "ea-api"],
            cwd=release_root,
            env={},
        ).stdout
    )[0]
    document, _identity = builder._build_rollback_capsule(inspection)
    document["x-ea-rollback-capsule"]["source_container_id_sha256"] = "8" * 64
    capsule_path.write_bytes(
        (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    capsule_path.chmod(0o600)
    runner.calls.clear()
    runner.call_envs.clear()
    return runner, receipt_root, capsule_path


def _rewrite_recovery_capsule(
    capsule_path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    document = json.loads(capsule_path.read_text(encoding="utf-8"))
    mutate(document)
    capsule_path.write_bytes(
        (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    capsule_path.chmod(0o600)


def test_recovered_capsule_topology_uses_only_canonical_release_layers(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, receipt_root, capsule_path = _recovered_capsule_live_runner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner, receipt_dir=receipt_root).deploy(
        preflight_only=True
    )

    expected_layers = list(deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER)
    assert receipt["status"] == "preflight_only_pass"
    assert receipt["target_compose_files"] == expected_layers
    topology = receipt["forward_topology_source"]
    assert topology["working_dir"] == str(receipt_root)
    assert topology["compose_config_files"] == [str(capsule_path)]
    assert topology["compose_environment_files"] == []
    assert (
        topology["mapping"]
        == "verified_recovery_capsule_rebased_to_canonical_release_layers"
    )
    bridge = topology["verified_recovery_capsule_bridge"]
    assert bridge["status"] == "pass"
    assert bridge["current_live_projection_exact"] is True
    assert bridge["capsule_bytes_used_as_forward_input"] is False
    assert bridge["two_sample_seal_verified"] is True
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    configured_layers = [
        config_call[index + 1]
        for index, item in enumerate(config_call[:-1])
        if item == "-f"
    ]
    assert configured_layers == [
        str(release_root / filename) for filename in expected_layers
    ]
    assert str(capsule_path) not in configured_layers
    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("drift", "reason"),
    [
        ("runtime", "forward_recovery_capsule_runtime_projection_mismatch"),
        ("image", "forward_recovery_capsule_image_mismatch"),
        (
            "functional_identity",
            "forward_recovery_capsule_functional_identity_mismatch",
        ),
        (
            "external_resources",
            "forward_recovery_capsule_external_resources_mismatch",
        ),
        (
            "allowed_differences",
            "forward_recovery_capsule_allowed_differences_invalid",
        ),
        ("deployment_path", "forward_recovery_capsule_deployment_path_mismatch"),
        ("noncanonical", "forward_recovery_capsule_json_noncanonical"),
        ("duplicate_key", "forward_recovery_capsule_json_invalid"),
        ("nonfinite", "forward_recovery_capsule_json_invalid"),
        ("source_container_hash", "forward_recovery_capsule_extension_invalid"),
        (
            "release_head",
            "forward_external_bridge_release_head_blob_mismatch",
        ),
        ("mode", "forward_recovery_capsule_file_mode_invalid"),
        (
            "environment_label",
            "forward_recovery_capsule_environment_label_invalid",
        ),
        ("symlink", "forward_recovery_capsule_file_invalid"),
    ],
)
def test_recovered_capsule_topology_rejects_drift_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    reason: str,
) -> None:
    runner, receipt_root, capsule_path = _recovered_capsule_live_runner(release_root)
    if drift == "runtime":
        _rewrite_recovery_capsule(
            capsule_path,
            lambda document: document["services"]["ea-api"]["environment"].update(
                {"RECOVERY_DRIFT": "1"}
            ),
        )
    elif drift == "image":
        _rewrite_recovery_capsule(
            capsule_path,
            lambda document: document["x-ea-rollback-capsule"].update(
                {"source_image_reference": "ea-runtime:other"}
            ),
        )
    elif drift == "functional_identity":

        def mutate_identity(document: dict[str, object]) -> None:
            extension = document["x-ea-rollback-capsule"]
            identity = extension["functional_identity"]
            domains = identity["domains"]
            domains["environment"]["count"] += 1
            identity["functional_identity_sha256"] = deploy._canonical_json_sha256(
                domains
            )

        _rewrite_recovery_capsule(capsule_path, mutate_identity)
    elif drift == "external_resources":

        def mutate_resources(document: dict[str, object]) -> None:
            resources = document["x-ea-rollback-capsule"]["external_resources"]
            resources["networks"][0]["network_id"] = "9" * 64

        _rewrite_recovery_capsule(capsule_path, mutate_resources)
    elif drift == "allowed_differences":
        _rewrite_recovery_capsule(
            capsule_path,
            lambda document: document["x-ea-rollback-capsule"].update(
                {"allowed_runtime_differences": ["container_id"]}
            ),
        )
    elif drift == "deployment_path":
        _rewrite_recovery_capsule(
            capsule_path,
            lambda document: document["x-ea-rollback-capsule"].update(
                {"deployment_id": "different-recovery-source-001"}
            ),
        )
    elif drift == "noncanonical":
        capsule_path.write_bytes(b" " + capsule_path.read_bytes())
    elif drift == "duplicate_key":
        payload = capsule_path.read_bytes()
        capsule_path.write_bytes(b'{"name":"ea",' + payload[1:])
    elif drift == "nonfinite":
        capsule_path.write_bytes(
            capsule_path.read_bytes().replace(b'"version":2', b'"version":NaN', 1)
        )
    elif drift == "source_container_hash":
        _rewrite_recovery_capsule(
            capsule_path,
            lambda document: document["x-ea-rollback-capsule"].update(
                {"source_container_id_sha256": "invalid"}
            ),
        )
    elif drift == "release_head":
        runner.head_blob_overrides[deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER[0]] = (
            "0" * 40
        )
    elif drift == "mode":
        capsule_path.chmod(0o640)
    elif drift == "environment_label":
        runner.baseline_environment_files = (str(release_root / ".env"),)
    elif drift == "symlink":
        trusted_copy = release_root / "capsule-copy.json"
        trusted_copy.write_bytes(capsule_path.read_bytes())
        trusted_copy.chmod(0o600)
        capsule_path.unlink()
        capsule_path.symlink_to(trusted_copy)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner, receipt_dir=receipt_root).deploy(
            preflight_only=True
        )

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


@pytest.mark.parametrize(
    ("drift", "reason"),
    [
        ("capsule", "forward_recovery_capsule_changed_before_mutation"),
        ("directory", "forward_recovery_capsule_changed_before_mutation"),
        ("environment_label", "prior_api_topology_changed_before_mutation"),
        ("topology", "prior_api_topology_changed_before_mutation"),
    ],
)
def test_recovered_capsule_bridge_revalidates_at_mutation_boundary(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    reason: str,
) -> None:
    runner, receipt_root, capsule_path = _recovered_capsule_live_runner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner, receipt_dir=receipt_root)
    context = lane.preflight()
    if drift == "capsule":
        capsule_path.write_bytes(capsule_path.read_bytes() + b" ")
    elif drift == "directory":
        receipt_root.chmod(0o750)
    elif drift == "environment_label":
        runner.baseline_environment_files = (str(release_root / ".env"),)
    else:
        runner.baseline_files = (deploy.MEMORIAL_COMPOSE_FILE,)

    with pytest.raises(deploy.DeployError, match=reason):
        lane._require_previous_api_unchanged(dict(context["previous"]))

    assert not any("up" in call for call in runner.calls)


def test_captured_five_layer_topology_uses_direct_joint_bridge_in_place(
    release_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, prior_root, external_root = _captured_five_layer_live_runner(
        release_root, tmp_path
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    expected_layers = list(deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER)
    assert receipt["status"] == "preflight_only_pass"
    assert receipt["target_compose_files"] == expected_layers
    topology = receipt["forward_topology_source"]
    assert topology["working_dir"] == str(prior_root)
    assert topology["compose_config_files"] == [
        str(external_root / filename) for filename in expected_layers
    ]
    assert topology["trusted_external_bridge"]["status"] == "pass"
    assert (
        topology["trusted_external_bridge"]["bridge"]
        == "direct_joint_without_baseline_normalization"
    )
    assert topology["trusted_external_bridge"]["two_sample_seal_verified"] is True
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    configured_layers = [
        Path(config_call[index + 1]).name
        for index, item in enumerate(config_call[:-1])
        if item == "-f"
    ]
    assert configured_layers == expected_layers
    assert configured_layers.index(deploy.MEMORIAL_COMPOSE_FILE) < (
        configured_layers.index("docker-compose.whatsapp-web-session.yml")
    )
    assert configured_layers.index(deploy.MEMORIAL_COMPOSE_FILE) < (
        configured_layers.index("docker-compose.cloudflared.yml")
    )
    configured_environment = [
        config_call[index + 1]
        for index, item in enumerate(config_call[:-1])
        if item == "--env-file"
    ]
    assert configured_environment == [
        str(
            release_root / deploy.EA_RUNTIME_ENV_DIRECTORY / deploy.EA_RUNTIME_ENV_FILE
        ),
        str(
            release_root
            / deploy.EA_RUNTIME_ENV_DIRECTORY
            / deploy.EA_RUNTIME_LOCAL_ENV_FILE
        ),
    ]
    assert deploy.API_BASELINE_NORMALIZATION_COMPOSE_FILE not in configured_layers
    assert receipt["rollback_compose_files"] == [
        "memorial-release-001.rollback-capsule.compose.json"
    ]
    assert not any("up" in call for call in runner.calls)


def test_captured_five_layer_bridge_replaces_only_prior_memorial_blob(
    release_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _prior_root, external_root = _captured_five_layer_live_runner(
        release_root, tmp_path
    )
    prior_memorial = external_root / deploy.MEMORIAL_COMPOSE_FILE
    prior_memorial.write_bytes(b"services: {}\n# prior-memorial-layer\n")
    prior_memorial.chmod(0o600)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    bridge = receipt["forward_topology_source"]["trusted_external_bridge"]
    seals = {row["basename"]: row for row in bridge["compose_file_seals"]}
    memorial = seals[deploy.MEMORIAL_COMPOSE_FILE]
    assert receipt["status"] == "preflight_only_pass"
    assert bridge["replaceable_layer_basenames"] == [deploy.MEMORIAL_COMPOSE_FILE]
    assert memorial["external_matches_release"] is False
    assert memorial["forward_policy"] == "replace_with_release_head"
    assert all(
        row["external_matches_release"] is True
        and row["forward_policy"] == "require_exact_external_release_blob"
        for name, row in seals.items()
        if name != deploy.MEMORIAL_COMPOSE_FILE
    )
    assert receipt["target_compose_files"] == list(
        deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER
    )
    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("drift", "reason"),
    [
        ("order", "forward_external_bridge_layer_order_invalid"),
        ("name", "forward_baseline_compose_file_unmappable"),
        ("root", "forward_external_bridge_common_root_invalid"),
        ("blob", "forward_external_bridge_compose_blob_mismatch"),
        ("head_blob", "forward_external_bridge_release_head_blob_mismatch"),
        (
            "head_memorial_blob",
            "forward_external_bridge_release_head_blob_mismatch",
        ),
        ("common_root_mode", "forward_external_bridge_common_root_mode_invalid"),
        ("environment_label", "forward_external_bridge_environment_label_invalid"),
        (
            "environment_projection",
            "forward_external_bridge_environment_projection_invalid",
        ),
        (
            "target_environment_projection",
            "forward_external_bridge_environment_projection_mismatch",
        ),
        (
            "environment_mode",
            "forward_external_bridge_environment_file_invalid_mode_invalid",
        ),
        ("symlink", "forward_external_bridge_compose_invalid"),
        ("mode", "forward_external_bridge_compose_mode_invalid"),
        ("untrusted_prior_root", "forward_external_bridge_working_dir_untrusted"),
    ],
)
def test_captured_five_layer_bridge_rejects_drift_before_mutation(
    release_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    reason: str,
) -> None:
    runner, prior_root, external_root = _captured_five_layer_live_runner(
        release_root, tmp_path
    )
    layers = list(deploy.TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER)
    if drift == "order":
        layers[2], layers[3] = layers[3], layers[2]
        runner.baseline_files = tuple(layers)
    elif drift == "name":
        unknown = external_root / "docker-compose.untrusted.yml"
        unknown.write_bytes((external_root / layers[3]).read_bytes())
        unknown.chmod(0o600)
        layers[3] = unknown.name
        runner.baseline_files = tuple(layers)
    elif drift == "root":
        other_root = tmp_path / "other-compose-root"
        other_root.mkdir(mode=0o700)
        other_root.chmod(0o700)
        moved = other_root / layers[-1]
        moved.write_bytes((external_root / layers[-1]).read_bytes())
        moved.chmod(0o600)
        layers[-1] = str(moved)
        runner.baseline_files = tuple(layers)
    elif drift == "blob":
        (external_root / layers[1]).write_bytes(b"services: {drift: true}\n")
    elif drift == "head_blob":
        runner.head_blob_overrides[layers[1]] = "0" * 40
    elif drift == "head_memorial_blob":
        runner.head_blob_overrides[deploy.MEMORIAL_COMPOSE_FILE] = "0" * 40
    elif drift == "common_root_mode":
        external_root.chmod(0o750)
    elif drift == "environment_label":
        runner.baseline_environment_files = tuple(
            reversed(runner.baseline_environment_files or ())
        )
    elif drift == "environment_projection":
        projection = (
            prior_root
            / deploy.EA_RUNTIME_ENV_DIRECTORY
            / deploy.EA_RUNTIME_LOCAL_ENV_FILE
        )
        projection.write_bytes(b"EA_PRIOR_LOCAL=drifted\n")
        projection.chmod(0o600)
    elif drift == "target_environment_projection":
        target_local = release_root / ".env.local"
        target_local.write_bytes(b"EA_PRIOR_LOCAL=target-drifted\n")
        target_local.chmod(0o600)
    elif drift == "environment_mode":
        projection = (
            prior_root
            / deploy.EA_RUNTIME_ENV_DIRECTORY
            / deploy.EA_RUNTIME_LOCAL_ENV_FILE
        )
        projection.chmod(0o640)
    elif drift == "symlink":
        selected = external_root / layers[3]
        selected.unlink()
        selected.symlink_to(release_root / layers[3])
    elif drift == "mode":
        (external_root / layers[3]).chmod(0o640)
    elif drift == "untrusted_prior_root":
        runner.trusted_baseline_root = False
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_split_topology_never_opens_external_compose_or_environment_bytes(
    release_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_working_root = tmp_path / "missing-old-release"
    missing_config_root = tmp_path / "missing-external-config"
    runner = FakeRunner(
        release_root,
        baseline_root=missing_working_root,
        baseline_config_root=missing_config_root,
        baseline_files=("docker-compose.yml", "docker-compose.memorial.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    assert receipt["status"] == "preflight_only_pass"
    assert receipt["forward_topology_source"]["external_layer_basenames"] == [
        "docker-compose.yml",
        "docker-compose.memorial.yml",
    ]
    assert all(
        str(missing_working_root) not in " ".join(call)
        and str(missing_config_root) not in " ".join(call)
        for call in runner.calls
        if "config" in call
    )


def test_unknown_split_topology_layer_fails_before_mutation(
    release_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(
        release_root,
        baseline_root=tmp_path / "old-release",
        baseline_config_root=tmp_path / "external-config",
        baseline_files=("untrusted-compose.yml",),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="forward_baseline_compose_file_unmappable:untrusted-compose.yml",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


def test_capsule_is_private_rendered_and_receipt_redacts_environment_values(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    secret = "private$value\nsecond-line"
    runner.prior_extra_environment = [f"CAPSULE_SECRET={secret}", "EMPTY_VALUE="]
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    context = lane.preflight()

    capsule_metadata = lane.rollback_capsule_path.stat()
    assert stat.S_IMODE(capsule_metadata.st_mode) == 0o600
    assert capsule_metadata.st_nlink == 1
    capsule_text = lane.rollback_capsule_path.read_text(encoding="utf-8")
    assert "private$$value\\nsecond-line" in capsule_text
    receipt_text = lane.receipt_path.read_text(encoding="utf-8")
    assert secret not in receipt_text
    assert "CAPSULE_SECRET" not in receipt_text
    assert context["rollback_render"]["status"] == "pass"
    assert context["rollback_render"]["environment_count"] == 3
    lane._clear_rollback_artifacts(terminal_status="discarded_test")
    assert not lane.rollback_capsule_path.exists()


def test_supplemental_groups_round_trip_through_sealed_capsule(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.prior_host_config["GroupAdd"] = ["1000"]
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    context = lane.preflight()

    capsule = json.loads(lane.rollback_capsule_path.read_text(encoding="utf-8"))
    assert capsule["services"]["ea-api"]["group_add"] == ["1000"]
    assert context["rollback_render"]["status"] == "pass"
    lane._clear_rollback_artifacts(terminal_status="discarded_test")


@pytest.mark.parametrize("group_add", [1000, [1000], [""], ["bad\nvalue"]])
def test_invalid_supplemental_groups_fail_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    group_add: object,
) -> None:
    runner = FakeRunner(release_root)
    runner.prior_host_config["GroupAdd"] = group_add
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match="rollback_capsule_group_add_invalid"):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


def test_supplemental_group_render_drift_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.prior_host_config["GroupAdd"] = ["1000"]

    def drift(rendered: dict[str, object]) -> None:
        services = rendered["services"]
        assert isinstance(services, dict)
        service = services["ea-api"]
        assert isinstance(service, dict)
        service["group_add"] = ["1001"]

    runner.rollback_capsule_render_mutator = drift
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="rollback_capsule_render_functional_identity_mismatch:host_config",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


@pytest.mark.parametrize(
    ("surface", "field", "value", "reason"),
    [
        ("config", "Tty", True, "rollback_capsule_config_field_unsupported:Tty"),
        (
            "host",
            "Privileged",
            True,
            "rollback_capsule_host_field_unsupported:Privileged",
        ),
        (
            "host",
            "Devices",
            [{"PathOnHost": "/dev/null"}],
            "rollback_capsule_host_field_unsupported:Devices",
        ),
    ],
)
def test_unsupported_non_neutral_inspect_field_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    field: str,
    value: object,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    if surface == "config":
        runner.prior_config_overrides[field] = value
    else:
        runner.prior_host_config[field] = value
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


def test_observed_live_posture_maps_to_a_single_render_verified_capsule(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    assert receipt["status"] == "preflight_only_pass"
    capsule = receipt["rollback_capsule"]
    assert capsule["contract_name"] == deploy.ROLLBACK_CAPSULE_CONTRACT_NAME
    assert capsule["mode"] == "0600"
    assert capsule["status"] == "discarded_preflight_only"
    assert len(capsule["functional_identity_sha256"]) == 64
    assert receipt["rollback_render_preflight"]["network_count"] == 2
    assert receipt["previous_api"]["functional_identity"]["version"] == 2
    assert (
        receipt["previous_api"]["functional_identity"]["domains"]["noncompose_labels"][
            "count"
        ]
        == 3
    )
    legacy_identity = dict(receipt["previous_api"]["functional_identity"])
    legacy_identity["version"] = 1
    with pytest.raises(deploy.DeployError, match="test_functional_identity_invalid"):
        deploy.MemorialDeployLane._validated_functional_identity(
            legacy_identity,
            reason_prefix="test",
        )


def test_static_ipv4_network_binding_round_trips_through_sealed_capsule(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    public_endpoint = runner.prior_networks["ea_public_ingress"]
    assert isinstance(public_endpoint, dict)
    public_endpoint["IPAMConfig"] = {"IPv4Address": "172.21.0.3"}
    public_endpoint["IPAddress"] = "172.21.0.3"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    context = lane.preflight()

    capsule = json.loads(lane.rollback_capsule_path.read_text(encoding="utf-8"))
    service_networks = capsule["services"]["ea-api"]["networks"]
    assert [
        options["ipv4_address"]
        for options in service_networks.values()
        if "ipv4_address" in options
    ] == ["172.21.0.3"]
    assert context["rollback_render"]["status"] == "pass"
    assert context["rollback_render"]["network_count"] == 2
    lane._clear_rollback_artifacts(terminal_status="discarded_test")


def test_absent_null_and_empty_ipam_are_identical_dynamic_attachments(
    release_root: Path,
) -> None:
    identities: dict[str, dict[str, object]] = {}
    rendered_networks: dict[str, dict[str, object]] = {}
    for shape in ("absent", "null", "empty"):
        runner = FakeRunner(release_root)
        _configure_observed_live_rollback_posture(runner, release_root)
        public_endpoint = runner.prior_networks["ea_public_ingress"]
        assert isinstance(public_endpoint, dict)
        if shape == "null":
            public_endpoint["IPAMConfig"] = None
        elif shape == "empty":
            public_endpoint["IPAMConfig"] = {}
        inspection = json.loads(
            runner.run(
                ["docker", "inspect", "ea-api"],
                cwd=release_root,
                env={},
            ).stdout
        )[0]
        lane = _lane(release_root, runner)

        document, identity = lane._build_rollback_capsule(inspection)

        identities[shape] = identity
        rendered_networks[shape] = dict(
            dict(document["services"])["ea-api"]["networks"]
        )
        assert all(
            "ipv4_address" not in options
            for options in rendered_networks[shape].values()
        )

    assert identities["absent"] == identities["null"] == identities["empty"]
    assert (
        rendered_networks["absent"]
        == rendered_networks["null"]
        == rendered_networks["empty"]
    )


@pytest.mark.parametrize(
    ("ipam_config", "reason"),
    [
        ({"IPv4Address": ""}, "rollback_capsule_static_ipv4_invalid"),
        ({"IPv4Address": None}, "rollback_capsule_static_ipv4_invalid"),
        ({"IPv4Address": False}, "rollback_capsule_static_ipv4_invalid"),
        (
            {"IPv4Address": "172.21.0.3", "Unexpected": "value"},
            "rollback_capsule_network_ipam_config_unsupported",
        ),
        (
            {"Unexpected": ""},
            "rollback_capsule_network_ipam_config_unsupported",
        ),
        (
            {"IPv4Address": "172.21.0.3", "IPv6Address": ""},
            "rollback_capsule_network_ipam_config_unsupported",
        ),
        (
            {"IPv6Address": "2001:db8::3"},
            "rollback_capsule_network_ipam_config_unsupported",
        ),
        ({"IPv4Address": "2001:db8::3"}, "rollback_capsule_static_ipv4_invalid"),
        ({"IPv4Address": "172.21.0.999"}, "rollback_capsule_static_ipv4_invalid"),
        ({"IPv4Address": 172021003}, "rollback_capsule_static_ipv4_invalid"),
        ("172.21.0.3", "rollback_capsule_network_ipam_config_unsupported"),
    ],
)
def test_unsupported_or_invalid_static_ipam_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    ipam_config: object,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    public_endpoint = runner.prior_networks["ea_public_ingress"]
    assert isinstance(public_endpoint, dict)
    public_endpoint["IPAMConfig"] = ipam_config
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


def test_static_ipv4_render_drift_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    public_endpoint = runner.prior_networks["ea_public_ingress"]
    assert isinstance(public_endpoint, dict)
    public_endpoint["IPAMConfig"] = {"IPv4Address": "172.21.0.3"}

    def perturb(rendered: dict[str, object]) -> None:
        service = dict(rendered["services"])["ea-api"]
        static_options = next(
            options
            for options in service["networks"].values()
            if "ipv4_address" in options
        )
        static_options["ipv4_address"] = "172.21.0.4"

    runner.rollback_capsule_render_mutator = perturb
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="rollback_capsule_render_functional_identity_mismatch:networks",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize("ipv6_address", ["2001:db8::3", ""])
def test_rendered_ipv6_network_binding_is_rejected_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    ipv6_address: str,
) -> None:
    runner = FakeRunner(release_root)

    def perturb(rendered: dict[str, object]) -> None:
        service = dict(rendered["services"])["ea-api"]
        first_options = next(iter(service["networks"].values()))
        first_options["ipv6_address"] = ipv6_address

    _configure_observed_live_rollback_posture(runner, release_root)
    runner.rollback_capsule_render_mutator = perturb
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match=(
            "rollback_capsule_render_service_network_field_unsupported:ipv6_address"
        ),
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    "ipv4_address",
    [False, 0, "", "2001:db8::3", "172.21.0.999"],
)
def test_invalid_rendered_static_ipv4_is_rejected_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    ipv4_address: object,
) -> None:
    runner = FakeRunner(release_root)

    def perturb(rendered: dict[str, object]) -> None:
        service = dict(rendered["services"])["ea-api"]
        first_options = next(iter(service["networks"].values()))
        first_options["ipv4_address"] = ipv4_address

    _configure_observed_live_rollback_posture(runner, release_root)
    runner.rollback_capsule_render_mutator = perturb
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="rollback_capsule_render_static_ipv4_invalid",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_postrollback_host_config_drift_retains_crash_recovery_artifacts(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_host_config_overrides = {"ReadonlyRootfs": True}
    secret = "must-not-enter-receipt"
    runner.prior_extra_environment = [f"CAPSULE_SECRET={secret}"]
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
    with pytest.raises(
        deploy.DeployError,
        match="deployment_and_rollback_failed:.*rollback_functional_identity_mismatch",
    ):
        lane.deploy()

    receipt_text = lane.receipt_path.read_text(encoding="utf-8")
    assert secret not in receipt_text
    assert lane.rollback_capsule_path.exists()
    assert lane.joint_recovery_journal_path.exists()
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "rollback_failed"
    assert receipt["rollback_capsule"]["status"] == "sealed"
    assert receipt["rollback_recovery"]["status"] == "armed"


def test_capsule_drift_after_forward_mutation_fails_closed_and_is_retained(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    runner.tamper_capsule_on_forward = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError,
        match="deployment_and_rollback_failed:.*deployment_input_seal_changed:rollback",
    ):
        lane.deploy()

    assert lane.rollback_capsule_path.exists()
    assert lane.joint_recovery_journal_path.exists()
    assert (
        json.loads(lane.receipt_path.read_text(encoding="utf-8"))["status"]
        == "rollback_failed"
    )


def test_existing_joint_recovery_journal_blocks_before_capsule_or_mutation(
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
    lane.joint_recovery_journal_path.write_text("{}\n", encoding="utf-8")
    lane.joint_recovery_journal_path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError,
        match="api_baseline_normalization_recovery_active_or_indeterminate",
    ):
        lane.deploy()

    assert not lane.rollback_capsule_path.exists()
    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


@pytest.mark.parametrize(
    ("domain", "reason"),
    [
        ("environment", "functional_identity_mismatch:environment"),
        ("healthcheck", "functional_identity_mismatch:healthcheck"),
        ("host_config", "functional_identity_mismatch:host_config"),
        ("image", "render_image_mismatch"),
        ("mounts", "functional_identity_mismatch:mounts"),
        ("networks", "functional_identity_mismatch:networks"),
        ("noncompose_labels", "functional_identity_mismatch:noncompose_labels"),
        ("ports", "functional_identity_mismatch:ports"),
        ("process", "functional_identity_mismatch:process"),
        ("stop_config", "functional_identity_mismatch:stop_config"),
    ],
)
def test_rendered_capsule_perturbation_fails_closed_for_every_runtime_domain(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    domain: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)

    def perturb(rendered: dict[str, object]) -> None:
        service = dict(rendered["services"])["ea-api"]
        if domain == "environment":
            service["environment"]["DOMAIN_DRIFT"] = "1"
        elif domain == "healthcheck":
            service["healthcheck"]["retries"] += 1
        elif domain == "host_config":
            service["read_only"] = False
        elif domain == "image":
            service["image"] = "ea-runtime:unexpected"
        elif domain == "mounts":
            service["volumes"][0]["read_only"] = not bool(
                service["volumes"][0].get("read_only")
            )
        elif domain == "networks":
            first = next(iter(service["networks"].values()))
            first.setdefault("aliases", []).append("domain-drift")
        elif domain == "noncompose_labels":
            service["labels"]["org.opencontainers.image.title"] = "drift"
        elif domain == "ports":
            service["ports"][0]["published"] = 18090
        elif domain == "process":
            service["command"] = [*service["command"], "--domain-drift"]
        elif domain == "stop_config":
            service["stop_signal"] = "SIGUSR1"
        else:  # pragma: no cover - parameter exhaustiveness
            raise AssertionError(domain)

    runner.rollback_capsule_render_mutator = perturb
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)
    assert not any(call[:3] == ["docker", "image", "tag"] for call in runner.calls)


@pytest.mark.parametrize("surface", ["service", "top_level"])
def test_unknown_rendered_non_neutral_field_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    runner = FakeRunner(release_root)

    def perturb(rendered: dict[str, object]) -> None:
        if surface == "service":
            dict(rendered["services"])["ea-api"]["privileged"] = True
        else:
            rendered["secrets"] = {"unexpected": {"external": True}}

    runner.rollback_capsule_render_mutator = perturb
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match="field_unsupported"):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize("surface", ["network_settings", "mount"])
def test_unknown_live_inspect_surface_field_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    runner = FakeRunner(release_root)
    if surface == "network_settings":
        runner.prior_network_settings_overrides["UnexpectedRouteState"] = {
            "gateway": "192.0.2.1"
        }
        reason = "rollback_capsule_network_settings_field_unsupported"
    else:
        mounts = FakeRunner._api_mounts(release_root, memorial=False)
        mounts[0]["UnexpectedMountState"] = "non-neutral"
        runner.prior_mounts_override = mounts
        reason = "rollback_capsule_mount_field_unsupported"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_external_network_identity_is_rechecked_immediately_before_forward_recreate(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    runner.network_resource_id_after_first_inspect["ea_default"] = "9" * 64
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="rollback_external_network_identity_changed"
    ):
        _lane(release_root, runner).deploy()

    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)


def test_real_compose_config_normalization_round_trips_every_runtime_domain(
    release_root: Path,
) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI unavailable")
    version = subprocess.run(  # nosec B603 - read-only fixed Docker command
        ["docker", "compose", "version"],
        cwd=release_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if version.returncode != 0:
        pytest.skip("Docker Compose plugin unavailable")

    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    public_endpoint = runner.prior_networks["ea_public_ingress"]
    assert isinstance(public_endpoint, dict)
    public_endpoint["IPAMConfig"] = {"IPv4Address": "172.21.0.3"}
    public_endpoint["IPAddress"] = "172.21.0.3"
    lane = _lane(release_root, runner)
    inspection = json.loads(
        runner.run(
            ["docker", "inspect", "ea-api"],
            cwd=release_root,
            env={},
        ).stdout
    )[0]
    document, expected_identity = lane._build_rollback_capsule(inspection)
    capsule = lane.receipt_dir / "actual-config-only.compose.json"
    capsule.parent.mkdir(parents=True, exist_ok=True)
    capsule.parent.chmod(0o700)
    capsule.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    capsule.chmod(0o600)
    completed = subprocess.run(  # nosec B603 - config-only; no daemon mutation
        [
            "docker",
            "compose",
            "--project-name",
            "ea",
            "--project-directory",
            str(lane.receipt_dir),
            "-f",
            str(capsule),
            "config",
            "--format",
            "json",
        ],
        cwd=lane.receipt_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        pytest.fail(f"Docker Compose config-only probe failed:{completed.returncode}")
    rendered = json.loads(completed.stdout)
    projected = lane._rollback_render_runtime_projection(
        rendered,
        document,
        image_id=runner.old_image,
        image_config={
            "Env": [],
            "Cmd": ["uvicorn", "app.main:app"],
            "Entrypoint": ["/usr/bin/tini", "--"],
            "User": "10001:10001",
        },
    )

    assert deploy._container_functional_identity(projected) == expected_identity
    rendered_service = dict(rendered["services"])["ea-api"]
    assert rendered_service["group_add"] == ["1000"]
    assert rendered_service["extra_hosts"] == ["host.docker.internal=host-gateway"]
    assert [
        options["ipv4_address"]
        for options in rendered_service["networks"].values()
        if "ipv4_address" in options
    ] == ["172.21.0.3"]
    assert projected["NetworkSettings"]["Networks"]["ea_public_ingress"][
        "IPAMConfig"
    ] == {"IPv4Address": "172.21.0.3"}
    assert not any(
        token in completed.args for token in ("up", "start", "create", "run")
    )


def _arm_test_active_recovery(
    lane: deploy.MemorialDeployLane,
) -> tuple[dict[str, object], str]:
    context = lane.preflight()
    previous = dict(context["previous"])
    rollback_tag = lane._protect_previous_image(previous)
    lane._arm_rollback_recovery(
        previous=previous,
        rollback_tag=rollback_tag,
        non_memorial_controls=dict(context["non_memorial_controls"]),
        public_origin=str(context["public_origin"]),
    )
    return context, rollback_tag


@pytest.mark.parametrize(
    ("persisted_state", "expected_status", "expected_mutations"),
    [
        ("before_recreate", "baseline_already_exact", 0),
        ("during_recreate", "rollback_verified", 1),
        ("after_recreate", "rollback_verified", 1),
    ],
)
def test_recover_active_reconciles_sigkill_equivalent_persisted_states(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    persisted_state: str,
    expected_status: str,
    expected_mutations: int,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    _context, _rollback_tag = _arm_test_active_recovery(lane)
    if persisted_state == "during_recreate":
        runner.api_present = False
    elif persisted_state == "after_recreate":
        runner.api_mode = "forward"
        runner.rollback_mode = False
    before_up = sum("up" in call and call[-1] == "ea-api" for call in runner.calls)
    recovery = _lane(
        release_root,
        runner,
        receipt_dir=lane.receipt_dir,
        global_lock_path=lane.global_lock_path,
    )

    result = recovery.recover_active()

    after_up = sum("up" in call and call[-1] == "ea-api" for call in runner.calls)
    assert result["status"] == expected_status
    assert result["api_mutation_count"] == expected_mutations
    assert after_up - before_up == expected_mutations
    assert "container-ea-api" not in json.dumps(result, sort_keys=True)
    assert "container_id" not in dict(result["verification"])
    assert len(str(dict(result["verification"])["container_id_sha256"])) == 64
    assert not lane.rollback_capsule_path.exists()
    assert not lane.joint_recovery_journal_path.exists()


def test_active_recovery_round_trips_static_ipv4_binding(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    public_endpoint = runner.prior_networks["ea_public_ingress"]
    assert isinstance(public_endpoint, dict)
    public_endpoint["IPAMConfig"] = {"IPv4Address": "172.21.0.3"}
    public_endpoint["IPAddress"] = "172.21.0.3"
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    _arm_test_active_recovery(lane)
    runner.api_present = False
    recovery = _lane(
        release_root,
        runner,
        receipt_dir=lane.receipt_dir,
        global_lock_path=lane.global_lock_path,
    )

    result = recovery.recover_active()

    assert result["status"] == "rollback_verified"
    assert result["api_mutation_count"] == 1
    assert not lane.rollback_capsule_path.exists()
    assert not lane.joint_recovery_journal_path.exists()


def test_active_recovery_accepts_compose_v5_empty_ipam_for_dynamic_restore(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    _configure_observed_live_rollback_posture(runner, release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    context, _rollback_tag = _arm_test_active_recovery(lane)
    expected_identity = dict(dict(context["previous"])["functional_identity"])
    for endpoint in runner.prior_networks.values():
        assert isinstance(endpoint, dict)
        endpoint["IPAMConfig"] = {}
    runner.api_present = False
    recovery = _lane(
        release_root,
        runner,
        receipt_dir=lane.receipt_dir,
        global_lock_path=lane.global_lock_path,
    )

    result = recovery.recover_active()

    restored = json.loads(
        runner.run(
            ["docker", "inspect", "ea-api"],
            cwd=release_root,
            env={},
        ).stdout
    )[0]
    assert result["status"] == "rollback_verified"
    assert result["api_mutation_count"] == 1
    assert deploy._container_functional_identity(restored) == expected_identity
    assert all(
        dict(endpoint).get("IPAMConfig") == {}
        for endpoint in dict(restored["NetworkSettings"]["Networks"]).values()
    )
    assert not lane.rollback_capsule_path.exists()
    assert not lane.joint_recovery_journal_path.exists()


@pytest.mark.parametrize("capsule_present", [True, False])
def test_recover_active_replays_cleanup_capsule_first_and_is_idempotent(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsule_present: bool,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    _arm_test_active_recovery(lane)
    journal = dict(lane._rollback_recovery_document or {})
    journal["status"] = deploy.ROLLBACK_RECOVERY_CLEANUP_STATUS
    journal["terminal_status"] = "retired_after_test_commit"
    journal["cleanup_started_at"] = "2026-07-22T00:00:00Z"
    lane._rollback_recovery_seal = lane._replace_private_artifact(
        lane.joint_recovery_journal_path,
        lane._rollback_recovery_payload(journal),
        dict(lane._rollback_recovery_seal or {}),
        reason_prefix="rollback_recovery_journal",
    )
    lane._rollback_recovery_document = journal
    if not capsule_present:
        lane._remove_private_artifact(
            lane.rollback_capsule_path,
            dict(lane._rollback_capsule_seal or {}),
            reason_prefix="rollback_capsule",
        )
    recovery = _lane(
        release_root,
        runner,
        receipt_dir=lane.receipt_dir,
        global_lock_path=lane.global_lock_path,
    )
    before_up = sum("up" in call for call in runner.calls)

    first = recovery.recover_active()
    second = recovery.recover_active()

    assert first["status"] == "cleanup_replayed"
    assert first["capsule_was_present"] is capsule_present
    assert first["api_mutation_count"] == 0
    assert second == {
        "contract_name": "ea.memorial_api_recovery_result.v1",
        "status": "no_active_recovery",
        "api_mutation_count": 0,
    }
    assert sum("up" in call for call in runner.calls) == before_up
    assert not lane.rollback_capsule_path.exists()
    assert not lane.joint_recovery_journal_path.exists()


def test_active_recovery_journal_is_redacted_and_protected_image_bound(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(release_root)
    secret = "journal-must-not-contain-$-secret"
    runner.prior_extra_environment = [f"PRIVATE_RECOVERY_VALUE={secret}"]
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    _context, rollback_tag = _arm_test_active_recovery(lane)
    journal_text = lane.joint_recovery_journal_path.read_text(encoding="utf-8")

    assert secret not in journal_text
    assert "PRIVATE_RECOVERY_VALUE" not in journal_text
    assert "container-ea-api" not in journal_text
    assert "source_container_id_sha256" in journal_text

    runner.image_refs[rollback_tag] = runner.candidate_image
    recovery = _lane(
        release_root,
        runner,
        receipt_dir=lane.receipt_dir,
        global_lock_path=lane.global_lock_path,
    )
    with pytest.raises(
        deploy.DeployError, match="rollback_recovery_protected_image_mismatch"
    ):
        recovery.recover_active()
    assert lane.rollback_capsule_path.exists()
    assert lane.joint_recovery_journal_path.exists()
    assert not any("up" in call and call[-1] == "ea-api" for call in runner.calls)


def test_private_artifact_parent_walk_rejects_symlink_and_fchmods_final_dir(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o755)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(deploy.DeployError, match="directory_unavailable"):
        deploy.MemorialDeployLane._write_private_artifact_once(
            linked / "secret.json",
            b"{}\n",
            reason_prefix="private_test",
        )

    seal = deploy.MemorialDeployLane._write_private_artifact_once(
        real / "secret.json",
        b"{}\n",
        reason_prefix="private_test",
    )
    assert stat.S_IMODE(real.stat().st_mode) == 0o700
    assert seal["mode"] == "0600"


def test_private_artifact_parent_walk_allows_same_inode_child_churn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    artifact = private / "secret.json"
    deploy.MemorialDeployLane._write_private_artifact_once(
        artifact,
        b"{}\n",
        reason_prefix="private_test",
    )
    real_open = deploy.os.open
    child_created = False

    def open_after_child_churn(
        path: str | bytes | int,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal child_created
        if (
            not child_created
            and path == private.name
            and dir_fd is not None
            and flags & deploy.os.O_DIRECTORY
        ):
            child_created = True
            (private / "unrelated-sibling").write_bytes(b"sibling churn\n")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(deploy.os, "open", open_after_child_churn)

    loaded = deploy.MemorialDeployLane._read_private_artifact(
        artifact,
        reason_prefix="private_test",
    )

    assert child_created is True
    assert loaded is not None
    assert loaded[0] == b"{}\n"
