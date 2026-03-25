from __future__ import annotations

from tests.product_test_helpers import build_product_client, start_workspace


def test_commitment_candidate_detail_endpoint_returns_staged_candidate() -> None:
    client = build_product_client(principal_id="exec-candidate-review")
    start_workspace(client, mode="executive_ops", workspace_name="Executive Office")

    staged = client.post(
        "/app/api/commitments/candidates/stage",
        json={
            "text": "Please send the revised board packet to Sofia by tomorrow morning.",
            "counterparty": "Sofia N.",
            "due_at": "2026-03-26T09:00:00+00:00",
            "kind": "commitment",
        },
    )
    assert staged.status_code == 200
    body = staged.json()
    assert body
    candidate_id = body[0]["candidate_id"]

    detail = client.get(f"/app/api/commitment-candidates/{candidate_id}")
    assert detail.status_code == 200
    candidate = detail.json()
    assert candidate["candidate_id"] == candidate_id
    assert "board packet" in candidate["title"].lower()
    assert candidate["counterparty"] == "Sofia N."
