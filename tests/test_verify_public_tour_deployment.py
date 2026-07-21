from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

import pytest

from scripts import verify_public_tour_deployment as verifier


BASE_URL = "https://ea.example"
SLUG = "flagship-tour"
VIDEO_BYTES = b"reviewed-mp4-video"
VIEWER_BYTES = b"<!doctype html><html><body><canvas></canvas></body></html>"
VIDEO_DISCLOSURE = "Generated synthetic walkthrough; not a captured or provider-verified scan."
VIEWER_DISCLOSURE = (
    "Generated interactive reconstruction; not a captured or provider-verified 3D scan."
)
VIEWER_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'self'; "
    "style-src 'unsafe-inline'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def _payload() -> dict[str, object]:
    return {
        "slug": SLUG,
        "title": "Flagship Tour",
        "facts": {},
        "brief": {},
        "scenes": [],
        "video_url": f"/tours/files/{SLUG}/generated-reconstruction/walkthrough.mp4",
        "video_release": {
            "contract": "ea.public-tour-video-release.v1",
            "status": "ready",
            "release_revision": "release-2026-07-13.1",
            "asset_sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
            "disclosure": VIDEO_DISCLOSURE,
            "synthetic": True,
            "verified_provider_capture": False,
        },
        "generated_viewer": {
            "url": f"/tours/viewer/{SLUG}/generated-reconstruction/viewer.html",
            "release_revision": "viewer-2026-07-13.1",
            "disclosure": VIEWER_DISCLOSURE,
            "synthetic": True,
            "verified_provider_capture": False,
        },
    }


def _html(disclosure: str = VIEWER_DISCLOSURE) -> bytes:
    return (
        "<!doctype html><html lang='en'><head><title>Tour</title></head>"
        f"<body><main><p id='tour-release-notice'>{disclosure}</p></main></body></html>"
    ).encode("utf-8")


def _video_headers(*, body: bytes = VIDEO_BYTES) -> dict[str, str]:
    return {
        "content-type": "video/mp4",
        "content-length": str(len(body)),
        "cache-control": "public, max-age=86400, immutable",
        "x-propertyquarry-asset-sha256": hashlib.sha256(VIDEO_BYTES).hexdigest(),
        "x-propertyquarry-media-revision": "release-2026-07-13.1",
        "x-content-type-options": "nosniff",
    }


def _viewer_headers(*, body: bytes = VIEWER_BYTES) -> dict[str, str]:
    return {
        "content-type": "text/html; charset=utf-8",
        "content-length": str(len(body)),
        "cache-control": "no-store",
        "access-control-allow-origin": "*",
        "cross-origin-resource-policy": "cross-origin",
        "content-security-policy": VIEWER_CSP,
        "x-propertyquarry-asset-sha256": hashlib.sha256(VIEWER_BYTES).hexdigest(),
        "x-propertyquarry-viewer-revision": "viewer-2026-07-13.1",
        "x-content-type-options": "nosniff",
    }


