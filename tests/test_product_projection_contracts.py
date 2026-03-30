from __future__ import annotations

from datetime import datetime, timezone

from app.product.projections.decisions import _decision_sla_status
from app.product.projections.common import product_commitment_status, status_open


def test_product_commitment_status_maps_cancelled_to_dropped() -> None:
    assert product_commitment_status("cancelled") == "dropped"
    assert product_commitment_status("completed") == "completed"


def test_status_open_treats_dropped_as_terminal() -> None:
    assert status_open("open") is True
    assert status_open("dropped") is False
    assert status_open("cancelled") is False


def test_decision_sla_status_uses_dynamic_runtime_windows() -> None:
    now = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)

    assert _decision_sla_status("open", "2026-03-30T11:59:00+00:00", now=now) == "due_now"
    assert _decision_sla_status("open", "2026-04-01T11:59:00+00:00", now=now) == "due_soon"
    assert _decision_sla_status("open", "2026-04-03T12:01:00+00:00", now=now) == "on_track"
    assert _decision_sla_status("open", None, now=now) == "unscheduled"
    assert _decision_sla_status("decided", "2026-04-03T12:01:00+00:00", now=now) == "resolved"
