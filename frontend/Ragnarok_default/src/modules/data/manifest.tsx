/** Data tab-module — import external data (APIs, starter packs, files). */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const dataModule: TabModuleDefinition = {
  id: 'Data',
  label: 'Data',
  hint: 'Import external data',
  description:
    'Import from public data sources (ENTSO-E, EIA, Open-Meteo, PyPSA-Earth, …) '
    + 'and assemble country starter packs. The core Open/Import Project file '
    + 'actions stay available without it.',
  // A database cylinder (external data import).
  icon: lineIcon(<>
    <ellipse cx="10" cy="5" rx="6" ry="2.4" />
    <path d="M4 5v10c0 1.3 2.7 2.4 6 2.4s6-1.1 6-2.4V5" />
    <path d="M4 10c0 1.3 2.7 2.4 6 2.4s6-1.1 6-2.4" />
  </>),
  order: 0,
};
