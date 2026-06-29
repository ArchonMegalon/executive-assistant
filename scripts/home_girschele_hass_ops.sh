#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="${HOME_GIRSCHELE_COMPOSE_FILE:-$REPO_ROOT/docker-compose.home-girschele.yml}"
COMPOSE_PROJECT="${HOME_GIRSCHELE_COMPOSE_PROJECT:-ea-home-girschele}"
ENV_FILE="${HOME_GIRSCHELE_ENV_FILE:-$REPO_ROOT/.env}"
SERVICE_NAME="${HOME_GIRSCHELE_SERVICE_NAME:-home-girschele-hass}"
DOMAIN="${HOME_GIRSCHELE_DOMAIN:-home.girschele.com}"
PUBLIC_BASE_URL="${HOME_GIRSCHELE_PUBLIC_BASE_URL:-https://$DOMAIN}"
LOCAL_BASE_URL="${HOME_GIRSCHELE_LOCAL_BASE_URL:-http://127.0.0.1:8123}"
CONFIG_DIR="${HOME_GIRSCHELE_HASS_CONFIG_DIR:-$REPO_ROOT/.state/home-girschele/homeassistant-config}"
RECEIPT_PATH="${HOME_GIRSCHELE_HEALTH_RECEIPT:-$REPO_ROOT/.state/home-girschele/homeassistant-health.receipt.json}"
CLOUDFLARE_ENV_FILE="${HOME_GIRSCHELE_CLOUDFLARE_ENV_FILE:-$REPO_ROOT/.env}"
CF_ACCESS_ENV_FILE="${HOME_GIRSCHELE_CF_ACCESS_ENV_FILE:-/docker/fleet/secrets/codexliz-cf-access.env}"
CF_ACCOUNT_ID="${HOME_GIRSCHELE_CLOUDFLARE_ACCOUNT_ID:-}"
CF_TUNNEL_NAME="${HOME_GIRSCHELE_CLOUDFLARE_TUNNEL_NAME:-chummer-run}"
CF_ZONE_ID="${HOME_GIRSCHELE_CLOUDFLARE_ZONE_ID:-bd452cbf817e065da8063fc21673d536}"
ACCESS_EMAILS="${HOME_GIRSCHELE_ACCESS_EMAILS:-Tibor.girschele@gmail.com,Elisabeth.girschele@gmail.com,h.girschele@gmx.de,Archon.megalon@gmail.com}"
STATE_DIR="${HOME_GIRSCHELE_STATE_DIR:-$REPO_ROOT/.state/home-girschele}"
BACKUP_DIR="${HOME_GIRSCHELE_BACKUP_DIR:-$STATE_DIR/backups}"
BACKUP_RECEIPT_PATH="${HOME_GIRSCHELE_BACKUP_RECEIPT:-$STATE_DIR/homeassistant-backup.receipt.json}"
RESTORE_RECEIPT_PATH="${HOME_GIRSCHELE_RESTORE_RECEIPT:-$STATE_DIR/homeassistant-restore-drill.receipt.json}"
DRIFT_RECEIPT_PATH="${HOME_GIRSCHELE_DRIFT_RECEIPT:-$STATE_DIR/homeassistant-drift.receipt.json}"
DISK_LOG_RECEIPT_PATH="${HOME_GIRSCHELE_DISK_LOG_RECEIPT:-$STATE_DIR/homeassistant-disk-log.receipt.json}"
SCHEDULE_RECEIPT_PATH="${HOME_GIRSCHELE_SCHEDULE_RECEIPT:-$STATE_DIR/homeassistant-scheduled-health.receipt.json}"
SCHEDULE_LOG_PATH="${HOME_GIRSCHELE_SCHEDULE_LOG:-$STATE_DIR/scheduled-health.log}"
SYSTEMD_USER_DIR="${HOME_GIRSCHELE_SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SYSTEMD_SERVICE_NAME="${HOME_GIRSCHELE_SYSTEMD_SERVICE_NAME:-home-girschele-health.service}"
SYSTEMD_TIMER_NAME="${HOME_GIRSCHELE_SYSTEMD_TIMER_NAME:-home-girschele-health.timer}"
EXPECTED_TUNNEL_ORIGIN="${HOME_GIRSCHELE_EXPECTED_TUNNEL_ORIGIN:-http://172.17.0.1:8123}"
MIN_FREE_BYTES="${HOME_GIRSCHELE_MIN_FREE_BYTES:-2147483648}"
MAX_DOCKER_LOG_BYTES="${HOME_GIRSCHELE_MAX_DOCKER_LOG_BYTES:-67108864}"

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required tool: $1" >&2
    exit 1
  fi
}

read_env_value() {
  local file="$1"
  local key="$2"
  if [[ ! -f "$file" ]]; then
    return 0
  fi
  sed -n "s/^${key}=//p" "$file" | tail -n 1 | tr -d '\r'
}

load_home_girschele_private_defaults() {
  if [[ -z "$CF_ZONE_ID" ]]; then
    CF_ZONE_ID="$(read_env_value "$CLOUDFLARE_ENV_FILE" HOME_GIRSCHELE_CLOUDFLARE_ZONE_ID)"
  fi
  if [[ -z "$ACCESS_EMAILS" ]]; then
    ACCESS_EMAILS="$(read_env_value "$CLOUDFLARE_ENV_FILE" HOME_GIRSCHELE_ACCESS_EMAILS)"
  fi
  if [[ "$CLOUDFLARE_ENV_FILE" != "$ENV_FILE" ]]; then
    if [[ -z "$CF_ZONE_ID" ]]; then
      CF_ZONE_ID="$(read_env_value "$ENV_FILE" HOME_GIRSCHELE_CLOUDFLARE_ZONE_ID)"
    fi
    if [[ -z "$ACCESS_EMAILS" ]]; then
      ACCESS_EMAILS="$(read_env_value "$ENV_FILE" HOME_GIRSCHELE_ACCESS_EMAILS)"
    fi
  fi
}

