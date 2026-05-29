"""Unit tests for the custom-constraint DSL parser (pure, no solve)."""
from __future__ import annotations

import pytest

from backend.pypsa.network.constraint_dsl import DslParseError, parse_dsl, parse_line


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


def test_comments_and_blank_lines() -> None:
    parsed = parse_dsl("gen(coal) <= 1000\n# a comment\n\nload_shed <= 5  # trailing\n")
    assert len(parsed) == 2
    assert parsed[1].line_no == 4


@pytest.mark.parametrize(
    "bad",
    [
        "gen(",
        "gen()",
        "foo(x) <= 1",
        "gen(coal) 1000",          # no comparator
        "gen(coal) <= >= 5",       # two comparators
        "gen(coal) <= 5 +",        # trailing operator
    ],
)
def test_parse_errors(bad: str) -> None:
    with pytest.raises(DslParseError):
        parse_line(bad, 1)
