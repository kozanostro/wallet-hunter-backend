import os
import time
import sqlite3
from typing import Optional, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

MMMCOIN_TOTAL_SUPPLY = 30_000_000.0

app = FastAPI(title="WalletHunter API", version="1.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://kozanostro.github.io"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- DB ----------------
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

        minutes_in_app INTEGER DEFAULT 0,
        wallet_status  TEXT DEFAULT 'idle',
        wallet_address TEXT DEFAULT '',

        win_chance  REAL DEFAULT 1.0,
        gen_level   INTEGER DEFAULT 0,

        t_wallet_seconds INTEGER DEFAULT 0,
        t_seed_seconds   INTEGER DEFAULT 900,

        bal_mmc     REAL DEFAULT 0,
        bal_ton     REAL DEFAULT 0,
        bal_usdt    REAL DEFAULT 0,
        bal_stars   REAL DEFAULT 0
    )
    """)
    conn.commit()

def ensure_user_columns():
    cur = conn.cursor()
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

    conn.commit()

db_init()
ensure_user_columns()

# ---------------- Models ----------------
class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"

class EventBody(BaseModel):
    user_id: int
    event: str = Field(..., description="open|phase_wallet_start|phase_wallet_done|phase_seed_start|phase_seed_done|close")
    phase: Optional[str] = ""
    minutes_delta: Optional[int] = 0
    wallet_address: Optional[str] = ""
    wallet_status: Optional[str] = ""

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

    wallet_address: Optional[str] = None
    wallet_status: Optional[str] = None
    minutes_in_app: Optional[int] = None

# ---------------- Helpers ----------------
def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server")
    if (x_api_key or "").strip() != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

def upsert_user(p: PingBody):
    now = int(time.time())
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

def get_user_row(user_id: int) -> sqlite3.Row:
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="User not found")
    return r

def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))

def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid float: {v}")

def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid int: {v}")

# ---------------- Routes ----------------
@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.post("/ping")
def ping(body: PingBody):
    upsert_user(body)
    return {"ok": True}

@app.get("/config")
def config(user_id: int):
    r = get_user_row(user_id)
    return {
        "ok": True,
        "user_id": r["user_id"],
        "t_wallet_seconds": int(r["t_wallet_seconds"] or 0),
        "t_seed_seconds": int(r["t_seed_seconds"] or 900),
        "win_chance": float(r["win_chance"] or 1.0),
        "gen_level": int(r["gen_level"] or 0),
        "wallet_status": r["wallet_status"] or "idle",
        "wallet_address": r["wallet_address"] or "",
        "mmmcoin_total_supply": MMMCOIN_TOTAL_SUPPLY,
    }

@app.post("/event")
def event(body: EventBody):
    r = get_user_row(body.user_id)
    cur = conn.cursor()

    now = int(time.time())
    cur.execute("UPDATE users SET last_seen=? WHERE user_id=?", (now, body.user_id))

    if body.minutes_delta and body.minutes_delta > 0:
        new_minutes = int(r["minutes_in_app"] or 0) + int(body.minutes_delta)
        cur.execute("UPDATE users SET minutes_in_app=? WHERE user_id=?", (new_minutes, body.user_id))

    if body.wallet_address is not None and body.wallet_address != "":
        cur.execute("UPDATE users SET wallet_address=? WHERE user_id=?", (str(body.wallet_address), body.user_id))

    if body.wallet_status is not None and body.wallet_status != "":
        cur.execute("UPDATE users SET wallet_status=? WHERE user_id=?", (str(body.wallet_status), body.user_id))

    conn.commit()
    return {"ok": True}

@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="", alias="X-API-Key")):
    require_admin(x_api_key)

    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, first_name, last_name, language, created_at, last_seen,
               minutes_in_app, wallet_status, wallet_address,
               win_chance, gen_level, t_wallet_seconds, t_seed_seconds,
               bal_mmc, bal_ton, bal_usdt, bal_stars
          FROM users
         ORDER BY last_seen DESC
         LIMIT 500
    """)
    rows = [dict(r) for r in cur.fetchall()]
    return {"ok": True, "users": rows, "mmmcoin_total_supply": MMMCOIN_TOTAL_SUPPLY}

@app.post("/admin/user/update")
def admin_user_update(body: AdminUpdateBody, x_api_key: str = Header(default="", alias="X-API-Key")):
    require_admin(x_api_key)
    _ = get_user_row(body.user_id)

    raw = body.model_dump()

    fields: Dict[str, Any] = {}
    for k, v in raw.items():
        if k == "user_id" or v is None:
            continue

        # нормализация типов (чтобы не ловить “странные” значения)
        if k in ("gen_level", "t_wallet_seconds", "t_seed_seconds", "minutes_in_app"):
            vv = _safe_int(v)
            if k == "gen_level":
                vv = _clamp_int(vv, 0, 999)
            if k in ("t_wallet_seconds", "t_seed_seconds"):
                vv = _clamp_int(vv, 0, 60 * 60 * 24 * 365)  # до года
            if k == "minutes_in_app":
                vv = _clamp_int(vv, 0, 10**9)
            fields[k] = vv
            continue

        if k in ("win_chance", "bal_mmc", "bal_ton", "bal_usdt", "bal_stars"):
            vv = _safe_float(v)
            fields[k] = vv
            continue

        if k in ("wallet_status", "wallet_address"):
            vv = str(v).strip()
            # пустое не пишем
            if vv != "":
                fields[k] = vv
            continue

        # на всякий — неизвестные поля отсекаем
        # (если понадобится расширить — добавим явно)
        # fields[k] = v

    if not fields:
        return {"ok": True, "updated": False, "reason": "no_valid_fields"}

    sets = ", ".join([f"{k}=?" for k in fields.keys()])
    vals = list(fields.values()) + [body.user_id]

    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {sets} WHERE user_id=?", vals)
    conn.commit()

    return {"ok": True, "updated": True, "fields": list(fields.keys())}
