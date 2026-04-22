#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${EA_ROOT}/.env"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/resolve_onemin_ai_key.sh [--all]
  bash scripts/resolve_onemin_ai_key.sh --next CURRENT_KEY

Resolution order:
  1. ONEMIN_AI_API_KEY
  2. ONEMIN_AI_API_KEY_FALLBACK_<n> in ascending numeric order
  3. ONEMIN_DIRECT_API_KEYS_JSON / ONEMIN_DIRECT_API_KEYS_JSON_FILE entries

The script loads values from the current shell first and then from .env when present.
Default output is the first non-empty key.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

read_env_value() {
  local key="$1"
  if [[ -n "${!key:-}" ]]; then
    printf '%s\n' "${!key}"
    return 0
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    local line
    line="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n1 || true)"
    if [[ -n "${line}" ]]; then
      printf '%s\n' "${line#*=}"
      return 0
    fi
  fi
  printf '\n'
}

ordered_key_names() {
  printf '%s\n' "ONEMIN_AI_API_KEY"
  {
    compgen -A variable -- "ONEMIN_AI_API_KEY_FALLBACK_" || true
    if [[ -f "${ENV_FILE}" ]]; then
      sed -n 's/^\(ONEMIN_AI_API_KEY_FALLBACK_[0-9][0-9]*\)=.*/\1/p' "${ENV_FILE}"
    fi
  } | awk 'NF { print }' | sort -Vu
}

ordered_keys() {
  ENV_FILE="${ENV_FILE}" python3 - <<'PY'
import json
import os
import re
from pathlib import Path

env_file = Path(os.environ.get("ENV_FILE", ""))

def strip_optional_quotes(value: str) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned

dotenv_values: dict[str, str] = {}
if env_file.exists():
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        dotenv_values[key] = strip_optional_quotes(value)

def env_value(name: str) -> str:
    value = str(os.environ.get(name) or dotenv_values.get(name) or "").strip()
    return strip_optional_quotes(value)

fallback_re = re.compile(r"^ONEMIN_AI_API_KEY_FALLBACK_(\d+)$")

def manifest_payload():
    inline = env_value("ONEMIN_DIRECT_API_KEYS_JSON")
    if inline:
        try:
            return json.loads(inline)
        except Exception:
            return None
    raw_path = env_value("ONEMIN_DIRECT_API_KEYS_JSON_FILE")
    if not raw_path:
        return None
    try:
        configured = Path(raw_path)
    except Exception:
        return None
    candidates: list[Path] = []
    if configured.is_absolute():
        candidates.append(configured)
        if str(configured).startswith("/config/"):
            candidates.append(env_file.parent / "config" / configured.name)
    else:
        candidates.extend([env_file.parent / configured, configured])
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = candidate.resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        if not normalized.exists():
            continue
        try:
            return json.loads(normalized.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def manifest_entries():
    payload = manifest_payload()
    if isinstance(payload, dict):
        if isinstance(payload.get("slots"), list):
            items = payload.get("slots") or []
        elif isinstance(payload.get("keys"), list):
            items = payload.get("keys") or []
        elif isinstance(payload.get("accounts"), list):
            items = payload.get("accounts") or []
        else:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    fallback_numbers = {
        int(match.group(1))
        for name in list(os.environ) + list(dotenv_values)
        for match in [fallback_re.match(str(name or "").strip())]
        if match is not None
    }
    next_fallback = max(fallback_numbers, default=0) + 1
    rows: list[tuple[str, str]] = []
    for item in items:
        slot = ""
        account_name = ""
        key = ""
        if isinstance(item, str):
            key = str(item or "").strip()
        elif isinstance(item, dict):
            key = str(
                item.get("key")
                or item.get("secret")
                or item.get("api_key")
                or item.get("value")
                or item.get("token")
                or ""
            ).strip()
            slot = str(item.get("slot") or item.get("slot_name") or "").strip()
            account_name = str(item.get("account_name") or item.get("name") or "").strip()
        if not key:
            continue
        normalized = account_name
        lowered_slot = str(slot or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized:
            if lowered_slot == "primary":
                normalized = "ONEMIN_AI_API_KEY"
            else:
                match = re.fullmatch(r"fallback_?(\d+)", lowered_slot)
                if match is not None:
                    normalized = f"ONEMIN_AI_API_KEY_FALLBACK_{int(match.group(1))}"
                else:
                    normalized = f"ONEMIN_AI_API_KEY_FALLBACK_{next_fallback}"
                    next_fallback += 1
        rows.append((normalized, key))
    return rows

names: list[str] = []
seen_names: set[str] = set()
names.append("ONEMIN_AI_API_KEY")
seen_names.add("ONEMIN_AI_API_KEY")
fallback_numbers: set[int] = set()
for name in list(os.environ) + list(dotenv_values):
    match = fallback_re.match(str(name or "").strip())
    if match is None:
        continue
    try:
        fallback_numbers.add(int(match.group(1)))
    except Exception:
        continue
manifest_by_slot: dict[int, str] = {}
trailing_names: list[str] = []
for account_name, _key in manifest_entries():
    if account_name == "ONEMIN_AI_API_KEY":
        continue
    match = fallback_re.match(account_name)
    if match is not None:
        number = int(match.group(1))
        fallback_numbers.add(number)
        manifest_by_slot[number] = account_name
    else:
        trailing_names.append(account_name)
for number in sorted(fallback_numbers):
    candidate = manifest_by_slot.get(number) or f"ONEMIN_AI_API_KEY_FALLBACK_{number}"
    if candidate not in seen_names:
        names.append(candidate)
        seen_names.add(candidate)
for candidate in trailing_names:
    if candidate not in seen_names:
        names.append(candidate)
        seen_names.add(candidate)

seen_keys: set[str] = set()
manifest_keys = dict(manifest_entries())
for name in names:
    value = env_value(name) or str(manifest_keys.get(name) or "").strip()
    if not value or value in seen_keys:
        continue
    seen_keys.add(value)
    print(value)
PY
}

if [[ "${1:-}" == "--all" ]]; then
  ordered_keys
  exit 0
fi

if [[ "${1:-}" == "--next" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "missing current key for --next" >&2
    exit 2
  fi
  current="${2}"
  found_current=0
  while IFS= read -r candidate; do
    if [[ "${found_current}" -eq 1 ]]; then
      printf '%s\n' "${candidate}"
      exit 0
    fi
    if [[ "${candidate}" == "${current}" ]]; then
      found_current=1
    fi
  done < <(ordered_keys)
  exit 1
fi

first_key="$(ordered_keys | head -n1 || true)"
if [[ -z "${first_key}" ]]; then
  echo "no 1min.ai key configured" >&2
  exit 1
fi
printf '%s\n' "${first_key}"
