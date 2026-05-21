import React from 'react';

/**
 * Multi-select pill row. Empty `selected` array = "All" (every name implicitly active).
 * Clicking "All" returns an empty selection; clicking any individual pill toggles it.
 * Clicking a single pill while "All" is active starts a selection that excludes only
 * the clicked pill (matches the legacy behaviour from UserDefinedChartCard).
 */
export function AssetPills({
  names,
  selected,
  onChange,
}: {
  names: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const allSelected = selected.length === 0;

  const toggle = (name: string) => {
    if (allSelected) {
      onChange(names.filter((n) => n !== name));
    } else if (selected.includes(name)) {
      const next = selected.filter((k) => k !== name);
      onChange(next);
    } else {
      onChange([...selected, name]);
    }
  };

  return (
    <div className="asset-pills">
      <button
        type="button"
        className={`asset-pill${allSelected ? ' asset-pill--active' : ''}`}
        onClick={() => onChange([])}
      >
        All
      </button>
      {names.map((name) => {
        const active = allSelected || selected.includes(name);
        return (
          <button
            key={name}
            type="button"
            className={`asset-pill${active ? ' asset-pill--active' : ''}`}
            onClick={() => toggle(name)}
          >
            {name}
          </button>
        );
      })}
    </div>
  );
}
