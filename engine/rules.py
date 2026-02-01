from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from engine.extract import Unit


@dataclass
class RuleMatch:
    rule_id: str
    name: str
    severity: str
    action: str
    detail: str = ""


@dataclass
class Rule:
    id: str
    name: str
    when: str
    severity: str
    action: str


def load_rules(yaml_path: str | Path) -> list[Rule]:
    """Load rules from YAML file."""
    path = Path(yaml_path)
    with open(path) as f:
        data = yaml.safe_load(f)
    rules = []
    for r in data.get("rules", []):
        rules.append(Rule(
            id=r["id"],
            name=r["name"],
            when=r["when"],
            severity=r["severity"],
            action=r["action"],
        ))
    return rules


# === 규칙별 매칭 함수 ===

def _check_render_side_effect(unit: Unit) -> str | None:
    if unit.kind == "component" and unit.render_side_effects > 0:
        return f"render body에서 side-effect {unit.render_side_effects}건 감지"
    return None


def _check_useeffect_deps(unit: Unit) -> str | None:
    if "useEffect" not in unit.hook_calls:
        return None
    # heuristic: useEffect with empty deps but referencing outer vars
    # 간단히: source에서 useEffect(()=>{...}, []) 패턴 감지
    if re.search(r"useEffect\(\s*\(\)\s*=>", unit.source):
        if re.search(r",\s*\[\s*\]\s*\)", unit.source):
            return "useEffect 빈 deps + 외부 변수 참조 가능성"
    return None


def _check_setstate_in_loop(unit: Unit) -> str | None:
    patterns = [
        r"for\s*\(.*\)\s*\{[^}]*set[A-Z]",
        r"\.forEach\([^)]*set[A-Z]",
        r"\.map\([^)]*set[A-Z]",
    ]
    for p in patterns:
        if re.search(p, unit.source, re.DOTALL):
            return "loop 내부에서 setState 호출 감지"
    return None


def _check_derived_state(unit: Unit) -> str | None:
    if re.search(r"useState\(\s*props\.", unit.source):
        return "props를 useState 초기값으로 사용 (derived state)"
    return None


def _check_prop_drilling(unit: Unit) -> str | None:
    # 간단 heuristic: 파라미터 전개 패턴이 많으면
    spread_count = len(re.findall(r"\{\.\.\.(\w+)\}", unit.source))
    if spread_count >= 3:
        return f"prop spreading {spread_count}회 감지 (drilling 의심)"
    return None


def _check_any_abuse(unit: Unit) -> str | None:
    matches = re.findall(r":\s*any\b", unit.source)
    if len(matches) > 3:
        return f"'any' 타입 {len(matches)}건 사용"
    return None


def _check_api_no_trycatch(unit: Unit) -> str | None:
    has_api = bool(re.search(
        r"(fetch|axios|\.get|\.post|\.put|\.delete)\s*\(", unit.source))
    if has_api and unit.try_catch_count == 0:
        return "API 호출 존재하지만 try/catch 없음"
    return None


def _check_empty_catch(unit: Unit) -> str | None:
    if re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", unit.source):
        return "빈 catch 블록 감지"
    if re.search(
            r"catch\s*\([^)]*\)\s*\{\s*console\.log", unit.source):
        return "catch에서 console.log만 사용"
    return None


def _check_null_unsafe(unit: Unit) -> str | None:
    # 3+ deep property access without ?.
    if re.search(r"\w+\.\w+\.\w+\.\w+", unit.source):
        if not re.search(r"\?\.", unit.source):
            return "깊은 프로퍼티 접근에 optional chaining 없음"
    return None


def _check_boolean_overload(unit: Unit) -> str | None:
    if unit.boolean_complexity >= 6:
        return f"boolean 연산자 {unit.boolean_complexity}개 (>=6)"
    return None


def _check_deep_nesting(unit: Unit) -> str | None:
    if unit.nesting_depth >= 5:
        return f"중첩 깊이 {unit.nesting_depth} (>=5)"
    return None


def _check_inline_handler(unit: Unit) -> str | None:
    if unit.kind != "component":
        return None
    inline = len(re.findall(
        r"on\w+=\{\s*\(\s*\w*\s*\)\s*=>", unit.source))
    if inline >= 3:
        return f"inline handler {inline}건 (useCallback 고려)"
    return None


def _check_magic_strings(unit: Unit) -> str | None:
    strings = re.findall(r"['\"]([^'\"]{2,})['\"]", unit.source)
    from collections import Counter
    counts = Counter(strings)
    repeated = {s: c for s, c in counts.items() if c >= 3}
    if repeated:
        top = max(repeated, key=repeated.get)
        return f"문자열 '{top}' {repeated[top]}회 반복"
    return None


def _check_comment_over_naming(unit: Unit) -> str | None:
    comments = len(re.findall(r"//.*|/\*.*?\*/", unit.source, re.DOTALL))
    code_lines = max(1, unit.loc - comments)
    ratio = comments / code_lines
    if ratio > 0.4 and unit.identifier_ambiguity > 0.5:
        return f"주석 비율 {ratio:.0%} + 모호한 변수명 {unit.identifier_ambiguity:.0%}"
    return None


# 규칙 ID → 체커 매핑
RULE_CHECKERS = {
    "REACT-001": _check_render_side_effect,
    "REACT-002": _check_useeffect_deps,
    "REACT-003": _check_setstate_in_loop,
    "REACT-004": _check_derived_state,
    "REACT-005": _check_prop_drilling,
    "TS-001": _check_any_abuse,
    "TS-002": _check_api_no_trycatch,
    "TS-003": _check_empty_catch,
    "TS-004": _check_null_unsafe,
    "CX-001": _check_boolean_overload,
    "CX-002": _check_deep_nesting,
    "CX-003": _check_inline_handler,
    "CX-004": None,  # handled by similarity engine
    "CX-005": _check_magic_strings,
    "CX-006": _check_comment_over_naming,
}


def match_rules(unit: Unit, rules: list[Rule]) -> list[RuleMatch]:
    """Apply all rules to a unit, return matches."""
    matches = []
    for rule in rules:
        checker = RULE_CHECKERS.get(rule.id)
        if checker is None:
            continue
        detail = checker(unit)
        if detail:
            matches.append(RuleMatch(
                rule_id=rule.id,
                name=rule.name,
                severity=rule.severity,
                action=rule.action,
                detail=detail,
            ))
    return matches
