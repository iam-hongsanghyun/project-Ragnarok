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
 *
 * After an import the model check reads the workbook the session now holds and lists what is very likely not what was
 * meant, each with its visible fix (set the weightings from the timestamp spacing; clean placeholder bounds).
 */
import React from 'react';
import { DataImportView } from '../features/data/DataImportView';
import { ModelCheckPanel } from '../features/validation/ModelCheckPanel';
import { WorkbookFragment } from 'lib/api/databases';
import type { WorkbookModel } from 'lib/types';

interface Props {
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
  /** The working model; its identity is the model-check refresh key. */
  model: WorkbookModel;
  onSessionSync: () => Promise<void>;
  onSessionReload: () => Promise<void>;
  onSetWeightingsFromSpacing?: () => Promise<void> | void;
}

export function DataView({ onApplyFragment, model, onSessionSync, onSessionReload, onSetWeightingsFromSpacing }: Props) {
  return (
    <DataImportView
      applyFragment={onApplyFragment}
      afterImport={(
        <ModelCheckPanel
          refreshKey={model}
          onSessionSync={onSessionSync}
          onSessionReload={onSessionReload}
          onSetWeightingsFromSpacing={onSetWeightingsFromSpacing}
        />
      )}
    />
  );
}
