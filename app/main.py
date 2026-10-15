import re, secrets, pathlib
from contextlib import asynccontextmanager
from datetime import date
import httpx
import psycopg.errors
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import gcal
from .auth import current_user, hash_password, make_token, verify_password
from .db import get_conn, pool
from .ics import import_events
from .legs import LIST_LEGS, STATS, UPDATE_LEG, insert_leg

@asynccontextmanager
async def lifespan(app):
    pool.open()
    yield
    pool.close()

app = FastAPI(title="Flight tracker", lifespan=lifespan)
DUMMY_HASH = hash_password("not-a-real-password")   # so a wrong email takes as long as a wrong password

# ---------- request shapes ----------
IATA = r"^[A-Za-z]{3}$"

class Register(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=80)

class Login(BaseModel):
    email: str
    password: str

class LegIn(BaseModel):
    flight_date: date
    origin: str = Field(pattern=IATA)
    dest: str = Field(pattern=IATA)
    flight_number: str = Field(default="", max_length=12)
    note: str = Field(default="", max_length=200)

    @field_validator("origin", "dest")
    @classmethod
    def upper(cls, v): return v.upper()

class LegPatch(BaseModel):
    flight_date: date | None = None
    origin: str | None = Field(default=None, pattern=IATA)
    dest: str | None = Field(default=None, pattern=IATA)
    flight_number: str | None = Field(default=None, max_length=12)
    note: str | None = Field(default=None, max_length=200)

