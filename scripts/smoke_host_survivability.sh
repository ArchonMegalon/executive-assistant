#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%F_%H%M%S)"
OUT="/tmp/ea-smoke-$STAMP"
mkdir -p "$OUT"

if [[ -z "${EA_HEAVY_JOB_CMD:-}" ]]; then
  echo "Set EA_HEAVY_JOB_CMD to the heavy command to test (example: EA_HEAVY_JOB_CMD='bash scripts/smoke.sh')."
  exit 2
fi

{
  echo "== PRECHECK =="
  date
  uptime
} | tee "$OUT/summary.txt"
free -h | tee "$OUT/free_pre.txt" >/dev/null
df -h | tee "$OUT/df_pre.txt" >/dev/null
df -ih | tee "$OUT/dfi_pre.txt" >/dev/null
ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%mem | head -40 > "$OUT/ps_pre.txt"

(
  for _ in $(seq 1 120); do
    echo "==== $(date) ===="
    uptime
    free -m
    ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%mem | head -20
    sleep 5
  done
) > "$OUT/watchdog.txt" 2>&1 &
WATCHDOG_PID=$!

set +e
if command -v systemd-run >/dev/null 2>&1; then
  systemd-run --scope \
    -p MemoryMax=2G \
    -p CPUQuota=200% \
    -p TasksMax=512 \
    -p OOMPolicy=kill \
    bash -lc "timeout 20m ${EA_HEAVY_JOB_CMD}"
  RC=$?
else
  timeout 20m bash -lc "${EA_HEAVY_JOB_CMD}"
  RC=$?
fi
set -e

kill "$WATCHDOG_PID" || true

free -h > "$OUT/free_post.txt"
df -h > "$OUT/df_post.txt"
ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%mem | head -40 > "$OUT/ps_post.txt"

journalctl -k -b | egrep -i 'out of memory|killed process|oom' > "$OUT/oom_kernel.txt" || true
journalctl -u ssh -b > "$OUT/ssh_journal.txt" || true

echo "EXIT_CODE=$RC" | tee -a "$OUT/summary.txt"
if grep -qiE 'out of memory|killed process|oom' "$OUT/oom_kernel.txt"; then
  echo "FAIL: OOM / kernel kill detected" | tee -a "$OUT/summary.txt"
  exit 1
fi

echo "PASS: No kernel OOM evidence detected" | tee -a "$OUT/summary.txt"
echo "Artifacts: $OUT"
