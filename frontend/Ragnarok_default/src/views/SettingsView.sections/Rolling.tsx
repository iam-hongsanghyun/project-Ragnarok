/**
 * Rolling horizon section — stitch many short solves into one result.
 */
import React, { useState, useEffect } from 'react';
import { PathwayConfig, RollingHorizonConfig, WorkbookModel } from 'lib/types';
import { normalizeRollingConfig } from 'lib/results/rolling';
import { formatTimestamp } from 'lib/utils/helpers';

const MIN_CHUNKS = 2;

export interface RollingSectionProps {
  rollingConfig: RollingHorizonConfig;
  onRollingConfigChange: (config: RollingHorizonConfig) => void;
  pathwayConfig: PathwayConfig;
  maxSnapshots: number;
  snapshotStart: number;
  snapshotEnd: number;
  snapshotWeight: number;
  model: WorkbookModel;
}

function snapshotTimestamp(model: WorkbookModel, originalIndex: number): string | null {
  const rows = model.snapshots ?? [];
  const row = rows[originalIndex];
  if (!row) return null;
  const raw = String(row.snapshot ?? row.name ?? row.datetime ?? '').trim();
  if (!raw || raw.toLowerCase() === 'now') return null;
  return formatTimestamp(raw) || raw;
}

function stepForChunks(window: number, chunks: number): number {
  const safeChunks = Math.max(1, Math.min(chunks, window));
  return Math.max(1, Math.ceil(window / safeChunks));
}

function chunksFromHorizon(window: number, horizon: number, overlap: number): number {
  const step = Math.max(1, horizon - overlap);
  return Math.max(1, Math.ceil(window / step));
}

function horizonFromChunks(window: number, chunks: number, overlap: number): number {
  const step = stepForChunks(window, chunks);
  const cappedOverlap = Math.max(0, Math.min(overlap, step - 1));
  return Math.min(window, step + cappedOverlap);
}

function computeWindows(
  totalSnapshots: number,
  horizon: number,
  overlap: number,
): Array<{ start: number; end: number }> {
  const step = Math.max(1, horizon - overlap);
  const result: Array<{ start: number; end: number }> = [];
  for (let start = 0; start < totalSnapshots; start += step) {
    result.push({ start, end: Math.min(totalSnapshots, start + horizon) });
  }
  return result;
}

