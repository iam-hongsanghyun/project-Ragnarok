/**
 * TopTab — sub-tab navigation pill row.
 *
 * Renders the `.subnav` pill strip with `.subnav-btn` buttons. Used by
 * AnalyticsSubnav (Validation / Result / Analytics / Comparison / Log)
 * and by BuildView's step strip (with extra step-number rendering via
 * the `renderExtra` slot).
 *
 * For static label-only tabs, pass an array of TopTabItem.
 * For richer per-item content (badges, error counts, step numbers),
 * pass `renderExtra(item)` and it renders alongside the label.
 */
import React from 'react';

export interface TopTabItem<Id extends string = string> {
  id: Id;
  label: string;
  /** Extra modifier classes, e.g., 'subnav-btn--error' for an error pill. */
  modifier?: string;
  /** If the tab is disabled. */
  disabled?: boolean;
}

interface Props<Id extends string> {
  items: TopTabItem<Id>[];
  active: Id;
  onChange: (id: Id) => void;
  /** aria-label for the <nav>. */
  ariaLabel?: string;
  /** Optional per-item extra rendering (rendered after the label span). */
  renderExtra?: (item: TopTabItem<Id>, isActive: boolean) => React.ReactNode;
  /** Extra className applied to the .subnav wrapper. */
  className?: string;
}

export function TopTab<Id extends string>({ items, active, onChange, ariaLabel, renderExtra, className }: Props<Id>) {
  const cls = ['subnav', className ?? ''].filter(Boolean).join(' ');
  return (
    <nav className={cls} aria-label={ariaLabel}>
      {items.map((item) => {
        const isActive = item.id === active;
        const btnCls = [
          'subnav-btn',
          isActive ? 'subnav-btn--active' : '',
          item.modifier ?? '',
        ].filter(Boolean).join(' ');
        return (
          <button
            key={item.id}
            type="button"
            className={btnCls}
            onClick={() => onChange(item.id)}
            disabled={item.disabled}
            aria-current={isActive ? 'page' : undefined}
          >
            <span className="subnav-btn-label">{item.label}</span>
            {renderExtra?.(item, isActive)}
          </button>
        );
      })}
    </nav>
  );
}
