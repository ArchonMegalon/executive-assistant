#!/usr/bin/env bash
set -euo pipefail

[ -f docker-compose.yml ] || { echo "Run this from the Arr repo root"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker is required"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl is required"; exit 1; }

cfg() {
  TUNNEL_TOKEN="${TUNNEL_TOKEN:-dummy}" docker compose "$@"
}

echo "== compose config =="
cfg config -q
echo "PASS docker compose config -q"

all_services="$(cfg config --services)"
echo
echo "== services =="
printf '%s\n' "$all_services"

request_svc="$(printf '%s\n' "$all_services" | awk '/^(seerr_v2|overseerr_v2)$/ {print; exit}')"
bootstrap_svc="$(printf '%s\n' "$all_services" | awk '/^arr_rootpaths_v2$/ {print; exit}')"

services=(
  qbittorrent_v2
  prowlarr_v2
  radarr_v2
  sonarr_v2
  flaresolverr_v2
  gluetun_v2
  jackett_v2
)

if [ -n "${request_svc:-}" ]; then
  services+=("$request_svc")
fi

if printf '%s\n' "$all_services" | grep -qx cloudflared; then
  if [ -n "${TUNNEL_TOKEN:-}" ]; then
    services+=(cloudflared)
  else
    echo
    echo "Skipping cloudflared because TUNNEL_TOKEN is not set"
  fi
fi

echo
echo "== bringing Arr stack up =="
docker compose up -d "${services[@]}"

if [ -n "${bootstrap_svc:-}" ]; then
  echo
  echo "== bootstrapping Arr root paths =="
  docker compose --profile bootstrap up "$bootstrap_svc"
fi

echo
echo "== docker compose ps =="
docker compose ps

echo
echo "== service state / health =="
while read -r svc; do
  [ -n "$svc" ] || continue
  cid="$(docker compose ps -q "$svc" || true)"
  if [ -z "$cid" ]; then
    echo "$svc | missing"
    continue
  fi
  docker inspect --format '{{.Name}} | state={{.State.Status}} | running={{.State.Running}} | health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid"
done < <(printf '%s\n' "$all_services")

probe_http() {
  local name="$1"
  local url="$2"
  local code
  code="$(curl -k -sS -o /dev/null -m 5 -w '%{http_code}' "$url" || true)"
  if [ "$code" = "000" ]; then
    echo "FAIL $name $url"
    return 1
  fi
  echo "PASS $name $url -> HTTP $code"
  return 0
}

echo
echo "== host probes =="
probe_http qbittorrent  http://127.0.0.1:8080/ || true
probe_http prowlarr     http://127.0.0.1:9696/ || true
probe_http radarr       http://127.0.0.1:7878/ || true
probe_http sonarr       http://127.0.0.1:8989/ || true
probe_http flaresolverr http://127.0.0.1:8191/ || true

if [ -n "${request_svc:-}" ]; then
  probe_http "$request_svc" http://127.0.0.1:5055/ || true
fi

echo
echo "== recent logs from unhealthy/exited containers =="
while read -r svc; do
  [ -n "$svc" ] || continue
  cid="$(docker compose ps -q "$svc" || true)"
  [ -n "$cid" ] || continue
  state="$(docker inspect --format '{{.State.Status}}' "$cid")"
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  if [ "$state" != "running" ] || [ "$health" = "unhealthy" ]; then
    echo
    echo "--- $svc ---"
    docker logs --tail 40 "$cid" 2>&1 || true
  fi
done < <(printf '%s\n' "$all_services")
