/**
 * ModelIssue shape — split from `features/validation/useModelIssues.ts` so
 * lib code (build steps, exporters, etc.) can reference the shape without
 * pulling in React.
 *
 * The actual hook (`useModelIssues`) lives in
 * `features/validation/useModelIssues.ts` and re-exports this type for
 * back-compatibility.
 */

export interface ModelIssue {
  sheet: string;
  rowIndex: number;
  col?: string;
  severity: 'error' | 'warning';
  message: string;
}
