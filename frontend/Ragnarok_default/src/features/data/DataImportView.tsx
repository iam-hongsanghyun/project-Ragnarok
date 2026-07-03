/**
 * Three-pane shell for the Data view's network-data importer.
 *
 *   left rail   ·   map (main)   ·   right rail
 *
 * Flow: Country → Databases (sources) → Datasets (multi-select).
 *
 *   1. Pick a country (click or search). Map zooms in.
 *   2. In the left rail TICK the datasets you want — across as many
 *      databases as you like (e.g. OSM transmission + WRI power plants).
 *   3. The right rail shows the settings for EVERY database with ticked
 *      datasets: one section per database (its Common group + a group per
 *      dataset). Each database keeps its own filter values — filter ids can
 *      collide across databases, so the blobs are never merged.
 *   4. One Fetch → one backend request per database, in parallel; the
 *      previews stack in the right rail and the overlays merge on the map.
 *   5. Add to workbook → every fetched fragment merges into the model.
 *
 * Caller (App) supplies `applyFragment` which merges sheets via
 * `mergeWorkbookFragment`.
 */
import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import {
  CountryMeta,
  Source,
  WorkbookFragment,
  GeoJSONFeatureCollection,
  fetchCountryBoundaries,
  listCountries,
  listSources,
} from 'lib/api/databases';
import { ResizablePanels } from '../../layout/ResizablePanels';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { CategoryDatabaseList } from './CategoryDatabaseList';
import { FilterPanel, SourceEntry } from './FilterPanel';
import { PypsaEarthPanel } from './PypsaEarthPanel';
import { WorldMap } from './WorldMap';
import { dataImportStore, runStatus, type Run } from 'lib/data/store';
import { oneClickStore } from 'lib/data/oneClickStore';

// Persistent state keys — selections stick across tab switches and reloads.
const KEY_COUNTRY = 'ragnarok:data-import:country-iso';
const KEY_SOURCE = 'ragnarok:data-import:source-id';
const KEY_SELECTION = 'ragnarok:data-import:selection-by-source';
const KEY_FILTERS = 'ragnarok:data-import:filters-by-source';

interface Props {
  applyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
}

/** The union of all a source's datasets' filters, de-duped by id (common
 *  settings appear once). This is the full settings surface for the source. */
function sourceFilterSchemas(source: Source) {
  const seen = new Set<string>();
  const out = [];
  for (const ds of source.datasets) {
    for (const f of ds.filters) {
      if (!seen.has(f.id)) {
        seen.add(f.id);
        out.push(f);
      }
    }
  }
  return out;
}

function defaultFilterValues(source: Source): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of sourceFilterSchemas(source)) {
    out[f.id] = f.default ?? (f.kind === 'multiselect' ? [] : f.kind === 'toggle' ? false : null);
  }
  return out;
}

/** Merge the ready parts' map overlays into one FeatureCollection. */
function mergeOverlays(overlays: Array<GeoJSONFeatureCollection | null | undefined>): GeoJSONFeatureCollection | null {
  const features = overlays.flatMap((o) => o?.features ?? []);
  if (features.length === 0) return null;
  return { type: 'FeatureCollection', features };
}

/** Stable fingerprint of a run's parts — identifies which selection produced it.
 *  Pure (depends only on `run`), so it lives at module scope and never needs to
 *  be an effect/memo dependency. */
function runKey(run: Run): string {
  return JSON.stringify(run.parts.map((p) => [p.sourceId, p.datasetIds, p.filtersJson]));
}

