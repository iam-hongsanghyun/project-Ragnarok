/** Training tab-module — guided, step-by-step tutorials. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const trainingModule: TabModuleDefinition = {
  id: 'Training',
  label: 'Training',
  hint: 'Guided step-by-step tutorials',
  description:
    'The guided course: interactive walkthroughs that drive the app tab-by-tab. '
    + 'Purely additive — switch it off for a lean expert workspace.',
  // An open book (guided, step-by-step walkthroughs).
  icon: lineIcon(<>
    <path d="M10 6.2C8.6 5 6.8 4.5 4 4.5v9.6c2.8 0 4.6.5 6 1.7 1.4-1.2 3.2-1.7 6-1.7V4.5c-2.8 0-4.6.5-6 1.7Z" />
    <path d="M10 6.2v9.6" />
  </>),
  order: 120,
};
