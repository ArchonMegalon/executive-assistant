# EA OS (Patched Deployment Bundle)

This bundle fixes the issues identified in the audit:
- **Port coupling bug**: separates external host port from internal container port (always 8090).
- **Postgres permission-denied**: uses a **named volume** for Postgres data.
- **Sudo ownership trap**: deploy script chowns to the real (non-root) operator.
- **Rootless Docker support**: docker socket path configurable via `DOCKER_SOCK`.
- **Ingest endpoints secured**: require `Authorization: Bearer $EA_INGEST_TOKEN`.
- **Operator/debug endpoints secured**: require `Authorization: Bearer $EA_OPERATOR_TOKEN`.
- **Better OCR for German scans**: installs `tesseract-ocr-deu`.
- **Logging**: JSONL file logs + Postgres audit table + `/debug/audit` endpoint.
- **Telegram**: sends daily briefing + a multi-select poll; listens for poll answers and reacts.

## Quick start

1) Copy this folder to `/docker/EA` on your VPS.
2) Create `.env` from `.env.example` and fill in secrets.
3) Edit `config/tenants.yml` and `config/places.yml` with your local tenant/chat/location data.
   Do not commit personal addresses, chat IDs, or geolocation coordinates.
4) Deploy:

```bash
cd /docker/EA
bash scripts/deploy.sh
```

## Smoke tests

```bash
bash scripts/smoke.sh
bash scripts/runbook.sh
bash scripts/docker_e2e.sh
bash scripts/docker_e2e_design_workflows.sh
```

Gate reports are written to `logs/gates/*.json` and uploaded by CI.

## Notes
- The EA container joins the existing `openclaw-net` network to reach LiteLLM and to exec into OpenClaw containers via docker socket.
- If you run rootless Docker, set `DOCKER_SOCK=/run/user/<uid>/docker.sock` in `.env`.
- Default bootstrap admin creation is disabled unless `EA_ALLOW_BOOTSTRAP_ADMIN=true` is explicitly set.
- You can override generic OpenClaw fallback container names with `EA_DEFAULT_OPENCLAW_CONTAINER`.
