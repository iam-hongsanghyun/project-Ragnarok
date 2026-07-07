/**
 * Physical Risk view — native rebuild of the standalone `climaterisk` app as a
 * Ragnarok tab. Sub-tab shell only in Phase 0: Assets + Results are a working
 * end-to-end slice (seed a portfolio from the model, edit it, run + view
 * physical-risk analytics); the rest are placeholders for Phase 1.
 *
 * Mirrors AnalyticsView's shell (ViewPaneHeader + sub-tab nav + routed body),
 * using the `TopTab` primitive for the sub-tab strip.
 *
 * The portfolio + libraries are owned HERE (not per-section): a physical-risk
 * session id is a server-minted random UUID (unlike the workbook session's
 * fixed 'default' id), so Assets and Results must share the same live
 * `Portfolio` object rather than each guessing it independently. The session
 * id is persisted (`usePersistedState`) so it survives sub-tab navigation and
 * page reloads; `getSession` re-fetches the portfolio for a persisted id on
 * mount, failing silently (cleared) if that session no longer exists server-side.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ViewPaneHeader, TopTab, TopTabItem } from '../shared/components/primitives';
import { usePersistedState } from '../shared/hooks/usePersistedState';
import { useToast } from '../shared/components/Toast';
import { getLibraries, getRun, getSession, submitRun } from 'lib/physicalRisk/api';
import { Libraries, Portfolio, Run, Scenario } from 'lib/physicalRisk/types';
import { RUN_POLLING } from 'lib/constants';
import { AssetsSection } from './PhysicalRiskView.sections/AssetsSection';
import { ScenariosSection } from './PhysicalRiskView.sections/ScenariosSection';
import { VulnerabilitySection } from './PhysicalRiskView.sections/VulnerabilitySection';
import { ResultsSection } from './PhysicalRiskView.sections/ResultsSection';
import { MapSection } from './PhysicalRiskView.sections/MapSection';
import { AdaptationSection } from './PhysicalRiskView.sections/AdaptationSection';
import { FinanceSection } from './PhysicalRiskView.sections/FinanceSection';
import { SupplyChainSection } from './PhysicalRiskView.sections/SupplyChainSection';
import { ForecastSection } from './PhysicalRiskView.sections/ForecastSection';
import { MethodSection } from './PhysicalRiskView.sections/MethodSection';

export type PhysicalRiskSubTab =
  | 'Assets'
  | 'Scenarios'
  | 'Vulnerability'
  | 'Results'
  | 'Map'
  | 'Adaptation'
  | 'Finance'
  | 'SupplyChain'
  | 'Forecast'
  | 'Method';

const SUB_TABS: TopTabItem<PhysicalRiskSubTab>[] = [
  { id: 'Assets', label: 'Assets' },
  { id: 'Scenarios', label: 'Scenarios' },
  { id: 'Vulnerability', label: 'Vulnerability' },
  { id: 'Results', label: 'Results' },
  { id: 'Map', label: 'Map' },
  { id: 'Adaptation', label: 'Adaptation' },
  { id: 'Finance', label: 'Finance' },
  { id: 'SupplyChain', label: 'Supply chain' },
  { id: 'Forecast', label: 'Forecast' },
  { id: 'Method', label: 'Method' },
];

export interface PhysicalRiskViewProps {
  subTab: PhysicalRiskSubTab;
  onSubTabChange: (tab: PhysicalRiskSubTab) => void;
}

export function PhysicalRiskView({ subTab, onSubTabChange }: PhysicalRiskViewProps) {
  const { showToast } = useToast();
  const [lastSessionId, setLastSessionId] = usePersistedState<string | null>('ui:physical-risk-session-id', null);
  const [portfolio, setPortfolioState] = useState<Portfolio | null>(null);
  const [libraries, setLibraries] = useState<Libraries | null>(null);
  // Run state lives HERE, not in ResultsSection, so a computed result survives
  // switching to Assets and back; the poll is guarded by `aliveRef` so it never
  // fires setState after the whole tab unmounts.
  const [run, setRun] = useState<Run | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollTimer = useRef<number | null>(null);
  const aliveRef = useRef(true);

  // Keep the persisted session id in sync whenever the portfolio changes
  // (freshly seeded, or restored) so a reload/tab-switch can find it again.
  const setPortfolio = useCallback((next: Portfolio | null) => {
    setPortfolioState(next);
    setLastSessionId(next?.sessionId ?? null);
  }, [setLastSessionId]);

  useEffect(() => {
    let cancelled = false;
    void getLibraries().then((libs) => { if (!cancelled) setLibraries(libs); }).catch(() => { /* dropdowns fall back to free text */ });
    if (lastSessionId) {
      void getSession(lastSessionId)
        .then((p) => { if (!cancelled) setPortfolioState(p); })
        .catch(() => { if (!cancelled) setLastSessionId(null); }); // session expired server-side (process restart)
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    };
  }, []);

  const pollRun = useCallback((sessionId: string, runId: string) => {
    const poll = () => {
      void getRun(sessionId, runId)
        .then((r) => {
          if (!aliveRef.current) return;
          setRun(r);
          if (r.status === 'queued' || r.status === 'running') {
            pollTimer.current = window.setTimeout(poll, RUN_POLLING.runningDelayMs);
          } else if (r.status === 'error') {
            showToast(r.error ?? 'Physical risk run failed', 'error');
          }
        })
        .catch((err) => {
          if (!aliveRef.current) return;
          showToast(err instanceof Error ? err.message : 'Failed to poll the run', 'error');
        });
    };
    pollTimer.current = window.setTimeout(poll, RUN_POLLING.initialDelayMs);
  }, [showToast]);

  const runAnalysis = useCallback(async (perils: string[], scenario: Scenario) => {
    if (!portfolio) { showToast('Load the fleet on the Assets tab first', 'error'); return; }
    if (perils.length === 0) { showToast('Select at least one peril', 'error'); return; }
    if (pollTimer.current) window.clearTimeout(pollTimer.current); // cancel any prior poll
    setSubmitting(true);
    try {
      const queued = await submitRun(portfolio.sessionId, perils, scenario);
      if (!aliveRef.current) return;
      setRun(queued);
      pollRun(portfolio.sessionId, queued.id);
    } catch (err) {
      if (aliveRef.current) showToast(err instanceof Error ? err.message : 'Failed to submit the run', 'error');
    } finally {
      if (aliveRef.current) setSubmitting(false);
    }
  }, [portfolio, pollRun, showToast]);

  // Every ported sub-tab gets the same prop set (see PhysicalRiskSectionProps)
  // so new sections never require view plumbing changes.
  const sectionProps = { portfolio, onPortfolioChange: setPortfolio, libraries, run };

  return (
    <div className="analytics-view">
      <div className="analytics-view-main">
        <ViewPaneHeader variant="analytics">
          <TopTab items={SUB_TABS} active={subTab} onChange={onSubTabChange} ariaLabel="Physical Risk sub-tabs" />
        </ViewPaneHeader>

        {subTab === 'Assets' && (
          <AssetsSection portfolio={portfolio} onPortfolioChange={setPortfolio} libraries={libraries} />
        )}
        {subTab === 'Scenarios' && <ScenariosSection {...sectionProps} />}
        {subTab === 'Vulnerability' && <VulnerabilitySection {...sectionProps} />}
        {subTab === 'Results' && (
          <ResultsSection
            portfolio={portfolio}
            libraries={libraries}
            run={run}
            submitting={submitting}
            onRun={runAnalysis}
          />
        )}
        {subTab === 'Map' && <MapSection {...sectionProps} />}
        {subTab === 'Adaptation' && <AdaptationSection {...sectionProps} />}
        {subTab === 'Finance' && <FinanceSection {...sectionProps} />}
        {subTab === 'SupplyChain' && <SupplyChainSection {...sectionProps} />}
        {subTab === 'Forecast' && <ForecastSection {...sectionProps} />}
        {subTab === 'Method' && <MethodSection {...sectionProps} />}
      </div>
    </div>
  );
}
