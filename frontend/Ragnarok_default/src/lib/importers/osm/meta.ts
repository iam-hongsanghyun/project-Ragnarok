/** OSM importer metadata — same JSON the right-rail FilterPanel consumes. */
import type { DatabaseMeta } from 'lib/api/databases';

export const osmMeta: DatabaseMeta = {
  id: 'osm',
  name: 'OpenStreetMap (Overpass)',
  category: 'transmission',
  subcategory: 'Live grid topology',
  license: 'ODbL',
  homepage: 'https://www.openstreetmap.org',
  version_hint: 'live',
  description:
    'Power infrastructure tagged in OpenStreetMap (power=line / cable / substation). Voltage thresholds are user-tunable; output lands as buses + lines + transformers.',
  targets: ['buses', 'lines', 'transformers'],
  available: true,
  country_coverage: 'global',
  filters: [
    {
      id: 'min_voltage_kv',
      label: 'Min voltage',
      kind: 'number',
      default: 110,
      min: 1,
      max: 1500,
      step: 10,
      unit: 'kV',
    },
    {
      id: 'include_cables',
      label: 'Include cables',
      kind: 'toggle',
      default: true,
      description: 'Underground cables in addition to overhead lines.',
    },
    {
      id: 'include_dc',
      label: 'Include HVDC',
      kind: 'toggle',
      default: true,
    },
    {
      id: 'topology_style',
      label: 'Topology preset',
      kind: 'select',
      default: 'raw',
      options: [
        { value: 'raw', label: 'Raw (preserve OSM as-is)' },
        { value: 'pypsa_earth', label: 'PyPSA-Earth style (full cleanup)' },
      ],
      description:
        '"Raw" keeps OSM verbatim — no merging, no clustering, no splitting; line endpoints snap to a substation within 5 km otherwise a synthetic endpoint bus is created. "PyPSA-Earth style" turns ON every cleanup step below. Uncheck individual steps to opt out within the preset.',
    },
    // Fine-grained cleanup toggles. Apply ON TOP OF `topology_style = pypsa_earth`.
    // When `topology_style = raw`, all of these are ignored.
    {
      id: 'merge_fragments',
      label: 'Merge OSM fragments by shared node',
      kind: 'toggle',
      default: true,
      description:
        'Stitch OSM ways that share an endpoint node into a single logical line. Off → one row per OSM way.',
    },
    {
      id: 'cluster_substations',
      label: 'Cluster nearby substations into stations',
      kind: 'toggle',
      default: true,
      description:
        'DBSCAN-cluster substations within "Cluster radius" → one station_id per cluster, one bus per (station, voltage).',
    },
    {
      id: 'cluster_eps_km',
      label: 'Cluster radius',
      kind: 'number',
      default: 5,
      min: 0,
      step: 0.5,
      unit: 'km',
      description:
        'Two OSM substations within this distance collapse to the same station. Only used when "Cluster nearby substations" is on.',
    },
    {
      id: 'add_line_endings',
      label: 'Synthesize endpoint substations',
      kind: 'toggle',
      default: true,
      description:
        'Create a substation at every line endpoint that doesn\'t fall near a real one.',
    },
    {
      id: 'snap_endpoints',
      label: 'Snap line endpoints to nearest bus (no cap)',
      kind: 'toggle',
      default: true,
      description:
        'Force every line endpoint to its nearest cluster bus, with no distance ceiling. Off → 5 km cap.',
    },
    {
      id: 'split_at_substations',
      label: 'Split lines at intermediate substations',
      kind: 'toggle',
      default: true,
      description:
        'When a line passes near a substation operating at the same voltage, break the line there. Off → through-lines stay unsplit.',
    },
    {
      id: 'split_tolerance_m',
      label: 'Split tolerance',
      kind: 'number',
      default: 100,
      min: 0,
      step: 10,
      unit: 'm',
      description:
        'A substation must lie within this distance of a line\'s path to trigger a split.',
    },
    {
      id: 'emit_transformers',
      label: 'Emit transformers at multi-voltage stations',
      kind: 'toggle',
      default: true,
      description:
        'Add a Transformer row between consecutive voltage levels at each station that has more than one voltage.',
    },
    {
      id: 'collapse_parallels',
      label: 'Collapse parallel lines by bus pair',
      kind: 'toggle',
      default: true,
      description:
        'Group all lines connecting the same (bus0, bus1, voltage) into one row with num_parallel = max. Off → keep every parallel circuit as a separate row.',
    },
  ],
};
