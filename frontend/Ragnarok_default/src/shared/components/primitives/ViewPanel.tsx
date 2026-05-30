/**
 * ViewPanel — outer container for a view's content. One per tab.
 *
 * Renders the canonical `.view` className plus an optional view-specific
 * modifier so existing per-view CSS hooks (e.g., `.plugins-view`,
 * `.analytics-view`, `.build-view`) still work. New views should pass a
 * `name` prop matching their feature folder.
 */
import React from 'react';

interface Props {
  /** View-specific modifier, e.g., 'plugins' → adds `.plugins-view`. */
  name?: string;
  children: React.ReactNode;
  className?: string;
}

export function ViewPanel({ name, children, className }: Props) {
  const cls = ['view', name ? `${name}-view` : '', className ?? ''].filter(Boolean).join(' ');
  return <div className={cls}>{children}</div>;
}
