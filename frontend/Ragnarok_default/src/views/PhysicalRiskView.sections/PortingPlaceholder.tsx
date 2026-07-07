/**
 * Shared placeholder for Physical Risk sub-tabs not yet ported from the
 * standalone climaterisk app (Phase 1). Reuses the same empty-state look as
 * `AnalyticsPane`'s `EmptyAnalytics` — no new visual language.
 */
import React from 'react';

interface Props {
  title: string;
  description: string;
}

export function PortingPlaceholder({ title, description }: Props) {
  return (
    <div className="pane">
      <div className="analytics-empty">
        <h3>{title} — porting in progress</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}
