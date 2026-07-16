#!/usr/bin/env python3
"""Fail-closed Playwright gate for a live Manfred spatial candidate."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    _canonical_json_bytes_without_lf,
    _open_directory_path_nofollow,
    _sha256,
    _spatial_package_sha256,
    _spatial_release_contract,
    _spatial_tree_snapshot,
    _strict_json_object,
    _validate_project_name,
)
from scripts.measure_memorial_live_browser import (  # noqa: E402
    _resolve_chromium_executable,
)


RECEIPT_SCHEMA = "ea.manfred_spatial_candidate_browser.v4"
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_REVISION_HEADER = "x-ea-source-revision"
_SINGLETON_EVIDENCE_HEADERS = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        _SOURCE_REVISION_HEADER,
        "x-propertyquarry-asset-sha256",
        "x-propertyquarry-viewer-revision",
    }
)
_EXPECTED_ROUTE_STOP_COUNT = 9
_ROUTE_ACTIONABILITY_TIMEOUT_MS = 30_000
_ROUTE_ACTIONABILITY_DIAGNOSTIC_SCHEMA = "ea.manfred_route_actionability_diagnostic.v1"
_ROUTE_ACTIONABILITY_ERROR = (
    "manfred_candidate_spatial_browser_route_actionability_invalid"
)
_ROUTE_DIAGNOSTIC_TEXT_MAX = 160
_ROUTE_DIAGNOSTIC_COUNT_MAX = 99
_ROUTE_DIAGNOSTIC_COORDINATE_MAX = 100_000.0
_CAMERA_PROBE_TIMEOUT_MS = 45_000
_MAX_HTTP_BYTES = 8 * 1024 * 1024
_REQUEST_MEDIA_TYPES = {
    "floorplan": "image/png",
    "orbit_controls": "text/javascript",
    "three_module": "text/javascript",
}
_RECONSTRUCTION_MANIFEST_RELPATH = "generated-reconstruction/reconstruction.json"
_SURFACES = (
    ("desktop", 1440, 1000, False, False, False),
    ("mobile", 390, 844, True, False, False),
    ("reduced_motion", 1200, 900, False, True, True),
    ("webgl_fallback", 1200, 900, False, False, False),
)
_WEBGL_FALLBACK_INIT = """
(() => {
  const original = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
    const normalized = String(kind || '').toLowerCase();
    if (normalized === 'webgl' || normalized === 'webgl2' ||
        normalized === 'experimental-webgl') {
      return null;
    }
    return original.call(this, kind, ...args);
  };
})();
"""


def _launch_chromium(playwright):  # type: ignore[no-untyped-def]
    """Launch installed Chromium without relying on Playwright's optional shell."""

    executable_path, _executable_source = _resolve_chromium_executable(playwright)
    if not executable_path:
        raise RuntimeError("manfred_candidate_spatial_browser_runtime_unavailable")
    try:
        return playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-proxy-server",
            ],
        )
    except Exception:
        raise RuntimeError("manfred_candidate_spatial_browser_launch_failed") from None


_ROUTE_CAMERA_READY_SCRIPT = """
({index}) => {
  const debug = window.__pqReconstructionDebug;
  if (!debug || typeof debug.getRenderMetrics !== "function") return false;
  const metrics = debug.getRenderMetrics();
  return Boolean(
    metrics &&
    metrics.ready === true &&
    Number(metrics.activeRouteIndex) === Number(index) &&
    metrics.viewMode === "room" &&
    metrics.isTransitioning === false &&
    Number(metrics.frameCount || 0) > 0
  );
}
"""
_ROUTE_ACTIONABILITY_DIAGNOSTIC_SCRIPT = """
({selector}) => {
  const nodes = Array.from(document.querySelectorAll(selector));
  const element = nodes.length === 1 ? nodes[0] : null;
  const bounded = (value, maximum = 160) => String(value || '').slice(0, maximum);
  let elementState = null;
  let hitTest = null;
  let scrollContainer = null;
  if (element) {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const centerX = rect.left + (rect.width / 2);
    const centerY = rect.top + (rect.height / 2);
    const hit = document.elementFromPoint(centerX, centerY);
    const scroller = element.closest('aside');
    elementState = {
      attached: element.isConnected,
      visible: Boolean(
        rect.width > 0 && rect.height > 0 &&
        style.display !== 'none' && style.visibility !== 'hidden' &&
        Number(style.opacity || 1) > 0
      ),
      enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
      bounding_box: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      },
      display: bounded(style.display, 40),
      visibility: bounded(style.visibility, 40),
      pointer_events: bounded(style.pointerEvents, 40),
      opacity: bounded(style.opacity, 40),
    };
    hitTest = {
      tag: bounded(hit && hit.tagName, 40).toLowerCase(),
      classes: bounded(hit && hit.className, 160),
      route_index: bounded(hit && hit.getAttribute && hit.getAttribute('data-route-index'), 20),
      target_matches: Boolean(hit && (hit === element || element.contains(hit))),
    };
    if (scroller) {
      scrollContainer = {
        scroll_top: scroller.scrollTop,
        client_height: scroller.clientHeight,
        scroll_height: scroller.scrollHeight,
      };
    }
  }
  let metrics = null;
  try {
    const debug = window.__pqReconstructionDebug;
    const raw = debug && typeof debug.getRenderMetrics === 'function'
      ? debug.getRenderMetrics()
      : null;
    if (raw && typeof raw === 'object') {
      metrics = {
        active_route_index: raw.activeRouteIndex,
        view_mode: bounded(raw.viewMode, 40),
        is_transitioning: raw.isTransitioning === true,
        frame_count: raw.frameCount,
      };
    }
  } catch (_error) {
    metrics = null;
  }
  return {
    locator_count: nodes.length,
    viewer_status: bounded(document.documentElement.dataset.viewerStatus, 40),
    element: elementState,
    hit_test: hitTest,
    scroll_container: scrollContainer,
    viewer_metrics: metrics,
  };
}
"""
_BOUNDED_CANVAS_SCREENSHOT_SCRIPT = """
element => {
  const gl =
    element.getContext("webgl2") ||
    element.getContext("webgl") ||
    element.getContext("experimental-webgl");
  const attributes = gl && gl.getContextAttributes();
  const bufferWidth = Number(gl && gl.drawingBufferWidth || 0);
  const bufferHeight = Number(gl && gl.drawingBufferHeight || 0);
  const width = Math.min(160, bufferWidth);
  const height = Math.min(96, bufferHeight);
  if (
    !gl ||
    gl.isContextLost() ||
    !attributes ||
    attributes.preserveDrawingBuffer !== true ||
    width < 1 ||
    height < 1
  ) return null;
  const pixels = new Uint8Array(width * height * 4);
  const x = Math.floor((bufferWidth - width) / 2);
  const y = Math.floor((bufferHeight - height) / 2);
  gl.readPixels(x, y, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  if (gl.getError() !== gl.NO_ERROR) return null;
  const proof = document.createElement("canvas");
  proof.width = width;
  proof.height = height;
  const context = proof.getContext("2d");
  if (!context) return null;
  const image = context.createImageData(width, height);
  for (let row = 0; row < height; row += 1) {
    const source = pixels.subarray(
      row * width * 4,
      (row + 1) * width * 4,
    );
    image.data.set(source, (height - row - 1) * width * 4);
  }
  context.putImageData(image, 0, 0);
  return proof.toDataURL("image/png");
}
"""
_VIEWER_STATUS_SCRIPT = """
expected => document.documentElement.dataset.viewerStatus === expected
"""
_VIEWER_STATE_SCRIPT = """
() => {
  const root = document.documentElement;
  const canvas = document.querySelector('#viewport canvas');
  const routeButtons = Array.from(document.querySelectorAll('.route-button'));
  const visibleEnabledButtons = Array.from(document.querySelectorAll('button:not([disabled])'))
    .filter((button) => {
      const rect = button.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
  const horizontalOverflow = Math.max(
    0,
    root.scrollWidth - root.clientWidth,
    document.body ? document.body.scrollWidth - document.body.clientWidth : 0,
  );
  const rect = canvas ? canvas.getBoundingClientRect() : null;
  return {
    viewer_status: String(root.dataset.viewerStatus || ''),
    horizontal_overflow_px: Math.ceil(horizontalOverflow),
    canvas_count: document.querySelectorAll('#viewport canvas').length,
    canvas_visible: Boolean(
      canvas && rect && rect.width > 0 && rect.height > 0 &&
      getComputedStyle(canvas).visibility !== 'hidden' &&
      getComputedStyle(canvas).display !== 'none'
    ),
    canvas_role: canvas ? String(canvas.getAttribute('role') || '') : '',
    canvas_label: canvas ? String(canvas.getAttribute('aria-label') || '') : '',
    route_labels: routeButtons.map((button) => String(button.textContent || '').trim()),
    route_indices: routeButtons.map((button) => String(button.dataset.routeIndex || '')),
    enabled_route_button_count: routeButtons.filter((button) => !button.disabled).length,
    button_count: document.querySelectorAll('button').length,
    enabled_button_count: document.querySelectorAll('button:not([disabled])').length,
    undersized_target_count: visibleEnabledButtons.filter((button) => {
      const rect = button.getBoundingClientRect();
      return rect.width < 44 || rect.height < 44;
    }).length,
    fallback_visible: Boolean(
      document.querySelector('#viewer-fallback') &&
      document.querySelector('#viewer-fallback').getBoundingClientRect().height > 0
    ),
    fallback_role: String(document.querySelector('#viewer-fallback')?.getAttribute('role') || ''),
    fallback_text: String(document.querySelector('#viewer-fallback')?.textContent || '').trim(),
    live_status_role: String(document.querySelector('#viewer-live-status')?.getAttribute('role') || ''),
    live_status_text: String(document.querySelector('#viewer-live-status')?.textContent || '').trim(),
    reduced_motion: matchMedia('(prefers-reduced-motion: reduce)').matches,
  };
}
"""


def _safe_slug(value: object) -> str:
    slug = str(value or "").strip()
    if not _SLUG_RE.fullmatch(slug) or slug in {".", ".."}:
        raise ValueError("manfred_candidate_spatial_browser_slug_invalid")
    return slug


