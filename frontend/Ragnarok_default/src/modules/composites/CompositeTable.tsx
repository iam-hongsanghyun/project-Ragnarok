/**
 * CompositeTable — every composite asset in the model, one row each: name, type, capacity, how it connects to the network
 * (read from its PyPSA rows by `lib/build/connections.ts`), and the rows it owns. Edit re-derives it from its stored spec;
 * Delete asks the backend what it would remove and keep before confirming.
 */
import React, { useMemo, useState } from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { derivedLines, plantCards, type PlantCard, type PlantChange } from 'lib/build/plants';
import { connectionsOf, matchedGenerators, plantComponentRows, portPhrase } from 'lib/build/connections';
import { previewDetach, previewPlantDelete } from 'lib/api/plants';
import { CompositeSyncBar } from './CompositeSyncBar';
import { COMPOSITE_TEMPLATES_SHEET } from 'lib/workbook/workbook';
import { useDialog } from '../../shared/components/Dialog';
import { ConnectionSchematic } from './ConnectionSchematic';

interface Props {
  model: WorkbookModel;
  onEdit: (plant: PlantCard) => void;
  /** Open the Place on buses form with this composite as the source. */
  onPlace?: (plant: PlantCard) => void;
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
  /** A composite to open expanded (the map's marker click lands here). */
  focusPlantId?: string | null;
}

const mw = (v: number): string => `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} MW`;
const fmtMw = (v: number | null, extendable: boolean | null): string => (extendable ? 'sized by the solver' : v !== null ? mw(v) : '—');

