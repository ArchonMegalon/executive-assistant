from __future__ import annotations

from app.repositories.approvals import InMemoryApprovalRepository


def test_inmemory_approvals_create_pending_and_decide() -> None:
    repo = InMemoryApprovalRepository(default_ttl_minutes=60)
    request = repo.create_request(
        session_id="s1",
        step_id="st1",
        reason="approval_required",
        requested_action_json={"action": "artifact.save"},
    )
    pending = repo.list_pending(limit=10)
    assert len(pending) == 1
    assert pending[0].approval_id == request.approval_id
    found = repo.decide(
        request.approval_id,
        decision="approve",
        decided_by="tester",
        reason="looks good",
    )
    assert found is not None
    _request, decision = found
    assert decision.decision == "approved"
    assert decision.decided_by == "tester"
    assert repo.list_pending(limit=10) == []


def test_inmemory_approvals_ttl_auto_expire() -> None:
    repo = InMemoryApprovalRepository(default_ttl_minutes=60)
    request = repo.create_request(
        session_id="s1",
        step_id="st1",
        reason="approval_required",
        requested_action_json={"action": "artifact.save"},
        expires_at="2000-01-01T00:00:00+00:00",
    )
    assert repo.list_pending(limit=10) == []
    history = repo.list_history(limit=10)
    assert len(history) == 1
    assert history[0].approval_id == request.approval_id
    assert history[0].decision == "expired"


def test_inmemory_approvals_expire_endpoint_path() -> None:
    repo = InMemoryApprovalRepository(default_ttl_minutes=60)
    request = repo.create_request(
        session_id="s1",
        step_id="st1",
        reason="approval_required",
        requested_action_json={"action": "artifact.save"},
    )
    found = repo.expire(
        request.approval_id,
        decided_by="tester",
        reason="manual expiry",
    )
    assert found is not None
    _request, decision = found
    assert decision.decision == "expired"
    assert decision.reason == "manual expiry"
