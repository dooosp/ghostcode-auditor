# ghostcode-auditor

Static analysis tool that detects shadow logic in TypeScript/React codebases — dead code, hidden complexity, redundant patterns, and maintenance risks.

**Zero LLM** — pure AST analysis with tree-sitter.

## What it detects

- **Shadow Logic**: Unreachable branches, dead feature flags, orphaned handlers
- **Cognitive Complexity**: Deeply nested conditions, excessive branching
- **Redundancy**: Duplicate logic across files, copy-paste patterns
- **Runway Risk**: Code areas with no recent git blame activity

## Metrics

| Metric | What it measures |
|--------|-----------------|
| Shadow Score | Ratio of potentially dead code |
| Cognitive Score | Structural complexity per function |
| Redundancy Score | Cross-file similarity index |
| Runway Score | Maintenance momentum (git blame recency) |

## Architecture

```
FastAPI
  ├─ /scan     → full codebase scan
  ├─ /pr       → PR incremental scan (changed files only)
  └─ /report   → HTML report (Jinja2)
        │
  engine/
    ├─ ingest.py      → file discovery + filtering
    ├─ extract.py     → tree-sitter AST parsing
    ├─ rules.py       → 15 detection rules
    ├─ scores.py      → 4 metric calculators
    ├─ similarity.py  → cross-file redundancy
    ├─ evidence.py    → blame + context collection
    └─ pipeline.py    → orchestration
```

## Stack

- **Language**: Python 3
- **API**: FastAPI + Uvicorn
- **Parsing**: tree-sitter (TypeScript, JavaScript)
- **Templates**: Jinja2 (HTML reports)
- **Cache**: File-based AST cache

## Setup

```bash
pip install -r requirements.txt
uvicorn api.main:app --port 3007
```

## Endpoints

```
POST /scan    { "path": "/path/to/project" }
POST /pr      { "path": "/path/to/project", "files": ["src/foo.ts"] }
GET  /report  → HTML report
```
