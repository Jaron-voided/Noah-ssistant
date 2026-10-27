CREATE TABLE IF NOT EXISTS captures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL CHECK(type IN ('note','link','event','task','image')),
    raw        TEXT NOT NULL,
    title      TEXT,
    url        TEXT,
    event_dt   TEXT,
    metadata   TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
