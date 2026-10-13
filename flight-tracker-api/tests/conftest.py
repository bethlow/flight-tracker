import os
import psycopg, pytest

ADMIN = "postgresql://app:app@localhost/postgres"
TEST_URL = "postgresql://app:app@localhost/flights_test"
os.environ["DATABASE_URL"] = TEST_URL          # must be set before the app is imported
os.environ["JWT_SECRET"] = "test-secret"

@pytest.fixture(scope="session")
def client():
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS flights_test WITH (FORCE)")
        c.execute("CREATE DATABASE flights_test")
    from app import migrate, seed
    from app.main import app
    from fastapi.testclient import TestClient
    migrate.run(TEST_URL)
    with psycopg.connect(TEST_URL) as c:
        seed.load_airports(c)
    with TestClient(app) as tc:
        yield tc

def signup(client, email, name="Test"):
    r = client.post("/api/auth/register", json={"email": email, "password": "correct horse", "name": name})
    assert r.status_code == 201, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    lb = client.get("/api/me", headers=h).json()["logbooks"][0]["id"]
    return h, lb