load_home_girschele_private_defaults

compose_args() {
  if [[ -f "$ENV_FILE" ]]; then
    printf '%s\n' --env-file "$ENV_FILE" -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE"
  else
    printf '%s\n' -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE"
  fi
}

container_exists() {
  docker inspect "$SERVICE_NAME" >/dev/null 2>&1
}

container_running() {
  [[ "$(docker inspect "$SERVICE_NAME" --format '{{.State.Running}}' 2>/dev/null || true)" == "true" ]]
}

container_config_source() {
  docker inspect "$SERVICE_NAME" --format '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true
}

container_network_mode() {
  docker inspect "$SERVICE_NAME" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true
}

container_log_option() {
  local key="$1"
  docker inspect "$SERVICE_NAME" --format "{{index .HostConfig.LogConfig.Config \"$key\"}}" 2>/dev/null || true
}

container_log_path() {
  docker inspect "$SERVICE_NAME" --format '{{.LogPath}}' 2>/dev/null || true
}

json_bool() {
  if [[ "$1" == true ]]; then
    printf 'true'
  else
    printf 'false'
  fi
}

latest_backup_archive() {
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'homeassistant-config-*.tar.gz' 2>/dev/null | sort | tail -n 1
}

cloudflare_credentials() {
  CF_EMAIL="$(read_env_value "$CLOUDFLARE_ENV_FILE" CLOUDFLARE_EMAIL)"
  CF_API_KEY="$(read_env_value "$CLOUDFLARE_ENV_FILE" CLOUDFLARE_GLOBAL_API_KEY)"
  if [[ -z "$CF_EMAIL" || -z "$CF_API_KEY" || -z "$CF_ZONE_ID" ]]; then
    return 1
  fi
}

cloudflare_access_apps() {
  cloudflare_credentials || return 1
  curl -fsS "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/access/apps?per_page=200" \
    -H "X-Auth-Email: $CF_EMAIL" \
    -H "X-Auth-Key: $CF_API_KEY" \
    -H "Content-Type: application/json"
}

cloudflare_account_id() {
  cloudflare_credentials || return 1
  if [[ -n "$CF_ACCOUNT_ID" ]]; then
    printf '%s' "$CF_ACCOUNT_ID"
    return 0
  fi
  curl -fsS "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID" \
    -H "X-Auth-Email: $CF_EMAIL" \
    -H "X-Auth-Key: $CF_API_KEY" \
    -H "Content-Type: application/json" | jq -r '.result.account.id'
}

cloudflare_tunnel_config() {
  cloudflare_credentials || return 1
  local account_id tunnels tunnel_id
  account_id="$(cloudflare_account_id)"
  [[ -n "$account_id" && "$account_id" != "null" ]] || return 1
  tunnels="$(curl -fsS "https://api.cloudflare.com/client/v4/accounts/$account_id/cfd_tunnel?per_page=100" \
    -H "X-Auth-Email: $CF_EMAIL" \
    -H "X-Auth-Key: $CF_API_KEY" \
    -H "Content-Type: application/json")"
  tunnel_id="$(printf '%s' "$tunnels" | jq -r --arg name "$CF_TUNNEL_NAME" '.result[]? | select(.name == $name) | .id' | head -n 1)"
  [[ -n "$tunnel_id" && "$tunnel_id" != "null" ]] || return 1
  curl -fsS "https://api.cloudflare.com/client/v4/accounts/$account_id/cfd_tunnel/$tunnel_id/configurations" \
    -H "X-Auth-Email: $CF_EMAIL" \
    -H "X-Auth-Key: $CF_API_KEY" \
    -H "Content-Type: application/json"
}

migrate_config() {
  require_tool docker
  local source_dir
  source_dir="$(container_config_source)"

  mkdir -p "$CONFIG_DIR"

  if [[ -z "$source_dir" ]]; then
    if [[ -f "$CONFIG_DIR/configuration.yaml" ]]; then
      echo "HA config already exists at $CONFIG_DIR"
      return 0
    fi
    echo "No existing HA /config mount found and $CONFIG_DIR is empty." >&2
    exit 1
  fi

  if [[ "$source_dir" == "$CONFIG_DIR" ]]; then
    echo "HA config already uses durable path: $CONFIG_DIR"
    return 0
  fi

  if container_running; then
    docker stop "$SERVICE_NAME" >/dev/null
  fi

  docker cp "$SERVICE_NAME:/config/." "$CONFIG_DIR"
  echo "Migrated HA config from $source_dir to $CONFIG_DIR"
}

ensure_proxy_config() {
  require_tool docker
  if ! [[ -f "$CONFIG_DIR/configuration.yaml" ]]; then
    echo "missing HA configuration.yaml at $CONFIG_DIR" >&2
    exit 1
  fi

  if grep -q 'use_x_forwarded_for: true' "$CONFIG_DIR/configuration.yaml" &&
     grep -q '192.168.96.0/24' "$CONFIG_DIR/configuration.yaml"; then
    echo "HA reverse-proxy config is present"
    return 0
  fi

  docker run --rm \
    --entrypoint /bin/sh \
    -v "$CONFIG_DIR:/config" \
    "ghcr.io/home-assistant/home-assistant:${HOME_GIRSCHELE_HASS_IMAGE_TAG:-stable}" \
    -c 'cat >> /config/configuration.yaml <<'"'"'EOF'"'"'

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 192.168.96.0/24
EOF'
  echo "Added HA reverse-proxy config for the Cloudflare tunnel network"
}

up_service() {
  require_tool docker
  local current_source
  current_source="$(container_config_source)"

  if [[ -n "$current_source" && "$current_source" != "$CONFIG_DIR" ]]; then
    if container_running; then
      docker stop "$SERVICE_NAME" >/dev/null
    fi
    docker rm "$SERVICE_NAME" >/dev/null
  fi

  mapfile -t args < <(compose_args)
  docker compose "${args[@]}" --profile home-assistant up -d "$SERVICE_NAME"

  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "$LOCAL_BASE_URL/" >/dev/null 2>&1; then
      echo "HA is reachable at $LOCAL_BASE_URL"
      return 0
    fi
    sleep 2
  done

  echo "HA did not become reachable at $LOCAL_BASE_URL" >&2
  docker logs --tail 120 "$SERVICE_NAME" >&2 || true
  exit 1
}

