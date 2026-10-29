/**
 * Gas + H2 co-firing blend limits (`options.cofiringConfig`).
 *
 * The H2 share of the fuel burned (LHV basis) is held within [min, max] in every snapshot or over the run, for the
 * fuel-network co-firing plants added in Composites. Without an explicit config a run takes the limits stored
 * with each plant; "Explicit" sends this block, which always wins (even when disabled). Shares are typed in percent and
 * sent as fractions; labels, units and help text come from the run-options reference.
 */
import React from 'react';
import { DEFAULT_SESSION_ID } from 'lib/api/session';
import { fetchPlants, type PlantSummary } from 'lib/api/plants';
import {
  DEFAULT_COFIRING,
  type AdvancedSolveOptions,
  type CofiringLimits,
  type CofiringOptions,
  type CofiringScope,
  type CofiringUnit,
} from 'lib/settings/advancedSolve';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';
import { useAsync } from '../../shared/hooks/useAsync';
import { NullableNumberInput, OnOff, OptionRow, useOptionFields } from './OptionRow';

/** Registry type of the plants this block constrains (`backend/app/plants/cofiring.py: network_plants`). */
const COFIRING_PLANT_TYPE = 'cofiring_network';

const toPercent = (fraction: number | null): number | null => (fraction === null ? null : Math.round(fraction * 1e6) / 1e4);
const fromPercent = (percent: number | null): number | null => (percent === null ? null : Math.min(1, Math.max(0, percent / 100)));

export interface CofiringSectionProps {
  advancedSolve?: AdvancedSolveOptions;
  onAdvancedSolveChange: (v: AdvancedSolveOptions) => void;
}

interface LimitInputsProps {
  idPrefix: string;
  limits: CofiringLimits;
  onChange: (patch: Partial<CofiringLimits>) => void;
  fields: ReturnType<typeof useOptionFields>;
}

