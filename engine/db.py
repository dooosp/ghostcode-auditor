from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "cache" / "ghostcode.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None):
    own = conn is None
    if own:
        conn = get_conn()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS scans (
        scan_id   TEXT PRIMARY KEY,
        repo_name TEXT NOT NULL,
        commit_sha TEXT NOT NULL,
        branch    TEXT,
        scan_type TEXT NOT NULL DEFAULT 'full',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        report_json TEXT
    );

    CREATE TABLE IF NOT EXISTS units (
        id         TEXT PRIMARY KEY,
        scan_id    TEXT NOT NULL REFERENCES scans(scan_id),
        file_path  TEXT NOT NULL,
        name       TEXT NOT NULL,
        kind       TEXT NOT NULL,
        span_start INTEGER,
        span_end   INTEGER,
        loc        INTEGER,
        nesting_depth INTEGER,
        branch_count  INTEGER,
        early_return_count INTEGER,
        try_catch_count INTEGER,
        hook_calls TEXT,
        boolean_complexity INTEGER,
        render_side_effects INTEGER,
        identifier_ambiguity REAL,
        source TEXT
    );

    CREATE TABLE IF NOT EXISTS evidence (
        unit_id   TEXT PRIMARY KEY REFERENCES units(id),
        scan_id   TEXT NOT NULL REFERENCES scans(scan_id),
        distinct_authors INTEGER,
        touched_after_creation INTEGER,
        touch_count_30d INTEGER,
        touch_count_90d INTEGER,
        commit_signals TEXT,
        review_evidence_score INTEGER
    );

    CREATE TABLE IF NOT EXISTS scores (
        unit_id   TEXT PRIMARY KEY REFERENCES units(id),
        scan_id   TEXT NOT NULL REFERENCES scans(scan_id),
        cognitive_load REAL,
        review_evidence REAL,
        shadow    INTEGER,
        fragility REAL,
        redundancy_cluster_id TEXT
    );

    CREATE TABLE IF NOT EXISTS clusters (
        cluster_id TEXT NOT NULL,
        scan_id    TEXT NOT NULL REFERENCES scans(scan_id),
        member_unit_id TEXT NOT NULL REFERENCES units(id),
        suggestion TEXT,
        PRIMARY KEY (cluster_id, member_unit_id)
    );

    CREATE TABLE IF NOT EXISTS cache (
        cache_key  TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        ttl_days   INTEGER NOT NULL DEFAULT 7
    );

    CREATE INDEX IF NOT EXISTS idx_units_scan
        ON units(scan_id);
    CREATE INDEX IF NOT EXISTS idx_evidence_scan
        ON evidence(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scores_scan
        ON scores(scan_id);
    CREATE INDEX IF NOT EXISTS idx_cache_ttl
        ON cache(created_at);
    """)

    if own:
        conn.close()
