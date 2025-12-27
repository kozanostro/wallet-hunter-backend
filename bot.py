import sqlite3
import time
from telebot import TeleBot, types

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8269898838:AAEC6ud1Dv0zpIYgBX84sGudW0HzGnk24BE"

DOMINO_WEBAPP_URL = "https://kozanostro.github.io/miniapp/?v=21"
WALLETHUNTER_WEBAPP_URL = "https://kozanostro.github.io/wallet-hunter-miniapp/?v=1"

DB_PATH = "bot.db"

# ВАЖНО: поставь сюда свой Telegram ID (узнаешь командой /myid)
ADMIN_IDS = {1901263391}  # <-- замени 0 на свой id, можно несколько: {111, 222}

# =====================================================

bot = TeleBot(BOT_TOKEN)


# ===================== DB =====================
def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = db_connect()

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

db_init()


def upsert_user(tg_user):
    """Регистрирует/обновляет пользователя в БД."""
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
    return user_id in ADMIN_IDS and 0 not in ADMIN_IDS


# ===================== UI =====================
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🎮 Игры", "👤 Кабинет")
    kb.row("💎 Стейкинг", "📩 Обратная связь")
    return kb


def games_menu():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🁫 Domino (Mini App)", web_app=types.WebAppInfo(url=DOMINO_WEBAPP_URL)))
    kb.add(types.InlineKeyboardButton("🧩 WalletHunter (Mini App)", web_app=types.WebAppInfo(url=WALLETHUNTER_WEBAPP_URL)))
    kb.add(types.InlineKeyboardButton("💥 Smash (скоро)", callback_data="game_smash"))
    return kb


def cabinet_menu():
    kb = types.InlineKeyboardMarkup()

    domino_cabinet_url = (
        DOMINO_WEBAPP_URL + "&screen=cabinet"
        if "?" in DOMINO_WEBAPP_URL else DOMINO_WEBAPP_URL + "?screen=cabinet"
    )
    wh_cabinet_url = (
        WALLETHUNTER_WEBAPP_URL + "&screen=cabinet"
        if "?" in WALLETHUNTER_WEBAPP_URL else WALLETHUNTER_WEBAPP_URL + "?screen=cabinet"
    )

    kb.add(types.InlineKeyboardButton("👤 Кабинет Domino", web_app=types.WebAppInfo(url=domino_cabinet_url)))
    kb.add(types.InlineKeyboardButton("👤 Кабинет WalletHunter", web_app=types.WebAppInfo(url=wh_cabinet_url)))
    return kb


# ===================== HANDLERS =====================
@bot.message_handler(commands=["start"])
def start(message):
    upsert_user(message.from_user)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())


@bot.message_handler(commands=["myid"])
def myid(message):
    upsert_user(message.from_user)
    bot.send_message(message.chat.id, f"Ваш ID: {message.from_user.id}")


@bot.message_handler(func=lambda m: m.text == "🎮 Игры")
def on_games(message):
    upsert_user(message.from_user)
    bot.send_message(message.chat.id, "Выбери игру:", reply_markup=games_menu())


@bot.message_handler(func=lambda m: m.text == "👤 Кабинет")
def on_cabinet(message):
    upsert_user(message.from_user)
    bot.send_message(message.chat.id, "Выбери кабинет:", reply_markup=cabinet_menu())


@bot.message_handler(func=lambda m: m.text == "💎 Стейкинг")
def on_staking(message):
    upsert_user(message.from_user)
    bot.send_message(
        message.chat.id,
        "Стейкинг (пока заглушка):\n— условия\n— начисления\n— история",
        reply_markup=main_menu()
    )


@bot.message_handler(func=lambda m: m.text == "📩 Обратная связь")
def on_feedback(message):
    upsert_user(message.from_user)
    bot.send_message(
        message.chat.id,
        "Обратная связь:\nНапиши сообщение, я передам в админ-чат (сделаем дальше).",
        reply_markup=main_menu()
    )


@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    if call.data == "game_smash":
        bot.answer_callback_query(call.id, "Smash скоро будет 👍")
        bot.send_message(call.message.chat.id, "Smash: в разработке.")
    else:
        bot.answer_callback_query(call.id, "Неизвестная команда")


# ===================== ADMIN COMMANDS =====================
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
    bot.send_message(message.chat.id,
        "🔧 Admin команды:\n"
        "/users [N] — последние N пользователей (по умолчанию 20)\n"
        "/user <id> — карточка пользователя\n"
        "/setwin <id> <percent> — шанс выигрыша\n"
        "/setgen <id> <level> — уровень генератора\n"
        "/setbal <id> <mmc|ton|usdt|stars> <value> — баланс\n"
        "/myid — показать твой Telegram ID\n"
    )


