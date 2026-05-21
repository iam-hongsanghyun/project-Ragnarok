import React from 'react';

/**
 * Sentinel value placed in the selection array to represent "explicitly nothing
 * selected" — distinct from `[]` which means "All". Downstream code that filters
 * by Set membership (bus / carrier filters) naturally drops it because no real
 * asset, bus, or carrier is named `__none__`.
 */
const NONE_SENTINEL = '__none__';

/**
 * Multi-select pill row with three logical states:
 *   - `selected = []`                        → All selected
 *   - `selected = ['__none__']`              → Nothing selected (explicit)
 *   - `selected = ['a', 'b', ...]`           → Specific items selected
 *
 * The "All" pill is a toggle: click it while all are selected to deselect
 * everything, click again to re-select all. Individual pills behave like
 * before — clicking one while in "All" mode starts an "all except clicked"
 * selection; the last pill removed transitions to the explicit "none" state.
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
  const allSelected  = selected.length === 0;
  const noneSelected = selected.length === 1 && selected[0] === NONE_SENTINEL;

  const toggleAll = () => {
    onChange(allSelected ? [NONE_SENTINEL] : []);
  };

  const togglePill = (name: string) => {
    if (allSelected) {
      onChange(names.filter((n) => n !== name));   // "all except clicked"
    } else if (noneSelected) {
      onChange([name]);                            // start fresh from none
    } else if (selected.includes(name)) {
      const next = selected.filter((k) => k !== name);
      onChange(next.length === 0 ? [NONE_SENTINEL] : next);
    } else {
      onChange([...selected, name]);
    }
  };

  return (
    <div className="asset-pills">
      <button
        type="button"
        className={`asset-pill${allSelected ? ' asset-pill--active' : ''}`}
        onClick={toggleAll}
        title={allSelected ? 'Click to deselect all' : 'Click to select all'}
      >
        All
      </button>
      {names.map((name) => {
        const active = allSelected || (!noneSelected && selected.includes(name));
        return (
          <button
            key={name}
            type="button"
            className={`asset-pill${active ? ' asset-pill--active' : ''}`}
            onClick={() => togglePill(name)}
          >
            {name}
          </button>
        );
      })}
    </div>
  );
}
