from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_proactive_ooda_has_deployable_lightweight_service_and_operator_targets() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    deploy_script = (ROOT / "scripts" / "deploy_proactive_ooda_runtime.sh").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "ea-proactive-ooda:" in compose
    assert "image: ea-runtime:latest" in compose
    assert "python /app/scripts/run_proactive_ooda.py" in compose
    assert "EA_PROACTIVE_OODA_ENABLED=${EA_PROACTIVE_OODA_ENABLED:-0}" in compose
    assert "EA_PROACTIVE_OODA_ARMED_SEND=${EA_PROACTIVE_OODA_CONTAINER_ARMED_SEND:-1}" in compose
    assert "EA_PROACTIVE_OODA_STATE_PATH=${EA_PROACTIVE_OODA_CONTAINER_STATE_PATH:-/data/provider-ledger/proactive_ooda_notified.json}" in compose
    assert "EA_PROACTIVE_OODA_RECEIPT_PATH=${EA_PROACTIVE_OODA_CONTAINER_RECEIPT_PATH:-/data/provider-ledger/proactive_ooda_latest_run.generated.json}" in compose
    assert "EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED=${EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED:-0}" in compose
    assert "DATABASE_URL=${DATABASE_URL:-postgresql://postgres:${POSTGRES_PASSWORD}@ea-db:5432/ea}" in compose
    assert "ea_provider_ledger:/data/provider-ledger" in compose
    assert "ea-proactive-ooda" in makefile
    assert "deploy-ea-ooda-runtime:" in makefile
    assert "bash scripts/deploy_proactive_ooda_runtime.sh" in makefile
    assert "proactive-ooda-safe-work:" in makefile
    assert "verify-proactive-ooda:" in makefile
    assert "verify-proactive-ooda-live-receipt:" in makefile
    assert "EA_OODA_DEPLOY_DOCKER_EXEC_TIMEOUT_SECONDS" in deploy_script
    assert "timeout --kill-after=10s" in deploy_script
    assert "run_ooda_exec property-scout-disabled" in deploy_script
    assert "run_ooda_exec teable-resync" in deploy_script
    assert "compose up -d --no-build --no-deps --force-recreate ea-proactive-ooda ea-telegram-teable-sync" in deploy_script
    assert "bootstrap_proactive_ooda_teable_tables.py\" --create-missing --write-config" in deploy_script
    assert "resync_proactive_ooda_teable_projection.py" in deploy_script
    assert "verify_proactive_ooda_operator_status.py" in deploy_script
    assert "verify_proactive_ooda_gold_acceptance.py" in deploy_script
    assert "_scheduler_property_scout_enabled" in deploy_script
    assert "EA_PROACTIVE_OODA_DISCOVERY_JSON=" in env_example
    assert "EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON=" in env_example
    assert "EA_PROACTIVE_OODA_ARMED_SEND=0" in env_example
    assert "EA_PROACTIVE_OODA_CONTAINER_ARMED_SEND=1" in env_example
    assert "EA_PROACTIVE_OODA_RECEIPT_PATH=" in env_example
    assert "EA_PROACTIVE_OODA_CONTAINER_RECEIPT_PATH=/data/provider-ledger/proactive_ooda_latest_run.generated.json" in env_example
    assert "EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED=1" in env_example
    assert "EA_PROACTIVE_OODA_STAGE_PACKET_DIR=" in env_example
    assert "EA_PROACTIVE_OODA_SAFE_WORK_RESULTS_ENABLED=1" in env_example
    assert "EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR=" in env_example
    assert "EA_PROACTIVE_OODA_SAFE_WORK_LIMIT=100" in env_example
    assert "EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_ENABLED=1" in env_example
    assert "EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_LIMIT=6" in env_example
    assert "EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_TIMEOUT_SECONDS=10" in env_example
    assert "EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED=0" in env_example
    assert "EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID=" in env_example
    assert '"proactive_ooda_runs"' in env_example
    assert '"proactive_ooda_items"' in env_example
    assert '"proactive_ooda_safe_work"' in env_example
