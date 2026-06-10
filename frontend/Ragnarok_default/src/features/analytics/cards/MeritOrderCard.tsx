/**
 * MeritOrderCard — supply stack (merit order) chart.
 *
 * Classic power-market chart: x-axis = cumulative installed capacity (MW),
 * y-axis = marginal cost ($/MWh). Each generator is a vertical block
 * (width = p_nom, height = marginal_cost) coloured by carrier, rendered as
 * an ECharts custom series (lib/charts/options.ts).
 */
import React, { useMemo } from 'react';
import { MeritOrderEntry } from 'lib/types';
import { buildMeritOrderOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

interface Props {
  entries: MeritOrderEntry[];
  systemLoad?: number; // peak system load in MW — draws a vertical demand line
  currencySymbol?: string;
}

export function MeritOrderCard({ entries, systemLoad, currencySymbol = '$' }: Props) {
  const option = useMemo(() => {
    if (!entries.length) return null;
    return buildMeritOrderOption({ entries, systemLoad, currencySymbol, theme: readChartTheme() });
  }, [entries, systemLoad, currencySymbol]);
  const hostRef = useEChart<HTMLDivElement>(option);

  if (!entries.length) {
    return (
      <div className="merit-empty">
        No dispatchable generators found — add generators with p_nom &gt; 0 to see the merit order.
      </div>
    );
  }

  const totalMW = entries.reduce((s, e) => s + e.p_nom, 0);

  return (
    <div className="merit-card">
      <div ref={hostRef} className="merit-host" role="img" />

      {/* Carrier legend */}
      <div className="merit-legend">
        {Array.from(new Map(entries.map((e) => [e.carrier, e.color])).entries()).map(
          ([carrier, color]) => (
            <div key={carrier} className="legend-item-inline">
              <span className="legend-swatch" style={{ backgroundColor: color }} />
              <span>{carrier}</span>
            </div>
          ),
        )}
        {systemLoad != null && (
          <div className="legend-item-inline">
            <span className="legend-swatch" style={{ backgroundColor: 'var(--danger)' }} />
            <span>Peak load ({Math.round(systemLoad).toLocaleString()} MW)</span>
          </div>
        )}
      </div>

      {/* Summary stats */}
      <div className="merit-stats">
        <span>Total installed: <strong>{Math.round(totalMW).toLocaleString()} MW</strong></span>
        <span>Generators: <strong>{entries.length}</strong></span>
        <span>Price range: <strong>
          {currencySymbol}{Math.min(...entries.map((e) => e.marginal_cost)).toLocaleString()} –
          {currencySymbol}{Math.max(...entries.map((e) => e.marginal_cost)).toLocaleString()} /MWh
        </strong></span>
      </div>
    </div>
  );
}