restore_access() {
  require_tool curl
  require_tool jq

  local email api_key
  email="$(read_env_value "$CLOUDFLARE_ENV_FILE" CLOUDFLARE_EMAIL)"
  api_key="$(read_env_value "$CLOUDFLARE_ENV_FILE" CLOUDFLARE_GLOBAL_API_KEY)"
  if [[ -z "$email" || -z "$api_key" || -z "$CF_ZONE_ID" || -z "$ACCESS_EMAILS" ]]; then
    echo "Cloudflare email, global API key, zone id, or allowed email list is missing." >&2
    exit 1
  fi

  local apps_url apps app_id payload method url emails_json
  apps_url="https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/access/apps"
  apps="$(curl -fsS "$apps_url?per_page=200" \
    -H "X-Auth-Email: $email" \
    -H "X-Auth-Key: $api_key" \
    -H "Content-Type: application/json")"
  app_id="$(printf '%s' "$apps" | jq -r --arg domain "$DOMAIN" '.result[]? | select(.domain == $domain) | .id' | head -n 1)"
  emails_json="$(printf '%s\n' "$ACCESS_EMAILS" | tr ',' '\n' | sed '/^[[:space:]]*$/d' | jq -R '{email:{email:.}}' | jq -s '.')"

  payload="$(jq -n \
    --arg domain "$DOMAIN" \
    --argjson emails "$emails_json" \
    '{
      type: "self_hosted",
      name: "Home",
      domain: $domain,
      self_hosted_domains: [$domain],
      destinations: [{type: "public", uri: $domain}],
      app_launcher_visible: true,
      allowed_idps: [],
      auto_redirect_to_identity: false,
      session_duration: "24h",
      http_only_cookie_attribute: true,
      enable_binding_cookie: false,
      options_preflight_bypass: false,
      policies: [
        {
          name: "Home service token",
          decision: "non_identity",
          include: [{any_valid_service_token: {}}],
          exclude: [],
          require: [],
          precedence: 1
        },
        {
          name: "Home email allow",
          decision: "allow",
          include: $emails,
          exclude: [],
          require: [],
          precedence: 2
        }
      ]
    }')"

  if [[ -n "$app_id" ]]; then
    method=PUT
    url="$apps_url/$app_id"
  else
    method=POST
    url="$apps_url"
  fi

  curl -fsS -X "$method" "$url" \
    -H "X-Auth-Email: $email" \
    -H "X-Auth-Key: $api_key" \
    -H "Content-Type: application/json" \
    --data "$payload" | jq -e '.success == true' >/dev/null

  echo "Cloudflare Access is configured for $DOMAIN"
}

curl_status() {
  local url="$1"
  local headers_file="$2"
  local body_file="$3"
  shift 3
  curl -k -sS --max-time 12 -D "$headers_file" -o "$body_file" -w '%{http_code}' "$@" "$url" || true
}

websocket_probe() {
  local url="$1"
  local headers_file="$2"
  local body_file="$3"
  shift 3
  set +e
  curl -k -sS --http1.1 --max-time 8 \
    -D "$headers_file" \
    -o "$body_file" \
    -H 'Connection: Upgrade' \
    -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' \
    -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
    "$@" "$url" >/dev/null
  local status=$?
  set -e
  if grep -q '^HTTP/1.1 101' "$headers_file"; then
    printf '101'
  else
    printf 'curl_exit_%s' "$status"
  fi
}

