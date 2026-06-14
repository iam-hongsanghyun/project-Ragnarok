/**
 * Carbon price section — scalar price + an interactive year-indexed schedule,
 * with a searchable scenario library. One dropdown drives everything: the
 * selected scenario is loaded on the chart (editable) and applied to the run;
 * ticked scenarios are overlaid for comparison. The library persists with the
 * project (see lib/results/carbonLibrary).
 */
import React, { useRef, useState } from 'react';
import { CarbonPriceScheduleEntry, CarbonScheduleProfile } from 'lib/types';
import { SETTINGS_CONFIG } from 'lib/constants';
import { CarbonScheduleChart } from 'features/carbon/CarbonScheduleChart';
import { CarbonScenarioPicker } from 'features/carbon/CarbonScenarioPicker';
import { cloneSchedule, createCarbonProfileId } from 'lib/results/carbonLibrary';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';

export interface CarbonSectionProps {
  carbonPrice: number;
  onCarbonPriceChange: (v: number) => void;
  carbonPriceSchedule: CarbonPriceScheduleEntry[];
  onCarbonPriceScheduleChange: (next: CarbonPriceScheduleEntry[]) => void;
  carbonLibrary: CarbonScheduleProfile[];
  onCarbonLibraryChange: (next: CarbonScheduleProfile[]) => void;
  carbonCheck: { emittingGenerators: number; hasCo2Column: boolean; totalGenerators: number };
  currencySymbol: string;
}

// Distinct overlay colours, indexed by the profile's position in the library
// (so the chart curve and the dropdown swatch always match).
const PALETTE = ['#2563eb', '#db2777', '#7c3aed', '#0891b2', '#65a30d', '#ea580c'];
const colorOf = (i: number) => PALETTE[i % PALETTE.length];