export function RollingSection({
  rollingConfig,
  onRollingConfigChange,
  pathwayConfig,
  maxSnapshots,
  snapshotStart,
  snapshotEnd,
  snapshotWeight,
  model,
}: RollingSectionProps) {
  const rawWindow = pathwayConfig.enabled ? maxSnapshots : snapshotEnd - snapshotStart;
  const weight = Math.max(1, Math.floor(snapshotWeight) || 1);
  const windowSnapshots = Math.max(1, Math.floor(rawWindow / weight));
  const maxChunks = Math.max(MIN_CHUNKS, windowSnapshots);

  const derivedChunks = Math.max(
    MIN_CHUNKS,
    Math.min(
      maxChunks,
      chunksFromHorizon(
        windowSnapshots,
        rollingConfig.horizonSnapshots,
        rollingConfig.overlapSnapshots,
      ),
    ),
  );
  const stepFromConfig = stepForChunks(windowSnapshots, derivedChunks);
  const overlap = Math.max(0, Math.min(rollingConfig.overlapSnapshots, stepFromConfig - 1));
  const horizon = horizonFromChunks(windowSnapshots, derivedChunks, overlap);
  const step = Math.max(1, horizon - overlap);
  const windows = computeWindows(windowSnapshots, horizon, overlap);

  const [chunksText, setChunksText] = useState<string>(String(derivedChunks));
  const [overlapText, setOverlapText] = useState<string>(String(overlap));

  useEffect(() => { setChunksText(String(derivedChunks)); }, [derivedChunks]);
  useEffect(() => { setOverlapText(String(overlap)); }, [overlap]);

  const commitChunks = (raw: string) => {
    const parsed = Math.max(MIN_CHUNKS, Math.min(maxChunks, parseInt(raw, 10) || MIN_CHUNKS));
    const nextStep = stepForChunks(windowSnapshots, parsed);
    const nextOverlap = Math.max(0, Math.min(overlap, nextStep - 1));
    const nextHorizon = horizonFromChunks(windowSnapshots, parsed, nextOverlap);
    setChunksText(String(parsed));
    setOverlapText(String(nextOverlap));
    onRollingConfigChange(normalizeRollingConfig({
      ...rollingConfig,
      horizonSnapshots: nextHorizon,
      overlapSnapshots: nextOverlap,
    }));
  };

  const commitOverlap = (raw: string) => {
    const parsed = Math.max(0, parseInt(raw, 10) || 0);
    const cappedOverlap = Math.min(parsed, step - 1);
    const nextHorizon = horizonFromChunks(windowSnapshots, derivedChunks, cappedOverlap);
    setOverlapText(String(cappedOverlap));
    onRollingConfigChange(normalizeRollingConfig({
      ...rollingConfig,
      horizonSnapshots: nextHorizon,
      overlapSnapshots: cappedOverlap,
    }));
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Rolling horizon</h3>
        <p>Stitch many short solves into one result. Independent from pathway mode; the backend hands each window to PyPSA in turn and forwards storage state.</p>
      </header>
      <div className="sg-setting-row">
        <label className="sg-setting-label">Mode</label>
        <div className="sg-btn-row">
          <button
            className={`tb-btn sg-solver-btn${!rollingConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onRollingConfigChange({ ...normalizeRollingConfig(rollingConfig), enabled: false })}
          >
            Off
          </button>
          <button
            className={`tb-btn sg-solver-btn${rollingConfig.enabled ? '' : ' tb-btn--muted'}`}
            onClick={() => onRollingConfigChange({ ...normalizeRollingConfig(rollingConfig), enabled: true })}
          >
            On
          </button>
        </div>
      </div>
      {rollingConfig.enabled && (
        <>
          <div className="sg-setting-divider" />
          <div className="rolling-input-row">
            <div className="rolling-input">
              <label className="sg-setting-label" htmlFor="rs-rolling-chunks">Chunks</label>
              <input
                id="rs-rolling-chunks"
                type="number"
                min={MIN_CHUNKS}
                max={maxChunks}
                step={1}
                className="sg-num-input"
                value={chunksText}
                onChange={(e) => setChunksText(e.target.value)}
                onBlur={(e) => commitChunks(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              />
            </div>
            <div className="rolling-input">
              <label className="sg-setting-label" htmlFor="rs-rolling-overlap">Overlap (snapshots)</label>
              <input
                id="rs-rolling-overlap"
                type="number"
                min={0}
                max={Math.max(0, step - 1)}
                step={1}
                className="sg-num-input"
                value={overlapText}
                onChange={(e) => setOverlapText(e.target.value)}
                onBlur={(e) => commitOverlap(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
              />
            </div>
          </div>
          <div className="sg-setting-row">
            <div className="rolling-summary">
              {windows.length} window{windows.length === 1 ? '' : 's'} · horizon {horizon} · step {step} · over {windowSnapshots} snapshots
            </div>
          </div>
          <RollingTimeline
            windows={windows}
            total={windowSnapshots}
            model={model}
            snapshotStart={snapshotStart}
            snapshotWeight={weight}
            pathwayEnabled={pathwayConfig.enabled}
          />
        </>
      )}
    </section>
  );
}

function RollingTimeline({
  windows,
  total,
  model,
  snapshotStart,
  snapshotWeight,
  pathwayEnabled,
}: {
  windows: Array<{ start: number; end: number }>;
  total: number;
  model: WorkbookModel;
  snapshotStart: number;
  snapshotWeight: number;
  pathwayEnabled: boolean;
}) {
  if (total <= 0 || windows.length === 0) return null;
  const pct = (v: number) => (v / total) * 100;

  const originalStart = pathwayEnabled ? 0 : snapshotStart;
  const tsAt = (localIndex: number): string | null =>
    snapshotTimestamp(model, originalStart + localIndex * snapshotWeight);

  const overlapMarks: Array<{ start: number; end: number }> = [];
  for (let i = 0; i < windows.length - 1; i++) {
    const a = windows[i];
    const b = windows[i + 1];
    if (b.start < a.end) {
      overlapMarks.push({ start: b.start, end: a.end });
    }
  }

  const firstTs = tsAt(0);
  const lastTs = tsAt(Math.max(0, total - 1));

  return (
    <div className="rolling-timeline" role="img" aria-label="Rolling horizon schedule">
      {windows.map((w, i) => {
        const startTs = tsAt(w.start);
        const endTs = tsAt(w.end - 1);
        return (
          <div className="rolling-timeline-row" key={i}>
            <span className="rolling-timeline-label">#{i + 1}</span>
            <div className="rolling-timeline-track">
              <div
                className="rolling-timeline-window"
                style={{ left: `${pct(w.start)}%`, width: `${pct(w.end - w.start)}%` }}
                title={`Snapshots ${w.start}–${w.end - 1}`}
              />
              {overlapMarks.map((m, j) => (
                <div
                  key={`o${j}`}
                  className="rolling-timeline-overlap"
                  style={{ left: `${pct(m.start)}%`, width: `${pct(m.end - m.start)}%` }}
                />
              ))}
            </div>
            <span className="rolling-timeline-range">
              {startTs && endTs ? (
                <>
                  <span>{startTs}</span>
                  <span className="rolling-timeline-range-sep">→</span>
                  <span>{endTs}</span>
                </>
              ) : (
                <>{w.start}–{w.end - 1}</>
              )}
            </span>
          </div>
        );
      })}
      <div className="rolling-timeline-axis">
        <span>{firstTs ?? '0'}</span>
        <span>{lastTs ?? String(total)}</span>
      </div>
    </div>
  );
}
