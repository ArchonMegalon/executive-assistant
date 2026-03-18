from __future__ import annotations

from app.domain.models import TaskContract, now_utc_iso
from app.repositories.task_contracts import InMemoryTaskContractRepository


def test_inmemory_task_contracts_upsert_get_list() -> None:
    repo = InMemoryTaskContractRepository()
    row = repo.upsert(
        TaskContract(
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
    )
    assert row.task_key == "rewrite_text"
    found = repo.get("rewrite_text")
    assert found is not None
    assert found.deliverable_type == "rewrite_note"
    assert found.runtime_policy_json == {}
    listed = repo.list_all(limit=10)
    assert len(listed) == 1


def test_inmemory_task_contracts_list_tracks_updated_order() -> None:
    repo = InMemoryTaskContractRepository()
    first = repo.upsert(
        TaskContract(
            task_key="alpha",
            deliverable_type="rewrite_note",
            default_risk_class="low",
            default_approval_class="none",
            allowed_tools=("artifact_repository",),
            evidence_requirements=(),
            memory_write_policy="reviewed_only",
            budget_policy_json={},
            updated_at=now_utc_iso(),
        )
    )
    second = repo.upsert(
        TaskContract(
            task_key="beta",
            deliverable_type="rewrite_note",
            default_risk_class="low",
            default_approval_class="none",
            allowed_tools=("artifact_repository",),
            evidence_requirements=(),
            memory_write_policy="reviewed_only",
            budget_policy_json={},
            updated_at=now_utc_iso(),
        )
    )
    _ = first, second

    repo.upsert(
        TaskContract(
            task_key="alpha",
            deliverable_type="rewrite_note_v2",
            default_risk_class="low",
            default_approval_class="none",
            allowed_tools=("artifact_repository",),
            evidence_requirements=(),
            memory_write_policy="reviewed_only",
            budget_policy_json={},
            updated_at=now_utc_iso(),
        )
    )

    listed = repo.list_all(limit=10)

    assert [row.task_key for row in listed[:2]] == ["alpha", "beta"]
