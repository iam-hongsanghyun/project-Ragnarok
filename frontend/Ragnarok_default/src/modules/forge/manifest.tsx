/** Forge tab-module — bulk shaping / transforms of the loaded model. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const forgeModule: TabModuleDefinition = {
  id: 'Forge',
  label: 'Forge',
  hint: 'Shape & transform data',
  description:
    'Model-level transforms: topology reduction (clustering), carrier capacity '
    + 'targets, snapshot retargeting, demand forecasts, renewable/hydro profile '
    + 'attachment, and query & edit. Each tool rewrites the working model '
    + 'through the core session.',
  // Sliders (bulk shaping / transforms of the data).
  icon: lineIcon(<>
    <path d="M4 6h7M15 6h1M4 14h1M9 14h7" />
    <circle cx="13" cy="6" r="1.8" />
    <circle cx="7" cy="14" r="1.8" />
  </>),
  order: 30,
};
