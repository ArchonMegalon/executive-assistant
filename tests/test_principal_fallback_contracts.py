from __future__ import annotations

import pytest

from app.domain.models import RewriteRequest, TaskExecutionRequest
from app.repositories.task_contracts import InMemoryTaskContractRepository
from app.services.orchestrator import RewriteOrchestrator
from app.services.planner import PlannerService
from app.services.task_contracts import TaskContractService


def test_planner_requires_explicit_effective_principal() -> None:
    planner = PlannerService(TaskContractService(InMemoryTaskContractRepository()))

    with pytest.raises(ValueError, match="principal_id_required"):
        planner.build_plan(task_key="rewrite_text", principal_id="", goal="rewrite this")


def test_orchestrator_rewrite_and_task_execution_require_explicit_principal() -> None:
    orchestrator = RewriteOrchestrator()

    with pytest.raises(ValueError, match="principal_id_required"):
        orchestrator.build_artifact(RewriteRequest(text="scope check"))

    with pytest.raises(ValueError, match="principal_id_required"):
        orchestrator.execute_task_artifact(TaskExecutionRequest(task_key="rewrite_text", text="scope check"))


def test_task_contract_service_requires_explicit_principal_for_rewrite_intent() -> None:
    service = TaskContractService(InMemoryTaskContractRepository())

    with pytest.raises(ValueError, match="principal_id_required"):
        service.compile_rewrite_intent(principal_id="")
