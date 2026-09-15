"""SQLite connection and schema. WAL so the API can read while ingest writes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Denominator: text-bearing posts per minute. Enables share-of-conversation
-- scoring instead of raw counts.
CREATE TABLE IF NOT EXISTS minute_totals (
    minute INTEGER PRIMARY KEY,
    posts  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_minutes (
    minute INTEGER NOT NULL,
    topic  TEXT    NOT NULL,
    hits   INTEGER NOT NULL,
    PRIMARY KEY (minute, topic)
);

CREATE TABLE IF NOT EXISTS matches (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    INTEGER NOT NULL,
    topic TEXT    NOT NULL,
    did   TEXT    NOT NULL,
    rkey  TEXT    NOT NULL,
    lang  TEXT,
    text  TEXT    NOT NULL,
    -- Comma-joined URLs from the post's facets and external embed. The cheapest
    -- explanation there is: the story behind a spike is usually a link.
    links TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_matches_topic_ts ON matches(topic, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket     INTEGER NOT NULL,
    -- The thing that spiked: a topic name, or a term discovered in the stream.
    subject    TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'topic',
    mode       TEXT    NOT NULL DEFAULT 'deep',
    hits       INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    share      REAL    NOT NULL,
    baseline   REAL    NOT NULL,
    zscore     REAL    NOT NULL,
    terms      TEXT    NOT NULL DEFAULT '',
    -- Top URLs shared inside the spiking window. A link is usually the story.
    links      TEXT    NOT NULL DEFAULT '',
    -- Learned probability that this spike holds rather than reverting. NULL
    -- until a model has been fitted, which is the normal state early on.
    confidence REAL,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_identity
    ON alerts(bucket, subject, mode, kind);
CREATE INDEX IF NOT EXISTS idx_alerts_bucket ON alerts(bucket DESC);

-- Terms discovered in the stream itself, rather than matched against a list.
-- Only the heaviest hitters of each minute are kept: a full vocabulary is
-- unbounded, and a term outside the top of its own minute cannot spike anyway.
CREATE TABLE IF NOT EXISTS term_minutes (
    minute INTEGER NOT NULL,
    term   TEXT    NOT NULL,
    hits   INTEGER NOT NULL,
    PRIMARY KEY (minute, term)
);
CREATE INDEX IF NOT EXISTS idx_term_minutes_term ON term_minutes(term, minute);

-- A uniform sample of the stream, used to explain a term spike after the fact.
-- Terms are discovered, not declared, so there is no way to know in advance
-- which posts will be worth keeping. Storing all of them is ~1.7 GB/day;
-- storing a fixed fraction on a short retention is a few tens of megabytes and
-- still leaves hundreds of posts behind any spike worth reading about.
CREATE TABLE IF NOT EXISTS post_samples (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    INTEGER NOT NULL,
    did   TEXT    NOT NULL,
    rkey  TEXT    NOT NULL,
    lang  TEXT,
    text  TEXT    NOT NULL,
    links TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_post_samples_ts ON post_samples(ts);

-- Terms that spiked together, grouped into the story they belong to, and
-- chained across windows so an event has a life rather than a moment. `key`
-- is that chain; (key, mode) is the identity because each horizon sees the
-- same story at its own resolution.
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    key           TEXT    NOT NULL,
    mode          TEXT    NOT NULL,
    terms         TEXT    NOT NULL,
    first_bucket  INTEGER NOT NULL,
    last_bucket   INTEGER NOT NULL,
    buckets       INTEGER NOT NULL DEFAULT 1,
    hits          INTEGER NOT NULL DEFAULT 0,
    zscore        REAL    NOT NULL DEFAULT 0,
    confidence    REAL,
    links         TEXT    NOT NULL DEFAULT '',
    -- The post that said it first, and how little it resembled anything before.
    story_did     TEXT,
    story_rkey    TEXT,
    story_ts      INTEGER,
    story_text    TEXT,
    story_novelty REAL,
    -- How much this resembles an event that already happened. A nightly show
    -- trends every night; that is not news the second time.
    recurrence    REAL,
    recurs_from   TEXT,
    created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_identity ON events(key, mode);
CREATE INDEX IF NOT EXISTS idx_events_last ON events(last_bucket DESC);

-- Bluesky's own trending topics, polled for free from the public API. Ground
-- truth: the only way to say whether this detector found anything real, and
-- how long before or after the platform said so itself.
CREATE TABLE IF NOT EXISTS bsky_trends (
    topic        TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    category     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT '',
    post_count   INTEGER NOT NULL DEFAULT 0,
    started_at   INTEGER,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bsky_trends_seen ON bsky_trends(first_seen DESC);
"""

# Older databases carry an `alerts` table with UNIQUE(bucket, topic) baked into
# the table definition, sometimes a `novelty` column where `terms` now is, and
# no `subject`, `kind`, `mode` or `links`. SQLite cannot drop a constraint or
# rename around one in place, so the table is rebuilt. Alerts are derived data
# and can always be recomputed from counts, so nothing here is precious - the
# rebuild carries rows over out of politeness, not necessity.
REBUILD_ALERTS = """
ALTER TABLE alerts RENAME TO alerts_legacy;

CREATE TABLE alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket     INTEGER NOT NULL,
    subject    TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'topic',
    mode       TEXT    NOT NULL DEFAULT 'deep',
    hits       INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    share      REAL    NOT NULL,
    baseline   REAL    NOT NULL,
    zscore     REAL    NOT NULL,
    terms      TEXT    NOT NULL DEFAULT '',
    links      TEXT    NOT NULL DEFAULT '',
    confidence REAL,
    created_at INTEGER NOT NULL
);

INSERT INTO alerts
    (id, bucket, subject, kind, mode, hits, total, share, baseline, zscore,
     terms, links, created_at)
SELECT id, bucket, {subject}, 'topic', {mode}, hits, total, share, baseline,
       zscore, {terms}, '', created_at
FROM alerts_legacy;

DROP TABLE alerts_legacy;

CREATE UNIQUE INDEX idx_alerts_identity ON alerts(bucket, subject, mode, kind);
CREATE INDEX idx_alerts_bucket ON alerts(bucket DESC);
"""


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _first_column(connection: sqlite3.Connection, table: str, *candidates: str) -> str | None:
    """The first of `candidates` the table actually has. Older builds renamed
    columns, so a migration cannot assume which name it is reading from."""
    for name in candidates:
        if _has_column(connection, table, name):
            return name
    return None


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring an older database up to the current schema.

    Runs before SCHEMA, not after: SCHEMA declares indexes over columns an old
    table does not have, so applying it first fails.
    """
    if _table_exists(connection, "alerts") and not _has_column(connection, "alerts", "subject"):
        subject = _first_column(connection, "alerts", "subject", "topic") or "''"
        terms = _first_column(connection, "alerts", "terms", "novelty")
        mode = "mode" if _has_column(connection, "alerts", "mode") else "'deep'"
        connection.executescript(
            REBUILD_ALERTS.format(
                subject=subject,
                mode=mode,
                terms=f"COALESCE({terms}, '')" if terms else "''",
            )
        )

    # Adding a column carries no constraint, so these need no rebuild.
    if _table_exists(connection, "matches") and not _has_column(connection, "matches", "links"):
        connection.execute("ALTER TABLE matches ADD COLUMN links TEXT NOT NULL DEFAULT ''")
    if _table_exists(connection, "alerts") and not _has_column(connection, "alerts", "confidence"):
        connection.execute("ALTER TABLE alerts ADD COLUMN confidence REAL")


def create_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    _migrate(connection)
    connection.executescript(SCHEMA)
    return connection
