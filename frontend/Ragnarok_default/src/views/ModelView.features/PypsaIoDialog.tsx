/**
 * PypsaIoDialog — PyPSA-native import and export (Model view -> toolbar -> More formats -> PyPSA I/O).
 *
 * Import: PyPSA Excel, PyPSA CSV folder (zip), MATPOWER (.m / .mat) and pandapower (JSON). The backend converts the
 * file and answers the workbook without touching the session, so "Read file" is the preview: the dialog lists what the
 * import will create (rows per sheet) and the working model is replaced only when the user confirms. pandapower
 * builds an isolated environment on first use (HTTP 202); the dialog waits and retries by itself.
 * Which formats are offered comes from `GET /api/import/pypsa-io/capabilities`.
 * Export: PyPSA Excel and CSV (zip) of the working model, with the standard-types option when the backend has it.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  getPypsaIoCapabilities,
  postPypsaImport,
  summariseModel,
  type PypsaExportKind,
  type PypsaImportKind,
  type PypsaImportOptions,
  type PypsaIoCapabilities,
} from 'lib/api/pypsaIo';
import type { WorkbookModel } from 'lib/types';

export interface PypsaIoDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called on confirm with the converted workbook; the caller replaces the working model. */
  onImported: (model: WorkbookModel, filename: string) => void | Promise<void>;
  /** Download the working model; `options` is the export option block the backend reads. */
  onExport: (kind: PypsaExportKind, options: Record<string, unknown>) => void | Promise<void>;
  showToast: (message: string, kind?: 'success' | 'error' | 'info') => void;
}

const IMPORT_FORMATS: Array<{ kind: PypsaImportKind; label: string; accept: string; hint: string }> = [
  { kind: 'pypsa-excel', label: 'PyPSA Excel workbook', accept: '.xlsx,.xls', hint: 'A workbook written by Network.export_to_excel.' },
  { kind: 'pypsa-csv', label: 'PyPSA CSV folder (zip)', accept: '.zip', hint: 'A zip of a PyPSA CSV folder (buses.csv, generators.csv, ...).' },
  { kind: 'matpower', label: 'MATPOWER case', accept: '.m,.mat', hint: 'A MATPOWER .m or .mat case (bus, gen, branch, gencost).' },
  { kind: 'pandapower', label: 'pandapower net (JSON)', accept: '.json', hint: 'A pandapower net saved with pandapower.to_json.' },
];

interface Pending { model: WorkbookModel; filename: string; kind: PypsaImportKind }

function setupText(caps: PypsaIoCapabilities | null): string | null {
  if (!caps) return null;
  const s = caps.pandapowerSetup;
  if (s.state === 'ready') return null;
  if (s.state === 'setting_up') return `pandapower environment is being prepared${s.stage ? ` (${s.stage})` : ''}.`;
  if (s.state === 'failed') return `pandapower is unavailable: ${s.error ?? 'environment setup failed'}.`;
  if (s.state === 'disabled') return 'pandapower is unavailable: automatic environment setup is disabled.';
  return 'pandapower has not been set up yet; the first import builds an isolated environment (about a minute).';
}

function pandapowerBlocked(caps: PypsaIoCapabilities | null): boolean {
  const state = caps?.pandapowerSetup.state;
  return state === 'failed' || state === 'disabled';
}

