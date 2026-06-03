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
 * Ragnarok mark — a judge's gavel with a lightning bolt struck through its
 * head: the union of market/auction clearing (the gavel) and electric power
 * (the bolt), which is what Ragnarok models.
 *
 * Pure inline SVG, so the same mark scales crisply from a 16 px favicon to a
 * hero splash with no raster assets. It paints in `currentColor`, so it reads
 * on light and dark chrome alike (it takes the colour of the surrounding
 * text), and the bolt is a cut-out — it shows the background through, so it
 * stays legible whatever sits behind the mark. The whole glyph is one group
 * rotated 45° about the centre, giving the head its diagonal orientation and
 * dropping the handle toward the lower-left.
 */
export function RagnarokLogo({ size = 24, className, title = 'Ragnarok' }: RagnarokLogoProps) {
  const decorative = title === '';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      className={className}
      fill="currentColor"
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : title}
      aria-hidden={decorative ? true : undefined}
      focusable="false"
    >
      {!decorative && <title>{title}</title>}
      <g transform="rotate(45 256 256)">
        {/* Hammer head — two banded ends … */}
        <rect x="70" y="151" width="104" height="74" rx="37" />
        <rect x="338" y="151" width="104" height="74" rx="37" />
        {/* … and the central striking block with the lightning bolt cut out. */}
        <path
          fillRule="evenodd"
          d="M181 113 H331 V263 H181 Z M272 126 L224 192 L252 192 L236 250 L300 178 L266 178 L290 126 Z"
        />
        {/* Handle shaft + flared foot */}
        <rect x="226" y="255" width="60" height="150" rx="12" />
        <rect x="208" y="390" width="96" height="52" rx="24" />
      </g>
    </svg>
  );
}
