import React, { useMemo } from 'react';
import { MixItem } from 'lib/types';
import { buildDonutOption } from 'lib/charts/options';
import { readChartTheme } from 'lib/charts/theme';
import { useEChart } from '../../../shared/echarts/useEChart';

export function DonutChart({ data, unit }: { data: MixItem[]; unit?: string }) {
  const option = useMemo(
    () => buildDonutOption({ data, unit, theme: readChartTheme() }),
    [data, unit],
  );
  const hostRef = useEChart<HTMLDivElement>(option);

  return (
    <div className="donut-layout">
      <div ref={hostRef} className="donut-chart" role="img" aria-label="Mix chart" />
      <div className="legend-list">
        <div className="map-legend-title" style={{ marginBottom: 4 }}>
          {unit ? `Breakdown (${unit})` : 'Breakdown'}
        </div>
        {data.map((item) => (
          <div key={item.label} className="legend-item">
            <span className="legend-swatch" style={{ backgroundColor: item.color }} />
            <span>{item.label}</span>
            <strong>{Math.round(item.value).toLocaleString()}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
