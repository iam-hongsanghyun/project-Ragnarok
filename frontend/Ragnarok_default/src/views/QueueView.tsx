/**
 * Queue view — the backend's serial run queue.
 *
 * Runs execute one at a time. Each card shows the run's settings and a Cancel
 * action; cancelling the currently-running job kills it and the queue advances
 * to the next. Finished runs leave the queue and appear in History.
 */
import React from 'react';
import { QueueJob } from 'lib/types';

interface QueueViewProps {
  jobs: QueueJob[];
  onCancel: (id: string) => void;
}

export function QueueView({ jobs, onCancel }: QueueViewProps) {
  if (jobs.length === 0) {
    return (
      <div className="history-empty">
        The queue is empty — click Run to queue a solve. Runs execute one at a
        time and move to History when they finish.
      </div>
    );
  }

  let queuePos = 0;
  return (
    <div className="queue-list">
      {jobs.map((job) => {
        if (job.status === 'queued') queuePos += 1;
        return (
          <QueueCard
            key={job.id}
            job={job}
            position={job.status === 'queued' ? queuePos : null}
            onCancel={() => onCancel(job.id)}
          />
        );
      })}
    </div>
  );
}

function QueueCard({
  job, position, onCancel,
}: {
  job: QueueJob;
  position: number | null;
  onCancel: () => void;
}) {
  const running = job.status === 'running';
  const chips: Array<{ label: string; value: string }> = [];
  if (job.snapshots != null) chips.push({ label: 'snapshots', value: String(job.snapshots) });
  if (job.snapshotWeight != null) chips.push({ label: 'weight', value: `${job.snapshotWeight}h` });
  if (job.scenarioLabel) chips.push({ label: 'scenario', value: job.scenarioLabel });
  if (job.solver) chips.push({ label: 'solver', value: job.solver });
  if (job.carbonPrice != null) chips.push({ label: 'carbon', value: String(job.carbonPrice) });
  if (job.rolling) chips.push({ label: 'mode', value: 'rolling' });
  if (job.pathway) chips.push({ label: 'mode', value: 'pathway' });

  return (
    <div className={`queue-card${running ? ' queue-card--running' : ''}`}>
      <div className="queue-card-head">
        <span className={`queue-status queue-status--${job.status}`}>
          {running && <span className="topbar-spinner" />}
          {running ? 'Running' : position != null ? `Queued · #${position}` : job.status}
        </span>
        <span className="queue-card-label" title={job.filename ?? job.label}>{job.label}</span>
        <span className="queue-card-spacer" />
        <button className="tb-btn" onClick={onCancel}>Cancel</button>
      </div>
      <div className="queue-card-chips">
        {chips.map((c, i) => (
          <span key={`${c.label}-${i}`} className="queue-chip">
            <b>{c.value}</b> {c.label}
          </span>
        ))}
        {job.filename && <span className="queue-chip queue-chip--file">{job.filename}</span>}
      </div>
    </div>
  );
}
