/** P2X tab-module — power-to-X use-case surface (hydrogen, ammonia, methanol, e-fuels). */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const p2xModule: TabModuleDefinition = {
  id: 'P2X',
  label: 'P2X',
  hint: 'Power-to-X chains, LCOH and RFNBO matching',
  description:
    'Power-to-X use cases built into the core model: electrolyser, H2 storage, ammonia, '
    + 'methanol and e-fuel chains from catalogued technology data, RFNBO hourly or monthly '
    + 'matching, and results read as LCOH, LCOA and LCOM with a cost waterfall. Builds ordinary '
    + 'components into the working model; never required to solve it.',
  // A droplet over a flame-less bar: H2 molecule (two joined circles).
  icon: lineIcon(<>
    <circle cx="7" cy="10" r="3.2" />
    <circle cx="13" cy="10" r="3.2" />
    <path d="M10 6.6v6.8" />
  </>),
  order: 75,
};
