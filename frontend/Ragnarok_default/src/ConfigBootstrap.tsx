/**
 * Block-render wrapper that fetches the boot bundle from
 * ``GET /api/config`` before the rest of the app mounts.
 *
 * The bundle carries the PyPSA component schema and the standard-types
 * catalogues — both computed live on the backend from the installed
 * ``pypsa`` package — plus the network-import policy and the solver
 * capabilities. Frontend modules under ``lib/constants/`` start with
 * empty defaults; this wrapper calls their setters once the fetch
 * resolves, so by the time any consumer renders the live-binding
 * exports already point at the populated values.
 *
 * Three rendered states:
 *
 *   • loading — small "Connecting to backend…" spinner
 *   • error   — connection-required screen with a Retry button (no
 *               cached bundle and the backend is unreachable, or the
 *               backend returned an error we cannot recover from)
 *   • ready   — children render
 */
import React, { useEffect, useState } from 'react';

import { loadConfigBundle } from 'lib/api/config';
import {
  applyConfigBundle,
  type PypsaSchemaFile,
  type NetworkImportPolicyFile,
} from 'lib/constants/pypsa_schema';
import {
  applyStandardTypesBundle,
  type StandardTypesCatalogue,
} from 'lib/constants/pypsa_standard_types';

type Status = 'loading' | 'ready' | 'error';

interface Props {
  children: React.ReactNode;
}

export function ConfigBootstrap({ children }: Props) {
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    setError(null);
    (async () => {
      try {
        const bundle = await loadConfigBundle();
        if (cancelled) return;
        // The boot client's payload types are loose (Record<string, unknown>
        // for the schema components dict) because lib/api/ doesn't import
        // from lib/constants/ — that would couple the API layer to the
        // UI-facing constants. Cast at the boundary here: the backend
        // sends the shape lib/constants/ expects.
        applyConfigBundle(
          bundle.schema as unknown as PypsaSchemaFile,
          bundle.network_import_policy as unknown as NetworkImportPolicyFile,
        );
        applyStandardTypesBundle(
          bundle.standard_types as unknown as StandardTypesCatalogue,
        );
        setStatus('ready');
      } catch (exc) {
        if (cancelled) return;
        setError(String(exc));
        setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (status === 'loading') {
    return (
      <div className="boot-screen boot-screen--loading">
        <div className="boot-screen__inner">
          <div className="boot-screen__title">Ragnarok</div>
          <div className="boot-screen__msg">Connecting to backend…</div>
        </div>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="boot-screen boot-screen--error">
        <div className="boot-screen__inner">
          <div className="boot-screen__title">Ragnarok</div>
          <div className="boot-screen__msg">
            Cannot reach the backend.
          </div>
          <div className="boot-screen__detail">{error}</div>
          <button
            type="button"
            className="boot-screen__retry"
            onClick={() => setAttempt((a) => a + 1)}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
