/**
 * Three-pane shell for the Data view's network-data importer.
 *
 *   left rail   ·   map (main)   ·   right rail
 *
 * Left rail = `CategoryDatabaseList`. Main = `WorldMap` with `CountrySearch`
 * overlaid. Right rail = `FilterPanel`. Flow per the plan:
 *
 *   1. Pick a country (click or search). Map zooms in.
 *   2. Pick a category, then a database from the left rail.
 *   3. Tweak filters in the right rail; Fetch → preview overlay on the map.
 *   4. Add to workbook → fragment merges into the current model.
 *   5. Pick another database and repeat (country stays selected).
 *
 * Caller (App) supplies the `applyFragment` callback that merges sheets via
 * `mergeWorkbookFragment` and re-derives the run state.
 */
import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import {
  CountryMeta,
  DatabaseMeta,
  WorkbookFragment,
  GeoJSONFeatureCollection,
  fetchCountryBoundaries,
  listCountries,
  listDatabases,
} from 'lib/api/databases';
import { ResizablePanels } from '../../layout/ResizablePanels';
import { usePersistedState } from 'shared/hooks/usePersistedState';
import { CategoryDatabaseList } from './CategoryDatabaseList';
import { FilterPanel } from './FilterPanel';
import { WorldMap } from './WorldMap';
import { dataImportStore } from 'lib/data/store';

// Persistent state keys — every selection the user can make sticks across
// tab switches and reloads. Transient state (preview / fetch error / spinner)
// is intentionally NOT persisted: those are re-derivable cheap, and stale
// values would mislead after a long absence.
const KEY_COUNTRY = 'ragnarok:data-import:country-iso';
const KEY_DATABASE = 'ragnarok:data-import:database-id';
const KEY_FILTERS = 'ragnarok:data-import:filters-by-db';

interface Props {
  applyFragment: (fragment: WorkbookFragment, databaseName: string, countryName: string) => void;
}

function defaultFilterValues(db: DatabaseMeta): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of db.filters) {
    out[f.id] = f.default ?? (f.kind === 'multiselect' ? [] : f.kind === 'toggle' ? false : null);
  }
  return out;
}

