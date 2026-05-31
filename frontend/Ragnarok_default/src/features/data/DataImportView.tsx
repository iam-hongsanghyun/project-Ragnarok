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
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CountryMeta,
  DatabaseMeta,
  FetchResponse,
  PreviewSummary,
  WorkbookFragment,
  GeoJSONFeatureCollection,
  fetchCountryBoundaries,
  fetchImport,
  listCountries,
  listDatabases,
  previewImport,
} from '../../shared/api/databases';
import { ResizablePanels } from '../../layout/ResizablePanels';
import { usePersistedState } from '../../shared/utils/usePersistedState';
import { CategoryDatabaseList } from './CategoryDatabaseList';
import { FilterPanel } from './FilterPanel';
import { WorldMap } from './WorldMap';

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

  const [preview, setPreview] = useState<PreviewSummary | null>(null);
  const [lastFetch, setLastFetch] = useState<FetchResponse | null>(null);
  const [fetching, setFetching] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  // Reset per-fetch state when the user changes country or database. These
  // are transient (cheap to re-derive on click) — persisting them would risk
  // showing stale numbers next to fresh filter values.
  useEffect(() => {
    setPreview(null);
    setLastFetch(null);
    setError(null);
  }, [selectedIso, selectedDatabaseId]);

  const handleSelectCountry = useCallback(
    (iso: string) => {
      setSelectedIso(iso);
    },
    [setSelectedIso],
  );

  const handleFetchPreview = useCallback(async () => {
    if (!selectedDatabase || !selectedCountry) return;
    setFetching(true);
    setError(null);
    try {
      const resp = await previewImport({
        databaseId: selectedDatabase.id,
        countryIso: selectedCountry.iso,
        filters: filterValues,
      });
      setPreview(resp.preview);
      // Drop any stale fetch — the user must re-run the full fetch.
      setLastFetch(null);
    } catch (exc) {
      setError(String(exc));
      setPreview(null);
    } finally {
      setFetching(false);
    }
  }, [selectedDatabase, selectedCountry, filterValues]);

  const handleApply = useCallback(async () => {
    if (!selectedDatabase || !selectedCountry) return;
    setApplying(true);
    setError(null);
    try {
      // Always re-fetch the full fragment at apply time so the preview's
      // filters/conversion options match the merged result exactly.
      const resp = await fetchImport({
        databaseId: selectedDatabase.id,
        countryIso: selectedCountry.iso,
        filters: filterValues,
      });
      setLastFetch(resp);
      applyFragment(resp.fragment, selectedDatabase.name, selectedCountry.name);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setApplying(false);
    }
  }, [selectedDatabase, selectedCountry, filterValues, applyFragment]);

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
          {lastFetch && (
            <div className="data-import-banner" role="status">
              Added <b>{lastFetch.database_id}</b> rows to the workbook for{' '}
              <b>{selectedCountry?.name}</b>. Switch to <b>Model</b> or <b>Build</b> to review.
            </div>
          )}
        </main>
        <FilterPanel
          database={selectedDatabase}
          values={filterValues}
          onChange={updateFilterValue}
          onFetch={handleFetchPreview}
          onApply={handleApply}
          fetching={fetching}
          applying={applying}
          preview={preview}
          error={error}
        />
      </ResizablePanels>
    </div>
  );
}
