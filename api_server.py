print("=== API_SERVER LOADED FROM /opt/wallethunter/backend/api_server.py ===")

import os
import time
import sqlite3
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# -------------------- CONFIG --------------------
DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = (os.getenv("ADMIN_API_KEY") or "").strip()

APP_TITLE = "WalletHunter API"
APP_VERSION = "1.2.0"

# -------------------- APP --------------------
app = FastAPI(title=APP_TITLE, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # потом сузим до GitHub Pages домена
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- DB HELPERS --------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # чуть меньше “database is locked”
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def _ensure_schema() -> None:
    with db() as conn:
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

        cur.execute("PRAGMA table_info(users)")
        existing = {row[1] for row in cur.fetchall()}

        def add_col(name: str, col_sql: str) -> None:
            if name not in existing:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col_sql}")

        # твои “новые” поля — всегда добавляем (если их нет)
        add_col("minutes_in_app", "minutes_in_app INTEGER DEFAULT 0")
        add_col("wallet_status", "wallet_status TEXT DEFAULT 'idle'")
        add_col("wallet_address", "wallet_address TEXT DEFAULT ''")
        add_col("t_wallet_seconds", "t_wallet_seconds INTEGER DEFAULT 0")

        conn.commit()

@app.on_event("startup")
def on_startup():
    _ensure_schema()
    # важная диагностика: чтобы сразу видеть, подхватился ли ключ
    print(f"[STARTUP] DB_PATH={DB_PATH}")
    print(f"[STARTUP] ADMIN_API_KEY set={bool(ADMIN_API_KEY)}")

# -------------------- MODELS --------------------
class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"

# -------------------- AUTH --------------------
def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server (.env not loaded?)")
    if (x_api_key or "").strip() != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

# -------------------- ROUTES --------------------
@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}

def upsert_user(p: PingBody):
    now = int(time.time())
    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE user_id=?", (p.user_id,))
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

    conn = db()
    cur = conn.cursor()

    # Берём только реально существующие поля
    cur.execute("""
        SELECT
            user_id,
            username,
            first_name,
            last_name,
            language,
            created_at,
            last_seen,
            win_chance,
            gen_level,
            bal_mmc,
            bal_ton,
            bal_usdt,
            bal_stars,
            minutes_in_app,
            wallet_status,
            wallet_address,
            t_wallet_seconds
        FROM users
        ORDER BY last_seen DESC
        LIMIT 200
    """)

    rows = cur.fetchall()
    return {
        "ok": True,
        "count": len(rows),
        "users": [dict(r) for r in rows],
    }



    except sqlite3.OperationalError as e:
        # вот это убирает “мистический 500” — теперь ты увидишь точную причину
        raise HTTPException(status_code=500, detail=f"sqlite error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"server error: {type(e).__name__}: {e}")


