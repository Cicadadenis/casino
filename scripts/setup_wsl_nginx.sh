#!/usr/bin/env bash
# NOTE: This file must use LF line endings in WSL/Linux.
set -euo pipefail

# Usage inside WSL:
# bash scripts/setup_wsl_nginx.sh ~/crypto-auth-site localhost

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${1:-$PROJECT_DIR}"
DOMAIN="${2:-localhost}"
SERVICE_NAME="crypto-auth-site-wsl"
NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
ENV_FILE="${APP_DIR}/.env"

check_systemd() {
  if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
    return 0
  fi

  echo
  echo "ERROR: systemd is not enabled in this WSL distro."
  echo "Enable it first, then rerun this script:"
  echo
  echo "1) Edit /etc/wsl.conf and add:"
  echo "   [boot]"
  echo "   systemd=true"
  echo
  echo "2) From Windows PowerShell run:"
  echo "   wsl --shutdown"
  echo
  echo "3) Start WSL again and rerun:"
  echo "   ./scripts/setup_wsl_nginx.sh ${APP_DIR} ${DOMAIN}"
  echo
  exit 1
}

generate_secret_key() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
  fi
}

upsert_env_var() {
  local key="$1"
  local value="$2"
  if [ -f "$ENV_FILE" ] && grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx dos2unix
check_systemd

if [ ! -f "${APP_DIR}/app.py" ]; then
  echo "Project not found in ${APP_DIR}"
  exit 1
fi

cd "$APP_DIR"
if [ ! -f "$ENV_FILE" ]; then
  touch "$ENV_FILE"
fi

echo
echo "=== CryptoBot configuration ==="
echo "Enter CRYPTOBOT_TOKEN (input hidden). Leave empty to skip for now."
read -r -s -p "CRYPTOBOT_TOKEN: " CRYPTOBOT_TOKEN
echo

SECRET_KEY="$(generate_secret_key)"
upsert_env_var "SECRET_KEY" "$SECRET_KEY"
if [ -n "${CRYPTOBOT_TOKEN}" ]; then
  upsert_env_var "CRYPTOBOT_TOKEN" "$CRYPTOBOT_TOKEN"
else
  if ! grep -q '^CRYPTOBOT_TOKEN=' "$ENV_FILE"; then
    upsert_env_var "CRYPTOBOT_TOKEN" ""
  fi
fi
upsert_env_var "CRYPTOBOT_API_URL" "https://pay.crypt.bot/api"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt gunicorn
python3 scripts/init_db.py

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=Crypto Auth Site (WSL)
After=network.target

[Service]
User=${USER}
Group=${USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/.venv/bin"
ExecStart=${APP_DIR}/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 "app:create_app()"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee "$NGINX_CONF" >/dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /static {
        alias ${APP_DIR}/static;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

sudo ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sudo nginx -t
sudo systemctl restart nginx

echo
echo "Done for WSL."
echo "Env file: ${ENV_FILE}"
if [ -n "${CRYPTOBOT_TOKEN}" ]; then
  echo "CRYPTOBOT_TOKEN saved."
else
  echo "CRYPTOBOT_TOKEN not provided (you can add it later to ${ENV_FILE})."
fi
echo "Open: http://${DOMAIN}"