export function CarbonSection(props: CarbonSectionProps) {
  const settingsRanges = SETTINGS_CONFIG.ranges;
  const schedule = props.carbonPriceSchedule;
  const scheduleActive = schedule.length > 0;
  const library = props.carbonLibrary;

  const [overlayIds, setOverlayIds] = useState<Set<string>>(new Set());
  const [compareMode, setCompareMode] = useState(false);
  // The selected/active scenario (loaded on the chart, edited, applied to the
  // run). null = scalar or an unsaved custom curve.
  const [editingId, setEditingId] = useState<string | null>(null);
  // The active scenario's schedule when it was selected — restored on Revert.
  const editBackup = useRef<CarbonPriceScheduleEntry[] | null>(null);
  // Result of the last "Apply to model" pre-check.
  const [applyResult, setApplyResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const toggleOverlay = (id: string) =>
    setOverlayIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  // Chart edits flow into the active schedule; while a scenario is selected,
  // they save straight back to it (live).
  const onScheduleChange = (next: CarbonPriceScheduleEntry[]) => {
    setApplyResult(null); // the run input changed — re-apply to re-confirm
    props.onCarbonPriceScheduleChange(next);
    if (editingId) {
      props.onCarbonLibraryChange(
        library.map((x) => (x.id === editingId ? { ...x, schedule: cloneSchedule(next) } : x)),
      );
    }
  };

  // Select a scenario: load it on the chart, bind it (edits save back), and
  // apply it to the run. Passing null clears to the scalar price.
  const selectScenario = (id: string | null) => {
    setApplyResult(null);
    if (id === null) {
      editBackup.current = null;
      setEditingId(null);
      props.onCarbonPriceScheduleChange([]);
      return;
    }
    const p = library.find((x) => x.id === id);
    if (!p) return;
    editBackup.current = cloneSchedule(p.schedule);
    setCompareMode(false);
    setEditingId(id);
    props.onCarbonPriceScheduleChange(cloneSchedule(p.schedule));
  };

  const saveCurrentAsNew = () => {
    const profile: CarbonScheduleProfile = {
      id: createCarbonProfileId(),
      name: `Schedule ${library.length + 1}`,
      schedule: cloneSchedule(schedule),
    };
    props.onCarbonLibraryChange([...library, profile]);
    editBackup.current = cloneSchedule(profile.schedule);
    setEditingId(profile.id); // continue editing the curve you just saved
  };

  // Discard edits made since the scenario was selected (stay on it).
  const revertActive = () => {
    if (!editingId) return;
    const original = editBackup.current ?? [];
    props.onCarbonLibraryChange(library.map((x) => (x.id === editingId ? { ...x, schedule: cloneSchedule(original) } : x)));
    props.onCarbonPriceScheduleChange(cloneSchedule(original));
  };

  const renameProfile = (id: string, name: string) =>
    props.onCarbonLibraryChange(library.map((x) => (x.id === id ? { ...x, name } : x)));
  const deleteProfile = (id: string) => {
    props.onCarbonLibraryChange(library.filter((x) => x.id !== id));
    if (editingId === id) { editBackup.current = null; setEditingId(null); props.onCarbonPriceScheduleChange([]); }
    setOverlayIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
  };

  const overlays = library.flatMap((p, i) =>
    overlayIds.has(p.id) ? [{ name: p.name, color: colorOf(i), schedule: p.schedule }] : [],
  );
  const editingName = editingId ? (library.find((p) => p.id === editingId)?.name ?? null) : null;
  const isCustom = !editingId && scheduleActive;

  // Explicit "Apply to model": pre-check the model (carbon pricing has no
  // effect without emitting generators / a co2_emissions column) and confirm
  // the selected carbon as the run's input. The pricing itself is applied in
  // the backend at solve; this is the validate-and-confirm gate.
  const applyToModel = () => {
    const { emittingGenerators, hasCo2Column, totalGenerators } = props.carbonCheck;
    if (!hasCo2Column) {
      setApplyResult({ ok: false, msg: 'Carriers have no co2_emissions column — add it (Model → carriers) so a carbon price has any effect.' });
      return;
    }
    if (emittingGenerators === 0) {
      setApplyResult({ ok: false, msg: 'No generator uses an emitting carrier (co2_emissions > 0) — the carbon price would not change the solve.' });
      return;
    }
    const what = scheduleActive
      ? `the ${editingName ? `“${editingName}” ` : ''}schedule (${schedule.length} point${schedule.length > 1 ? 's' : ''})`
      : `the scalar ${props.currencySymbol}${props.carbonPrice}/tCO₂`;
    setApplyResult({ ok: true, msg: `Applied — ${what} will price ${emittingGenerators} of ${totalGenerators} generators on the next run.` });
  };

  return (
    <section className="constraints-workspace-section">
      <header className="constraints-workspace-section-header">
        <h3>Carbon price</h3>
        <p>Added to each generator's marginal cost proportional to its carrier's <code>co2_emissions</code> factor. Use a schedule to ramp the price across years (pathway runs apply the price for each investment period; single-period runs use the snapshot timestamp's year).</p>
      </header>

      <div className="sg-setting-row">
        <label className="sg-setting-label" htmlFor="rs-carbon-price">
          Scalar price <span style={{ color: 'var(--muted)', fontSize: '0.78rem', marginLeft: 6 }}>(used when the schedule below is empty)</span>
        </label>
        <div className="sg-carbon-row">
          <span className="sg-carbon-sym">{props.currencySymbol}</span>
          <NumberDraftInput
            id="rs-carbon-price"
            className="sg-carbon-input"
            min={settingsRanges.carbonPrice.min}
            step={settingsRanges.carbonPrice.step}
            value={props.carbonPrice}
            disabled={scheduleActive}
            onCommit={props.onCarbonPriceChange}
          />
          <span className="sg-carbon-unit">/tCO₂</span>
        </div>
      </div>

      <div className="sg-setting-divider" />

      <div className="sg-setting-row">
        <label className="sg-setting-label">Schedule</label>
        <p className="sg-setting-hint" style={{ marginTop: 0 }}>
          Pick a scenario to edit & apply it; tick scenarios in the dropdown to overlay them for comparison. On the chart, drag a point to set its price, click empty space to add one, select a point to edit or delete it, and hover a saved curve to read its name &amp; value.
        </p>

        <div className="carbon-toolbar">
          <CarbonScenarioPicker
            library={library}
            activeId={editingId}
            isCustom={isCustom}
            overlayIds={overlayIds}
            colorOf={colorOf}
            onSelect={selectScenario}
            onToggleCompare={toggleOverlay}
            onRename={renameProfile}
            onDelete={deleteProfile}
            onNewFromCurrent={saveCurrentAsNew}
            canSaveNew={scheduleActive}
          />
          <button
            className="tb-btn sg-solver-btn"
            onClick={applyToModel}
            disabled={compareMode}
            title="Check the model is carbon-ready and use this carbon price for the run"
          >
            Apply to model
          </button>
          <button
            className={`tb-btn sg-solver-btn${compareMode ? '' : ' tb-btn--muted'}`}
            onClick={() => setCompareMode((v) => !v)}
            disabled={!compareMode && overlays.length === 0}
            title="Hide the editable curve and show only the ticked saved schedules"
          >
            {compareMode ? 'Back to editing' : 'Compare only'}
          </button>
        </div>
        {applyResult && (
          <p className={`carbon-apply-result${applyResult.ok ? ' is-ok' : ' is-warn'}`}>
            {applyResult.ok ? '✓ ' : '⚠ '}{applyResult.msg}
          </p>
        )}

        {editingName && !compareMode && (
          <p className="carbon-editing-note">
            Editing <b>{editingName}</b> — changes save to it automatically.{' '}
            <button type="button" className="carbon-editing-cancel" onClick={revertActive}>Revert changes</button>
          </p>
        )}
        {isCustom && !compareMode && (
          <p className="carbon-editing-note">
            Unsaved custom curve.{' '}
            <button type="button" className="carbon-editing-done" onClick={saveCurrentAsNew}>Save as new</button>
          </p>
        )}

        <CarbonScheduleChart
          schedule={schedule}
          onChange={onScheduleChange}
          currencySymbol={props.currencySymbol}
          scalarPrice={props.carbonPrice}
          overlays={overlays}
          compareMode={compareMode}
        />

        {scheduleActive && (
          <p className="sg-setting-hint">
            Each snapshot uses the most-recent entry whose year is ≤ the snapshot's year. Pathway runs use the investment-period year; single-period runs use the snapshot timestamp year.
          </p>
        )}
      </div>
    </section>
  );
}
