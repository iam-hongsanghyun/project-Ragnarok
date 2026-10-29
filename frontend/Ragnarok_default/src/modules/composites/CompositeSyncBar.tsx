/**
 * CompositeSyncBar — shown whenever a cell of the RAGNAROK_Composites sheet differs from the composite it describes (or an older
 * workbook has no sheet rows yet). The backend says which composites to re-expand; Apply writes the new sub-component rows as one edit.
 * Used by the Composites tab and by the Model tab, so a sheet edit is visible wherever it is made.
 */
import React, { useEffect, useState } from 'react';
import type { WorkbookModel } from 'lib/types';
import type { PlantChange } from 'lib/build/plants';
import { previewCompositeSync, type CompositeSync } from 'lib/api/plants';

export function useCompositeSync(model: WorkbookModel): CompositeSync | null {
  const [sync, setSync] = useState<CompositeSync | null>(null);
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      Promise.resolve(previewCompositeSync(model)).then((r) => { if (live) setSync(r ?? null); }).catch(() => { if (live) setSync(null); });
    }, 300);
    return () => { live = false; window.clearTimeout(timer); };
  }, [model]);
  return sync?.change ? sync : null;
}

interface Props {
  model: WorkbookModel;
  onApply: (change: PlantChange, label: string) => void | Promise<void>;
}

export function CompositeSyncBar({ model, onApply }: Props) {
  const sync = useCompositeSync(model);
  const [error, setError] = useState<string | null>(null);
  if (!sync?.change) return null;
  const apply = async () => {
    setError(null);
    try { await onApply(sync.change as PlantChange, sync.plantIds.length > 0 ? `Re-derived ${sync.plantIds.join(', ')} from the sheet` : 'Added the RAGNAROK_Composites rows'); } catch (e) { setError(e instanceof Error ? e.message : 'could not apply'); }
  };
  return (
    <div className="cmp-warn" role="status" data-testid="composite-sync">
      {sync.plantIds.length > 0 && <>Edited in the RAGNAROK_Composites sheet: {sync.plantIds.join(', ')}. Apply to re-derive their sub-components from the sheet row (a composite is edited as one asset). </>}
      {(sync.added ?? []).length > 0 && <>No sheet row yet for {(sync.added ?? []).join(', ')} (an older workbook): add the rows. </>}
      <button type="button" className="ghost-button sm" onClick={apply}>{sync.plantIds.length > 0 ? 'Apply sheet edits' : 'Add the sheet rows'}</button>
      {sync.warnings.map((w) => <span key={w} className="cmp-note"> {w}</span>)}
      {error && <span className="cmp-error" role="alert"> {error}</span>}
    </div>
  );
}
