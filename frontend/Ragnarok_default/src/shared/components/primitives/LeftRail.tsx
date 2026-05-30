/**
 * LeftRail — vertical rail panel with a titled header + scrollable body.
 *
 * The canonical rail across every view in Ragnarok. Replaces:
 *   .view-rail / .view-rail--left / .view-rail-header
 *   .analytics-view-rail / .analytics-view-rail-header
 *   .settings-section-nav (with the manually-added title strip)
 *
 * The rail can sit on the LEFT (default) or RIGHT (`side="right"`).
 * The body is a flex container; callers fill it with their own list /
 * tree / form.
 *
 * Header trailing action: pass `headerAction` (e.g., a "Clear all"
 * button on the Analytics run-history rail) — it renders right-aligned
 * inside the header strip.
 */
import React from 'react';

interface Props {
  title: string;
  /** aria-label for the <aside> wrapper. Defaults to `title`. */
  ariaLabel?: string;
  /** Optional trailing element in the header strip (e.g., a button). */
  headerAction?: React.ReactNode;
  /** Rail side. Default 'left'. 'right' uses a left-border instead. */
  side?: 'left' | 'right';
  children: React.ReactNode;
  /** Extra className for callers that need specific width overrides. */
  className?: string;
}

export function LeftRail({ title, ariaLabel, headerAction, side = 'left', children, className }: Props) {
  const sideClass = side === 'right' ? 'view-rail--right' : 'view-rail--left';
  const cls = ['view-rail', sideClass, className ?? ''].filter(Boolean).join(' ');
  return (
    <aside className={cls} aria-label={ariaLabel ?? title}>
      <div className="view-rail-header">
        <span>{title}</span>
        {headerAction}
      </div>
      <div className="view-rail-body">{children}</div>
    </aside>
  );
}