def _receipt(
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> dict[str, object]:
    return {
        "status": status,
        "headers": dict(headers or {}),
        "body": body,
        "body_exceeded_cap": False,
        "error": "" if status == 200 else "http_error",
    }


def _origin_fetcher(
    payload: dict[str, object],
    *,
    html_body: bytes | None = None,
    mutations: dict[tuple[str, str], dict[str, object]] | None = None,
) -> tuple[object, list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []
    encoded_payload = json.dumps(payload, sort_keys=True).encode("utf-8")
    responses: dict[tuple[str, str], dict[str, object]] = {
        ("GET", f"/tours/{SLUG}.json"): _receipt(
            headers={"content-type": "application/json"},
            body=encoded_payload,
        ),
        ("GET", f"/tours/{SLUG}"): _receipt(
            headers={"content-type": "text/html; charset=utf-8"},
            body=html_body if html_body is not None else _html(),
        ),
        ("HEAD", f"/tours/files/{SLUG}/generated-reconstruction/walkthrough.mp4"): _receipt(
            headers=_video_headers(),
        ),
        ("GET", f"/tours/files/{SLUG}/generated-reconstruction/walkthrough.mp4"): _receipt(
            headers=_video_headers(),
            body=VIDEO_BYTES,
        ),
        ("HEAD", f"/tours/viewer/{SLUG}/generated-reconstruction/viewer.html"): _receipt(
            headers=_viewer_headers(),
        ),
        ("GET", f"/tours/viewer/{SLUG}/generated-reconstruction/viewer.html"): _receipt(
            headers=_viewer_headers(),
            body=VIEWER_BYTES,
        ),
    }
    for key, mutation in dict(mutations or {}).items():
        current = dict(responses[key])
        if "headers" in mutation:
            headers = dict(current.get("headers") or {})
            headers.update(dict(mutation["headers"]))
            current["headers"] = headers
        for field, value in mutation.items():
            if field != "headers":
                current[field] = value
        responses[key] = current

    def _fetch(url: str, *, method: str, max_body_bytes: int) -> dict[str, object]:
        del max_body_bytes
        key = (method, urlsplit(url).path)
        calls.append(key)
        assert key in responses, f"unexpected verifier request: {key}"
        return dict(responses[key])

    return _fetch, calls


def test_deployment_verifier_accepts_clean_released_video_and_generated_viewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher, calls = _origin_fetcher(_payload())
    monkeypatch.setattr(verifier, "_http_fetch", fetcher)

    first = verifier.verify_deployment(base_url=BASE_URL, slug=SLUG)
    second = verifier.verify_deployment(base_url=BASE_URL, slug=SLUG)

    assert first == second
    assert first["status"] == "pass"
    assert first["pass"] is True
    assert first["blockers"] == []
    assert first["checks"] == {
        "json_verified": True,
        "html_verified": True,
        "video_present": True,
        "video_verified": True,
        "video_size_bytes": len(VIDEO_BYTES),
        "generated_viewer_present": True,
        "generated_viewer_verified": True,
        "generated_viewer_size_bytes": len(VIEWER_BYTES),
    }
    assert len(calls) == 12


def test_deployment_verifier_blocks_propertyquarry_style_video_url_without_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    payload.pop("video_release")
    payload.pop("generated_viewer")
    fetcher, calls = _origin_fetcher(
        payload,
        html_body=_html("This surface does not claim a captured or provider-verified 3D scan."),
    )
    monkeypatch.setattr(verifier, "_http_fetch", fetcher)

    receipt = verifier.verify_deployment(base_url=BASE_URL, slug=SLUG)

    assert receipt["pass"] is False
    assert any(row["code"] == "video_url_without_release" for row in receipt["blockers"])
    assert calls == [("GET", f"/tours/{SLUG}.json"), ("GET", f"/tours/{SLUG}")]


def test_deployment_verifier_does_not_follow_redirected_public_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher, _calls = _origin_fetcher(
        _payload(),
        mutations={
            ("GET", f"/tours/{SLUG}.json"): {
                "status": 302,
                "headers": {"content-type": "text/html", "location": "https://other.example/tour"},
                "body": b"",
            }
        },
    )
    monkeypatch.setattr(verifier, "_http_fetch", fetcher)

    receipt = verifier.verify_deployment(base_url=BASE_URL, slug=SLUG)

    assert receipt["pass"] is False
    assert {
        (row["code"], row.get("endpoint"), row.get("actual"))
        for row in receipt["blockers"]
    } >= {("http_status_invalid", "tour_json", 302)}


def test_deployment_verifier_blocks_media_header_and_body_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher, _calls = _origin_fetcher(
        _payload(),
        mutations={
            ("HEAD", f"/tours/files/{SLUG}/generated-reconstruction/walkthrough.mp4"): {
                "headers": {"x-propertyquarry-media-revision": "wrong-revision"}
            },
            ("GET", f"/tours/files/{SLUG}/generated-reconstruction/walkthrough.mp4"): {
                "body": b"tampered-video",
                "headers": {"content-length": str(len(b"tampered-video"))},
            },
            ("GET", f"/tours/viewer/{SLUG}/generated-reconstruction/viewer.html"): {
                "headers": {"content-security-policy": "default-src https:"}
            },
        },
    )
    monkeypatch.setattr(verifier, "_http_fetch", fetcher)

    receipt = verifier.verify_deployment(base_url=BASE_URL, slug=SLUG)
    codes = {row["code"] for row in receipt["blockers"]}

    assert receipt["pass"] is False
    assert "video_revision_header_invalid" in codes
    assert "video_body_digest_mismatch" in codes
    assert "viewer_csp_invalid" in codes


def test_deployment_verifier_recursively_blocks_sensitive_keys_and_test_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload()
    payload["facts"] = {
        "api_key": "must-not-leak",
        "generation": {
            "source_path": "/tmp/pytest-of-tibor/debug-probe/reconstruction.json",
        },
    }
    fetcher, _calls = _origin_fetcher(payload)
    monkeypatch.setattr(verifier, "_http_fetch", fetcher)

    receipt = verifier.verify_deployment(base_url=BASE_URL, slug=SLUG)
    codes = {row["code"] for row in receipt["blockers"]}

    assert receipt["pass"] is False
    assert "sensitive_key_exposed" in codes
    assert "provenance_string_forbidden" in codes
    assert all("must-not-leak" not in json.dumps(row) for row in receipt["blockers"])


@pytest.mark.parametrize(
    ("origin", "slug", "code"),
    [
        ("https://user:password@ea.example", SLUG, "base_url_invalid"),
        (BASE_URL, "../escape", "slug_invalid"),
    ],
)
def test_deployment_verifier_rejects_unsafe_entrypoints_without_network(
    origin: str,
    slug: str,
    code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier,
        "_http_fetch",
        lambda *_args, **_kwargs: pytest.fail("unsafe inputs must not trigger a request"),
    )

    receipt = verifier.verify_deployment(base_url=origin, slug=slug)

    assert receipt["pass"] is False
    assert any(row["code"] == code for row in receipt["blockers"])


def test_deployment_verifier_cli_is_deterministic_and_nonzero_on_blocker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = verifier.main(
        ["--base-url", "https://user:password@ea.example", "--slug", SLUG]
    )
    stdout = capsys.readouterr().out
    receipt = json.loads(stdout)

    assert exit_code == 1
    assert stdout.count("\n") == 1
    assert receipt["status"] == "blocked"
    assert receipt["pass"] is False
