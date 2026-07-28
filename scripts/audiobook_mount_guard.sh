#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

host_path="${EA_AUDIOBOOK_MOUNT_GUARD_HOST_PATH:-/mnt/pcloud/media/Audiobooks}"
jobs_host_path="${EA_AUDIOBOOK_MOUNT_GUARD_JOBS_HOST_PATH:-/docker/EA/data/audiobooks/jobs}"
jobs_container_path="${EA_AUDIOBOOK_MOUNT_GUARD_JOBS_CONTAINER_PATH:-/data/audiobooks/jobs}"
jobs_incoming_path="${jobs_container_path}/_incoming"
jobs_marker_path="${jobs_container_path}/.ea-audiobook-jobs-root"
jobs_expected_fstype="${EA_AUDIOBOOK_MOUNT_GUARD_JOBS_FSTYPE:-ext4}"
jobs_marker_sha256="${EA_AUDIOBOOK_MOUNT_GUARD_JOBS_MARKER_SHA256:-1999ca026a56fb3e8ed57416e553b7c9cfa85fdb5c03ba0070c16ac865c899c2}"
state_root="${EA_AUDIOBOOK_MOUNT_GUARD_STATE_ROOT:-/docker/EA/data/audiobook-mount-guard}"
required_samples="${EA_AUDIOBOOK_MOUNT_GUARD_REQUIRED_SAMPLES:-2}"
cooldown_seconds="${EA_AUDIOBOOK_MOUNT_GUARD_COOLDOWN_SECONDS:-1800}"

