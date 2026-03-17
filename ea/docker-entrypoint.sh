#!/bin/sh
set -eu

LEDGER_DIR="${EA_RESPONSES_PROVIDER_LEDGER_DIR:-/data/provider-ledger}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "${LEDGER_DIR}"
  chown -R ea:ea "${LEDGER_DIR}"
  exec runuser -u ea -- "$@"
fi

exec "$@"
