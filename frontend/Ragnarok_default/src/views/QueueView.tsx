/**
 * Queue view — the backend's serial run queue.
 *
 * Runs execute one at a time. Each row mirrors the History row design (flat,
 * full-width) and carries the run's settings plus a Cancel action; cancelling
 * the currently-running job kills it and the queue advances to the next.
 * Finished runs leave the queue and appear in History.
 */
import React from 'react';
import { QueueJob } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

interface QueueViewProps {
  jobs: QueueJob[];
  onCancel: (id: string) => void;
}

export function QueueView({ jobs, onCancel }: QueueViewProps) {
  let queuePos = 0;
  return (
    <div className="history-view">
      {jobs.length === 0 ? (
        <div className="history-empty">
          The queue is empty — click Run to queue a solve. Runs execute one at a
          time and move to History when they finish.
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
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function QueueRow({
  job, position, onCancel,
}: {
  job: QueueJob;
  position: number | null;
  onCancel: () => void;
}) {
  const running = job.status === 'running';
  const when = job.startedAt ?? job.submittedAt;

  return (
    <div className={`history-row${running ? ' is-selected' : ''}`}>
      <span className={`queue-status queue-status--${job.status}`}>
        {running && <span className="topbar-spinner" />}
        {running ? 'Running' : position != null ? `Queued #${position}` : job.status}
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

      <button className="tb-btn" onClick={onCancel}>Cancel</button>
    </div>
  );
}
