/**
 * Three-pane shell for the Data view's network-data importer.
 *
 *   left rail   ·   map (main)   ·   right rail
 *
 * Flow: Country → Database (source) → Datasets (multi-select).
 *
 *   1. Pick a country (click or search). Map zooms in.
 *   2. In the left rail pick a database (source) and TICK the datasets you
 *      want — KPG193 offers network / renewable capacity / demand profile /
 *      renewable profile (all on by default).
 *   3. The right rail shows the settings: a Common group (shared across the
 *      selected datasets) + a group per dataset for its own settings.
 *   4. One Fetch → the backend fetches the selected datasets together and
 *      returns one aligned, PyPSA-ready fragment → preview overlays the map.
 *   5. Add to workbook → fragment merges into the current model.
 *
 * Caller (App) supplies `applyFragment` which merges sheets via
 * `mergeWorkbookFragment`.
 */
import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import {
  CountryMeta,
  FilterSchema,
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
import { FilterPanel } from './FilterPanel';
import { WorldMap } from './WorldMap';
import { dataImportStore } from 'lib/data/store';

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
function sourceFilterSchemas(source: Source): FilterSchema[] {
  const seen = new Set<string>();
  const out: FilterSchema[] = [];
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

export function DataImportView({ applyFragment }: Props) {
  const [sources, setSources] = useState<Source[]>([]);
  const [countries, setCountries] = useState<CountryMeta[]>([]);
  const [countriesGeoJSON, setCountriesGeoJSON] = useState<GeoJSONFeatureCollection | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const [selectedIso, setSelectedIso] = usePersistedState<string | null>(KEY_COUNTRY, null);
  const [focusedSourceId, setFocusedSourceId] = usePersistedState<string | null>(KEY_SOURCE, null);
  // Which datasets are ticked, per source. Absent → default = all datasets.
  const [selectionBySource, setSelectionBySource] = usePersistedState<Record<string, string[]>>(
    KEY_SELECTION,
    {},
  );
  // One shared filter blob per source (settings are shared across its datasets).
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
  const focusedSource = useMemo(
    () => (focusedSourceId ? sources.find((s) => s.source_id === focusedSourceId) || null : null),
    [sources, focusedSourceId],
  );

  // Selected dataset ids for the focused source (default = none — the user
  // ticks the datasets they want to fetch).
  const selectedDatasetIds = useMemo(() => {
    if (!focusedSource) return [] as string[];
    return selectionBySource[focusedSource.source_id] ?? [];
  }, [focusedSource, selectionBySource]);

  // Shared filter blob for the focused source.
  const filterValues = useMemo(() => {
    if (!focusedSource) return {} as Record<string, unknown>;
    const saved = filtersBySource[focusedSource.source_id];
    return saved && Object.keys(saved).length > 0 ? saved : defaultFilterValues(focusedSource);
  }, [filtersBySource, focusedSource]);

  // Union of API keys the selected datasets need.
  const requiresSecrets = useMemo(() => {
    if (!focusedSource) return [] as string[];
    const out = new Set<string>();
    for (const ds of focusedSource.datasets) {
      if (selectedDatasetIds.includes(ds.id)) {
        for (const s of ds.requires_secrets ?? []) out.add(s);
      }
    }
    return Array.from(out);
  }, [focusedSource, selectedDatasetIds]);

  const updateFilterValue = useCallback(
    (filterId: string, value: unknown) => {
      if (!focusedSource) return;
      setFiltersBySource({
        ...filtersBySource,
        [focusedSource.source_id]: { ...filterValues, [filterId]: value },
      });
    },
    [filtersBySource, filterValues, focusedSource, setFiltersBySource],
  );

  const handleFocusSource = useCallback(
    (sourceId: string) => setFocusedSourceId(sourceId),
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

  // The held run only counts if it matches the current source / country /
  // dataset selection / filters; otherwise the right rail shows fresh state.
  const selectionJson = useMemo(
    () => JSON.stringify([...selectedDatasetIds].sort()),
    [selectedDatasetIds],
  );
  const filtersJson = useMemo(
    () => JSON.stringify(filterValues, Object.keys(filterValues).sort()),
    [filterValues],
  );
  const currentRun =
    activeRun &&
    activeRun.sourceId === focusedSourceId &&
    activeRun.countryIso === selectedIso &&
    activeRun.datasetIdsJson === selectionJson
      ? activeRun
      : null;
  const preview = currentRun?.preview || null;
  const fetching = currentRun?.status === 'fetching';
  const error = currentRun?.status === 'error' ? currentRun.error : null;

  // Source / dataset / filter changes invalidate the held run.
  useEffect(() => {
    if (!focusedSource) return;
    if (
      activeRun &&
      (activeRun.sourceId !== focusedSourceId ||
        activeRun.countryIso !== selectedIso ||
        activeRun.datasetIdsJson !== selectionJson ||
        activeRun.filtersJson !== filtersJson)
    ) {
      dataImportStore.clear();
      setLastAddedSeq(null);
    }
  }, [activeRun, focusedSource, focusedSourceId, selectedIso, selectionJson, filtersJson]);

  const handleSelectCountry = useCallback(
    (iso: string) => setSelectedIso(iso),
    [setSelectedIso],
  );

  const handleFetch = useCallback(() => {
    if (!focusedSource || !selectedCountry || selectedDatasetIds.length === 0) return;
    dataImportStore.start({
      sourceId: focusedSource.source_id,
      sourceLabel: focusedSource.source_label,
      datasetIds: selectedDatasetIds,
      countryIso: selectedCountry.iso,
      countryName: selectedCountry.name,
      filters: filterValues,
      requiresSecrets,
    });
    setLastAddedSeq(null);
  }, [focusedSource, selectedCountry, selectedDatasetIds, filterValues, requiresSecrets]);

  const handleApply = useCallback(() => {
    if (!currentRun || currentRun.status !== 'ready' || !currentRun.response) return;
    if (!focusedSource || !selectedCountry) return;
    applyFragment(currentRun.response.fragment, focusedSource.source_label, selectedCountry.name);
    setLastAddedSeq(currentRun.seq);
  }, [currentRun, focusedSource, selectedCountry, applyFragment]);

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
        />
        <main className="view-main data-import-main">
          <WorldMap
            countriesGeoJSON={countriesGeoJSON}
            countries={countries}
            selectedIso={selectedIso}
            onSelect={handleSelectCountry}
            overlay={preview?.overlay || null}
          />
          {lastAdded && (
            <div className="data-import-banner" role="status">
              Added <b>{lastAdded.sourceLabel}</b> to the workbook for{' '}
              <b>{lastAdded.countryName}</b>. Switch to <b>Model</b> or <b>Build</b> to review.
            </div>
          )}
        </main>
        <FilterPanel
          source={focusedSource}
          selectedDatasetIds={selectedDatasetIds}
          values={filterValues}
          onChange={updateFilterValue}
          onFetch={handleFetch}
          onApply={handleApply}
          fetching={fetching}
          applying={false}
          preview={preview}
          canApply={currentRun?.status === 'ready'}
          error={error}
        />
      </ResizablePanels>
    </div>
  );
}
