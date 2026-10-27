import { describe, it, expect } from '@jest/globals';
import { splitOutputLayout } from './layout';

describe('splitOutputLayout', () => {
  it('arranges named keys into rows and leaves the rest, without the layout key', () => {
    const out = splitOutputLayout({
      prices: 1,
      volumes: 2,
      summary: 3,
      extra: 4,
      layout: { rows: [['prices', 'volumes'], ['summary']] },
    });
    expect(out.rows).toEqual([['prices', 'volumes'], ['summary']]);
    expect(out.rest).toEqual({ extra: 4 });
  });

  it('drops unknown/duplicate keys and empty rows', () => {
    const out = splitOutputLayout({ a: 1, b: 2, layout: { rows: [['a', 'zzz'], ['zzz'], ['a', 'b']] } });
    expect(out.rows).toEqual([['a'], ['b']]);
    expect(out.rest).toEqual({});
  });

  it('degrades to the plain flow on a malformed layout', () => {
    expect(splitOutputLayout({ a: 1, layout: 'nope' })).toEqual({ rows: [], rest: { a: 1 } });
    expect(splitOutputLayout({ a: 1 })).toEqual({ rows: [], rest: { a: 1 } });
  });
});
