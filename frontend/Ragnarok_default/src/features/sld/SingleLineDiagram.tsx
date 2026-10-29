/**
 * SingleLineDiagram — the working model drawn as a textbook one-line diagram.
 *
 * Buses are thick bars in voltage bands (highest at the top, dotted dividers), generators are circles with a sine wave above
 * their bus, loads are arrows below it, lines are orthogonal wires, links are dashed wires with a direction arrow, transformers
 * are two overlapping circles, composites are one labelled box. Geometry comes from `layout.ts` (pure, memoised here); this file
 * draws it and adds pan / zoom, a hover tooltip, click-to-select and SVG export. Events are delegated once on the SVG.
 */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { buildSldLayout, SLD, type SldBus, type SldEdge, type SldItem, type SldLayout, type SldOptions } from './layout';
import './sld.css';

/** Drawing colours are literals, not CSS variables, so the exported SVG looks the same outside the app. */
const INK = '#1f2937';
const FAINT = '#9ca3af';
const LINE = '#0f766e';
const LINK = '#0369a1';
const TRAFO = '#b45309';
const SELECT = '#1d4ed8';
const FONT = 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif';

export interface SingleLineDiagramProps {
  model: WorkbookModel;
  /** Called with the component's sheet (`buses`, `generators`, `lines`, ... or `RAGNAROK_Composites`) and its name. */
  onSelect?: (sheet: string, name: string) => void;
}

interface View { k: number; tx: number; ty: number }

