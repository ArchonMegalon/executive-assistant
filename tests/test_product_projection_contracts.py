from __future__ import annotations

from app.product.projections.common import product_commitment_status, status_open


def test_product_commitment_status_maps_cancelled_to_dropped() -> None:
    assert product_commitment_status("cancelled") == "dropped"
    assert product_commitment_status("completed") == "completed"


def test_status_open_treats_dropped_as_terminal() -> None:
    assert status_open("open") is True
    assert status_open("dropped") is False
    assert status_open("cancelled") is False
