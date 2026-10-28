/** Screening tab-module — statistical pre-screen of sites and regions on historical series. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const screeningModule: TabModuleDefinition = {
  id: 'Screening',
  label: 'Screening',
  hint: 'Correlation and complementarity of sites and regions',
  description:
    'Statistical pre-screen of solar and wind sites and of regions on the historical '
    + 'series you upload: correlation, clustering, within- vs between-region structure, '
    + 'complementarity and portfolios. Nothing touches the model until you add sites.',
  // Two overlapping curves (co-movement).
  icon: lineIcon(<>
    <path d="M3 13c2-6 4-6 6-2s4 4 8-5" />
    <path d="M3 8c2 5 4 5 6 1s4-3 8 4" />
  </>),
  order: 85,
};
