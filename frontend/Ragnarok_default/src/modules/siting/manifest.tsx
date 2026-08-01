/** Siting tab-module — where to build (location optimisation). */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const sitingModule: TabModuleDefinition = {
  id: 'Siting',
  label: 'Siting',
  hint: 'Where to build (location optimisation)',
  description:
    'Location optimisation for new capacity: candidate sites, resource layers, '
    + 'and built-capacity rings on the map. Reads the working model; never '
    + 'required to solve it.',
  // A map pin (where to build).
  icon: lineIcon(<>
    <path d="M10 17s-5-4.6-5-8.2a5 5 0 0 1 10 0C15 12.4 10 17 10 17Z" />
    <circle cx="10" cy="8.6" r="1.8" />
  </>),
  order: 80,
};
