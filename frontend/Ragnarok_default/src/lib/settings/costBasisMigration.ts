/**
 * The one-off cost-basis migration notice (workbook schema 1 -> 2).
 *
 * Ragnarok's core hands cost columns to PyPSA unchanged: `capital_cost` is PyPSA's periodised cost per
 * modelled horizon and `overnight_cost` is annuitised by PyPSA itself. An older Ragnarok workbook held an
 * OVERNIGHT price in `capital_cost`, so the server moves it to `overnight_cost` once, when the workbook is
 * loaded. This turns the server's report into the text shown to the user.
 */
import type { CostBasisMigration } from 'lib/api/session';

const MAX_ROWS_SHOWN = 20;

function money(v: number): string {
  return Math.round(v).toLocaleString('en-US');
}

/** Human-readable summary of a migration report: what moved, at which rate, and what needs a look. */
export function formatCostBasisMigration(m: CostBasisMigration): string {
  const n = m.changedRows.length;
  const lines: string[] = [];
  lines.push(
    `This workbook was saved before Ragnarok handed costs to PyPSA unchanged. ${n} row(s) carried an overnight price `
    + 'in capital_cost, which PyPSA would now read as a per-horizon cost. They were moved once to PyPSA\'s '
    + 'overnight_cost (capital_cost set to 0), so the solve is unchanged: PyPSA annuitises overnight_cost '
    + 'with the row\'s discount_rate and lifetime and scales it by the modelled horizon.',
  );
  if (m.discountRate != null) {
    lines.push(`discount_rate written: ${(m.discountRate * 100).toFixed(2)} % (from ${m.discountRateSource || 'the project'}).`);
  }
  m.changedRows.slice(0, MAX_ROWS_SHOWN).forEach((r) => {
    const life = r.lifetimeDefaulted ? `${r.lifetime} y (was unset)` : r.lifetime != null ? `${r.lifetime} y` : 'not set';
    lines.push(`  ${r.sheet} / ${r.name}: overnight_cost ${money(r.overnight_cost)}, lifetime ${life}${r.extendable ? '' : ', fixed asset (reported, not optimised)'}`);
  });
  if (n > MAX_ROWS_SHOWN) lines.push(`  ... and ${n - MAX_ROWS_SHOWN} more.`);
  if (m.review.length > 0) {
    lines.push('Needs your review:');
    m.review.forEach((r) => lines.push(`  ${r.sheet} / ${r.name}: ${r.reason}`));
  }
  m.notes.forEach((note) => lines.push(note));
  return lines.join('\n');
}
