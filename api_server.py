import os
import time
import sqlite3
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

app = FastAPI(title="WalletHunter API", version="1.1")

# CORS: GitHub Pages + (если надо) добавишь свои домены
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kozanostro.github.io",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DB helpers -------------------------------------------------------------

def db_connect() -> sqlite3.Connection:
    # timeout важен при конкурентном доступе (бот + api)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Лечит "database is locked" на практике (бот и API одновременно)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")  # 5 сек ждать, вместо падения

    return conn


def add_col(cur: sqlite3.Cursor, table: str, col_name: str, col_sql: str):
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if col_name not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_sql}")


def db_init_and_migrate():
    conn = db_connect()
    try:
        cur = conn.cursor()

        # Базовая таблица (минимум). Колонки миграциями добьём.
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

        # Миграции: добавим то, что у тебя уже всплывало в логах
        add_col(cur, "users", "minutes_in_app", "minutes_in_app INTEGER DEFAULT 0")
        add_col(cur, "users", "wallet_status", "wallet_status TEXT DEFAULT 'idle'")
        add_col(cur, "users", "wallet_address", "wallet_address TEXT DEFAULT ''")
        add_col(cur, "users", "t_wallet_seconds", "t_wallet_seconds INTEGER DEFAULT 0")

        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
def on_startup():
    db_init_and_migrate()


# --- Models ----------------------------------------------------------------

class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"


# --- Auth ------------------------------------------------------------------

def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server")
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# --- Routes ----------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}


@app.post("/ping")
def ping(body: PingBody):
    now = int(time.time())
    conn = db_connect()
    try:
        cur = conn.cursor()

        # На всякий — если БД старую подсунули, миграции догонят
        add_col(cur, "users", "minutes_in_app", "minutes_in_app INTEGER DEFAULT 0")
        add_col(cur, "users", "wallet_status", "wallet_status TEXT DEFAULT 'idle'")
        add_col(cur, "users", "wallet_address", "wallet_address TEXT DEFAULT ''")
        add_col(cur, "users", "t_wallet_seconds", "t_wallet_seconds INTEGER DEFAULT 0")

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
                now, now
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
        return {"ok": True}
    finally:
        conn.close()


@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="", alias="X-API-Key")):
    require_admin(x_api_key)

    conn = db_connect()
    try:
        cur = conn.cursor()

        # Гарантируем, что колонки есть до SELECT
        add_col(cur, "users", "minutes_in_app", "minutes_in_app INTEGER DEFAULT 0")
        add_col(cur, "users", "wallet_status", "wallet_status TEXT DEFAULT 'idle'")
        add_col(cur, "users", "wallet_address", "wallet_address TEXT DEFAULT ''")
        add_col(cur, "users", "t_wallet_seconds", "t_wallet_seconds INTEGER DEFAULT 0")
        conn.commit()

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

        rows = [dict(r) for r in cur.fetchall()]
        return {"ok": True, "users": rows}
    finally:
        conn.close()
