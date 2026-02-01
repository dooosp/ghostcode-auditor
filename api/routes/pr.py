import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.pipeline import run_pr_scan, post_pr_comment

router = APIRouter()
logger = logging.getLogger("ghostcode")


class PRScanRequest(BaseModel):
    repo_path: str
    repo_name: str  # owner/repo
    pr_number: int
    head_sha: str


@router.post("/")
async def pr_scan(req: PRScanRequest):
    """PR 증분 스캔 + 코멘트."""
    if not Path(req.repo_path).is_dir():
        raise HTTPException(400, f"Not a directory: {req.repo_path}")

    report = await asyncio.to_thread(
        run_pr_scan, req.repo_path, req.repo_name,
        req.pr_number, req.head_sha,
    )

    if report.get("summary", {}).get("scanned_units", 0) == 0:
        return {"status": "no_units", "scan_id": report.get("scan_id")}

    # Post comment (fire-and-forget style, log errors)
    posted = await asyncio.to_thread(
        post_pr_comment, req.repo_name, req.pr_number, report,
    )
    if not posted:
        logger.warning("Failed to post PR comment for PR#%d", req.pr_number)

    return {
        "status": "ok",
        "scan_id": report["scan_id"],
        "comment_posted": posted,
        "summary": report["summary"],
    }
