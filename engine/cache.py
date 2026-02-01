from __future__ import annotations

import hashlib
import json
import os

from engine.db import get_conn, init_db

TTL_DAYS = int(os.environ.get("CACHE_TTL_DAYS", "7"))


def _make_key(file_hash: str, unit_span: str,
              ruleset_version: str = "1.0") -> str:
    raw = f"{file_hash}|{unit_span}|{ruleset_version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_cached(cache_key: str) -> dict | None:
    """Get cached data if not expired."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT data FROM cache "
            "WHERE cache_key = ? "
            "AND julianday('now') - julianday(created_at) < ttl_days",
            (cache_key,),
        ).fetchone()
        if row:
            return json.loads(row["data"])
        return None
    finally:
        conn.close()


def set_cached(cache_key: str, data: dict, ttl_days: int = TTL_DAYS):
    """Store data in cache."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache (cache_key, data, ttl_days) "
            "VALUES (?, ?, ?)",
            (cache_key, json.dumps(data, ensure_ascii=False), ttl_days),
        )
        conn.commit()
    finally:
        conn.close()


def purge_expired():
    """Remove expired cache entries."""
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM cache "
            "WHERE julianday('now') - julianday(created_at) >= ttl_days"
        )
        conn.commit()
    finally:
        conn.close()


def make_unit_cache_key(file_content_hash: str,
                        span: tuple[int, int]) -> str:
    return _make_key(file_content_hash, f"{span[0]}:{span[1]}")
