from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_v121_doc_alignment() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/EA_OS_Change_Guide_for_Dev_v1_21_Task_Contracts.md").read_text(encoding="utf-8")
    assert "EA_OS_Change_Guide_for_Dev_v1_21_Task_Contracts.md" in readme
    assert "task_registry.py" in guide
    assert "TaskContract" in guide
    assert "smoke_v1_21_task_contract_registry.py" in guide
    assert "smoke_v1_21_intent_spec_v2_shape.py" in guide
    assert "smoke_v1_21_provider_broker.py" in guide
    assert "approval_class" in guide
    assert "provider_broker.py" in guide
    assert "capability_router.py" in guide
    _pass("v1.21 doc/code alignment")


if __name__ == "__main__":
    test_v121_doc_alignment()
