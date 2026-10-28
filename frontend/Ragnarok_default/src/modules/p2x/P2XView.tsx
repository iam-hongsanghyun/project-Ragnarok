/**
 * P2XView — the P2X tab: chain designer, RFNBO rules, results. Everything is built into the core model through the
 * ordinary fragment merge (`onApplyFragment`); the results read stored runs. No separate engine.
 */
import React from 'react';
import { TopTab, ViewPaneHeader, ViewPanel } from '../../shared/components/primitives';
import type { TopTabItem } from '../../shared/components/primitives';
import type { WorkbookModel } from 'lib/types';
import type { WorkbookFragment } from 'lib/api/databases';
import type { TechCatalogue } from 'lib/api/p2x';
import { fetchTechnologies } from 'lib/api/p2x';
import { stringValue } from 'lib/utils/helpers';
import { ChainDesigner } from './ChainDesigner';
import { RfnboPanel } from './RfnboPanel';
import { ResultsPanel } from './ResultsPanel';
import { defaultForm, DesignerForm } from './spec';
import './p2x.css';

type P2XTab = 'chain' | 'rfnbo' | 'results';
const TABS: TopTabItem<P2XTab>[] = [
  { id: 'chain', label: 'Chain designer' },
  { id: 'rfnbo', label: 'RFNBO' },
  { id: 'results', label: 'Results' },
];

interface Props {
  model: WorkbookModel;
  discountRate: number;
  onApplyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void | Promise<void>;
}

export function P2XView({ model, discountRate, onApplyFragment }: Props) {
  const [tab, setTab] = React.useState<P2XTab>('chain');
  const [catalogue, setCatalogue] = React.useState<TechCatalogue | null>(null);
  const [catalogueError, setCatalogueError] = React.useState<string | null>(null);
  const [form, setForm] = React.useState<DesignerForm>(() => defaultForm(discountRate));
  const chainIds = React.useMemo(() => (model.RAGNAROK_P2X ?? []).map((r) => stringValue(r.name)).filter(Boolean), [model.RAGNAROK_P2X]);

  React.useEffect(() => {
    let live = true;
    fetchTechnologies()
      .then((c) => { if (live) setCatalogue(c); })
      .catch((e) => { if (live) setCatalogueError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, []);

  return (
    <ViewPanel name="p2x">
      <ViewPaneHeader variant="analytics">
        <TopTab items={TABS} active={tab} onChange={setTab} ariaLabel="P2X sections" />
      </ViewPaneHeader>
      {/* The designer stays mounted so its form survives a visit to the other tabs. */}
      <div className="p2x-scroll" hidden={tab !== 'chain'}>
        <ChainDesigner model={model} form={form} onChange={setForm} catalogue={catalogue} catalogueError={catalogueError}
          onApplyFragment={onApplyFragment} existingChainIds={chainIds} />
      </div>
      {tab === 'rfnbo' && <RfnboPanel model={model} />}
      {tab === 'results' && <ResultsPanel />}
    </ViewPanel>
  );
}
