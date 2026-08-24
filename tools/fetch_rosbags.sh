#!/usr/bin/env bash
set -euo pipefail

# Downloads rosbag directories from a remote collection device over SSH/rsync
# and removes each one from the device after a successful copy.

# Defaults target the deployed RK3588 collector, so a bare run downloads and
# then DELETES that device's bags. Override REMOTE_HOST for any other device.
REMOTE_HOST="${REMOTE_HOST:-firefly@192.168.19.139}"
REMOTE_REPO_DIR="${REMOTE_REPO_DIR:-work/UniLidar-SDK-Collection}"
REMOTE_BAG_SUBDIR="${REMOTE_BAG_SUBDIR:-rosbags_mid360}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_DEST_ROOT="${LOCAL_DEST_ROOT:-${REPO_ROOT}/data/rosbags_downloaded/${REMOTE_BAG_SUBDIR}}"

usage() {
  cat <<EOF
Usage:
  $0

Behavior:
  - Lists rosbag directories under ${REMOTE_REPO_DIR}/data/${REMOTE_BAG_SUBDIR}
    on ${REMOTE_HOST}
  - Downloads each one to ${LOCAL_DEST_ROOT}
  - Removes each rosbag directory from the device after a successful copy

Environment overrides:
  REMOTE_HOST           device to pull from (default: ${REMOTE_HOST})
  REMOTE_REPO_DIR       repo path on the device (default: ${REMOTE_REPO_DIR})
  REMOTE_BAG_SUBDIR     "rosbags_mid360" (default) or "rosbags" for the
                         docker Recorder's bags
  LOCAL_DEST_ROOT       local destination (default: ${LOCAL_DEST_ROOT})
  REMOTE_SSH_PASSWORD   sshpass password for REMOTE_HOST (defaults to the
                         RK3588's stock password). Set it empty to use SSH
                         keys/agent instead.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "unexpected arguments: $*" >&2
  usage >&2
  exit 1
fi

# Single dash, so REMOTE_SSH_PASSWORD="" opts back into SSH keys/agent.
REMOTE_SSH_PASSWORD="${REMOTE_SSH_PASSWORD-firefly}"

if [[ -n "${REMOTE_SSH_PASSWORD}" ]] && ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass not installed; falling back to SSH keys/agent." >&2
  REMOTE_SSH_PASSWORD=""
fi

if [[ -n "${REMOTE_SSH_PASSWORD}" ]]; then
  export SSHPASS="${REMOTE_SSH_PASSWORD}"
  SSH_CMD=(sshpass -e ssh -o StrictHostKeyChecking=accept-new)
  RSYNC_RSH="sshpass -e ssh -o StrictHostKeyChecking=accept-new"
else
  SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new)
  RSYNC_RSH="ssh -o StrictHostKeyChecking=accept-new"
fi

REMOTE_BAG_PATH="${REMOTE_REPO_DIR}/data/${REMOTE_BAG_SUBDIR}"

if ! "${SSH_CMD[@]}" "${REMOTE_HOST}" true; then
  echo "cannot reach ${REMOTE_HOST} over ssh" >&2
  exit 1
fi

mapfile -t BAG_NAMES < <("${SSH_CMD[@]}" "${REMOTE_HOST}" "ls -1 '${REMOTE_BAG_PATH}'" 2>/dev/null)
if [[ ${#BAG_NAMES[@]} -eq 0 ]]; then
  echo "no rosbag directories found at ${REMOTE_HOST}:${REMOTE_BAG_PATH}/"
  exit 0
fi

mkdir -p "${LOCAL_DEST_ROOT}"

echo "Found ${#BAG_NAMES[@]} rosbag directories at ${REMOTE_HOST}:${REMOTE_BAG_PATH}/"
for BAG_NAME in "${BAG_NAMES[@]}"; do
  DEST_PATH="${LOCAL_DEST_ROOT}/${BAG_NAME}"

  echo "Downloading:"
  echo "  source: ${REMOTE_HOST}:${REMOTE_BAG_PATH}/${BAG_NAME}"
  echo "  dest:   ${DEST_PATH}"

  rsync -a --checksum --info=progress2 -e "${RSYNC_RSH}" \
    "${REMOTE_HOST}:${REMOTE_BAG_PATH}/${BAG_NAME}/" "${DEST_PATH}/"

  "${SSH_CMD[@]}" "${REMOTE_HOST}" "rm -rf -- '${REMOTE_BAG_PATH}/${BAG_NAME}'"
  echo "Removed from device: ${REMOTE_BAG_PATH}/${BAG_NAME}"
done

echo "Download complete: ${LOCAL_DEST_ROOT}"
