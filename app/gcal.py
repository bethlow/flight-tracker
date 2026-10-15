"""Google Calendar sync: each user connects their own calendar (OAuth), then the app
can pull flight events from it on demand via a 'Sync now' button (or, eventually, a
scheduler -- sync_user_calendar below has no FastAPI dependency so it can be called
the same way from either)."""
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt

from .config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, JWT_SECRET
from .ics import import_items

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/events"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly openid email"
HISTORY_FLOOR = "1990-01-01T00:00:00Z"   # "as far back as possible" -- Calendar API needs some lower bound
RESYNC_OVERLAP = timedelta(days=7)       # re-check the last week on every sync, in case an old event got edited

class NotConnected(Exception):
    pass

class ReauthRequired(Exception):
    """The stored refresh token was rejected by Google (revoked, expired from disuse, ...). The
    caller's row has already been deleted, so the user shows as disconnected and can reconnect."""

def is_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

def connect_url(user_id):
    """A short-lived signed state ties the callback (which Google calls with no auth header) back to this user."""
    state = jwt.encode({"uid": user_id, "exp": int(time.time()) + 600}, JWT_SECRET, algorithm="HS256")
    params = {
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"

def verify_state(state):
    try:
        return int(jwt.decode(state, JWT_SECRET, algorithms=["HS256"])["uid"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None

def _token_request(**data):
    r = httpx.post(TOKEN_URL, data={"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, **data}, timeout=15)
    r.raise_for_status()
    return r.json()

def exchange_code(code):
    return _token_request(code=code, redirect_uri=GOOGLE_REDIRECT_URI, grant_type="authorization_code")

def refresh_access_token(refresh_token):
    return _token_request(refresh_token=refresh_token, grant_type="refresh_token")

def token_expiry(tok):
    return datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600))

def revoke(refresh_token):
    """Best-effort: tells Google to invalidate the grant. The local row is removed either way."""
    try:
        httpx.post(REVOKE_URL, params={"token": refresh_token}, timeout=10)
    except httpx.HTTPError:
        pass

def email_from_id_token(id_token):
    if not id_token:
        return None
    try:
        # Safe to skip signature verification: id_token came straight from Google's token endpoint
        # over a server-to-server call (not user-supplied), and the email is display-only, never
        # used for authorization.
        return jwt.decode(id_token, options={"verify_signature": False}).get("email")
    except jwt.PyJWTError:
        return None

def get_valid_access_token(conn, user_id, row):
    """Returns a usable access token, refreshing it first if needed. May raise httpx.HTTPStatusError."""
    if row["access_token"] and row["expires_at"] and row["expires_at"] > datetime.now(timezone.utc) + timedelta(minutes=1):
        return row["access_token"]
    tok = refresh_access_token(row["refresh_token"])
    expires_at = token_expiry(tok)
    new_refresh = tok.get("refresh_token")   # Google doesn't always rotate it, but persist it when it does
    if new_refresh:
        conn.execute("UPDATE google_tokens SET access_token = %s, expires_at = %s, refresh_token = %s WHERE user_id = %s",
                     (tok["access_token"], expires_at, new_refresh, user_id))
    else:
        conn.execute("UPDATE google_tokens SET access_token = %s, expires_at = %s WHERE user_id = %s",
                     (tok["access_token"], expires_at, user_id))
    return tok["access_token"]

def fetch_events(access_token, time_min=HISTORY_FLOOR):
    events, page_token = [], None
    while True:
        params = {"calendarId": "primary", "singleEvents": "true", "maxResults": 2500,
                   "timeMin": time_min, "orderBy": "startTime"}
        if page_token:
            params["pageToken"] = page_token
        r = httpx.get(EVENTS_URL, params=params, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        events += data.get("items", [])
        page_token = data.get("nextPageToken")
        if not page_token:
            return events

def events_to_items(events):
    """Shape Calendar API events into the (date, summary, location) tuples app/ics.py's import rules expect."""
    for ev in events:
        start = ev.get("start", {})
        d = start.get("date") or (start.get("dateTime") or "")[:10]
        if d:
            yield d, ev.get("summary", ""), ev.get("location", "")

def sync_user_calendar(conn, lb, uid):
    """Pulls new flights from this user's connected Google Calendar into logbook `lb`.
    Raises NotConnected if they haven't connected one, ReauthRequired if Google rejected the
    stored token (so they'll need to reconnect), or httpx.HTTPError for other Google-side failures."""
    row = conn.execute("SELECT access_token, refresh_token, expires_at, last_synced_at FROM google_tokens WHERE user_id = %s", (uid,)).fetchone()
    if not row:
        raise NotConnected
    time_min = (row["last_synced_at"] - RESYNC_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ") if row["last_synced_at"] else HISTORY_FLOOR
    try:
        access_token = get_valid_access_token(conn, uid, row)
        events = fetch_events(access_token, time_min=time_min)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 401):
            conn.execute("DELETE FROM google_tokens WHERE user_id = %s", (uid,))
            conn.commit()   # the route reports this as an error response, which would otherwise roll this back
            raise ReauthRequired from e
        raise
    result = import_items(conn, lb, uid, events_to_items(events))
    conn.execute("UPDATE google_tokens SET last_synced_at = now() WHERE user_id = %s", (uid,))
    return result
