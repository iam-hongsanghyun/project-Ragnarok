/** Composites tab-module — multi-component assets (BESS, CCGT / OCGT, gas + H2 co-firing, Power-to-X) and how they connect. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const compositesModule: TabModuleDefinition = {
  id: 'Composites',
  label: 'Composites',
  hint: 'Multi-component assets: BESS, CCGT/OCGT, gas+H2 co-firing, Power-to-X',
  description:
    'Assets made of several PyPSA components: battery storage, CCGT / OCGT, gas + H2 co-firing and Power-to-X chains. '
    + 'Choose the buses and generators each one connects to, see a schematic and the PyPSA rows it creates, apply it to '
    + 'the working model, and read its results (starts, H2 share, CO2 avoided, LCOH, RFNBO compliance). The result is '
    + 'ordinary rows in the workbook; never required to solve it.',
  // Two boxes joined by a line: components linked into one asset.
  icon: lineIcon(<>
    <rect x="2.5" y="6.5" width="5" height="7" rx="1" />
    <rect x="12.5" y="6.5" width="5" height="7" rx="1" />
    <path d="M7.5 10h5" />
  </>),
  order: 25,
};
