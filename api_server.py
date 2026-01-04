import os
import time
import sqlite3
from typing import Optional, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

MMMCOIN_TOTAL_SUPPLY = 30_000_000.0

app = FastAPI(title="WalletHunter API", version="1.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = db()

def init_db():
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        language TEXT,
        created_at INTEGER,
        last_seen INTEGER,

        minutes_in_app INTEGER DEFAULT 0,

        wallet_status TEXT DEFAULT 'idle',
        wallet_linked INTEGER DEFAULT 0,
        wallet_address TEXT DEFAULT '',

        win_chance REAL DEFAULT 1.0,
        gen_level INTEGER DEFAULT 0,

        t_wallet_seconds INTEGER DEFAULT 0,
        t_seed_seconds INTEGER DEFAULT 900,

        bal_mmc REAL DEFAULT 0,
        bal_ton REAL DEFAULT 0,
        bal_usdt REAL DEFAULT 0,
        bal_stars REAL DEFAULT 0
    )
    """)
    conn.commit()

init_db()

# ---------------- MODELS ----------------
class AdminUpdateBody(BaseModel):
    user_id: int

    win_chance: Optional[float] = None
    gen_level: Optional[int] = None
    t_wallet_seconds: Optional[int] = None
    t_seed_seconds: Optional[int] = None

    bal_mmc: Optional[float] = None
    bal_ton: Optional[float] = None
    bal_usdt: Optional[float] = None
    bal_stars: Optional[float] = None

    wallet_status: Optional[str] = None
    wallet_address: Optional[str] = None
    wallet_linked: Optional[int] = None

    minutes_in_app: Optional[int] = None


# ---------------- HELPERS ----------------
def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(500, "ADMIN_API_KEY not set")
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(403, "Forbidden")

def user_exists(uid: int):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
    if not cur.fetchone():
        raise HTTPException(404, "User not found")

# ---------------- ROUTES ----------------
@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="")):
    require_admin(x_api_key)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 500")
    return {
        "ok": True,
        "users": [dict(r) for r in cur.fetchall()],
        "mmmcoin_total_supply": MMMCOIN_TOTAL_SUPPLY
    }

@app.post("/admin/user/update")
def admin_user_update(body: AdminUpdateBody, x_api_key: str = Header(default="")):
    require_admin(x_api_key)
    user_exists(body.user_id)

    fields: Dict[str, Any] = {}
    for k, v in body.model_dump().items():
        if k != "user_id" and v is not None:
            fields[k] = v

    if not fields:
        return {"ok": True, "updated": False}

    sets = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [body.user_id]

    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {sets} WHERE user_id=?", values)
    conn.commit()

    return {"ok": True, "updated": True, "fields": list(fields.keys())}
