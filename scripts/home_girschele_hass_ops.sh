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
CF_ZONE_ID="${HOME_GIRSCHELE_CLOUDFLARE_ZONE_ID:-}"
ACCESS_EMAILS="${HOME_GIRSCHELE_ACCESS_EMAILS:-}"

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
  trap 'rm -rf "$tmp_dir"' RETURN

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
  harden)
    migrate_config
    ensure_proxy_config
    up_service
    restore_access
    health
    ;;
  *)
    echo "usage: $0 {migrate-config|up|restore-access|health|harden}" >&2
    exit 2
    ;;
esac
