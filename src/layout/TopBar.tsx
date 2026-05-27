import { RunResults, WorkspaceTab } from '../shared/types';

interface TopBarValidateResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

interface TopBarProps {
  runStatus: 'idle' | 'running' | 'done' | 'error';
  runElapsed: number;
  status: string;
  filename: string;
  displayResults: RunResults | null;
  validateResult: TopBarValidateResult | null;
  tab: WorkspaceTab;
  enabledModuleCount: number;
  onOpenRunDialog: () => void;
  onOpen: () => void;
  onClear: () => void;
  onCancelRun: () => void;
  onSelectTab: (tab: WorkspaceTab) => void;
}

export function TopBar({
  runStatus,
  runElapsed,
  status,
  filename,
  displayResults,
  validateResult,
  tab,
  enabledModuleCount,
  onOpenRunDialog,
  onOpen,
  onClear,
  onCancelRun,
  onSelectTab,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="topbar-brand">Ragnarok</span>
        <div className="topbar-divider" />
        <button
          className="run-button"
          onClick={onOpenRunDialog}
          disabled={runStatus === 'running'}
          title={runStatus === 'running' ? 'A run is already in progress' : undefined}
        >
          Run
        </button>
        <button className="tb-btn" onClick={onOpen}>Open</button>
        <button
          className="tb-btn tb-btn--muted"
          onClick={onClear}
          title="Remove the currently loaded model and start from an empty workbook"
        >
          Clear
        </button>
        <div className="topbar-divider" />
        <span className="topbar-file">{filename}</span>
        {displayResults && (
          <span className="topbar-run-meta">{displayResults.runMeta.snapshotCount} snaps · {displayResults.runMeta.snapshotWeight}h res</span>
        )}
        {runStatus === 'running' ? (
          <>
            <span className="topbar-running">
              <span className="topbar-spinner" />
              Running… {Math.floor(runElapsed / 60) > 0 ? `${Math.floor(runElapsed / 60)}m ` : ''}{(runElapsed % 60).toString().padStart(2, '0')}s
            </span>
            <button className="tb-btn tb-btn--muted topbar-cancel" onClick={onCancelRun}>Cancel</button>
          </>
        ) : (
          <span className="topbar-status" title={status}>{status}</span>
        )}
      </div>
      <nav className="tab-nav">
        {(['Model', 'Analytics'] as WorkspaceTab[]).map((item) => (
          <button
            key={item}
            className={`tab-button ${tab === item ? 'is-active' : ''}`}
            onClick={() => onSelectTab(item)}
          >
            {item}
            {item === 'Analytics' && validateResult && (
              <span className={`tab-badge ${validateResult.valid ? 'tab-badge--ok' : 'tab-badge--error'}`}>
                {validateResult.valid ? 'ok' : `${validateResult.errors.length + validateResult.warnings.length}`}
              </span>
            )}
          </button>
        ))}
        {enabledModuleCount > 0 && (
          <button
            className={`tab-button ${tab === 'Plugins' ? 'is-active' : ''}`}
            onClick={() => onSelectTab('Plugins')}
          >
            Plugins
            <span className="tab-badge tab-badge--ok">
              {enabledModuleCount}
            </span>
          </button>
        )}
      </nav>
    </header>
  );
}
