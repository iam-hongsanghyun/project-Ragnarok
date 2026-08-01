/**
 * Shared 20×20 line-icon frame for activity-bar glyphs.
 *
 * stroke = currentColor so the icon inherits the button's active/hover colour.
 * Used by the core entries in `layout/ActivityBar.tsx` and by every tab-module
 * manifest under `src/modules/` — one frame, so core and module icons render
 * identically on the bar.
 */
import React from 'react';

export function lineIcon(children: React.ReactNode): React.ReactNode {
  return (
    <svg
      viewBox="0 0 20 20"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}
