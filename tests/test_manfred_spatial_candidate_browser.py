from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts import prepare_manfred_memorial_candidate as prepare
from scripts import verify_manfred_spatial_candidate_browser as browser_gate


LABELS = [f"Stop {index}" for index in range(1, 10)]
COMMIT = "a" * 40
SLUG = "tour-slug"
VIEWER_RELPATH = "generated-reconstruction/viewer.html"
RECEIPT_LOCAL_PATHS = [
    "tour.json",
    VIEWER_RELPATH,
    "generated-reconstruction/reconstruction.json",
    "generated-reconstruction/source-floorplan.png",
    "generated-reconstruction/vendor/three.module.js",
    (
        "generated-reconstruction/vendor/examples/jsm/controls/"
        "OrbitControls.js"
    ),
]
RECEIPT_LOCAL_FILES = [
    {"path": path, "sha256": f"{index + 20:064x}", "size_bytes": 100}
    for index, path in enumerate(RECEIPT_LOCAL_PATHS)
]
PACKAGE_SHA256 = prepare._sha256(
    prepare._canonical_json_bytes_without_lf(
        sorted(RECEIPT_LOCAL_FILES, key=lambda row: str(row["path"]))
    )
)


class _FakeButton:
    def __init__(self, page: _FakePage, index: int) -> None:
        self.page = page
        self.index = index

    def count(self) -> int:
        return 1

    def inner_text(self) -> str:
        return self.page.labels[self.index]

    def bounding_box(self) -> dict[str, float]:
        return {"x": 0.0, "y": 0.0, "width": 100.0, "height": 44.0}

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def click(self, *, force: bool, no_wait_after: bool, timeout: int) -> None:
        assert force is True
        assert no_wait_after is True
        assert timeout == 5_000
        self.page.active = self.index

    def evaluate(self, _script: str) -> bool:
        return True

    def get_attribute(self, name: str) -> str:
        assert name == "data-active"
        return "true" if self.page.active == self.index else "false"


class _FakeCanvas:
    def __init__(self, page: _FakePage) -> None:
        self.page = page

    def bounding_box(self) -> dict[str, float]:
        return {"x": 0.0, "y": 0.0, "width": 320.0, "height": 240.0}


class _FakeLiveStatus:
    def __init__(self, page: _FakePage) -> None:
        self.page = page

    def inner_text(self) -> str:
        return f"Room route: {self.page.labels[self.page.active]}"


