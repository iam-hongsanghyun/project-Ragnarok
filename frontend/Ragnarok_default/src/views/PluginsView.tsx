/**
 * Plugins view — install and manage frontend-only plugins.
 *
 * Parallel to Model / Settings / Analytics. Plugins are a frontend concern: the
 * Ragnarok backend never hosts or runs them.
 */
import React from 'react';
import { PluginManagerPanel } from '../features/plugins/PluginManagerPanel';
import { FrontendPluginHost } from '../features/plugins/frontendPlugins';

interface Props {
  host: FrontendPluginHost;
}

export function PluginsView(props: Props) {
  return (
    <div className="view plugins-view">
      <main className="view-main">
        <PluginManagerPanel host={props.host} />
      </main>
    </div>
  );
}
