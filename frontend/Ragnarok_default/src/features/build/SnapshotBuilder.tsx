/**
 * SnapshotBuilder — generate the time axis from a start, a resolution and a
 * horizon, instead of typing rows.
 *
 * Sits on the Build → Snapshots step. The `snapshots` sheet is the only one
 * whose row count is routinely in the thousands (a year at hourly resolution is
 * 8760), so it is the one sheet that has to be specified rather than authored.
 *
 * Generation REPLACES the axis rather than appending, because a half-replaced
 * axis silently misaligns every profile indexed against it — so the confirm
 * step names the row count being discarded.
 */
import React, { useMemo, useState } from 'react';
import {
  HORIZONS,
  LARGE_SNAPSHOTS,
  RESOLUTIONS,
  buildSnapshots,
  countForHorizon,
  summariseSpec,
  validateSpec,
} from 'lib/build/snapshots';
import { useDialog } from '../../shared/components/Dialog';

interface Props {
  /** Rows already on the `snapshots` sheet — generation replaces them. */
  existingCount: number;
  /** Replace the axis with these labels. */
  onGenerate: (labels: string[]) => void;
  /** Global run resolution, in hours per snapshot (Settings → Simulation window). */
  snapshotWeight: number;
  onSnapshotWeightChange: (hours: number) => void;
}

const DEFAULT_START = '2030-01-01 00:00';

export function SnapshotBuilder({ existingCount, onGenerate, snapshotWeight, onSnapshotWeightChange }: Props) {
  const { confirm } = useDialog();
  const [start, setStart] = useState(DEFAULT_START);
  const [resolutionId, setResolutionId] = useState('1h');
  const [horizonId, setHorizonId] = useState('1d');
  const [customCount, setCustomCount] = useState('24');
  const [syncWeight, setSyncWeight] = useState(true);
  const [busy, setBusy] = useState(false);

  const resolution = RESOLUTIONS.find((r) => r.id === resolutionId) ?? RESOLUTIONS[2];
  const horizon = HORIZONS.find((h) => h.id === horizonId) ?? HORIZONS[0];

  const count = horizon.hours === null
    ? Number.parseInt(customCount, 10)
    : countForHorizon(horizon.hours, resolution.hours);

  const spec = { start, stepHours: resolution.hours, count: Number.isFinite(count) ? count : 0 };
  const problem = validateSpec(spec);
  const summary = useMemo(() => summariseSpec(spec), [spec.start, spec.stepHours, spec.count]); // eslint-disable-line react-hooks/exhaustive-deps

  const weightMismatch = summary !== null && summary.matchingWeight !== snapshotWeight;

  const generate = async () => {
    if (problem) return;
    if (existingCount > 0) {
      const ok = await confirm(
        `This replaces the existing time axis — all ${existingCount.toLocaleString()} row`
        + `${existingCount === 1 ? '' : 's'} on the snapshots sheet.\n\n`
        + 'Any profile already indexed against the old axis (loads-p_set, generators-p_max_pu, …) '
        + 'will no longer line up unless it is re-imported.',
        { title: 'Replace the time axis?', confirmText: 'Replace', danger: true },
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      onGenerate(buildSnapshots(spec));
      if (syncWeight && summary) onSnapshotWeightChange(summary.matchingWeight);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="snapshot-builder" aria-label="Snapshot builder">
      <div className="snapshot-builder__fields">
        <label className="snapshot-builder__field">
          <span>Start</span>
          <input
            data-tour="snap-start"
            type="text"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            placeholder={DEFAULT_START}
            spellCheck={false}
          />
        </label>

        <label className="snapshot-builder__field">
          <span>Resolution</span>
          <select data-tour="snap-resolution" value={resolutionId} onChange={(e) => setResolutionId(e.target.value)}>
            {RESOLUTIONS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </label>

        <label className="snapshot-builder__field">
          <span>Horizon</span>
          <select data-tour="snap-horizon" value={horizonId} onChange={(e) => setHorizonId(e.target.value)}>
            {HORIZONS.map((h) => <option key={h.id} value={h.id}>{h.label}</option>)}
          </select>
        </label>

        {horizon.hours === null && (
          <label className="snapshot-builder__field snapshot-builder__field--narrow">
            <span>Count</span>
            <input
              type="number"
              min={1}
              value={customCount}
              onChange={(e) => setCustomCount(e.target.value)}
            />
          </label>
        )}

        <button
          type="button"
          data-tour="snap-generate"
          className="primary-button"
          disabled={!!problem || busy}
          onClick={() => void generate()}
        >
          {existingCount > 0 ? 'Replace axis' : 'Generate snapshots'}
        </button>
      </div>

      {problem ? (
        <p className="snapshot-builder__problem">{problem.message}</p>
      ) : summary && (
        <p className="snapshot-builder__summary">
          <b>{summary.count.toLocaleString()}</b> snapshot{summary.count === 1 ? '' : 's'} ·{' '}
          {summary.first} → {summary.last} ·{' '}
          covers <b>{summary.totalHours.toLocaleString()} h</b> at {resolution.label} each
          {existingCount > 0 && (
            <span className="snapshot-builder__replacing">
              {' '}· replaces {existingCount.toLocaleString()} existing row{existingCount === 1 ? '' : 's'}
            </span>
          )}
        </p>
      )}

      {summary && summary.count >= LARGE_SNAPSHOTS && (
        <p className="snapshot-builder__warn">
          {summary.count.toLocaleString()} snapshots will solve slowly. Snapshot count drives solve
          time far harder than component count — consider a shorter horizon first, or narrow the run
          in Settings → Simulation window without changing this sheet.
        </p>
      )}

      <label className="snapshot-builder__weight" data-tour="snap-weight">
        <input type="checkbox" checked={syncWeight} onChange={(e) => setSyncWeight(e.target.checked)} />
        <span>
          Also set the run resolution to {resolution.hours} h per snapshot
          {weightMismatch && <b> (currently {snapshotWeight} h — costs and energy totals scale by this)</b>}
        </span>
      </label>
    </section>
  );
}
