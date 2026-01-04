import os
import time
import sqlite3
from typing import Optional, Dict, Any, List
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator, ConfigDict

DB_PATH = os.getenv("DB_PATH", "/opt/wallethunter/backend/bot.db")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

MMMCOIN_TOTAL_SUPPLY = 30_000_000.0

app = FastAPI(title="WalletHunter API", version="1.3")
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # пытаемся вытащить тело запроса (JSON или сырой текст)
    try:
        body = await request.json()
    except Exception:
        try:
            body = (await request.body()).decode("utf-8", "replace")
        except Exception:
            body = "<cannot read body>"

    # ЛОГ в консоль/journalctl
    print("=== 422 VALIDATION ERROR ===")
    print("URL:", request.url)
    print("HEADERS Content-Type:", request.headers.get("content-type"))
    print("BODY:", body)
    print("ERRORS:", exc.errors())
    print("============================")

    # ответ клиенту тоже понятный
    return JSONResponse(
        status_code=422,
        content={"ok": False, "detail": exc.errors(), "body": body},
    )

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
    if "bal_mmc" not in existing:
        add("bal_mmc REAL DEFAULT 0")
    if "bal_ton" not in existing:
        add("bal_ton REAL DEFAULT 0")
    if "bal_usdt" not in existing:
        add("bal_usdt REAL DEFAULT 0")
    if "bal_stars" not in existing:
        add("bal_stars REAL DEFAULT 0")

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
    # разрешаем принимать и snake_case и camelCase
    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(..., alias="userId")

    win_chance: Optional[float] = Field(default=None, alias="winChance")
    gen_level: Optional[int] = Field(default=None, alias="genLevel")
    t_wallet_seconds: Optional[int] = Field(default=None, alias="tWalletSeconds")
    t_seed_seconds: Optional[int] = Field(default=None, alias="tSeedSeconds")

    bal_mmc: Optional[float] = Field(default=None, alias="balMmc")
    bal_ton: Optional[float] = Field(default=None, alias="balTon")
    bal_usdt: Optional[float] = Field(default=None, alias="balUsdt")
    bal_stars: Optional[float] = Field(default=None, alias="balStars")

    wallet_address: Optional[str] = Field(default=None, alias="walletAddress")
    wallet_status: Optional[str] = Field(default=None, alias="walletStatus")
    minutes_in_app: Optional[int] = Field(default=None, alias="minutesInApp")

    @field_validator("win_chance")
    @classmethod
    def clamp_win(cls, v):
        if v is None:
            return v
        v = float(v)
        if v < 0:
            return 0.0
        if v > 100:
            return 100.0
        return v

    @field_validator(
        "gen_level", "t_wallet_seconds", "t_seed_seconds", "minutes_in_app",
        mode="before"
    )
    @classmethod
    def non_negative_ints(cls, v):
        if v is None:
            return v
        return max(0, int(v))

    @field_validator("bal_mmc", "bal_ton", "bal_usdt", "bal_stars", mode="before")
    @classmethod
    def parse_money(cls, v):
        if v is None:
            return v
        # если прилетает "123,45" — исправим на "123.45"
        if isinstance(v, str):
            v = v.replace(",", ".").strip()
        return float(v)



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

def row_to_public_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    # sqlite3.Row -> dict already ok
    return d

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
        cur.execute("UPDATE users SET wallet_address=? WHERE user_id=?", (body.wallet_address, body.user_id))
    if body.wallet_status is not None and body.wallet_status != "":
        cur.execute("UPDATE users SET wallet_status=? WHERE user_id=?", (body.wallet_status, body.user_id))

    conn.commit()
    return {"ok": True}

# --- ADMIN ---
# ВАЖНО: alias="X-API-Key" чтобы совпадало с тем, что шлёт админка/curл
@app.get("/admin/users")
def admin_users(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
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
def admin_user_update(
    body: AdminUpdateBody,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    require_admin(x_api_key)
    _ = get_user_row(body.user_id)

    allowed_fields = {
        "win_chance",
        "gen_level",
        "t_wallet_seconds",
        "t_seed_seconds",
        "bal_mmc",
        "bal_ton",
        "bal_usdt",
        "bal_stars",
        "wallet_address",
        "wallet_status",
        "minutes_in_app",
    }

    fields: Dict[str, Any] = {}
    dumped = body.model_dump(by_alias=False)
    for k, v in dumped.items():
        if k == "user_id":
            continue
        if k in allowed_fields and v is not None:
            fields[k] = v

    if not fields:
        return {"ok": True, "updated": False, "reason": "no fields"}

    sets = ", ".join([f"{k}=?" for k in fields.keys()])
    vals = list(fields.values()) + [body.user_id]

    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {sets} WHERE user_id=?", vals)
    conn.commit()

    # вернём свежую строку — удобно админке
    r2 = get_user_row(body.user_id)
    return {"ok": True, "updated": True, "fields": list(fields.keys()), "user": dict(r2)}



