import React, { useState, useRef, useLayoutEffect } from 'react';
import { ChartMode, TimeSeriesRow, TimeSeriesSeries } from 'lib/types';
import { numberValue, isoDate, isoTime } from 'lib/utils/helpers';

/**
 * Track an element's rendered pixel size so the chart can size its SVG
 * viewBox to the actual box instead of a fixed 820×360. Driving the
 * viewBox from the measured size (1 unit = 1 px) lets the chart fill —
 * and re-render to fit — its dashboard cell on every resize, with no
 * aspect-ratio letterboxing and no stroke/text distortion. Falls back to
 * the historic 820×360 until the first measurement lands.
 */
function useElementSize<T extends HTMLElement>(): [React.RefObject<T | null>, number, number] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 820, h: 360 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setSize((prev) => {
        const w = Math.max(Math.round(r.width), 160);
        const h = Math.max(Math.round(r.height), 100);
        return prev.w === w && prev.h === h ? prev : { w, h };
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size.w, size.h];
}

const H24 = 86_400_000;
const H7D = 7 * H24;
const H90D = 90 * H24;

// All x-axis labels use the canonical ISO target format (YYYY-MM-DD), never locale month names.
function formatXLabel(ts: string | undefined, spanMs: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  if (spanMs <= H24)  return isoTime(d);                      // HH:MM
  if (spanMs <= H7D)  return `${isoDate(d)} ${isoTime(d)}`;   // YYYY-MM-DD HH:MM
  if (spanMs <= H90D) return isoDate(d);                      // YYYY-MM-DD
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; // YYYY-MM
}

