-- Each user can connect their own Google account. One row per user; tokens let the
-- server pull calendar events without the user present (a scheduled sync, eventually).
CREATE TABLE google_tokens (
  user_id        BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  refresh_token  TEXT NOT NULL,
  access_token   TEXT,
  expires_at     TIMESTAMPTZ,
  google_email   TEXT,
  last_synced_at TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
