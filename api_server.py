import os
import time
import sqlite3
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = os.getenv("DB_PATH", "bot.db")
ADMIN_API_KEY = os.getenv("qJKi0x2CDPg-AQjHqBeF7qQdcbXcQrwGCU9RD0Quaow", "")  # сюда положишь секрет

app = FastAPI(title="WalletHunter API", version="1.0")

# CORS: разрешаем GitHub Pages домен(а)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://kozanostro.github.io",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class PingBody(BaseModel):
    user_id: int
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    language: Optional[str] = ""
    app: Optional[str] = "WalletHunter"

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

def require_admin(x_api_key: str):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY not set on server")
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/ping")
def ping(body: PingBody):
    # Любой пользователь может "пинговать" — это просто обновление last_seen
    upsert_user(body)
    return {"ok": True}

@app.get("/admin/users")
def admin_users(x_api_key: str = Header(default="")):
    require_admin(x_api_key)

    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, first_name, last_name, language, created_at, last_seen,
               win_chance, gen_level, bal_mmc, bal_ton, bal_usdt, bal_stars
          FROM users
         ORDER BY last_seen DESC
         LIMIT 200
    """)
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append(dict(r))
    return {"ok": True, "users": out}
