/**
 * The validation report the upload step shows: errors, warnings, resolution, time-zone reading
 * and the per-site gap table; user-supplied site names are escaped by React, never injected.
 */
import React from 'react';
import { renderToStaticMarkup as staticMarkup } from 'react-dom/server';
import { describe, test, expect } from '@jest/globals';
import type { ValidationReport } from 'lib/api/screening';
import { ValidationReportView } from './UploadPanel';

const toMarkup = (el: React.ReactElement): string => staticMarkup(el);

const report: ValidationReport = {
  errors: [],
  warnings: ['1 site(s) have gaps (5 missing steps): 3 value(s) interpolated, 2 timestamp(s) dropped.'],
  resolution: { stepMinutes: 60, steps: 8760, start: '2019-01-01T00:00:00', end: '2019-12-31T23:00:00' },
  timestamps: { interpretation: 'read as UTC', unparseable: 0, rowsRead: 8760 },
  duplicates: { count: 2, resolution: 'averaged' },
  gaps: {
    sitesWithGaps: 1, missingStepsTotal: 5, policy: 'interpolate', maxInterpolatedSteps: 48, interpolatedValues: 3, rowsDropped: 2,
    bySite: { '<script>x</script>': { missingSteps: 5, runs: 2, longestRunSteps: 3, first: [{ from: '2019-03-01T04:00:00', steps: 3 }] } },
  },
  units: { outOfRange: [], basis: 'capacity factor 0-1' },
};

describe('ValidationReportView', () => {
  test('shows resolution, zone reading, duplicates, gaps and the gap table', () => {
    const html = toMarkup(<ValidationReportView report={report} />);
    expect(html).toContain('8,760 steps of 60 min');
    expect(html).toContain('read as UTC');
    expect(html).toContain('Duplicates: 2 (averaged)');
    expect(html).toContain('3 interpolated, 2 timestamp(s) dropped');
    expect(html).toContain('2019-03-01T04:00');
    expect(html).toContain('Valid.');
  });

  test('escapes site names and shows errors instead of "Valid."', () => {
    const bad: ValidationReport = { ...report, errors: ['S1: 4 value(s) outside the capacity-factor range 0-1'] };
    const html = toMarkup(<ValidationReportView report={bad} />);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('outside the capacity-factor range');
    expect(html).not.toContain('Valid.');
  });

  test('without a report it shows only the message', () => {
    expect(toMarkup(<ValidationReportView report={undefined} message="Could not read file" />)).toContain('Could not read file');
    expect(toMarkup(<ValidationReportView report={undefined} />)).toBe('');
  });
});
