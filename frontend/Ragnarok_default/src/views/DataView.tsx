/**
 * Data view — entry point for external dataset importers and the data platform.
 *
 * Placeholder for now. Will host the roadmap items tracked in docs/TODO.md:
 *   D1  profile / weather data layer (storage + source registry + health)
 *   I1  location-based data & model bootstrap
 *   I2  PyPSA-Earth / open-data toolchain importer
 *   I3  demand forecast generator
 */
import React from 'react';

export function DataView() {
  return (
    <div className="view data-view">
      <div className="view-empty">
        <h3>Data</h3>
        <p>
          Importers and external datasets will live here. Empty for now — tracked
          as <code>D1</code> / <code>I1</code> / <code>I2</code> / <code>I3</code> in
          <code> docs/TODO.md</code>.
        </p>
      </div>
    </div>
  );
}