health() {
  require_tool curl
  require_tool jq

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir:-}"' RETURN

  local local_root_headers local_root_body local_api_headers local_api_body local_ws_headers local_ws_body
  local public_headers public_body protected_headers protected_body token_headers token_body token_api_headers token_api_body token_ws_headers token_ws_body
  local_root_headers="$tmp_dir/local-root.headers"
  local_root_body="$tmp_dir/local-root.body"
  local_api_headers="$tmp_dir/local-api.headers"
  local_api_body="$tmp_dir/local-api.body"
  local_ws_headers="$tmp_dir/local-ws.headers"
  local_ws_body="$tmp_dir/local-ws.body"
  public_headers="$tmp_dir/public.headers"
  public_body="$tmp_dir/public.body"
  protected_headers="$tmp_dir/protected.headers"
  protected_body="$tmp_dir/protected.body"
  token_headers="$tmp_dir/token.headers"
  token_body="$tmp_dir/token.body"
  token_api_headers="$tmp_dir/token-api.headers"
  token_api_body="$tmp_dir/token-api.body"
  token_ws_headers="$tmp_dir/token-ws.headers"
  token_ws_body="$tmp_dir/token-ws.body"

  local local_root local_api local_ws public_status protected_status token_status token_api token_ws
  local_root="$(curl_status "$LOCAL_BASE_URL/" "$local_root_headers" "$local_root_body" -L)"
  local_api="$(curl_status "$LOCAL_BASE_URL/api/" "$local_api_headers" "$local_api_body")"
  local_ws="$(websocket_probe "$LOCAL_BASE_URL/api/websocket" "$local_ws_headers" "$local_ws_body")"
  public_status="$(curl_status "$PUBLIC_BASE_URL/" "$public_headers" "$public_body")"
  protected_status="$(curl_status "$PUBLIC_BASE_URL/.well-known/cloudflare-access-protected-resource/" "$protected_headers" "$protected_body")"

  local access_client_id access_client_secret token_available
  access_client_id="$(read_env_value "$CF_ACCESS_ENV_FILE" CODEXLIZ_CF_ACCESS_CLIENT_ID)"
  access_client_secret="$(read_env_value "$CF_ACCESS_ENV_FILE" CODEXLIZ_CF_ACCESS_CLIENT_SECRET)"
  if [[ -n "$access_client_id" && -n "$access_client_secret" ]]; then
    token_available=true
    token_status="$(curl_status "$PUBLIC_BASE_URL/" "$token_headers" "$token_body" \
      -H "CF-Access-Client-Id: $access_client_id" \
      -H "CF-Access-Client-Secret: $access_client_secret")"
    token_api="$(curl_status "$PUBLIC_BASE_URL/api/" "$token_api_headers" "$token_api_body" \
      -H "CF-Access-Client-Id: $access_client_id" \
      -H "CF-Access-Client-Secret: $access_client_secret")"
    token_ws="$(websocket_probe "$PUBLIC_BASE_URL/api/websocket" "$token_ws_headers" "$token_ws_body" \
      -H "CF-Access-Client-Id: $access_client_id" \
      -H "CF-Access-Client-Secret: $access_client_secret")"
  else
    token_available=false
    token_status="skipped"
    token_api="skipped"
    token_ws="skipped"
  fi

  local local_frontend_ok local_api_ok local_ws_ok public_guard_ok token_frontend_ok token_api_ok token_ws_ok config_ok access_resource_ok
  grep -qi 'Home Assistant' "$local_root_body" && local_frontend_ok=true || local_frontend_ok=false
  [[ "$local_api" == "401" ]] && local_api_ok=true || local_api_ok=false
  [[ "$local_ws" == "101" ]] && local_ws_ok=true || local_ws_ok=false
  grep -q 'use_x_forwarded_for: true' "$CONFIG_DIR/configuration.yaml" &&
    grep -q '192.168.96.0/24' "$CONFIG_DIR/configuration.yaml" &&
    [[ "$CONFIG_DIR" != /tmp/* ]] && config_ok=true || config_ok=false
  grep -qi '^location: .*cloudflareaccess\.com' "$public_headers" && public_guard_ok=true || public_guard_ok=false
  [[ "$protected_status" == "200" ]] && grep -q '"protected"[[:space:]]*:[[:space:]]*true' "$protected_body" && access_resource_ok=true || access_resource_ok=false
  [[ "$token_status" == "302" || "$token_status" == "200" ]] && token_frontend_ok=true || token_frontend_ok=false
  [[ "$token_api" == "401" ]] && token_api_ok=true || token_api_ok=false
  [[ "$token_ws" == "101" ]] && token_ws_ok=true || token_ws_ok=false

  local pass
  if [[ "$local_frontend_ok" == true &&
        "$local_api_ok" == true &&
        "$local_ws_ok" == true &&
        "$config_ok" == true &&
        "$public_guard_ok" == true &&
        "$access_resource_ok" == true &&
        "$token_available" == true &&
        "$token_frontend_ok" == true &&
        "$token_api_ok" == true &&
        "$token_ws_ok" == true ]]; then
    pass=true
  else
    pass=false
  fi

  mkdir -p "$(dirname "$RECEIPT_PATH")"
  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg domain "$DOMAIN" \
    --arg configDir "$CONFIG_DIR" \
    --arg localRoot "$local_root" \
    --arg localApi "$local_api" \
    --arg localWs "$local_ws" \
    --arg publicStatus "$public_status" \
    --arg protectedStatus "$protected_status" \
    --arg tokenStatus "$token_status" \
    --arg tokenApi "$token_api" \
    --arg tokenWs "$token_ws" \
    --argjson tokenAvailable "$token_available" \
    --argjson pass "$pass" \
    --argjson localFrontendOk "$local_frontend_ok" \
    --argjson localApiOk "$local_api_ok" \
    --argjson localWsOk "$local_ws_ok" \
    --argjson configOk "$config_ok" \
    --argjson publicGuardOk "$public_guard_ok" \
    --argjson accessResourceOk "$access_resource_ok" \
    --argjson tokenFrontendOk "$token_frontend_ok" \
    --argjson tokenApiOk "$token_api_ok" \
    --argjson tokenWsOk "$token_ws_ok" \
    '{
      contractName: "home.girschele.home_assistant.health.v1",
      generatedAt: $generatedAt,
      domain: $domain,
      status: (if $pass then "pass" else "fail" end),
      config: {
        configDir: $configDir,
        outsideTmp: ($configDir | startswith("/tmp/") | not),
        reverseProxyConfigPresent: $configOk
      },
      checks: {
        localFrontend: {httpStatus: $localRoot, ok: $localFrontendOk},
        localApiUnauthorized: {httpStatus: $localApi, ok: $localApiOk},
        localWebSocketUpgrade: {status: $localWs, ok: $localWsOk},
        publicAccessGuard: {httpStatus: $publicStatus, redirectedToCloudflareAccess: $publicGuardOk},
        accessProtectedResource: {httpStatus: $protectedStatus, protectedTrue: $accessResourceOk},
        serviceTokenAvailable: $tokenAvailable,
        serviceTokenFrontend: {httpStatus: $tokenStatus, ok: $tokenFrontendOk},
        serviceTokenApiUnauthorized: {httpStatus: $tokenApi, ok: $tokenApiOk},
        serviceTokenWebSocketUpgrade: {status: $tokenWs, ok: $tokenWsOk}
      }
    }' > "$RECEIPT_PATH"

  jq -r '"home.girschele.com health: " + .status + " (" + .generatedAt + ")"' "$RECEIPT_PATH"
  if [[ "$pass" != true ]]; then
    jq '.' "$RECEIPT_PATH"
    exit 1
  fi
}

backup_config() {
  require_tool python3
  require_tool jq
  require_tool sha256sum

  if [[ ! -d "$CONFIG_DIR" || ! -f "$CONFIG_DIR/configuration.yaml" ]]; then
    echo "missing HA config directory at $CONFIG_DIR" >&2
    exit 1
  fi

  mkdir -p "$BACKUP_DIR" "$(dirname "$BACKUP_RECEIPT_PATH")"
  local timestamp archive manifest archive_sha archive_size file_count required_json required_ok
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$BACKUP_DIR/homeassistant-config-$timestamp.tar.gz"
  manifest="$BACKUP_DIR/homeassistant-config-$timestamp.manifest.json"

  python3 - "$CONFIG_DIR" "$archive" "$manifest" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tarfile

root = Path(sys.argv[1]).resolve()
archive = Path(sys.argv[2])
manifest = Path(sys.argv[3])

excluded_names = {".ha_run.lock"}
excluded_prefixes = ("home-assistant.log",)
entries: list[dict[str, object]] = []

with tarfile.open(archive, "w:gz") as tar:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not rel or path.is_dir():
            continue
        if path.name in excluded_names or any(path.name.startswith(prefix) for prefix in excluded_prefixes):
            continue
        tar.add(path, arcname=rel, recursive=False)
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append({"path": rel, "size": path.stat().st_size, "sha256": digest})
        else:
            entries.append({"path": rel, "size": 0, "sha256": ""})

required = [
    "configuration.yaml",
    ".storage/auth",
    ".storage/core.config_entries",
    "home-assistant_v2.db",
]
present = {entry["path"] for entry in entries}
manifest.write_text(
    json.dumps(
        {
            "root": str(root),
            "archive": str(archive),
            "fileCount": len(entries),
            "requiredPaths": [{"path": item, "present": item in present} for item in required],
            "files": entries,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

  archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
  archive_size="$(stat -c '%s' "$archive")"
  file_count="$(jq -r '.fileCount' "$manifest")"
  required_json="$(jq -c '.requiredPaths' "$manifest")"
  required_ok="$(jq -r 'all(.requiredPaths[]; .present == true)' "$manifest")"

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg configDir "$CONFIG_DIR" \
    --arg archivePath "$archive" \
    --arg manifestPath "$manifest" \
    --arg archiveSha256 "$archive_sha" \
    --argjson archiveSize "$archive_size" \
    --argjson fileCount "$file_count" \
    --argjson requiredPaths "$required_json" \
    --argjson requiredOk "$(json_bool "$required_ok")" \
    '{
      contractName: "home.girschele.home_assistant.backup.v1",
      generatedAt: $generatedAt,
      status: (if $requiredOk and ($archiveSize > 0) and ($fileCount > 0) then "pass" else "fail" end),
      configDir: $configDir,
      archive: {
        path: $archivePath,
        sha256: $archiveSha256,
        sizeBytes: $archiveSize,
        fileCount: $fileCount,
        manifestPath: $manifestPath
      },
      requiredPaths: $requiredPaths,
      excludes: ["home-assistant.log*", ".ha_run.lock"]
    }' > "$BACKUP_RECEIPT_PATH"

  jq -r '"home.girschele.com backup: " + .status + " " + .archive.path' "$BACKUP_RECEIPT_PATH"
  if [[ "$(jq -r '.status' "$BACKUP_RECEIPT_PATH")" != "pass" ]]; then
    jq '.' "$BACKUP_RECEIPT_PATH"
    exit 1
  fi
}

restore_drill() {
  require_tool docker
  require_tool jq
  require_tool tar
  require_tool sha256sum

  local archive="${1:-}"
  if [[ -z "$archive" ]]; then
    archive="$(latest_backup_archive)"
  fi
  if [[ -z "$archive" || ! -f "$archive" ]]; then
    backup_config
    archive="$(latest_backup_archive)"
  fi

  local tmp_dir restore_dir archive_sha expected_sha archive_size required_ok config_ok config_exit
  tmp_dir="$(mktemp -d)"
  restore_dir="$tmp_dir/config"
  mkdir -p "$restore_dir" "$(dirname "$RESTORE_RECEIPT_PATH")"
  trap 'rm -rf "${tmp_dir:-}"' RETURN

  tar -xzf "$archive" -C "$restore_dir"
  archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
  expected_sha="$(jq -r '.archive.sha256 // empty' "$BACKUP_RECEIPT_PATH" 2>/dev/null || true)"
  archive_size="$(stat -c '%s' "$archive")"

  if [[ -f "$restore_dir/configuration.yaml" &&
        -f "$restore_dir/.storage/auth" &&
        -f "$restore_dir/.storage/core.config_entries" &&
        -f "$restore_dir/home-assistant_v2.db" ]]; then
    required_ok=true
  else
    required_ok=false
  fi

  set +e
  docker run --rm \
    --entrypoint python \
    -v "$restore_dir:/config" \
    "ghcr.io/home-assistant/home-assistant:${HOME_GIRSCHELE_HASS_IMAGE_TAG:-stable}" \
    -m homeassistant --script check_config --config /config >/tmp/home-girschele-restore-check.log 2>&1
  config_exit=$?
  set -e
  if [[ "$config_exit" == "0" ]]; then
    config_ok=true
  else
    config_ok=false
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg archivePath "$archive" \
    --arg archiveSha256 "$archive_sha" \
    --arg expectedSha256 "$expected_sha" \
    --argjson archiveSize "$archive_size" \
    --argjson requiredOk "$(json_bool "$required_ok")" \
    --argjson configOk "$(json_bool "$config_ok")" \
    --argjson configExit "$config_exit" \
    '{
      contractName: "home.girschele.home_assistant.restore_drill.v1",
      generatedAt: $generatedAt,
      status: (if $requiredOk and $configOk and ($archiveSize > 0) then "pass" else "fail" end),
      drillType: "non_destructive_temp_extract",
      archive: {
        path: $archivePath,
        sha256: $archiveSha256,
        expectedSha256: $expectedSha256,
        sizeBytes: $archiveSize
      },
      checks: {
        requiredStateFilesPresent: $requiredOk,
        homeAssistantCheckConfig: {exitCode: $configExit, ok: $configOk}
      }
    }' > "$RESTORE_RECEIPT_PATH"

  jq -r '"home.girschele.com restore drill: " + .status + " " + .archive.path' "$RESTORE_RECEIPT_PATH"
  if [[ "$(jq -r '.status' "$RESTORE_RECEIPT_PATH")" != "pass" ]]; then
    jq '.checks' "$RESTORE_RECEIPT_PATH"
    cat /tmp/home-girschele-restore-check.log >&2 || true
    exit 1
  fi
}

drift_check() {
  require_tool curl
  require_tool docker
  require_tool jq

  mkdir -p "$(dirname "$DRIFT_RECEIPT_PATH")"
  local source_dir network_mode log_max_size log_max_file container_running_ok mount_ok network_ok log_ok compose_ok
  source_dir="$(container_config_source)"
  network_mode="$(container_network_mode)"
  log_max_size="$(container_log_option max-size)"
  log_max_file="$(container_log_option max-file)"

  container_running && container_running_ok=true || container_running_ok=false
  [[ "$source_dir" == "$CONFIG_DIR" && "$source_dir" != /tmp/* ]] && mount_ok=true || mount_ok=false
  [[ "$network_mode" == "host" ]] && network_ok=true || network_ok=false
  [[ "$log_max_size" == "10m" && "$log_max_file" == "3" ]] && log_ok=true || log_ok=false
  if [[ -f "$COMPOSE_FILE" ]] &&
     grep -q "$SERVICE_NAME" "$COMPOSE_FILE" &&
     grep -q 'network_mode: host' "$COMPOSE_FILE" &&
     grep -q 'max-size: "10m"' "$COMPOSE_FILE" &&
     grep -q 'max-file: "3"' "$COMPOSE_FILE"; then
    compose_ok=true
  else
    compose_ok=false
  fi

  local tmp_dir public_headers public_body protected_headers protected_body public_status protected_status public_guard_ok protected_ok
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir:-}"' RETURN
  public_headers="$tmp_dir/public.headers"
  public_body="$tmp_dir/public.body"
  protected_headers="$tmp_dir/protected.headers"
  protected_body="$tmp_dir/protected.body"
  public_status="$(curl_status "$PUBLIC_BASE_URL/" "$public_headers" "$public_body")"
  protected_status="$(curl_status "$PUBLIC_BASE_URL/.well-known/cloudflare-access-protected-resource/" "$protected_headers" "$protected_body")"
  grep -qi '^location: .*cloudflareaccess\.com' "$public_headers" && public_guard_ok=true || public_guard_ok=false
  [[ "$protected_status" == "200" ]] && grep -q '"protected"[[:space:]]*:[[:space:]]*true' "$protected_body" && protected_ok=true || protected_ok=false

  local admin_paths_file admin_paths_json admin_paths_guarded_ok path path_headers path_body path_status path_location path_location_host path_ok
  admin_paths_file="$tmp_dir/admin-paths.jsonl"
  : >"$admin_paths_file"
  admin_paths_guarded_ok=true
  for path in /onboarding.html /config /lovelace; do
    path_headers="$tmp_dir/admin-${path//\//_}.headers"
    path_body="$tmp_dir/admin-${path//\//_}.body"
    path_status="$(curl_status "$PUBLIC_BASE_URL$path" "$path_headers" "$path_body")"
    path_location="$(awk 'BEGIN{IGNORECASE=1} /^location:/{print $2}' "$path_headers" | tr -d '\r' | tail -n 1)"
    path_location_host="$(printf '%s' "$path_location" | sed -E 's#^https?://([^/]+)/?.*#\1#')"
    if [[ "$path_status" =~ ^30[12378]$ && "$path_location" == *cloudflareaccess.com* ]]; then
      path_ok=true
    else
      path_ok=false
      admin_paths_guarded_ok=false
    fi
    jq -cn \
      --arg path "$path" \
      --arg httpStatus "$path_status" \
      --arg locationHost "$path_location_host" \
      --argjson ok "$(json_bool "$path_ok")" \
      '{path: $path, httpStatus: $httpStatus, locationHost: $locationHost, ok: $ok}' >>"$admin_paths_file"
  done
  admin_paths_json="$(jq -s '.' "$admin_paths_file")"

  local tunnel_config tunnel_log tunnel_ok tunnel_source
  tunnel_ok=false
  tunnel_source="cloudflare_api"
  if tunnel_config="$(cloudflare_tunnel_config 2>/dev/null)" &&
     printf '%s' "$tunnel_config" | jq -e --arg domain "$DOMAIN" --arg service "$EXPECTED_TUNNEL_ORIGIN" '
       any(.result.config.ingress[]?; .hostname == $domain and .service == $service)
     ' >/dev/null; then
    tunnel_ok=true
  else
    tunnel_source="cloudflared_log_fallback"
    tunnel_log="$(docker logs chummer-run-cloudflared 2>&1 || true)"
    if grep -q "\"hostname\":\"$DOMAIN\"" <<<"$tunnel_log" && grep -q "\"service\":\"$EXPECTED_TUNNEL_ORIGIN\"" <<<"$tunnel_log"; then
      tunnel_ok=true
    fi
  fi

  local apps access_api_ok access_app_ok service_token_policy_ok email_policy_ok app_summary
  access_api_ok=false
  access_app_ok=false
  service_token_policy_ok=false
  email_policy_ok=false
  app_summary='{}'
  if apps="$(cloudflare_access_apps 2>/dev/null)"; then
    access_api_ok=true
    app_summary="$(printf '%s' "$apps" | jq -c --arg domain "$DOMAIN" '
      (.result // [])
      | map(select((.domain == $domain) or ((.self_hosted_domains // []) | index($domain))))
      | .[0] // {}
    ')"
    [[ "$app_summary" != "{}" ]] && access_app_ok=true || access_app_ok=false
    if printf '%s' "$app_summary" | jq -e '
      any(.policies[]?; .decision == "non_identity" and any(.include[]?; has("any_valid_service_token")))
    ' >/dev/null; then
      service_token_policy_ok=true
    fi
    if printf '%s' "$app_summary" | jq -e '
      any(.policies[]?; .decision == "allow" and any(.include[]?; has("email")))
    ' >/dev/null; then
      email_policy_ok=true
    fi
  fi

  local pass
  if [[ "$container_running_ok" == true &&
        "$mount_ok" == true &&
        "$network_ok" == true &&
        "$log_ok" == true &&
        "$compose_ok" == true &&
        "$public_guard_ok" == true &&
        "$admin_paths_guarded_ok" == true &&
        "$protected_ok" == true &&
        "$tunnel_ok" == true &&
        "$access_api_ok" == true &&
        "$access_app_ok" == true &&
        "$service_token_policy_ok" == true &&
        "$email_policy_ok" == true ]]; then
    pass=true
  else
    pass=false
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg domain "$DOMAIN" \
    --arg expectedConfigDir "$CONFIG_DIR" \
    --arg actualConfigDir "$source_dir" \
    --arg networkMode "$network_mode" \
    --arg logMaxSize "$log_max_size" \
    --arg logMaxFile "$log_max_file" \
    --arg publicStatus "$public_status" \
    --arg protectedStatus "$protected_status" \
    --arg expectedTunnelOrigin "$EXPECTED_TUNNEL_ORIGIN" \
    --arg tunnelSource "$tunnel_source" \
    --argjson adminPaths "$admin_paths_json" \
    --argjson pass "$(json_bool "$pass")" \
    --argjson containerRunningOk "$(json_bool "$container_running_ok")" \
    --argjson mountOk "$(json_bool "$mount_ok")" \
    --argjson networkOk "$(json_bool "$network_ok")" \
    --argjson logOk "$(json_bool "$log_ok")" \
    --argjson composeOk "$(json_bool "$compose_ok")" \
    --argjson publicGuardOk "$(json_bool "$public_guard_ok")" \
    --argjson adminPathsGuardedOk "$(json_bool "$admin_paths_guarded_ok")" \
    --argjson protectedOk "$(json_bool "$protected_ok")" \
    --argjson tunnelOk "$(json_bool "$tunnel_ok")" \
    --argjson accessApiOk "$(json_bool "$access_api_ok")" \
    --argjson accessAppOk "$(json_bool "$access_app_ok")" \
    --argjson serviceTokenPolicyOk "$(json_bool "$service_token_policy_ok")" \
    --argjson emailPolicyOk "$(json_bool "$email_policy_ok")" \
    '{
      contractName: "home.girschele.home_assistant.drift.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      domain: $domain,
      checks: {
        containerRunning: $containerRunningOk,
        durableMount: {ok: $mountOk, expected: $expectedConfigDir, actual: $actualConfigDir},
        hostNetwork: {ok: $networkOk, actual: $networkMode},
        logRotation: {ok: $logOk, maxSize: $logMaxSize, maxFile: $logMaxFile},
        composeContract: $composeOk,
        publicAccessGuard: {httpStatus: $publicStatus, ok: $publicGuardOk},
        adminAndOnboardingPathsGuarded: {ok: $adminPathsGuardedOk, paths: $adminPaths},
        protectedResource: {httpStatus: $protectedStatus, ok: $protectedOk},
        tunnelRoute: {ok: $tunnelOk, expectedOrigin: $expectedTunnelOrigin, source: $tunnelSource},
        cloudflareAccessApi: $accessApiOk,
        cloudflareAccessApp: $accessAppOk,
        serviceTokenPolicy: $serviceTokenPolicyOk,
        emailAllowPolicy: $emailPolicyOk
      }
    }' > "$DRIFT_RECEIPT_PATH"

  jq -r '"home.girschele.com drift: " + .status + " (" + .generatedAt + ")"' "$DRIFT_RECEIPT_PATH"
  if [[ "$(jq -r '.status' "$DRIFT_RECEIPT_PATH")" != "pass" ]]; then
    jq '.checks' "$DRIFT_RECEIPT_PATH"
    exit 1
  fi
}

disk_log_check() {
  require_tool docker
  require_tool jq

  mkdir -p "$(dirname "$DISK_LOG_RECEIPT_PATH")"
  local config_df docker_df config_free_kb docker_free_kb config_free_bytes docker_free_bytes config_dir_bytes log_path log_bytes
  config_df="$(df -Pk "$CONFIG_DIR" | awk 'NR==2 {print $4}')"
  docker_df="$(df -Pk /var/lib/docker | awk 'NR==2 {print $4}')"
  config_free_kb="${config_df:-0}"
  docker_free_kb="${docker_df:-0}"
  config_free_bytes=$((config_free_kb * 1024))
  docker_free_bytes=$((docker_free_kb * 1024))
  config_dir_bytes="$(du -sb "$CONFIG_DIR" | awk '{print $1}')"
  log_path="$(container_log_path)"
  if [[ -n "$log_path" && -f "$log_path" ]]; then
    log_bytes="$(stat -c '%s' "$log_path")"
  else
    log_bytes=0
  fi

  local log_max_size log_max_file config_free_ok docker_free_ok log_size_ok log_rotation_ok pass
  log_max_size="$(container_log_option max-size)"
  log_max_file="$(container_log_option max-file)"
  [[ "$config_free_bytes" -ge "$MIN_FREE_BYTES" ]] && config_free_ok=true || config_free_ok=false
  [[ "$docker_free_bytes" -ge "$MIN_FREE_BYTES" ]] && docker_free_ok=true || docker_free_ok=false
  [[ "$log_bytes" -le "$MAX_DOCKER_LOG_BYTES" ]] && log_size_ok=true || log_size_ok=false
  [[ "$log_max_size" == "10m" && "$log_max_file" == "3" ]] && log_rotation_ok=true || log_rotation_ok=false

  if [[ "$config_free_ok" == true &&
        "$docker_free_ok" == true &&
        "$log_size_ok" == true &&
        "$log_rotation_ok" == true ]]; then
    pass=true
  else
    pass=false
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg configDir "$CONFIG_DIR" \
    --arg logPath "$log_path" \
    --arg logMaxSize "$log_max_size" \
    --arg logMaxFile "$log_max_file" \
    --argjson minFreeBytes "$MIN_FREE_BYTES" \
    --argjson maxLogBytes "$MAX_DOCKER_LOG_BYTES" \
    --argjson configFreeBytes "$config_free_bytes" \
    --argjson dockerFreeBytes "$docker_free_bytes" \
    --argjson configDirBytes "$config_dir_bytes" \
    --argjson logBytes "$log_bytes" \
    --argjson pass "$(json_bool "$pass")" \
    --argjson configFreeOk "$(json_bool "$config_free_ok")" \
    --argjson dockerFreeOk "$(json_bool "$docker_free_ok")" \
    --argjson logSizeOk "$(json_bool "$log_size_ok")" \
    --argjson logRotationOk "$(json_bool "$log_rotation_ok")" \
    '{
      contractName: "home.girschele.home_assistant.disk_log.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      thresholds: {minFreeBytes: $minFreeBytes, maxDockerLogBytes: $maxLogBytes},
      checks: {
        configDiskFree: {ok: $configFreeOk, bytes: $configFreeBytes, configDir: $configDir},
        dockerDiskFree: {ok: $dockerFreeOk, bytes: $dockerFreeBytes},
        configDirSize: {bytes: $configDirBytes},
        dockerLogSize: {ok: $logSizeOk, path: $logPath, bytes: $logBytes},
        dockerLogRotation: {ok: $logRotationOk, maxSize: $logMaxSize, maxFile: $logMaxFile}
      }
    }' > "$DISK_LOG_RECEIPT_PATH"

  jq -r '"home.girschele.com disk/log: " + .status + " (" + .generatedAt + ")"' "$DISK_LOG_RECEIPT_PATH"
  if [[ "$(jq -r '.status' "$DISK_LOG_RECEIPT_PATH")" != "pass" ]]; then
    jq '.checks' "$DISK_LOG_RECEIPT_PATH"
    exit 1
  fi
}

scheduled_health() {
  require_tool jq
  mkdir -p "$(dirname "$SCHEDULE_RECEIPT_PATH")" "$(dirname "$SCHEDULE_LOG_PATH")"
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduled-health start"
    health
    drift_check
    disk_log_check
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduled-health complete"
  } >>"$SCHEDULE_LOG_PATH" 2>&1

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg healthReceipt "$RECEIPT_PATH" \
    --arg driftReceipt "$DRIFT_RECEIPT_PATH" \
    --arg diskLogReceipt "$DISK_LOG_RECEIPT_PATH" \
    --arg logPath "$SCHEDULE_LOG_PATH" \
    '{
      contractName: "home.girschele.home_assistant.scheduled_health.v1",
      generatedAt: $generatedAt,
      status: "pass",
      reusedHealthReceipt: $healthReceipt,
      driftReceipt: $driftReceipt,
      diskLogReceipt: $diskLogReceipt,
      logPath: $logPath
    }' > "$SCHEDULE_RECEIPT_PATH"
  jq -r '"home.girschele.com scheduled health: " + .status + " (" + .generatedAt + ")"' "$SCHEDULE_RECEIPT_PATH"
}

install_scheduled_health() {
  require_tool systemctl
  mkdir -p "$SYSTEMD_USER_DIR" "$(dirname "$SCHEDULE_RECEIPT_PATH")"
  local service_path timer_path systemctl_status pass
  service_path="$SYSTEMD_USER_DIR/$SYSTEMD_SERVICE_NAME"
  timer_path="$SYSTEMD_USER_DIR/$SYSTEMD_TIMER_NAME"

  cat >"$service_path" <<SERVICE
[Unit]
Description=home.girschele.com Home Assistant scheduled health receipt

[Service]
Type=oneshot
WorkingDirectory=$REPO_ROOT
ExecStart=/usr/bin/env bash $REPO_ROOT/scripts/home_girschele_hass_ops.sh scheduled-health
SERVICE

  cat >"$timer_path" <<TIMER
[Unit]
Description=Run home.girschele.com Home Assistant health every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
TIMER

  set +e
  systemctl --user daemon-reload
  systemctl --user enable --now "$SYSTEMD_TIMER_NAME"
  systemctl_status=$?
  set -e
  [[ "$systemctl_status" == "0" ]] && pass=true || pass=false

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg servicePath "$service_path" \
    --arg timerPath "$timer_path" \
    --arg timerName "$SYSTEMD_TIMER_NAME" \
    --argjson systemctlExit "$systemctl_status" \
    --argjson pass "$(json_bool "$pass")" \
    '{
      contractName: "home.girschele.home_assistant.schedule_install.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      servicePath: $servicePath,
      timerPath: $timerPath,
      timerName: $timerName,
      systemctlUserEnableExitCode: $systemctlExit
    }' > "$STATE_DIR/homeassistant-schedule-install.receipt.json"

  jq -r '"home.girschele.com schedule install: " + .status + " (" + .generatedAt + ")"' "$STATE_DIR/homeassistant-schedule-install.receipt.json"
  if [[ "$pass" != true ]]; then
    jq '.' "$STATE_DIR/homeassistant-schedule-install.receipt.json"
    exit 1
  fi
}

case "${1:-health}" in
  migrate-config)
    migrate_config
    ensure_proxy_config
    ;;
  up)
    up_service
    ;;
  restore-access)
    restore_access
    ;;
  health)
    health
    ;;
  backup)
    backup_config
    ;;
  restore-drill)
    shift || true
    restore_drill "${1:-}"
    ;;
  drift)
    drift_check
    ;;
  disk-log)
    disk_log_check
    ;;
  scheduled-health)
    scheduled_health
    ;;
  install-scheduled-health)
    install_scheduled_health
    ;;
  harden)
    migrate_config
    ensure_proxy_config
    up_service
    restore_access
    backup_config
    restore_drill
    drift_check
    disk_log_check
    health
    ;;
  *)
    echo "usage: $0 {migrate-config|up|restore-access|health|backup|restore-drill|drift|disk-log|scheduled-health|install-scheduled-health|harden}" >&2
    exit 2
    ;;
esac
