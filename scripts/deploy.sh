#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_MANIFEST_PATH="${RELEASE_MANIFEST_PATH:-${APP_ROOT}/.codex-studio/published/release_manifest.generated.json}"
RELEASE_AUTHORITY_STATUS_PATH="${RELEASE_AUTHORITY_STATUS_PATH:-${APP_ROOT}/.codex-studio/published/release_authority_status.generated.json}"
DEPLOY_CONTEXT_PATH="${DEPLOY_CONTEXT_PATH:-${APP_ROOT}/.codex-studio/published/deploy_context.generated.json}"
EXTRA_COMPOSE_OVERRIDES=()
DEPLOY_PRIMARY_MODE="${EA_DEPLOY_PRIMARY_MODE:-${EA_DEPLOY_PROJECT_MODE:-EA_CORE}}"
DEPLOY_ENABLED_MODES=()
if [[ "${PROPERTYQUARRY_USE_LEGACY_STACK:-0}" == "1" ]]; then
  export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ea}"
else
  export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-propertyquarry}"
fi

memory_only="${PROPERTYQUARRY_MEMORY_ONLY:-${EA_MEMORY_ONLY:-0}}"
bootstrap_db="${PROPERTYQUARRY_BOOTSTRAP_DB:-${EA_BOOTSTRAP_DB:-0}}"
enable_fastestvpn="${PROPERTYQUARRY_ENABLE_FASTESTVPN:-${EA_ENABLE_FASTESTVPN:-0}}"
if [[ "${EA_ENABLE_FASTESTVPN:-0}" == "1" ]]; then
  enable_fastestvpn="1"
fi
enable_cloudflared="${PROPERTYQUARRY_ENABLE_CLOUDFLARED:-${EA_ENABLE_CLOUDFLARED:-auto}}"
run_runtime_hard_exit_gates="${PROPERTYQUARRY_RUN_RUNTIME_HARD_EXIT_GATES:-${EA_RUN_RUNTIME_HARD_EXIT_GATES:-1}}"
cf_tunnel_token_name="${PROPERTYQUARRY_CF_TUNNEL_TOKEN:-}"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${APP_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${APP_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

env_file_value() {
  local key="$1"
  env_file_value_from "${APP_ROOT}/.env" "${key}"
}

env_file_value_from() {
  local file="$1"
  local key="$2"
  local line=""
  if [[ -f "${file}" ]]; then
    line="$(grep -E "^${key}=" "${file}" | tail -n1 || true)"
  fi
  printf '%s' "${line#*=}"
}

effective_value() {
  local key="$1"
  if [[ -n "${!key+x}" ]]; then
    printf '%s' "${!key}"
    return 0
  fi
  env_file_value "${key}"
}

loopback_port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH "( sport = :${port} )" | grep -q .
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  "${PYTHON_BIN}" - "${port}" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
raise SystemExit(0)
PY
}

choose_free_loopback_port() {
  local start="$1"
  local count="$2"
  local port=0
  for ((port = start; port < start + count; port++)); do
    if ! loopback_port_listening "${port}"; then
      printf '%s' "${port}"
      return 0
    fi
  done
  return 1
}

configure_responses_proxy_host_port() {
  if [[ -n "${EA_RESPONSES_PROXY_HOST_PORT:-}" ]]; then
    return 0
  fi

  local configured_port=""
  configured_port="$(env_file_value_from "${APP_ROOT}/.env.local" "EA_RESPONSES_PROXY_HOST_PORT")"
  if [[ -n "${configured_port}" ]]; then
    export EA_RESPONSES_PROXY_HOST_PORT="${configured_port}"
    return 0
  fi

  configured_port="$(env_file_value "EA_RESPONSES_PROXY_HOST_PORT")"
  if [[ -n "${configured_port}" ]]; then
    export EA_RESPONSES_PROXY_HOST_PORT="${configured_port}"
    return 0
  fi

  local default_port="8092"
  if ! loopback_port_listening "${default_port}"; then
    export EA_RESPONSES_PROXY_HOST_PORT="${default_port}"
    return 0
  fi

  local chosen=""
  chosen="$(choose_free_loopback_port 8094 32)" || {
    echo "Could not find a free loopback port for EA_RESPONSES_PROXY_HOST_PORT after 127.0.0.1:${default_port} was already in use." >&2
    exit 1
  }
  export EA_RESPONSES_PROXY_HOST_PORT="${chosen}"
  echo "EA_RESPONSES_PROXY_HOST_PORT auto-selected ${chosen} because 127.0.0.1:${default_port} is already in use."
}

normalize_origin_like() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%/}"
  printf '%s' "${value}"
}

is_placeholder_origin_like() {
  local value
  value="$(normalize_origin_like "$1")"
  [[ -z "${value}" ]] && return 1
  case "${value}" in
    http://localhost|http://localhost:*|https://localhost|https://localhost:*|\
    http://127.0.0.1|http://127.0.0.1:*|https://127.0.0.1|https://127.0.0.1:*|\
    https://example.test|https://*.example.test|http://example.test|http://*.example.test)
      return 0
      ;;
  esac
  [[ "${value}" == *".example.test" ]] && return 0
  return 1
}

is_placeholder_value_like() {
  local value
  value="$(normalize_origin_like "$1")"
  [[ -z "${value}" ]] && return 1
  case "${value}" in
    example|example-*|replace-me|replace_with_*|changeme|change-me|placeholder|todo)
      return 0
      ;;
  esac
  return 1
}

require_non_placeholder_secret() {
  local key="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    cat >&2 <<EOF
Refusing to deploy without ${key}.

Set a real production value in .env before deploy.
EOF
    exit 4
  fi
  if is_placeholder_value_like "${value}"; then
    cat >&2 <<EOF
Refusing to deploy with placeholder ${key}.

Set a real production value in .env before deploy.
EOF
    exit 4
  fi
}

