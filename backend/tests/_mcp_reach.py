"""Which HTTP operation does each MCP tool reach? A static resolution over ``backend/mcp`` (AST, no network).

Every request in the package goes through a handful of call shapes (``_get`` / ``_post`` / ``_put`` / ``_patch`` /
``_request`` / ``_request_bytes`` / ``_upload`` / ``screening_post``). For each function (tool, client method or
module helper) the analysis collects

* the ``(METHOD, path template)`` of the requests it makes directly (an f-string placeholder becomes ``{}``; a
  ``self.CONST`` prefix is substituted; a path held in a variable is resolved from the assignments in the same function,
  else from the ``/api`` literals of that function), and
* the functions it calls: ``x.name(...)`` resolves to a ``RagnarokClient`` method, ``name(...)`` to a function of the
  same module. Tools reach the union over that call graph.

A template whose placeholder is a function parameter (``/api/export/{}``) cannot name its operation statically; those are
resolved by ``PARAMETERISED`` below and re-checked against the real client by ``test_mcp_coverage.py`` with a recording
transport.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parents[1] / "mcp"

Op = tuple[str, str]  # (METHOD, openapi path)

_METHOD_OF = {"_get": "GET", "_post": "POST", "_put": "PUT", "_patch": "PATCH", "_upload": "POST"}


def norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


class _Func:
    def __init__(self, module: str, name: str, node: ast.AST, is_tool: bool, in_client: bool) -> None:
        self.module, self.name, self.node, self.is_tool, self.in_client = module, name, node, is_tool, in_client
        self.requests: set[Op] = set()   # (METHOD, template with {})
        self.calls: set[tuple[str, str]] = set()  # ("attr"|"name", callee)


def _is_tool(fn: ast.AST) -> bool:
    for d in getattr(fn, "decorator_list", []):
        f = d.func if isinstance(d, ast.Call) else d
        if isinstance(f, ast.Attribute) and f.attr == "tool":
            return True
    return False


def _resolve(node: ast.AST, fn: ast.AST, consts: dict[str, str], depth: int = 0) -> set[str]:
    """Possible path templates of an expression; empty = unresolvable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.JoinedStr):
        parts: list[set[str]] = [{""}]
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append({str(v.value)})
            elif isinstance(v.value, ast.Attribute) and v.value.attr in consts:  # type: ignore[attr-defined]
                parts.append({consts[v.value.attr]})  # type: ignore[attr-defined]
            elif isinstance(v.value, ast.IfExp):  # f"/x/{'a' if c else 'b'}"
                alts = _resolve(v.value, fn, consts, depth)
                parts.append(alts or {"{}"})
            else:
                parts.append({"{}"})
        out = {""}
        for p in parts:
            out = {a + b for a in out for b in p}
        return out
    if isinstance(node, ast.IfExp):
        return _resolve(node.body, fn, consts, depth) | _resolve(node.orelse, fn, consts, depth)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _resolve(node.left, fn, consts, depth), _resolve(node.right, fn, consts, depth)
        return {a + b for a in left for b in right}
    if isinstance(node, ast.Name) and depth < 3:
        out: set[str] = set()
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign):
                continue
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == node.id:
                    out |= _resolve(n.value, fn, consts, depth + 1)
                elif isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple) and len(t.elts) == len(n.value.elts):  # a, b = x, y
                    for target, value in zip(t.elts, n.value.elts):
                        if isinstance(target, ast.Name) and target.id == node.id:
                            out |= _resolve(value, fn, consts, depth + 1)
        return out
    return set()


def _api_literals(fn: ast.AST, consts: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Constant, ast.JoinedStr)):
            out |= {p for p in _resolve(n, fn, consts) if p.startswith("/api")}
    return out


def _callee(call: ast.Call) -> tuple[str, str] | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return ("attr", f.attr)
    if isinstance(f, ast.Name):
        return ("name", f.id)
    return None


