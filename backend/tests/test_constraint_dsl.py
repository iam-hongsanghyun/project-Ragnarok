"""Unit tests for the custom-constraint DSL parser (pure, no solve)."""
from __future__ import annotations

import pytest

from backend.pypsa.network.constraint_dsl import (
    DslParseError,
    _spec_to_parsed,
    parse_dsl,
    parse_line,
)


def _terms(side):
    return [(t.coef, t.kind, t.carrier) for t in side]


def test_simple_carrier_cap() -> None:
    pc = parse_line("gen(coal) <= 1000", 1)
    assert _terms(pc.lhs) == [(1.0, "gen", "coal")]
    assert pc.sense == "<="
    assert _terms(pc.rhs) == [(1000.0, "const", None)]


def test_intensity_like_form() -> None:
    pc = parse_line("emissions <= 0.5 * gen", 1)
    assert _terms(pc.lhs) == [(1.0, "emissions", None)]
    assert _terms(pc.rhs) == [(0.5, "gen", None)]


def test_signed_multi_term() -> None:
    pc = parse_line("gen(solar) + gen(wind) - 2*gen(gas) >= 5000", 1)
    assert _terms(pc.lhs) == [
        (1.0, "gen", "solar"),
        (1.0, "gen", "wind"),
        (-2.0, "gen", "gas"),
    ]
    assert pc.sense == ">="


def test_cf_and_bare_atoms() -> None:
    assert _terms(parse_line("cf(nuclear) <= 0.8", 1).lhs) == [(1.0, "cf", "nuclear")]
    assert _terms(parse_line("load_shed <= 100", 1).lhs) == [(1.0, "load_shed", None)]
    assert _terms(parse_line("cap(wind) >= 50", 1).lhs) == [(1.0, "cap", "wind")]


def test_quoted_carrier_with_space() -> None:
    pc = parse_line('gen("offshore wind") <= 10', 1)
    assert _terms(pc.lhs) == [(1.0, "gen", "offshore wind")]


def _selectors(side):
    return [(t.coef, t.kind, t.carrier, t.column, t.values) for t in side]


def test_multi_value_carrier_selector() -> None:
    pc = parse_line("gen(solar & wind) <= 5000", 1)
    assert _selectors(pc.lhs) == [(1.0, "gen", None, None, ["solar", "wind"])]


def test_column_selector() -> None:
    pc = parse_line("cap(type, solar & wind) <= 100000", 1)
    assert _selectors(pc.lhs) == [(1.0, "cap", None, "type", ["solar", "wind"])]
    assert _terms(pc.rhs) == [(100000.0, "const", None)]


def test_column_selector_single_value_and_quoted() -> None:
    pc = parse_line('emissions(type, "coal fired") >= 1', 1)
    assert _selectors(pc.lhs) == [(1.0, "emissions", None, "type", ["coal fired"])]
    pc2 = parse_line('cf("fuel group", vre & "run of river") <= 0.8', 1)
    assert _selectors(pc2.lhs) == [(1.0, "cf", None, "fuel group", ["vre", "run of river"])]


def test_single_carrier_stays_legacy_shape() -> None:
    pc = parse_line("cap(solar) <= 80", 1)
    assert _selectors(pc.lhs) == [(1.0, "cap", "solar", None, None)]


def test_comments_and_blank_lines() -> None:
    parsed = parse_dsl("gen(coal) <= 1000\n# a comment\n\nload_shed <= 5  # trailing\n")
    assert len(parsed) == 2
    assert parsed[1].line_no == 4


def test_spec_wire_format_accepts_column_selector() -> None:
    """The JSON spec path (what the frontend sends) carries column selectors."""
    spec = {
        "id": "cap(type, solar & wind) <= 100000",
        "lhs": [{"coef": 1, "kind": "cap", "column": "type", "values": ["solar", "wind"]}],
        "sense": "<=",
        "rhs": [{"coef": 100000, "kind": "const"}],
    }
    pc = _spec_to_parsed(spec, 1)
    assert _selectors(pc.lhs) == [(1.0, "cap", None, "type", ["solar", "wind"])]


def test_spec_wire_format_rejects_column_without_values() -> None:
    spec = {"lhs": [{"kind": "gen", "column": "type"}], "sense": "<=", "rhs": [{"kind": "const", "coef": 1}]}
    with pytest.raises(DslParseError):
        _spec_to_parsed(spec, 1)


@pytest.mark.parametrize(
    "bad",
    [
        "gen(",
        "gen()",
        "foo(x) <= 1",
        "gen(coal) 1000",          # no comparator
        "gen(coal) <= >= 5",       # two comparators
        "gen(coal) <= 5 +",        # trailing operator
        "gen(type,) <= 1",         # column with no values
        "gen(solar &) <= 1",       # dangling '&'
        "gen(type, a, b) <= 1",    # second comma
        "load_shed(x) <= 1",       # bare-only atom with selector
    ],
)
def test_parse_errors(bad: str) -> None:
    with pytest.raises(DslParseError):
        parse_line(bad, 1)