def _safe_viewer_relpath(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or raw != "generated-reconstruction/viewer.html"
    ):
        raise ValueError("manfred_candidate_spatial_browser_viewer_path_invalid")
    return raw


def _loopback_base_url(value: object) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(normalized)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("manfred_candidate_spatial_browser_base_url_invalid")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("manfred_candidate_spatial_browser_base_url_invalid") from exc
    if port is None or not 1024 <= port <= 65535:
        raise ValueError("manfred_candidate_spatial_browser_base_url_invalid")
    return normalized


def _route_labels(value: object) -> list[str]:
    labels = list(value) if isinstance(value, (list, tuple)) else []
    if (
        len(labels) != _EXPECTED_ROUTE_STOP_COUNT
        or len(set(str(label) for label in labels)) != _EXPECTED_ROUTE_STOP_COUNT
        or any(
            not isinstance(label, str)
            or not label.strip()
            or label != label.strip()
            or len(label) > 80
            or not label.isprintable()
            for label in labels
        )
    ):
        raise ValueError("manfred_candidate_spatial_browser_route_labels_invalid")
    return [str(label) for label in labels]


def _commit(value: object) -> str:
    if type(value) is not str:
        raise ValueError("manfred_candidate_spatial_browser_commit_invalid")
    normalized = value.strip().lower()
    if not _COMMIT_RE.fullmatch(normalized):
        raise ValueError("manfred_candidate_spatial_browser_commit_invalid")
    return normalized


def _package_sha256(value: object) -> str:
    if type(value) is not str:
        raise ValueError("manfred_candidate_spatial_browser_package_digest_invalid")
    normalized = value.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError("manfred_candidate_spatial_browser_package_digest_invalid")
    return normalized


def _media_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _response_headers(values: object) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip().lower()
        value = str(raw_value).strip()
        if name in normalized and name in _SINGLETON_EVIDENCE_HEADERS:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_http_header_ambiguous"
            )
        if name in normalized:
            normalized[name] = f"{normalized[name]}, {value}"
        else:
            normalized[name] = value
    return normalized


def _http_get(
    base_url: str,
    path: str,
    *,
    expected_status: int,
    maximum: int = _MAX_HTTP_BYTES,
) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        method="GET",
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "User-Agent": "EA-Manfred-Spatial-Browser-Gate/2.0",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            status = int(response.status or 0)
            body = response.read(maximum + 1)
            headers = _response_headers(response.headers)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(maximum + 1)
        headers = _response_headers(exc.headers)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_http_unreachable"
        ) from exc
    if (
        status != expected_status
        or len(body) > maximum
        or str(headers.get("content-encoding") or "").lower() not in {"", "identity"}
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_http_invalid")
    return body, headers


def _candidate_version(
    base_url: str,
    *,
    expected_commit: str,
    oci_image_revision: str,
) -> dict[str, object]:
    body, headers = _http_get(
        base_url,
        "/version",
        expected_status=200,
        maximum=64 * 1024,
    )
    payload = _strict_json_object(
        body,
        error="manfred_candidate_spatial_browser_version_invalid",
    )
    raw_authority_commit = payload.get("commit_sha")
    raw_runtime_commit = headers.get(_SOURCE_REVISION_HEADER)
    if type(raw_authority_commit) is not str or type(raw_runtime_commit) is not str:
        raise RuntimeError("manfred_candidate_spatial_browser_version_mismatch")
    try:
        body_commit = _commit(raw_authority_commit)
        header_commit = _commit(raw_runtime_commit)
        normalized_expected_commit = _commit(expected_commit)
        image_commit = _commit(oci_image_revision)
    except ValueError as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_version_mismatch"
        ) from exc
    if (
        len(
            {
                body_commit,
                header_commit,
                normalized_expected_commit,
                image_commit,
            }
        )
        != 1
        or payload.get("repository") != "EA"
        or payload.get("role") != "api"
        or payload.get("release_authority_state") != "clear"
        or payload.get("release_authority_posture") != "authoritative_runtime"
        or payload.get("release_authority_source") != "published_status_artifact"
        or _media_type(headers.get("content-type")) != "application/json"
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_version_mismatch")
    return {
        "path": "/version",
        "status": 200,
        "commit_sha": normalized_expected_commit,
        "body_commit_sha": body_commit,
        "source_revision_header": header_commit,
        "expected_commit_sha": normalized_expected_commit,
        "oci_image_revision": image_commit,
        "repository": "EA",
        "role": "api",
        "release_authority_state": "clear",
        "release_authority_posture": "authoritative_runtime",
        "release_authority_source": "published_status_artifact",
        "commit_observed_over_http": True,
        "revision_agreement_verified": True,
    }


def _image_id(value: object) -> str:
    if type(value) is not str or not _IMAGE_ID_RE.fullmatch(value):
        raise ValueError("manfred_candidate_spatial_browser_image_id_invalid")
    return value


def _container_id(value: object) -> str:
    if type(value) is not str or not _CONTAINER_ID_RE.fullmatch(value):
        raise ValueError("manfred_candidate_spatial_browser_container_id_invalid")
    return value


def _candidate_project(
    value: object,
    *,
    error: str = "manfred_candidate_spatial_browser_container_inspection_invalid",
) -> str:
    try:
        return _validate_project_name(value)
    except ValueError as exc:
        raise RuntimeError(error) from exc


def _inspected_oci_image_identity(image_id: str) -> dict[str, object]:
    normalized_image_id = _image_id(image_id)
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", normalized_image_id],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        UnicodeError,
    ) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_image_inspection_invalid"
        ) from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError("manfred_candidate_spatial_browser_image_inspection_invalid")
    row = payload[0]
    if not isinstance(row, dict) or row.get("Id") != normalized_image_id:
        raise RuntimeError("manfred_candidate_spatial_browser_image_inspection_invalid")
    config = row.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        raise RuntimeError("manfred_candidate_spatial_browser_image_inspection_invalid")
    try:
        revision = _commit(labels.get("org.opencontainers.image.revision"))
    except ValueError as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_image_inspection_invalid"
        ) from exc
    return {
        "image_id": normalized_image_id,
        "oci_image_revision": revision,
        "revision_source": "docker_image_inspect_by_immutable_id",
        "immutable_image_id_verified": True,
    }


def _inspected_serving_container_identity(
    container_id: str,
    *,
    image_id: str,
    base_url: str,
) -> dict[str, object]:
    normalized_container_id = _container_id(container_id)
    normalized_image_id = _image_id(image_id)
    normalized_base_url = _loopback_base_url(base_url)
    expected_host_port = urllib.parse.urlsplit(normalized_base_url).port
    if expected_host_port is None:  # pragma: no cover - normalized above
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        )
    try:
        completed = subprocess.run(
            ["docker", "container", "inspect", normalized_container_id],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        payload = json.loads(completed.stdout)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        UnicodeError,
    ) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        ) from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        )
    row = payload[0]
    if (
        not isinstance(row, dict)
        or row.get("Id") != normalized_container_id
        or row.get("Image") != normalized_image_id
    ):
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        )
    config = row.get("Config")
    state = row.get("State")
    network = row.get("NetworkSettings")
    if not all(isinstance(value, dict) for value in (config, state, network)):
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        )
    labels = dict(config).get("Labels")
    project = _candidate_project(dict(labels or {}).get("com.docker.compose.project"))
    service = str(dict(labels or {}).get("com.docker.compose.service") or "")
    ports = dict(network).get("Ports")
    if (
        not isinstance(labels, dict)
        or service != "gateway"
        or dict(state).get("Running") is not True
        or not isinstance(ports, dict)
    ):
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        )
    published: list[tuple[str, str, str]] = []
    for container_port, bindings in ports.items():
        if bindings is None:
            continue
        if not isinstance(container_port, str) or not isinstance(bindings, list):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_container_inspection_invalid"
            )
        for binding in bindings:
            if not isinstance(binding, dict):
                raise RuntimeError(
                    "manfred_candidate_spatial_browser_container_inspection_invalid"
                )
            published.append(
                (
                    container_port,
                    str(binding.get("HostIp") or ""),
                    str(binding.get("HostPort") or ""),
                )
            )
    expected_publication = ("18090/tcp", "127.0.0.1", str(expected_host_port))
    if published != [expected_publication]:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_container_inspection_invalid"
        )
    return {
        "container_id": normalized_container_id,
        "image_id": normalized_image_id,
        "compose_project": project,
        "compose_service": service,
        "running": True,
        "container_port": 18090,
        "host_ip": "127.0.0.1",
        "host_port": expected_host_port,
        "exact_loopback_publication_verified": True,
        "inspection_source": "docker_container_inspect_by_immutable_id",
    }


