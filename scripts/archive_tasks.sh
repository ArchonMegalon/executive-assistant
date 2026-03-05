#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${EA_ROOT}/TASKS_WORK_LOG.md"
ARCHIVE_FILE="${EA_ROOT}/TASKS_ARCHIVE.md"
PRUNE_DONE=0
DRY_RUN=0

for arg in "$@"; do
  case "${arg}" in
    --prune-done)
      PRUNE_DONE=1
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    *)
      echo "unknown argument: ${arg}" >&2
      echo "usage: scripts/archive_tasks.sh [--dry-run] [--prune-done]" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "${LOG_FILE}" ]]; then
  echo "missing ${LOG_FILE}" >&2
  exit 1
fi

python3 - "${LOG_FILE}" "${ARCHIVE_FILE}" "${PRUNE_DONE}" "${DRY_RUN}" <<'PY'
import datetime as dt
import pathlib
import sys

log_path = pathlib.Path(sys.argv[1])
archive_path = pathlib.Path(sys.argv[2])
prune_done = sys.argv[3] == "--prune-done"
dry_run = sys.argv[4] == "1"

text = log_path.read_text()
lines = text.splitlines()

start = None
end = None
for i, line in enumerate(lines):
    if line.strip() == "## Done":
        start = i
        continue
    if start is not None and i > start and line.startswith("## "):
        end = i
        break

if start is None:
    print("no Done section found", file=sys.stderr)
    sys.exit(1)
if end is None:
    end = len(lines)

done_block = lines[start:end]
rows = []
for line in done_block:
    s = line.strip()
    if not s.startswith("|"):
        continue
    if "---" in s:
        continue
    if "| ID | Priority | Task | Owner | Status | Notes |" in s:
        continue
    if "| - | - | - | - | - | - |" in s:
        continue
    rows.append(line)

if not rows:
    print("no done rows to archive")
    sys.exit(0)

stamp = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
header = f"\n## Archived {stamp}\n\n| ID | Priority | Task | Owner | Status | Notes |\n|---|---|---|---|---|---|\n"
body = "\n".join(rows) + "\n"

if dry_run:
    print("dry-run rows:")
    for r in rows:
        print(r)
    print(f"would archive {len(rows)} rows to {archive_path}")
    if prune_done:
        print("would prune Done section rows from work log")
    sys.exit(0)

if not archive_path.exists():
    archive_path.write_text("# Tasks Archive\n")

with archive_path.open("a") as f:
    f.write(header)
    f.write(body)

if prune_done:
    rebuilt = []
    rebuilt.extend(lines[: start + 1])
    rebuilt.append("")
    rebuilt.append("| ID | Priority | Task | Owner | Status | Notes |")
    rebuilt.append("|---|---|---|---|---|---|")
    rebuilt.append("| - | - | - | - | - | - |")
    rebuilt.extend(lines[end:])
    log_path.write_text("\n".join(rebuilt) + "\n")

print(f"archived {len(rows)} rows to {archive_path}")
if prune_done:
    print("pruned Done section rows from work log")
PY
