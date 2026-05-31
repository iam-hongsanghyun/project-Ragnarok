/**
 * Build wizard step registry.
 *
 * Each step owns one or more schema sheets. Steps appear in PyPSA dependency
 * order so the data referenced by later sheets (carriers, buses) is always
 * defined first. Build writes directly into the shared `WorkbookModel`; there
 * is no draft fork — switching to the Model tab shows the same data.
 */
import { WorkbookModel } from 'lib/types';
import { ModelIssue } from 'lib/validation/issue';
import { getComponentSchema } from 'lib/constants/pypsa_schema';

export interface BuildStep {
  id: string;
  label: string;
  /** Primary sheet edited on this step (used for the grid and detail pane). */
  primarySheet: string;
  /** Secondary sheets edited or summarised on this step. */
  extraSheets: string[];
  description: string;
  /** True once the user has supplied enough data to move on. */
  isComplete: (model: WorkbookModel) => boolean;
}

const hasRows = (model: WorkbookModel, sheet: string): boolean =>
  Array.isArray(model[sheet]) && model[sheet].length > 0;

const minRows = (model: WorkbookModel, sheet: string, n: number): boolean =>
  Array.isArray(model[sheet]) && model[sheet].length >= n;

export const BUILD_STEPS: BuildStep[] = [
  {
    id: 'network',
    label: 'Network',
    primarySheet: 'network',
    extraSheets: [],
    description: 'Project metadata: name, CRS, base year.',
    isComplete: (m) => hasRows(m, 'network'),
  },
  {
    id: 'carriers',
    label: 'Carriers',
    primarySheet: 'carriers',
    extraSheets: [],
    description: 'Energy carriers (electricity, gas, heat...) and their emission factors.',
    isComplete: (m) => hasRows(m, 'carriers'),
  },
  {
    id: 'buses',
    label: 'Buses',
    primarySheet: 'buses',
    extraSheets: [],
    description: 'Network nodes. Every generator, load and line attaches to a bus.',
    isComplete: (m) => hasRows(m, 'buses'),
  },
  {
    id: 'generators',
    label: 'Generators',
    primarySheet: 'generators',
    extraSheets: ['generators-p_max_pu'],
    description: 'Dispatchable and variable generation. Cost and capacity feed the optimisation directly.',
    isComplete: (m) => hasRows(m, 'generators'),
  },
  {
    id: 'loads',
    label: 'Loads',
    primarySheet: 'loads',
    extraSheets: ['loads-p_set'],
    description: 'Demand at each bus, either as a static p_set or a time-series profile.',
    isComplete: (m) => hasRows(m, 'loads'),
  },
  {
    id: 'storage',
    label: 'Storage',
    primarySheet: 'storage_units',
    extraSheets: ['stores'],
    description: 'Storage units and stores. Optional — skip if you have no storage.',
    isComplete: (m) => hasRows(m, 'storage_units') || hasRows(m, 'stores') || true,
  },
  {
    id: 'lines',
    label: 'Lines',
    primarySheet: 'lines',
    extraSheets: [],
    description: 'AC transmission lines between buses.',
    isComplete: (m) => hasRows(m, 'lines') || minRows(m, 'buses', 1),
  },
  {
    id: 'links',
    label: 'Links',
    primarySheet: 'links',
    extraSheets: ['transformers'],
    description: 'Controllable links (HVDC, converters) and transformers between buses.',
    isComplete: (m) => hasRows(m, 'links') || minRows(m, 'buses', 1),
  },
  {
    id: 'processes',
    label: 'Processes',
    primarySheet: 'processes',
    extraSheets: [],
    description: 'Sector-coupling conversion processes. Optional.',
    isComplete: () => true,
  },
  {
    id: 'constraints',
    label: 'Constraints',
    primarySheet: 'global_constraints',
    extraSheets: [],
    description: 'Global constraints (CO₂ caps, expansion limits). Edit details in the Constraints workspace.',
    isComplete: () => true,
  },
  {
    id: 'review',
    label: 'Review',
    primarySheet: 'network',
    extraSheets: [],
    description: 'Validate the model before solving.',
    isComplete: () => true,
  },
];

export function getStepIssues(step: BuildStep, issues: ModelIssue[]): ModelIssue[] {
  const sheets = new Set<string>([step.primarySheet, ...step.extraSheets]);
  return issues.filter((issue) => sheets.has(issue.sheet));
}

export function findStepByIndex(index: number): BuildStep | null {
  return BUILD_STEPS[index] ?? null;
}

/** Step is gated only by missing schema rows, not by validation severity. */
export function stepHasSchema(step: BuildStep): boolean {
  return getComponentSchema(step.primarySheet) != null;
}