export function PypsaIoDialog({ open, onClose, onImported, onExport, showToast }: PypsaIoDialogProps) {
  const [caps, setCaps] = useState<PypsaIoCapabilities | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [kind, setKind] = useState<PypsaImportKind>('pypsa-excel');
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<PypsaImportOptions>({});
  const [overwriteText, setOverwriteText] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [standardTypes, setStandardTypes] = useState(false);
  const retryTimer = useRef<number | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    if (!open) return undefined;
    cancelled.current = false;
    setCapsError(null);
    getPypsaIoCapabilities().then(setCaps).catch((e: unknown) => setCapsError(e instanceof Error ? e.message : 'Capabilities unavailable.'));
    return () => {
      cancelled.current = true;
      if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    };
  }, [open]);

  const importOffered = useCallback(
    (k: PypsaImportKind) => !!caps && caps.import.includes(k) && !(k === 'pandapower' && pandapowerBlocked(caps)),
    [caps],
  );

  const readFile = useCallback(async () => {
    if (!file) return;
    const sent: PypsaImportOptions = { ...options };
    if (kind === 'matpower') {
      const n = Number(overwriteText);
      sent.overwriteZeroSNom = overwriteText.trim() !== '' && Number.isFinite(n) ? n : undefined;
    }
    setError(null);
    setPending(null);
    const attempt = async (): Promise<void> => {
      retryTimer.current = null;
      setBusy(`Reading ${file.name}`);
      try {
        const outcome = await postPypsaImport(kind, file, sent);
        if (cancelled.current) return;
        if (outcome.status === 'setting_up') {
          setBusy(`${outcome.detail} Retrying in ${outcome.retryAfterSeconds} s.`);
          retryTimer.current = window.setTimeout(() => { void attempt(); }, outcome.retryAfterSeconds * 1000);
          return;
        }
        setPending({ model: outcome.model, filename: file.name, kind });
        setBusy(null);
      } catch (e) {
        if (cancelled.current) return;
        setError(e instanceof Error ? e.message : 'Import failed.');
        setBusy(null);
      }
    };
    await attempt();
  }, [file, kind, options, overwriteText]);

  const stopWaiting = () => {
    if (retryTimer.current !== null) window.clearTimeout(retryTimer.current);
    retryTimer.current = null;
    setBusy(null);
  };

  const confirmReplace = async () => {
    if (!pending) return;
    try {
      await onImported(pending.model, pending.filename);
      setPending(null);
      setFile(null);
      onClose();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Import failed.', 'error');
    }
  };

  const doExport = async (k: PypsaExportKind) => {
    const exportOptions: Record<string, unknown> = {};
    if (standardTypes) exportOptions.exportStandardTypes = true;
    await onExport(k, exportOptions);
  };

  if (!open) return null;

  const format = IMPORT_FORMATS.find((f) => f.kind === kind) ?? IMPORT_FORMATS[0];
  const summary = pending ? summariseModel(pending.model) : [];
  const setup = setupText(caps);
  const waiting = busy !== null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card pypsa-io-dialog" role="dialog" aria-label="PyPSA import and export" onClick={(e) => e.stopPropagation()}>
        <div className="validation-report">
          <div className="validation-report-header">
            <div>
              <p className="eyebrow">Model</p>
              <h2>PyPSA import and export</h2>
            </div>
            <button type="button" className="tb-btn tb-btn--muted" onClick={onClose}>Close</button>
          </div>
          {capsError && <p className="sg-setting-hint" role="alert">{capsError}</p>}

          <div className="validation-section">
            <p className="validation-section-title">Import</p>
            <div className="pypsa-io-row">
              <label className="sg-setting-label" htmlFor="pypsa-io-format">Format</label>
              <select
                id="pypsa-io-format"
                className="forge-adjust-select"
                value={kind}
                onChange={(e) => { setKind(e.target.value as PypsaImportKind); setFile(null); setPending(null); setError(null); }}
              >
                {IMPORT_FORMATS.map((f) => (
                  <option key={f.kind} value={f.kind} disabled={!importOffered(f.kind)}>{f.label}</option>
                ))}
              </select>
            </div>
            <p className="sg-setting-hint">{format.hint}</p>
            {kind === 'pandapower' && setup && <p className="sg-setting-hint">{setup}</p>}

            <div className="pypsa-io-row">
              <label className="sg-setting-label" htmlFor="pypsa-io-file">File</label>
              <input
                id="pypsa-io-file"
                type="file"
                accept={format.accept}
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPending(null); setError(null); }}
              />
            </div>

            {(kind === 'pypsa-excel' || kind === 'pypsa-csv') && (
              <label className="modal-check-row">
                <input type="checkbox" checked={!!options.skipTime} onChange={(e) => setOptions({ ...options, skipTime: e.target.checked })} />
                <span>Skip time series (static components only)</span>
              </label>
            )}
            {kind === 'matpower' && (
              <div className="pypsa-io-row">
                <label className="sg-setting-label" htmlFor="pypsa-io-snom">Overwrite zero s_nom</label>
                <input
                  id="pypsa-io-snom"
                  type="number"
                  className="forge-number"
                  min={0}
                  value={overwriteText}
                  onChange={(e) => setOverwriteText(e.target.value)}
                  placeholder="leave empty to keep"
                />
                <span className="sg-setting-hint">MVA given to branches whose rating is 0 (unlimited in MATPOWER).</span>
              </div>
            )}
            {kind === 'pandapower' && (
              <>
                <label className="modal-check-row">
                  <input type="checkbox" checked={!!options.extraLineData} onChange={(e) => setOptions({ ...options, extraLineData: e.target.checked })} />
                  <span>Keep extra line data (max_i_ka, df, parallel, ...)</span>
                </label>
                <label className="modal-check-row">
                  <input type="checkbox" checked={!!options.usePandapowerIndex} onChange={(e) => setOptions({ ...options, usePandapowerIndex: e.target.checked })} />
                  <span>Name components by their pandapower index</span>
                </label>
              </>
            )}

            <div className="master-dialog-row">
              <button type="button" className="tb-btn" disabled={!file || waiting || !importOffered(kind)} onClick={() => void readFile()}>
                Read file
              </button>
              {waiting && retryTimer.current !== null && (
                <button type="button" className="tb-btn tb-btn--muted" onClick={stopWaiting}>Stop waiting</button>
              )}
            </div>
            {busy && <p className="sg-setting-hint" role="status">{busy}</p>}
            {error && <p className="sg-setting-hint" role="alert">{error}</p>}

            {pending && (
              <div className="pypsa-io-preview" role="region" aria-label="Import preview">
                <p className="validation-section-title">This import will create</p>
                <table className="data-table">
                  <thead><tr><th>Sheet</th><th>Rows</th></tr></thead>
                  <tbody>
                    {summary.map((r) => (<tr key={r.sheet}><td>{r.sheet}</td><td>{r.rows}</td></tr>))}
                  </tbody>
                </table>
                <p className="sg-setting-hint">
                  Confirming replaces the working model (and its time series) with this one. Nothing has changed yet.
                </p>
                <div className="master-dialog-row">
                  <button type="button" className="primary-button" onClick={() => void confirmReplace()}>Replace working model</button>
                  <button type="button" className="tb-btn tb-btn--muted" onClick={() => setPending(null)}>Discard</button>
                </div>
              </div>
            )}
          </div>

          <div className="validation-section">
            <p className="validation-section-title">Export working model</p>
            {caps?.exportOptions.includes('exportStandardTypes') && (
              <label className="modal-check-row">
                <input type="checkbox" checked={standardTypes} onChange={(e) => setStandardTypes(e.target.checked)} />
                <span>Write PyPSA's standard line and transformer types into the file</span>
              </label>
            )}
            <div className="master-dialog-row">
              <button type="button" className="tb-btn" disabled={!caps?.export.includes('pypsa-excel')} onClick={() => void doExport('pypsa-excel')}>
                Export PyPSA Excel
              </button>
              <button type="button" className="tb-btn" disabled={!caps?.export.includes('pypsa-csv')} onClick={() => void doExport('pypsa-csv')}>
                Export PyPSA CSV (zip)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
