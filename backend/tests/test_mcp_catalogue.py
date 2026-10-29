"""Tool-surface routing: area registry, tool_catalogue, server instructions, generated docs, offline routing eval.

The eval approximates the client's keyword tool search with BM25 over tool name + description + area text. It is a
floor, not a measurement of the real search: it catches descriptions that lack the words people use.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from backend.mcp import catalogue, server, tools_catalogue
from backend.mcp.catalogue import AREAS, TOOL_AREA, render_catalogue, render_doc_block
from backend.mcp.server import mcp

_ROOT = Path(__file__).resolve().parents[2]
_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "mcp_routing_cases.json").read_text(
        encoding="utf-8"
    )
)
_DOC = _ROOT / "docs" / "bifrost-agent.md"
_TOP3_FLOOR = 0.85
_TOP1_FLOOR = 0.75


def _tools() -> list[Any]:
    return mcp._tool_manager.list_tools()


# ── registry ──────────────────────────────────────────────────────────────────────────────────────
def test_every_tool_has_exactly_one_known_area() -> None:
    names = {t.name for t in _tools()}
    missing = sorted(names - set(TOOL_AREA))
    assert not missing, (
        f"tools without an area (add them to declare_areas in their module): {missing}"
    )
    stale = sorted(set(TOOL_AREA) - names)
    assert not stale, f"declare_areas names tools that do not exist: {stale}"
    assert set(TOOL_AREA.values()) <= set(AREAS)
    empty = [a for a in AREAS if a not in TOOL_AREA.values()]
    assert not empty, f"areas with no tools: {empty}"


def test_declare_areas_rejects_unknown_area() -> None:
    with pytest.raises(ValueError, match="unknown area 'nope'; valid: inspect"):
        catalogue.declare_areas({"x": "nope"})


def test_entry_points_and_recipes_name_registered_tools() -> None:
    names = {t.name for t in _tools()}
    for a in AREAS.values():
        assert a.recipes, f"area {a.id} has no recipe"
        for e in a.entry_points:
            assert e in names, f"{a.id} entry point {e}"
            assert TOOL_AREA[e] == a.id, (
                f"entry point {e} belongs to {TOOL_AREA[e]}, not {a.id}"
            )
        for title, steps in a.recipes:
            assert title and steps
            for step in steps:
                assert step.split("(")[0] in names, (
                    f"{a.id} recipe {title!r}: unknown tool in {step!r}"
                )


# ── tool_catalogue ────────────────────────────────────────────────────────────────────────────────
def test_tool_catalogue_is_read_only_and_listed() -> None:
    tool = next(t for t in _tools() if t.name == "tool_catalogue")
    assert tool.annotations.readOnlyHint is True
    assert "confirm" not in tool.parameters.get("properties", {})


def test_tool_catalogue_overview_and_area() -> None:
    overview = asyncio.run(tools_catalogue.tool_catalogue())
    for area in AREAS:
        assert f"- {area} (" in overview
    assert len(overview) < 4500
    comp = asyncio.run(tools_catalogue.tool_catalogue("composites"))
    assert (
        "add_plant" in comp and "[W+confirm]" in comp and "[R] list_plant_types" in comp
    )
    assert "Recipes:" in comp and "submit_solve" in comp


def test_tool_catalogue_unknown_area_is_an_actionable_sentence() -> None:
    out = asyncio.run(tools_catalogue.tool_catalogue("power"))
    assert out.startswith('error: unknown area "power"; valid: inspect, build')


def test_tool_catalogue_output_ceiling() -> None:
    for area in AREAS:
        assert len(render_catalogue(_tools(), area)) <= 7000, area


# ── instructions ──────────────────────────────────────────────────────────────────────────────────
def test_instructions_only_name_registered_tools() -> None:
    text = server._INSTRUCTIONS
    names = {t.name for t in _tools()}
    # snake_case words are tool names unless they are known non-tool tokens
    allowed = {"physical_risk_*"}
    for token in set(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text)):
        assert token in names or token in allowed, (
            f"instructions mention unknown tool {token!r}"
        )
    for area in AREAS.values():
        for e in area.entry_points:
            assert e in text
    assert "confirm=true" in text and "tool_catalogue" in text
    assert 25 <= len(text.splitlines()) <= 45
    assert len(text) < 6500


# ── generated docs ────────────────────────────────────────────────────────────────────────────────
def test_doc_catalogue_block_is_in_sync() -> None:
    doc = _DOC.read_text(encoding="utf-8")
    block = render_doc_block(_tools())
    assert block in doc, (
        "docs/bifrost-agent.md tool catalogue is stale: run scripts/gen_mcp_catalogue_doc.py"
    )


def test_doc_counts_match_tool_count() -> None:
    n = len(_tools())
    doc = _DOC.read_text(encoding="utf-8")
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"MCP server has {n} tools" in doc
    assert f"MCP server ({n} tools)" in readme


# ── routing eval (offline keyword retrieval baseline) ─────────────────────────────────────────────
_STOP = {
        "a",
        "an",
        "the",
        "to",
        "of",
        "on",
        "in",
        "at",
        "for",
        "and",
        "or",
        "my",
        "me",
        "it",
        "is",
        "are",
        "be",
        "with",
        "from",
        "by",
        "as",
        "that",
        "this",
        "all",
        "what",
        "how",
        "show",
        "give",
        "set",
        "up",
        "do",
    }
_TOKEN = re.compile(r"[a-z0-9]+|[가-힣]+")


def _norm(tok: str) -> str:
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") and tok[-2] != "s" else tok


def _tokens(text: str) -> list[str]:
    return [
        _norm(t)
        for t in _TOKEN.findall(text.lower().replace("_", " "))
        if t not in _STOP
    ]


def _match(q: str, d: str) -> bool:
    if q == d:
        return True
    hangul = "가" <= q[0] <= "힣"
    return (
        hangul and len(q) >= 2 and len(d) >= 2 and (d.startswith(q) or q.startswith(d))
    )


def retrieve(docs: dict[str, str], query: str, k: int = 3) -> list[str]:
    """BM25 over ``name`` (x3 weight) + body text; Hangul tokens match by prefix (Korean particles)."""
    bodies = {n: _tokens(n) * 3 + _tokens(t) for n, t in docs.items()}
    avg = sum(len(b) for b in bodies.values()) / len(bodies)
    q_tokens = _tokens(query)
    scores: dict[str, float] = {}
    for qt in q_tokens:
        tf = {n: sum(1 for d in b if _match(qt, d)) for n, b in bodies.items()}
        df = sum(1 for v in tf.values() if v)
        if not df:
            continue
        idf = math.log(1 + (len(bodies) - df + 0.5) / (df + 0.5))
        for n, f in tf.items():
            if f:
                scores[n] = scores.get(n, 0.0) + idf * f * 2.2 / (
                    f + 1.2 * (0.25 + 0.75 * len(bodies[n]) / avg)
                )
    return [n for n, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def evaluate(
    docs: dict[str, str], cases: list[dict[str, Any]]
) -> tuple[float, float, list[dict[str, Any]]]:
    """Return (top-3 hit rate, top-1 hit rate, misses). A hit is any accepted tool within the first k results."""
    miss, top1, top3 = [], 0, 0
    for c in cases:
        got = retrieve(docs, c["request"], 3)
        top3 += any(g in c["expect"] for g in got)
        top1 += bool(got) and got[0] in c["expect"]
        if not any(g in c["expect"] for g in got):
            miss.append({"request": c["request"], "expect": c["expect"], "got": got})
    return top3 / len(cases), top1 / len(cases), miss


def _docs(with_area: bool) -> dict[str, str]:
    out = {}
    for t in _tools():
        text = t.description or ""
        if with_area:
            a = AREAS[TOOL_AREA[t.name]]
            text += f" {a.id} {a.title} {a.purpose} {a.keywords}"
        out[t.name] = text
    return out


def test_routing_fixture_names_registered_tools() -> None:
    names = {t.name for t in _tools()}
    assert len(_CASES) >= 30
    for c in _CASES:
        assert set(c["expect"]) <= names, c


def test_routing_hit_rate_floor(capsys: pytest.CaptureFixture[str]) -> None:
    top3, top1, miss = evaluate(_docs(True), _CASES)
    d3, d1, _ = evaluate(_docs(False), _CASES)
    with capsys.disabled():
        print(
            f"\nrouting eval ({len(_CASES)} requests): name+description+area top-3 {top3:.0%} top-1 {top1:.0%}; "
            f"name+description only top-3 {d3:.0%} top-1 {d1:.0%}"
        )
        for m in miss:
            print("  miss:", m)
    assert top3 >= _TOP3_FLOOR, miss
    assert top1 >= _TOP1_FLOOR
