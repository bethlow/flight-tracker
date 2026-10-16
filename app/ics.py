"""Import flights from a Google Calendar export (.ics). Same rules as phase 1, but writing to Postgres."""
import re
from .legs import insert_leg

PATTERNS = [
    re.compile(r"Flight: (?P<fn>\w\w ?\d+) from (?P<o>[A-Z]{3}) to (?P<d>[A-Z]{3})"),
    re.compile(r"(?P<fn>[A-Z0-9]{2}\s?\d+)?.*?\|\s*(?P<o>[A-Z]{3}) to (?P<d>[A-Z]{3})"),
]
TO_CITY = re.compile(r"Flight to (?P<city>[^(]+?)\s*\((?P<fn>[\w ]+)\)")

# When an event only says "Flight to <city>" and several airports match, pick here. Edit to taste.
CITY_HINTS = {"New York": "JFK", "New York City": "LGA", "London": "LHR", "Houston": "HOU",
              "Washington": "DCA", "Mexico City": "MEX", "Madrid": "MAD", "Barcelona": "BCN",
              "Detroit": "DTW", "Santo Domingo": "SDQ", "Copenhagen": "CPH", "Columbus": "CMH",
              "Chicago": "ORD", "Portland": "PDX"}

def parse_events(text):
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n[ \t]", "", text)                                 # unfold wrapped lines
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", text, re.S):
        ev = {}
        for line in block.split("\n"):
            key, _, val = line.partition(":")
            ev.setdefault(key.split(";")[0], val.replace("\\,", ",").replace("\\n", " ").strip())
        if "DTSTART" in ev and "SUMMARY" in ev:
            d = ev["DTSTART"][:8]
            yield f"{d[:4]}-{d[4:6]}-{d[6:8]}", ev["SUMMARY"], ev.get("LOCATION", "")

def city_to_iata(conn, city, lb):
    city = city.split(",")[0].strip()
    if city in CITY_HINTS:
        return CITY_HINTS[city]
    rows = conn.execute("SELECT iata, name FROM airports WHERE lower(city) = lower(%s)", (city,)).fetchall()
    if len(rows) == 1:
        return rows[0]["iata"]
    intl = [r["iata"] for r in rows if "International" in r["name"] or "Intercontinental" in r["name"]]
    if len(intl) == 1:
        return intl[0]
    used = {r["i"] for r in conn.execute("SELECT origin AS i FROM legs WHERE logbook_id=%s UNION SELECT dest FROM legs WHERE logbook_id=%s", (lb, lb))}
    seen = [r["iata"] for r in rows if r["iata"] in used]
    return seen[0] if len(seen) == 1 else None

def import_events(conn, lb, uid, text):
    return import_items(conn, lb, uid, parse_events(text))

def import_items(conn, lb, uid, items):
    """Same import rules, for events from any source (.ics text or the Google Calendar API)."""
    events = sorted(items, key=lambda e: not any(p.search(e[1]) for p in PATTERNS))  # explicit ones first
    added = dup = 0
    review = []
    for date, summary, loc in events:
        m = next((p.search(summary) for p in PATTERNS if p.search(summary)), None)
        if m:
            o, d, fn = m["o"], m["d"], (m["fn"] or "").strip()
        else:
            m = TO_CITY.search(summary)
            codes = re.findall(r"\b[A-Z]{3}\b", loc)
            if not m or not codes:
                continue                                                  # not a flight we understand
            o, d, fn = codes[-1], city_to_iata(conn, m["city"], lb), m["fn"]
            if d is None:
                review.append({"date": date, "summary": summary}); continue
        known = {r["iata"] for r in conn.execute("SELECT iata FROM airports WHERE iata = ANY(%s)", ([o, d],))}
        if o == d or not {o, d} <= known:
            review.append({"date": date, "summary": summary}); continue
        if fn and conn.execute("SELECT 1 FROM legs WHERE logbook_id=%s AND flight_date=%s AND origin=%s AND replace(flight_number,' ','')=replace(%s,' ','')",
                               (lb, date, o, fn)).fetchone():
            dup += 1; continue                                            # same flight number already recorded
        if insert_leg(conn, lb, uid, date, o, d, fn, "", "calendar"):
            added += 1
        else:
            dup += 1
    return {"added": added, "duplicates": dup, "needs_review": review}
