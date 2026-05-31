/**
 * Parse the human-friendly constraint code box into a structured JSON spec
 * (the wire format the frontend sends to the backend). Mirrors the backend
 * parser in backend/pypsa/network/constraint_dsl.py — keep the two in sync.
 *
 * Grammar (one constraint per line; `#` comments; blank lines ignored):
 *   line    := linexpr ("<="|">="|"==") linexpr
 *   linexpr := term (("+"|"-") term)*
 *   term    := [NUMBER "*"] atom
 *   atom    := ("gen"|"cap"|"cf"|"emissions") ["(" CARRIER ")"] | "load_shed" | NUMBER
 */
import { ConstraintSpec, ConstraintTerm, ConstraintTermKind } from '../types';

const FUNC_ATOMS = new Set(['gen', 'cap', 'cf', 'emissions']);
const BARE_ATOMS = new Set(['gen', 'cap', 'emissions', 'load_shed']);
const SENSES = new Set(['<=', '>=', '==']);

export interface ParsedConstraintLine {
  spec?: ConstraintSpec;
  lineNo: number;
  raw: string;
  error?: string;
}

type Token = { kind: string; val: string };

const TOKEN_RE = /\s*(<=|>=|==|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|"[^"]*"|[A-Za-z_][A-Za-z0-9_]*|\(|\)|\*|\+|-)/y;

function tokenize(s: string): Token[] | string {
  const tokens: Token[] = [];
  let pos = 0;
  while (pos < s.length) {
    if (/\s/.test(s[pos])) { pos += 1; continue; }
    TOKEN_RE.lastIndex = pos;
    const m = TOKEN_RE.exec(s);
    if (!m || m.index !== pos) return `unexpected character '${s[pos]}'`;
    const raw = m[1];
    let kind: string;
    if (raw === '<=' || raw === '>=' || raw === '==') kind = 'op';
    else if (/^[0-9]/.test(raw)) kind = 'num';
    else if (raw.startsWith('"')) kind = 'str';
    else if (/^[A-Za-z_]/.test(raw)) kind = 'ident';
    else kind = { '(': 'lparen', ')': 'rparen', '*': 'star', '+': 'plus', '-': 'minus' }[raw] ?? 'op';
    tokens.push({ kind, val: raw });
    pos += m[0].length;
  }
  return tokens;
}

function parseLinexpr(tokens: Token[]): ConstraintTerm[] | string {
  const terms: ConstraintTerm[] = [];
  let i = 0;
  let sign = 1;
  const n = tokens.length;
  if (n === 0) return 'empty expression';
  while (i < n) {
    let coef = sign;
    if (tokens[i].kind === 'num' && i + 1 < n && tokens[i + 1].kind === 'star') {
      coef = sign * parseFloat(tokens[i].val);
      i += 2;
    }
    const tok = tokens[i];
    if (tok.kind === 'num') {
      terms.push({ coef: coef * parseFloat(tok.val), kind: 'const' });
      i += 1;
    } else if (tok.kind === 'ident') {
      const name = tok.val;
      i += 1;
      let carrier: string | undefined;
      if (i < n && tokens[i].kind === 'lparen') {
        i += 1;
        if (i >= n || (tokens[i].kind !== 'ident' && tokens[i].kind !== 'str')) {
          return `expected carrier name after '${name}('`;
        }
        carrier = tokens[i].val.replace(/^"|"$/g, '');
        i += 1;
        if (i >= n || tokens[i].kind !== 'rparen') return `missing ')' after '${name}(${carrier}'`;
        i += 1;
      }
      if (carrier !== undefined) {
        if (!FUNC_ATOMS.has(name)) return `'${name}(...)' is not a valid term`;
        terms.push({ coef, kind: name as ConstraintTermKind, carrier });
      } else {
        if (!BARE_ATOMS.has(name)) return `unknown term '${name}'`;
        terms.push({ coef, kind: name as ConstraintTermKind });
      }
    } else {
      return `unexpected token '${tok.val}'`;
    }
    if (i < n) {
      if (tokens[i].kind === 'plus') { sign = 1; i += 1; }
      else if (tokens[i].kind === 'minus') { sign = -1; i += 1; }
      else return `expected '+' or '-' before '${tokens[i].val}'`;
      if (i >= n) return 'expression ends with an operator';
    }
  }
  return terms;
}

function parseLine(raw: string, lineNo: number): ParsedConstraintLine {
  const toks = tokenize(raw);
  if (typeof toks === 'string') return { lineNo, raw, error: toks };
  const opIdx = toks.map((t, idx) => (t.kind === 'op' ? idx : -1)).filter((x) => x >= 0);
  if (opIdx.length === 0) return { lineNo, raw, error: 'missing comparator (one of <=, >=, ==)' };
  if (opIdx.length > 1) return { lineNo, raw, error: 'only one comparator allowed per line' };
  const sense = toks[opIdx[0]].val;
  if (!SENSES.has(sense)) return { lineNo, raw, error: 'invalid comparator' };
  const lhs = parseLinexpr(toks.slice(0, opIdx[0]));
  if (typeof lhs === 'string') return { lineNo, raw, error: lhs };
  const rhs = parseLinexpr(toks.slice(opIdx[0] + 1));
  if (typeof rhs === 'string') return { lineNo, raw, error: rhs };
  return { lineNo, raw, spec: { id: raw.trim(), lhs, sense: sense as ConstraintSpec['sense'], rhs } };
}

/** Parse the whole code box; returns per-line results (spec or error). */
export function parseConstraintDsl(text: string): ParsedConstraintLine[] {
  const out: ParsedConstraintLine[] = [];
  text.split(/\r?\n/).forEach((rawLine, idx) => {
    const line = rawLine.split('#', 1)[0].trim();
    if (!line) return;
    out.push(parseLine(line, idx + 1));
  });
  return out;
}

/** Convenience: just the valid specs (drops lines with parse errors). */
export function dslToSpecs(text: string): ConstraintSpec[] {
  return parseConstraintDsl(text)
    .map((r) => r.spec)
    .filter((s): s is ConstraintSpec => !!s);
}
