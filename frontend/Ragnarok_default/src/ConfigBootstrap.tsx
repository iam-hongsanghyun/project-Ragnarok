/**
 * Boot gate + progress screen.
 *
 * Runs before the rest of the app mounts. The flow mirrors what the
 * backend does on startup:
 *
 *   1. Poll ``GET /api/status`` every 500 ms.
 *      • fetch fails → backend not up yet → "Starting backend…"
 *        (indeterminate; the heavy `import pypsa` happens before the
 *        server binds its port, so this phase covers it).
 *      • status.ready === false → render the progress bar + per-step
 *        checklist of what the backend is building right now.
 *      • status.phase === 'error' → show the backend's error + Retry.
 *   2. Once ready, fetch ``GET /api/config`` once, apply the shared
 *      schema / standard-types into the live-binding constants, and
 *      render <App>.
 *
 * The whole sync is one-shot at startup — after <App> mounts, no further
 * status/config polling happens for the session.
 */
import React, { useEffect, useRef, useState } from 'react';

import {
  fetchStartupStatus,
  loadConfigBundle,
  type StartupStatus,
} from 'lib/api/config';
import {
  applyConfigBundle,
  type PypsaSchemaFile,
  type NetworkImportPolicyFile,
} from 'lib/constants/pypsa_schema';
import {
  applyStandardTypesBundle,
  type StandardTypesCatalogue,
} from 'lib/constants/pypsa_standard_types';

type Phase = 'connecting' | 'warming' | 'fetching_config' | 'ready' | 'error';

interface Props {
  children: React.ReactNode;
}

const POLL_INTERVAL_MS = 500;

export function ConfigBootstrap({ children }: Props) {
  const [phase, setPhase] = useState<Phase>('connecting');
  const [status, setStatus] = useState<StartupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    setPhase('connecting');
    setStatus(null);
    setError(null);

    const finish = async () => {
      setPhase('fetching_config');
      const bundle = await loadConfigBundle();
      if (cancelledRef.current) return;
      applyConfigBundle(
        bundle.schema as unknown as PypsaSchemaFile,
        bundle.network_import_policy as unknown as NetworkImportPolicyFile,
      );
      applyStandardTypesBundle(
        bundle.standard_types as unknown as StandardTypesCatalogue,
      );
      if (cancelledRef.current) return;
      setPhase('ready');
    };

    const poll = async () => {
      if (cancelledRef.current) return;
      try {
        const s = await fetchStartupStatus();
        if (cancelledRef.current) return;
        setStatus(s);
        if (s.phase === 'error') {
          setError(s.error || 'Backend reported a startup error.');
          setPhase('error');
          return;
        }
        if (s.ready) {
          try {
            await finish();
          } catch (exc) {
            if (cancelledRef.current) return;
            setError(String(exc));
            setPhase('error');
          }
          return;
        }
        // Not ready yet — keep showing the warm progress.
        setPhase('warming');
        setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        // Backend not reachable yet — keep trying.
        if (cancelledRef.current) return;
        setPhase('connecting');
        setTimeout(poll, POLL_INTERVAL_MS);
      }
    };

    poll();
    return () => {
      cancelledRef.current = true;
    };
  }, [attempt]);

  if (phase === 'ready') {
    return <>{children}</>;
  }

  if (phase === 'error') {
    return (
      <BootScreen
        title="Ragnarok"
        message="The backend failed to start."
        detail={error}
        onRetry={() => setAttempt((a) => a + 1)}
      />
    );
  }

  // connecting / warming / fetching_config → progress screen
  const steps = status?.steps ?? [];
  const progress =
    phase === 'fetching_config'
      ? 0.95
      : status?.progress ?? 0;
  const detail =
    phase === 'connecting'
      ? 'Starting backend… (first start imports PyPSA, this can take a few seconds)'
      : phase === 'fetching_config'
        ? 'Loading configuration…'
        : status?.detail ?? 'Working…';

  return (
    <BootScreen
      title="Ragnarok"
      message="Starting up"
      progress={progress}
      detail={detail}
      steps={steps}
    />
  );
}

// ── Presentational boot screen ──────────────────────────────────────────────

function BootScreen({
  title,
  message,
  detail,
  progress,
  steps,
  onRetry,
}: {
  title: string;
  message: string;
  detail?: string | null;
  progress?: number;
  steps?: { key: string; label: string; done: boolean }[];
  onRetry?: () => void;
}) {
  const isError = !!onRetry;
  return (
    <div className={`boot-screen ${isError ? 'boot-screen--error' : 'boot-screen--loading'}`}>
      <div className="boot-screen__inner">
        <div className="boot-screen__title">{title}</div>
        <div className="boot-screen__msg">{message}</div>

        {typeof progress === 'number' && (
          <div className="boot-screen__bar" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div
              className="boot-screen__bar-fill"
              style={{ width: `${Math.max(4, Math.round(progress * 100))}%` }}
            />
          </div>
        )}

        {detail && <div className="boot-screen__detail">{detail}</div>}

        {steps && steps.length > 0 && (
          <ul className="boot-screen__steps">
            {steps.map((s) => (
              <li
                key={s.key}
                className={`boot-screen__step${s.done ? ' is-done' : ''}`}
              >
                <span className="boot-screen__step-mark">{s.done ? '✓' : '○'}</span>
                <span className="boot-screen__step-label">{s.label}</span>
              </li>
            ))}
          </ul>
        )}

        {onRetry && (
          <button type="button" className="boot-screen__retry" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
