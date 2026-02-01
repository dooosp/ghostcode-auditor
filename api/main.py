import os
from fastapi import FastAPI
from api.routes import scan, pr, report

app = FastAPI(
    title="GhostCode Auditor",
    version="0.1.0",
    description="Shadow logic detection for TS/React codebases",
)

app.include_router(scan.router, prefix="/scan", tags=["scan"])
app.include_router(pr.router, prefix="/pr", tags=["pr"])
app.include_router(report.router, prefix="/report", tags=["report"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 3007))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, reload=True)
