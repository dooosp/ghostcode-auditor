from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Template

from engine.extract import Unit
from engine.evidence import Evidence
from engine.scores import UnitScores
from engine.similarity import Cluster
from engine.rules import RuleMatch

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _generate_why(unit: Unit, score: UnitScores,
                  evidence: Evidence) -> list[str]:
    """Generate human-readable 'why' reasons for a hotspot."""
    reasons = []
    if unit.nesting_depth >= 4:
        reasons.append(f"deep nesting ({unit.nesting_depth})")
    if unit.branch_count >= 8:
        reasons.append(f"branch count high ({unit.branch_count})")
    if unit.boolean_complexity >= 4:
        reasons.append(f"boolean complexity ({unit.boolean_complexity})")
    if unit.try_catch_count == 0 and unit.loc > 20:
        reasons.append("no error handling in long function")
    if unit.render_side_effects > 0:
        reasons.append(f"render side-effects ({unit.render_side_effects})")
    if evidence.distinct_authors <= 1:
        authors_msg = f"low human touch ({evidence.distinct_authors} author"
        if not evidence.touched_after_creation:
            authors_msg += ", never revised"
        authors_msg += ")"
        reasons.append(authors_msg)
    if unit.identifier_ambiguity > 0.3:
        reasons.append(
            f"ambiguous identifiers ({unit.identifier_ambiguity:.0%})")
    return reasons


def _generate_actions(unit: Unit, rule_matches: list[RuleMatch],
                      cluster_id: str | None) -> list[str]:
    """Generate actionable recommendations."""
    actions = []
    # From rule matches
    for rm in rule_matches[:3]:
        actions.append(rm.action)
    # Generic actions based on scores
    if unit.nesting_depth >= 5 and not any("분리" in a for a in actions):
        actions.append("함수 분리 (early return 패턴 적용)")
    if unit.try_catch_count == 0 and unit.loc > 20:
        if not any("에러" in a or "try" in a.lower() for a in actions):
            actions.append("에러 처리 추가")
    if cluster_id:
        actions.append("shared utility 추출 (중복 클러스터 참조)")
    if not actions:
        actions.append("코드 오너 지정 및 리뷰 요청")
    return actions[:5]


def calc_runway(units: list[Unit],
                scores: dict[str, UnitScores]) -> int:
    """Calculate refactoring runway in months.

    Without historical data (first scan), returns estimate based on
    current shadow density.
    """
    shadow_count = sum(1 for s in scores.values() if s.shadow)
    total = len(units)
    if total == 0:
        return 99
    density = shadow_count / total
    if density == 0:
        return 99
    # Heuristic: assume team can convert ~5% of shadow units/month
    team_throughput = max(1, int(total * 0.05))
    return max(1, shadow_count // team_throughput)


def build_report(
    repo_name: str,
    commit_sha: str,
    branch: str,
    scan_type: str,
    units: list[Unit],
    evidence_map: dict[str, Evidence],
    scores_map: dict[str, UnitScores],
    clusters: list[Cluster],
    rule_matches_map: dict[str, list[RuleMatch]],
) -> dict:
    """Build the full JSON report."""
    scan_id = str(uuid.uuid4())[:8]

    # Summary
    shadow_count = sum(1 for s in scores_map.values() if s.shadow)
    total = len(units)
    density = shadow_count / total if total else 0
    avg_cog = (sum(s.cognitive_load for s in scores_map.values()) / total
               if total else 0)
    unique_clusters = len(clusters)
    total_in_clusters = sum(len(c.members) for c in clusters)
    redundancy = total_in_clusters / total if total else 0
    runway = calc_runway(units, scores_map)

    # Cluster lookup
    unit_cluster = {}
    for c in clusters:
        for mid in c.members:
            unit_cluster[mid] = c.id

    # Assign cluster IDs to scores
    for uid, s in scores_map.items():
        s.redundancy_cluster_id = unit_cluster.get(uid)

    # Hotspots: top 10 by cognitive_load (shadow first)
    ranked = sorted(
        units,
        key=lambda u: (
            -int(scores_map[u.id].shadow),
            -scores_map[u.id].cognitive_load,
        ),
    )
    top_hotspots = ranked[:10]

    hotspots = []
    for u in top_hotspots:
        s = scores_map[u.id]
        ev = evidence_map.get(u.id, Evidence(unit_id=u.id))
        rm = rule_matches_map.get(u.id, [])
        cid = unit_cluster.get(u.id)

        hotspots.append({
            "path": u.file_path,
            "symbol": u.name,
            "kind": u.kind,
            "span": {"start": u.span[0], "end": u.span[1]},
            "scores": {
                "cognitive_load": s.cognitive_load,
                "review_evidence": s.review_evidence,
                "fragility": s.fragility,
                "redundancy_cluster_id": cid,
            },
            "why": _generate_why(u, s, ev),
            "actions": _generate_actions(u, rm, cid),
        })

    cluster_list = [
        {
            "id": c.id,
            "members": [
                f"{next((u.file_path for u in units if u.id == mid), '?')}#{next((u.name for u in units if u.id == mid), '?')}"
                for mid in c.members
            ],
            "suggestion": c.suggestion,
        }
        for c in clusters
    ]

    return {
        "scan_id": scan_id,
        "scan_type": scan_type,
        "repo": {"name": repo_name, "commit": commit_sha,
                 "branch": branch},
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_units": total,
            "scanned_units": total,
            "shadow_logic_density": round(density, 3),
            "avg_cognitive_load": round(avg_cog, 1),
            "redundancy_score": round(redundancy, 3),
            "refactoring_runway_months": runway,
        },
        "hotspots": hotspots,
        "clusters": cluster_list,
    }


def save_json(report: dict, output_path: str | Path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


PR_COMMENT_TEMPLATE = """\
## GhostCode Audit Report

**Scan**: {{ scan_type }} | {{ summary.scanned_units }} units analyzed | {{ hotspots | length }} hotspots

### Top Hotspots

| # | File | Function | Cognitive Load | Review Evidence | Action |
|---|------|----------|---------------|-----------------|--------|
{% for h in hotspots[:5] -%}
| {{ loop.index }} | {{ h.path }} | {{ h.symbol }} | {{ h.scores.cognitive_load }}/100 | {{ h.scores.review_evidence }}/100 | {{ h.actions[0] if h.actions else '-' }} |
{% endfor %}

### Shadow Logic Density: {{ (summary.shadow_logic_density * 100) | round(1) }}%{{ ' (⚠️)' if summary.shadow_logic_density > 0.15 else ' (✅)' }}

{{ shadow_count }} of {{ summary.scanned_units }} units have low review evidence + high complexity.
{% if clusters %}

### Redundancy Alert
{% for c in clusters[:3] %}
`{{ c.members | join('`, `') }}` → **{{ c.suggestion }}**
{% endfor %}
{% endif %}

---
*GhostCode Auditor v0.1*
"""


def render_pr_comment(report: dict) -> str:
    shadow_count = sum(
        1 for h in report["hotspots"]
        if h["scores"]["review_evidence"] < 30
        and h["scores"]["cognitive_load"] > 70
    )
    tmpl = Template(PR_COMMENT_TEMPLATE)
    return tmpl.render(
        **report,
        shadow_count=shadow_count,
    )
