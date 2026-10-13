# Flight tracker, phase 2: API, auth, sharing, deploy

FastAPI + Postgres. You and your partner share one logbook. Everything is plain SQL (no ORM) so you can read exactly what runs.

## Layout
- `migrations/001_init.sql`  the schema (users, airports, logbooks, logbook_members, invites, legs). Read this first.
- `app/legs.py`      all flight SQL: insert, update, list, and the four stats queries (distance is computed inside Postgres)
- `app/main.py`      the API routes
- `app/auth.py`      password hashing (scrypt) and login tokens (JWT)
- `app/ics.py`       Google Calendar (.ics) import, same rules as phase 1
- `app/migrate.py`   applies new `migrations/*.sql` files once each
- `app/seed.py`      loads airports (and optionally your past flights)
- `static/index.html` the web page (login, flights, stats, invite, import)
- `tests/`           6 tests that run against a real Postgres

## Run locally
    createdb flights                       # needs Postgres installed; or use any Postgres URL
    cp .env.example .env                   # then edit DATABASE_URL / JWT_SECRET
    pip install -r requirements.txt
    export $(grep -v '^#' .env | xargs)    # or just: export APP_ENV=dev DATABASE_URL=...
    python -m app.migrate && python -m app.seed
    uvicorn app.main:app --reload          # open http://localhost:8000
    # after you register in the page, load your 119 past flights:
    python -m app.seed --legs data/legs.json --email you@example.com
    python -m pytest                       # needs a Postgres user "app" that can create databases; see tests/conftest.py

## API (all under /api; JSON; send `Authorization: Bearer <token>`)
| Method | Path | What |
|---|---|---|
| POST | /auth/register, /auth/login | returns a token |
| GET | /me | you + your logbooks + members |
| POST | /logbooks/{id}/invites | owner makes a 7-day invite code |
| POST | /invites/{code}/accept | join someone's logbook |
| GET/POST | /logbooks/{id}/legs | list (optional ?year=) / add a flight |
| PATCH/DELETE | /legs/{id} | edit / remove |
| GET | /logbooks/{id}/stats | totals, top routes, top airports, per year |
| POST | /logbooks/{id}/import-ics | upload a calendar export |
| GET | /airports?q=lisbon | airport search |

Interactive docs while it runs: /docs

## SQL ideas to practice here
- Rewrite `top_airports` in `app/legs.py` using a CTE instead of a subquery.
- Add `002_flight_times.sql`: departure/arrival timestamps with time zones (airports already have `tz`).
- Add an index and use `EXPLAIN ANALYZE` to see the planner use it.
- Turn the route stats into a database VIEW.

## Known gaps (on purpose, for later)
- The map dashboard isn't ported into `static/index.html` yet (phase 2b).
- No login rate-limiting, password reset, or email verification.
- The login token lives in the browser's localStorage: fine for a personal app, not for anything sensitive.
