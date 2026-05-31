/** World Bank annual demand importer metadata. */
import type { DatabaseMeta } from '../../../../shared/api/databases';

export const worldbankDemandMeta: DatabaseMeta = {
  id: 'worldbank_demand',
  name: 'World Bank — annual electricity consumption',
  category: 'demand',
  subcategory: 'Annual aggregates',
  license: 'CC-BY 4.0',
  homepage: 'https://data.worldbank.org/indicator/EG.USE.ELEC.KH.PC',
  version_hint: 'live',
  description:
    'Annual electricity consumption per country derived from the World Bank Open Data API (EG.USE.ELEC.KH.PC × SP.POP.TOTL). Lands as one Load row at the selected year’s average power (MW), to be reconciled to a real bus afterwards. Multi-year series available in the preview.',
  targets: ['loads'],
  available: true,
  country_coverage: 'global',
  filters: [
    {
      id: 'year',
      label: 'Year',
      kind: 'number',
      default: 2014,
      min: 1971,
      max: 2024,
      step: 1,
      description: 'World Bank data lags by 2-3 years; older years are most complete.',
    },
    {
      id: 'load_name',
      label: 'Load name',
      kind: 'select',
      default: 'national_load',
      options: [
        { value: 'national_load', label: 'national_load' },
        { value: 'system_load', label: 'system_load' },
        { value: 'demand', label: 'demand' },
      ],
      description: 'Suffixed with the country ISO so multi-country runs do not collide.',
    },
  ],
};
