from __future__ import annotations

from dataclasses import dataclass

from engine.extract import Unit
from engine.evidence import Evidence

# === 가중치 기본값 ===
W_NESTING = 15
W_BRANCH = 10
W_BOOLEAN = 8
W_CALLBACK = 12
W_AMBIGUITY = 10
W_CONTEXT = 5
W_EXCEPTION = 8
W_SIDE_EFFECT = 7

# React 보정
REACT_USEEFFECT_UNSTABLE_PENALTY = 15
REACT_RENDER_SIDE_EFFECT_PENALTY = 20
REACT_CLEANUP_BONUS = -5

# Shadow 임계값
SHADOW_EVIDENCE_THRESHOLD = 30
SHADOW_COGNITIVE_THRESHOLD = 70


@dataclass
class UnitScores:
    unit_id: str
    cognitive_load: float = 0.0
    review_evidence: float = 0.0
    shadow: bool = False
    fragility: float = 0.0
    redundancy_cluster_id: str | None = None


def calc_cognitive_load(unit: Unit) -> float:
    """Calculate cognitive load score (0~100) with React adjustments."""

    # nesting: 0~6 → 0~90 (capped)
    nesting_score = min(unit.nesting_depth, 6) * W_NESTING

    # branch: 0~10 → 0~100 (capped)
    branch_score = min(unit.branch_count, 10) * W_BRANCH

    # boolean complexity: 0~8 → 0~64
    bool_score = min(unit.boolean_complexity, 8) * W_BOOLEAN

    # callback depth (estimated from nested arrow functions)
    cb_score = min(unit.callback_depth, 5) * W_CALLBACK

    # identifier ambiguity (0.0~1.0 → 0~100)
    ambig_score = unit.identifier_ambiguity * 100 * (W_AMBIGUITY / 100)

    # context switches (not easily computed from AST alone, placeholder)
    ctx_score = min(unit.context_switches, 5) * W_CONTEXT

    # exception irregularity
    exc_score = 0
    if unit.try_catch_count > 0:
        exc_score = W_EXCEPTION
    elif unit.kind == "function" and unit.loc > 20:
        # long function without try/catch may be risky
        exc_score = W_EXCEPTION // 2

    # side effects
    se_score = min(unit.render_side_effects, 3) * W_SIDE_EFFECT

    raw = (nesting_score + branch_score + bool_score + cb_score +
           ambig_score + ctx_score + exc_score + se_score)

    # React 보정
    react_adj = 0
    if unit.kind in ("component", "hook"):
        has_useeffect = "useEffect" in unit.hook_calls
        if has_useeffect and not unit.has_cleanup:
            react_adj += REACT_USEEFFECT_UNSTABLE_PENALTY
        if unit.has_cleanup:
            react_adj += REACT_CLEANUP_BONUS
        if unit.render_side_effects > 0 and unit.kind == "component":
            react_adj += REACT_RENDER_SIDE_EFFECT_PENALTY

    score = raw + react_adj

    # 정규화: 0~100
    return max(0.0, min(100.0, score))


def calc_fragility(unit: Unit, cognitive_load: float,
                   review_evidence: float) -> float:
    """Fragility = weighted mix of cognitive load and low evidence."""
    # higher cognitive load + lower evidence = higher fragility
    evidence_inv = 100 - review_evidence
    return min(100.0, (cognitive_load * 0.6 + evidence_inv * 0.4))


def calc_shadow(cognitive_load: float, review_evidence: float) -> bool:
    return (review_evidence < SHADOW_EVIDENCE_THRESHOLD and
            cognitive_load > SHADOW_COGNITIVE_THRESHOLD)


def score_unit(unit: Unit, evidence: Evidence) -> UnitScores:
    """Calculate all scores for a single unit."""
    cog = calc_cognitive_load(unit)
    rev = float(evidence.review_evidence_score)
    frag = calc_fragility(unit, cog, rev)
    shadow = calc_shadow(cog, rev)

    return UnitScores(
        unit_id=unit.id,
        cognitive_load=round(cog, 1),
        review_evidence=rev,
        shadow=shadow,
        fragility=round(frag, 1),
    )


def score_all(units: list[Unit],
              evidence_map: dict[str, Evidence]) -> dict[str, UnitScores]:
    """Score all units. Returns {unit_id: UnitScores}."""
    result = {}
    for unit in units:
        ev = evidence_map.get(unit.id)
        if ev is None:
            ev = Evidence(unit_id=unit.id)
        result[unit.id] = score_unit(unit, ev)
    return result