def _verified_local_package(
    package_dir: Path,
    *,
    slug: str,
    viewer_relpath: str,
    expected_package_sha256: str,
) -> tuple[
    dict[str, bytes],
    dict[str, dict[str, object]],
    dict[str, object],
    tuple[int, int],
]:
    normalized = Path(os.path.abspath(os.fspath(package_dir.expanduser())))
    root_descriptor = _open_directory_path_nofollow(normalized)
    try:
        root_metadata = os.fstat(root_descriptor)
        root_identity = (root_metadata.st_dev, root_metadata.st_ino)
    finally:
        os.close(root_descriptor)
    snapshot = _spatial_tree_snapshot(
        normalized,
        require_sanitized_modes=False,
        expected_root_identity=root_identity,
    )
    try:
        tour_bytes = snapshot["tour.json"]
    except KeyError as exc:
        raise ValueError("manfred_candidate_spatial_browser_package_invalid") from exc
    tour = _strict_json_object(
        tour_bytes,
        error="manfred_candidate_spatial_browser_package_invalid",
    )
    (
        observed_slug,
        asset_paths,
        observed_viewer,
        proof_relpath,
    ) = _spatial_release_contract(tour, expected_slug=slug)
    if (
        normalized.name != observed_slug
        or observed_viewer != viewer_relpath
        or proof_relpath != _RECONSTRUCTION_MANIFEST_RELPATH
        or set(snapshot) != {"tour.json", *asset_paths}
        or len(snapshot) != 6
    ):
        raise ValueError("manfred_candidate_spatial_browser_package_invalid")
    release = dict(tour.get("generated_viewer_release") or {})
    raw_release_revision = release.get("release_revision")
    if (
        type(raw_release_revision) is not str
        or raw_release_revision != raw_release_revision.strip()
        or not raw_release_revision
        or len(raw_release_revision) > 200
        or not raw_release_revision.isprintable()
    ):
        raise ValueError("manfred_candidate_spatial_browser_package_invalid")
    release_revision = raw_release_revision
    bindings: dict[str, dict[str, object]] = {}
    for raw_binding in list(release.get("asset_bindings") or []):
        if not isinstance(raw_binding, dict):
            raise ValueError("manfred_candidate_spatial_browser_package_invalid")
        binding = dict(raw_binding)
        relpath = str(binding.get("path") or "")
        content = snapshot.get(relpath)
        if (
            content is None
            or binding.get("sha256") != _sha256(content)
            or binding.get("size_bytes") != len(content)
            or relpath in bindings
        ):
            raise ValueError("manfred_candidate_spatial_browser_package_invalid")
        bindings[relpath] = binding
    package_digest = _spatial_package_sha256(snapshot)
    if package_digest != expected_package_sha256:
        raise ValueError("manfred_candidate_spatial_browser_package_digest_mismatch")
    local_files = [
        {
            "path": relpath,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for relpath, content in sorted(snapshot.items())
    ]
    final_root_descriptor = _open_directory_path_nofollow(normalized)
    try:
        final_root_metadata = os.fstat(final_root_descriptor)
        if (
            final_root_metadata.st_dev,
            final_root_metadata.st_ino,
        ) != root_identity:
            raise ValueError("manfred_candidate_spatial_browser_package_identity_drift")
    finally:
        os.close(final_root_descriptor)
    return (
        snapshot,
        bindings,
        {
            "package_sha256": package_digest,
            "local_file_count": len(local_files),
            "local_files": local_files,
            "local_package_verified": True,
            "local_root_identity_bound": True,
            "tour_manifest_sha256": _sha256(tour_bytes),
            "release_revision": release_revision,
        },
        root_identity,
    )


def _http_package_binding(
    base_url: str,
    *,
    slug: str,
    snapshot: dict[str, bytes],
    bindings: dict[str, dict[str, object]],
    release_revision: str,
) -> dict[str, object]:
    quoted_slug = urllib.parse.quote(slug, safe="")
    http_assets: list[dict[str, object]] = []
    proof_manifest: dict[str, object] | None = None
    for relpath, binding in sorted(bindings.items()):
        role = str(binding.get("role") or "")
        path = f"/tours/viewer/{quoted_slug}/{urllib.parse.quote(relpath, safe='/')}"
        if role == "reconstruction_manifest":
            body, _headers = _http_get(
                base_url,
                path,
                expected_status=404,
                maximum=64 * 1024,
            )
            if body == snapshot[relpath]:
                raise RuntimeError(
                    "manfred_candidate_spatial_browser_proof_route_exposed"
                )
            proof_manifest = {
                "path": path,
                "status": 404,
                "serveable": False,
                "local_sha256": _sha256(snapshot[relpath]),
            }
            continue
        body, headers = _http_get(
            base_url,
            path,
            expected_status=200,
        )
        digest = _sha256(body)
        expected_digest = str(binding.get("sha256") or "")
        content_type = str(headers.get("content-type") or "")
        expected_mime = str(binding.get("mime_type") or "").strip().lower()
        if (
            body != snapshot[relpath]
            or digest != expected_digest
            or headers.get("x-propertyquarry-asset-sha256") != expected_digest
            or headers.get("x-propertyquarry-viewer-revision") != release_revision
            or _media_type(content_type) != expected_mime
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_http_package_mismatch"
            )
        http_assets.append(
            {
                "path": path,
                "role": role,
                "status": 200,
                "sha256": digest,
                "size_bytes": len(body),
                "content_type": content_type[:120],
                "asset_sha256_header_verified": True,
                "viewer_revision_header_verified": True,
                "body_matches_local_package": True,
            }
        )
    if len(http_assets) != 4 or proof_manifest is None:
        raise RuntimeError("manfred_candidate_spatial_browser_http_package_mismatch")
    return {
        "http_asset_count": len(http_assets),
        "http_assets": http_assets,
        "http_assets_match_local_package": True,
        "proof_manifest": proof_manifest,
    }


def _overflow(page: object) -> int:
    return int(
        page.evaluate(  # type: ignore[attr-defined]
            """
() => Math.ceil(Math.max(
  0,
  document.documentElement.scrollWidth - document.documentElement.clientWidth,
  document.body ? document.body.scrollWidth - document.body.clientWidth : 0,
))
"""
        )
    )


def _required_request_paths(slug: str) -> dict[str, str]:
    quoted_slug = urllib.parse.quote(slug, safe="")
    prefix = f"/tours/viewer/{quoted_slug}/generated-reconstruction"
    return {
        "floorplan": f"{prefix}/source-floorplan.png",
        "orbit_controls": (f"{prefix}/vendor/examples/jsm/controls/OrbitControls.js"),
        "three_module": f"{prefix}/vendor/three.module.js",
    }


def _browser_resource_expectations(
    base_url: str,
    *,
    slug: str,
    viewer_relpath: str,
    snapshot: dict[str, bytes],
) -> dict[str, dict[str, object]]:
    normalized_base_url = _loopback_base_url(base_url)
    quoted_slug = urllib.parse.quote(slug, safe="")
    viewer_path = (
        f"/tours/viewer/{quoted_slug}/{urllib.parse.quote(viewer_relpath, safe='/')}"
    )
    required_paths = _required_request_paths(slug)
    specs = {
        "viewer_document": (viewer_path, viewer_relpath, "text/html"),
        "floorplan": (
            required_paths["floorplan"],
            "generated-reconstruction/source-floorplan.png",
            "image/png",
        ),
        "orbit_controls": (
            required_paths["orbit_controls"],
            ("generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"),
            "text/javascript",
        ),
        "three_module": (
            required_paths["three_module"],
            "generated-reconstruction/vendor/three.module.js",
            "text/javascript",
        ),
    }
    expectations: dict[str, dict[str, object]] = {}
    for role, (path, relpath, content_type) in specs.items():
        content = snapshot.get(relpath)
        if not isinstance(content, bytes) or not content:
            raise ValueError("manfred_candidate_spatial_browser_package_invalid")
        expectations[role] = {
            "url": f"{normalized_base_url}{path}",
            "path": path,
            "relpath": relpath,
            "content_type": content_type,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
    return expectations


def _navigation_evidence(
    page: object,
    response: object | None,
    *,
    expected_url: str,
) -> dict[str, object]:
    status = getattr(response, "status", None)
    response_url = str(getattr(response, "url", "") or "")
    page_url = str(getattr(page, "url", "") or "")
    if (
        type(status) is not int
        or status != 200
        or response_url != expected_url
        or page_url != expected_url
    ):
        raise RuntimeError(
            "manfred_candidate_spatial_browser_navigation_identity_invalid"
        )
    return {
        "page_url": page_url,
        "response_url": response_url,
        "exact_candidate_url_verified": True,
    }


def _browser_response_evidence(
    responses: list[object],
    *,
    expectations: dict[str, dict[str, object]],
    invalid_urls: list[str] | None = None,
) -> dict[str, dict[str, object]]:
    if invalid_urls:
        raise RuntimeError("manfred_candidate_spatial_browser_response_url_invalid")
    expected_by_url = {
        str(row["url"]): (role, row) for role, row in expectations.items()
    }
    observed: dict[str, list[dict[str, object]]] = {role: [] for role in expectations}
    for response in responses:
        url = str(getattr(response, "url", "") or "")
        expected = expected_by_url.get(url)
        if expected is None:
            continue
        role, contract = expected
        status = getattr(response, "status", None)
        headers = getattr(response, "headers", None)
        if type(headers) is not dict:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_response_body_invalid"
            )
        try:
            body = bytes(response.body())  # type: ignore[attr-defined]
        except Exception as exc:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_response_body_invalid"
            ) from exc
        content_type = str(headers.get("content-type") or "")
        digest = _sha256(body)
        if (
            type(status) is not int
            or status != 200
            or _media_type(content_type) != contract["content_type"]
            or digest != contract["sha256"]
            or len(body) != contract["size_bytes"]
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_response_body_mismatch"
            )
        observed[role].append(
            {
                "content_type": _media_type(content_type),
                "sha256": digest,
                "size_bytes": len(body),
            }
        )
    evidence: dict[str, dict[str, object]] = {}
    for role, contract in expectations.items():
        rows = observed[role]
        if not rows or any(row != rows[0] for row in rows):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_response_body_mismatch"
            )
        evidence[role] = {
            "url": contract["url"],
            "path": contract["path"],
            "status": 200,
            "content_type": contract["content_type"],
            "sha256": contract["sha256"],
            "size_bytes": contract["size_bytes"],
            "response_count": len(rows),
            "body_matches_local_package": True,
            "exact_candidate_url_verified": True,
        }
    return evidence


def _request_evidence(
    observed: dict[str, dict[str, object]], expected: dict[str, str]
) -> dict[str, dict[str, object]]:
    evidence: dict[str, dict[str, object]] = {}
    for role, path in sorted(expected.items()):
        row = dict(observed.get(role) or {})
        if (
            row.get("path") != path
            or type(row.get("status")) is not int
            or row.get("status") != 200
            or _media_type(row.get("content_type")) != _REQUEST_MEDIA_TYPES.get(role)
            or not _SHA256_RE.fullmatch(str(row.get("sha256") or ""))
            or type(row.get("size_bytes")) is not int
            or int(row.get("size_bytes") or 0) <= 0
            or type(row.get("response_count")) is not int
            or int(row.get("response_count") or 0) <= 0
            or row.get("body_matches_local_package") is not True
            or row.get("exact_candidate_url_verified") is not True
        ):
            raise RuntimeError("manfred_candidate_spatial_browser_asset_request_failed")
        evidence[role] = row
    return evidence


def _candidate_required_request_path(
    url: object,
    *,
    expected_origin: str,
    required_paths: dict[str, str],
) -> str | None:
    parsed = urllib.parse.urlsplit(str(url))
    if (
        parsed.scheme != "http"
        or parsed.netloc != expected_origin
        or parsed.query
        or parsed.fragment
        or parsed.path not in required_paths.values()
    ):
        return None
    return parsed.path


