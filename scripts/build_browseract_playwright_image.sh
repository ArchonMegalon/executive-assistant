#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${EA_UI_PLAYWRIGHT_IMAGE:-chummer-playwright:local}"

docker build \
  -t "${IMAGE_NAME}" \
  -f "${ROOT}/docker/playwright/Dockerfile" \
  "${ROOT}/docker/playwright"
