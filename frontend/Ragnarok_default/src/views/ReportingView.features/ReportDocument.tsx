/**
 * ReportDocument — renders one assembled report payload as a paper document
 * or a slide sequence. Same DOM for both; `.report-doc--slides` restyles each
 * section as a 16:9-ish card. Printing is handled by the `@media print` rules
 * in `styles/_reporting.css`.
 */
import React from 'react';
import type { ReportDocumentPayload } from 'lib/reporting/types';
import { ReportBlockView } from './ReportBlocks';

function formatStamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

export function ReportDocument({
  doc,
  layout,
}: {
  doc: ReportDocumentPayload;
  layout: 'document' | 'slides';
}) {
  return (
    <article className={`report-doc report-doc--${layout}`}>
      <header className="report-cover">
        <p className="eyebrow">
          {doc.perspectiveLabel} · {doc.audience}
        </p>
        <h1>{doc.title}</h1>
        <p className="report-subtitle">{doc.subtitle}</p>
        <p className="report-meta">
          Run {doc.runName} · saved {formatStamp(doc.provenance.savedAt)} · report generated{' '}
          {formatStamp(doc.generatedAt)}
        </p>
      </header>

      {doc.sections.map((section) => (
        <section className="report-section" key={section.id}>
          <h2>{section.title}</h2>
          <p className="report-key-question">{section.keyQuestion}</p>
          {section.blocks.map((block, i) => (
            // Blocks are static payload data; index keys are stable here.
            // eslint-disable-next-line react/no-array-index-key
            <ReportBlockView key={i} block={block} />
          ))}
        </section>
      ))}

      <section className="report-section report-caveats">
        <h2>Assumptions and caveats</h2>
        <ul>
          {doc.caveats.map((caveat) => (
            <li key={caveat.slice(0, 48)}>{caveat}</li>
          ))}
        </ul>
        <p className="report-meta">{doc.provenance.note}</p>
      </section>
    </article>
  );
}
