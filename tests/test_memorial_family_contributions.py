from __future__ import annotations

import hashlib
import json
import stat
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
    monkeypatch.delenv("EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR", raising=False)
    monkeypatch.delenv("EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR", raising=False)
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

    public_memorials._PUBLIC_MEMORIAL_RATE_DB = (
        tmp_path / "artifacts" / "memorial_rate_limits.sqlite3"
    )
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


def _reject(client: TestClient, contribution_id: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/memorials/manfred/contributions/{contribution_id}/reject",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={
            "reviewer": "Memorial curator",
            "reason": "Not suitable for publication in this form.",
        },
    )


def _unpublish(client: TestClient, contribution_id: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/memorials/manfred/contributions/{contribution_id}/unpublish",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={
            "reviewer": "Memorial curator",
            "reason": "Family requested an immediate public takedown.",
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

    private_payload = (
        private_root / "manfred" / "family_contributions.json"
    ).read_text(encoding="utf-8")
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

    projection_text = (
        public_root / "manfred" / "family_contributions.public.json"
    ).read_text(encoding="utf-8")
    assert "public_excerpt" in projection_text
    assert "Manfred made time for a patient conversation." in projection_text
    assert "RAW_PRIVATE" not in projection_text
    raw_projection = client.get(
        "/memorials/files/manfred/family_contributions.public.json"
    )
    assert raw_projection.status_code == 404


def test_contribution_roots_are_writable_and_source_roots_remain_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, public_source, private_source = _memorial_client(monkeypatch, tmp_path)
    public_contributions = tmp_path / "contributions" / "public"
    private_contributions = tmp_path / "contributions" / "private"
    monkeypatch.setenv(
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR",
        str(public_contributions),
    )
    monkeypatch.setenv(
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR",
        str(private_contributions),
    )
    manifest_path = public_source / "manfred" / "memorial.json"
    original_manifest = manifest_path.read_bytes()

    submitted = _submit(client)
    assert submitted.status_code == 201
    contribution_id = submitted.json()["contribution_id"]
    assert _approve(client, contribution_id).status_code == 200

    private_ledger = private_contributions / "manfred" / "family_contributions.json"
    public_projection = (
        public_contributions / "manfred" / "family_contributions.public.json"
    )
    assert private_ledger.is_file()
    assert public_projection.is_file()
    assert stat.S_IMODE(private_ledger.stat().st_mode) == 0o600
    assert stat.S_IMODE(private_ledger.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(
        (private_ledger.parent / ".family_contributions.lock").stat().st_mode
    ) == 0o600
    assert stat.S_IMODE(public_projection.stat().st_mode) == 0o644
    assert stat.S_IMODE(public_projection.parent.stat().st_mode) == 0o755
    assert manifest_path.read_bytes() == original_manifest
    assert not (public_source / "manfred" / "family_contributions.public.json").exists()
    assert not (private_source / "manfred" / "family_contributions.json").exists()
    public_payload = client.get("/memorials/manfred.json").json()
    assert public_payload["memory_cards"][0]["title"] == "A carefully curated memory"
    assert "RAW_PRIVATE" not in json.dumps(public_payload)


def test_private_contribution_root_rejects_symlink_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import memorial_family_contributions

    real_root = tmp_path / "real-private-contributions"
    real_root.mkdir()
    alias_root = tmp_path / "private-contributions-alias"
    alias_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setenv("EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR", str(alias_root))

    with pytest.raises(
        memorial_family_contributions.MemorialContributionError,
        match="memorial_contribution_path_invalid",
    ):
        memorial_family_contributions.submit_family_contribution(
            slug="manfred",
            payload={
                "title": "Private",
                "body": "Must not follow a contribution-root symlink.",
                "publication_consent": False,
            },
        )

    assert list(real_root.iterdir()) == []


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
    assert operator_rows[0]["submission"]["body"].startswith(
        "CORRECTED_PRIVATE_SENTINEL"
    )

    reapproved = _approve(
        client,
        contribution_id,
        title="The corrected public memory",
        body="The family approved this corrected public account.",
    )
    assert reapproved.status_code == 200
    assert "The corrected public memory" in json.dumps(
        client.get("/memorials/manfred.json").json()
    )

    denied_withdrawal = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/withdraw",
        headers={"x-memorial-contribution-token": "wrong-token"},
        json={"reason": "withdraw"},
    )
    assert denied_withdrawal.status_code == 403
    assert "The corrected public memory" in json.dumps(
        client.get("/memorials/manfred.json").json()
    )

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
        content=json.dumps(
            {"title": "large", "body": "x" * 20_000, "publication_consent": True}
        ),
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


def test_recovery_receipt_and_token_authenticated_status_are_private_and_minimal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    response = _submit(client)

    assert response.status_code == 201
    submission_receipt = response.json()
    recovery = submission_receipt["recovery_receipt"]
    assert recovery == {
        "schema_version": "ea.memorial_family_contribution.recovery_receipt.v1",
        "contribution_id": submission_receipt["contribution_id"],
        "status": "pending_review",
        "visibility": "private",
        "manage_token_header": "x-memorial-contribution-token",
        "status_path": (
            f"/memorials/manfred/contributions/{submission_receipt['contribution_id']}/status"
        ),
        "token_recoverable": False,
        "manage_token": submission_receipt["manage_token"],
    }
    assert "RAW_PRIVATE" not in json.dumps(submission_receipt)

    denied = client.get(
        recovery["status_path"],
        headers={"x-memorial-contribution-token": "wrong-token"},
    )
    assert denied.status_code == 403
    assert _error_code(denied) == "memorial_contribution_unauthorized"

    status = client.get(
        recovery["status_path"],
        headers={
            "x-memorial-contribution-token": submission_receipt["manage_token"]
        },
    )
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["status"] == "pending_review"
    assert status_payload["visibility"] == "private"
    assert status_payload["publication_consent"] is True
    assert status_payload["actions"] == {
        "can_correct": True,
        "can_withdraw": True,
    }
    assert "manage_token" not in status_payload["recovery_receipt"]
    assert submission_receipt["manage_token"] not in json.dumps(status_payload)
    assert "manage_token_hash" not in json.dumps(status_payload)
    assert "submission" not in status_payload
    assert "RAW_PRIVATE" not in json.dumps(status_payload)
    assert status.headers["cache-control"] == "no-store"
    assert status.headers["referrer-policy"] == "no-referrer"


def test_operator_can_reject_pending_contribution_with_private_audit_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    submission = _submit(client).json()
    contribution_id = submission["contribution_id"]

    unauthorized = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/reject",
        json={"reviewer": "No access", "reason": "No access"},
    )
    assert unauthorized.status_code == 403
    assert _error_code(unauthorized) == "memorial_write_unauthorized"

    missing_reason = client.post(
        f"/memorials/manfred/contributions/{contribution_id}/reject",
        headers={"x-memorial-write-token": "unit-write-token"},
        json={"reviewer": "Memorial curator"},
    )
    assert missing_reason.status_code == 400
    assert _error_code(missing_reason) == "memorial_contribution_reason_required"

    rejected = _reject(client, contribution_id)
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["visibility"] == "private"
    assert rejected.json()["public_removed"] is True
    assert rejected.json()["rejected_at"]
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []

    rows = client.get(
        "/memorials/manfred/contributions/operator",
        headers={"x-memorial-write-token": "unit-write-token"},
    ).json()["contributions"]
    record = rows[0]
    assert record["status"] == "rejected"
    assert record["public_memory"] == {}
    assert record["history"][-1]["action"] == "operator_rejected"
    assert record["history"][-1]["from_status"] == "pending_review"
    assert record["history"][-1]["to_status"] == "rejected"
    assert record["history"][-1]["reviewer"] == "Memorial curator"
    assert "manage_token_hash" not in json.dumps(record)

    tombstone = json.loads(
        (
            public_root
            / "manfred"
            / "family_contributions.takedowns.public.json"
        ).read_text(encoding="utf-8")
    )
    assert tombstone["takedowns"] == [
        {
            "contribution_id": contribution_id,
            "status": "rejected",
            "recorded_at": rejected.json()["rejected_at"],
            "updated_at": rejected.json()["rejected_at"],
        }
    ]
    assert "RAW_PRIVATE" not in json.dumps(tombstone)
    assert set(tombstone["takedowns"][0]) == {
        "contribution_id",
        "status",
        "recorded_at",
        "updated_at",
    }
    assert (
        client.get(
            "/memorials/files/manfred/family_contributions.takedowns.public.json"
        ).status_code
        == 404
    )

    status = client.get(
        submission["recovery_receipt"]["status_path"],
        headers={"x-memorial-contribution-token": submission["manage_token"]},
    ).json()
    assert status["status"] == "rejected"
    assert status["visibility"] == "private"
    assert "reason" not in json.dumps(status)


