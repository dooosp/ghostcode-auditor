from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

EXCLUDE_DIRS = {
    "node_modules", "dist", "build", ".next", "coverage",
    "__tests__", "__mocks__", ".git", ".cache", "vendor",
    ".turbo", ".vercel", "out", "storybook-static",
}

INCLUDE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}

EXCLUDE_PATTERNS = {
    ".min.js", ".min.css", ".bundle.js",
    ".d.ts", ".map", ".snap",
}


@dataclass
class IngestResult:
    repo_path: str
    commit_sha: str
    branch: str
    files: list[str] = field(default_factory=list)


def clone_repo(repo_url: str, branch: str = "main",
               target_dir: str | None = None) -> str:
    """Clone repo to target_dir. Returns repo path."""
    if target_dir is None:
        target_dir = tempfile.mkdtemp(prefix="gc_")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch,
         repo_url, target_dir],
        check=True, capture_output=True, text=True,
    )
    return target_dir


def get_commit_sha(repo_path: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def get_branch(repo_path: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _should_exclude(path: Path) -> bool:
    parts = path.parts
    if any(d in EXCLUDE_DIRS for d in parts):
        return True
    name = path.name
    if any(name.endswith(p) for p in EXCLUDE_PATTERNS):
        return True
    return False


def collect_files(repo_path: str,
                  max_files: int = 1000) -> list[str]:
    """Collect TS/JS files, excluding vendor/build artifacts."""
    root = Path(repo_path)
    files = []
    for ext in INCLUDE_EXTENSIONS:
        for p in root.rglob(f"*{ext}"):
            if _should_exclude(p.relative_to(root)):
                continue
            files.append(str(p.relative_to(root)))
            if len(files) >= max_files:
                return files
    return sorted(files)


def ingest(repo_path: str, max_files: int = 1000) -> IngestResult:
    """Main ingest: collect metadata + file list from local repo."""
    return IngestResult(
        repo_path=repo_path,
        commit_sha=get_commit_sha(repo_path),
        branch=get_branch(repo_path),
        files=collect_files(repo_path, max_files),
    )
