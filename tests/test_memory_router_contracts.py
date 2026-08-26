from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.api.routes.memory_candidates import build_memorial_approved_pack

REPO_ROOT = Path(__file__).resolve().parents[1]


def _client() -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_MEMORIAL_APPROVED_MEMORY_TOKEN", None)
    os.environ.pop("EA_MEMORIAL_APPROVED_MEMORY_TOKEN_FILE", None)
    os.environ.pop("EA_MEMORIAL_APPROVED_MEMORY_PRINCIPAL_ID", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "exec-1"})
    return client


def test_memory_router_keeps_split_subrouters_mounted_under_v1_memory() -> None:
    client = _client()
    route_paths = {route.path for route in client.app.routes}

    expected_paths = {
        "/v1/memory/candidates",
        "/v1/memory/items/{item_id}",
        "/v1/memory/memorial-approved/{slug}",
        "/v1/memory/entities",
        "/v1/memory/relationships/{relationship_id}",
        "/v1/memory/commitments",
        "/v1/memory/follow-up-rules/{rule_id}",
        "/v1/memory/communication-policies",
        "/v1/memory/stakeholders/{stakeholder_id}",
        "/v1/memory/authority-bindings",
        "/v1/memory/delivery-preferences/{preference_id}",
        "/v1/memory/interruption-budgets/{budget_id}",
    }

    assert expected_paths <= route_paths


def test_memorial_approved_pack_excludes_raw_mail_private_and_unapproved_rows() -> None:
    reviewed = {
        "reviewer": "owner",
        "last_verified_at": "2026-08-26T00:00:00+00:00",
    }
    card = SimpleNamespace(
        item_id="card-1",
        category="memorial_memory_card",
        fact_json={
            "memorial_slug": "manfred",
            "public_approved": True,
            "public_approval_key": "manfred-card-1",
            "title": "Schach und Familie",
            "body": "Schach sollte in der Familie bleiben.",
            "source_label": "Freigegebene Erinnerung",
        },
        **reviewed,
    )
    duplicate = SimpleNamespace(
        item_id="card-duplicate",
        category=card.category,
        fact_json=dict(card.fact_json),
        **reviewed,
    )
    facet = SimpleNamespace(
        item_id="facet-1",
        category="memorial_grounded_profile",
        fact_json={
            "memorial_slug": "manfred",
            "public_approved": True,
            "public_approval_key": "manfred-facet-1",
            "trait": "Direkte Erklärung",
            "evidence": "Schwierige Themen werden knapp und klar erklärt.",
        },
        **reviewed,
    )
    raw_mail = SimpleNamespace(
        item_id="mail-1",
        category="memorial_mail_message",
        fact_json={
            "memorial_slug": "manfred",
            "public_approved": True,
            "body_text": "private sender@example.test content",
        },
        **reviewed,
    )
    unapproved = SimpleNamespace(
        item_id="card-2",
        category="memorial_memory_card",
        fact_json={
            **card.fact_json,
            "public_approved": False,
            "body": "Must not leave EA.",
        },
        **reviewed,
    )

    pack = build_memorial_approved_pack(
        [raw_mail, unapproved, duplicate, facet, card],
        slug="manfred",
    )
    rendered = pack.model_dump_json()

    assert pack.contract_name == "ea.memorial-approved-memory-pack/v1"
    assert pack.raw_mail_content_included is False
    assert len(pack.items) == 2
    assert {item.kind for item in pack.items} == {
        "memory_card",
        "orientation_facet",
    }
    assert "sender@example.test" not in rendered
    assert "Must not leave EA" not in rendered
    assert len(pack.source_set_sha256) == 64


def test_memorial_approved_pack_rejects_non_manfred_slug() -> None:
    with pytest.raises(Exception) as caught:
        build_memorial_approved_pack([], slug="unknown")

    assert getattr(caught.value, "status_code", None) == 404


