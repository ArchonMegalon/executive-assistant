#!/bin/sh
set -eu

# Avoid an unbounded restart storm if an image is internally inconsistent.
# Retry the import with capped backoff, then replace this guard with the proxy.
delay_seconds=5
attempt=0
error_log=/tmp/ea-responses-proxy-import.err

while ! python -c 'from app.main import app; assert app is not None' 2>"$error_log"; do
    attempt=$((attempt + 1))
    echo "ea-responses-proxy startup import failed attempt=$attempt retry_in=${delay_seconds}s" >&2
    sed -n '1,80p' "$error_log" >&2 || true
    sleep "$delay_seconds"
    if [ "$delay_seconds" -lt 300 ]; then
        delay_seconds=$((delay_seconds * 2))
        if [ "$delay_seconds" -gt 300 ]; then
            delay_seconds=300
        fi
    fi
done

rm -f "$error_log"
exec python /app/scripts/ea_responses_proxy.py
