/** Control-panel tab-module — switch constraints such as ramp limits off for a filtered set of components, values kept. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const controlPanelModule: TabModuleDefinition = {
  id: 'ControlPanel',
  label: 'Control Panel',
  hint: 'Switch constraints on and off by carrier or any column, values kept',
  description:
    'Switches for PyPSA constraints that are on when a value is stated: ramp limits, start-up / shut-down ramps, minimum '
    + 'up / down times, unit commitment, minimum load. Each rule selects rows by a column (carrier, or any other) and its '
    + 'values; switched off, the run solves without those attributes while the workbook keeps every value. Saved in the project.',
  // Two slider switches.
  icon: lineIcon(<>
    <rect x="3" y="4.5" width="14" height="4" rx="2" />
    <circle cx="13" cy="6.5" r="1.4" />
    <rect x="3" y="11.5" width="14" height="4" rx="2" />
    <circle cx="7" cy="13.5" r="1.4" />
  </>),
  order: 45,
};