class _RouteActionabilityError(RuntimeError):
    """Stable public error code with bounded, receipt-safe diagnostics."""

    def __init__(self, diagnostics: dict[str, object]) -> None:
        super().__init__(_ROUTE_ACTIONABILITY_ERROR)
        self.diagnostics = diagnostics


def _bounded_route_diagnostic_text(value: object, *, maximum: int) -> str:
    if type(value) is not str:
        return ""
    normalized = " ".join(value.split())
    printable = "".join(
        character for character in normalized if character.isprintable()
    )
    return printable[:maximum]


def _bounded_route_diagnostic_int(
    value: object,
    *,
    default: int = -1,
    minimum: int = -1,
    maximum: int = 1_000_000_000,
) -> int:
    if type(value) is not int:
        return default
    return max(minimum, min(maximum, value))


def _bounded_route_diagnostic_number(value: object) -> float | None:
    if type(value) not in {int, float}:
        return None
    normalized = float(value)
    if not math.isfinite(normalized):
        return None
    return round(
        max(
            -_ROUTE_DIAGNOSTIC_COORDINATE_MAX,
            min(_ROUTE_DIAGNOSTIC_COORDINATE_MAX, normalized),
        ),
        2,
    )


def _route_actionability_diagnostic_payload(
    *,
    raw: dict[str, object],
    index: int,
    label: str,
    selector: str,
    phase: str,
    locator_count_before_click: int | None,
    cause: Exception,
    collection_status: str,
) -> dict[str, object]:
    raw_element = raw.get("element")
    element = dict(raw_element) if isinstance(raw_element, dict) else {}
    raw_box = element.get("bounding_box")
    box = dict(raw_box) if isinstance(raw_box, dict) else {}
    bounded_box = {
        name: _bounded_route_diagnostic_number(box.get(name))
        for name in ("x", "y", "width", "height")
    }
    if any(value is None for value in bounded_box.values()):
        bounded_box_or_none: dict[str, float | None] | None = None
    else:
        bounded_box_or_none = bounded_box

    raw_hit_test = raw.get("hit_test")
    hit_test = dict(raw_hit_test) if isinstance(raw_hit_test, dict) else {}
    raw_scroll = raw.get("scroll_container")
    scroll = dict(raw_scroll) if isinstance(raw_scroll, dict) else {}
    raw_metrics = raw.get("viewer_metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    try:
        failure_message = str(cause)
    except Exception:
        failure_message = ""
    failure_message_bytes = failure_message.encode("utf-8", errors="replace")
    return {
        "schema": _ROUTE_ACTIONABILITY_DIAGNOSTIC_SCHEMA,
        "collection_status": (
            collection_status if collection_status in {"pass", "failed"} else "failed"
        ),
        "phase": phase if phase in {"locator_count", "click"} else "unknown",
        "route_index": _bounded_route_diagnostic_int(
            index,
            minimum=0,
            maximum=_EXPECTED_ROUTE_STOP_COUNT - 1,
        ),
        "route_label": _bounded_route_diagnostic_text(
            label,
            maximum=80,
        ),
        "selector": _bounded_route_diagnostic_text(
            selector,
            maximum=_ROUTE_DIAGNOSTIC_TEXT_MAX,
        ),
        "failure_type": _bounded_route_diagnostic_text(
            type(cause).__name__,
            maximum=80,
        ),
        "failure_message_sha256": hashlib.sha256(failure_message_bytes).hexdigest(),
        "failure_message_size_bytes": min(len(failure_message_bytes), 1_000_000),
        "locator_count_before_click": _bounded_route_diagnostic_int(
            locator_count_before_click,
            maximum=_ROUTE_DIAGNOSTIC_COUNT_MAX,
        ),
        "locator_count_after_failure": _bounded_route_diagnostic_int(
            raw.get("locator_count"),
            maximum=_ROUTE_DIAGNOSTIC_COUNT_MAX,
        ),
        "viewer_status": _bounded_route_diagnostic_text(
            raw.get("viewer_status"),
            maximum=40,
        ),
        "element": {
            "attached": element.get("attached") is True,
            "visible": element.get("visible") is True,
            "enabled": element.get("enabled") is True,
            "bounding_box": bounded_box_or_none,
            "display": _bounded_route_diagnostic_text(
                element.get("display"), maximum=40
            ),
            "visibility": _bounded_route_diagnostic_text(
                element.get("visibility"), maximum=40
            ),
            "pointer_events": _bounded_route_diagnostic_text(
                element.get("pointer_events"), maximum=40
            ),
            "opacity": _bounded_route_diagnostic_text(
                element.get("opacity"), maximum=40
            ),
        },
        "hit_test": {
            "tag": _bounded_route_diagnostic_text(hit_test.get("tag"), maximum=40),
            "classes": _bounded_route_diagnostic_text(
                hit_test.get("classes"), maximum=_ROUTE_DIAGNOSTIC_TEXT_MAX
            ),
            "route_index": _bounded_route_diagnostic_text(
                hit_test.get("route_index"), maximum=20
            ),
            "target_matches": hit_test.get("target_matches") is True,
        },
        "scroll_container": {
            "scroll_top": _bounded_route_diagnostic_number(scroll.get("scroll_top")),
            "client_height": _bounded_route_diagnostic_number(
                scroll.get("client_height")
            ),
            "scroll_height": _bounded_route_diagnostic_number(
                scroll.get("scroll_height")
            ),
        },
        "viewer_metrics": {
            "active_route_index": _bounded_route_diagnostic_int(
                metrics.get("active_route_index"),
                minimum=-1,
                maximum=_EXPECTED_ROUTE_STOP_COUNT - 1,
            ),
            "view_mode": _bounded_route_diagnostic_text(
                metrics.get("view_mode"), maximum=40
            ),
            "is_transitioning": metrics.get("is_transitioning") is True,
            "frame_count": _bounded_route_diagnostic_int(
                metrics.get("frame_count"),
                default=0,
                minimum=0,
            ),
        },
    }


def _route_actionability_diagnostics(
    page: object,
    *,
    index: int,
    label: str,
    selector: str,
    phase: str,
    locator_count_before_click: int | None,
    cause: Exception,
) -> dict[str, object]:
    raw = page.evaluate(  # type: ignore[attr-defined]
        _ROUTE_ACTIONABILITY_DIAGNOSTIC_SCRIPT,
        {"selector": selector},
    )
    if not isinstance(raw, dict):
        raise RuntimeError("route_actionability_diagnostic_invalid")
    return _route_actionability_diagnostic_payload(
        raw=raw,
        index=index,
        label=label,
        selector=selector,
        phase=phase,
        locator_count_before_click=locator_count_before_click,
        cause=cause,
        collection_status="pass",
    )


def _route_actionability_error(
    page: object,
    *,
    index: int,
    label: str,
    selector: str,
    phase: str,
    locator_count_before_click: int | None,
    cause: Exception,
) -> _RouteActionabilityError:
    try:
        diagnostics = _route_actionability_diagnostics(
            page,
            index=index,
            label=label,
            selector=selector,
            phase=phase,
            locator_count_before_click=locator_count_before_click,
            cause=cause,
        )
    except Exception:
        diagnostics = _route_actionability_diagnostic_payload(
            raw={},
            index=index,
            label=label,
            selector=selector,
            phase=phase,
            locator_count_before_click=locator_count_before_click,
            cause=cause,
            collection_status="failed",
        )
    return _RouteActionabilityError(diagnostics)


def _route_interactions(
    page: object, expected_labels: list[str]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    observed_digests: set[str] = set()
    interaction_order = [*range(1, len(expected_labels)), 0]
    for index in interaction_order:
        label = expected_labels[index]
        selector = f".route-button[data-route-index='{index}']"
        button = page.locator(selector)  # type: ignore[attr-defined]
        locator_count: int | None = None
        phase = "locator_count"
        try:
            raw_locator_count = button.count()
            if type(raw_locator_count) is not int:
                raise RuntimeError("route_button_locator_count_invalid")
            locator_count = raw_locator_count
            if locator_count != 1:
                raise RuntimeError("route_button_locator_count_invalid")
            phase = "click"
            button.click(timeout=_ROUTE_ACTIONABILITY_TIMEOUT_MS)
        except Exception as exc:
            raise _route_actionability_error(
                page,
                index=index,
                label=label,
                selector=selector,
                phase=phase,
                locator_count_before_click=locator_count,
                cause=exc,
            ) from exc
        state_ready = False
        for _attempt in range(50):
            active = page.locator(  # type: ignore[attr-defined]
                f".route-button[data-route-index='{index}']"
            ).get_attribute("data-active")
            live = page.locator("#viewer-live-status").inner_text()  # type: ignore[attr-defined]
            if active == "true" and label in live:
                state_ready = True
                break
            page.wait_for_timeout(100)  # type: ignore[attr-defined]
        if not state_ready:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_route_state_unchanged"
            )
        camera_ready = False
        for _attempt in range(50):
            if (
                page.evaluate(  # type: ignore[attr-defined]
                    _ROUTE_CAMERA_READY_SCRIPT,
                    {"index": index},
                )
                is True
            ):
                camera_ready = True
                break
            page.wait_for_timeout(100)  # type: ignore[attr-defined]
        if not camera_ready:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_route_state_unchanged"
            )
        page.evaluate(  # type: ignore[attr-defined]
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        canvas = page.locator("#viewport canvas")  # type: ignore[attr-defined]
        try:
            data_url = canvas.evaluate(
                _BOUNDED_CANVAS_SCREENSHOT_SCRIPT,
                timeout=_CAMERA_PROBE_TIMEOUT_MS,
            )
        except Exception:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_camera_probe_failed"
            ) from None
        prefix = "data:image/png;base64,"
        if type(data_url) is not str or not data_url.startswith(prefix):
            raise RuntimeError("manfred_candidate_spatial_browser_camera_probe_failed")
        try:
            screenshot = base64.b64decode(
                data_url[len(prefix) :],
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_camera_probe_failed"
            ) from exc
        if not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("manfred_candidate_spatial_browser_camera_probe_failed")
        digest = hashlib.sha256(screenshot).hexdigest()
        if digest in observed_digests:
            raise RuntimeError("manfred_candidate_spatial_browser_camera_state_static")
        observed_digests.add(digest)
        rows.append(
            {
                "index": index,
                "label": label,
                "active_state_verified": True,
                "live_region_verified": True,
                "playwright_actionability_verified": True,
                "click_handler_state_change_verified": True,
                "camera_canvas_screenshot_sha256": digest,
            }
        )
    if len(observed_digests) != _EXPECTED_ROUTE_STOP_COUNT:
        raise RuntimeError("manfred_candidate_spatial_browser_camera_state_static")
    return sorted(rows, key=lambda row: int(row["index"]))


