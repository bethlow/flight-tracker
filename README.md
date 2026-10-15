# Flight tracker, phase 2: API, auth, sharing, deploy

FastAPI + Postgres. You and your partner share one logbook. Everything is plain SQL (no ORM) so you can read exactly what runs.

## Using the dashboard

Once the app is running (see [Run locally](#run-locally) below) and you've opened it in a browser:

1. **Create an account.** Enter your name, email, and a password (8+ characters), then click "Create account". This also creates your own logbook — the shared trip log you and a partner will add flights to.
2. **Sign in next time** with just your email and password.
3. **Invite your partner.** Click "Invite partner" to generate a code that's valid for 7 days, then send it to them however you like (text, email, etc).
4. **Accept an invite.** If someone sent you a code, paste it into "Have an invite code?" and click "Join" — you'll now share their logbook instead of your own.
5. **Add a flight.** Fill in the origin and destination airport codes (IATA, e.g. `BOS`, `LIS`), the date, and an optional flight number/note, then "Save flight".
6. **Or import flights in bulk.** If you have a calendar export (`.ics`) with your flights on it, use "import calendar" instead of entering them one by one. Duplicates are skipped automatically.
   - **Or connect Google Calendar.** Under "⚙ Account", click "Connect Google Calendar", sign in with Google, and grant read-only calendar access. Click "Sync now" any time afterward to pull in new flights — same duplicate-skipping rules apply. Needs `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` set on the server (see `.env.example`), or the button shows an error when clicked.
7. **Check your stats and map.** Totals (flights, miles, places, countries), top routes, top airports, and a map of everywhere you've flown update automatically as you add flights. Use the year chips above the stats to filter to a single year.
8. **Edit or delete a flight.** Click any flight in the "Flights" list to edit it, or the ✕ next to it to remove it.

## Layout
- `migrations/001_init.sql`  the schema (users, airports, logbooks, logbook_members, invites, legs). Read this first.
- `migrations/002_google_calendar.sql`  adds `google_tokens`, one row per user who's connected their Google account.
- `app/legs.py`      all flight SQL: insert, update, list, and the four stats queries (distance is computed inside Postgres)
- `app/main.py`      the API routes
- `app/auth.py`      password hashing (scrypt) and login tokens (JWT)
- `app/ics.py`       calendar import rules (flight parsing + de-dup), shared by the `.ics` upload and the live Google sync
- `app/gcal.py`      Google OAuth (connect/callback, token refresh) and pulling events from the Calendar API
- `app/migrate.py`   applies new `migrations/*.sql` files once each
- `app/seed.py`      loads airports (and optionally your past flights)
- `static/index.html` the web page (login, flights, stats, map, invite, import). Map tiles/markers use Leaflet, loaded from a CDN — needs internet on first load.
- `tests/`           tests that run against a real Postgres

## Run locally

Needs Postgres and Python 3.10+ installed.

1. Create the database:

       createdb flights                       # or point DATABASE_URL at any Postgres you have

2. Set up your environment file:

       cp .env.example .env                   # then edit DATABASE_URL / JWT_SECRET to match your setup

3. Install dependencies (a virtualenv is recommended):

       python3 -m venv .venv && source .venv/bin/activate
       pip install -r requirements.txt

4. Load the environment, then set up the database schema and reference data (airports):

       export $(grep -v '^#' .env | xargs)    # or just: export APP_ENV=dev DATABASE_URL=...
       python -m app.migrate && python -m app.seed

5. Start the server:

       uvicorn app.main:app --reload          # open http://localhost:8000

   From here, follow [Using the dashboard](#using-the-dashboard) above to create an account.

6. Optional: once you've registered, load your own past flights from a JSON file:

       python -m app.seed --legs data/legs.json --email you@example.com

7. Run the tests (needs a Postgres user named "app" that can create databases — see `tests/conftest.py`):

       python -m pytest

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
| GET | /auth/google/connect-url | Google OAuth URL to start a connection |
| GET/DELETE | /me/google | connection status / disconnect |
| POST | /logbooks/{id}/sync-calendar | pull new flights from the connected Google Calendar |
| GET | /airports?q=lisbon | airport search |

Interactive docs while it runs: /docs

## SQL ideas to practice here
- Rewrite `top_airports` in `app/legs.py` using a CTE instead of a subquery.
- Add `002_flight_times.sql`: departure/arrival timestamps with time zones (airports already have `tz`).
- Add an index and use `EXPLAIN ANALYZE` to see the planner use it.
- Turn the route stats into a database VIEW.

## Known gaps (on purpose, for later)
- No login rate-limiting, password reset, or email verification.
- The login token lives in the browser's localStorage: fine for a personal app, not for anything sensitive.