@bot.message_handler(commands=["users"])
def cmd_users(message):
    upsert_user(message.from_user)
    if not admin_guard(message):
        return

    parts = message.text.split()
    limit = 20
    if len(parts) >= 2:
        try:
            limit = max(1, min(200, int(parts[1])))
        except:
            limit = 20

    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, first_name, last_name, last_seen, win_chance, gen_level
          FROM users
         ORDER BY last_seen DESC
         LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    if not rows:
        bot.send_message(message.chat.id, "Пока пользователей нет.")
        return

    lines = []
    for r in rows:
        uname = f"@{r['username']}" if r["username"] else f"{r['first_name'] or ''} {r['last_name'] or ''}".strip() or "—"
        last_seen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["last_seen"]))
        lines.append(f"{r['user_id']} | {uname} | last: {last_seen} | win={r['win_chance']:.1f}% | gen={r['gen_level']}")

    bot.send_message(message.chat.id, "👥 Users:\n" + "\n".join(lines))


@bot.message_handler(commands=["user"])
def cmd_user(message):
    upsert_user(message.from_user)
    if not admin_guard(message):
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Используй: /user <id>")
        return

    try:
        uid = int(parts[1])
    except:
        bot.send_message(message.chat.id, "ID должен быть числом.")
        return

    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    if not r:
        bot.send_message(message.chat.id, "Пользователь не найден.")
        return

    created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"]))
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["last_seen"]))
    uname = f"@{r['username']}" if r["username"] else "—"

    text = (
        f"👤 User {r['user_id']}\n"
        f"username: {uname}\n"
        f"name: {(r['first_name'] or '')} {(r['last_name'] or '')}\n"
        f"lang: {r['language']}\n"
        f"created: {created}\n"
        f"last_seen: {last}\n\n"
        f"win: {r['win_chance']:.1f}%\n"
        f"gen: {r['gen_level']}\n"
        f"bal: mmc={r['bal_mmc']}, ton={r['bal_ton']}, usdt={r['bal_usdt']}, stars={r['bal_stars']}"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["setwin"])
def cmd_setwin(message):
    upsert_user(message.from_user)
    if not admin_guard(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Используй: /setwin <id> <percent>")
        return

    try:
        uid = int(parts[1])
        percent = float(parts[2])
        percent = max(0.0, min(100.0, percent))
    except:
        bot.send_message(message.chat.id, "Неверный формат. Пример: /setwin 123 10")
        return

    cur = conn.cursor()
    cur.execute("UPDATE users SET win_chance=? WHERE user_id=?", (percent, uid))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ win_chance для {uid} = {percent:.1f}%")


@bot.message_handler(commands=["setgen"])
def cmd_setgen(message):
    upsert_user(message.from_user)
    if not admin_guard(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Используй: /setgen <id> <level>")
        return

    try:
        uid = int(parts[1])
        level = int(parts[2])
        level = max(0, min(999, level))
    except:
        bot.send_message(message.chat.id, "Неверный формат. Пример: /setgen 123 5")
        return

    cur = conn.cursor()
    cur.execute("UPDATE users SET gen_level=? WHERE user_id=?", (level, uid))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ gen_level для {uid} = {level}")


@bot.message_handler(commands=["setbal"])
def cmd_setbal(message):
    upsert_user(message.from_user)
    if not admin_guard(message):
        return

    parts = message.text.split()
    if len(parts) < 4:
        bot.send_message(message.chat.id, "Используй: /setbal <id> <mmc|ton|usdt|stars> <value>")
        return

    try:
        uid = int(parts[1])
        asset = parts[2].lower()
        value = float(parts[3])
    except:
        bot.send_message(message.chat.id, "Неверный формат. Пример: /setbal 123 usdt 50")
        return

    col = {
        "mmc": "bal_mmc",
        "ton": "bal_ton",
        "usdt": "bal_usdt",
        "stars": "bal_stars"
    }.get(asset)

    if not col:
        bot.send_message(message.chat.id, "Asset должен быть: mmc | ton | usdt | stars")
        return

    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {col}=? WHERE user_id=?", (value, uid))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ {asset} для {uid} = {value}")


# ===================== RUN =====================
if __name__ == "__main__":
    print("Bot started. DB:", DB_PATH)
    bot.infinity_polling(skip_pending=True)
