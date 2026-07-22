#!/usr/bin/env bash
set -euo pipefail
umask 077

STATE="${NET_WATCHDOG_STATE:-/run/net-watchdog.failcount}"
FAIL=0
[[ -f "$STATE" ]] && FAIL="$(cat "$STATE" 2>/dev/null || echo 0)"
case "${FAIL}" in
  ''|*[!0-9]*) FAIL=0 ;;
esac

ok=0
reason="none"

# ICMP is useful when available, but it is not a prerequisite: many healthy
# networks filter it.
for ip in 1.1.1.1 8.8.8.8; do
  if timeout 4 ping -c1 -W2 "$ip" >/dev/null 2>&1; then
    ok=1
    reason="icmp:${ip}"
    break
  fi
done

# Independently accept successful HTTP egress. One provider outage must not be
# allowed to classify the entire host as offline.
if [[ "$ok" -eq 0 ]]; then
  for url in \
    http://1.1.1.1/cdn-cgi/trace \
    http://connectivitycheck.gstatic.com/generate_204 \
    http://www.msftconnecttest.com/connecttest.txt; do
    if timeout 8 curl -fsS --connect-timeout 4 --max-time 7 "$url" >/dev/null 2>&1; then
      ok=1
      reason="http:${url}"
      break
    fi
  done
fi

# Last-resort raw TCP probes avoid DNS, HTTP and certificate dependencies.
if [[ "$ok" -eq 0 ]]; then
  for endpoint in 1.1.1.1:443 8.8.8.8:53 9.9.9.9:53; do
    host="${endpoint%:*}"
    port="${endpoint##*:}"
    if timeout 5 bash -c 'exec 3<>"/dev/tcp/$1/$2"' _ "$host" "$port" >/dev/null 2>&1; then
      ok=1
      reason="tcp:${endpoint}"
      break
    fi
  done
fi

if [[ "$ok" -eq 1 ]]; then
  printf '0\n' > "$STATE"
  exit 0
fi

FAIL=$((FAIL+1))
printf '%s\n' "$FAIL" > "$STATE"
logger -t net-watchdog "connectivity FAIL count=$FAIL"

# Fail closed: this observer must never restart the network stack or force a
# reboot. Those actions can destroy reachable sessions and make a transient
# probe failure self-fulfilling. Emit escalating receipts for an operator or a
# separately governed recovery service instead.
if [[ "$FAIL" -eq 5 ]]; then
  logger -p daemon.warning -t net-watchdog "connectivity unavailable for about 5 checks; observation only, no automatic recovery"
elif [[ "$FAIL" -ge 15 ]] && (( FAIL % 15 == 0 )); then
  logger -p daemon.err -t net-watchdog "connectivity still unavailable count=$FAIL; operator action required, automatic reboot disabled"
fi
