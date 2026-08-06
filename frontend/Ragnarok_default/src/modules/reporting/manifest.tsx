/** Reporting tab-module — perspective-based report documents from stored runs. */
import React from 'react';
import { lineIcon } from 'shared/components/lineIcon';
import type { TabModuleDefinition } from '../types';

export const reportingModule: TabModuleDefinition = {
  id: 'Reporting',
  label: 'Reporting',
  hint: 'Perspective-based reports from stored runs',
  description:
    'Printable report documents assembled from stored solve runs, framed for '
    + 'an audience: policy maker, investor, PPA buyer, lender, procurement. '
    + 'Every figure reads from the stored run — deterministic, no AI.',
  // A report page: sheet with a headline and text lines.
  icon: lineIcon(<>
    <path d="M5.5 3h6.5l2.5 2.5V17h-9z" />
    <path d="M12 3v2.5h2.5" />
    <path d="M8 9h4.5" />
    <path d="M8 11.8h4.5" />
    <path d="M8 14.6h3" />
  </>),
  order: 90,
};
