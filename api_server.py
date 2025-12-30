import os
import time
import sqlite3
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --------- ENV ----------
DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

app = FastAPI(title="WalletHunter API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://kozanostro.github.io"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- DB helpers ----------
def db_connect() -> sqlite3.Connection:
    # timeout важен, чтобы не ловить "database is locked" на ровном месте
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL обычно сильно снижает шанс блокировок
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def db_init_and_migrate() -> None:
    with db_connect() as conn:
        cur = conn.cursor()

        # Базовая таблица
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

        # Мягкие миграции: добавляем колонки если их нет
        cur.execute("PRAGMA table_info(users)")
        existing = {row[1] for row in cur.fetchall()}

        def add_col(name: str, ddl: str):
            if name in existing:
                return
            cur.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

        add_col("minutes_in_app", "INTEGER DEFAULT 0")
        add_col("wallet_status", "TEXT DEFAULT 'idle'")
        add_col("wallet_address", "TEXT DEFAULT ''")
        add_col("t_wallet_seconds", "INTEGER DEFAULT 0")

        conn.commit()


def get_existing_user_columns(conn: sqlite3.Connection) -> List[str]:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    return [row[1] for row in cur.fetchall()]


# --------- Models ----------
class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"


# --------- Auth ----------
def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server")
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# --------- Startup ----------
@app.on_event("startup")
def on_startup():
    db_init_and_migrate()


# --------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}


def upsert_user(p: PingBody):
    now = int(time.time())
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id=?", (p.user_id,))
        exists = cur.fetchone() is not None

        if not exists:
            cur.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, language, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (p.user_id, p.username or "", p.first_name or "", p.last_name or "", p.language or "", now, now))
        else:
            cur.execute("""
                UPDATE users
                   SET username=?, first_name=?, last_name=?, language=?, last_seen=?
                 WHERE user_id=?
            """, (p.username or "", p.first_name or "", p.last_name or "", p.language or "", now, p.user_id))

        conn.commit()


@app.post("/ping")
def ping(body: PingBody):
    upsert_user(body)
    return {"ok": True}


@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="")):
    require_admin(x_api_key)

    try:
        with db_connect() as conn:
            cols = set(get_existing_user_columns(conn))

            # какие колонки хотим видеть (НО берём только те, что реально есть)
            wanted = [
                "user_id", "username", "first_name", "last_name", "language",
                "created_at", "last_seen",
                "minutes_in_app", "wallet_status", "wallet_address", "t_wallet_seconds",
                "win_chance", "gen_level",
                "bal_mmc", "bal_ton", "bal_usdt", "bal_stars",
            ]
            selected = [c for c in wanted if c in cols]
            if not selected:
                raise HTTPException(status_code=500, detail="users table has no selectable columns (?)")

            sql = f"""
                SELECT {", ".join(selected)}
                  FROM users
                 ORDER BY last_seen DESC
                 LIMIT 200
            """

            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            return {"ok": True, "columns": selected, "users": [dict(r) for r in rows]}

    except sqlite3.Error as e:
        # чтобы не было “тихих 500”
        raise HTTPException(status_code=500, detail=f"sqlite error: {e}")
