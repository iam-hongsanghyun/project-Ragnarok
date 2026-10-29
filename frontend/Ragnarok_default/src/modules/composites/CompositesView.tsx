/**
 * CompositesView — the Composites tab: composites in this model (with their connections), add / edit one, the rules that act on
 * them, and their results. Everything is built into the core model through the plant change set (`onApplyPlantChange`); the
 * results read stored runs. No separate engine.
 */
import React from 'react';
import { TopTab, ViewPaneHeader, ViewPanel } from '../../shared/components/primitives';
import type { TopTabItem } from '../../shared/components/primitives';
import type { WorkbookModel } from 'lib/types';
import { plantCards, type PlantCard, type PlantChange } from 'lib/build/plants';
import { CompositeForm } from './CompositeForm';
import { CompositeTable } from './CompositeTable';
import { PlaceForm } from './PlaceForm';
import { ResultsSection } from './ResultsSection';
import { RulesPanel } from './RulesPanel';
import './composites.css';
import './p2x.css';

type Section = 'model' | 'add' | 'place' | 'rules' | 'results';
const SECTIONS: TopTabItem<Section>[] = [
  { id: 'model', label: 'In this model' },
  { id: 'add', label: 'Add a composite' },
  { id: 'place', label: 'Place on buses' },
  { id: 'rules', label: 'Rules' },
  { id: 'results', label: 'Results' },
];

interface Props {
  model: WorkbookModel;
  discountRate: number;
  currencySymbol?: string;
  onApplyPlantChange: (change: PlantChange, label: string) => void | Promise<void>;
  /** A composite to open for editing (the Build map's marker click). Cleared through `onFocusHandled`. */
  focusPlantId?: string | null;
  onFocusHandled?: () => void;
}

export function CompositesView({ model, discountRate, currencySymbol, onApplyPlantChange, focusPlantId, onFocusHandled }: Props) {
  const [section, setSection] = React.useState<Section>('model');
  const [editing, setEditing] = React.useState<PlantCard | null>(null);
  const [placeSource, setPlaceSource] = React.useState<PlantCard | null>(null);

  React.useEffect(() => {
    if (!focusPlantId) return;
    const card = plantCards(model).find((c) => c.plantId === focusPlantId);
    if (card?.editable) { setEditing(card); setSection('add'); }
    onFocusHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPlantId]);

  const edit = (card: PlantCard) => { setEditing(card); setSection('add'); };
  const apply = async (change: PlantChange, label: string) => {
    await onApplyPlantChange(change, label);
    setSection('model');
  };

  return (
    <ViewPanel name="composites">
      <ViewPaneHeader variant="analytics">
        <TopTab items={SECTIONS} active={section} onChange={(s) => { if (s !== 'add') setEditing(null); setSection(s); }} ariaLabel="Composites sections" />
      </ViewPaneHeader>
      <div className="cmp-scroll">
        {section === 'model' && <CompositeTable model={model} onEdit={edit} onPlace={(c) => { setPlaceSource(c); setSection('place'); }} onApply={onApplyPlantChange} focusPlantId={focusPlantId} />}
        {section === 'add' && (
          <CompositeForm model={model} onApply={apply} editing={editing} discountRate={discountRate}
            onDoneEditing={() => { setEditing(null); setSection('model'); }} />
        )}
        {section === 'place' && <PlaceForm key={placeSource?.plantId ?? 'none'} model={model} onApply={apply} initialSource={placeSource} />}
        {section === 'rules' && <RulesPanel model={model} onEdit={edit} />}
        {section === 'results' && <ResultsSection model={model} currencySymbol={currencySymbol} />}
      </div>
    </ViewPanel>
  );
}
