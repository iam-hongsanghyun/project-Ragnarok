import React from 'react';

export interface RagnarokLogoProps {
  /** Rendered width = height, in px. */
  size?: number;
  className?: string;
  /**
   * Accessible label. Pass an empty string for a purely decorative mark that
   * sits next to a visible "Ragnarok" wordmark (avoids double-announcing it to
   * screen readers).
   */
  title?: string;
}

/**
 * Ragnarok mark — Mjölnir, Thor's hammer, in gold on a dark Norse-storm
 * gradient.
 *
 * Pure inline SVG, so the same mark scales crisply from a 16 px favicon to a
 * hero splash with no raster assets, and it carries its own colours (it does
 * not depend on theme tokens, so it reads the same on light and dark chrome).
 * Gradient / filter ids are made unique per instance via {@link React.useId}
 * (colons stripped so they are valid inside `url(#…)`) so several logos on one
 * page never collide.
 */
export function RagnarokLogo({ size = 24, className, title = 'Ragnarok' }: RagnarokLogoProps) {
  const uid = React.useId().replace(/:/g, '');
  const stormId = `rk-storm-${uid}`;
  const metalId = `rk-metal-${uid}`;
  const glowId = `rk-glow-${uid}`;
  const decorative = title === '';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : title}
      aria-hidden={decorative ? true : undefined}
      focusable="false"
    >
      {!decorative && <title>{title}</title>}
      <defs>
        <linearGradient id={stormId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3730a3" />
          <stop offset="55%" stopColor="#312e81" />
          <stop offset="100%" stopColor="#15123f" />
        </linearGradient>
        <linearGradient id={metalId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#fffbeb" />
          <stop offset="45%" stopColor="#fcd34d" />
          <stop offset="100%" stopColor="#f59e0b" />
        </linearGradient>
        <filter id={glowId} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="2.1" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {/* Storm field */}
      <rect
        x="2"
        y="2"
        width="60"
        height="60"
        rx="16"
        fill={`url(#${stormId})`}
        stroke="#4f46e5"
        strokeOpacity="0.45"
        strokeWidth="1"
      />
      {/* Mjölnir — flared blocky head + flaring handle base */}
      <g filter={`url(#${glowId})`} fill={`url(#${metalId})`}>
        <path d="M18 12 H46 V22 H51 L49 31 H15 L13 22 H18 Z" />
        <path d="M28 31 H36 L40 55 H24 Z" />
      </g>
      {/* Engraved band across the head */}
      <rect x="19" y="16.5" width="26" height="2.6" rx="1.3" fill="#1e1b4b" opacity="0.4" />
    </svg>
  );
}
