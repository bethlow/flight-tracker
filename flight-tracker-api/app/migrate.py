"""Applies migrations/*.sql in order, once each. Run: python -m app.migrate"""
import pathlib, psycopg
from .config import DATABASE_URL

def run(url=DATABASE_URL):
    files = sorted((pathlib.Path(__file__).parent.parent / "migrations").glob("*.sql"))
    with psycopg.connect(url) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        for f in files:
            if f.name in done: continue
            conn.execute(f.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,))
            print("applied", f.name)

if __name__ == "__main__":
    run()