export function DataImportView({ applyFragment }: Props) {
  const [databases, setDatabases] = useState<DatabaseMeta[]>([]);
  const [countries, setCountries] = useState<CountryMeta[]>([]);
  const [countriesGeoJSON, setCountriesGeoJSON] = useState<GeoJSONFeatureCollection | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const [selectedIso, setSelectedIso] = usePersistedState<string | null>(KEY_COUNTRY, null);

  const [selectedDatabaseId, setSelectedDatabaseId] = usePersistedState<string | null>(
    KEY_DATABASE,
    null,
  );
  // One filter blob per database id so switching back to a previously-used
  // database restores the user's tuning. Defaults seed in via the effect
  // below for any database the user has not touched yet.
  const [filtersByDb, setFiltersByDb] = usePersistedState<Record<string, Record<string, unknown>>>(
    KEY_FILTERS,
    {},
  );

  // Per-fetch state lives in a module-scoped store (see dataImportStore.ts),
  // not React state, so it survives switching to Model/Build/etc. and back
  // — the in-flight fetch keeps running and the result lands in the store
  // whether or not this view is currently mounted.
  const activeRun = useSyncExternalStore(
    dataImportStore.subscribe,
    dataImportStore.get,
    dataImportStore.get,
  );
  // `lastAdded` is the only purely view-local signal — it just controls the
  // "Added X rows to the workbook" banner, which intentionally clears when
  // the user leaves and comes back.
  const [lastAddedSeq, setLastAddedSeq] = useState<number | null>(null);

  // The current store entry only counts if it matches the user's current
  // selection. Otherwise it's leftover from a different country/database
  // and the right rail should show fresh defaults.
  const currentRun =
    activeRun &&
    activeRun.databaseId === selectedDatabaseId &&
    activeRun.countryIso === selectedIso
      ? activeRun
      : null;
  const preview = currentRun?.preview || null;
  const fetching = currentRun?.status === 'fetching';
  const error = currentRun?.status === 'error' ? currentRun.error : null;

  // Bootstrap: load databases + countries + GeoJSON in parallel on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [dbs, ctrs, gj] = await Promise.all([
          listDatabases(),
          listCountries(),
          fetchCountryBoundaries(),
        ]);
        if (cancelled) return;
        setDatabases(dbs);
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
  const selectedDatabase = useMemo(
    () => (selectedDatabaseId ? databases.find((d) => d.id === selectedDatabaseId) || null : null),
    [databases, selectedDatabaseId],
  );

  // Filter blob for the currently selected database. Falls back to declared
  // defaults the first time the user picks a database; persisted writes go
  // through `updateFilterValue` below.
  const filterValues = useMemo(() => {
    if (!selectedDatabase) return {} as Record<string, unknown>;
    const saved = filtersByDb[selectedDatabase.id];
    return saved && Object.keys(saved).length > 0
      ? saved
      : defaultFilterValues(selectedDatabase);
  }, [filtersByDb, selectedDatabase]);

  const updateFilterValue = useCallback(
    (filterId: string, value: unknown) => {
      if (!selectedDatabase) return;
      setFiltersByDb({
        ...filtersByDb,
        [selectedDatabase.id]: { ...filterValues, [filterId]: value },
      });
    },
    [filtersByDb, filterValues, selectedDatabase, setFiltersByDb],
  );

  // Filter / selection changes invalidate the held run — the user must
  // re-fetch so preview + fragment stay in lockstep with what's in the
  // right rail.
  const filtersJson = useMemo(
    () => JSON.stringify(filterValues, Object.keys(filterValues).sort()),
    [filterValues],
  );
  useEffect(() => {
    // Skip while the bootstrap hasn't loaded the database metas yet:
    // during that brief window `selectedDatabase` is null and
    // `filterValues` collapses to `{}`, which would spuriously not-match
    // the active run's real `filtersJson` and clear an in-flight fetch
    // right when the user comes back from another tab.
    if (!selectedDatabase) return;
    if (
      activeRun &&
      (activeRun.databaseId !== selectedDatabaseId ||
        activeRun.countryIso !== selectedIso ||
        activeRun.filtersJson !== filtersJson)
    ) {
      // The user has moved on — drop the stale run so the UI doesn't show
      // numbers belonging to a previous filter blob.
      dataImportStore.clear();
      setLastAddedSeq(null);
    }
  }, [activeRun, selectedDatabase, selectedDatabaseId, selectedIso, filtersJson]);

  const handleSelectCountry = useCallback(
    (iso: string) => {
      setSelectedIso(iso);
    },
    [setSelectedIso],
  );

  // Kick off a fetch through the store. The store owns the Promise, so the
  // fetch survives a view unmount (e.g. user switches to Model and back).
  const handleFetch = useCallback(() => {
    if (!selectedDatabase || !selectedCountry) return;
    dataImportStore.start({
      databaseId: selectedDatabase.id,
      databaseName: selectedDatabase.name,
      countryIso: selectedCountry.iso,
      countryName: selectedCountry.name,
      filters: filterValues,
      requiresSecrets: selectedDatabase.requires_secrets,
    });
    setLastAddedSeq(null);
  }, [selectedDatabase, selectedCountry, filterValues]);

  // Apply is a pure-frontend merge — no network call.
  const handleApply = useCallback(() => {
    if (!currentRun || currentRun.status !== 'ready' || !currentRun.response) return;
    if (!selectedDatabase || !selectedCountry) return;
    applyFragment(
      currentRun.response.fragment,
      selectedDatabase.name,
      selectedCountry.name,
    );
    setLastAddedSeq(currentRun.seq);
  }, [currentRun, selectedDatabase, selectedCountry, applyFragment]);

  const lastAdded =
    lastAddedSeq !== null && currentRun && currentRun.seq === lastAddedSeq
      ? currentRun
      : null;

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
          databases={databases}
          selectedCountry={selectedCountry}
          selectedDatabaseId={selectedDatabaseId}
          onSelectDatabase={setSelectedDatabaseId}
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
              Added <b>{lastAdded.databaseName}</b> rows to the workbook for{' '}
              <b>{lastAdded.countryName}</b>. Switch to <b>Model</b> or <b>Build</b> to review.
            </div>
          )}
        </main>
        <FilterPanel
          database={selectedDatabase}
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