def test_operator_unpublish_tombstone_survives_restart_and_stale_projection_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    submission = _submit(client).json()
    contribution_id = submission["contribution_id"]
    invalid_pending_takedown = _unpublish(client, contribution_id)
    assert invalid_pending_takedown.status_code == 409
    assert (
        _error_code(invalid_pending_takedown)
        == "memorial_contribution_not_unpublishable"
    )
    assert _approve(client, contribution_id).status_code == 200
    published_record = client.get(
        "/memorials/manfred/contributions/operator",
        headers={"x-memorial-write-token": "unit-write-token"},
    ).json()["contributions"][0]
    assert client.get("/memorials/manfred.json").json()["memory_cards"]

    removed = _unpublish(client, contribution_id)
    assert removed.status_code == 200
    assert removed.json()["status"] == "unpublished"
    assert removed.json()["visibility"] == "private"
    assert removed.json()["public_removed"] is True
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []
    invalid_unpublished_rejection = _reject(client, contribution_id)
    assert invalid_unpublished_rejection.status_code == 409
    assert (
        _error_code(invalid_unpublished_rejection)
        == "memorial_contribution_not_rejectable"
    )

    from app.services import memorial_family_contributions

    memorial_family_contributions._write_public_projection(
        "manfred", [published_record]
    )
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []

    from app.api.app import create_app

    restarted = TestClient(create_app())
    restarted.headers.update({"X-EA-Principal-ID": "family-contribution-restart"})
    assert restarted.get("/memorials/manfred.json").json()["memory_cards"] == []
    status = restarted.get(
        submission["recovery_receipt"]["status_path"],
        headers={"x-memorial-contribution-token": submission["manage_token"]},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "unpublished"
    assert status.json()["visibility"] == "private"


@pytest.mark.parametrize("failure_point", ["projection", "private_ledger"])
def test_operator_takedown_remains_hidden_across_individual_write_faults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_point: str,
) -> None:
    client, _public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    submission = _submit(client).json()
    contribution_id = submission["contribution_id"]
    assert _approve(client, contribution_id).status_code == 200
    assert client.get("/memorials/manfred.json").json()["memory_cards"]

    from app.services import memorial_family_contributions

    if failure_point == "projection":
        original = memorial_family_contributions._write_public_projection
        monkeypatch.setattr(
            memorial_family_contributions,
            "_write_public_projection",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("projection fault")),
        )
    else:
        original = memorial_family_contributions._save_private_ledger
        monkeypatch.setattr(
            memorial_family_contributions,
            "_save_private_ledger",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private fault")),
        )

    failed = _unpublish(client, contribution_id)
    assert failed.status_code == 503
    assert _error_code(failed) == "memorial_contribution_store_unavailable"
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []
    effective_status = client.get(
        submission["recovery_receipt"]["status_path"],
        headers={"x-memorial-contribution-token": submission["manage_token"]},
    )
    assert effective_status.status_code == 200
    assert effective_status.json()["status"] == "unpublished"
    assert effective_status.json()["visibility"] == "private"
    assert effective_status.json()["timestamps"]["takedown_recorded_at"]

    if failure_point == "projection":
        monkeypatch.setattr(
            memorial_family_contributions, "_write_public_projection", original
        )
    else:
        monkeypatch.setattr(
            memorial_family_contributions, "_save_private_ledger", original
        )
    retried = _unpublish(client, contribution_id)
    assert retried.status_code == 200
    assert retried.json()["status"] == "unpublished"
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []


