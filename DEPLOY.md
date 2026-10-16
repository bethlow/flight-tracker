# Deploying (Neon Postgres + Render)

Free tiers and menus change, so check each site for current limits and screens. The shape stays the same:
**a database somewhere + a container that runs this repo + two secret settings.**

## 1. Put the code on GitHub
    git init && git add . && git commit -m "flight tracker"
    # create an empty repo on github.com, then:
    git remote add origin <your repo url> && git push -u origin main
(`.gitignore` already keeps `.env` out. Never commit secrets.)

## 2. Database: Neon (hosted Postgres)
1. Create a project at neon.tech.
2. Copy the **connection string** (looks like `postgresql://user:pass@host/dbname?sslmode=require`). Keep `sslmode=require`.

## 3. App: Render (runs the Dockerfile)
1. New -> Web Service -> connect your GitHub repo. Runtime: **Docker**.
2. Environment variables:
   - `DATABASE_URL` = the Neon string
   - `JWT_SECRET`   = output of `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
   - Optional, for Google Calendar sync: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and
     `GOOGLE_REDIRECT_URI` = `https://<your-service>.onrender.com/api/auth/google/callback`
     (add that same URL to the OAuth client's "Authorized redirect URIs" in Google Cloud Console).
3. Health check path: `/api/health`.
4. Deploy. On each start the container runs `python -m app.migrate` (creates tables), `python -m app.seed` (loads airports), then the server.
5. Open your `*.onrender.com` URL, create your account, and invite your partner from the page.

## 4. Load your flights
Easiest: in the page, use **import calendar (.ics)** with your Google Calendar export.
Or load the 119 flights from phase 1 from your own computer:

    DATABASE_URL='<neon string>' JWT_SECRET=x python -m app.seed --legs data/legs.json --email you@example.com

## 5. Changing the database later
Never edit tables by hand. Add `migrations/002_something.sql`, commit, push; the next deploy applies it once.

## Things to learn from the first deploy
- Read the build and runtime logs in Render when something fails (most failures are a missing env var).
- Free web services usually sleep when idle, so the first request after a break is slow.
- Look at your Neon dashboard for backups and branching, and try a restore on a throwaway branch.
- HTTPS comes from the host (and your custom domain, if you add one); the app itself only speaks plain HTTP inside.