class _FakePage:
    def __init__(self, labels: list[str], *, static_pixels: bool = False) -> None:
        self.labels = labels
        self.static_pixels = static_pixels
        self.active = -1

    def locator(self, selector: str):  # type: ignore[no-untyped-def]
        if selector == "#viewport canvas":
            return _FakeCanvas(self)
        if selector == "#viewer-live-status":
            return _FakeLiveStatus(self)
        index = int(selector.split("'")[1])
        return _FakeButton(self, index)

    def wait_for_function(self, _script: str, *, arg, timeout: int) -> None:  # type: ignore[no-untyped-def]
        assert timeout == 5_000
        assert self.active == arg["index"]
        assert self.labels[self.active] == arg["label"]

    def evaluate(self, _script: str) -> None:
        return None

    def screenshot(self, **kwargs) -> bytes:  # type: ignore[no-untyped-def]
        assert kwargs["animations"] == "disabled"
        value = 7 if self.static_pixels else self.active + 1
        return bytes([value]) * 128


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("https://127.0.0.1:18090", "base_url_invalid"),
        ("http://example.test:18090", "base_url_invalid"),
        ("http://127.0.0.1", "base_url_invalid"),
        ("http://127.0.0.1:18090/path", "base_url_invalid"),
    ],
)
def test_browser_gate_requires_an_exact_loopback_candidate_origin(
    value: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        browser_gate._loopback_base_url(value)


def test_browser_gate_requires_exact_viewer_path_and_nine_unique_labels() -> None:
    assert (
        browser_gate._safe_viewer_relpath(
            "generated-reconstruction/viewer.html"
        )
        == "generated-reconstruction/viewer.html"
    )
    assert browser_gate._route_labels(LABELS) == LABELS

    with pytest.raises(ValueError, match="viewer_path_invalid"):
        browser_gate._safe_viewer_relpath("generated-reconstruction/debug.html")
    with pytest.raises(ValueError, match="route_labels_invalid"):
        browser_gate._route_labels(LABELS[:-1])
    with pytest.raises(ValueError, match="route_labels_invalid"):
        browser_gate._route_labels([*LABELS[:-1], LABELS[-2]])


def test_browser_gate_requires_all_three_browser_asset_requests() -> None:
    expected = browser_gate._required_request_paths("tour-slug")
    observed = {
        path: {
            "status": 200,
            "content_type": browser_gate._REQUEST_MEDIA_TYPES[role],
        }
        for role, path in expected.items()
    }

    evidence = browser_gate._request_evidence(observed, expected)

    assert set(evidence) == {"floorplan", "orbit_controls", "three_module"}
    observed[expected["floorplan"]]["status"] = 404
    with pytest.raises(RuntimeError, match="asset_request_failed"):
        browser_gate._request_evidence(observed, expected)


def test_browser_gate_binds_asset_requests_to_the_exact_candidate_origin() -> None:
    expected = browser_gate._required_request_paths("tour-slug")
    path = expected["floorplan"]
    assert browser_gate._candidate_required_request_path(
        f"http://127.0.0.1:18090{path}",
        expected_origin="127.0.0.1:18090",
        required_paths=expected,
    ) == path
    for url in (
        f"http://external.test{path}",
        f"https://127.0.0.1:18090{path}",
        f"http://127.0.0.1:18090{path}?cache=other",
    ):
        assert browser_gate._candidate_required_request_path(
            url,
            expected_origin="127.0.0.1:18090",
            required_paths=expected,
        ) is None


def test_route_gate_interacts_all_stops_and_binds_unique_camera_pixels() -> None:
    rows = browser_gate._route_interactions(_FakePage(LABELS), LABELS)

    assert [row["label"] for row in rows] == LABELS
    assert len({row["camera_canvas_screenshot_sha256"] for row in rows}) == 9
    assert all(row["active_state_verified"] is True for row in rows)


def test_route_gate_rejects_static_camera_pixels() -> None:
    with pytest.raises(RuntimeError, match="camera_state_static"):
        browser_gate._route_interactions(
            _FakePage(LABELS, static_pixels=True), LABELS
        )


def _build_local_package(
    tmp_path: Path,
) -> tuple[Path, dict[str, bytes], str, dict[str, dict[str, object]]]:
    assets = {
        VIEWER_RELPATH: b"<!doctype html><canvas></canvas>",
        "generated-reconstruction/reconstruction.json": b'{"proof":true}\n',
        "generated-reconstruction/source-floorplan.png": b"png-bytes",
        "generated-reconstruction/vendor/three.module.js": b"export const T=1;",
        (
            "generated-reconstruction/vendor/examples/jsm/controls/"
            "OrbitControls.js"
        ): b"export const O=1;",
    }
    specs = (
        (VIEWER_RELPATH, "text/html", "viewer_document"),
        (
            "generated-reconstruction/reconstruction.json",
            "application/json",
            "reconstruction_manifest",
        ),
        (
            "generated-reconstruction/source-floorplan.png",
            "image/png",
            "floorplan_texture",
        ),
        (
            "generated-reconstruction/vendor/three.module.js",
            "text/javascript",
            "viewer_module",
        ),
        (
            "generated-reconstruction/vendor/examples/jsm/controls/"
            "OrbitControls.js",
            "text/javascript",
            "viewer_module",
        ),
    )
    bindings = {
        path: {
            "path": path,
            "sha256": hashlib.sha256(assets[path]).hexdigest(),
            "size_bytes": len(assets[path]),
            "mime_type": mime_type,
            "role": role,
        }
        for path, mime_type, role in specs
    }
    tour = {
        "slug": SLUG,
        "generated_reconstruction": {
            "manifest_relpath": (
                "generated-reconstruction/reconstruction.json"
            ),
            "floorplan_relpath": (
                "generated-reconstruction/source-floorplan.png"
            ),
        },
        "generated_viewer_release": {
            "viewer_relpath": VIEWER_RELPATH,
            "release_revision": "test-release-v1",
            "asset_bindings": list(bindings.values()),
        },
    }
    snapshot = {
        "tour.json": prepare._canonical_json_bytes(tour),
        **assets,
    }
    bundle = tmp_path / SLUG
    bundle.mkdir(parents=True)
    for relpath, content in snapshot.items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o644)
    for path in [bundle, *bundle.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
    return bundle, snapshot, prepare._spatial_package_sha256(snapshot), bindings


def test_browser_gate_derives_commit_from_version_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def version_response(  # type: ignore[no-untyped-def]
        _base_url, path, *, expected_status, maximum
    ):
        assert path == "/version"
        assert expected_status == 200
        assert maximum == 64 * 1024
        return (
            json.dumps(
                {"commit_sha": COMMIT, "repository": "EA", "role": "api"}
            ).encode("utf-8"),
            {"content-type": "application/json"},
        )

    monkeypatch.setattr(browser_gate, "_http_get", version_response)
    assert browser_gate._candidate_version(
        "http://127.0.0.1:18090",
        expected_commit=COMMIT,
    )["commit_sha"] == COMMIT
    with pytest.raises(RuntimeError, match="version_mismatch"):
        browser_gate._candidate_version(
            "http://127.0.0.1:18090",
            expected_commit="c" * 40,
        )


@pytest.mark.parametrize(
    ("commit_sha", "content_type"),
    [
        (123, "application/json"),
        (COMMIT, "text/plain; note=application/json"),
    ],
)
def test_browser_gate_rejects_untyped_or_mislabeled_version_evidence(
    monkeypatch: pytest.MonkeyPatch,
    commit_sha: object,
    content_type: str,
) -> None:
    def version_response(  # type: ignore[no-untyped-def]
        _base_url, _path, *, expected_status, maximum
    ):
        assert expected_status == 200
        assert maximum == 64 * 1024
        return (
            json.dumps(
                {"commit_sha": commit_sha, "repository": "EA", "role": "api"}
            ).encode("utf-8"),
            {"content-type": content_type},
        )

    monkeypatch.setattr(browser_gate, "_http_get", version_response)
    with pytest.raises(RuntimeError, match="version_mismatch"):
        browser_gate._candidate_version(
            "http://127.0.0.1:18090",
            expected_commit=COMMIT,
        )


def test_browser_gate_hashes_the_exact_local_package(
    tmp_path: Path,
) -> None:
    bundle, snapshot, digest, bindings = _build_local_package(tmp_path)
    observed, observed_bindings, evidence, root_identity = (
        browser_gate._verified_local_package(
            bundle,
            slug=SLUG,
            viewer_relpath=VIEWER_RELPATH,
            expected_package_sha256=digest,
        )
    )

    assert observed == snapshot
    assert observed_bindings == bindings
    assert evidence["package_sha256"] == digest
    assert evidence["local_file_count"] == 6
    assert evidence["local_root_identity_bound"] is True
    assert len(root_identity) == 2
    with pytest.raises(ValueError, match="package_digest_mismatch"):
        browser_gate._verified_local_package(
            bundle,
            slug=SLUG,
            viewer_relpath=VIEWER_RELPATH,
            expected_package_sha256="f" * 64,
        )


def test_browser_gate_rejects_same_byte_local_package_root_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _snapshot, digest, _bindings = _build_local_package(tmp_path)
    moved = tmp_path / "moved-package"
    original_snapshot = browser_gate._spatial_tree_snapshot
    swapped = False

    def racing_snapshot(root, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal swapped
        result = original_snapshot(root, **kwargs)
        if not swapped:
            Path(root).rename(moved)
            shutil.copytree(moved, root)
            swapped = True
        return result

    monkeypatch.setattr(browser_gate, "_spatial_tree_snapshot", racing_snapshot)
    with pytest.raises(ValueError, match="package_identity_drift"):
        browser_gate._verified_local_package(
            bundle,
            slug=SLUG,
            viewer_relpath=VIEWER_RELPATH,
            expected_package_sha256=digest,
        )
    assert swapped is True


def test_browser_gate_binds_http_assets_to_local_package_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bundle, snapshot, _digest, bindings = _build_local_package(tmp_path)
    prefix = f"/tours/viewer/{SLUG}/"

    def exact_http(  # type: ignore[no-untyped-def]
        _base_url, path, *, expected_status, maximum=browser_gate._MAX_HTTP_BYTES
    ):
        relpath = path.removeprefix(prefix)
        binding = bindings[relpath]
        if binding["role"] == "reconstruction_manifest":
            assert expected_status == 404
            return b'{"detail":"tour_asset_not_found"}', {
                "content-type": "application/json"
            }
        assert expected_status == 200
        return snapshot[relpath], {
            "content-type": str(binding["mime_type"]),
            "x-propertyquarry-asset-sha256": str(binding["sha256"]),
            "x-propertyquarry-viewer-revision": "test-release-v1",
        }

    monkeypatch.setattr(browser_gate, "_http_get", exact_http)
    evidence = browser_gate._http_package_binding(
        "http://127.0.0.1:18090",
        slug=SLUG,
        snapshot=snapshot,
        bindings=bindings,
        release_revision="test-release-v1",
    )
    assert evidence["http_asset_count"] == 4
    assert evidence["http_assets_match_local_package"] is True

    def tampered_http(  # type: ignore[no-untyped-def]
        base_url, path, *, expected_status, maximum=browser_gate._MAX_HTTP_BYTES
    ):
        body, headers = exact_http(
            base_url,
            path,
            expected_status=expected_status,
            maximum=maximum,
        )
        if path.endswith("viewer.html"):
            body += b"tampered"
        return body, headers

    monkeypatch.setattr(browser_gate, "_http_get", tampered_http)
    with pytest.raises(RuntimeError, match="http_package_mismatch"):
        browser_gate._http_package_binding(
            "http://127.0.0.1:18090",
            slug=SLUG,
            snapshot=snapshot,
            bindings=bindings,
            release_revision="test-release-v1",
        )


def _valid_receipt() -> dict[str, object]:
    viewer_path = f"/tours/viewer/{SLUG}/{VIEWER_RELPATH}"
    proof_path = viewer_path.rsplit("/", 1)[0] + "/reconstruction.json"
    required_paths = browser_gate._required_request_paths(SLUG)

    def normal_surface(
        width: int,
        height: int,
        *,
        mobile: bool,
        reduced_motion: bool,
        collect_routes: bool,
    ) -> dict[str, object]:
        interactions = [
            {
                "index": index,
                "label": label,
                "active_state_verified": True,
                "live_region_verified": True,
                "playwright_actionability_verified": True,
                "click_handler_state_change_verified": True,
                "camera_canvas_screenshot_sha256": f"{index + 1:064x}",
            }
            for index, label in enumerate(LABELS)
        ] if collect_routes else []
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
                role: {
                    "path": path,
                    "status": 200,
                    "content_type": browser_gate._REQUEST_MEDIA_TYPES[role],
                }
                for role, path in required_paths.items()
            },
            "route_interactions": interactions,
            "route_interaction_count": len(interactions),
            "camera_state_changes_verified": collect_routes,
            "horizontal_overflow_px": 0,
            "page_error_count": 0,
            "console_error_count": 0,
            "request_failure_count": 0,
            "viewer_subtree_non_2xx_count": 0,
        }

    local_files = copy.deepcopy(RECEIPT_LOCAL_FILES)
    local_by_path = {str(row["path"]): row for row in local_files}
    proof_sha256 = next(
        row["sha256"]
        for row in local_files
        if row["path"] == "generated-reconstruction/reconstruction.json"
    )
    http_specs = (
        (VIEWER_RELPATH, "viewer_document", "text/html"),
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
            "generated-reconstruction/vendor/examples/jsm/controls/"
            "OrbitControls.js",
            "viewer_module",
            "text/javascript",
        ),
    )
    return {
        "schema": browser_gate.RECEIPT_SCHEMA,
        "status": "pass",
        "slug": SLUG,
        "candidate_commit": COMMIT,
        "candidate_commit_source": "GET /version",
        "candidate_version": {
            "path": "/version",
            "status": 200,
            "commit_sha": COMMIT,
            "repository": "EA",
            "role": "api",
            "commit_observed_over_http": True,
        },
        "package_sha256": PACKAGE_SHA256,
        "package_binding": {
            "package_sha256": PACKAGE_SHA256,
            "local_file_count": 6,
            "local_files": local_files,
            "local_package_verified": True,
            "local_root_identity_bound": True,
            "tour_manifest_sha256": str(
                local_by_path["tour.json"]["sha256"]
            ),
            "release_revision": "test-release-v1",
            "http_asset_count": 4,
            "http_assets": [
                {
                    "path": f"/tours/viewer/{SLUG}/{relpath}",
                    "role": role,
                    "status": 200,
                    "sha256": str(local_by_path[relpath]["sha256"]),
                    "size_bytes": int(local_by_path[relpath]["size_bytes"]),
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
                "local_sha256": proof_sha256,
            },
            "runtime_identity_revalidated_after_browser": True,
        },
        "landing": {
            "path": f"/tours/{SLUG}",
            "status": 200,
            "horizontal_overflow_px": 0,
            "viewer_route_referenced": True,
            "page_error_count": 0,
            "console_error_count": 0,
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
                collect_routes=False,
            ),
            "mobile": normal_surface(
                390,
                844,
                mobile=True,
                reduced_motion=False,
                collect_routes=False,
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
                "viewer_status": "not-ready",
                "fallback_visible": True,
                "enabled_route_button_count": 0,
                "enabled_button_count": 0,
                "alert_role": "alert",
                "live_status_role": "status",
                "accessible_fallback_verified": True,
                "horizontal_overflow_px": 0,
                "page_error_count": 0,
                "console_error_count": 0,
            },
        },
        "surface_count": 4,
        "route_stop_count": 9,
        "all_route_stops_interacted": True,
        "camera_state_changes_verified": True,
        "required_asset_requests_verified": True,
        "responsive_overflow_verified": True,
        "page_error_count": 0,
        "console_error_count": 0,
        "request_failure_count": 0,
        "viewer_subtree_non_2xx_count": 0,
        "secret_material_recorded": False,
    }


