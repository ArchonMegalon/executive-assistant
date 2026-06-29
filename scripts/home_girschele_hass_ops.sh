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
REPLICA_DIR="${HOME_GIRSCHELE_REPLICA_DIR:-/mnt/pcloud/EA/home-girschele/homeassistant-backups}"
LOCAL_RETENTION_COUNT="${HOME_GIRSCHELE_LOCAL_RETENTION_COUNT:-14}"
REPLICA_RETENTION_COUNT="${HOME_GIRSCHELE_REPLICA_RETENTION_COUNT:-30}"
BACKUP_RECEIPT_PATH="${HOME_GIRSCHELE_BACKUP_RECEIPT:-$STATE_DIR/homeassistant-backup.receipt.json}"
REPLICATION_RECEIPT_PATH="${HOME_GIRSCHELE_REPLICATION_RECEIPT:-$STATE_DIR/homeassistant-replication.receipt.json}"
RESTORE_RECEIPT_PATH="${HOME_GIRSCHELE_RESTORE_RECEIPT:-$STATE_DIR/homeassistant-restore-drill.receipt.json}"
REPLICA_RESTORE_RECEIPT_PATH="${HOME_GIRSCHELE_REPLICA_RESTORE_RECEIPT:-$STATE_DIR/homeassistant-replica-restore-drill.receipt.json}"
DRIFT_RECEIPT_PATH="${HOME_GIRSCHELE_DRIFT_RECEIPT:-$STATE_DIR/homeassistant-drift.receipt.json}"
DISK_LOG_RECEIPT_PATH="${HOME_GIRSCHELE_DISK_LOG_RECEIPT:-$STATE_DIR/homeassistant-disk-log.receipt.json}"
ALERT_RECEIPT_PATH="${HOME_GIRSCHELE_ALERT_RECEIPT:-$STATE_DIR/homeassistant-alert.receipt.json}"
CLOUDFLARE_ACCESS_RECEIPT_PATH="${HOME_GIRSCHELE_CLOUDFLARE_ACCESS_RECEIPT:-$STATE_DIR/homeassistant-cloudflare-access.receipt.json}"
CLOUDFLARE_SNAPSHOT_DIR="${HOME_GIRSCHELE_CLOUDFLARE_SNAPSHOT_DIR:-$STATE_DIR/cloudflare-snapshots}"
CLOUDFLARE_SNAPSHOT_RECEIPT_PATH="${HOME_GIRSCHELE_CLOUDFLARE_SNAPSHOT_RECEIPT:-$STATE_DIR/homeassistant-cloudflare-snapshot.receipt.json}"
STATUS_MARKDOWN_PATH="${HOME_GIRSCHELE_STATUS_MARKDOWN:-$STATE_DIR/homeassistant-status.md}"
STATUS_RECEIPT_PATH="${HOME_GIRSCHELE_STATUS_RECEIPT:-$STATE_DIR/homeassistant-status.receipt.json}"
INCIDENT_DRILL_RECEIPT_PATH="${HOME_GIRSCHELE_INCIDENT_DRILL_RECEIPT:-$STATE_DIR/homeassistant-incident-drill.receipt.json}"
SCHEDULE_RECEIPT_PATH="${HOME_GIRSCHELE_SCHEDULE_RECEIPT:-$STATE_DIR/homeassistant-scheduled-health.receipt.json}"
SCHEDULE_LOG_PATH="${HOME_GIRSCHELE_SCHEDULE_LOG:-$STATE_DIR/scheduled-health.log}"
SYSTEMD_USER_DIR="${HOME_GIRSCHELE_SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SYSTEMD_SERVICE_NAME="${HOME_GIRSCHELE_SYSTEMD_SERVICE_NAME:-home-girschele-health.service}"
SYSTEMD_TIMER_NAME="${HOME_GIRSCHELE_SYSTEMD_TIMER_NAME:-home-girschele-health.timer}"
EXPECTED_TUNNEL_ORIGIN="${HOME_GIRSCHELE_EXPECTED_TUNNEL_ORIGIN:-http://172.17.0.1:8123}"
MIN_FREE_BYTES="${HOME_GIRSCHELE_MIN_FREE_BYTES:-2147483648}"
MAX_DOCKER_LOG_BYTES="${HOME_GIRSCHELE_MAX_DOCKER_LOG_BYTES:-67108864}"
CF_SERVICE_TOKEN_NAME="${HOME_GIRSCHELE_CF_SERVICE_TOKEN_NAME:-}"
ALERT_PHONE_HINT="${HOME_GIRSCHELE_ALERT_PHONE_HINT:-*6419}"
ALERT_DRY_RUN="${HOME_GIRSCHELE_ALERT_DRY_RUN:-false}"
ALERT_TELEGRAM_CHAT_ID="${HOME_GIRSCHELE_ALERT_TELEGRAM_CHAT_ID:-}"
EA_LIVE_OPS_SCRIPT="${HOME_GIRSCHELE_EA_LIVE_OPS_SCRIPT:-$REPO_ROOT/scripts/ea_live_ops.py}"

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

latest_replica_archive() {
  find "$REPLICA_DIR" -maxdepth 1 -type f -name 'homeassistant-config-*.tar.gz' 2>/dev/null | sort | tail -n 1
}

archive_manifest_path() {
  local archive="$1"
  printf '%s' "${archive%.tar.gz}.manifest.json"
}

absolute_path() {
  require_tool python3
  python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(strict=False))
PY
}

