import os
import time
import sqlite3
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --------- ENV ---------
DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")  # <- ВАЖНО: читаем по имени переменной

app = FastAPI(title="WalletHunter API", version="1.1")

# --------- CORS ---------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kozanostro.github.io",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
   def ensure_user_columns():
     conn = sqlite3.connect(DB_PATH)
     cur = conn.cursor()
     cur.execute("PRAGMA table_info(users)")
     existing = {row[1] for row in cur.fetchall()}

    def add(col):
        cur.execute(f"ALTER TABLE users ADD COLUMN {col}")

    if "t_wallet_seconds" not in existing:
        add("t_wallet_seconds INTEGER DEFAULT 0")

    if "wallet_address" not in existing:
        add("wallet_address TEXT DEFAULT ''")

    conn.commit()
    conn.close()

# --------- DB helpers ---------
def db_connect() -> sqlite3.Connection:
    # timeout помогает, когда bot.py держит БД
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row

    # чуть лучше для совместной работы (если возможно)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def db_init_and_migrate() -> None:
    conn = db_connect()
    cur = conn.cursor()

    # 1) Базовая таблица
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

    # 2) Миграции: добавляем недостающие колонки (без падений)
    cur.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cur.fetchall()}

    def add_col(name: str, sql: str) -> None:
        if name not in existing:
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {sql}")

    # Эти колонки у тебя “всплывали” в ошибках/логах
    add_col("minutes_in_app", "INTEGER DEFAULT 0")
    add_col("wallet_status", "TEXT DEFAULT 'idle'")
    add_col("wallet_address", "TEXT DEFAULT ''")
    add_col("t_wallet_seconds", "INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


db_init_and_migrate()

# --------- Models ---------
class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"


# --------- Auth ---------
def require_admin(x_api_key: str) -> None:
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server")
    # Header может прийти как пустая строка
    if (x_api_key or "").strip() != ADMIN_API_KEY.strip():
        raise HTTPException(status_code=403, detail="Forbidden")


# --------- API ---------
@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}


@app.post("/ping")
def ping(body: PingBody):
    now = int(time.time())
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (body.user_id,))
    exists = cur.fetchone() is not None

    if not exists:
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            body.user_id,
            body.username or "",
            body.first_name or "",
            body.last_name or "",
            body.language or "",
            now,
            now
        ))
    else:
        cur.execute("""
            UPDATE users
               SET username=?, first_name=?, last_name=?, language=?, last_seen=?
             WHERE user_id=?
        """, (
            body.username or "",
            body.first_name or "",
            body.last_name or "",
            body.language or "",
            now,
            body.user_id
        ))

    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="")):
    require_admin(x_api_key)

    # на всякий случай: если ты обновил код, а БД старая — миграция перед SELECT
    db_init_and_migrate()

    conn = db_connect()
    cur = conn.cursor()

    # Выбираем ВСЕ нужные колонки (которые точно будут после миграции)
    cur.execute("""
        SELECT
            user_id, username, first_name, last_name, language,
            created_at, last_seen,
            win_chance, gen_level,
            bal_mmc, bal_ton, bal_usdt, bal_stars,
            minutes_in_app, wallet_status, wallet_address, t_wallet_seconds
        FROM users
        ORDER BY last_seen DESC
        LIMIT 200
    """)

    rows = cur.fetchall()
    conn.close()
    return {"ok": True, "users": [dict(r) for r in rows]}

