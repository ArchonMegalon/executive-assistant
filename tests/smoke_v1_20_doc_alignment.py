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


def test_v120_doc_and_runtime_alignment() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/EA_OS_Change_Guide_for_Dev_v1_20_Commitment_OS.md").read_text(encoding="utf-8")
    assert "run_v120_smoke.sh" in readme
    assert "v1.20 commitment OS foundations" in readme
    assert "execution_sessions" in guide
    assert "execution_steps" in guide
    assert "execution_events" in guide
    assert "ea/app/execution/session_store.py" in guide
    assert "smoke_v1_20_gog_session_id_uniqueness.py" in guide
    assert "button_context_action" in guide
    _pass("v1.20 doc/runtime alignment")


if __name__ == "__main__":
    test_v120_doc_and_runtime_alignment()
