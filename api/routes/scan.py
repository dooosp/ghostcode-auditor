import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.pipeline import run_full_scan

router = APIRouter()


class ScanRequest(BaseModel):
    repo_path: str
    repo_name: str = ""


@router.post("/")
async def start_scan(req: ScanRequest):
    """풀스캔 실행. 로컬 repo 경로 필요."""
    if not Path(req.repo_path).is_dir():
        raise HTTPException(400, f"Not a directory: {req.repo_path}")

    report = await asyncio.to_thread(
        run_full_scan, req.repo_path, req.repo_name
    )
    return report