function LimitInputs({ idPrefix, limits, onChange, fields }: LimitInputsProps) {
  const field = (name: string) => fields[`options.cofiringConfig.${name}`];
  const unitLabel = limits.unit === 'vol' ? '% vol' : '% energy (LHV)';
  const bad = limits.minShare !== null && limits.maxShare !== null && limits.minShare > limits.maxShare;
  return (
    <>
      <OptionRow label="Minimum H2 share" field={field('minShare')} unit={unitLabel} htmlFor={`${idPrefix}-min`}>
        <NullableNumberInput
          id={`${idPrefix}-min`} min={0} max={100} step={1} placeholder="no minimum" value={toPercent(limits.minShare)}
          onChange={(n) => onChange({ minShare: fromPercent(n) })}
        />
      </OptionRow>
      <OptionRow label="Maximum H2 share" field={field('maxShare')} unit={unitLabel} htmlFor={`${idPrefix}-max`}>
        <NullableNumberInput
          id={`${idPrefix}-max`} min={0} max={100} step={1} placeholder="no maximum" value={toPercent(limits.maxShare)}
          onChange={(n) => onChange({ maxShare: fromPercent(n) })}
        />
      </OptionRow>
      {bad && <p className="sg-setting-hint" role="alert">The minimum share is above the maximum; the run is refused.</p>}
      <OptionRow label="Share basis" field={field('unit')} htmlFor={`${idPrefix}-unit`}>
        <select id={`${idPrefix}-unit`} value={limits.unit} onChange={(e) => onChange({ unit: e.target.value as CofiringUnit })}>
          {((field('unit')?.allowed as string[] | undefined) ?? ['energy', 'vol']).map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
      </OptionRow>
      <OptionRow label="Scope" field={field('scope')} htmlFor={`${idPrefix}-scope`}>
        <select id={`${idPrefix}-scope`} value={limits.scope} onChange={(e) => onChange({ scope: e.target.value as CofiringScope })}>
          {((field('scope')?.allowed as string[] | undefined) ?? ['hourly', 'period']).map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
      </OptionRow>
    </>
  );
}

export function CofiringSection({ advancedSolve, onAdvancedSolveChange }: CofiringSectionProps) {
  const adv = advancedSolve ?? {};
  const cfg = adv.cofiringConfig;
  const fields = useOptionFields('options.cofiringConfig');
  const plantState = useAsync<PlantSummary[]>('plants', () => fetchPlants(DEFAULT_SESSION_ID));
  const plants = (plantState.data ?? []).filter((p) => p.type === COFIRING_PLANT_TYPE);
  const setCfg = (patch: Partial<CofiringOptions>) => onAdvancedSolveChange({ ...adv, cofiringConfig: { ...(cfg ?? DEFAULT_COFIRING), ...patch } });
  const labelOf = (id: string) => plants.find((p) => p.plantId === id)?.label ?? id;
  const listed = cfg && cfg.plants.length > 0 ? cfg.plants : plants.map((p) => p.plantId);

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Gas + H2 co-firing</h3>
        <p>{fields['options.cofiringConfig']?.meaning ?? 'Blend-share limits for the fuel-network co-firing plants.'}</p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label">Source of the limits</label>
        <div className="sg-btn-row">
          <button
            type="button" className={`tb-btn sg-solver-btn${!cfg ? '' : ' tb-btn--muted'}`}
            onClick={() => onAdvancedSolveChange({ ...adv, cofiringConfig: undefined })}
          >
            Plant data
          </button>
          <button
            type="button" className={`tb-btn sg-solver-btn${cfg ? '' : ' tb-btn--muted'}`}
            onClick={() => { if (!cfg) setCfg({}); }}
          >
            Explicit
          </button>
        </div>
        <p className="sg-setting-hint">
          Plant data: each plant keeps the blend limits stored with it in Build (nothing is sent with the run). Explicit: the
          block below is sent and overrides them.
        </p>
      </div>

      {cfg && (
        <>
          <OptionRow label="Enforce the limits" field={fields['options.cofiringConfig.enabled']}>
            <OnOff value={cfg.enabled} onChange={(on) => setCfg({ enabled: on })} offLabel="Disabled" onLabel="Enabled" />
          </OptionRow>

          {cfg.enabled && (
            <>
              <OptionRow label="Plants" field={fields['options.cofiringConfig.plants']}>
                <SearchableMultiSelect
                  values={cfg.plants}
                  options={plants.map((p) => ({ value: p.plantId, label: p.label }))}
                  placeholder="All co-firing plants"
                  onChange={(vals) => setCfg({ plants: vals })}
                />
              </OptionRow>
              {plantState.data && plants.length === 0 && (
                <p className="sg-setting-hint">
                  The model has no fuel-network co-firing plant. A limit that names none is refused by the run; add one in Build, Generators.
                </p>
              )}
              <LimitInputs idPrefix="rs-cofire" limits={cfg} onChange={(patch) => setCfg(patch)} fields={fields} />

              <div className="sg-setting-divider" />
              <div className="sg-setting-row">
                <label className="sg-setting-label">Per-plant limits</label>
                {listed.length === 0 && <p className="sg-setting-hint">No plants to override.</p>}
                {listed.map((id) => {
                  const own = cfg.perPlant[id];
                  return (
                    <div key={id} className="sg-setting-row">
                      <div className="sg-btn-row">
                        <b>{labelOf(id)}</b>
                        <button
                          type="button" className={`tb-btn${own ? '' : ' tb-btn--muted'}`}
                          onClick={() => {
                            const { [id]: _drop, ...rest } = cfg.perPlant;
                            setCfg({ perPlant: own ? rest : { ...cfg.perPlant, [id]: { minShare: cfg.minShare, maxShare: cfg.maxShare, unit: cfg.unit, scope: cfg.scope } } });
                          }}
                        >
                          {own ? 'Remove own limits' : 'Set own limits'}
                        </button>
                      </div>
                      {own && (
                        <LimitInputs
                          idPrefix={`rs-cofire-${id}`} limits={own} fields={fields}
                          onChange={(patch) => setCfg({ perPlant: { ...cfg.perPlant, [id]: { ...own, ...patch } } })}
                        />
                      )}
                    </div>
                  );
                })}
                <p className="sg-setting-hint">{fields['options.cofiringConfig.perPlant']?.meaning}</p>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
