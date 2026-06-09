/**
 * Queue view — the backend's serial run queue.
 *
 * Runs execute one at a time. Each row mirrors the History row design (flat,
 * full-width) and carries the run's settings plus a Cancel action; cancelling
 * the currently-running job kills it and the queue advances to the next.
 * Finished/cancelled/failed rows stay until deleted so they can be rerun.
 */
import React from 'react';
import { QueueJob } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface QueueViewProps {
  jobs: QueueJob[];
  onCancel: (id: string) => void;
  onRerun: (id: string) => void;
  onImport: (id: string) => void;
  onDelete: (id: string) => void;
}

export function QueueView({
  jobs, onCancel, onRerun, onImport, onDelete,
}: QueueViewProps) {
  // Only "queued" items get a live position number; "staged" jobs are parked
  // and never auto-run, so they're numbered separately as "(paused)".
  let queuePos = 0;
  return (
    <div className="history-view">
      {jobs.length === 0 ? (
        <div className="history-empty">
          The queue is empty — click Run to queue a solve, or "Queue next Run" to
          stage one for later. Runs execute one at a time and stay here until deleted.
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
