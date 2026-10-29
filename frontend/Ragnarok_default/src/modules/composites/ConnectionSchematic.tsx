/**
 * ConnectionSchematic — a block diagram of how a composite asset plugs into the network, drawn from `Connections`
 * (`lib/build/connections.ts`), i.e. from the PyPSA rows themselves, never from the asset type.
 *
 * Buses are vertical bars (solid = already in the model, dashed = created by the asset), components are boxes, arrows follow the
 * energy direction and carry the carrier of the bus. Columns are found by walking the arrows from the buses nothing feeds, so the
 * same code lays out a generator, a turbine fed by two fuel buses or an electrolyser chain.
 */
import React from 'react';
import { carrierWord, type Connections, type Edge } from 'lib/build/connections';

const COL_W = 200;
const BOX_W = 136;
const BOX_H = 44;
const BAR_W = 10;
const ROW_H = 78;
const PAD = 24;

interface Placed { id: string; x: number; y: number; w: number; h: number; kind: 'bus' | 'component'; label: string; sub: string; created: boolean }

/** Column of every node: buses even, components odd; a component sits one column right of its latest input and feeds the column after. */
function columns(c: Connections): Map<string, number> {
  const slot = new Map<string, number>();
  c.nodes.forEach((n) => slot.set(n.id, n.kind === 'bus' ? 0 : 1));
  const id = (e: Edge) => `${e.sheet}:${e.name}`;
  for (let pass = 0; pass < 8; pass += 1) {
    let changed = false;
    for (const n of c.nodes.filter((x) => x.kind === 'component')) {
      const mine = c.edges.filter((e) => id(e) === n.id);
      const feeds = mine.filter((e) => e.direction !== 'out').map((e) => slot.get(`bus:${e.bus}`) ?? 0);
      const s = feeds.length ? Math.max(...feeds) + 1 : 1;
      if (s !== slot.get(n.id)) { slot.set(n.id, s); changed = true; }
      for (const e of mine.filter((x) => x.direction === 'out')) {
        const b = `bus:${e.bus}`;
        if ((slot.get(b) ?? 0) < s + 1) { slot.set(b, s + 1); changed = true; }
      }
    }
    if (!changed) break;
  }
  const used = Array.from(new Set(slot.values())).sort((a, b) => a - b);
  const dense = new Map<string, number>();
  slot.forEach((v, k) => dense.set(k, used.indexOf(v)));
  return dense;
}

export function ConnectionSchematic({ connections }: { connections: Connections }) {
  const markerId = React.useId().replace(/[^A-Za-z0-9_-]/g, '');
  const { placed, width, height, lines } = React.useMemo(() => {
    const col = columns(connections);
    const byCol = new Map<number, Placed[]>();
    for (const n of connections.nodes) {
      const k = col.get(n.id) ?? 0;
      const degree = connections.edges.filter((e) => (n.kind === 'bus' ? `bus:${e.bus}` : `${e.sheet}:${e.name}`) === n.id).length;
      const h = n.kind === 'bus' ? Math.max(BOX_H, degree * 16) : BOX_H;
      const p: Placed = { id: n.id, x: PAD + k * COL_W + (n.kind === 'bus' ? 0 : 0), y: 0, w: n.kind === 'bus' ? BAR_W : BOX_W, h, kind: n.kind, label: n.label, sub: n.sub, created: n.created };
      byCol.set(k, [...(byCol.get(k) ?? []), p]);
    }
    const colHeights = Array.from(byCol.values()).map((list) => list.reduce((s, p) => s + p.h, 0) + (list.length - 1) * (ROW_H - BOX_H));
    const total = Math.max(BOX_H, ...colHeights);
    const all: Placed[] = [];
    byCol.forEach((list) => {
      let y = PAD + 14 + (total - (list.reduce((s, p) => s + p.h, 0) + (list.length - 1) * (ROW_H - BOX_H))) / 2;
      list.forEach((p) => { p.y = y; y += p.h + (ROW_H - BOX_H); all.push(p); });
    });
    const index = new Map(all.map((p) => [p.id, p]));
    const seen = new Map<string, number>();
    const attach = (nodeId: string): number => {
      const p = index.get(nodeId) as Placed;
      const degree = connections.edges.filter((e) => (p.kind === 'bus' ? `bus:${e.bus}` : `${e.sheet}:${e.name}`) === nodeId).length;
      const i = seen.get(nodeId) ?? 0;
      seen.set(nodeId, i + 1);
      return p.y + ((i + 1) / (degree + 1)) * p.h;
    };
    const ls = connections.edges.map((e) => {
      const b = index.get(`bus:${e.bus}`) as Placed;
      const c = index.get(`${e.sheet}:${e.name}`) as Placed;
      const from = e.direction === 'in' || e.direction === 'both' ? b : c;
      const to = e.direction === 'in' || e.direction === 'both' ? c : b;
      const x1 = from.x + from.w;
      const x2 = to.x;
      const y1 = attach(from.id);
      const y2 = attach(to.id);
      const mid = (x1 + x2) / 2;
      return { key: `${e.sheet}:${e.name}:${e.column}`, d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`, both: e.direction === 'both', label: carrierWord(connections.nodes.find((n) => n.id === `bus:${e.bus}`)?.sub ?? ''), lx: mid, ly: (y1 + y2) / 2 - 4 };
    });
    const maxCol = Math.max(0, ...Array.from(byCol.keys()));
    return { placed: all, width: PAD * 2 + maxCol * COL_W + BOX_W + 40, height: total + PAD * 2 + 14, lines: ls };
  }, [connections]);

  if (placed.length === 0) return <p className="cmp-note">Nothing to draw yet.</p>;
  return (
    <figure className="cmp-schematic" data-testid="connection-schematic">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Connection schematic">
        <defs>
          <marker id={`${markerId}-a`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="cmp-arrow-head" />
          </marker>
        </defs>
        {lines.map((l) => (
          <g key={l.key}>
            <path d={l.d} className="cmp-edge" markerEnd={`url(#${markerId}-a)`} markerStart={l.both ? `url(#${markerId}-a)` : undefined} />
            <text x={l.lx} y={l.ly} textAnchor="middle" className="cmp-edge-label">{l.label}</text>
          </g>
        ))}
        {placed.map((p) => p.kind === 'bus' ? (
          <g key={p.id}>
            <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={2} className={p.created ? 'cmp-bus cmp-bus--created' : 'cmp-bus'} />
            <text x={p.x} y={p.y - 14} textAnchor="start" className="cmp-node-label"><title>{p.label}</title>{p.label.length > 26 ? `${p.label.slice(0, 25)}...` : p.label}</text>
            <text x={p.x} y={p.y - 3} textAnchor="start" className="cmp-node-sub">{p.sub}{p.created ? ', created' : ''}</text>
          </g>
        ) : (
          <g key={p.id}>
            <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={5} className="cmp-box" />
            <text x={p.x + p.w / 2} y={p.y + 19} textAnchor="middle" className="cmp-node-label">{p.label.length > 20 ? `${p.label.slice(0, 19)}...` : p.label}</text>
            <text x={p.x + p.w / 2} y={p.y + 34} textAnchor="middle" className="cmp-node-sub">{p.sub.length > 24 ? `${p.sub.slice(0, 23)}...` : p.sub}</text>
          </g>
        ))}
      </svg>
      <figcaption className="cmp-note">Bars are buses (solid: already in the model; dashed: created by this composite). Boxes are the PyPSA components it writes. Arrows show the direction of energy; the label is the carrier of the bus.</figcaption>
    </figure>
  );
}
