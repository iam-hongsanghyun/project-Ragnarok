/**
 * Queue view — the backend's run queue.
 *
 * Runs execute up to "Parallel runs" at a time (1 = serial queue, the default).
 * A core-budget bar shows how many CPU cores the running solves are using out of
 * what's available. Each row mirrors the History row design (flat, full-width)
 * and carries the run's settings, its assigned core count, and a Cancel action;
 * cancelling a running job kills it and frees its slot for the next.
 * Finished/cancelled/failed rows stay until deleted so they can be rerun.
 */
import React from 'react';
import { QueueJob } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface QueueViewProps {
  jobs: QueueJob[];
  /** Max solves running at once (1 = serial queue). */
  concurrency: number;
  /** Cores available on the host — the ceiling for concurrency and the bar. */
  cpuCount: number;
  onSetConcurrency: (value: number) => void;
  onCancel: (id: string) => void;
  onRerun: (id: string) => void;
  onImport: (id: string) => void;
  onDelete: (id: string) => void;
}

export function QueueView({
  jobs, concurrency, cpuCount, onSetConcurrency, onCancel, onRerun, onImport, onDelete,
}: QueueViewProps) {
  // Only "queued" items get a live position number; "staged" jobs are parked
  // and never auto-run, so they're numbered separately as "(paused)".
  let queuePos = 0;

  // Cores in use right now = sum over the running solves. Over-subscribed only
  // happens when the user pins explicit thread counts that exceed the host.
  const running = jobs.filter((j) => j.status === 'running');
  const assigned = running.reduce((sum, j) => sum + (j.cores ?? 0), 0);
  const max = Math.max(1, cpuCount);
  const over = assigned > max;
  const fillPct = Math.min(100, (assigned / max) * 100);

  return (
    <div className="history-view">
      <div className="queue-toolbar">
        <label className="queue-conc-control">
          <span className="queue-conc-label">Parallel runs</span>
          <select
            className="queue-conc-select"
            value={Math.min(concurrency, max)}
            onChange={(e) => onSetConcurrency(Number(e.target.value))}
          >
            {Array.from({ length: max }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n === 1 ? '1 — Queue (one at a time)' : `${n} — Concurrent`}
              </option>
            ))}
          </select>
        </label>

        <div className="queue-core-budget" title={`${assigned} of ${max} cores assigned to running solves`}>
          <div className="queue-core-bar">
            <span
              className={`queue-core-fill${over ? ' is-over' : ''}`}
              style={{ width: `${fillPct}%` }}
            />
          </div>
          <span className={`queue-core-text${over ? ' is-over' : ''}`}>
            Cores in use: {assigned} / {max}{over ? ' — over-subscribed' : ''}
          </span>
        </div>
      </div>

      <p className="sg-setting-hint queue-conc-hint">
        {concurrency > 1
          ? `Up to ${concurrency} solves run at once.`
          : 'Solves run one at a time.'}{' '}
        An explicit thread count (Settings → Solver) is honoured as-is; <b>Auto</b>{' '}
        splits cores evenly across the parallel-runs setting (≈{Math.max(1, Math.floor(max / Math.max(1, concurrency)))} each now).
        Leave headroom to avoid over-subscribing the CPU.
      </p>

      {jobs.length === 0 ? (
        <div className="history-empty">
          The queue is empty — click Run to queue a solve, or "Queue next Run" to
          stage one for later. {concurrency > 1
            ? `Up to ${concurrency} run at a time`
            : 'Runs execute one at a time'} and stay here until deleted.
        </div>
      ) : (
        <div className="history-list">
          {jobs.map((job) => {
            if (job.status === 'queued') queuePos += 1;
            return (
              <QueueRow
                key={job.id}
                job={job}
                position={job.status === 'queued' ? queuePos : null}
                onCancel={() => onCancel(job.id)}
                onRerun={() => onRerun(job.id)}
                onImport={() => onImport(job.id)}
                onDelete={() => onDelete(job.id)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function QueueRow({
  job, position, onCancel, onRerun, onImport, onDelete,
}: {
  job: QueueJob;
  position: number | null;
  onCancel: () => void;
  onRerun: () => void;
  onImport: () => void;
  onDelete: () => void;
}) {
  const running = job.status === 'running';
  const staged = job.status === 'staged';
  // "active" = can be cancelled (it will run, or is parked waiting to run).
  const active = running || job.status === 'queued' || staged;
  const when = job.startedAt ?? job.submittedAt;
  const hasPayload = job.payloadAvailable !== false;
  const statusLabel =
    running ? 'Running'
      : position != null ? `Queue #${position}`
        : staged ? 'Queued (paused)'
          : job.status === 'done' ? 'Done'
            : job.status === 'error' ? 'Failed'
              : job.status === 'cancelled' ? 'Cancelled'
                : job.status;

  return (
    <div className={`history-row${running ? ' is-selected' : ''}`}>
      <span className={`queue-status queue-status--${job.status}`}>
        {running && <span className="topbar-spinner" />}
        {statusLabel}
      </span>

      <span className="history-row-name history-row-name--static" title={job.filename ?? job.label}>
        {job.label}
      </span>

      {when && (
        <span className="history-row-time" title={new Date(when).toLocaleString()}>
          {formatRelTime(when)}
        </span>
      )}
      {/* Cores assigned to this solve — actual once running, projected while it
          waits. Shown for active rows; terminal rows drop it to reduce clutter. */}
      {active && job.cores != null && (
        <span className="history-row-chip" title="CPU cores assigned to this solve">
          {job.cores} core{job.cores === 1 ? '' : 's'}
        </span>
      )}
      {job.snapshots != null && <span className="history-row-chip">{job.snapshots} snaps</span>}
      {job.snapshotWeight != null && <span className="history-row-chip">{job.snapshotWeight}h</span>}
      {job.scenarioLabel && <span className="history-row-chip">{job.scenarioLabel}</span>}
      {job.solver && <span className="history-row-chip">{job.solver}</span>}
      {job.rolling && <span className="history-row-chip">rolling</span>}
      {job.pathway && <span className="history-row-chip">pathway</span>}

      <span className="history-row-spacer" />

      {active && <button className="tb-btn" onClick={onCancel}>Cancel</button>}
      {/* Staged → "Run" activates it in place; finished/cancelled → "Rerun"
          re-runs the same retained model. Both flip this card to "Queue #n". */}
      {!running && !active && hasPayload && (
        <button className="tb-btn" onClick={onRerun}>Rerun</button>
      )}
      {staged && (
        <button className="tb-btn" onClick={onRerun}>Run</button>
      )}
      {/* Import the retained model into the editor as a new project to tweak;
          a subsequent Run/Queue makes a NEW entry, leaving this card intact. */}
      {hasPayload && (
        <button className="tb-btn" onClick={onImport} title="Load this run's model into the editor as a new project">
          Import project
        </button>
      )}
      <button className="tb-btn" onClick={onDelete}>Delete</button>
    </div>
  );
}
