from __future__ import annotations

import json
import subprocess
from pathlib import Path

from engine.ingest import ingest, clone_repo
from engine.extract import extract_all, parse_file
from engine.evidence import collect_all_evidence
from engine.scores import score_all
from engine.similarity import find_clusters
from engine.rules import load_rules, match_rules
from engine.report import build_report, render_pr_comment, save_json
from engine.db import get_conn, init_db

RULES_PATH = Path(__file__).parent.parent / "rules" / "react-ts.yaml"


def run_full_scan(repo_path: str, repo_name: str = "") -> dict:
    """Run a full scan on a local repo."""
    init_db()
    result = ingest(repo_path)
    if not repo_name:
        repo_name = Path(repo_path).name

    units = extract_all(result.repo_path, result.files)
    ev_map = collect_all_evidence(result.repo_path, units)
    scores = score_all(units, ev_map)
    clusters = find_clusters(units)

    rules = load_rules(RULES_PATH)
    rm_map = {u.id: match_rules(u, rules) for u in units}

    report = build_report(
        repo_name=repo_name,
        commit_sha=result.commit_sha,
        branch=result.branch,
        scan_type="full",
        units=units,
        evidence_map=ev_map,
        scores_map=scores,
        clusters=clusters,
        rule_matches_map=rm_map,
    )

    _store_report(report)
    return report


def run_pr_scan(repo_path: str, repo_name: str,
                pr_number: int, head_sha: str) -> dict:
    """Run incremental scan on PR changed files only."""
    init_db()
    changed = _get_pr_changed_files(repo_path, pr_number)
    if not changed:
        return {"scan_id": "none", "summary": {"scanned_units": 0}}

    # Filter to supported extensions
    supported = {".ts", ".tsx", ".js", ".jsx"}
    changed = [f for f in changed
               if Path(f).suffix in supported]

    units = []
    for f in changed:
        units.extend(parse_file(f, repo_path))

    if not units:
        return {"scan_id": "none", "summary": {"scanned_units": 0}}

    ev_map = collect_all_evidence(repo_path, units)
    scores = score_all(units, ev_map)
    clusters = find_clusters(units)

    rules = load_rules(RULES_PATH)
    rm_map = {u.id: match_rules(u, rules) for u in units}

    branch = ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True)
        branch = r.stdout.strip()
    except Exception:
        pass

    report = build_report(
        repo_name=repo_name,
        commit_sha=head_sha,
        branch=branch,
        scan_type=f"pr#{pr_number}",
        units=units,
        evidence_map=ev_map,
        scores_map=scores,
        clusters=clusters,
        rule_matches_map=rm_map,
    )

    _store_report(report)
    return report


def _get_pr_changed_files(repo_path: str, pr_number: int) -> list[str]:
    """Get list of changed files from PR via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number), "--name-only"],
            cwd=repo_path, capture_output=True, text=True,
            check=True, timeout=30,
        )
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return []


def _store_report(report: dict):
    """Store report in SQLite."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO scans "
            "(scan_id, repo_name, commit_sha, branch, scan_type, report_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                report["scan_id"],
                report["repo"]["name"],
                report["repo"]["commit"],
                report["repo"].get("branch", ""),
                report["scan_type"],
                json.dumps(report, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def post_pr_comment(repo_full_name: str, pr_number: int,
                    report: dict) -> bool:
    """Post report as PR comment via gh CLI."""
    comment = render_pr_comment(report)
    try:
        subprocess.run(
            ["gh", "api",
             f"/repos/{repo_full_name}/issues/{pr_number}/comments",
             "--method", "POST",
             "--field", f"body={comment}"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return False
