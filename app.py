import os
import random
import secrets
import jwt
import datetime
import sqlite3
import json
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.sqlite3")
LOCAL_PAGES_DIR = os.path.join(BASE_DIR, "external_pages")
load_dotenv(os.path.join(BASE_DIR, ".env"))

BONUS_ON_REGISTER = 1000
BONUS_TRANSFER_THRESHOLD = 10000
DEFAULT_LINES = 5
MAX_LINES = 9
MAX_BET_PER_LINE = 100
SLOT_SYMBOLS = [
    {"id": "seven", "em": "7️⃣", "mult": [0, 0, 8, 20, 45], "weight": 3},
    {"id": "diamond", "em": "💎", "mult": [0, 0, 6, 16, 35], "weight": 4},
    {"id": "star", "em": "⭐", "mult": [0, 0, 5, 12, 28], "weight": 6},
    {"id": "bell", "em": "🔔", "mult": [0, 0, 4, 10, 24], "weight": 7},
    {"id": "cherry", "em": "🍒", "mult": [0, 0, 3, 8, 18], "weight": 10},
    {"id": "lemon", "em": "🍋", "mult": [0, 0, 2, 6, 14], "weight": 12},
]
SLOT_PAYLINES = [
    [1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0],
    [2, 2, 2, 2, 2],
    [0, 1, 2, 1, 0],
    [2, 1, 0, 1, 2],
    [0, 0, 1, 2, 2],
    [2, 2, 1, 0, 0],
    [0, 1, 1, 1, 2],
    [2, 1, 1, 1, 0],
]
EXTERNAL_PAGES = {
    "gnome": {
        "filename": "gnome_redesign.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\gnome_redesign.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/gnome_redesign.html",
    },
    "book-of-ra": {
        "filename": "book-of-ra-redesign.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\book-of-ra-redesign.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/book-of-ra-redesign.html",
    },
    "resident": {
        "filename": "resident.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\resident.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/resident.html",
    },
    "garage": {
        "filename": "garage.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\garage (2).html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/garage (2).html",
    },
    "admin-panel": {
        "filename": "admin.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\admin.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/admin.html",
    },
    "fruit-cocktail": {
        "filename": "fruit-cocktail.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\fruit-cocktail.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/fruit-cocktail.html",
    },
    "crazy-monkey": {
        "filename": "crazy-monkey.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\crazy-monkey.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/crazy-monkey.html",
    },
    "island": {
        "filename": "island.html",
        "windows_path": r"c:\Users\denis\Downloads\Telegram Desktop\island.html",
        "wsl_path": "/mnt/c/Users/denis/Downloads/Telegram Desktop/island.html",
    },
}