mount_info_json() {
  local path="$1"
  local target source fstype
  if command -v findmnt >/dev/null 2>&1; then
    target="$(findmnt -T "$path" -o TARGET --noheadings 2>/dev/null | head -n 1 | xargs || true)"
    source="$(findmnt -T "$path" -o SOURCE --noheadings 2>/dev/null | head -n 1 | xargs || true)"
    fstype="$(findmnt -T "$path" -o FSTYPE --noheadings 2>/dev/null | head -n 1 | xargs || true)"
  else
    target=""
    source=""
    fstype=""
  fi
  jq -cn --arg target "$target" --arg source "$source" --arg fstype "$fstype" \
    '{target: $target, source: $source, fstype: $fstype}'
}

prune_backup_archives() {
  local dir="$1"
  local keep="$2"
  local pruned_file="$3"
  : >"$pruned_file"
  [[ "$keep" =~ ^[0-9]+$ ]] || keep=0
  local archives count remove_count archive manifest
  mapfile -t archives < <(find "$dir" -maxdepth 1 -type f -name 'homeassistant-config-*.tar.gz' 2>/dev/null | sort)
  count="${#archives[@]}"
  remove_count=$((count - keep))
  if (( remove_count <= 0 )); then
    return 0
  fi
  for archive in "${archives[@]:0:remove_count}"; do
    manifest="$(archive_manifest_path "$archive")"
    rm -f "$archive" "$manifest"
    jq -cn --arg archive "$archive" --arg manifest "$manifest" \
      '{archive: $archive, manifest: $manifest}' >>"$pruned_file"
  done
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

cloudflare_service_tokens() {
  cloudflare_credentials || return 1
  local account_id
  account_id="$(cloudflare_account_id)"
  [[ -n "$account_id" && "$account_id" != "null" ]] || return 1
  curl -fsS "https://api.cloudflare.com/client/v4/accounts/$account_id/access/service_tokens?per_page=200" \
    -H "X-Auth-Email: $CF_EMAIL" \
    -H "X-Auth-Key: $CF_API_KEY" \
    -H "Content-Type: application/json"
}

cloudflare_matching_service_token() {
  require_tool jq
  local access_client_id tokens
  access_client_id="$(read_env_value "$CF_ACCESS_ENV_FILE" CODEXLIZ_CF_ACCESS_CLIENT_ID)"
  [[ -n "$access_client_id" ]] || return 1
  tokens="$(cloudflare_service_tokens)" || return 1
  printf '%s' "$tokens" | jq -ce --arg clientId "$access_client_id" --arg name "$CF_SERVICE_TOKEN_NAME" '
    (.result // [])
    | map(select(
        (if ($name | length) > 0 then .name == $name else .client_id == $clientId end)
      ))
    | .[0] // empty
    | {id, name, client_id, expires_at}
  '
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

  docker run --rm -i \
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

  local apps_url apps app_id payload method url emails_json token_json token_id token_name token_expires service_token_include
  apps_url="https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/access/apps"
  apps="$(curl -fsS "$apps_url?per_page=200" \
    -H "X-Auth-Email: $email" \
    -H "X-Auth-Key: $api_key" \
    -H "Content-Type: application/json")"
  app_id="$(printf '%s' "$apps" | jq -r --arg domain "$DOMAIN" '.result[]? | select(.domain == $domain) | .id' | head -n 1)"
  emails_json="$(printf '%s\n' "$ACCESS_EMAILS" | tr ',' '\n' | sed '/^[[:space:]]*$/d' | jq -R '{email:{email:.}}' | jq -s '.')"
  if ! token_json="$(cloudflare_matching_service_token 2>/dev/null)"; then
    echo "No Cloudflare Access service token matches the configured client id or HOME_GIRSCHELE_CF_SERVICE_TOKEN_NAME." >&2
    exit 1
  fi
  token_id="$(printf '%s' "$token_json" | jq -r '.id')"
  token_name="$(printf '%s' "$token_json" | jq -r '.name')"
  token_expires="$(printf '%s' "$token_json" | jq -r '.expires_at // empty')"
  service_token_include="$(jq -n --arg tokenId "$token_id" '[{service_token: {token_id: $tokenId}}]')"

  payload="$(jq -n \
    --arg domain "$DOMAIN" \
    --argjson serviceTokenInclude "$service_token_include" \
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
          include: $serviceTokenInclude,
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

  local response api_success named_policy_ok pass
  response="$(curl -fsS -X "$method" "$url" \
    -H "X-Auth-Email: $email" \
    -H "X-Auth-Key: $api_key" \
    -H "Content-Type: application/json" \
    --data "$payload")"
  printf '%s' "$response" | jq -e '.success == true' >/dev/null
  api_success=true
  if printf '%s' "$response" | jq -e --arg tokenId "$token_id" '
    any(.result.policies[]?; .decision == "non_identity" and any(.include[]?; (.service_token.token_id // "") == $tokenId))
  ' >/dev/null; then
    named_policy_ok=true
  else
    named_policy_ok=false
  fi
  [[ "$api_success" == true && "$named_policy_ok" == true ]] && pass=true || pass=false

  mkdir -p "$(dirname "$CLOUDFLARE_ACCESS_RECEIPT_PATH")"
  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg domain "$DOMAIN" \
    --arg method "$method" \
    --arg appId "$(printf '%s' "$response" | jq -r '.result.id // empty')" \
    --arg serviceTokenId "$token_id" \
    --arg serviceTokenName "$token_name" \
    --arg serviceTokenExpiresAt "$token_expires" \
    --argjson apiSuccess "$(json_bool "$api_success")" \
    --argjson namedPolicyOk "$(json_bool "$named_policy_ok")" \
    --argjson pass "$(json_bool "$pass")" \
    '{
      contractName: "home.girschele.home_assistant.cloudflare_access.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      domain: $domain,
      method: $method,
      appId: $appId,
      serviceTokenPolicy: {
        selector: "service_token.token_id",
        serviceTokenId: $serviceTokenId,
        serviceTokenName: $serviceTokenName,
        expiresAt: $serviceTokenExpiresAt,
        ok: $namedPolicyOk
      },
      cloudflareApiSuccess: $apiSuccess
    }' > "$CLOUDFLARE_ACCESS_RECEIPT_PATH"

  jq -r '"Cloudflare Access for home.girschele.com: " + .status + " named token " + .serviceTokenPolicy.serviceTokenName' "$CLOUDFLARE_ACCESS_RECEIPT_PATH"
  if [[ "$pass" != true ]]; then
    jq '.' "$CLOUDFLARE_ACCESS_RECEIPT_PATH"
    exit 1
  fi
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
  require_tool docker
  require_tool jq
  require_tool sha256sum

  if [[ ! -d "$CONFIG_DIR" || ! -f "$CONFIG_DIR/configuration.yaml" ]]; then
    echo "missing HA config directory at $CONFIG_DIR" >&2
    exit 1
  fi

  mkdir -p "$BACKUP_DIR" "$(dirname "$BACKUP_RECEIPT_PATH")"
  local timestamp archive manifest tmp_archive tmp_manifest archive_sha archive_size file_count required_json required_ok
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="$BACKUP_DIR/homeassistant-config-$timestamp.tar.gz"
  manifest="$BACKUP_DIR/homeassistant-config-$timestamp.manifest.json"
  tmp_archive="$BACKUP_DIR/.homeassistant-config-$timestamp.tar.gz.tmp"
  tmp_manifest="$BACKUP_DIR/.homeassistant-config-$timestamp.manifest.json.tmp"
  rm -f "$tmp_archive" "$tmp_manifest"

  docker run --rm -i \
    --entrypoint python \
    -v "$CONFIG_DIR:/config:ro" \
    -v "$BACKUP_DIR:/backup" \
    "ghcr.io/home-assistant/home-assistant:${HOME_GIRSCHELE_HASS_IMAGE_TAG:-stable}" \
    - "$CONFIG_DIR" "$archive" "$manifest" "$(basename "$tmp_archive")" "$(basename "$tmp_manifest")" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tarfile

host_root = sys.argv[1]
host_archive = sys.argv[2]
host_manifest = sys.argv[3]
root = Path("/config")
archive = Path("/backup") / sys.argv[4]
manifest = Path("/backup") / sys.argv[5]

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
            "root": host_root,
            "archive": host_archive,
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
  mv "$tmp_archive" "$archive"
  mv "$tmp_manifest" "$manifest"

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

replicate_backup() {
  require_tool jq
  require_tool python3
  require_tool sha256sum
  require_tool stat

  local archive manifest
  archive="$(latest_backup_archive)"
  if [[ -z "$archive" || ! -f "$archive" ]]; then
    backup_config
    archive="$(latest_backup_archive)"
  fi
  manifest="$(archive_manifest_path "$archive")"

  mkdir -p "$REPLICA_DIR" "$(dirname "$REPLICATION_RECEIPT_PATH")"

  local state_abs replica_abs mount_json offhost_ok mount_target mount_source mount_fstype
  state_abs="$(absolute_path "$STATE_DIR")"
  replica_abs="$(absolute_path "$REPLICA_DIR")"
  mount_json="$(mount_info_json "$replica_abs")"
  mount_target="$(printf '%s' "$mount_json" | jq -r '.target')"
  mount_source="$(printf '%s' "$mount_json" | jq -r '.source')"
  mount_fstype="$(printf '%s' "$mount_json" | jq -r '.fstype')"
  if [[ "$replica_abs" != "$state_abs" &&
        "$replica_abs" != "$state_abs"/* &&
        "$replica_abs" == /mnt/* &&
        -n "$mount_target" &&
        "$mount_source" != "/dev/vda1" ]]; then
    offhost_ok=true
  else
    offhost_ok=false
  fi

  local replica_archive replica_manifest archive_sha replica_sha archive_size manifest_copied copied_ok
  replica_archive="$REPLICA_DIR/$(basename "$archive")"
  replica_manifest="$REPLICA_DIR/$(basename "$manifest")"
  cp -p "$archive" "$replica_archive"
  if [[ -f "$manifest" ]]; then
    cp -p "$manifest" "$replica_manifest"
    manifest_copied=true
  else
    manifest_copied=false
  fi
  archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
  replica_sha="$(sha256sum "$replica_archive" | awk '{print $1}')"
  archive_size="$(stat -c '%s' "$replica_archive")"
  [[ "$archive_sha" == "$replica_sha" && "$archive_size" -gt 0 ]] && copied_ok=true || copied_ok=false

  local local_keep replica_keep tmp_dir local_pruned_file replica_pruned_file local_pruned_json replica_pruned_json pass
  local_keep="$LOCAL_RETENTION_COUNT"
  replica_keep="$REPLICA_RETENTION_COUNT"
  [[ "$local_keep" =~ ^[0-9]+$ ]] || local_keep=14
  [[ "$replica_keep" =~ ^[0-9]+$ ]] || replica_keep=30
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir:-}"' RETURN
  local_pruned_file="$tmp_dir/local-pruned.jsonl"
  replica_pruned_file="$tmp_dir/replica-pruned.jsonl"
  prune_backup_archives "$BACKUP_DIR" "$local_keep" "$local_pruned_file"
  prune_backup_archives "$REPLICA_DIR" "$replica_keep" "$replica_pruned_file"
  local_pruned_json="$(jq -s '.' "$local_pruned_file")"
  replica_pruned_json="$(jq -s '.' "$replica_pruned_file")"

  if [[ "$copied_ok" == true && "$manifest_copied" == true && "$offhost_ok" == true ]]; then
    pass=true
  else
    pass=false
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg sourceArchive "$archive" \
    --arg sourceManifest "$manifest" \
    --arg replicaArchive "$replica_archive" \
    --arg replicaManifest "$replica_manifest" \
    --arg archiveSha256 "$archive_sha" \
    --arg replicaSha256 "$replica_sha" \
    --arg replicaDir "$replica_abs" \
    --arg stateDir "$state_abs" \
    --arg mountTarget "$mount_target" \
    --arg mountSource "$mount_source" \
    --arg mountFstype "$mount_fstype" \
    --argjson archiveSize "$archive_size" \
    --argjson localKeep "$local_keep" \
    --argjson replicaKeep "$replica_keep" \
    --argjson copiedOk "$(json_bool "$copied_ok")" \
    --argjson manifestCopied "$(json_bool "$manifest_copied")" \
    --argjson offhostOk "$(json_bool "$offhost_ok")" \
    --argjson localPruned "$local_pruned_json" \
    --argjson replicaPruned "$replica_pruned_json" \
    --argjson pass "$(json_bool "$pass")" \
    '{
      contractName: "home.girschele.home_assistant.replication.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      source: {archive: $sourceArchive, manifest: $sourceManifest},
      replica: {
        directory: $replicaDir,
        archive: $replicaArchive,
        manifest: $replicaManifest,
        sha256: $replicaSha256,
        sizeBytes: $archiveSize,
        manifestCopied: $manifestCopied
      },
      checks: {
        copiedShaMatches: $copiedOk,
        offHostReplicaTarget: {
          ok: $offhostOk,
          stateDir: $stateDir,
          mountTarget: $mountTarget,
          mountSource: $mountSource,
          fstype: $mountFstype
        }
      },
      retention: {
        localKeep: $localKeep,
        replicaKeep: $replicaKeep,
        localPruned: $localPruned,
        replicaPruned: $replicaPruned
      },
      archiveSha256: $archiveSha256
    }' > "$REPLICATION_RECEIPT_PATH"

  jq -r '"home.girschele.com backup replication: " + .status + " " + .replica.archive' "$REPLICATION_RECEIPT_PATH"
  if [[ "$pass" != true ]]; then
    jq '.checks' "$REPLICATION_RECEIPT_PATH"
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

restore_replica_drill() {
  require_tool docker
  require_tool jq
  require_tool tar
  require_tool sha256sum

  local archive="${1:-}"
  if [[ -z "$archive" ]]; then
    archive="$(latest_replica_archive)"
  fi
  if [[ -z "$archive" || ! -f "$archive" ]]; then
    replicate_backup
    archive="$(latest_replica_archive)"
  fi

  local tmp_dir restore_dir archive_sha expected_sha archive_size required_ok config_ok config_exit
  tmp_dir="$(mktemp -d)"
  restore_dir="$tmp_dir/config"
  mkdir -p "$restore_dir" "$(dirname "$REPLICA_RESTORE_RECEIPT_PATH")"
  trap 'rm -rf "${tmp_dir:-}"' RETURN

  tar -xzf "$archive" -C "$restore_dir"
  archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
  expected_sha="$(jq -r '.replica.sha256 // .archiveSha256 // empty' "$REPLICATION_RECEIPT_PATH" 2>/dev/null || true)"
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
    --name "home-girschele-replica-restore-drill-$(date -u +%Y%m%d%H%M%S)" \
    --entrypoint python \
    -v "$restore_dir:/config" \
    "ghcr.io/home-assistant/home-assistant:${HOME_GIRSCHELE_HASS_IMAGE_TAG:-stable}" \
    -m homeassistant --script check_config --config /config >/tmp/home-girschele-replica-restore-check.log 2>&1
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
      contractName: "home.girschele.home_assistant.replica_restore_drill.v1",
      generatedAt: $generatedAt,
      status: (if $requiredOk and $configOk and ($archiveSize > 0) then "pass" else "fail" end),
      drillType: "fresh_disposable_container_from_replicated_backup",
      archive: {
        path: $archivePath,
        sha256: $archiveSha256,
        expectedSha256: $expectedSha256,
        sizeBytes: $archiveSize,
        source: "replica"
      },
      checks: {
        requiredStateFilesPresent: $requiredOk,
        freshHomeAssistantContainerCheckConfig: {exitCode: $configExit, ok: $configOk}
      }
    }' > "$REPLICA_RESTORE_RECEIPT_PATH"

  jq -r '"home.girschele.com replica restore drill: " + .status + " " + .archive.path' "$REPLICA_RESTORE_RECEIPT_PATH"
  if [[ "$(jq -r '.status' "$REPLICA_RESTORE_RECEIPT_PATH")" != "pass" ]]; then
    jq '.checks' "$REPLICA_RESTORE_RECEIPT_PATH"
    cat /tmp/home-girschele-replica-restore-check.log >&2 || true
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

  local apps access_api_ok access_app_ok service_token_policy_ok email_policy_ok app_summary expected_token_json expected_token_id expected_token_name service_token_policy_mode broad_service_token_policy
  access_api_ok=false
  access_app_ok=false
  service_token_policy_ok=false
  email_policy_ok=false
  expected_token_id=""
  expected_token_name=""
  service_token_policy_mode="missing"
  broad_service_token_policy=false
  app_summary='{}'
  if expected_token_json="$(cloudflare_matching_service_token 2>/dev/null)"; then
    expected_token_id="$(printf '%s' "$expected_token_json" | jq -r '.id')"
    expected_token_name="$(printf '%s' "$expected_token_json" | jq -r '.name')"
  fi
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
      broad_service_token_policy=true
      service_token_policy_mode="any_valid_service_token"
    fi
    if [[ -n "$expected_token_id" ]] && printf '%s' "$app_summary" | jq -e --arg tokenId "$expected_token_id" '
      any(.policies[]?; .decision == "non_identity" and any(.include[]?; (.service_token.token_id // "") == $tokenId))
    ' >/dev/null; then
      service_token_policy_ok=true
      service_token_policy_mode="named_service_token"
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
    --arg serviceTokenPolicyMode "$service_token_policy_mode" \
    --arg expectedServiceTokenId "$expected_token_id" \
    --arg expectedServiceTokenName "$expected_token_name" \
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
    --argjson broadServiceTokenPolicy "$(json_bool "$broad_service_token_policy")" \
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
        serviceTokenPolicy: {
          ok: $serviceTokenPolicyOk,
          mode: $serviceTokenPolicyMode,
          expectedServiceTokenId: $expectedServiceTokenId,
          expectedServiceTokenName: $expectedServiceTokenName,
          broadAnyValidPolicyPresent: $broadServiceTokenPolicy
        },
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

snapshot_cloudflare() {
  require_tool curl
  require_tool jq
  require_tool sha256sum

  local timestamp snapshot_dir tunnel_config apps app_json tunnel_path app_path tunnel_sha app_sha route_ok app_ok token_json expected_token_id named_policy_ok pass
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  snapshot_dir="$CLOUDFLARE_SNAPSHOT_DIR/$timestamp"
  mkdir -p "$snapshot_dir" "$(dirname "$CLOUDFLARE_SNAPSHOT_RECEIPT_PATH")"
  tunnel_path="$snapshot_dir/tunnel-config.json"
  app_path="$snapshot_dir/access-app.json"

  tunnel_config="$(cloudflare_tunnel_config)"
  printf '%s' "$tunnel_config" | jq '.' > "$tunnel_path"
  apps="$(cloudflare_access_apps)"
  app_json="$(printf '%s' "$apps" | jq -c --arg domain "$DOMAIN" '
    (.result // [])
    | map(select((.domain == $domain) or ((.self_hosted_domains // []) | index($domain))))
    | .[0] // {}
  ')"
  printf '%s' "$app_json" | jq '.' > "$app_path"

  tunnel_sha="$(sha256sum "$tunnel_path" | awk '{print $1}')"
  app_sha="$(sha256sum "$app_path" | awk '{print $1}')"
  if printf '%s' "$tunnel_config" | jq -e --arg domain "$DOMAIN" --arg service "$EXPECTED_TUNNEL_ORIGIN" '
    any(.result.config.ingress[]?; .hostname == $domain and .service == $service)
  ' >/dev/null; then
    route_ok=true
  else
    route_ok=false
  fi
  [[ "$app_json" != "{}" ]] && app_ok=true || app_ok=false
  named_policy_ok=false
  expected_token_id=""
  if token_json="$(cloudflare_matching_service_token 2>/dev/null)"; then
    expected_token_id="$(printf '%s' "$token_json" | jq -r '.id')"
    if printf '%s' "$app_json" | jq -e --arg tokenId "$expected_token_id" '
      any(.policies[]?; .decision == "non_identity" and any(.include[]?; (.service_token.token_id // "") == $tokenId))
    ' >/dev/null; then
      named_policy_ok=true
    fi
  fi
  if [[ "$route_ok" == true && "$app_ok" == true && "$named_policy_ok" == true ]]; then
    pass=true
  else
    pass=false
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg snapshotDir "$snapshot_dir" \
    --arg tunnelPath "$tunnel_path" \
    --arg accessAppPath "$app_path" \
    --arg tunnelSha256 "$tunnel_sha" \
    --arg accessAppSha256 "$app_sha" \
    --arg domain "$DOMAIN" \
    --arg expectedTunnelOrigin "$EXPECTED_TUNNEL_ORIGIN" \
    --arg expectedServiceTokenId "$expected_token_id" \
    --argjson routeOk "$(json_bool "$route_ok")" \
    --argjson appOk "$(json_bool "$app_ok")" \
    --argjson namedPolicyOk "$(json_bool "$named_policy_ok")" \
    --argjson pass "$(json_bool "$pass")" \
    '{
      contractName: "home.girschele.home_assistant.cloudflare_snapshot.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      snapshotDir: $snapshotDir,
      files: {
        tunnelConfig: {path: $tunnelPath, sha256: $tunnelSha256},
        accessApp: {path: $accessAppPath, sha256: $accessAppSha256}
      },
      checks: {
        tunnelRoute: {ok: $routeOk, domain: $domain, expectedOrigin: $expectedTunnelOrigin},
        accessAppPresent: $appOk,
        namedServiceTokenPolicy: {ok: $namedPolicyOk, expectedServiceTokenId: $expectedServiceTokenId}
      }
    }' > "$CLOUDFLARE_SNAPSHOT_RECEIPT_PATH"

  jq -r '"home.girschele.com Cloudflare snapshot: " + .status + " " + .snapshotDir' "$CLOUDFLARE_SNAPSHOT_RECEIPT_PATH"
  if [[ "$pass" != true ]]; then
    jq '.checks' "$CLOUDFLARE_SNAPSHOT_RECEIPT_PATH"
    exit 1
  fi
}

send_operator_alert() {
  require_tool jq
  require_tool python3
  local text="$1"
  local dry_run="${2:-$ALERT_DRY_RUN}"
  local whatsapp_output whatsapp_exit whatsapp_json telegram_json bot_token chat_id payload_json telegram_status telegram_reason

  if [[ "$dry_run" == true ]]; then
    jq -cn --arg transport "dry_run" --arg reason "dry_run" '{ok: true, transport: $transport, reason: $reason}'
    return 0
  fi

  whatsapp_output=""
  whatsapp_exit=127
  if [[ -f "$EA_LIVE_OPS_SCRIPT" ]]; then
    set +e
    whatsapp_output="$(python3 "$EA_LIVE_OPS_SCRIPT" send-whatsapp --phone-hint "$ALERT_PHONE_HINT" --text "$text" 2>&1)"
    whatsapp_exit=$?
    set -e
  fi
  if [[ "$whatsapp_exit" == "0" ]] && printf '%s' "$whatsapp_output" | jq -e '.sent == true' >/dev/null 2>&1; then
    printf '%s' "$whatsapp_output" | jq -c '{ok: true, transport: "whatsapp", delivery: .}'
    return 0
  fi
  whatsapp_json="$(printf '%s' "$whatsapp_output" | jq -c '.' 2>/dev/null || jq -cn --arg raw "$(printf '%s' "$whatsapp_output" | head -c 500)" --argjson exitCode "$whatsapp_exit" '{exitCode: $exitCode, raw: $raw}')"

  bot_token="$(read_env_value "$ENV_FILE" EA_TELEGRAM_BOT_TOKEN)"
  chat_id="$(resolve_telegram_chat_id)"
  if [[ -z "$bot_token" || -z "$chat_id" ]]; then
    jq -cn --argjson whatsapp "$whatsapp_json" \
      '{ok: false, transport: "none", reason: "operator_transport_not_configured", whatsappAttempt: $whatsapp}'
    return 1
  fi

  set +e
  telegram_json="$(EA_HA_TG_TOKEN="$bot_token" EA_HA_TG_CHAT="$chat_id" EA_HA_TG_TEXT="$text" python3 - <<'PY'
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

token = os.environ.get("EA_HA_TG_TOKEN", "").strip()
chat_id = os.environ.get("EA_HA_TG_CHAT", "").strip()
text = os.environ.get("EA_HA_TG_TEXT", "").strip()
payload = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode("utf-8")
request = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
except urllib.error.HTTPError as exc:
    print(json.dumps({"status": "failed", "reason": f"telegram_http_{exc.code}", "detail": exc.read().decode("utf-8", errors="ignore")[:160]}))
    raise SystemExit(1)
except Exception as exc:
    print(json.dumps({"status": "failed", "reason": type(exc).__name__}))
    raise SystemExit(1)
try:
    parsed = json.loads(raw or "{}")
except json.JSONDecodeError:
    parsed = {}
result = dict(parsed.get("result") or {}) if isinstance(parsed, dict) else {}
message_id = str(result.get("message_id") or "").strip()
ok = bool(parsed.get("ok"))
print(json.dumps({"status": "sent" if ok else "failed", "message_id": message_id}))
raise SystemExit(0 if ok else 1)
PY
)"
  telegram_status=$?
  set -e
  telegram_reason="$(printf '%s' "$telegram_json" | jq -r '.reason // empty' 2>/dev/null || true)"
  if [[ "$telegram_status" == "0" ]] && printf '%s' "$telegram_json" | jq -e '.status == "sent"' >/dev/null 2>&1; then
    jq -cn --argjson whatsapp "$whatsapp_json" --argjson telegram "$telegram_json" \
      '{ok: true, transport: "telegram", whatsappAttempt: $whatsapp, delivery: $telegram}'
    return 0
  fi
  payload_json="$(printf '%s' "$telegram_json" | jq -c '.' 2>/dev/null || jq -cn --arg raw "$(printf '%s' "$telegram_json" | head -c 500)" '{raw: $raw}')"
  jq -cn --argjson whatsapp "$whatsapp_json" --argjson telegram "$payload_json" --arg reason "${telegram_reason:-telegram_failed}" \
    '{ok: false, transport: "telegram", reason: $reason, whatsappAttempt: $whatsapp, delivery: $telegram}'
  return 1
}

resolve_telegram_chat_id() {
  local chat_id
  chat_id="$ALERT_TELEGRAM_CHAT_ID"
  if [[ -z "$chat_id" ]]; then
    chat_id="$(read_env_value "$ENV_FILE" EA_WHATSAPP_WEB_TG_SUMMARY_CHAT_ID)"
  fi
  if [[ -z "$chat_id" ]]; then
    chat_id="$(read_env_value "$ENV_FILE" EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID)"
  fi
  if [[ -z "$chat_id" ]]; then
    chat_id="$(read_env_value "$ENV_FILE" EA_TELEGRAM_DEFAULT_CHAT_ID)"
  fi
  if [[ -z "$chat_id" ]] && command -v docker >/dev/null 2>&1 && docker inspect ea-api >/dev/null 2>&1; then
    chat_id="$(docker exec -i ea-api python3 - <<'PY' 2>/dev/null || true
from __future__ import annotations

import os

from app.services.proactive_telegram_binding import resolve_proactive_telegram_chat_id

principal = os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID", "").strip()
chat = resolve_proactive_telegram_chat_id(principal_id=principal)
print(str(chat or "").strip())
PY
)"
  fi
  printf '%s' "$chat_id" | tail -n 1 | tr -d '\r'
}

alert_check() {
  require_tool jq
  local mode="${1:-check}"
  local tmp_dir failures_file failures_json failure_count delivery_json delivery_ok message pass
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir:-}"' RETURN
  failures_file="$tmp_dir/failures.jsonl"
  : >"$failures_file"

  if [[ "$mode" == "drill" ]]; then
    jq -cn \
      --arg name "synthetic-incident-drill" \
      --arg receipt "$ALERT_RECEIPT_PATH" \
      --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{name: $name, receipt: $receipt, status: "fail", generatedAt: $generatedAt, synthetic: true}' >>"$failures_file"
  else
    local name receipt status generated_at
    for row in \
      "health|$RECEIPT_PATH" \
      "drift|$DRIFT_RECEIPT_PATH" \
      "disk-log|$DISK_LOG_RECEIPT_PATH"; do
      name="${row%%|*}"
      receipt="${row#*|}"
      if [[ -f "$receipt" ]]; then
        status="$(jq -r '.status // "missing"' "$receipt")"
        generated_at="$(jq -r '.generatedAt // ""' "$receipt")"
      else
        status="missing"
        generated_at=""
      fi
      if [[ "$status" != "pass" ]]; then
        jq -cn --arg name "$name" --arg receipt "$receipt" --arg status "$status" --arg generatedAt "$generated_at" \
          '{name: $name, receipt: $receipt, status: $status, generatedAt: $generatedAt}' >>"$failures_file"
      fi
    done
  fi

  failures_json="$(jq -s '.' "$failures_file")"
  failure_count="$(printf '%s' "$failures_json" | jq 'length')"
  if [[ "$failure_count" == "0" ]]; then
    delivery_json='{"ok":true,"transport":"none","reason":"no_failed_receipts"}'
    delivery_ok=true
    pass=true
  else
    message="home.girschele.com Home Assistant alert: $failure_count failed receipt(s). Check $STATUS_MARKDOWN_PATH and $STATE_DIR."
    set +e
    delivery_json="$(send_operator_alert "$message" "$ALERT_DRY_RUN")"
    delivery_rc=$?
    set -e
    if [[ "$delivery_rc" == "0" ]] && printf '%s' "$delivery_json" | jq -e '.ok == true' >/dev/null; then
      delivery_ok=true
      pass=true
    else
      delivery_ok=false
      pass=false
    fi
  fi

  mkdir -p "$(dirname "$ALERT_RECEIPT_PATH")"
  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg mode "$mode" \
    --arg phoneHint "$ALERT_PHONE_HINT" \
    --argjson failureCount "$failure_count" \
    --argjson failures "$failures_json" \
    --argjson delivery "$delivery_json" \
    --argjson deliveryOk "$(json_bool "$delivery_ok")" \
    --argjson pass "$(json_bool "$pass")" \
    '{
      contractName: "home.girschele.home_assistant.alert.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      mode: $mode,
      watchedReceipts: ["health", "drift", "disk-log"],
      failureCount: $failureCount,
      failures: $failures,
      delivery: ($delivery + {ok: $deliveryOk, phoneHint: $phoneHint})
    }' > "$ALERT_RECEIPT_PATH"

  jq -r '"home.girschele.com alert check: " + .status + " failures=" + (.failureCount|tostring) + " transport=" + (.delivery.transport // "none")' "$ALERT_RECEIPT_PATH"
  if [[ "$pass" != true ]]; then
    jq '.delivery' "$ALERT_RECEIPT_PATH"
    exit 1
  fi
}

status_board() {
  require_tool jq
  require_tool python3
  mkdir -p "$(dirname "$STATUS_MARKDOWN_PATH")" "$(dirname "$STATUS_RECEIPT_PATH")"
  python3 - "$STATUS_MARKDOWN_PATH" "$STATUS_RECEIPT_PATH" \
    "$RECEIPT_PATH" "$BACKUP_RECEIPT_PATH" "$REPLICATION_RECEIPT_PATH" "$RESTORE_RECEIPT_PATH" \
    "$REPLICA_RESTORE_RECEIPT_PATH" "$DRIFT_RECEIPT_PATH" "$DISK_LOG_RECEIPT_PATH" \
    "$CLOUDFLARE_ACCESS_RECEIPT_PATH" "$CLOUDFLARE_SNAPSHOT_RECEIPT_PATH" "$ALERT_RECEIPT_PATH" \
    "$SCHEDULE_RECEIPT_PATH" "$INCIDENT_DRILL_RECEIPT_PATH" <<'PY'
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

status_path = Path(sys.argv[1])
receipt_path = Path(sys.argv[2])
receipt_paths = [Path(item) for item in sys.argv[3:]]
rows: list[dict[str, str]] = []
for path in receipt_paths:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        rows.append(
            {
                "receipt": str(path),
                "contractName": str(data.get("contractName") or path.name),
                "status": str(data.get("status") or "unknown"),
                "generatedAt": str(data.get("generatedAt") or ""),
            }
        )
    else:
        rows.append(
            {
                "receipt": str(path),
                "contractName": path.name,
                "status": "missing",
                "generatedAt": "",
            }
        )
generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
overall = "pass" if all(row["status"] == "pass" for row in rows if "incident-drill" not in row["receipt"]) else "fail"
lines = [
    "# home.girschele.com Home Assistant Status",
    "",
    f"- Generated: `{generated_at}`",
    f"- Overall: `{overall}`",
    "",
    "| Receipt | Status | Generated |",
    "| --- | --- | --- |",
]
for row in rows:
    lines.append(f"| `{row['contractName']}` | `{row['status']}` | `{row['generatedAt']}` |")
status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
receipt = {
    "contractName": "home.girschele.home_assistant.status_board.v1",
    "generatedAt": generated_at,
    "status": overall,
    "statusMarkdownPath": str(status_path),
    "receipts": rows,
}
receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
print(f"home.girschele.com status board: {overall} {status_path}")
raise SystemExit(0 if overall == "pass" else 1)
PY
}

incident_drill() {
  require_tool jq
  local timestamp drill_dir steps_file step command log_path exit_code steps_json pass
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  drill_dir="$STATE_DIR/incident-drills/$timestamp"
  steps_file="$drill_dir/steps.jsonl"
  mkdir -p "$drill_dir" "$(dirname "$INCIDENT_DRILL_RECEIPT_PATH")"
  : >"$steps_file"

  for step in \
    "snapshot-cloudflare|snapshot Cloudflare tunnel and Access app" \
    "restore-access|reapply named-token Cloudflare Access recovery" \
    "backup|create local HA backup" \
    "replicate-backup|replicate backup off host" \
    "restore-replica-drill|prove fresh-container restore from replica" \
    "drift|verify drift invariants" \
    "health|verify public and local HA health" \
    "alert-check|deliver operator alert if health, drift, or disk receipts failed" \
    "status|refresh status board"; do
    command="${step%%|*}"
    log_path="$drill_dir/${command}.log"
    set +e
    "$0" "$command" >"$log_path" 2>&1
    exit_code=$?
    set -e
    jq -cn \
      --arg command "$command" \
      --arg description "${step#*|}" \
      --arg logPath "$log_path" \
      --argjson exitCode "$exit_code" \
      '{command: $command, description: $description, exitCode: $exitCode, ok: ($exitCode == 0), logPath: $logPath}' >>"$steps_file"
  done

  steps_json="$(jq -s '.' "$steps_file")"
  if printf '%s' "$steps_json" | jq -e 'all(.[]; .ok == true)' >/dev/null; then
    pass=true
  else
    pass=false
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg drillDir "$drill_dir" \
    --argjson steps "$steps_json" \
    --argjson pass "$(json_bool "$pass")" \
    '{
      contractName: "home.girschele.home_assistant.incident_drill.v1",
      generatedAt: $generatedAt,
      status: (if $pass then "pass" else "fail" end),
      drillType: "backup_restore_and_cloudflare_access_tunnel_recovery",
      drillDir: $drillDir,
      steps: $steps
    }' > "$INCIDENT_DRILL_RECEIPT_PATH"

  jq -r '"home.girschele.com incident drill: " + .status + " " + .drillDir' "$INCIDENT_DRILL_RECEIPT_PATH"
  if [[ "$pass" != true ]]; then
    jq '.steps[] | select(.ok == false)' "$INCIDENT_DRILL_RECEIPT_PATH"
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
    alert_check
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduled-health complete"
  } >>"$SCHEDULE_LOG_PATH" 2>&1

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg healthReceipt "$RECEIPT_PATH" \
    --arg driftReceipt "$DRIFT_RECEIPT_PATH" \
    --arg diskLogReceipt "$DISK_LOG_RECEIPT_PATH" \
    --arg alertReceipt "$ALERT_RECEIPT_PATH" \
    --arg logPath "$SCHEDULE_LOG_PATH" \
    '{
      contractName: "home.girschele.home_assistant.scheduled_health.v1",
      generatedAt: $generatedAt,
      status: "pass",
      reusedHealthReceipt: $healthReceipt,
      driftReceipt: $driftReceipt,
      diskLogReceipt: $diskLogReceipt,
      alertReceipt: $alertReceipt,
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
  replicate-backup)
    replicate_backup
    ;;
  restore-drill)
    shift || true
    restore_drill "${1:-}"
    ;;
  restore-replica-drill)
    shift || true
    restore_replica_drill "${1:-}"
    ;;
  drift)
    drift_check
    ;;
  disk-log)
    disk_log_check
    ;;
  snapshot-cloudflare)
    snapshot_cloudflare
    ;;
  alert-check)
    alert_check
    ;;
  alert-drill)
    alert_check drill
    ;;
  status)
    status_board
    ;;
  incident-drill)
    incident_drill
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
    replicate_backup
    restore_replica_drill
    snapshot_cloudflare
    drift_check
    disk_log_check
    health
    alert_check
    status_board
    ;;
  *)
    echo "usage: $0 {migrate-config|up|restore-access|health|backup|replicate-backup|restore-drill|restore-replica-drill|drift|disk-log|snapshot-cloudflare|alert-check|alert-drill|status|incident-drill|scheduled-health|install-scheduled-health|harden}" >&2
    exit 2
    ;;
esac
