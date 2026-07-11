from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _error_code(response) -> str:  # type: ignore[no-untyped-def]
    payload = response.json()
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "")
    return str(payload.get("detail") or "")


def _memorial_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    slug: str = "manfred",
) -> tuple[TestClient, Path, Path]:
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_API_TOKEN", "")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    public_root = tmp_path / "public"
    private_root = tmp_path / "private"
    bundle = public_root / slug
    bundle.mkdir(parents=True)
    (bundle / "memorial.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "person_name": "Manfred Hoza",
                "title": "In Erinnerung an Manfred",
                "memory_cards": [],
                "audio_clips": [],
                "write_token": "unit-write-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_PUBLIC_MEMORIAL_DIR", str(public_root))
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR", str(private_root))

    from app.api.routes import public_memorials
    from app.services import memorial_archive_registry

    public_memorials._PUBLIC_MEMORIAL_RATE_DB = tmp_path / "artifacts" / "memorial_rate_limits.sqlite3"
    memorial_archive_registry.PUBLIC_MEMORIAL_ROOT = tmp_path / "public_registry"
    memorial_archive_registry.ARCHIVE_ROOT = tmp_path / "archive"

    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "family-contribution-test"})
    return client, public_root, private_root


def _submit(
    client: TestClient,
    *,
    slug: str = "manfred",
    publication_consent: bool = True,
    body: str = "RAW_PRIVATE_MEMORY_SENTINEL from a family afternoon.",
):  # type: ignore[no-untyped-def]
    return client.post(
        f"/memorials/{slug}/contributions",
        json={
            "title": "RAW_PRIVATE_TITLE_SENTINEL",
            "body": body,
            "source_label": "RAW_PRIVATE_SOURCE_SENTINEL",
            "contributor_name": "RAW_PRIVATE_NAME_SENTINEL",
            "relationship": "RAW_PRIVATE_RELATIONSHIP_SENTINEL",
            "publication_consent": publication_consent,
        },
    )


def _approve(
    client: TestClient,
    contribution_id: str,
    *,
    title: str = "A carefully curated memory",
    body: str = "Manfred made time for a patient conversation.",
):  # type: ignore[no-untyped-def]
    return client.post(
        f"/memorials/manfred/contributions/{contribution_id}/approve",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={
            "reviewer": "Memorial curator",
            "review_note": "Names and private circumstances removed.",
            "source_label": "Erinnerung aus der Familie",
            "title": title,
            "body": body,
        },
    )


def test_family_submission_stays_private_and_operator_review_is_authorized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _public_root, private_root = _memorial_client(monkeypatch, tmp_path)

    response = _submit(client)

    assert response.status_code == 201
    receipt = response.json()
    assert receipt["status"] == "pending_review"
    assert receipt["visibility"] == "private"
    assert receipt["manage_token"]
    assert "RAW_PRIVATE" not in json.dumps(receipt)
    public_json = client.get("/memorials/manfred.json")
    assert public_json.status_code == 200
    assert public_json.json()["memory_cards"] == []
    public_page = client.get("/memorials/manfred")
    assert public_page.status_code == 200
    assert "RAW_PRIVATE" not in public_page.text

    unauthorized = client.get("/memorials/manfred/contributions/operator")
    assert unauthorized.status_code == 403
    assert _error_code(unauthorized) == "memorial_write_unauthorized"
    assert "RAW_PRIVATE" not in unauthorized.text

    authorized = client.get(
        "/memorials/manfred/contributions/operator",
        headers={"x-memorial-write-token": "unit-write-token"},
    )
    assert authorized.status_code == 200
    candidate = authorized.json()["contributions"][0]
    assert candidate["submission"]["body"].startswith("RAW_PRIVATE_MEMORY_SENTINEL")
    assert "manage_token_hash" not in candidate

    private_payload = (private_root / "manfred" / "family_contributions.json").read_text(encoding="utf-8")
    assert "RAW_PRIVATE_MEMORY_SENTINEL" in private_payload
    assert receipt["manage_token"] not in private_payload


def test_operator_approval_publishes_only_explicit_curated_excerpt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    submitted = _submit(client).json()
    contribution_id = submitted["contribution_id"]

    unauthorized = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/approve",
        json={"reviewer": "No access", "title": "No", "body": "No"},
    )
    assert unauthorized.status_code == 403
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []

    approved = _approve(client, contribution_id)

    assert approved.status_code == 200
    assert approved.json()["status"] == "published"
    assert approved.json()["visibility"] == "public"
    public_payload = client.get("/memorials/manfred.json").json()
    assert public_payload["memory_cards"] == [
        {
            "source_label": "Erinnerung aus der Familie",
            "title": "A carefully curated memory",
            "body": "Manfred made time for a patient conversation.",
            "curation_status": "approved_public_excerpt",
        }
    ]
    serialized = json.dumps(public_payload)
    assert "RAW_PRIVATE" not in serialized
    page = client.get("/memorials/manfred")
    assert page.status_code == 200
    assert "A carefully curated memory" in page.text
    assert "Manfred made time for a patient conversation." in page.text
    assert "RAW_PRIVATE" not in page.text

    projection_text = (public_root / "manfred" / "family_contributions.public.json").read_text(
        encoding="utf-8"
    )
    assert "public_excerpt" in projection_text
    assert "Manfred made time for a patient conversation." in projection_text
    assert "RAW_PRIVATE" not in projection_text
    raw_projection = client.get(
        "/memorials/files/manfred/family_contributions.public.json"
    )
    assert raw_projection.status_code == 404


