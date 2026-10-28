/**
 * Screening view — a statistical pre-screen of solar and wind sites and of the
 * regions they sit in, on historical series the user uploads (correlation,
 * clustering, within- vs between-region structure, complementarity, portfolios).
 * A first-party tab module (`modules/screening/`); the panes live in
 * `features/screening/`. "Add selected sites to model" is the one way back into
 * the model (the Data-view fragment merge), so the Siting tab stays independent.
 */
import React, { useMemo } from 'react';
import { ViewPaneHeader } from '../shared/components/primitives';
import { WorkbookModel } from 'lib/types';
import { WorkbookFragment } from 'lib/api/databases';
import { ScreeningPane } from '../features/screening/ScreeningPane';
import { connectableBusesOf, snapshotLabelsOf } from './SitingView';

interface Props {
  model: WorkbookModel;
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
  currencySymbol: string;
  /** Settings -> Discount rate, written to extendable candidates as `discount_rate`. */
  discountRate?: number;
  /** Stored run whose system price can serve as the reference series; null = none yet. */
  runName?: string | null;
}

export function ScreeningView({ model, onApplyFragment, currencySymbol, discountRate, runName = null }: Props) {
  const buses = useMemo(() => connectableBusesOf(model.buses), [model.buses]);
  const snapshots = useMemo(() => snapshotLabelsOf(model.snapshots), [model.snapshots]);
  return (
    <div className="analytics-view">
      <div className="analytics-view-main">
        <ViewPaneHeader variant="analytics">
          <div>
            <p className="eyebrow">Screening</p>
            <h2>Site and region screening</h2>
          </div>
        </ViewPaneHeader>
        <div style={{ display: 'flex', flex: 1, minHeight: 0, flexDirection: 'column' }}>
          <ScreeningPane
            buses={buses}
            targetSnapshots={snapshots}
            currencySymbol={currencySymbol}
            discountRate={discountRate}
            runName={runName}
            onApplyFragment={onApplyFragment}
          />
        </div>
      </div>
    </div>
  );
}
