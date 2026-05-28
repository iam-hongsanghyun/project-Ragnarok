/**
 * Component types section — read-only PyPSA standard catalogue for
 * line_types / transformer_types with "Add to model" actions.
 */
import React from 'react';
import { GridRow, WorkbookModel } from '../../shared/types';
import {
  PYPSA_STANDARD_LINE_TYPES,
  PYPSA_STANDARD_TRANSFORMER_TYPES,
  PYPSA_STANDARD_TYPES_SOURCE,
} from '../../constants/pypsa_standard_types';
import { stringValue } from '../../shared/utils/helpers';
import { CatalogueTable } from './ComponentTypes/CatalogueTable';

export interface ComponentTypesSectionProps {
  model: WorkbookModel;
  onAddStandardType: (sheet: 'line_types' | 'transformer_types', row: GridRow) => void;
}

export function ComponentTypesSection(props: ComponentTypesSectionProps) {
  const lineTypes = (props.model.line_types ?? []) as GridRow[];
  const transformerTypes = (props.model.transformer_types ?? []) as GridRow[];
  const modelLineNames = new Set(lineTypes.map((r) => stringValue(r.name)));
  const modelXfmrNames = new Set(transformerTypes.map((r) => stringValue(r.name)));

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Component types</h3>
        <p>
          PyPSA-native <code>line_types</code> and <code>transformer_types</code> catalogues.
          The {PYPSA_STANDARD_LINE_TYPES.length} standard line types and {PYPSA_STANDARD_TRANSFORMER_TYPES.length} standard transformer types ship with PyPSA
          ({PYPSA_STANDARD_TYPES_SOURCE.repo} @ {(PYPSA_STANDARD_TYPES_SOURCE.commit ?? '').slice(0, 7) || 'unknown'}).
          They're already available for use in the <code>type</code> column of lines / transformers — clicking <em>Add to model</em> only copies the row into your workbook so you can edit it.
        </p>
      </header>

      <h4 style={{ marginTop: 16, marginBottom: 6 }}>Line types — standard catalogue ({PYPSA_STANDARD_LINE_TYPES.length})</h4>
      <CatalogueTable
        rows={PYPSA_STANDARD_LINE_TYPES}
        cols={[
          { key: 'name', label: 'Name' },
          { key: 'f_nom', label: 'f_nom (Hz)' },
          { key: 'r_per_length', label: 'r (Ω/km)' },
          { key: 'x_per_length', label: 'x (Ω/km)' },
          { key: 'c_per_length', label: 'c (nF/km)' },
          { key: 'i_nom', label: 'i_nom (kA)' },
          { key: 'mounting', label: 'Mounting' },
          { key: 'cross_section', label: 'Cross section (mm²)' },
        ]}
        alreadyInModel={modelLineNames}
        onAdd={(row) => props.onAddStandardType('line_types', row)}
      />

      <h4 style={{ marginTop: 24, marginBottom: 6 }}>Transformer types — standard catalogue ({PYPSA_STANDARD_TRANSFORMER_TYPES.length})</h4>
      <CatalogueTable
        rows={PYPSA_STANDARD_TRANSFORMER_TYPES}
        cols={[
          { key: 'name', label: 'Name' },
          { key: 's_nom', label: 's_nom (MVA)' },
          { key: 'v_nom_0', label: 'v_nom_0 (kV)' },
          { key: 'v_nom_1', label: 'v_nom_1 (kV)' },
          { key: 'vsc', label: 'vsc (%)' },
          { key: 'vscr', label: 'vscr (%)' },
          { key: 'pfe', label: 'pfe (kW)' },
          { key: 'i0', label: 'i0 (%)' },
        ]}
        alreadyInModel={modelXfmrNames}
        onAdd={(row) => props.onAddStandardType('transformer_types', row)}
      />
    </section>
  );
}
