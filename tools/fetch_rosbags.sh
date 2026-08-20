#!/usr/bin/env bash
set -euo pipefail

# Downloads rosbag directories from a remote collection device over SSH/rsync
# and removes each one from the device after a successful copy.

REMOTE_HOST="${REMOTE_HOST:?set REMOTE_HOST to user@device-ip, e.g. firefly@192.168.19.139}"
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
  REMOTE_HOST          required, e.g. firefly@192.168.19.139
  REMOTE_REPO_DIR       repo path on the device (default: ${REMOTE_REPO_DIR})
  REMOTE_BAG_SUBDIR     "rosbags_mid360" (default) or "rosbags" for the
                         docker Recorder's bags
  LOCAL_DEST_ROOT       local destination (default: ${LOCAL_DEST_ROOT})
  REMOTE_SSH_PASSWORD   use sshpass instead of SSH keys/agent (dev convenience
                         only — never commit a password to this repo)
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

if [[ -n "${REMOTE_SSH_PASSWORD:-}" ]]; then
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
