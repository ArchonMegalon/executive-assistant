from __future__ import annotations

from pathlib import Path

import pytest

from app.api.routes import public_memorial_surface


def _publication(**overrides: object) -> dict[str, object]:
    publication: dict[str, object] = {
        "approved": True,
        "id": "public-item",
        "slug": "public-item",
        "title": "Public item",
        "audience": "public",
        "sensitivity": "PUBLIC",
        "review_status": "published",
        "url": "/memorials/manfred/archive/public-item",
    }
    publication.update(overrides)
    return publication


def _registry(*publications: dict[str, object]) -> dict[str, object]:
    return {"slug": "manfred", "fliplink_publications": list(publications)}


def test_archive_publication_serves_explicitly_authorized_internal_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "index.html"
    html_path.write_text("<!doctype html><title>Approved memorial</title>", encoding="utf-8")
    observed_path_args: list[tuple[str, str]] = []

    monkeypatch.setattr(public_memorial_surface, "_load_memorial", lambda slug: {})
    monkeypatch.setattr(
        public_memorial_surface,
        "_public_memorial_archive_registry",
        lambda slug: _registry(_publication()),
    )
    monkeypatch.setattr(
        public_memorial_surface,
        "_memorial_archive_publication_html_path",
        lambda slug, publication_slug: (
            observed_path_args.append((slug, publication_slug)) or html_path
        ),
    )

    response = public_memorial_surface.public_memorial_archive_publication(
        "manfred",
        "public-item",
    )

    assert response.status_code == 200
    assert b"Approved memorial" in response.body
    assert observed_path_args == [("manfred", "public-item")]


@pytest.mark.parametrize(
    "publications",
    [
        (),
        ({key: value for key, value in _publication().items() if key != "approved"},),
        (_publication(approved=False),),
        (_publication(approved="true"),),
        (_publication(audience="private"),),
        (_publication(audience="privtae"),),
        (_publication(sensitivity="PRIVATE"),),
        (_publication(review_status="approved"),),
        (_publication(slug="different-item"),),
        (_publication(slug="../public-item"),),
    ],
    ids=[
        "missing-registry-entry",
        "missing-approval",
        "false-approval",
        "non-boolean-approval",
        "private-audience",
        "invalid-audience",
        "private-sensitivity",
        "not-published",
        "different-slug",
        "unsafe-registry-slug",
    ],
)
def test_archive_publication_rejects_unapproved_registry_before_path_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    publications: tuple[dict[str, object], ...],
) -> None:
    private_html = tmp_path / "private-exists.html"
    private_html.write_text("private path content", encoding="utf-8")
    path_probe_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(public_memorial_surface, "_load_memorial", lambda slug: {})
    monkeypatch.setattr(
        public_memorial_surface,
        "_public_memorial_archive_registry",
        lambda slug: _registry(*publications),
    )
    monkeypatch.setattr(
        public_memorial_surface,
        "_memorial_archive_publication_html_path",
        lambda slug, publication_slug: (
            path_probe_calls.append((slug, publication_slug)) or private_html
        ),
    )

    response = public_memorial_surface.public_memorial_archive_publication(
        "manfred",
        "public-item",
    )

    assert response.status_code == 404
    assert path_probe_calls == []
    assert b"private path content" not in response.body
    assert str(private_html).encode() not in response.body


def test_archive_publication_preserves_authorized_external_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_html = tmp_path / "missing.html"
    monkeypatch.setattr(public_memorial_surface, "_load_memorial", lambda slug: {})
    monkeypatch.setattr(
        public_memorial_surface,
        "_public_memorial_archive_registry",
        lambda slug: _registry(
            _publication(url="https://archive.example/public-item")
        ),
    )
    monkeypatch.setattr(
        public_memorial_surface,
        "_memorial_archive_publication_html_path",
        lambda slug, publication_slug: missing_html,
    )

    response = public_memorial_surface.public_memorial_archive_publication(
        "manfred",
        "public-item",
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://archive.example/public-item"
