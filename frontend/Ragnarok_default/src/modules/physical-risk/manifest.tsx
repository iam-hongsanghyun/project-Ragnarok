/** Physical Risk tab-module — climate exposure of the asset fleet. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const physicalRiskModule: TabModuleDefinition = {
  id: 'PhysicalRisk',
  label: 'Physical Risk',
  hint: 'Climate exposure & physical risk',
  description:
    'CLIMADA-based physical climate risk: hazard × exposure × vulnerability '
    + 'over the asset portfolio, adaptation cost-benefit, finance views, and '
    + 'the physical-risk → forced-outage coupling for runs. Owns its own '
    + 'backend worker and stores.',
  // A hazard triangle (climate exposure / physical risk).
  icon: lineIcon(<>
    <path d="M10 3.5 17 16H3Z" />
    <path d="M10 8v4" />
    <circle cx="10" cy="14.2" r="0.6" fill="currentColor" stroke="none" />
  </>),
  order: 70,
};
