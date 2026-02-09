from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from engine.ingest import ingest, clone_repo
from engine.extract import extract_all, parse_file, Unit
from engine.evidence import collect_all_evidence, Evidence
from engine.scores import score_all, UnitScores
from engine.similarity import find_clusters
from engine.rules import load_rules, match_rules
from engine.report import build_report, render_pr_comment, save_json
from engine.cache import get_cached, set_cached, _make_key
from engine.db import get_conn, init_db

logger = logging.getLogger("ghostcode")

RULES_PATH = Path(__file__).parent.parent / "rules" / "react-ts.yaml"
RULESET_VERSION = "1.0"


def _file_content_hash(repo_path: str, file_path: str) -> str:
    """SHA256 hash of file content for cache keying."""
    full = Path(repo_path) / file_path
    try:
        data = full.read_bytes()
        return hashlib.sha256(data).hexdigest()[:16]
    except (OSError, IOError):
        return ""


def _unit_cache_key(file_hash: str, unit: Unit) -> str:
    """Build cache key from file hash + unit span + ruleset version."""
    span_str = f"{unit.span[0]}:{unit.span[1]}"
    return _make_key(file_hash, span_str, RULESET_VERSION)


def _cached_scan(repo_path: str, units: list[Unit]) -> tuple[
    dict[str, Evidence], dict[str, UnitScores],
    list[Unit], list[Unit],
]:
    """Check cache for each unit. Returns (cached_ev, cached_scores,
    hit_units, miss_units)."""
    cached_ev: dict[str, Evidence] = {}
    cached_scores: dict[str, UnitScores] = {}
    hit_units: list[Unit] = []
    miss_units: list[Unit] = []

    # Group units by file for hash efficiency
    file_hashes: dict[str, str] = {}
    for u in units:
        if u.file_path not in file_hashes:
            file_hashes[u.file_path] = _file_content_hash(
                repo_path, u.file_path)

    for u in units:
        fh = file_hashes.get(u.file_path, "")
        if not fh:
            miss_units.append(u)
            continue
        key = _unit_cache_key(fh, u)
        cached = get_cached(key)
        if cached:
            # Restore from cache
            ev_data = cached.get("evidence", {})
            sc_data = cached.get("scores", {})
            cached_ev[u.id] = Evidence(
                unit_id=u.id,
                distinct_authors=ev_data.get("distinct_authors", 0),
                touched_after_creation=ev_data.get(
                    "touched_after_creation", False),
                touch_count_30d=ev_data.get("touch_count_30d", 0),
                touch_count_90d=ev_data.get("touch_count_90d", 0),
                commit_signals=ev_data.get("commit_signals", []),
                review_evidence_score=ev_data.get(
                    "review_evidence_score", 0),
            )
            cached_scores[u.id] = UnitScores(
                unit_id=u.id,
                cognitive_load=sc_data.get("cognitive_load", 0),
                review_evidence=sc_data.get("review_evidence", 0),
                shadow=sc_data.get("shadow", False),
                fragility=sc_data.get("fragility", 0),
                redundancy_cluster_id=sc_data.get(
                    "redundancy_cluster_id"),
            )
            hit_units.append(u)
        else:
            miss_units.append(u)

    return cached_ev, cached_scores, hit_units, miss_units


def _store_cache(repo_path: str, miss_units: list[Unit],
                 ev_map: dict[str, Evidence],
                 scores_map: dict[str, UnitScores]):
    """Store computed results in cache for miss units."""
    file_hashes: dict[str, str] = {}
    for u in miss_units:
        if u.file_path not in file_hashes:
            file_hashes[u.file_path] = _file_content_hash(
                repo_path, u.file_path)

    for u in miss_units:
        fh = file_hashes.get(u.file_path, "")
        if not fh:
            continue
        key = _unit_cache_key(fh, u)
        ev = ev_map.get(u.id)
        sc = scores_map.get(u.id)
        if ev and sc:
            data = {
                "evidence": {
                    "distinct_authors": ev.distinct_authors,
                    "touched_after_creation": ev.touched_after_creation,
                    "touch_count_30d": ev.touch_count_30d,
                    "touch_count_90d": ev.touch_count_90d,
                    "commit_signals": ev.commit_signals,
                    "review_evidence_score": ev.review_evidence_score,
                },
                "scores": {
                    "cognitive_load": sc.cognitive_load,
                    "review_evidence": sc.review_evidence,
                    "shadow": sc.shadow,
                    "fragility": sc.fragility,
                    "redundancy_cluster_id": sc.redundancy_cluster_id,
                },
            }
            set_cached(key, data)


def run_full_scan(repo_path: str, repo_name: str = "") -> dict:
    """Run a full scan on a local repo."""
    init_db()
    result = ingest(repo_path)
    if not repo_name:
        repo_name = Path(repo_path).name

    units = extract_all(result.repo_path, result.files)

    # Cache lookup
    cached_ev, cached_scores, hit_units, miss_units = _cached_scan(
        result.repo_path, units)
    cache_hits = len(hit_units)
    cache_misses = len(miss_units)
    if cache_hits > 0:
        logger.info("Cache: %d hits, %d misses", cache_hits, cache_misses)

    # Compute only for cache misses
    if miss_units:
        new_ev = collect_all_evidence(result.repo_path, miss_units)
        new_scores = score_all(miss_units, new_ev)
        # Store in cache
        _store_cache(result.repo_path, miss_units, new_ev, new_scores)
    else:
        new_ev = {}
        new_scores = {}

    # Merge cached + new
    ev_map = {**cached_ev, **new_ev}
    scores = {**cached_scores, **new_scores}

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

    # Cache lookup
    cached_ev, cached_scores, hit_units, miss_units = _cached_scan(
        repo_path, units)
    if miss_units:
        new_ev = collect_all_evidence(repo_path, miss_units)
        new_scores = score_all(miss_units, new_ev)
        _store_cache(repo_path, miss_units, new_ev, new_scores)
    else:
        new_ev = {}
        new_scores = {}

    ev_map = {**cached_ev, **new_ev}
    scores = {**cached_scores, **new_scores}
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
