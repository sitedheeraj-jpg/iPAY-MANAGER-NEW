#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/agent-member-bot}"
SERVICE_NAME="agent-member-bot"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root: sudo bash deploy/vps/install.sh"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.11+ using your distribution package manager."
  exit 1
fi

install -d -m 0755 "${APP_DIR}"
if [[ "$(realpath "${BASH_SOURCE[0]}")" != "${APP_DIR}/deploy/vps/install.sh" ]]; then
  echo "Copy the project to ${APP_DIR} first, then run this script from the project root."
fi

if ! id -u agentbot >/dev/null 2>&1; then
  useradd --system --home-dir "${APP_DIR}" --shell /usr/sbin/nologin agentbot
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  chmod 600 "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env. Edit it with your secrets before starting the service."
fi

chown -R agentbot:agentbot "${APP_DIR}"
install -m 0644 "${APP_DIR}/deploy/vps/agent-member-bot.service" \
  "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo
echo "VPS installation is ready."
echo "1. Edit ${APP_DIR}/.env"
echo "2. Start with: systemctl start ${SERVICE_NAME}"
echo "3. Check logs with: journalctl -u ${SERVICE_NAME} -f"