def analyse() -> tuple[dict[Op, set[str]], set[Op], list[str]]:
    """``(reach, templates, unresolved)``: tools by operation key, every ``(METHOD, template)`` seen, and call sites
    whose path could not be resolved."""
    funcs: list[_Func] = []
    unresolved: list[str] = []
    for file in sorted(MCP_DIR.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        consts: dict[str, str] = {}
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            for s in cls.body:
                if isinstance(s, ast.Assign) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str):
                    for t in s.targets:
                        if isinstance(t, ast.Name):
                            consts[t.id] = s.value.value
        owners: list[tuple[ast.AST, bool]] = [(n, False) for n in tree.body]
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RagnarokClient"]:
            owners += [(n, True) for n in cls.body]
        for node, in_client in owners:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            f = _Func(file.stem, node.name, node, _is_tool(node), in_client)
            for n in ast.walk(node):
                if not isinstance(n, ast.Call):
                    continue
                c = _callee(n)
                if c is None:
                    continue
                _kind, name = c
                if f.name == "_request" or name == "request":  # the transport itself
                    continue
                method = path_arg = None
                if name in _METHOD_OF and n.args:
                    method, path_arg = _METHOD_OF[name], n.args[0]
                elif name in ("_request", "_request_bytes") and len(n.args) >= 2 and isinstance(n.args[0], ast.Constant):
                    method, path_arg = str(n.args[0].value), n.args[1]
                elif name == "screening_post" and n.args:
                    method = "POST"
                    path_arg = ast.JoinedStr([ast.Constant("/api/screening/"), ast.FormattedValue(n.args[0], -1, None)]) \
                        if not isinstance(n.args[0], ast.Constant) else ast.Constant("/api/screening/" + str(n.args[0].value))
                if method and path_arg is not None:
                    paths = _resolve(path_arg, node, consts) or _api_literals(node, consts)
                    if not paths and f.name not in ("_get", "_post", "_put", "_patch", "_upload", "_post_json"):
                        unresolved.append(f"{file.stem}.{f.name}:{n.lineno}")
                    for p in paths:
                        if p.startswith("/api"):
                            f.requests.add((method, norm(p)))
                else:
                    f.calls.add(c)
            funcs.append(f)

    client_methods = {f.name: f for f in funcs if f.in_client}
    by_module: dict[tuple[str, str], _Func] = {(f.module, f.name): f for f in funcs if not f.in_client}

    def closure(f: _Func) -> set[Op]:
        seen: set[int] = set()
        out: set[Op] = set()
        stack = [f]
        while stack:
            cur = stack.pop()
            if id(cur) in seen:
                continue
            seen.add(id(cur))
            out |= cur.requests
            for kind, name in cur.calls:
                if kind == "attr" and name in client_methods:
                    stack.append(client_methods[name])
                elif kind == "name" and (cur.module, name) in by_module:
                    stack.append(by_module[(cur.module, name)])
        return out

    reach: dict[Op, set[str]] = {}
    templates: set[Op] = set()
    for f in funcs:
        templates |= f.requests
        if f.is_tool:
            for op in closure(f):
                reach.setdefault(op, set()).add(f.name)
    return reach, templates, unresolved


def match(templates_reach: dict[Op, set[str]], ops: set[Op]) -> tuple[dict[Op, set[str]], dict[Op, set[str]]]:
    """Split ``ops`` (METHOD, openapi path) into ``(exact, wildcard_only)``: reached by an exact template, or only by a
    template whose placeholder could stand for the concrete op segment (``/api/export/{}`` ~ ``/api/export/hdf5``)."""
    exact: dict[Op, set[str]] = {}
    loose: dict[Op, set[str]] = {}
    for method, path in ops:
        key = (method, norm(path))
        if key in templates_reach:
            exact[(method, path)] = templates_reach[key]
            continue
        for (m, tpl), tools in templates_reach.items():
            if m != method or "{}" not in tpl:
                continue
            rx = "^" + re.escape(tpl).replace(re.escape("{}"), "[^/]+") + "$"
            if re.match(rx, path):
                loose.setdefault((method, path), set()).update(tools)
    return exact, loose