def _validate_receipt(receipt: dict[str, object]) -> dict[str, object]:
    return browser_gate.validate_spatial_candidate_browser_receipt(
        receipt,
        slug=SLUG,
        viewer_relpath=VIEWER_RELPATH,
        route_labels=LABELS,
        candidate_commit=COMMIT,
        package_sha256=PACKAGE_SHA256,
    )


def test_strict_receipt_validator_accepts_the_complete_bound_receipt() -> None:
    receipt = _valid_receipt()
    assert _validate_receipt(receipt) is receipt


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("schema", "schema_invalid"),
        ("slug", "contract_invalid"),
        ("viewer", "contract_invalid"),
        ("commit", "contract_invalid"),
        ("package", "contract_invalid"),
        ("secret", "contract_invalid"),
        ("proof_as_viewer", "package_invalid"),
        ("duplicate_camera", "surfaces_invalid"),
        ("top_float", "contract_invalid"),
        ("package_float", "package_invalid"),
        ("http_float", "package_invalid"),
        ("proof_float", "proof_invalid"),
        ("request_float", "surfaces_invalid"),
        ("version_float", "version_invalid"),
        ("http_mime", "package_invalid"),
        ("request_mime", "surfaces_invalid"),
        ("landing_bool", "landing_invalid"),
        ("package_proof_bool", "package_invalid"),
        ("proof_bool", "proof_invalid"),
        ("fallback_bool", "surfaces_invalid"),
        ("version_bool", "version_invalid"),
    ],
)
def test_strict_receipt_validator_rejects_unbound_or_partial_evidence(
    mutation: str,
    error: str,
) -> None:
    receipt = copy.deepcopy(_valid_receipt())
    if mutation == "schema":
        receipt.pop("candidate_version")
    elif mutation == "slug":
        receipt["slug"] = "other-tour"
    elif mutation == "viewer":
        receipt["viewer_path"] = "/tours/viewer/other/viewer.html"
    elif mutation == "commit":
        receipt["candidate_commit"] = "c" * 40
    elif mutation == "package":
        receipt["package_sha256"] = "d" * 64
    elif mutation == "secret":
        receipt["secret_material_recorded"] = True
    elif mutation == "proof_as_viewer":
        package = dict(receipt["package_binding"])
        assets = list(package["http_assets"])
        proof_row = next(
            row
            for row in package["local_files"]
            if row["path"] == "generated-reconstruction/reconstruction.json"
        )
        assets[0]["path"] = (
            f"/tours/viewer/{SLUG}/"
            "generated-reconstruction/reconstruction.json"
        )
        assets[0]["sha256"] = proof_row["sha256"]
        assets[0]["size_bytes"] = proof_row["size_bytes"]
    else:
        if mutation == "duplicate_camera":
            surfaces = dict(receipt["surfaces"])
            reduced = dict(surfaces["reduced_motion"])
            interactions = list(reduced["route_interactions"])
            interactions[1]["camera_canvas_screenshot_sha256"] = interactions[0][
                "camera_canvas_screenshot_sha256"
            ]
        elif mutation == "top_float":
            receipt["surface_count"] = 4.0
        elif mutation == "package_float":
            package = receipt["package_binding"]
            assert isinstance(package, dict)
            package["local_file_count"] = 6.0
        elif mutation == "http_float":
            package = dict(receipt["package_binding"])
            list(package["http_assets"])[0]["status"] = 200.0
        elif mutation == "proof_float":
            proof = receipt["proof_manifest"]
            assert isinstance(proof, dict)
            proof["status"] = 404.0
        elif mutation == "request_float":
            surfaces = dict(receipt["surfaces"])
            reduced = dict(surfaces["reduced_motion"])
            requests = dict(reduced["required_requests"])
            floorplan = requests["floorplan"]
            assert isinstance(floorplan, dict)
            floorplan["status"] = 200.0
        elif mutation == "version_float":
            version = receipt["candidate_version"]
            assert isinstance(version, dict)
            version["status"] = 200.0
        elif mutation == "http_mime":
            package = dict(receipt["package_binding"])
            list(package["http_assets"])[0]["content_type"] = "text/plain"
        elif mutation == "request_mime":
            surfaces = dict(receipt["surfaces"])
            reduced = dict(surfaces["reduced_motion"])
            requests = dict(reduced["required_requests"])
            requests["floorplan"]["content_type"] = "text/plain"
        elif mutation == "landing_bool":
            landing = receipt["landing"]
            assert isinstance(landing, dict)
            landing["viewer_route_referenced"] = 1
        elif mutation == "package_proof_bool":
            package = receipt["package_binding"]
            assert isinstance(package, dict)
            package_proof = package["proof_manifest"]
            assert isinstance(package_proof, dict)
            package_proof["serveable"] = 0
        elif mutation == "proof_bool":
            proof = receipt["proof_manifest"]
            assert isinstance(proof, dict)
            proof["serveable"] = 0
        elif mutation == "fallback_bool":
            surfaces = receipt["surfaces"]
            assert isinstance(surfaces, dict)
            fallback = surfaces["webgl_fallback"]
            assert isinstance(fallback, dict)
            fallback["fallback_visible"] = 1
        else:
            version = receipt["candidate_version"]
            assert isinstance(version, dict)
            version["commit_observed_over_http"] = 1
    with pytest.raises(RuntimeError, match=error):
        _validate_receipt(receipt)
