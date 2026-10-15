import httpx, jwt
from app import gcal
from .conftest import signup

LEG = {"flight_date": "2020-03-01", "origin": "bos", "dest": "LAX", "flight_number": "B6 1187"}

def test_auth_basics(client):
    assert client.get("/api/me").status_code == 401
    h, _ = signup(client, "a@example.com", "Ann")
    assert client.get("/api/me", headers=h).json()["user"]["email"] == "a@example.com"
    assert client.post("/api/auth/register", json={"email": "A@example.com", "password": "correct horse", "name": "x"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "A@Example.com", "password": "correct horse"})
    assert ok.status_code == 200 and ok.json()["token"]
    assert client.post("/api/auth/register", json={"email": "bad", "password": "short", "name": "x"}).status_code == 422
    assert client.get("/api/me", headers={"Authorization": "Bearer junk"}).status_code == 401

def test_leg_crud_and_distance(client):
    h, lb = signup(client, "b@example.com")
    r = client.post(f"/api/logbooks/{lb}/legs", json=LEG, headers=h)
    assert r.status_code == 201
    leg_id = r.json()["id"]
    assert client.post(f"/api/logbooks/{lb}/legs", json=LEG, headers=h).status_code == 409          # duplicate
    assert client.post(f"/api/logbooks/{lb}/legs", json={**LEG, "dest": "ZZZ"}, headers=h).status_code == 422
    assert client.post(f"/api/logbooks/{lb}/legs", json={**LEG, "dest": "BOS"}, headers=h).status_code == 422
    legs = client.get(f"/api/logbooks/{lb}/legs", headers=h).json()
    assert len(legs) == 1 and legs[0]["origin"] == "BOS" and 2600 < legs[0]["distance_mi"] < 2625
    assert legs[0]["origin_city"] == "Boston"
    assert client.patch(f"/api/legs/{leg_id}", json={"dest": "SFO"}, headers=h).status_code == 200
    legs = client.get(f"/api/logbooks/{lb}/legs", headers=h).json()
    assert legs[0]["dest"] == "SFO" and 2680 < legs[0]["distance_mi"] < 2710          # distance recomputed in SQL
    assert client.delete(f"/api/legs/{leg_id}", headers=h).status_code == 204
    assert client.delete(f"/api/legs/{leg_id}", headers=h).status_code == 404

def test_stats_only_count_past_flights(client):
    h, lb = signup(client, "c@example.com")
    for d, o, t in [("2019-05-01", "BOS", "CLE"), ("2019-05-04", "CLE", "BOS"), ("2020-06-01", "BOS", "LIS"), ("2099-01-01", "BOS", "LHR")]:
        assert client.post(f"/api/logbooks/{lb}/legs", json={"flight_date": d, "origin": o, "dest": t}, headers=h).status_code == 201
    s = client.get(f"/api/logbooks/{lb}/stats", headers=h).json()
    assert s["summary"]["flights"] == 3 and s["summary"]["countries"] == 2           # 2099 flight not counted yet
    assert s["top_routes"][0] == {"a": "BOS", "b": "CLE", "flights": 2}
    assert [y["year"] for y in s["by_year"]] == [2019, 2020]
    s19 = client.get(f"/api/logbooks/{lb}/stats?year=2019", headers=h).json()
    assert s19["summary"]["flights"] == 2 and len(s19["by_year"]) == 2                # chips still show every year
    assert len(client.get(f"/api/logbooks/{lb}/legs", headers=h).json()) == 4         # but the list includes the future trip

