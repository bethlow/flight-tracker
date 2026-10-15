"""All the SQL for flights. The distance is computed by Postgres itself (haversine formula)."""

HAVERSINE = """3958.8 * 2 * asin(sqrt(
    sin(radians(d.lat - o.lat) / 2) ^ 2 +
    cos(radians(o.lat)) * cos(radians(d.lat)) * sin(radians(d.lon - o.lon) / 2) ^ 2))"""

INSERT_LEG = f"""
INSERT INTO legs (logbook_id, flight_date, origin, dest, flight_number, note, source, created_by, distance_mi)
SELECT %(lb)s, %(date)s, o.iata, d.iata, %(fn)s, %(note)s, %(source)s, %(uid)s, round(({HAVERSINE})::numeric, 1)
FROM airports o, airports d WHERE o.iata = %(o)s AND d.iata = %(d)s
ON CONFLICT (logbook_id, flight_date, origin, dest) DO NOTHING
RETURNING id"""

UPDATE_LEG = f"""
UPDATE legs SET flight_date = %(date)s, origin = %(o)s, dest = %(d)s, flight_number = %(fn)s, note = %(note)s,
  distance_mi = (SELECT round(({HAVERSINE})::numeric, 1) FROM airports o, airports d WHERE o.iata = %(o)s AND d.iata = %(d)s)
WHERE id = %(id)s RETURNING id"""

LIST_LEGS = """
SELECT l.id, l.flight_date, l.origin, l.dest, o.city AS origin_city, d.city AS dest_city,
       o.lat AS origin_lat, o.lon AS origin_lon, d.lat AS dest_lat, d.lon AS dest_lon,
       l.flight_number, l.note, l.distance_mi, l.source
FROM legs l JOIN airports o ON o.iata = l.origin JOIN airports d ON d.iata = l.dest
WHERE l.logbook_id = %(lb)s AND (%(year)s::int IS NULL OR EXTRACT(year FROM l.flight_date) = %(year)s)
ORDER BY l.flight_date DESC, l.id DESC"""

# "Been there" stats only count flights up to today; the year filter is optional.
_WHERE = "logbook_id = %(lb)s AND flight_date <= CURRENT_DATE AND (%(year)s::int IS NULL OR EXTRACT(year FROM flight_date) = %(year)s)"

STATS = {
    "summary": f"""
        SELECT COUNT(*) AS flights, COALESCE(round(SUM(distance_mi)), 0)::int AS miles,
               COUNT(DISTINCT dest) AS places, COUNT(DISTINCT a.country) AS countries
        FROM legs JOIN airports a ON a.iata = legs.dest WHERE {_WHERE}""",
    "top_routes": f"""
        SELECT LEAST(origin, dest) AS a, GREATEST(origin, dest) AS b, COUNT(*) AS flights
        FROM legs WHERE {_WHERE} GROUP BY 1, 2 ORDER BY flights DESC, 1, 2 LIMIT 5""",
    "top_airports": f"""
        SELECT iata, COUNT(*) AS visits FROM (
          SELECT origin AS iata FROM legs WHERE {_WHERE} UNION ALL SELECT dest FROM legs WHERE {_WHERE}
        ) t GROUP BY iata ORDER BY visits DESC, iata LIMIT 5""",
    "by_year": f"""
        SELECT EXTRACT(year FROM flight_date)::int AS year, COUNT(*) AS flights, round(SUM(distance_mi))::int AS miles
        FROM legs WHERE {_WHERE} GROUP BY 1 ORDER BY 1""",
}

def insert_leg(conn, lb, uid, date, o, d, fn="", note="", source="manual"):
    """Returns the new leg id, or None if that flight was already in the logbook."""
    row = conn.execute(INSERT_LEG, dict(lb=lb, date=date, o=o, d=d, fn=fn, note=note, source=source, uid=uid)).fetchone()
    return row["id"] if row else None