def _assert_route_contract(
    state: dict[str, object], expected_labels: list[str]
) -> None:
    expected_indices = [str(index) for index in range(_EXPECTED_ROUTE_STOP_COUNT)]
    if (
        list(state.get("route_labels") or []) != expected_labels
        or list(state.get("route_indices") or []) != expected_indices
        or int(state.get("enabled_route_button_count") or 0)
        != _EXPECTED_ROUTE_STOP_COUNT
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_route_contract_invalid")


def _wait_for_viewer_status(
    page: object,
    *,
    expected: str,
    timeout_ms: int,
) -> None:
    if expected not in {"ready", "unavailable"}:
        raise ValueError("manfred_candidate_spatial_browser_viewer_status_invalid")
    attempts = max(1, (int(timeout_ms) + 99) // 100)
    for attempt in range(attempts):
        try:
            ready = page.evaluate(  # type: ignore[attr-defined]
                _VIEWER_STATUS_SCRIPT,
                expected,
            )
        except Exception as exc:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_viewer_status_unavailable"
            ) from exc
        if ready is True:
            return
        if attempt + 1 < attempts:
            page.wait_for_timeout(100)  # type: ignore[attr-defined]
    raise RuntimeError("manfred_candidate_spatial_browser_viewer_status_unavailable")


def _audit_landing(browser: object, *, url: str, viewer_path: str) -> dict[str, object]:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})  # type: ignore[attr-defined]
    try:
        page = context.new_page()
        page_errors: list[bool] = []
        console_errors: list[bool] = []
        page.on("pageerror", lambda _error: page_errors.append(True))
        page.on(
            "console",
            lambda message: (
                console_errors.append(True) if message.type == "error" else None
            ),
        )
        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(250)
        navigation = _navigation_evidence(
            page,
            response,
            expected_url=url,
        )
        source = page.content()
        if (
            page_errors
            or console_errors
            or _overflow(page) != 0
            or viewer_path not in source
        ):
            raise RuntimeError("manfred_candidate_spatial_browser_landing_failed")
        return {
            "path": urllib.parse.urlsplit(url).path,
            "status": 200,
            "horizontal_overflow_px": 0,
            "viewer_route_referenced": True,
            "page_error_count": 0,
            "console_error_count": 0,
            **navigation,
        }
    finally:
        context.close()


def _audit_surface(
    browser: object,
    *,
    base_url: str,
    viewer_path: str,
    surface: tuple[str, int, int, bool, bool, bool],
    expected_labels: list[str],
    required_paths: dict[str, str],
    browser_expectations: dict[str, dict[str, object]],
) -> dict[str, object]:
    name, width, height, is_mobile, reduced_motion, collect_routes = surface
    context = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": width, "height": height},
        is_mobile=is_mobile,
        reduced_motion="reduce" if reduced_motion else "no-preference",
    )
    try:
        if name == "webgl_fallback":
            context.add_init_script(_WEBGL_FALLBACK_INIT)
        page = context.new_page()
        page.set_default_timeout(15_000)
        page_errors: list[bool] = []
        console_errors: list[bool] = []
        request_failures: list[bool] = []
        viewer_subtree_non_2xx: list[bool] = []
        observed_responses: list[object] = []
        invalid_response_urls: list[str] = []
        expected_base = urllib.parse.urlsplit(base_url)
        expected_origin = expected_base.netloc
        expected_viewer_url = f"{base_url}{viewer_path}"
        expected_urls_by_path = {
            str(row["path"]): str(row["url"]) for row in browser_expectations.values()
        }
        viewer_prefix = viewer_path.rsplit("/", 1)[0] + "/"
        page.on("pageerror", lambda _error: page_errors.append(True))
        page.on(
            "console",
            lambda message: (
                console_errors.append(True) if message.type == "error" else None
            ),
        )

        def record_response(response: object) -> None:
            parsed = urllib.parse.urlsplit(str(response.url))  # type: ignore[attr-defined]
            path = parsed.path
            status_code = int(response.status)  # type: ignore[attr-defined]
            if (
                parsed.scheme == expected_base.scheme
                and parsed.netloc == expected_origin
                and path.startswith(viewer_prefix)
                and not 200 <= status_code < 300
            ):
                viewer_subtree_non_2xx.append(True)
            expected_url = expected_urls_by_path.get(path)
            if expected_url is None:
                return
            if (
                parsed.scheme != expected_base.scheme
                or parsed.netloc != expected_origin
                or str(response.url) != expected_url  # type: ignore[attr-defined]
            ):
                invalid_response_urls.append(str(response.url))  # type: ignore[attr-defined]
                return
            observed_responses.append(response)

        def record_request_failure(request: object) -> None:
            parsed = urllib.parse.urlsplit(str(request.url))  # type: ignore[attr-defined]
            if (
                parsed.scheme == expected_base.scheme
                and parsed.netloc == expected_origin
                and parsed.path.startswith(viewer_prefix)
            ):
                request_failures.append(True)

        page.on("response", record_response)
        page.on("requestfailed", record_request_failure)
        response = page.goto(
            expected_viewer_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        if (
            response is not None
            and str(response.url) == expected_viewer_url
            and all(item is not response for item in observed_responses)
        ):
            observed_responses.append(response)
        _wait_for_viewer_status(
            page,
            expected="unavailable" if name == "webgl_fallback" else "ready",
            timeout_ms=15_000 if name == "webgl_fallback" else 20_000,
        )
        page.wait_for_load_state("load", timeout=15_000)
        page.wait_for_timeout(250)
        state = dict(page.evaluate(_VIEWER_STATE_SCRIPT))
        navigation = _navigation_evidence(
            page,
            response,
            expected_url=expected_viewer_url,
        )

        def finalize_browser_package_evidence() -> tuple[
            dict[str, dict[str, object]],
            dict[str, object],
            int,
        ]:
            page.wait_for_load_state("networkidle", timeout=15_000)
            page.wait_for_timeout(100)
            context.set_offline(True)
            response_set_before = (
                len(observed_responses),
                len(invalid_response_urls),
                len(request_failures),
                len(viewer_subtree_non_2xx),
            )
            browser_responses = _browser_response_evidence(
                observed_responses,
                expectations=browser_expectations,
                invalid_urls=invalid_response_urls,
            )
            page.wait_for_timeout(100)
            response_set_after = (
                len(observed_responses),
                len(invalid_response_urls),
                len(request_failures),
                len(viewer_subtree_non_2xx),
            )
            if response_set_after != response_set_before:
                raise RuntimeError(
                    "manfred_candidate_spatial_browser_response_set_changed"
                )
            requests = _request_evidence(browser_responses, required_paths)
            viewer_response = dict(browser_responses["viewer_document"])
            browser_response_count = sum(
                int(row["response_count"]) for row in browser_responses.values()
            )
            return (
                requests,
                viewer_response,
                browser_response_count,
            )

        if page_errors or console_errors or request_failures or viewer_subtree_non_2xx:
            raise RuntimeError("manfred_candidate_spatial_browser_surface_failed")
        if int(state.get("horizontal_overflow_px") or 0) != 0:
            raise RuntimeError("manfred_candidate_spatial_browser_overflow")
        if bool(state.get("reduced_motion")) is not reduced_motion:
            raise RuntimeError("manfred_candidate_spatial_browser_motion_mismatch")
        if name == "webgl_fallback":
            if (
                state.get("viewer_status") != "unavailable"
                or state.get("fallback_visible") is not True
                or state.get("fallback_role") != "alert"
                or "3d preview is unavailable"
                not in str(state.get("fallback_text") or "").lower()
                or "floorplan" not in str(state.get("fallback_text") or "").lower()
                or state.get("live_status_role") != "status"
                or "unavailable" not in str(state.get("live_status_text") or "").lower()
                or state.get("enabled_route_button_count") != 0
                or state.get("enabled_button_count") != 0
                or int(state.get("button_count") or 0) < 18
            ):
                raise RuntimeError("manfred_candidate_spatial_browser_fallback_failed")
            (
                requests,
                viewer_response,
                browser_response_count,
            ) = finalize_browser_package_evidence()
            navigation = _navigation_evidence(
                page,
                response,
                expected_url=expected_viewer_url,
            )
            if (
                page_errors
                or console_errors
                or request_failures
                or viewer_subtree_non_2xx
            ):
                raise RuntimeError("manfred_candidate_spatial_browser_surface_failed")
            return {
                "status": 200,
                "viewport": {"width": width, "height": height},
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
                "viewer_response": viewer_response,
                "required_requests": requests,
                "browser_response_count": browser_response_count,
                "browser_consumed_package_verified": True,
                **navigation,
            }
        if state.get("viewer_status") != "ready":
            raise RuntimeError("manfred_candidate_spatial_browser_viewer_not_ready")
        if (
            int(state.get("canvas_count") or 0) != 1
            or state.get("canvas_visible") is not True
            or state.get("canvas_role") != "img"
            or not str(state.get("canvas_label") or "").strip()
        ):
            raise RuntimeError("manfred_candidate_spatial_browser_canvas_invalid")
        _assert_route_contract(state, expected_labels)
        if state.get("undersized_target_count") != 0:
            raise RuntimeError("manfred_candidate_spatial_browser_target_size_invalid")
        if state.get("fallback_visible") is not False:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_fallback_state_invalid"
            )
        route_rows = (
            _route_interactions(page, expected_labels) if collect_routes else []
        )
        page.wait_for_timeout(250)
        (
            requests,
            viewer_response,
            browser_response_count,
        ) = finalize_browser_package_evidence()
        navigation = _navigation_evidence(
            page,
            response,
            expected_url=expected_viewer_url,
        )
        if page_errors or console_errors or request_failures or viewer_subtree_non_2xx:
            raise RuntimeError("manfred_candidate_spatial_browser_surface_failed")
        return {
            "status": 200,
            "viewport": {"width": width, "height": height},
            "mobile": is_mobile,
            "prefers_reduced_motion": reduced_motion,
            "viewer_status": "ready",
            "canvas_ready": True,
            "route_stop_count": _EXPECTED_ROUTE_STOP_COUNT,
            "undersized_target_count": 0,
            "required_requests": requests,
            "route_interactions": route_rows,
            "route_interaction_count": len(route_rows),
            "camera_state_changes_verified": bool(route_rows),
            "horizontal_overflow_px": 0,
            "page_error_count": 0,
            "console_error_count": 0,
            "request_failure_count": 0,
            "viewer_subtree_non_2xx_count": 0,
            "viewer_response": viewer_response,
            "browser_response_count": browser_response_count,
            "browser_consumed_package_verified": True,
            **navigation,
        }
    finally:
        context.close()


