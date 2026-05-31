import React, { useState } from 'react';
import { RunHistoryEntry } from 'lib/types';
import { formatRelTime } from 'lib/utils/formatRelTime';

export interface RunHistoryCardProps {
  entry: RunHistoryEntry;
  onView: () => void;
  onRename: (label: string) => void;
  onPin: (pinned: boolean) => void;
  onDelete: () => void;
  onToggleComparison: (inComparison: boolean) => void;
  currencySymbol?: string;
}

export function RunHistoryCard({ entry, onView, onRename, onPin, onDelete, onToggleComparison, currencySymbol = '$' }: RunHistoryCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.label);
  const [confirming, setConfirming] = useState(false);

  const commitRename = () => {
    onRename(draft.trim() || entry.label);
    setEditing(false);
  };

  const kpiEmissions = entry.results.summary[4];
  const kpiPrice = entry.results.summary[3];

  return (
    <div className={`hist-card${entry.pinned ? ' hist-card--pinned' : ''}${!entry.inComparison ? ' hist-card--excluded' : ''}`}>
      <div className="hist-card-header">

        {/* Comparison checkbox */}
        <label className="hist-compare-check" title={entry.inComparison ? 'Included in Comparison tab — uncheck to exclude' : 'Excluded from Comparison tab — check to include'}>
          <input
            type="checkbox"
            checked={entry.inComparison}
            onChange={(e) => onToggleComparison(e.target.checked)}
          />
        </label>

        {editing ? (
          <input
            className="hist-label-input"
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur();
            }}
          />
        ) : (
          <span
            className="hist-label"
            onClick={() => { setDraft(entry.label); setEditing(true); }}
            title="Click to rename"
          >
            {entry.label}
          </span>
        )}

        <button
          className={`hist-pin-btn${entry.pinned ? ' active' : ''}`}
          title={entry.pinned ? 'Unpin' : "Pin — won't auto-expire"}
          onClick={() => onPin(!entry.pinned)}
        >
          {entry.pinned ? 'Unpin' : 'Pin'}
        </button>
      </div>

      <div className="hist-meta">
        <span>{formatRelTime(entry.savedAt)}</span>
        <span>·</span>
        <span className="hist-meta-filename">{entry.filename}</span>
      </div>

      <div className="hist-settings">
        {entry.scenarioLabel && <span>{entry.scenarioLabel}</span>}
        <span>{entry.results.runMeta.snapshotCount} snaps</span>
        <span>{entry.snapshotWeight}h</span>
        {entry.carbonPrice > 0 && <span>{currencySymbol}{entry.carbonPrice}/t CO₂</span>}
        {entry.activeConstraints.length > 0 && (
          <span title={entry.activeConstraints.map((c) => c.label).join(', ')}>
            {entry.activeConstraints.length} constraint{entry.activeConstraints.length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {(kpiEmissions || kpiPrice) && (
        <div className="hist-kpis">
          {kpiEmissions && (
            <span className="hist-kpi">
              <strong>{kpiEmissions.value}</strong> {kpiEmissions.label}
            </span>
          )}
          {kpiPrice && (
            <span className="hist-kpi">
              <strong>{kpiPrice.value}</strong> {kpiPrice.label}
            </span>
          )}
        </div>
      )}

      <div className="hist-card-footer">
        <button className="ghost-button sm hist-view-btn" onClick={onView}>
          View results →
        </button>

        {confirming ? (
          <div className="hist-confirm-row">
            <span className="hist-confirm-label">Delete?</span>
            <button className="hist-confirm-yes" onClick={() => { setConfirming(false); onDelete(); }}>Yes</button>
            <button className="hist-confirm-no" onClick={() => setConfirming(false)}>No</button>
          </div>
        ) : (
          <button className="hist-delete-btn" onClick={() => setConfirming(true)}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
