/**
 * AnnualBudgetsCard: each budget beside its horizon total, what the solve achieved, and binding / slack.
 */
import React from 'react';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { fetchRunAnnualBudgets, type AnnualBudgetRow } from 'lib/api/resultsDerived';
import { AnnualBudgetsCard } from './AnnualBudgetsCard';
import { mount, settle, type Mounted } from '../../../shared/testing/dom';

jest.mock('lib/api/resultsDerived');
const mockBudgets = jest.mocked(fetchRunAnnualBudgets);

const row = (over: Partial<AnnualBudgetRow>): AnnualBudgetRow => ({
  component: 'generators', name: 'wind', attribute: 'e_sum_min', annual: 1000, horizonYears: 1, value: 123.456789, scope: 'run',
  achieved: 130, achievedUnit: 'MWh', dual: null, binding: false, ...over,
});

let mounted: Mounted | null = null;
afterEach(async () => { await mounted?.unmount(); mounted = null; jest.resetAllMocks(); });

describe('AnnualBudgetsCard', () => {
  it('prints the budget, the PyPSA horizon total, the achieved value and the status', async () => {
    mockBudgets.mockResolvedValue({ run: 'r', total: 2, items: [row({}), row({ component: 'global_constraints', name: 'cap', attribute: 'constant', achieved: null, achievedUnit: 'not in the payload', binding: true, dual: -42 })] });
    mounted = await mount(<AnnualBudgetsCard runName="r" />);
    await settle();
    const rows = Array.from(mounted.container.querySelectorAll('tbody tr')).map((r) => Array.from(r.children).map((c) => c.textContent));
    expect(rows[0]).toEqual(['generators / wind', 'e_sum_min', '1,000', '123.457', '130 MWh', 'Slack', '—']);
    expect(rows[1].slice(4)).toEqual(['not reported', 'Binding', '-42']);
    expect(mockBudgets).toHaveBeenCalledWith('r');
  });

  it('handles no run, no budgets and a server error', async () => {
    mounted = await mount(<AnnualBudgetsCard />);
    expect(mounted.container.textContent).toContain('read back from a stored run');
    await mounted.unmount();
    mockBudgets.mockResolvedValueOnce({ run: 'r', total: 0, items: [] });
    mounted = await mount(<AnnualBudgetsCard runName="r" />);
    await settle();
    expect(mounted.container.textContent).toContain('applied no annual budgets');
    await mounted.unmount();
    mockBudgets.mockRejectedValueOnce(new Error('gone'));
    mounted = await mount(<AnnualBudgetsCard runName="r2" />);
    await settle();
    expect(mounted.container.querySelector('[role="alert"]')?.textContent).toContain('gone');
  });
});
