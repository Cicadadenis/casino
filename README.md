# Crypto Auth Site

Готовый мини-сайт на Flask:
- регистрация и вход;
- при регистрации +1000 бонусных монет;
- личный кабинет с основным и бонусным балансом;
- пополнение через CryptoBot (создание invoice);
- вывод через CryptoBot (заявка на вывод);
- перевод с бонусного на основной счет доступен только если бонусный баланс больше 10000.

## 1) Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts/init_db.py
python app.py
```

Открой `http://127.0.0.1:8000`.

## 2) Настройка CryptoBot

В `.env` укажи:
- `CRYPTOBOT_TOKEN` — токен API CryptoBot.
- `CRYPTOBOT_API_URL` — обычно `https://pay.crypt.bot/api`.

Webhook endpoint:
- `POST /cryptobot/webhook`

Для продакшена стоит добавить проверку подписи webhook от CryptoBot.

## 3) Скрипт для VPS (Ubuntu + Nginx + systemd)

1. Скопируй проект на VPS, например в `/opt/crypto-auth-site`.
2. Запусти:

```bash
sudo bash scripts/setup_vps_nginx.sh /opt/crypto-auth-site your-domain.com
```

## 4) Скрипт для WSL (Ubuntu + Nginx + systemd)

```bash
bash scripts/setup_wsl_nginx.sh ~/crypto-auth-site localhost
```

## 5) База данных

Создается скриптом:

```bash
python scripts/init_db.py
```

Файл БД: `database.sqlite3`.
