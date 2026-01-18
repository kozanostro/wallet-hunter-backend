# bot.py — WalletHunter Telegram Bot
# VERSION: BOT-1.06 (stable-final)
# Goal: Wallet Hunter as separate MAIN button (opens WebApp), Games contain only Domino+Smash.

import os
import sqlite3
import time
import traceback
from typing import Set

from telebot import TeleBot, types

# --- optional: load .env if python-dotenv installed ---
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv("/opt/wallethunter/backend/.env")
except Exception:
    pass


# ===================== ENV / SETTINGS =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Put BOT_TOKEN=... into /opt/wallethunter/backend/.env")

DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db").strip()

DOMINO_WEBAPP_URL = os.getenv("DOMINO_WEBAPP_URL", "https://kozanostro.github.io/miniapp/?v=21").strip()
WALLETHUNTER_WEBAPP_URL = os.getenv(
    "WALLETHUNTER_WEBAPP_URL",
    "https://kozanostro.github.io/wallet-hunter-miniapp/?v=1"
).strip()


def parse_admin_ids(s: str) -> Set[int]:
    s = (s or "").strip()
    if not s:
        return set()
    out: Set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out


ADMIN_IDS = parse_admin_ids(os.getenv("ADMIN_IDS", "1901263391"))
bot = TeleBot(BOT_TOKEN)

print(f"[BOT] VERSION=BOT-1.06 starting… DB_PATH={DB_PATH} ADMIN_IDS={sorted(list(ADMIN_IDS))}")
# =========================================================


# ===================== DB =====================
def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


conn = db_connect()


def ensure_user_columns(cur):
    cur.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cur.fetchall()}

    def add(col_sql: str):
        cur.execute(f"ALTER TABLE users ADD COLUMN {col_sql}")

    if "minutes_in_app" not in existing:
        add("minutes_in_app INTEGER DEFAULT 0")
    if "wallet_status" not in existing:
        add("wallet_status TEXT DEFAULT 'idle'")
    if "wallet_address" not in existing:
        add("wallet_address TEXT DEFAULT ''")
    if "t_wallet_seconds" not in existing:
        add("t_wallet_seconds INTEGER DEFAULT 0")
    if "t_seed_seconds" not in existing:
        add("t_seed_seconds INTEGER DEFAULT 900")


