from __future__ import annotations

import logging

from app.domain.models import IntentSpecV3, TaskContract, now_utc_iso
from app.repositories.task_contracts import InMemoryTaskContractRepository, TaskContractRepository
from app.repositories.task_contracts_postgres import PostgresTaskContractRepository
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


class TaskContractService:
    def __init__(self, repo: TaskContractRepository) -> None:
        self._repo = repo

    def _require_principal_id(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def upsert_contract(
        self,
        *,
        task_key: str,
        deliverable_type: str,
        default_risk_class: str,
        default_approval_class: str,
        allowed_tools: tuple[str, ...] = (),
        evidence_requirements: tuple[str, ...] = (),
        memory_write_policy: str = "reviewed_only",
        budget_policy_json: dict[str, object] | None = None,
    ) -> TaskContract:
        row = TaskContract(
            task_key=str(task_key or "").strip(),
            deliverable_type=str(deliverable_type or ""),
            default_risk_class=str(default_risk_class or "low"),
            default_approval_class=str(default_approval_class or "none"),
            allowed_tools=tuple(str(v) for v in allowed_tools),
            evidence_requirements=tuple(str(v) for v in evidence_requirements),
            memory_write_policy=str(memory_write_policy or "reviewed_only"),
            budget_policy_json=dict(budget_policy_json or {}),
            updated_at=now_utc_iso(),
        )
        return self._repo.upsert(row)

    def get_contract(self, task_key: str) -> TaskContract | None:
        return self._repo.get(task_key)

    def list_contracts(self, limit: int = 100) -> list[TaskContract]:
        return self._repo.list_all(limit=limit)

    def contract_or_default(self, task_key: str) -> TaskContract:
        found = self._repo.get(task_key)
        if found:
            return found
        if task_key == "rewrite_text":
            return TaskContract(
                task_key="rewrite_text",
                deliverable_type="rewrite_note",
                default_risk_class="low",
                default_approval_class="none",
                allowed_tools=("artifact_repository",),
                evidence_requirements=(),
                memory_write_policy="reviewed_only",
                budget_policy_json={"class": "low"},
                updated_at=now_utc_iso(),
            )
        return TaskContract(
            task_key=task_key,
            deliverable_type="generic_artifact",
            default_risk_class="low",
            default_approval_class="none",
            allowed_tools=(),
            evidence_requirements=(),
            memory_write_policy="reviewed_only",
            budget_policy_json={"class": "low"},
            updated_at=now_utc_iso(),
        )

    def compile_rewrite_intent(
        self,
        principal_id: str,
        *,
        goal: str = "rewrite supplied text into an artifact",
    ) -> IntentSpecV3:
        contract = self.contract_or_default("rewrite_text")
        budget_class = str(contract.budget_policy_json.get("class") or "low")
        return IntentSpecV3(
            principal_id=self._require_principal_id(principal_id),
            goal=str(goal or "rewrite supplied text into an artifact"),
            task_type=contract.task_key,
            deliverable_type=contract.deliverable_type,
            risk_class=contract.default_risk_class,
            approval_class=contract.default_approval_class,
            budget_class=budget_class,
            allowed_tools=contract.allowed_tools,
            evidence_requirements=contract.evidence_requirements,
            desired_artifact=contract.deliverable_type,
            memory_write_policy=contract.memory_write_policy,
        )


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def build_task_contract_repo(settings: Settings) -> TaskContractRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.task_contracts")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "task contracts configured for memory")
        return InMemoryTaskContractRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresTaskContractRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresTaskContractRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "task contracts auto fallback", exc)
            log.warning("postgres task-contract backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "task contracts auto backend without DATABASE_URL")
    return InMemoryTaskContractRepository()


def build_task_contract_service(settings: Settings | None = None) -> TaskContractService:
    resolved = settings or get_settings()
    return TaskContractService(build_task_contract_repo(resolved))