export function InteractiveTimeSeriesCard({
  title,
  description,
  data,
  series,
  mode,
  stacked,
  xAxisTitle,
  yAxisTitle,
  showLegend = true,
  showAxisLabels = true,
  xLabelAngle = 0,
}: {
  title: string;
  description: string;
  data: TimeSeriesRow[];
  series: TimeSeriesSeries[];
  mode: ChartMode;
  stacked: boolean;
  xAxisTitle?: string;
  yAxisTitle?: string;
  showLegend?: boolean;
  showAxisLabels?: boolean;
  xLabelAngle?: number;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [mainRef, width, height] = useElementSize<HTMLDivElement>();

  if (!series.length) {
    return (
      <section className="chart-card chart-card-wide">
        <div className="chart-card-header">
          <div><h3>{title}</h3><p>{description}</p></div>
        </div>
        <p className="empty-text">No chart series are available for this selection.</p>
      </section>
    );
  }

  if (!data.length) {
    return (
      <section className="chart-card">
        <div className="chart-card-header">
          <div><h3>{title}</h3><p>{description}</p></div>
        </div>
        <p className="empty-text">No series available for this selection.</p>
      </section>
    );
  }

  const visible = data;
  const visibleSeries = series.filter((item) =>
    visible.some((row) => Math.abs(numberValue(row[item.key] as string | number | undefined)) > 1e-6),
  );

  let maxValue = 1, minValue = 0;
  if (stacked && (mode === 'area' || mode === 'bar' || mode === 'line')) {
    maxValue = visible.reduce((max, row) => {
      const stackTotal = visibleSeries.reduce(
        (sum, item) => sum + Math.max(0, numberValue(row[item.key] as string | number | undefined)), 0,
      );
      return stackTotal > max ? stackTotal : max;
    }, 1);
  } else {
    for (const row of visible) {
      for (const item of visibleSeries) {
        const v = numberValue(row[item.key] as string | number | undefined);
        const abs = Math.abs(v);
        if (abs > maxValue) maxValue = abs;
        if (v < minValue) minValue = v;
      }
    }
  }

  const range = Math.max(maxValue - minValue, 1);

  // Approximate glyph metrics for the .chart-axis font (12px). Used to size
  // the gutters so y labels never clip and to budget the rotated x-label band.
  const CHAR_PX = 6.6;
  const FONT_PX = 12;

  // Pre-format the five y-axis tick labels once, so the same strings drive
  // both the left-gutter width and the rendered <text>.
  const yTickLabels = [0, 0.25, 0.5, 0.75, 1].map((t) =>
    Math.round(minValue + range * t).toLocaleString(),
  );
  const maxYLabelPx = showAxisLabels
    ? Math.max(...yTickLabels.map((s) => s.length)) * CHAR_PX
    : 0;

  // Time span drives label format + base tick density.
  const firstTs = visible[0]?.timestamp;
  const lastTs  = visible[visible.length - 1]?.timestamp;
  const spanMs  = firstTs && lastTs
    ? new Date(lastTs).getTime() - new Date(firstTs).getTime()
    : 0;

  // Widest x label (in px) for the current span, to budget the bottom band
  // and to space ticks so neighbouring labels don't collide.
  const maxXLabelPx = showAxisLabels
    ? Math.max(
        1,
        ...visible.map((row) =>
          (row.timestamp ? formatXLabel(row.timestamp, spanMs) : row.label).length,
        ),
      ) * CHAR_PX
    : 0;

  const angle = Number.isFinite(xLabelAngle) ? xLabelAngle : 0;
  const rad = Math.abs(angle) * Math.PI / 180;
  // Vertical footprint of the (possibly rotated) x labels.
  const xLabelBandPx = showAxisLabels
    ? Math.ceil(Math.sin(rad) * maxXLabelPx + Math.cos(rad) * FONT_PX) + 8
    : 0;

  const padTop = 38, padRight = 38;
  const padLeft = (showAxisLabels ? 14 + maxYLabelPx : 14) + (yAxisTitle ? 18 : 0);
  const padBottom = (showAxisLabels ? xLabelBandPx + 8 : 12) + (xAxisTitle ? 18 : 0);
  const innerWidth = Math.max(width - padLeft - padRight, 10);
  const innerHeight = Math.max(height - padTop - padBottom, 10);

  const xForIndex = (i: number) => padLeft + (i / Math.max(visible.length - 1, 1)) * innerWidth;
  const yForValue = (v: number) => padTop + innerHeight - ((v - minValue) / range) * innerHeight;
  const zeroY = yForValue(0);

  const spanTargetTicks =
    spanMs <= H24  ? Math.min(visible.length, 12) :
    spanMs <= H7D  ? 7  :
    spanMs <= H90D ? 13 :
    8;
  // Cap tick density by available width: each label needs its horizontal
  // footprint (full width when horizontal, ~cos·width when rotated) plus a gap.
  const xFootprintPx = Math.max(14, Math.cos(rad) * maxXLabelPx + (angle ? 6 : 12));
  const maxTicksByWidth = Math.max(2, Math.floor(innerWidth / xFootprintPx));
  const targetTicks = Math.max(1, Math.min(spanTargetTicks, maxTicksByWidth));
  const stride = Math.max(1, Math.ceil(visible.length / targetTicks));

  return (
    <section className="chart-card chart-card-wide">
      <div className="chart-card-header">
        <div><h3>{title}</h3><p>{description}</p></div>
      </div>
      <div className="chart-shell">
        <div className="chart-main" ref={mainRef}>
          <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} role="img"
            onMouseLeave={() => setHoverIndex(null)}
            onMouseMove={(e) => {
              const svgEl = e.currentTarget as SVGSVGElement;
              const pt = svgEl.createSVGPoint();
              pt.x = e.clientX; pt.y = e.clientY;
              const svgPt = pt.matrixTransform(svgEl.getScreenCTM()!.inverse());
              const rawIndex = Math.round(((svgPt.x - padLeft) / innerWidth) * (visible.length - 1));
              setHoverIndex(Math.max(0, Math.min(visible.length - 1, rawIndex)));
            }}
          >
            {[0, 0.25, 0.5, 0.75, 1].map((tick, tickIndex) => (
              <g key={tick}>
                <line x1={padLeft} x2={width - padRight} y1={padTop + innerHeight - innerHeight * tick} y2={padTop + innerHeight - innerHeight * tick} className="chart-grid" />
                {showAxisLabels && (
                  <text x={padLeft - 6} y={padTop + innerHeight - innerHeight * tick + 4} className="chart-axis" textAnchor="end">{yTickLabels[tickIndex]}</text>
                )}
              </g>
            ))}

            {mode === 'bar' && visible.map((row, rowIndex) => {
              const groupWidth = innerWidth / Math.max(visible.length, 1);
              const baseX = padLeft + rowIndex * groupWidth;
              let runningStack = 0;
              return (
                <g key={`${row.label}-${rowIndex}`}>
                  {visibleSeries.map((item, itemIndex) => {
                    const rawValue = numberValue(row[item.key] as string | number | undefined);
                    const value = stacked ? Math.max(0, rawValue) : rawValue;
                    if (stacked) {
                      const barHeight = (value / maxValue) * innerHeight;
                      const y = height - padBottom - (runningStack / maxValue) * innerHeight - barHeight;
                      runningStack += value;
                      return <rect key={item.key} x={baseX + 4} y={y} width={Math.max(groupWidth - 8, 3)} height={barHeight} fill={item.color} fillOpacity={0.82} />;
                    }
                    const barWidth = Math.max((groupWidth - 10) / Math.max(visibleSeries.length, 1), 4);
                    const y = Math.min(zeroY, yForValue(value));
                    const barHeight = Math.abs(zeroY - yForValue(value));
                    return <rect key={item.key} x={baseX + 4 + itemIndex * barWidth} y={y} width={barWidth - 2} height={barHeight} fill={item.color} fillOpacity={0.82} />;
                  })}
                </g>
              );
            })}

            {mode === 'area' && (() => {
              let runningBase = new Array(visible.length).fill(0);
              return visibleSeries.map((item) => {
                const topPoints = visible.map((row, index) => {
                  const rawValue = numberValue(row[item.key] as string | number | undefined);
                  const value = stacked ? Math.max(0, rawValue) : rawValue;
                  const top = stacked ? runningBase[index] + value : value;
                  return `${xForIndex(index)},${yForValue(top)}`;
                });
                const bottomPoints = [...visible].reverse().map((row, reverseIndex) => {
                  const index = visible.length - 1 - reverseIndex;
                  const base = stacked ? runningBase[index] : 0;
                  return `${xForIndex(index)},${yForValue(base)}`;
                });
                const polygon = (
                  <polygon key={item.key} points={[...topPoints, ...bottomPoints].join(' ')} fill={item.color} fillOpacity={stacked ? 0.72 : 0.24} stroke={item.color} strokeWidth={1.8} />
                );
                if (stacked) {
                  runningBase = runningBase.map((base, index) => base + Math.max(0, numberValue(visible[index][item.key] as string | number | undefined)));
                }
                return polygon;
              });
            })()}

            {mode === 'line' && (() => {
              let runningBase = new Array(visible.length).fill(0);
              return visibleSeries.map((item) => {
                const path = visible.map((row, index) => {
                  const raw = numberValue(row[item.key] as string | number | undefined);
                  const value = stacked ? runningBase[index] + Math.max(0, raw) : raw;
                  return `${index === 0 ? 'M' : 'L'} ${xForIndex(index)} ${yForValue(value)}`;
                }).join(' ');
                if (stacked) {
                  runningBase = runningBase.map((base, index) => base + Math.max(0, numberValue(visible[index][item.key] as string | number | undefined)));
                }
                return <path key={item.key} d={path} fill="none" stroke={item.color} strokeWidth={3} strokeLinecap="round" />;
              });
            })()}

            {showAxisLabels && visible.map((row, index) => {
              if (index % stride !== 0) return null;
              const label = row.timestamp ? formatXLabel(row.timestamp, spanMs) : row.label;
              const lx = xForIndex(index);
              const ly = height - padBottom + (angle ? 12 : 16);
              return (
                <text
                  key={`${row.label}-${index}`}
                  x={lx}
                  y={ly}
                  className="chart-axis chart-axis-x"
                  textAnchor={angle ? 'end' : 'middle'}
                  style={angle ? { textAnchor: 'end' } : undefined}
                  transform={angle ? `rotate(${angle} ${lx} ${ly})` : undefined}
                >
                  {label}
                </text>
              );
            })}

            {yAxisTitle && (
              <text className="chart-axis-title" transform="rotate(-90)" x={-(padTop + innerHeight / 2)} y={14} textAnchor="middle">{yAxisTitle}</text>
            )}
            {xAxisTitle && (
              <text className="chart-axis-title" x={padLeft + innerWidth / 2} y={height - 6} textAnchor="middle">{xAxisTitle}</text>
            )}

            {minValue < 0 && maxValue > 0 && (
              <line x1={padLeft} x2={width - padRight} y1={zeroY} y2={zeroY} stroke="rgba(15, 23, 42, 0.28)" strokeWidth={1.2} />
            )}

            {hoverIndex !== null && (() => {
              const hx = xForIndex(hoverIndex);
              const row = visible[hoverIndex];
              const tooltipItems = visibleSeries.map((s) => ({ label: s.label, color: s.color, value: numberValue(row[s.key] as string | number | undefined) }));
              const tipWidth = 180, tipHeight = 16 + tooltipItems.length * 18;
              const tx = hx + 12 + tipWidth > width - padRight ? hx - tipWidth - 12 : hx + 12;
              const ty = padTop + 4;
              return (
                <g style={{ pointerEvents: 'none' }}>
                  <line x1={hx} x2={hx} y1={padTop} y2={height - padBottom} stroke="rgba(15,23,42,0.22)" strokeWidth={1.5} strokeDasharray="4 3" />
                  <g transform={`translate(${tx},${ty})`}>
                    <rect rx="4" ry="4" width={tipWidth} height={tipHeight} fill="rgba(15,23,42,0.88)" />
                    {tooltipItems.map((item, i) => (
                      <g key={item.label} transform={`translate(10,${18 + i * 18})`}>
                        <rect x="0" y="-8" width="8" height="8" rx="0" fill={item.color} />
                        <text x="12" y="0" className="chart-tip-line">
                          {item.label}: <tspan fontWeight="700">{Math.round(item.value).toLocaleString()}</tspan>
                        </text>
                      </g>
                    ))}
                  </g>
                </g>
              );
            })()}
            <rect x={padLeft} y={padTop} width={innerWidth} height={innerHeight} fill="transparent" />
          </svg>
        </div>
        {showLegend && (
        <div className="chart-legend chart-legend-side">
          <div className="map-legend-title" style={{ marginBottom: 4 }}>Series</div>
          {visibleSeries.map((item) => (
            <div key={item.key} className="legend-item-inline">
              <span className="legend-swatch" style={{ backgroundColor: item.color }} />
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        )}
      </div>
    </section>
  );
}
