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


def test_runner_supports_event_worker_role() -> None:
    runner_src = (ROOT / "ea/app/runner.py").read_text(encoding="utf-8")
    assert 'elif r == "event_worker":' in runner_src
    assert "from app.workers.event_worker import poll_external_events" in runner_src
    _pass("v1.19.4 runner event_worker role support")


def test_role_event_worker_is_canonical_shim() -> None:
    role_src = (ROOT / "ea/app/roles/event_worker.py").read_text(encoding="utf-8")
    assert "from app.workers.event_worker import poll_external_events" in role_src
    assert "async def run_event_worker() -> None:" in role_src
    assert "await poll_external_events()" in role_src
    _pass("v1.19.4 role event_worker canonical shim")


def test_compose_event_worker_runs_via_runner_role() -> None:
    compose_src = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ea-event-worker:" in compose_src
    assert "EA_ROLE=event_worker" in compose_src
    assert "python -m app.runner" in compose_src
    _pass("v1.19.4 compose event-worker runner-role alignment")


if __name__ == "__main__":
    test_runner_supports_event_worker_role()
    test_role_event_worker_is_canonical_shim()
    test_compose_event_worker_runs_via_runner_role()
