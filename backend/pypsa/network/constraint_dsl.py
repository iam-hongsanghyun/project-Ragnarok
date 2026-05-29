"""Safe free-text DSL for custom linopy constraints.

A small, **non-eval** mini-language so users can author linear caps/floors the
structured constraint table can't express. One constraint per line; ``#`` starts
a comment; blank lines are ignored.

Grammar (flat, linear)::

    line    := linexpr ("<=" | ">=" | "==") linexpr
    linexpr := term (("+" | "-") term)*
    term    := [NUMBER "*"] atom
    atom    := ("gen" | "cap" | "emissions") ["(" CARRIER ")"]
             | "cf" "(" CARRIER ")"        # only as  cf(C) <op> NUMBER
             | "load_shed"
             | NUMBER

Atoms (units), all linear in the dispatch variable ``Generator-p``:

* ``gen[(C)]``      — weighted energy of carrier C, or all supply if bare (MWh)
* ``cap[(C)]``      — installed/optimised capacity of C, or all supply (MW)
* ``emissions[(C)]``— Σ co2_factor·dispatch over emitters (tCO₂)
* ``load_shed``     — Σ load-shedding dispatch (MWh)
* ``cf(C)``         — capacity factor of C; only ``cf(C) <op> number`` (fraction 0–1),
                      rewritten to the linear bound ``gen(C) <op> k·cap(C)·hours``.

Carriers are bare ``[A-Za-z0-9_]+`` tokens or ``"quoted strings"`` (for names with
spaces). Compilation reuses :func:`build_model_context` so the math matches the
structured custom-constraint path exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pypsa

from .custom_constraints import ModelContext, build_model_context

_FUNC_ATOMS = ("gen", "cap", "cf", "emissions")
_BARE_ATOMS = ("gen", "cap", "emissions", "load_shed")
_SENSES = ("<=", ">=", "==")


class DslParseError(ValueError):
    """Raised when a DSL line cannot be parsed. Carries the 1-based line number."""

    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(message)
        self.line_no = line_no
        self.message = message


@dataclass
class Term:
    coef: float
    kind: str            # gen | cap | cf | emissions | load_shed | const
    carrier: str | None  # None ⇒ aggregate over all supply / emitters


@dataclass
class ParsedConstraint:
    line_no: int
    raw: str
    lhs: list[Term]
    sense: str
    rhs: list[Term]


# ── Tokeniser ────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<op><=|>=|==)
      | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
      | (?P<str>"[^"]*")
      | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<star>\*)
      | (?P<plus>\+)
      | (?P<minus>-)
    )
    """,
    re.VERBOSE,
)


