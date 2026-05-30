/**
 * Plugins view — module manager (left rail) + plugin host (main).
 *
 * Parallel to Model / Settings / Analytics — not part of the serialized
 * Model → Settings → Analytics flow.
 */
import React from 'react';
import { WorkbookModel } from '../shared/types';
import { PluginConstraintsPanel } from '../features/plugins/PluginConstraintsPanel';
import { FrontendPluginHost } from '../features/plugins/frontendPlugins';

interface Props {
  host: FrontendPluginHost;
  model: WorkbookModel;
  customDsl: string;
  onCustomDslChange: (text: string) => void;
}

export function PluginsView(props: Props) {
  return (
    <div className="view plugins-view">
      <main className="view-main">
        <PluginConstraintsPanel
          host={props.host}
          model={props.model}
          customDsl={props.customDsl}
          onCustomDslChange={props.onCustomDslChange}
        />
      </main>
    </div>
  );
}
