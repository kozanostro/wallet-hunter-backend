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

# ---------------- Models ----------------
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

    wallet_status: Optional[str] = None   # ← ВАЖНО: STRING
    wallet_address: Optional[str] = None
    minutes_in_app: Optional[int] = None


# ---------------- Helpers ----------------
def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(500, "ADMIN_API_KEY not set on server")
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(403, "Forbidden")

def user_exists(user_id: int):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(404, "User not found")

# ---------------- Routes ----------------
@app.get("/admin/users")
def admin_users(x_api_key: str = Header("", alias="X-API-Key")):
    require_admin(x_api_key)

    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY last_seen DESC LIMIT 500")
    return {
        "ok": True,
        "users": [dict(r) for r in cur.fetchall()],
        "mmmcoin_total_supply": MMMCOIN_TOTAL_SUPPLY,
    }

@app.post("/admin/user/update")
def admin_user_update(
    body: AdminUpdateBody,
    x_api_key: str = Header("", alias="X-API-Key"),
):
    require_admin(x_api_key)
    user_exists(body.user_id)

    data: Dict[str, Any] = {}

    for k, v in body.model_dump().items():
        if k != "user_id" and v is not None:
            data[k] = v

    if not data:
        return {"ok": True, "updated": False}

    sql = ", ".join(f"{k}=?" for k in data)
    values = list(data.values()) + [body.user_id]

    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {sql} WHERE user_id=?", values)
    conn.commit()

    return {"ok": True, "updated": True, "fields": list(data)}
