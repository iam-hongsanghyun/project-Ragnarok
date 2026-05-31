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
      label: 'Topology cleanup',
      kind: 'select',
      default: 'raw',
      options: [
        { value: 'raw', label: 'Raw (preserve OSM as-is)' },
        { value: 'pypsa_earth', label: 'PyPSA-Earth style (snap + split)' },
      ],
      description:
        '"Raw" keeps OSM tags verbatim, snaps line endpoints to a substation within 5 km, and leaves through-lines unsplit. "PyPSA-Earth style" clusters substations within 5 km (DBSCAN), forces every line endpoint to snap to its nearest cluster bus, and splits lines that cross intermediate substations — giving a connected, solvable network at the cost of editing OSM-reported geometry.',
    },
  ],
};