@pytest.mark.parametrize(
    ("actor", "expected_action"),
    [
        ("operator", "operator_unpublished"),
        ("contributor", "contributor_withdrew"),
    ],
)
def test_saturated_history_compacts_without_blocking_public_removal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actor: str,
    expected_action: str,
) -> None:
    client, _public_root, private_root = _memorial_client(monkeypatch, tmp_path)
    submission = _submit(client).json()
    contribution_id = submission["contribution_id"]
    assert _approve(client, contribution_id).status_code == 200
    assert client.get("/memorials/manfred.json").json()["memory_cards"]

    ledger_path = private_root / "manfred" / "family_contributions.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["contributions"][0]["history"] = [
        {
            "action": f"prior_event_{index:02d}",
            "recorded_at": (
                f"2026-07-10T{8 + (index // 60):02d}:{index % 60:02d}:00Z"
            ),
        }
        for index in range(64)
    ]
    ledger["contributions"][0].pop("history_compaction", None)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ledger_path.chmod(0o600)

    if actor == "operator":
        removed = _unpublish(client, contribution_id)
    else:
        removed = client.post(
            f"/memorials/manfred/contributions/{contribution_id}/withdraw",
            headers={
                "x-memorial-contribution-token": submission["manage_token"]
            },
            json={"reason": "Contributor requested removal."},
        )

    assert removed.status_code == 200
    assert removed.json()["public_removed"] is True
    assert client.get("/memorials/manfred.json").json()["memory_cards"] == []
    stored = json.loads(ledger_path.read_text(encoding="utf-8"))["contributions"][0]
    assert len(stored["history"]) == 64
    assert stored["history"][0]["action"] == "prior_event_01"
    assert stored["history"][-1]["action"] == expected_action
    compaction = stored["history_compaction"]
    assert set(compaction) == {"schema", "evicted_count", "evicted_sha256"}
    assert (
        compaction["schema"]
        == "ea.memorial_family_contribution.history_compaction.v1"
    )
    assert compaction["evicted_count"] == 1
    assert len(compaction["evicted_sha256"]) == 64
    assert compaction["evicted_sha256"] != "0" * 64
    first_event = {
        "action": "prior_event_00",
        "recorded_at": "2026-07-10T08:00:00Z",
    }
    expected_digest = hashlib.sha256(
        bytes.fromhex("0" * 64)
        + b"\x00"
        + json.dumps(
            first_event,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert compaction["evicted_sha256"] == expected_digest


def test_invalid_takedown_ledger_fails_closed_without_leaking_public_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, public_root, _private_root = _memorial_client(monkeypatch, tmp_path)
    contribution_id = _submit(client).json()["contribution_id"]
    assert _approve(client, contribution_id).status_code == 200
    assert client.get("/memorials/manfred.json").json()["memory_cards"]

    tombstone_path = (
        public_root / "manfred" / "family_contributions.takedowns.public.json"
    )
    tombstone_path.write_text(
        json.dumps(
            {
                "schema": "wrong",
                "slug": "manfred",
                "takedowns": [{"private_submission": "MUST_NOT_ESCAPE"}],
            }
        ),
        encoding="utf-8",
    )

    public_payload = client.get("/memorials/manfred.json")
    assert public_payload.status_code == 200
    assert public_payload.json()["memory_cards"] == []
    assert "MUST_NOT_ESCAPE" not in public_payload.text
    failed = _unpublish(client, contribution_id)
    assert failed.status_code == 503
    assert _error_code(failed) == "memorial_contribution_store_invalid"
