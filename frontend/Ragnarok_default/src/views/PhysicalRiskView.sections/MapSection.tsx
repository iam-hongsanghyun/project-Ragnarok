import React from 'react';
import { PortingPlaceholder } from './PortingPlaceholder';

export function MapSection() {
  return (
    <PortingPlaceholder
      title="Map"
      description="Georeferenced asset + hazard-footprint map (draw/import a footprint, preview hazard layers, inspect per-asset impact pins) — ported from climaterisk's Map tab onto Ragnarok's own MapPane, not maplibre-gl."
    />
  );
}
