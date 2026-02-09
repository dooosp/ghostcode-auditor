"""GhostCode Auditor - Engine Tests (pytest)."""
from __future__ import annotations

import os
import sys
import tempfile
import shutil

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine.extract import (
    parse_file, Unit, _count_callback_depth,
    _max_nesting, _count_branches,
)
from engine.evidence import Evidence, _calc_score
from engine.scores import (
    calc_cognitive_load, calc_fragility, calc_shadow,
    score_unit, UnitScores,
)
from engine.similarity import tokenize, shingles, jaccard, find_clusters
from engine.rules import load_rules, match_rules, Rule
from engine.cache import (
    get_cached, set_cached, purge_expired, make_unit_cache_key,
)
from engine.db import init_db, get_conn
from engine import db as db_module

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "rules", "react-ts.yaml",
)


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory):
    """Create a temporary repo with sample TS/TSX files for testing."""
    repo = tmp_path_factory.mktemp("gc_test")

    # Initialize as git repo so ingest/evidence can work
    os.system(f"cd {repo} && git init && git checkout -b main")

    src = repo / "src"
    src.mkdir()

    # App.tsx - component with hooks, side effects, nesting
    (src / "App.tsx").write_text("""\
import React, { useState, useEffect } from 'react';

export function App() {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch('/api/data').then(r => r.json()).then(d => setData(d));
  }, []);

  fetch('/api/extra');

  if (data) {
    if (data.items) {
      return <div>{data.items.map(i => <span>{i}</span>)}</div>;
    }
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
      const year = d.getFullYear();
      if (year > 2000) {
        return `${year}-${d.getMonth()+1}-${d.getDate()}`;
      }
    }
  }
  return 'invalid';
}
""")

    # utils.ts - duplicate-like functions for similarity testing
    (src / "utils.ts").write_text("""\
export function formatA(d: Date) {
  return d.toISOString().split('T')[0];
}

export function formatB(d: Date) {
  return d.toISOString().split('T')[1];
}

export function complexFunc(data: any, opts: any) {
  if (data) {
    for (const item of data.items) {
      if (item.active) {
        if (opts.verbose) {
          if (item.nested) {
            console.log(item.nested.deep.value);
          }
        }
      }
    }
  }
}
""")

    # Commit the files
    os.system(
        f"cd {repo} && git add -A && "
        f"git commit -m 'initial commit' --author='test <test@test.com>'"
    )

    return str(repo)


@pytest.fixture()
def temp_db():
    """Use a temporary SQLite DB for cache tests."""
    orig = db_module.DB_PATH
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_module.DB_PATH = type(orig)(f.name)
    init_db()
    yield
    try:
        os.unlink(str(db_module.DB_PATH))
    except OSError:
        pass
    db_module.DB_PATH = orig


# ── Extract Tests ─────────────────────────────────────────

