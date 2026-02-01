import os
import sys
import json

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.extract import parse_file, Unit
from engine.evidence import Evidence, _calc_score
from engine.scores import (
    calc_cognitive_load, calc_shadow, score_unit, UnitScores,
)
from engine.similarity import tokenize, shingles, jaccard, find_clusters
from engine.rules import load_rules, match_rules
from engine.cache import (
    get_cached, set_cached, purge_expired, make_unit_cache_key,
)
from engine.db import init_db, get_conn, DB_PATH
from engine.report import build_report, render_pr_comment


REPO_PATH = "/tmp/gc_test"
RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "rules", "react-ts.yaml")

passed = 0
failed = 0


def test(name):
    def decorator(fn):
        global passed, failed
        try:
            fn()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} -> {e}")
            failed += 1
    return decorator


print("=== Extract Tests ===")


@test("parse_file finds 3 units")
def _():
    units = parse_file("src/App.tsx", REPO_PATH)
    assert len(units) == 3, f"expected 3, got {len(units)}"


@test("unit kinds are correct")
def _():
    units = parse_file("src/App.tsx", REPO_PATH)
    kinds = {u.name: u.kind for u in units}
    assert kinds["App"] == "component"
    assert kinds["useCustomHook"] == "hook"
    assert kinds["formatDate"] == "function"


@test("nesting depth for formatDate >= 2")
def _():
    units = parse_file("src/App.tsx", REPO_PATH)
    fd = next(u for u in units if u.name == "formatDate")
    assert fd.nesting_depth >= 2, f"got {fd.nesting_depth}"


@test("hook_calls detected for App")
def _():
    units = parse_file("src/App.tsx", REPO_PATH)
    app = next(u for u in units if u.name == "App")
    assert "useState" in app.hook_calls
    assert "useEffect" in app.hook_calls


@test("render side effects detected for App")
def _():
    units = parse_file("src/App.tsx", REPO_PATH)
    app = next(u for u in units if u.name == "App")
    assert app.render_side_effects >= 1


print("\n=== Evidence Tests ===")


@test("review_evidence score 0 for single author, no revisions")
def _():
    score = _calc_score(1, False, 0, False)
    assert score == 0


@test("review_evidence score 30 for 2+ authors")
def _():
    score = _calc_score(2, False, 0, False)
    assert score == 30


@test("review_evidence score 80 for full signals")
def _():
    score = _calc_score(3, True, 5, True)
    assert score == 80


print("\n=== Scores Tests ===")


@test("shadow = True when evidence low + cognitive high")
def _():
    assert calc_shadow(75.0, 20.0) is True


@test("shadow = False when evidence adequate")
def _():
    assert calc_shadow(75.0, 50.0) is False


@test("shadow = False when cognitive low")
def _():
    assert calc_shadow(50.0, 10.0) is False


@test("cognitive_load returns 0~100")
def _():
    u = Unit(id="t", file_path="t.ts", name="test", kind="function",
             span=(1, 5), loc=5, source="function test() {}")
    score = calc_cognitive_load(u)
    assert 0 <= score <= 100, f"got {score}"


print("\n=== Similarity Tests ===")


@test("identical functions have jaccard 1.0")
def _():
    s1 = shingles(tokenize("function a(x) { return x + 1; }"))
    s2 = shingles(tokenize("function b(y) { return y + 1; }"))
    assert jaccard(s1, s2) == 1.0


@test("different functions have low jaccard")
def _():
    s1 = shingles(tokenize("function a(x) { return x + 1; }"))
    s2 = shingles(tokenize("async function fetchData(url) { const r = await fetch(url); return r.json(); }"))
    assert jaccard(s1, s2) < 0.5


@test("find_clusters groups similar units")
def _():
    u1 = Unit(id="a", file_path="u.ts", name="formatA", kind="function",
              span=(1, 3), loc=3,
              source="function formatA(d) { return d.toISOString().split('T')[0]; }")
    u2 = Unit(id="b", file_path="u.ts", name="formatB", kind="function",
              span=(4, 6), loc=3,
              source="function formatB(d) { return d.toISOString().split('T')[1]; }")
    clusters = find_clusters([u1, u2])
    assert len(clusters) == 1
    assert len(clusters[0].members) == 2


print("\n=== Rules Tests ===")


@test("load 15 rules from YAML")
def _():
    rules = load_rules(RULES_PATH)
    assert len(rules) == 15


@test("REACT-001 matches component with render side-effect")
def _():
    units = parse_file("src/App.tsx", REPO_PATH)
    rules = load_rules(RULES_PATH)
    app = next(u for u in units if u.name == "App")
    matches = match_rules(app, rules)
    ids = [m.rule_id for m in matches]
    assert "REACT-001" in ids


@test("no rules match clean function")
def _():
    u = Unit(id="c", file_path="c.ts", name="clean", kind="function",
             span=(1, 3), loc=3, source="function clean(x: number): number { return x * 2; }")
    rules = load_rules(RULES_PATH)
    matches = match_rules(u, rules)
    assert len(matches) == 0


print("\n=== Cache Tests ===")

# Use temp DB for cache tests
import tempfile
from engine import db as db_module
_orig_path = db_module.DB_PATH
db_module.DB_PATH = type(_orig_path)(tempfile.mktemp(suffix=".db"))
init_db()


@test("set and get cache")
def _():
    key = make_unit_cache_key("abc123", (1, 10))
    set_cached(key, {"score": 42})
    result = get_cached(key)
    assert result is not None
    assert result["score"] == 42


@test("cache miss for nonexistent key")
def _():
    result = get_cached("nonexistent_key_12345")
    assert result is None


# Restore original DB path
db_module.DB_PATH = _orig_path

print("\n=== Report Tests ===")


@test("build_report produces valid structure")
def _():
    from engine.ingest import ingest
    from engine.extract import extract_all
    from engine.evidence import collect_all_evidence
    from engine.scores import score_all

    result = ingest(REPO_PATH)
    units = extract_all(result.repo_path, result.files)
    ev = collect_all_evidence(result.repo_path, units)
    scores = score_all(units, ev)
    clusters = find_clusters(units)
    rules = load_rules(RULES_PATH)
    rm = {u.id: match_rules(u, rules) for u in units}

    report = build_report("test", result.commit_sha, result.branch,
                          "full", units, ev, scores, clusters, rm)

    assert "scan_id" in report
    assert "summary" in report
    assert "hotspots" in report
    assert report["summary"]["total_units"] == 3


@test("PR comment renders without error")
def _():
    from engine.ingest import ingest
    from engine.extract import extract_all
    from engine.evidence import collect_all_evidence
    from engine.scores import score_all

    result = ingest(REPO_PATH)
    units = extract_all(result.repo_path, result.files)
    ev = collect_all_evidence(result.repo_path, units)
    scores = score_all(units, ev)
    rules = load_rules(RULES_PATH)
    rm = {u.id: match_rules(u, rules) for u in units}

    report = build_report("test", result.commit_sha, result.branch,
                          "full", units, ev, scores, [], rm)
    comment = render_pr_comment(report)
    assert "GhostCode Audit Report" in comment
    assert "Top Hotspots" in comment


# === Summary ===
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed > 0:
    sys.exit(1)
