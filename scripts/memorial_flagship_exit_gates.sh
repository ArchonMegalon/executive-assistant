#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR="${TMPDIR:-/tmp}"
PYTHON_BIN="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
export TMPDIR

usage() {
  cat <<'EOF'
Usage:
  memorial_flagship_exit_gates.sh --real-public --base-url https://memorial.example
  memorial_flagship_exit_gates.sh --provider-free-local --base-url http://127.0.0.1:8090

The default mode is real-public. MEMORIAL_FLAGSHIP_GATE_MODE and
MEMORIAL_FLAGSHIP_BASE_URL may be used instead of the corresponding arguments.
EOF
}

gate_mode="${MEMORIAL_FLAGSHIP_GATE_MODE:-real-public}"
base_url="${MEMORIAL_FLAGSHIP_BASE_URL:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --real-public)
      gate_mode="real-public"
      shift
      ;;
    --provider-free-local)
      gate_mode="provider-free-local"
      shift
      ;;
    --base-url)
      if [[ $# -lt 2 || -z "$2" ]]; then
        echo "memorial_flagship_exit_gates: --base-url requires a value" >&2
        exit 64
      fi
      base_url="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "memorial_flagship_exit_gates: unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

if [[ -z "$base_url" ]]; then
  echo "memorial_flagship_exit_gates: a base URL is required; use --base-url or MEMORIAL_FLAGSHIP_BASE_URL" >&2
  exit 64
fi

"$PYTHON_BIN" - "$gate_mode" "$base_url" <<'PY'
import ipaddress
import socket
import sys
import urllib.parse

RESERVED_PUBLIC_HOST_SUFFIXES = frozenset(
    {
        "alt",
        "arpa",
        "example",
        "example.com",
        "example.net",
        "example.org",
        "home.arpa",
        "internal",
        "invalid",
        "lan",
        "local",
        "localdomain",
        "localhost",
        "onion",
        "test",
    }
)


def dns_host_resolves_globally(hostname):
    try:
        canonical = hostname.encode("idna").decode("ascii").rstrip(".").lower()
    except UnicodeError:
        return False
    if not canonical or "." not in canonical or any(
        canonical == suffix or canonical.endswith(f".{suffix}")
        for suffix in RESERVED_PUBLIC_HOST_SUFFIXES
    ):
        return False
    try:
        records = socket.getaddrinfo(
            canonical,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return False
    addresses = set()
    try:
        for family, _socket_type, _protocol, _canonical_name, sockaddr in records:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            addresses.add(ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0]))
    except (IndexError, TypeError, ValueError):
        return False
    return bool(addresses) and all(address.is_global for address in addresses)


def public_hostname_allowed(hostname):
    if not hostname or "%" in hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        return dns_host_resolves_globally(hostname)

mode, raw_url = sys.argv[1:]
if mode not in {"real-public", "provider-free-local"}:
    raise SystemExit(f"memorial_flagship_exit_gates: invalid gate mode: {mode}")
try:
    parsed = urllib.parse.urlsplit(raw_url)
except ValueError as exc:
    raise SystemExit(f"memorial_flagship_exit_gates: invalid base URL: {exc}") from exc
if (
    parsed.scheme.lower() not in {"http", "https"}
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
    or parsed.path not in {"", "/"}
):
    raise SystemExit("memorial_flagship_exit_gates: base URL must be a credential-free HTTP(S) origin")
host = parsed.hostname.rstrip(".").lower()
if mode == "real-public":
    if parsed.scheme.lower() != "https":
        raise SystemExit("memorial_flagship_exit_gates: real-public mode requires an HTTPS origin")
    if not public_hostname_allowed(host):
        raise SystemExit("memorial_flagship_exit_gates: real-public mode requires a public origin")
else:
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost" or host.endswith(".localhost")
    if not is_loopback:
        raise SystemExit("memorial_flagship_exit_gates: provider-free-local mode requires a loopback origin")
PY

export MEMORIAL_FLAGSHIP_GATE_MODE="$gate_mode"
export MEMORIAL_FLAGSHIP_BASE_URL="${base_url%/}"

if [[ "$gate_mode" == "real-public" ]]; then
  case "${MEMORIAL_DIAGNOSTIC_SKIP_MEANINGFUL_BROWSER_RECEIPT:-}" in
    1|true|TRUE|yes|YES|on|ON)
      echo "memorial_flagship_exit_gates: diagnostic meaningful-browser bypass is forbidden in real-public mode" >&2
      exit 64
      ;;
  esac
fi