export function CompositeTable({ model, onEdit, onPlace, onApply, focusPlantId }: Props) {
  const cards = useMemo(() => plantCards(model), [model]);
  const buses = (model.buses ?? []) as GridRow[];
  const [open, setOpen] = useState<Record<string, boolean>>(focusPlantId ? { [focusPlantId]: true } : {});
  const [error, setError] = useState<string | null>(null);
  const { confirm } = useDialog();
  const detach = async (card: PlantCard) => {
    setError(null);
    try {
      const prev = await previewDetach(card.plantId, model);
      const msg = `Detach composite ${card.plantId}? Its ${card.rowCount} rows stay in the workbook with every value, as plain components: they are no longer one asset, and editing the sheet row no longer re-derives them.`;
      if (await confirm(msg, { confirmText: 'Detach' })) await onApply(prev.change, `Detached composite ${card.plantId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not detach');
    }
  };

  const saveTemplate = async (card: PlantCard) => {
    setError(null);
    const { plantId: _id, bus: _bus, ...spec } = (card.spec ?? {}) as Record<string, unknown>;
    try {
      await onApply({ remove: {}, release: [], kept: { buses: [], carriers: [] },
        fragment: { sheets: { [COMPOSITE_TEMPLATES_SHEET]: [{ name: `${card.plantId}_template`, type: card.type ?? '', spec: JSON.stringify(spec) }] } } }, `Saved template ${card.plantId}_template`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not save the template');
    }
  };

  const remove = async (card: PlantCard) => {
    setError(null);
    try {
      const prev = await previewPlantDelete(card.plantId, model);
      const removed = Object.entries(prev.removed).filter(([s]) => !s.startsWith('RAGNAROK')).map(([s, n]) => `${n} ${s}`).join(', ');
      const kept = [...prev.kept.buses.map((b) => `bus ${b}`), ...prev.kept.carriers.map((c) => `carrier ${c}`)];
      const msg = `Delete composite ${card.plantId}? This removes ${removed || 'its rows'}${kept.length ? ` and keeps ${kept.join(', ')} (still used by other components)` : ''}.${prev.warnings.length ? ` ${prev.warnings.join(' ')}` : ''}`;
      if (await confirm(msg, { danger: true, confirmText: 'Delete composite' })) await onApply(prev.change, `Deleted composite ${card.plantId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not delete');
    }
  };

  if (cards.length === 0) {
    return <p className="cmp-note" data-testid="composite-table">No composite assets in this model yet. Use Add a composite to create a BESS, CCGT / OCGT, gas + H2 co-firing plant or a Power-to-X chain.</p>;
  }

  return (
    <div data-testid="composite-table">
      <CompositeSyncBar model={model} onApply={onApply} />
      <table className="cmp-table" aria-label="Composites in this model">
        <thead><tr><th>Name</th><th>Type</th><th className="num">Capacity</th><th>Connections</th><th>PyPSA rows</th><th>Actions</th></tr></thead>
        <tbody>
          {cards.map((card) => {
            const rows = plantComponentRows(model, card.plantId);
            const conn = connectionsOf(rows, buses, matchedGenerators(model, card.plantId, card.spec));
            const expanded = Boolean(open[card.plantId]);
            const comps = card.components.filter((c) => c.sheet !== 'buses' && c.sheet !== 'carriers');
            return (
              <React.Fragment key={card.plantId}>
                <tr data-plant={card.plantId} className={focusPlantId === card.plantId ? 'cmp-row--focus' : undefined}>
                  <td title={card.label}><strong>{card.plantId}</strong></td>
                  <td>{card.type ?? 'imported'}</td>
                  <td className="num">{fmtMw(card.capacityMwEl, card.extendable)}</td>
                  <td>
                    {conn.ports.length === 0 && conn.matched.length === 0 && <span className="cmp-note">no bus found in its rows</span>}
                    <ul className="cmp-portlist">
                      {conn.ports.map((p) => (
                        <li key={p.bus}>{portPhrase(p)} <code>{p.bus}</code>{p.created ? ' (created)' : ''}{p.loadMw !== null ? `; offtake load ${mw(p.loadMw)}` : ''}</li>
                      ))}
                      {conn.matched.length > 0 && <li>renewable supply matched to generators {conn.matched.map((g, i) => <React.Fragment key={g}>{i > 0 ? ', ' : ''}<code>{g}</code></React.Fragment>)}</li>}
                    </ul>
                  </td>
                  <td>
                    <button type="button" className="cmp-link" aria-expanded={expanded} aria-label={`PyPSA rows of ${card.plantId}`}
                      onClick={() => setOpen((o) => ({ ...o, [card.plantId]: !o[card.plantId] }))}>{expanded ? 'Hide' : 'Show'} {card.rowCount} rows</button>
                    {!expanded && <span className="cmp-note"> {Array.from(new Set(comps.map((c) => c.sheet))).join(', ')}</span>}
                  </td>
                  <td className="cmp-actions-cell">
                    <button type="button" className="ghost-button sm" disabled={!card.editable} title={card.editable ? 'Re-derive the components' : 'No registry row: delete and add it again'} onClick={() => onEdit(card)}>Edit</button>
                    {onPlace && <button type="button" className="ghost-button sm" disabled={!card.editable} title="Place copies of this composite on other buses" onClick={() => onPlace(card)}>Place on buses</button>}
                    <button type="button" className="ghost-button sm" disabled={!card.editable} title="Keep this composite's settings as a reusable template" onClick={() => saveTemplate(card)}>Save as template</button>
                    <button type="button" className="ghost-button sm" disabled={!card.editable} title="Turn its rows into plain components" onClick={() => detach(card)}>Detach</button>
                    <button type="button" className="ghost-button sm" onClick={() => remove(card)}>Delete</button>
                  </td>
                </tr>
                {expanded && (
                  <tr className="cmp-row--detail">
                    <td colSpan={6}>
                      {derivedLines(card.derived).map((l) => <p key={l} className="cmp-note">{l}</p>)}
                      <ul className="cmp-rowlist">
                        {card.components.map((c) => (
                          <li key={`${c.sheet}:${c.name}`} className={c.present ? undefined : 'cmp-missing'}><code>{c.sheet}</code> {c.name}{c.role ? `: ${c.role}` : ''}{c.present ? '' : ' (missing)'}</li>
                        ))}
                      </ul>
                      <ConnectionSchematic connections={conn} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      {error && <p className="cmp-error" role="alert">{error}</p>}
    </div>
  );
}
