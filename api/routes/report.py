import json

from fastapi import APIRouter, HTTPException

from engine.db import get_conn, init_db

router = APIRouter()


@router.get("/{scan_id}")
async def get_report(scan_id: str):
    """리포트 조회."""
    init_db()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT report_json FROM scans WHERE scan_id = ?",
            (scan_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not row["report_json"]:
        raise HTTPException(404, f"Report not found: {scan_id}")

    return json.loads(row["report_json"])
