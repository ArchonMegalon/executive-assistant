#!/usr/bin/env bash
set -euo pipefail

# Codex stores authentication-adjacent metadata, prompts, transcripts, and
# local runtime databases below CODEX_HOME. Do not inherit a collaborative
# umask that makes new state group/world readable.
umask 077

real_codex="${HOST_REAL_CODEX:-/usr/bin/codex}"
lowprio="${HOST_LOWPRIO:-/home/tibor/.local/bin/host-lowprio}"
codex_home="${CODEX_HOME:-${HOME}/.codex}"
log_maintainer="${CODEX_LOG_MAINTAINER:-/home/tibor/.local/libexec/codex-log-maintenance}"
startup_wait_seconds="${CODEX_STARTUP_GUARD_WAIT_SECONDS:-300}"
startup_stagger_seconds="${CODEX_STARTUP_STAGGER_SECONDS:-1}"
log_maintenance_threshold_bytes="${CODEX_LOG_MAINTENANCE_THRESHOLD_BYTES:-268435456}"
log_maintenance_retain_rows="${CODEX_LOG_MAINTENANCE_RETAIN_ROWS:-50000}"
log_maintenance_max_wait_seconds="${CODEX_LOG_MAINTENANCE_MAX_WAIT_SECONDS:-86400}"

normalize_seconds() {
  local value="$1"
  local fallback="$2"

  case "$value" in
    ''|*[!0-9]*) printf '%s' "$fallback" ;;
    *) printf '%s' "$value" ;;
  esac
}

startup_wait_seconds="$(normalize_seconds "$startup_wait_seconds" 300)"
startup_stagger_seconds="$(normalize_seconds "$startup_stagger_seconds" 1)"
log_maintenance_threshold_bytes="$(normalize_seconds "$log_maintenance_threshold_bytes" 268435456)"
log_maintenance_retain_rows="$(normalize_seconds "$log_maintenance_retain_rows" 50000)"
log_maintenance_max_wait_seconds="$(normalize_seconds "$log_maintenance_max_wait_seconds" 86400)"

deduplicate_path() {
  local source_path="${PATH:-}"
  local normalized=""
  local entry=""
  local old_ifs="$IFS"

  IFS=:
  for entry in $source_path; do
    [ -n "$entry" ] || continue
    case ":${normalized}:" in
      *":${entry}:"*) ;;
      *) normalized="${normalized:+${normalized}:}${entry}" ;;
    esac
  done
  IFS="$old_ifs"
  export PATH="$normalized"
  return 0
}

schedule_log_maintenance() {
  local database="${codex_home}/logs_2.sqlite"
  local database_size=""
  local -a command=()

  [ "${CODEX_LOG_MAINTENANCE_DISABLE:-0}" != "1" ] || return 0
  [ -x "$log_maintainer" ] || return 0
  [ -f "$database" ] || return 0
  database_size="$(stat -c %s "$database" 2>/dev/null || printf '0')"
  [ "$database_size" -ge "$log_maintenance_threshold_bytes" ] || return 0

  command=(
    "$log_maintainer"
    --codex-home "$codex_home"
    --max-bytes "$log_maintenance_threshold_bytes"
    --retain-rows "$log_maintenance_retain_rows"
    --max-wait-seconds "$log_maintenance_max_wait_seconds"
  )
  if command -v ionice >/dev/null 2>&1; then
    command=(ionice -c 3 "${command[@]}")
  fi
  if [ "${CODEX_LOG_MAINTENANCE_NO_SYSTEMD:-0}" != "1" ] \
    && command -v systemd-run >/dev/null 2>&1 \
    && systemd-run --user --unit=codex-log-maintenance --collect -q \
      -p Nice=19 -p IOSchedulingClass=idle "${command[@]}" >/dev/null 2>&1; then
    return 0
  fi
  nohup nice -n 19 "${command[@]}" >/dev/null 2>&1 </dev/null &
  return 0
}

needs_runtime_startup_guard() {
  case "${1:-}" in
    -h|--help|-V|--version|help|completion)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

acquire_runtime_startup_guard() {
  command -v flock >/dev/null 2>&1 || return

  mkdir -p "$codex_home"
  exec 8>"${codex_home}/.startup.lock"

  if ! flock -n 8; then
    printf 'Codex startup: another Codex launcher is initializing; waiting up to %ss...\n' \
      "$startup_wait_seconds" >&2
    if ! flock -w "$startup_wait_seconds" 8; then
      printf 'Codex startup: initialization gate timed out; no process was terminated.\n' >&2
      return 75
    fi
  fi

  # Stagger simultaneous launches without waiting for healthy long-lived WAL
  # writers to disappear. SQLite WAL mode supports concurrent Codex sessions;
  # treating any writer as a blocker makes every second launcher time out.
  if [ "$startup_stagger_seconds" -gt 0 ]; then
    sleep "$startup_stagger_seconds"
  fi
  flock -u 8
  exec 8>&-
}

