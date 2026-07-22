#!/usr/bin/env bash
set -euo pipefail

umask 077

source_root="${EA_AUDIOBOOK_BACKUP_SOURCE:-/docker/EA/data/audiobooks/jobs}"
remote_root="${EA_AUDIOBOOK_BACKUP_REMOTE:-pcloud:EA/audiobook_jobs}"
versions_root="${EA_AUDIOBOOK_BACKUP_VERSIONS_REMOTE:-pcloud:EA/audiobook_jobs_versions}"
rclone_config="${EA_AUDIOBOOK_BACKUP_RCLONE_CONFIG:-/etc/rclone/pcloud.conf}"
state_root="${EA_AUDIOBOOK_BACKUP_STATE_ROOT:-/docker/EA/data/audiobooks/backup-state}"
sentinel="${source_root}/.ea-audiobook-jobs-root"

if [[ ! -d "${source_root}" ]]; then
  echo "audiobook backup refused: source root missing" >&2
  exit 2
fi
if [[ ! -f "${sentinel}" ]]; then
  echo "audiobook backup refused: source sentinel missing" >&2
  exit 2
fi
if [[ ! -r "${rclone_config}" ]]; then
  echo "audiobook backup refused: rclone config unreadable" >&2
  exit 2
fi

filesystem_type="$(findmnt -T "${source_root}" -n -o FSTYPE)"
case "${filesystem_type}" in
  fuse*|*rclone*)
    echo "audiobook backup refused: active source is FUSE-backed" >&2
    exit 2
    ;;
esac

source_mode="$(stat -c '%a' "${source_root}")"
if (( (8#${source_mode} & 8#077) != 0 )); then
  echo "audiobook backup refused: source root is not private" >&2
  exit 2
fi

mkdir -p "${state_root}/cache"
chmod 700 "${state_root}" "${state_root}/cache"

source_job_count="$(find "${source_root}" -mindepth 2 -maxdepth 2 -type f -name job.json -print | wc -l)"
remote_preflight="$(rclone size "${remote_root}" --config "${rclone_config}" --json 2>/dev/null || true)"
if [[ -z "${remote_preflight}" ]]; then
  remote_preflight='{}'
fi
remote_preflight_count="$(jq -r '.count // 0' <<<"${remote_preflight}")"
if (( remote_preflight_count > 1 && source_job_count == 0 )); then
  echo "audiobook backup refused: active source lost all job manifests" >&2
  exit 2
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${versions_root}/${timestamp}"

rclone sync \
  "${source_root}" \
  "${remote_root}" \
  --config "${rclone_config}" \
  --cache-dir "${state_root}/cache" \
  --backup-dir "${backup_dir}" \
  --max-delete 2000 \
  --checkers 4 \
  --transfers 2 \
  --contimeout 10s \
  --timeout 2m \
  --retries 5 \
  --low-level-retries 10 \
  --log-level NOTICE

source_size="$(rclone size "${source_root}" --config "${rclone_config}" --json)"
remote_size="$(rclone size "${remote_root}" --config "${rclone_config}" --json)"
source_count="$(jq -r '.count' <<<"${source_size}")"
source_bytes="$(jq -r '.bytes' <<<"${source_size}")"
remote_count="$(jq -r '.count' <<<"${remote_size}")"
remote_bytes="$(jq -r '.bytes' <<<"${remote_size}")"

if [[ "${source_count}" != "${remote_count}" || "${source_bytes}" != "${remote_bytes}" ]]; then
  echo "audiobook backup verification failed: source and remote size differ" >&2
  exit 3
fi

receipt_tmp="${state_root}/latest.json.tmp"
jq -n \
  --arg status "verified" \
  --arg observed_at "${timestamp}" \
  --arg filesystem_type "${filesystem_type}" \
  --argjson count "${source_count}" \
  --argjson bytes "${source_bytes}" \
  '{status:$status,observed_at:$observed_at,active_filesystem:$filesystem_type,count:$count,bytes:$bytes,remote_verified:true}' \
  >"${receipt_tmp}"
chmod 600 "${receipt_tmp}"
mv -f "${receipt_tmp}" "${state_root}/latest.json"

# Versioned replaced/deleted objects are retained for 30 days. A failed prune
# does not invalidate the verified current backup.
rclone mkdir "${versions_root}" --config "${rclone_config}"
rclone delete "${versions_root}" \
  --config "${rclone_config}" \
  --min-age 30d \
  --log-level ERROR || true