const trunc = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}~` : s);
const keyOf = (sheet: string, name: string): string => `${sheet}\u0000${name}`;

function GeneratorSymbol({ item, bus }: { item: SldItem; bus: SldBus }) {
  const cx = item.x;
  const cy = bus.y - 39;
  return (
    <g>
      <line x1={cx} y1={bus.y} x2={cx} y2={cy + 13} stroke={INK} strokeWidth={1.5} />
      <circle cx={cx} cy={cy} r={13} fill="#ffffff" stroke={item.color} strokeWidth={2.5} />
      <path d={`M ${cx - 8} ${cy} C ${cx - 5} ${cy - 9} ${cx - 3} ${cy - 9} ${cx} ${cy} S ${cx + 5} ${cy + 9} ${cx + 8} ${cy}`} fill="none" stroke={INK} strokeWidth={1.4} />
      <text x={cx} y={cy - 17} textAnchor="middle" fontSize={10} fontFamily={FONT} fill={INK}>{trunc(item.label, 9)}</text>
    </g>
  );
}

function StorageSymbol({ item, bus }: { item: SldItem; bus: SldBus }) {
  const cx = item.x;
  const top = bus.y - 44;
  return (
    <g>
      <line x1={cx} y1={bus.y} x2={cx} y2={top + 20} stroke={INK} strokeWidth={1.5} />
      <rect x={cx - 11} y={top} width={22} height={20} rx={2} fill="#ffffff" stroke={INK} strokeWidth={1.5} />
      <rect x={cx - 4} y={top - 3} width={8} height={3} fill={INK} />
      <rect x={cx - 8} y={top + 9} width={16} height={8} fill={item.color} opacity={0.85} />
      <text x={cx} y={top - 7} textAnchor="middle" fontSize={10} fontFamily={FONT} fill={INK}>{trunc(item.label, 9)}</text>
    </g>
  );
}

function CompositeSymbol({ item, bus }: { item: SldItem; bus: SldBus }) {
  const w = item.w - 12;
  const top = bus.y - 64;
  return (
    <g>
      <line x1={item.x} y1={bus.y} x2={item.x} y2={top + 36} stroke={INK} strokeWidth={1.5} />
      <rect x={item.x - w / 2} y={top} width={w} height={36} rx={3} fill="#f5f3ff" stroke={item.color} strokeWidth={2} />
      <text x={item.x} y={top + 15} textAnchor="middle" fontSize={10.5} fontWeight={600} fontFamily={FONT} fill={INK}>{trunc(item.label, 18)}</text>
      <text x={item.x} y={top + 29} textAnchor="middle" fontSize={9.5} fontFamily={FONT} fill="#4b5563">{trunc(item.name, 16)}</text>
    </g>
  );
}

function LoadSymbol({ item, bus }: { item: SldItem; bus: SldBus }) {
  const y0 = bus.y + bus.h;
  return (
    <g>
      <line x1={item.x} y1={y0} x2={item.x} y2={y0 + 16} stroke={INK} strokeWidth={1.5} />
      <polygon points={`${item.x - 5},${y0 + 14} ${item.x + 5},${y0 + 14} ${item.x},${y0 + 24}`} fill={INK} />
      <text x={item.x} y={y0 + 36} textAnchor="middle" fontSize={9.5} fontFamily={FONT} fill="#4b5563">{trunc(item.label, 7)}</text>
    </g>
  );
}

function MoreChip({ item, bus, below }: { item: SldItem; bus: SldBus; below: boolean }) {
  const y = below ? bus.y + bus.h + 6 : bus.y - 24;
  return (
    <g>
      <rect x={item.x - 15} y={y} width={30} height={16} rx={8} fill="#e5e7eb" stroke={FAINT} />
      <text x={item.x} y={y + 12} textAnchor="middle" fontSize={10} fontFamily={FONT} fill={INK}>{item.label}</text>
    </g>
  );
}

function ItemShape({ item, bus, below }: { item: SldItem; bus: SldBus; below: boolean }) {
  switch (item.kind) {
    case 'generator': return <GeneratorSymbol item={item} bus={bus} />;
    case 'storage_unit':
    case 'store': return <StorageSymbol item={item} bus={bus} />;
    case 'composite': return <CompositeSymbol item={item} bus={bus} />;
    case 'load': return <LoadSymbol item={item} bus={bus} />;
    default: return <MoreChip item={item} bus={bus} below={below} />;
  }
}

/** Hit boxes are drawn per item so one delegated listener can read `data-sld-*` from the event target. */
function itemBox(item: SldItem, bus: SldBus): { x: number; y: number; w: number; h: number } {
  if (item.kind === 'load') return { x: item.x - 16, y: bus.y + bus.h, w: 32, h: 42 };
  if (item.kind === 'composite') return { x: item.x - (item.w - 12) / 2, y: bus.y - 64, w: item.w - 12, h: 64 };
  return { x: item.x - 22, y: bus.y - 62, w: 44, h: 62 };
}

function EdgeShape({ edge, selected }: { edge: SldEdge; selected: boolean }) {
  const pts = edge.points.map((p) => p.join(',')).join(' ');
  const color = edge.sheet === 'links' ? LINK : edge.sheet === 'transformers' ? TRAFO : LINE;
  return (
    <g data-sld-sheet={edge.sheet} data-sld-name={edge.name} data-sld-id={keyOf(edge.sheet, edge.name)} style={{ cursor: 'pointer' }}>
      <polyline points={pts} fill="none" stroke="transparent" strokeWidth={10} pointerEvents="stroke" />
      <polyline points={pts} fill="none" stroke={selected ? SELECT : color} strokeWidth={selected ? 2.6 : 1.8} strokeDasharray={edge.sheet === 'links' ? '7 4' : undefined} strokeLinejoin="round" />
      {edge.arrow && (
        <polygon points="-6,-5 6,0 -6,5" fill={selected ? SELECT : color} transform={`translate(${edge.arrow.x} ${edge.arrow.y}) rotate(${edge.arrow.angle})`} />
      )}
      {edge.symbol && (
        <g>
          <circle cx={edge.symbol.x} cy={edge.symbol.y - 5} r={9} fill="#ffffff" stroke={selected ? SELECT : color} strokeWidth={1.8} />
          <circle cx={edge.symbol.x} cy={edge.symbol.y + 5} r={9} fill="none" stroke={selected ? SELECT : color} strokeWidth={1.8} />
        </g>
      )}
    </g>
  );
}

/** The drawing itself, in layout coordinates (no pan / zoom): also what the export serialises. */
export function SldDrawing({ layout, selected }: { layout: SldLayout; selected: string | null }) {
  return (
    <g>
      <rect x={0} y={0} width={layout.width} height={layout.height} fill="#ffffff" />
      {layout.bands.map((band) => (
        <g key={band.key} data-sld-band={band.key}>
          {band.dividerY !== null && <line x1={8} y1={band.dividerY} x2={layout.width - 8} y2={band.dividerY} stroke={FAINT} strokeWidth={1.2} strokeDasharray="2 5" />}
          <text x={10} y={band.y0 + 20} fontSize={13} fontWeight={700} fontFamily={FONT} fill={INK}>{band.label}</text>
        </g>
      ))}
      {layout.edges.map((e) => <EdgeShape key={e.id} edge={e} selected={selected === keyOf(e.sheet, e.name)} />)}
      {layout.buses.map((bus) => (
        <g key={bus.name}>
          <g data-sld-sheet="buses" data-sld-name={bus.name} data-sld-id={keyOf('buses', bus.name)} style={{ cursor: 'pointer' }}>
            <rect x={bus.x} y={bus.y - 6} width={bus.w} height={bus.h + 12} fill="transparent" />
            <rect x={bus.x} y={bus.y} width={bus.w} height={bus.h} rx={1} fill={selected === keyOf('buses', bus.name) ? SELECT : INK} />
            <text x={bus.x + 2} y={bus.y - 5} fontSize={10.5} fontWeight={600} fontFamily={FONT} fill={INK}>{bus.label}</text>
          </g>
          {[...bus.top, ...bus.loads].map((item) => {
            const box = itemBox(item, bus);
            const isSelected = selected === keyOf(item.sheet, item.name);
            return (
              <g key={item.id} data-sld-sheet={item.sheet} data-sld-name={item.name} data-sld-id={item.id} style={{ cursor: item.kind === 'more' ? 'default' : 'pointer' }}>
                <rect x={box.x} y={box.y} width={box.w} height={box.h} fill="transparent" />
                {isSelected && <rect x={box.x} y={box.y} width={box.w} height={box.h} fill="none" stroke={SELECT} strokeWidth={1.5} strokeDasharray="3 2" />}
                <ItemShape item={item} bus={bus} below={bus.loads.includes(item)} />
              </g>
            );
          })}
        </g>
      ))}
    </g>
  );
}

function tooltipIndex(layout: SldLayout): Map<string, string[]> {
  const out = new Map<string, string[]>();
  layout.buses.forEach((b) => {
    out.set(keyOf('buses', b.name), b.tooltip);
    [...b.top, ...b.loads].forEach((i) => out.set(i.id, i.tooltip));
  });
  layout.edges.forEach((e) => out.set(keyOf(e.sheet, e.name), e.tooltip));
  return out;
}

export function SingleLineDiagram({ model, onSelect }: SingleLineDiagramProps) {
  const [showNonElectric, setShowNonElectric] = usePersistedState<boolean>('ui:sld-non-electric', false);
  const [voltage, setVoltage] = useState<number | null>(null);
  const [area, setArea] = useState<string | null>(null);
  const [drawLarge, setDrawLarge] = useState(false);
  const options: SldOptions = useMemo(() => ({ showNonElectric, voltageFilter: voltage, areaFilter: area, drawLarge }), [showNonElectric, voltage, area, drawLarge]);
  const layout = useMemo(() => buildSldLayout(model, options), [model, options]);
  const tips = useMemo(() => tooltipIndex(layout), [layout]);

  const frameRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 });
  const [selected, setSelected] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; lines: string[] } | null>(null);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  const fit = useCallback(() => {
    if (size.w === 0 || size.h === 0 || layout.width === 0) return;
    const k = Math.min(size.w / layout.width, size.h / layout.height, 1.6);
    setView({ k, tx: (size.w - layout.width * k) / 2, ty: Math.max(0, (size.h - layout.height * k) / 2) });
  }, [size, layout]);

  useLayoutEffect(() => {
    const el = frameRef.current;
    if (!el) return undefined;
    const read = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    read();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // refit when the drawing changes or the pane is first measured / resized
  useEffect(() => { fit(); }, [fit]);

  // wheel zoom about the pointer; needs a non-passive listener to stop the page scrolling
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return undefined;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      setView((v) => {
        const k = Math.min(8, Math.max(0.03, v.k * Math.exp(-ev.deltaY * 0.0015)));
        const f = k / v.k;
        return { k, tx: px - (px - v.tx) * f, ty: py - (py - v.ty) * f };
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const target = (ev: React.SyntheticEvent): Element | null => (ev.target as Element | null)?.closest?.('[data-sld-id]') ?? null;

  const onPointerDown = (ev: React.PointerEvent) => { drag.current = { x: ev.clientX, y: ev.clientY, moved: false }; };
  const onPointerMove = (ev: React.PointerEvent) => {
    const d = drag.current;
    if (d && (ev.buttons & 1) === 1) {
      const dx = ev.clientX - d.x;
      const dy = ev.clientY - d.y;
      if (d.moved || Math.abs(dx) + Math.abs(dy) > 3) {
        d.moved = true;
        d.x = ev.clientX;
        d.y = ev.clientY;
        setTip(null);
        setView((v) => ({ ...v, tx: v.tx + dx, ty: v.ty + dy }));
      }
      return;
    }
    const el = target(ev);
    const lines = el ? tips.get(el.getAttribute('data-sld-id') ?? '') : undefined;
    const rect = frameRef.current?.getBoundingClientRect();
    if (el && lines && rect) setTip({ x: ev.clientX - rect.left + 14, y: ev.clientY - rect.top + 14, lines });
    else setTip(null);
  };
  const onPointerUp = (ev: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) return;
    const el = target(ev);
    const sheet = el?.getAttribute('data-sld-sheet');
    const name = el?.getAttribute('data-sld-name');
    if (!el || !sheet || !name) { setSelected(null); return; }
    setSelected(keyOf(sheet, name));
    onSelect?.(sheet, name);
  };

  const download = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
    clone.setAttribute('width', String(layout.width));
    clone.setAttribute('height', String(layout.height));
    clone.querySelector('[data-sld-content]')?.removeAttribute('transform');
    const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'single-line-diagram.svg';
    a.click();
    URL.revokeObjectURL(url);
  };

  const electricCount = layout.buses.length;
  return (
    <div className="sld" data-testid="sld">
      <div className="sld-toolbar">
        <label className="sld-check">
          <input type="checkbox" checked={showNonElectric} onChange={(e) => setShowNonElectric(e.target.checked)} />
          <span>Show non-electric buses</span>
        </label>
        {layout.voltageLevels.length > 1 && (
          <label className="sld-select">
            <span>Voltage level</span>
            <select value={voltage === null ? '' : String(voltage)} onChange={(e) => setVoltage(e.target.value === '' ? null : Number(e.target.value))}>
              <option value="">All</option>
              {layout.voltageLevels.map((v) => <option key={v} value={String(v)}>{v} kV</option>)}
            </select>
          </label>
        )}
        {layout.areas.length > 1 && (
          <label className="sld-select">
            <span>Area</span>
            <select value={area ?? ''} onChange={(e) => setArea(e.target.value === '' ? null : e.target.value)}>
              <option value="">All</option>
              {layout.areas.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
        )}
        <span className="sld-spacer" />
        <span className="sld-count">{layout.tooLarge ? `${layout.busCount} buses` : `${electricCount} buses, ${layout.edges.length} connections`}</span>
        <button type="button" className="sld-btn" onClick={fit} disabled={layout.tooLarge}>Fit to view</button>
        <button type="button" className="sld-btn" onClick={download} disabled={layout.tooLarge || electricCount === 0}>Download SVG</button>
      </div>
      <div
        className="sld-frame"
        ref={frameRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => { drag.current = null; setTip(null); }}
      >
        {layout.tooLarge ? (
          <div className="sld-notice" role="status">
            <p>This model has {layout.busCount} buses. A one-line diagram of that many is hard to read and slow to draw (the limit for the automatic view is {SLD.maxBuses}).</p>
            <p>Filter to one voltage level or area, or draw everything anyway.</p>
            <div className="sld-notice-actions">
              {layout.voltageLevels.length > 0 && (
                <label className="sld-select">
                  <span>Voltage level</span>
                  <select value="" onChange={(e) => setVoltage(e.target.value === '' ? null : Number(e.target.value))}>
                    <option value="">Choose</option>
                    {layout.voltageLevels.map((v) => <option key={v} value={String(v)}>{v} kV</option>)}
                  </select>
                </label>
              )}
              {layout.areas.length > 0 && (
                <label className="sld-select">
                  <span>Area</span>
                  <select value="" onChange={(e) => setArea(e.target.value === '' ? null : e.target.value)}>
                    <option value="">Choose</option>
                    {layout.areas.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
              )}
              <button type="button" className="sld-btn" onClick={() => setDrawLarge(true)}>Draw all {layout.busCount} buses</button>
            </div>
          </div>
        ) : electricCount === 0 ? (
          <div className="sld-notice" role="status"><p>No buses to draw. Add buses in the model, or switch on non-electric buses.</p></div>
        ) : (
          <svg ref={svgRef} className="sld-svg" width="100%" height="100%" role="img" aria-label="Single-line diagram">
            <g data-sld-content="" transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
              <SldDrawing layout={layout} selected={selected} />
            </g>
          </svg>
        )}
        {tip && (
          <div className="sld-tip" style={{ left: tip.x, top: tip.y }}>
            {tip.lines.map((l, i) => <div key={i} className={i === 0 ? 'sld-tip-title' : undefined}>{l}</div>)}
          </div>
        )}
        {layout.skippedEdges > 0 && !layout.tooLarge && <div className="sld-foot">{layout.skippedEdges} connection(s) not drawn (an end is hidden or inside a composite)</div>}
      </div>
    </div>
  );
}
