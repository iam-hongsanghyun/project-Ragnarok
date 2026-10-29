/**
 * Hierarchical agglomerative clustering (HAC) options for Forge -> Reduce / cluster network.
 *
 * HAC groups buses by distance in a feature space built from numeric bus columns (default x, y), merged bottom-up with
 * a linkage criterion (`POST /api/transform/cluster`, method `hac`: hacFeatures, hacAffinity, hacLinkage). The number of
 * clusters is the shared "Target buses" field. Ward linkage needs the euclidean (or l2) metric; the server refuses other pairs.
 */
import React, { useMemo } from 'react';
import type { GridRow } from 'lib/types';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';

export interface HacOptionsValue {
  /** Numeric bus columns forming the feature matrix. */
  features: string[];
  affinity: string;
  linkage: string;
}

export const DEFAULT_HAC: HacOptionsValue = { features: ['x', 'y'], affinity: 'euclidean', linkage: 'ward' };

export const HAC_AFFINITIES = ['euclidean', 'l1', 'l2', 'manhattan', 'cosine'] as const;
export const HAC_LINKAGES = ['ward', 'complete', 'average', 'single'] as const;

/** Columns of the bus rows holding a finite number on every bus (the only usable HAC features). */
export function numericBusColumns(rows: GridRow[]): string[] {
  if (rows.length === 0) return [];
  const cols = new Set<string>();
  rows.forEach((r) => Object.keys(r).forEach((k) => cols.add(k)));
  const isNumeric = (v: unknown) =>
    (typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)));
  return Array.from(cols).filter((c) => c !== 'name' && rows.every((r) => isNumeric(r[c]))).sort();
}

export interface HacOptionsProps {
  busRows: GridRow[];
  value: HacOptionsValue;
  onChange: (next: HacOptionsValue) => void;
}

export function HacOptions({ busRows, value, onChange }: HacOptionsProps) {
  const numeric = useMemo(() => numericBusColumns(busRows), [busRows]);
  const wardNeedsEuclidean = value.linkage === 'ward' && value.affinity !== 'euclidean' && value.affinity !== 'l2';
  return (
    <>
      <div className="sg-setting-row">
        <label className="sg-setting-label">HAC features</label>
        <SearchableMultiSelect
          values={value.features}
          options={numeric}
          placeholder="x, y (default)"
          onChange={(features) => onChange({ ...value, features })}
        />
        <p className="sg-setting-hint">
          Numeric bus columns whose values place each bus in feature space (a column must be filled on every bus).
          {numeric.length === 0 ? ' No numeric bus column found.' : ` ${value.features.length === 0 ? 'x and y are used when none is picked.' : `${value.features.length} selected.`}`}
        </p>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="forge-hac-affinity">Distance metric</label>
        <select id="forge-hac-affinity" className="forge-select" value={value.affinity} onChange={(e) => onChange({ ...value, affinity: e.target.value })}>
          {HAC_AFFINITIES.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>
      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="forge-hac-linkage">Linkage</label>
        <select id="forge-hac-linkage" className="forge-select" value={value.linkage} onChange={(e) => onChange({ ...value, linkage: e.target.value })}>
          {HAC_LINKAGES.map((l) => <option key={l} value={l}>{l}</option>)}
        </select>
        <p className="sg-setting-hint">
          ward minimises within-cluster variance; complete, average and single merge by the farthest, mean or nearest pair of buses.
        </p>
        {wardNeedsEuclidean && <p className="sg-setting-hint" role="alert">Ward linkage requires the euclidean (or l2) metric; the server refuses this pair.</p>}
      </div>
    </>
  );
}