require_valid_prod_auth() {
  local api_token="$1"
  local cf_access_team_domain="$2"
  local cf_access_aud="$3"

  if [[ -n "${api_token}" ]]; then
    require_non_placeholder_secret "EA_API_TOKEN" "${api_token}"
    return 0
  fi

  if [[ -z "${cf_access_team_domain}" || -z "${cf_access_aud}" ]]; then
    cat >&2 <<'EOF'
Refusing to deploy without production auth.

Set one of these before deploy:
  EA_API_TOKEN=<real-token>

or configure Cloudflare Access auth:
  EA_CF_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com
  EA_CF_ACCESS_AUD=<audience>
EOF
    exit 4
  fi

  if is_placeholder_origin_like "https://${cf_access_team_domain}"; then
    cat >&2 <<'EOF'
Refusing to deploy with placeholder EA_CF_ACCESS_TEAM_DOMAIN.

Set a real Cloudflare Access team domain in .env before deploy.
EOF
    exit 4
  fi

  if is_placeholder_value_like "${cf_access_aud}"; then
    cat >&2 <<'EOF'
Refusing to deploy with placeholder EA_CF_ACCESS_AUD.

Set a real Cloudflare Access audience in .env before deploy.
EOF
    exit 4
  fi
}

ensure_runtime_readable_file_projection() {
  local env_name="$1"
  local default_path="${2:-}"
  local access_policy="${3:-runtime_uid}"
  local raw_path
  raw_path="$(effective_value "${env_name}")"
  raw_path="$(normalize_origin_like "${raw_path}")"
  if [[ -z "${raw_path}" ]]; then
    raw_path="${default_path}"
  fi
  [[ -z "${raw_path}" ]] && return 0

  local resolved_path
  if [[ "${raw_path}" = /* ]]; then
    resolved_path="${raw_path}"
  else
    resolved_path="${APP_ROOT}/${raw_path}"
  fi
  [[ -f "${resolved_path}" ]] || return 0

  if [[ "${access_policy}" == "runtime_group_1000" ]]; then
    chgrp 1000 "${resolved_path}"
    chmod 0640 "${resolved_path}"
    local strict_mode
    strict_mode="$(stat -c '%a' "${resolved_path}" 2>/dev/null || true)"
    if [[ "${strict_mode}" != "640" ]]; then
      echo "Unable to secure runtime group-readable secret projection: ${resolved_path}" >&2
      return 1
    fi
    return 0
  fi

  # Bind-mounted secret projections must be readable by the non-root EA runtime
  # UID inside Docker. Prefer a narrow ACL; fall back to read-only world access on
  # hosts where ACL tooling is unavailable.
  if command -v setfacl >/dev/null 2>&1 && setfacl -m u:10001:r "${resolved_path}" >/dev/null 2>&1; then
    chmod go-w "${resolved_path}"
    return 0
  fi
  chmod a+r,go-w "${resolved_path}"
}

ensure_runtime_readable_config_projection() {
  local relative_path="$1"
  case "${relative_path}" in
    config/*) ;;
    *)
      echo "Refusing runtime-readable config projection outside config/: ${relative_path}" >&2
      return 1
      ;;
  esac

  local resolved_path="${APP_ROOT}/${relative_path}"
  if [[ ! -f "${resolved_path}" || -L "${resolved_path}" ]]; then
    echo "Required runtime-readable config projection is missing or unsafe: ${resolved_path}" >&2
    return 1
  fi

  # The release worktree may be created with umask 0077. Grant the runtime UID
  # traverse-only access to config/ and read access to this exact nonsecret file;
  # do not broaden access to sibling credentials in the same directory.
  local config_dir="${APP_ROOT}/config"
  if command -v setfacl >/dev/null 2>&1 \
    && setfacl -m u:10001:--x "${config_dir}" >/dev/null 2>&1 \
    && setfacl -m u:10001:r "${resolved_path}" >/dev/null 2>&1; then
    chmod go-w "${config_dir}" "${resolved_path}"
    return 0
  fi
  chmod a+x,go-w "${config_dir}"
  chmod a+r,go-w "${resolved_path}"
}

ensure_runtime_writable_dir_projection() {
  local env_name="$1"
  local default_path="$2"
  local raw_path
  raw_path="$(effective_value "${env_name}")"
  raw_path="$(normalize_origin_like "${raw_path}")"
  if [[ -z "${raw_path}" ]]; then
    raw_path="${default_path}"
  fi

  local resolved_path
  if [[ "${raw_path}" = /* ]]; then
    resolved_path="${raw_path}"
  else
    resolved_path="${APP_ROOT}/${raw_path}"
  fi
  mkdir -p "${resolved_path}"

  # A previous release may already have projected this directory to the
  # container runtime UID. It is ready as-is when that owner can write and
  # traverse it. Avoid mutations that an unprivileged host operator cannot
  # perform on a directory that is nevertheless correct for the container.
  local existing_owner_uid
  local existing_mode
  local owner_digit
  local owner_permissions=0
  existing_owner_uid="$(stat -c '%u' "${resolved_path}" 2>/dev/null || true)"
  existing_mode="$(stat -c '%a' "${resolved_path}" 2>/dev/null || true)"
  owner_digit="${existing_mode: -3:1}"
  if [[ "${owner_digit}" =~ ^[0-7]$ ]]; then
    owner_permissions=$((10#${owner_digit}))
  fi
  if [[ "${existing_owner_uid}" == "10001" ]] && (( (owner_permissions & 3) == 3 )); then
    return 0
  fi

  # Bind-mounted writable runtime dirs must be writable by the non-root EA
  # runtime UID. Prefer narrow ACL/chown. On ACL-less unprivileged hosts, use a
  # sticky writable directory so Docker does not create an unwritable root-owned
  # bind target at first deploy.
  if command -v setfacl >/dev/null 2>&1 && setfacl -m u:10001:rwx -m d:u:10001:rwx "${resolved_path}" >/dev/null 2>&1; then
    chmod go-w "${resolved_path}"
    return 0
  fi
  if chown 10001:10001 "${resolved_path}" >/dev/null 2>&1; then
    chmod u+rwx,go-rwx "${resolved_path}"
    return 0
  fi
  if chmod 1777 "${resolved_path}" >/dev/null 2>&1; then
    return 0
  fi
  local mode
  mode="$(stat -c '%a' "${resolved_path}" 2>/dev/null || true)"
  if [[ "${mode}" == "1777" ]]; then
    return 0
  fi
  echo "Unable to make runtime bind directory writable for UID 10001: ${resolved_path}" >&2
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      cat <<'EOF'
Usage:
  bash scripts/deploy.sh [--compose-override <file>]...

Options:
  --compose-override <file>  Layer an extra compose override onto the deploy topology.

Environment:
  PROPERTYQUARRY_MEMORY_ONLY=1            Deploy API service using docker-compose.memory.yml override.
  PROPERTYQUARRY_BOOTSTRAP_DB=1           Run db bootstrap after deploy (ignored if PROPERTYQUARRY_MEMORY_ONLY=1).
  PROPERTYQUARRY_ENABLE_FASTESTVPN=1      Layer docker-compose.fastestvpn.yml when FastestVPN *.ovpn profiles are present.
  PROPERTYQUARRY_ENABLE_CLOUDFLARED=1|0   Force Cloudflare tunnel override on or off (default: auto when PROPERTYQUARRY_CF_TUNNEL_TOKEN is set).
  PROPERTYQUARRY_CF_TUNNEL_TOKEN=<token>  PropertyQuarry Cloudflare tunnel token alias.
  PROPERTYQUARRY_RUN_RUNTIME_HARD_EXIT_GATES=1|0  Run runtime hard exit gates after health goes green (default: 1).
  EA_PROACTIVE_OODA_ENABLED=1             Include the lightweight OODA loop in full topology checks.
  TEABLE_API_KEY=...                      Verify and recover EA env/config artifacts from Teable before deploy.
  TEABLE_BASE_URL=https://app.teable.ai   Optional non-default Teable host for recovery.

Runtime isolation preflight:
  python3 scripts/prepare_ea_runtime_env.py
      Materialize owner-only EA env files with all PropertyQuarry keys removed.

Backward-compatible aliases:
  EA_MEMORY_ONLY, EA_BOOTSTRAP_DB, EA_ENABLE_FASTESTVPN, EA_ENABLE_CLOUDFLARED,
  EA_CF_TUNNEL_TOKEN, EA_RUN_RUNTIME_HARD_EXIT_GATES
  EA_RUN_RUNTIME_HARD_EXIT_GATES=1|0     Alias for PROPERTYQUARRY_RUN_RUNTIME_HARD_EXIT_GATES.
EOF
      exit 0
      ;;
    --compose-override)
      if [[ $# -lt 2 ]]; then
        echo "--compose-override requires a compose file path" >&2
        exit 1
      fi
      EXTRA_COMPOSE_OVERRIDES+=("$2")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "${PROPERTYQUARRY_USE_LEGACY_STACK:-0}" != "1" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy the inherited EA mega-stack from the standalone PropertyQuarry repo.

Use the hardened property-only runtime instead:
  docker compose -f docker-compose.property.yml up -d --build

If you intentionally need the legacy assistant topology for migration work, rerun with:
  PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh
EOF
  exit 2
fi

echo "== PropertyQuarry deploy: ${APP_ROOT} (project=${COMPOSE_PROJECT_NAME}) =="

if [[ -n "${TEABLE_API_KEY:-}" ]]; then
  echo "Ensuring EA env/config recovery artifacts from Teable before deploy."
  bash "${APP_ROOT}/scripts/bootstrap_from_teable.sh" --ensure-local >/dev/null
fi

if [[ ! -f "${APP_ROOT}/.env" ]]; then
  cp "${APP_ROOT}/.env.example" "${APP_ROOT}/.env"
  chmod 600 "${APP_ROOT}/.env"
  echo "Created .env from .env.example. Fill values and rerun."
  exit 1
fi

echo "Preparing isolated EA runtime environment files."
"${PYTHON_BIN}" "${APP_ROOT}/scripts/prepare_ea_runtime_env.py" --root "${APP_ROOT}"

echo "Verifying bind-mounted EA application source permissions."
"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_ea_runtime_source_permissions.py" \
  --root "${APP_ROOT}" --repair >/dev/null

if [[ -n "${TEABLE_API_KEY:-}" ]]; then
  proactive_teable_base_id="$(normalize_origin_like "$(effective_value EA_ENV_TEABLE_BASE_ID)")"
  if [[ -n "${proactive_teable_base_id}" ]]; then
    echo "Reconciling proactive OODA Teable projection tables."
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/bootstrap_proactive_ooda_teable_tables.py" --create-missing --write-config >/dev/null
  fi
fi

ensure_runtime_readable_file_projection "ONEMIN_DIRECT_API_KEYS_JSON_FILE"
ensure_runtime_readable_file_projection \
  "EA_RESPONSES_NO_RETENTION_CLIENT_TOKEN_HOST_FILE" \
  "./.ea-runtime-secrets/no_retention_client_token" \
  "runtime_group_1000"
ensure_runtime_readable_config_projection "config/onemin_api_keys.example.json"
ensure_runtime_readable_config_projection "config/tenants.yml"
ensure_runtime_readable_config_projection "config/onemin_slot_owners.json"
ensure_runtime_readable_config_projection "config/places.yml"
"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_whatsapp_callback_secret_runtime_projection.py" \
  --generate-missing >/dev/null
ensure_runtime_writable_dir_projection "EA_RUNTIME_HOST_ROOT" "./.runtime"
ensure_runtime_writable_dir_projection "EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT" "./data/pocket-ai-audio"
pocket_audio_archive_host_root="$(normalize_origin_like "$(effective_value EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT)")"
if [[ -z "${pocket_audio_archive_host_root}" ]]; then
  pocket_audio_archive_host_root="./data/pocket-ai-audio"
fi
export EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT="${pocket_audio_archive_host_root}"

public_origin_line="$(grep -E '^(EA_PUBLIC_APP_BASE_URL|PROPERTYQUARRY_PUBLIC_BASE_URL)=' "${APP_ROOT}/.env" | tail -n1 || true)"
public_origin_source="EA_PUBLIC_APP_BASE_URL"
public_origin_value="$(normalize_origin_like "$(effective_value EA_PUBLIC_APP_BASE_URL)")"
if [[ -z "${public_origin_value}" ]]; then
  public_origin_source="PROPERTYQUARRY_PUBLIC_BASE_URL"
  public_origin_value="$(normalize_origin_like "$(effective_value PROPERTYQUARRY_PUBLIC_BASE_URL)")"
fi
if [[ -z "${public_origin_value}" && -n "${public_origin_line}" ]]; then
  public_origin_source="${public_origin_line%%=*}"
  public_origin_value="$(normalize_origin_like "${public_origin_line#*=}")"
fi
if [[ -z "${public_origin_value}" ]]; then
  public_origin_source="portable_default"
  public_origin_value="$(normalize_origin_like "${EA_PUBLIC_APP_BASE_URL:-https://example.test}")"
fi
if [[ -z "${public_origin_value}" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy without a public runtime origin.

Set one of these in .env before deploy:
  EA_PUBLIC_APP_BASE_URL=https://assistant.example.test
  PROPERTYQUARRY_PUBLIC_BASE_URL=https://property.example.test

Release authority requires the deployed runtime to declare its public origin.
EOF
  exit 4
fi

runtime_mode="$(normalize_origin_like "$(effective_value EA_RUNTIME_MODE)")"
if [[ -z "${runtime_mode}" ]]; then
  runtime_mode="prod"
fi
if [[ "${runtime_mode}" == "prod" ]]; then
  api_token_value="$(normalize_origin_like "$(effective_value EA_API_TOKEN)")"
  cf_access_team_domain="$(normalize_origin_like "$(effective_value EA_CF_ACCESS_TEAM_DOMAIN)")"
  cf_access_aud="$(normalize_origin_like "$(effective_value EA_CF_ACCESS_AUD)")"
  signing_secret_value="$(normalize_origin_like "$(effective_value EA_SIGNING_SECRET)")"
  workspace_issuer="$(normalize_origin_like "$(effective_value EA_WORKSPACE_ACCESS_TOKEN_ISSUER)")"
  workspace_audience="$(normalize_origin_like "$(effective_value EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE)")"
  workspace_key_version="$(normalize_origin_like "$(effective_value EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION)")"
  require_valid_prod_auth "${api_token_value}" "${cf_access_team_domain}" "${cf_access_aud}"
  require_non_placeholder_secret "EA_SIGNING_SECRET" "${signing_secret_value}"
  if is_placeholder_origin_like "${public_origin_value}" || is_placeholder_origin_like "${workspace_issuer}"; then
    cat >&2 <<'EOF'
Refusing to deploy with placeholder workspace access token binding origin/issuer.

Set real production values before deploy:
  EA_PUBLIC_APP_BASE_URL=https://assistant.example.test
  EA_WORKSPACE_ACCESS_TOKEN_ISSUER=https://assistant.example.test

Do not deploy with example.test or localhost token-binding origins.
EOF
    exit 4
  fi
  if [[ -z "${workspace_audience}" || -z "${workspace_key_version}" ]]; then
    cat >&2 <<'EOF'
Refusing to deploy without complete workspace access token binding metadata.

Set these in .env before deploy:
  EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE=workspace-access
  EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION=v1
EOF
    exit 4
  fi
  if is_placeholder_value_like "${workspace_audience}" || is_placeholder_value_like "${workspace_key_version}"; then
    cat >&2 <<'EOF'
Refusing to deploy with placeholder workspace access token binding metadata.

Set real values before deploy:
  EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE=workspace-access
  EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION=v1

Do not deploy with placeholder token audience or key-version values.
EOF
    exit 4
  fi
fi

source_worktree_status=""
if ! source_worktree_status="$(
  PYTHONPATH="${APP_ROOT}/scripts${PYTHONPATH:+:${PYTHONPATH}}" "${PYTHON_BIN}" - "${APP_ROOT}" <<'PY'
import json
import sys
from pathlib import Path

from source_state_head import source_worktree_metadata

metadata = source_worktree_metadata(Path(sys.argv[1]), dirty_path_limit=12)
if not bool(metadata.get("source_worktree_dirty")):
    raise SystemExit(0)
print(
    json.dumps(
        {
            "source_dirty_count": int(metadata.get("source_dirty_count") or 0),
            "source_dirty_files": list(metadata.get("source_dirty_files") or []),
            "source_dirty_omitted_count": int(metadata.get("source_dirty_omitted_count") or 0),
            "source_dirty_status_sha256": str(metadata.get("source_dirty_status_sha256") or ""),
        },
        separators=(",", ":"),
    )
)
raise SystemExit(1)
PY
)"; then
  cat >&2 <<'EOF'
Refusing to deploy from a source-dirty git worktree.

Commit the approved release source on an attached release branch before deploy.
Only paths classified as generated-only by source_state_head are permitted; source changes are never bypassed.

Release authority requires a clean worktree for deployment claims.
EOF
  echo "Source-dirty detail: ${source_worktree_status:-source_state_probe_failed}" >&2
  exit 5
fi

release_branch="$(git -C "${APP_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
release_tracking_branch="$(git -C "${APP_ROOT}" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
if [[ -z "${release_branch}" || "${release_branch}" == "HEAD" || -z "${release_tracking_branch}" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy from a detached or untracked Git worktree.

Use an attached temporary release branch with an upstream, for example:
  git worktree add -b release/manfred-<deployment-id> /tmp/ea-manfred-release HEAD
  git -C /tmp/ea-manfred-release branch --set-upstream-to=origin/main

Release authority requires a real branch and tracking branch bound to the deployed commit.
EOF
  exit 5
fi

deploy_commit_sha="$(git -C "${APP_ROOT}" rev-parse HEAD 2>/dev/null || true)"
if [[ ! "${deploy_commit_sha}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing to deploy without a valid 40-character lowercase Git commit revision." >&2
  exit 5
fi
if [[ -n "${EA_SOURCE_REVISION:-}" && "${EA_SOURCE_REVISION}" != "${deploy_commit_sha}" ]]; then
  cat >&2 <<EOF
Refusing to deploy with conflicting EA_SOURCE_REVISION.

Declared revision: ${EA_SOURCE_REVISION}
Checked-out revision: ${deploy_commit_sha}

The runtime image must be built from and attest the exact checked-out release commit.
EOF
  exit 5
fi
export EA_SOURCE_REVISION="${deploy_commit_sha}"

if [[ -z "${EA_DEPLOYMENT_ID:-${DEPLOYMENT_ID:-${RENDER_GIT_COMMIT:-}}}" ]]; then
  deploy_commit_fragment="${deploy_commit_sha:0:12}"
  EA_DEPLOYMENT_ID="deploy-$(date -u +%Y%m%dT%H%M%SZ)-${deploy_commit_fragment}"
  export EA_DEPLOYMENT_ID
  export EA_DEPLOYMENT_ID_SOURCE="deploy_script_generated"
elif [[ -n "${EA_DEPLOYMENT_ID:-}" ]]; then
  export EA_DEPLOYMENT_ID_SOURCE="${EA_DEPLOYMENT_ID_SOURCE:-ea_deploy_id_env}"
elif [[ -n "${DEPLOYMENT_ID:-}" ]]; then
  export EA_DEPLOYMENT_ID="${DEPLOYMENT_ID}"
  export EA_DEPLOYMENT_ID_SOURCE="${EA_DEPLOYMENT_ID_SOURCE:-deploy_platform}"
elif [[ -n "${RENDER_GIT_COMMIT:-}" ]]; then
  export EA_DEPLOYMENT_ID="${RENDER_GIT_COMMIT}"
  export EA_DEPLOYMENT_ID_SOURCE="${EA_DEPLOYMENT_ID_SOURCE:-render_git_commit}"
fi

database_url_line="$(grep -E '^DATABASE_URL=' "${APP_ROOT}/.env" | tail -n1 || true)"
database_url_value="${database_url_line#DATABASE_URL=}"
if [[ "${database_url_value}" == *"/ea_smoke_runtime" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy with DATABASE_URL pointed at the isolated smoke database.

Fix .env first:
  DATABASE_URL=postgresql://postgres:...@ea-db:5432/ea

The smoke database `ea_smoke_runtime` is only for scripts/smoke_postgres.sh and
must never be used for a real deploy.
EOF
  exit 3
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.prod.yml)
FASTESTVPN_OVERLAY_ENABLED=0
CLOUDFLARED_OVERLAY_ENABLED=0
if [[ "${enable_fastestvpn}" == "1" ]]; then
  if find "${APP_ROOT}/vpn/fastestvpn" -maxdepth 1 -type f -name '*.ovpn' | grep -q .; then
    COMPOSE_ARGS+=(-f docker-compose.fastestvpn.yml)
    FASTESTVPN_OVERLAY_ENABLED=1
  else
    echo "EA_ENABLE_FASTESTVPN=1 but no FastestVPN *.ovpn profiles were found under ${APP_ROOT}/vpn/fastestvpn" >&2
    echo "PROPERTYQUARRY_ENABLE_FASTESTVPN=1 but no FastestVPN *.ovpn profiles were found under ${APP_ROOT}/vpn/fastestvpn" >&2
    exit 1
  fi
fi

for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
  if [[ ! -f "${APP_ROOT}/${override}" && ! -f "${override}" ]]; then
    echo "Compose override not found: ${override}" >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "${override}")
done

sync_enabled_modes_from_overrides() {
  DEPLOY_ENABLED_MODES=()
  add_enabled_mode "${DEPLOY_PRIMARY_MODE}"
  local override
  local base
  for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
    base="$(basename "${override}")"
    case "${base}" in
      docker-compose.memorial.yml) add_enabled_mode "MEMORIAL" ;;
      docker-compose.provider-lab.yml) add_enabled_mode "PROVIDER_LAB" ;;
      docker-compose.property.yml) add_enabled_mode "PROPERTY" ;;
    esac
  done
}

whatsapp_web_session_overlay_enabled=0
for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
  if [[ "$(basename "${override}")" == "docker-compose.whatsapp-web-session.yml" ]]; then
    whatsapp_web_session_overlay_enabled=1
    break
  fi
done

vocallab_worker_overlay_enabled=0
for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
  if [[ "$(basename "${override}")" == "docker-compose.vocallab-worker.yml" ]]; then
    vocallab_worker_overlay_enabled=1
    break
  fi
done

if [[ "${memory_only}" != "1" ]]; then
  should_enable_cloudflared="${enable_cloudflared}"
  cloudflared_override="docker-compose.cloudflared.yml"
  if [[ "${should_enable_cloudflared}" == "1" || ( "${should_enable_cloudflared}" == "auto" && -n "${cf_tunnel_token_name}" ) || ( "${should_enable_cloudflared}" == "auto" && -n "$(grep -E '^(PROPERTYQUARRY_CF_TUNNEL_TOKEN|EA_CF_TUNNEL_TOKEN)=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')" ) ]]; then
    COMPOSE_ARGS+=(-f "${cloudflared_override}")
    CLOUDFLARED_OVERLAY_ENABLED=1
  fi
fi

compose() {
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" "${COMPOSE_ARGS[@]}" "$@"
}

normalize_mode() {
  printf '%s' "${1:-}" | tr '[:lower:]-' '[:upper:]_'
}

add_enabled_mode() {
  local mode
  mode="$(normalize_mode "$1")"
  [[ -n "${mode}" ]] || return 0
  local existing
  for existing in "${DEPLOY_ENABLED_MODES[@]:-}"; do
    if [[ "${existing}" == "${mode}" ]]; then
      return 0
    fi
  done
  DEPLOY_ENABLED_MODES+=("${mode}")
}

sync_enabled_modes_from_overrides

materialize_release_manifest() {
  local enabled_modes_csv=""
  local compose_files_csv=""
  local compose_overrides_csv=""
  if [[ "${#DEPLOY_ENABLED_MODES[@]}" -gt 0 ]]; then
    enabled_modes_csv="$(IFS=,; printf '%s' "${DEPLOY_ENABLED_MODES[*]}")"
  fi
  compose_files_csv="$(printf '%s\n' "${COMPOSE_ARGS[@]}" | awk 'prev == "-f" { print; } { prev = $0 }' | paste -sd, -)"
  if [[ "${#EXTRA_COMPOSE_OVERRIDES[@]}" -gt 0 ]]; then
    compose_overrides_csv="$(IFS=,; printf '%s' "${EXTRA_COMPOSE_OVERRIDES[*]}")"
  fi
  EA_DEPLOY_PRIMARY_MODE="${DEPLOY_PRIMARY_MODE}" \
  EA_DEPLOY_ENABLED_MODES="${enabled_modes_csv}" \
  EA_DEPLOY_COMPOSE_FILES="${compose_files_csv}" \
  EA_DEPLOY_COMPOSE_OVERRIDES="${compose_overrides_csv}" \
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_release_manifest.py" --output "${RELEASE_MANIFEST_PATH}" >/dev/null
}

materialize_release_authority_status() {
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_release_authority_status.py" \
    --output "${RELEASE_AUTHORITY_STATUS_PATH}" \
    --release-manifest "${RELEASE_MANIFEST_PATH}" >/dev/null
}

verify_release_authority_manifest() {
  if ! "${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_authority.py" \
    --release-manifest "${RELEASE_MANIFEST_PATH}" >/dev/null; then
    cat >&2 <<EOF
Refusing to publish a runtime without authoritative release evidence.

The materialized release manifest failed release-authority verification:
  ${RELEASE_MANIFEST_PATH}

Fix the reported release-authority issues and rerun deploy.
EOF
    return 1
  fi
}

write_deploy_context() {
  local enabled_modes_csv=""
  local compose_files_csv=""
  local compose_overrides_csv=""
  local deploy_public_origin="${public_origin_value}"
  local deploy_public_origin_source="${public_origin_source}"
  local deploy_branch=""
  local deploy_tracking_branch=""
  local deploy_commit_sha=""
  deploy_branch="$(git -C "${APP_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  deploy_tracking_branch="$(git -C "${APP_ROOT}" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  deploy_commit_sha="$(git -C "${APP_ROOT}" rev-parse HEAD 2>/dev/null || true)"
  if [[ "${#DEPLOY_ENABLED_MODES[@]}" -gt 0 ]]; then
    enabled_modes_csv="$(IFS=,; printf '%s' "${DEPLOY_ENABLED_MODES[*]}")"
  fi
  compose_files_csv="$(printf '%s\n' "${COMPOSE_ARGS[@]}" | awk 'prev == "-f" { print; } { prev = $0 }' | paste -sd, -)"
  if [[ "${#EXTRA_COMPOSE_OVERRIDES[@]}" -gt 0 ]]; then
    compose_overrides_csv="$(IFS=,; printf '%s' "${EXTRA_COMPOSE_OVERRIDES[*]}")"
  fi
  export DEPLOY_CONTEXT_PATH
  export EA_DEPLOYMENT_ID
  export EA_DEPLOYMENT_ID_SOURCE="${EA_DEPLOYMENT_ID_SOURCE:-}"
  export EA_DEPLOY_PUBLIC_ORIGIN="${deploy_public_origin}"
  export EA_DEPLOY_PUBLIC_ORIGIN_SOURCE="${deploy_public_origin_source}"
  export EA_DEPLOY_BRANCH="${deploy_branch}"
  export EA_DEPLOY_TRACKING_BRANCH="${deploy_tracking_branch}"
  export EA_DEPLOY_COMMIT_SHA="${deploy_commit_sha}"
  export EA_DEPLOY_PRIMARY_MODE="${DEPLOY_PRIMARY_MODE}"
  export EA_DEPLOY_ENABLED_MODES="${enabled_modes_csv}"
  export EA_DEPLOY_COMPOSE_FILES="${compose_files_csv}"
  export EA_DEPLOY_COMPOSE_OVERRIDES="${compose_overrides_csv}"
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_deploy_context.py" --output "${DEPLOY_CONTEXT_PATH}" >/dev/null
}

sync_telegram_webhooks() {
  local env_public_base
  local env_property_public_base
  local webhook_public_base
  local env_bot_registry
  local env_bot_token
  env_public_base="$(grep -E '^EA_PUBLIC_APP_BASE_URL=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  env_property_public_base="$(grep -E '^PROPERTYQUARRY_PUBLIC_BASE_URL=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  webhook_public_base="${env_public_base:-${env_property_public_base}}"
  env_bot_registry="$(grep -E '^EA_TELEGRAM_BOT_REGISTRY_JSON=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  env_bot_token="$(grep -E '^EA_TELEGRAM_BOT_TOKEN=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  if [[ -z "${env_public_base}" && -z "${env_property_public_base}" ]]; then
    return 0
  fi
  if [[ -z "${env_bot_registry}" && -z "${env_bot_token}" ]]; then
    return 0
  fi
  echo "Syncing Telegram webhooks to ${webhook_public_base}"
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/bootstrap_telegram_bot.py" --env-file "${APP_ROOT}/.env" --all-bots --set-webhook >/dev/null
}

build_and_recreate_services() {
  local -a build_services=("$@")
  if [[ "${#build_services[@]}" -eq 0 ]]; then
    return 0
  fi

  compose build "${build_services[@]}"
  compose up -d --no-build ea-db
  local service
  for service in "${build_services[@]}"; do
    compose up -d --no-build --no-deps --force-recreate "${service}"
    if ! wait_for_service_ready "${service}"; then
      echo "Service failed to become ready during deploy: ${service}" >&2
      return 1
    fi
  done
}

recover_docker_build_pressure() {
  local threshold
  local usage_percent

  threshold="${EA_DEPLOY_DOCKER_PRUNE_USAGE_PERCENT:-95}"
  if [[ ! "${threshold}" =~ ^[0-9]+$ ]] || (( threshold < 1 || threshold > 100 )); then
    echo "EA_DEPLOY_DOCKER_PRUNE_USAGE_PERCENT must be an integer from 1 to 100." >&2
    return 1
  fi
  usage_percent="$(df -P "${APP_ROOT}" | awk 'NR == 2 { gsub(/%/, "", $5); print $5 }')"
  if [[ ! "${usage_percent}" =~ ^[0-9]+$ ]]; then
    echo "Unable to determine Docker host filesystem usage." >&2
    return 1
  fi
  if (( usage_percent < threshold )); then
    return 0
  fi

  echo "Host filesystem usage is ${usage_percent}%; pruning dangling images and unused build cache."
  docker image prune --force >/dev/null
  docker builder prune --all --force >/dev/null
}

recreate_services_without_build() {
  local -a recreate_services=("$@")
  if [[ "${#recreate_services[@]}" -eq 0 ]]; then
    return 0
  fi

  local service
  for service in "${recreate_services[@]}"; do
    compose up -d --no-build --no-deps --force-recreate "${service}"
    if ! wait_for_service_ready "${service}"; then
      echo "Service failed to become ready during no-build deploy: ${service}" >&2
      return 1
    fi
  done
}

run_one_shot_initializer() {
  local service="$1"
  compose pull "${service}"
  if ! compose up \
    --no-build \
    --no-deps \
    --force-recreate \
    --abort-on-container-exit \
    --exit-code-from "${service}" \
    "${service}"; then
    echo "One-shot runtime initializer failed during deploy: ${service}" >&2
    return 1
  fi

  local cid
  local exit_code
  cid="$(compose ps -a -q "${service}" || true)"
  [[ -n "${cid}" ]] || {
    echo "One-shot runtime initializer did not create a container: ${service}" >&2
    return 1
  }
  exit_code="$(docker inspect -f '{{.State.ExitCode}}' "${cid}" 2>/dev/null || true)"
  if [[ "${exit_code}" != "0" ]]; then
    echo "One-shot runtime initializer did not exit successfully: ${service}" >&2
    return 1
  fi
}

service_container_ready() {
  local service="$1"
  local cid
  local running
  local restarting
  local health

  cid="$(compose ps -q "${service}" || true)"
  if [[ -z "${cid}" ]]; then
    return 1
  fi

  running="$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || true)"
  restarting="$(docker inspect -f '{{.State.Restarting}}' "${cid}" 2>/dev/null || true)"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${cid}" 2>/dev/null || true)"

  [[ "${running}" == "true" ]] || return 1
  if [[ "${restarting}" == "true" ]]; then
    return 1
  fi
  if [[ -n "${health}" && "${health}" != "healthy" ]]; then
    return 1
  fi
}

wait_for_service_ready() {
  local service="$1"
  local timeout_seconds="${EA_DEPLOY_SERVICE_READY_TIMEOUT_SECONDS:-150}"
  if [[ ! "${timeout_seconds}" =~ ^[0-9]+$ ]] || (( timeout_seconds < 1 || timeout_seconds > 600 )); then
    echo "EA_DEPLOY_SERVICE_READY_TIMEOUT_SECONDS must be an integer from 1 to 600." >&2
    return 1
  fi
  local elapsed
  for ((elapsed = 0; elapsed < timeout_seconds; elapsed++)); do
    if service_container_ready "${service}"; then
      return 0
    fi
    sleep 1
  done
  service_container_ready "${service}"
}

cd "${APP_ROOT}"
if [[ "${memory_only}" == "1" ]]; then
  COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.memory.yml)
  TOPOLOGY_SERVICES=(ea-api)
  FAILURE_LOG_SERVICES=(ea-api)
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" -f docker-compose.yml -f docker-compose.memory.yml up -d --build ea-api
else
  configure_responses_proxy_host_port
  RUNTIME_BUILD_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler)
  RUNTIME_RECREATE_ONLY_SERVICES=(ea-proactive-ooda ea-telegram-teable-sync)
  TOPOLOGY_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-proactive-ooda ea-telegram-teable-sync ea-db)
  FAILURE_LOG_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-proactive-ooda ea-telegram-teable-sync ea-db)
  if [[ "${whatsapp_web_session_overlay_enabled}" == "1" ]]; then
    RUNTIME_BUILD_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)
    TOPOLOGY_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)
    FAILURE_LOG_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)
  fi
  if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
    TOPOLOGY_SERVICES+=(ea-cloudflared)
    FAILURE_LOG_SERVICES+=(ea-cloudflared)
  fi
  if [[ "${FASTESTVPN_OVERLAY_ENABLED}" == "1" ]]; then
    RUNTIME_BUILD_SERVICES=(ea-fastestvpn-proxy-ch "${RUNTIME_BUILD_SERVICES[@]}")
    RUNTIME_RECREATE_ONLY_SERVICES+=(ea-docker-socket-proxy)
    TOPOLOGY_SERVICES+=(ea-fastestvpn-proxy-ch ea-docker-socket-proxy)
    FAILURE_LOG_SERVICES+=(ea-fastestvpn-proxy-ch ea-docker-socket-proxy)
  fi
  if [[ "${vocallab_worker_overlay_enabled}" == "1" ]]; then
    FAILURE_LOG_SERVICES+=(ea-vocallab-secret-init)
    run_one_shot_initializer ea-vocallab-secret-init
  fi
  build_and_recreate_services "${RUNTIME_BUILD_SERVICES[@]}"
  recover_docker_build_pressure
  recreate_services_without_build "${RUNTIME_RECREATE_ONLY_SERVICES[@]}"
  if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
    echo "Refreshing Cloudflare tunnel after API recreate"
    compose up -d --no-build --no-deps --force-recreate ea-cloudflared
    if ! wait_for_service_ready ea-cloudflared; then
      echo "Cloudflare tunnel failed to restart cleanly during deploy" >&2
      exit 1
    fi
  fi
fi

if [[ "${bootstrap_db}" == "1" ]]; then
  if [[ "${memory_only}" == "1" ]]; then
    echo "PROPERTYQUARRY_BOOTSTRAP_DB=1 ignored because PROPERTYQUARRY_MEMORY_ONLY=1"
  else
    echo "PROPERTYQUARRY_BOOTSTRAP_DB=1 -> applying kernel migrations"
    bash "${APP_ROOT}/scripts/db_bootstrap.sh"
  fi
fi

HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"

for _ in $(seq 1 60); do
  topology_ready=1
  for service in "${TOPOLOGY_SERVICES[@]}"; do
    if ! service_container_ready "${service}"; then
      topology_ready=0
      break
    fi
  done

  if [[ "${topology_ready}" == "1" ]] && curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    stable_checks=1
    for _stable in $(seq 1 5); do
      sleep 1
      if ! curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
        stable_checks=0
        break
      fi
    done
    if [[ "${stable_checks}" != "1" ]]; then
      continue
    fi
    sync_telegram_webhooks
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_ea_browser_workflow_proof.py" >/dev/null
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_ea_flagship_release_gate.py" >/dev/null
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_weekly_product_pulse.py" >/dev/null
    if [[ "${run_runtime_hard_exit_gates}" != "0" ]]; then
      bash "${APP_ROOT}/scripts/runtime_hard_exit_gates.sh"
    fi
    write_deploy_context
    materialize_release_manifest
    verify_release_authority_manifest
    materialize_release_authority_status
    verify_mode_args=(--mode "${DEPLOY_PRIMARY_MODE}")
    for enabled_mode in "${DEPLOY_ENABLED_MODES[@]}"; do
      verify_mode_args+=(--enabled-mode "${enabled_mode}")
    done
    for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
      verify_mode_args+=(--compose-override "${override}")
    done
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_runtime_mode.py" "${verify_mode_args[@]}" >/dev/null
    verify_artifact_args=()
    for enabled_mode in "${DEPLOY_ENABLED_MODES[@]}"; do
      verify_artifact_args+=(--enabled-mode "${enabled_mode}")
    done
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_artifact_plane.py" "${verify_artifact_args[@]}" >/dev/null
    if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
      public_smoke_base_url="${public_origin_value:-https://example.test}"
      public_smoke_base_url="${public_smoke_base_url%/}"
      public_smoke_urls="${PROPERTYQUARRY_CLOUDFLARED_PUBLIC_SMOKE_URLS:-${EA_CLOUDFLARED_PUBLIC_SMOKE_URLS:-${public_smoke_base_url}/health}}"
      for public_url in ${public_smoke_urls}; do
        for _public in $(seq 1 60); do
          if curl -fsS --max-time 10 "${public_url}" >/dev/null 2>&1; then
            break
          fi
          sleep 2
        done
        if ! curl -fsS --max-time 10 "${public_url}" >/dev/null 2>&1; then
          echo "Cloudflare public smoke failed: ${public_url}" >&2
          exit 1
        fi
      done
    fi
    echo "PropertyQuarry runtime healthy at http://localhost:${HOST_PORT} with ${TOPOLOGY_SERVICES[*]}"
    echo "Release manifest written to ${RELEASE_MANIFEST_PATH}"
    echo "Release authority status written to ${RELEASE_AUTHORITY_STATUS_PATH}"
    exit 0
  fi
  sleep 1
done

echo "Health check failed; dumping logs"
compose ps || true
compose logs --tail 200 "${FAILURE_LOG_SERVICES[@]}" || true
exit 1
