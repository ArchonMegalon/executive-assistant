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


def test_metasurvey_event_session_wiring() -> None:
    src = (ROOT / "ea/app/intake/metasurvey_feedback.py").read_text(encoding="utf-8")
    assert "source=\"external_event_metasurvey\"" in src
    assert "compile_intent_spec(" in src
    assert "create_execution_session(" in src
    assert "mark_execution_step_status(" in src
    assert "finalize_execution_session(" in src
    _pass("v1.20 metasurvey event session wiring")


def test_approvethis_event_session_wiring() -> None:
    src = (ROOT / "ea/app/approvals/normalizer.py").read_text(encoding="utf-8")
    assert "source=\"external_event_approvethis\"" in src
    assert "compile_intent_spec(" in src
    assert "create_execution_session(" in src
    assert "mark_execution_step_status(" in src
    assert "finalize_execution_session(" in src
    _pass("v1.20 approvethis event session wiring")


if __name__ == "__main__":
    test_metasurvey_event_session_wiring()
    test_approvethis_event_session_wiring()
