"""Loads reference data. Safe to run repeatedly.
    python -m app.seed                                   # airports only
    python -m app.seed --legs data/legs.json --email me@example.com   # also load your past flights
"""
import argparse, csv, json, pathlib
import psycopg
from psycopg.rows import dict_row
from .config import DATABASE_URL
from .legs import insert_leg

DATA = pathlib.Path(__file__).parent.parent / "data"
EXTRA = [("NLU", "Felipe Angeles International Airport", "Mexico City", "Mexico", 19.7457, -99.0158, "America/Mexico_City")]

def load_airports(conn):
    rows = list(EXTRA)
    with open(DATA / "airports.dat", newline="", encoding="utf-8") as f:
        for r in csv.reader(f):
            if len(r[4]) == 3 and r[4].isalpha() and r[12] == "airport":
                rows.append((r[4].upper(), r[1], r[2], r[3], float(r[6]), float(r[7]), r[11]))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO airports (iata,name,city,country,lat,lon,tz) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)

def load_legs(conn, email, path):
    row = conn.execute("""SELECT m.logbook_id, m.user_id FROM users u JOIN logbook_members m ON m.user_id = u.id AND m.role = 'owner'
                          WHERE u.email = %s ORDER BY m.logbook_id LIMIT 1""", (email.lower(),)).fetchone()
    if not row:
        raise SystemExit(f"No user {email}. Register in the app first, then re-run.")
    n = 0
    for date, o, d, fn in json.load(open(path)):
        fn = (fn[:2] + " " + fn[2:]) if fn else ""
        n += bool(insert_leg(conn, row["logbook_id"], row["user_id"], date, o, d, fn, "", "calendar"))
    print(f"loaded {n} flights")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--legs"); ap.add_argument("--email")
    a = ap.parse_args()
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        load_airports(conn)
        if a.legs:
            load_legs(conn, a.email, a.legs)