# ---------- helpers ----------
def role_in(conn, lb, user):
    row = conn.execute("SELECT role FROM logbook_members WHERE logbook_id=%s AND user_id=%s", (lb, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Logbook not found")        # 404, not 403: don't reveal it exists
    return row["role"]

def need_airports(conn, *codes):
    known = {r["iata"] for r in conn.execute("SELECT iata FROM airports WHERE iata = ANY(%s)", (list(codes),))}
    missing = [c for c in codes if c not in known]
    if missing:
        raise HTTPException(422, f"Unknown airport code: {', '.join(missing)}")

# ---------- auth ----------
@app.post("/api/auth/register", status_code=201)
def register(body: Register, conn=Depends(get_conn)):
    email = body.email.lower()
    row = conn.execute("INSERT INTO users (email, name, password_hash) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                       (email, body.name.strip(), hash_password(body.password))).fetchone()
    if not row:
        raise HTTPException(409, "That email is already registered")
    lb = conn.execute("INSERT INTO logbooks (name) VALUES (%s) RETURNING id", (f"{body.name.strip()}'s travels",)).fetchone()
    conn.execute("INSERT INTO logbook_members (logbook_id, user_id, role) VALUES (%s,%s,'owner')", (lb["id"], row["id"]))
    return {"token": make_token(row["id"])}

@app.post("/api/auth/login")
def login(body: Login, conn=Depends(get_conn)):
    row = conn.execute("SELECT id, password_hash FROM users WHERE email=%s", (body.email.lower(),)).fetchone()
    ok = verify_password(body.password, row["password_hash"] if row else DUMMY_HASH)
    if not (row and ok):
        raise HTTPException(401, "Wrong email or password")
    return {"token": make_token(row["id"])}

@app.get("/api/me")
def me(user=Depends(current_user), conn=Depends(get_conn)):
    books = conn.execute("""
        SELECT l.id, l.name, m.role,
          (SELECT json_agg(json_build_object('name', u.name, 'role', mm.role) ORDER BY u.name)
             FROM logbook_members mm JOIN users u ON u.id = mm.user_id WHERE mm.logbook_id = l.id) AS members
        FROM logbooks l JOIN logbook_members m ON m.logbook_id = l.id WHERE m.user_id = %s ORDER BY l.id""", (user["id"],)).fetchall()
    return {"user": user, "logbooks": books}

# ---------- sharing ----------
@app.post("/api/logbooks/{lb}/invites", status_code=201)
def create_invite(lb: int, user=Depends(current_user), conn=Depends(get_conn)):
    if role_in(conn, lb, user) != "owner":
        raise HTTPException(403, "Only the owner can invite people")
    code = secrets.token_urlsafe(6)
    conn.execute("INSERT INTO invites (code, logbook_id, created_by, expires_at) VALUES (%s,%s,%s, now() + interval '7 days')", (code, lb, user["id"]))
    return {"code": code, "expires_in_days": 7}

@app.post("/api/invites/{code}/accept")
def accept_invite(code: str, user=Depends(current_user), conn=Depends(get_conn)):
    row = conn.execute("SELECT logbook_id FROM invites WHERE code=%s AND expires_at > now()", (code,)).fetchone()
    if not row:
        raise HTTPException(404, "Invite not found or expired")
    conn.execute("INSERT INTO logbook_members (logbook_id, user_id, role) VALUES (%s,%s,'member') ON CONFLICT DO NOTHING", (row["logbook_id"], user["id"]))
    return {"logbook_id": row["logbook_id"]}

# ---------- flights ----------
@app.get("/api/logbooks/{lb}/legs")
def list_legs(lb: int, year: int | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    role_in(conn, lb, user)
    return conn.execute(LIST_LEGS, {"lb": lb, "year": year}).fetchall()

@app.post("/api/logbooks/{lb}/legs", status_code=201)
def add_leg(lb: int, body: LegIn, user=Depends(current_user), conn=Depends(get_conn)):
    role_in(conn, lb, user)
    if body.origin == body.dest:
        raise HTTPException(422, "Origin and destination must differ")
    need_airports(conn, body.origin, body.dest)
    new_id = insert_leg(conn, lb, user["id"], body.flight_date, body.origin, body.dest, body.flight_number.strip(), body.note.strip())
    if new_id is None:
        raise HTTPException(409, "That flight is already in the logbook")
    return {"id": new_id}

@app.patch("/api/legs/{leg_id}")
def edit_leg(leg_id: int, body: LegPatch, user=Depends(current_user), conn=Depends(get_conn)):
    cur = conn.execute("""SELECT l.* FROM legs l JOIN logbook_members m ON m.logbook_id = l.logbook_id AND m.user_id = %s
                          WHERE l.id = %s""", (user["id"], leg_id)).fetchone()
    if not cur:
        raise HTTPException(404, "Flight not found")
    new = {**{k: cur[k] for k in ("flight_date", "origin", "dest", "flight_number", "note")},
           **{k: (v.upper() if k in ("origin", "dest") else v) for k, v in body.model_dump(exclude_none=True).items()}}
    if new["origin"] == new["dest"]:
        raise HTTPException(422, "Origin and destination must differ")
    need_airports(conn, new["origin"], new["dest"])
    try:
        conn.execute(UPDATE_LEG, dict(id=leg_id, date=new["flight_date"], o=new["origin"], d=new["dest"], fn=new["flight_number"], note=new["note"]))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That flight is already in the logbook")
    return {"id": leg_id}

@app.delete("/api/legs/{leg_id}", status_code=204)
def delete_leg(leg_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    row = conn.execute("""DELETE FROM legs WHERE id = %s AND logbook_id IN
                          (SELECT logbook_id FROM logbook_members WHERE user_id = %s) RETURNING id""", (leg_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Flight not found")

@app.get("/api/logbooks/{lb}/stats")
def stats(lb: int, year: int | None = None, user=Depends(current_user), conn=Depends(get_conn)):
    role_in(conn, lb, user)
    p = {"lb": lb, "year": year}
    return {"summary": conn.execute(STATS["summary"], p).fetchone(),
            "top_routes": conn.execute(STATS["top_routes"], p).fetchall(),
            "top_airports": conn.execute(STATS["top_airports"], p).fetchall(),
            "by_year": conn.execute(STATS["by_year"], {"lb": lb, "year": None}).fetchall()}   # always all years, for the filter chips

@app.post("/api/logbooks/{lb}/import-ics")
async def import_ics(lb: int, file: UploadFile = File(...), user=Depends(current_user), conn=Depends(get_conn)):
    role_in(conn, lb, user)
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(413, "File too large (5 MB max)")
    return import_events(conn, lb, user["id"], raw.decode("utf-8", errors="replace"))

# ---------- google calendar sync ----------
@app.get("/api/auth/google/connect-url")
def google_connect_url(user=Depends(current_user)):
    if not gcal.is_configured():
        raise HTTPException(503, "Google Calendar sync isn't set up on this server")
    return {"url": gcal.connect_url(user["id"])}

@app.get("/api/auth/google/callback")
def google_callback(code: str | None = None, state: str | None = None, error: str | None = None, conn=Depends(get_conn)):
    uid = gcal.verify_state(state) if state else None
    if error or not code or uid is None:
        return RedirectResponse("/?gcal=error")
    try:
        tok = gcal.exchange_code(code)
        access_token, expires_at = tok["access_token"], gcal.token_expiry(tok)
        email = gcal.email_from_id_token(tok.get("id_token"))
    except (httpx.HTTPError, KeyError):
        return RedirectResponse("/?gcal=error")
    refresh_token = tok.get("refresh_token")
    if not refresh_token:
        existing = conn.execute("SELECT refresh_token FROM google_tokens WHERE user_id = %s", (uid,)).fetchone()
        refresh_token = existing["refresh_token"] if existing else None
    if not refresh_token:
        return RedirectResponse("/?gcal=error")
    conn.execute("""
        INSERT INTO google_tokens (user_id, refresh_token, access_token, expires_at, google_email)
        VALUES (%(uid)s, %(rt)s, %(at)s, %(exp)s, %(email)s)
        ON CONFLICT (user_id) DO UPDATE SET
          refresh_token = %(rt)s, access_token = %(at)s, expires_at = %(exp)s, google_email = %(email)s
        """, {"uid": uid, "rt": refresh_token, "at": access_token, "exp": expires_at, "email": email})
    return RedirectResponse("/?gcal=connected")

@app.get("/api/me/google")
def google_status(user=Depends(current_user), conn=Depends(get_conn)):
    row = conn.execute("SELECT google_email, last_synced_at FROM google_tokens WHERE user_id = %s", (user["id"],)).fetchone()
    return {"connected": bool(row), "email": row["google_email"] if row else None,
            "last_synced_at": row["last_synced_at"] if row else None}

@app.delete("/api/me/google", status_code=204)
def google_disconnect(user=Depends(current_user), conn=Depends(get_conn)):
    row = conn.execute("DELETE FROM google_tokens WHERE user_id = %s RETURNING refresh_token", (user["id"],)).fetchone()
    if row:
        gcal.revoke(row["refresh_token"])

@app.post("/api/logbooks/{lb}/sync-calendar")
def sync_calendar(lb: int, user=Depends(current_user), conn=Depends(get_conn)):
    role_in(conn, lb, user)
    try:
        return gcal.sync_user_calendar(conn, lb, user["id"])
    except gcal.NotConnected:
        raise HTTPException(409, "Connect your Google Calendar first")
    except gcal.ReauthRequired:
        raise HTTPException(409, "Your Google Calendar connection expired -- reconnect it")
    except httpx.HTTPError:
        raise HTTPException(502, "Couldn't reach Google -- try again in a bit")

# ---------- misc ----------
@app.get("/api/airports")
def airports(q: str = Query(min_length=2, max_length=40), conn=Depends(get_conn)):
    return conn.execute("""SELECT iata, name, city, country FROM airports
                           WHERE iata = upper(%(q)s) OR city ILIKE %(like)s OR name ILIKE %(like)s
                           ORDER BY (iata = upper(%(q)s)) DESC, name LIMIT 10""", {"q": q, "like": f"%{q}%"}).fetchall()

@app.get("/api/health")
def health(conn=Depends(get_conn)):
    conn.execute("SELECT 1")
    return {"ok": True}

app.mount("/", StaticFiles(directory=pathlib.Path(__file__).parent.parent / "static", html=True), name="static")
