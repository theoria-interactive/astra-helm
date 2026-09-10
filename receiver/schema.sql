CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY NOT NULL,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  ingested_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS events_ingested_at_idx ON events (ingested_at);
