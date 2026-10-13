CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE airports (
  iata    TEXT PRIMARY KEY CHECK (iata ~ '^[A-Z]{3}$'),
  name    TEXT NOT NULL,
  city    TEXT,
  country TEXT,
  lat     DOUBLE PRECISION NOT NULL,
  lon     DOUBLE PRECISION NOT NULL,
  tz      TEXT
);

-- A logbook is a shared set of flights. You and your partner are both members of one.
CREATE TABLE logbooks (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE logbook_members (
  logbook_id BIGINT NOT NULL REFERENCES logbooks(id) ON DELETE CASCADE,
  user_id    BIGINT NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
  role       TEXT   NOT NULL CHECK (role IN ('owner', 'member')),
  PRIMARY KEY (logbook_id, user_id)
);

CREATE TABLE invites (
  code       TEXT PRIMARY KEY,
  logbook_id BIGINT NOT NULL REFERENCES logbooks(id) ON DELETE CASCADE,
  created_by BIGINT NOT NULL REFERENCES users(id),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE legs (
  id            BIGSERIAL PRIMARY KEY,
  logbook_id    BIGINT NOT NULL REFERENCES logbooks(id) ON DELETE CASCADE,
  flight_date   DATE   NOT NULL,
  origin        TEXT   NOT NULL REFERENCES airports(iata),
  dest          TEXT   NOT NULL REFERENCES airports(iata),
  flight_number TEXT   NOT NULL DEFAULT '',
  note          TEXT   NOT NULL DEFAULT '',
  distance_mi   DOUBLE PRECISION NOT NULL,
  source        TEXT   NOT NULL DEFAULT 'manual',
  created_by    BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (origin <> dest),
  UNIQUE (logbook_id, flight_date, origin, dest)
);
CREATE INDEX idx_legs_logbook_date ON legs (logbook_id, flight_date);
