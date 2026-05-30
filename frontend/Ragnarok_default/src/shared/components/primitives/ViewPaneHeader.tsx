/**
 * ViewPaneHeader — top section strip used by every view.
 *
 * Renders the canonical `.view-pane-header` chrome (12/16 padding, 1px
 * bottom border, --panel background) and yields the content slot to the
 * caller (sub-tab nav, file ops, step strip, etc.). View-specific gap
 * tuning lives in the `.view-toolbar` / `.analytics-outer-header` CSS
 * modifier rules; pass `variant="toolbar"` or `variant="analytics"` to
 * pick one up.
 */
import React from 'react';

interface Props {
  /**
   * Selects which existing gap rule layers on top of the shared header
   * baseline. 'toolbar' = tight 6px gap (file ops); 'analytics' = 16px
   * gap (subnav + stats); undefined = the shared default.
   */
  variant?: 'toolbar' | 'analytics';
  children: React.ReactNode;
  className?: string;
}

export function ViewPaneHeader({ variant, children, className }: Props) {
  const variantClass = variant === 'toolbar' ? 'view-toolbar' : variant === 'analytics' ? 'analytics-outer-header' : '';
  const cls = ['view-pane-header', variantClass, className ?? ''].filter(Boolean).join(' ');
  return <div className={cls}>{children}</div>;
}
