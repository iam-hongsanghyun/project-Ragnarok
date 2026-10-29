/**
 * RulesPanel — the rules that act on composites at solve time: the co-firing blend-share limits (stored on each fuel-network
 * plant, enforced as a constraint) and the RFNBO matching rules for Power-to-X.
 */
import React from 'react';
import type { GridRow, WorkbookModel } from 'lib/types';
import { plantCards, type PlantCard } from 'lib/build/plants';
import { RfnboPanel } from './RfnboPanel';

interface Props { model: WorkbookModel; onEdit: (plant: PlantCard) => void }

const share = (v: unknown): string => (typeof v === 'number' ? `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })} %` : 'none');

export function RulesPanel({ model, onEdit }: Props) {
  const cards = plantCards(model);
  const cofiring = cards.filter((c) => c.type === 'cofiring_network');
  const hasP2x = cards.some((c) => c.type === 'p2x') || ((model.RAGNAROK_P2X as GridRow[] | undefined)?.length ?? 0) > 0;
  return (
    <div className="cmp-rules">
      <section className="cmp-section" data-testid="cofiring-rules">
        <h3>Co-firing blend limits</h3>
        <p className="cmp-note">
          A gas + H2 co-firing plant with a fuel network lets the solver choose the blend; its hydrogen share of the fuel is held within the limits
          stored on the plant (Maximum / Minimum H2 share). Shares are entered as vol% or energy% (vol is converted with the LHV per Nm3). A run that sets
          no cofiringConfig option takes these limits; an explicit run option always wins.
        </p>
        {cofiring.length === 0 ? <p className="cmp-note">No fuel-network co-firing plant in this model.</p> : (
          <table className="cmp-table" aria-label="Co-firing blend limits">
            <thead><tr><th>Plant</th><th className="num">Maximum H2 share</th><th className="num">Minimum H2 share</th><th>Basis</th><th>Applies</th><th /></tr></thead>
            <tbody>
              {cofiring.map((c) => (
                <tr key={c.plantId}>
                  <td>{c.plantId}</td>
                  <td className="num">{share(c.spec?.blendMax)}</td>
                  <td className="num">{share(c.spec?.blendMin)}</td>
                  <td>{String(c.spec?.blendUnit ?? 'vol')}</td>
                  <td>{String(c.spec?.blendScope ?? 'hourly')}</td>
                  <td><button type="button" className="ghost-button sm" disabled={!c.editable} onClick={() => onEdit(c)}>Edit limits</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="cmp-section">
        <h3>RFNBO matching (Power-to-X)</h3>
        {!hasP2x && <p className="cmp-note">No P2X composite in this model: the rules below apply once one is added. They are stored for the session and ride with the next solve.</p>}
        <RfnboPanel model={model} />
      </section>
    </div>
  );
}
