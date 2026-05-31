import { describe, it, expect } from '@jest/globals';
import { dslToSpecs, parseConstraintDsl } from './dsl';

describe('constraintDsl parser (mirrors backend)', () => {
  it('parses a carrier cap into a structured spec', () => {
    const specs = dslToSpecs('gen(coal) <= 1000');
    expect(specs).toHaveLength(1);
    expect(specs[0].lhs).toEqual([{ coef: 1, kind: 'gen', carrier: 'coal' }]);
    expect(specs[0].sense).toBe('<=');
    expect(specs[0].rhs).toEqual([{ coef: 1000, kind: 'const' }]);
  });

  it('parses signed multi-term and bare/cf atoms', () => {
    const [s] = dslToSpecs('gen(solar) + gen(wind) - 2*gen(gas) >= 5000');
    expect(s.lhs).toEqual([
      { coef: 1, kind: 'gen', carrier: 'solar' },
      { coef: 1, kind: 'gen', carrier: 'wind' },
      { coef: -2, kind: 'gen', carrier: 'gas' },
    ]);
    expect(dslToSpecs('cf(nuclear) <= 0.8')[0].lhs[0]).toEqual({ coef: 1, kind: 'cf', carrier: 'nuclear' });
    expect(dslToSpecs('load_shed <= 100')[0].lhs[0]).toEqual({ coef: 1, kind: 'load_shed' });
    expect(dslToSpecs('emissions <= 0.5 * gen')[0].rhs[0]).toEqual({ coef: 0.5, kind: 'gen' });
  });

  it('skips comments/blank lines and reports errors per line', () => {
    expect(dslToSpecs('gen(coal) <= 1000\n# comment\n\nload_shed <= 5')).toHaveLength(2);
    const results = parseConstraintDsl('gen(coal) 1000\nfoo(x) <= 1');
    expect(results[0].error).toMatch(/comparator/);
    expect(results[1].error).toMatch(/not a valid term/);
  });
});
