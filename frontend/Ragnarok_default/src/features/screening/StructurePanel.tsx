/**
 * Region structure — does spreading across regions buy diversification?
 *
 * `/regions/structure` returns the distribution of pairwise site correlations within each
 * region and across each region pair (box plot, interactive: hover for the five numbers,
 * the mean and the correlation of the two aggregated region series), the pooled means and
 * their gap, and for each site its correlation with its own region (leave-one-out) and the
 * other regions; sites that behave more like another region are flagged. It needs the
 * sites, so it reads a site dataset (not an uploaded region series).
 */
import React, { useMemo, useState } from 'react';
import { ScreenParams, StructureResponse, fetchStructure } from 'lib/api/screening';
import type { ChartTheme } from 'lib/charts/theme';
import { buildWithinBetweenOption, fmt } from 'lib/screening/screening';
import { useAsync } from '../../shared/hooks/useAsync';
import { ChartPanel } from './ChartPanel';

interface Props {
  /** Site-dataset params (level `region` fields included); null = not available (say why in `unavailable`). */
  params: ScreenParams | null;
  /** Keep only sites of these region labels; undefined = all. */
  regions?: string[];
  unavailable: string | null;
  theme: ChartTheme;
}

export function StructurePanel({ params, regions, unavailable, theme }: Props) {
  const [oddOnly, setOddOnly] = useState(false);
  const st = useAsync<StructureResponse>(
    params ? `structure|${JSON.stringify([params, regions])}` : null,
    () => fetchStructure(params as ScreenParams, regions),
  );
  const option = useMemo(() => (st.data ? buildWithinBetweenOption(st.data, theme) : null), [st.data, theme]);
  const rows = useMemo(() => {
    if (!st.data) return [];
    const sv = st.data.siteVsRegion;
    const odd = new Set(sv.behavesLike.map((o) => o.site));
    return sv.sites.map((s) => ({ site: s, own: sv.regionOf[s], ownR: sv.own[s], best: sv.bestOther[s], odd: odd.has(s) }))
      .filter((r) => !oddOnly || r.odd);
  }, [st.data, oddOnly]);
  const sum = st.data?.summary;

  return (
    <div className="scr-card">
      <div className="scr-card-head">
        <h3>Within- vs between-region correlation</h3>
        <label className="scr-label">
          <input type="checkbox" checked={oddOnly} onChange={(e) => setOddOnly(e.target.checked)} /> Only sites that behave like another region
        </label>
      </div>
      {unavailable && <p className="scr-hint">{unavailable}</p>}
      {params && (
        <>
          <ChartPanel option={option} loading={st.loading} error={st.error} emptyText="No structure yet." label="Within and between region correlation" tall />
          {sum && st.data && (
            <p className="scr-hint" data-testid="structure-summary">
              Sites of one region correlate by {fmt(sum.withinMean, 2)} on average (median {fmt(sum.withinMedian, 2)}, {sum.nWithinPairs} pairs);
              sites of different regions by {fmt(sum.betweenMean, 2)} (median {fmt(sum.betweenMedian, 2)}, {sum.nBetweenPairs} pairs).
              Gap {fmt(sum.gain, 2)}: {sum.gain !== null && sum.gain > 0.2
                ? 'region borders carry information, so spreading capacity across regions buys diversification.'
                : 'region borders say little about co-movement, so spreading across regions buys little by itself.'}
              {' '}{st.data.nObs.toLocaleString()} observations, {st.data.nSites} sites. Diamonds mark the correlation of the aggregated region series,
              higher than the pair mean because averaging sites removes their local noise.
            </p>
          )}
          {st.data?.warnings.map((w) => <p key={w} className="scr-warn">{w}</p>)}
          {st.data && (
            <div className="scr-table-scroll">
              <table className="data-table" data-testid="site-vs-region-table">
                <thead>
                  <tr><th>Site</th><th>Region</th><th>r with own region</th><th>Closest other region</th><th>r with it</th><th>Behaves like</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.site} className={r.odd ? 'scr-row-focus' : undefined}>
                      <td>{r.site}</td><td>{r.own}</td>
                      <td className="scr-num">{fmt(r.ownR, 2)}</td>
                      <td>{r.best?.region ?? ''}</td><td className="scr-num">{fmt(r.best?.r ?? null, 2)}</td>
                      <td>{r.odd ? r.best?.region : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {st.data && (
            <p className="scr-hint">
              Own-region correlation leaves the site out of its region series, so a site is not compared with itself.
              A site behaves like another region when its closest other region beats its own
              ({st.data.siteVsRegion.behavesLike.length} of {st.data.siteVsRegion.sites.length}).
            </p>
          )}
        </>
      )}
    </div>
  );
}
