"""Keep every run in SQLite so performance trends can be queried with plain SQL."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .results import EndpointStats

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,
    commit_sha  TEXT,
    passed      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS endpoint_stats (
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    label           TEXT NOT NULL,
    samples         INTEGER NOT NULL,
    error_rate      REAL NOT NULL,
    p50_ms          REAL NOT NULL,
    p95_ms          REAL NOT NULL,
    p99_ms          REAL NOT NULL,
    throughput_rps  REAL NOT NULL,
    PRIMARY KEY (run_id, label)
);
"""

# Example trend query: p95 of every endpoint over the last 10 runs
TREND_SQL = """
SELECT r.run_at, r.commit_sha, s.label, s.p95_ms, s.error_rate, s.throughput_rps
FROM endpoint_stats s
JOIN runs r ON r.id = s.run_id
WHERE r.id IN (SELECT id FROM runs ORDER BY id DESC LIMIT ?)
ORDER BY r.id, s.label;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def record_run(
    conn: sqlite3.Connection,
    stats: dict[str, EndpointStats],
    passed: bool,
    commit_sha: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO runs (run_at, commit_sha, passed) VALUES (?, ?, ?)",
        (datetime.now(UTC).isoformat(timespec="seconds"), commit_sha, int(passed)),
    )
    run_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO endpoint_stats VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (run_id, s.label, s.samples, s.error_rate, s.p50_ms, s.p95_ms, s.p99_ms, s.throughput_rps)
            for s in stats.values()
        ],
    )
    conn.commit()
    return run_id


def trend(conn: sqlite3.Connection, last_n: int = 10) -> list[tuple]:
    return conn.execute(TREND_SQL, (last_n,)).fetchall()
