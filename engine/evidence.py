from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from engine.extract import Unit

REFACTOR_SIGNALS = re.compile(
    r"(refactor|test|type|cleanup|lint|format|rename|extract|simplify)",
    re.IGNORECASE,
)


@dataclass
class Evidence:
    unit_id: str
    distinct_authors: int = 0
    touched_after_creation: bool = False
    touch_count_30d: int = 0
    touch_count_90d: int = 0
    commit_signals: list[str] = field(default_factory=list)
    review_evidence_score: int = 0


def _run_blame(repo_path: str, file_path: str,
               start: int, end: int) -> list[dict]:
    """Run git blame for a line range, return per-line info."""
    try:
        result = subprocess.run(
            ["git", "blame", "--porcelain",
             f"-L{start},{end}", "--", file_path],
            cwd=repo_path, capture_output=True, text=True,
            check=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    entries = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("author "):
            current["author"] = line[7:]
        elif line.startswith("author-time "):
            try:
                current["time"] = int(line[12:])
            except ValueError:
                pass
        elif line.startswith("summary "):
            current["summary"] = line[8:]
        elif line.startswith("\t"):
            if current:
                entries.append(current)
                current = {}

    if current:
        entries.append(current)
    return entries


def _run_log(repo_path: str, file_path: str,
             start: int, end: int) -> list[dict]:
    """Get commit history touching specific lines."""
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H|%an|%at|%s",
             f"-L{start},{end}:{file_path}"],
            cwd=repo_path, capture_output=True, text=True,
            check=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "sha": parts[0],
                "author": parts[1],
                "time": int(parts[2]) if parts[2].isdigit() else 0,
                "summary": parts[3],
            })
    return commits


def _calc_score(distinct_authors: int,
                touched_after_creation: bool,
                touch_count_90d: int,
                has_refactor_signal: bool) -> int:
    """Calculate review_evidence score (0~100)."""
    score = 0
    if distinct_authors >= 2:
        score += 30
    if touched_after_creation:
        score += 20
    if touch_count_90d >= 2:
        score += 20
    if has_refactor_signal:
        score += 10
    # +20 reserved for PR review data (선택, MVP에서 미구현)
    return min(100, score)


def collect_evidence(repo_path: str, unit: Unit) -> Evidence:
    """Collect git-based evidence for a single unit."""
    start, end = unit.span
    blame_entries = _run_blame(repo_path, unit.file_path, start, end)
    log_entries = _run_log(repo_path, unit.file_path, start, end)

    # distinct authors from blame
    authors = {e.get("author", "") for e in blame_entries if e.get("author")}
    distinct_authors = len(authors)

    # touched after creation: >1 unique commits
    unique_shas = {e["sha"] for e in log_entries if "sha" in e}
    touched_after = len(unique_shas) > 1

    # touch counts by time window
    now = datetime.now().timestamp()
    d30 = now - timedelta(days=30).total_seconds()
    d90 = now - timedelta(days=90).total_seconds()

    touch_30 = sum(1 for e in log_entries if e.get("time", 0) > d30)
    touch_90 = sum(1 for e in log_entries if e.get("time", 0) > d90)

    # commit signal detection
    signals = []
    for e in log_entries:
        s = e.get("summary", "")
        found = REFACTOR_SIGNALS.findall(s)
        signals.extend(found)
    signals = list(set(s.lower() for s in signals))

    score = _calc_score(distinct_authors, touched_after,
                        touch_90, len(signals) > 0)

    return Evidence(
        unit_id=unit.id,
        distinct_authors=distinct_authors,
        touched_after_creation=touched_after,
        touch_count_30d=touch_30,
        touch_count_90d=touch_90,
        commit_signals=signals,
        review_evidence_score=score,
    )


def collect_all_evidence(repo_path: str,
                         units: list[Unit]) -> dict[str, Evidence]:
    """Collect evidence for all units. Returns {unit_id: Evidence}."""
    result = {}
    for unit in units:
        result[unit.id] = collect_evidence(repo_path, unit)
    return result