def db_init():
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id     INTEGER PRIMARY KEY,
        username    TEXT,
        first_name  TEXT,
        last_name   TEXT,
        language    TEXT,
        created_at  INTEGER,
        last_seen   INTEGER,

        win_chance  REAL DEFAULT 1.0,
        gen_level   INTEGER DEFAULT 0,

        bal_mmc     REAL DEFAULT 0,
        bal_ton     REAL DEFAULT 0,
        bal_usdt    REAL DEFAULT 0,
        bal_stars   REAL DEFAULT 0
    )
    """)
    conn.commit()

    cur = conn.cursor()
    ensure_user_columns(cur)
    conn.commit()


db_init()


def upsert_user(tg_user):
    now = int(time.time())
    user_id = tg_user.id
    username = tg_user.username or ""
    first_name = tg_user.first_name or ""
    last_name = tg_user.last_name or ""
    language = getattr(tg_user, "language_code", "") or ""

    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cur.fetchone() is not None

    if not exists:
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, first_name, last_name, language, now, now))
    else:
        cur.execute("""
            UPDATE users
               SET username=?, first_name=?, last_name=?, language=?, last_seen=?
             WHERE user_id=?
        """, (username, first_name, last_name, language, now, user_id))

    conn.commit()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
# =========================================================


# ===================== URL HELPERS =====================
def add_query_param(url: str, key: str, value: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{key}={value}"
# =========================================================


# ===================== UI =====================
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🎮 Игры", "🔍 Wallet Hunter")
    kb.row("💎 Стейкинг", "📩 Обратная связь")
    return kb


def games_menu():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🁫 Domino (Mini App)", web_app=types.WebAppInfo(url=DOMINO_WEBAPP_URL)))
    kb.add(types.InlineKeyboardButton("💥 Smash (скоро)", callback_data="game_smash"))
    return kb


def wallet_hunter_webapp_kb():
    # Telegram WebApp opens ONLY via inline button (not via reply keyboard)
    if not WALLETHUNTER_WEBAPP_URL:
        raise RuntimeError("WALLETHUNTER_WEBAPP_URL is empty")

    url = add_query_param(WALLETHUNTER_WEBAPP_URL, "wallet", "ton")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("▶️ Открыть Wallet Hunter", web_app=types.WebAppInfo(url=url)))
    return kb
# =========================================================


# ===================== FEEDBACK FLOW =====================
WAIT_FEEDBACK = set()


@bot.message_handler(func=lambda m: (m.text or "") == "📩 Обратная связь")
def on_feedback(message):
    upsert_user(message.from_user)
    WAIT_FEEDBACK.add(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "Напиши сообщение одним текстом — я отправлю его админу.",
        reply_markup=main_menu()
    )


@bot.message_handler(func=lambda m: (m.from_user.id in WAIT_FEEDBACK) and (m.text is not None))
def on_feedback_text(message):
    WAIT_FEEDBACK.discard(message.from_user.id)
    upsert_user(message.from_user)

    txt = (message.text or "").strip()
    if not txt:
        bot.send_message(message.chat.id, "Пустое сообщение, попробуй ещё раз.", reply_markup=main_menu())
        return

    sender = f"{message.from_user.id} @{message.from_user.username or ''} {message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
    payload = f"📩 Feedback\nОт: {sender}\n\n{txt}"

    sent_any = False
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, payload)
            sent_any = True
        except Exception:
            pass

    if sent_any:
        bot.send_message(message.chat.id, "✅ Отправлено админу.", reply_markup=main_menu())
    else:
        bot.send_message(message.chat.id, "⚠️ Не удалось доставить админу (проверь ADMIN_IDS).", reply_markup=main_menu())
# =========================================================


# ===================== HANDLERS =====================
@bot.message_handler(commands=["start"])
def start(message):
    upsert_user(message.from_user)
    # Telegram caches reply keyboard, so remove then re-send
    bot.send_message(message.chat.id, "Обновляю меню…", reply_markup=types.ReplyKeyboardRemove())
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())


@bot.message_handler(commands=["myid"])
def myid(message):
    upsert_user(message.from_user)
    bot.send_message(message.chat.id, f"Ваш ID: {message.from_user.id}")


@bot.message_handler(func=lambda m: (m.text or "") == "🎮 Игры")
def on_games(message):
    upsert_user(message.from_user)
    bot.send_message(message.chat.id, "Выбери игру:", reply_markup=games_menu())


@bot.message_handler(func=lambda m: (m.text or "") == "🔍 Wallet Hunter")
def on_wallet_hunter(message):
    upsert_user(message.from_user)
    try:
        bot.send_message(
            message.chat.id,
            "🔍 Wallet Hunter\n\nНажми кнопку ниже, чтобы открыть мини-апп:",
            reply_markup=wallet_hunter_webapp_kb()
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка запуска Wallet Hunter: {e}")


@bot.message_handler(func=lambda m: (m.text or "") == "💎 Стейкинг")
def on_staking(message):
    upsert_user(message.from_user)
    bot.send_message(
        message.chat.id,
        "💎 Стейкинг (пока заглушка).\nПозже сюда добавим MMCoin/условия/историю.",
        reply_markup=main_menu()
    )


@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    if call.data == "game_smash":
        bot.answer_callback_query(call.id, "Smash скоро будет 👍")
        bot.send_message(call.message.chat.id, "Smash: в разработке.")
    else:
        bot.answer_callback_query(call.id, "Неизвестная команда")
# =========================================================


# ===================== ADMIN =====================
def admin_guard(message) -> bool:
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Команда доступна только админу.")
        return False
    return True


@bot.message_handler(commands=["adminhelp"])
def adminhelp(message):
    upsert_user(message.from_user)
    if not admin_guard(message):
        return
    bot.send_message(
        message.chat.id,
        "🔧 Admin команды:\n"
        "/users [N] — последние N пользователей (по умолчанию 20)\n"
        "/user <id> — карточка пользователя\n"
        "/setwin <id> <percent> — шанс выигрыша\n"
        "/setgen <id> <level> — уровень генератора\n"
        "/setbal <id> <mmc|ton|usdt|stars> <value> — баланс\n"
        "/myid — показать твой Telegram ID\n"
    )
# =========================================================


# ===================== RUN =====================
if __name__ == "__main__":
    try:
        print(f"[BOT] Bot started. DB={DB_PATH}")
        bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
    except Exception:
        print("[BOT] FATAL ERROR:")
        print(traceback.format_exc())
        raise