def create_app():

    ADMIN_JWT_SECRET = os.getenv("ADMIN_JWT_SECRET", "supersecretjwtkey")
    ADMIN_JWT_ALG = "HS256"

    def resolve_external_page_path(game_key):
        meta = EXTERNAL_PAGES.get(game_key)
        if not meta:
            return None

        local_path = os.path.join(LOCAL_PAGES_DIR, meta["filename"])
        if os.path.exists(local_path):
            return local_path

        source_candidates = [meta["windows_path"], meta["wsl_path"]]
        for source_path in source_candidates:
            if source_path and os.path.exists(source_path):
                os.makedirs(LOCAL_PAGES_DIR, exist_ok=True)
                with open(source_path, "rb") as src, open(local_path, "wb") as dst:
                    dst.write(src.read())
                return local_path

        if os.path.exists(local_path):
            return local_path
        return None

    def resolve_landing_page_path():
        local_name = "index-11.html"
        local_path = os.path.join(LOCAL_PAGES_DIR, local_name)
        if os.path.exists(local_path):
            return local_path

        candidates = [
            r"c:\Users\denis\Downloads\Telegram Desktop\index (11).html",
            "/mnt/c/Users/denis/Downloads/Telegram Desktop/index (11).html",
        ]
        for source_path in candidates:
            if source_path and os.path.exists(source_path):
                os.makedirs(LOCAL_PAGES_DIR, exist_ok=True)
                with open(source_path, "rb") as src, open(local_path, "wb") as dst:
                    dst.write(src.read())
                return local_path

        if os.path.exists(local_path):
            return local_path
        return None

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", secrets.token_hex(24))
    app.config["CRYPTOBOT_TOKEN"] = os.getenv("CRYPTOBOT_TOKEN", "")
    app.config["CRYPTOBOT_API_URL"] = os.getenv("CRYPTOBOT_API_URL", "https://pay.crypt.bot/api")

    @app.before_request
    def before_request():
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row

    @app.teardown_request
    def teardown_request(_exception):
        db = getattr(g, "db", None)
        if db is not None:
            db.close()

    def login_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            # Сессия Flask
            if "user_id" in session:
                return view(*args, **kwargs)
            # JWT Bearer токен
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
                try:
                    payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ADMIN_JWT_ALG])
                    session["user_id"] = payload["uid"]
                    return view(*args, **kwargs)
                except Exception:
                    pass
            return jsonify({"ok": False, "what": "Unauthorized"}), 401

        return wrapped_view

    def current_user():
        # Сессия Flask
        if "user_id" in session:
            return g.db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        # JWT Bearer токен
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            try:
                payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ADMIN_JWT_ALG])
                return g.db.execute("SELECT * FROM users WHERE id = ?", (payload["uid"],)).fetchone()
            except Exception:
                pass
        return None

    def add_transaction(user_id, tx_type, amount, status, note=""):
        g.db.execute(
            """
            INSERT INTO transactions (user_id, tx_type, amount, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, tx_type, amount, status, note, datetime.utcnow().isoformat()),
        )
        g.db.commit()

    def weighted_symbol():
        pool = []
        for sym in SLOT_SYMBOLS:
            pool.extend([sym] * sym["weight"])
        return random.choice(pool)

    def spin_grid():
        grid = []
        for col in range(5):
            column = []
            for row in range(3):
                column.append(weighted_symbol())
            grid.append(column)
        return grid

    def evaluate_grid(grid, bet_per_line, lines):
        total_win = 0.0
        win_lines = []
        for idx, line in enumerate(SLOT_PAYLINES[: lines]):
            first = grid[0][line[0]]
            count = 1
            for col in range(1, 5):
                sym = grid[col][line[col]]
                if sym["id"] == first["id"]:
                    count += 1
                else:
                    break
            if count >= 3:
                line_win = bet_per_line * first["mult"][count - 1]
                total_win += line_win
                win_lines.append({"line": idx + 1, "symbol": first["em"], "count": count, "win": line_win})
        return round(total_win, 2), win_lines

    def cryptobot_create_invoice(amount, asset="USDT"):
        import requests as req_lib
        token = os.getenv("CRYPTOBOT_TOKEN")
        api_url = os.getenv("CRYPTOBOT_API_URL", "https://pay.crypt.bot/api")

        if not token:
            return {"ok": False, "error": "CRYPTOBOT_TOKEN не задан"}

        try:
            resp = req_lib.post(
                f"{api_url}/createInvoice",
                headers={
                    "Crypto-Pay-API-Token": token,
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0"
                },
                json={
                    "asset": asset,
                    "amount": str(round(amount, 6)),
                    "description": "Пополнение баланса"
                },
                timeout=15
            )
            return resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_uah_rates():
        req = Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=tether,tron,litecoin&vs_currencies=uah",
            method="GET",
        )
        with urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {
            "USDT": float(data["tether"]["uah"]),
            "TRX": float(data["tron"]["uah"]),
            "LTC": float(data["litecoin"]["uah"]),
        }

    @app.route("/")
    def index():
        project_landing = os.path.join(LOCAL_PAGES_DIR, "index-11.html")
        if os.path.exists(project_landing):
            return send_file(project_landing)
        landing_path = resolve_landing_page_path()
        if landing_path:
            return send_file(landing_path)
        user = current_user()
        return render_template("index.html", user=user)

    @app.route("/games")
    def games_menu():
        return render_template("games.html", user=current_user())

    @app.route("/casino")
    @login_required
    def casino():
        user = current_user()
        return render_template("casino.html", user=user, default_lines=DEFAULT_LINES)

    @app.route("/admin")
    def admin_menu():
        return render_template("admin_menu.html", user=current_user())

    @app.route("/play/<game_key>")
    def play_game(game_key):
        path = resolve_external_page_path(game_key)
        if not path:
            abort(404)
        return send_file(path)

    @app.route("/admin-panel")
    def admin_panel():
        path = resolve_external_page_path("admin-panel")
        if not path:
            abort(404)
        return send_file(path)

    def admin_api_required(view):
        @wraps(view)

        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "", 1).strip() if auth.startswith("Bearer ") else ""
            if not token:
                return jsonify({"what": "Unauthorized"}), 401
            try:
                payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=[ADMIN_JWT_ALG])
                if payload.get("role") == "admin":
                    g.api_is_admin = True
                    return view(*args, **kwargs)
                elif payload.get("role") == "user":
                    g.api_user_id = int(payload.get("uid", 0))
                    g.api_is_admin = False
                    return view(*args, **kwargs)
            except Exception:
                return jsonify({"what": "Unauthorized"}), 401
            return jsonify({"what": "Unauthorized"}), 401

        return wrapped

    @app.route("/signin", methods=["POST"])
    def admin_signin():
        payload = request.get_json(silent=True) or {}
        email = payload.get("email", "").strip().lower()
        secret = payload.get("secret", "")
        expected_email = os.getenv("ADMIN_EMAIL", "satanasat3301@gmail.com").strip().lower()
        expected_password = os.getenv("ADMIN_PASSWORD", "cicada3301")
        if email == expected_email and secret == expected_password:
            payload = {
                "role": "admin",
                "email": email,
                "exp": int((datetime.utcnow() + timedelta(days=7)).timestamp())
            }
            token = jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=ADMIN_JWT_ALG)
            return jsonify({"access": token})

        user = g.db.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], secret):
            return jsonify({"what": "Неверные учетные данные"}), 401
        # JWT для обычного пользователя
        payload = {
            "role": "user",
            "uid": int(user["id"]),
            "email": user["username"],
            "exp": int((datetime.utcnow() + timedelta(days=7)).timestamp())
        }
        token = jwt.encode(payload, ADMIN_JWT_SECRET, algorithm=ADMIN_JWT_ALG)
        return jsonify(
            {
                "access": token,
                "uid": int(user["id"]),
                "email": user["username"],
                "name": user["username"].split("@")[0],
            }
        )

    @app.route("/signup", methods=["POST"])
    def api_signup():
        payload = request.get_json(silent=True) or {}
        email = payload.get("email", "").strip().lower()
        secret = payload.get("secret", "")
        name = payload.get("name", "").strip()
        if not email or "@" not in email:
            return jsonify({"what": "Некорректный email"}), 400
        if len(secret) < 6:
            return jsonify({"what": "Пароль минимум 6 символов"}), 400
        exists = g.db.execute("SELECT id FROM users WHERE username = ?", (email,)).fetchone()
        if exists:
            return jsonify({"what": "Пользователь уже существует"}), 409
        g.db.execute(
            """
            INSERT INTO users (username, password_hash, bonus_balance, main_balance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (email, generate_password_hash(secret), BONUS_ON_REGISTER, 0.0, datetime.utcnow().isoformat()),
        )
        g.db.commit()
        user = g.db.execute("SELECT id FROM users WHERE username = ?", (email,)).fetchone()
        add_transaction(int(user["id"]), "register_bonus", BONUS_ON_REGISTER, "done", "Бонус при регистрации")
        return jsonify({"ok": True, "uid": int(user["id"]), "name": name or email.split("@")[0]})

    @app.route("/bonus/add", methods=["POST"])
    def api_bonus_add():
        payload = request.get_json(silent=True) or {}
        try:
            uid = int(payload.get("uid", 0))
        except (TypeError, ValueError):
            return jsonify({"what": "Некорректный uid"}), 400
        user = g.db.execute("SELECT id, main_balance, bonus_balance FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            return jsonify({"what": "Пользователь не найден"}), 404
        # Бонус уже начисляется в /signup, endpoint оставляем для совместимости фронта.
        return jsonify({"ok": True, "bonus_balance": float(user["bonus_balance"])})

    @app.route("/user/is", methods=["POST"])
    @admin_api_required
    def admin_user_is():
        if not getattr(g, "api_is_admin", False):
            return jsonify({"what": "Forbidden"}), 403
        payload = request.get_json(silent=True) or {}
        req_list = payload.get("list", [])
        out = []
        for item in req_list:
            try:
                uid = int((item or {}).get("uid", 0))
            except (TypeError, ValueError):
                continue
            user = g.db.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()
            if user:
                out.append({"uid": int(user["id"]), "name": user["username"], "email": f"{user['username']}@local"})
        return jsonify({"list": out})

    @app.route("/prop/wallet/get", methods=["POST"])
    @admin_api_required
    def admin_wallet_get():
        payload = request.get_json(silent=True) or {}
        try:
            uid = int(payload.get("uid") or getattr(g, "api_user_id", 0))
            cid = int(payload.get("cid", 0))
        except (TypeError, ValueError):
            return jsonify({"what": "Некорректные параметры"}), 400
        if not getattr(g, "api_is_admin", False) and uid != int(getattr(g, "api_user_id", 0)):
            return jsonify({"what": "Forbidden"}), 403
        user = g.db.execute("SELECT main_balance, bonus_balance FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            return jsonify({"what": "Пользователь не найден"}), 404
        if cid == 2:
            wallet = float(user["main_balance"])
        elif cid == 1:
            wallet = float(user["bonus_balance"])
        else:
            wallet = 0.0
        return jsonify({"wallet": wallet})

    @app.route("/prop/wallet/add", methods=["POST"])
    @admin_api_required
    def admin_wallet_add():
        payload = request.get_json(silent=True) or {}
        try:
            uid = int(payload.get("uid") or getattr(g, "api_user_id", 0))
            cid = int(payload.get("cid", 0))
            amount = float(payload.get("sum", 0))
        except (TypeError, ValueError):
            return jsonify({"what": "Некорректные параметры"}), 400
        if not getattr(g, "api_is_admin", False) and uid != int(getattr(g, "api_user_id", 0)):
            return jsonify({"what": "Forbidden"}), 403
        if amount == 0:
            return jsonify({"what": "Сумма должна быть больше нуля"}), 400
        user = g.db.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            return jsonify({"what": "Пользователь не найден"}), 404

        if cid == 2:
            g.db.execute("UPDATE users SET main_balance = main_balance + ? WHERE id = ?", (amount, uid))
            add_transaction(uid, "admin_add_main", amount, "done", "Выдача монет админом")
        elif cid == 1:
            g.db.execute("UPDATE users SET bonus_balance = bonus_balance + ? WHERE id = ?", (amount, uid))
            add_transaction(uid, "admin_add_bonus", amount, "done", "Выдача бонусов админом")
        else:
            return jsonify({"what": "Неизвестный cid"}), 400
        g.db.commit()
        return jsonify({"ok": True})

    @app.route("/prop/wallet/set", methods=["POST"])
    @admin_api_required
    def admin_wallet_set():
        payload = request.get_json(silent=True) or {}
        try:
            uid = int(payload.get("uid") or getattr(g, "api_user_id", 0))
            main_balance = float(payload.get("main_balance", 0))
            bonus_balance = float(payload.get("bonus_balance", 0))
        except (TypeError, ValueError):
            return jsonify({"what": "Incorrect parameters"}), 400
        if not getattr(g, "api_is_admin", False):
            return jsonify({"what": "Forbidden"}), 403
        
        user = g.db.execute("SELECT id, main_balance, bonus_balance FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            return jsonify({"what": "User not found"}), 404

        old_main = float(user["main_balance"])
        old_bonus = float(user["bonus_balance"])
        
        # Update balances
        g.db.execute("UPDATE users SET main_balance = ?, bonus_balance = ? WHERE id = ?", (main_balance, bonus_balance, uid))
        
        # Record transactions for changes
        main_delta = main_balance - old_main
        bonus_delta = bonus_balance - old_bonus
        
        if main_delta != 0:
            tx_type = "admin_edit_main" if main_delta > 0 else "admin_edit_main_remove"
            add_transaction(uid, tx_type, abs(main_delta), "done", f"Editing main balance: {old_main} -> {main_balance}")
        
        if bonus_delta != 0:
            tx_type = "admin_edit_bonus" if bonus_delta > 0 else "admin_edit_bonus_remove"
            add_transaction(uid, tx_type, abs(bonus_delta), "done", f"Editing bonus balance: {old_bonus} -> {bonus_balance}")
        
        g.db.commit()
        return jsonify({"ok": True})

    @app.route("/user/delete", methods=["POST"])
    @admin_api_required
    def admin_user_delete():
        if not getattr(g, "api_is_admin", False):
            return jsonify({"what": "Forbidden"}), 403
        payload = request.get_json(silent=True) or {}
        try:
            uid = int(payload.get("uid", 0))
        except (TypeError, ValueError):
            return jsonify({"what": "Некорректный uid"}), 400
        user = g.db.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            return jsonify({"what": "Пользователь не найден"}), 404

        g.db.execute("DELETE FROM transactions WHERE user_id = ?", (uid,))
        g.db.execute("DELETE FROM crypto_invoices WHERE user_id = ?", (uid,))
        g.db.execute("DELETE FROM withdrawal_requests WHERE user_id = ?", (uid,))
        g.db.execute("DELETE FROM users WHERE id = ?", (uid,))
        g.db.commit()
        return jsonify({"ok": True})

    @app.route("/api/slot/spin", methods=["POST"])
    @login_required
    def api_slot_spin():
        payload = request.get_json(silent=True) or {}
        account = payload.get("account", "main")
        bet_per_line = float(payload.get("bet_per_line", 1))
        lines = int(payload.get("lines", DEFAULT_LINES))

        if account not in {"main", "bonus"}:
            return jsonify({"ok": False, "error": "Некорректный счет"}), 400
        if bet_per_line <= 0 or bet_per_line > MAX_BET_PER_LINE:
            return jsonify({"ok": False, "error": "Некорректная ставка"}), 400
        if lines < 1 or lines > MAX_LINES:
            return jsonify({"ok": False, "error": "Некорректное число линий"}), 400

        user = current_user()
        balance_field = "main_balance" if account == "main" else "bonus_balance"
        current_balance = float(user[balance_field])
        total_bet = round(bet_per_line * lines, 2)
        if total_bet > current_balance:
            return jsonify({"ok": False, "error": "Недостаточно средств"}), 400

        grid = spin_grid()
        total_win, win_lines = evaluate_grid(grid, bet_per_line, lines)
        new_balance = round(current_balance - total_bet + total_win, 2)

        g.db.execute(f"UPDATE users SET {balance_field} = ? WHERE id = ?", (new_balance, user["id"]))
        g.db.commit()
        add_transaction(user["id"], f"slot_bet_{account}", total_bet, "done", f"Ставка: {bet_per_line} x {lines}")
        if total_win > 0:
            add_transaction(user["id"], f"slot_win_{account}", total_win, "done", f"Выигрыш по {len(win_lines)} линиям")

        refreshed = current_user()
        return jsonify(
            {
                "ok": True,
                "grid": [[cell["em"] for cell in col] for col in grid],
                "total_bet": total_bet,
                "win": total_win,
                "win_lines": win_lines,
                "balances": {
                    "main": round(float(refreshed["main_balance"]), 2),
                    "bonus": round(float(refreshed["bonus_balance"]), 2),
                },
            }
        )

    @app.route("/api/me/balances")
    @login_required
    def api_me_balances():
        user = current_user()
        return jsonify(
            {
                "ok": True,
                "main_balance": round(float(user["main_balance"]), 2),
                "bonus_balance": round(float(user["bonus_balance"]), 2),
            }
        )

    @app.route("/api/me/set_balance", methods=["POST"])
    @login_required
    def api_me_set_balance():
        payload = request.get_json(silent=True) or {}
        account = payload.get("account", "main")
        balance = payload.get("balance")
        if account not in {"main", "bonus"}:
            return jsonify({"ok": False, "error": "Некорректный счет"}), 400
        try:
            balance = round(float(balance), 2)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Некорректный баланс"}), 400
        if balance < 0:
            return jsonify({"ok": False, "error": "Баланс не может быть отрицательным"}), 400

        user = current_user()
        field = "main_balance" if account == "main" else "bonus_balance"
        g.db.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (balance, user["id"]))
        g.db.commit()
        refreshed = current_user()
        return jsonify(
            {
                "ok": True,
                "main_balance": round(float(refreshed["main_balance"]), 2),
                "bonus_balance": round(float(refreshed["bonus_balance"]), 2),
            }
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if len(username) < 3 or len(password) < 6:
                flash("Логин минимум 3 символа, пароль минимум 6 символов", "error")
                return render_template("register.html")

            exists = g.db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if exists:
                flash("Пользователь уже существует", "error")
                return render_template("register.html")

            g.db.execute(
                """
                INSERT INTO users (username, password_hash, bonus_balance, main_balance, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, generate_password_hash(password), BONUS_ON_REGISTER, 0.0, datetime.utcnow().isoformat()),
            )
            g.db.commit()
            user_id = g.db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
            add_transaction(user_id, "register_bonus", BONUS_ON_REGISTER, "done", "Бонус при регистрации")

            flash(f"Регистрация успешна. Начислено {BONUS_ON_REGISTER} бонусных монет.", "success")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = g.db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

            if not user or not check_password_hash(user["password_hash"], password):
                flash("Неверный логин или пароль", "error")
                return render_template("login.html")

            session["user_id"] = user["id"]
            flash("Вход выполнен", "success")
            return redirect(url_for("cabinet"))

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Вы вышли из аккаунта", "success")
        return redirect(url_for("index"))

    @app.route("/cabinet")
    @login_required
    def cabinet():
        user = current_user()
        txs = g.db.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 30", (user["id"],)
        ).fetchall()
        return render_template(
            "cabinet.html",
            user=user,
            txs=txs,
            threshold=BONUS_TRANSFER_THRESHOLD,
        )

    @app.route("/transfer-bonus", methods=["POST"])
    @login_required
    def transfer_bonus():
        user = current_user()
        amount = float(request.form.get("amount", "0"))
        if amount <= 0:
            flash("Сумма должна быть больше 0", "error")
            return redirect(url_for("cabinet"))
        if user["bonus_balance"] <= BONUS_TRANSFER_THRESHOLD:
            flash(f"Перевод доступен только если бонусный счет больше {BONUS_TRANSFER_THRESHOLD}", "error")
            return redirect(url_for("cabinet"))
        if amount > user["bonus_balance"]:
            flash("Недостаточно бонусных средств", "error")
            return redirect(url_for("cabinet"))

        g.db.execute(
            """
            UPDATE users
            SET bonus_balance = bonus_balance - ?, main_balance = main_balance + ?
            WHERE id = ?
            """,
            (amount, amount, user["id"]),
        )
        g.db.commit()
        add_transaction(user["id"], "bonus_to_main", amount, "done", "Перевод с бонусного на основной")
        flash(f"Переведено {amount:.2f} с бонусного на основной", "success")
        return redirect(url_for("cabinet"))

    @app.route("/deposit", methods=["POST"])
    @login_required
    def deposit():
        user = current_user()
        amount_uah = float(request.form.get("amount_uah", "0"))
        asset = request.form.get("asset", "USDT").strip().upper()
        if amount_uah <= 0:
            flash("Введите корректную сумму в гривнах", "error")
            return redirect(url_for("cabinet"))
        if asset not in {"USDT", "TRX", "LTC"}:
            flash("Некорректная валюта", "error")
            return redirect(url_for("cabinet"))

        try:
            rates = get_uah_rates()
            rate_uah = rates[asset]
        except Exception:
            flash("Не удалось получить текущий курс валют", "error")
            return redirect(url_for("cabinet"))

        amount_asset = amount_uah / rate_uah
        decimals = 2 if asset == "USDT" else 4 if asset == "TRX" else 6
        amount_asset = round(amount_asset, decimals)
        if amount_asset <= 0:
            flash("Сумма слишком мала для выбранной валюты", "error")
            return redirect(url_for("cabinet"))

        result = cryptobot_create_invoice(amount_asset, asset=asset)
        if not result.get("ok"):
            add_transaction(
                user["id"],
                "deposit",
                amount_uah,
                "failed",
                f"Ошибка CryptoBot ({asset}): {result.get('error', 'crypto error')}",
            )
            flash(f"Не удалось создать счет в CryptoBot: {result.get('error', 'unknown error')}", "error")
            return redirect(url_for("cabinet"))

        invoice = result["result"]
        g.db.execute(
            """
            INSERT INTO crypto_invoices (user_id, invoice_id, amount, asset, pay_url, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                invoice.get("invoice_id"),
                amount_uah,
                invoice.get("asset", asset),
                invoice.get("pay_url", ""),
                "new",
                datetime.utcnow().isoformat(),
            ),
        )
        g.db.commit()
        add_transaction(
            user["id"],
            "deposit",
            amount_uah,
            "pending",
            f"Инвойс: {amount_asset} {asset} (~{amount_uah:.2f} грн)",
        )
        flash(f"Инвойс создан: {amount_asset} {asset} по текущему курсу (~{amount_uah:.2f} грн).", "success")
        return redirect(invoice.get("pay_url") or url_for("cabinet"))

    @app.route("/withdraw", methods=["POST"])
    @login_required
    def withdraw():
        user = current_user()
        amount = float(request.form.get("amount", "0"))
        wallet = request.form.get("wallet", "").strip()
        if amount <= 0 or not wallet:
            flash("Укажите корректную сумму и wallet", "error")
            return redirect(url_for("cabinet"))
        if amount > user["main_balance"]:
            flash("Недостаточно средств на основном счете", "error")
            return redirect(url_for("cabinet"))

        # Реальный вывод через CryptoBot transfer реализуется через API /transfer.
        # Здесь создаем заявку и сразу резервируем сумму для безопасности.
        g.db.execute("UPDATE users SET main_balance = main_balance - ? WHERE id = ?", (amount, user["id"]))
        g.db.execute(
            """
            INSERT INTO withdrawal_requests (user_id, amount, wallet, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], amount, wallet, "pending", datetime.utcnow().isoformat()),
        )
        g.db.commit()
        add_transaction(user["id"], "withdraw", amount, "pending", f"Заявка на вывод: {wallet}")
        flash("Заявка на вывод создана (pending)", "success")
        return redirect(url_for("cabinet"))

    @app.route("/cryptobot/webhook", methods=["POST"])
    def cryptobot_webhook():
        # Минимальный обработчик: подтверждаем пополнение по invoice_id.
        data = request.get_json(silent=True) or {}
        payload = data.get("payload", {})
        if payload.get("status") == "paid":
            invoice_id = payload.get("invoice_id")
            invoice = g.db.execute(
                "SELECT * FROM crypto_invoices WHERE invoice_id = ? AND status != 'paid'", (invoice_id,)
            ).fetchone()
            if invoice:
                g.db.execute(
                    "UPDATE users SET main_balance = main_balance + ? WHERE id = ?",
                    (invoice["amount"], invoice["user_id"]),
                )
                g.db.execute("UPDATE crypto_invoices SET status = 'paid' WHERE id = ?", (invoice["id"],))
                g.db.commit()
                add_transaction(invoice["user_id"], "deposit", invoice["amount"], "done", "Инвойс оплачен")
        return {"ok": True}

    @app.route("/transaction/list", methods=["GET"])
    @login_required
    def transaction_list():
        limit = int(request.args.get("limit", 20))
        user = current_user()
        txs = g.db.execute(
            "SELECT tx_type, amount, status, note, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user["id"], limit)
        ).fetchall()
        return jsonify([dict(tx) for tx in txs])

    @app.route("/cryptobot/invoice", methods=["POST"])
    @login_required
    def cryptobot_invoice():
        user = current_user()
        payload = request.get_json(silent=True) or {}
        try:
            coins = int(payload.get("coins", 0))
            cid = int(payload.get("cid", 0))
            asset = payload.get("asset", "USDT").strip().upper()
        except (TypeError, ValueError):
            return jsonify({"what": "Invalid parameters"}), 400
        
        if coins <= 0:
            return jsonify({"what": "Amount must be positive"}), 400
        if asset not in {"USDT", "TRX", "LTC"}:
            return jsonify({"what": "Unsupported asset"}), 400

        # Convert coins (UAH) to crypto amount using exchange rates
        amount_uah = float(coins)
        try:
            rates = get_uah_rates()
            rate_uah = rates[asset]
        except Exception:
            return jsonify({"what": "Failed to get exchange rates"}), 500

        amount_asset = amount_uah / rate_uah
        decimals = 2 if asset == "USDT" else 4 if asset == "TRX" else 6
        amount_asset = round(amount_asset, decimals)
        if amount_asset <= 0:
            return jsonify({"what": "Amount too small"}), 400

        # Create crypto invoice
        result = cryptobot_create_invoice(amount_asset, asset=asset)
        if not result.get("ok"):
            add_transaction(
                user["id"],
                "deposit",
                amount_uah,
                "failed",
                f"CryptoBot error ({asset}): {result.get('error', 'unknown')}",
            )
            return jsonify({"what": f"CryptoBot error: {result.get('error', 'unknown')}"}), 500

        # CryptoBot API returns {"ok": true, "result": {invoice_id, pay_url, ...}}
        invoice = result.get("result", result)
        g.db.execute(
            "INSERT INTO crypto_invoices (user_id, invoice_id, amount, asset, pay_url, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], invoice.get("invoice_id"), amount_uah, invoice.get("asset", asset), invoice.get("pay_url", ""), "new", datetime.utcnow().isoformat())
        )
        g.db.commit()
        add_transaction(
            user["id"],
            "deposit",
            amount_uah,
            "pending",
            f"Инвойс: {amount_asset} {asset} (~{amount_uah:.2f} грн)",
        )

        return jsonify({"ok": True, "pay_url": invoice.get("pay_url", ""), "invoice_id": invoice.get("invoice_id")})

    @app.route("/cryptobot/status", methods=["GET"])
    @login_required
    def cryptobot_status():
        import requests as req_lib
        invoice_id = request.args.get("invoice_id")
        cid = request.args.get("cid", 0)
        if not invoice_id:
            return jsonify({"ok": False, "what": "no invoice_id"}), 400

        token = os.getenv("CRYPTOBOT_TOKEN")
        api_url = os.getenv("CRYPTOBOT_API_URL", "https://pay.crypt.bot/api")

        try:
            resp = req_lib.get(
                f"{api_url}/getInvoices",
                headers={"Crypto-Pay-API-Token": token},
                params={"invoice_ids": invoice_id},
                timeout=10
            )
            data = resp.json()
        except Exception as e:
            return jsonify({"ok": False, "what": str(e)}), 500

        items = data.get("result", {}).get("items", [])
        if not items:
            return jsonify({"ok": False, "what": "invoice not found"}), 404

        invoice = items[0]
        status = invoice.get("status")

        if status == "paid":
            # Проверяем не зачислили ли уже
            user = current_user()
            row = g.db.execute(
                "SELECT * FROM crypto_invoices WHERE invoice_id = ? AND status != 'paid'",
                (invoice_id,)
            ).fetchone()
            if row:
                g.db.execute(
                    "UPDATE users SET main_balance = main_balance + ? WHERE id = ?",
                    (row["amount"], row["user_id"])
                )
                g.db.execute(
                    "UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?",
                    (invoice_id,)
                )
                g.db.commit()
                add_transaction(row["user_id"], "deposit", row["amount"], "done", "Инвойс оплачен")
            return jsonify({"ok": True, "status": "paid"})

        return jsonify({"ok": True, "status": status})

    @app.route("/cryptobot/withdraw", methods=["POST"])
    @login_required
    def cryptobot_withdraw():
        import requests as req_lib
        import time as _time
        user = current_user()
        payload = request.get_json(silent=True) or {}

        try:
            coins = int(payload.get("coins", 0))
            telegram_user_id = int(payload.get("telegram_user_id", 0))
            cid = int(payload.get("cid", 0))
        except (TypeError, ValueError):
            return jsonify({"what": "Неверные параметры"}), 400

        if coins < 1000:
            return jsonify({"what": "Минимум 1000 монет"}), 400

        if not telegram_user_id:
            return jsonify({"what": "Укажите Telegram User ID"}), 400

        balance = float(user["main_balance"])
        if coins > balance:
            return jsonify({"what": "Недостаточно средств"}), 400

        # Конвертируем монеты в USDT (1000 монет = 1 USDT, меняй под свой курс)
        amount_usdt = round(coins / 1000, 2)
        if amount_usdt < 0.1:
            return jsonify({"what": "Сумма слишком мала"}), 400

        token = os.getenv("CRYPTOBOT_TOKEN")
        api_url = os.getenv("CRYPTOBOT_API_URL", "https://pay.crypt.bot/api")

        try:
            resp = req_lib.post(
                f"{api_url}/transfer",
                headers={
                    "Crypto-Pay-API-Token": token,
                    "Content-Type": "application/json"
                },
                json={
                    "user_id": telegram_user_id,
                    "asset": "USDT",
                    "amount": str(amount_usdt),
                    "spend_id": f"withdraw_{user['id']}_{int(_time.time())}",
                    "comment": "Вывод из SlotKing"
                },
                timeout=15
            )
            result = resp.json()
        except Exception as e:
            return jsonify({"what": str(e)}), 500

        if result.get("ok"):
            # Списываем монеты
            g.db.execute(
                "UPDATE users SET main_balance = main_balance - ? WHERE id = ?",
                (coins, user["id"])
            )
            g.db.commit()
            add_transaction(user["id"], "withdraw", coins, "done",
                           f"Вывод {amount_usdt} USDT → TG:{telegram_user_id}")
            return jsonify({"ok": True})
        else:
            err = result.get("error", {})
            return jsonify({"what": f"CryptoBot: {err.get('name', 'ошибка')}"}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8000, debug=True)