def test_memorial_approved_route_uses_a_path_scoped_service_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_token = "memorial-service-token-with-at-least-thirty-two-characters"
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("EA_LEDGER_BACKEND", raising=False)
    monkeypatch.setenv("EA_API_TOKEN", "different-global-token-with-at-least-thirty-two-characters")
    monkeypatch.setenv("EA_MEMORIAL_APPROVED_MEMORY_TOKEN", service_token)
    monkeypatch.setenv(
        "EA_MEMORIAL_APPROVED_MEMORY_PRINCIPAL_ID",
        "memorial:manfred",
    )
    from app.api.app import create_app

    client = TestClient(create_app())
    path = "/v1/memory/memorial-approved/manfred"

    accepted = client.get(
        path,
        headers={
            "X-EA-Memorial-Token": service_token,
            "X-EA-Memorial-Principal": "memorial:manfred",
        },
    )
    wrong_principal = client.get(
        path,
        headers={
            "X-EA-Memorial-Token": service_token,
            "X-EA-Memorial-Principal": "someone-else",
        },
    )
    global_token = client.get(
        path,
        headers={
            "X-EA-API-Token": (
                "different-global-token-with-at-least-thirty-two-characters"
            ),
            "X-EA-Principal-ID": "memorial:manfred",
        },
    )

    assert accepted.status_code == 200
    assert accepted.headers["cache-control"] == "no-store"
    assert accepted.json()["raw_mail_content_included"] is False
    assert wrong_principal.status_code == 401
    assert global_token.status_code == 401


def test_memorial_approved_route_loads_service_credential_from_protected_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.api.dependencies import _memorial_approved_memory_service_token

    service_token = "memorial-file-token-with-at-least-thirty-two-characters"
    token_file = tmp_path / "memorial-approved-memory-token"
    token_file.write_text(f"{service_token}\n", encoding="utf-8")
    token_file.chmod(0o600)
    monkeypatch.delenv("EA_MEMORIAL_APPROVED_MEMORY_TOKEN", raising=False)
    monkeypatch.setenv("EA_MEMORIAL_APPROVED_MEMORY_TOKEN_FILE", str(token_file))

    assert _memorial_approved_memory_service_token() == service_token

    token_file.chmod(0o640)

    assert _memorial_approved_memory_service_token() == service_token

    token_file.chmod(0o644)

    assert _memorial_approved_memory_service_token() == ""


def test_memory_commitment_schema_name_does_not_change_product_api_contracts() -> None:
    document = _client().app.openapi()
    schemas = document["components"]["schemas"]

    assert "CommitmentOut" in schemas
    assert "MemoryCommitmentOut" in schemas
    assert not {
        name
        for name in schemas
        if name.endswith("CommitmentOut")
        and name not in {"CommitmentOut", "MemoryCommitmentOut"}
    }
    assert schemas["PersonDetailOut"]["properties"]["commitments"]["items"] == {
        "$ref": "#/components/schemas/CommitmentOut"
    }

    product_responses = {
        ("post", "/app/api/commitments"),
        ("post", "/app/api/commitments/candidates/{candidate_id}/accept"),
        ("get", "/app/api/commitments/{commitment_ref}"),
        ("post", "/app/api/commitments/{commitment_ref}/resolve"),
    }
    for method, path in product_responses:
        response_schema = document["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {"$ref": "#/components/schemas/CommitmentOut"}

    product_commitment_list = document["paths"]["/app/api/commitments"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert product_commitment_list["items"] == {
        "$ref": "#/components/schemas/CommitmentOut"
    }

    for method, path in {
        ("post", "/app/api/people/{person_id}/correct"),
        ("get", "/app/api/people/{person_id}/detail"),
    }:
        response_schema = document["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {"$ref": "#/components/schemas/PersonDetailOut"}

    memory_responses = {
        ("post", "/v1/memory/commitments"),
        ("get", "/v1/memory/commitments/{commitment_id}"),
    }
    for method, path in memory_responses:
        response_schema = document["paths"][path][method]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema == {
            "$ref": "#/components/schemas/MemoryCommitmentOut"
        }

    memory_commitment_list = document["paths"]["/v1/memory/commitments"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert memory_commitment_list["items"] == {
        "$ref": "#/components/schemas/MemoryCommitmentOut"
    }


def test_memory_router_module_is_a_thin_aggregator() -> None:
    source = (REPO_ROOT / "ea/app/api/routes/memory.py").read_text(encoding="utf-8")

    assert "include_router(memory_candidates_router)" in source
    assert "include_router(memory_graph_router)" in source
    assert "include_router(memory_operations_router)" in source
    assert "include_router(memory_governance_router)" in source
    assert "@router.post(" not in source
    assert "@router.get(" not in source


def test_memory_operations_module_is_a_thin_aggregator() -> None:
    source = (REPO_ROOT / "ea/app/api/routes/memory_operations.py").read_text(encoding="utf-8")

    assert "include_router(memory_commitments_router)" in source
    assert "include_router(memory_followups_router)" in source
    assert "include_router(memory_windows_router)" in source
    assert "@router.post(" not in source
    assert "@router.get(" not in source
