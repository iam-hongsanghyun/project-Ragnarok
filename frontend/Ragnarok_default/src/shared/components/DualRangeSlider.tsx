import React from 'react';
import { formatTimestamp } from '../../shared/utils/helpers';

export function DualRangeSlider({
  min, max, low, high, step = 1,
  formatLabel,
  onChange,
}: {
  min: number; max: number; low: number; high: number; step?: number;
  formatLabel?: (v: number) => string;
  onChange: (low: number, high: number) => void;
}) {
  const pct = (v: number) => ((v - min) / (max - min)) * 100;
  const fmt = formatLabel ?? String;
  return (
    <div className="dual-range">
      <div className="dual-range-labels">
        <span>{fmt(low)}</span>
        <span>{fmt(high)}</span>
      </div>
      <div className="dual-range-track">
        <div className="dual-range-fill" style={{ left: `${pct(low)}%`, width: `${pct(high) - pct(low)}%` }} />
        <input
          type="range" min={min} max={max} step={step} value={low}
          className="dual-range-input"
          onChange={(e) => {
            const v = Number(e.target.value);
            onChange(Math.min(v, high - step), high);
          }}
        />
        <input
          type="range" min={min} max={max} step={step} value={high}
          className="dual-range-input"
          onChange={(e) => {
            const v = Number(e.target.value);
            onChange(low, Math.max(v, low + step));
          }}
        />
      </div>
    </div>
  );
}

export function SingleRangeSlider({
  min, max, value, step = 1, disabled = false,
  minLabel, maxLabel,
  onChange,
}: {
  min: number; max: number; value: number; step?: number; disabled?: boolean;
  minLabel?: React.ReactNode; maxLabel?: React.ReactNode;
  onChange: (value: number) => void;
}) {
  const span = Math.max(max - min, 1);
  const pct = ((value - min) / span) * 100;
  return (
    <div className="dual-range">
      <div className="dual-range-labels">
        <span>{minLabel ?? min}</span>
        <span>{maxLabel ?? max}</span>
      </div>
      <div className="dual-range-track">
        <div className="dual-range-fill" style={{ left: 0, width: `${pct}%` }} />
        <input
          type="range" min={min} max={max} step={step} value={value}
          disabled={disabled}
          className="dual-range-input"
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
    </div>
  );
}

export function TimelineSlider({
  data,
  startIndex,
  endIndex,
  onChange,
}: {
  data: Array<{ timestamp?: string }>;
  startIndex: number;
  endIndex: number;
  onChange: (start: number, end: number) => void;
}) {
  if (!data.length) return null;
  const maxIdx = Math.max(data.length - 1, 0);
  return (
    <div className="chart-time-controls analytics-time-controls">
      <div style={{ flex: 1, minWidth: 0 }}>
        <DualRangeSlider
          min={0} max={maxIdx}
          low={startIndex} high={endIndex}
          formatLabel={(v) => formatTimestamp(data[v]?.timestamp) ?? String(v)}
          onChange={(lo, hi) => onChange(lo, hi)}
        />
      </div>
      <div className="chart-window">
        <strong>{endIndex - startIndex + 1}</strong>
        <span>
          {formatTimestamp(data[startIndex]?.timestamp)} to {formatTimestamp(data[endIndex]?.timestamp)}
        </span>
      </div>
    </div>
  );
}
