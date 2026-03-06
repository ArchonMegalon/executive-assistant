from __future__ import annotations

import pytest

from app.domain.models import RewriteRequest
from app.services.orchestrator import RewriteOrchestrator


def test_principal_scoped_rewrite_fetch_helpers_enforce_ownership() -> None:
    orchestrator = RewriteOrchestrator()
    artifact = orchestrator.build_artifact(RewriteRequest(text="scope-check", principal_id="exec-1"))
    session = orchestrator.fetch_session(artifact.execution_session_id)

    assert session is not None
    assert session.receipts
    assert session.run_costs

    scoped_session = orchestrator.fetch_session_for_principal(session.session.session_id, principal_id="exec-1")
    assert scoped_session is not None
    assert scoped_session.session.intent.principal_id == "exec-1"

    scoped_artifact = orchestrator.fetch_artifact_for_principal(artifact.artifact_id, principal_id="exec-1")
    assert scoped_artifact is not None
    assert scoped_artifact[0].artifact_id == artifact.artifact_id
    assert scoped_artifact[1].session.session_id == session.session.session_id

    receipt_id = session.receipts[0].receipt_id
    scoped_receipt = orchestrator.fetch_receipt_for_principal(receipt_id, principal_id="exec-1")
    assert scoped_receipt is not None
    assert scoped_receipt[0].receipt_id == receipt_id
    assert scoped_receipt[1].session.session_id == session.session.session_id

    cost_id = session.run_costs[0].cost_id
    scoped_cost = orchestrator.fetch_run_cost_for_principal(cost_id, principal_id="exec-1")
    assert scoped_cost is not None
    assert scoped_cost[0].cost_id == cost_id
    assert scoped_cost[1].session.session_id == session.session.session_id

    with pytest.raises(PermissionError, match="principal_scope_mismatch"):
        orchestrator.fetch_session_for_principal(session.session.session_id, principal_id="exec-2")

    with pytest.raises(PermissionError, match="principal_scope_mismatch"):
        orchestrator.fetch_artifact_for_principal(artifact.artifact_id, principal_id="exec-2")

    with pytest.raises(PermissionError, match="principal_scope_mismatch"):
        orchestrator.fetch_receipt_for_principal(receipt_id, principal_id="exec-2")

    with pytest.raises(PermissionError, match="principal_scope_mismatch"):
        orchestrator.fetch_run_cost_for_principal(cost_id, principal_id="exec-2")
