/**
 * Constraints sections, split into two Settings nav entries:
 *  - Standard Constraints: the custom-solver table + native PyPSA
 *    `global_constraints` table.
 *  - Advanced Constraints: the free-text constraint code box + the read-only
 *    applied-constraints list.
 */
import React from 'react';
import { AppliedConstraint, CustomConstraint, GridRow, PathwayConfig, Primitive, WorkbookModel } from 'lib/types';
import { generatorCarriers } from 'lib/constraints/custom';
import { GlobalConstraintsSection as CustomConstraintsEditor } from '../../features/constraints/GlobalConstraintsSection';
import { CarrierGrowthEditor } from './Constraints/CarrierGrowthEditor';
import { GlobalConstraintsTableEditor } from './Constraints/GlobalConstraintsTableEditor';
import { CustomDslSection } from '../../features/constraints/CustomDslSection';

export interface ConstraintsSectionProps {
  model: WorkbookModel;
  pathwayConfig: PathwayConfig;
  constraints: CustomConstraint[];
  onConstraintsChange: (next: CustomConstraint[]) => void;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
  appliedConstraints?: AppliedConstraint[];
  onUpdateRow: (sheet: 'global_constraints' | 'carriers', rowIndex: number, key: string, value: Primitive) => void;
  onAddRow: (sheet: 'global_constraints') => void;
  onDeleteRow: (sheet: 'global_constraints', rowIndex: number) => void;
}

// Reserved carrier columns that are metadata, not numeric attributes you can
// weight a global constraint by. Everything else on the carriers sheet is
// fair game for `primary_energy` constraints.
const CARRIER_META_COLS = new Set(['name', 'color', 'nice_name']);

export function StandardConstraintsSection(props: ConstraintsSectionProps) {
  const carriers = Array.from(
    new Set(props.model.carriers.map((c) => String(c.name ?? '')).filter(Boolean)),
  );
  // Only these can bind a custom carrier constraint (see generatorCarriers).
  const genCarriers = generatorCarriers(props.model);
  // Numeric columns on the carriers sheet (co2_emissions, max_growth, …)
  // are the valid `carrier_attribute` choices for `primary_energy` rows.
  const carrierAttributes = Array.from(
    new Set(
      props.model.carriers
        .flatMap((row) => Object.keys(row))
        .filter((key) => !CARRIER_META_COLS.has(key)),
    ),
  );
  const busNames = Array.from(
    new Set((props.model.buses ?? []).map((b) => String(b.name ?? '')).filter(Boolean)),
  );
  const investmentPeriods = props.pathwayConfig.enabled
    ? props.pathwayConfig.periods.map((p) => p.period)
    : [];
  const globalRows = (props.model.global_constraints ?? []) as GridRow[];
  return (
    <>
      <section className="constraints-workspace-section">
        <header className="constraints-workspace-section-header">
          <h3>Custom solver constraints</h3>
          <p>Applied as <code>linopy</code> constraints during the solve. Add custom rows for caps and floors that aren't expressible in the native <code>global_constraints</code> sheet.</p>
        </header>
        <CustomConstraintsEditor
          constraints={props.constraints}
          // Generator carriers, NOT the carriers sheet: the solver resolves a
          // carrier constraint against `generators.carrier`, so offering sheet-only
          // carriers (e.g. "AC") would silently produce constraints it drops.
          carriers={genCarriers}
          onChange={props.onConstraintsChange}
        />
      </section>
      <div className="sg-setting-divider" style={{ margin: '24px 0' }} />
      <section className="constraints-workspace-section">
        <header className="constraints-workspace-section-header">
          <h3>PyPSA <code>global_constraints</code> sheet</h3>
          <p>Native PyPSA constraints that flow through the generic import path and persist as rows in the <code>global_constraints</code> workbook sheet.</p>
        </header>
        <GlobalConstraintsTableEditor
          rows={globalRows}
          carriers={carriers}
          carrierAttributes={carrierAttributes}
          busNames={busNames}
          investmentPeriods={investmentPeriods}
          pathwayEnabled={props.pathwayConfig.enabled}
          onAdd={() => props.onAddRow('global_constraints')}
          onDelete={(rowIndex) => props.onDeleteRow('global_constraints', rowIndex)}
          onSet={(rowIndex, key, value) => props.onUpdateRow('global_constraints', rowIndex, key, value)}
        />
      </section>
      <div className="sg-setting-divider" style={{ margin: '24px 0' }} />
      <section className="constraints-workspace-section">
        <header className="constraints-workspace-section-header">
          <h3>Carrier growth limits</h3>
          <p>
            <code>max_growth</code> caps new capacity (MW) per investment period and{' '}
            <code>max_relative_growth</code> caps it as a ratio of the previous period; both are columns of the{' '}
            <code>carriers</code> sheet. Leave empty for unlimited. They only bind on multi-period (pathway) runs.
          </p>
        </header>
        <CarrierGrowthEditor
          carriers={props.model.carriers ?? []}
          pathwayEnabled={props.pathwayConfig.enabled}
          onSet={(rowIndex, key, value) => props.onUpdateRow('carriers', rowIndex, key, value)}
        />
      </section>
    </>
  );
}

export function AdvancedConstraintsSection(props: ConstraintsSectionProps) {
  return (
    <CustomDslSection
      customDsl={props.customDsl}
      onCustomDslChange={props.onCustomDslChange}
      appliedConstraints={props.appliedConstraints}
    />
  );
}
