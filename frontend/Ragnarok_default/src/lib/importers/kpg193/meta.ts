/**
 * KPG193 — Korean Power Grid 193-bus reference network.
 *
 * Source: https://github.com/agm-center/kpg-testgrid
 * Authoritative algorithm: util/build_kpg193_pypsa.py in simplePyPSA_KR.
 *
 * The fetch step DISCOVERS the available versions and renewable years
 * from the GitHub Contents API at request time — no hardcoded paths —
 * so as upstream adds new versions (kpg193_v2_0, …) or new renewable
 * snapshots (2023, 2024, …), they show up automatically. The user can
 * still pin a specific version / year via the filters below; the
 * default `latest` lets the discovery pick the newest available.
 */
import type { DatabaseMeta } from 'lib/api/databases';

export const kpg193Meta: DatabaseMeta = {
  id: 'kpg193',
  name: 'KPG193 — Korean reference grid (193-bus)',
  short_name: 'KPG193',
  category: 'transmission',
  subcategory: 'Reference network',
  license: 'See agm-center/kpg-testgrid (academic / research use)',
  homepage: 'https://github.com/agm-center/kpg-testgrid',
  version_hint: 'latest (discovered)',
  description:
    'Complete reference network for the Republic of Korea power system: 193 buses, ~360 transmission lines, ~300 thermal generators with cost + commitment parameters, per-bus renewable nameplate capacity (PV / wind / hydro), and DC links. Static single-trip import — drop into the workbook and run a least-cost dispatch right away. Versions and renewable-year snapshots are discovered from the repo at fetch time, so newer datasets appear without a code change.',
  targets: ['buses', 'generators', 'lines', 'transformers', 'links', 'loads', 'carriers'],
  available: true,
  country_coverage: ['KOR'],
  filters: [
    {
      id: 'version',
      label: 'Dataset version',
      kind: 'select',
      default: 'latest',
      options: [{ value: 'latest', label: 'latest (discover at fetch time)' }],
      description:
        'Which kpg193_v* directory in the repo to use. "latest" picks the highest-numbered version found in the repo via the GitHub Contents API; you can pin a specific value (e.g. "v1_5", "v2_0") to freeze. The preview note shows which version was actually used.',
    },
    {
      id: 'renewable_year',
      label: 'Renewable capacity year',
      kind: 'select',
      default: 'latest',
      options: [{ value: 'latest', label: 'latest (discover at fetch time)' }],
      description:
        'Which year of the renewables_capacity/{solar,wind,hydro}_generators_<year>.csv files to attach. "latest" picks the most recent year present in the chosen version directory; you can pin a year (e.g. "2022") to freeze.',
    },
    {
      id: 'include_renewables',
      label: 'Include renewable capacities (PV / wind / hydro)',
      kind: 'toggle',
      default: true,
      description:
        'Pull per-bus solar / wind / hydro nameplate capacity from the auxiliary CSVs and emit them as PyPSA Generator rows alongside the thermal fleet (which lives in the MATPOWER mpc.gen block).',
    },
    {
      id: 'include_dc_links',
      label: 'Include HVDC links',
      kind: 'toggle',
      default: true,
      description:
        'Convert mpc.dcline rows into PyPSA Link rows. p_min_pu = Pmin/Pmax (negative → bidirectional). Efficiency = 1 − loss1 (the piecewise-linear loss-per-MW term).',
    },
  ],
};
