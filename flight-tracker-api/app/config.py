import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost/flights")
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    if os.environ.get("APP_ENV") == "dev":
        JWT_SECRET = "dev-only-secret"
    else:
        raise RuntimeError("Set JWT_SECRET (or APP_ENV=dev for local development).")
TOKEN_DAYS = 30