class TestExtract:
    def test_parse_file_finds_units(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        names = [u.name for u in units]
        assert "App" in names
        assert "useCustomHook" in names
        assert "formatDate" in names

    def test_unit_kinds(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        kinds = {u.name: u.kind for u in units}
        assert kinds["App"] == "component"
        assert kinds["useCustomHook"] == "hook"
        assert kinds["formatDate"] == "function"

    def test_nesting_depth(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        fd = next(u for u in units if u.name == "formatDate")
        assert fd.nesting_depth >= 2, f"got {fd.nesting_depth}"

    def test_hook_calls_detected(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        app = next(u for u in units if u.name == "App")
        assert "useState" in app.hook_calls
        assert "useEffect" in app.hook_calls

    def test_render_side_effects(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        app = next(u for u in units if u.name == "App")
        assert app.render_side_effects >= 1

    def test_callback_depth_nonzero(self, sample_repo):
        """Verify callback_depth is computed (not stuck at 0)."""
        units = parse_file("src/App.tsx", sample_repo)
        app = next(u for u in units if u.name == "App")
        # fetch(...).then(r => ...).then(d => ...) => depth >= 1
        assert app.callback_depth >= 1, (
            f"callback_depth should be >= 1, got {app.callback_depth}")

    def test_callback_depth_function(self):
        """Test _count_callback_depth with nested arrow functions."""
        from tree_sitter import Parser, Language
        import tree_sitter_javascript
        lang = Language(tree_sitter_javascript.language())
        parser = Parser(lang)
        code = (
            b"function test() {"
            b"  fetch(url, () => {"
            b"    setTimeout(() => { console.log(1); }, 100);"
            b"  });"
            b"}"
        )
        tree = parser.parse(code)
        func = tree.root_node.children[0]
        depth = _count_callback_depth(func)
        assert depth == 2

    def test_branch_count(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        fd = next(u for u in units if u.name == "formatDate")
        assert fd.branch_count >= 3

    def test_loc_positive(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        for u in units:
            assert u.loc > 0

    def test_empty_file_returns_empty(self, sample_repo):
        """Nonexistent file returns empty list."""
        units = parse_file("nonexistent.ts", sample_repo)
        assert units == []

    def test_deep_nesting_detected(self, sample_repo):
        units = parse_file("src/utils.ts", sample_repo)
        cf = next(u for u in units if u.name == "complexFunc")
        assert cf.nesting_depth >= 4


# ── Scores Tests ──────────────────────────────────────────

class TestScores:
    def test_cognitive_load_range(self):
        u = Unit(
            id="t", file_path="t.ts", name="test", kind="function",
            span=(1, 5), loc=5, source="function test() {}",
        )
        score = calc_cognitive_load(u)
        assert 0 <= score <= 100

    def test_cognitive_load_increases_with_complexity(self):
        simple = Unit(
            id="s", file_path="s.ts", name="simple", kind="function",
            span=(1, 3), loc=3, source="",
        )
        complex_ = Unit(
            id="c", file_path="c.ts", name="complex", kind="function",
            span=(1, 30), loc=30,
            nesting_depth=5, branch_count=8,
            boolean_complexity=4, callback_depth=3,
            try_catch_count=0, source="",
        )
        assert calc_cognitive_load(complex_) > calc_cognitive_load(simple)

    def test_shadow_true(self):
        assert calc_shadow(75.0, 20.0) is True

    def test_shadow_false_high_evidence(self):
        assert calc_shadow(75.0, 50.0) is False

    def test_shadow_false_low_cognitive(self):
        assert calc_shadow(50.0, 10.0) is False

    def test_fragility_range(self):
        f = calc_fragility(
            Unit(id="x", file_path="x.ts", name="x", kind="function",
                 span=(1, 1), loc=1, source=""),
            80.0, 20.0,
        )
        assert 0 <= f <= 100

    def test_fragility_higher_with_low_evidence(self):
        u = Unit(
            id="x", file_path="x.ts", name="x", kind="function",
            span=(1, 1), loc=1, source="",
        )
        f_low = calc_fragility(u, 80.0, 10.0)
        f_high = calc_fragility(u, 80.0, 90.0)
        assert f_low > f_high

    def test_score_unit_returns_unit_scores(self):
        u = Unit(
            id="su", file_path="su.ts", name="su", kind="function",
            span=(1, 5), loc=5, source="",
        )
        ev = Evidence(unit_id="su", review_evidence_score=50)
        result = score_unit(u, ev)
        assert isinstance(result, UnitScores)
        assert result.unit_id == "su"

    def test_react_component_penalty(self):
        """Component with useEffect + no cleanup gets penalty."""
        comp = Unit(
            id="rc", file_path="rc.tsx", name="Comp", kind="component",
            span=(1, 20), loc=20,
            hook_calls=["useEffect", "useState"],
            has_cleanup=False,
            render_side_effects=1,
            source="",
        )
        func = Unit(
            id="rf", file_path="rf.ts", name="func", kind="function",
            span=(1, 20), loc=20, source="",
        )
        assert calc_cognitive_load(comp) > calc_cognitive_load(func)


# ── Evidence Tests ────────────────────────────────────────

class TestEvidence:
    def test_score_zero_single_author(self):
        assert _calc_score(1, False, 0, False) == 0

    def test_score_30_two_authors(self):
        assert _calc_score(2, False, 0, False) == 30

    def test_score_50_touched_and_authors(self):
        assert _calc_score(2, True, 0, False) == 50

    def test_score_80_full_signals(self):
        assert _calc_score(3, True, 5, True) == 80

    def test_score_capped_at_100(self):
        assert _calc_score(10, True, 100, True) <= 100


# ── Similarity Tests ──────────────────────────────────────

class TestSimilarity:
    def test_tokenize_keywords(self):
        tokens = tokenize("const x = 1;")
        assert "const" in tokens
        assert "_VAR" in tokens
        assert "_NUM" in tokens

    def test_tokenize_strings(self):
        tokens = tokenize('const s = "hello";')
        assert "_STR" in tokens

    def test_tokenize_normalizes_identifiers(self):
        t1 = tokenize("function a(x) { return x + 1; }")
        t2 = tokenize("function b(y) { return y + 1; }")
        assert t1 == t2

    def test_shingles_basic(self):
        tokens = ["a", "b", "c", "d", "e"]
        s = shingles(tokens, 3)
        assert "a b c" in s
        assert "c d e" in s

    def test_shingles_short_input(self):
        s = shingles(["a", "b"], 4)
        assert len(s) == 1  # single shingle for short input

    def test_jaccard_identical(self):
        s1 = shingles(tokenize("function a(x) { return x + 1; }"))
        s2 = shingles(tokenize("function b(y) { return y + 1; }"))
        assert jaccard(s1, s2) == 1.0

    def test_jaccard_different(self):
        s1 = shingles(tokenize("function a(x) { return x + 1; }"))
        s2 = shingles(tokenize(
            "async function fetchData(url) {"
            " const r = await fetch(url); return r.json(); }"))
        assert jaccard(s1, s2) < 0.5

    def test_jaccard_empty_sets(self):
        assert jaccard(set(), set()) == 1.0
        assert jaccard({"a"}, set()) == 0.0

    def test_find_clusters_similar(self):
        u1 = Unit(
            id="a", file_path="u.ts", name="formatA", kind="function",
            span=(1, 3), loc=3,
            source="function formatA(d) {"
                   " return d.toISOString().split('T')[0]; }",
        )
        u2 = Unit(
            id="b", file_path="u.ts", name="formatB", kind="function",
            span=(4, 6), loc=3,
            source="function formatB(d) {"
                   " return d.toISOString().split('T')[1]; }",
        )
        clusters = find_clusters([u1, u2])
        assert len(clusters) == 1
        assert len(clusters[0].members) == 2

    def test_find_clusters_no_pair(self):
        u1 = Unit(
            id="x", file_path="x.ts", name="x", kind="function",
            span=(1, 1), loc=1, source="function x() { return 1; }",
        )
        assert find_clusters([u1]) == []

    def test_find_clusters_different(self):
        u1 = Unit(
            id="a", file_path="a.ts", name="funcA", kind="function",
            span=(1, 5), loc=5,
            source="function funcA(items) { return items.filter(i => i.active).map(i => i.name); }",
        )
        u2 = Unit(
            id="b", file_path="b.ts", name="funcB", kind="function",
            span=(1, 10), loc=10,
            source="async function funcB(url, opts) { const resp = await fetch(url, opts); if (!resp.ok) throw new Error('fail'); return await resp.json(); }",
        )
        clusters = find_clusters([u1, u2])
        assert len(clusters) == 0


# ── Rules Tests ───────────────────────────────────────────

class TestRules:
    def test_load_rules_count(self):
        rules = load_rules(RULES_PATH)
        assert len(rules) == 15

    def test_load_rules_structure(self):
        rules = load_rules(RULES_PATH)
        r = rules[0]
        assert r.id == "REACT-001"
        assert r.severity in ("high", "medium", "low")
        assert r.action

    def test_react001_matches_side_effect(self, sample_repo):
        units = parse_file("src/App.tsx", sample_repo)
        rules = load_rules(RULES_PATH)
        app = next(u for u in units if u.name == "App")
        matches = match_rules(app, rules)
        ids = [m.rule_id for m in matches]
        assert "REACT-001" in ids

    def test_no_rules_match_clean_function(self):
        u = Unit(
            id="c", file_path="c.ts", name="clean", kind="function",
            span=(1, 3), loc=3,
            source="function clean(x: number): number { return x * 2; }",
        )
        rules = load_rules(RULES_PATH)
        matches = match_rules(u, rules)
        assert len(matches) == 0

    def test_cx002_deep_nesting(self):
        u = Unit(
            id="dn", file_path="d.ts", name="deep", kind="function",
            span=(1, 20), loc=20,
            nesting_depth=6, source="",
        )
        rules = load_rules(RULES_PATH)
        matches = match_rules(u, rules)
        ids = [m.rule_id for m in matches]
        assert "CX-002" in ids

    def test_ts001_any_abuse(self):
        u = Unit(
            id="aa", file_path="a.ts", name="anyFunc", kind="function",
            span=(1, 10), loc=10,
            source="function anyFunc(a: any, b: any, c: any, d: any) { return a; }",
        )
        rules = load_rules(RULES_PATH)
        matches = match_rules(u, rules)
        ids = [m.rule_id for m in matches]
        assert "TS-001" in ids

    def test_ts002_api_no_trycatch(self):
        u = Unit(
            id="at", file_path="a.ts", name="fetcher", kind="function",
            span=(1, 5), loc=5,
            try_catch_count=0,
            source="function fetcher() { fetch('/api'); }",
        )
        rules = load_rules(RULES_PATH)
        matches = match_rules(u, rules)
        ids = [m.rule_id for m in matches]
        assert "TS-002" in ids


# ── Cache Tests ───────────────────────────────────────────

class TestCache:
    def test_set_and_get(self, temp_db):
        key = make_unit_cache_key("abc123", (1, 10))
        set_cached(key, {"score": 42})
        result = get_cached(key)
        assert result is not None
        assert result["score"] == 42

    def test_cache_miss(self, temp_db):
        result = get_cached("nonexistent_key_12345")
        assert result is None

    def test_cache_overwrite(self, temp_db):
        key = make_unit_cache_key("def456", (1, 5))
        set_cached(key, {"v": 1})
        set_cached(key, {"v": 2})
        result = get_cached(key)
        assert result["v"] == 2

    def test_purge_expired(self, temp_db):
        """Purge should not remove fresh entries."""
        key = make_unit_cache_key("fresh", (1, 1))
        set_cached(key, {"keep": True}, ttl_days=30)
        purge_expired()
        result = get_cached(key)
        assert result is not None

    def test_cache_key_varies_by_span(self, temp_db):
        k1 = make_unit_cache_key("same_hash", (1, 10))
        k2 = make_unit_cache_key("same_hash", (11, 20))
        assert k1 != k2


# ── Report Tests ──────────────────────────────────────────

class TestReport:
    def test_build_report_structure(self, sample_repo):
        from engine.ingest import ingest
        from engine.extract import extract_all
        from engine.evidence import collect_all_evidence
        from engine.scores import score_all
        from engine.report import build_report

        result = ingest(sample_repo)
        units = extract_all(result.repo_path, result.files)
        ev = collect_all_evidence(result.repo_path, units)
        scores = score_all(units, ev)
        clusters = find_clusters(units)
        rules = load_rules(RULES_PATH)
        rm = {u.id: match_rules(u, rules) for u in units}

        report = build_report(
            "test", result.commit_sha, result.branch,
            "full", units, ev, scores, clusters, rm,
        )

        assert "scan_id" in report
        assert "summary" in report
        assert "hotspots" in report
        assert report["summary"]["total_units"] >= 3

    def test_pr_comment_renders(self, sample_repo):
        from engine.ingest import ingest
        from engine.extract import extract_all
        from engine.evidence import collect_all_evidence
        from engine.scores import score_all
        from engine.report import build_report, render_pr_comment

        result = ingest(sample_repo)
        units = extract_all(result.repo_path, result.files)
        ev = collect_all_evidence(result.repo_path, units)
        scores = score_all(units, ev)
        rules = load_rules(RULES_PATH)
        rm = {u.id: match_rules(u, rules) for u in units}

        report = build_report(
            "test", result.commit_sha, result.branch,
            "full", units, ev, scores, [], rm,
        )
        comment = render_pr_comment(report)
        assert "GhostCode Audit Report" in comment
        assert "Top Hotspots" in comment
