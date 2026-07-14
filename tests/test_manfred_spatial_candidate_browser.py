from __future__ import annotations

import pytest

from scripts import verify_manfred_spatial_candidate_browser as browser_gate


LABELS = [f"Stop {index}" for index in range(1, 10)]


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
        path: {"status": 200, "content_type": "application/octet-stream"}
        for path in expected.values()
    }

    evidence = browser_gate._request_evidence(observed, expected)

    assert set(evidence) == {"floorplan", "orbit_controls", "three_module"}
    observed[expected["floorplan"]]["status"] = 404
    with pytest.raises(RuntimeError, match="asset_request_failed"):
        browser_gate._request_evidence(observed, expected)


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
