/**
 * CompositeEditModal — edit one composite in a popup, from any tab (the Model tab's grouped rows and its RAGNAROK_Composites sheet,
 * the Build tab). It is the Composites form itself (`CompositeForm` with `editing`), so ports, size, investment fields, schematic,
 * preview and Apply are the same code; Apply updates the working model through `onApply` and the grid follows.
 */
import React, { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import type { WorkbookModel } from 'lib/types';
import { plantCards, type PlantChange } from 'lib/build/plants';
import { CompositeForm } from './CompositeForm';
import './composites.css';

interface Props {
  model: WorkbookModel;
  plantId: string;
  discountRate?: number;
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
  onClose: () => void;
  /** Leave the popup and open the same composite in the Composites tab. */
  onOpenInComposites?: (plantId: string) => void;
}

export function CompositeEditModal({ model, plantId, discountRate, onApply, onClose, onOpenInComposites }: Props) {
  const card = useMemo(() => plantCards(model).find((c) => c.plantId === plantId && c.editable) ?? null, [model, plantId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="modal-card cmp-modal" role="dialog" aria-modal="true" aria-label={`Edit composite ${plantId}`} data-testid="composite-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cmp-modal__bar">
          {onOpenInComposites && <button type="button" className="cmp-link" onClick={() => { onClose(); onOpenInComposites(plantId); }}>Open in Composites</button>}
          <button type="button" className="ghost-button sm" onClick={onClose}>Close</button>
        </div>
        {card
          ? <CompositeForm model={model} editing={card} discountRate={discountRate} onDoneEditing={onClose} onApply={onApply} />
          : <p className="cmp-note">Composite {plantId} cannot be edited here: it has no registry row (delete and add it again, or detach it).</p>}
      </div>
    </div>,
    document.body,
  );
}
