/**
 * Risk (CVaR) and two-stage sizing — two Solve options kept in the advanced solve settings.
 *
 *  - CVaR: in stochastic mode PyPSA weighs the worst share of scenario probability next to the expected cost
 *    (`options.riskPreference {alpha, omega}`); the backend refuses it without at least two weighted scenarios.
 *  - Two-stage: size capacities on the LP relaxation, fix them, re-solve the dispatch (`options.twoStage`).
 *
 * Labels' units and help text come from the run-options reference.
 */
import React from 'react';
import type { StochasticConfig } from 'lib/types';
import {
  DEFAULT_RISK_PREFERENCE,
  type AdvancedSolveOptions,
} from 'lib/settings/advancedSolve';
import { NullableNumberInput, OnOff, OptionRow, useOptionFields } from './OptionRow';

export interface RiskTwoStageSectionProps {
  advancedSolve?: AdvancedSolveOptions;
  onAdvancedSolveChange: (v: AdvancedSolveOptions) => void;
  stochasticConfig: StochasticConfig;
}

export function RiskTwoStageSection({ advancedSolve, onAdvancedSolveChange, stochasticConfig }: RiskTwoStageSectionProps) {
  const adv = advancedSolve ?? {};
  const set = (patch: Partial<AdvancedSolveOptions>) => onAdvancedSolveChange({ ...adv, ...patch });
  const risk = adv.riskPreference;
  const alphaFields = useOptionFields('options.riskPreference');
  const twoStageFields = useOptionFields('options.twoStage');
  const stochasticReady = stochasticConfig.enabled && stochasticConfig.scenarios.length >= 2;

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Risk (CVaR) and two-stage</h3>
        <p>
          Stochastic planning minimises the expected cost over the weighted scenarios. A CVaR preference also weighs the
          worst scenarios, so the investment hedges tail risk. Two-stage sizing separates capacity sizing from dispatch.
        </p>
      </header>

      <OptionRow label="CVaR risk preference" field={alphaFields['options.riskPreference']}>
        <OnOff value={!!risk} onChange={(on) => set({ riskPreference: on ? { ...DEFAULT_RISK_PREFERENCE } : undefined })} offLabel="Risk-neutral" onLabel="CVaR" />
      </OptionRow>
      {risk && !stochasticReady && (
        <p className="sg-setting-hint" role="alert">
          CVaR needs stochastic mode with at least two weighted scenarios (Settings, Stochastic); the run is refused otherwise.
        </p>
      )}
      {risk && (
        <>
          <OptionRow label="Confidence level alpha" field={alphaFields['options.riskPreference.alpha']} htmlFor="rs-cvar-alpha">
            <NullableNumberInput
              id="rs-cvar-alpha" min={0.01} max={0.99} step={0.01} value={risk.alpha}
              onChange={(n) => { if (n !== null && n > 0 && n < 1) set({ riskPreference: { ...risk, alpha: n } }); }}
            />
          </OptionRow>
          <OptionRow label="CVaR weight omega" field={alphaFields['options.riskPreference.omega']} htmlFor="rs-cvar-omega">
            <NullableNumberInput
              id="rs-cvar-omega" min={0} max={1} step={0.05} value={risk.omega}
              onChange={(n) => { if (n !== null && n >= 0 && n <= 1) set({ riskPreference: { ...risk, omega: n } }); }}
            />
          </OptionRow>
        </>
      )}

      <div className="sg-setting-divider" />
      <OptionRow label="Two-stage sizing" field={twoStageFields['options.twoStage.enabled']}>
        <OnOff value={!!adv.twoStage} onChange={(on) => set({ twoStage: on || undefined })} />
      </OptionRow>
    </section>
  );
}
