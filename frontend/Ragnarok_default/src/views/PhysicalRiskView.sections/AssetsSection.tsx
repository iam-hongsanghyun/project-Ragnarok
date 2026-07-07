/**
 * Physical Risk — Assets sub-tab.
 *
 * Seeds a portfolio from the live Ragnarok model (one asset per generator /
 * storage unit with a located bus), then edits it in place. Only `value` and
 * `vulnerabilityClass` are editable in Phase 0 (per the shared contract);
 * every edit PUTs the full portfolio back to the session (server is the
 * source of truth, same convention as the workbook session).
 *
 * The portfolio itself is owned by `PhysicalRiskView` (shared with Results) —
 * this section only seeds it and patches individual assets.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NumberDraftInput } from '../../shared/components/NumberDraftInput';
import { SearchableSelect } from '../../shared/components/SearchableSelect';
import { useToast } from '../../shared/components/Toast';
import { DEFAULT_PHYSICAL_RISK_SESSION_ID, saveSession, seedFromModel } from 'lib/physicalRisk/api';
import { Asset, Libraries, Portfolio } from 'lib/physicalRisk/types';

// NumberDraftInput commits on every keystroke, so a full-portfolio PUT per
// character would flood the server and race out of order. Coalesce edits into a
// single trailing save.
const SAVE_DEBOUNCE_MS = 500;

interface Props {
  portfolio: Portfolio | null;
  onPortfolioChange: (portfolio: Portfolio | null) => void;
  libraries: Libraries | null;
}

export function AssetsSection({ portfolio, onPortfolioChange, libraries }: Props) {
  const { showToast } = useToast();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFleet = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await seedFromModel({ sessionId: DEFAULT_PHYSICAL_RISK_SESSION_ID });
      onPortfolioChange(p);
      showToast(`Loaded ${p.assets.length} asset(s) from the model`, 'success');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to seed the portfolio';
      setError(message);
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  }, [onPortfolioChange, showToast]);

  // Latest merged portfolio, updated synchronously on every edit so rapid
  // successive edits build on each other (no stale-closure last-writer-wins),
  // and the debounced save always sends the newest state.
  const latestRef = useRef<Portfolio | null>(portfolio);
  useEffect(() => { latestRef.current = portfolio; }, [portfolio]);
  const saveTimer = useRef<number | null>(null);

  const doSave = useCallback(() => {
    const p = latestRef.current;
    if (!p) return;
    void saveSession(p.sessionId, p).catch((err) => {
      const message = err instanceof Error ? err.message : 'Failed to save the portfolio';
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

  const patch = useCallback(
    (assetId: string, next: Partial<Asset>) => {
      const base = latestRef.current;
      if (!base) return;
      const assets = base.assets.map((a) => (a.id === assetId ? { ...a, ...next } : a));
      const updated = { ...base, assets };
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

  const vclassOptions = libraries?.vulnerabilityClasses.map((v) => ({ value: v.id, label: v.label })) ?? [];

  return (
    <div className="pane">
      <div className="pane-header">
        <div>
          <h2>Assets</h2>
          <p className="chart-card p">
            Facilities exposed to physical climate risk — seeded one-per generator and storage unit from
            the current model's bus locations.
          </p>
        </div>
        <button className="tb-btn tb-btn--primary" onClick={() => void loadFleet()} disabled={loading}>
          {loading ? 'Loading fleet…' : portfolio ? 'Reload fleet from model' : 'Load fleet'}
        </button>
      </div>

      {error && <p className="sg-error-text">{error}</p>}

      {!portfolio || portfolio.assets.length === 0 ? (
        <div className="analytics-empty">
          <h3>No assets loaded</h3>
          <p>
            Click "Load fleet" to seed a portfolio from the current model — one asset per generator or
            storage unit whose bus has lat/lon coordinates.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Carrier</th>
                <th>Lat</th>
                <th>Lon</th>
                <th>Value</th>
                <th>Vulnerability class</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.assets.map((asset) => (
                <tr key={asset.id}>
                  <td>{asset.name}</td>
                  <td>{asset.kind}</td>
                  <td>{asset.carrier || '—'}</td>
                  <td>{asset.lat.toFixed(4)}</td>
                  <td>{asset.lon.toFixed(4)}</td>
                  <td>
                    <NumberDraftInput
                      value={asset.value}
                      min={0}
                      onCommit={(v) => patch(asset.id, { value: v })}
                    />
                  </td>
                  <td>
                    <SearchableSelect
                      value={asset.vulnerabilityClass}
                      options={vclassOptions.length > 0 ? vclassOptions : [asset.vulnerabilityClass]}
                      onChange={(v) => patch(asset.id, { vulnerabilityClass: v })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
