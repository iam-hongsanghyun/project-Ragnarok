/**
 * Map overlay: text search for the country picker. Top-right of the map.
 *
 * Substring match on country name + ISO. Results show below the box;
 * selecting one fires the same `onSelect` the GeoJSON click path uses.
 */
import React, { useMemo, useState } from 'react';
import { CountryMeta } from '../../shared/api/databases';

interface Props {
  countries: CountryMeta[];
  selectedIso: string | null;
  onSelect: (iso: string) => void;
}

const MAX_RESULTS = 8;

export function CountrySearch({ countries, selectedIso, onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [focused, setFocused] = useState(false);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return countries
      .filter((c) => c.name.toLowerCase().includes(q) || c.iso.toLowerCase().includes(q))
      .slice(0, MAX_RESULTS);
  }, [countries, query]);

  const selected = selectedIso
    ? countries.find((c) => c.iso === selectedIso) || null
    : null;

  const showDropdown = focused && results.length > 0;

  return (
    <div className="data-import-search">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 120)}
        placeholder={selected ? `${selected.name} (${selected.iso})` : 'Search country…'}
        aria-label="Search country"
        className="data-import-search__input"
      />
      {showDropdown && (
        <ul className="data-import-search__results" role="listbox">
          {results.map((c) => (
            <li key={c.iso}>
              <button
                type="button"
                className="data-import-search__option"
                onMouseDown={(e) => {
                  e.preventDefault();
                  onSelect(c.iso);
                  setQuery('');
                }}
              >
                <span className="data-import-search__name">{c.name}</span>
                <span className="data-import-search__iso">{c.iso}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