resume_thread_id() {
  local -a args=("$@")
  local i=0
  local in_resume=0
  local candidate=""

  while [ "$i" -lt "${#args[@]}" ]; do
    candidate="${args[$i]}"
    if [ "$in_resume" -eq 0 ]; then
      case "$candidate" in
        resume)
          in_resume=1
          i=$((i + 1))
          continue
          ;;
        -c|--config|--enable|--disable|-i|--image|-m|--model|--local-provider|-p|--profile|-s|--sandbox|-a|--ask-for-approval|-C|--cd|--add-dir)
          i=$((i + 2))
          continue
          ;;
        --oss|--full-auto|--dangerously-bypass-approvals-and-sandbox|--search|--no-alt-screen|--strict-config)
          i=$((i + 1))
          continue
          ;;
        *)
          return 1
          ;;
      esac
    fi

    case "$candidate" in
      --last)
        printf '%s' "last"
        return 0
        ;;
      -c|--config|--enable|--disable|-i|--image|-m|--model|--local-provider|-p|--profile|-s|--sandbox|-a|--ask-for-approval|-C|--cd|--add-dir|--remote|--remote-auth-token-env)
        i=$((i + 2))
        continue
        ;;
      --all|--include-non-interactive|--oss|--dangerously-bypass-approvals-and-sandbox|--dangerously-bypass-hook-trust|--search|--no-alt-screen|--strict-config)
        i=$((i + 1))
        continue
        ;;
      --)
        i=$((i + 1))
        continue
        ;;
      -*)
        i=$((i + 1))
        continue
        ;;
    esac

    if [[ "$candidate" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
      printf '%s' "${candidate,,}"
    else
      candidate="${candidate//[^a-zA-Z0-9_.-]/_}"
      printf 'name-%s' "${candidate:0:96}"
    fi
    return 0
  done

  if [ "$in_resume" -eq 1 ]; then
    printf '%s' "picker"
    return 0
  fi
  return 1
}

active_resume_pids() {
  local resume_id="$1"
  ps -u "$(id -u)" -o pid=,comm=,args= 2>/dev/null | awk -v id="$resume_id" '
    $2 == "codex" && index(" " $0 " ", " resume " id " ") {
      print $1
    }
  '
}

exec_codex() {
  local resume_id=""
  local resume_lock=""
  local active_pids=""
  local -a command=()

  if [ "${HOST_LOWPRIO_DISABLE:-0}" != "1" ]; then
    export HOST_LOWPRIO_NICE="${HOST_LOWPRIO_NICE:-5}"
    export HOST_LOWPRIO_IONICE_CLASS="${HOST_LOWPRIO_IONICE_CLASS:-2}"
    export HOST_LOWPRIO_CPU_WEIGHT="${HOST_LOWPRIO_CPU_WEIGHT:-100}"
    export HOST_LOWPRIO_IO_WEIGHT="${HOST_LOWPRIO_IO_WEIGHT:-100}"
    export HOST_LOWPRIO_CPU_QUOTA="${HOST_LOWPRIO_CPU_QUOTA:-200%}"
    command=("$lowprio" "$real_codex" "$@")
  else
    command=("$real_codex" "$@")
  fi

  if command -v flock >/dev/null 2>&1 && resume_id="$(resume_thread_id "$@")"; then
    active_pids=""
    if [[ "$resume_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
      active_pids="$(active_resume_pids "$resume_id")"
    fi
    if [ -n "$active_pids" ]; then
      printf 'Codex resume refused: thread %s is already active (pid%s %s). Use a different thread or exit the existing session.\n' \
        "$resume_id" "$([ "$(wc -w <<<"$active_pids")" -eq 1 ] || printf 's')" "$(tr '\n' ',' <<<"$active_pids" | sed 's/,$//')" >&2
      return 75
    fi

    mkdir -p "${codex_home}/resume-locks"
    resume_lock="${codex_home}/resume-locks/${resume_id}.lock"
    if ! flock -n "$resume_lock" true; then
      printf 'Codex resume refused: thread %s is already active. Use a different thread or exit the existing session.\n' \
        "$resume_id" >&2
      return 75
    fi
    exec flock -n -E 75 "$resume_lock" "${command[@]}"
  fi

  exec "${command[@]}"
}

deduplicate_path
runtime_startup=0
if needs_runtime_startup_guard "${1:-}"; then
  runtime_startup=1
  if [ "${CODEX_STARTUP_GUARD_DISABLE:-0}" != "1" ]; then
    acquire_runtime_startup_guard
  fi
fi
if [ "$runtime_startup" -eq 1 ]; then
  schedule_log_maintenance
fi
exec_codex "$@"
