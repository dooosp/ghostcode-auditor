from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser, Node

TSX_LANG = Language(tree_sitter_typescript.language_tsx())
TS_LANG = Language(tree_sitter_typescript.language_typescript())
JS_LANG = Language(tree_sitter_javascript.language())

LANG_MAP = {
    ".tsx": TSX_LANG,
    ".ts": TS_LANG,
    ".jsx": JS_LANG,
    ".js": JS_LANG,
}


@dataclass
class Unit:
    id: str
    file_path: str
    name: str
    kind: str  # "component" | "hook" | "function"
    span: tuple[int, int]  # (start_line, end_line) 1-based
    loc: int
    nesting_depth: int = 0
    branch_count: int = 0
    early_return_count: int = 0
    try_catch_count: int = 0
    hook_calls: list[str] = field(default_factory=list)
    has_cleanup: bool = False
    render_side_effects: int = 0
    boolean_complexity: int = 0
    callback_depth: int = 0
    identifier_ambiguity: float = 0.0
    context_switches: int = 0
    source: str = ""


def _make_id(file_path: str, name: str, span: tuple[int, int]) -> str:
    raw = f"{file_path}:{name}:{span[0]}:{span[1]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _classify_kind(name: str, node: Node) -> str:
    if name.startswith("use") and name[3:4].isupper():
        return "hook"
    if _has_jsx_return(node):
        return "component"
    return "function"


def _has_jsx_return(node: Node) -> bool:
    """Check if function body contains JSX return."""
    body = node.child_by_field_name("body")
    if body is None:
        return False
    for child in _walk(body):
        if child.type in ("jsx_element", "jsx_self_closing_element",
                          "jsx_fragment"):
            return True
    return False


def _walk(node: Node):
    """Depth-first walk of all descendants."""
    yield node
    for child in node.children:
        yield from _walk(child)


def _max_nesting(node: Node, depth: int = 0) -> int:
    """Calculate max nesting depth of control flow."""
    nesting_types = {
        "if_statement", "for_statement", "for_in_statement",
        "while_statement", "do_statement", "switch_statement",
        "try_statement", "ternary_expression",
    }
    max_d = depth
    for child in node.children:
        if child.type in nesting_types:
            max_d = max(max_d, _max_nesting(child, depth + 1))
        else:
            max_d = max(max_d, _max_nesting(child, depth))
    return max_d


def _count_branches(node: Node) -> int:
    branch_types = {
        "if_statement", "else_clause", "switch_case",
        "ternary_expression", "binary_expression",
    }
    count = 0
    for child in _walk(node):
        if child.type in branch_types:
            if child.type == "binary_expression":
                op = child.child_by_field_name("operator")
                if op and op.type in ("&&", "||", "??"):
                    count += 1
            else:
                count += 1
    return count


def _count_early_returns(node: Node) -> int:
    body = node.child_by_field_name("body")
    if body is None:
        return 0
    stmts = [c for c in body.children if c.type == "return_statement"]
    return max(0, len(stmts) - 1)


def _count_try_catch(node: Node) -> int:
    return sum(1 for c in _walk(node) if c.type == "try_statement")


def _extract_hooks(node: Node) -> list[str]:
    hooks = []
    for c in _walk(node):
        if c.type == "call_expression":
            fn = c.child_by_field_name("function")
            if fn and fn.text:
                name = fn.text.decode("utf-8", errors="replace")
                if name.startswith("use") and name[3:4].isupper():
                    hooks.append(name)
    return hooks


def _count_boolean_complexity(node: Node) -> int:
    count = 0
    for c in _walk(node):
        if c.type == "binary_expression":
            op = c.child_by_field_name("operator")
            if op and op.type in ("&&", "||"):
                count += 1
    return count


def _count_render_side_effects(node: Node) -> int:
    """Count fetch/storage calls outside useEffect in component body."""
    side_effect_names = {
        "fetch", "localStorage", "sessionStorage", "XMLHttpRequest",
    }
    count = 0
    body = node.child_by_field_name("body")
    if body is None:
        return 0
    for c in _walk(body):
        if c.type == "call_expression":
            fn = c.child_by_field_name("function")
            if fn and fn.text:
                fn_name = fn.text.decode("utf-8", errors="replace")
                if fn_name in side_effect_names:
                    count += 1
    return count


AMBIGUOUS_NAMES = {
    "data", "tmp", "temp", "result", "res", "ret", "val",
    "value", "item", "items", "obj", "arr", "list", "info",
    "response", "output", "input", "x", "y", "z", "a", "b",
    "foo", "bar", "baz", "cb", "fn", "func", "handler",
}


def _calc_identifier_ambiguity(node: Node) -> float:
    identifiers = []
    for c in _walk(node):
        if c.type == "identifier" and c.text:
            identifiers.append(c.text.decode("utf-8", errors="replace"))
    if not identifiers:
        return 0.0
    ambiguous = sum(1 for i in identifiers if i.lower() in AMBIGUOUS_NAMES)
    return ambiguous / len(identifiers)


def _get_function_node_and_name(node: Node):
    """Extract (function_node, name) from various declaration patterns."""
    # function_declaration / function
    if node.type in ("function_declaration", "function"):
        name_node = node.child_by_field_name("name")
        if name_node and name_node.text:
            return node, name_node.text.decode("utf-8", errors="replace")

    # export_statement wrapping function_declaration
    if node.type == "export_statement":
        for child in node.children:
            if child.type == "function_declaration":
                return _get_function_node_and_name(child)
            if child.type == "lexical_declaration":
                return _get_function_node_and_name(child)

    # lexical_declaration: const X = () => {} or const X = function() {}
    if node.type == "lexical_declaration":
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if (name_node and value_node and
                        value_node.type in ("arrow_function",
                                            "function_expression")):
                    name = name_node.text.decode("utf-8", errors="replace")
                    return value_node, name

    return None, None


def _build_unit(file_path: str, func_node: Node, name: str) -> Unit:
    start = func_node.start_point.row + 1
    end = func_node.end_point.row + 1
    source = func_node.text.decode("utf-8", errors="replace")

    return Unit(
        id=_make_id(file_path, name, (start, end)),
        file_path=file_path,
        name=name,
        kind=_classify_kind(name, func_node),
        span=(start, end),
        loc=end - start + 1,
        nesting_depth=_max_nesting(func_node),
        branch_count=_count_branches(func_node),
        early_return_count=_count_early_returns(func_node),
        try_catch_count=_count_try_catch(func_node),
        hook_calls=_extract_hooks(func_node),
        boolean_complexity=_count_boolean_complexity(func_node),
        render_side_effects=_count_render_side_effects(func_node),
        identifier_ambiguity=_calc_identifier_ambiguity(func_node),
        source=source,
    )


def parse_file(file_path: str, repo_path: str) -> list[Unit]:
    """Parse a single TS/JS file and extract all units."""
    ext = Path(file_path).suffix
    lang = LANG_MAP.get(ext)
    if lang is None:
        return []

    full_path = Path(repo_path) / file_path
    try:
        source = full_path.read_bytes()
    except (OSError, IOError):
        return []

    parser = Parser(lang)
    tree = parser.parse(source)
    units = []

    for node in tree.root_node.children:
        func_node, name = _get_function_node_and_name(node)
        if func_node and name:
            units.append(_build_unit(file_path, func_node, name))

    return units


def extract_all(repo_path: str, files: list[str]) -> list[Unit]:
    """Extract units from all files."""
    all_units = []
    for f in files:
        all_units.extend(parse_file(f, repo_path))
    return all_units
