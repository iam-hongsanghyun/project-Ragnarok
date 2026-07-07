/**
 * Physical Risk — Scenarios sub-tab.
 *
 * Ported from climaterisk's `ScenariosView`: the physical (climate forcing) and
 * transition (policy pathway) scenario picker that seeds every run, plus the
 * peril selection and horizon/anchor-year targets. Unlike the standalone app
 * (separate `Scenario` + `RunConfig` documents), this backend merges both into
 * one `Portfolio.scenario` (`ScenarioConfig` in `entities.py`) — perils live
 * alongside climate/transition/horizon here instead of a sibling run-config.
 *
 * Edits patch `portfolio.scenario` in place and PUT the whole portfolio back,
 * mirroring `AssetsSection`'s latestRef + trailing-debounce save pattern (a
 * flood of edits — e.g. dragging the discount-rate stepper — must coalesce
 * into one PUT, not one per keystroke).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { SearchableMultiSelect } from '../../shared/components/SearchableMultiSelect';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { useToast } from '../../shared/components/Toast';
import { saveFullSession, getFullLibraries, FullLibraries, FullPortfolio, ScenarioConfig } from 'lib/physicalRisk/configViews';
import { PhysicalRiskSectionProps } from 'lib/physicalRisk/types';

const SAVE_DEBOUNCE_MS = 500;

export function ScenariosSection({ portfolio, onPortfolioChange }: PhysicalRiskSectionProps) {
  const { showToast } = useToast();
  const [libraries, setLibraries] = useState<FullLibraries | null>(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    void getFullLibraries()
      .then((libs) => { if (aliveRef.current) setLibraries(libs); })
      .catch(() => { /* selects fall back to the portfolio's raw ids */ });
    return () => { aliveRef.current = false; };
  }, []);

  // Latest merged portfolio, updated synchronously so rapid successive edits
  // build on each other, and the debounced save always sends the newest state.
  const full = portfolio as FullPortfolio | null;
  const latestRef = useRef<FullPortfolio | null>(full);
  useEffect(() => { latestRef.current = full; }, [full]);
  const saveTimer = useRef<number | null>(null);

  const doSave = useCallback(() => {
    const p = latestRef.current;
    if (!p) return;
    void saveFullSession(p.sessionId, p).catch((err) => {
      const message = err instanceof Error ? err.message : 'Failed to save the scenario';
      showToast(message, 'error');
    });
  }, [showToast]);

  // Flush any pending save when the section unmounts so an in-flight edit is not lost.
  useEffect(() => () => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
      doSave();
    }
  }, [doSave]);

  const patchScenario = useCallback(
    (patch: Partial<ScenarioConfig>) => {
      const base = latestRef.current;
      if (!base) return;
      const updated: FullPortfolio = { ...base, scenario: { ...base.scenario, ...patch } };
      latestRef.current = updated;
      onPortfolioChange(updated);
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => {
        saveTimer.current = null;
        doSave();
      }, SAVE_DEBOUNCE_MS);
    },
    [onPortfolioChange, doSave],
  );

  if (!full) {
    return (
      <div className="pane">
        <div className="pane-header">
          <div>
            <h2>Scenarios</h2>
            <p className="chart-card p">Climate and transition scenario, perils and horizon for the loaded portfolio.</p>
          </div>
        </div>
        <div className="analytics-empty">
          <h3>No portfolio loaded</h3>
          <p>Load the fleet on the Assets tab first, then configure the scenario here.</p>
        </div>
      </div>
    );
  }

  const scenario = full.scenario;
  const perilOptions = (libraries?.perils ?? []).map((p) => ({ value: p.id, label: p.label }));
  const climateOptions = (libraries?.scenarios.climate ?? []).map((c) => ({ value: c.id, label: c.label }));
  const transitionOptions = (libraries?.scenarios.transition ?? []).map((t) => ({ value: t.id, label: t.label }));
  const sectorOptions = (libraries?.sectors ?? []).map((s) => ({ value: s.id, label: s.label }));
  const anchorYearChoices = libraries?.scenarios.anchorYears ?? scenario.anchorYears;

  const toggleAnchorYear = (year: number) => {
    const has = scenario.anchorYears.includes(year);
    const next = has ? scenario.anchorYears.filter((y) => y !== year) : [...scenario.anchorYears, year];
    patchScenario({ anchorYears: next.sort((a, b) => a - b) });
  };

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Scenarios</h2>
          <p className="chart-card p">
            Climate and transition scenario, perils and horizon that every run and report uses for this portfolio.
          </p>
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Physical — climate forcing</h3>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Perils</label>
          <SearchableMultiSelect
            values={scenario.perils}
            options={perilOptions}
            onChange={(next) => patchScenario({ perils: next })}
            placeholder="Select perils"
          />
        </div>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Climate scenario (RCP / SSP)</label>
          <SearchableSelect
            value={scenario.climate}
            options={climateOptions.length > 0 ? climateOptions : [scenario.climate]}
            onChange={(v) => patchScenario({ climate: v })}
          />
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 16 }}>
        <h3>Transition — policy pathway</h3>
        <div className="sg-setting-row">
          <label className="sg-setting-label">NGFS scenario</label>
          <SearchableSelect
            value={scenario.transition}
            options={transitionOptions.length > 0 ? transitionOptions : [scenario.transition]}
            onChange={(v) => patchScenario({ transition: v })}
          />
        </div>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Discount rate</label>
          <input
            type="number"
            className="sg-number-input"
            min={0}
            max={1}
            step={0.005}
            value={scenario.discountRate}
            onChange={(e) => patchScenario({ discountRate: Number(e.target.value) })}
          />
        </div>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Default sector</label>
          <SearchableSelect
            value={scenario.sector}
            options={sectorOptions.length > 0 ? sectorOptions : [scenario.sector]}
            onChange={(v) => patchScenario({ sector: v })}
          />
          <p className="sg-setting-hint">Used for assets that carry no sector of their own (drives the emissions proxy).</p>
        </div>
      </div>

      <div className="chart-card">
        <h3>Horizon — target year and anchor years</h3>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Horizon year</label>
          <input
            type="number"
            className="sg-number-input"
            min={2020}
            max={2100}
            step={5}
            value={scenario.horizonYear}
            onChange={(e) => patchScenario({ horizonYear: Number(e.target.value) || scenario.horizonYear })}
          />
        </div>
        <div className="sg-setting-row">
          <label className="sg-setting-label">Anchor years</label>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            {anchorYearChoices.map((y) => (
              <label key={y} className="modal-check-row">
                <input type="checkbox" checked={scenario.anchorYears.includes(y)} onChange={() => toggleAnchorYear(y)} />
                {y}
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