def _tokenize(s: str, line_no: int) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(s):
        if s[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(s, pos)
        if not m or m.start() == m.end():
            raise DslParseError(line_no, f"unexpected character '{s[pos]}'")
        kind = m.lastgroup or ""
        val = m.group(kind)
        tokens.append((kind, val))
        pos = m.end()
    return tokens


def _parse_linexpr(tokens: list[tuple[str, str]], line_no: int) -> list[Term]:
    terms: list[Term] = []
    i = 0
    sign = 1.0
    n = len(tokens)
    if n == 0:
        raise DslParseError(line_no, "empty expression")
    while i < n:
        coef = sign
        # optional NUMBER '*'
        if tokens[i][0] == "num" and i + 1 < n and tokens[i + 1][0] == "star":
            coef = sign * float(tokens[i][1])
            i += 2
        kind, val = tokens[i]
        if kind == "num":
            terms.append(Term(coef * float(val), "const", None))
            i += 1
        elif kind == "ident":
            name = val
            i += 1
            carrier: str | None = None
            has_paren = i < n and tokens[i][0] == "lparen"
            if has_paren:
                i += 1  # (
                if i >= n or tokens[i][0] not in ("ident", "str"):
                    raise DslParseError(line_no, f"expected carrier name after '{name}('")
                carrier = tokens[i][1].strip('"')
                i += 1
                if i >= n or tokens[i][0] != "rparen":
                    raise DslParseError(line_no, f"missing ')' after '{name}({carrier}'")
                i += 1
            if carrier is not None:
                if name not in _FUNC_ATOMS:
                    raise DslParseError(line_no, f"'{name}(...)' is not a valid term")
                terms.append(Term(coef, name, carrier))
            else:
                if name not in _BARE_ATOMS:
                    raise DslParseError(
                        line_no,
                        f"unknown term '{name}' (expected gen, cap, emissions, load_shed, cf(carrier))",
                    )
                terms.append(Term(coef, name, None))
        else:
            raise DslParseError(line_no, f"unexpected token '{val}'")
        # separator
        if i < n:
            if tokens[i][0] == "plus":
                sign = 1.0
                i += 1
            elif tokens[i][0] == "minus":
                sign = -1.0
                i += 1
            else:
                raise DslParseError(line_no, f"expected '+' or '-' before '{tokens[i][1]}'")
            if i >= n:
                raise DslParseError(line_no, "expression ends with an operator")
    return terms


def parse_line(raw: str, line_no: int) -> ParsedConstraint:
    """Parse one DSL line into a :class:`ParsedConstraint`. Raises DslParseError."""
    tokens = _tokenize(raw, line_no)
    op_positions = [idx for idx, (k, _) in enumerate(tokens) if k == "op"]
    if len(op_positions) == 0:
        raise DslParseError(line_no, "missing comparator (one of <=, >=, ==)")
    if len(op_positions) > 1:
        raise DslParseError(line_no, "only one comparator allowed per line")
    op_idx = op_positions[0]
    sense = tokens[op_idx][1]
    lhs = _parse_linexpr(tokens[:op_idx], line_no)
    rhs = _parse_linexpr(tokens[op_idx + 1:], line_no)
    return ParsedConstraint(line_no=line_no, raw=raw.strip(), lhs=lhs, sense=sense, rhs=rhs)


def parse_dsl(text: str) -> list[ParsedConstraint]:
    """Parse all non-blank, non-comment lines. Raises on the first bad line."""
    out: list[ParsedConstraint] = []
    for n0, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        out.append(parse_line(line, n0))
    return out


# ── Compilation to linopy ─────────────────────────────────────────────────────
def _carrier_gens(ctx: ModelContext, carrier: str | None) -> list[str]:
    n = ctx.network
    if carrier is None:
        return ctx.supply_gens
    return [g for g in n.generators.index[n.generators.carrier == carrier].tolist()
            if not g.startswith("load_shedding_")]


def _gen_expr(ctx: ModelContext, carrier: str | None):
    gens = _carrier_gens(ctx, carrier)
    if not gens:
        raise ValueError(f"no generators with carrier '{carrier}'")
    return (ctx.gen_p.sel({ctx.dim: gens}) * ctx.weights).sum()


def _cap_expr(ctx: ModelContext, carrier: str | None):
    n = ctx.network
    gens = _carrier_gens(ctx, carrier)
    if not gens:
        raise ValueError(f"no generators with carrier '{carrier}'")
    extendable = [
        g for g in gens
        if "p_nom_extendable" in n.generators.columns and bool(n.generators.at[g, "p_nom_extendable"])
    ]
    fixed = [g for g in gens if g not in extendable]
    total = float(n.generators.loc[fixed, "p_nom"].fillna(0.0).sum())
    if extendable and ctx.cap_var is not None and ctx.cap_dim is not None:
        total = total + ctx.cap_var.sel({ctx.cap_dim: extendable}).sum()
    elif extendable:
        total = total + float(n.generators.loc[extendable, "p_nom"].fillna(0.0).sum())
    return total


def _emissions_expr(ctx: ModelContext, carrier: str | None):
    n = ctx.network
    gens = _carrier_gens(ctx, carrier) if carrier is not None else ctx.supply_gens
    emitters = [
        (g, ctx.emissions_factors.get(n.generators.at[g, "carrier"], 0.0)) for g in gens
    ]
    emitters = [(g, co2) for g, co2 in emitters if co2 > 0]
    if not emitters:
        raise ValueError(
            f"no CO₂-emitting generators{' for carrier ' + repr(carrier) if carrier else ''}"
        )
    return sum(co2 * (ctx.gen_p.sel({ctx.dim: [g]}) * ctx.weights).sum() for g, co2 in emitters)


def _load_shed_expr(ctx: ModelContext):
    if not ctx.shed_gens:
        raise ValueError("no load-shedding generators (enable load shedding in Settings)")
    return (ctx.gen_p.sel({ctx.dim: ctx.shed_gens}) * ctx.weights).sum()


def _term_expr(ctx: ModelContext, term: Term):
    """Return (linear_expr_or_None, constant_float) contribution of a term."""
    if term.kind == "const":
        return None, term.coef
    if term.kind == "gen":
        return term.coef * _gen_expr(ctx, term.carrier), 0.0
    if term.kind == "emissions":
        return term.coef * _emissions_expr(ctx, term.carrier), 0.0
    if term.kind == "load_shed":
        return term.coef * _load_shed_expr(ctx), 0.0
    if term.kind == "cap":
        cap = _cap_expr(ctx, term.carrier)
        if isinstance(cap, (int, float)):
            return None, term.coef * float(cap)
        return term.coef * cap, 0.0
    raise ValueError(f"term '{term.kind}' cannot be used here")


def _combine(ctx: ModelContext, terms: list[Term]):
    lin = None
    const = 0.0
    for t in terms:
        e, c = _term_expr(ctx, t)
        const += c
        if e is not None:
            lin = e if lin is None else lin + e
    return lin, const


def _is_cf_line(pc: ParsedConstraint) -> bool:
    return any(t.kind == "cf" for t in pc.lhs) or any(t.kind == "cf" for t in pc.rhs)


def _compile_cf(ctx: ModelContext, pc: ParsedConstraint):
    """cf(C) <op> number  ⇒  gen(C) <op> number·cap(C)·hours."""
    if (len(pc.lhs) == 1 and pc.lhs[0].kind == "cf" and pc.lhs[0].coef == 1.0
            and len(pc.rhs) == 1 and pc.rhs[0].kind == "const"):
        carrier = pc.lhs[0].carrier
        k = pc.rhs[0].coef
    elif (len(pc.rhs) == 1 and pc.rhs[0].kind == "cf" and pc.rhs[0].coef == 1.0
            and len(pc.lhs) == 1 and pc.lhs[0].kind == "const"):
        carrier = pc.rhs[0].carrier
        k = pc.lhs[0].coef
    else:
        raise ValueError("cf(carrier) must be used as 'cf(carrier) <=|>=|== number' (fraction 0–1)")
    if ctx.modeled_hours <= 0:
        raise ValueError("modeled hours are zero")
    lhs = _gen_expr(ctx, carrier)
    rhs = k * _cap_expr(ctx, carrier) * ctx.modeled_hours
    return lhs, pc.sense, rhs


def _add(model, lin, sense: str, rhs_const: float, name: str):
    if sense == "<=":
        model.add_constraints(lin <= rhs_const, name=name)
    elif sense == ">=":
        model.add_constraints(lin >= rhs_const, name=name)
    else:
        model.add_constraints(lin == rhs_const, name=name)


def apply_dsl_constraints(
    n: pypsa.Network,
    text: str,
    emissions_factors: dict[str, float],
    notes: list[str],
) -> None:
    """Parse and apply the DSL text to ``n.model``. Bad lines are skipped with a note."""
    if not text or not text.strip():
        return
    ctx = build_model_context(n, emissions_factors)
    for n0, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = f"dsl_{n0}"
        try:
            pc = parse_line(line, n0)
            if _is_cf_line(pc):
                lin, sense, rhs = _compile_cf(ctx, pc)
                # move to  lhs - rhs <op> 0  isn't needed; both sides linear → compare directly
                n.model.add_constraints(
                    {"<=": lin <= rhs, ">=": lin >= rhs, "==": lin == rhs}[sense], name=name
                )
                notes.append(f"DSL line {n0}: '{pc.raw}' added.")
                continue
            lhs_lin, lhs_c = _combine(ctx, pc.lhs)
            rhs_lin, rhs_c = _combine(ctx, pc.rhs)
            combined = None
            if lhs_lin is not None:
                combined = lhs_lin
            if rhs_lin is not None:
                combined = (-rhs_lin) if combined is None else (combined - rhs_lin)
            if combined is None:
                raise ValueError("constraint has no decision variables")
            rhs_const = rhs_c - lhs_c
            _add(n.model, combined, pc.sense, rhs_const, name)
            notes.append(f"DSL line {n0}: '{pc.raw}' added.")
        except DslParseError as exc:
            notes.append(f"DSL line {n0}: parse error — {exc.message}")
        except Exception as exc:  # noqa: BLE001 — never crash the solve on one bad line
            notes.append(f"DSL line {n0}: could not be added — {exc}")
