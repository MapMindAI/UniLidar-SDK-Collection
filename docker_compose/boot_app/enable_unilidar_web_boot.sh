#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVICE_DST="/etc/systemd/system/unilidar-web.service"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root, for example: sudo bash $0" >&2
  exit 1
fi

if [[ -z "${SUDO_USER:-}" ]]; then
  SERVICE_USER="$(id -un)"
fi

if [[ ! -d "${REPO_ROOT}" ]]; then
  echo "Repo root not found: ${REPO_ROOT}" >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/docker_compose/unilidar_mapping/webserver.py" ]]; then
  echo "webserver.py not found under repo root: ${REPO_ROOT}" >&2
  exit 1
fi

cat > "${SERVICE_DST}" <<EOF
[Unit]
Description=UniLidar Remote Web Server
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_ROOT}
Environment=UNILIDAR_WEB_HOST=0.0.0.0
Environment=UNILIDAR_WEB_PORT=8080
ExecStart=/usr/bin/python3 ${REPO_ROOT}/docker_compose/unilidar_mapping/webserver.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

chmod 0644 "${SERVICE_DST}"
systemctl daemon-reload
systemctl enable unilidar-web.service
systemctl restart unilidar-web.service

echo "Installed ${SERVICE_DST}"
echo "Service user: ${SERVICE_USER}"
echo "Working directory: ${REPO_ROOT}"
echo "Enabled and started unilidar-web.service"
echo "Check status with: systemctl status unilidar-web.service"
echo "Follow logs with: journalctl -u unilidar-web.service -f"
