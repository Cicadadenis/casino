#!/usr/bin/env bash
set -euo pipefail

# Usage:
# sudo bash scripts/setup_vps_nginx.sh /opt/crypto-auth-site your-domain.com

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${1:-$PROJECT_DIR}"
DOMAIN="${2:-}"

# --- Запрос домена, если не передан ---
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "_" ]; then
  read -rp "Введите домен (например, example.com): " DOMAIN
  if [ -z "$DOMAIN" ]; then
    echo "Домен обязателен!"; exit 1
  fi
fi
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

if grep -q '^CRYPTOBOT_TOKEN=' "$ENV_FILE"; then
  CRYPTOBOT_TOKEN=$(grep '^CRYPTOBOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
else
  echo
  echo "Введите CRYPTOBOT_TOKEN (скрытый ввод, можно оставить пустым):"
  read -r -s -p "CRYPTOBOT_TOKEN: " CRYPTOBOT_TOKEN
  echo
fi

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


# --- Nginx конфиг для 80 порта (редирект на https) и 443 (SSL) ---
cat > "$NGINX_CONF" <<EOF
server {
  listen 80;
  server_name ${DOMAIN};
  location /.well-known/acme-challenge/ {
    root /var/www/html;
  }
  location / {
    return 301 https://$host$request_uri;
  }
}

server {
  listen 443 ssl;
  server_name ${DOMAIN};

  ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_ciphers HIGH:!aNULL:!MD5;

  location /static {
    alias ${APP_DIR}/static;
  }

  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
EOF

ln -sf "$NGINX_CONF" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
rm -f /etc/nginx/sites-enabled/default


systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

nginx -t && systemctl restart nginx

# --- Установка certbot и получение сертификата ---
if ! command -v certbot >/dev/null 2>&1; then
  echo "Устанавливаю certbot..."
  apt install -y certbot python3-certbot-nginx
fi

echo "Получаю SSL-сертификат для ${DOMAIN}..."
certbot --nginx --non-interactive --agree-tos --redirect -d "$DOMAIN" -m "admin@${DOMAIN}" || {
  echo "Ошибка получения сертификата! Проверьте DNS и доступность домена."; exit 1;
}

systemctl restart nginx

echo
echo "Готово! Сервис: ${SERVICE_NAME}, домен: ${DOMAIN}"
echo "Env file: ${ENV_FILE}"
if [ -n "${CRYPTOBOT_TOKEN}" ]; then
  echo "CRYPTOBOT_TOKEN сохранён."
else
  echo "CRYPTOBOT_TOKEN не указан (можно добавить позже в ${ENV_FILE})."
fi
echo "Откройте: https://${DOMAIN}"
