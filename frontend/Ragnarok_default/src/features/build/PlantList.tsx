/**
 * The plants of the model as cards: one row per plant, expandable to its components, with Edit and Delete.
 *
 * A plant is shown, edited and deleted as ONE unit (every component carries the plant id). Delete asks the backend what it would
 * remove and keep (a bus or carrier another component uses stays) before confirming.
 */
import React, { useMemo, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import { plantCards, type PlantCard, type PlantChange } from 'lib/build/plants';
import { previewPlantDelete } from 'lib/api/plants';
import { useDialog } from '../../shared/components/Dialog';
import './plants.css';

interface Props {
  model: WorkbookModel;
  onEdit?: (plant: PlantCard) => void;
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
  /** Plain list (Model tab tree): no heading hint. */
  compact?: boolean;
}

const fmtMw = (v: number | null, extendable: boolean | null): string => (extendable ? 'sized by the solver' : v !== null ? `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} MW` : '');

export function PlantList({ model, onEdit, onApply, compact }: Props) {
  const cards = useMemo(() => plantCards(model), [model]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const { confirm } = useDialog();

  if (cards.length === 0) return null;

  const remove = async (card: PlantCard) => {
    setError(null);
    try {
      const prev = await previewPlantDelete(card.plantId, model);
      const removed = Object.entries(prev.removed).filter(([s]) => !s.startsWith('RAGNAROK')).map(([s, n]) => `${n} ${s}`).join(', ');
      const kept = [...prev.kept.buses.map((b) => `bus ${b}`), ...prev.kept.carriers.map((c) => `carrier ${c}`)];
      const msg = `Delete plant ${card.plantId}? This removes ${removed || 'its rows'}${kept.length ? ` and keeps ${kept.join(', ')} (still used by other components)` : ''}.${prev.warnings.length ? ` ${prev.warnings.join(' ')}` : ''}`;
      if (await confirm(msg, { danger: true, confirmText: 'Delete plant' })) await onApply(prev.change, `Deleted plant ${card.plantId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not delete');
    }
  };

  return (
    <div className="plant-list" data-testid="plant-list">
      <h4 className="plant-list__title">Plants ({cards.length})</h4>
      {!compact && <p className="plant-list__hint">Each plant is one unit: edit it to re-derive its components, delete it to remove them all.</p>}
      {cards.map((card) => (
        <div key={card.plantId} className="plant-card" data-plant={card.plantId}>
          <div className="plant-card__head">
            <button type="button" className="plant-card__toggle" aria-expanded={Boolean(open[card.plantId])} aria-label={`Components of ${card.plantId}`}
              onClick={() => setOpen((o) => ({ ...o, [card.plantId]: !o[card.plantId] }))}>{open[card.plantId] ? '▾' : '▸'}</button>
            <span className="plant-card__name" title={card.label}>{card.plantId}</span>
            <span className="plant-card__meta">{card.type ?? 'imported'}{card.bus ? ` · ${card.bus}` : ''}{fmtMw(card.capacityMwEl, card.extendable) ? ` · ${fmtMw(card.capacityMwEl, card.extendable)}` : ''} · {card.rowCount} rows</span>
            {onEdit && <button type="button" className="ghost-button sm" disabled={!card.editable} title={card.editable ? 'Re-derive the components' : 'No registry row: delete and add it again'} onClick={() => onEdit(card)}>Edit</button>}
            <button type="button" className="ghost-button sm" onClick={() => remove(card)}>Delete</button>
          </div>
          {open[card.plantId] && (
            <ul className="plant-card__components">
              {card.components.map((c) => (
                <li key={`${c.sheet}:${c.name}`} className={c.present ? undefined : 'plant-card__missing'}><code>{c.sheet}</code> · {c.name}{c.role ? ` — ${c.role}` : ''}{c.present ? '' : ' (missing)'}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
      {error && <p className="plant-picker__error">{error}</p>}
    </div>
  );
}
