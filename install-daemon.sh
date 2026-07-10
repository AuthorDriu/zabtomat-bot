#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="zabtomat-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
APP_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"

if [[ "${APP_DIR}" == *" "* ]]; then
    echo "Ошибка: путь к проекту содержит пробелы, systemd unit для такого пути этот простой установщик не создаёт: ${APP_DIR}" >&2
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    exec sudo bash "${SCRIPT_PATH}" "$@"
fi

APP_USER="${SUDO_USER:-$(id -un)}"
APP_GROUP="$(id -gn "${APP_USER}")"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Ошибка: не найден ${PYTHON_BIN}" >&2
    echo "Сначала выполните установку зависимостей из README: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
    exit 1
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
    echo "Ошибка: не найден ${APP_DIR}/.env" >&2
    echo "Создайте .env из .env.example и заполните настройки перед запуском демона." >&2
    exit 1
fi

mapfile -t RUNTIME_PATHS < <("${PYTHON_BIN}" - "${APP_DIR}" <<'PY'
import sys
from pathlib import Path

from dotenv import dotenv_values

app_dir = Path(sys.argv[1])
env = dotenv_values(app_dir / ".env")

log_dir = Path(env.get("LOG_DIR") or "./logs")
database_path = Path(env.get("DATABASE_PATH") or "./database/database.sqlite3")

if not log_dir.is_absolute():
    log_dir = app_dir / log_dir
if not database_path.is_absolute():
    database_path = app_dir / database_path

print(log_dir.resolve())
print(database_path.parent.resolve())
print((log_dir.parent / "logs.zip").resolve())
PY
)

LOG_DIR_PATH="${RUNTIME_PATHS[0]}"
DATABASE_DIR_PATH="${RUNTIME_PATHS[1]}"
LOG_ARCHIVE_PATH="${RUNTIME_PATHS[2]}"

mkdir -p "${LOG_DIR_PATH}" "${DATABASE_DIR_PATH}"
touch "${LOG_ARCHIVE_PATH}"
chown -R "${APP_USER}:${APP_GROUP}" "${LOG_DIR_PATH}" "${DATABASE_DIR_PATH}"
chown "${APP_USER}:${APP_GROUP}" "${LOG_ARCHIVE_PATH}"

cat > "${SERVICE_FILE}" <<SERVICE
[Unit]
Description=Zabbix Matrix Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PYTHON_BIN} ${APP_DIR}/run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"

echo "Сервис установлен и запущен: ${SERVICE_NAME}.service"
echo "Статус: sudo systemctl status ${SERVICE_NAME}"
echo "Логи:   sudo journalctl -u ${SERVICE_NAME} -f"
