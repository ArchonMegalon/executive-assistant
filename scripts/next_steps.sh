#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$EA_ROOT"

echo "========================================="
echo " EA OS - Next Steps Script (Scaffolding) "
echo "========================================="

echo
echo "[1] SECURITY: ensure ingest token is set"
if ! grep -q '^EA_INGEST_TOKEN=' .env || grep -q '^EA_INGEST_TOKEN=CHANGE_ME' .env; then
  echo "-> Generating a strong ingest token and writing to .env"
  TOKEN="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
  sed -i "s/^EA_INGEST_TOKEN=.*/EA_INGEST_TOKEN=${TOKEN}/" .env || echo "EA_INGEST_TOKEN=${TOKEN}" >> .env
  chmod 600 .env
  echo "✅ EA_INGEST_TOKEN set."
else
  echo "✅ EA_INGEST_TOKEN already set."
fi

echo
echo "[2] VERIFY docker socket path (rootless vs rootful)"
DOCKER_SOCK="$(grep '^DOCKER_SOCK=' .env | tail -n1 | cut -d= -f2- || true)"
DOCKER_SOCK="${DOCKER_SOCK:-/var/run/docker.sock}"
if [[ ! -S "${DOCKER_SOCK}" ]]; then
  echo "⚠️ Docker socket not found at ${DOCKER_SOCK}"
  echo "   If you run rootless docker, set DOCKER_SOCK=/run/user/<uid>/docker.sock in .env"
else
  echo "✅ Docker socket present: ${DOCKER_SOCK}"
fi

echo
echo "[3] VERIFY OpenClaw containers referenced in tenants.yml exist"
python - <<'PY'
import yaml, subprocess, sys, pathlib, re
p=pathlib.Path("config/tenants.yml")
cfg=yaml.safe_load(p.read_text())
names=set()
for t,v in cfg.get("tenants", {}).items():
    names.add(v.get("openclaw_container"))
    if v.get("include_family"):
        names.add(v.get("family_openclaw_container"))
names={n for n in names if n}
ps=subprocess.check_output(["docker","ps","--format","{{.Names}}"], text=True).splitlines()
missing=[n for n in sorted(names) if n not in ps]
if missing:
    print("MISSING:", ", ".join(missing))
    sys.exit(2)
print("OK: all OpenClaw containers found.")
PY

echo
echo "[4] TASKER template: location webhook"
HOST_PORT="$(grep '^EA_HOST_PORT=' .env | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"
TOKEN="$(grep '^EA_INGEST_TOKEN=' .env | tail -n1 | cut -d= -f2-)"
cat <<TPL
POST http://<YOUR_VPS>:$HOST_PORT/ingest/location/tibor
Headers: Authorization: Bearer $TOKEN
JSON:
{
  "ts":"2026-02-22T12:34:56Z",
  "lat":48.2082,
  "lon":16.3738,
  "accuracy_m":35,
  "label":"optional human label from Tasker"
}
TPL

echo
echo "[5] WhatsApp memory ingestion template"
cat <<TPL
POST http://<YOUR_VPS>:$HOST_PORT/ingest/whatsapp-memory/tibor
Headers: Authorization: Bearer $TOKEN
JSON:
{
  "ts":"2026-02-22T12:34:56Z",
  "source":"tasker|export|manual",
  "messages":[
    {"dir":"in","from":"+43...","text":"..."},
    {"dir":"out","to":"+43...","text":"..."}
  ]
}
TPL

echo
echo "[6] OPTIONAL: UFW hardening (commented out)"
cat <<'UFW'
# sudo ufw allow 22/tcp
# sudo ufw allow 8090/tcp   # or your EA_HOST_PORT, ideally only via CF tunnel
# sudo ufw enable
UFW

echo
echo "[7] Smoke tests"
bash scripts/smoke.sh || true
EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh /docker/EA || true
echo
echo "Done. Next: configure gog Tasks commands if needed and wire PayPal/refund + delivery tracker workflows."