def audit_spatial_candidate_browser(
    *,
    base_url: str,
    slug: str,
    viewer_relpath: str,
    route_labels: list[str],
    candidate_commit: str,
    oci_image_id: str,
    serving_container_id: str,
    package_sha256: str,
    package_dir: Path,
) -> dict[str, object]:
    normalized_base_url = _loopback_base_url(base_url)
    normalized_slug = _safe_slug(slug)
    normalized_viewer = _safe_viewer_relpath(viewer_relpath)
    expected_labels = _route_labels(route_labels)
    expected_commit = _commit(candidate_commit)
    oci_image = _inspected_oci_image_identity(oci_image_id)
    serving_container = _inspected_serving_container_identity(
        serving_container_id,
        image_id=str(oci_image["image_id"]),
        base_url=normalized_base_url,
    )
    expected_image_revision = _commit(oci_image["oci_image_revision"])
    expected_package_sha256 = _package_sha256(package_sha256)
    quoted_slug = urllib.parse.quote(normalized_slug, safe="")
    viewer_path = (
        f"/tours/viewer/{quoted_slug}/{urllib.parse.quote(normalized_viewer, safe='/')}"
    )
    landing_path = f"/tours/{quoted_slug}"
    required_paths = _required_request_paths(normalized_slug)
    snapshot, bindings, local_package, package_root_identity = _verified_local_package(
        package_dir,
        slug=normalized_slug,
        viewer_relpath=normalized_viewer,
        expected_package_sha256=expected_package_sha256,
    )
    browser_expectations = _browser_resource_expectations(
        normalized_base_url,
        slug=normalized_slug,
        viewer_relpath=normalized_viewer,
        snapshot=snapshot,
    )
    candidate_version = _candidate_version(
        normalized_base_url,
        expected_commit=expected_commit,
        oci_image_revision=expected_image_revision,
    )
    http_package = _http_package_binding(
        normalized_base_url,
        slug=normalized_slug,
        snapshot=snapshot,
        bindings=bindings,
        release_revision=str(local_package["release_revision"]),
    )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_playwright_unavailable"
        ) from exc

    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright)
        try:
            landing = _audit_landing(
                browser,
                url=f"{normalized_base_url}{landing_path}",
                viewer_path=viewer_path,
            )
            proof_context = browser.new_context()
            try:
                proof_path = viewer_path.rsplit("/", 1)[0] + "/reconstruction.json"
                proof_response = proof_context.request.get(
                    f"{normalized_base_url}{proof_path}",
                    fail_on_status_code=False,
                    timeout=15_000,
                )
                if int(proof_response.status) != 404:
                    raise RuntimeError(
                        "manfred_candidate_spatial_browser_proof_route_exposed"
                    )
                proof_manifest = {
                    "path": proof_path,
                    "status": 404,
                    "serveable": False,
                }
            finally:
                proof_context.close()
            surfaces = {
                surface[0]: _audit_surface(
                    browser,
                    base_url=normalized_base_url,
                    viewer_path=viewer_path,
                    surface=surface,
                    expected_labels=expected_labels,
                    required_paths=required_paths,
                    browser_expectations=browser_expectations,
                )
                for surface in _SURFACES
            }
        finally:
            browser.close()
    reduced = dict(surfaces["reduced_motion"])
    fallback = dict(surfaces["webgl_fallback"])
    if (
        int(reduced.get("route_interaction_count") or 0) != _EXPECTED_ROUTE_STOP_COUNT
        or reduced.get("camera_state_changes_verified") is not True
        or fallback.get("fallback_visible") is not True
        or any(
            dict(surface).get("browser_consumed_package_verified") is not True
            for surface in surfaces.values()
        )
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_gate_failed")
    final_candidate_version = _candidate_version(
        normalized_base_url,
        expected_commit=expected_commit,
        oci_image_revision=expected_image_revision,
    )
    final_oci_image = _inspected_oci_image_identity(oci_image_id)
    final_serving_container = _inspected_serving_container_identity(
        serving_container_id,
        image_id=str(oci_image["image_id"]),
        base_url=normalized_base_url,
    )
    final_http_package = _http_package_binding(
        normalized_base_url,
        slug=normalized_slug,
        snapshot=snapshot,
        bindings=bindings,
        release_revision=str(local_package["release_revision"]),
    )
    (
        final_snapshot,
        final_bindings,
        final_local_package,
        final_package_root_identity,
    ) = _verified_local_package(
        package_dir,
        slug=normalized_slug,
        viewer_relpath=normalized_viewer,
        expected_package_sha256=expected_package_sha256,
    )
    if (
        final_candidate_version != candidate_version
        or final_oci_image != oci_image
        or final_serving_container != serving_container
        or final_http_package != http_package
        or final_snapshot != snapshot
        or final_bindings != bindings
        or final_local_package != local_package
        or final_package_root_identity != package_root_identity
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_runtime_identity_drift")
    package_binding = {
        **local_package,
        **http_package,
        "runtime_identity_revalidated_after_browser": True,
    }
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "slug": normalized_slug,
        "candidate_origin": normalized_base_url,
        "candidate_commit": str(candidate_version["commit_sha"]),
        "candidate_commit_source": (
            "GET /version body + X-EA-Source-Revision + expected commit + "
            "OCI image revision"
        ),
        "candidate_version": candidate_version,
        "candidate_oci_image": oci_image,
        "serving_container": serving_container,
        "package_sha256": str(local_package["package_sha256"]),
        "package_binding": package_binding,
        "landing": landing,
        "proof_manifest": proof_manifest,
        "viewer_path": viewer_path,
        "surfaces": surfaces,
        "surface_count": len(surfaces),
        "route_stop_count": _EXPECTED_ROUTE_STOP_COUNT,
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


def validate_spatial_candidate_browser_receipt(
    receipt: dict[str, object],
    *,
    base_url: str,
    slug: str,
    viewer_relpath: str,
    route_labels: list[str],
    candidate_commit: str,
    oci_image_id: str,
    serving_container_id: str,
    package_sha256: str,
) -> dict[str, object]:
    if not isinstance(receipt, dict):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_schema_invalid")

    def exact_int(value: object, expected: int) -> bool:
        return type(value) is int and value == expected

    expected_origin = _loopback_base_url(base_url)
    expected_slug = _safe_slug(slug)
    expected_viewer_relpath = _safe_viewer_relpath(viewer_relpath)
    expected_labels = _route_labels(route_labels)
    expected_commit = _commit(candidate_commit)
    expected_image_id = _image_id(oci_image_id)
    expected_container_id = _container_id(serving_container_id)
    expected_image_revision = expected_commit
    expected_package = _package_sha256(package_sha256)
    quoted_slug = urllib.parse.quote(expected_slug, safe="")
    expected_viewer_path = (
        f"/tours/viewer/{quoted_slug}/"
        f"{urllib.parse.quote(expected_viewer_relpath, safe='/')}"
    )
    expected_proof_path = (
        expected_viewer_path.rsplit("/", 1)[0] + "/reconstruction.json"
    )
    expected_viewer_url = f"{expected_origin}{expected_viewer_path}"
    expected_landing_url = f"{expected_origin}/tours/{quoted_slug}"
    top_level_keys = {
        "all_route_stops_interacted",
        "browser_consumed_package_verified",
        "camera_state_changes_verified",
        "candidate_commit",
        "candidate_commit_source",
        "candidate_origin",
        "candidate_oci_image",
        "candidate_version",
        "console_error_count",
        "landing",
        "package_binding",
        "package_sha256",
        "page_error_count",
        "proof_manifest",
        "request_failure_count",
        "required_asset_requests_verified",
        "responsive_overflow_verified",
        "route_stop_count",
        "schema",
        "secret_material_recorded",
        "serving_container",
        "slug",
        "status",
        "surface_count",
        "surfaces",
        "viewer_path",
        "viewer_subtree_non_2xx_count",
    }
    if set(receipt) != top_level_keys:
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_schema_invalid")
    version = receipt.get("candidate_version")
    oci_image = receipt.get("candidate_oci_image")
    package = receipt.get("package_binding")
    landing = receipt.get("landing")
    proof = receipt.get("proof_manifest")
    surfaces = receipt.get("surfaces")
    serving_container = receipt.get("serving_container")
    if not all(
        isinstance(value, dict)
        for value in (
            version,
            oci_image,
            package,
            landing,
            proof,
            surfaces,
            serving_container,
        )
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_schema_invalid")
    version = dict(version or {})
    oci_image = dict(oci_image or {})
    package = dict(package or {})
    landing = dict(landing or {})
    proof = dict(proof or {})
    surfaces = dict(surfaces or {})
    serving_container = dict(serving_container or {})
    serving_project = _candidate_project(
        serving_container.get("compose_project"),
        error="manfred_candidate_spatial_browser_receipt_container_invalid",
    )
    if (
        receipt.get("schema") != RECEIPT_SCHEMA
        or receipt.get("status") != "pass"
        or receipt.get("slug") != expected_slug
        or receipt.get("candidate_origin") != expected_origin
        or receipt.get("viewer_path") != expected_viewer_path
        or receipt.get("candidate_commit") != expected_commit
        or receipt.get("candidate_commit_source")
        != (
            "GET /version body + X-EA-Source-Revision + expected commit + "
            "OCI image revision"
        )
        or receipt.get("package_sha256") != expected_package
        or not exact_int(receipt.get("surface_count"), 4)
        or not exact_int(receipt.get("route_stop_count"), _EXPECTED_ROUTE_STOP_COUNT)
        or receipt.get("all_route_stops_interacted") is not True
        or receipt.get("camera_state_changes_verified") is not True
        or receipt.get("required_asset_requests_verified") is not True
        or receipt.get("browser_consumed_package_verified") is not True
        or receipt.get("responsive_overflow_verified") is not True
        or any(
            type(receipt.get(name)) is not int or receipt.get(name) != 0
            for name in (
                "page_error_count",
                "console_error_count",
                "request_failure_count",
                "viewer_subtree_non_2xx_count",
            )
        )
        or receipt.get("secret_material_recorded") is not False
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_contract_invalid")
    if (
        set(oci_image)
        != {
            "image_id",
            "oci_image_revision",
            "revision_source",
            "immutable_image_id_verified",
        }
        or oci_image.get("image_id") != expected_image_id
        or oci_image.get("oci_image_revision") != expected_commit
        or oci_image.get("revision_source") != "docker_image_inspect_by_immutable_id"
        or oci_image.get("immutable_image_id_verified") is not True
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_image_invalid")
    if (
        set(serving_container)
        != {
            "container_id",
            "image_id",
            "compose_project",
            "compose_service",
            "running",
            "container_port",
            "host_ip",
            "host_port",
            "exact_loopback_publication_verified",
            "inspection_source",
        }
        or serving_container.get("container_id") != expected_container_id
        or serving_container.get("image_id") != expected_image_id
        or serving_container.get("compose_project") != serving_project
        or serving_container.get("compose_service") != "gateway"
        or serving_container.get("running") is not True
        or not exact_int(serving_container.get("container_port"), 18090)
        or serving_container.get("host_ip") != "127.0.0.1"
        or not exact_int(
            serving_container.get("host_port"),
            int(urllib.parse.urlsplit(expected_origin).port or 0),
        )
        or serving_container.get("exact_loopback_publication_verified") is not True
        or serving_container.get("inspection_source")
        != "docker_container_inspect_by_immutable_id"
    ):
        raise RuntimeError(
            "manfred_candidate_spatial_browser_receipt_container_invalid"
        )
    if (
        set(version)
        != {
            "path",
            "status",
            "commit_sha",
            "body_commit_sha",
            "source_revision_header",
            "expected_commit_sha",
            "oci_image_revision",
            "repository",
            "role",
            "release_authority_state",
            "release_authority_posture",
            "release_authority_source",
            "commit_observed_over_http",
            "revision_agreement_verified",
        }
        or version
        != {
            "path": "/version",
            "status": 200,
            "commit_sha": expected_commit,
            "body_commit_sha": expected_commit,
            "source_revision_header": expected_commit,
            "expected_commit_sha": expected_commit,
            "oci_image_revision": expected_image_revision,
            "repository": "EA",
            "role": "api",
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "published_status_artifact",
            "commit_observed_over_http": True,
            "revision_agreement_verified": True,
        }
        or not exact_int(version.get("status"), 200)
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_version_invalid")
    if (
        version.get("commit_observed_over_http") is not True
        or version.get("revision_agreement_verified") is not True
        or expected_image_revision != expected_commit
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_version_invalid")
    package_keys = {
        "http_asset_count",
        "http_assets",
        "http_assets_match_local_package",
        "local_file_count",
        "local_files",
        "local_package_verified",
        "local_root_identity_bound",
        "package_sha256",
        "proof_manifest",
        "release_revision",
        "runtime_identity_revalidated_after_browser",
        "tour_manifest_sha256",
    }
    local_files = package.get("local_files")
    http_assets = package.get("http_assets")
    package_proof = package.get("proof_manifest")
    if (
        set(package) != package_keys
        or package.get("package_sha256") != expected_package
        or not exact_int(package.get("local_file_count"), 6)
        or not exact_int(package.get("http_asset_count"), 4)
        or package.get("local_package_verified") is not True
        or package.get("local_root_identity_bound") is not True
        or package.get("http_assets_match_local_package") is not True
        or package.get("runtime_identity_revalidated_after_browser") is not True
        or type(package.get("release_revision")) is not str
        or not package.get("release_revision")
        or package.get("release_revision") != package.get("release_revision").strip()
        or len(package.get("release_revision")) > 200
        or not package.get("release_revision").isprintable()
        or type(package.get("tour_manifest_sha256")) is not str
        or not _SHA256_RE.fullmatch(package.get("tour_manifest_sha256"))
        or not isinstance(local_files, list)
        or len(local_files) != 6
        or not isinstance(http_assets, list)
        or len(http_assets) != 4
        or not isinstance(package_proof, dict)
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_package_invalid")
    local_paths: set[str] = set()
    local_rows_by_path: dict[str, dict[str, object]] = {}
    for raw_row in local_files:
        if not isinstance(raw_row, dict) or set(raw_row) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_package_invalid"
            )
        row = dict(raw_row)
        path = str(row.get("path") or "")
        parsed_path = PurePosixPath(path)
        if (
            path in local_paths
            or parsed_path.is_absolute()
            or any(part in {"", ".", ".."} for part in parsed_path.parts)
            or path != parsed_path.as_posix()
            or (
                path != "tour.json" and not path.startswith("generated-reconstruction/")
            )
            or type(row.get("sha256")) is not str
            or not _SHA256_RE.fullmatch(row.get("sha256"))
            or type(row.get("size_bytes")) is not int
            or int(row.get("size_bytes") or 0) <= 0
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_package_invalid"
            )
        local_paths.add(path)
        local_rows_by_path[path] = row
    expected_local_paths = {
        "tour.json",
        expected_viewer_relpath,
        _RECONSTRUCTION_MANIFEST_RELPATH,
        "generated-reconstruction/source-floorplan.png",
        "generated-reconstruction/vendor/three.module.js",
        ("generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"),
    }
    if local_paths != expected_local_paths:
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_package_invalid")
    canonical_local_rows = [
        {
            "path": path,
            "sha256": str(local_rows_by_path[path]["sha256"]),
            "size_bytes": int(local_rows_by_path[path]["size_bytes"]),
        }
        for path in sorted(local_rows_by_path)
    ]
    if (
        _sha256(_canonical_json_bytes_without_lf(canonical_local_rows))
        != expected_package
        or package.get("tour_manifest_sha256")
        != local_rows_by_path["tour.json"]["sha256"]
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_package_invalid")
    http_paths: set[str] = set()
    http_roles: list[str] = []
    expected_http_roles = {
        (
            f"/tours/viewer/{quoted_slug}/"
            f"{urllib.parse.quote(expected_viewer_relpath, safe='/')}"
        ): "viewer_document",
        (
            f"/tours/viewer/{quoted_slug}/generated-reconstruction/source-floorplan.png"
        ): "floorplan_texture",
        (
            f"/tours/viewer/{quoted_slug}/generated-reconstruction/"
            "vendor/three.module.js"
        ): "viewer_module",
        (
            f"/tours/viewer/{quoted_slug}/generated-reconstruction/vendor/"
            "examples/jsm/controls/OrbitControls.js"
        ): "viewer_module",
    }
    expected_http_media_types = {
        path: (
            "text/html"
            if role == "viewer_document"
            else "image/png"
            if role == "floorplan_texture"
            else "text/javascript"
        )
        for path, role in expected_http_roles.items()
    }
    for raw_row in http_assets:
        if not isinstance(raw_row, dict) or set(raw_row) != {
            "asset_sha256_header_verified",
            "body_matches_local_package",
            "content_type",
            "path",
            "role",
            "sha256",
            "size_bytes",
            "status",
            "viewer_revision_header_verified",
        }:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_package_invalid"
            )
        row = dict(raw_row)
        path = str(row.get("path") or "")
        role = str(row.get("role") or "")
        relpath = urllib.parse.unquote(
            path.removeprefix(f"/tours/viewer/{quoted_slug}/")
        )
        local_row = local_rows_by_path.get(relpath)
        if (
            path in http_paths
            or path
            != (f"/tours/viewer/{quoted_slug}/{urllib.parse.quote(relpath, safe='/')}")
            or not path.startswith(
                f"/tours/viewer/{quoted_slug}/generated-reconstruction/"
            )
            or role not in {"viewer_document", "floorplan_texture", "viewer_module"}
            or expected_http_roles.get(path) != role
            or not exact_int(row.get("status"), 200)
            or not _SHA256_RE.fullmatch(str(row.get("sha256") or ""))
            or type(row.get("size_bytes")) is not int
            or int(row.get("size_bytes") or 0) <= 0
            or _media_type(row.get("content_type"))
            != expected_http_media_types.get(path)
            or row.get("asset_sha256_header_verified") is not True
            or row.get("viewer_revision_header_verified") is not True
            or row.get("body_matches_local_package") is not True
            or local_row is None
            or row.get("sha256") != local_row.get("sha256")
            or row.get("size_bytes") != local_row.get("size_bytes")
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_package_invalid"
            )
        http_paths.add(path)
        http_roles.append(role)
    if (
        set(http_paths) != set(expected_http_roles)
        or sorted(http_roles)
        != [
            "floorplan_texture",
            "viewer_document",
            "viewer_module",
            "viewer_module",
        ]
        or dict(package_proof)
        != {
            "path": expected_proof_path,
            "status": 404,
            "serveable": False,
            "local_sha256": next(
                str(row["sha256"])
                for row in local_files
                if row["path"] == _RECONSTRUCTION_MANIFEST_RELPATH
            ),
        }
        or not exact_int(dict(package_proof).get("status"), 404)
        or dict(package_proof).get("serveable") is not False
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_package_invalid")
    if (
        set(landing)
        != {
            "path",
            "status",
            "horizontal_overflow_px",
            "viewer_route_referenced",
            "page_error_count",
            "console_error_count",
            "page_url",
            "response_url",
            "exact_candidate_url_verified",
        }
        or landing
        != {
            "path": f"/tours/{quoted_slug}",
            "status": 200,
            "horizontal_overflow_px": 0,
            "viewer_route_referenced": True,
            "page_error_count": 0,
            "console_error_count": 0,
            "page_url": expected_landing_url,
            "response_url": expected_landing_url,
            "exact_candidate_url_verified": True,
        }
        or any(
            not exact_int(landing.get(name), expected)
            for name, expected in (
                ("status", 200),
                ("horizontal_overflow_px", 0),
                ("page_error_count", 0),
                ("console_error_count", 0),
            )
        )
        or landing.get("viewer_route_referenced") is not True
        or landing.get("exact_candidate_url_verified") is not True
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_landing_invalid")
    if (
        set(proof) != {"path", "status", "serveable"}
        or proof
        != {
            "path": expected_proof_path,
            "status": 404,
            "serveable": False,
        }
        or not exact_int(proof.get("status"), 404)
        or proof.get("serveable") is not False
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_proof_invalid")
    if set(surfaces) != {
        "desktop",
        "mobile",
        "reduced_motion",
        "webgl_fallback",
    }:
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_surfaces_invalid")
    required_paths = _required_request_paths(expected_slug)
    browser_specs = {
        "viewer_document": (
            expected_viewer_path,
            expected_viewer_relpath,
            "text/html",
        ),
        "floorplan": (
            required_paths["floorplan"],
            "generated-reconstruction/source-floorplan.png",
            "image/png",
        ),
        "orbit_controls": (
            required_paths["orbit_controls"],
            ("generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"),
            "text/javascript",
        ),
        "three_module": (
            required_paths["three_module"],
            "generated-reconstruction/vendor/three.module.js",
            "text/javascript",
        ),
    }
    browser_row_keys = {
        "body_matches_local_package",
        "content_type",
        "exact_candidate_url_verified",
        "path",
        "response_count",
        "sha256",
        "size_bytes",
        "status",
        "url",
    }

    def validate_browser_row(raw_row: object, role: str) -> int:
        if not isinstance(raw_row, dict) or set(raw_row) != browser_row_keys:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
            )
        path, relpath, content_type = browser_specs[role]
        row = dict(raw_row)
        local_row = local_rows_by_path[relpath]
        response_count = row.get("response_count")
        if (
            row.get("url") != f"{expected_origin}{path}"
            or row.get("path") != path
            or not exact_int(row.get("status"), 200)
            or _media_type(row.get("content_type")) != content_type
            or row.get("sha256") != local_row.get("sha256")
            or row.get("size_bytes") != local_row.get("size_bytes")
            or type(response_count) is not int
            or response_count <= 0
            or row.get("body_matches_local_package") is not True
            or row.get("exact_candidate_url_verified") is not True
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
            )
        return response_count

    normal_keys = {
        "browser_consumed_package_verified",
        "browser_response_count",
        "camera_state_changes_verified",
        "canvas_ready",
        "console_error_count",
        "horizontal_overflow_px",
        "mobile",
        "page_error_count",
        "prefers_reduced_motion",
        "request_failure_count",
        "required_requests",
        "route_interaction_count",
        "route_interactions",
        "route_stop_count",
        "status",
        "undersized_target_count",
        "exact_candidate_url_verified",
        "page_url",
        "response_url",
        "viewer_response",
        "viewer_status",
        "viewer_subtree_non_2xx_count",
        "viewport",
    }
    for name, width, height, is_mobile, reduced_motion, collect_routes in _SURFACES[
        :-1
    ]:
        raw_surface = surfaces.get(name)
        if not isinstance(raw_surface, dict) or set(raw_surface) != normal_keys:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
            )
        surface = dict(raw_surface)
        requests = surface.get("required_requests")
        viewer_response = surface.get("viewer_response")
        interactions = surface.get("route_interactions")
        interaction_digests: set[str] = set()
        if (
            not exact_int(surface.get("status"), 200)
            or surface.get("viewport") != {"width": width, "height": height}
            or not isinstance(surface.get("viewport"), dict)
            or not exact_int(dict(surface["viewport"]).get("width"), width)
            or not exact_int(dict(surface["viewport"]).get("height"), height)
            or surface.get("mobile") is not is_mobile
            or surface.get("prefers_reduced_motion") is not reduced_motion
            or surface.get("viewer_status") != "ready"
            or surface.get("canvas_ready") is not True
            or surface.get("page_url") != expected_viewer_url
            or surface.get("response_url") != expected_viewer_url
            or surface.get("exact_candidate_url_verified") is not True
            or surface.get("browser_consumed_package_verified") is not True
            or not exact_int(
                surface.get("route_stop_count"),
                _EXPECTED_ROUTE_STOP_COUNT,
            )
            or not exact_int(surface.get("undersized_target_count"), 0)
            or not exact_int(surface.get("horizontal_overflow_px"), 0)
            or any(
                not exact_int(surface.get(key), 0)
                for key in (
                    "page_error_count",
                    "console_error_count",
                    "request_failure_count",
                    "viewer_subtree_non_2xx_count",
                )
            )
            or not isinstance(requests, dict)
            or set(requests) != set(required_paths)
            or not isinstance(interactions, list)
            or len(interactions)
            != (_EXPECTED_ROUTE_STOP_COUNT if collect_routes else 0)
            or not exact_int(surface.get("route_interaction_count"), len(interactions))
            or surface.get("camera_state_changes_verified") is not collect_routes
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
            )
        browser_response_count = validate_browser_row(
            viewer_response,
            "viewer_document",
        )
        for role in required_paths:
            browser_response_count += validate_browser_row(
                requests.get(role),
                role,
            )
        if not exact_int(
            surface.get("browser_response_count"),
            browser_response_count,
        ):
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
            )
        for index, raw_row in enumerate(interactions):
            if not isinstance(raw_row, dict) or set(raw_row) != {
                "active_state_verified",
                "camera_canvas_screenshot_sha256",
                "click_handler_state_change_verified",
                "index",
                "label",
                "live_region_verified",
                "playwright_actionability_verified",
            }:
                raise RuntimeError(
                    "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
                )
            row = dict(raw_row)
            screenshot_digest = row.get("camera_canvas_screenshot_sha256")
            if (
                not exact_int(row.get("index"), index)
                or row.get("label") != expected_labels[index]
                or type(screenshot_digest) is not str
                or not _SHA256_RE.fullmatch(screenshot_digest)
                or screenshot_digest in interaction_digests
                or any(
                    row.get(key) is not True
                    for key in (
                        "active_state_verified",
                        "click_handler_state_change_verified",
                        "live_region_verified",
                        "playwright_actionability_verified",
                    )
                )
            ):
                raise RuntimeError(
                    "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
                )
            interaction_digests.add(screenshot_digest)
        if collect_routes and len(interaction_digests) != _EXPECTED_ROUTE_STOP_COUNT:
            raise RuntimeError(
                "manfred_candidate_spatial_browser_receipt_surfaces_invalid"
            )
    fallback = surfaces.get("webgl_fallback")
    fallback_keys = {
        "accessible_fallback_verified",
        "alert_role",
        "browser_consumed_package_verified",
        "browser_response_count",
        "console_error_count",
        "enabled_button_count",
        "enabled_route_button_count",
        "fallback_visible",
        "horizontal_overflow_px",
        "live_status_role",
        "page_error_count",
        "page_url",
        "response_url",
        "exact_candidate_url_verified",
        "required_requests",
        "status",
        "viewer_response",
        "viewer_status",
        "viewport",
    }
    if not isinstance(fallback, dict) or set(fallback) != fallback_keys:
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_surfaces_invalid")
    fallback = dict(fallback)
    fallback_requests = fallback.get("required_requests")
    if (
        any(
            not exact_int(fallback.get(name), expected)
            for name, expected in (
                ("status", 200),
                ("enabled_route_button_count", 0),
                ("enabled_button_count", 0),
                ("horizontal_overflow_px", 0),
                ("page_error_count", 0),
                ("console_error_count", 0),
            )
        )
        or not isinstance(fallback.get("viewport"), dict)
        or not exact_int(dict(fallback["viewport"]).get("width"), 1200)
        or not exact_int(dict(fallback["viewport"]).get("height"), 900)
        or fallback.get("viewer_status") != "unavailable"
        or fallback.get("fallback_visible") is not True
        or fallback.get("alert_role") != "alert"
        or fallback.get("live_status_role") != "status"
        or fallback.get("accessible_fallback_verified") is not True
        or fallback.get("page_url") != expected_viewer_url
        or fallback.get("response_url") != expected_viewer_url
        or fallback.get("exact_candidate_url_verified") is not True
        or fallback.get("browser_consumed_package_verified") is not True
        or not isinstance(fallback_requests, dict)
        or set(fallback_requests) != set(required_paths)
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_surfaces_invalid")
    fallback_response_count = validate_browser_row(
        fallback.get("viewer_response"),
        "viewer_document",
    )
    for role in required_paths:
        fallback_response_count += validate_browser_row(
            fallback_requests.get(role),
            role,
        )
    if not exact_int(
        fallback.get("browser_response_count"),
        fallback_response_count,
    ):
        raise RuntimeError("manfred_candidate_spatial_browser_receipt_surfaces_invalid")
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the live Playwright gate for one Manfred spatial candidate."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--viewer-relpath", required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--oci-image-id", required=True)
    parser.add_argument("--serving-container-id", required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--package-dir", required=True)
    parser.add_argument(
        "--route-label",
        action="append",
        dest="route_labels",
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = audit_spatial_candidate_browser(
            base_url=args.base_url,
            slug=args.slug,
            viewer_relpath=args.viewer_relpath,
            route_labels=list(args.route_labels or []),
            candidate_commit=args.candidate_commit,
            oci_image_id=args.oci_image_id,
            serving_container_id=args.serving_container_id,
            package_sha256=args.package_sha256,
            package_dir=Path(args.package_dir),
        )
        validate_spatial_candidate_browser_receipt(
            receipt,
            base_url=args.base_url,
            slug=args.slug,
            viewer_relpath=args.viewer_relpath,
            route_labels=list(args.route_labels or []),
            candidate_commit=args.candidate_commit,
            oci_image_id=args.oci_image_id,
            serving_container_id=args.serving_container_id,
            package_sha256=args.package_sha256,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "secret_material_recorded": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
