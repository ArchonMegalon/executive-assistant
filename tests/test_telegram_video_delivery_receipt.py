from __future__ import annotations

from pathlib import Path

from scripts.materialize_telegram_video_delivery_receipt import build_receipt


def test_telegram_video_delivery_receipt_is_bounded_and_redacted(tmp_path: Path) -> None:
    receipt = build_receipt(output_path=tmp_path / "telegram_video_delivery_operator.generated.json")

    assert receipt["contract_name"] == "ea.telegram_video_delivery_operator_receipt"
    assert receipt["status"] == "bounded_pass"
    assert receipt["live_operator_delivery_required_for_gold"] is True
    checks = {item["code"]: item for item in receipt["checks"]}
    assert all(item["status"] == "pass" for item in checks.values())
    source_context = checks["delivery_receipt_redacts_source_url"]["source_context"]
    assert source_context["source_url_raw_stored"] is False
    assert "secret-token" not in source_context["source_path_redacted"]