if [[ ! "${required_samples}" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "${cooldown_seconds}" =~ ^[0-9]+$ ]] ||
   [[ ! "${jobs_expected_fstype}" =~ ^[a-zA-Z0-9._+-]+$ ]] ||
   [[ ! "${jobs_marker_sha256}" =~ ^[0-9a-f]{64}$ ]] ||
   [[ "${jobs_host_path}" != /* ]] ||
   [[ "${jobs_container_path}" != /* ]]; then
  printf 'invalid mount-guard sample or cooldown configuration\n' >&2
  exit 2
fi

mkdir -p "${state_root}"
chmod 700 "${state_root}"
exec 9>"${state_root}/guard.lock"
flock -n 9 || exit 0

state_file="${state_root}/state.json"
receipt_file="${state_root}/latest.json"
now_epoch="$(date +%s)"
observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
previous_count=0
previous_fingerprint=""
last_action_epoch=0
last_action_fingerprint=""
if [[ -s "${state_file}" ]]; then
  previous_count="$(jq -r '.consecutive_mismatches // 0' "${state_file}" 2>/dev/null || echo 0)"
  previous_fingerprint="$(jq -r '.fingerprint // ""' "${state_file}" 2>/dev/null || true)"
  last_action_epoch="$(jq -r '.last_action_epoch // 0' "${state_file}" 2>/dev/null || echo 0)"
  last_action_fingerprint="$(jq -r '.last_action_fingerprint // ""' "${state_file}" 2>/dev/null || true)"
fi
[[ "${previous_count}" =~ ^[0-9]+$ ]] || previous_count=0
[[ "${last_action_epoch}" =~ ^[0-9]+$ ]] || last_action_epoch=0

current_count=0
current_fingerprint=""
mismatch_csv=""
mismatch_detail_csv=""
unknown_csv=""
skipped_csv=""
action_details=""
result_reason=""
action_started=0
host_jobs_id=""
reference_incoming_id=""
recovery_tags=()
recovery_override_files=()

cleanup_recovery_material() {
  local value
  for value in "${recovery_override_files[@]}"; do
    rm -f -- "${value}" || true
  done
  for value in "${recovery_tags[@]}"; do
    timeout 8 docker image rm "${value}" >/dev/null 2>&1 || true
  done
  return 0
}

write_result() {
  local status="$1"
  local state_tmp="${state_file}.tmp"
  local receipt_tmp="${receipt_file}.tmp"
  jq -n \
    --argjson consecutive_mismatches "${current_count}" \
    --arg fingerprint "${current_fingerprint}" \
    --argjson last_action_epoch "${last_action_epoch}" \
    --arg last_action_fingerprint "${last_action_fingerprint}" \
    --arg updated_at "${observed_at}" \
    '{consecutive_mismatches:$consecutive_mismatches,fingerprint:$fingerprint,last_action_epoch:$last_action_epoch,last_action_fingerprint:$last_action_fingerprint,updated_at:$updated_at}' \
    >"${state_tmp}"
  jq -n \
    --arg status "${status}" \
    --arg observed_at "${observed_at}" \
    --arg host_path "${host_path}" \
    --arg jobs_host_path "${jobs_host_path}" \
    --arg jobs_container_path "${jobs_container_path}" \
    --arg jobs_expected_fstype "${jobs_expected_fstype}" \
    --arg host_jobs_identity "${host_jobs_id}" \
    --arg reference_incoming_identity "${reference_incoming_id}" \
    --arg mismatches "${mismatch_csv}" \
    --arg mismatch_details "${mismatch_detail_csv}" \
    --arg unknowns "${unknown_csv}" \
    --arg skipped "${skipped_csv}" \
    --arg action_details "${action_details}" \
    --arg reason "${result_reason}" \
    --arg fingerprint "${current_fingerprint}" \
    --argjson consecutive_mismatches "${current_count}" \
    '{status:$status,observed_at:$observed_at,host_path:$host_path,local_jobs:{host_path:$jobs_host_path,container_path:$jobs_container_path,expected_fstype:$jobs_expected_fstype,host_identity:$host_jobs_identity,reference_incoming_identity:$reference_incoming_identity},mismatched_consumers:($mismatches|split(",")|map(select(length>0))),mismatch_details:($mismatch_details|split(",")|map(select(length>0))),unknown_consumers:($unknowns|split(",")|map(select(length>0))),skipped_consumers:($skipped|split(",")|map(select(length>0))),action_details:($action_details|split(";")|map(select(length>0))),reason:$reason,fingerprint:$fingerprint,consecutive_mismatches:$consecutive_mismatches}' \
    >"${receipt_tmp}"
  chmod 600 "${state_tmp}" "${receipt_tmp}"
  mv -f "${state_tmp}" "${state_file}"
  mv -f "${receipt_tmp}" "${receipt_file}"
}

on_error() {
  local rc=$?
  trap - ERR
  set +e
  cleanup_recovery_material
  if (( action_started == 1 )); then
    result_reason="action_command_failed_rc_${rc}"
    write_result "action_failed"
  else
    current_count=0
    current_fingerprint=""
    result_reason="unexpected_guard_error_rc_${rc}"
    write_result "guard_error"
  fi
  exit "${rc}"
}
trap on_error ERR

on_signal() {
  trap - ERR INT TERM
  set +e
  cleanup_recovery_material
  if (( action_started == 1 )); then
    result_reason="action_interrupted_by_signal"
    write_result "action_failed"
  fi
  exit 143
}
trap on_signal INT TERM

probe_host() {
  local mount_target=""
  local mount_source=""
  local mount_fstype=""
  read -r mount_target mount_source mount_fstype < <(
    timeout 8 findmnt -T "${host_path}" -n -o TARGET,SOURCE,FSTYPE 2>/dev/null || true
  )
  [[ "${mount_target}" == "/mnt/pcloud" ]] || return 1
  [[ "${mount_source}" == "pcloud:" ]] || return 1
  [[ "${mount_fstype}" == "fuse.rclone" ]] || return 1
  timeout 8 find "${host_path}" -mindepth 1 -maxdepth 1 -print -quit >/dev/null 2>&1 || return 1
  local value
  value="$(timeout 8 stat -c '%d:%i' "${host_path}" 2>/dev/null || true)"
  [[ "${value}" =~ ^[0-9]+:[0-9]+$ ]] || return 1
  printf '%s' "${value}"
}

is_enotconn() {
  local value="$1"
  [[ "${value}" == *"Transport endpoint is not connected"* ||
     "${value}" == *"ENOTCONN"* ]]
}

probe_host_jobs() {
  local mount_target=""
  local mount_source=""
  local mount_fstype=""
  if ! read -r mount_target mount_source mount_fstype < <(
    timeout 8 findmnt -T "${jobs_host_path}" -n -o TARGET,SOURCE,FSTYPE 2>/dev/null
  ); then
    printf 'unhealthy||host_jobs_findmnt_failed\n'
    return 0
  fi
  if [[ -z "${mount_target}" || -z "${mount_source}" || "${mount_fstype}" != "${jobs_expected_fstype}" ]]; then
    printf 'unhealthy||host_jobs_fstype_mismatch\n'
    return 0
  fi

  local stat_value=""
  if ! stat_value="$(timeout 8 stat -c '%d:%i|%F' -- "${jobs_host_path}" 2>&1)"; then
    if is_enotconn "${stat_value}"; then
      printf 'unhealthy||host_jobs_enotconn\n'
    else
      printf 'unhealthy||host_jobs_stat_failed\n'
    fi
    return 0
  fi
  if [[ ! "${stat_value}" =~ ^([0-9]+:[0-9]+)\|directory$ ]]; then
    printf 'unhealthy||host_jobs_identity_invalid\n'
    return 0
  fi
  local jobs_id="${BASH_REMATCH[1]}"

  # The service account deliberately cannot traverse the private jobs tree.
  # mountinfo still lets it reject a stale FUSE/bind descendant before using
  # the exact Docker binds below as read-only views of the marker and incoming
  # directory.
  local nested_mount=""
  # shellcheck disable=SC2016
  if ! nested_mount="$(
    timeout 8 awk -v base="${jobs_host_path}" \
      '$5 == base || index($5, base "/") == 1 { print $5; exit }' \
      /proc/self/mountinfo 2>/dev/null
  )"; then
    printf 'unhealthy||host_jobs_mountinfo_probe_failed\n'
    return 0
  fi
  if [[ -n "${nested_mount}" ]]; then
    printf 'unhealthy||host_jobs_nested_mount_present\n'
    return 0
  fi
  printf 'ok|%s|\n' "${jobs_id}"
}

host_id="$(probe_host || true)"
if [[ -z "${host_id}" ]]; then
  current_count=0
  current_fingerprint=""
  result_reason="host_mount_identity_or_read_probe_failed"
  write_result "host_mount_unhealthy"
  exit 0
fi
IFS='|' read -r host_jobs_status host_jobs_id host_jobs_reason < <(probe_host_jobs)
if [[ "${host_jobs_status}" != "ok" || ! "${host_jobs_id}" =~ ^[0-9]+:[0-9]+$ ]]; then
  current_count=0
  current_fingerprint=""
  result_reason="${host_jobs_reason:-host_jobs_contract_probe_failed}"
  write_result "host_jobs_unhealthy"
  exit 0
fi
if ! timeout 8 docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
  current_count=0
  current_fingerprint=""
  unknown_csv="docker:daemon_probe_failed"
  result_reason="docker_daemon_probe_failed_closed"
  write_result "probe_unknown"
  exit 0
fi

containers=(
  ea-api
  ea-worker
  ea-scheduler
  ea-responses-proxy
  ea-whatsapp-web-action-processor
  audiobookshelf_v2
)
container_paths=(
  /data/audiobooks/audiobookshelf
  /data/audiobooks/audiobookshelf
  /data/audiobooks/audiobookshelf
  /data/audiobooks/audiobookshelf
  /data/audiobooks/audiobookshelf
  /mnt/pcloud/media/Audiobooks
)
expected_projects=(ea ea ea ea ea audiobookshelf)
expected_services=(
  ea-api
  ea-worker
  ea-scheduler
  ea-responses-proxy
  ea-whatsapp-web-action-processor
  audiobookshelf_v2
)

declare -A observed_container_id
declare -A observed_image_id
declare -A observed_inode
declare -A observed_local_signature
declare -A created_container_id
declare -A compose_project
declare -A compose_working_dir
declare -A compose_config_files
declare -A compose_environment_files
declare -A compose_service
declare -A recovery_override_by_container

trusted_compose_path() {
  local path="$1"
  local expected_type="$2"
  local owner=""
  local permissions=""
  local effective_uid=""

  [[ "${path}" == /* ]] || return 1
  [[ "${path}" != *$'\n'* && "${path}" != *"|"* ]] || return 1
  [[ ! -L "${path}" ]] || return 1
  case "${expected_type}" in
    directory)
      [[ -d "${path}" && -x "${path}" ]] || return 1
      ;;
    file)
      [[ -f "${path}" && -r "${path}" ]] || return 1
      ;;
    *)
      return 1
      ;;
  esac
  owner="$(stat -c '%u' -- "${path}" 2>/dev/null || true)"
  permissions="$(stat -c '%A' -- "${path}" 2>/dev/null || true)"
  effective_uid="$(id -u)"
  [[ "${owner}" == "0" || "${owner}" == "${effective_uid}" ]] || return 1
  [[ "${permissions}" =~ ^[-d][rwxStTs-]{9}$ ]] || return 1
  [[ "${permissions:5:1}" != "w" && "${permissions:8:1}" != "w" ]] || return 1
}

trusted_compose_file_list() {
  local values="$1"
  local required="$2"
  local -a paths=()
  local path=""

  if [[ -z "${values}" ]]; then
    [[ "${required}" == "optional" ]]
    return
  fi
  [[ "${values}" != *$'\n'* && "${values}" != *"|"* ]] || return 1
  IFS=',' read -r -a paths <<<"${values}"
  (( ${#paths[@]} > 0 && ${#paths[@]} <= 32 )) || return 1
  for path in "${paths[@]}"; do
    [[ -n "${path}" ]] || return 1
    trusted_compose_path "${path}" file || return 1
  done
}

resolve_compose_topology() {
  local container="$1"
  local expected_container_id="$2"
  local expected_image_id="$3"
  local expected_project="$4"
  local expected_service="$5"
  local inspect_json=""
  local row=""
  local container_id=""
  local image_id=""
  local project=""
  local service=""
  local working_dir=""
  local config_files=""
  local environment_files=""

  inspect_json="$(timeout 8 docker inspect "${container}" 2>/dev/null || true)"
  if [[ -z "${inspect_json}" ]] ||
     ! jq -e 'type == "array" and length == 1' >/dev/null 2>&1 <<<"${inspect_json}"; then
    return 1
  fi
  row="$(
    jq -r \
      '.[0]
       | [.Id,
          .Image,
          (.Config.Labels["com.docker.compose.project"] // ""),
          (.Config.Labels["com.docker.compose.service"] // ""),
          (.Config.Labels["com.docker.compose.project.working_dir"] // ""),
          (.Config.Labels["com.docker.compose.project.config_files"] // ""),
          (.Config.Labels["com.docker.compose.project.environment_file"] // "")]
       | @tsv' <<<"${inspect_json}"
  )"
  IFS=$'\t' read -r \
    container_id image_id project service working_dir config_files environment_files \
    <<<"${row}"
  [[ "${container_id}" == "${expected_container_id}" ]] || return 1
  [[ "${image_id}" == "${expected_image_id}" ]] || return 1
  [[ "${project}" == "${expected_project}" ]] || return 1
  [[ "${service}" == "${expected_service}" ]] || return 1
  [[ "${project}" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || return 1
  [[ "${service}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || return 1
  trusted_compose_path "${working_dir}" directory || return 1
  trusted_compose_file_list "${config_files}" required || return 1
  trusted_compose_file_list "${environment_files}" optional || return 1

  compose_project["${container}"]="${project}"
  compose_working_dir["${container}"]="${working_dir}"
  compose_config_files["${container}"]="${config_files}"
  compose_environment_files["${container}"]="${environment_files}"
  compose_service["${container}"]="${service}"
}

run_compose_for_container() {
  local mode="$1"
  local container="$2"
  local override_file="${recovery_override_by_container[$container]}"
  local -a command=(
    docker compose
    --project-name "${compose_project[$container]}"
    --project-directory "${compose_working_dir[$container]}"
  )
  local -a paths=()
  local path=""

  if [[ -n "${compose_environment_files[$container]}" ]]; then
    IFS=',' read -r -a paths <<<"${compose_environment_files[$container]}"
    for path in "${paths[@]}"; do
      command+=(--env-file "${path}")
    done
  fi
  IFS=',' read -r -a paths <<<"${compose_config_files[$container]}"
  for path in "${paths[@]}"; do
    command+=(-f "${path}")
  done
  command+=(-f "${override_file}")

  case "${mode}" in
    preflight)
      COMPOSE_IGNORE_ORPHANS=true "${command[@]}" config --format json >/dev/null
      ;;
    recreate)
      COMPOSE_IGNORE_ORPHANS=true "${command[@]}" \
        up -d --no-deps --force-recreate --no-build --pull never \
        --wait --wait-timeout 180 "${compose_service[$container]}"
      ;;
    *)
      return 2
      ;;
  esac
}

probe_container() {
  local container="$1"
  local container_path="$2"
  local expected_project="$3"
  local expected_service="$4"
  local inspect_json
  inspect_json="$(timeout 8 docker inspect "${container}" 2>/dev/null || true)"
  if [[ -z "${inspect_json}" ]]; then
    printf 'unknown|container_inspect_failed||||\n'
    return 0
  fi
  if ! jq -e 'type == "array" and length == 1' >/dev/null 2>&1 <<<"${inspect_json}"; then
    printf 'unknown|container_inspect_invalid||||\n'
    return 0
  fi
  local row
  row="$(
    jq -r \
      '.[0]
       | [.Id,
          .Image,
          (.State.Running | tostring),
          (.State.Paused | tostring),
          (.State.Restarting | tostring),
          .State.Status,
          (.Config.Labels["com.docker.compose.project"] // ""),
          (.Config.Labels["com.docker.compose.service"] // ""),
          ([.Config.Env[]? | select(startswith("EA_DEPLOY_PRIMARY_MODE="))][0] // ""),
          ([.Config.Env[]? | select(startswith("EA_DEPLOY_ENABLED_MODES="))][0] // "")]
       | @tsv' <<<"${inspect_json}"
  )"
  local container_id image_id running paused restarting status project service primary_mode_entry enabled_modes_entry
  IFS=$'\t' read -r \
    container_id image_id running paused restarting status project service \
    primary_mode_entry enabled_modes_entry <<<"${row}"
  if [[ ! "${container_id}" =~ ^[0-9a-f]{64}$ ]] || [[ ! "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'unknown|container_identity_invalid||||\n'
    return 0
  fi
  if [[ "${running}" != "true" ]]; then
    printf 'stopped|not_running|%s|%s|%s|%s\n' "${container_id}" "${image_id}" "${project}" "${service}"
    return 0
  fi
  if [[ "${paused}" == "true" || "${restarting}" == "true" || "${status}" != "running" ]]; then
    printf 'unknown|unstable_container_state|%s|%s|%s|%s\n' "${container_id}" "${image_id}" "${project}" "${service}"
    return 0
  fi
  if [[ "${project}" != "${expected_project}" || "${service}" != "${expected_service}" ]]; then
    printf 'unknown|compose_identity_mismatch|%s|%s|%s|%s\n' "${container_id}" "${image_id}" "${project}" "${service}"
    return 0
  fi
  if [[ "${project}" == "ea" &&
        "${primary_mode_entry#EA_DEPLOY_PRIMARY_MODE=}" == "MEMORIAL" &&
        "${enabled_modes_entry#EA_DEPLOY_ENABLED_MODES=}" == "MEMORIAL" ]]; then
    printf 'skipped|memorial_mode_without_audiobook_mount|%s|%s|%s|%s\n' \
      "${container_id}" "${image_id}" "${project}" "${service}"
    return 0
  fi
  local inode
  inode="$(timeout 8 docker exec "${container}" stat -c '%d:%i' "${container_path}" 2>/dev/null || true)"
  if [[ ! "${inode}" =~ ^[0-9]+:[0-9]+$ ]]; then
    printf 'unknown|mount_probe_failed|%s|%s|%s|%s\n' "${container_id}" "${image_id}" "${project}" "${service}"
    return 0
  fi
  printf 'ok|%s|%s|%s|%s|%s\n' "${container_id}" "${image_id}" "${inode}" "${project}" "${service}"
}

probe_container_jobs() {
  local container="$1"
  local expected_container_id="$2"
  local expected_image_id="$3"
  local inspect_json=""
  inspect_json="$(timeout 8 docker inspect "${container}" 2>/dev/null || true)"
  if [[ -z "${inspect_json}" ]] ||
     ! jq -e 'type == "array" and length == 1' >/dev/null 2>&1 <<<"${inspect_json}"; then
    printf 'unknown|local_jobs_container_inspect_failed||\n'
    return 0
  fi

  local row=""
  row="$(
    jq -r \
      --arg source "${jobs_host_path}" \
      --arg destination "${jobs_container_path}" \
      '.[0] as $container
       | ([$container.Mounts[]? | select(.Destination == $destination)]) as $mounts
       | [$container.Id,
          $container.Image,
          (($mounts | length) | tostring),
          ($mounts[0].Type // ""),
          ($mounts[0].Source // ""),
          ($mounts[0].Destination // ""),
          (($mounts[0].RW // false) | tostring),
          ($mounts[0].Propagation // "")]
       | @tsv' <<<"${inspect_json}"
  )"
  local container_id image_id mount_count mount_type mount_source mount_destination mount_rw mount_propagation
  IFS=$'\t' read -r container_id image_id mount_count mount_type mount_source mount_destination mount_rw mount_propagation <<<"${row}"
  if [[ "${container_id}" != "${expected_container_id}" || "${image_id}" != "${expected_image_id}" ]]; then
    printf 'unknown|local_jobs_container_identity_changed||\n'
    return 0
  fi
  if [[ "${mount_count}" != "1" ||
        "${mount_type}" != "bind" ||
        "${mount_source}" != "${jobs_host_path}" ||
        "${mount_destination}" != "${jobs_container_path}" ||
        "${mount_rw}" != "true" ||
        "${mount_propagation}" != "rprivate" ]]; then
    printf 'mismatch|local_jobs_bind_contract_mismatch||\n'
    return 0
  fi

  local jobs_stat=""
  local probe_rc=0
  if jobs_stat="$(
    timeout 8 docker exec "${container}" env LC_ALL=C \
      timeout 4 stat -c '%d:%i|%F' -- "${jobs_container_path}" 2>&1
  )"; then
    :
  else
    probe_rc=$?
    if (( probe_rc == 124 )); then
      printf 'mismatch|local_jobs_stat_timeout||\n'
    elif is_enotconn "${jobs_stat}"; then
      printf 'mismatch|local_jobs_enotconn||\n'
    else
      printf 'unknown|local_jobs_stat_failed||\n'
    fi
    return 0
  fi
  if [[ ! "${jobs_stat}" =~ ^([0-9]+:[0-9]+)\|directory$ ]]; then
    printf 'unknown|local_jobs_identity_invalid||\n'
    return 0
  fi
  local jobs_id="${BASH_REMATCH[1]}"
  if [[ "${jobs_id}" != "${host_jobs_id}" ]]; then
    printf 'mismatch|local_jobs_host_identity_mismatch|%s|\n' "${jobs_id}"
    return 0
  fi

  local container_jobs_fstype=""
  # shellcheck disable=SC2016
  if ! container_jobs_fstype="$(
    timeout 8 docker exec "${container}" awk -v target="${jobs_container_path}" \
      '$5 == target {
         for (field = 1; field <= NF; field++) {
           if ($field == "-") { print $(field + 1); found = 1; exit }
         }
       }
       END { if (!found) exit 1 }' \
      /proc/self/mountinfo 2>/dev/null
  )"; then
    printf 'mismatch|local_jobs_mountinfo_missing|%s|\n' "${jobs_id}"
    return 0
  fi
  if [[ "${container_jobs_fstype}" != "${jobs_expected_fstype}" ]]; then
    printf 'mismatch|local_jobs_fstype_mismatch|%s|\n' "${jobs_id}"
    return 0
  fi

  local marker_stat=""
  if marker_stat="$(
    timeout 8 docker exec "${container}" env LC_ALL=C \
      timeout 4 stat -c '%F' -- "${jobs_marker_path}" 2>&1
  )"; then
    :
  else
    probe_rc=$?
    if (( probe_rc == 124 )); then
      printf 'mismatch|local_jobs_marker_timeout|%s|\n' "${jobs_id}"
    elif is_enotconn "${marker_stat}"; then
      printf 'mismatch|local_jobs_marker_enotconn|%s|\n' "${jobs_id}"
    else
      printf 'unknown|local_jobs_marker_stat_failed|%s|\n' "${jobs_id}"
    fi
    return 0
  fi
  if [[ "${marker_stat}" != "regular file" ]]; then
    printf 'unknown|local_jobs_marker_not_regular|%s|\n' "${jobs_id}"
    return 0
  fi
  local marker_output=""
  if marker_output="$(
    timeout 8 docker exec "${container}" env LC_ALL=C \
      timeout 4 sha256sum -- "${jobs_marker_path}" 2>&1
  )"; then
    :
  else
    probe_rc=$?
    if (( probe_rc == 124 )); then
      printf 'mismatch|local_jobs_marker_timeout|%s|\n' "${jobs_id}"
    elif is_enotconn "${marker_output}"; then
      printf 'mismatch|local_jobs_marker_enotconn|%s|\n' "${jobs_id}"
    else
      printf 'unknown|local_jobs_marker_read_failed|%s|\n' "${jobs_id}"
    fi
    return 0
  fi
  if [[ "${marker_output%% *}" != "${jobs_marker_sha256}" ]]; then
    printf 'unknown|local_jobs_marker_digest_mismatch|%s|\n' "${jobs_id}"
    return 0
  fi

  local incoming_stat=""
  if incoming_stat="$(
    timeout 8 docker exec "${container}" env LC_ALL=C \
      timeout 4 stat -c '%d:%i|%F' -- "${jobs_incoming_path}" 2>&1
  )"; then
    :
  else
    probe_rc=$?
    if (( probe_rc == 124 )); then
      printf 'mismatch|local_jobs_incoming_timeout|%s|\n' "${jobs_id}"
    elif is_enotconn "${incoming_stat}"; then
      printf 'mismatch|local_jobs_incoming_enotconn|%s|\n' "${jobs_id}"
    else
      printf 'unknown|local_jobs_incoming_stat_failed|%s|\n' "${jobs_id}"
    fi
    return 0
  fi
  if [[ ! "${incoming_stat}" =~ ^([0-9]+:[0-9]+)\|directory$ ]]; then
    printf 'unknown|local_jobs_incoming_identity_invalid|%s|\n' "${jobs_id}"
    return 0
  fi
  local incoming_id="${BASH_REMATCH[1]}"
  if [[ "${incoming_id%%:*}" != "${jobs_id%%:*}" ]]; then
    printf 'mismatch|local_jobs_incoming_device_mismatch|%s|%s\n' "${jobs_id}" "${incoming_id}"
    return 0
  fi

  local nested_mount=""
  # shellcheck disable=SC2016
  if ! nested_mount="$(
    timeout 8 docker exec "${container}" awk -v base="${jobs_incoming_path}" \
      '$5 == base || index($5, base "/") == 1 { print $5; exit }' \
      /proc/self/mountinfo 2>/dev/null
  )"; then
    printf 'unknown|local_jobs_incoming_mountinfo_probe_failed|%s|%s\n' "${jobs_id}" "${incoming_id}"
    return 0
  fi
  if [[ -n "${nested_mount}" ]]; then
    printf 'mismatch|local_jobs_incoming_nested_mount|%s|%s\n' "${jobs_id}" "${incoming_id}"
    return 0
  fi

  local readdir_output=""
  if readdir_output="$(
    timeout 8 docker exec "${container}" env LC_ALL=C \
      timeout 4 find "${jobs_incoming_path}" -mindepth 1 -maxdepth 1 \
      -exec stat -c '%d:%i' -- '{}' ';' -quit 2>&1
  )"; then
    :
  else
    probe_rc=$?
    if (( probe_rc == 124 )); then
      printf 'mismatch|local_jobs_incoming_readdir_timeout|%s|%s\n' "${jobs_id}" "${incoming_id}"
    elif is_enotconn "${readdir_output}"; then
      printf 'mismatch|local_jobs_incoming_readdir_enotconn|%s|%s\n' "${jobs_id}" "${incoming_id}"
    else
      printf 'unknown|local_jobs_incoming_readdir_failed|%s|%s\n' "${jobs_id}" "${incoming_id}"
    fi
    return 0
  fi
  printf 'ok||%s|%s\n' "${jobs_id}" "${incoming_id}"
}

mismatched=()
mismatch_details=()
unknown=()
skipped=()
identity_rows=()
declare -A mismatch_seen
reference_incoming_container=""
local_probe_count=0

mark_mismatch() {
  local container="$1"
  local reason="$2"
  local identity="$3"
  if [[ -z "${mismatch_seen[${container}]+x}" ]]; then
    mismatched+=("${container}")
    mismatch_seen["${container}"]=1
  fi
  mismatch_details+=("${container}:${reason}")
  identity_rows+=("${container}:${reason}:${identity}")
}

for index in "${!containers[@]}"; do
  container="${containers[$index]}"
  IFS='|' read -r probe_status field1 field2 field3 _ < <(
    probe_container \
      "${container}" \
      "${container_paths[$index]}" \
      "${expected_projects[$index]}" \
      "${expected_services[$index]}"
  )
  case "${probe_status}" in
    stopped)
      skipped+=("${container}:${field1}")
      ;;
    skipped)
      skipped+=("${container}:${field1}")
      ;;
    unknown)
      unknown+=("${container}:${field1}")
      ;;
    ok)
      observed_container_id["${container}"]="${field1}"
      observed_image_id["${container}"]="${field2}"
      observed_inode["${container}"]="${field3}"
      if [[ "${field3}" != "${host_id}" ]]; then
        mark_mismatch \
          "${container}" \
          "pcloud_generation_mismatch" \
          "container=${field1}:image=${field2}:pcloud=${field3}"
      fi
      ;;
  esac
done

# Audiobookshelf has only the pCloud contract. Every running EA consumer must
# also expose the private local jobs bind, marker, and incoming directory from
# the same ext4 generation.
for index in "${!containers[@]}"; do
  container="${containers[$index]}"
  [[ "${container}" == "audiobookshelf_v2" ]] && continue
  [[ -z "${observed_container_id[${container}]+x}" ]] && continue
  local_probe_count=$((local_probe_count + 1))
  IFS='|' read -r local_status local_reason local_jobs_id local_incoming_id < <(
    probe_container_jobs \
      "${container}" \
      "${observed_container_id[$container]}" \
      "${observed_image_id[$container]}"
  )
  observed_local_signature["${container}"]="${local_status}|${local_reason}|${local_jobs_id}|${local_incoming_id}"
  case "${local_status}" in
    unknown)
      unknown+=("${container}:${local_reason}")
      ;;
    mismatch)
      mark_mismatch \
        "${container}" \
        "${local_reason}" \
        "container=${observed_container_id[$container]}:image=${observed_image_id[$container]}:jobs=${local_jobs_id:-unavailable}:incoming=${local_incoming_id:-unavailable}"
      ;;
    ok)
      if [[ -z "${reference_incoming_id}" ]]; then
        reference_incoming_id="${local_incoming_id}"
        reference_incoming_container="${container}"
      elif [[ "${local_incoming_id}" != "${reference_incoming_id}" ]]; then
        mark_mismatch \
          "${container}" \
          "local_jobs_incoming_identity_mismatch" \
          "container=${observed_container_id[$container]}:image=${observed_image_id[$container]}:jobs=${local_jobs_id}:incoming=${local_incoming_id}:reference=${reference_incoming_id}"
      fi
      ;;
    *)
      unknown+=("${container}:local_jobs_probe_contract_invalid")
      ;;
  esac
done

if (( local_probe_count > 0 )) && [[ -z "${reference_incoming_id}" ]]; then
  unknown+=("local_jobs:no_verified_incoming_reference")
fi

if (( ${#skipped[@]} > 0 )); then
  skipped_csv="$(IFS=,; echo "${skipped[*]}")"
fi
if (( ${#unknown[@]} > 0 )); then
  unknown_csv="$(IFS=,; echo "${unknown[*]}")"
  current_count=0
  current_fingerprint=""
  result_reason="probe_unknown_fail_closed"
  write_result "probe_unknown"
  exit 0
fi
if (( ${#mismatched[@]} == 0 )); then
  current_count=0
  current_fingerprint=""
  result_reason="all_running_consumers_match_verified_host_mounts"
  write_result "healthy"
  exit 0
fi

mismatch_csv="$(IFS=,; echo "${mismatched[*]}")"
mismatch_detail_csv="$(IFS=,; echo "${mismatch_details[*]}")"
current_fingerprint="$({
  printf '%s\n' "pcloud-host:${host_id}"
  printf '%s\n' "jobs-host:${host_jobs_id}"
  printf '%s\n' "incoming-reference:${reference_incoming_id}"
  printf '%s\n' "${identity_rows[@]}" | sort
} | sha256sum | awk '{print $1}')"
if [[ "${current_fingerprint}" == "${previous_fingerprint}" ]]; then
  current_count=$((previous_count + 1))
else
  current_count=1
fi
if (( current_count < required_samples )); then
  result_reason="waiting_for_same_generation_consecutive_confirmation"
  write_result "mismatch_observed"
  exit 0
fi
if [[ "${current_fingerprint}" == "${last_action_fingerprint}" ]] && (( now_epoch - last_action_epoch < cooldown_seconds )); then
  result_reason="same_mismatch_action_cooldown_active"
  write_result "cooldown"
  exit 0
fi

# Revalidate the exact host generation, container IDs, image IDs, Compose
# identities, and stale inodes immediately before any mutation.
latest_host_id="$(probe_host || true)"
if [[ "${latest_host_id}" != "${host_id}" ]]; then
  current_count=0
  current_fingerprint=""
  result_reason="host_generation_changed_before_action"
  write_result "preaction_changed"
  exit 0
fi
IFS='|' read -r latest_jobs_status latest_jobs_id _ < <(probe_host_jobs)
if [[ "${latest_jobs_status}" != "ok" || "${latest_jobs_id}" != "${host_jobs_id}" ]]; then
  current_count=0
  current_fingerprint=""
  result_reason="host_jobs_generation_changed_before_action"
  write_result "preaction_changed"
  exit 0
fi
runtime_image_id=""
for container in "${mismatched[@]}"; do
  selected_index=-1
  for index in "${!containers[@]}"; do
    if [[ "${containers[$index]}" == "${container}" ]]; then
      selected_index="${index}"
      break
    fi
  done
  (( selected_index >= 0 ))
  IFS='|' read -r probe_status field1 field2 field3 _ < <(
    probe_container \
      "${container}" \
      "${container_paths[$selected_index]}" \
      "${expected_projects[$selected_index]}" \
      "${expected_services[$selected_index]}"
  )
  if [[ "${probe_status}" != "ok" || "${field1}" != "${observed_container_id[$container]}" || "${field2}" != "${observed_image_id[$container]}" || "${field3}" != "${observed_inode[$container]}" ]]; then
    current_count=0
    current_fingerprint=""
    result_reason="container_identity_changed_before_action"
    write_result "preaction_changed"
    exit 0
  fi
  if [[ "${container}" != "audiobookshelf_v2" ]]; then
    IFS='|' read -r local_status local_reason local_jobs_id local_incoming_id < <(
      probe_container_jobs "${container}" "${field1}" "${field2}"
    )
    local_signature="${local_status}|${local_reason}|${local_jobs_id}|${local_incoming_id}"
    if [[ "${local_signature}" != "${observed_local_signature[$container]}" ]]; then
      current_count=0
      current_fingerprint=""
      result_reason="local_jobs_identity_changed_before_action"
      write_result "preaction_changed"
      exit 0
    fi
    if [[ -z "${runtime_image_id}" ]]; then
      runtime_image_id="${field2}"
    elif [[ "${runtime_image_id}" != "${field2}" ]]; then
      current_count=0
      current_fingerprint=""
      result_reason="selected_ea_runtime_images_differ"
      write_result "preaction_refused"
      exit 0
    fi
  fi
done

# Keep the healthy incoming generation used as the local reference pinned even
# when that consumer is not itself in the targeted recreation set.
if [[ -n "${reference_incoming_container}" &&
      -z "${mismatch_seen[${reference_incoming_container}]+x}" ]]; then
  selected_index=-1
  for index in "${!containers[@]}"; do
    if [[ "${containers[$index]}" == "${reference_incoming_container}" ]]; then
      selected_index="${index}"
      break
    fi
  done
  (( selected_index >= 0 ))
  IFS='|' read -r probe_status field1 field2 field3 _ < <(
    probe_container \
      "${reference_incoming_container}" \
      "${container_paths[$selected_index]}" \
      "${expected_projects[$selected_index]}" \
      "${expected_services[$selected_index]}"
  )
  if [[ "${probe_status}" != "ok" ||
        "${field1}" != "${observed_container_id[$reference_incoming_container]}" ||
        "${field2}" != "${observed_image_id[$reference_incoming_container]}" ||
        "${field3}" != "${observed_inode[$reference_incoming_container]}" ]]; then
    current_count=0
    current_fingerprint=""
    result_reason="incoming_reference_changed_before_action"
    write_result "preaction_changed"
    exit 0
  fi
  IFS='|' read -r local_status local_reason local_jobs_id local_incoming_id < <(
    probe_container_jobs "${reference_incoming_container}" "${field1}" "${field2}"
  )
  local_signature="${local_status}|${local_reason}|${local_jobs_id}|${local_incoming_id}"
  if [[ "${local_signature}" != "${observed_local_signature[$reference_incoming_container]}" ||
        "${local_incoming_id}" != "${reference_incoming_id}" ]]; then
    current_count=0
    current_fingerprint=""
    result_reason="incoming_reference_changed_before_action"
    write_result "preaction_changed"
    exit 0
  fi
fi

# Resolve the exact Compose topology from the still-running container labels.
# A release may use several overlays and an explicit environment file; falling
# back to a repository default can silently remove its security and mode
# bindings. Missing, untrusted, or no-longer-renderable topology fails closed
# before any container is mutated.
for container in "${mismatched[@]}"; do
  selected_index=-1
  for index in "${!containers[@]}"; do
    if [[ "${containers[$index]}" == "${container}" ]]; then
      selected_index="${index}"
      break
    fi
  done
  (( selected_index >= 0 ))
  if ! resolve_compose_topology \
    "${container}" \
    "${observed_container_id[$container]}" \
    "${observed_image_id[$container]}" \
    "${expected_projects[$selected_index]}" \
    "${expected_services[$selected_index]}"; then
    cleanup_recovery_material
    current_count=0
    current_fingerprint=""
    result_reason="compose_topology_untrusted_or_unavailable:${container}"
    write_result "preaction_refused"
    exit 0
  fi

  old_container_id="${observed_container_id[$container]}"
  old_image_id="${observed_image_id[$container]}"
  image_hex="${old_image_id#sha256:}"
  recovery_tag="local/ea-audiobook-mount-guard:${container}-${image_hex}"
  override_file="${state_root}/recovery-${container}-${now_epoch}.json"
  override_tmp="${override_file}.tmp"
  recovery_tags+=("${recovery_tag}")
  recovery_override_files+=("${override_tmp}" "${override_file}")
  recovery_override_by_container["${container}"]="${override_file}"
  preparation_failed=0
  docker image tag "${old_image_id}" "${recovery_tag}" || preparation_failed=1
  if (( preparation_failed == 0 )); then
    jq -n \
      --arg service "${compose_service[$container]}" \
      --arg image "${recovery_tag}" \
      '{services:{($service):{image:$image}}}' \
      >"${override_tmp}" || preparation_failed=1
  fi
  if (( preparation_failed == 0 )); then
    chmod 600 "${override_tmp}" || preparation_failed=1
  fi
  if (( preparation_failed == 0 )); then
    mv -f "${override_tmp}" "${override_file}" || preparation_failed=1
  fi
  if (( preparation_failed == 0 )); then
    run_compose_for_container preflight "${container}" || preparation_failed=1
  fi
  if (( preparation_failed != 0 )); then
    cleanup_recovery_material
    current_count=0
    current_fingerprint=""
    result_reason="compose_topology_render_failed:${container}"
    write_result "preaction_refused"
    exit 0
  fi
done

last_action_epoch="${now_epoch}"
last_action_fingerprint="${current_fingerprint}"
result_reason="recreate_lease_acquired"
write_result "action_started"
action_started=1

for container in "${mismatched[@]}"; do
  old_container_id="${observed_container_id[$container]}"
  old_image_id="${observed_image_id[$container]}"
  run_compose_for_container recreate "${container}"
  new_container_id="$(docker inspect -f '{{.Id}}' "${container}")"
  new_image_id="$(docker inspect -f '{{.Image}}' "${container}")"
  [[ "${new_container_id}" != "${old_container_id}" ]]
  [[ "${new_image_id}" == "${old_image_id}" ]]
  created_container_id["${container}"]="${new_container_id}"
  action_details+="${container}:${old_container_id:0:12}->${new_container_id:0:12}:image=${new_image_id:7:12};"
done

recovered=0
for _attempt in $(seq 1 36); do
  latest_host_id="$(probe_host || true)"
  if [[ "${latest_host_id}" != "${host_id}" ]]; then
    break
  fi
  IFS='|' read -r latest_jobs_status latest_jobs_id _ < <(probe_host_jobs)
  if [[ "${latest_jobs_status}" != "ok" || "${latest_jobs_id}" != "${host_jobs_id}" ]]; then
    break
  fi
  recovered=1
  for container in "${mismatched[@]}"; do
    selected_index=-1
    for index in "${!containers[@]}"; do
      if [[ "${containers[$index]}" == "${container}" ]]; then
        selected_index="${index}"
        break
      fi
    done
    (( selected_index >= 0 ))
    IFS='|' read -r probe_status field1 field2 field3 _ < <(
      probe_container \
        "${container}" \
        "${container_paths[$selected_index]}" \
        "${expected_projects[$selected_index]}" \
        "${expected_services[$selected_index]}"
    )
    if [[ "${probe_status}" != "ok" || "${field1}" != "${created_container_id[$container]}" || "${field2}" != "${observed_image_id[$container]}" || "${field3}" != "${host_id}" ]]; then
      recovered=0
      break
    fi
    if [[ "${container}" != "audiobookshelf_v2" ]]; then
      IFS='|' read -r local_status local_reason local_jobs_id local_incoming_id < <(
        probe_container_jobs "${container}" "${field1}" "${field2}"
      )
      if [[ "${local_status}" != "ok" ||
            "${local_jobs_id}" != "${host_jobs_id}" ||
            "${local_incoming_id}" != "${reference_incoming_id}" ]]; then
        recovered=0
        break
      fi
    fi
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container}" 2>/dev/null || true)"
    if [[ "${health}" != "none" && "${health}" != "healthy" ]]; then
      recovered=0
      break
    fi
    if [[ "${container}" == "audiobookshelf_v2" ]]; then
      if ! timeout 8 docker exec audiobookshelf_v2 node -e "fetch('http://127.0.0.1/status').then(r=>r.json()).then(v=>{if(v.app==='audiobookshelf'&&v.isInit===true){process.exit(0)}process.exit(1)}).catch(()=>process.exit(1))"; then
        recovered=0
        break
      fi
    elif [[ "${health}" == "none" ]]; then
      started_at="$(docker inspect -f '{{.State.StartedAt}}' "${container}")"
      started_epoch="$(date -d "${started_at}" +%s 2>/dev/null || echo "${now_epoch}")"
      if (( $(date +%s) - started_epoch < 15 )); then
        recovered=0
        break
      fi
    fi
  done
  if (( recovered == 1 )) &&
     [[ -n "${reference_incoming_container}" ]] &&
     [[ -z "${mismatch_seen[${reference_incoming_container}]+x}" ]]; then
    IFS='|' read -r local_status local_reason local_jobs_id local_incoming_id < <(
      probe_container_jobs \
        "${reference_incoming_container}" \
        "${observed_container_id[$reference_incoming_container]}" \
        "${observed_image_id[$reference_incoming_container]}"
    )
    if [[ "${local_status}" != "ok" ||
          "${local_jobs_id}" != "${host_jobs_id}" ||
          "${local_incoming_id}" != "${reference_incoming_id}" ]]; then
      recovered=0
    fi
  fi
  (( recovered == 1 )) && break
  sleep 5
done

if (( recovered != 1 )); then
  false
fi

cleanup_recovery_material
current_count=0
current_fingerprint=""
result_reason="affected_consumers_recreated_and_readiness_verified"
write_result "recovered"
action_started=0
trap - ERR INT TERM
