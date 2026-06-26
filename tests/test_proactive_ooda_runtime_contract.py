from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_proactive_ooda_has_deployable_lightweight_service_and_operator_targets() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "ea-proactive-ooda:" in compose
    assert "image: ea-runtime:latest" in compose
    assert "python /app/scripts/run_proactive_ooda.py" in compose
    assert "EA_PROACTIVE_OODA_ENABLED=${EA_PROACTIVE_OODA_ENABLED:-0}" in compose
    assert "EA_PROACTIVE_OODA_STATE_PATH=${EA_PROACTIVE_OODA_CONTAINER_STATE_PATH:-/data/provider-ledger/proactive_ooda_notified.json}" in compose
    assert "DATABASE_URL=${DATABASE_URL:-postgresql://postgres:${POSTGRES_PASSWORD}@ea-db:5432/ea}" in compose
    assert "ea_proactive_ooda_state:" in compose
    assert "ea-proactive-ooda" in makefile
    assert "verify-proactive-ooda:" in makefile
    assert "verify-proactive-ooda-live-receipt:" in makefile
    assert "EA_PROACTIVE_OODA_DISCOVERY_JSON=" in env_example
    assert "EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON=" in env_example
    assert "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID=" in env_example
