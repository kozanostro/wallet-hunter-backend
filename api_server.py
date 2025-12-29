import os
import time
import sqlite3
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ==== ENV ====
DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")

# В .env должно быть: ADMIN_API_KEY=твой_секрет
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()


# ==== APP ====
app = FastAPI(title="WalletHunter API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kozanostro.github.io",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==== DB HELPERS ====
_conn: Optional[sqlite3.Connection] = None


def db_connect() -> sqlite3.Connection:
    """
    Единое подключение для простого MVP.
    Важно: timeout + WAL уменьшают шанс 'database is locked'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Настройки против блокировок (SQLite)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # Базовая таблица users (минимум)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT DEFAULT '',
            first_name  TEXT DEFAULT '',
            last_name   TEXT DEFAULT '',
            language    TEXT DEFAULT '',
            created_at  INTEGER DEFAULT 0,
            last_seen   INTEGER DEFAULT 0,

            win_chance  REAL DEFAULT 1.0,
            gen_level   INTEGER DEFAULT 0,

            bal_mmc     REAL DEFAULT 0,
            bal_ton     REAL DEFAULT 0,
            bal_usdt    REAL DEFAULT 0,
            bal_stars   REAL DEFAULT 0
        )
        """
    )

    # Миграции: добавляем колонки, если их нет
    cur.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cur.fetchall()}

    def add_col(name: str, ddl: str) -> None:
        if name not in existing:
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

    add_col("minutes_in_app", "INTEGER DEFAULT 0")
    add_col("wallet_status", "TEXT DEFAULT 'idle'")
    add_col("wallet_address", "TEXT DEFAULT ''")

    conn.commit()


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = db_connect()
        ensure_schema(_conn)
    return _conn


@app.on_event("startup")
def _startup() -> None:
    # Прогреваем подключение и схему при старте
    get_conn()


# ==== AUTH ====
def require_admin(x_api_key: str) -> None:
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server")
    if (x_api_key or "").strip() != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ==== MODELS ====
class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"


# ==== LOGIC ====
def upsert_user(p: PingBody) -> None:
    conn = get_conn()
    now = int(time.time())
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (p.user_id,))
    exists = cur.fetchone() is not None

    if not exists:
        cur.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name, language, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p.user_id,
                p.username or "",
                p.first_name or "",
                p.last_name or "",
                p.language or "",
                now,
                now,
            ),
        )
    else:
        cur.execute(
            """
            UPDATE users
               SET username=?, first_name=?, last_name=?, language=?, last_seen=?
             WHERE user_id=?
            """,
            (
                p.username or "",
                p.first_name or "",
                p.last_name or "",
                p.language or "",
                now,
                p.user_id,
            ),
        )

    conn.commit()


# ==== ROUTES ====
@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}


@app.post("/ping")
def ping(body: PingBody):
    upsert_user(body)
    return {"ok": True}


@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="")):
    require_admin(x_api_key)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, username, first_name, last_name, language, created_at, last_seen,
               win_chance, gen_level,
               bal_mmc, bal_ton, bal_usdt, bal_stars,
               minutes_in_app, wallet_status, wallet_address
          FROM users
         ORDER BY last_seen DESC
         LIMIT 200
        """
    )

    rows = cur.fetchall()
    return {"ok": True, "users": [dict(r) for r in rows]}
