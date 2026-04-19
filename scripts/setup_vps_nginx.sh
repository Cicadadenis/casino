#!/usr/bin/env bash
set -euo pipefail

# Usage:
# sudo bash scripts/setup_vps_nginx.sh /opt/crypto-auth-site your-domain.com

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${1:-$PROJECT_DIR}"
DOMAIN="${2:-_}"
SERVICE_NAME="crypto-auth-site"
NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
ENV_FILE="${APP_DIR}/.env"

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

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo bash scripts/setup_vps_nginx.sh ${APP_DIR} ${DOMAIN}"
  exit 1
fi

apt update
apt install -y python3 python3-venv python3-pip nginx

mkdir -p "$APP_DIR"
if [ ! -f "${APP_DIR}/app.py" ]; then
  echo "Copy project files to ${APP_DIR} first."
  exit 1
fi

cd "$APP_DIR"
if [ ! -f "$ENV_FILE" ]; then
  touch "$ENV_FILE"
fi

echo
echo "=== CryptoBot configuration (VPS) ==="
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

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Crypto Auth Site
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/.venv/bin"
ExecStart=${APP_DIR}/.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 "app:create_app()"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > "$NGINX_CONF" <<EOF
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

ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
nginx -t
systemctl restart nginx

echo
echo "Done. Service: ${SERVICE_NAME}, domain: ${DOMAIN}"
echo "Env file: ${ENV_FILE}"
if [ -n "${CRYPTOBOT_TOKEN}" ]; then
  echo "CRYPTOBOT_TOKEN saved."
else
  echo "CRYPTOBOT_TOKEN not provided (you can add it later to ${ENV_FILE})."
fi
echo "Open: http://${DOMAIN}"