def test_correction_and_withdrawal_remove_public_memory_until_reapproved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    receipt = _submit(client).json()
    contribution_id = receipt["contribution_id"]
    manage_token = receipt["manage_token"]
    assert _approve(client, contribution_id).status_code == 200

    denied_correction = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/correct",
        headers={"x-memorial-contribution-token": "wrong-token"},
        json={"body": "CORRECTED_PRIVATE_SENTINEL"},
    )
    assert denied_correction.status_code == 403
    assert _error_code(denied_correction) == "memorial_contribution_unauthorized"
    assert client.get("/memorials/manfred.json").json()["memory_cards"]

    corrected = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/correct",
        headers={"x-memorial-contribution-token": manage_token},
        json={
            "body": "CORRECTED_PRIVATE_SENTINEL pending a new review.",
            "correction_reason": "A family detail needed correction.",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["status"] == "correction_pending"
    assert corrected.json()["public_removed"] is True
    after_correction = json.dumps(client.get("/memorials/manfred.json").json())
    assert "A carefully curated memory" not in after_correction
    assert "CORRECTED_PRIVATE_SENTINEL" not in after_correction

    operator_rows = client.get(
        "/memorials/manfred/contributions/operator",
        headers={"x-memorial-write-token": "unit-write-token"},
    ).json()["contributions"]
    assert operator_rows[0]["submission"]["body"].startswith("CORRECTED_PRIVATE_SENTINEL")

    reapproved = _approve(
        client,
        contribution_id,
        title="The corrected public memory",
        body="The family approved this corrected public account.",
    )
    assert reapproved.status_code == 200
    assert "The corrected public memory" in json.dumps(client.get("/memorials/manfred.json").json())

    denied_withdrawal = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/withdraw",
        headers={"x-memorial-contribution-token": "wrong-token"},
        json={"reason": "withdraw"},
    )
    assert denied_withdrawal.status_code == 403
    assert "The corrected public memory" in json.dumps(client.get("/memorials/manfred.json").json())

    withdrawn = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/withdraw",
        headers={"x-memorial-contribution-token": manage_token},
        json={"reason": "The contributor withdrew permission."},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert withdrawn.json()["visibility"] == "private"
    final_public = json.dumps(client.get("/memorials/manfred.json").json())
    assert "The corrected public memory" not in final_public
    assert "CORRECTED_PRIVATE_SENTINEL" not in final_public


def test_contribution_mutations_are_json_only_bounded_and_require_publication_consent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _public_root, _private_root = _memorial_client(monkeypatch, tmp_path)

    non_json = client.post(
        "/memorials/manfred/contributions",
        content="title=unsafe",
        headers={"content-type": "text/plain"},
    )
    assert non_json.status_code == 415
    assert _error_code(non_json) == "memorial_contribution_json_required"

    oversized = _submit(client, body="x" * 7000)
    assert oversized.status_code == 400
    assert _error_code(oversized) == "memorial_contribution_body_too_long"

    no_consent = _submit(client, publication_consent=False)
    assert no_consent.status_code == 201
    approval = _approve(client, no_consent.json()["contribution_id"])
    assert approval.status_code == 409
    assert _error_code(approval) == "memorial_contribution_publication_consent_required"
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []

    declared_too_large = client.post(
        "/memorials/manfred/contributions",
        content=json.dumps({"title": "large", "body": "x" * 20_000, "publication_consent": True}),
        headers={"content-type": "application/json"},
    )
    assert declared_too_large.status_code == 413
    assert _error_code(declared_too_large) == "request_payload_too_large"


def test_private_contribution_ledger_rejects_symlinks_and_wrong_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _public_root, private_root = _memorial_client(monkeypatch, tmp_path)
    slug_root = private_root / "manfred"
    slug_root.mkdir(parents=True)
    ledger = slug_root / "family_contributions.json"
    outside = tmp_path / "outside-private-ledger.json"
    outside.write_text(
        json.dumps(
            {
                "schema": "ea.memorial_family_contributions.private.v1",
                "slug": "manfred",
                "contributions": [],
            }
        ),
        encoding="utf-8",
    )
    ledger.symlink_to(outside)

    symlinked = client.get(
        "/memorials/manfred/contributions/operator",
        headers={"x-memorial-write-token": "unit-write-token"},
    )
    assert symlinked.status_code == 503
    assert _error_code(symlinked) == "memorial_contribution_store_invalid"

    ledger.unlink()
    ledger.write_text(
        json.dumps({"schema": "wrong", "slug": "manfred", "contributions": []}),
        encoding="utf-8",
    )
    wrong_schema = client.get(
        "/memorials/manfred/contributions/operator",
        headers={"x-memorial-write-token": "unit-write-token"},
    )
    assert wrong_schema.status_code == 503
    assert _error_code(wrong_schema) == "memorial_contribution_store_invalid"
