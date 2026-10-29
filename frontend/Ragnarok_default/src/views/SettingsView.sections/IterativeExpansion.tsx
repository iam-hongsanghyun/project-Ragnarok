/**
 * Iterative transmission expansion (`options.iterativeExpansion`).
 *
 * PyPSA re-solves the expansion LP, rescaling the reactances of the lines that grew, until the mean-square change of
 * `s_nom_opt` is below the threshold. Optional discrete unit sizes round the expansion to whole line / link modules.
 * Units and help text come from the run-options reference.
 */
import React from 'react';
import type { WorkbookModel } from 'lib/types';
import {
  DEFAULT_ITERATIVE_EXPANSION,
  type AdvancedSolveOptions,
  type IterativeExpansionOptions,
  type LinkUnitOption,
} from 'lib/settings/advancedSolve';
import { NullableNumberInput, OnOff, OptionRow, useOptionFields } from './OptionRow';

export interface IterativeExpansionSectionProps {
  advancedSolve?: AdvancedSolveOptions;
  onAdvancedSolveChange: (v: AdvancedSolveOptions) => void;
  model: WorkbookModel;
}

export function IterativeExpansionSection({ advancedSolve, onAdvancedSolveChange, model }: IterativeExpansionSectionProps) {
  const adv = advancedSolve ?? {};
  const it = adv.iterativeExpansion;
  const fields = useOptionFields('options.iterativeExpansion');
  const f = (name: string) => fields[`options.iterativeExpansion.${name}`];
  const setIt = (patch: Partial<IterativeExpansionOptions>) =>
    onAdvancedSolveChange({ ...adv, iterativeExpansion: { ...(it ?? DEFAULT_ITERATIVE_EXPANSION), ...patch } });
  const enabled = !!it?.enabled;
  const linkNames = ((model.links ?? []) as Array<{ name?: unknown }>).map((r) => String(r.name ?? '')).filter(Boolean);
  const links = it?.links ?? [];
  const setLink = (i: number, patch: Partial<LinkUnitOption>) => setIt({ links: links.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const unusedLink = linkNames.find((n) => !links.some((l) => l.link === n));

  const intField = (key: 'minIterations' | 'maxIterations', label: string) => (
    <OptionRow label={label} field={f(key)} htmlFor={`rs-iter-${key}`}>
      <NullableNumberInput
        id={`rs-iter-${key}`} min={1} step={1} value={it?.[key]}
        onChange={(n) => { if (n !== null && n >= 1) setIt({ [key]: Math.round(n) }); }}
      />
    </OptionRow>
  );

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Iterative transmission expansion</h3>
        <p>
          Solve the expansion repeatedly, rescaling line impedances after each solve, so the lines that grew carry the flows
          their new size implies. Applies to extendable lines (s_nom_extendable) and links.
        </p>
      </header>

      <OptionRow label="Iterative expansion" field={f('enabled')}>
        <OnOff value={enabled} onChange={(on) => setIt({ enabled: on })} />
      </OptionRow>

      {enabled && it && (
        <>
          <OptionRow label="Convergence threshold" field={f('msqThreshold')} htmlFor="rs-iter-msq">
            <NullableNumberInput
              id="rs-iter-msq" min={0} step={0.01} value={it.msqThreshold}
              onChange={(n) => { if (n !== null && n >= 0) setIt({ msqThreshold: n }); }}
            />
          </OptionRow>
          {intField('minIterations', 'Minimum iterations')}
          {intField('maxIterations', 'Maximum iterations')}
          {it.minIterations > it.maxIterations && (
            <p className="sg-setting-hint" role="alert">Minimum iterations exceed the maximum.</p>
          )}

          <div className="sg-setting-divider" />
          <OptionRow label="Line unit size" field={f('lineUnitSize')} htmlFor="rs-iter-line-unit">
            <NullableNumberInput
              id="rs-iter-line-unit" min={0} step={10} placeholder="continuous" value={it.lineUnitSize}
              onChange={(n) => setIt({ lineUnitSize: n !== null && n > 0 ? n : undefined })}
            />
          </OptionRow>
          {it.lineUnitSize !== undefined && (
            <OptionRow label="Line rounding threshold" field={f('lineThreshold')} htmlFor="rs-iter-line-thr">
              <NullableNumberInput
                id="rs-iter-line-thr" min={0} max={1} step={0.05} placeholder="PyPSA default" value={it.lineThreshold}
                onChange={(n) => setIt({ lineThreshold: n !== null && n >= 0 && n <= 1 ? n : undefined })}
              />
            </OptionRow>
          )}
          <OptionRow label="Fractional last unit" field={f('fractionalLastUnitSize')}>
            <OnOff value={it.fractionalLastUnitSize} onChange={(on) => setIt({ fractionalLastUnitSize: on })} />
          </OptionRow>

          <div className="sg-setting-divider" />
          <div className="sg-setting-row">
            <label className="sg-setting-label">Link unit sizes (MW)</label>
            {links.map((l, i) => (
              <div className="sg-btn-row" key={i}>
                <select aria-label="Link" value={l.link} onChange={(e) => setLink(i, { link: e.target.value })}>
                  {linkNames.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                <NullableNumberInput
                  ariaLabel={`${l.link} unit size in MW`} min={0} step={10} placeholder="MW per unit" value={l.unitSize || null}
                  onChange={(n) => setLink(i, { unitSize: n !== null && n > 0 ? n : 0 })}
                />
                <NullableNumberInput
                  ariaLabel={`${l.link} rounding threshold`} min={0} max={1} step={0.05} placeholder="threshold 0-1" value={l.threshold}
                  onChange={(n) => setLink(i, { threshold: n !== null && n >= 0 && n <= 1 ? n : undefined })}
                />
                <button type="button" className="tb-btn tb-btn--muted" onClick={() => setIt({ links: links.filter((_, j) => j !== i) })}>Remove</button>
              </div>
            ))}
            <div className="sg-btn-row">
              <button
                type="button" className="tb-btn" disabled={!unusedLink}
                onClick={() => unusedLink && setIt({ links: [...links, { link: unusedLink, unitSize: 0 }] })}
              >
                Add link
              </button>
            </div>
            <p className="sg-setting-hint">{f('linkUnitSize')?.meaning} A row without a unit size is not sent.</p>
          </div>
        </>
      )}
    </section>
  );
}
