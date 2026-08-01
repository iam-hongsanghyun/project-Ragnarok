/** Post-analysis tab-module — decisions drawn from results (no re-solve). */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const postAnalysisModule: TabModuleDefinition = {
  id: 'PostAnalysis',
  label: 'Post-analysis',
  hint: 'Decisions from results (no re-solve)',
  description:
    'Tools that read a finished run without re-solving: decision use-cases, '
    + 'procurement strategy, company/ownership, merchant and bid-strategy '
    + 'analysis, PPA contracts.',
  // A lightbulb (decisions drawn from the results).
  icon: lineIcon(<>
    <path d="M10 3a5 5 0 0 0-3 9v2h6v-2a5 5 0 0 0-3-9Z" />
    <path d="M8 17h4M8.5 14.5h3" />
  </>),
  order: 90,
};
