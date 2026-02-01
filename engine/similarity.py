from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from engine.extract import Unit

# 토큰 정규화: 변수명 → _VAR, 문자열 → _STR, 숫자 → _NUM
_TOKEN_RE = re.compile(
    r'"[^"]*"|\'[^\']*\'|`[^`]*`'  # strings
    r'|\b\d+\.?\d*\b'              # numbers
    r'|\b[a-zA-Z_$]\w*\b'          # identifiers
    r'|[{}()\[\];,.:?!<>=+\-*/&|^~%@]'  # operators/punctuation
)

_KEYWORDS = {
    "const", "let", "var", "function", "return", "if", "else",
    "for", "while", "do", "switch", "case", "break", "continue",
    "try", "catch", "finally", "throw", "new", "delete", "typeof",
    "instanceof", "in", "of", "class", "extends", "super", "this",
    "import", "export", "default", "from", "async", "await", "yield",
    "true", "false", "null", "undefined", "void",
}

SHINGLE_SIZE = 4
SIMILARITY_THRESHOLD_UTIL = 0.7
SIMILARITY_THRESHOLD_COMPONENT = 0.85


@dataclass
class Cluster:
    id: str
    members: list[str] = field(default_factory=list)
    suggestion: str = ""


def tokenize(source: str) -> list[str]:
    """Normalize source into token sequence."""
    tokens = []
    for match in _TOKEN_RE.finditer(source):
        tok = match.group()
        if tok.startswith(("'", '"', "`")):
            tokens.append("_STR")
        elif tok[0].isdigit():
            tokens.append("_NUM")
        elif tok in _KEYWORDS:
            tokens.append(tok)
        elif len(tok) == 1 and not tok.isalpha():
            tokens.append(tok)
        else:
            tokens.append("_VAR")
    return tokens


def shingles(tokens: list[str], n: int = SHINGLE_SIZE) -> set[str]:
    """Generate n-gram shingles from token sequence."""
    if len(tokens) < n:
        return {" ".join(tokens)}
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_clusters(units: list[Unit]) -> list[Cluster]:
    """Find similar function clusters using token shingles."""
    if len(units) < 2:
        return []

    # Precompute shingles
    unit_shingles: list[tuple[Unit, set[str]]] = []
    for u in units:
        tokens = tokenize(u.source)
        if len(tokens) < SHINGLE_SIZE:
            continue
        unit_shingles.append((u, shingles(tokens)))

    # Pairwise comparison → union-find clustering
    n = len(unit_shingles)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(n):
        for j in range(i + 1, n):
            u_i, s_i = unit_shingles[i]
            u_j, s_j = unit_shingles[j]

            # 컴포넌트 간 유사도는 높은 임계값
            both_component = (u_i.kind == "component" and
                              u_j.kind == "component")
            threshold = (SIMILARITY_THRESHOLD_COMPONENT if both_component
                         else SIMILARITY_THRESHOLD_UTIL)

            sim = jaccard(s_i, s_j)
            if sim >= threshold:
                union(i, j)

    # Build clusters (2+ members only)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        member_units = [unit_shingles[i][0] for i in members]
        names = [f"{u.file_path}#{u.name}" for u in member_units]
        cluster_id = hashlib.sha256(
            "|".join(sorted(names)).encode()
        ).hexdigest()[:8]

        # suggestion 생성
        common = _suggest_common_name(member_units)
        clusters.append(Cluster(
            id=cluster_id,
            members=[u.id for u in member_units],
            suggestion=f"extract shared utility: {common}()",
        ))

    return clusters


def _suggest_common_name(units: list[Unit]) -> str:
    """Suggest a common utility name from unit names."""
    names = [u.name for u in units]
    # Find common prefix
    if not names:
        return "sharedLogic"
    prefix = names[0]
    for name in names[1:]:
        while not name.startswith(prefix) and prefix:
            prefix = prefix[:-1]
    if len(prefix) > 3:
        return f"shared{prefix[0].upper()}{prefix[1:]}"
    return "sharedLogic"
