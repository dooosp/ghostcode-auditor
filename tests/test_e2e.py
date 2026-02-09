"""GhostCode Auditor - E2E API Tests."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory):
    """Create a temporary git repo with sample TS/TSX files."""
    repo = tmp_path_factory.mktemp("gc_e2e")

    os.system(f"cd {repo} && git init && git checkout -b main")

    src = repo / "src"
    src.mkdir()

    (src / "App.tsx").write_text("""\
import React, { useState, useEffect } from 'react';

export function App() {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch('/api/data').then(r => r.json()).then(d => setData(d));
  }, []);

  fetch('/api/extra');

  if (data) {
    return <div>{JSON.stringify(data)}</div>;
  }
  return <div>Loading...</div>;
}

export function useCustomHook(url: string) {
  const [state, setState] = useState(null);
  useEffect(() => {
    fetch(url).then(r => r.json()).then(d => setState(d));
    return () => {};
  }, [url]);
  return state;
}

export function formatDate(d: Date): string {
  if (d) {
    if (d.getTime() > 0) {
      return d.toISOString();
    }
  }
  return 'invalid';
}
""")

    os.system(
        f"cd {repo} && git add -A && "
        f"git commit -m 'initial commit' --author='test <test@test.com>'"
    )
    return str(repo)


@pytest.fixture(scope="session")
def client():
    """Create a test client for the FastAPI app."""
    from httpx import ASGITransport, AsyncClient
    from api.main import app
    transport = ASGITransport(app=app)
    import asyncio
    # Return a sync-friendly wrapper
    return transport, app


class TestHealthEndpoint:
    @pytest.mark.anyio
    async def test_health(self):
        from httpx import ASGITransport, AsyncClient
        from api.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestScanEndpoint:
    @pytest.mark.anyio
    async def test_scan_valid_repo(self, sample_repo):
        from httpx import ASGITransport, AsyncClient
        from api.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/scan/",
                json={"repo_path": sample_repo, "repo_name": "test"},
                timeout=60,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "scan_id" in data
        assert "summary" in data
        assert "hotspots" in data
        assert data["summary"]["total_units"] >= 3
        assert data["summary"]["scanned_units"] >= 3

    @pytest.mark.anyio
    async def test_scan_invalid_path(self):
        from httpx import ASGITransport, AsyncClient
        from api.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/scan/",
                json={"repo_path": "/nonexistent/path"},
            )
        assert resp.status_code == 400


class TestReportEndpoint:
    @pytest.mark.anyio
    async def test_report_not_found(self):
        from httpx import ASGITransport, AsyncClient
        from api.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            resp = await ac.get("/report/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_scan_then_retrieve_report(self, sample_repo):
        from httpx import ASGITransport, AsyncClient
        from api.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as ac:
            # First do a scan
            scan_resp = await ac.post(
                "/scan/",
                json={"repo_path": sample_repo, "repo_name": "test"},
                timeout=60,
            )
            assert scan_resp.status_code == 200
            scan_id = scan_resp.json()["scan_id"]

            # Then retrieve the report
            report_resp = await ac.get(f"/report/{scan_id}")
            assert report_resp.status_code == 200
            report = report_resp.json()
            assert report["scan_id"] == scan_id
            assert "hotspots" in report