cd "$ROOT"
export MEMORIAL_FLAGSHIP_EXIT_GATES_RUNNING=1
PYTHONPATH="$ROOT/ea${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m pytest -q --import-mode=importlib \
  tests/test_memorial_archive_registry_public.py \
  tests/test_memorial_audio_probe_contracts.py \
  tests/test_memorial_demo_rehearsal_contracts.py \
  tests/test_memorial_flagship_preflight.py \
  tests/test_memorial_fliplink_publisher.py \
  tests/test_memorial_family_contributions.py \
  tests/test_memorial_private_context.py \
  tests/test_memorial_recovery_inventory.py \
  tests/test_memorial_recovery_inventory_cli.py \
  tests/test_memorial_share_packet.py \
  ea/tests/test_memorial_narration_work_package.py \
  tests/test_measure_memorial_live_browser.py \
  tests/test_memorial_room_ready_contracts.py \
  tests/test_memorial_security_contracts.py \
  tests/test_validate_memorial_voice_loop.py \
  tests/test_providers_api_contracts.py \
  tests/test_memorial_showtime_contracts.py \
  -k 'memorial'

PYTHONPATH="$ROOT/ea${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m pytest -q --import-mode=importlib \
  ea/tests/test_audiobook_epub_pipeline.py \
  ea/tests/test_audiobook_narration_planner.py

if [[ -n "${PYTEST_CURRENT_TEST:-}" ]]; then
  "$PYTHON_BIN" -m pytest -q \
    tests/e2e/test_memorial_showtime_cli.py
else
  "$PYTHON_BIN" -m pytest -q \
    tests/e2e/test_memorial_browser.py \
    tests/e2e/test_memorial_flagship_exit_gates.py \
    tests/e2e/test_memorial_flagship_operator_tools.py \
    tests/e2e/test_memorial_showtime_cli.py
fi

cd "$ROOT"
preflight_args=("manfred" "--base-url" "$MEMORIAL_FLAGSHIP_BASE_URL")
"$PYTHON_BIN" scripts/memorial_flagship_preflight.py "${preflight_args[@]}"

if [[ "$gate_mode" == "provider-free-local" ]]; then
  echo "PROVIDER_FREE_LOCAL_GATE_PASS: local tests and live privacy preflight passed; no real voice, microphone, provider, or public-launch proof was attempted"
  exit 0
fi

avatar_mode="--avatar-optional"
if [[ "${MEMORIAL_FLAGSHIP_AVATAR_REQUIRED:-0}" == "1" ]]; then
  avatar_mode="--avatar-required"
fi
"$PYTHON_BIN" ea/scripts/memorial_room_ready.py \
  --slug manfred \
  --base-url "$MEMORIAL_FLAGSHIP_BASE_URL" \
  --questions examples/demo_questions.manfred.json \
  --output-dir "$TMPDIR/manfred_room_ready_exit_gate" \
  --launch-mode \
  "$avatar_mode" \
  --skip-exit-gates

"$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

report_path = Path(os.environ["TMPDIR"]) / "manfred_room_ready_exit_gate" / "showtime_report.json"
if not report_path.is_file():
    raise SystemExit(f"missing_showtime_report:{report_path}")
payload = json.loads(report_path.read_text(encoding="utf-8"))
results = payload.get("results") or []
voice_step = next((item for item in results if item.get("name") == "voice_roundtrip_validation"), None)
if not voice_step:
    raise SystemExit("missing_voice_roundtrip_validation_step")
effective = str(voice_step.get("effective_status") or "")
if effective != "pass":
    raise SystemExit(f"voice_roundtrip_validation_not_pass:{effective}")
PY

browser_args=(
  --base-url "$MEMORIAL_FLAGSHIP_BASE_URL"
  --slug manfred
  --output "$TMPDIR/manfred_room_ready_exit_gate/memorial_live_turn_gate.json"
  --exit-gate
  --real-stt
  --gold-mode
  --require-public-origin
)
"$PYTHON_BIN" "$ROOT/scripts/measure_memorial_live_browser.py" "${browser_args[@]}"

gold_readiness_receipt="$TMPDIR/manfred_room_ready_exit_gate/memorial_gold_readiness.json"
MEMORIAL_PUBLIC_BROWSER_RECEIPT="$TMPDIR/manfred_room_ready_exit_gate/memorial_live_turn_gate.json" \
  "$PYTHON_BIN" "$ROOT/scripts/verify_memorial_gold_readiness.py" >"$gold_readiness_receipt"

"$PYTHON_BIN" - "$gold_readiness_receipt" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"memorial_flagship_exit_gates: invalid gold-readiness receipt: {type(exc).__name__}") from exc
if not isinstance(payload, dict) or payload.get("status") != "pass":
    raise SystemExit("memorial_flagship_exit_gates: gold-readiness receipt did not pass")
if payload.get("memorial_voice_gold_claim_allowed") is not True:
    raise SystemExit("memorial_flagship_exit_gates: gold-readiness verifier did not authorize the public claim")
PY
