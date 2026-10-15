import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost/flights")
JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    if os.environ.get("APP_ENV") == "dev":
        JWT_SECRET = "dev-only-secret"
    else:
        raise RuntimeError("Set JWT_SECRET (or APP_ENV=dev for local development).")
TOKEN_DAYS = 30

# Google Calendar sync (optional): unset until a user connects their calendar, so local
# dev and tests work without it. Create credentials at console.cloud.google.com.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
