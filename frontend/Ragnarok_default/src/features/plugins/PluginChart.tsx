import React from 'react';
import { ChartMode, PluginChartSpec } from 'lib/types';
import { chartSpecToDonut, chartSpecToRows, chartSpecToSeries } from 'lib/plugins/chartSpec';
import { InteractiveTimeSeriesCard } from '../analytics/cards/InteractiveTimeSeriesCard';
import { DonutChart } from '../analytics/cards/DonutChart';
import { PluginMap } from './PluginMap';

/**
 * Renders a plugin-declared `PluginChartSpec` with the app's own chart
 * components. The host owns rendering; the plugin only supplies data.
 */
export function PluginChart({ spec, title }: { spec: PluginChartSpec; title?: string }) {
  if (spec.kind === 'map') {
    return <PluginMap spec={spec} title={title} />;
  }

  if (spec.kind === 'donut') {
    const data = chartSpecToDonut(spec);
    if (data.length === 0) {
      return <p className="sg-setting-hint" style={{ margin: 0 }}>Chart has no data.</p>;
    }
    return (
      <section className="chart-card">
        {title && (
          <div className="chart-card-header"><div><h3>{title}</h3></div></div>
        )}
        <DonutChart data={data} />
      </section>
    );
  }

  const series = chartSpecToSeries(spec);
  const data = chartSpecToRows(spec, series);
  if (series.length === 0 || data.length === 0) {
    return <p className="sg-setting-hint" style={{ margin: 0 }}>Chart has no data.</p>;
  }

  return (
    <InteractiveTimeSeriesCard
      title={title ?? ''}
      description={spec.description ?? ''}
      data={data}
      series={series}
      mode={spec.kind as ChartMode}
      stacked={Boolean(spec.stacked)}
      xAxisTitle={spec.xAxisTitle}
      yAxisTitle={spec.yAxisTitle}
      showLegend={spec.showLegend ?? true}
    />
  );
}
