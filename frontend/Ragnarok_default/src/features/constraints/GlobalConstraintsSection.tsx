import React from 'react';
import { ConstraintMetric, CustomConstraint } from 'lib/types';
import { METRIC_DEFS } from 'lib/constants';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';

/**
 * Human-readable constraint title composed from its parts, e.g.
 *   "CO₂ Intensity Cap ≤ 0 tCO₂/MWh"
 *   "Max Carrier Generation (coal) ≤ 5000 MWh"
 * Used as the auto-filled label; the user can override it.
 */
function autoLabel(metric: ConstraintMetric, carrier: string, value: number): string {
  const def = METRIC_DEFS[metric];
  const carrierPart = def.needsCarrier && carrier ? ` (${carrier})` : '';
  return `${def.label}${carrierPart} ${def.sense} ${value} ${def.unit}`.trim();
}

export function GlobalConstraintsSection({
  constraints,
  carriers,
  onChange,
}: {
  constraints: CustomConstraint[];
  carriers: string[];
  onChange: (next: CustomConstraint[]) => void;
}) {
  const update = (id: string, patch: Partial<CustomConstraint>) =>
    onChange(
      constraints.map((c) => {
        if (c.id !== id) return c;
        // A direct label edit wins and stops the title from auto-following.
        if ('label' in patch) return { ...c, ...patch };
        const merged = { ...c, ...patch };
        // Keep the title in sync with metric / carrier / sense / value while it
        // is still the auto-generated value (or empty). A title the user has
        // typed themselves is preserved.
        const wasAuto =
          c.label.trim() === '' || c.label === autoLabel(c.metric, c.carrier, c.value);
        if (wasAuto) merged.label = autoLabel(merged.metric, merged.carrier, merged.value);
        return merged;
      }),
    );

  const handleAdd = () => {
    const metric: ConstraintMetric = 'co2_cap';
    const def = METRIC_DEFS[metric];
    const carrier = def.needsCarrier ? (carriers[0] ?? '') : '';
    const value = 0;
    const nc: CustomConstraint = {
      id: `cc_${Date.now()}`,
      enabled: true,
      label: autoLabel(metric, carrier, value),
      metric,
      carrier,
      value,
      unit: def.unit,
    };
    onChange([...constraints, nc]);
  };

  const handleMetricChange = (id: string, nextMetric: ConstraintMetric) => {
    const def = METRIC_DEFS[nextMetric];
    const current = constraints.find((c) => c.id === id);
    // metric/unit/carrier change here; `update` re-derives the title if it was
    // still auto-generated.
    update(id, {
      metric: nextMetric,
      unit: def.unit,
      carrier: def.needsCarrier ? (current?.carrier || carriers[0] || '') : '',
    });
  };

  const activeCount = constraints.filter((c) => c.enabled).length;

  if (constraints.length === 0) {
    return (
      <div className="constraints-empty">
        <p>No custom solver constraints yet. Add one below to cap CO₂ intensity, carrier output, or capacity factors.</p>
        <button className="tb-btn" onClick={handleAdd}>+ Add constraint</button>
      </div>
    );
  }

  return (
    <div className="constraints-table-wrap">
      {activeCount > 0 && (
        <div className="gcc-active-row">
          <span className="gcc-active-dot" />
          <span className="gcc-active-label">{activeCount} active</span>
        </div>
      )}
      <table className="constraints-table">
        <thead>
          <tr>
            <th aria-label="enabled" />
            <th>Label</th>
            <th>Metric</th>
            <th>Sense</th>
            <th>Carrier</th>
            <th>Value</th>
            <th>Unit</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {constraints.map((c) => {
            const def = METRIC_DEFS[c.metric];
            return (
              <tr key={c.id}>
                <td>
                  <input
                    type="checkbox"
                    className="gcc-check"
                    checked={c.enabled}
                    onChange={(e) => update(c.id, { enabled: e.target.checked })}
                    title="Enabled"
                  />
                </td>
                <td>
                  <input
                    className="constraints-cell-input"
                    value={c.label}
                    onChange={(e) => update(c.id, { label: e.target.value })}
                    placeholder="label"
                  />
                </td>
                <td title={def?.description}>
                  <SearchableSelect
                    className="constraints-cell-input"
                    value={c.metric}
                    options={(Object.keys(METRIC_DEFS) as ConstraintMetric[]).map((m) => ({ value: m, label: METRIC_DEFS[m].label }))}
                    onChange={(v) => handleMetricChange(c.id, v as ConstraintMetric)}
                  />
                </td>
                <td className="constraints-cell-sense">{def?.sense}</td>
                <td>
                  {def?.needsCarrier ? (
                    <SearchableSelect
                      className="constraints-cell-input"
                      value={c.carrier}
                      options={carriers}
                      onChange={(v) => update(c.id, { carrier: v })}
                    />
                  ) : (
                    <span className="constraints-cell-placeholder">—</span>
                  )}
                </td>
                <td>
                  <NumberDraftInput
                    className="constraints-cell-input constraints-cell-input--num"
                    value={c.value}
                    onCommit={(v) => update(c.id, { value: v })}
                  />
                </td>
                <td className="constraints-cell-unit">{c.unit}</td>
                <td>
                  <button
                    className="gcc-del"
                    onClick={() => onChange(constraints.filter((x) => x.id !== c.id))}
                    title="Delete row"
                  >
                    x
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button className="tb-btn" style={{ marginTop: 12 }} onClick={handleAdd}>+ Add constraint</button>
    </div>
  );
}