def test_layovers_vs_round_trips(client):
    h, lb = signup(client, "layover@example.com")
    # a same-day round trip (there and back) is not a layover -- both legs' dests are real,
    # non-layover arrivals (CLE outbound, home BOS on the way back), so both count as "places"
    for d, o, t in [("2021-01-01", "BOS", "CLE"), ("2021-01-01", "CLE", "BOS")]:
        assert client.post(f"/api/logbooks/{lb}/legs", json={"flight_date": d, "origin": o, "dest": t}, headers=h).status_code == 201
    s = client.get(f"/api/logbooks/{lb}/stats", headers=h).json()["summary"]
    assert s["places"] == 2 and s["countries"] == 1 and s["layovers"] == 0

    # a same-day connection onward to a third city is a layover -- JFK wasn't really visited
    for d, o, t in [("2021-02-01", "BOS", "JFK"), ("2021-02-01", "JFK", "LHR")]:
        assert client.post(f"/api/logbooks/{lb}/legs", json={"flight_date": d, "origin": o, "dest": t}, headers=h).status_code == 201
    s = client.get(f"/api/logbooks/{lb}/stats", headers=h).json()["summary"]
    assert s["places"] == 3 and s["countries"] == 2 and s["layovers"] == 1
    assert "JFK" not in [a["iata"] for a in client.get(f"/api/logbooks/{lb}/stats", headers=h).json()["top_airports"]]

def test_sharing_and_isolation(client):
    ha, lb = signup(client, "owner@example.com", "Owner")
    hp, _ = signup(client, "partner@example.com", "Partner")
    ho, _ = signup(client, "outsider@example.com", "Outsider")
    client.post(f"/api/logbooks/{lb}/legs", json=LEG, headers=ha)
    assert client.get(f"/api/logbooks/{lb}/legs", headers=hp).status_code == 404       # not a member yet
    assert client.post(f"/api/logbooks/{lb}/invites", headers=hp).status_code == 404
    code = client.post(f"/api/logbooks/{lb}/invites", headers=ha).json()["code"]
    assert client.post(f"/api/invites/{code}/accept", headers=hp).status_code == 200
    assert len(client.get(f"/api/logbooks/{lb}/legs", headers=hp).json()) == 1          # partner sees it
    leg = client.get(f"/api/logbooks/{lb}/legs", headers=hp).json()[0]["id"]
    assert client.patch(f"/api/legs/{leg}", json={"note": "partner edit"}, headers=hp).status_code == 200
    assert client.post(f"/api/logbooks/{lb}/invites", headers=hp).status_code == 403    # members can't invite
    assert client.get(f"/api/logbooks/{lb}/legs", headers=ho).status_code == 404        # outsider sees nothing
    assert client.delete(f"/api/legs/{leg}", headers=ho).status_code == 404
    assert client.patch(f"/api/legs/{leg}", json={"note": "hax"}, headers=ho).status_code == 404
    assert client.post("/api/invites/nope/accept", headers=ho).status_code == 404
    members = client.get("/api/me", headers=ha).json()["logbooks"][0]["members"]
    assert [m["name"] for m in members] == ["Owner", "Partner"]

ICS = "\r\n".join(["BEGIN:VCALENDAR",
  "BEGIN:VEVENT", "DTSTART;VALUE=DATE:20240518", "SUMMARY:Flight: B6 541 from BOS to CLE", "LOCATION:Boston", "END:VEVENT",
  "BEGIN:VEVENT", "DTSTART;VALUE=DATE:20240523", "SUMMARY:Flight to Boston (B6 640)", "LOCATION:Cleveland CLE", "END:VEVENT",
  "BEGIN:VEVENT", "DTSTART;VALUE=DATE:20240601", "SUMMARY:Dentist", "END:VEVENT",
  "BEGIN:VEVENT", "DTSTART;VALUE=DATE:20240701", "SUMMARY:Flight to Springfield (XX 1)", "LOCATION:Boston BOS", "END:VEVENT",
  "END:VCALENDAR"])

def test_ics_import(client):
    h, lb = signup(client, "d@example.com")
    f = {"file": ("cal.ics", ICS, "text/calendar")}
    r = client.post(f"/api/logbooks/{lb}/import-ics", files=f, headers=h).json()
    assert r["added"] == 2 and r["duplicates"] == 0 and len(r["needs_review"]) == 1      # Springfield is ambiguous
    again = client.post(f"/api/logbooks/{lb}/import-ics", files={"file": ("cal.ics", ICS, "text/calendar")}, headers=h).json()
    assert again["added"] == 0 and again["duplicates"] == 2                               # safe to re-run
    routes = {(l["origin"], l["dest"]) for l in client.get(f"/api/logbooks/{lb}/legs", headers=h).json()}
    assert routes == {("BOS", "CLE"), ("CLE", "BOS")}