export function DataImportView({ applyFragment }: Props) {
  const [sources, setSources] = useState<Source[]>([]);
  // One-click build lives in a module store so its busy/result state survives
  // tab switches (the Data view unmounts when you navigate away).
  const oneClick = useSyncExternalStore(
    oneClickStore.subscribe,
    oneClickStore.get,
    oneClickStore.get,
  );
  const [countries, setCountries] = useState<CountryMeta[]>([]);
  const [countriesGeoJSON, setCountriesGeoJSON] = useState<GeoJSONFeatureCollection | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const [selectedIso, setSelectedIso] = usePersistedState<string | null>(KEY_COUNTRY, null);
  const [focusedSourceId, setFocusedSourceId] = usePersistedState<string | null>(KEY_SOURCE, null);
  // The PyPSA-Earth whole-country builder is focused in the left rail like a
  // source, but it's an async job — its panel replaces the right-rail settings.
  const [pypsaEarthFocused, setPypsaEarthFocused] = useState(false);
  // Which datasets are ticked, per source. Absent → default = none.
  const [selectionBySource, setSelectionBySource] = usePersistedState<Record<string, string[]>>(
    KEY_SELECTION,
    {},
  );
  // One filter blob PER SOURCE (shared across that source's datasets; never
  // merged across sources — ids like `min_capacity_mw` collide between them).
  const [filtersBySource, setFiltersBySource] = usePersistedState<
    Record<string, Record<string, unknown>>
  >(KEY_FILTERS, {});

  const activeRun = useSyncExternalStore(
    dataImportStore.subscribe,
    dataImportStore.get,
    dataImportStore.get,
  );
  const [lastAddedSeq, setLastAddedSeq] = useState<number | null>(null);

  // Bootstrap: sources + countries + GeoJSON in parallel on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [srcs, ctrs, gj] = await Promise.all([
          listSources(),
          listCountries(),
          fetchCountryBoundaries(),
        ]);
        if (cancelled) return;
        setSources(srcs);
        setCountries(ctrs);
        setCountriesGeoJSON(gj);
      } catch (exc) {
        if (cancelled) return;
        setBootstrapError(String(exc));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedCountry = useMemo(
    () => (selectedIso ? countries.find((c) => c.iso === selectedIso) || null : null),
    [countries, selectedIso],
  );

  const filterValuesFor = useCallback(
    (source: Source): Record<string, unknown> => {
      const saved = filtersBySource[source.source_id];
      return saved && Object.keys(saved).length > 0 ? saved : defaultFilterValues(source);
    },
    [filtersBySource],
  );

  // EVERY source with ticked datasets gets a settings section in the right
  // rail and a slice of the fetch — not just the last-clicked one. (That
  // single-focus behavior made e.g. OSM ticks silently inert once WRI was
  // ticked.)
  const entries: SourceEntry[] = useMemo(
    () =>
      sources
        .map((source) => ({
          source,
          datasetIds: selectionBySource[source.source_id] ?? [],
          values: filterValuesFor(source),
        }))
        .filter((entry) => entry.datasetIds.length > 0),
    [sources, selectionBySource, filterValuesFor],
  );

  const updateFilterValue = useCallback(
    (sourceId: string, filterId: string, value: unknown) => {
      const source = sources.find((s) => s.source_id === sourceId);
      if (!source) return;
      setFiltersBySource({
        ...filtersBySource,
        [sourceId]: { ...filterValuesFor(source), [filterId]: value },
      });
    },
    [sources, filtersBySource, filterValuesFor, setFiltersBySource],
  );

  const handleFocusSource = useCallback(
    (sourceId: string) => { setFocusedSourceId(sourceId); setPypsaEarthFocused(false); },
    [setFocusedSourceId],
  );

  const handleToggleDataset = useCallback(
    (sourceId: string, datasetId: string) => {
      setFocusedSourceId(sourceId);
      const src = sources.find((s) => s.source_id === sourceId);
      if (!src) return;
      const current = selectionBySource[sourceId] ?? [];
      const next = current.includes(datasetId)
        ? current.filter((id) => id !== datasetId)
        : [...current, datasetId];
      setSelectionBySource({ ...selectionBySource, [sourceId]: next });
    },
    [sources, selectionBySource, setSelectionBySource, setFocusedSourceId],
  );

  // The held run only counts if it matches the current country + every
  // source's dataset selection and filters; otherwise the right rail shows
  // fresh state. Keyed by the same per-part JSON the store records.
  const selectionKey = useMemo(
    () =>
      JSON.stringify(
        entries.map((e) => [
          e.source.source_id,
          [...e.datasetIds].sort(),
          JSON.stringify(e.values, Object.keys(e.values).sort()),
        ]),
      ),
    [entries],
  );
  const currentRun =
    activeRun &&
    activeRun.countryIso === selectedIso &&
    runKey(activeRun) ===
      JSON.stringify(
        entries.map((e) => [
          e.source.source_id,
          [...e.datasetIds].sort(),
          JSON.stringify(e.values, Object.keys(e.values).sort()),
        ]),
      )
      ? activeRun
      : null;

  const fetching = currentRun ? runStatus(currentRun) === 'fetching' : false;
  const readyParts = useMemo(
    () => (currentRun ? currentRun.parts.filter((p) => p.status === 'ready' && p.response) : []),
    [currentRun],
  );
  const errors = useMemo(
    () =>
      currentRun
        ? currentRun.parts
            .filter((p) => p.status === 'error' && p.error)
            .map((p) => `${p.sourceLabel}: ${p.error}`)
        : [],
    [currentRun],
  );
  const overlay = useMemo(
    () => mergeOverlays(readyParts.map((p) => p.preview?.overlay)),
    [readyParts],
  );

  // Country / selection / filter changes invalidate the held run.
  useEffect(() => {
    if (
      activeRun &&
      (activeRun.countryIso !== selectedIso || runKey(activeRun) !== selectionKey)
    ) {
      dataImportStore.clear();
      setLastAddedSeq(null);
    }
  }, [activeRun, selectedIso, selectionKey]);

  const handleSelectCountry = useCallback(
    (iso: string) => setSelectedIso(iso),
    [setSelectedIso],
  );

  const handleFetch = useCallback(() => {
    if (!selectedCountry || entries.length === 0) return;
    dataImportStore.start({
      countryIso: selectedCountry.iso,
      countryName: selectedCountry.name,
      parts: entries.map((e) => ({
        sourceId: e.source.source_id,
        sourceLabel: e.source.source_label,
        datasetIds: e.datasetIds,
        filters: e.values,
        requiresSecrets: Array.from(
          new Set(
            e.source.datasets
              .filter((ds) => e.datasetIds.includes(ds.id))
              .flatMap((ds) => ds.requires_secrets ?? []),
          ),
        ),
      })),
    });
    setLastAddedSeq(null);
  }, [selectedCountry, entries]);

  // Apply a finished one-click build as soon as the Data view is present to
  // receive it (it may have completed while the user was on another tab), then
  // return the store to idle so it applies exactly once.
  useEffect(() => {
    if (oneClick.status === 'ready' && oneClick.build) {
      applyFragment(
        oneClick.build.fragment,
        oneClick.build.label || 'One-click model',
        oneClick.countryName || '',
      );
      oneClickStore.consume();
    }
  }, [oneClick.status, oneClick.build, oneClick.countryName, applyFragment]);

  const handleApply = useCallback(() => {
    if (!currentRun || readyParts.length === 0 || !selectedCountry) return;
    for (const part of readyParts) {
      if (part.response) {
        applyFragment(part.response.fragment, part.sourceLabel, selectedCountry.name);
      }
    }
    setLastAddedSeq(currentRun.seq);
  }, [currentRun, readyParts, selectedCountry, applyFragment]);

  const lastAdded =
    lastAddedSeq !== null && currentRun && currentRun.seq === lastAddedSeq ? currentRun : null;

  if (bootstrapError) {
    return (
      <div className="view data-view">
        <div className="view-empty">
          <h3>Data import is unavailable</h3>
          <p>{bootstrapError}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="view data-view data-import-view">
      <ResizablePanels
        id="data-import"
        direction="horizontal"
        initialSizes={[20, 60, 20]}
        minSize={200}
        className="data-import-panels"
      >
        <CategoryDatabaseList
          sources={sources}
          selectedCountry={selectedCountry}
          focusedSourceId={focusedSourceId}
          selectionBySource={selectionBySource}
          onFocusSource={handleFocusSource}
          onToggleDataset={handleToggleDataset}
          onFocusPypsaEarth={() => { setPypsaEarthFocused(true); setFocusedSourceId(null); }}
          pypsaEarthFocused={pypsaEarthFocused}
        />
        <main className="view-main data-import-main">
          <WorldMap
            countriesGeoJSON={countriesGeoJSON}
            countries={countries}
            selectedIso={selectedIso}
            onSelect={handleSelectCountry}
            overlay={overlay}
          />
          {selectedCountry && (
            <div className="data-import-oneclick" role="group">
              <div>
                <b>One-click model</b> — assemble a runnable {selectedCountry.name} model from open,
                keyless data (OSM network + plants, WRI fleet, World Bank demand) in a single step.
              </div>
              <button
                type="button"
                className="primary-button"
                disabled={oneClick.status === 'building'}
                onClick={() => oneClickStore.start(selectedCountry.iso, selectedCountry.name)}
              >
                {oneClick.status === 'building'
                  ? `Building ${oneClick.countryName ?? ''} model…`
                  : `Build ${selectedCountry.name} model`}
              </button>
              {oneClick.status === 'error' && oneClick.error && (
                <span className="data-import-oneclick__err">{oneClick.error}</span>
              )}
            </div>
          )}
          {lastAdded && (
            <div className="data-import-banner" role="status">
              Added{' '}
              <b>{readyParts.map((p) => p.sourceLabel).join(', ')}</b> to the workbook for{' '}
              <b>{lastAdded.countryName}</b>. Switch to <b>Model</b> or <b>Build</b> to review.
            </div>
          )}
        </main>
        {pypsaEarthFocused ? (
          <PypsaEarthPanel
            selectedCountry={selectedCountry ? { iso: selectedCountry.iso, name: selectedCountry.name } : null}
            applyFragment={applyFragment}
          />
        ) : (
          <FilterPanel
            entries={entries}
            onChange={updateFilterValue}
            onFetch={handleFetch}
            onApply={handleApply}
            fetching={fetching}
            applying={false}
            parts={currentRun?.parts ?? null}
            canApply={!fetching && readyParts.length > 0}
            errors={errors}
          />
        )}
      </ResizablePanels>
    </div>
  );
}
