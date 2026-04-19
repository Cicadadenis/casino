#!/usr/bin/env bash
set -euo pipefail

# Usage:
# sudo bash scripts/setup_vps_nginx.sh /opt/crypto-auth-site your-domain.com

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${1:-$PROJECT_DIR}"
DOMAIN="${2:-}"

sanitize_domain() {
  local d="$1"
  d="${d#http://}"
  d="${d#https://}"
  d="${d%%/*}"
  d="${d%%:}"
  echo "$d"
}
# --- Запрос домена, если не передан ---
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "_" ]; then
  read -rp "Введите домен (например, example.com): " DOMAIN
  if [ -z "$DOMAIN" ]; then
    echo "Домен обязателен!"; exit 1
  fi
fi
DOMAIN="$(sanitize_domain "$DOMAIN")"
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
pip install -r requirements.txt gunicorn --break-system-packages


# --- Права на файлы сайта ---
chown -R www-data:www-data "$APP_DIR"
find "$APP_DIR" -type d -exec chmod 750 {} \;
find "$APP_DIR" -type f -exec chmod 640 {} \;

if [ -f "scripts/init_db.py" ]; then
  python3 scripts/init_db.py
else
  echo "Warning: scripts/init_db.py not found, skipping database initialization"
fi

# --- Auto-detect best service configuration ---
test_service_config() {
  local test_cmd="$1"
  local config_name="$2"
  
  echo "Testing ${config_name}..."
  cd "$APP_DIR"
  source .venv/bin/activate
  
  if timeout 5 bash -c "$test_cmd" 2>/dev/null; then
    echo "SUCCESS: ${config_name} works!"
    return 0
  else
    echo "FAILED: ${config_name}"
    return 1
  fi
}

# Try different configurations
SERVICE_CONFIG=""
if test_service_config "${APP_DIR}/.venv/bin/python -m gunicorn -w 1 -b 127.0.0.1:8000 app:app --check-config" "gunicorn app:app"; then
  SERVICE_CONFIG="ExecStart=${APP_DIR}/.venv/bin/python -m gunicorn -w 2 -b 127.0.0.1:8000 app:app"
elif test_service_config "${APP_DIR}/.venv/bin/python -c 'import app; print(\"OK\")'" "import app"; then
  # Check if app has Flask app object
  if test_service_config "${APP_DIR}/.venv/bin/python -c 'import app; print(hasattr(app, \"app\"))'" "app has app object"; then
    SERVICE_CONFIG="ExecStart=${APP_DIR}/.venv/bin/python -m gunicorn -w 2 -b 127.0.0.1:8000 app:app"
  else
    # Create a wrapper for gunicorn
    cat > "${APP_DIR}/gunicorn_wrapper.py" <<PY
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import app

# Try to find the Flask app
flask_app = None
if hasattr(app, 'app'):
    flask_app = app.app
elif hasattr(app, 'create_app'):
    flask_app = app.create_app()
else:
    # Try common patterns
    for attr in ['application', 'wsgi_app']:
        if hasattr(app, attr):
            flask_app = getattr(app, attr)
            break
    # Try to get any callable object
    if flask_app is None:
        for name in dir(app):
            obj = getattr(app, name)
            if hasattr(obj, '__call__') and not name.startswith('_'):
                flask_app = obj
                break

if flask_app is None:
    print("ERROR: Could not find Flask app object")
    print("Available attributes:", [name for name in dir(app) if not name.startswith('_')])
    sys.exit(1)

print("Found Flask app:", type(flask_app))
PY
    SERVICE_CONFIG="ExecStart=${APP_DIR}/.venv/bin/python -m gunicorn -w 2 -b 127.0.0.1:8000 gunicorn_wrapper:flask_app"
  fi
elif test_service_config "${APP_DIR}/.venv/bin/python app.py" "direct python app.py"; then
  SERVICE_CONFIG="ExecStart=${APP_DIR}/.venv/bin/python app.py"
elif test_service_config "${APP_DIR}/.venv/bin/python -c 'from app import create_app; create_app()'" "app factory"; then
  SERVICE_CONFIG="ExecStart=${APP_DIR}/.venv/bin/python -m gunicorn -w 2 -b 127.0.0.1:8000 \"app:create_app()\""
else
  echo "WARNING: Could not determine correct service config, using default"
  SERVICE_CONFIG="ExecStart=${APP_DIR}/.venv/bin/python -m gunicorn -w 2 -b 127.0.0.1:8000 app:app"
fi

echo "Using service config: ${SERVICE_CONFIG}"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Crypto Auth Site
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/.venv/bin"
${SERVICE_CONFIG}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF



# --- Nginx конфиг только для 80 порта (без SSL) ---
cat > "$NGINX_CONF" <<EOF
server {
  listen 80;
  server_name ${DOMAIN};
  location /.well-known/acme-challenge/ {
    root /var/www/html;
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


# Force stop and restart with new configuration
systemctl stop "${SERVICE_NAME}" || true
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}"


nginx -t && systemctl restart nginx

# --- Установка certbot и получение сертификата ---
if ! command -v certbot >/dev/null 2>&1; then
  echo "Устанавливаю certbot..."
  apt install -y certbot python3-certbot-nginx
fi

echo "Получаю SSL-сертификат для ${DOMAIN}..."
certbot certonly --webroot -w /var/www/html --non-interactive --agree-tos -d "$DOMAIN" -m "admin@${DOMAIN}" --staging || {
  echo "Ошибка получения сертификата! Пробую без staging..."
  certbot certonly --webroot -w /var/www/html --non-interactive --agree-tos -d "$DOMAIN" -m "admin@${DOMAIN}" || {
    echo "Ошибка получения сертификата! Проверьте DNS и доступность домена."; exit 1;
  }
}

# --- Теперь обновляем nginx-конфиг для 80+443 (SSL) ---
cat > "$NGINX_CONF" <<EOF
server {
  listen 80;
  server_name ${DOMAIN};
  location /.well-known/acme-challenge/ {
    root /var/www/html;
  }
  location / {
    return 301 https://\$host\$request_uri;
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
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }
}
EOF

nginx -t && systemctl restart nginx

echo
echo "Готово! Сервис: ${SERVICE_NAME}, домен: ${DOMAIN}"
echo "Env file: ${ENV_FILE}"
if [ -n "${CRYPTOBOT_TOKEN}" ]; then
  echo "CRYPTOBOT_TOKEN сохранён."
else
  echo "CRYPTOBOT_TOKEN не указан (можно добавить позже в ${ENV_FILE})."
fi
echo "Откройте: https://${DOMAIN}"

# --- Диагностика статуса и логов сервиса ---
echo
echo "==== STATUS systemd-сервиса ===="
systemctl status --no-pager "${SERVICE_NAME}"
echo
echo "==== Последние 30 строк лога (journalctl) ===="
journalctl -u "${SERVICE_NAME}" -n 30 --no-pager