def test_google_calendar_not_configured(client):
    h, lb = signup(client, "e@example.com")
    assert client.get("/api/auth/google/connect-url", headers=h).status_code == 503       # no GOOGLE_CLIENT_ID in test env
    assert client.post(f"/api/logbooks/{lb}/sync-calendar", headers=h).status_code == 409 # not connected either way

def test_google_calendar_callback_rejects_bad_state(client):
    r = client.get("/api/auth/google/callback?code=abc&state=garbage", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/?gcal=error"
    r = client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.headers["location"] == "/?gcal=error"

def test_google_calendar_connect_and_sync(client, monkeypatch):
    h, lb = signup(client, "f@example.com")
    uid = client.get("/api/me", headers=h).json()["user"]["id"]

    monkeypatch.setattr(gcal, "exchange_code", lambda code: {
        "access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "id_token": None})
    state = jwt.encode({"uid": uid, "exp": 9999999999}, "test-secret", algorithm="HS256")
    r = client.get(f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/?gcal=connected"
    assert client.get("/api/me/google", headers=h).json() == {"connected": True, "email": None, "last_synced_at": None}

    events = [
        {"start": {"date": "2024-05-01"}, "summary": "Flight: B6 541 from BOS to CLE", "location": "Boston"},
        {"start": {"dateTime": "2024-06-01T10:00:00Z"}, "summary": "Dentist"},                  # not a flight, ignored
    ]
    monkeypatch.setattr(gcal, "get_valid_access_token", lambda conn, user_id, row: "AT")
    monkeypatch.setattr(gcal, "fetch_events", lambda access_token, **kw: events)
    r = client.post(f"/api/logbooks/{lb}/sync-calendar", headers=h)
    assert r.json() == {"added": 1, "duplicates": 0, "needs_review": []}
    legs = client.get(f"/api/logbooks/{lb}/legs", headers=h).json()
    assert len(legs) == 1 and (legs[0]["origin"], legs[0]["dest"]) == ("BOS", "CLE") and legs[0]["source"] == "calendar"
    assert client.get("/api/me/google", headers=h).json()["last_synced_at"] is not None

    # a reauth-needed failure (Google rejects the token) surfaces as 409 and clears the connection
    def boom(conn, user_id, row):
        raise httpx.HTTPStatusError("bad", request=None, response=httpx.Response(400, request=httpx.Request("GET", "https://x")))
    monkeypatch.setattr(gcal, "get_valid_access_token", boom)
    r = client.post(f"/api/logbooks/{lb}/sync-calendar", headers=h)
    assert r.status_code == 409
    assert client.get("/api/me/google", headers=h).json()["connected"] is False

    assert client.delete("/api/me/google", headers=h).status_code == 204
    assert client.get("/api/me/google", headers=h).json()["connected"] is False

def test_events_to_items_handles_all_day_and_timed_events():
    events = [{"start": {"date": "2024-05-01"}, "summary": "a", "location": "x"},
              {"start": {"dateTime": "2024-06-02T10:00:00Z"}, "summary": "b", "location": "y"},
              {"start": {}, "summary": "no date"}]
    assert list(gcal.events_to_items(events)) == [("2024-05-01", "a", "x"), ("2024-06-02", "b", "y")]

def test_airport_search_and_health(client):
    assert client.get("/api/health").json() == {"ok": True}
    r = client.get("/api/airports?q=bos").json()
    assert r[0]["iata"] == "BOS"
    assert any(a["iata"] == "LIS" for a in client.get("/api/airports?q=lisbon").json())
    assert client.get("/api/airports?q=b").status_code == 422
