/**
 * Data view — external-data importer.
 *
 * Country-first three-pane shell (left rail = database list grouped by
 * Transmission / Generation / Demand; main = world map with country search;
 * right rail = database filters + preview). Each database is its own module
 * under `backend/app/importers/databases/`; the central index is
 * `databases.json`.
 *
 * Roadmap items closed here: `I1` (location-based bootstrap) and `I2`
 * (PyPSA-Earth importer). `I3` / `D1` slot in as new database modules using
 * the same shell.
 */
import React from 'react';
import { DataImportView } from '../features/data/DataImportView';
import { WorkbookFragment } from '../shared/api/databases';

interface Props {
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
}

export function DataView({ onApplyFragment }: Props) {
  return <DataImportView applyFragment={onApplyFragment} />;
}
