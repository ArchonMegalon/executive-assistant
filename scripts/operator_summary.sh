#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

echo "== Operator Summary =="
echo

echo "-- version --"
bash scripts/version_info.sh
echo

echo "-- key commands --"
echo "deploy:            make deploy"
echo "deploy (memory):   make deploy-memory"
echo "deploy + bootstrap: EA_BOOTSTRAP_DB=1 make deploy"
echo "bootstrap only:    make bootstrap"
echo "db status:         make db-status"
echo "db size:           make db-size"
echo "db retention:      make db-retention"
echo "smoke api:         make smoke-api"
echo "endpoints:         make endpoints"
echo "openapi export:    make openapi-export"
echo "openapi diff:      make openapi-diff"
echo "openapi prune:     make openapi-prune"
echo

echo "-- docs --"
echo "runbook:           RUNBOOK.md"
echo "architecture:      ARCHITECTURE_MAP.md"
echo "http examples:     HTTP_EXAMPLES.http"
echo "changelog:         CHANGELOG.md"
echo "env matrix:        ENVIRONMENT_MATRIX.md"
echo "release checklist: RELEASE_CHECKLIST.md"
echo

echo "-- queued task --"
awk '/^## Queue/{flag=1;next}/^## In Progress/{flag=0}flag' TASKS_WORK_LOG.md | sed -n '1,8p'
