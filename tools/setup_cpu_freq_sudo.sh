#!/usr/bin/env bash
set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/unilidar-cpu-freq"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root, for example: sudo bash $0" >&2
  exit 1
fi

# Detect service user from the systemd unit, fall back to SUDO_USER, then prompt.
SERVICE_USER="$(systemctl show -p User --value unilidar-web.service 2>/dev/null || true)"
if [[ -z "${SERVICE_USER}" ]]; then
  SERVICE_USER="${SUDO_USER:-}"
fi
if [[ -z "${SERVICE_USER}" ]]; then
  read -rp "Enter the user that runs unilidar-web.service: " SERVICE_USER
fi
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "User '${SERVICE_USER}' does not exist." >&2
  exit 1
fi

echo "Granting passwordless sudo for cpufreq writes to user: ${SERVICE_USER}"

cat > "${SUDOERS_FILE}" <<EOF
# Allow ${SERVICE_USER} to set CPU frequency governor and limits without a password.
# Written by setup_cpu_freq_sudo.sh — edit or delete this file to revoke.
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/tee /sys/devices/system/cpu/cpufreq/policy*/scaling_governor
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/tee /sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/tee /sys/devices/system/cpu/cpufreq/policy*/scaling_min_freq
EOF

chmod 0440 "${SUDOERS_FILE}"

if visudo -cf "${SUDOERS_FILE}"; then
  echo "Sudoers rule installed: ${SUDOERS_FILE}"
else
  rm -f "${SUDOERS_FILE}"
  echo "visudo validation failed — rule not installed." >&2
  exit 1
fi
